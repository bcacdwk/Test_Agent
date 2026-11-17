"""Headless plotting (matplotlib object API on an Agg canvas) and the I-V plots of ``plot_iv`` (blueprint 2.8).

Never imports ``matplotlib.pyplot`` and never switches the global backend: figures are built with
``matplotlib.figure.Figure`` and rendered by ``FigureCanvasAgg``, so plotting works without a display (CI, lab PC
services, Windows) and does not disturb an interactive session of the caller.

``plot_iv`` (definition; the source of knowledge file ``06-analysis-extraction.md``): one figure per scale
(``linear``: I against V; ``log``: |I| on a log axis; ``both`` = the two), one panel per measured current column
(``y``: default all ``*_I`` measured columns), x = the swept source voltage (default the source voltage column that
varies most); a stepped run draws one curve per step level (the other varying source column), a double sweep one
line per segment. Trusted points are joined by lines; limited (``C``/``T``) points are drawn as open circles and
untrusted ones as crosses, so excluded data stay visible; invalid data (``199.999E+99``) and zero currents on a log
axis are left out and counted in the figure's note. Plots never refuse and never extract anything.

Where the files go: ``analyze_run``/``run_method("plot_iv", ...)`` returns a ``PlotSet`` (PNG bytes) that the server
stores through the archive as ``plots/<name>-<n>.png`` in the run folder; agent scripts call ``plot_iv`` with
``out_dir`` (default ``work/<run_id>/plots/``), because run folders are written only by the server.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from pydantic import ConfigDict, validate_call

from b1500_test_agent.analysis.common import trust_policy, varying_sources
from b1500_test_agent.analysis.dataset import SEGMENT, RunData, trust_levels, work_dir_for
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import TrustPolicy

PlotScale = Literal["linear", "log", "both"]
INVALID_ABOVE = 1e90
"""Values at or above this magnitude are the instrument's invalid-data marker (199.999E+99), never plotted."""

MAX_LEGEND = 12
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


def new_figure(*, width_in: float = 6.0, height_in: float = 4.0, dpi: int = 120) -> Figure:
    """A figure attached to an Agg canvas (``fig.add_subplot()`` to draw)."""
    figure = Figure(figsize=(width_in, height_in), dpi=dpi, layout="constrained")
    FigureCanvasAgg(figure)
    return figure


def save_figure(figure: Figure, path: Path) -> Path:
    """Render ``figure`` to a PNG file at ``path`` (parent directories are created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, format="png")
    return path


def figure_png(figure: Figure) -> bytes:
    """``figure`` rendered as PNG bytes."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return buffer.getvalue()


@dataclass(frozen=True)
class RenderedPlot:
    """One rendered PNG: ``name`` is the file stem (e.g. ``iv-log``)."""

    name: str
    png: bytes


@dataclass(frozen=True)
class PlotSet:
    """The output of ``plot_iv`` as a registered method: PNGs for the archive to store (never written here)."""

    plots: tuple[RenderedPlot, ...]
    x: str
    y: tuple[str, ...]
    scale: PlotScale
    warnings: tuple[str, ...] = ()


def _columns(d: RunData, x: str | None, y: list[str] | None) -> tuple[str, list[str], str | None]:
    sources = varying_sources(d.table, d)
    if x is None:
        if not sources:
            raise InvalidInputError(f"plot_iv: run {d.run_id} has no varying source voltage; pass x=<column>.")
        x = max(sources, key=lambda c: int(d.table[c].nunique()))
    d.unit(x)
    currents = [c for c in d.measured_columns if c.endswith("_I")] if y is None else list(y)
    if not currents:
        raise InvalidInputError(f"plot_iv: run {d.run_id} has no measured current column; pass y=[...].")
    for column in currents:
        if d.unit(column) != "A":
            raise InvalidInputError(f"plot_iv: {column} is not a current column.")
    steps = [c for c in sources if c != x]
    return x, currents, steps[0] if len(steps) == 1 else None


