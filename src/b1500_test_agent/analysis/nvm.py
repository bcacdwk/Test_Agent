"""Non-volatile memory analysis of program/read runs (blueprint v2 2.10 ``nvm.py``) of kind ``pulse_read``: WP9.4
``memory_window_pulse`` (``fefet.pulse_write_read``, ``spgu.program_smu_read``); WP9.5 ``switching_kinetics_fit``
(``fefet.switching_kinetics``), ``endurance_summary`` (``fefet.endurance``) and ``retention_fit``
(``fefet.retention``).

Definitions (the single source of the sections "Program/read memory window", "Switching kinetics", "Endurance" and
"Retention" of knowledge file ``06b-analysis-time-pulse.md`` of skill ``b1500-test``; change both together):

- **Reads.** The run table of kind ``pulse_read`` has one group of rows per read, keyed by ``cycle`` and ``phase``:
  ``phase == "read"`` (cycle 0) is the reference read before any pulse; ``program`` / ``erase`` rows are the read
  that follows that operation (the *programmed* and *erased* state) in that cycle, endurance checkpoint (``cycle`` =
  the cumulative cycle count), grid point (``cycle`` = its index) or retention read (``cycle`` = its index after the
  write, ``t_s`` = its time after the write).
- **Per-read quantity** (``quantity``): ``vth`` = the threshold voltage of a staircase read (``x`` default ``gate_V``,
  else the only swept source column; ``y`` default ``drain_I``) by ``vth_method`` ``constant_current`` (default;
  ``i_crit_a`` x ``w_over_l``, 100 nA by default as in ``mosfet.py``, log10|Id| interpolated) or
  ``linear_extrapolation`` (max-gm tangent minus Vd/2); ``current`` = ``y`` at the read: the mean of a spot read's
  trusted samples, or a sweep's value at ``x = at_v`` (default: the plan parameter ``vg_read``). ``auto`` (default)
  takes ``vth`` when the reads sweep ``x``, else ``current``. Each read is judged like the method it uses: untrusted
  points refuse that read unless ``force`` (forced reads are flagged); limited (``C``/``T``) points never enter. A
  refused or failed read drops out with a warning; when every read of a state drops out its results are refused (or
  failed). The kinetics, endurance and retention methods use ``vth`` (staircase reads; spot reads are refused).
- **Memory window** (``vth``): ``MW = mean Vth(erase) - mean Vth(program)`` over the cycles (positive for an n-channel
  FeFET: a positive program pulse lowers Vth); ``fit`` holds the per-cycle windows' minimum, maximum and standard
  deviation over the cycles that have both reads (``cycles``) and the reference read's Vth. A negative window is
  flagged (the operations' polarity or naming). With one operation only (a program-only sequence) there is no window:
  the state's mean, first and last value are reported (cumulative programming).
- **Read window** (``current``): ``current_ratio = |I(program)| / |I(erase)|`` of the mean read currents (> 1 when the
  programmed state conducts more at the read level).
- **Switching kinetics** (``switching_kinetics_fit``; schedule ``grid``): the grid comes from the run manifest's plan
  program (``grid``: per point ``cycle``, ``level`` V, ``width`` s, ``row``; ``grid_mode``; the grid operation is
  the second of ``sequence``); a point's value is the Vth of the read after its grid pulse, the reads after the
  resets give ``vth_reset`` (mean, spread). ``grid_mode`` ``reset``: nucleation-limited switching (NLS; Tagantsev et
  al., Phys. Rev. B 66, 214109, 2002, not page-checked) fitted by least squares over every usable point,
  ``Vth(V, w) = V0 + A(V) (1 - exp(-(w / tau(V))^beta))`` with ``tau(V) = tau0 exp((Va / |V|)^alpha)``: ``V0`` (one
  start level) and ``A(V)`` (the switched window of each amplitude) enter linearly and are projected out; ``tau0``,
  ``Va``, ``beta`` (and ``alpha`` when the option ``alpha`` is null; default fixed at 2) by Levenberg-Marquardt from a
  start found amplitude by amplitude (a grid over ``tau``, ``beta``). Needs at least 2 amplitudes (3 with a free
  ``alpha``), 3 usable widths per amplitude and more points than parameters. An amplitude whose ``tau(V)`` lies
  outside the width span constrains the fit weakly (warning). ``grid_mode`` ``ispp``: per width row the cumulative
  ``dVth`` after each amplitude step from the row's start (its reset read, else the reference read); ``v50`` = the
  amplitude at which ``|dVth|`` reaches half the row's final ``|dVth|`` (linear interpolation; mean over the rows),
  ``ispp_slope`` = the largest ``|dVth step / amplitude step|`` (V/V); the NLS parameters need ``reset``.
- **Endurance** (``endurance_summary``; schedule ``cycles`` with checkpoint reads): per checkpoint ``N`` (the
  ``cycle`` of its reads) ``MW(N) = Vth(erase read) - Vth(program read)`` when both reads are usable. ``wake_up`` =
  ``MW_max / MW_initial - 1`` (the first checkpoint's window), ``fatigue`` = ``1 - MW_final / MW_max``,
  ``cycles_to_failure`` = the first cycle count after the maximum where MW falls below the criterion (``mw_fail`` V,
  else ``fail_fraction`` x ``MW_max``, default 0.5), interpolated linearly in ``log10 N`` between checkpoints; never
  reached: a lower bound at the last checkpoint.
- **Retention** (``retention_fit``; schedule ``retention``): per state the reads at ``t_s > 0`` (and ``>= t_min``),
  ``Vth = a + b log10(t / 1 s)`` by least squares: ``retention_slope_program``/``retention_slope_erase`` = ``b``
  (V/decade); ``MW(t) = Vth_erase - Vth_program`` of the reads with the same index (the same ``t_s``) fitted the
  same way: ``memory_window_slope``, ``memory_window_at_target`` (the fit at ``target_time_s``, default 10 years =
  3.156e8 s, a common non-volatile-memory convention: set it per product; a warning when that is more than two decades
  beyond the last read), ``retention_time`` (s: where the MW fit reaches ``mw_min`` V, else ``fail_fraction`` x the
  first read's MW, default 0.5; a window that does not decay gives a lower bound at the target time). Extrapolations
  are derived values, never measurements.

Results: ``memory_window_pulse``: ``vth``: ``memory_window`` (V, when both operations ran), ``vth_program``,
``vth_erase`` (V; ``fit``: ``first``, ``last``, ``std``, ``reads``) and ``vth_initial`` (V, the reference read);
``current``: ``i_program``, ``i_erase``, ``i_initial`` (A) and ``current_ratio`` (1, when both operations ran).
``switching_kinetics_fit``: ``tau0`` (s), ``beta`` (1), ``va`` (V), ``alpha`` (1, when fitted), ``vth_reset`` (V) or,
for ISPP, ``v50`` (V), ``ispp_slope`` (1) and ``vth_reset``. ``endurance_summary``: ``memory_window_initial``,
``memory_window_max``, ``memory_window_final`` (V), ``wake_up``, ``fatigue``, ``cycles_to_failure`` (1).
``retention_fit``: ``retention_slope_program``, ``retention_slope_erase``, ``memory_window_slope`` (V/dec),
``memory_window_at_target`` (V), ``retention_time`` (s). Every result is derived (``ExtractionResult``) with the
method, its parameters and the reads used; refusals and failures come back as results, never as exceptions
(``InvalidInputError`` only for unusable calls: not a ``pulse_read`` table, not the schedule the method needs, unknown
column, a sweep read without ``at_v``).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    interpolate,
    line_fit,
    policy_params,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.dataset import CYCLE, PHASE, T_S, RunData
from b1500_test_agent.analysis.mosfet import DEFAULT_I_CRIT_A, vth_constant_current, vth_linear_extrapolation
from b1500_test_agent.analysis.nls import fit_nls
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)

PulseQuantity = Literal["auto", "vth", "current"]
VthMethod = Literal["constant_current", "linear_extrapolation"]
State = Literal["initial", "program", "erase"]

READ_LEVEL_PARAM = "vg_read"
"""Plan parameter of the spot read level (the default ``at_v`` of ``current`` on sweep reads)."""


@dataclass
class PulseRead:
    """One read of a program/read run: its cycle, the state it reads and its rows."""

    cycle: int
    state: State
    rows: pd.DataFrame


@dataclass
class ReadValue:
    """A per-read quantity: ``value`` (``None`` when refused or failed: ``why``), forced, warnings, points used."""

    value: float | None
    why: str = ""
    refused: bool = False
    forced: bool = False
    points: int = 0
    warnings: list[str] = field(default_factory=list)


def pulse_reads(d: RunData, method: str) -> list[PulseRead]:
    """The reads of a ``pulse_read`` run in acquisition order (module docstring).

    Raises:
        InvalidInputError: If the run has no ``phase``/``cycle`` columns or no program/erase read.
    """
    table = d.table
    missing = [c for c in (PHASE, CYCLE) if c not in table.columns]
    if missing:
        raise InvalidInputError(f"{method}: run {d.run_id} has no {missing} column(s); it needs a program/read run "
                                "(kind pulse_read)")
    reads: list[PulseRead] = []
    keys = table[CYCLE].astype(int).astype(str) + "/" + table[PHASE].astype(str)
    for key in dict.fromkeys(keys):
        rows = table[keys == key]
        cycle, phase = key.split("/", 1)
        state: State = "initial" if phase == "read" else phase  # type: ignore[assignment]
        if state not in ("initial", "program", "erase"):
            raise InvalidInputError(f"{method}: run {d.run_id} has rows of phase {phase!r}; a program/read run has "
                                    "read, program and erase reads")
        reads.append(PulseRead(cycle=int(cycle), state=state, rows=rows))
    if not any(r.state != "initial" for r in reads):
        raise InvalidInputError(f"{method}: run {d.run_id} has no read after a program or erase pulse")
    return reads


def _swept(d: RunData, read: PulseRead, x: str) -> bool:
    return x in read.rows.columns and read.rows[x].nunique(dropna=True) > 1


def _vth(d: RunData, read: PulseRead, *, method: VthMethod, i_crit_a: float, w_over_l: float | None, x: str, y: str,
         force: bool, policy: TrustPolicy) -> ReadValue:
    sub = d.subset(read.rows)
    if not _swept(d, read, x):
        return ReadValue(None, why=f"the {read.state} read of cycle {read.cycle} does not sweep {x}")
    if method == "constant_current":
        found = vth_constant_current(sub, i_crit_a=i_crit_a, w_over_l=w_over_l, force=force, x=x, y=y,
                                     criteria=policy)
    else:
        found = vth_linear_extrapolation(sub, force=force, x=x, y=y, criteria=policy)
    if found.value is None:
        return ReadValue(None, why=f"cycle {read.cycle} {read.state}: {found.error or found.outcome}",
                         refused=found.outcome == "refused")
    return ReadValue(float(found.value), forced=found.forced_on_untrusted, points=found.points_used,
                     warnings=[f"cycle {read.cycle} {read.state}: {w}" for w in found.warnings])


def _current(d: RunData, read: PulseRead, *, x: str, y: str, at_v: float | None, force: bool,
             policy: TrustPolicy) -> ReadValue:
    sub = d.subset(read.rows)
    sweep = _swept(d, read, x)
    r = analysed_rows(sub, x if x in sub.table.columns else y, y, policy, segment=None)
    where = f"the {read.state} read of cycle {read.cycle}"
    problems = r.problems(where, noise=False)
    if problems and not force:
        return ReadValue(None, why="refused: " + "; ".join(problems), refused=True)
    forced = bool(problems)
    warnings = [f"forced on untrusted data in {where}"] if forced else []
    if r.size == 0:
        return ReadValue(None, why=f"{where}: no trusted point of {y}")
    if not sweep:
        return ReadValue(float(np.mean(r.ys)), forced=forced, points=int(r.size), warnings=warnings)
    if at_v is None:
        raise InvalidInputError(f"the reads sweep {x}: pass at_v=<volts> for the {y} value (or quantity vth)")
    found = interpolate(r.xs, r.ys, at_v)
    if found is None:
        return ReadValue(None, why=f"{where}: {x} = {at_v:g} V lies outside its trusted points")
    return ReadValue(found[0], forced=forced, points=int(r.size), warnings=warnings)


def _default_x(d: RunData, y: str) -> str:
    """``gate_V`` when present, else the only ``_V`` source column that varies (the read sweep)."""
    table = d.table
    if "gate_V" in table.columns:
        return "gate_V"
    swept = [c for c in table.columns if c.endswith("_V") and f"{c}_status" not in table.columns
             and table[c].nunique(dropna=True) > 1]
    return swept[0] if len(swept) == 1 else "gate_V"


@validate_call(config=_CALL_CONFIG)
def memory_window_pulse(
    d: RunData,
    *,
    quantity: PulseQuantity = "auto",
    vth_method: VthMethod = "constant_current",
    i_crit_a: float = Field(default=DEFAULT_I_CRIT_A, gt=0),
    w_over_l: float | None = Field(default=None, gt=0),
    at_v: float | None = None,
    x: str | None = None,
    y: str = "drain_I",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Memory window (or read-current window) of a program/read run (module docstring)."""
    policy = trust_policy(criteria)
    reads = pulse_reads(d, "memory_window_pulse")
    x_col = x or _default_x(d, y)
    for column in (x_col, y):
        if column not in d.table.columns and (column == y or quantity == "vth"):
            raise InvalidInputError(f"memory_window_pulse: run {d.run_id} has no column {column!r}")
    sweeps = any(_swept(d, r, x_col) for r in reads)
    chosen: Literal["vth", "current"] = ("vth" if sweeps else "current") if quantity == "auto" else quantity
    level = at_v
    if chosen == "current" and sweeps and level is None:
        param = d.param(READ_LEVEL_PARAM)
        level = float(param.value) if param is not None and isinstance(param.value, int | float) else None
    out = Results("memory_window_pulse", {
        "quantity": chosen, "vth_method": vth_method, "i_crit_a": i_crit_a, "w_over_l": w_over_l, "at_v": level,
        "x": x_col, "y": y, "force": force, "trust_policy": policy_params(policy)})
    if chosen == "vth":
        values = {id(r): _vth(d, r, method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x_col, y=y,
                              force=force, policy=policy) for r in reads}
        prefix, unit = "vth", "V"
    else:
        values = {id(r): _current(d, r, x=x_col, y=y, at_v=level, force=force, policy=policy) for r in reads}
        prefix, unit = "i", "A"
    out.warnings.extend(w for v in values.values() for w in v.warnings)
    out.warnings.extend(f"{r.state} read of cycle {r.cycle} left out: {values[id(r)].why}" for r in reads
                        if values[id(r)].value is None)
    if any(v.forced for v in values.values()):
        out.flag(["at least one read was extracted from untrusted data"])
    by_state: dict[State, list[tuple[int, ReadValue]]] = {"initial": [], "program": [], "erase": []}
    for r in reads:
        by_state[r.state].append((r.cycle, values[id(r)]))
    results: list[ExtractionResult] = []
    means: dict[State, float] = {}
    for state in ("program", "erase", "initial"):
        items = by_state[state]  # type: ignore[index]
        if not items:
            continue
        name = f"{prefix}_{state}"
        usable = [(c, v.value) for c, v in items if v.value is not None]
        if not usable:
            why = "; ".join(v.why for _, v in items)
            refused = all(v.refused for _, v in items)
            results.append(out.not_ok(name, unit, "refused" if refused else "failed",
                                      f"no usable {state} read: {why}", excluded={}))
            continue
        numbers = [v for _, v in usable]
        means[state] = float(np.mean(numbers))  # type: ignore[index]
        fit = {"reads": float(len(numbers)), "first": numbers[0], "last": numbers[-1]}
        if len(numbers) > 1:
            fit["std"] = float(np.std(numbers, ddof=1))
        results.append(out.ok(name, means[state], unit, excluded={},  # type: ignore[index]
                              points_used=sum(v.points for _, v in items if v.value is not None), fit=fit))
    if by_state["program"] and by_state["erase"]:
        results.insert(0, _window(out, chosen, by_state, means, unit))
    return results


