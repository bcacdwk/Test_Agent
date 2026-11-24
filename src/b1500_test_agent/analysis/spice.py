"""SPICE export of a compact model (blueprint v2 2.10 ``export_spice_netlist``, WP7.7; OD-6: running a simulator is
not part of v2, the files are for the human to run).

Definitions (the single source of the section "SPICE export" of knowledge file ``07-compact-models.md``; change both
together):

- **Files.** Two text files: ``<stem>.lib``, the model alone (a level-1 ``.model`` card, or the EKV model as a
  behavioural ``.subckt``) for reuse in other circuits, and ``<stem>.sp``, a self-contained netlist (title line,
  the same model inline, one device, one DC voltage source per driven terminal, a ``.dc`` statement reproducing the
  run's sweep, ``.print dc`` of the drain-source current, ``.end``). The server stores them as
  ``analysis/<stem>-<n>.lib|.sp`` in the run folder; agent scripts write them with ``write_spice_files`` under
  ``work/<run_id>/spice/``.
- **Level 1** is the standard card ``.model <name> NMOS|PMOS (LEVEL=1 VTO=... KP=... LAMBDA=... GAMMA=0 PHI=0.6)``
  with ``M1 d g s b <name> W=... L=...``: ``KP = beta L/W`` with the given geometry, else ``W = L = 1u`` and
  ``KP = beta`` (stated in the file).
- **EKV** has no portable built-in card (EKV 2.6 levels differ between simulators and derive the slope factor from
  GAMMA/PHI), so it is exported as a subcircuit ``<name> d g s b`` with the equations of ``model.py`` in one
  behavioural current source between the internal drain and source nodes (``rs`` resistors to ``d`` and ``s`` when
  ``rs > 0``): ngspice ``B1 di si I=...`` with ``ln``, HSPICE ``G1 di si CUR='...'`` with ``log`` (natural
  logarithm in both). Parameter values are written into the expression as numbers (no ``.param`` scoping
  differences). A p-channel model mirrors every voltage and drives the current from ``si`` to ``di``.
- **Sweep.** The run's swept terminal (most changes between rows) is the inner ``.dc`` source; a stepped terminal
  (Id-Vd family, Vd steps, body bias) the outer one; both must be uniform grids (start, stop, step from the table;
  a double sweep uses its forward segment). Constant terminals get their DC value; a missing source column is the
  GNDU (0 V); a missing bulk column ties the bulk to the source. A synchronous or logarithmic sweep cannot be written
  as ``.dc`` and fails the export (fit and comparison still work).
- ``I(VD)`` is the current through the drain source from its ``+`` node (the simulator's sign); the measured drain
  current is ``-I(VD)``. The files carry the run id, recipe, backend (SIMULATED for ``sim``), the fit and its RMS
  error: the model is derived, never a measurement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from b1500_test_agent.analysis.dataset import RunData, work_dir_for
from b1500_test_agent.models.analysis import ExtractionResult

if TYPE_CHECKING:
    from b1500_test_agent.analysis.model import CompactModel

Dialect = Literal["ngspice", "hspice"]
ROLES = ("gate", "drain", "source", "bulk")
"""Recipe roles of the four MOSFET terminals (their ``<role>_V`` columns hold the terminal voltages)."""
NODES = {"gate": "g", "drain": "d", "source": "s", "bulk": "b"}
UNIFORM_TOL = 1e-6
"""Relative tolerance of a uniform grid (step differences)."""

MAX_LINE = 100


class SweepError(ValueError):
    """The run's sweep cannot be written as a ``.dc`` statement."""


@dataclass(frozen=True)
class ExportFile:
    """One exported text file: ``suffix`` (``.lib`` or ``.sp``) and its text (LF line ends)."""

    suffix: str
    text: str


@dataclass(frozen=True)
class SpiceExport:
    """The output of ``export_spice_netlist``: the files for the archive to store under ``analysis/`` (never written
    here) and the results (the model's error on this run, or the refusal/failure)."""

    stem: str
    files: tuple[ExportFile, ...]
    results: list[ExtractionResult]


@dataclass(frozen=True)
class GridSweep:
    """A ``.dc`` sweep: source name, start, stop, step (``step`` 0 for a single level)."""

    terminal: str
    start: float
    stop: float
    step: float


@dataclass(frozen=True)
class SweepPlan:
    """The terminals of the netlist: inner and optional outer sweep, constant DC values, bulk tied to the source."""

    inner: GridSweep
    outer: GridSweep | None
    constants: dict[str, float]
    bulk_tied: bool


def num(value: float) -> str:
    """A SPICE number: shortest of 7 significant digits, exponent form allowed (``2e-05``)."""
    text = f"{value:.7g}"
    return "0" if text in ("-0", "0") else text


