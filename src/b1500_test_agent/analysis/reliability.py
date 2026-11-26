"""Reliability and time-domain analysis (blueprint v2 2.10 ``reliability.py``): the time-series plot
``plot_timeseries`` (WP5.7), the sampling methods ``sampling_summary`` and ``time_to_breakdown`` and the library helper
``weibull_fit`` over a run list (WP7.4); the stress-measure methods of WP7.6 and WP10.7 (``bti_power_law``,
``degradation_vs_time``, ``silc``, ``fast_bti_shift``) live in ``stress.py``.

``plot_timeseries`` (definition; the source of knowledge file ``06-analysis-extraction.md``): one figure per scale
(``linear``, the default; ``log``: absolute values on a log axis; ``both`` = the two), one panel per value column
(``y``: default every measured value column of the run, in table order; any value column may be named), against
``x`` = ``t_s`` (seconds; the default when the run has it), else ``cycle``, else ``step`` (the point index; the
figure then says that the run has no time base). ``log_time=true`` puts x on a log axis (log-time stress or
retention schedules). Runs with a ``phase`` column draw one curve per phase (stress, read, recovery ...), else one
per ``segment``, else one per WGFMU ``event``; at most 12 groups get a legend. As in ``plot_iv``, trusted points are
joined by lines, limited (``C``/``T``) points are open circles, untrusted points crosses; invalid data
(``199.999E+99``), non-finite values and, on a log axis, values or times at or below zero are left out and counted
in the figure's note. A curve with more than ``max_points`` points (default 5,000) is decimated by keeping the
minimum and the maximum of each of ``max_points / 2`` equal index buckets (spikes and steps stay visible; noted on
the figure). Plots never refuse and never extract anything.

Where the files go: ``analyze_run``/``run_method("plot_timeseries", ...)`` returns a ``PlotSet`` that the server
stores as ``plots/timeseries-<scale>-<n>.png``; agent scripts call ``plot_timeseries`` with ``out_dir`` (default
``work/<run_id>/plots/``), because run folders are written only by the server.

``sampling_summary`` (definition): statistics of one measured column ``y`` of a sampling run (default: the run's
only measured current, else its first measured column) against ``t_s`` (seconds since the bias step; required).
Over the trusted points inside ``[t_min, t_max]`` (default: all): ``initial`` and ``final`` = medians of the first
and the last ``edge`` points (default 10, at most a tenth of the points), ``mean``, ``std`` (sample standard
deviation) and ``drift`` = (final - initial) / |initial| (unit ``1``). With ``fit="stretched_exp"`` it also fits the
relaxation ``y(t) = y_inf + (y0 - y_inf) exp(-(t/tau)^beta)`` (IGZO bias-stress transients, Libsch & Kanicki,
APL 62, 1286, 1993, not page-checked; Kohlrausch law): linear least squares for ``y_inf`` and ``y0`` at each ``(tau,
beta)`` (variable projection), a coarse grid over ``tau`` (``t``-span / 30 to 30 x the span, log) and ``beta`` (0.1 to
1.5) on the data averaged in at most 400 log-time bins, then Levenberg-Marquardt on every point in ``(ln tau, beta)``;
results ``tau`` (s), ``beta`` (1) and ``y_inf`` (unit of ``y``); ``fit`` holds ``y0``, ``r2``, the residual rms and
the standard errors from the Jacobian. A ``tau`` beyond 3x the last time or a ``beta`` at a grid edge is flagged
(poorly constrained). Trust as every method: untrusted points refuse the call unless ``force``; limited (``C``/``T``)
points are excluded and counted.

``time_to_breakdown`` (definition): the time to dielectric breakdown under constant stress from the stressed
terminal's current ``y`` (default as ``sampling_summary``). The breakdown sample is the first sample (in ``t_s``
order) that reports compliance on ``y`` (status ``C``: the stress source current-limited by the breakdown path),
or whose |I| is at least ``jump_factor`` (default 10) x the median |I| of the ``window`` (default 5) samples before
it (a hard breakdown below the compliance), or reaches ``i_bd_a`` when given. ``t_bd`` = its ``t_s``: the breakdown
happened after the previous sample, so the resolution is one sampling interval (``fit.t_prev_s``,
``fit.resolution_s``); a breakdown at the very first sample is flagged (the site may have been broken before the
stress). ``classification`` ``breakdown``; with no breakdown sample the result is the last time with
``bound="lower"`` and ``classification`` ``no_breakdown`` (a right-censored life for ``weibull_fit``). ``fit`` also
holds the current before and at breakdown and the criterion (1 compliance, 2 jump, 3 threshold). Untrusted points
before the breakdown sample refuse the call unless ``force``; points after it are ignored (post-breakdown data).

``weibull_fit`` (library helper, not an ``analyze_run`` method: it reads a list of runs, e.g. one TDDB run per site
at one stress): ``time_to_breakdown`` of each run (options passed through), then the two-parameter Weibull
``F(t) = 1 - exp(-(t/eta)^beta)`` by maximum likelihood with right censoring (``no_breakdown`` runs survive to their
last time; refused or failed runs are left out and named in the warnings): ``beta`` solves
``1/beta + mean(ln t_f) - sum(t^beta ln t)/sum(t^beta) = 0`` over all times (bisection), ``eta = (sum t^beta / r)^(1/
beta)`` with ``r`` failures. ``method="rank"`` instead regresses ``ln(-ln(1 - F))`` on ``ln t`` with Bernard's median
ranks ``F = (i - 0.3)/(n + 0.4)`` (failures only, censored runs refused). Results ``weibull_beta`` (1) and
``weibull_eta`` (s); ``fit`` holds ``n``, ``failures``, ``censored`` and, for the MLE, the log-likelihood and the
Fisher standard error of beta. It also takes plain ``times_s`` (+ ``censored`` flags) instead of runs. At least two
failures are needed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    excluded_counts,
    line_fit,
    policy_params,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.dataset import (
    CYCLE,
    EVENT,
    PHASE,
    SEGMENT,
    STEP,
    T_S,
    RunData,
    row_reasons,
    status_column,
    trust_levels,
    work_dir_for,
)
from b1500_test_agent.analysis.plots import (
    INVALID_ABOVE,
    MAX_LEGEND,
    PlotScale,
    PlotSet,
    RenderedPlot,
    figure_png,
    new_figure,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

TimeAxis = Literal["t_s", "cycle", "step"]
DEFAULT_MAX_POINTS = 5_000
_X_UNITS = {T_S: "s", CYCLE: "cycle", STEP: "point"}
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
_GROUP_COLUMNS = (PHASE, SEGMENT, EVENT)


def envelope_indices(values: np.ndarray, max_points: int) -> np.ndarray:
    """Indices that keep at most ``max_points`` of ``values`` (in order): all of them when they fit, else the
    minimum and the maximum of each of ``max_points // 2`` equal index buckets (NaN-safe; empty buckets skipped)."""
    n = len(values)
    if n <= max_points:
        return np.arange(n)
    buckets = max(1, max_points // 2)
    edges = np.linspace(0, n, buckets + 1).astype(np.intp)
    keep: list[int] = []
    for start, stop in pairwise(edges):
        chunk = values[start:stop]
        finite = np.isfinite(chunk)
        if not finite.any():
            continue
        masked_low = np.where(finite, chunk, np.inf)
        masked_high = np.where(finite, chunk, -np.inf)
        keep.extend((start + int(np.argmin(masked_low)), start + int(np.argmax(masked_high))))
    return np.unique(np.asarray(keep, dtype=np.intp))


def _x_column(d: RunData, x: TimeAxis | None) -> str:
    if x is None:
        return next(c for c in (T_S, CYCLE, STEP) if c in d.table.columns)
    if x not in d.table.columns:
        raise InvalidInputError(f"plot_timeseries: run {d.run_id} has no {x!r} column; columns: "
                                f"{list(d.table.columns)}.")
    return x


def _y_columns(d: RunData, y: list[str] | None) -> list[str]:
    columns = list(d.measured_columns) if y is None else list(y)
    if not columns:
        raise InvalidInputError(f"plot_timeseries: run {d.run_id} has no measured value column; pass y=[...].")
    for column in columns:
        d.unit(column)  # raises for a column that is not a value column of the run
    return columns


def _groups(table: pd.DataFrame) -> tuple[str | None, list[tuple[str, np.ndarray]]]:
    for column in _GROUP_COLUMNS:
        if column in table.columns:
            labels = table[column].astype(str)
            return column, [(label or "(none)", (labels == label).to_numpy()) for label in labels.drop_duplicates()]
    return None, [("", np.ones(len(table), dtype=bool))]


def render_timeseries(
    d: RunData,
    *,
    y: list[str] | None = None,
    x: TimeAxis | None = None,
    scale: PlotScale = "linear",
    log_time: bool = False,
    max_points: int = DEFAULT_MAX_POINTS,
    criteria: TrustPolicy | None = None,
) -> PlotSet:
    """Render the time-series plots of ``d`` (module docstring) as PNG bytes; nothing is written."""
    policy = trust_policy(criteria)
    x_column = _x_column(d, x)
    columns = _y_columns(d, y)
    table = d.table
    levels = trust_levels(table, policy).to_numpy()
    group_column, groups = _groups(table)
    xs = table[x_column].to_numpy(dtype=float)
    scales: list[Literal["linear", "log"]] = ["linear", "log"] if scale == "both" else [
        "log" if scale == "log" else "linear"]
    warnings: list[str] = []
    if x_column == STEP and x is None:
        warnings.append(f"run {d.run_id} has no t_s or cycle column; x is the point index (step).")
    plots: list[RenderedPlot] = []
    for kind in scales:
        figure = new_figure(width_in=7.0, height_in=2.8 * len(columns) + 0.6)
        skipped = decimated = 0
        for panel, column in enumerate(columns):
            axes = figure.add_subplot(len(columns), 1, panel + 1)
            values = table[column].to_numpy(dtype=float)
            values = np.abs(values) if kind == "log" else values
            for label, mask in groups:
                drawable = mask & np.isfinite(xs) & np.isfinite(values) & (np.abs(values) < INVALID_ABOVE)
                if kind == "log":
                    drawable &= values > 0
                if log_time:
                    drawable &= xs > 0
                skipped += int((mask & ~drawable).sum())
                ok = np.flatnonzero(drawable & (levels == "ok"))
                kept = ok[envelope_indices(values[ok], max_points)]
                decimated += len(ok) - len(kept)
                line = axes.plot(xs[kept], values[kept], "-", linewidth=1.0, label=label or None)
                color = line[0].get_color()
                for level, marker in (("limited", "o"), ("untrusted", "x")):
                    flagged = np.flatnonzero(drawable & (levels == level))
                    if flagged.size:
                        shown = flagged[envelope_indices(values[flagged], max_points)]
                        axes.plot(xs[shown], values[shown], marker, mfc="none" if marker == "o" else color,
                                  color=color, markersize=4 if marker == "o" else 5, linestyle="none")
            if kind == "log":
                axes.set_yscale("log")
            if log_time:
                axes.set_xscale("log")
            unit = d.unit(column)
            name = f"|{column}|" if kind == "log" else column
            axes.set_ylabel(name if unit == "1" else f"{name} ({unit})")
            axes.set_xlabel(f"{x_column} ({_X_UNITS[x_column]})")
            axes.grid(True, which="both", alpha=0.3)
            if 1 < len(groups) <= MAX_LEGEND:
                axes.legend(fontsize=7, title=group_column, title_fontsize=7)
        title = f"{d.run_id} {d.manifest.recipe_id} ({'SIMULATED' if d.manifest.simulated else 'measured'})"
        figure.suptitle(title, fontsize=9)
        notes = []
        if skipped:
            notes.append(f"{skipped} point(s) not drawn on the {kind} plot (invalid data, non-finite values, or "
                         "values/times <= 0 on a log axis).")
        if decimated:
            notes.append(f"{decimated} trusted point(s) thinned to the min/max envelope (max_points={max_points}).")
        if notes:
            figure.text(0.01, 0.005, " ".join(notes), fontsize=6)
            warnings.extend(notes)
        plots.append(RenderedPlot(name=f"timeseries-{kind}", png=figure_png(figure)))
    return PlotSet(plots=tuple(plots), x=x_column, y=tuple(columns), scale=scale, warnings=tuple(warnings))


@validate_call(config=_CALL_CONFIG)
def plot_timeseries(
    d: RunData,
    *,
    y: list[str] | None = None,
    x: TimeAxis | None = None,
    scale: PlotScale = "linear",
    log_time: bool = False,
    max_points: int = Field(default=DEFAULT_MAX_POINTS, ge=100, le=200_000),
    out_dir: Path | None = None,
    criteria: TrustPolicy | None = None,
) -> list[Path]:
    """Render the time-series plots of ``d`` (module docstring) into ``out_dir`` (default
    ``work/<run_id>/plots/``) and return the PNG paths. For agent scripts; ``analyze_run`` stores them in the run
    folder instead."""
    rendered = render_timeseries(d, y=y, x=x, scale=scale, log_time=log_time, max_points=max_points,
                                 criteria=criteria)
    target = out_dir if out_dir is not None else work_dir_for(d.run_id) / "plots"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for plot in rendered.plots:
        path = target / f"{plot.name}.png"
        path.write_bytes(plot.png)
        paths.append(path)
    return paths


@validate_call(config=_CALL_CONFIG)
def plot_timeseries_method(
    d: RunData,
    *,
    y: list[str] | None = None,
    x: TimeAxis | None = None,
    scale: PlotScale = "linear",
    log_time: bool = False,
    max_points: int = Field(default=DEFAULT_MAX_POINTS, ge=100, le=200_000),
    criteria: TrustPolicy | None = None,
) -> PlotSet:
    """The registered ``plot_timeseries`` method: ``render_timeseries`` with JSON options; the caller stores the
    ``PlotSet``."""
    return render_timeseries(d, y=y, x=x, scale=scale, log_time=log_time, max_points=max_points, criteria=criteria)


# -- sampling_summary ------------------------------------------------------------------------------------------------

FitModel = Literal["none", "stretched_exp"]
DEFAULT_EDGE = 10
MAX_FIT_BINS = 400
BETA_GRID = (0.1, 1.5)
"""Range of the stretched-exponential exponent searched (Kohlrausch beta; 1 = single exponential)."""
TAU_GRID_FACTOR = 30.0
"""``tau`` is searched from the time span / 30 to 30 x the span (log grid)."""


def _time_column(d: RunData, method: str) -> np.ndarray:
    if T_S not in d.table.columns:
        raise InvalidInputError(f"{method}: run {d.run_id} has no t_s column (a time-sampling run is needed).")
    return d.table[T_S].to_numpy(dtype=float)


def _default_y(d: RunData, y: str | None, method: str) -> str:
    measured = d.measured_columns
    if y is not None:
        if y not in measured:
            raise InvalidInputError(f"{method}: {y!r} is not a measured column of run {d.run_id}; measured: "
                                    f"{measured}.")
        return y
    currents = [c for c in measured if c.endswith("_I")]
    if len(currents) == 1:
        return currents[0]
    if not measured:
        raise InvalidInputError(f"{method}: run {d.run_id} has no measured column.")
    if currents:
        raise InvalidInputError(f"{method}: run {d.run_id} measures several currents {currents}; pass y=<column>.")
    return measured[0]


def _rows_in_window(d: RunData, y: str, policy: TrustPolicy, t_min: float | None,
                    t_max: float | None) -> tuple[np.ndarray, np.ndarray, pd.Series, pd.Series, np.ndarray]:
    """``(t, y, levels, reasons, usable)`` of the rows: usable = trusted, finite and inside the window."""
    table = d.table
    t = table[T_S].to_numpy(dtype=float)
    values = table[y].to_numpy(dtype=float)
    levels = trust_levels(table, policy, columns=[y])
    reasons = row_reasons(table[[STEP, y, status_column(y)]], policy)
    inside = np.isfinite(t) & np.isfinite(values)
    if t_min is not None:
        inside &= t >= t_min
    if t_max is not None:
        inside &= t <= t_max
    reasons = reasons.where(inside | (reasons != "N"), "outside_window")
    usable = (levels == "ok").to_numpy() & inside
    return t, values, levels, reasons, usable


def _stretched(t: np.ndarray, tau: float, beta: float) -> np.ndarray:
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        return np.exp(-np.power(np.maximum(t, 0.0) / tau, beta))


def _projected(t: np.ndarray, y: np.ndarray, tau: float, beta: float) -> tuple[float, float, float]:
    """Best ``(y_inf, y0, sse)`` for fixed ``(tau, beta)`` by linear least squares."""
    g = _stretched(t, tau, beta)
    design = np.column_stack([1.0 - g, g])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coef
    return float(coef[0]), float(coef[1]), float(residual @ residual)


def _log_bins(t: np.ndarray, y: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Means of ``t`` and ``y`` in at most ``bins`` log-spaced time bins (positive times)."""
    if t.size <= bins:
        return t, y
    lo, hi = float(t.min()), float(t.max())
    edges = np.geomspace(max(lo, hi * 1e-12), hi, bins + 1) if lo > 0 else np.linspace(lo, hi, bins + 1)
    which = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, bins - 1)
    counts = np.bincount(which, minlength=bins)
    keep = counts > 0
    tb = np.bincount(which, weights=t, minlength=bins)[keep] / counts[keep]
    yb = np.bincount(which, weights=y, minlength=bins)[keep] / counts[keep]
    return tb, yb


def fit_stretched_exponential(t: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Least-squares ``y = y_inf + (y0 - y_inf) exp(-(t/tau)^beta)`` (module docstring): returns ``tau``, ``beta``,
    ``y_inf``, ``y0``, ``r2``, ``rms`` and the standard errors ``tau_se``, ``beta_se``.

    Raises:
        ValueError: With fewer than 8 points or no positive time span.
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    positive = t > 0
    t, y = t[positive], y[positive]
    if t.size < 8 or not float(t.max()) > float(t.min()):
        raise ValueError("a stretched-exponential fit needs at least 8 points at t > 0 over a time span")
    span = float(t.max())
    tb, yb = _log_bins(t, y, MAX_FIT_BINS)
    best = (math.inf, 1.0, 0.5)
    for tau in np.geomspace(float(t.min()) / TAU_GRID_FACTOR, span * TAU_GRID_FACTOR, 61):
        for beta in np.linspace(BETA_GRID[0], BETA_GRID[1], 57):
            sse = _projected(tb, yb, float(tau), float(beta))[2]
            if sse < best[0]:
                best = (sse, float(tau), float(beta))
    p = np.array([math.log(best[1]), best[2]])

    def residuals(q: np.ndarray) -> np.ndarray:
        tau, beta = math.exp(q[0]), float(np.clip(q[1], 0.01, 5.0))
        g = _stretched(t, tau, beta)
        design = np.column_stack([1.0 - g, g])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        return y - design @ coef

    r = residuals(p)
    cost = float(r @ r)
    damping = 1e-3
    jac = np.zeros((t.size, 2))
    for _ in range(100):
        for k, h in enumerate((1e-5, 1e-5)):
            step = np.zeros(2)
            step[k] = h
            jac[:, k] = (residuals(p + step) - r) / h
        jtj = jac.T @ jac
        grad = jac.T @ r
        improved = False
        for _ in range(20):
            delta = np.linalg.solve(jtj + damping * np.diag(np.diag(jtj) + 1e-30), -grad)
            trial = p + delta
            r_trial = residuals(trial)
            cost_trial = float(r_trial @ r_trial)
            if cost_trial < cost:
                improved = True
                p, r, cost = trial, r_trial, cost_trial
                damping = max(damping / 10.0, 1e-12)
                break
            damping *= 10.0
        if not improved or float(np.max(np.abs(delta))) < 1e-10:
            break
    tau, beta = math.exp(p[0]), float(np.clip(p[1], 0.01, 5.0))
    y_inf, y0, sse = _projected(t, y, tau, beta)
    spread = float(np.sum((y - y.mean()) ** 2))
    dof = max(t.size - 4, 1)
    sigma2 = sse / dof
    try:
        covariance = np.linalg.inv(jac.T @ jac) * sigma2
        ln_tau_se, beta_se = (math.sqrt(max(float(covariance[k, k]), 0.0)) for k in range(2))
    except np.linalg.LinAlgError:
        ln_tau_se, beta_se = math.inf, math.inf
    return {"tau": tau, "beta": beta, "y_inf": y_inf, "y0": y0, "r2": 1.0 - sse / spread if spread > 0 else 1.0,
            "rms": math.sqrt(sse / t.size), "tau_se": tau * ln_tau_se, "beta_se": beta_se}


@validate_call(config=_CALL_CONFIG)
def sampling_summary(
    d: RunData,
    *,
    y: str | None = None,
    fit: FitModel = "none",
    t_min: float | None = None,
    t_max: float | None = None,
    edge: int = Field(default=DEFAULT_EDGE, ge=1, le=10_000),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Statistics (and optionally the stretched-exponential relaxation) of one column of a sampling run (module
    docstring): ``initial``, ``final``, ``mean``, ``std``, ``drift`` [+ ``tau``, ``beta``, ``y_inf``]."""
    policy = trust_policy(criteria)
    _time_column(d, "sampling_summary")
    y = _default_y(d, y, "sampling_summary")
    unit = d.unit(y)
    t, values, levels, reasons, usable = _rows_in_window(d, y, policy, t_min, t_max)
    out = Results("sampling_summary", {"y": y, "fit": fit, "t_min": t_min, "t_max": t_max, "edge": edge,
                                       "force": force, "trust_policy": policy_params(policy)})
    excluded = excluded_counts(reasons)
    names = ["initial", "final", "mean", "std", "drift"] + (["tau", "beta", "y_inf"] if fit == "stretched_exp"
                                                              else [])
    units: dict[str, Unit] = {"initial": unit, "final": unit, "mean": unit, "std": unit, "drift": "1", "tau": "s",
                              "beta": "1", "y_inf": unit}
    untrusted = reasons[(levels == "untrusted").to_numpy()]
    if len(untrusted) and not force:
        letters = ", ".join(f"{k}: {v}" for k, v in excluded_counts(untrusted).items())
        problem = [f"{len(untrusted)} untrusted point(s) in {y} ({letters})"]
        return [out.refused(name, units[name], problem, excluded=excluded) for name in names]
    if len(untrusted):
        out.flag([f"{len(untrusted)} untrusted point(s) in {y}"])
    ts, ys = t[usable], values[usable]
    order = np.argsort(ts, kind="stable")
    ts, ys = ts[order], ys[order]
    if ys.size < 2:
        return [out.failed(name, units[name], f"fewer than 2 trusted points of {y} in the window",
                           excluded=excluded) for name in names]
    k = max(1, min(edge, ys.size // 10 or 1))
    initial, final = float(np.median(ys[:k])), float(np.median(ys[-k:]))
    window = window_of(ts, "s")
    common = {"excluded": excluded, "points_used": int(ys.size), "window": window}
    fit_info = {"t_first_s": float(ts[0]), "t_last_s": float(ts[-1]), "edge_points": k}
    results = [
        out.ok("initial", initial, unit, fit=fit_info, **common),
        out.ok("final", final, unit, fit=fit_info, **common),
        out.ok("mean", float(np.mean(ys)), unit, **common),
        out.ok("std", float(np.std(ys, ddof=1)), unit, **common),
    ]
    if initial != 0:
        results.append(out.ok("drift", (final - initial) / abs(initial), "1", fit=fit_info, **common))
    else:
        results.append(out.failed("drift", "1", "the initial value is 0; the relative drift is undefined",
                                  excluded=excluded))
    if fit == "stretched_exp":
        try:
            p = fit_stretched_exponential(ts, ys)
        except ValueError as exc:
            results += [out.failed(name, units[name], str(exc), excluded=excluded) for name in ("tau", "beta",
                                                                                                "y_inf")]
            return results
        warnings = []
        if p["tau"] > 3.0 * float(ts[-1]):
            warnings.append(f"tau {p['tau']:.3g} s lies beyond 3x the last time {ts[-1]:.3g} s: poorly "
                            "constrained; sample longer.")
        if not BETA_GRID[0] + 0.01 < p["beta"] < BETA_GRID[1] - 0.01:
            warnings.append(f"beta {p['beta']:.3g} sits at the edge of the searched range {list(BETA_GRID)}.")
        details = {"y0": p["y0"], "y_inf": p["y_inf"], "r2": p["r2"], "rms": p["rms"], "tau_se": p["tau_se"],
                   "beta_se": p["beta_se"]}
        results += [out.ok("tau", p["tau"], "s", fit=details, warnings=warnings, **common),
                    out.ok("beta", p["beta"], "1", fit=details, warnings=warnings, **common),
                    out.ok("y_inf", p["y_inf"], unit, fit=details, warnings=warnings, **common)]
    return results


# -- time_to_breakdown -----------------------------------------------------------------------------------------------

BD_COMPLIANCE, BD_JUMP, BD_THRESHOLD = 1, 2, 3


@validate_call(config=_CALL_CONFIG)
def time_to_breakdown(
    d: RunData,
    *,
    y: str | None = None,
    jump_factor: float = Field(default=10.0, gt=1.0, le=1e9),
    window: int = Field(default=5, ge=1, le=1000),
    i_bd_a: float | None = Field(default=None, gt=0),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Time to breakdown under constant stress (module docstring). One ``ExtractionResult`` ``t_bd`` (s)."""
    policy = trust_policy(criteria)
    t_all = _time_column(d, "time_to_breakdown")
    y = _default_y(d, y, "time_to_breakdown")
    out = Results("time_to_breakdown", {"y": y, "jump_factor": jump_factor, "window": window, "i_bd_a": i_bd_a,
                                        "force": force, "trust_policy": policy_params(policy)})
    table = d.table
    order = np.argsort(t_all, kind="stable")
    t = t_all[order]
    values = table[y].to_numpy(dtype=float)[order]
    status = table[status_column(y)].astype(str).to_numpy()[order]
    levels = trust_levels(table, policy, columns=[y]).to_numpy()[order]
    finite = np.isfinite(t) & np.isfinite(values)
    magnitude = np.abs(values)
    found: tuple[int, int] | None = None
    history: list[float] = []
    for position in range(t.size):
        if not finite[position]:
            continue
        if status[position] == "C":
            found = (position, BD_COMPLIANCE)
            break
        if i_bd_a is not None and magnitude[position] >= i_bd_a and levels[position] != "untrusted":
            found = (position, BD_THRESHOLD)
            break
        if len(history) >= window and levels[position] != "untrusted":
            reference = float(np.median(history[-window:]))
            if reference > 0 and magnitude[position] >= jump_factor * reference:
                found = (position, BD_JUMP)
                break
        if levels[position] == "ok":
            history.append(float(magnitude[position]))
    end = found[0] if found is not None else t.size
    before = levels[:end] == "untrusted"
    excluded = {"after_breakdown": int(t.size - end - 1)} if found is not None and t.size - end - 1 > 0 else {}
    if before.any():
        letters = sorted(set(status[:end][before]))
        problem = [f"{int(before.sum())} untrusted point(s) before the breakdown sample ({', '.join(letters)})"]
        if not force:
            return out.refused("t_bd", "s", problem, excluded=excluded)
        out.flag(problem)
    used = int(np.count_nonzero(finite[:end] & (levels[:end] != "untrusted"))) + (1 if found else 0)
    if found is None:
        trusted = np.flatnonzero(finite & (levels != "untrusted"))
        if not trusted.size:
            return out.failed("t_bd", "s", f"no trusted sample of {y}", excluded=excluded)
        last = int(trusted[-1])
        return out.ok("t_bd", float(t[last]), "s", excluded=excluded, points_used=used, bound="lower",
                      classification="no_breakdown",
                      fit={"t_last_s": float(t[last]), "i_last_a": float(values[last])},
                      warnings=[f"no breakdown within {t[last]:.6g} s: the life is longer (right-censored)."])
    position, criterion = found
    previous = np.flatnonzero(finite[:position])
    t_prev = float(t[previous[-1]]) if previous.size else 0.0
    fit = {"criterion": float(criterion), "t_prev_s": t_prev, "resolution_s": float(t[position]) - t_prev,
           "i_at_bd_a": float(values[position])}
    if previous.size:
        fit["i_before_bd_a"] = float(values[previous[-1]])
    if history:
        fit["i_initial_a"] = float(history[0])
    warnings = [] if previous.size else [(
        "breakdown at the first sample: the site may have been broken or leaky before the stress (check it with a "
        "low-voltage leakage measurement); t_bd is at most this time.")]
    return out.ok("t_bd", float(t[position]), "s", excluded=excluded, points_used=used, classification="breakdown",
                  window=window_of(np.array([t_prev, float(t[position])]), "s"), fit=fit, warnings=warnings)


# -- weibull_fit -----------------------------------------------------------------------------------------------------


def _weibull_mle(times: np.ndarray, failed: np.ndarray) -> tuple[float, float, float, float]:
    """``(beta, eta, log-likelihood, beta standard error)`` of the right-censored two-parameter Weibull MLE."""
    logs = np.log(times)
    r = int(failed.sum())
    mean_log_f = float(logs[failed].mean())

    def score(beta: float) -> float:
        weights = np.exp(beta * (logs - logs.max()))
        return 1.0 / beta + mean_log_f - float((weights * logs).sum() / weights.sum())

    lo, hi = 0.01, 100.0
    if score(lo) < 0 or score(hi) > 0:
        raise ValueError("the Weibull likelihood has no maximum in beta 0.01-100 (identical failure times?)")
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if score(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1 + 1e-12:
            break
    beta = math.sqrt(lo * hi)
    eta = float((np.power(times, beta).sum() / r) ** (1.0 / beta))
    z = np.power(times / eta, beta)
    loglik = float(r * math.log(beta) - r * beta * math.log(eta) + (beta - 1.0) * logs[failed].sum() - z.sum())
    # observed information of beta with eta profiled out (Fisher approximation for the standard error)
    h = beta * 1e-4

    def profile(b: float) -> float:
        e = float((np.power(times, b).sum() / r) ** (1.0 / b))
        return float(r * math.log(b) - r * b * math.log(e) + (b - 1.0) * logs[failed].sum()
                     - np.power(times / e, b).sum())

    curvature = (profile(beta + h) - 2.0 * loglik + profile(beta - h)) / (h * h)
    se = math.sqrt(-1.0 / curvature) if curvature < 0 else math.inf
    return beta, eta, loglik, se


def weibull_fit(
    runs: Sequence[RunData] = (),
    *,
    times_s: Sequence[float] | None = None,
    censored: Sequence[bool] | None = None,
    method: Literal["mle", "rank"] = "mle",
    criteria: TrustPolicy | None = None,
    **options: Any,
) -> list[ExtractionResult]:
    """Weibull ``beta`` and ``eta`` of breakdown times (module docstring): from ``runs`` (``time_to_breakdown`` with
    ``options``) or from ``times_s`` with optional ``censored`` flags. Returns ``weibull_beta`` and ``weibull_eta``.

    Raises:
        InvalidInputError: Neither or both of ``runs`` and ``times_s``, mismatched ``censored``, a bad time.
    """
    if bool(runs) == (times_s is not None):
        raise InvalidInputError("weibull_fit needs either runs or times_s (not both).")
    out = Results("weibull_fit", {"method": method, "runs": [r.run_id for r in runs], "options": options,
                                  "source": "runs" if runs else "times_s"})
    times: list[float] = []
    flags: list[bool] = []
    if runs:
        for run in runs:
            result = time_to_breakdown(run, criteria=criteria, **options)
            if result.outcome != "ok" or result.value is None:
                out.warnings.append(f"run {run.run_id} left out: {result.error}")
                continue
            times.append(result.value)
            flags.append(result.classification == "no_breakdown")
    else:
        assert times_s is not None
        times = [float(v) for v in times_s]
        flags = [False] * len(times) if censored is None else [bool(c) for c in censored]
        if len(flags) != len(times):
            raise InvalidInputError("censored must have one flag per time.")
    array = np.asarray(times, dtype=float)
    if array.size and (not np.all(np.isfinite(array)) or np.any(array <= 0)):
        raise InvalidInputError("breakdown times must be finite and positive.")
    failed = ~np.asarray(flags, dtype=bool)
    counts = {"n": float(array.size), "failures": float(failed.sum()), "censored": float((~failed).sum())}
    if int(failed.sum()) < 2:
        return [out.failed(name, unit, f"{int(failed.sum())} failure(s): at least 2 are needed", excluded={},
                           fit=counts) for name, unit in (("weibull_beta", "1"), ("weibull_eta", "s"))]
    if method == "rank":
        if (~failed).any():
            problem = [f"{int((~failed).sum())} censored time(s): median ranks need complete data (use mle)"]
            return [out.refused(name, unit, problem, excluded={}, fit=counts)
                    for name, unit in (("weibull_beta", "1"), ("weibull_eta", "s"))]
        ordered = np.sort(array)
        ranks = (np.arange(1, ordered.size + 1) - 0.3) / (ordered.size + 0.4)
        slope, intercept, r2 = line_fit(np.log(ordered), np.log(-np.log(1.0 - ranks)))
        beta, eta = slope, math.exp(-intercept / slope)
        details = {**counts, "r2": r2}
    else:
        try:
            beta, eta, loglik, se = _weibull_mle(array, failed)
        except ValueError as exc:
            return [out.failed(name, unit, str(exc), excluded={}, fit=counts)
                    for name, unit in (("weibull_beta", "1"), ("weibull_eta", "s"))]
        details = {**counts, "loglik": loglik, "beta_se": se}
    used = int(array.size)
    return [out.ok("weibull_beta", beta, "1", excluded={}, points_used=used, fit=details),
            out.ok("weibull_eta", eta, "s", excluded={}, points_used=used, fit=details)]