def _window(out: Results, chosen: str, by_state: dict[State, list[tuple[int, ReadValue]]],
            means: dict[State, float], unit: Unit) -> ExtractionResult:
    """``memory_window`` (vth) or ``current_ratio`` (current) from the per-state means (module docstring)."""
    name: str = "memory_window" if chosen == "vth" else "current_ratio"
    result_unit: Unit = unit if chosen == "vth" else "1"
    if "program" not in means or "erase" not in means:
        return out.failed(name, result_unit, "no usable read of the program or of the erase state", excluded={})
    programs = {c: v.value for c, v in by_state["program"] if v.value is not None}
    erases = {c: v.value for c, v in by_state["erase"] if v.value is not None}
    both = sorted(set(programs) & set(erases))
    initial = [v.value for _, v in by_state["initial"] if v.value is not None]
    points = len(programs) + len(erases)
    if chosen == "vth":
        value = means["erase"] - means["program"]
        per_cycle = [erases[c] - programs[c] for c in both]
        fit: dict[str, float] = {"vth_program": means["program"], "vth_erase": means["erase"],
                                 "cycles": float(len(both))}
        if per_cycle:
            fit.update(mw_min=min(per_cycle), mw_max=max(per_cycle))
        if len(per_cycle) > 1:
            fit["mw_std"] = float(np.std(per_cycle, ddof=1))
        if initial:
            fit["vth_initial"] = initial[0]
        warnings = [] if value >= 0 else [
            ("Negative memory window: Vth after erase is below Vth after program. Check the pulse polarity (n-FeFET: "
             "positive program, negative erase) and the operation names.")]
        return out.ok(name, value, result_unit, excluded={}, points_used=points, fit=fit, warnings=warnings)
    if means["erase"] == 0:
        return out.failed(name, result_unit, "the erased-state read current is 0 A: the ratio is undefined",
                          excluded={})
    value = abs(means["program"]) / abs(means["erase"])
    return out.ok(name, value, result_unit, excluded={}, points_used=points,
                  fit={"i_program": means["program"], "i_erase": means["erase"], "cycles": float(len(both))})




