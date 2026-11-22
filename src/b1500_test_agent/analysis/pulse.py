"""Pulsed I-V analyses (blueprint v2 2.10 ``pulse.py``; card ``smu-pulsed-iv``): ``pulsed_vs_dc`` (a two-run method:
``analyze_run`` ``options.reference_run``) and ``pulse_plateau``.

Definitions (the source of knowledge file ``06b-analysis-pulse-stress.md``; change both together):

- **pulsed_vs_dc** compares a pulsed run ``d`` (kind ``smu_pulsed``) with a DC reference run of the same device and
  bias conditions (``reference``: e.g. ``mosfet.idvg`` for ``mosfet.idvg_pulsed``, ``mosfet.idvd`` for
  ``mosfet.idvd_pulsed``, ``basic.contact_resistor``/``generic.smu_spot`` for ``basic.pulsed_spot``). ``x``
  defaults to the swept voltage (the source voltage column with the most values), ``y`` to the only measured current,
  else the only current of another role (Id of a gate sweep), else the swept terminal's own; both runs must have
  them. Constant
  source columns present in both runs (e.g. ``drain_V``) must agree within 1 mV + 0.1 % (else ``failed``: a comparison
  at other bias conditions means nothing). For an output family (another varying source column, e.g. ``gate_V`` of an
  Id-Vd family) one curve is compared: ``curve`` (its step level; default the largest |level| present in both runs).
  Over the common x window the reference is linearly interpolated at the pulsed run's x values (trusted rows of both,
  ``segment``); ``Delta(x) = y_pulsed(x) - y_dc(x)``, ``r(x) = Delta / |y_dc|`` where ``|y_dc| >= min_current_a``
  (default 1 % of the largest |y_dc| in the window). Results: ``pulsed_minus_dc`` (unit of ``y``) and
  ``pulsed_over_dc`` (ratio) at ``v`` (default: the x of the largest |y_pulsed|, the highest power and the strongest
  self-heating), and ``max_rel_difference`` (the largest |r| over the window, its x in ``fit``). A positive difference
  on an n-type transistor at high power is DC self-heating (mobility loss) removed by the pulses; a difference at
  negligible power points to charge trapping (slow traps charge during DC) or to a mismatch of the two runs.
- **pulse_plateau** reads the plateau level of pulses. A time-resolved table (``t_s`` with several rows per pulse,
  e.g. a WGFMU waveform) is cut into pulses: by its ``event`` column when it has one (each run of one event label is
  a pulse), else on the pulsed voltage ``x``: rows more than ``threshold`` (V, default 0.05) away from the base level
  (the first row's ``x``), split where ``x`` jumps by more than ``threshold`` between samples (pulses that do not
  return to base); each pulse's plateau drops the ``edge`` fraction of its samples at both ends (at least one sample
  stays) and averages ``y`` over its trusted samples. A table with one row per pulse (SMU pulsed spot/sweep: the
  instrument already measured at the pulse end over the pulsed ADC time) uses every row as one plateau. Result
  ``plateau_current`` (A) or ``plateau_voltage`` (V) of the pulse at level ``v`` (interpolated between pulse
  levels), of pulse number ``pulse`` (0-based; negative counts from the end), or by default of the pulse with the
  largest |level|; ``fit``: ``level_v``, ``samples``, ``std``, ``pulses``, ``plateau_s`` (time-resolved only);
  ``window``: the plateau's ``t_s`` span.

Trust as every method (``mosfet.py`` docstring): untrusted rows refuse the call unless ``force`` (flagged); limited
rows (``C``/``T``) are excluded.
"""

from __future__ import annotations

import itertools
from typing import Annotated

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    interpolate,
    policy_params,
    sig,
    sweep_columns,
    trust_policy,
    varying_sources,
    window_of,
)
from b1500_test_agent.analysis.dataset import EVENT, T_S, RunData, Segment, parse_value_column
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QuantityRange, TrustPolicy, Unit

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Fraction = Annotated[float, Field(gt=0, lt=0.5)]
Threshold = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Amps = Annotated[float, Field(gt=0, allow_inf_nan=False)]

BIAS_ABS_TOL_V = 1e-3
BIAS_REL_TOL = 1e-3
"""Constant source columns of the two runs agree within 1 mV + 0.1 % (A columns: 1 nA + 0.1 %)."""

FLOOR_FRACTION = 0.01
"""Default ``min_current_a`` of ``pulsed_vs_dc``: 1 % of the largest |y_dc| in the window."""

LEVEL_TOL = 1e-6
"""Two step levels are the same curve within 1 uV."""


