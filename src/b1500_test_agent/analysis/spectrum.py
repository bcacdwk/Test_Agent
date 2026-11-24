"""Spectral estimation and the PSD model fit behind ``psd_welch`` and ``plot_psd`` (``noise.py``; WP10.5). The
definitions are in the ``noise.py`` docstring ("psd_welch"); this module holds the numerics (numpy only):

- ``welch_psd``: one-sided Welch PSD (Hann, half-overlapping segments, mean removed per segment);
- ``log_bins``: log-spaced averaging of a PSD inside a window;
- ``fit_psd``: ``A/f^gamma + W`` (``power``) or ``A/f^gamma + B/(1 + (f/fc)^2) + W`` (``power_lorentzian``) fitted to
  ``ln S`` by weighted least squares: a grid over ``gamma`` (and ``fc``) with non-negative amplitudes solved for the
  relative residuals (every subset of the optional amplitudes), then Levenberg-Marquardt in log space (two starts of
  the white floor, the better kept); ``auto`` keeps the Lorentzian only when the Bayesian information criterion drops
  by more than ``BIC_MARGIN``, its corner lies inside the window (x/÷ 3) and at its corner it is at least
  ``BUMP_FACTOR`` x the 1/f part (a visible bump).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

PsdModel = Literal["auto", "power", "power_lorentzian"]
BINS_PER_DECADE = 10
GAMMA_RANGE = (0.2, 2.5)
"""Range of the 1/f exponent searched."""
BIC_MARGIN = 10.0
"""``auto`` adds the Lorentzian only when it lowers the Bayesian information criterion by more than this."""
BUMP_FACTOR = 2.0
"""``auto`` keeps a Lorentzian only when at its corner it is at least this many times the 1/f part (a statistical
wiggle of a pure 1/f spectrum at its lowest bins is not an RTN corner)."""
CORNER_SPAN = 10.0
"""The Lorentzian corner is searched from the lowest bin / 10 to the highest bin x 10."""
LN_LIMIT = 690.0
FLOOR_START = 1e-3
FLOOR_HIGH = 0.5
"""The refinement starts twice, with the grid's white floor (or ``FLOOR_START`` x the smallest binned PSD value when
the grid needed none) and with ``FLOOR_HIGH`` x that value, and keeps the better: from a steep grid start the floor
can otherwise run to 0 and strand gamma on a plateau of the log-space cost."""
NEGLIGIBLE = 1e-6
"""A fitted white floor below this fraction of the smallest binned PSD value is reported as 0 (not resolved)."""
_TINY = 1e-300


def welch_psd(values: Sequence[float] | np.ndarray, dt: float, *, segments: int = 8
              ) -> tuple[np.ndarray, np.ndarray, int]:
    """One-sided PSD of ``values`` sampled every ``dt`` (module docstring "psd_welch"): returns the frequencies
    (0 .. Nyquist, Hz), the PSD (unit^2/Hz) and the segment length in points.

    Raises:
        ValueError: For ``segments`` < 1, ``dt`` <= 0 or segments shorter than 16 points.
    """
    x = np.asarray(values, dtype=float)
    if segments < 1 or not dt > 0:
        raise ValueError(f"need segments >= 1 and dt > 0, got {segments}, {dt}")
    nper = int(2 * x.size // (segments + 1)) if segments > 1 else int(x.size)
    if nper < 16:
        raise ValueError(f"{x.size} points in {segments} segments leave {nper} points per segment (< 16)")
    step = max(1, nper // 2)
    count = (x.size - nper) // step + 1
    window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(nper) / nper)  # periodic Hann
    acc = np.zeros(nper // 2 + 1)
    for k in range(count):
        seg = x[k * step:k * step + nper]
        acc += np.abs(np.fft.rfft((seg - seg.mean()) * window)) ** 2
    psd = acc / count * dt / float(np.sum(window**2))
    last = -1 if nper % 2 == 0 else None
    psd[1:last] *= 2.0
    return np.fft.rfftfreq(nper, dt), psd, nper


def log_bins(f: np.ndarray, s: np.ndarray, f_lo: float, f_hi: float, *, per_decade: int = BINS_PER_DECADE
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(frequency, mean PSD, FFT bins)`` of the log-spaced bins of ``[f_lo, f_hi]`` that hold an FFT bin; the bin
    frequency is the geometric mean of its FFT frequencies."""
    inside = (f >= f_lo) & (f <= f_hi) & (f > 0)
    fi, si = f[inside], s[inside]
    if fi.size == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0, dtype=int)
    count = max(1, math.ceil(per_decade * math.log10(f_hi / f_lo))) if f_hi > f_lo else 1
    edges = np.geomspace(f_lo, f_hi, count + 1)
    which = np.clip(np.searchsorted(edges, fi, side="right") - 1, 0, count - 1)
    m = np.bincount(which, minlength=count)
    keep = m > 0
    fb = np.exp(np.bincount(which, weights=np.log(fi), minlength=count)[keep] / m[keep])
    sb = np.bincount(which, weights=si, minlength=count)[keep] / m[keep]
    return fb, sb, m[keep]


