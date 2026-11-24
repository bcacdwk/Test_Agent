"""Quasi-static C-V (QSCV) runs (blueprint v2 2.10; WP8.5): recognising a ``smu_qscv`` table, loading its trusted
curve and plotting it. ``cv.py`` uses these so ``cv_cox`` and ``plot_cv`` serve QSCV runs; ``dit.py`` builds the
high-low Dit on them. The definitions are the source of knowledge file ``08-capacitance-cv.md`` (skill
``b1500-test``); change both together.

**Data.** A QSCV run table (kind ``smu_qscv``, ``moscap.qscv``) holds ``dc_v`` (the step voltage the SMU reports),
``<role>_Cp`` (the quasi-static capacitance ``C = (I - Leak) cinteg / (V - V0)``, F; leakage-compensated by the
instrument with ``leakage: compensate``) with its status, optionally ``<role>_I`` (the leakage current) and ``segment``
of a double sweep; no ``freq_hz`` (no frequency) and no second MFCMU quantity. Its capacitance is the low-frequency
(LF) capacitance: interface traps and the inversion layer follow the slow ramp. Trust follows the shared rules: SMU
status ``C``/``T`` (compliance), ``V`` (range overflow or the dummy data after an automatic abort) and ``X`` are
untrusted under the recipe's policy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from b1500_test_agent.analysis.common import Rows, analysed_rows, trust_policy
from b1500_test_agent.analysis.dataset import DC_V, FREQ_HZ, SEGMENT, RunData, Segment, parse_value_column, trust_levels
from b1500_test_agent.analysis.plots import INVALID_ABOVE, PlotSet, RenderedPlot, figure_png, new_figure
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import TrustPolicy

MFCMU_SECONDARY = frozenset({"G", "Rs", "D", "theta"})
"""Second quantities of the MFCMU pairs: a run with one of them is an MFCMU run, not a QSCV run."""

QUASI_STATIC_HINT = ("a quasi-static (QSCV) run: cv_cox, dit_high_low and plot_cv apply; flatband, doping, threshold "
                     "and hysteresis need a high-frequency C-V (moscap.cv)")


def qscv_offset_run(d: RunData) -> bool:
    """True for the one-row table of a QSCV offset measurement (``moscap.qscv`` with ``offset: measure``):
    ``<role>_Cp`` without ``dc_v`` or ``freq_hz``; it holds the path's offset, no curve."""
    if FREQ_HZ in d.table.columns or DC_V in d.table.columns:
        return False
    return any((parsed := parse_value_column(c)) is not None and parsed[1] == "Cp" for c in d.measured_columns)


def quasi_static_role(d: RunData) -> str | None:
    """The role of a QSCV run's capacitance column (module docstring), ``None`` for any other run."""
    if FREQ_HZ in d.table.columns or DC_V not in d.table.columns:
        return None
    found: dict[str, set[str]] = {}
    for column in d.measured_columns:
        parsed = parse_value_column(column)
        if parsed is not None:
            found.setdefault(parsed[0], set()).add(parsed[1])
    roles = [role for role, quantities in found.items() if "Cp" in quantities and not quantities & MFCMU_SECONDARY]
    return roles[0] if len(roles) == 1 else None


def qscv_rows(d: RunData, policy: TrustPolicy, *, segment: Segment | None) -> tuple[str, Rows]:
    """The role and the analysed rows (``dc_v`` against ``<role>_Cp``) of one segment of a QSCV run (``None``: all
    rows; a single sweep has no segments).

    Raises:
        InvalidInputError: If ``d`` is not a QSCV run.
    """
    role = quasi_static_role(d)
    if role is None:
        raise InvalidInputError(f"run {d.run_id} ({d.manifest.recipe_id}) is not a quasi-static C-V run (dc_v and "
                                "<role>_Cp without freq_hz)")
    rows = d.rows(segment) if segment is not None and d.has_segments else d.table
    return role, analysed_rows(d, DC_V, f"{role}_Cp", policy, rows=rows)


def qscv_curve(d: RunData, policy: TrustPolicy, *, segment: Segment | None) -> tuple[Rows, np.ndarray, np.ndarray,
                                                                                    list[str]]:
    """The trusted points of one segment as ``(rows, v, c, problems)``, sorted by bias; ``problems`` lists why an
    extraction must be refused (untrusted points)."""
    role, rows = qscv_rows(d, policy, segment=segment)
    v = rows.rows[DC_V].to_numpy(dtype=float)[rows.ok]
    c = rows.rows[f"{role}_Cp"].to_numpy(dtype=float)[rows.ok]
    order = np.argsort(v, kind="stable")
    return rows, v[order], c[order], rows.problems(f"{role}_Cp (QSCV)", noise=False)


def render_qscv(d: RunData, *, criteria: TrustPolicy | None = None) -> PlotSet:
    """The QSCV plot: C against ``dc_v`` per segment and, with leakage data, the leakage current (semilog |I|);
    trusted points as lines, limited as circles, untrusted as crosses. Never refuses, never extracts."""
    policy = trust_policy(criteria)
    role = quasi_static_role(d)
    if role is None:
        raise InvalidInputError(f"run {d.run_id} is not a quasi-static C-V run")
    table = d.table
    levels = trust_levels(table, policy).to_numpy()
    leak = f"{role}_I"
    panels = [(f"{role}_Cp", "C quasi-static (F)", False)]
    if leak in table.columns:
        panels.append((leak, "|leakage| (A)", True))
    segments = list(pd.unique(table[SEGMENT])) if SEGMENT in table.columns else [None]
    x = table[DC_V].to_numpy(dtype=float)
    figure = new_figure(width_in=6.5, height_in=3.2 * len(panels))
    skipped = 0
    for index, (column, label, log) in enumerate(panels):
        axes = figure.add_subplot(len(panels), 1, index + 1)
        y = table[column].to_numpy(dtype=float)
        for segment in segments:
            mask = np.ones(len(table), dtype=bool) if segment is None else (table[SEGMENT] == segment).to_numpy()
            yv = np.abs(y) if log else y
            positive = (yv > 0) if log else np.ones(len(table), dtype=bool)
            drawable = mask & np.isfinite(x) & np.isfinite(yv) & (np.abs(y) < INVALID_ABOVE) & positive
            skipped += int((mask & ~drawable).sum())
            ok = drawable & (levels == "ok")
            line = axes.plot(x[ok], yv[ok], "-", linewidth=1.2, label=segment)
            for level, marker in (("limited", "o"), ("untrusted", "x")):
                pick = drawable & (levels == level)
                if pick.any():
                    axes.plot(x[pick], yv[pick], marker, mfc="none", color=line[0].get_color(), markersize=5)
        if log:
            axes.set_yscale("log")
        axes.set_xlabel(f"{DC_V} (V)")
        axes.set_ylabel(label)
        axes.grid(True, alpha=0.3)
        if len(segments) > 1:
            axes.legend(fontsize=7)
    title = f"{d.run_id} {d.manifest.recipe_id} QSCV ({'SIMULATED' if d.manifest.simulated else 'measured'})"
    figure.suptitle(title, fontsize=9)
    warnings = (f"{skipped} point(s) not drawn (invalid data)",) if skipped else ()
    return PlotSet(plots=(RenderedPlot(name="qscv", png=figure_png(figure)),), x=DC_V,
                   y=tuple(column for column, _, _ in panels), scale="linear", warnings=warnings)


__all__ = ["QUASI_STATIC_HINT", "qscv_curve", "qscv_offset_run", "qscv_rows", "quasi_static_role", "render_qscv"]