# -- shared helpers of the schedule methods ---------------------------------------------------------------------------

YEAR_S = 3.15576e7
DEFAULT_TARGET_S = 10 * YEAR_S
"""Default retention target: 10 years."""


def _program(d: RunData) -> dict[str, Any]:
    """The run's compiled ``pulse_read`` program (the plan in the manifest)."""
    return dict(d.manifest.plan.program)


def _schedule(d: RunData, method: str, wanted: str, *, endurance: bool = False) -> dict[str, Any]:
    """The plan program of a ``pulse_read`` run of schedule ``wanted`` (endurance: ``cycles`` with checkpoints).

    Raises:
        InvalidInputError: For another kind or schedule.
    """
    program = _program(d)
    schedule = program.get("schedule", "cycles") if d.manifest.plan.kind == "pulse_read" else None
    ok = schedule == wanted and (not endurance or program.get("cycle_reads", "every") != "every")
    if not ok:
        need = "cycles with checkpoint reads (cycle_reads log or list)" if endurance else wanted
        raise InvalidInputError(f"{method}: run {d.run_id} is not a pulse_read run of schedule {need} (kind "
                                f"{d.manifest.plan.kind}, schedule {schedule})")
    return program


def _vths(d: RunData, reads: list[PulseRead], out: Results, *, vth_method: VthMethod, i_crit_a: float,
          w_over_l: float | None, x: str | None, y: str, force: bool, policy: TrustPolicy) -> dict[int, ReadValue]:
    """Vth of every read (``_vth``) by its position in ``reads``; warnings and the forced flag go to ``out``.

    Raises:
        InvalidInputError: For an unknown column.
    """
    x_col = x or _default_x(d, y)
    for column in (x_col, y):
        if column not in d.table.columns:
            raise InvalidInputError(f"{out.method}: run {d.run_id} has no column {column!r}")
    values = {i: _vth(d, r, method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x_col, y=y, force=force,
                      policy=policy) for i, r in enumerate(reads)}
    out.params["x"] = x_col
    out.warnings.extend(w for v in values.values() for w in v.warnings)
    out.warnings.extend(f"{r.state} read of cycle {r.cycle} left out: {values[i].why}" for i, r in enumerate(reads)
                        if values[i].value is None)
    if any(v.forced for v in values.values()):
        out.flag(["at least one read was extracted from untrusted data"])
    return values


