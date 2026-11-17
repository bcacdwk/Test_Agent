"""Data-quality classification of a run (blueprint 2.8 ``assess_quality``; rules R-QUAL-*).

Status letters decide trust (``TrustPolicy``): ``N`` ok; ``C``/``T`` limited (excluded from fits); ``V X F D G S U``
and unknown letters untrusted (extraction refused unless forced). The verdict is the worst row level.

Noise: ``noise_sigma`` is a robust white-noise estimate from second differences in acquisition order,
``sigma = 1.4826 * median(|y[i+1] - 2 y[i] + y[i-1]|) / sqrt(6)`` (a smooth curve has near-zero second differences,
white noise of standard deviation sigma gives second differences of standard deviation sqrt(6) sigma). The
signal-to-noise ratio is the value range over that sigma; below ``MIN_SNR`` a column is at its noise floor. With
fewer than ``MIN_NOISE_POINTS`` points the estimate is not made (curvature would dominate it).
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from pydantic import ConfigDict, validate_call

from b1500_test_agent.analysis.dataset import TRUST_LEVELS, RunData, status_column
from b1500_test_agent.models.analysis import QualityReport, TrustLevel, TrustPolicy

MIN_SNR = 10.0
"""Signal range below ten times the noise estimate counts as noise-dominated (pure white noise gives about 5)."""

MIN_NOISE_POINTS = 7
"""Fewest points (five second differences) for a noise estimate."""

_MAD_TO_SIGMA = 1.4826
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


def second_differences(values: np.ndarray) -> np.ndarray:
    """Second differences of the finite values of ``values`` in their given order."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return np.diff(finite, 2) if finite.size >= 3 else np.empty(0)


def noise_sigma(values: np.ndarray, *, second_diffs: np.ndarray | None = None) -> float | None:
    """Robust white-noise standard deviation of a curve sampled in order (``None`` with fewer than
    ``MIN_NOISE_POINTS`` points). ``second_diffs`` lets a caller pool second differences of several segments."""
    d2 = second_differences(values) if second_diffs is None else second_diffs
    if d2.size < MIN_NOISE_POINTS - 2:
        return None
    return float(_MAD_TO_SIGMA * np.median(np.abs(d2)) / np.sqrt(6.0))


def signal_to_noise(values: np.ndarray, sigma: float | None) -> float | None:
    """Value range over ``sigma``; ``None`` when ``sigma`` is unknown or zero (noise-free)."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if sigma is None or sigma <= 0 or finite.size == 0:
        return None
    return float((finite.max() - finite.min()) / sigma)


def column_noise(
    d: RunData, column: str, policy: TrustPolicy | None = None
) -> tuple[float | None, float | None]:
    """``(sigma, snr)`` of a measured column over its ``ok`` points, second differences taken within each segment
    in acquisition order."""
    policy = policy if policy is not None else TrustPolicy()
    pooled: list[np.ndarray] = []
    kept: list[np.ndarray] = []
    for segment in d.segments():
        rows = d.rows(segment)
        ok = rows[status_column(column)].map(lambda s: policy.classify(str(s)) == "ok").to_numpy(dtype=bool)
        values = rows[column].to_numpy(dtype=float)[ok]
        pooled.append(second_differences(values))
        kept.append(values)
    d2 = np.concatenate(pooled) if pooled else np.empty(0)
    sigma = noise_sigma(np.empty(0), second_diffs=d2)
    values = np.concatenate(kept) if kept else np.empty(0)
    return sigma, signal_to_noise(values, sigma)


_MEANING = {"limited": "limited, excluded from fits", "untrusted": "untrusted, extraction refused unless forced"}


@validate_call(config=_CALL_CONFIG)
def assess_quality(d: RunData, criteria: TrustPolicy | None = None) -> QualityReport:
    """Classify every point of ``d`` under ``criteria`` (a recipe's ``QualityCriteria`` or any ``TrustPolicy``;
    default ``TrustPolicy()``, the recipe default classes): status counts overall and per measured column, row
    trust fractions, noise and SNR per measured column, verdict = worst row level (no points → ``untrusted``)."""
    policy = criteria if criteria is not None else TrustPolicy()
    table = d.table
    measured = d.measured_columns
    counts: Counter[str] = Counter()
    per_column: dict[str, dict[str, int]] = {}
    warnings: list[str] = []
    for column in measured:
        column_counts = {str(k): int(v) for k, v in sorted(table[status_column(column)].value_counts().items())}
        per_column[column] = column_counts
        counts.update(column_counts)
        for letter, count in column_counts.items():
            level = policy.classify(letter)
            if level != "ok":
                warnings.append(f"{column}: {count} point(s) with status {letter} ({_MEANING[level]}).")

    levels = d.trust_levels(policy)
    points = len(table)
    fractions: dict[TrustLevel, float] = {
        level: (float((levels == level).sum()) / points if points else 0.0) for level in TRUST_LEVELS
    }
    if points == 0:
        verdict: TrustLevel = "untrusted"
        warnings.append("The run table has no points.")
    elif fractions["untrusted"] > 0:
        verdict = "untrusted"
    elif fractions["limited"] > 0:
        verdict = "limited"
    else:
        verdict = "ok"

    noise: dict[str, float] = {}
    snr: dict[str, float] = {}
    for column in measured:
        sigma, ratio = column_noise(d, column, policy)
        if sigma is not None:
            noise[column] = sigma
        if ratio is not None:
            snr[column] = ratio
            if ratio < MIN_SNR:
                warnings.append(
                    f"{column}: signal range is only {ratio:.1f}x its noise estimate (< {MIN_SNR:g}): at the noise "
                    "floor (normal for leakage or bias currents, a red flag for the response being analysed)."
                )
    return QualityReport(
        counts=dict(sorted(counts.items())),
        fractions=fractions,
        noise=noise,
        verdict=verdict,
        warnings=warnings,
        points=points,
        columns=per_column,
        snr=snr,
    )
