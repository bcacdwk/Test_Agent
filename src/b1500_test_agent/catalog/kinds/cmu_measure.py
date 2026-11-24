"""``cmu_measure``: MFCMU capacitance measurements (blueprint v2 2.7; WP8.3: MM 17 spot C and MM 18 C-V (DC bias)
sweep, single or double, in a host loop over a frequency list; the MFCMU directly or through an SCUU; WP8.4: the C-V
variants pulsed spot C / pulsed C-V (MM 19/20), C-f (MM 22), C-V (AC level) (MM 23) and C-t (MM 26), whose settings,
previews and per-frequency measurements live in ``kinds/cmu_variants.py``).

Roles (recipe ``roles``, bound through the pin map):

- exactly one ``cmu_high`` role (the MFCMU High side: DC bias and AC drive; its name prefixes the data columns) and
  one ``cmu_low`` role (the Low side, the virtual ground the current is measured at); both on MFCMU side targets
  (``7H``/``7L``) or both through one SCUU (``SCUU1.OUT1``/``OUT2``, ``kinds/cmu_routes.py``);
- optional SMU roles: ``ground`` (the GNDU: nothing is sent; an SMU: ``DV 0`` with compliance setting ``icomp`` or,
  when absent, the MFCMU's nominal current) and ``bias_v`` (``DV`` at setting ``v``, compliance ``icomp``), e.g. a
  MOSFET's source and bulk during split C-V. In a C-V sweep a role with ``measure: [I]`` is measured at every step
  (MM 18 lists it after the MFCMU, PG p471 (4-153)); a spot measurement (MM 17) measures only the MFCMU.

Settings of the ``cmu_high`` role (``$param`` references): ``freqs`` (Hz, a list: one measurement per frequency, in
order; the host loop; for C-f the sweep itself), ``ac`` (oscillator level, V rms), ``model`` (the parameter pair:
``cp_g`` (``IMP 100``), ``cp_d`` 101, ``cs_rs`` 200, ``cs_d`` 201, ``z_theta`` 10; default ``cp_g``), ``measurement``
(a literal: ``spot``, ``cv``, ``pulsed``, ``cf``, ``acv``, ``ct``; without it ``cv`` when ``start``/``stop`` are set,
else ``spot``), and either ``dc`` (V) with ``samples`` (spot, MM 17) or ``start``, ``stop``, ``points``, ``mode``
(``single``/``double``), ``hold``, ``delay`` (s; C-V sweep, MM 18: ``WDCV`` linear from ``start`` to ``stop`` and
back for ``double``, ``WTDCV hold,delay``, ``WMDCV 2,1``: automatic abort on NULL loop unbalance, IV amplifier
saturation or overflow, then the start value), or the variant settings of ``kinds/cmu_variants.py``.
The recipe parameter ``integration`` (``short`` ``ACT 0,1``, ``medium`` ``ACT 0,2`` = the initial setting, ``long``
``ACT 2,2``: two power-line cycles) sets the MFCMU averaging (PG p354 (4-36)). Ranging is automatic (``RC ch,0``).

Acquisition (one transaction, guarded driver only): ``FMT 1,1`` (each sweep step also returns its source value, a
C-t sample its sampling index), ``TSC 0`` (``TSC 1`` for C-t: time stamps) and ``LMN 0`` (the parsed layout has no
monitors), ``IMP``, ``ACT``, ``RC``; with an SCUU the
``measure`` routes (``Transaction.apply_routes``: ``SSP chnum,4``, read back through ``*LRN? 81``; the SSP switches
the MFCMU on, so it is never in ``CN``); ``CN`` of the other channels, ``ERRX?`` drain (an interlock or any error
aborts), on hardware the ``LOP?`` positive control, ``DV`` per SMU role; then per frequency: spot ``FC``/``ACV``/
``DCV`` (``OutputGuard.check_ac``), ``MM 17``, ``ERRX?`` drain and ``samples`` x (``XE`` + read, ``tx.check_abort``,
``ERRX?`` drain before the next trigger),
or C-V ``MM 18``/``FC``/``ACV``/``WTDCV``/``WMDCV``/``WDCV`` (both DC end points checked by the guard), ``ERRX?``
drain, ``XE`` and one read, or one variant measurement (a C-t transient: one ``XE`` per block); ``tx.checkpoint``
after each frequency (after each C-t block; the C-f sweep is one segment: a cancel acts between segments; R-RUN-02).
At the end the MFCMU goes to DC 0 V and AC 0 V (guarded) and, with an SCUU, the ``rest`` routes return the
outputs to the switch's rest state (``SSP chnum,3`` for ``rest: smu``); the transaction cleanup (``DCV 0``/``ACV 0``,
routes to rest, ``DZ``, ``CL``, verify) runs on every exit anyway.

Table (``analysis/dataset.py`` contract): ``step``, ``t_s`` (C-t: seconds since the bias step, from the time stamps:
``T - (T1 - h_bias - (index1 - 1) x interval)`` with the first sample of the transient), ``segment`` (double sweeps),
``freq_hz`` (C-f: the frequency the instrument returns with each step), ``ac_vrms`` (C-ACV: the level it returns),
``dc_v`` (programmed; in a DC bias sweep the bias the instrument returns with each step, in a pulsed C-V the pulse
level; C-t the bias), the MFCMU pair ``<high role>_<Cp|G|Cs|Rs|D|Z|theta>`` + ``_status``
(``CmuReading.table_values``: theta in radian), measured SMU currents ``<role>_I`` + ``_status`` (MM 18 sweeps) and
the programmed ``<role>_V`` of ``bias_v`` roles. The pulse base of a pulsed C-V is in the stored program (``base_v``).

Envelope: the MFCMU channel's ``max_abs_v`` = the largest |DC level| (bias, pulse base and levels, C-t base and
bias), ``ac`` = (largest AC level, |DC|, frequency span); ``v_start``/``v_stop`` the first and last DC bias of an
MM 18 sweep, else the lowest and highest DC level; its
current is the nominal peak AC current into a short through the smallest impedance range, ``sqrt(2) x Vac / 50 Ohm``
(the MFCMU has no settable compliance; the value only feeds the current bookkeeping of R-LIM/R-DUT/R-GNDU, as for
``cmu_correction``). Corrections: rule R-CORR-01 needs fresh phase/open/short records of this pin map covering every
frequency (``freqs`` is in Hz, so the rule reads it).

Estimate conventions (TODO(verify) at bring-up L6, the simulator uses the same): ``ACT`` auto mode 8 ms per N, PLC
mode N / 50 Hz per point; 0.5 s per frequency (per C-t block) for setup and data transfer; a pulsed point takes one
pulse period.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.cmu_routes import MEASURE_PHASE, REST_PHASE, CmuPath, mfcmu_path
from b1500_test_agent.catalog.kinds.cmu_variants import (
    CT_BLOCK_OVERHEAD_S,
    VARIANTS,
    CtBlock,
    block_span_s,
    check_variant,
    measure_ct_block,
    measure_sweep_variant,
    pulse_period_s,
    variant_fields,
    variant_preview,
)
from b1500_test_agent.catalog.kinds.smu_staircase import (
    READ_TIMEOUT_MARGIN_S,
    BiasOutput,
    MeasureColumn,
    bias_command,
    drain_or_raise,
    force_bias,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import CmuBlock, CmuSignal, CmuSweepTiming, CvSweepSetup
from b1500_test_agent.driver.cmu_data import CmuLayout, CmuReading, parse_cmu_blocks
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import (
    AcEnvelope,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
)
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

Mode = Literal["spot", "cv", "pulsed", "cf", "acv", "ct"]
MEASUREMENT_SETTING: Final = "measurement"
"""Literal role setting naming the measurement (module docstring)."""

MM_MODES: Final[dict[str, int]] = {"spot": 17, "cv": 18, "pulsed": 20, "cf": 22, "acv": 23, "ct": 26}
"""Measurement -> ``MM`` mode (a pulsed program of one point is the pulsed spot C, MM 19)."""

IMP_MODELS: Final[dict[str, int]] = {"cp_g": 100, "cp_d": 101, "cs_rs": 200, "cs_d": 201, "z_theta": 10}
"""``model`` setting -> ``IMP`` mode (PG Table 4-16, p347 (4-29)); every one has run-table columns
(``cmu_data.TABLE_IMP_MODES``)."""

DEFAULT_MODEL: Final = "cp_g"

INTEGRATION_PARAM: Final = "integration"
ACT_PRESETS: Final[dict[str, tuple[int, int]]] = {"short": (0, 1), "medium": (0, 2), "long": (2, 2)}
"""``integration`` -> ``ACT mode,N`` (PG p354 (4-36)): auto mode N = 1 or 2 (the initial setting), or two power-line
cycles."""

DEFAULT_PRESET: Final = "medium"

ACT_AUTO_UNIT_S: Final = 8e-3
"""Estimated averaging time per auto-mode coefficient (TODO(verify) L6; the simulator's convention)."""

LINE_HZ: Final = 50.0
"""Line frequency assumed for PLC averaging estimates (50 Hz gives the longer cycle: a conservative estimate)."""

FREQ_OVERHEAD_S: Final = 0.5
"""Estimated setup and data transfer time per frequency."""

SPOT_OVERHEAD_S: Final = 0.05
"""Estimated host round trip per spot measurement (``XE`` + read)."""

MIN_RANGE_OHM: Final = 50.0
"""Smallest MFCMU impedance range (PG Table 4-17, p348 (4-30)): the envelope's current is ``sqrt(2) x Vac / 50 Ohm``
(module docstring)."""

SMU_FUNCTIONS: Final = frozenset({"ground", "bias_v"})
"""SMU role functions this kind drives besides the two MFCMU roles."""

MAX_FREQS: Final = 64
"""Longest frequency list of one plan (the correction lists hold at most as many; ``cmu_correction``)."""


class CmuProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    mode: Mode
    channel: Channel
    high_role: str
    low_role: str
    freqs_hz: list[float] = Field(min_length=1, max_length=MAX_FREQS)
    ac_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    model: str
    imp: int
    act: tuple[int, int]
    point_s: float = Field(gt=0)
    dc_v: float = 0.0
    samples: int = Field(default=1, ge=1)
    start: float = 0.0
    stop: float = 0.0
    points: int = Field(default=1, ge=1, le=flex.CMU_MAX_STEPS)
    double: bool = False
    hold_s: float = Field(default=0.0, ge=0.0)
    delay_s: float = Field(default=0.0, ge=0.0)
    step_spacing: Literal["linear", "log"] = "linear"
    """Step spacing of a C-f (from the listed frequencies) or AC level sweep."""
    ac_stop: float = Field(default=0.0, ge=0.0, le=flex.CMU_MAX_AC_V)
    """AC level sweep: the stop level (``ac_vrms`` is the start level)."""
    base_v: float = 0.0
    """Pulsed C-V: the base between pulses; C-t: the level before the bias step."""
    width_s: float = Field(default=0.0, ge=0.0)
    period_s: float = Field(default=0.0, ge=0.0)
    """Pulsed C-V: ``PTDCV`` width and period (0 = automatic)."""
    interval_s: float = Field(default=0.0, ge=0.0)
    ct_blocks: list[CtBlock] = Field(default_factory=list)
    """C-t: sampling interval and the ``MM 26`` blocks of one transient (``dc_v`` is the bias)."""
    biases: list[BiasOutput] = Field(default_factory=list)
    measure: list[MeasureColumn] = Field(default_factory=list)
    """SMU channels measured at every C-V step (MM 18 order after the MFCMU)."""
    source_columns: dict[str, float] = Field(default_factory=dict)
    """Programmed levels of the ``bias_v`` roles (``<role>_V``)."""
    enable: list[Channel] = Field(default_factory=list)
    """``CN`` list: the SMU roles' channels and the MFCMU unless an SCUU connects it."""
    routes: list[Route] = Field(default_factory=list)
    rest_routes: list[Route] = Field(default_factory=list)

    @property
    def mm(self) -> int:
        """The ``MM`` mode (19 for a pulsed program of one point)."""
        return 19 if self.mode == "pulsed" and self.points == 1 else MM_MODES[self.mode]

    @property
    def steps(self) -> int:
        """Data blocks of one frequency: spot ``samples``, a sweep ``points`` (``2 x points`` double; C-f over the
        listed frequencies), C-t the samples of all its blocks."""
        if self.mode == "spot":
            return self.samples
        if self.mode == "ct":
            return sum(b.number for b in self.ct_blocks)
        return self.points * (2 if self.double else 1)

    @property
    def loop_freqs(self) -> list[float]:
        """The frequencies of the host loop (one entry for C-f: its sweep starts at the first listed frequency)."""
        return self.freqs_hz[:1] if self.mode == "cf" else self.freqs_hz

    @property
    def segments(self) -> int:
        """Checkpoints of the run: one per loop frequency, one per C-t block."""
        return len(self.loop_freqs) * (len(self.ct_blocks) if self.mode == "ct" else 1)

    def segment_s(self) -> float:
        """Estimated longest time between two checkpoints (one frequency's measurement, one C-t block)."""
        if self.mode == "spot":
            return FREQ_OVERHEAD_S + self.samples * (self.point_s + SPOT_OVERHEAD_S)
        if self.mode == "ct":
            return max(block_span_s(self, b) for b in self.ct_blocks) + CT_BLOCK_OVERHEAD_S
        if self.mode == "pulsed":
            return FREQ_OVERHEAD_S + self.hold_s + self.steps * pulse_period_s(self.width_s, self.period_s) \
                + self.point_s
        return FREQ_OVERHEAD_S + self.hold_s + self.steps * (self.delay_s + self.point_s)

    def frequency_s(self) -> float:
        """Estimated time of one loop frequency (a whole C-t transient)."""
        if self.mode == "ct":
            return sum(block_span_s(self, b) + CT_BLOCK_OVERHEAD_S for b in self.ct_blocks)
        return self.segment_s()

    def timeout_s(self) -> float:
        """Read timeout of one measurement: ``2 x segment + 10 s``."""
        return 2.0 * self.segment_s() + READ_TIMEOUT_MARGIN_S

    def dc_levels(self) -> list[float]:
        """Every DC level the program applies: the spot/C-f/C-ACV bias, the sweep end points, the pulse base and
        levels, the C-t base and bias."""
        if self.mode in ("spot", "cf", "acv"):
            return [self.dc_v]
        if self.mode == "cv":
            return [self.start, self.stop]
        if self.mode == "pulsed":
            return [self.base_v, self.start, self.stop]
        return [self.base_v, self.dc_v]

    def sweep(self, freq_hz: float) -> CvSweepSetup:
        """The MM 18 setup at ``freq_hz``."""
        return CvSweepSetup(channel=self.channel, start=self.start, stop=self.stop, points=self.points,
                            double=self.double, timing=CmuSweepTiming(hold_s=self.hold_s, delay_s=self.delay_s),
                            freq_hz=freq_hz, ac_vrms=self.ac_vrms, measure_smu=tuple(m.channel for m in self.measure),
                            auto_abort=True, post="start")


# -- helpers ---------------------------------------------------------------------------------------------------------


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _count(value: object, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CompileError(f"{what} must be an integer {low}..{high}, got {value!r}")
    return value


def _frequencies(value: object, what: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise CompileError(f"{what} must be a non-empty list of frequencies in Hz, got {value!r}")
    freqs = [_number(v, what) for v in value]
    if len(freqs) > MAX_FREQS:
        raise CompileError(f"{what} lists {len(freqs)} frequencies; at most {MAX_FREQS}")
    if len(set(freqs)) != len(freqs):
        raise CompileError(f"{what} lists a frequency twice")
    low, high = flex.CMU_FREQ_HZ
    outside = [f for f in freqs if not low <= f <= high]
    if outside:
        raise CompileError(f"{what}: {outside[0]:g} Hz is outside the MFCMU's {low:g}..{high:g} Hz")
    return freqs


def point_time_s(act: tuple[int, int]) -> float:
    """Estimated averaging time of one MFCMU point for ``ACT mode,N`` (module docstring)."""
    mode, n = act
    return n * ACT_AUTO_UNIT_S if mode == 0 else n / LINE_HZ


def cmu_current_a(ac_vrms: float) -> float:
    """Nominal peak AC current into a short through the smallest range, ``sqrt(2) x Vac / 50 Ohm`` (module
    docstring)."""
    return math.sqrt(2.0) * ac_vrms / MIN_RANGE_OHM


# -- the kind --------------------------------------------------------------------------------------------------------


class CmuMeasureKind:
    """MFCMU spot C (MM 17) and C-V sweep (MM 18) over a frequency list (see the module docstring)."""

    kind_id = "cmu_measure"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        high, low = self._mfcmu_roles(recipe)
        bound = binding.roles.get(high)
        path = mfcmu_path(recipe, binding, station, kind_id=self.kind_id)
        if bound is None or bound.channel is None:  # R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=CompiledEnvelope(channels={}), estimate=Estimate(points=0, duration_s=0))
        program = self._program(recipe, params, binding, path, high, low, bound.channel)
        levels = program.dc_levels()
        dc_max = max(abs(v) for v in levels)
        ac_max = max(program.ac_vrms, program.ac_stop)
        current = cmu_current_a(ac_max)
        first, last = (levels[0], levels[-1]) if program.mode == "cv" else (min(levels), max(levels))
        channels: dict[int, ChannelEnvelope] = {program.channel: ChannelEnvelope(
            role=high, max_abs_v=dc_max, max_abs_i=current, function="cmu_high", v_start=first, v_stop=last,
            ac=AcEnvelope(max_vrms=ac_max, max_dc_v=dc_max, f_min_hz=min(program.freqs_hz),
                          f_max_hz=max(program.freqs_hz)))}
        for bias in program.biases:
            spec = recipe.roles[bias.role]
            channels[bias.channel] = ChannelEnvelope(role=bias.role, max_abs_v=abs(bias.level),
                                                     max_abs_i=abs(bias.comp), function=spec.function,
                                                     v_start=bias.level, v_stop=bias.level)
        envelope = CompiledEnvelope(channels=channels, routes=frozenset(path.routes))
        loops = len(program.loop_freqs)
        estimate = Estimate(points=loops * program.steps, duration_s=round(loops * program.frequency_s() + 1.0, 6),
                            max_segment_s=round(program.segment_s(), 6))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self._preview(program, path),
                                program=program.model_dump(mode="json"), routes_by_phase=path.routes_by_phase)

    def _mfcmu_roles(self, recipe: Recipe) -> tuple[str, str]:
        high = [n for n, r in recipe.roles.items() if r.function == "cmu_high"]
        low = [n for n, r in recipe.roles.items() if r.function == "cmu_low"]
        if len(high) != 1 or len(low) != 1:
            raise CompileError(f"{self.kind_id} recipes have exactly one cmu_high and one cmu_low role; {recipe.id} "
                               f"declares {sorted(recipe.roles)}")
        other = sorted(n for n, r in recipe.roles.items()
                       if r.function not in ("cmu_high", "cmu_low") and r.function not in SMU_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id}: roles {other} have functions this kind does not drive (MFCMU roles "
                               f"plus {sorted(SMU_FUNCTIONS)} SMU roles)")
        return high[0], low[0]

    def _program(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding, path: CmuPath,
                 high: str, low: str, channel: int) -> CmuProgram:
        role = recipe.roles[high]

        def get(key: str, default: object = None) -> object:
            return setting_value(role, key, params, default)

        model = get("model", DEFAULT_MODEL)
        if model not in IMP_MODELS:
            raise CompileError(f"{high}.model must be one of {sorted(IMP_MODELS)}, got {model!r}")
        preset = params.get(INTEGRATION_PARAM)
        name = preset.value if preset is not None else DEFAULT_PRESET
        if name not in ACT_PRESETS:
            raise CompileError(f"{INTEGRATION_PARAM} must be one of {sorted(ACT_PRESETS)}, got {name!r}")
        act = ACT_PRESETS[str(name)]
        ac = _number(get("ac"), f"{high}.ac")
        freqs = _frequencies(get("freqs"), f"{high}.freqs")
        common: dict[str, object] = {
            "channel": channel, "high_role": high, "low_role": low, "model": model, "imp": IMP_MODELS[str(model)],
            "freqs_hz": freqs, "ac_vrms": ac, "act": act, "point_s": point_time_s(act), "routes": path.routes,
            "rest_routes": path.rest,
        }
        inferred = "cv" if "start" in role.settings or "stop" in role.settings else "spot"
        measurement = get(MEASUREMENT_SETTING, inferred)
        if measurement not in MM_MODES:
            raise CompileError(f"{high}.{MEASUREMENT_SETTING} must be one of {sorted(MM_MODES)}, got {measurement!r}")
        mode: Mode = measurement  # type: ignore[assignment]
        if mode in VARIANTS:
            common.update(variant_fields(mode, get, high, freqs, point_time_s(act)))
        elif mode == "cv":
            sweep_mode = get("mode", "single")
            if sweep_mode not in ("single", "double"):
                raise CompileError(f"{high}.mode must be single or double, got {sweep_mode!r}")
            common.update(start=_number(get("start"), f"{high}.start"), stop=_number(get("stop"), f"{high}.stop"),
                          points=_count(get("points"), f"{high}.points", 1, flex.CMU_MAX_STEPS),
                          double=sweep_mode == "double", hold_s=_number(get("hold", 0.0), f"{high}.hold"),
                          delay_s=_number(get("delay", 0.0), f"{high}.delay"))
        else:
            common.update(dc_v=_number(get("dc", 0.0), f"{high}.dc"),
                          samples=_count(get("samples", 1), f"{high}.samples", 1, 1000))
        biases, measure, columns, enable = self._smu_roles(recipe, params, binding, path, mode, cmu_current_a(ac))
        if not path.via_scuu:
            enable = [channel, *enable]
        try:
            program = CmuProgram.model_validate({**common, "mode": mode, "biases": biases, "measure": measure,
                                                 "source_columns": columns, "enable": enable})
            if program.mode == "cv":
                program.sweep(program.freqs_hz[0])  # the driver's domain checks (levels, timing, steps)
            elif program.mode in VARIANTS:
                check_variant(program)
        except ValueError as exc:
            raise CompileError(f"{recipe.id}: {exc}") from None
        return program

    def _smu_roles(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding, path: CmuPath,
                   mode: Mode, mfcmu_a: float,
                   ) -> tuple[list[BiasOutput], list[MeasureColumn], dict[str, float], list[int]]:
        biases: list[BiasOutput] = []
        measure: list[MeasureColumn] = []
        columns: dict[str, float] = {}
        enable: list[int] = []
        for name, role in recipe.roles.items():
            if role.function not in SMU_FUNCTIONS:
                continue
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue  # GNDU or unbound: R-PIN-01 decides
            if bound.channel in path.scuu_modules:
                raise CompileError(f"{self.kind_id}: role {name} uses channel {bound.channel}, an SMU of "
                                   f"{path.switch} (the SCUU switches it; it cannot take CN)")
            explicit = setting_value(role, COMPLIANCE_SETTING, params)
            level = 0.0
            if role.function == "bias_v":
                level = _number(setting_value(role, "v", params), f"{name}.v")
                if explicit is None:
                    raise CompileError(f"{name}.{COMPLIANCE_SETTING}: a bias_v role needs its current compliance")
                columns[f"{name}_V"] = level
            comp = _number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else mfcmu_a
            biases.append(BiasOutput(role=name, channel=bound.channel, level=level, comp=comp))
            enable.append(bound.channel)
            if role.measure:
                if role.measure != ["I"]:
                    raise CompileError(f"{name}: an SMU role of {self.kind_id} measures only I")
                if mode != "cv":
                    raise CompileError(f"{name}: SMU currents are measured only during a C-V sweep (MM 18); the "
                                       f"{mode} measurement measures the MFCMU alone")
                measure.append(MeasureColumn(channel=bound.channel, role=name, quantity="I"))
        if len(measure) > 9:
            raise CompileError(f"{self.kind_id}: a C-V sweep measures at most nine SMU channels besides the MFCMU")
        return biases, measure, columns, enable

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints the run reports (``tx.checkpoint``): one per loop frequency, one per C-t block."""
        return CmuProgram.model_validate(plan.program).segments

    @staticmethod
    def _preview(program: CmuProgram, path: CmuPath) -> list[str]:
        ch = program.channel
        lines = [flex.fmt(1, 1), flex.tsc(program.mode == "ct"), flex.lmn(0), flex.imp(program.imp),
                 flex.act(*program.act), flex.rc(ch, 0), *path.preview(ch, MEASURE_PHASE)]
        if program.enable:
            lines.append(flex.cn(program.enable))
        lines += [bias_command(b) for b in program.biases]
        for freq in program.loop_freqs:
            if program.mode in VARIANTS:
                lines += variant_preview(program, freq)
            elif program.mode == "spot":
                lines += [flex.fc(ch, freq), flex.acv(ch, program.ac_vrms), flex.dcv(ch, program.dc_v),
                          flex.mm(17, [ch]), *([flex.XE] * program.samples)]
            else:
                setup = program.sweep(freq)
                lines += [flex.mm(18, [ch, *setup.measure_smu]), flex.fc(ch, freq), flex.acv(ch, program.ac_vrms),
                          flex.wtdcv(*setup.timing.values()), flex.wmdcv(2, 1),
                          flex.wdcv(ch, setup.sweep_mode, setup.start, setup.stop, setup.points), flex.XE]
        lines += [flex.dcv(ch, 0.0), flex.acv(ch, 0.0), *path.preview(ch, REST_PHASE)]
        return lines

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        program = CmuProgram.model_validate(plan.program)
        driver = tx.driver
        ch = program.channel
        driver.set_format(1, 1)
        driver.set_time_stamp(program.mode == "ct")
        driver.set_cmu_monitor(False)
        driver.set_impedance_model(program.imp)
        driver.set_cmu_integration(*program.act)
        driver.set_cmu_range(ch)
        if program.routes:
            tx.apply_routes(program.routes, phase=MEASURE_PHASE)
        if program.enable:
            driver.enable(program.enable)
        drain_or_raise(tx, "connecting the outputs")
        tx.mark("outputs connected")
        tx.lop_positive_control(sorted({ch, *program.enable}))
        for bias in program.biases:
            force_bias(tx, bias)
        blocks: list[CmuBlock] = []
        offset = 0
        done = 0
        total = program.segments
        for freq in program.loop_freqs:
            origin: float | None = None
            for index in range(len(program.ct_blocks) if program.mode == "ct" else 1):
                if program.mode == "ct":
                    measured = [measure_ct_block(tx, program, freq, index)]
                    origin = ct_origin(program, measured[0].readings) if index == 0 else origin
                    label = f"{freq:g} Hz block {index + 1}/{len(program.ct_blocks)}"
                else:
                    measured = self._measure_frequency(tx, program, freq)
                    label = (f"{program.freqs_hz[0]:g}..{program.freqs_hz[-1]:g} Hz" if program.mode == "cf"
                             else f"{freq:g} Hz")
                blocks.extend(measured)
                readings = [r for b in measured for r in b.readings]
                done += 1
                tx.checkpoint(done, total, label, rows=lambda readings=readings, freq=freq, first=offset,
                              origin=origin: _rows(program, readings, freq, first_step=first, origin=origin))
                offset += len(readings)
        driver.apply_cmu_signal(ch, CmuSignal(freq_hz=program.freqs_hz[-1], ac_vrms=0.0, dc_v=0.0))
        if program.rest_routes:
            tx.apply_routes(program.rest_routes, phase=REST_PHASE)
        statuses = sorted({r.status for b in blocks for r in b.readings} - {"N"})
        result: dict[str, object] = {"frequencies": len(program.freqs_hz), "readings": sum(len(b.readings)
                                                                                         for b in blocks)}
        if program.mode in VARIANTS:
            result["measurement_mode"] = program.mm
        if program.mode == "ct":
            result["ct_blocks"] = len(program.ct_blocks)
        if statuses:
            result["cmu_status"] = ",".join(statuses)
        return RawAcquisition(blocks=[b.raw for b in blocks], kind_result=result)  # type: ignore[arg-type]

    @staticmethod
    def _measure_frequency(tx: Transaction, program: CmuProgram, freq: float) -> list[CmuBlock]:
        driver = tx.driver
        ch = program.channel
        if program.mode in VARIANTS:
            return [measure_sweep_variant(tx, program, freq)]
        if program.mode == "spot":
            driver.apply_cmu_signal(ch, CmuSignal(freq_hz=freq, ac_vrms=program.ac_vrms, dc_v=program.dc_v))
            driver.spot_c(ch)
            drain_or_raise(tx, f"the spot setup at {freq:g} Hz")
            out = []
            for k in range(program.samples):
                if k:  # an error of the previous trigger (e.g. 320 excess current: output off) aborts here
                    drain_or_raise(tx, f"spot sample {k} at {freq:g} Hz")
                out.append(driver.measure_cmu(driver.cmu_layout(17), steps=1, timeout_s=program.timeout_s()))
                tx.check_abort()
            return out
        setup = program.sweep(freq)
        driver.cv_sweep(setup)
        drain_or_raise(tx, f"the C-V setup at {freq:g} Hz")
        layout = driver.cmu_layout(18, smu_channels=len(program.measure))
        block = driver.measure_cmu(layout, steps=setup.steps, timeout_s=program.timeout_s())
        tx.check_abort()
        return [block]

    # to_table ----------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        program = CmuProgram.model_validate(plan.program)
        per_freq = program.samples if program.mode == "spot" else len(program.ct_blocks) if program.mode == "ct" else 1
        expected = len(program.loop_freqs) * per_freq
        if len(raw.blocks) != expected:
            raise ValueError(f"expected {expected} measurement blocks, got {len(raw.blocks)}")
        layout = table_layout(program)
        rows: list[dict[str, object]] = []
        origin: float | None = None
        for index, block in enumerate(raw.blocks):
            freq = program.loop_freqs[index // per_freq]
            readings = parse_cmu_blocks(block.points[:len(block.points) - len(block.points) % layout.width], layout)
            if program.mode == "ct" and index % per_freq == 0:
                origin = ct_origin(program, readings)
            rows.extend(_rows(program, readings, freq, first_step=len(rows), origin=origin))
        return pd.DataFrame(rows)


def table_layout(program: CmuProgram) -> CmuLayout:
    """The data layout ``acquire`` sets up (``FMT 1,1``, ``TSC 0`` or, for C-t, ``TSC 1``, ``LMN 0``): parameter
    pair, source data in a sweep, the sampling index and time stamp of C-t, the measured SMU channels."""
    return CmuLayout(imp=program.imp, mode=program.mm, source=True, index=True, timestamp=program.mode == "ct",
                     smu_channels=len(program.measure))


def ct_origin(program: CmuProgram, readings: Sequence[CmuReading]) -> float | None:
    """Time stamp of a C-t transient's bias step: ``T1 - h_bias - (index1 - 1) x interval`` of its first sample (PG
    p476 (4-158): time data = t + h_bias + (index - 1) x interval); ``None`` without a time-stamped sample."""
    first = readings[0] if readings else None
    if first is None or first.time is None:
        return None
    index = first.index.value if first.index is not None else 1.0
    return first.time.value - (program.ct_blocks[0].h_bias_s + (index - 1.0) * program.interval_s)


def _rows(program: CmuProgram, readings: Sequence[CmuReading], freq: float, *, first_step: int,
          origin: float | None = None) -> list[dict[str, object]]:
    """Table rows of one measurement's readings (module docstring; ``origin``: the C-t bias step's time stamp)."""
    rows: list[dict[str, object]] = []
    for k, reading in enumerate(readings):
        row: dict[str, object] = {"step": first_step + k}
        if origin is not None and reading.time is not None:
            row["t_s"] = max(reading.time.value - origin, 0.0)
        if program.double and program.mode in ("cv", "pulsed", "cf", "acv"):
            row["segment"] = "fwd" if k < program.points else "rev"
        source = reading.source
        row["freq_hz"] = source.value if program.mode == "cf" and source is not None else freq
        row["ac_vrms"] = source.value if program.mode == "acv" and source is not None else program.ac_vrms
        if program.mode in ("cv", "pulsed") and source is not None:
            row["dc_v"] = source.value
        else:
            row["dc_v"] = program.start if program.mode == "pulsed" else program.dc_v
        for quantity, (value, status) in reading.table_values().items():
            name = f"{program.high_role}_{quantity}"
            row[name] = value
            row[f"{name}_status"] = status
        for column, point in zip(program.measure, reading.smu, strict=False):
            name = f"{column.role}_I"
            row[name] = point.value
            row[f"{name}_status"] = str(point.status.value)
        for column, level in program.source_columns.items():
            row[column] = level
        rows.append(row)
    return rows
