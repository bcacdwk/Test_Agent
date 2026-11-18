"""Small numpy fits used by the v2 device-model tests (blueprint 4.2 fidelity targets, WP5.9).

The tests extract every checked quantity from model *output* (currents, capacitances, sampled series) with these
textbook methods; ``analysis/`` is not imported (its methods arrive with the module WPs).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

Q_E = 1.602176634e-19
EPS0_F_CM = 8.8541878128e-14
UT_300 = 8.617333262e-5 * 300.0


def linfit(x: Sequence[float] | np.ndarray, y: Sequence[float] | np.ndarray) -> tuple[float, float]:
    """Least-squares slope and intercept."""
    slope, intercept = np.polyfit(np.asarray(x, dtype=float), np.asarray(y, dtype=float), 1)
    return float(slope), float(intercept)


def crossing(x: np.ndarray, y: np.ndarray, level: float) -> float:
    """First ``x`` where ``y`` crosses ``level`` (linear interpolation)."""
    above = y >= level
    idx = np.nonzero(above[1:] != above[:-1])[0]
    if idx.size == 0:
        raise AssertionError(f"no crossing of {level}")
    i = int(idx[0])
    return float(x[i] + (level - y[i]) * (x[i + 1] - x[i]) / (y[i + 1] - y[i]))


def bisect_root(fn: Callable[[float], float], lo: float, hi: float, tol: float = 1e-9) -> float:
    """Root of an increasing ``fn`` on ``[lo, hi]``."""
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if fn(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def welch_psd(x: np.ndarray, dt: float, segment: int) -> tuple[np.ndarray, np.ndarray]:
    """One-sided Welch PSD (Hann window, 50 % overlap): frequencies (Hz) and PSD (units²/Hz)."""
    window = np.hanning(segment)
    scale = 2.0 * dt / np.sum(window * window)
    step = segment // 2
    spectra = []
    for start in range(0, len(x) - segment + 1, step):
        chunk = x[start:start + segment]
        spectra.append(np.abs(np.fft.rfft((chunk - chunk.mean()) * window)) ** 2 * scale)
    return np.fft.rfftfreq(segment, dt), np.mean(spectra, axis=0)


def dwell_times(levels: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
    """Durations (s) of the high (``True``) and low runs of a two-level series, first and last runs dropped."""
    change = np.nonzero(levels[1:] != levels[:-1])[0] + 1
    bounds = np.concatenate(([0], change, [len(levels)]))
    runs = np.diff(bounds)[1:-1] * dt
    states = levels[bounds[1:-2]]
    return runs[states], runs[~states]


def constant_current_vth(current: Callable[[float], float], i_crit: float, lo: float = -5.0, hi: float = 5.0) -> float:
    """Gate voltage where an increasing ``current(vg)`` reaches ``i_crit`` (log-scale bisection)."""
    return bisect_root(lambda vg: math.log(max(current(vg), 1e-300)) - math.log(i_crit), lo, hi, 1e-10)
