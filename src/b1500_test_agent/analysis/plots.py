"""Headless plotting helpers (matplotlib object API on an Agg canvas; blueprint 2.8 ``plot_iv`` is declared for M2).

Never imports ``matplotlib.pyplot`` and never switches the global backend: figures are built with
``matplotlib.figure.Figure`` and rendered by ``FigureCanvasAgg``, so plotting works without a display (CI, lab PC
services, Windows) and does not disturb an interactive session of the caller. PNG files go to the caller's
directory (``work/<run_id>/`` for agent scripts; run folders are written only by the server).
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


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
