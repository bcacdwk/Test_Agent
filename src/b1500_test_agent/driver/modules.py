"""DC output capabilities and range codes of the SMU types and the GNDU (rule R-LIM-01, range-code mapping).

Sources ("PG" = Keysight B1500 Series Programming Guide, Edition 15; "UG" = Keysight B1500A User's Guide,
Edition 17; PDF page numbers are physical 1-based pages of ``B1500A Programming Guide.pdf`` and
``B1500A User Guide.pdf``):

- Range codes and which module type has them: PG Table 4-2 (V measurement, PDF 335), Table 4-3 (I measurement,
  PDF 337), Table 4-4 (V output, PDF 339), Table 4-5 (I output, PDF 340). Output and measurement tables list the
  same codes per SMU type, so one list per quantity serves ``DV``/``WV`` ``vrange`` and ``RI``/``RV``.
- V/I envelopes: PG Tables 4-6 and 4-7 (HR/MP/HPSMU, PDF 341-342), 4-8 and 4-9 (MC/HCSMU, PDF 343-344), 4-11 and
  4-12 (HVSMU, PDF 345); UG HPSMU PDF 60-62, MPSMU PDF 63-65, MCSMU PDF 67-68, HRSMU PDF 69-71 (maximum voltage,
  current and power).
- GNDU: 0 V, sinks up to 4.2 A (UG PDF 58).
- High-resolution ADC not available for HCSMU, HVSMU, MCSMU (PG ``AAD``, PDF 351); ``CMM`` mode 4 not available
  for HPSMU, MPSMU, HRSMU (PG PDF 380); HPSMU, HCSMU and HVSMU occupy two slots (PG Table 4-1, PDF 334).
- Power compliance maxima as a cross-check of the envelopes: 2 W MP/HRSMU, 20 W HPSMU, 40 W HCSMU, 3 W MCSMU
  (PG ``WV`` ``Pcomp``, PDF 569).

HCSMU (B1512A) and HVSMU (B1513x) are B1505A-family modules; their limits come from the Programming Guide tables
because the B1500A User's Guide does not describe them.

v2 spec rows (blueprint v2 2.5, last bullet; rules R-LIM-01, R-PULSE-01, R-SPGU-01, R-CMU-01, R-WG-02, R-GNDU-01,
R-ASU-01 and the ``OutputGuard`` pulse/AC/waveform checks): ``SPGU_SPEC`` (HV-SPGU output and PG timing),
``SMU_PULSE_SPECS`` (``PT`` pulse width/period per SMU type), ``WGFMU_SPEC`` (ranges, modes, ALWG and event limits),
``CMU_SPEC`` (MFCMU frequency, AC level, DC bias), ``SCUU_SPEC`` and ``ASU_SPEC`` (switch accessories); the GNDU row
stays in ``MODULE_SPECS``. ``module_spec`` keeps answering only for DC sources (SMUs and the GNDU).
"""

from __future__ import annotations

import math
from typing import Final, Literal, NamedTuple

from pydantic import Field

from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Ranging
from b1500_test_agent.models.sources import (
    WGFMU_GRID_S,
    PulseTrain,
    on_grid,
    open_load_voltage,
)
from b1500_test_agent.models.spgu import AlwgProgram, SpguPulseProgram
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL

SpecType = Literal["HPSMU", "MPSMU", "HRSMU", "MCSMU", "HCSMU", "HVSMU", "GNDU"]

V_RANGE_FULL_SCALE: dict[int, float] = {
    2: 0.2, 5: 0.5, 11: 2.0, 20: 2.0, 50: 5.0, 12: 20.0, 200: 20.0, 13: 40.0, 400: 40.0, 14: 100.0, 1000: 100.0,
    15: 200.0, 2000: 200.0, 5000: 500.0, 15000: 1500.0, 30000: 3000.0,
}  # fmt: skip
"""Voltage range code (absolute value) -> full scale in V (PG Tables 4-2/4-4). Codes 11-15 are the short forms of
20, 200, 400, 1000, 2000."""

I_RANGE_FULL_SCALE: dict[int, float] = {
    8: 1e-12, 9: 1e-11, 10: 1e-10, 11: 1e-9, 12: 1e-8, 13: 1e-7, 14: 1e-6, 15: 1e-5, 16: 1e-4, 17: 1e-3, 18: 1e-2,
    19: 0.1, 20: 1.0, 21: 2.0, 22: 20.0, 23: 40.0,
}  # fmt: skip
"""Current range code (absolute value) -> full scale in A (PG Tables 4-3/4-5): 8 = 1 pA ... 19 = 100 mA, 20 = 1 A,
21 = 2 A, 22 = 20 A, 23 = 40 A."""


class RangeSpec(StrictModel):
    """One output/measurement range of a module: the positive (limited auto) code, full scale and availability."""

    code: int = Field(gt=0)
    full_scale: float = Field(gt=0)
    requires_asu: bool = False
    pulse_only: bool = False