def _base(method: str, policy: TrustPolicy, **params: Any) -> Results:
    return Results(method, {**params, "trust_policy": policy_params(policy)})


def _none_usable(out: Results, name: str, unit: Unit, values: list[ReadValue], what: str) -> ExtractionResult:
    why = "; ".join(v.why for v in values) or f"no {what}"
    refused = bool(values) and all(v.refused for v in values)
    return out.not_ok(name, unit, "refused" if refused else "failed", f"no usable {what}: {why}", excluded={})


# -- switching kinetics -----------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def switching_kinetics_fit(
    d: RunData,
    *,
    vth_method: VthMethod = "constant_current",
    i_crit_a: float = Field(default=DEFAULT_I_CRIT_A, gt=0),
    w_over_l: float | None = Field(default=None, gt=0),
    alpha: float | None = Field(default=2.0, ge=0.5, le=5.0),
    x: str | None = None,
    y: str = "drain_I",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """NLS switching kinetics of an amplitude x width grid run, or the ISPP step response (module docstring)."""
    policy = trust_policy(criteria)
    program = _schedule(d, "switching_kinetics_fit", "grid")
    grid = {int(p["cycle"]): p for p in program.get("grid", [])}
    sequence = list(program.get("sequence", []))
    if len(sequence) != 2 or not grid:
        raise InvalidInputError(f"switching_kinetics_fit: run {d.run_id} stores no grid (program grid/sequence)")
    reset_op, grid_op = sequence
    mode = str(program.get("grid_mode", "reset"))
    out = _base("switching_kinetics_fit", policy, vth_method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l,
                alpha=alpha, y=y, force=force, grid_mode=mode)
    reads = pulse_reads(d, "switching_kinetics_fit")
    values = _vths(d, reads, out, vth_method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x, y=y,
                   force=force, policy=policy)
    points = [(grid[r.cycle], values[i]) for i, r in enumerate(reads) if r.state == grid_op and r.cycle in grid]
    resets = [(r.cycle, values[i]) for i, r in enumerate(reads) if r.state == reset_op]
    initial = next((values[i].value for i, r in enumerate(reads) if r.state == "initial"), None)
    results: list[ExtractionResult] = []
    if mode == "ispp":
        results += _ispp(out, points, resets, initial)
    else:
        results += _nls(out, points, alpha)
    usable = [v.value for _, v in resets if v.value is not None]
    if usable:
        fit = {"reads": float(len(usable)), "min": min(usable), "max": max(usable)}
        if len(usable) > 1:
            fit["std"] = float(np.std(usable, ddof=1))
        results.append(out.ok("vth_reset", float(np.mean(usable)), "V", excluded={}, points_used=len(usable),
                              fit=fit))
    elif resets:
        results.append(_none_usable(out, "vth_reset", "V", [v for _, v in resets], "reset read"))
    return results


