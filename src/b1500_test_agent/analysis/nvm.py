"""Non-volatile memory analysis of program/read runs (blueprint v2 2.10 ``nvm.py``; WP9.4 ``memory_window_pulse`` on
runs of kind ``pulse_read``: ``fefet.pulse_write_read``, ``spgu.program_smu_read``). WP9.5 adds the switching-kinetics,
endurance and retention methods to this module.

Definitions (the single source of the section "Program/read memory window" of knowledge file
``06b-analysis-time-pulse.md`` of skill ``b1500-test``; change both together):

- **Reads.** The run table of kind ``pulse_read`` has one group of rows per read, keyed by ``cycle`` and ``phase``:
  ``phase == "read"`` (cycle 0) is the reference read before any pulse; ``program`` / ``erase`` rows are the read
  that follows that operation in that cycle (the *programmed* and *erased* state).
- **Per-read quantity** (``quantity``): ``vth`` = the threshold voltage of a staircase read (``x`` default ``gate_V``,
  else the only swept source column; ``y`` default ``drain_I``) by ``vth_method`` ``constant_current`` (default;
  ``i_crit_a`` x ``w_over_l``, 100 nA by default, log10|Id| interpolated) or ``linear_extrapolation`` (max-gm tangent
  minus Vd/2); ``current`` = ``y`` at the read: the mean of a spot read's trusted samples, or a sweep's value at
  ``x = at_v`` (default: the plan parameter ``vg_read``). ``auto`` (default) takes ``vth`` when the reads sweep ``x``,
  else ``current``. Each read is judged like the method it uses: untrusted points refuse that read unless ``force``
  (forced reads are flagged); limited (``C``/``T``) points never enter. A refused or failed read drops out with a
  warning; when every read of a state drops out its results are refused (or failed).
- **Memory window** (``vth``): ``MW = mean Vth(erase) - mean Vth(program)`` over the cycles (positive for an n-channel
  FeFET: a positive program pulse lowers Vth); ``fit`` holds the per-cycle windows' minimum, maximum and standard
  deviation over the cycles that have both reads (``cycles``) and the reference read's Vth. A negative window is
  flagged (the operations' polarity or naming). With one operation only (a program-only sequence) there is no window:
  the state's mean, first and last value are reported (cumulative programming).
- **Read window** (``current``): ``current_ratio = |I(program)| / |I(erase)|`` of the mean read currents (> 1 when the
  programmed state conducts more at the read level).

Results: ``vth``: ``memory_window`` (V, when both operations ran), ``vth_program``, ``vth_erase`` (V; ``fit``:
``first``, ``last``, ``std``, ``reads``) and ``vth_initial`` (V, the reference read); ``current``: ``i_program``,
``i_erase``, ``i_initial`` (A) and ``current_ratio`` (1, when both operations ran). Every result is derived
(``ExtractionResult``) with the method, its parameters and the reads used; refusals and failures come back as
results, never as exceptions (``InvalidInputError`` only for unusable calls: not a ``pulse_read`` table, unknown
column, a sweep read without ``at_v``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, analysed_rows, interpolate, policy_params, trust_policy
from b1500_test_agent.analysis.dataset import CYCLE, PHASE, RunData
from b1500_test_agent.analysis.mosfet import DEFAULT_I_CRIT_A, vth_constant_current, vth_linear_extrapolation
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


__all__ = ["PulseRead", "memory_window_pulse", "pulse_reads"]