def _grid(values: Sequence[float], what: str) -> tuple[float, float, float]:
    levels = np.asarray(values, dtype=float)
    if levels.size == 1:
        return float(levels[0]), float(levels[0]), 0.0
    steps = np.diff(levels)
    step = float(np.median(steps))
    if step == 0 or np.max(np.abs(steps - step)) > UNIFORM_TOL * max(abs(step), np.max(np.abs(levels))):
        raise SweepError(f"{what} is not a uniform grid (steps {np.unique(np.round(steps, 9))[:4].tolist()}...); "
                         "a .dc statement needs equal steps (a synchronous or logarithmic sweep cannot be exported)")
    return float(levels[0]), float(levels[-1]), step


def sweep_plan(d: RunData, rows: pd.DataFrame, x: str, step: str | None) -> SweepPlan:
    """The ``.dc`` reproduction of ``rows`` (one segment of ``d``): ``x`` the inner sweep, ``step`` the outer one."""
    role_of = {f"{role}_V": role for role in ROLES}
    inner_role, outer_role = role_of[x], (role_of[step] if step is not None else None)
    if step is not None:
        levels = list(dict.fromkeys(rows[step].to_numpy(dtype=float).tolist()))
        curves = [rows[rows[step] == level][x].to_numpy(dtype=float) for level in levels]
        if any(c.size != curves[0].size or not np.allclose(c, curves[0], rtol=0, atol=1e-9) for c in curves[1:]):
            raise SweepError(f"the {x} sweep differs between the {step} levels; a nested .dc needs one inner grid")
        inner_values: Sequence[float] = curves[0].tolist()
        outer = GridSweep(NODES[outer_role or ""], *_grid(levels, step))  # type: ignore[index]
    else:
        inner_values = rows[x].to_numpy(dtype=float).tolist()
        outer = None
    inner = GridSweep(NODES[inner_role], *_grid(inner_values, x))
    constants: dict[str, float] = {}
    for role in ROLES:
        column = f"{role}_V"
        if role in (inner_role, outer_role) or column not in d.table.columns:
            continue
        values = rows[column].to_numpy(dtype=float)
        if values.size and np.ptp(values) > 1e-9:
            raise SweepError(f"{column} varies together with {x}: a synchronous sweep cannot be written as .dc")
        constants[NODES[role]] = float(values[0]) if values.size else 0.0
    if "source_V" not in d.table.columns:
        constants["s"] = 0.0
    return SweepPlan(inner=inner, outer=outer, constants=constants, bulk_tied="bulk_V" not in d.table.columns)


def _wrap(prefix: str, body: str, *, quote: str = "") -> list[str]:
    """``prefix`` + ``body`` split after ``*`` operators into lines of at most about ``MAX_LINE`` characters (``+``
    continuation lines; never inside a number such as ``1e-05`` or a name)."""
    tokens: list[str] = []
    current = ""
    for char in body:
        current += char
        if char == "*":
            tokens.append(current)
            current = ""
    tokens.append(current)
    lines: list[str] = []
    line = prefix + quote
    for token in tokens:
        if len(line) + len(token) > MAX_LINE and line.strip("+ "):
            lines.append(line)
            line = "+ "
        line += token
    lines.append(line + quote)
    return lines


def _ekv_expression(cm: CompactModel, dialect: Dialect, nodes: tuple[str, str, str]) -> str:
    """The EKV current (A) as a SPICE expression of the node voltages (n-type core; mirrored for p)."""
    p = cm.full_params()
    ut = cm.thermal_voltage
    ln = "ln" if dialect == "ngspice" else "log"
    g, di, si = nodes
    if cm.polarity == "n":
        vg, vd, vs = f"V({g},b)", f"V({di},b)", f"V({si},b)"
        vt0 = p["vt0"]
    else:  # mirrored: the n-type core sees -V and the threshold -vt0
        vg, vd, vs = f"V(b,{g})", f"V(b,{di})", f"V(b,{si})"
        vt0 = -p["vt0"]
    n, beta = p["n"], p["beta"]
    vp = f"(({vg}-({num(vt0)}))/{num(n)})"
    two_ut = num(2 * ut)
    forward = f"{ln}(1+exp(({vp}-{vs})/{two_ut}))"
    reverse = f"{ln}(1+exp(({vp}-{vd})/{two_ut}))"
    ispec = num(2 * n * beta * ut * ut)
    vov = f"{num(2 * n * ut)}*{ln}(1+exp(({vg}-({num(vt0)})-{num(n)}*min({vs},{vd}))/{num(2 * n * ut)}))"
    return (f"{ispec}*({forward}*{forward}-{reverse}*{reverse})*(1+{num(p['lambda'])}*abs({vd}-{vs}))"
            f"/(1+{num(p['theta'])}*{vov})")


def model_name(cm: CompactModel) -> str:
    return f"{cm.polarity}ch_{cm.model}"