@dataclass(frozen=True)
class PsdFit:
    """A fitted PSD model ``A/f^gamma + B/(1 + (f/fc)^2) + W`` (``B = 0`` for ``power``) with its quality."""

    model: Literal["power", "power_lorentzian"]
    a: float
    gamma: float
    b: float
    fc: float
    w: float
    gamma_se: float
    rms_log: float
    bic: float
    bins: int

    def flicker(self, f: np.ndarray) -> np.ndarray:
        return self.a / np.power(f, self.gamma)

    def lorentzian(self, f: np.ndarray) -> np.ndarray:
        return self.b / (1.0 + (f / self.fc) ** 2) if self.b > 0 else np.zeros_like(f)

    def evaluate(self, f: np.ndarray) -> np.ndarray:
        return self.flicker(f) + self.lorentzian(f) + self.w


def _nnls_grid(basis: list[np.ndarray], s: np.ndarray, w: np.ndarray, required: Sequence[int]
               ) -> tuple[np.ndarray, np.ndarray]:
    """For every grid row of the basis arrays (``(G, n)`` each), the non-negative amplitudes minimizing
    ``sum w (sum_k c_k basis_k / s - 1)^2`` (relative residuals), with the components ``required`` > 0: tries every
    subset that contains them and keeps the best feasible one. Returns ``(coefficients (G, K), cost (G,))``."""
    k_all = len(basis)
    g = basis[0].shape[0]
    u = [b / s for b in basis]
    best_cost = np.full(g, np.inf)
    best = np.zeros((g, k_all))
    optional = [k for k in range(k_all) if k not in required]
    for mask in range(1 << len(optional)):
        active = list(required) + [optional[j] for j in range(len(optional)) if mask >> j & 1]
        if not active:
            continue
        stacked = np.stack([u[k] for k in active], 1)
        mat = np.einsum("gin,gjn,n->gij", stacked, stacked, w)
        rhs = np.einsum("gin,n->gi", stacked, w)
        coef = np.einsum("gij,gj->gi", np.linalg.pinv(mat), rhs)  # batched; a singular grid point costs only itself
        model = np.einsum("gi,gin->gn", coef, stacked)
        cost = np.einsum("gn,n->g", (model - 1.0) ** 2, w)
        feasible = np.all(coef > 0, axis=1) & np.isfinite(cost)
        better = feasible & (cost < best_cost)
        if better.any():
            best_cost = np.where(better, cost, best_cost)
            full = np.zeros((g, k_all))
            full[:, active] = coef
            best = np.where(better[:, None], full, best)
    return best, best_cost


