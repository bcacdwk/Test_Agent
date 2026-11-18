"""Reliability and time-domain analysis (blueprint v2 2.10 ``reliability.py``). WP5.7 adds the time-series plot
``plot_timeseries``; the reliability methods of M7 (``sampling_summary``, ``time_to_breakdown``, ``weibull_fit``,
``bti_power_law``, ``degradation_vs_time``, ``silc``, ``fast_bti_shift``) join this module.

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
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import trust_policy
from b1500_test_agent.analysis.dataset import (
    CYCLE,
    EVENT,
    PHASE,
    SEGMENT,
    STEP,
    T_S,
    RunData,
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
from b1500_test_agent.models.analysis import TrustPolicy

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
