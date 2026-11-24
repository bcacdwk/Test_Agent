"""``cmu_measure``: MFCMU capacitance measurements (blueprint v2 2.7; WP8.3: MM 17 spot C and MM 18 C-V (DC bias)
sweep, single or double, in a host loop over a frequency list; the MFCMU directly or through an SCUU).

Roles (recipe ``roles``, bound through the pin map):

- exactly one ``cmu_high`` role (the MFCMU High side: DC bias and AC drive; its name prefixes the data columns) and
  one ``cmu_low`` role (the Low side, the virtual ground the current is measured at); both on MFCMU side targets
  (``7H``/``7L``) or both through one SCUU (``SCUU1.OUT1``/``OUT2``, ``kinds/cmu_routes.py``);
- optional SMU roles: ``ground`` (the GNDU: nothing is sent; an SMU: ``DV 0`` with compliance setting ``icomp`` or,
  when absent, the MFCMU's nominal current) and ``bias_v`` (``DV`` at setting ``v``, compliance ``icomp``), e.g. a
  MOSFET's source and bulk during split C-V. In a C-V sweep a role with ``measure: [I]`` is measured at every step
  (MM 18 lists it after the MFCMU, PG p471 (4-153)); a spot measurement (MM 17) measures only the MFCMU.

Settings of the ``cmu_high`` role (``$param`` references): ``freqs`` (Hz, a list: one measurement per frequency, in
order; the host loop), ``ac`` (oscillator level, V rms), ``model`` (the parameter pair: ``cp_g`` (``IMP 100``),
``cp_d`` 101, ``cs_rs`` 200, ``cs_d`` 201, ``z_theta`` 10; default ``cp_g``), and either ``dc`` (V) with
``samples`` (spot, MM 17) or ``start``, ``stop``, ``points``, ``mode`` (``single``/``double``), ``hold``, ``delay``
(s; C-V sweep, MM 18: ``WDCV`` linear from ``start`` to ``stop`` and back for ``double``, ``WTDCV hold,delay``,
``WMDCV 2,1``: automatic abort on NULL loop unbalance, IV amplifier saturation or overflow, then the start value).
The recipe parameter ``integration`` (``short`` ``ACT 0,1``, ``medium`` ``ACT 0,2`` = the initial setting, ``long``
``ACT 2,2``: two power-line cycles) sets the MFCMU averaging (PG p354 (4-36)). Ranging is automatic (``RC ch,0``).

Acquisition (one transaction, guarded driver only): ``FMT 1,1`` (each sweep step also returns its DC bias), ``TSC 0``
and ``LMN 0`` (the parsed layout has no time stamps and no monitors), ``IMP``, ``ACT``, ``RC``; with an SCUU the
``measure`` routes (``Transaction.apply_routes``: ``SSP chnum,4``, read back through ``*LRN? 81``; the SSP switches
the MFCMU on, so it is never in ``CN``); ``CN`` of the other channels, ``ERRX?`` drain (an interlock or any error
aborts), on hardware the ``LOP?`` positive control, ``DV`` per SMU role; then per frequency: spot ``FC``/``ACV``/
``DCV`` (``OutputGuard.check_ac``), ``MM 17``, ``ERRX?`` drain and ``samples`` x (``XE`` + read, ``tx.check_abort``,
``ERRX?`` drain before the next trigger),
or C-V ``MM 18``/``FC``/``ACV``/``WTDCV``/``WMDCV``/``WDCV`` (both DC end points checked by the guard), ``ERRX?``
drain, ``XE`` and one read; ``tx.checkpoint`` after each frequency (a cancel acts between frequencies; R-RUN-02
segments). At the end the MFCMU goes to DC 0 V and AC 0 V (guarded) and, with an SCUU, the ``rest`` routes return the
outputs to the switch's rest state (``SSP chnum,3`` for ``rest: smu``); the transaction cleanup (``DCV 0``/``ACV 0``,
routes to rest, ``DZ``, ``CL``, verify) runs on every exit anyway.

Table (``analysis/dataset.py`` contract): ``step``, ``segment`` (double sweeps), ``freq_hz``, ``ac_vrms``, ``dc_v``
(programmed; in a sweep the DC bias the instrument returns with each step), the MFCMU pair ``<high role>_<Cp|G|Cs|
Rs|D|Z|theta>`` + ``_status`` (``CmuReading.table_values``: theta in radian), measured SMU currents ``<role>_I`` +
``_status`` (sweeps) and the programmed ``<role>_V`` of ``bias_v`` roles.

Envelope: the MFCMU channel's ``max_abs_v`` = the largest |DC bias|, ``ac`` = (AC level, |DC|, frequency span); its
current is the nominal peak AC current into a short through the smallest impedance range, ``sqrt(2) x Vac / 50 Ohm``
(the MFCMU has no settable compliance; the value only feeds the current bookkeeping of R-LIM/R-DUT/R-GNDU, as for
``cmu_correction``). Corrections: rule R-CORR-01 needs fresh phase/open/short records of this pin map covering every
frequency (``freqs`` is in Hz, so the rule reads it).

Estimate conventions (TODO(verify) at bring-up L6, the simulator uses the same): ``ACT`` auto mode 8 ms per N, PLC
mode N / 50 Hz per point; 0.5 s per frequency for setup and data transfer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.cmu_routes import MEASURE_PHASE, REST_PHASE, CmuPath, mfcmu_path
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

Mode = Literal["spot", "cv"]

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
    def steps(self) -> int:
        """Data blocks of one frequency: spot ``samples``, a sweep ``points`` (``2 x points`` double)."""
        return self.samples if self.mode == "spot" else self.points * (2 if self.double else 1)

    def segment_s(self) -> float:
        """Estimated time of one frequency's measurement (between two checkpoints)."""
        if self.mode == "spot":
            return FREQ_OVERHEAD_S + self.samples * (self.point_s + SPOT_OVERHEAD_S)
        return FREQ_OVERHEAD_S + self.hold_s + self.steps * (self.delay_s + self.point_s)

    def timeout_s(self) -> float:
        """Read timeout of one measurement: ``2 x segment + 10 s``."""
        return 2.0 * self.segment_s() + READ_TIMEOUT_MARGIN_S

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
        levels = [program.dc_v] if program.mode == "spot" else [program.start, program.stop]
        dc_max = max(abs(v) for v in levels)
        current = cmu_current_a(program.ac_vrms)
        channels: dict[int, ChannelEnvelope] = {program.channel: ChannelEnvelope(
            role=high, max_abs_v=dc_max, max_abs_i=current, function="cmu_high", v_start=levels[0], v_stop=levels[-1],
            ac=AcEnvelope(max_vrms=program.ac_vrms, max_dc_v=dc_max, f_min_hz=min(program.freqs_hz),
                          f_max_hz=max(program.freqs_hz)))}
        for bias in program.biases:
            spec = recipe.roles[bias.role]
            channels[bias.channel] = ChannelEnvelope(role=bias.role, max_abs_v=abs(bias.level),
                                                     max_abs_i=abs(bias.comp), function=spec.function,
                                                     v_start=bias.level, v_stop=bias.level)
        envelope = CompiledEnvelope(channels=channels, routes=frozenset(path.routes))
        total = len(program.freqs_hz) * program.steps
        segment = program.segment_s()
        estimate = Estimate(points=total, duration_s=round(len(program.freqs_hz) * segment + 1.0, 6),
                            max_segment_s=round(segment, 6))
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
        common: dict[str, object] = {
            "channel": channel, "high_role": high, "low_role": low, "model": model, "imp": IMP_MODELS[str(model)],
            "freqs_hz": _frequencies(get("freqs"), f"{high}.freqs"), "ac_vrms": ac, "act": act,
            "point_s": point_time_s(act), "routes": path.routes, "rest_routes": path.rest,
        }
        mode: Mode = "cv" if "start" in role.settings or "stop" in role.settings else "spot"
        if mode == "cv":
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
                    raise CompileError(f"{name}: SMU currents are measured only during a C-V sweep; a spot C "
                                       "measurement measures the MFCMU alone")
                measure.append(MeasureColumn(channel=bound.channel, role=name, quantity="I"))
        if len(measure) > 9:
            raise CompileError(f"{self.kind_id}: a C-V sweep measures at most nine SMU channels besides the MFCMU")
        return biases, measure, columns, enable

    @staticmethod
    def _preview(program: CmuProgram, path: CmuPath) -> list[str]:
        ch = program.channel
        lines = [flex.fmt(1, 1), flex.tsc(False), flex.lmn(0), flex.imp(program.imp), flex.act(*program.act),
                 flex.rc(ch, 0), *path.preview(ch, MEASURE_PHASE)]
        if program.enable:
            lines.append(flex.cn(program.enable))
        lines += [bias_command(b) for b in program.biases]
        for freq in program.freqs_hz:
            if program.mode == "spot":
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
        driver.set_time_stamp(False)
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
        for index, freq in enumerate(program.freqs_hz):
            measured = self._measure_frequency(tx, program, freq)
            blocks.extend(measured)
            readings = [r for b in measured for r in b.readings]
            tx.checkpoint(index + 1, len(program.freqs_hz), f"{freq:g} Hz",
                          rows=lambda readings=readings, freq=freq, first=offset: _rows(program, readings, freq,
                                                                                       first_step=first))
            offset += len(readings)
        driver.apply_cmu_signal(ch, CmuSignal(freq_hz=program.freqs_hz[-1], ac_vrms=0.0, dc_v=0.0))
        if program.rest_routes:
            tx.apply_routes(program.rest_routes, phase=REST_PHASE)
        statuses = sorted({r.status for b in blocks for r in b.readings} - {"N"})
        result: dict[str, object] = {"frequencies": len(program.freqs_hz), "readings": sum(len(b.readings)
                                                                                         for b in blocks)}
        if statuses:
            result["cmu_status"] = ",".join(statuses)
        return RawAcquisition(blocks=[b.raw for b in blocks], kind_result=result)  # type: ignore[arg-type]

    @staticmethod
    def _measure_frequency(tx: Transaction, program: CmuProgram, freq: float) -> list[CmuBlock]:
        driver = tx.driver
        ch = program.channel
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
        per_freq = program.samples if program.mode == "spot" else 1
        expected = len(program.freqs_hz) * per_freq
        if len(raw.blocks) != expected:
            raise ValueError(f"expected {expected} measurement blocks, got {len(raw.blocks)}")
        layout = table_layout(program)
        rows: list[dict[str, object]] = []
        for index, block in enumerate(raw.blocks):
            freq = program.freqs_hz[index // per_freq]
            readings = parse_cmu_blocks(block.points[:len(block.points) - len(block.points) % layout.width], layout)
            rows.extend(_rows(program, readings, freq, first_step=len(rows)))
        return pd.DataFrame(rows)


def table_layout(program: CmuProgram) -> CmuLayout:
    """The data layout ``acquire`` sets up (``FMT 1,1``, ``TSC 0``, ``LMN 0``): parameter pair, source data in a
    sweep, the measured SMU channels."""
    return CmuLayout(imp=program.imp, mode=17 if program.mode == "spot" else 18, source=True, index=True,
                     smu_channels=len(program.measure))


def _rows(program: CmuProgram, readings: Sequence[CmuReading], freq: float, *,
          first_step: int) -> list[dict[str, object]]:
    """Table rows of one measurement's readings (module docstring)."""
    rows: list[dict[str, object]] = []
    for k, reading in enumerate(readings):
        row: dict[str, object] = {"step": first_step + k}
        if program.mode == "cv" and program.double:
            row["segment"] = "fwd" if k < program.points else "rev"
        row["freq_hz"] = freq
        row["ac_vrms"] = program.ac_vrms
        source = reading.source
        row["dc_v"] = program.dc_v if program.mode == "spot" or source is None else source.value
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
