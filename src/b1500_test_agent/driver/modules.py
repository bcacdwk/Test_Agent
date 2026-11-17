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

Only DC limits are modelled (v1 has no pulsed kinds). HCSMU (B1512A) and HVSMU (B1513x) are B1505A-family modules;
their limits come from the Programming Guide tables because the B1500A User's Guide does not describe them.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Ranging
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
"""Spec per module type (and the mainframe GNDU). MFCMU, HVSPGU and WGFMU have no entry: they are not DC sources in
v1, so a rule that needs their limits must refuse."""


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