def _output_current(d: RunData, x: str | None) -> str | None:
    """Default ``y`` of ``pulsed_vs_dc``: the only measured current, else the only one of another role than the
    swept terminal (Id of a gate sweep), else the swept terminal's own current; ``None`` lets ``sweep_columns``
    decide (or ask for ``y``)."""
    currents = [c for c in d.measured_columns if c.endswith("_I")]
    if len(currents) <= 1:
        return currents[0] if currents else None
    if x is None:
        candidates = [c for c in d.source_columns if c.endswith("_V")]
        x = max(candidates, key=lambda c: int(d.table[c].nunique())) if candidates else ""
    parsed = parse_value_column(x) if x else None
    own = f"{parsed[0]}_I" if parsed else ""
    others = [c for c in currents if c != own]
    if len(others) == 1:
        return others[0]
    return own if own in currents else None


def _constant(table: pd.DataFrame, column: str) -> float | None:
    values = table[column].dropna().to_numpy(dtype=float)
    if values.size == 0 or np.ptp(values) > 0:
        return None
    return float(values[0])


def _bias_mismatch(d: RunData, ref: RunData, x: str, step: str | None) -> list[str]:
    """Constant source columns (present in both runs, not ``x`` or the step) that differ."""
    out = []
    for column in d.source_columns:
        if column in (x, step) or column not in ref.table.columns:
            continue
        mine, theirs = _constant(d.table, column), _constant(ref.table, column)
        if mine is None or theirs is None:
            continue
        tol = (BIAS_ABS_TOL_V if column.endswith("_V") else 1e-9) + BIAS_REL_TOL * max(abs(mine), abs(theirs))
        if abs(mine - theirs) > tol:
            out.append(f"{column} {mine:g} vs {theirs:g}")
    return out


def _curve_rows(d: RunData, rows: pd.DataFrame, step: str | None, level: float | None) -> pd.DataFrame:
    if step is None or level is None:
        return rows
    if step not in rows.columns:
        raise InvalidInputError(f"run {d.run_id} has no step column {step!r}")
    return rows[(rows[step] - level).abs() <= LEVEL_TOL]


