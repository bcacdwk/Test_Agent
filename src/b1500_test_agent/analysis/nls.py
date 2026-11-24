"""Least-squares fit of nucleation-limited switching (NLS) over an amplitude x width grid (the numerical core of
``nvm.switching_kinetics_fit``; definitions in the ``nvm.py`` docstring and knowledge ``06b-analysis-time-pulse.md``).

Model (Tagantsev et al., Phys. Rev. B 66, 214109, 2002, with a field-dependent switching time):
``y = V0 + A(V) (1 - exp(-(w / tau(V))^beta))``, ``tau(V) = tau0 exp((Va / |V|)^alpha)``, where ``y`` is the read
quantity after one pulse of amplitude ``V`` and width ``w`` from the reset state (Vth of a FeFET), ``V0`` the reset
level (one for all points) and ``A(V)`` the window an amplitude switches at saturation (one per distinct amplitude:
the quasi-static loop limits it below the coercive voltage).

Algorithm (deterministic, numpy only): variable projection: for given nonlinear parameters ``q = (ln tau0, ln Va,
ln beta[, ln alpha])`` the linear ones (``V0``, every ``A(V)``) come from linear least squares, so the residual is a
function of ``q`` alone. Start: per amplitude a grid over ``(ln tau, beta)`` with its own linear offset and window
(the switched-fraction curve of that amplitude), ``beta`` = the median of the amplitudes that switch inside the width
span, then ``ln tau(V) = ln tau0 + Va^alpha |V|^-alpha`` by a straight-line fit in ``|V|^-alpha``. Then Levenberg-
Marquardt on ``q`` (forward-difference Jacobian, multiplicative damping). Standard errors from ``sigma^2 (J^T J)^-1``
with ``sigma^2 = SSE / (n - parameters)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

__all__ = ["NlsFit", "fit_nls", "switched_fraction"]

BETA_GRID = (0.3, 3.0)
"""Range of the stretched exponent searched at the start (Lorentzian-broadened NLS ~0.5-1, KAI 1-2)."""

TAU_MARGIN = 30.0
"""The start grid searches ``tau`` from the smallest width / 30 to 30 x the largest width (log grid)."""

MIN_WIDTHS_PER_LEVEL = 3


@dataclass
class NlsFit:
    """A converged fit: ``tau0`` (s), ``va`` (V), ``alpha``, ``beta``, ``v0`` (the reset level), per amplitude
    ``(tau(V) s, A(V))`` in ``per_level``, ``rms`` and ``r2`` of the residuals, standard errors (``tau0_rel_se`` =
    se of ``ln tau0``; ``alpha_se`` 0 when fixed) and warnings."""

    tau0: float
    va: float
    alpha: float
    beta: float
    v0: float
    per_level: dict[float, tuple[float, float]]
    rms: float
    r2: float
    tau0_rel_se: float
    va_se: float
    beta_se: float
    alpha_se: float
    warnings: list[str] = field(default_factory=list)


def switched_fraction(widths: np.ndarray, tau: np.ndarray, beta: float) -> np.ndarray:
    """``1 - exp(-(w / tau)^beta)`` (overflow-safe)."""
    with np.errstate(over="ignore", under="ignore", invalid="ignore", divide="ignore"):
        z = np.exp(np.clip(beta * (np.log(widths) - np.log(tau)), -700.0, 700.0))
        return -np.expm1(-z)


class _Problem:
    """The data and the variable-projection residual of one fit."""

    def __init__(self, levels: np.ndarray, widths: np.ndarray, y: np.ndarray, alpha: float | None) -> None:
        self.levels, self.widths, self.y = levels, widths, y
        self.fixed_alpha = alpha
        self.distinct = sorted({float(v) for v in levels})
        index = {v: i for i, v in enumerate(self.distinct)}
        self.group = np.array([index[float(v)] for v in levels])
        self.abs_v = np.abs(levels)

    def unpack(self, q: np.ndarray) -> tuple[float, float, float, float]:
        """``(ln tau0, Va, beta, alpha)`` of the nonlinear parameter vector."""
        alpha = self.fixed_alpha if self.fixed_alpha is not None else math.exp(float(q[3]))
        return float(q[0]), math.exp(float(q[1])), math.exp(float(q[2])), alpha

    def taus(self, q: np.ndarray) -> np.ndarray:
        ln_tau0, va, _, alpha = self.unpack(q)
        return np.exp(np.clip(ln_tau0 + (va / self.abs_v) ** alpha, -700.0, 700.0))

    def design(self, q: np.ndarray) -> np.ndarray:
        """Columns: the reset level, then the switched fraction of each amplitude group."""
        s = switched_fraction(self.widths, self.taus(q), self.unpack(q)[2])
        columns = [np.ones_like(self.y)]
        columns += [np.where(self.group == g, s, 0.0) for g in range(len(self.distinct))]
        return np.column_stack(columns)

    def linear(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(linear coefficients, residual)`` for ``q``."""
        design = self.design(q)
        coef, *_ = np.linalg.lstsq(design, self.y, rcond=None)
        return coef, self.y - design @ coef

    def residual(self, q: np.ndarray) -> np.ndarray:
        return self.linear(q)[1]