def _nls(out: Results, points: list[tuple[dict[str, Any], ReadValue]], alpha: float | None) -> list[ExtractionResult]:
    names = [("tau0", "s"), ("beta", "1"), ("va", "V")] + ([("alpha", "1")] if alpha is None else [])
    usable = [(p, v) for p, v in points if v.value is not None]
    if not usable:
        return [_none_usable(out, n, u, [v for _, v in points], "grid read") for n, u in names]  # type: ignore[arg-type]
    levels = np.array([float(p["level"]) for p, _ in usable])
    widths = np.array([float(p["width"]) for p, _ in usable])
    vth = np.array([float(v.value) for _, v in usable])  # type: ignore[arg-type]
    fit = fit_nls(levels, widths, vth, alpha=alpha)
    if isinstance(fit, str):
        return [out.failed(n, u, f"NLS fit: {fit}", excluded={}) for n, u in names]  # type: ignore[arg-type]
    out.warnings.extend(fit.warnings)
    window = window_of(widths, "s")
    common = {"points": float(len(usable)), "rms": fit.rms, "r2": fit.r2, "v0": fit.v0}
    tau_fit = {**common, "va": fit.va, "alpha": fit.alpha, "beta": fit.beta, "tau0_rel_se": fit.tau0_rel_se}
    for level, (tau, amplitude) in sorted(fit.per_level.items()):
        tau_fit[f"tau@{level:g}V"] = tau
        tau_fit[f"window@{level:g}V"] = amplitude
    n = len(usable)
    results = [out.ok("tau0", fit.tau0, "s", excluded={}, points_used=n, window=window, fit=tau_fit),
               out.ok("beta", fit.beta, "1", excluded={}, points_used=n, window=window,
                      fit={**common, "beta_se": fit.beta_se}),
               out.ok("va", fit.va, "V", excluded={}, points_used=n, window=window,
                      fit={**common, "va_se": fit.va_se})]
    if alpha is None:
        results.append(out.ok("alpha", fit.alpha, "1", excluded={}, points_used=n, window=window,
                              fit={**common, "alpha_se": fit.alpha_se}))
    return results