class ModuleSpec(StrictModel):
    """DC capabilities of one module type.

    ``v_source_envelope`` lists ``(|V| up to, max |Icomp|)`` corners for voltage forcing and ``i_source_envelope``
    ``(|I| up to, max |Vcomp|)`` corners for current forcing (both from the PG source setup tables); a point is
    inside when some corner covers both magnitudes. ``max_power_w`` is the largest V*I of the corners.
    """

    module_type: SpecType
    models: tuple[str, ...]
    slots: int = Field(ge=1, le=2)
    max_abs_v: float = Field(ge=0)
    max_abs_i: float = Field(gt=0)
    v_source_envelope: tuple[tuple[float, float], ...]
    i_source_envelope: tuple[tuple[float, float], ...]
    v_ranges: tuple[RangeSpec, ...] = ()
    i_ranges: tuple[RangeSpec, ...] = ()
    high_resolution_adc: bool = False
    cmm_modes: tuple[int, ...] = ()
    envelope_source: str
    sources: tuple[str, ...]

    @property
    def max_power_w(self) -> float:
        """Largest DC output power of the envelope (W)."""
        return max(v * i for v, i in self.v_source_envelope)

    def range_for(self, quantity: Literal["V", "I"], code: int) -> RangeSpec | None:
        """The range with ``abs(code)`` (short or long voltage form), or ``None`` when the module lacks it."""
        table = V_RANGE_FULL_SCALE if quantity == "V" else I_RANGE_FULL_SCALE
        full_scale = table.get(abs(code))
        ranges = self.v_ranges if quantity == "V" else self.i_ranges
        return next((r for r in ranges if full_scale is not None and r.full_scale == full_scale), None)


def _v(*codes: int) -> tuple[RangeSpec, ...]:
    return tuple(RangeSpec(code=c, full_scale=V_RANGE_FULL_SCALE[c]) for c in codes)


def _i(*codes: int, asu: tuple[int, ...] = (), pulse: tuple[int, ...] = ()) -> tuple[RangeSpec, ...]:
    return tuple(
        RangeSpec(code=c, full_scale=I_RANGE_FULL_SCALE[c], requires_asu=c in asu, pulse_only=c in pulse)
        for c in (*asu, *codes)
    )


_HR_MP_ENVELOPE = ((20.0, 0.1), (40.0, 0.05), (100.0, 0.02))
_HR_MP_I_ENVELOPE = ((0.02, 100.0), (0.05, 40.0), (0.1, 20.0))
_HR_MP_V_RANGES = _v(5, 20, 50, 200, 400, 1000)
_SMU_CMM = (0, 1, 2, 3)

MODULE_SPECS: dict[str, ModuleSpec] = {
    "HPSMU": ModuleSpec(
        module_type="HPSMU",
        models=("B1510A",),
        slots=2,
        max_abs_v=200.0,
        max_abs_i=1.0,
        v_source_envelope=((20.0, 1.0), (40.0, 0.5), (100.0, 0.125), (200.0, 0.05)),
        i_source_envelope=((0.05, 200.0), (0.125, 100.0), (0.5, 40.0), (1.0, 20.0)),
        v_ranges=_v(20, 200, 400, 1000, 2000),
        i_ranges=_i(*range(11, 21)),
        high_resolution_adc=True,
        cmm_modes=_SMU_CMM,
        envelope_source="PG Tables 4-6/4-7, PDF 341-342",
        sources=("PG Tables 4-2 to 4-7, PDF 335-342", "UG HPSMU, PDF 60-62 (200 V, 1 A, 20 W)"),
    ),
    "MPSMU": ModuleSpec(
        module_type="MPSMU",
        models=("B1511A", "B1511B"),
        slots=1,
        max_abs_v=100.0,
        max_abs_i=0.1,
        v_source_envelope=_HR_MP_ENVELOPE,
        i_source_envelope=_HR_MP_I_ENVELOPE,
        v_ranges=_HR_MP_V_RANGES,
        i_ranges=_i(*range(11, 20), asu=(8, 9, 10)),
        high_resolution_adc=True,
        cmm_modes=_SMU_CMM,
        envelope_source="PG Tables 4-6/4-7, PDF 341-342",
        sources=(
            "PG Tables 4-2 to 4-7, PDF 335-342 (1-100 pA ranges: B1511B with ASU only)",
            "UG MPSMU, PDF 63-65 (100 V, 100 mA, 2 W)",
        ),
    ),
    "HRSMU": ModuleSpec(
        module_type="HRSMU",
        models=("B1517A",),
        slots=1,
        max_abs_v=100.0,
        max_abs_i=0.1,
        v_source_envelope=_HR_MP_ENVELOPE,
        i_source_envelope=_HR_MP_I_ENVELOPE,
        v_ranges=_HR_MP_V_RANGES,
        i_ranges=_i(*range(9, 20), asu=(8,)),
        high_resolution_adc=True,
        cmm_modes=_SMU_CMM,
        envelope_source="PG Tables 4-6/4-7, PDF 341-342",
        sources=(
            "PG Tables 4-2 to 4-7, PDF 335-342 (1 pA range: ASU only)",
            "UG HRSMU, PDF 69-71 (100 V, 100 mA, 2 W)",
        ),
    ),
    "MCSMU": ModuleSpec(
        module_type="MCSMU",
        models=("B1514A",),
        slots=1,
        max_abs_v=30.0,
        max_abs_i=0.1,
        v_source_envelope=((30.0, 0.1),),
        i_source_envelope=((0.1, 30.0),),
        v_ranges=_v(2, 20, 200, 400),
        i_ranges=_i(*range(15, 21), pulse=(20,)),
        cmm_modes=(*_SMU_CMM, 4),
        envelope_source="PG Tables 4-8/4-9, PDF 343-344",
        sources=(
            "PG Tables 4-2 to 4-5, 4-8, 4-9, PDF 335-344 (40 V range limited to 30 V; 1 A range pulse only)",
            "UG MCSMU, PDF 67-68 (30 V, 0.1 A DC, 3 W DC)",
        ),
    ),
    "HCSMU": ModuleSpec(
        module_type="HCSMU",
        models=("B1512A",),
        slots=2,
        max_abs_v=40.0,
        max_abs_i=1.0,
        v_source_envelope=((40.0, 1.0),),
        i_source_envelope=((1.0, 40.0),),
        v_ranges=_v(2, 20, 200, 400),
        i_ranges=(*_i(*range(15, 21)), *_i(22, pulse=(22,))),
        cmm_modes=(*_SMU_CMM, 4),
        envelope_source="PG Tables 4-8/4-9, PDF 343-344",
        sources=("PG Tables 4-2 to 4-5, 4-8, 4-9, PDF 335-344 (DC 1 A at up to 40 V; 20 A range pulse only)",),
    ),
    "HVSMU": ModuleSpec(
        module_type="HVSMU",
        models=("B1513A", "B1513B", "B1513C"),
        slots=2,
        max_abs_v=3000.0,
        max_abs_i=0.008,
        v_source_envelope=((1500.0, 0.008), (3000.0, 0.004)),
        i_source_envelope=((0.004, 3000.0), (0.008, 1500.0)),
        v_ranges=_v(2000, 5000, 15000, 30000),
        i_ranges=_i(*range(11, 19)),
        cmm_modes=(*_SMU_CMM, 4),
        envelope_source="PG Tables 4-11/4-12, PDF 345",
        sources=("PG Tables 4-2 to 4-5, 4-11, 4-12, PDF 335-345",),
    ),
    "GNDU": ModuleSpec(
        module_type="GNDU",
        models=(),
        slots=1,
        max_abs_v=0.0,
        max_abs_i=4.2,
        v_source_envelope=((0.0, 4.2),),
        i_source_envelope=((4.2, 0.0),),
        envelope_source="UG GNDU, PDF 58",
        sources=("UG GNDU, PDF 58 (0 V reference, sinks up to 4.2 A)",),
    ),
}
"""DC spec per SMU type and the mainframe GNDU. MFCMU, HVSPGU and WGFMU are not DC sources: their rows are
``CMU_SPEC``, ``SPGU_SPEC`` and ``WGFMU_SPEC`` below (``module_spec`` refuses them)."""