def _level_start(widths: np.ndarray, y: np.ndarray) -> tuple[float, float, float] | None:
    """``(ln tau, beta, sse)`` of one amplitude's curve from a grid (its own offset and window); ``None`` when the
    amplitude has too few widths."""
    if np.unique(widths).size < MIN_WIDTHS_PER_LEVEL:
        return None
    best: tuple[float, float, float] | None = None
    ln_lo = math.log(float(widths.min()) / TAU_MARGIN)
    ln_hi = math.log(float(widths.max()) * TAU_MARGIN)
    for ln_tau in np.linspace(ln_lo, ln_hi, 61):
        for beta in np.linspace(BETA_GRID[0], BETA_GRID[1], 28):
            s = switched_fraction(widths, np.full_like(widths, math.exp(ln_tau)), float(beta))
            design = np.column_stack([np.ones_like(y), s])
            coef, *_ = np.linalg.lstsq(design, y, rcond=None)
            r = y - design @ coef
            sse = float(r @ r)
            if best is None or sse < best[2]:
                best = (float(ln_tau), float(beta), sse)
    return best


def _start(p: _Problem, alpha: float) -> np.ndarray | str:
    """Start values ``q`` (module docstring) or why there are none."""
    taus: list[tuple[float, float]] = []
    betas: list[float] = []
    for g, level in enumerate(p.distinct):
        mask = p.group == g
        found = _level_start(p.widths[mask], p.y[mask])
        if found is None:
            continue
        ln_tau, beta, _ = found
        inside = math.log(float(p.widths[mask].min())) <= ln_tau <= math.log(float(p.widths[mask].max()))
        taus.append((abs(level), ln_tau))
        if inside:
            betas.append(beta)
    if len(taus) < 2:
        return f"{len(taus)} amplitude(s) with at least {MIN_WIDTHS_PER_LEVEL} widths; tau(V) needs 2"
    beta = float(np.median(betas)) if betas else 1.0
    xs = np.array([v ** -alpha for v, _ in taus])
    ys = np.array([t for _, t in taus])
    slope, intercept = (float(c) for c in np.polyfit(xs, ys, 1))
    if slope <= 0:
        slope = max(float(np.ptp(ys)) / max(float(np.ptp(xs)), 1e-12), 1e-3)
        intercept = float(np.mean(ys - slope * xs))
    q = [intercept, math.log(slope ** (1.0 / alpha)), math.log(beta)]
    return np.array(q)