@validate_call(config=_CALL_CONFIG)
def pulsed_vs_dc(
    d: RunData,
    *,
    reference: RunData,
    x: str | None = None,
    y: str | None = None,
    v: float | None = None,
    curve: float | None = None,
    min_current_a: Amps | None = None,
    segment: Segment = "fwd",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Pulsed minus DC current (module docstring): ``pulsed_minus_dc``, ``pulsed_over_dc`` at ``v`` and
    ``max_rel_difference`` over the common window."""
    policy = trust_policy(criteria)
    x, y = sweep_columns(d, x, y if y is not None else _output_current(d, x), "pulsed_vs_dc")
    for column in (x, y):
        if column not in reference.table.columns:
            raise InvalidInputError(f"pulsed_vs_dc: the reference run {reference.run_id} has no column {column!r}; "
                                    "compare runs of the same roles (e.g. mosfet.idvg for mosfet.idvg_pulsed).")
    unit: Unit = d.unit(y)
    rows = d.rows(segment)
    steps = [c for c in varying_sources(rows, d) if c != x]
    step = steps[0] if len(steps) == 1 else None
    if len(steps) > 1:
        raise InvalidInputError(f"pulsed_vs_dc: several step columns {steps}; the family cannot be matched.")
    out = Results("pulsed_vs_dc", {"reference_run": reference.run_id, "x": x, "y": y, "v": v, "curve": curve,
                                   "min_current_a": min_current_a, "segment": segment, "force": force,
                                   "trust_policy": policy_params(policy)})
    names = ("pulsed_minus_dc", "pulsed_over_dc", "max_rel_difference")
    units: tuple[Unit, Unit, Unit] = (unit, "1", "1")

    def failed(error: str, excluded: dict[str, int] | None = None) -> list[ExtractionResult]:
        return [out.failed(n, u, error, excluded=excluded or {}) for n, u in zip(names, units, strict=True)]

    if d.manifest.backend != reference.manifest.backend:
        return failed(f"run {d.run_id} ({d.manifest.backend}) and the reference {reference.run_id} "
                      f"({reference.manifest.backend}) come from different backends")
    mismatch = _bias_mismatch(d, reference, x, step)
    if mismatch:
        return failed("bias conditions differ between the pulsed run and the reference: " + "; ".join(mismatch))
    ref_rows = reference.rows(segment if reference.has_segments else None)
    level = curve
    if step is not None:
        mine = sorted({round(float(v_), 9) for v_ in rows[step].dropna()}, key=abs)
        theirs = {round(float(v_), 9) for v_ in ref_rows[step].dropna()} if step in ref_rows.columns else set()
        common = [lv for lv in mine if any(abs(lv - t) <= LEVEL_TOL for t in theirs)]
        if level is None:
            if not common:
                return failed(f"no {step} level is present in both runs ({mine} vs {sorted(theirs)})")
            level = common[-1]
        elif not any(abs(level - t) <= LEVEL_TOL for t in common):
            return failed(f"{step} = {level:g} is not a curve of both runs (common: {common})")
    pulsed = analysed_rows(d, x, y, policy, segment=None, rows=_curve_rows(d, rows, step, level))
    dc = analysed_rows(reference, x, y, policy, segment=None, rows=_curve_rows(reference, ref_rows, step, level))
    problems = pulsed.problems(f"run {d.run_id}", noise=False) + dc.problems(f"reference {reference.run_id}",
                                                                             noise=False)
    if problems and not force:
        return [out.refused(n, u, problems, excluded=pulsed.excluded()) for n, u in zip(names, units, strict=True)]
    out.flag(problems)
    xs, ys = pulsed.xs, pulsed.ys
    rx, ry = dc.xs, dc.ys
    if xs.size < 2 or rx.size < 2:
        return failed("fewer than two trusted points in one of the runs", pulsed.excluded())
    low, high = max(xs.min(), rx.min()), min(xs.max(), rx.max())
    inside = (xs >= low - 1e-12) & (xs <= high + 1e-12)
    if inside.sum() < 2:
        return failed(f"the runs share no x window ({xs.min():g}..{xs.max():g} vs {rx.min():g}..{rx.max():g} V)",
                      pulsed.excluded())
    order = np.argsort(rx, kind="stable")
    xw, yw = xs[inside], ys[inside]
    y_dc = np.interp(xw, rx[order], ry[order])
    floor = min_current_a if min_current_a is not None else FLOOR_FRACTION * float(np.max(np.abs(y_dc)))
    usable = np.abs(y_dc) >= floor
    window = window_of(xw, "V")
    fit_common = {"reference_points": float(rx.size), "floor_a": floor} | ({"curve": level} if level is not None
                                                                         else {})
    if v is None:
        v = float(xw[int(np.argmax(np.abs(yw)))])
    at = interpolate(xw, yw, v)
    if at is None:
        return failed(f"v = {v:g} V lies outside the common window {low:g}..{high:g} V", pulsed.excluded())
    y_p = at[0]
    y_d = float(np.interp(v, rx[order], ry[order]))
    delta = y_p - y_d
    warnings: list[str] = []
    if d.manifest.dut_instance != reference.manifest.dut_instance:
        warnings.append(f"different DUT instances: {d.manifest.dut_instance!r} vs "
                        f"{reference.manifest.dut_instance!r}")
    results = [out.ok("pulsed_minus_dc", delta, unit, excluded=pulsed.excluded(), points_used=int(inside.sum()),
                      window=window, fit={"v": v, "y_pulsed": y_p, "y_dc": y_d, **fit_common}, warnings=warnings)]
    if y_d == 0:
        results.append(out.failed("pulsed_over_dc", "1", f"the reference current is 0 at {v:g} V",
                                  excluded=pulsed.excluded()))
    else:
        results.append(out.ok("pulsed_over_dc", y_p / y_d, "1", excluded=pulsed.excluded(), points_used=1,
                              window=window, fit={"v": v, **fit_common}, warnings=warnings))
    if not usable.any():
        results.append(out.failed("max_rel_difference", "1", f"no reference current above {floor:.3g} A",
                                  excluded=pulsed.excluded()))
    else:
        rel = (yw - y_dc)[usable] / np.abs(y_dc[usable])
        k = int(np.argmax(np.abs(rel)))
        results.append(out.ok("max_rel_difference", float(abs(rel[k])), "1", excluded=pulsed.excluded(),
                              points_used=int(usable.sum()), window=window,
                              fit={"v_at_max": float(xw[usable][k]), "signed": float(rel[k]),
                                   "mean_rel": float(np.mean(rel)), **fit_common}, warnings=warnings))
    return results


def _pulse_runs(x: np.ndarray, threshold: float, events: np.ndarray | None) -> list[np.ndarray]:
    """Index arrays of the pulses: runs of one ``events`` label, else runs of rows more than ``threshold`` away from
    the base (the first ``x``) split at jumps above ``threshold`` (module docstring)."""
    runs: list[np.ndarray] = []
    if events is not None:
        labels = pd.Series(events).astype(str)
        starts = np.flatnonzero(labels.ne(labels.shift()).to_numpy())
        bounds = [*starts.tolist(), len(labels)]
        return [np.arange(lo, hi) for lo, hi in itertools.pairwise(bounds) if labels.iloc[lo] not in ("", "nan")]
    on = np.abs(x - x[0]) > threshold
    start: int | None = None
    for i in range(len(x) + 1):
        breaks = i == len(x) or not on[i] or (start is not None and abs(x[i] - x[i - 1]) > threshold)
        if start is not None and breaks:
            runs.append(np.arange(start, i))
            start = None
        if i < len(x) and on[i] and start is None:
            start = i
    return runs


@validate_call(config=_CALL_CONFIG)
def pulse_plateau(
    d: RunData,
    *,
    x: str | None = None,
    y: str | None = None,
    v: float | None = None,
    pulse: int | None = None,
    edge: Fraction = 0.2,
    threshold: Threshold = 0.05,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Plateau level of a pulse (module docstring): ``plateau_current`` (A) or ``plateau_voltage`` (V)."""
    policy = trust_policy(criteria)
    table = d.table
    if x is None:
        candidates = [c for c in table.columns if c.endswith("_V") and not c.endswith("_status")
                      and c not in (y,)]
        if not candidates:
            raise InvalidInputError(f"pulse_plateau: run {d.run_id} has no voltage column; pass x=<column>.")
        x = max(candidates, key=lambda c: float(np.ptp(table[c].dropna().to_numpy(dtype=float)))
                if table[c].notna().any() else -1.0)
    if y is None:
        currents = [c for c in d.measured_columns if c.endswith("_I")]
        if len(currents) != 1:
            raise InvalidInputError(f"pulse_plateau: cannot choose the measured column of run {d.run_id} among "
                                    f"{currents}; pass y=<column>.")
        y = currents[0]
    unit = d.unit(y)
    d.unit(x)
    quantity = "plateau_current" if unit == "A" else "plateau_voltage"
    out = Results("pulse_plateau", {"x": x, "y": y, "v": v, "pulse": pulse, "edge": edge, "threshold": threshold,
                                    "force": force, "trust_policy": policy_params(policy)})
    r = analysed_rows(d, x, y, policy, segment=None)
    problems = r.problems("the pulses", noise=False)
    if problems and not force:
        return out.refused(quantity, unit, problems, excluded=r.excluded())
    out.flag(problems)
    xv = table[x].to_numpy(dtype=float)
    yv = table[y].to_numpy(dtype=float)
    usable = r.ok
    time_resolved = T_S in table.columns and table[T_S].notna().all()
    plateaus: list[tuple[float, float, float, int, float | None, float | None]] = []
    """``(level, mean, std, samples, t_start, t_end)`` per pulse."""
    if time_resolved:
        events = table[EVENT].to_numpy() if EVENT in table.columns else None
        runs = _pulse_runs(xv, threshold, events)
        times = table[T_S].to_numpy(dtype=float)
        for run in runs:
            cut = int(len(run) * edge)
            inner = run[cut:len(run) - cut] if len(run) - 2 * cut >= 1 else run
            keep = inner[usable[inner]]
            if keep.size == 0:
                continue
            plateaus.append((float(np.mean(xv[keep])), float(np.mean(yv[keep])),
                             float(np.std(yv[keep], ddof=1)) if keep.size > 1 else 0.0, int(keep.size),
                             float(times[inner[0]]), float(times[inner[-1]])))
    if not time_resolved or not plateaus:
        for i in np.flatnonzero(usable):
            plateaus.append((float(xv[i]), float(yv[i]), 0.0, 1, None, None))
    if not plateaus:
        return out.failed(quantity, unit, f"no trusted pulse in {x}/{y}", excluded=r.excluded())
    levels = np.array([p[0] for p in plateaus])
    means = np.array([p[1] for p in plateaus])
    fit_all = {"pulses": float(len(plateaus))}
    if v is not None:
        found = interpolate(levels, means, v)
        if found is None:
            return out.failed(quantity, unit, f"{x} = {v:g} V lies outside the pulse levels "
                              f"{levels.min():g}..{levels.max():g} V", excluded=r.excluded(), fit=fit_all)
        nearest = plateaus[int(np.argsort(levels, kind="stable")[found[1]])]
        return out.ok(quantity, found[0], unit, excluded=r.excluded(), points_used=nearest[3],
                      fit={"level_v": v, "samples": float(nearest[3]), "std": nearest[2], **fit_all})
    if pulse is not None:
        if not -len(plateaus) <= pulse < len(plateaus):
            raise InvalidInputError(f"pulse_plateau: pulse {pulse} does not exist ({len(plateaus)} pulses).")
        chosen = plateaus[pulse]
    else:
        top = float(np.max(np.abs(levels)))
        chosen = plateaus[int(np.flatnonzero(np.abs(levels) >= top - 1e-12)[-1])]
    level, mean, std, samples, t_start, t_end = chosen
    fit = {"level_v": level, "samples": float(samples), "std": std, **fit_all}
    window = None
    if t_start is not None and t_end is not None and t_end > t_start:
        fit["plateau_s"] = t_end - t_start
        window = QuantityRange(low=sig(t_start), high=sig(t_end), unit="s") if sig(t_start) < sig(t_end) else None
    return out.ok(quantity, mean, unit, excluded=r.excluded(), points_used=samples, window=window, fit=fit)


__all__ = ["pulse_plateau", "pulsed_vs_dc"]