def module_spec(model_or_type: str) -> ModuleSpec:
    """Look up a spec by module type (``HRSMU``), model number (``B1517A``) or ``GNDU``.

    Raises:
        KeyError: For unknown names and for modules without a DC source spec (MFCMU, HVSPGU, WGFMU).
    """
    key = MODULE_TYPE_BY_MODEL.get(model_or_type, model_or_type)
    try:
        return MODULE_SPECS[key]
    except KeyError:
        raise KeyError(f"no DC source spec for {model_or_type!r}; known: {sorted(MODULE_SPECS)}") from None


def _covered(envelope: tuple[tuple[float, float], ...], level: float, other: float) -> bool:
    return any(level <= max_level and other <= max_other for max_level, max_other in envelope)


def violations(spec: ModuleSpec, v: float, i: float, *, source: Literal["V", "I"] = "V") -> list[str]:
    """Why forcing on a module of ``spec`` would leave its DC capability; empty when it is inside.

    ``source="V"``: ``v`` is the forced voltage and ``i`` the current compliance; ``source="I"``: ``i`` is the forced
    current and ``v`` the voltage compliance. Signs are ignored. For the GNDU, ``v`` must be 0 and ``i`` is the
    current it sinks.
    """
    if not (math.isfinite(v) and math.isfinite(i)):
        return [f"{spec.module_type}: non-finite value (V={v!r}, I={i!r})"]
    abs_v, abs_i = abs(v), abs(i)
    found: list[str] = []
    if abs_v > spec.max_abs_v:
        found.append(f"{spec.module_type}: |V| {abs_v:g} V exceeds the module maximum {spec.max_abs_v:g} V")
    if abs_i > spec.max_abs_i:
        found.append(f"{spec.module_type}: |I| {abs_i:g} A exceeds the module maximum {spec.max_abs_i:g} A (DC)")
    if not found:
        inside = (
            _covered(spec.v_source_envelope, abs_v, abs_i)
            if source == "V"
            else _covered(spec.i_source_envelope, abs_i, abs_v)
        )
        if not inside:
            found.append(
                f"{spec.module_type}: {abs_v:g} V with {abs_i:g} A is outside the output envelope "
                f"(max {spec.max_power_w:g} W; {spec.envelope_source})"
            )
    return found


def range_full_scale(quantity: Literal["V", "I"], code: int) -> float:
    """Full scale (V or A) of a ranging code; the sign (limited auto / fixed) is ignored.

    Raises:
        KeyError: If the code is 0 (auto ranging has no full scale) or not an SMU range code.
    """
    table = V_RANGE_FULL_SCALE if quantity == "V" else I_RANGE_FULL_SCALE
    try:
        return table[abs(code)]
    except KeyError:
        raise KeyError(f"{code} is not a {quantity} range code") from None