def render_iv(
    d: RunData,
    *,
    scale: PlotScale = "both",
    x: str | None = None,
    y: list[str] | None = None,
    criteria: TrustPolicy | None = None,
) -> PlotSet:
    """Render the I-V plots of ``d`` (module docstring) as PNG bytes; nothing is written."""
    policy = trust_policy(criteria)
    x, currents, step = _columns(d, x, y)
    table = d.table
    levels = trust_levels(table, policy).to_numpy()
    scales: list[Literal["linear", "log"]] = ["linear", "log"] if scale == "both" else [
        "log" if scale == "log" else "linear"]
    plots: list[RenderedPlot] = []
    warnings: list[str] = []
    for kind in scales:
        figure = new_figure(width_in=6.0, height_in=3.2 * len(currents))
        skipped = 0
        for panel, column in enumerate(currents):
            axes = figure.add_subplot(len(currents), 1, panel + 1)
            groups = [("", np.ones(len(table), dtype=bool))]
            if step is not None:
                groups = [(f"{step} = {level:g} V", (table[step] == level).to_numpy())
                          for level in table[step].drop_duplicates()]
            if SEGMENT in table.columns:
                groups = [(f"{label} {segment}".strip(), mask & (table[SEGMENT] == segment).to_numpy())
                          for label, mask in groups for segment in table[SEGMENT].drop_duplicates()]
            for label, mask in groups:
                xv = table[x].to_numpy(dtype=float)[mask]
                yv = table[column].to_numpy(dtype=float)[mask]
                lv = levels[mask]
                yv = np.abs(yv) if kind == "log" else yv
                drawable = np.isfinite(xv) & np.isfinite(yv) & (np.abs(yv) < INVALID_ABOVE)
                if kind == "log":
                    drawable &= yv > 0
                skipped += int((~drawable).sum())
                ok = drawable & (lv == "ok")
                line = axes.plot(xv[ok], yv[ok], "-", linewidth=1.2, label=label or None)
                color = line[0].get_color()
                limited = drawable & (lv == "limited")
                untrusted = drawable & (lv == "untrusted")
                if limited.any():
                    axes.plot(xv[limited], yv[limited], "o", mfc="none", color=color, markersize=5)
                if untrusted.any():
                    axes.plot(xv[untrusted], yv[untrusted], "x", color=color, markersize=6)
            if kind == "log":
                axes.set_yscale("log")
            axes.set_xlabel(f"{x} (V)")
            axes.set_ylabel(f"|{column}| (A)" if kind == "log" else f"{column} (A)")
            axes.grid(True, which="both", alpha=0.3)
            if 1 < len(groups) <= MAX_LEGEND:
                axes.legend(fontsize=7)
        title = f"{d.run_id} {d.manifest.recipe_id} ({'SIMULATED' if d.manifest.simulated else 'measured'})"
        figure.suptitle(title, fontsize=9)
        if skipped:
            note = f"{skipped} point(s) not drawn on the {kind} plot (invalid data or zero current on a log axis)."
            figure.text(0.01, 0.005, note, fontsize=6)
            warnings.append(note)
        plots.append(RenderedPlot(name=f"iv-{kind}", png=figure_png(figure)))
    return PlotSet(plots=tuple(plots), x=x, y=tuple(currents), scale=scale, warnings=tuple(warnings))


@validate_call(config=_CALL_CONFIG)
def plot_iv(
    d: RunData,
    *,
    scale: PlotScale = "both",
    x: str | None = None,
    y: list[str] | None = None,
    out_dir: Path | None = None,
    criteria: TrustPolicy | None = None,
) -> list[Path]:
    """Render the I-V plots of ``d`` (module docstring) into ``out_dir`` (default ``work/<run_id>/plots/``) and
    return the PNG paths. For agent scripts; ``analyze_run`` stores the plots in the run folder instead."""
    rendered = render_iv(d, scale=scale, x=x, y=y, criteria=criteria)
    target = out_dir if out_dir is not None else work_dir_for(d.run_id) / "plots"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for plot in rendered.plots:
        path = target / f"{plot.name}.png"
        path.write_bytes(plot.png)
        paths.append(path)
    return paths


@validate_call(config=_CALL_CONFIG)
def plot_iv_method(
    d: RunData,
    *,
    scale: PlotScale = "both",
    x: str | None = None,
    y: list[str] | None = None,
    criteria: TrustPolicy | None = None,
) -> PlotSet:
    """The registered ``plot_iv`` method: ``render_iv`` with JSON options; the caller stores the ``PlotSet``."""
    return render_iv(d, scale=scale, x=x, y=y, criteria=criteria)
