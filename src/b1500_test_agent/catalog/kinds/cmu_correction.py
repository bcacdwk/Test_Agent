"""``cmu_correction``: MFCMU phase compensation and open/short/load data correction (blueprint v2 0 #11, 2.6, 2.7;
WP8.2).

Four recipes, one per correction (single-choice enum parameter ``correction``, so the agent cannot switch it):
``cmu.phase_compensation``, ``cmu.correction_open``, ``cmu.correction_short`` and ``cmu.correction_load``. Each run
is one physical state the human sets up and confirms (``physical_setup``, rule R-ALWAYS-01; the plan carries the
prompt in ``program["setup"]``): the terminals open at the device end (phase compensation, open), shorted at the
device end (short) or on the load standard (load). The roles ``high``/``low`` bind by ``cmu_side`` to the terminals
the C-V pin map lands on the MFCMU (``gate``/``bulk`` of ``moscap-cmu``, ``a``/``b`` of ``capacitor-cmu``): rule
R-CORR-01 accepts a correction only for the pin map it was measured with, so the corrections run with that pin map,
and they need no DUT profile (no DUT terminal is touched). The executor writes a ``CorrectionRecord`` to the
correction store after a successful run (``catalog/corrections.py``).

Sequence (PG p251 (3-71) "Data Correction"; every command through the guarded driver ``CmuOps``):

- **phase**: ``CN ch`` (+ the ``LOP?`` positive control on hardware), ``CORRST ch,1|2|3,0`` (the data corrections
  were measured with the previous phase data, so they are switched off and their records discarded: phase
  compensation always comes first, then open, short, load), ``ADJ ch,1`` (manual mode), ``ADJ? ch,1`` (about 30 s,
  read timeout 90 s; it resets the MFCMU; PG p355-356 (4-37)), then the read-back ``correction_state``. The MFCMU
  applies its own internal test signal, which no command sets: the envelope allows no programmed signal (0 V rms,
  DC 0 V).
- **open/short/load**: ``CN ch``, then the correction set-up is read back: the frequency list (``CORRL?``) and the
  standards' reference values (``DCORR?``: open Cp = G = 0, short Ls = Rs = 0, i.e. ideal terminals at the device
  end; load = the station profile's ``corrections.<alias>.load``). Only when it differs from the plan is it written
  (``CLCORR ch,2`` for the 23 default frequencies or ``CLCORR ch,1`` + ``CORRL ch,f``, then ``DCORR`` per standard):
  ``CLCORR``, ``CORRL`` and ``DCORR`` clear the data of every correction (PG p379 (4-61), p384 (4-66), p389 (4-71)),
  so an unchanged set-up is never rewritten and the open data survive the short run. Then ``FC``/``ACV``/``DCV`` (the
  first listed frequency, the plan's AC level, DC 0 V; ``OutputGuard.check_ac``), ``CORR? ch,corr`` (the guard
  checks the AC level at every listed frequency first), ``CORRST ch,corr,1`` and the read-back. A rewritten set-up
  cleared the other corrections, whose records the executor then discards (the run is flagged).

Through an SCUU (WP8.3; pin map targets ``SCUU1.OUT1``/``OUT2``, ``kinds/cmu_routes.py``): the ``measure`` routes
connect both SCUU outputs to the MFCMU first (``Transaction.apply_routes``: ``SSP chnum,4``, read back; the SSP
switches the MFCMU on, so it takes no ``CN``), the corrections then include the SCUU's own path, and the ``rest``
routes return the outputs to the switch's rest state at the end (the cleanup restores and verifies it on every exit).

The FLEX preview lists the worst case (set-up rewritten); the run's audit has the exact commands. No measurement
table (``to_table`` returns ``None``): ``kind_result`` holds the result code (``ADJ?``/``CORR?``), the set-up action
and the read-back correction state (``after_phase``, ``after_open``, ``after_short``, ``after_load``).

Hardware-bound (blueprint v2 7.6 item 7, ATV-21; TODO(verify) at bring-up L6): the ``CORR?`` duration per frequency
(estimate ``CORR_POINT_S``, read timeout ``CORR_TIMEOUT_BASE_S + CORR_TIMEOUT_PER_FREQ_S`` per frequency), the
largest useful frequency list (``MAX_CORRECTION_FREQS``), the power-on reference values ``DCORR?`` answers and that
the corrections persist until ``*RST``/device clear/power-off (the live ``CORRST?``/``ADJ?`` check of R-CORR-01
catches every loss).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final, Literal

from pydantic import JsonValue

from b1500_test_agent.catalog.kinds.cmu_routes import MEASURE_PHASE, REST_PHASE, mfcmu_path
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import PHASE_COMPENSATION_TIMEOUT_S, CmuSignal
from b1500_test_agent.driver.modules import CMU_SPEC
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, JsonScalar
from b1500_test_agent.models.plan import (
    AcEnvelope,
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
)
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.station import CmuCorrectionLive, CorrectionFunction, StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

Correction = Literal["phase", "open", "short", "load"]
CORRECTIONS: Final[tuple[Correction, ...]] = ("phase", "open", "short", "load")
DATA_CORRECTIONS: Final[tuple[CorrectionFunction, ...]] = ("open", "short", "load")

CORRECTION_PARAM: Final = "correction"
FREQS_PARAM: Final = "freqs_hz"
AC_PARAM: Final = "ac_vrms"

SETUP_PROMPTS: Final[dict[Correction, str]] = {
    "phase": "open the measurement terminals at the device end: lift the probes off the device (nothing touches "
             "the DUT or a standard) and keep them lifted until the run ends",
    "open": "open the measurement terminals at the device end: lift the probes off the device (same cables and "
            "landing position as the C-V) and keep them lifted until the run ends",
    "short": "short the measurement terminals at the device end: land the probes on a short (shorting bar or one "
             "metal pad) and keep them there until the run ends",
    "load": "connect the load standard of the station profile at the device end (same cables) and keep it "
            "connected until the run ends",
}
"""What the human does before confirming each correction (R-ALWAYS-01 shows it with ``physical_setup``)."""

IDEAL_STANDARDS: Final[dict[CorrectionFunction, tuple[int, float, float]]] = {
    "open": (flex.DCORR_MODES["open"], 0.0, 0.0),
    "short": (flex.DCORR_MODES["short"], 0.0, 0.0),
}
"""``DCORR`` reference values of an open and a short at the device end (no standard: Cp = G = 0, Ls = Rs = 0; PG p254
(3-74) example ``ref_cp = ref_g = 0``)."""

MAX_CORRECTION_FREQS: Final = 64
"""Largest correction frequency list a recipe may write (the 23 default frequencies plus room for a C-f list).
TODO(verify) at bring-up L6: the instrument's own limit."""

