"""Shared machinery of the extraction methods (blueprint 2.8): the analysed rows with their per-row trust, the
refusal gate, default column choice, interpolation, the noise-floor test and result assembly.

The rules every method follows are written once, in the ``mosfet.py`` module docstring ("Trust and refusal"); this
module implements them so that every method applies them identically.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from b1500_test_agent.analysis.dataset import (
    RunData,
    Segment,
    parse_value_column,
    row_reasons,
    status_column,
    trust_levels,
)
from b1500_test_agent.analysis.quality import MIN_SNR, noise_sigma, signal_to_noise
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import (
    Bound,
    ExtractionOutcome,
    ExtractionResult,
    MethodRecord,
    QuantityRange,
    TrustPolicy,
    Unit,
)
from b1500_test_agent.models.recipe import QualityCriteria

METHOD_VERSION = "1"
"""Version of the M2 method implementations (recorded in every ``MethodRecord``)."""

REFUSAL_HINT = ("Re-check the data (quality report); force=True extracts from the trusted points anyway and flags "
                "the result.")

COMPLIANCE_LETTERS = frozenset("CT")
"""Status letters of a compliance event (on the channel itself or on another channel of the step)."""

ABORT_LETTER = "V"
"""Status of the dummy data (``199.999E+99``) that follows an automatic abort (``WM 2``)."""

FLOOR_SIGMAS = 3.0
"""A current at the noise floor is reported as an upper bound of this many noise standard deviations."""

LOG_ROUGHNESS = 0.3
"""Median |second difference| of log10|I| (decades) above which a local stretch of a current curve is noise."""

FLOOR_HALF_WINDOW = 4
"""Neighbours on each side of a point used by the local noise-floor test (window shifted inward at the ends)."""

SIGNIFICANT_DIGITS = 7
"""Derived numbers of the M2 methods are rounded to this many significant digits (keeps results compact)."""

_TINY = 1e-300


def sig(value: float, digits: int = SIGNIFICANT_DIGITS) -> float:
    """``value`` rounded to ``digits`` significant digits."""
    return float(f"{value:.{digits}g}")


def trust_policy(criteria: TrustPolicy | None) -> TrustPolicy:
    """The caller's trust policy (the recipe's ``QualityCriteria``) or the default ``QualityCriteria()``."""
    return criteria if criteria is not None else QualityCriteria()


def max_limited_fraction(policy: TrustPolicy) -> float:
    """``max_limited_fraction_in_fit`` of a ``QualityCriteria`` (the default for a plain ``TrustPolicy``)."""
    return float(getattr(policy, "max_limited_fraction_in_fit", QualityCriteria().max_limited_fraction_in_fit))


def excluded_counts(reasons: pd.Series) -> dict[str, int]:
    """Counts of the non-``N`` reasons, sorted by reason."""
    counts = reasons[reasons != "N"].value_counts()
    return {str(k): int(v) for k, v in sorted(counts.items())}


def finite(values: dict[str, float | None]) -> dict[str, float]:
    """Rounds (``sig``) and drops non-finite entries so that a ``fit`` dictionary always validates."""
    return {k: sig(float(v)) for k, v in values.items() if v is not None and np.isfinite(v)}


# -- columns ---------------------------------------------------------------------------------------------------------


def require_iv(d: RunData, x: str, y: str, method: str) -> None:
    """``x`` must be a voltage and ``y`` a current column of the run (``InvalidInputError`` otherwise)."""
    if d.unit(x) != "V" or d.unit(y) != "A":
        raise InvalidInputError(f"{method} needs a voltage x and a current y; got {x}, {y}.")


def varying_sources(rows: pd.DataFrame, d: RunData) -> list[str]:
    """Source voltage columns that take more than one value in ``rows`` (table order)."""
    return [c for c in d.source_columns if c.endswith("_V") and rows[c].nunique(dropna=True) > 1]


def sweep_columns(d: RunData, x: str | None, y: str | None, method: str) -> tuple[str, str]:
    """Default columns of a single-terminal I-V: ``x`` = the source voltage column with the most distinct values
    (the swept terminal), ``y`` = the measured current of the same role, else the only measured current."""
    if x is None:
        candidates = [c for c in d.source_columns if c.endswith("_V")]
        if not candidates:
            raise InvalidInputError(f"{method}: run {d.run_id} has no source voltage column; pass x=<column>.")
        x = max(candidates, key=lambda c: int(d.table[c].nunique()))
    if y is None:
        parsed = parse_value_column(x)
        same = f"{parsed[0]}_I" if parsed else ""
        currents = [c for c in d.measured_columns if c.endswith("_I")]
        if same in currents:
            y = same
        elif len(currents) == 1:
            y = currents[0]
        else:
            raise InvalidInputError(f"{method}: cannot choose the current column of run {d.run_id} among "
                                    f"{currents}; pass y=<column>.")
    require_iv(d, x, y, method)
    return x, y


# -- analysed rows ---------------------------------------------------------------------------------------------------


@dataclass
class Rows:
    """The analysed rows of ``x``/``y`` (one segment or one curve) with per-row trust.

    ``reasons`` holds ``N`` for usable rows, the deciding status letter of limited and untrusted rows, ``missing``
    for rows without a finite x or y, ``aborted`` for the dummy rows after an automatic abort (only when built with
    ``abort_aware=True``) and, once a method calls ``use``, ``outside_window`` for usable rows it did not use.
    ``ok`` marks the usable rows (trusted and finite).
    """

    rows: pd.DataFrame
    x: str
    y: str
    levels: pd.Series
    reasons: pd.Series
    ok: np.ndarray
    compliance_at: int | None = None
    """Position (in ``rows``) of the first row with a compliance letter on any measured column, if any."""

    @property
    def xs(self) -> np.ndarray:
        """``x`` of the usable rows, acquisition order."""
        return self.rows[self.x].to_numpy(dtype=float)[self.ok]

    @property
    def ys(self) -> np.ndarray:
        """``y`` of the usable rows, acquisition order."""
        return self.rows[self.y].to_numpy(dtype=float)[self.ok]

    @property
    def size(self) -> int:
        return int(self.ok.sum())

    def untrusted(self) -> pd.Series:
        """Reasons of the untrusted rows (``aborted`` rows are not untrusted: they carry no data)."""
        mask = (self.levels == "untrusted").to_numpy() & (self.reasons != "aborted").to_numpy()
        return self.reasons[mask]

    def problems(self, where: str, *, noise: bool = True) -> list[str]:
        """Why an extraction from these rows must be refused: untrusted rows, or (``noise``) a noise-dominated
        ``y`` (signal range below ``MIN_SNR`` times the noise estimate)."""
        out: list[str] = []
        untrusted = self.untrusted()
        if len(untrusted):
            letters = ", ".join(f"{k}: {v}" for k, v in excluded_counts(untrusted).items())
            out.append(f"{len(untrusted)} untrusted point(s) in {where} ({letters})")
        if noise:
            ratio = self.snr()
            if ratio is not None and ratio < MIN_SNR:
                out.append(f"{self.y} is noise-dominated in {where} (range {ratio:.1f}x the noise estimate, "
                           f"< {MIN_SNR:g})")
        return out

    def snr(self) -> float | None:
        """Signal range of the usable ``y`` over its noise estimate (``None`` when not estimable)."""
        ys = self.ys
        return signal_to_noise(ys, noise_sigma(ys))

    def use(self, positions: Sequence[int] | np.ndarray) -> None:
        """Mark the usable rows that are not at ``positions`` (indices into ``xs``) as ``outside_window``."""
        usable = self.rows.index[self.ok]
        used = usable[np.asarray(positions, dtype=int)] if len(positions) else usable[:0]
        mask = self.ok & ~self.rows.index.isin(used)
        self.reasons = self.reasons.copy()
        self.reasons[mask] = "outside_window"

    def excluded(self) -> dict[str, int]:
        return excluded_counts(self.reasons)

    def limited_warning(self, low: float, high: float, max_fraction: float) -> str | None:
        """Warning when more rows inside ``[low, high]`` of ``x`` are limited than ``max_fraction`` allows."""
        inside = self.rows[self.x].between(low, high).to_numpy()
        total = int(inside.sum())
        limited = int(((self.levels == "limited").to_numpy() & inside).sum())
        if total and limited / total > max_fraction:
            return (f"{limited} of {total} points inside the window are limited (C/T), above "
                    f"max_limited_fraction_in_fit {max_fraction:g}.")
        return None


def analysed_rows(d: RunData, x: str, y: str, policy: TrustPolicy, *, segment: Segment | None = "fwd",
                  rows: pd.DataFrame | None = None, abort_aware: bool = False) -> Rows:
    """The rows of ``segment`` (or the given ``rows``) with trust under ``policy``.

    ``abort_aware``: rows after the first compliance row whose measured values are all ``V`` are the dummy data of
    the automatic abort; they get reason ``aborted`` and do not count as untrusted (classifying methods only).
    """
    rows = d.rows(segment) if rows is None else rows
    levels = trust_levels(rows, policy)
    reasons = row_reasons(rows, policy)
    xv = rows[x].to_numpy(dtype=float)
    yv = rows[y].to_numpy(dtype=float)
    finite_xy = np.isfinite(xv) & np.isfinite(yv)
    reasons = reasons.where(~((reasons == "N").to_numpy() & ~finite_xy), "missing")
    measured = d.measured_columns
    letters = rows[[status_column(c) for c in measured]].astype(str) if measured else pd.DataFrame(index=rows.index)
    compliance = letters.isin(COMPLIANCE_LETTERS).any(axis=1).to_numpy() if measured else np.zeros(len(rows), bool)
    first = int(np.argmax(compliance)) if compliance.any() else None
    if abort_aware and first is not None:
        dummy = (letters == ABORT_LETTER).all(axis=1).to_numpy()
        after = np.arange(len(rows)) > first
        reasons = reasons.where(~(dummy & after), "aborted")
    ok = (levels == "ok").to_numpy() & finite_xy
    return Rows(rows=rows, x=x, y=y, levels=levels, reasons=reasons, ok=ok, compliance_at=first)


def first_compliance(r: Rows) -> tuple[float, float] | None:
    """``(x, y)`` of the first row whose ``y`` value itself reports compliance (``C``), if any."""
    status = r.rows[status_column(r.y)].astype(str).to_numpy()
    hits = np.flatnonzero(status == "C")
    if not hits.size:
        return None
    row = r.rows.iloc[int(hits[0])]
    return float(row[r.x]), float(row[r.y])


# -- numerics --------------------------------------------------------------------------------------------------------


def strictly_monotonic(x: np.ndarray) -> bool:
    steps = np.diff(x)
    return bool(np.all(steps > 0) or np.all(steps < 0))


def increasing_with_x(xs: np.ndarray, ys: np.ndarray, ends: int = 3) -> bool:
    """True when |y| grows with x (an n-type transfer curve): median |y| at the high-x end above the low-x end."""
    order = np.argsort(xs)
    a = np.abs(ys[order])
    k = max(1, min(ends, a.size // 2))
    return bool(np.median(a[-k:]) >= np.median(a[:k]))


def interpolate(xs: np.ndarray, ys: np.ndarray, v: float, tol: float = 1e-9) -> tuple[float, int] | None:
    """``y`` at ``x = v`` by linear interpolation between the bracketing points of the x-sorted data, and the
    position (in the sorted data) of the point nearest to ``v``; ``None`` when ``v`` lies outside the data."""
    order = np.argsort(xs, kind="stable")
    sx, sy = xs[order], ys[order]
    if sx.size == 0 or v < sx[0] - tol or v > sx[-1] + tol:
        return None
    nearest = int(np.argmin(np.abs(sx - v)))
    if abs(sx[nearest] - v) <= tol:
        return float(sy[nearest]), nearest
    return float(np.interp(v, sx, sy)), nearest


def floor_limit(xs: np.ndarray, ys: np.ndarray, position: int) -> float | None:
    """Detection limit (``FLOOR_SIGMAS`` x the local noise) when the current around ``position`` of the x-sorted data
    is at the noise floor, else ``None``. A stretch is at the floor when log10|I| is rough there (median |second
    difference| above ``LOG_ROUGHNESS`` decades): a real current, even an exponential one, is smooth in log10|I|."""
    order = np.argsort(xs, kind="stable")
    sy = ys[order]
    width = min(2 * FLOOR_HALF_WINDOW + 1, sy.size)
    lo = min(max(0, position - FLOOR_HALF_WINDOW), sy.size - width)
    window = sy[lo:lo + width]
    if window.size < 5:
        return None
    logs = np.log10(np.maximum(np.abs(window), _TINY))
    if float(np.median(np.abs(np.diff(logs, 2)))) < LOG_ROUGHNESS:
        return None
    sigma = float(1.4826 * np.median(np.abs(np.diff(window, 2))) / np.sqrt(6.0))
    return FLOOR_SIGMAS * sigma if sigma > 0 else None


def line_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least-squares ``y = intercept + slope x``: ``(slope, intercept, r2)``."""
    slope, intercept = (float(c) for c in np.polyfit(x, y, 1))
    residual = y - (intercept + slope * x)
    spread = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / spread if spread > 0 else 1.0
    return slope, intercept, r2