def _ispp(out: Results, points: list[tuple[dict[str, Any], ReadValue]], resets: list[tuple[int, ReadValue]],
          initial: float | None) -> list[ExtractionResult]:
    out.warnings.append("grid_mode ispp: cumulative steps; the NLS parameters (tau0, beta, va) need grid_mode reset")
    start_of = {cycle: v.value for cycle, v in resets}
    rows: dict[int, list[tuple[float, float, int]]] = {}
    starts: dict[int, float | None] = {}
    for p, v in points:
        row = int(p["row"])
        if row not in starts:
            starts[row] = start_of.get(int(p["cycle"]), initial)
        if v.value is not None:
            rows.setdefault(row, []).append((float(p["level"]), float(v.value), int(p["cycle"])))
    v50s: dict[str, float] = {}
    slopes: list[tuple[float, float]] = []
    used = 0
    for row, items in sorted(rows.items()):
        start = starts.get(row)
        if start is None or len(items) < 2:
            continue
        used += len(items)
        deltas = [(level, value - start) for level, value, _ in items]
        final = abs(deltas[-1][1])
        slopes += [(abs((d1 - d0) / (a1 - a0)), a1) for (a0, d0), (a1, d1) in itertools.pairwise(deltas)]
        crossing = None
        for (a0, d0), (a1, d1) in itertools.pairwise([(deltas[0][0], 0.0), *deltas]):
            if abs(d0) < 0.5 * final <= abs(d1):
                crossing = a0 + (0.5 * final - abs(d0)) * (a1 - a0) / (abs(d1) - abs(d0))
                break
        width = next(float(p["width"]) for p, _ in points if int(p["row"]) == row)
        if crossing is not None and final > 0:
            v50s[f"v50@{width:g}s"] = crossing
    if not v50s or not slopes:
        return [out.failed("v50", "V", "no width row with a start read and two usable steps", excluded={}),
                out.failed("ispp_slope", "1", "no width row with a start read and two usable steps", excluded={})]
    best = max(slopes)
    return [out.ok("v50", float(np.mean(list(v50s.values()))), "V", excluded={}, points_used=used,
                   fit={**v50s, "rows": float(len(v50s))}),
            out.ok("ispp_slope", best[0], "1", excluded={}, points_used=used, fit={"at_level": best[1]})]


# -- endurance --------------------------------------------------------------------------------------------------------


@dataclass
class Checkpoint:
    """One endurance checkpoint: its cumulative cycle count and the Vth after its erase and program."""

    cycles: int
    vth_erase: float | None
    vth_program: float | None

    @property
    def window(self) -> float | None:
        if self.vth_erase is None or self.vth_program is None:
            return None
        return self.vth_erase - self.vth_program


def _checkpoints(d: RunData, out: Results, **kw: Any) -> list[Checkpoint]:
    reads = pulse_reads(d, out.method)
    values = _vths(d, reads, out, **kw)
    by: dict[int, dict[str, float | None]] = {}
    for i, r in enumerate(reads):
        if r.cycle > 0:
            by.setdefault(r.cycle, {})[r.state] = values[i].value
    return [Checkpoint(c, s.get("erase"), s.get("program")) for c, s in sorted(by.items())]


def endurance_curve(d: RunData, *, vth_method: VthMethod = "constant_current", i_crit_a: float = DEFAULT_I_CRIT_A,
                    w_over_l: float | None = None, x: str | None = None, y: str = "drain_I", force: bool = False,
                    criteria: TrustPolicy | None = None) -> list[Checkpoint]:
    """The checkpoints of an endurance run in cycle order (module docstring; library helper of
    ``endurance_summary``)."""
    policy = trust_policy(criteria)
    _schedule(d, "endurance_curve", "cycles", endurance=True)
    return _checkpoints(d, _base("endurance_curve", policy), vth_method=vth_method, i_crit_a=i_crit_a,
                        w_over_l=w_over_l, x=x, y=y, force=force, policy=policy)