CORR_POINT_S: Final = 0.5
"""Estimated ``CORR?`` time per listed frequency (the manual calls it short, PG p251 (3-71)). TODO(verify) L6."""

CORR_TIMEOUT_BASE_S: Final = 10.0
CORR_TIMEOUT_PER_FREQ_S: Final = 2.0
"""``CORR?`` read timeout = base + per frequency (four times the estimate per frequency). TODO(verify) L6."""

PHASE_ESTIMATE_S: Final = 35.0
"""Estimated phase compensation run: ``ADJ?`` about 30 s (PG p355 (4-37)) plus the set-up and read-back queries."""

SETUP_S: Final = 2.0
"""Estimated set-up and read-back time of a data correction run."""

MIN_RANGE_OHM: Final = 50.0
"""Smallest MFCMU impedance range (PG Table 4-17, p348): the envelope's current is the nominal peak AC current into a
short through it, ``sqrt(2) x Vac / 50 Ohm`` (the MFCMU has no settable compliance; the value only feeds the
current bookkeeping of R-LIM/R-DUT)."""


def _choice(params: dict[str, Quantity]) -> Correction:
    quantity = params.get(CORRECTION_PARAM)
    value = None if quantity is None else quantity.value
    if value not in CORRECTIONS:
        raise CompileError(f"{CORRECTION_PARAM} must be one of {list(CORRECTIONS)}, got {value!r}")
    return value  # type: ignore[return-value]