def ranging_code(spec: ModuleSpec, ranging: Ranging, *, asu: bool = False) -> int:
    """FLEX ranging code for a ``Ranging`` on a module: 0 = auto, ``+code`` = limited auto, ``-code`` = fixed.

    ``ranging.range_value`` must equal the full scale of a range the module has (1 pA ranges need ``asu=True``;
    pulse-only ranges are refused). Voltage codes use the long form (20 for 2 V).

    Raises:
        ValueError: If the module has no such DC range.
    """
    if ranging.mode == "auto":
        return 0
    ranges = spec.v_ranges if ranging.quantity == "V" else spec.i_ranges
    unit = "V" if ranging.quantity == "V" else "A"
    for candidate in ranges:
        if math.isclose(candidate.full_scale, ranging.range_value, rel_tol=1e-9, abs_tol=0.0):
            if candidate.pulse_only:
                raise ValueError(f"{spec.module_type}: the {ranging.range_value:g} {unit} range is pulse only")
            if candidate.requires_asu and not asu:
                raise ValueError(f"{spec.module_type}: the {ranging.range_value:g} {unit} range needs an ASU")
            return candidate.code if ranging.mode == "limited_auto" else -candidate.code
    available = ", ".join(f"{r.full_scale:g}" for r in ranges if not r.pulse_only)
    raise ValueError(
        f"{spec.module_type} has no {ranging.range_value:g} {unit} range (available: {available or 'none'})"
    )


# -- v2 spec rows: pulse sources, WGFMU, MFCMU and switch accessories ------------------------------------------------


class SpecProblem(NamedTuple):
    """One way a setting leaves a module spec: what is wrong, the observed value and the limit."""

    message: str
    observed: float | int | str | None
    limit: float | int | str | None