def window_of(x: np.ndarray, unit: Unit) -> QuantityRange | None:
    """The ``[min, max]`` window of ``x`` (``None`` for a single value), rounded with ``sig``."""
    raw_low, raw_high = float(np.min(x)), float(np.max(x))
    if not raw_low < raw_high:
        return None
    low, high = sig(raw_low), sig(raw_high)
    return QuantityRange(low=low, high=high, unit=unit) if low < high else QuantityRange(low=raw_low, high=raw_high,
                                                                                         unit=unit)


# -- results ---------------------------------------------------------------------------------------------------------


@dataclass
class Results:
    """Builds the ``ExtractionResult``s of one method call (shared record, warnings and the forced flag)."""

    method: str
    params: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    forced: bool = False

    @property
    def record(self) -> MethodRecord:
        return MethodRecord(name=self.method, version=METHOD_VERSION, params=self.params)

    def flag(self, problems: list[str]) -> None:
        """Record that the call proceeds despite ``problems`` (``force=True``)."""
        if problems:
            self.warnings.append("Forced on untrusted data: " + "; ".join(problems) + ".")
            self.forced = True

    def ok(self, quantity: str, value: float, unit: Unit, *, excluded: dict[str, int], points_used: int,
           window: QuantityRange | None = None, fit: dict[str, float] | None = None,
           warnings: Iterable[str] = (), bound: Bound = "exact", classification: str | None = None
           ) -> ExtractionResult:
        return ExtractionResult(
            method=self.method, quantity=quantity, value=sig(float(value)), unit=unit, method_record=self.record,
            window=window, points_used=points_used, points_excluded=excluded, fit=finite(dict(fit or {})),
            warnings=[*self.warnings, *warnings], forced_on_untrusted=self.forced, bound=bound,
            classification=classification,
        )

    def not_ok(self, quantity: str, unit: Unit, outcome: ExtractionOutcome, error: str, *, excluded: dict[str, int],
               fit: dict[str, float] | None = None) -> ExtractionResult:
        return ExtractionResult(
            method=self.method, quantity=quantity, value=None, unit=unit, method_record=self.record, window=None,
            points_used=0, points_excluded=excluded, fit=finite(dict(fit or {})), warnings=list(self.warnings),
            forced_on_untrusted=self.forced, outcome=outcome, error=error,
        )

    def refused(self, quantity: str, unit: Unit, problems: list[str], *, excluded: dict[str, int],
                fit: dict[str, float] | None = None) -> ExtractionResult:
        return self.not_ok(quantity, unit, "refused", "Refused: " + "; ".join(problems) + ". " + REFUSAL_HINT,
                           excluded=excluded, fit=fit)

    def failed(self, quantity: str, unit: Unit, error: str, *, excluded: dict[str, int],
               fit: dict[str, float] | None = None) -> ExtractionResult:
        return self.not_ok(quantity, unit, "failed", error, excluded=excluded, fit=fit)


def policy_params(policy: TrustPolicy) -> dict[str, Any]:
    """The trust policy as recorded in ``MethodRecord.params``."""
    return policy.model_dump()