def model_lines(cm: CompactModel, dialect: Dialect, *, w_um: float | None, l_um: float | None) -> list[str]:
    """The model alone: the level-1 ``.model`` card or the EKV ``.subckt``."""
    p = cm.full_params()
    name = model_name(cm)
    if cm.model == "level1":
        kp = p["beta"] * (l_um / w_um) if w_um and l_um else p["beta"]
        kind = "NMOS" if cm.polarity == "n" else "PMOS"
        return [f".model {name} {kind} (LEVEL=1 VTO={num(p['vto'])} KP={num(kp)} LAMBDA={num(p['lambda'])}",
                "+ GAMMA=0 PHI=0.6)"]
    rs = p["rs"]
    di, si = ("di", "si") if rs > 0 else ("d", "s")
    lines = [f".subckt {name} d g s b"]
    if rs > 0:
        lines += [f"RD d di {num(rs)}", f"RS s si {num(rs)}"]
    expression = _ekv_expression(cm, dialect, ("g", di, si))
    plus, minus = (di, si) if cm.polarity == "n" else (si, di)
    if dialect == "ngspice":
        lines += _wrap(f"B1 {plus} {minus} I=", expression)
    else:
        lines += _wrap(f"G1 {plus} {minus} CUR=", expression, quote="'")
    lines.append(f".ends {name}")
    return lines


def _header(cm: CompactModel, d: RunData, quality: dict[str, float], fitted: bool, dialect: Dialect) -> list[str]:
    p = cm.full_params()
    backend = d.manifest.backend
    flag = "SIMULATED data" if backend == "sim" else "hardware data"
    params = " ".join(f"{k}={num(v)}" for k, v in p.items())
    source = "fitted by compact_model_fit to this run" if fitted else "parameters given to export_spice_netlist"
    return [
        f"* b1500-test-agent compact model export ({cm.model}, {dialect}); derived values, not measurements",
        f"* run {d.run_id}, recipe {d.manifest.recipe_id}, backend {backend} ({flag})",
        f"* {source}: {params}; polarity {cm.polarity}; T = {num(cm.temperature_k)} K",
        (f"* error on this run: rms_rel {num(quality.get('rms_rel', float('nan')))}, rms_log "
         f"{num(quality.get('rms_log', float('nan')))} decades over {int(quality.get('points', 0))} points"),
    ]


def render_files(cm: CompactModel, d: RunData, plan: SweepPlan, *, dialect: Dialect, quality: dict[str, float],
                 fitted: bool, w_um: float | None, l_um: float | None) -> tuple[ExportFile, ExportFile]:
    """The ``.lib`` and ``.sp`` texts (module docstring)."""
    header = _header(cm, d, quality, fitted, dialect)
    model = model_lines(cm, dialect, w_um=w_um, l_um=l_um)
    if cm.model == "level1" and not (w_um and l_um):
        model.insert(0, "* no geometry given: W = L = 1u, KP = beta")
    lib = "\n".join([*header, *model]) + "\n"
    name = model_name(cm)
    bulk = "s" if plan.bulk_tied else "b"
    if cm.model == "level1":
        w, length = (f"{num(w_um)}u", f"{num(l_um)}u") if w_um and l_um else ("1u", "1u")
        device = f"M1 d g s {bulk} {name} W={w} L={length}"
    else:
        device = f"X1 d g s {bulk} {name}"
    sources = []
    driven = {plan.inner.terminal: plan.inner.start}
    if plan.outer is not None:
        driven[plan.outer.terminal] = plan.outer.start
    for node in ("g", "d", "s", "b"):
        if node == "b" and plan.bulk_tied:
            continue
        if node in driven:
            sources.append(f"V{node.upper()} {node} 0 DC {num(driven[node])}")
        elif node in plan.constants:
            sources.append(f"V{node.upper()} {node} 0 DC {num(plan.constants[node])}")
    dc = (f".dc V{plan.inner.terminal.upper()} {num(plan.inner.start)} {num(plan.inner.stop)} "
          f"{num(plan.inner.step or 1.0)}")
    if plan.outer is not None:
        dc += (f" V{plan.outer.terminal.upper()} {num(plan.outer.start)} {num(plan.outer.stop)} "
               f"{num(plan.outer.step or 1.0)}")
    title = f"{name} reproduces run {d.run_id} ({d.manifest.recipe_id})"
    netlist = [title, *header, "* the measured drain current is -I(VD)", *model, device, *sources, dc,
               ".print dc I(VD)", ".end"]
    return ExportFile(".lib", lib), ExportFile(".sp", "\n".join(netlist) + "\n")


def write_spice_files(export: SpiceExport, out_dir: Path | str | None = None, *, run_id: str | None = None
                      ) -> list[Path]:
    """Write the files of ``export`` for an agent script: ``out_dir`` or ``work/<run_id>/spice/`` (never the run
    folder); returns the paths."""
    if out_dir is None:
        if run_id is None:
            raise ValueError("write_spice_files needs out_dir or run_id")
        out_dir = work_dir_for(run_id) / "spice"
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in export.files:
        path = folder / f"{export.stem}{item.suffix}"
        path.write_text(item.text, encoding="utf-8", newline="\n")
        paths.append(path)
    return paths