def _log_model(theta: np.ndarray, f: np.ndarray, parts: tuple[bool, bool]) -> tuple[np.ndarray, np.ndarray]:
    """``ln`` of the model and its Jacobian for ``theta = (ln A, gamma[, ln B, ln fc][, ln W])``."""
    lorentz, white = parts
    a, gamma = math.exp(theta[0]), theta[1]
    flick = a * np.power(f, -gamma)
    total = flick.copy()
    cols = [flick, -flick * np.log(f)]
    k = 2
    if lorentz:
        b, fc = math.exp(theta[k]), math.exp(theta[k + 1])
        ratio = (f / fc) ** 2
        lor = b / (1.0 + ratio)
        total += lor
        cols += [lor, lor * 2.0 * ratio / (1.0 + ratio)]
        k += 2
    if white:
        wv = math.exp(theta[k])
        total += wv
        cols.append(np.full_like(f, wv))
    total = np.maximum(total, _TINY)
    return np.log(total), np.stack(cols, 1) / total[:, None]


def _bounded(theta: np.ndarray, f: np.ndarray, lorentz: bool) -> np.ndarray:
    """``theta`` with finite log amplitudes, ``gamma`` inside ``GAMMA_RANGE`` and the corner inside ``CORNER_SPAN``
    of the bins."""
    out = np.clip(theta, -LN_LIMIT, LN_LIMIT)  # log amplitudes stay finite under exp()
    out[1] = float(np.clip(out[1], GAMMA_RANGE[0], GAMMA_RANGE[1]))
    if lorentz:
        out[3] = float(np.clip(out[3], math.log(f.min() / CORNER_SPAN), math.log(f.max() * CORNER_SPAN)))
    return out


def _refine(theta: np.ndarray, f: np.ndarray, ln_s: np.ndarray, w: np.ndarray, parts: tuple[bool, bool]
            ) -> tuple[np.ndarray, float, np.ndarray]:
    """Levenberg-Marquardt on the weighted log residuals; returns ``theta``, the weighted cost and the Jacobian."""
    sw = np.sqrt(w)
    theta = _bounded(theta, f, parts[0])
    model, jac = _log_model(theta, f, parts)
    r = sw * (ln_s - model)
    cost = float(r @ r)
    damping = 1e-3
    for _ in range(200):
        jw = jac * sw[:, None]
        jtj, grad = jw.T @ jw, jw.T @ r
        improved = False
        for _ in range(30):
            try:
                delta = np.linalg.solve(jtj + damping * np.diag(np.diag(jtj) + 1e-12), grad)
            except np.linalg.LinAlgError:
                damping *= 10.0
                continue
            trial = _bounded(theta + delta, f, parts[0])
            t_model, t_jac = _log_model(trial, f, parts)
            r_trial = sw * (ln_s - t_model)
            c_trial = float(r_trial @ r_trial)
            if c_trial < cost:
                theta, model, jac, r, cost, improved = trial, t_model, t_jac, r_trial, c_trial, True
                damping = max(damping / 10.0, 1e-12)
                break
            damping *= 10.0
        if not improved or float(np.max(np.abs(delta))) < 1e-9:
            break
    return theta, cost, jac


def fit_psd(f: np.ndarray, s: np.ndarray, weights: np.ndarray, *, model: PsdModel = "auto") -> PsdFit:
    """Fit the log-binned PSD ``s`` at ``f`` (module docstring "psd_welch"). With ``auto`` both models are fitted and
    the Lorentzian kept only when the information criterion and the corner allow it.

    Raises:
        ValueError: With fewer than 4 bins (5 for the Lorentzian) or non-positive values.
    """
    f, s, weights = (np.asarray(v, dtype=float) for v in (f, s, weights))
    if f.size < 4 or np.any(s <= 0) or np.any(f <= 0):
        raise ValueError(f"a PSD fit needs at least 4 positive bins, got {f.size}")
    candidates = [m for m in (("power", "power_lorentzian") if model == "auto" else (model,))
                  if m == "power" or f.size >= 5]
    if not candidates:
        raise ValueError(f"a Lorentzian fit needs at least 5 bins, got {f.size}")
    fits = [_fit_one(f, s, weights, m) for m in candidates]
    fits = [x for x in fits if x is not None]
    if not fits:
        raise ValueError("no non-negative PSD model fits the data")
    if model != "auto" or len(fits) == 1:
        return fits[0]
    power, lorentz = fits
    f_lo, f_hi = float(f.min()), float(f.max())
    corner = np.asarray([lorentz.fc])
    visible = float(lorentz.lorentzian(corner)[0]) >= BUMP_FACTOR * float(lorentz.flicker(corner)[0])
    if lorentz.bic < power.bic - BIC_MARGIN and f_lo / 3.0 <= lorentz.fc <= 3.0 * f_hi and visible:
        return lorentz
    return power