def _levenberg_marquardt(p: _Problem, q: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Minimise ``|residual(q)|^2``: ``(q, residual, Jacobian at q)``."""
    r = p.residual(q)
    cost = float(r @ r)
    damping = 1e-3
    jac = np.zeros((r.size, q.size))
    for _ in range(200):
        for k in range(q.size):
            h = 1e-6 * max(1.0, abs(float(q[k])))
            step = np.zeros_like(q)
            step[k] = h
            jac[:, k] = (p.residual(q + step) - r) / h
        jtj, grad = jac.T @ jac, jac.T @ r
        improved = False
        delta = np.zeros_like(q)
        for _ in range(30):
            try:
                delta = np.linalg.solve(jtj + damping * np.diag(np.diag(jtj) + 1e-30), -grad)
            except np.linalg.LinAlgError:
                damping *= 10.0
                continue
            trial = q + delta
            r_trial = p.residual(trial)
            cost_trial = float(r_trial @ r_trial)
            if math.isfinite(cost_trial) and cost_trial < cost:
                improved = True
                converged = cost - cost_trial <= 1e-14 * max(cost, 1e-300)
                q, r, cost = trial, r_trial, cost_trial
                damping = max(damping / 10.0, 1e-12)
                break
            damping *= 10.0
        if not improved or float(np.max(np.abs(delta))) < 1e-10 or converged:
            break
    for k in range(q.size):
        h = 1e-6 * max(1.0, abs(float(q[k])))
        step = np.zeros_like(q)
        step[k] = h
        jac[:, k] = (p.residual(q + step) - r) / h
    return q, r, jac


def fit_nls(levels: np.ndarray, widths: np.ndarray, y: np.ndarray, *, alpha: float | None = 2.0) -> NlsFit | str:
    """Fit the NLS model (module docstring) to points ``(levels[i], widths[i], y[i])``; ``alpha`` fixed (default 2)
    or fitted (``None``). Returns the fit, or why it is not possible (too few amplitudes, widths or points, no
    convergence)."""
    levels = np.asarray(levels, dtype=float)
    widths = np.asarray(widths, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.any(widths <= 0) or np.any(levels == 0):
        return "widths must be positive and amplitudes non-zero"
    p = _Problem(levels, widths, y, alpha)
    need_levels = 2 if alpha is not None else 3
    if len(p.distinct) < need_levels:
        return f"{len(p.distinct)} amplitude(s); the fit needs {need_levels}"
    n_params = 1 + len(p.distinct) + (3 if alpha is not None else 4)
    if y.size <= n_params:
        return f"{y.size} points for {n_params} parameters"
    q0 = _start(p, alpha if alpha is not None else 2.0)
    if isinstance(q0, str):
        return q0
    if alpha is None:
        q0 = np.append(q0, math.log(2.0))
    q, r, jac = _levenberg_marquardt(p, q0)
    ln_tau0, va, beta, alpha_fit = p.unpack(q)
    coef, _ = p.linear(q)
    sse = float(r @ r)
    spread = float(np.sum((y - y.mean()) ** 2))
    sigma2 = sse / max(y.size - n_params, 1)
    try:
        cov = np.linalg.inv(jac.T @ jac) * sigma2
        se = [math.sqrt(max(float(cov[k, k]), 0.0)) for k in range(q.size)]
    except np.linalg.LinAlgError:
        se = [math.inf] * q.size
    if not all(math.isfinite(v) for v in (ln_tau0, va, beta, alpha_fit)):
        return "the fit did not converge"
    taus = {v: math.exp(ln_tau0 + (va / abs(v)) ** alpha_fit) for v in p.distinct}
    per_level = {v: (taus[v], float(coef[1 + g])) for g, v in enumerate(p.distinct)}
    warnings = [f"tau({v:g} V) = {taus[v]:.3g} s lies outside the widths {float(widths[p.group == g].min()):.3g}.."
                f"{float(widths[p.group == g].max()):.3g} s: that amplitude constrains the fit weakly"
                for g, v in enumerate(p.distinct)
                if not float(widths[p.group == g].min()) <= taus[v] <= float(widths[p.group == g].max())]
    return NlsFit(tau0=math.exp(ln_tau0), va=va, alpha=alpha_fit, beta=beta, v0=float(coef[0]), per_level=per_level,
                  rms=math.sqrt(sse / y.size), r2=1.0 - sse / spread if spread > 0 else 1.0, tau0_rel_se=se[0],
                  va_se=va * se[1], beta_se=beta * se[2], alpha_se=alpha_fit * se[3] if alpha is None else 0.0,
                  warnings=warnings)
