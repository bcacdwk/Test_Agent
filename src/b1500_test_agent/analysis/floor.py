"""Zero check: offset and noise floor of every SMU per current range (blueprint v2 3.1 ``system.zero_check``, WP7.1;
card ``zero-check``).

Definition (the source of knowledge file ``02-b1500-instrument.md`` section "Zero check floor"; change both together):
for every measured current column ``<role>_I`` of a run whose SMUs sat at 0 V with open terminals, the trusted
readings are grouped by the range label of the role (``<role>_range``: ``10pA``, ``1nA`` ...; one group ``auto``
without it). Per group the **offset** is their mean and the **floor** their sample standard deviation (n - 1), both in
A. The method returns one result per role, ``<role>_floor`` = the floor on the role's lowest range (the smallest full
scale of its groups); its ``fit`` lists the floor of every group under its label (``10pA``, ``1nA`` ...), ``offset`` =
the offset on the lowest range and ``max_abs_offset`` = the largest |offset| over the groups; ``points_used`` counts
the trusted readings over all groups. Floors and offsets are statistical estimates (about 7 % uncertainty with 100
readings), so they are rounded to ``DIGITS`` significant digits; the compact result keeps a five-SMU zero check inside
the 2k-token response of ``run_plan`` (blueprint 5.1). With option ``max_floor_a`` and/or ``max_offset_a`` the result
is classified ``pass`` (lowest-range floor at most ``max_floor_a`` and the lowest-range |offset| at most
``max_offset_a``) or ``fail``.

Trust: as every method (``mosfet.py`` docstring): untrusted rows refuse the call unless ``force``. Limited rows
(``C``/``T``) are excluded and warned about: a compliance at 0 V means the terminal is not open (something is
connected or leaking). A group needs ``MIN_POINTS`` trusted readings, else that role ``failed``.
"""

from __future__ import annotations

import math
from typing import Annotated

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, excluded_counts, policy_params, sig, trust_policy
from b1500_test_agent.analysis.dataset import RANGE_SUFFIX, RunData, parse_value_column, row_reasons, status_column
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy

MIN_POINTS = 3
"""Fewest trusted readings per range group for an offset and a floor."""

DIGITS = 3
"""Significant digits of the reported floors and offsets."""

AUTO_LABEL = "auto"
"""Group label of a role without a ``<role>_range`` column (auto ranging)."""

_UNIT_SCALE = {"pA": 1e-12, "nA": 1e-9, "uA": 1e-6, "mA": 1e-3, "A": 1.0}
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Amps = Annotated[float, Field(gt=0, allow_inf_nan=False)]


def label_full_scale(label: str) -> float:
    """Full scale (A) of a range label (``10pA`` -> 1e-11, ``1pA+`` -> 1e-12); ``inf`` for anything else."""
    text = label.rstrip("+")
    for unit in sorted(_UNIT_SCALE, key=len, reverse=True):
        if text.endswith(unit):
            try:
                return float(text[: -len(unit)]) * _UNIT_SCALE[unit]
            except ValueError:
                return math.inf
    return math.inf


@validate_call(config=_CALL_CONFIG)
def zero_floor(
    d: RunData,
    *,
    max_floor_a: Amps | None = None,
    max_offset_a: Amps | None = None,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Offset and noise floor per measured current and range (module docstring): ``<role>_floor`` per role, every
    range's floor and offset in ``fit``."""
    policy = trust_policy(criteria)
    currents = [c for c in d.measured_columns if c.endswith("_I")]
    if not currents:
        raise InvalidInputError(f"zero_floor: run {d.run_id} has no measured current column.")
    out = Results("zero_floor", {"max_floor_a": max_floor_a, "max_offset_a": max_offset_a, "force": force,
                                 "trust_policy": policy_params(policy)})
    table = d.table
    results: list[ExtractionResult] = []
    for column in currents:
        role = parse_value_column(column)[0]  # type: ignore[index]
        floor_q = f"{role}_floor"
        reasons = row_reasons(table[["step", column, status_column(column)]], policy)
        letters = table[status_column(column)].astype(str)
        levels = letters.map(policy.classify)
        values = table[column].to_numpy(dtype=float)
        ok = (levels == "ok").to_numpy() & np.isfinite(values)
        excluded = excluded_counts(reasons.where(ok | (reasons != "N"), "missing"))
        untrusted = int((levels == "untrusted").sum())
        warnings: list[str] = []
        if untrusted and not force:
            results.append(out.refused(floor_q, "A", [f"{untrusted} untrusted reading(s) of {column}"],
                                       excluded=excluded))
            continue
        if untrusted:
            warnings.append(f"Forced on untrusted data: {untrusted} untrusted reading(s) of {column} skipped.")
        limited = int((levels == "limited").sum())
        if limited:
            warnings.append(f"{limited} reading(s) of {column} at compliance (C/T) at 0 V: the terminal is not open "
                            "(something connected or leaking); they are excluded.")
        range_column = f"{role}{RANGE_SUFFIX}"
        labels = (table[range_column].astype(str).to_numpy() if range_column in table.columns
                  else np.full(len(table), AUTO_LABEL, dtype=object))
        groups: dict[str, np.ndarray] = {}
        for label in dict.fromkeys(labels):
            groups[str(label)] = values[ok & (labels == label)]
        short = sorted(label for label, data in groups.items() if data.size < MIN_POINTS)
        if short:
            results.append(out.failed(floor_q, "A", f"{column}: fewer than {MIN_POINTS} trusted readings on range(s) "
                                      f"{', '.join(short)}; raise samples.", excluded=excluded))
            continue
        floors = {label: sig(float(np.std(data, ddof=1)), DIGITS) for label, data in groups.items()}
        offsets = {label: sig(float(np.mean(data)), DIGITS) for label, data in groups.items()}
        lowest = min(groups, key=label_full_scale)
        floor, offset = floors[lowest], offsets[lowest]
        fit = {**floors, "offset": offset, "max_abs_offset": max(abs(v) for v in offsets.values())}
        used = int(sum(data.size for data in groups.values()))
        verdict = None
        if max_floor_a is not None or max_offset_a is not None:
            passed = (max_floor_a is None or floor <= max_floor_a) and (max_offset_a is None
                                                                        or abs(offset) <= max_offset_a)
            verdict = "pass" if passed else "fail"
        sizes = sorted({int(data.size) for data in groups.values()})
        counts = "/".join(map(str, sizes))
        notes = [*warnings, f"Lowest range {lowest}; {len(groups)} range group(s) of {counts} readings."]
        results.append(out.ok(floor_q, floor, "A", excluded=excluded, points_used=used, fit=fit, warnings=notes,
                              classification=verdict))
    return results