def _within(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _span(bounds: tuple[float, float]) -> str:
    return f"{bounds[0]:g}..{bounds[1]:g}"


class SpguSpec(StrictModel):
    """HV-SPGU (B1525A) output and PG-mode timing (UG p76 (2-36) "HVSPGU"; PG p507 (4-189) "SER", PG p512 (4-194)
    "SPPER", PG p513 (4-195) "SPRM", PG p514 (4-196) "SPT", PG p516 (4-198) "SPV"; operation errors 2111/2112 on
    PG p591-592).

    50 Ohm output without compliance; 0 to +-40 V open load, +-20 V into 50 Ohm; the level is adjusted to the declared
    load ``SER`` (0.1 Ohm to 1 MOhm, initial 50 Ohm), so an open load sees ``|V| (SER + 50) / SER``. Period 20 ns to
    10 s (10 ns resolution); width 10 ns to period - 10 ns; delay 0 to period - 20 ns (width and delay resolution
    2.5 ns, 10 ns when a transition exceeds 8 us); transitions 8 ns to 0.4 s (2 ns, 8 ns above 8 us; initial 20 ns);
    width >= leading / 0.8 and period >= delay + width + trailing / 0.8; count 1 to 1,000,000 pulses or duration
    1 us to 31,556,926 s (10 ns resolution); free run (``SPRM 0``) is never used (R-PULSE-01). ALWG (PG p150 (2-62)
    "Table 2-4"): at most 1024 - patterns vectors per channel, vector times 10 ns to 671.08863 ms on the 10 ns grid.
    """

    module_type: Literal["HVSPGU"] = "HVSPGU"
    models: tuple[str, ...] = ("B1525A",)
    output_ohm: float = 50.0
    max_open_v: float = 40.0
    max_matched_v: float = 20.0
    level_resolution_v: float = 1e-3
    period_s: tuple[float, float] = (2e-8, 10.0)
    period_resolution_s: float = 1e-8
    min_width_s: float = 1e-8
    width_margin_s: float = 1e-8
    delay_margin_s: float = 2e-8
    transition_s: tuple[float, float] = (8e-9, 0.4)
    initial_transition_s: float = 2e-8
    slow_transition_s: float = 8e-6
    time_resolution_s: tuple[float, float] = (2.5e-9, 1e-8)
    transition_resolution_s: tuple[float, float] = (2e-9, 8e-9)
    edge_fraction: float = 0.8
    count: tuple[int, int] = (1, 1_000_000)
    duration_s: tuple[float, float] = (1e-6, 31_556_926.0)
    duration_resolution_s: float = 1e-8
    load_ohm: tuple[float, float] = (0.1, 1e6)
    initial_load_ohm: float = 50.0
    alwg_max_vectors: int = 1024
    alwg_dt_s: tuple[float, float] = (1e-8, 0.67108863)
    high_z_min_load_ohm: float = 1e3
    """Smallest ``SER`` for a terminal declared ``high_z`` (blueprint v2 2.8 R-SPGU-01): a smaller declared load
    lets the auto-levelling raise the open-load voltage towards 2x the set level."""
    sources: tuple[str, ...] = ("UG p76 (2-36)", "PG p507 (4-189)", "PG p512-516 (4-194)", "PG p591-592")

    def open_load_v(self, max_abs_set_v: float, load_ohm: float | None) -> float:
        """|V| an open load sees for a set level and ``SER`` (``None`` = the initial 50 Ohm)."""
        return open_load_voltage(max_abs_set_v, load_ohm=load_ohm, source_ohm=self.output_ohm)

    def train_problems(self, train: PulseTrain) -> list[SpecProblem]:
        """Where a PG-mode pulse train leaves the module spec (empty when it is inside)."""
        found: list[SpecProblem] = []
        for name, level in (("base", train.base_v), ("peak", train.peak_v)):
            if abs(level) > self.max_open_v:
                found.append(SpecProblem(f"{name} {level:g} V is outside the SPV range +-{self.max_open_v:g} V",
                                         level, self.max_open_v))
            elif not on_grid(level, self.level_resolution_v):
                found.append(SpecProblem(f"{name} {level:g} V is not on the 1 mV setting resolution", level,
                                         self.level_resolution_v))
        period, width, delay = train.period_s, train.width_s, train.delay_s
        lead = train.lead_s if train.lead_s is not None else self.initial_transition_s
        trail = train.trail_s if train.trail_s is not None else self.initial_transition_s
        slow = max(lead, trail) > self.slow_transition_s
        if not _within(period, self.period_s):
            found.append(SpecProblem(f"period {period:g} s is outside {_span(self.period_s)} s", period,
                                     _span(self.period_s)))
        elif not on_grid(period, self.period_resolution_s):
            found.append(SpecProblem(f"period {period:g} s is not on the 10 ns resolution", period,
                                     self.period_resolution_s))
        max_width = period - self.width_margin_s
        if not self.min_width_s <= width <= max_width:
            found.append(SpecProblem(f"width {width:g} s is outside {self.min_width_s:g}..{max_width:g} s "
                                     "(period - 10 ns)", width, f"{self.min_width_s:g}..{max_width:g}"))
        step = self.time_resolution_s[1] if slow else self.time_resolution_s[0]
        for name, value in (("width", width), ("delay", delay)):
            if not on_grid(value, step):
                found.append(SpecProblem(f"{name} {value:g} s is not on the {step:g} s resolution", value, step))
        if delay > period - self.delay_margin_s:
            found.append(SpecProblem(f"delay {delay:g} s exceeds period - 20 ns", delay,
                                     period - self.delay_margin_s))
        t_step = self.transition_resolution_s[1] if slow else self.transition_resolution_s[0]
        for name, value in (("leading", lead), ("trailing", trail)):
            if not _within(value, self.transition_s):
                found.append(SpecProblem(f"{name} time {value:g} s is outside {_span(self.transition_s)} s", value,
                                         _span(self.transition_s)))
            elif not on_grid(value, t_step):
                found.append(SpecProblem(f"{name} time {value:g} s is not on the {t_step:g} s resolution", value,
                                         t_step))
        if width < lead / self.edge_fraction:
            found.append(SpecProblem(f"width {width:g} s is shorter than leading / 0.8 = {lead / 0.8:g} s "
                                     "(error 2111)", width, lead / self.edge_fraction))
        need = delay + width + trail / self.edge_fraction
        if period < need:
            found.append(SpecProblem(f"period {period:g} s is shorter than delay + width + trailing / 0.8 = "
                                     f"{need:g} s (error 2112)", period, need))
        if train.count is not None and not _within(train.count, self.count):
            found.append(SpecProblem(f"count {train.count} is outside {self.count[0]}..{self.count[1]}", train.count,
                                     f"{self.count[0]}..{self.count[1]}"))
        if train.duration_s is not None:
            if not _within(train.duration_s, self.duration_s):
                found.append(SpecProblem(f"duration {train.duration_s:g} s is outside {_span(self.duration_s)} s",
                                         train.duration_s, _span(self.duration_s)))
            elif not on_grid(train.duration_s, self.duration_resolution_s):
                found.append(SpecProblem(f"duration {train.duration_s:g} s is not on the 10 ns resolution",
                                         train.duration_s, self.duration_resolution_s))
        if train.load_ohm is not None and not _within(train.load_ohm, self.load_ohm):
            found.append(SpecProblem(f"SER load {train.load_ohm:g} Ohm is outside {_span(self.load_ohm)} Ohm",
                                     train.load_ohm, _span(self.load_ohm)))
        return found

    def _open_load_problem(self, ch: int, extreme_v: float, load_ohm: float) -> list[SpecProblem]:
        """Error 2107: the open-load level ``|V| (SER + 50) / SER`` must stay within the 40 V output (PG p591)."""
        open_v = self.open_load_v(extreme_v, load_ohm)
        if open_v > self.max_open_v * (1 + 1e-12):
            return [SpecProblem(f"channel {ch}: {extreme_v:g} V with a {load_ohm:g} Ohm load setting needs "
                                f"{open_v:g} V open load, beyond {self.max_open_v:g} V (error 2107)", open_v,
                                self.max_open_v)]
        return []

    def program_problems(self, program: SpguPulseProgram | AlwgProgram) -> list[SpecProblem]:
        """Where an SPGU program leaves the module spec (empty when inside). PG: every pulse source's train
        (``train_problems``), the three-level sum within +-40 V (error 2106, PG p591) and the open-load level within
        40 V (error 2107). ALWG (PG p150-151 (2-62) Tables 2-4/2-5): levels +-40 V on 1 mV, vector times 10 ns to
        671.08863 ms on 10 ns, at most ``1024 - patterns`` vectors per channel, the run bound and ``SER`` as for PG,
        the open-load level within 40 V."""
        found: list[SpecProblem] = []
        if isinstance(program, SpguPulseProgram):
            for ch, channel in sorted(program.channels.items()):
                for train in program.source_trains(ch):
                    found += [SpecProblem(f"channel {ch}: {p.message}", p.observed, p.limit)
                              for p in self.train_problems(train)]
                if channel.levels == "three_level" and abs(channel.extreme_v) > self.max_open_v:
                    found.append(SpecProblem(f"channel {ch}: the three-level sum {channel.extreme_v:g} V is outside "
                                             f"+-{self.max_open_v:g} V (error 2106)", channel.extreme_v,
                                             self.max_open_v))
                found += self._open_load_problem(ch, channel.extreme_v, channel.load_ohm)
            return found
        if program.count is not None and not _within(program.count, self.count):
            found.append(SpecProblem(f"count {program.count} is outside {self.count[0]}..{self.count[1]}",
                                     program.count, f"{self.count[0]}..{self.count[1]}"))
        if program.duration_s is not None and not (_within(program.duration_s, self.duration_s)
                                                   and on_grid(program.duration_s, self.duration_resolution_s)):
            found.append(SpecProblem(f"duration {program.duration_s:g} s is outside {_span(self.duration_s)} s or "
                                     "off the 10 ns resolution", program.duration_s, _span(self.duration_s)))
        for ch, channel in sorted(program.channels.items()):
            train = program.guard_train(ch)
            if not _within(channel.load_ohm, self.load_ohm):
                found.append(SpecProblem(f"channel {ch}: SER load {channel.load_ohm:g} Ohm is outside "
                                         f"{_span(self.load_ohm)} Ohm", channel.load_ohm, _span(self.load_ohm)))
            vectors = sum(len(pattern.vectors) for pattern in channel.patterns)
            if vectors > self.alwg_max_vectors - len(channel.patterns):
                found.append(SpecProblem(f"channel {ch}: {vectors} ALWG vectors exceed 1024 - "
                                         f"{len(channel.patterns)} patterns", vectors,
                                         self.alwg_max_vectors - len(channel.patterns)))
            for number, pattern in enumerate(channel.patterns, start=1):
                for level in pattern.levels():
                    if abs(level) > self.max_open_v or not on_grid(level, self.level_resolution_v):
                        found.append(SpecProblem(f"channel {ch} pattern {number}: level {level:g} V is outside "
                                                 f"+-{self.max_open_v:g} V or not on 1 mV", level, self.max_open_v))
                for vector in pattern.vectors:
                    if not (_within(vector.dt_s, self.alwg_dt_s) and on_grid(vector.dt_s, self.period_resolution_s)):
                        found.append(SpecProblem(f"channel {ch} pattern {number}: vector time {vector.dt_s:g} s is "
                                                 f"outside {_span(self.alwg_dt_s)} s or off the 10 ns grid",
                                                 vector.dt_s, _span(self.alwg_dt_s)))
            found += self._open_load_problem(ch, train.max_abs_set_v, channel.load_ohm)
        return found


class SmuPulseSpec(StrictModel):
    """SMU pulse timing (``PT``; PG p486-487 (4-168) "PT"): pulse width, period and their margins per SMU type.

    Period 5 ms to 5 s (0.1 ms resolution); period >= width + 2 ms for widths up to 100 ms, >= width + 10 ms above.
    SMU pulses have no programmable transition time; the trigger delay lies within the width.
    """

    module_type: Literal["HPSMU", "MPSMU", "HRSMU", "MCSMU", "HCSMU", "HVSMU"]
    width_s: tuple[float, float]
    width_resolution_s: float
    period_s: tuple[float, float] = (5e-3, 5.0)
    period_resolution_s: float = 1e-4
    short_margin_s: float = 2e-3
    long_margin_s: float = 1e-2
    long_width_s: float = 0.1
    source: str = "PG p486-487 (4-168)"

    def train_problems(self, train: PulseTrain) -> list[SpecProblem]:
        """Where an SMU pulse train leaves the ``PT`` table (empty when it is inside)."""
        found: list[SpecProblem] = []
        width, period = train.width_s, train.period_s
        if not _within(width, self.width_s):
            found.append(SpecProblem(f"{self.module_type} pulse width {width:g} s is outside "
                                     f"{_span(self.width_s)} s", width, _span(self.width_s)))
        elif not on_grid(width, self.width_resolution_s):
            found.append(SpecProblem(f"pulse width {width:g} s is not on the {self.width_resolution_s:g} s "
                                     "resolution", width, self.width_resolution_s))
        if not _within(period, self.period_s):
            found.append(SpecProblem(f"pulse period {period:g} s is outside {_span(self.period_s)} s", period,
                                     _span(self.period_s)))
        elif not on_grid(period, self.period_resolution_s):
            found.append(SpecProblem(f"pulse period {period:g} s is not on the 0.1 ms resolution", period,
                                     self.period_resolution_s))
        margin = self.short_margin_s if width <= self.long_width_s else self.long_margin_s
        if period < width + margin:
            found.append(SpecProblem(f"pulse period {period:g} s is shorter than width + {margin * 1e3:g} ms",
                                     period, width + margin))
        if train.lead_s is not None or train.trail_s is not None:
            found.append(SpecProblem("SMU pulses have no programmable transition time", None, None))
        if train.delay_s > width:
            found.append(SpecProblem(f"trigger delay {train.delay_s:g} s exceeds the width", train.delay_s, width))
        if train.load_ohm is not None:
            found.append(SpecProblem("SMU pulses have no SER load setting", train.load_ohm, None))
        return found


SMU_PULSE_SPECS: Final[dict[str, SmuPulseSpec]] = {
    "HPSMU": SmuPulseSpec(module_type="HPSMU", width_s=(5e-4, 2.0), width_resolution_s=1e-4),
    "MPSMU": SmuPulseSpec(module_type="MPSMU", width_s=(5e-4, 2.0), width_resolution_s=1e-4),
    "HRSMU": SmuPulseSpec(module_type="HRSMU", width_s=(5e-4, 2.0), width_resolution_s=1e-4),
    "HVSMU": SmuPulseSpec(module_type="HVSMU", width_s=(5e-4, 2.0), width_resolution_s=2e-6),
    "HCSMU": SmuPulseSpec(module_type="HCSMU", width_s=(5e-5, 2.0), width_resolution_s=2e-6),
    "MCSMU": SmuPulseSpec(module_type="MCSMU", width_s=(1e-5, 2.0), width_resolution_s=2e-6),
}
"""``PT`` width range and resolution per SMU type (PG p486 (4-168) "500"): HR/HP/MPSMU 500 us to 2 s at 100 us,
HVSMU 500 us to 2 s at 2 us, HCSMU 50 us to 2 s at 2 us, MCSMU 10 us to 2 s at 2 us (outside its 1 A range)."""


class WgfmuSpec(StrictModel):
    """B1530A WGFMU + RSU (WG p16 (1-4) "WGFMU"; ALWG limits WG5 p24 (1-14) "2048"; function limits WG p125 (4-55)
    "setMeasureEvent", WG p128 (4-58) "setRangeEvent", WG p80 (4-10) "addSequence"; errors 3302-3316 WG p153 (4-83)).

    No compliance (it covers the full scale of the current range). Force ranges 3 V (-3..3), 5 V (-5..5), -10 V
    (-10..0), 10 V (0..10); PG mode: 50 Ohm output, -5..5 V open load (3 V or 5 V range), voltage measurement only;
    current measurement in Fast IV or DC mode only (1 uA to 10 mA ranges); minimum pulse width 100 ns in PG mode and
    300 ns in Fast IV mode (``min_pulse_width_s``); SMU pass-through mode up to +-25 V, 100 mA,
    and the RSU's "From SMU" input takes at most +-25 V in any state (WG p20 (1-8): above it the RSU is damaged).
    ALWG: 10 ns grid, at most 2,048 vectors per pattern and 512 sequences per channel, vector time 10 ns to
    10995.11627775 s, sequence count 1 to 1,099,511,627,776; about 4,000,000 stored values per channel; measure
    interval 10 ns to 1.34217728 s, average 0 or 10 ns to 0.020971512 s and at most the interval; range events need
    Fast IV current measurement, lie outside the averaging windows and, three or more in a row, more than 2 us apart.
    """

    module_type: Literal["WGFMU"] = "WGFMU"
    models: tuple[str, ...] = ("B1530A",)
    force_ranges: dict[str, tuple[float, float]] = Field(default_factory=lambda: {
        "3v": (-3.0, 3.0), "5v": (-5.0, 5.0), "-10v": (-10.0, 0.0), "10v": (0.0, 10.0), "auto": (-10.0, 10.0)})
    pg_force_ranges: frozenset[str] = frozenset({"auto", "3v", "5v"})
    pg_max_open_v: float = 5.0
    pg_output_ohm: float = 50.0
    max_abs_v: float = 10.0
    current_ranges: dict[str, float] = Field(default_factory=lambda: {
        "1ua": 1e-6, "10ua": 1e-5, "100ua": 1e-4, "1ma": 1e-3, "10ma": 1e-2})
    current_modes: frozenset[str] = frozenset({"fastiv", "dc"})
    min_pulse_width_s: dict[str, float] = Field(default_factory=lambda: {"pg": 1e-7, "fastiv": 3e-7})
    """Shortest pulse per operation mode (WG p16 (1-4) "Minimum pulse width": PG mode 100 ns, Fast IV mode 300 ns;
    the manual gives none for DC mode, which outputs DC). R-WG-02 blocks a nominal WGFMU pulse train (``width_s``:
    the flat top, or rise + top of a PUND ramp, so the check is conservative) below the channel's mode minimum,
    although the 10 ns vector grid would accept it."""
    smu_mode_max_v: float = 25.0
    """Largest |V| at the RSU's "From SMU" input and on its SMU path (WG p20 (1-8) CAUTION "Maximum input voltage to
    the From SMU terminal is +-25 V ... Or the RSU will be damaged"; WG p16 (1-4) "SMU mode"). It bounds the SMU
    cabled to that input whatever the RSU's state (R-RSU-01 at validation, ``OutputGuard`` per command)."""
    smu_mode_max_a: float = 0.1
    """Largest current on the RSU's SMU path (WG p16 (1-4) "Maximum current: 100 mA"); R-RSU-01 and the
    ``OutputGuard`` hold the SMU cabled to the From SMU input to it."""
    max_output_a: float = 0.1
    """Current assumed to return from one WGFMU channel without a pulse envelope (R-GNDU-01): the RSU path's 100 mA
    (SMU mode). TODO(cite): the Fast IV short-circuit current (a B1530A data-sheet value, not in the manual corpus;
    unsafe to measure)."""
    grid_s: float = WGFMU_GRID_S
    max_vectors: int = 2048
    max_sequences: int = 512
    max_points: int = 4_000_000
    vector_dt_s: tuple[float, float] = (1e-8, 10995.11627775)
    sequence_count: tuple[float, float] = (1.0, 1_099_511_627_776.0)
    interval_s: tuple[float, float] = (1e-8, 1.34217728)
    average_s: tuple[float, float] = (1e-8, 0.020971512)
    range_event_spacing_s: float = 2e-6
    sources: tuple[str, ...] = ("WG p16 (1-4)", "WG p20 (1-8)", "WG5 p24 (1-14)", "WG p125 (4-55)", "WG p128 (4-58)",
                                "WG p153 (4-83)")

    def range_bounds(self, mode: str, force_range: str) -> tuple[float, float]:
        """Output level bounds of a force range in a mode (PG: open-load -5..5 V at most)."""
        low, high = self.force_ranges[force_range]
        if mode == "pg":
            low, high = max(low, -self.pg_max_open_v), min(high, self.pg_max_open_v)
        return low, high

    def train_problems(self, train: PulseTrain) -> list[SpecProblem]:
        """Where a WGFMU pulse train leaves the ALWG limits (levels against the largest range; the channel's own
        range and mode are checked against the waveform program by R-WG-02)."""
        found: list[SpecProblem] = []
        if train.max_abs_set_v > self.max_abs_v:
            found.append(SpecProblem(f"level {train.max_abs_set_v:g} V exceeds the WGFMU's {self.max_abs_v:g} V",
                                     train.max_abs_set_v, self.max_abs_v))
        for name, value in (("width", train.width_s), ("period", train.period_s), ("delay", train.delay_s),
                            ("leading", train.lead_s), ("trailing", train.trail_s)):
            if value is None or (name == "delay" and value == 0):
                continue
            if value < self.grid_s or not on_grid(value, self.grid_s):
                found.append(SpecProblem(f"{name} {value:g} s is not a multiple of the 10 ns grid", value,
                                         self.grid_s))
        if train.count is not None and train.count > self.sequence_count[1]:
            found.append(SpecProblem(f"count {train.count} exceeds the sequence count limit", train.count,
                                     self.sequence_count[1]))
        if train.load_ohm is not None:
            found.append(SpecProblem("WGFMU pulses have no SER load setting", train.load_ohm, None))
        return found


class CmuSpec(StrictModel):
    """B1520A MFCMU (UG p73 (2-33) "MFCMU"): AC 1 kHz to 5 MHz, 10 to 250 mVrms; internal DC bias 0 to +-25 V (up to
    +-100 V only through an SMU and the SCUU, which is an SMU role)."""

    module_type: Literal["MFCMU"] = "MFCMU"
    models: tuple[str, ...] = ("B1520A",)
    f_hz: tuple[float, float] = (1e3, 5e6)
    ac_vrms: tuple[float, float] = (0.01, 0.25)
    max_dc_v: float = 25.0
    source: str = "UG p73 (2-33)"


class ScuuSpec(StrictModel):
    """SMU CMU unify unit (``SSP``; PG p520 (4-202) "SSP"). Switching an output from SMU to MFCMU sets the SMU to 0 V,
    100 V range, 20 mA compliance; back to SMU: 0 V, 20 V range, 100 uA compliance (ATV-27 confirmed by the manual
    text). Every ``SSP`` is therefore an output change and goes through ``OutputGuard.check_route``."""

    kind: Literal["scuu"] = "scuu"
    smu_types: frozenset[str] = frozenset({"HRSMU", "MPSMU"})
    max_dc_v_with_smu: float = 100.0
    ssp_resets_smu: bool = True
    source: str = "PG p520 (4-202)"


class AsuSpec(StrictModel):
    """Atto sense and switch unit (``SAP``; PG p505 (4-187) "SAP"): the current ranges flagged ``requires_asu`` in
    ``MODULE_SPECS`` (1 pA on the HRSMU, 1 to 100 pA on the MPSMU B1511B) exist only on an SMU with an ASU
    (R-ASU-01)."""

    kind: Literal["asu"] = "asu"
    smu_types: frozenset[str] = frozenset({"HRSMU", "MPSMU"})
    lowest_range_a: float = 1e-12
    source: str = "PG p505 (4-187)"


SPGU_SPEC: Final = SpguSpec()
WGFMU_SPEC: Final = WgfmuSpec()
CMU_SPEC: Final = CmuSpec()
SCUU_SPEC: Final = ScuuSpec()
ASU_SPEC: Final = AsuSpec()

SPEC_SYMBOL: Final = "b1500_test_agent.driver.modules"
"""Module path used in rule finding sources (``code:b1500_test_agent.driver.modules.SPGU_SPEC ...``)."""