@validate_call(config=_CALL_CONFIG)
def endurance_summary(
    d: RunData,
    *,
    vth_method: VthMethod = "constant_current",
    i_crit_a: float = Field(default=DEFAULT_I_CRIT_A, gt=0),
    w_over_l: float | None = Field(default=None, gt=0),
    fail_fraction: float = Field(default=0.5, gt=0, lt=1),
    mw_fail: float | None = None,
    x: str | None = None,
    y: str = "drain_I",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Memory window versus program/erase cycles: wake-up, fatigue, cycles to failure (module docstring)."""
    policy = trust_policy(criteria)
    _schedule(d, "endurance_summary", "cycles", endurance=True)
    out = _base("endurance_summary", policy, vth_method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l,
                fail_fraction=fail_fraction, mw_fail=mw_fail, y=y, force=force)
    checkpoints = _checkpoints(d, out, vth_method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x, y=y,
                               force=force, policy=policy)
    curve = [(c.cycles, c.window) for c in checkpoints if c.window is not None]
    names = [("memory_window_initial", "V"), ("memory_window_max", "V"), ("memory_window_final", "V"),
             ("wake_up", "1"), ("fatigue", "1"), ("cycles_to_failure", "1")]
    if not curve:
        return [out.failed(n, u, "no checkpoint with both reads usable (see warnings)", excluded={})  # type: ignore[arg-type]
                for n, u in names]
    n = 2 * len(curve)
    cycles = np.array([c for c, _ in curve], dtype=float)
    mw = np.array([w for _, w in curve])
    window = window_of(cycles, "1")
    i_max = int(np.argmax(mw))
    first, top, last = curve[0], curve[i_max], curve[-1]
    final = next(c for c in checkpoints if c.cycles == last[0])
    results = [
        out.ok("memory_window_initial", first[1], "V", excluded={}, points_used=2, fit={"cycles": float(first[0])}),
        out.ok("memory_window_max", top[1], "V", excluded={}, points_used=2, fit={"cycles_at_max": float(top[0])}),
        out.ok("memory_window_final", last[1], "V", excluded={}, points_used=2,
               fit={"cycles": float(last[0]), "vth_program": float(final.vth_program or 0.0),
                    "vth_erase": float(final.vth_erase or 0.0), "checkpoints": float(len(curve))}),
    ]
    if len(curve) < 2 or first[1] <= 0 or top[1] <= 0:
        why = ("one checkpoint only" if len(curve) < 2 else "the window is not positive (pulse polarity or naming)")
        results += [out.failed(q, "1", f"needs two checkpoints with a positive window: {why}", excluded={})
                    for q in ("wake_up", "fatigue", "cycles_to_failure")]
        return results
    results.append(out.ok("wake_up", top[1] / first[1] - 1.0, "1", excluded={}, points_used=n, window=window,
                          fit={"mw_initial": first[1], "mw_max": top[1]}))
    results.append(out.ok("fatigue", 1.0 - last[1] / top[1], "1", excluded={}, points_used=n, window=window,
                          fit={"mw_max": top[1], "mw_final": last[1]}))
    criterion = mw_fail if mw_fail is not None else fail_fraction * top[1]
    results.append(_failure(out, cycles[i_max:], mw[i_max:], criterion, n, window))
    return results


def _failure(out: Results, cycles: np.ndarray, mw: np.ndarray, criterion: float, n: int,
             window: Any) -> ExtractionResult:
    """``cycles_to_failure``: the first crossing below ``criterion`` from the maximum on (log10 N interpolation)."""
    fit = {"criterion_v": criterion}
    below = np.nonzero(mw < criterion)[0]
    if below.size == 0:
        return out.ok("cycles_to_failure", float(cycles[-1]), "1", excluded={}, points_used=n, window=window,
                      fit=fit, bound="lower",
                      warnings=[f"the window stayed above {criterion:.4g} V up to the last checkpoint: a lower bound"])
    k = int(below[0])
    if k == 0:
        return out.ok("cycles_to_failure", float(cycles[0]), "1", excluded={}, points_used=n, window=window, fit=fit)
    l0, l1 = math.log10(cycles[k - 1]), math.log10(cycles[k])
    m0, m1 = float(mw[k - 1]), float(mw[k])
    at = l0 + (criterion - m0) * (l1 - l0) / (m1 - m0)
    return out.ok("cycles_to_failure", 10.0 ** at, "1", excluded={}, points_used=n, window=window, fit=fit)


# -- retention --------------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def retention_fit(
    d: RunData,
    *,
    vth_method: VthMethod = "constant_current",
    i_crit_a: float = Field(default=DEFAULT_I_CRIT_A, gt=0),
    w_over_l: float | None = Field(default=None, gt=0),
    target_time_s: float = Field(default=DEFAULT_TARGET_S, gt=0),
    t_min: float | None = Field(default=None, gt=0),
    fail_fraction: float = Field(default=0.5, gt=0, lt=1),
    mw_min: float | None = None,
    x: str | None = None,
    y: str = "drain_I",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Vth of each written state and the memory window versus log10(t) after the write (module docstring)."""
    policy = trust_policy(criteria)
    _schedule(d, "retention_fit", "retention")
    if T_S not in d.table.columns:
        raise InvalidInputError(f"retention_fit: run {d.run_id} has no t_s column")
    out = _base("retention_fit", policy, vth_method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l,
                target_time_s=target_time_s, t_min=t_min, fail_fraction=fail_fraction, mw_min=mw_min, y=y,
                force=force)
    reads = pulse_reads(d, "retention_fit")
    values = _vths(d, reads, out, vth_method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x, y=y,
                   force=force, policy=policy)
    series: dict[str, dict[int, tuple[float, float | None]]] = {}
    for i, r in enumerate(reads):
        t = float(r.rows[T_S].iloc[0]) if r.state != "initial" else math.nan
        if r.state != "initial" and math.isfinite(t) and t > 0 and (t_min is None or t >= t_min):
            series.setdefault(r.state, {})[r.cycle] = (t, values[i].value)
    results: list[ExtractionResult] = []
    for state in ("program", "erase"):
        if state in series:
            results.append(_log_fit(out, f"retention_slope_{state}", series[state], target_time_s))
    if "program" in series and "erase" in series:
        pairs = {k: (t, e - p) for k, (t, e) in series["erase"].items() if e is not None and k in series["program"]
                 and (p := series["program"][k][1]) is not None}
        results += _mw_retention(out, pairs, target_time_s, mw_min, fail_fraction)
    if not results:
        results.append(out.failed("retention_slope_program", "V/dec", "no read after a write at t_s > 0",
                                  excluded={}))
    return results


def _log_fit(out: Results, name: str, points: dict[int, tuple[float, float | None]],
             target: float) -> ExtractionResult:
    usable = [(t, v) for t, v in points.values() if v is not None]
    if len(usable) < 2:
        return out.failed(name, "V/dec", f"{len(usable)} usable read(s); a log-time fit needs 2", excluded={})
    t = np.array([a for a, _ in usable])
    v = np.array([b for _, b in usable])
    slope, intercept, r2 = line_fit(np.log10(t), v)
    return out.ok(name, slope, "V/dec", excluded={}, points_used=len(usable), window=window_of(t, "s"),
                  fit={"vth_1s": intercept, "r2": r2, "vth_first": float(v[0]), "vth_last": float(v[-1]),
                       "vth_target": intercept + slope * math.log10(target)},
                  warnings=_extrapolation(t, target))


def _extrapolation(t: np.ndarray, target: float) -> list[str]:
    decades = math.log10(target) - math.log10(float(t.max()))
    if decades > 2:
        return [f"extrapolated {decades:.1f} decades beyond the last read ({float(t.max()):g} s) to {target:g} s"]
    return []


def _mw_retention(out: Results, pairs: dict[int, tuple[float, float]], target: float, mw_min: float | None,
                  fail_fraction: float) -> list[ExtractionResult]:
    names = [("memory_window_slope", "V/dec"), ("memory_window_at_target", "V"), ("retention_time", "s")]
    if len(pairs) < 2:
        return [out.failed(n, u, f"{len(pairs)} read pair(s) with both states; the fit needs 2", excluded={})  # type: ignore[arg-type]
                for n, u in names]
    items = sorted(pairs.values())
    t = np.array([a for a, _ in items])
    mw = np.array([b for _, b in items])
    slope, intercept, r2 = line_fit(np.log10(t), mw)
    window = window_of(t, "s")
    warnings = _extrapolation(t, target)
    n = 2 * len(items)
    at_target = intercept + slope * math.log10(target)
    criterion = mw_min if mw_min is not None else fail_fraction * float(mw[0])
    fit = {"mw_1s": intercept, "r2": r2, "mw_first": float(mw[0]), "mw_last": float(mw[-1]), "criterion_v": criterion}
    results = [out.ok("memory_window_slope", slope, "V/dec", excluded={}, points_used=n, window=window, fit=fit),
               out.ok("memory_window_at_target", at_target, "V", excluded={}, points_used=n, window=window,
                      fit={**fit, "target_time_s": target}, warnings=warnings)]
    if slope >= 0:
        results.append(out.ok("retention_time", target, "s", excluded={}, points_used=n, window=window, fit=fit,
                              bound="lower", warnings=["the window does not decay: a lower bound at the target"]))
        return results
    t_fail = 10.0 ** ((criterion - intercept) / slope)
    early = [f"the window is below {criterion:.4g} V already at the first read"] if t_fail < float(t[0]) else []
    results.append(out.ok("retention_time", t_fail, "s", excluded={}, points_used=n, window=window, fit=fit,
                          warnings=[*early, *_extrapolation(t, t_fail)]))
    return results


__all__ = ["Checkpoint", "PulseRead", "endurance_curve", "endurance_summary", "memory_window_pulse", "pulse_reads",
           "retention_fit", "switching_kinetics_fit"]
