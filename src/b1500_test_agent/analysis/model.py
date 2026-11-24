"""Compact MOSFET models (blueprint v2 2.10 ``model.py``, WP7.7; §0 row 26, OD-6): ``compact_model_fit`` fits a
SPICE level-1 or an EKV model to an Id-Vg or Id-Vd run, ``model_compare`` evaluates a model against a run (RMS
error) and ``export_spice_netlist`` writes the model as a SPICE ``.model`` card or subcircuit plus a netlist that
reproduces the run's sweep (``spice.py``). Running a SPICE simulator is not part of v2 (OD-6): the files are ready
for the human to run in ngspice or HSPICE; the built-in evaluation here is the comparison.

Definitions (the single source of knowledge file ``07-compact-models.md`` of skill ``b1500-test``; change both
together). Equations are written for an n-channel device with all voltages referred to the bulk; a p-channel device
(``polarity`` ``p``) is mirrored: every terminal voltage and the current change sign.

- **Level 1** (SPICE ``LEVEL=1``, Shichman-Hodges): ``Vov = Vgs - VTO``; ``Id = 0`` for ``Vov <= 0``; linear
  region (``Vds < Vov``) ``Id = beta (Vov Vds - Vds^2/2)(1 + LAMBDA Vds)``; saturation
  ``Id = beta/2 Vov^2 (1 + LAMBDA Vds)``; ``beta = KP W/L``; a negative ``Vds`` swaps source and drain. No body
  effect is fitted (``GAMMA = 0``: the fit is valid at the run's bulk bias), no subthreshold current, no mobility
  degradation: the fit uses the points with ``|Id| >= level1_fraction x max|Id|`` (default 5 %).
- **EKV** (long-channel EKV interpolation with a constant slope factor, the model the simulator's ``mosfet_ekv``
  uses): ``U_T = k T/q``; pinch-off ``Vp = (Vg - VT0)/n``; ``i_f,r = ln^2(1 + exp((Vp - Vs,d)/(2 U_T)))``;
  ``I_spec = 2 n beta U_T^2``; smooth overdrive ``Vov = 2 n U_T ln(1 + exp((Vg - VT0 - n min(Vs, Vd))/(2 n U_T)))``;
  ``Id = I_spec (i_f - i_r)(1 + LAMBDA |Vd - Vs|)/(1 + THETA Vov)``. Parameters ``vt0`` (V; the threshold, quantity
  ``vth``), ``n`` (subthreshold swing ``n U_T ln10``), ``beta`` (A/V^2 = mu Cox W/L), ``theta`` (1/V, mobility
  degradation), ``lambda`` (1/V, channel-length modulation) and ``rs`` (Ohm, in series with source and drain each;
  the drop is solved self-consistently by bisection).
- **Points.** The terminal voltages are the run's ``<role>_V`` columns (roles ``gate``, ``drain``, ``source``,
  ``bulk``; a missing source is the GNDU at 0 V, a missing bulk follows the source), the current is ``y`` (default
  ``drain_I``). Trust rules as every method (``mosfet.py``): untrusted rows refuse the call unless ``force``,
  limited (``C``/``T``) rows never enter. Points with ``|Id| < i_min_a`` do not enter (default: 3 x the
  noise-floor detection limit of ``common.floor_limit`` found on the curves, at least ``1e-9 x max|Id|``): the
  floor carries no model information. A double sweep uses ``segment`` (default ``fwd``).
- **Fit.** Least squares (Levenberg-Marquardt within parameter bounds, several starts) on
  ``asinh(Id_model/(2 i_min)) - asinh(Id/(2 i_min))``, which is ``ln(Id_model/Id)`` above ``i_min``: every point
  weighs by its relative error, so the subthreshold decades set ``n`` and ``vt0`` and strong inversion ``beta``,
  ``theta``. ``lambda`` is fitted when the run drives ``|Vds| >= 0.5 V`` (else held at 0; option ``fit_lambda``),
  ``rs`` only with ``fit_rs`` (else 0: ``theta`` then absorbs about ``2 beta rs``). Each parameter result carries the
  full parameter set, its standard error (``<name>_se``, from the Jacobian at the optimum) and the fit quality
  ``rms_log`` (RMS of ``ln(Id_model/Id)``, about the RMS relative error) and ``rms_rel`` in ``fit``.
- **Comparison** (``model_compare``): the model with the given ``params`` (or, without them, fitted to the same run:
  a goodness of fit, not a validation) evaluated at every used point: ``rms_rel`` (RMS of
  ``(Id_model - Id)/|Id|``), ``rms_log`` (RMS of ``log10(Id_model/Id)``, decades), ``max_rel`` and ``rms_error`` (A),
  per curve in ``fit`` for a stepped run.

Every result is derived (``ExtractionResult``) with its method record, fit window and points; refusals and failures
are results (``InvalidInputError`` only for unusable calls: missing columns, unknown parameters).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    Rows,
    analysed_rows,
    floor_limit,
    policy_params,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.dataset import RunData, Segment, parse_value_column
from b1500_test_agent.analysis.spice import (
    ROLES,
    Dialect,
    SpiceExport,
    SweepError,
    render_files,
    sweep_plan,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

ModelName = Literal["ekv", "level1"]
Polarity = Literal["n", "p"]

BOLTZMANN_OVER_Q = 8.617333262e-5
"""k/q in V/K (U_T = k T/q)."""

DEFAULT_TEMPERATURE_K = 300.0
FLOOR_FACTOR = 3.0
"""``i_min_a`` default: this many times the largest noise-floor detection limit found on the curves."""

RELATIVE_FLOOR = 1e-9
"""``i_min_a`` is at least this fraction of the largest current (a point at Vds = 0 carries no model information)."""

ABSOLUTE_FLOOR = 1e-15
LAMBDA_MIN_VDS = 0.5
"""``lambda`` is fitted (default) only when the used points reach this |Vds| (V)."""

DEFAULT_LEVEL1_FRACTION = 0.05
POOR_FIT_RMS_LOG = 0.1
"""A fit with ``rms_log`` above this (about 10 % RMS relative error) gets a warning."""

MIN_SUBTHRESHOLD_POINTS = 5

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]
Temperature = Annotated[float, Field(gt=0, le=600, allow_inf_nan=False)]

# Parameter tables: name -> (unit, lower bound, upper bound, typical scale). ``beta`` is fitted as ln(beta).
EKV_PARAMS: dict[str, tuple[Unit, float, float, float]] = {
    "vt0": ("V", -20.0, 20.0, 0.1),
    "n": ("1", 1.0, 5.0, 0.1),
    "beta": ("A/V^2", 1e-12, 10.0, 1.0),
    "theta": ("1/V", 0.0, 10.0, 0.1),
    "lambda": ("1/V", 0.0, 5.0, 0.01),
    "rs": ("Ohm", 0.0, 1e6, 10.0),
}
LEVEL1_PARAMS: dict[str, tuple[Unit, float, float, float]] = {
    "vto": ("V", -20.0, 20.0, 0.1),
    "beta": ("A/V^2", 1e-12, 10.0, 1.0),
    "lambda": ("1/V", 0.0, 5.0, 0.01),
}
PARAMS: dict[ModelName, dict[str, tuple[Unit, float, float, float]]] = {"ekv": EKV_PARAMS, "level1": LEVEL1_PARAMS}
THRESHOLD_PARAM: dict[ModelName, str] = {"ekv": "vt0", "level1": "vto"}
"""The parameter reported as quantity ``vth``."""


# -- models ----------------------------------------------------------------------------------------------------------


def _softplus(x: np.ndarray) -> np.ndarray:
    """``ln(1 + exp(x))`` without overflow."""
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0.0)


def thermal_voltage(temperature_k: float) -> float:
    """``U_T = k T/q`` (V)."""
    return BOLTZMANN_OVER_Q * temperature_k


def _ekv_core(p: Mapping[str, float], ut: float, vg: np.ndarray, vd: np.ndarray, vs: np.ndarray) -> np.ndarray:
    """Intrinsic EKV current D->S of the n-type core, voltages referred to the bulk (no series resistance)."""
    n, vt0 = p["n"], p["vt0"]
    vp = (vg - vt0) / n
    i_f = _softplus((vp - vs) / (2 * ut)) ** 2
    i_r = _softplus((vp - vd) / (2 * ut)) ** 2
    ispec = 2 * n * p["beta"] * ut * ut
    vov = 2 * n * ut * _softplus((vg - vt0 - n * np.minimum(vs, vd)) / (2 * n * ut))
    return ispec * (i_f - i_r) * (1 + p.get("lambda", 0.0) * np.abs(vd - vs)) / (1 + p.get("theta", 0.0) * vov)


def _with_series_resistance(core: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray], rs: float,
                            vg: np.ndarray, vd: np.ndarray, vs: np.ndarray, iterations: int = 60) -> np.ndarray:
    """Solve ``I = core(vg, vd - I rs, vs + I rs)`` per point by bisection between 0 and the current without
    ``rs`` (the residual ``I - core(...)`` increases with ``I``)."""
    i0 = core(vg, vd, vs)
    if rs <= 0.0:
        return i0
    lo, hi = np.minimum(i0, 0.0), np.maximum(i0, 0.0)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        above = mid - core(vg, vd - mid * rs, vs + mid * rs) > 0
        hi = np.where(above, mid, hi)
        lo = np.where(above, lo, mid)
    return 0.5 * (lo + hi)


def _level1_core(p: Mapping[str, float], vg: np.ndarray, vd: np.ndarray, vs: np.ndarray) -> np.ndarray:
    """Level-1 current D->S of the n-type core (symmetric: a negative Vds swaps source and drain)."""
    swap = vd < vs
    src = np.where(swap, vd, vs)
    drn = np.where(swap, vs, vd)
    vgs, vds = vg - src, drn - src
    vov = vgs - p["vto"]
    beta, lam = p["beta"], p.get("lambda", 0.0)
    linear = beta * (vov * vds - 0.5 * vds * vds) * (1 + lam * vds)
    saturated = 0.5 * beta * vov * vov * (1 + lam * vds)
    current = np.where(vov <= 0, 0.0, np.where(vds < vov, linear, saturated))
    return np.where(swap, -current, current)


@dataclass(frozen=True)
class CompactModel:
    """A compact model with its parameters (``params`` keys of ``PARAMS[model]``), polarity and temperature;
    ``current`` evaluates the drain current (A, into the drain) at terminal voltages (V)."""

    model: ModelName
    params: Mapping[str, float]
    polarity: Polarity = "n"
    temperature_k: float = DEFAULT_TEMPERATURE_K

    def __post_init__(self) -> None:
        known = PARAMS[self.model]
        unknown = sorted(set(self.params) - set(known))
        if unknown:
            raise InvalidInputError(f"{self.model} has no parameter(s) {unknown}; parameters: {list(known)}.")
        missing = [k for k in (("vt0", "n", "beta") if self.model == "ekv" else ("vto", "beta")) if
                   k not in self.params]
        if missing:
            raise InvalidInputError(f"{self.model} needs the parameter(s) {missing}.")
        for name, value in self.params.items():
            _unit, low, high, _scale = known[name]
            if not (isinstance(value, int | float) and math.isfinite(value) and low <= value <= high):
                raise InvalidInputError(f"{self.model} parameter {name}={value!r} is outside {low:g}..{high:g}.")

    @property
    def thermal_voltage(self) -> float:
        """``U_T = k T/q`` (V) at the model temperature."""
        return thermal_voltage(self.temperature_k)

    def full_params(self) -> dict[str, float]:
        """Every parameter of the model (unset optional ones at 0)."""
        return {name: float(self.params.get(name, 0.0)) for name in PARAMS[self.model]}

    def current(self, vg: Any, vd: Any, vs: Any = 0.0, vb: Any = None) -> np.ndarray:
        """Drain current (A, positive into the drain of a conducting n-channel device) at the terminal voltages;
        ``vb`` ``None`` = the bulk at the source potential."""
        return model_current(self.model, self.full_params(), self.polarity, self.temperature_k, vg, vd, vs, vb)


def model_current(model: ModelName, p: Mapping[str, float], polarity: Polarity, temperature_k: float, vg: Any,
                  vd: Any, vs: Any = 0.0, vb: Any = None) -> np.ndarray:
    """``CompactModel.current`` without parameter validation (``p`` holds every parameter of ``model``)."""
    vg_a, vd_a, vs_a = (np.asarray(v, dtype=float) for v in (vg, vd, vs))
    vb_a = vs_a if vb is None else np.asarray(vb, dtype=float)
    s = 1.0 if polarity == "n" else -1.0
    g, d, src = (s * (v - vb_a) for v in (vg_a, vd_a, vs_a))
    g, d, src = np.broadcast_arrays(g, d, src)
    threshold = THRESHOLD_PARAM[model]
    core = {**p, threshold: s * p[threshold]}  # the n-type core sees the mirrored threshold
    if model == "level1":
        return s * _level1_core(core, g, d, src)
    ut = thermal_voltage(temperature_k)
    return s * _with_series_resistance(lambda a, b, c: _ekv_core(core, ut, a, b, c), p.get("rs", 0.0), g, d, src)


# -- data ------------------------------------------------------------------------------------------------------------


@dataclass
class Points:
    """The points of a model fit or comparison: terminal voltages, current, the curve key and the analysed rows."""

    vg: np.ndarray
    vd: np.ndarray
    vs: np.ndarray
    vb: np.ndarray
    current: np.ndarray
    curve: np.ndarray
    rows: Rows
    x: str
    step: str | None
    i_min: float
    positions: np.ndarray
    problems: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return int(self.current.size)


def _role_column(d: RunData, role: str) -> str | None:
    column = f"{role}_V"
    return column if column in d.table.columns else None


def _terminal_columns(d: RunData, y: str) -> tuple[dict[str, str | None], str, str | None]:
    """Voltage column per terminal, the swept column ``x`` (most changes between neighbouring rows) and the step
    column (another varying column that changes only between curves; ``None`` without; a column changing with ``x``
    is a synchronous source)."""
    parsed = parse_value_column(y)
    if parsed is None or parsed[1] != "I" or y not in d.measured_columns:
        raise InvalidInputError(f"y must be a measured current column of run {d.run_id}, got {y!r}; measured: "
                                f"{d.measured_columns}.")
    columns = {role: _role_column(d, role) for role in ROLES}
    for role in ("gate", "drain"):
        if columns[role] is None:
            raise InvalidInputError(f"Run {d.run_id} has no {role}_V column; the compact models need the gate and "
                                    "drain voltages (recipes mosfet.idvg, mosfet.idvd and their variants).")
    varying = [c for c in columns.values() if c is not None and d.table[c].nunique(dropna=True) > 1]
    if not varying:
        raise InvalidInputError(f"Run {d.run_id}: no terminal voltage varies; a model fit needs a sweep.")
    table = d.table
    changes = {c: int((table[c].diff().fillna(0) != 0).sum()) for c in varying}
    x = max(varying, key=lambda c: (changes[c], int(table[c].nunique())))
    others = [c for c in varying if c != x and changes[c] < changes[x] / 2]  # a step column changes per curve only
    step = max(others, key=lambda c: int(table[c].nunique())) if others else None
    return columns, x, step


def _floor_current(xs: np.ndarray, ys: np.ndarray, curve: np.ndarray) -> float:
    """Largest noise-floor detection limit (``common.floor_limit``) over the points of every curve (0 if none)."""
    worst = 0.0
    for key in np.unique(curve):
        idx = np.flatnonzero(curve == key)
        cx, cy = xs[idx], ys[idx]
        order = np.argsort(cx, kind="stable")
        for position in range(order.size):
            limit = floor_limit(cx, cy, position)
            if limit is not None:
                worst = max(worst, limit)
    return worst


def _points(d: RunData, *, y: str, segment: Segment, policy: TrustPolicy, i_min_a: float | None,
            level1_fraction: float | None) -> Points:
    columns, x, step = _terminal_columns(d, y)
    r = analysed_rows(d, x, y, policy, segment=segment)
    rows = r.rows[r.ok]
    voltage = {role: (rows[c].to_numpy(dtype=float) if c is not None else None) for role, c in columns.items()}
    vs = voltage["source"] if voltage["source"] is not None else np.zeros(len(rows))
    vb = voltage["bulk"] if voltage["bulk"] is not None else vs
    current = rows[y].to_numpy(dtype=float)
    curve = rows[step].to_numpy(dtype=float) if step is not None else np.zeros(len(rows))
    problems = r.problems(f"segment {segment}")
    peak = float(np.max(np.abs(current))) if current.size else 0.0
    if i_min_a is None:
        i_min = max(FLOOR_FACTOR * _floor_current(rows[x].to_numpy(dtype=float), current, curve),
                    RELATIVE_FLOOR * peak, ABSOLUTE_FLOOR)
    else:
        i_min = float(i_min_a)
    keep = np.abs(current) >= i_min
    if level1_fraction is not None:
        keep &= np.abs(current) >= level1_fraction * peak
    positions = np.flatnonzero(keep)
    r.use(positions)
    return Points(vg=voltage["gate"][keep], vd=voltage["drain"][keep], vs=vs[keep], vb=vb[keep],  # type: ignore[index]
                  current=current[keep], curve=curve[keep], rows=r, x=x, step=step, i_min=i_min,
                  positions=positions, problems=problems)


def detect_polarity(points: Points) -> Polarity:
    """``n`` when |Id| grows with the gate voltage (the gate-bulk voltage), else ``p``."""
    vgb = points.vg - points.vb
    if np.ptp(vgb) == 0:
        return "n" if float(np.median(points.current * (points.vd - points.vs))) >= 0 else "p"
    weight = np.log10(np.maximum(np.abs(points.current), ABSOLUTE_FLOOR))
    return "n" if float(np.corrcoef(vgb, weight)[0, 1]) >= 0 else "p"


# -- least squares ---------------------------------------------------------------------------------------------------


@dataclass
class LeastSquares:
    """Outcome of ``levenberg_marquardt``: parameters, residuals, cost and the Jacobian at the optimum."""

    p: np.ndarray
    residual: np.ndarray
    cost: float
    jacobian: np.ndarray
    iterations: int


def levenberg_marquardt(residual: Callable[[np.ndarray], np.ndarray], p0: np.ndarray, lower: np.ndarray,
                        upper: np.ndarray, scale: np.ndarray, *, max_iter: int = 200,
                        tol: float = 1e-12) -> LeastSquares:
    """Bounded Levenberg-Marquardt (trial steps projected into ``[lower, upper]``, Marquardt scaling, forward
    difference Jacobian with steps ``1e-6 x (|p| + scale)``)."""
    p = np.clip(np.asarray(p0, dtype=float), lower, upper)
    r = residual(p)
    cost = float(r @ r)
    damping = 1e-3
    jac = np.zeros((r.size, p.size))
    iterations = 0
    for iterations in range(1, max_iter + 1):
        previous = cost
        for k in range(p.size):
            h = 1e-6 * (abs(p[k]) + scale[k])
            step = p.copy()
            step[k] = p[k] + h if p[k] + h <= upper[k] else p[k] - h
            jac[:, k] = (residual(step) - r) / (step[k] - p[k])
        normal = jac.T @ jac
        grad = jac.T @ r
        improved = False
        delta = np.zeros_like(p)
        for _ in range(40):
            try:
                delta = np.linalg.solve(normal + damping * np.diag(np.diag(normal) + 1e-30), -grad)
            except np.linalg.LinAlgError:
                damping *= 10.0
                continue
            trial = np.clip(p + delta, lower, upper)
            r_trial = residual(trial)
            cost_trial = float(r_trial @ r_trial)
            if np.isfinite(cost_trial) and cost_trial < cost:
                p, r, cost = trial, r_trial, cost_trial
                damping = max(damping / 10.0, 1e-12)
                improved = True
                break
            damping *= 10.0
        if not improved or abs(previous - cost) <= tol * max(previous, 1e-300) or \
                float(np.max(np.abs(delta) / (np.abs(p) + scale))) < 1e-10:
            break
    return LeastSquares(p=p, residual=r, cost=cost, jacobian=jac.copy(), iterations=iterations)


def _standard_errors(fit: LeastSquares, fixed: np.ndarray) -> np.ndarray:
    """Standard errors of the free parameters (NaN when the normal matrix is singular)."""
    free = ~fixed
    jac = fit.jacobian[:, free]
    dof = max(fit.residual.size - int(free.sum()), 1)
    out = np.full(fit.p.size, np.nan)
    try:
        cov = np.linalg.inv(jac.T @ jac) * fit.cost / dof
    except np.linalg.LinAlgError:
        return out
    out[free] = np.sqrt(np.maximum(np.diag(cov), 0.0))
    return out


# -- fitting ---------------------------------------------------------------------------------------------------------


@dataclass
class ModelFit:
    """A fitted model, its quality on the fitted points and the standard errors of the fitted parameters."""

    model: CompactModel
    fitted: tuple[str, ...]
    standard_errors: dict[str, float]
    rms_log: float
    rms_rel: float
    iterations: int
    starts: int
    warnings: list[str] = field(default_factory=list)


def _residual_fn(model: ModelName, names: list[str], fixed: dict[str, float], polarity: Polarity, temperature_k: float,
                 pts: Points) -> Callable[[np.ndarray], np.ndarray]:
    scale = 2.0 * pts.i_min
    target = np.arcsinh(pts.current / scale)

    def residual(q: np.ndarray) -> np.ndarray:
        values = {name: 0.0 for name in PARAMS[model]} | dict(fixed)
        for name, value in zip(names, q, strict=True):
            values[name] = math.exp(value) if name == "beta" else float(value)
        current = model_current(model, values, polarity, temperature_k, pts.vg, pts.vd, pts.vs, pts.vb)
        return np.arcsinh(current / scale) - target

    return residual


def _bounds(model: ModelName, names: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    table = PARAMS[model]
    lower = np.array([math.log(table[n][1]) if n == "beta" else table[n][1] for n in names])
    upper = np.array([math.log(table[n][2]) if n == "beta" else table[n][2] for n in names])
    scale = np.array([table[n][3] for n in names])
    return lower, upper, scale


def _starts(model: ModelName, pts: Points, polarity: Polarity) -> list[dict[str, float]]:
    """Initial parameter sets: threshold candidates across the gate range x slope factors (EKV)."""
    s = 1.0 if polarity == "n" else -1.0
    vgs = s * (pts.vg - pts.vs)
    vds = np.abs(pts.vd - pts.vs)
    peak = int(np.argmax(np.abs(pts.current)))
    lo, hi = float(np.min(vgs)), float(np.max(vgs))
    candidates = np.linspace(lo - 0.5, hi - 0.05 * max(hi - lo, 0.1), 7)
    starts: list[dict[str, float]] = []
    for vt in candidates:
        vov = max(vgs[peak] - vt, 0.05)
        vd_peak = max(float(vds[peak]), 1e-3)
        lin = vov * min(vd_peak, vov) - 0.5 * min(vd_peak, vov) ** 2
        beta = float(np.clip(abs(pts.current[peak]) / max(lin, 1e-6), 1e-11, 5.0))
        if model == "level1":
            starts.append({"vto": s * float(vt), "beta": beta, "lambda": 0.0})
            continue
        for n in (1.2, 1.6, 2.4):
            starts.append({"vt0": s * float(vt), "n": n, "beta": beta, "theta": 0.1, "lambda": 0.0, "rs": 0.0})
    return starts


def fit_model(pts: Points, model: ModelName, *, polarity: Polarity, temperature_k: float = DEFAULT_TEMPERATURE_K,
              fit_lambda: bool, fit_rs: bool) -> ModelFit:
    """Least-squares fit of ``model`` to ``pts`` (module docstring); raises ``ValueError`` with too few points."""
    names = list(PARAMS[model])
    hold = {"lambda": not fit_lambda, "rs": not fit_rs}
    free = [n for n in names if not hold.get(n, False)]
    if pts.size < len(free) + 2:
        raise ValueError(f"only {pts.size} usable point(s) for {len(free)} parameters")
    lower, upper, scale = _bounds(model, free)
    best: LeastSquares | None = None
    starts = _starts(model, pts, polarity)
    stage_one = [n for n in free if n != "rs"]
    lo1, up1, sc1 = _bounds(model, stage_one)
    for start in starts:
        fixed = {n: (0.0 if n in ("lambda", "rs") else start[n]) for n in names if n not in stage_one}
        q0 = np.array([math.log(start[n]) if n == "beta" else start[n] for n in stage_one])
        trial = levenberg_marquardt(_residual_fn(model, stage_one, fixed, polarity, temperature_k, pts), q0, lo1, up1,
                                    sc1)
        if best is None or trial.cost < best.cost:
            best = trial
    assert best is not None
    values = {n: (math.exp(v) if n == "beta" else float(v)) for n, v in zip(stage_one, best.p, strict=True)}
    iterations = best.iterations
    stage = stage_one
    if "rs" in free:
        q0 = np.array([math.log(values[n]) if n == "beta" else values.get(n, 1.0) for n in free])
        q0[free.index("rs")] = 1.0
        refined = levenberg_marquardt(_residual_fn(model, free, {}, polarity, temperature_k, pts), q0, lower, upper,
                                      scale)
        iterations += refined.iterations
        if refined.cost <= best.cost:
            best, stage = refined, free
            values = {n: (math.exp(v) if n == "beta" else float(v)) for n, v in zip(free, best.p, strict=True)}
    final = {n: float(np.clip(values.get(n, 0.0), PARAMS[model][n][1], PARAMS[model][n][2])) for n in names}
    cm = CompactModel(model, final, polarity, temperature_k)
    errors = _standard_errors(best, np.zeros(len(stage), dtype=bool))
    se = {}
    for name, err in zip(stage, errors, strict=True):
        se[name] = float(err * final["beta"]) if name == "beta" else float(err)
    predicted = cm.current(pts.vg, pts.vd, pts.vs, pts.vb)
    rms_log, rms_rel = _log_and_rel(predicted, pts.current)
    warnings: list[str] = []
    for name in stage:
        _unit, low, high, _scale = PARAMS[model][name]
        value = final[name]
        if name not in ("theta", "lambda", "rs") and (math.isclose(value, low, rel_tol=1e-6, abs_tol=1e-12)
                                                      or math.isclose(value, high, rel_tol=1e-6)):
            warnings.append(f"{name} ended at its bound {value:g}: the data do not determine it.")
    return ModelFit(model=cm, fitted=tuple(stage), standard_errors=se, rms_log=rms_log, rms_rel=rms_rel,
                    iterations=iterations, starts=len(starts), warnings=warnings)


def _log_and_rel(predicted: np.ndarray, measured: np.ndarray) -> tuple[float, float]:
    """RMS of ``ln(|model|/|data|)`` (model currents of the wrong sign or zero count at ``ln(1e-6)``) and RMS
    relative error."""
    ratio = np.where(predicted * measured > 0, np.abs(predicted) / np.abs(measured), 1e-6)
    rms_log = float(np.sqrt(np.mean(np.log(ratio) ** 2)))
    rms_rel = float(np.sqrt(np.mean(((predicted - measured) / measured) ** 2)))
    return rms_log, rms_rel


# -- registered methods ----------------------------------------------------------------------------------------------


def _subthreshold_points(pts: Points, model: CompactModel) -> int:
    """Used points below the model's threshold (gate overdrive < 0)."""
    s = 1.0 if model.polarity == "n" else -1.0
    vth = model.params[THRESHOLD_PARAM[model.model]]
    return int(np.sum(s * (pts.vg - pts.vs) < s * vth))