def _fit_one(f: np.ndarray, s: np.ndarray, w: np.ndarray, model: Literal["power", "power_lorentzian"]
             ) -> PsdFit | None:
    gammas = np.arange(GAMMA_RANGE[0], GAMMA_RANGE[1] + 1e-9, 0.01 if model == "power" else 0.025)
    ln_f = np.log(f)
    if model == "power":
        grid = [(g, math.nan) for g in gammas]
        basis = [np.exp(-np.outer(gammas, ln_f)), np.ones((gammas.size, f.size))]
        coef, cost = _nnls_grid(basis, s, w, required=[0])
    else:
        corners = np.geomspace(f.min() / CORNER_SPAN, f.max() * CORNER_SPAN, 48)
        gg, cc = np.meshgrid(gammas, corners, indexing="ij")
        grid = list(zip(gg.ravel(), cc.ravel(), strict=True))
        flick = np.exp(-np.outer(gg.ravel(), ln_f))
        lor = 1.0 / (1.0 + (f[None, :] / cc.ravel()[:, None]) ** 2)
        basis = [flick, lor, np.ones_like(flick)]
        coef, cost = _nnls_grid(basis, s, w, required=[0, 1])
    if not np.isfinite(cost).any():
        return None
    k = int(np.argmin(cost))
    gamma, fc = grid[k]
    lorentz = model == "power_lorentzian"
    parts = (lorentz, True)  # the refinement carries the white floor even when the grid needed none
    theta = [math.log(coef[k, 0]), float(gamma)]
    if lorentz:
        theta += [math.log(coef[k, 1]), math.log(fc)]
    ln_s = np.log(s)
    floors = (coef[k, -1] if coef[k, -1] > 0 else FLOOR_START * float(np.min(s)), FLOOR_HIGH * float(np.min(s)))
    refined = [_refine(np.asarray([*theta, math.log(floor)]), f, ln_s, w, parts) for floor in floors]
    theta_arr, wcost, jac = min(refined, key=lambda r: r[1])
    p = theta_arr.size
    n = f.size
    sigma2 = wcost / max(n - p, 1)
    try:
        jw = jac * np.sqrt(w)[:, None]
        cov = np.linalg.pinv(jw.T @ jw) * sigma2
        gamma_se = math.sqrt(max(float(cov[1, 1]), 0.0))
    except np.linalg.LinAlgError:
        gamma_se = math.inf
    model_ln, _ = _log_model(theta_arr, f, parts)
    rms = math.sqrt(float(np.sum(w * (ln_s - model_ln) ** 2)) / float(np.sum(w)))
    bic = n * math.log(max(wcost / n, _TINY)) + p * math.log(n)
    k_l = 2
    b = math.exp(theta_arr[k_l]) if lorentz else 0.0
    fc_v = math.exp(theta_arr[k_l + 1]) if lorentz else math.nan
    wv = math.exp(theta_arr[-1])
    if wv < NEGLIGIBLE * float(np.min(s)):
        wv = 0.0  # the log-space fit drove an unneeded floor towards 0: report none
    return PsdFit(model=model, a=math.exp(theta_arr[0]), gamma=float(theta_arr[1]), b=b, fc=fc_v, w=wv,
                  gamma_se=gamma_se, rms_log=rms, bic=bic, bins=n)