def _number(params: dict[str, Quantity], name: str) -> float:
    quantity = params.get(name)
    value = None if quantity is None else quantity.value
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _frequencies(params: dict[str, Quantity]) -> list[float]:
    quantity = params.get(FREQS_PARAM)
    values = None if quantity is None else quantity.value
    if not isinstance(values, list) or not values:
        raise CompileError(f"{FREQS_PARAM} must be a non-empty list of frequencies in Hz, got {values!r}")
    freqs = sorted({float(v) for v in values})
    if len(freqs) > MAX_CORRECTION_FREQS:
        raise CompileError(f"{FREQS_PARAM} lists {len(freqs)} frequencies; at most {MAX_CORRECTION_FREQS}")
    return freqs


def same_frequencies(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> bool:
    """Equal frequency sets (relative tolerance 1e-6, the instrument's resolution is 1 mHz to 1 Hz)."""
    left, right = sorted(set(a)), sorted(set(b))
    return len(left) == len(right) and all(math.isclose(x, y, rel_tol=1e-6) for x, y in zip(left, right, strict=True))


def same_standard(found: tuple[int, float, float], wanted: list[float] | tuple[float, ...]) -> bool:
    """A ``DCORR?`` answer equals the wanted ``(mode, primary, secondary)``."""
    return int(found[0]) == int(wanted[0]) and all(
        math.isclose(x, float(y), rel_tol=1e-6, abs_tol=1e-15) for x, y in zip(found[1:], wanted[1:], strict=True))


def correction_alias(bound: BoundChannel) -> str:
    """The MFCMU alias the store and R-CORR-01 use (``CH<n>`` when the station names none)."""
    return bound.alias or f"CH{bound.channel}"


def live_after(kind_result: dict[str, object]) -> CmuCorrectionLive | None:
    """The correction state a run read back (``after_*`` items of ``kind_result``), ``None`` when it did not get
    that far."""
    if "after_phase" not in kind_result:
        return None
    phase = kind_result["after_phase"]
    corr_state = {k: bool(kind_result[f"after_{k}"]) for k in DATA_CORRECTIONS
                  if isinstance(kind_result.get(f"after_{k}"), bool)}
    return CmuCorrectionLive(corr_state=corr_state, phase=phase if isinstance(phase, bool) else None)


def _data_program(program: dict[str, JsonValue]) -> tuple[list[float], float, dict[CorrectionFunction, list[float]]]:
    """Frequencies, AC level and standards of a stored data-correction program."""
    freqs, vrms, standards = program.get("freqs_hz"), program.get("ac_vrms"), program.get("standards")
    if not isinstance(freqs, list) or not freqs or not isinstance(vrms, int | float) or not isinstance(standards, dict):
        raise CompileError("the stored correction program lacks its frequencies, AC level or standards")
    refs: dict[CorrectionFunction, list[float]] = {}
    for corr in DATA_CORRECTIONS:
        value = standards.get(corr)
        if isinstance(value, list) and len(value) == 3:
            refs[corr] = [float(v) for v in value]  # type: ignore[arg-type]
    return [float(f) for f in freqs], float(vrms), refs  # type: ignore[arg-type]


class CmuCorrectionKind:
    """MFCMU phase compensation and open/short/load correction (see the module docstring)."""

    kind_id = "cmu_correction"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        correction = _choice(params)
        high = [name for name, role in recipe.roles.items() if role.function == "cmu_high"]
        low = [name for name, role in recipe.roles.items() if role.function == "cmu_low"]
        if len(high) != 1 or len(low) != 1 or len(recipe.roles) != 2:
            raise CompileError(f"{self.kind_id} recipes have exactly one cmu_high and one cmu_low role; {recipe.id} "
                               f"declares {sorted(recipe.roles)}")
        program: dict[str, JsonValue] = {"correction": correction, "setup": SETUP_PROMPTS[correction],
                                         "role": high[0], "channel": None, "alias": None}
        bound = binding.roles.get(high[0])
        path = mfcmu_path(recipe, binding, station, kind_id=self.kind_id)
        if bound is None or bound.channel is None:  # R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=CompiledEnvelope(channels={}),
                                    estimate=Estimate(points=0, duration_s=0.0), program=program)
        ch = bound.channel
        alias = correction_alias(bound)
        program.update(channel=ch, alias=alias)
        if path.via_scuu:  # only then: plans without an SCUU keep their program (and hash)
            program.update(routes=[r.model_dump(mode="json") for r in path.routes],
                           rest_routes=[r.model_dump(mode="json") for r in path.rest])
        connect = path.preview(ch, MEASURE_PHASE) or [flex.cn([ch])]
        if correction == "phase":
            program["timeout_s"] = PHASE_COMPENSATION_TIMEOUT_S
            ac = AcEnvelope(max_vrms=0.0, max_dc_v=0.0, f_min_hz=CMU_SPEC.f_hz[0], f_max_hz=CMU_SPEC.f_hz[1])
            current = math.sqrt(2.0) * CMU_SPEC.ac_vrms[1] / MIN_RANGE_OHM  # the internal signal's level is unknown
            preview = [*connect, *(flex.corrst(ch, k, False) for k in DATA_CORRECTIONS),
                       flex.adj(ch, flex.ADJ_MANUAL), flex.adj_q(ch, flex.ADJ_MEASURE)]
            duration = PHASE_ESTIMATE_S
        else:
            freqs = _frequencies(params)
            vrms = _number(params, AC_PARAM)
            standards: dict[CorrectionFunction, list[float]] = {k: [float(v[0]), v[1], v[2]]
                                                                for k, v in IDEAL_STANDARDS.items()}
            load = station.corrections.get(alias).load if alias in station.corrections else None
            if load is not None:
                standards["load"] = [float(flex.DCORR_MODES["load"]), load.ls_h, load.rs_ohm]
            elif correction == "load":
                raise CompileError(f"the load correction needs the load standard's reference value: the station "
                                   f"profile declares none for {alias} (corrections.{alias}.load: ls_h, rs_ohm); a "
                                   "human records it in config/local/station.yaml")
            default = same_frequencies(freqs, flex.CLCORR_DEFAULT_FREQS_HZ)
            timeout = CORR_TIMEOUT_BASE_S + CORR_TIMEOUT_PER_FREQ_S * len(freqs)
            program.update(freqs_hz=list(freqs), default_list=default, ac_vrms=vrms, timeout_s=timeout,
                           standards={k: list(v) for k, v in standards.items()})
            ac = AcEnvelope(max_vrms=vrms, max_dc_v=0.0, f_min_hz=freqs[0], f_max_hz=freqs[-1])
            current = math.sqrt(2.0) * vrms / MIN_RANGE_OHM
            setup = [flex.clcorr(ch, 2)] if default else [flex.clcorr(ch, 1), *(flex.corrl(ch, f) for f in freqs)]
            setup += [flex.dcorr(ch, k, int(v[0]), v[1], v[2]) for k, v in standards.items()]
            preview = [*connect, flex.corrl_q(ch), *(flex.corrl_q(ch, i + 1) for i in range(len(freqs))),
                       *(flex.dcorr_q(ch, k) for k in standards), *setup, flex.fc(ch, freqs[0]),
                       flex.acv(ch, vrms), flex.dcv(ch, 0.0), flex.corr_q(ch, correction),
                       flex.corrst(ch, correction, True)]
            duration = SETUP_S + CORR_POINT_S * len(freqs)
        readback = [*(flex.corrst_q(ch, k) for k in DATA_CORRECTIONS), flex.adj_q(ch, flex.ADJ_READ_LAST),
                    flex.lrn_q(flex.LRN_ADJ_MODE)]
        envelope = CompiledEnvelope(channels={ch: ChannelEnvelope(
            role=high[0], max_abs_v=0.0, max_abs_i=current, function="cmu_high", v_start=0.0, v_stop=0.0, ac=ac)},
            routes=frozenset(path.routes))
        rest_lines = path.preview(ch, REST_PHASE)
        if rest_lines and correction != "phase":
            rest_lines = [flex.acv(ch, 0.0), *rest_lines]
        return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=duration),
                                flex_preview=[*preview, *readback, *rest_lines], program=program,
                                routes_by_phase=path.routes_by_phase)

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        program = plan.program
        correction = program.get("correction")
        ch = program.get("channel")
        timeout = program.get("timeout_s")
        if correction not in CORRECTIONS or not isinstance(ch, int) or not isinstance(timeout, int | float):
            raise CompileError(f"plan {plan.plan_id} has no {self.kind_id} program")
        driver = tx.driver
        routes = [Route.model_validate(r) for r in program.get("routes") or []]  # type: ignore[union-attr]
        if routes:
            tx.apply_routes(routes, phase=MEASURE_PHASE)  # SSP: the SCUU switches the MFCMU on (no CN)
        else:
            driver.enable([ch])
        tx.lop_positive_control([ch])
        alias = program.get("alias")
        result: dict[str, JsonScalar] = {"correction": correction, "alias": alias if isinstance(alias, str) else None,
                                         "channel": ch}
        if correction == "phase":
            for corr in DATA_CORRECTIONS:
                driver.set_correction(ch, corr, False)
            driver.set_phase_compensation_mode(ch, flex.ADJ_MANUAL)
            tx.mark("phase compensation started (about 30 s)")
            code = driver.measure_phase_compensation(ch, timeout_s=float(timeout))
            text = flex.ADJ_RESULTS.get(code, str(code))
        else:
            data: CorrectionFunction = correction  # type: ignore[assignment]
            freqs, vrms, standards = _data_program(program)
            result["setup"] = self._set_up(tx, ch, freqs, standards, default=program.get("default_list") is True)
            driver.apply_cmu_signal(ch, CmuSignal(freq_hz=freqs[0], ac_vrms=vrms, dc_v=0.0))
            tx.mark(f"{data} correction data measurement at {len(freqs)} frequencies")
            code = driver.measure_correction(ch, data, timeout_s=float(timeout))
            text = flex.CORR_RESULTS.get(code, str(code))
            if code == 0:
                driver.set_correction(ch, data, True)
        result.update(result_code=code, result_text=text)
        after = driver.correction_state(ch)
        result["after_phase"] = after.phase
        for corr in DATA_CORRECTIONS:
            result[f"after_{corr}"] = after.corr_state.get(corr)
        tx.mark(f"{correction}: result {code} ({text})")
        rest = [Route.model_validate(r) for r in program.get("rest_routes") or []]  # type: ignore[union-attr]
        if rest:
            if correction != "phase":
                driver.set_cmu_ac(ch, 0.0)  # no AC signal while the SCUU switches back
            tx.apply_routes(rest, phase=REST_PHASE)
        in_effect = after.phase is True if correction == "phase" else after.corr_state.get(correction) is True
        if code != 0:
            what = "phase compensation (ADJ?)" if correction == "phase" else f"{correction} correction (CORR?)"
            message = (f"{what} result {code} ({text}): check the physical set-up ({SETUP_PROMPTS[correction]}) "
                       "and run the recipe again")
        elif not in_effect:
            message = f"the {correction} correction completed but the read-back shows it not in effect"
        else:
            message = ""
        return RawAcquisition(kind_result=result, ok=code == 0 and in_effect, message=message)

    @staticmethod
    def _set_up(tx: Transaction, ch: int, freqs: list[float], standards: dict[CorrectionFunction, list[float]], *,
                default: bool) -> str:
        """Read the frequency list and the standards back; write them only when they differ (module docstring).
        Returns ``kept`` or ``rewritten``."""
        driver = tx.driver
        listed = driver.correction_frequencies(ch)
        found = {k: driver.correction_standard(ch, k) for k in standards}
        if same_frequencies(listed, freqs) and all(same_standard(found[k], v) for k, v in standards.items()):
            tx.mark("correction set-up kept (frequency list and standards unchanged)")
            return "kept"
        if default:
            driver.set_correction_frequencies(ch, defaults=True)
        else:
            driver.set_correction_frequencies(ch, freqs)
        for corr, (_, primary, secondary) in standards.items():
            driver.set_correction_standard(ch, corr, primary, secondary)
        tx.mark("correction set-up rewritten (the data of every correction were cleared)")
        return "rewritten"

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> None:
        return None
