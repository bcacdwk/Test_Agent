"""SMU current measurement ranging shared by the SMU kinds (blueprint v2 1.2 "ranging RI/RV", WP7.1).

Three ways a recipe role chooses its current measurement range (role settings, ``$param`` references allowed):

- ``irange`` (full scale in A): limited auto ranging that never goes below that range (``RI ch,+code``); the range
  must exist on the role's SMU (else ``CompileError``) and a range only an ASU has (1 pA on an HRSMU, 1-100 pA on a
  B1511B MPSMU) needs a declared, present ASU on that channel (rule R-ASU-01 blocks the plan otherwise);
- ``asu_1pa`` (bool): the same with the 1 pA range (``RI ch,8``), the ASU option of a low-current recipe
  (``rules.builtin.measure_range_a``);
- ``ranges`` (a ``float_list`` of full scales, kind ``smu_spot`` only): a range survey such as the zero check, one
  group of measurements per entry on a fixed range (``RI ch,-code``): the smallest range of the role's SMU at or above
  the entry; ASU-only ranges count only on an SMU with a declared, present ASU (so R-ASU-01 holds by construction).
  The range used is recorded per row in the ``<role>_range`` column, so an MPSMU asked for 10 pA (its smallest range
  without an ASU is 1 nA) shows ``1nA`` there.

Without any of them the SMU auto-ranges (the instrument default, no ``RI`` sent). Range codes and full scales: PG
Table 4-3 (PDF 337), ``RI`` PDF 501 (``driver/modules.py``). Labels (``range_label``) are the data-contract tokens of
the ``<role>_range`` column: ``10pA`` for a fixed range, ``1pA+`` for limited auto from that range.
"""

from __future__ import annotations

import math

from b1500_test_agent.catalog.schema import CompileError, setting_value
from b1500_test_agent.driver.modules import RangeSpec, module_spec
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import BoundChannel
from b1500_test_agent.models.recipe import RoleSpec
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import measure_range_a

SURVEY_SETTING = "ranges"
"""Role-settings key of a range survey (``float_list`` of full scales in A; kind ``smu_spot``)."""

_UNITS = ((1e-12, "pA"), (1e-9, "nA"), (1e-6, "uA"), (1e-3, "mA"), (1.0, "A"))


class RangeSetting(StrictModel):
    """One ``RI`` setting of a measured role: channel, FLEX code (``+c`` limited auto, ``-c`` fixed) and label."""

    channel: Channel
    role: str
    code: int
    label: str


def range_label(full_scale: float, *, fixed: bool) -> str:
    """``10pA``, ``1nA``, ``100mA`` (fixed) or ``1pA+`` (limited auto from that range)."""
    for scale, unit in reversed(_UNITS):
        if full_scale >= scale * (1 - 1e-9):
            value = round(full_scale / scale, 6)
            text = f"{value:g}{unit}"
            return text if fixed else text + "+"
    raise ValueError(f"{full_scale!r} is not a current range")


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise CompileError(f"{what} must be a positive full scale in A, got {value!r}")
    return float(value)


def _spec_ranges(bound: BoundChannel, name: str) -> tuple[str, tuple[RangeSpec, ...]]:
    try:
        spec = module_spec(bound.module_model or bound.module_type or "")
    except KeyError:
        raise CompileError(f"role {name}: channel {bound.channel} is not an SMU, so it has no current ranges") \
            from None
    return spec.module_type, tuple(r for r in spec.i_ranges if not r.pulse_only)


def limited_range(name: str, role: RoleSpec, params: dict[str, Quantity], bound: BoundChannel) -> RangeSetting | None:
    """The ``RI ch,+code`` of a role with ``irange`` or ``asu_1pa`` (``None`` when it auto-ranges)."""
    requested = measure_range_a(role, params)
    if requested is None or bound.channel is None:
        return None
    full_scale = _number(requested, f"{name} current range")
    module, ranges = _spec_ranges(bound, name)
    found = next((r for r in ranges if math.isclose(r.full_scale, full_scale, rel_tol=1e-9)), None)
    if found is None:
        available = ", ".join(range_label(r.full_scale, fixed=True) for r in ranges)
        raise CompileError(f"role {name}: a {module} has no {full_scale:g} A current range ({available})")
    return RangeSetting(channel=bound.channel, role=name, code=found.code,
                        label=range_label(found.full_scale, fixed=False))


def has_present_asu(station: StationProfile, channel: int) -> bool:
    """True when the station declares an ASU on SMU ``channel`` and records it ``present: true``."""
    return any(s.kind == "asu" and s.present is True and any(p.index == channel for p in s.ports.values())
               for s in station.switches)


def survey_ranges(name: str, role: RoleSpec, params: dict[str, Quantity], bound: BoundChannel,
                  station: StationProfile) -> list[RangeSetting] | None:
    """The fixed ``RI ch,-code`` per entry of a role's ``ranges`` survey (``None`` without one): the smallest range
    of its SMU at or above each entry, ASU ranges only with a declared, present ASU."""
    if SURVEY_SETTING not in role.settings:
        return None
    listed = setting_value(role, SURVEY_SETTING, params)
    if not isinstance(listed, list) or not listed:
        raise CompileError(f"{name}.{SURVEY_SETTING} must be a non-empty list of full scales in A, got {listed!r}")
    if bound.channel is None:
        return None
    module, ranges = _spec_ranges(bound, name)
    usable = sorted((r for r in ranges if not r.requires_asu or has_present_asu(station, bound.channel)),
                    key=lambda r: r.full_scale)
    found: list[RangeSetting] = []
    for index, value in enumerate(listed):
        full_scale = _number(value, f"{name}.{SURVEY_SETTING}[{index}]")
        match = next((r for r in usable if r.full_scale >= full_scale * (1 - 1e-9)), None)
        if match is None:
            raise CompileError(f"role {name}: a {module} has no current range of {full_scale:g} A or above")
        found.append(RangeSetting(channel=bound.channel, role=name, code=-match.code,
                                  label=range_label(match.full_scale, fixed=True)))
    return found