def _options(model: ModelName, **options: Any) -> dict[str, Any]:
    return {"model": model, **{k: v for k, v in options.items()}}


def _prepare(d: RunData, method: str, *, model: ModelName, y: str, segment: Segment, criteria: TrustPolicy | None,
             i_min_a: float | None, level1_fraction: float, polarity: Polarity | Literal["auto"], force: bool,
             extra: Mapping[str, Any]) -> tuple[Results, Points | None, Polarity, ExtractionResult | None]:
    policy = trust_policy(criteria)
    pts = _points(d, y=y, segment=segment, policy=policy, i_min_a=i_min_a,
                  level1_fraction=level1_fraction if model == "level1" else None)
    pol: Polarity = detect_polarity(pts) if polarity == "auto" and pts.size else ("n" if polarity == "auto"
                                                                                  else polarity)
    out = Results(method, {**_options(model, y=y, segment=segment, i_min_a=i_min_a, polarity=polarity,
                                      level1_fraction=level1_fraction, force=force, **extra),
                           "polarity_used": pol, "i_min_used": pts.i_min, "x": pts.x, "step": pts.step,
                           "trust_policy": policy_params(policy)})
    if pts.problems and not force:
        return out, None, pol, out.refused("vth", "V", pts.problems, excluded=pts.rows.excluded())
    out.flag(pts.problems)
    return out, pts, pol, None


@validate_call(config=_CALL_CONFIG)
def compact_model_fit(
    d: RunData,
    *,
    model: ModelName = "ekv",
    y: str = "drain_I",
    segment: Segment = "fwd",
    polarity: Polarity | Literal["auto"] = "auto",
    temperature_k: Temperature = DEFAULT_TEMPERATURE_K,
    fit_lambda: bool | None = None,
    fit_rs: bool = False,
    i_min_a: Positive | None = None,
    level1_fraction: Fraction = DEFAULT_LEVEL1_FRACTION,
    w_um: Positive | None = None,
    l_um: Positive | None = None,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Fit a level-1 or EKV model to an Id-Vg or Id-Vd run (module docstring). One result per model parameter
    (``vth`` = ``vt0``/``vto``, then ``n``, ``beta``, ``theta``, ``lambda``, ``rs`` for EKV; ``beta``, ``lambda`` and,
    with ``w_um``/``l_um``, ``kp`` = beta L/W for level 1); each ``fit`` holds the full parameter set, the standard
    errors and ``rms_log``/``rms_rel``. A refusal or failure returns one ``vth`` result without a value."""
    out, pts, pol, refused = _prepare(d, "compact_model_fit", model=model, y=y, segment=segment, criteria=criteria,
                                      i_min_a=i_min_a, level1_fraction=level1_fraction, polarity=polarity,
                                      force=force, extra={"temperature_k": temperature_k, "fit_lambda": fit_lambda,
                                                          "fit_rs": fit_rs, "w_um": w_um, "l_um": l_um})
    if refused is not None or pts is None:
        return [refused] if refused is not None else []
    excluded = pts.rows.excluded()
    wants_lambda = fit_lambda if fit_lambda is not None else bool(np.max(np.abs(pts.vd - pts.vs), initial=0.0)
                                                                    >= LAMBDA_MIN_VDS)
    try:
        fitted = fit_model(pts, model, polarity=pol, temperature_k=temperature_k, fit_lambda=wants_lambda,
                           fit_rs=fit_rs and model == "ekv")
    except ValueError as exc:
        return [out.failed("vth", "V", f"{model} fit impossible: {exc} (|{y}| >= {pts.i_min:.3g} A).",
                           excluded=excluded)]
    return _parameter_results(out, pts, fitted, w_um=w_um, l_um=l_um)


def _parameter_results(out: Results, pts: Points, fitted: ModelFit, *, w_um: float | None,
                       l_um: float | None) -> list[ExtractionResult]:
    cm = fitted.model
    params = cm.full_params()
    shared: dict[str, float] = {**params, **{f"{k}_se": v for k, v in fitted.standard_errors.items()},
                                "rms_log": fitted.rms_log, "rms_rel": fitted.rms_rel, "points": float(pts.size),
                                "temperature_k": cm.temperature_k, "i_min": pts.i_min,
                                "starts": float(fitted.starts), "iterations": float(fitted.iterations)}
    warnings = list(fitted.warnings)
    if fitted.rms_log > POOR_FIT_RMS_LOG:
        warnings.append(f"Poor fit: rms_log {fitted.rms_log:.3f} (> {POOR_FIT_RMS_LOG}); the model does not describe "
                        "these data well (level 1 has no subthreshold current or mobility degradation).")
    if cm.model == "ekv" and _subthreshold_points(pts, cm) < MIN_SUBTHRESHOLD_POINTS:
        warnings.append("Fewer than 5 used points below the threshold: n and vth rest on strong inversion only "
                        "(an Id-Vg sweep through the subthreshold region determines them).")
    if "lambda" not in fitted.fitted:
        warnings.append(f"lambda held at 0: the used points stay below |Vds| = {LAMBDA_MIN_VDS} V.")
    if cm.model == "ekv" and "rs" not in fitted.fitted:
        warnings.append("rs held at 0 (fit_rs false): theta includes the series resistance, about 2 beta rs.")
    window = window_of(pts.rows.rows[pts.x].to_numpy(dtype=float)[pts.rows.ok][pts.positions], "V")
    results = []
    for name in fitted.fitted:
        unit = PARAMS[cm.model][name][0]
        quantity = "vth" if name == THRESHOLD_PARAM[cm.model] else name
        results.append(out.ok(quantity, params[name], unit, excluded=pts.rows.excluded(), points_used=pts.size,
                              window=window, fit=shared, warnings=warnings))
    if cm.model == "level1" and w_um is not None and l_um is not None:
        results.append(out.ok("kp", params["beta"] * l_um / w_um, "A/V^2", excluded=pts.rows.excluded(),
                              points_used=pts.size, window=window, fit={**shared, "w_um": w_um, "l_um": l_um},
                              warnings=warnings))
    return results


def model_from_params(model: ModelName, params: Mapping[str, float], *, polarity: Polarity,
                      temperature_k: float) -> CompactModel:
    """A ``CompactModel`` from JSON options: ``vth`` is accepted for the threshold parameter, ``kp`` (level 1) needs
    ``w_um``/``l_um`` (pass ``beta`` instead)."""
    values = {k: float(v) for k, v in params.items() if k not in ("w_um", "l_um")}
    if "vth" in values:
        values.setdefault(THRESHOLD_PARAM[model], values.pop("vth"))
    if "kp" in values:
        if model != "level1" or "w_um" not in params or "l_um" not in params:
            raise InvalidInputError("kp needs model level1 with w_um and l_um in params (or pass beta = KP W/L).")
        kp = values.pop("kp")
        values.setdefault("beta", kp * float(params["w_um"]) / float(params["l_um"]))
    return CompactModel(model, values, polarity, temperature_k)


def compare(cm: CompactModel, pts: Points) -> dict[str, float]:
    """Model vs data on the used points: ``rms_rel``, ``rms_log`` (decades), ``max_rel``, ``rms_error`` (A), and per
    curve ``rms_rel@<step>=<level>`` for a stepped run."""
    predicted = cm.current(pts.vg, pts.vd, pts.vs, pts.vb)
    rel = (predicted - pts.current) / pts.current
    ratio = np.where(predicted * pts.current > 0, np.abs(predicted) / np.abs(pts.current), 1e-6)
    out = {"rms_rel": float(np.sqrt(np.mean(rel**2))), "rms_log": float(np.sqrt(np.mean(np.log10(ratio) ** 2))),
           "max_rel": float(np.max(np.abs(rel))), "rms_error": float(np.sqrt(np.mean((predicted - pts.current) ** 2)))}
    if pts.step is not None:
        for level in np.unique(pts.curve):
            mask = pts.curve == level
            out[f"rms_rel@{pts.step}={level:g}"] = float(np.sqrt(np.mean(rel[mask] ** 2)))
    return out


@validate_call(config=_CALL_CONFIG)
def model_compare(
    d: RunData,
    *,
    model: ModelName = "ekv",
    params: dict[str, float] | None = None,
    y: str = "drain_I",
    segment: Segment = "fwd",
    polarity: Polarity | Literal["auto"] = "auto",
    temperature_k: Temperature = DEFAULT_TEMPERATURE_K,
    i_min_a: Positive | None = None,
    level1_fraction: Fraction = DEFAULT_LEVEL1_FRACTION,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Evaluate a compact model against this run (module docstring): ``rms_rel``, ``rms_log`` (decades),
    ``max_rel`` and ``rms_error`` (A). ``params`` are the model parameters (``vt0``/``vth``, ``n``, ``beta`` ... as
    ``compact_model_fit`` reports them); without them the model is fitted to this run first (goodness of fit)."""
    out, pts, pol, refused = _prepare(d, "model_compare", model=model, y=y, segment=segment, criteria=criteria,
                                      i_min_a=i_min_a, level1_fraction=level1_fraction, polarity=polarity,
                                      force=force, extra={"params": dict(params or {}), "temperature_k": temperature_k})
    if refused is not None or pts is None:
        return [_renamed(refused, "rms_rel", "1")] if refused is not None else []
    excluded = pts.rows.excluded()
    if pts.size == 0:
        return [out.failed("rms_rel", "1", f"No usable point with |{y}| >= {pts.i_min:.3g} A.", excluded=excluded)]
    warnings: list[str] = []
    if params:
        cm = model_from_params(model, params, polarity=pol, temperature_k=temperature_k)
    else:
        wants_lambda = bool(np.max(np.abs(pts.vd - pts.vs)) >= LAMBDA_MIN_VDS)
        try:
            cm = fit_model(pts, model, polarity=pol, temperature_k=temperature_k, fit_lambda=wants_lambda,
                           fit_rs=False).model
        except ValueError as exc:
            return [out.failed("rms_rel", "1", f"{model} fit impossible: {exc}.", excluded=excluded)]
        warnings.append("No params given: the model was fitted to this run, so the errors measure the goodness of "
                        "fit, not a validation (pass params from another run's compact_model_fit).")
    metrics = compare(cm, pts)
    fit = {**cm.full_params(), **metrics, "points": float(pts.size), "i_min": pts.i_min}
    window = window_of(pts.rows.rows[pts.x].to_numpy(dtype=float)[pts.rows.ok][pts.positions], "V")
    if metrics["rms_log"] > POOR_FIT_RMS_LOG / math.log(10):
        warnings.append(f"The model misses the data: rms_log {metrics['rms_log']:.3f} decades.")
    common: dict[str, Any] = {"excluded": excluded, "points_used": pts.size, "window": window, "fit": fit,
                              "warnings": warnings}
    return [out.ok("rms_rel", metrics["rms_rel"], "1", **common),
            out.ok("rms_log", metrics["rms_log"], "1", **common),
            out.ok("max_rel", metrics["max_rel"], "1", **common),
            out.ok("rms_error", metrics["rms_error"], "A", **common)]


def _renamed(result: ExtractionResult, quantity: str, unit: Unit) -> ExtractionResult:
    return result.model_copy(update={"quantity": quantity, "unit": unit})


def model_points(d: RunData, *, model: ModelName = "ekv", y: str = "drain_I", segment: Segment = "fwd",
                 criteria: TrustPolicy | None = None, i_min_a: float | None = None,
                 level1_fraction: float = DEFAULT_LEVEL1_FRACTION) -> Points:
    """The points a fit or comparison of ``d`` uses (for agent scripts that plot model and data together)."""
    return _points(d, y=y, segment=segment, policy=trust_policy(criteria), i_min_a=i_min_a,
                   level1_fraction=level1_fraction if model == "level1" else None)


def curve_frame(cm: CompactModel, pts: Points) -> pd.DataFrame:
    """Measured and modelled current of every used point (columns ``vg vd vs vb id_meas id_model``)."""
    return pd.DataFrame({"vg": pts.vg, "vd": pts.vd, "vs": pts.vs, "vb": pts.vb, "id_meas": pts.current,
                         "id_model": cm.current(pts.vg, pts.vd, pts.vs, pts.vb)})


@validate_call(config=_CALL_CONFIG)
def export_spice_netlist(
    d: RunData,
    *,
    model: ModelName = "ekv",
    params: dict[str, float] | None = None,
    dialect: Dialect = "ngspice",
    y: str = "drain_I",
    segment: Segment = "fwd",
    polarity: Polarity | Literal["auto"] = "auto",
    temperature_k: Temperature = DEFAULT_TEMPERATURE_K,
    fit_lambda: bool | None = None,
    fit_rs: bool = False,
    i_min_a: Positive | None = None,
    level1_fraction: Fraction = DEFAULT_LEVEL1_FRACTION,
    w_um: Positive | None = None,
    l_um: Positive | None = None,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> SpiceExport:
    """The model (``params``, or fitted to this run like ``compact_model_fit``) as a SPICE ``.model`` card or EKV
    subcircuit (``.lib``) plus a netlist reproducing this run's sweep (``.sp``; ``spice.py``). ``results`` are the
    model's errors on this run (as ``model_compare``); a refusal or failure exports no file."""
    stem = f"spice-{model}"
    out, pts, pol, refused = _prepare(d, "export_spice_netlist", model=model, y=y, segment=segment,
                                      criteria=criteria, i_min_a=i_min_a, level1_fraction=level1_fraction,
                                      polarity=polarity, force=force,
                                      extra={"params": dict(params or {}), "dialect": dialect,
                                             "temperature_k": temperature_k, "fit_lambda": fit_lambda,
                                             "fit_rs": fit_rs, "w_um": w_um, "l_um": l_um})
    if refused is not None or pts is None:
        return SpiceExport(stem, (), [_renamed(refused, "rms_rel", "1")] if refused is not None else [])
    excluded = pts.rows.excluded()
    try:
        plan = sweep_plan(d, d.rows(segment), pts.x, pts.step)
    except SweepError as exc:
        return SpiceExport(stem, (), [out.failed("rms_rel", "1", f"No netlist: {exc}.", excluded=excluded)])
    warnings: list[str] = []
    if params:
        cm = model_from_params(model, params, polarity=pol, temperature_k=temperature_k)
    else:
        wants_lambda = fit_lambda if fit_lambda is not None else bool(np.max(np.abs(pts.vd - pts.vs), initial=0.0)
                                                                        >= LAMBDA_MIN_VDS)
        try:
            cm = fit_model(pts, model, polarity=pol, temperature_k=temperature_k, fit_lambda=wants_lambda,
                           fit_rs=fit_rs and model == "ekv").model
        except ValueError as exc:
            return SpiceExport(stem, (), [out.failed("rms_rel", "1", f"{model} fit impossible: {exc}.",
                                                     excluded=excluded)])
        warnings.append("Parameters fitted to this run (compact_model_fit); the errors are the goodness of fit.")
    metrics = compare(cm, pts)
    quality = {**metrics, "points": float(pts.size)}
    files = render_files(cm, d, plan, dialect=dialect, quality=quality, fitted=not params, w_um=w_um, l_um=l_um)
    fit = {**cm.full_params(), **metrics, "points": float(pts.size), "i_min": pts.i_min}
    window = window_of(pts.rows.rows[pts.x].to_numpy(dtype=float)[pts.rows.ok][pts.positions], "V")
    common: dict[str, Any] = {"excluded": excluded, "points_used": pts.size, "window": window, "fit": fit,
                              "warnings": warnings}
    return SpiceExport(stem, files, [out.ok("rms_rel", metrics["rms_rel"], "1", **common),
                                     out.ok("rms_log", metrics["rms_log"], "1", **common)])
