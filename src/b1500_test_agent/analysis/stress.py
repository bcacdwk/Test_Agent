"""Stress-measure analysis (blueprint v2 2.10, the ``reliability.py`` methods of WP7.6 in their own module so that
``reliability.py`` stays small): ``bti_power_law``, ``degradation_vs_time`` and ``silc`` on runs of kind
``stress_measure`` (``reliability.bti_sms``, ``igzo.bias_stress``, ``reliability.hci``, ``reliability.silc``).

Definitions (the single source of the section "Stress-measure analysis" of knowledge file
``05-reliability-defects.md`` of skill ``b1500-test``; change both together):

- **Reads.** The rows with ``phase == "read"`` grouped by ``cycle`` (the run-table contract of kind
  ``stress_measure``): cycle 0 is the reference read before any stress (``t_s = 0``); a later read is a *stress read*
  or a *recovery read* by the phase of the hold rows of its cycle (``stress`` or ``recovery``). A read's time is its
  ``t_s``: the cumulative stress time for stress reads; for recovery reads the recovery time is
  ``t_rec = t_s - t_stress`` with ``t_stress`` the time of the last stress read. ``t_min``/``t_max`` restrict the
  stress reads used by the fits (the reference read is always used).
- **Per-read quantity** ``X``: ``vth`` = the threshold voltage of a staircase read (x default ``gate_V``, y default
  ``drain_I``, segment ``fwd``) by the ``mosfet.py`` method ``vth_method``: ``constant_current`` (default; ``i_crit_a``
  x ``w_over_l``, 100 nA by default, log10|Id| interpolated) or ``linear_extrapolation`` (max-gm tangent minus Vd/2,
  Vd from the plan parameter ``vd``); ``id``/``ig`` = the current ``y`` at the read: the mean of a spot read's trusted
  samples, or the value of a staircase read at ``x = at_v`` (linear interpolation between the bracketing trusted
  points; a read that does not sweep ``x`` has no ``vth``). Each read is judged like the method it uses: untrusted
  points refuse that read unless ``force``
  (forced reads are flagged); limited (``C``/``T``) points never enter. A refused or failed read drops out with a
  warning; a refused or failed reference read refuses or fails every result.
- **Change** ``Δ(t) = X(t) - X(0)`` against the reference read; ``relative`` divides by ``|X(0)|`` (unit ``1``).
- **Power law** (``fit="power_law"``): ``|Δ| = b·t^m`` by least squares of ``log10|Δ|`` on ``log10 t`` over the stress
  reads whose change has the majority sign and ``|Δ| >= min_change`` (below it the change is lost in the read
  noise); at least 3 such reads, else failed. ``b`` is the change at 1 s on the fitted line, with the sign of the
  change (negative for a falling drain current); ``fit`` holds ``r2``, the reads used and the time window.
- **Stretched exponential** (``fit="stretched_exp"``, IGZO bias stress, Libsch & Kanicki, APL 62, 1286, 1993):
  ``Δ(t) = Δ∞·(1 - exp(-(t/τ)^β))`` fitted to the stress reads (reference included as ``Δ = 0``) by
  ``reliability.fit_stretched_exponential`` (at least 8 reads); results ``tau`` (s), ``beta`` (1) and ``delta_inf``.
- **Recovery** (runs with recovery reads): ``recovery`` = ``1 - Δ(t_rec,last)/Δ(t_stress)``, the recovered fraction of
  the shift at the last recovery read; ``recovery_rate`` (``bti_power_law``) = minus the least-squares slope of
  ``Δ(t_rec)/Δ(t_stress)`` against ``log10(t_rec)`` (fraction recovered per decade, log-recovery law).

Methods:

- ``bti_power_law``: ``X = vth``; results ``n`` (1, the power-law exponent), ``a`` (V, ``|ΔVth|`` at 1 s), ``dvth``
  (V, the signed shift at the last stress read; positive = threshold up: nMOS PBTI, negative = pMOS NBTI) and, with
  recovery reads, ``recovery`` and ``recovery_rate``; ``min_change`` default 1 mV.
- ``degradation_vs_time``: ``quantity`` ``id`` (default; ``relative`` default true: HCI ``ΔId/Id0``), ``vth``
  (``relative`` default false) or ``ig``; ``fit`` ``power_law`` (default: results ``b`` and ``m``), ``stretched_exp``
  (``tau``, ``beta``, ``delta_inf``) or ``none``; always ``delta`` (the change at the last stress read) and, with
  recovery reads, ``recovery``. ``min_change`` default 1e-3 (relative) or 1 mV / 1 pA (absolute).
- ``silc``: ``X`` = ``|Ig|`` at ``v_sense`` (``y`` default ``gate_I``; ``v_sense`` default: the plan parameter
  ``v_sense``, else the spot read level of the gate); the SILC ratio ``r(t) = (|Ig(t)| - |Ig0|)/|Ig0|``. Results
  ``silc_ratio`` (1, at the last stress read), ``silc_exponent`` (1, the power-law slope of ``r`` over the stress
  reads with ``|Ig(t)| - |Ig0| >= max(min_ratio x |Ig0|, 3·sqrt(2)·sem0)``, sem0 = the standard error of the
  reference read's samples; at least 3, else failed), ``ig0`` (A, the leakage before the stress) and ``q_inj``
  (C, the charge through the stressed gate: the trapezoid integral of ``|y|`` of the stress monitor rows over
  ``t_s`` from 0, the current before the first monitor sample taken as that sample's).

Every result is derived (``ExtractionResult``) with the method, its parameters and the reads used; refusals and
failures come back as results, never as exceptions (``InvalidInputError`` only for unusable calls: not a stress-measure
table, unknown column).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, analysed_rows, interpolate, line_fit, policy_params, trust_policy
from b1500_test_agent.analysis.dataset import CYCLE, PHASE, T_S, RunData, status_column, trust_levels
from b1500_test_agent.analysis.mosfet import DEFAULT_I_CRIT_A, vth_constant_current, vth_linear_extrapolation
from b1500_test_agent.analysis.reliability import BETA_GRID, fit_stretched_exponential
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)

ReadQuantity = Literal["id", "vth", "ig"]
VthMethod = Literal["constant_current", "linear_extrapolation"]
StressFit = Literal["power_law", "stretched_exp", "none"]
ReadKindLabel = Literal["reference", "stress", "recovery"]

MIN_FIT_READS = 3
"""Fewest stress reads a power-law fit uses."""

DEFAULT_MIN_SHIFT_V = 1e-3
DEFAULT_MIN_RELATIVE = 1e-3
DEFAULT_MIN_CURRENT_A = 1e-12
SILC_SIGMAS = 3.0
SENSE_PARAM = "v_sense"


@dataclass
class Read:
    """One read of the run: its cycle, kind, time (``t_s``) and rows."""

    cycle: int
    kind: ReadKindLabel
    t_s: float
    rows: pd.DataFrame


@dataclass
class Value:
    """A per-read quantity: ``value`` (``None`` when refused or failed: ``why``), samples (spot reads), warnings."""

    value: float | None
    why: str = ""
    samples: list[float] = field(default_factory=list)
    refused: bool = False
    forced: bool = False
    warnings: list[str] = field(default_factory=list)


def stress_reads(d: RunData, method: str) -> list[Read]:
    """The reads of a stress-measure run in cycle order (module docstring).

    Raises:
        InvalidInputError: If the run has no ``phase``/``cycle``/``t_s`` columns or no reference read.
    """
    table = d.table
    missing = [c for c in (PHASE, CYCLE, T_S) if c not in table.columns]
    if missing:
        raise InvalidInputError(f"{method}: run {d.run_id} has no {missing} column(s); it needs a stress-measure run "
                                "(kind stress_measure).")
    holds = table[table[PHASE] != "read"]
    hold_phase = {int(c): str(p) for c, p in holds.groupby(CYCLE, sort=True)[PHASE].first().items()}
    reads: list[Read] = []
    for cycle, rows in table[table[PHASE] == "read"].groupby(CYCLE, sort=True):
        number = int(cycle)
        kind: ReadKindLabel = "reference" if number == 0 else ("recovery" if hold_phase.get(number) == "recovery"
                                                                else "stress")
        reads.append(Read(cycle=number, kind=kind, t_s=float(rows[T_S].iloc[0]), rows=rows))
    if not reads or reads[0].kind != "reference":
        raise InvalidInputError(f"{method}: run {d.run_id} has no reference read (cycle 0).")
    return reads


def _sub(d: RunData, rows: pd.DataFrame) -> RunData:
    return RunData(manifest=d.manifest, table=rows.reset_index(drop=True), path=d.path)


def _vth(d: RunData, read: Read, *, method: VthMethod, i_crit_a: float, w_over_l: float | None, x: str, y: str,
         force: bool, policy: TrustPolicy) -> Value:
    sub = _sub(d, read.rows)
    if x not in sub.table.columns or sub.table[x].nunique(dropna=True) < 2:
        return Value(None, why=f"read {read.cycle} does not sweep {x}: a threshold needs staircase reads (read_kind "
                               "staircase); for spot reads use degradation_vs_time with quantity id")
    if method == "constant_current":
        found = vth_constant_current(sub, i_crit_a=i_crit_a, w_over_l=w_over_l, force=force, x=x, y=y,
                                     criteria=policy)
    else:
        found = vth_linear_extrapolation(sub, force=force, x=x, y=y, criteria=policy)
    if found.value is None:
        return Value(None, why=found.error or found.outcome, refused=found.outcome == "refused")
    return Value(float(found.value), forced=found.forced_on_untrusted, warnings=list(found.warnings))


def _current(d: RunData, read: Read, *, x: str, y: str, at_v: float | None, force: bool,
             policy: TrustPolicy) -> Value:
    """``y`` of one read: a spot read's mean over its trusted samples, or a sweep's value at ``x = at_v``."""
    sub = _sub(d, read.rows)
    sweep = x in sub.table.columns and sub.table[x].nunique(dropna=True) > 1
    r = analysed_rows(sub, x, y, policy, segment=None)
    problems = r.problems(f"read {read.cycle}", noise=False)
    forced = False
    if problems and not force:
        return Value(None, why="refused: " + "; ".join(problems), refused=True)
    if problems:
        forced = True
    if r.size == 0:
        return Value(None, why=f"read {read.cycle}: no trusted point of {y}")
    if not sweep:
        samples = [float(v) for v in r.ys]
        return Value(float(np.mean(samples)), samples=samples, forced=forced,
                     warnings=[f"forced on untrusted data in read {read.cycle}"] if forced else [])
    if at_v is None:
        raise InvalidInputError(f"read {read.cycle} is a sweep of {x}: pass at_v=<volts> for the {y} value")
    found = interpolate(r.xs, r.ys, at_v)
    if found is None:
        return Value(None, why=f"read {read.cycle}: {x} = {at_v:g} V lies outside its trusted points")
    return Value(found[0], forced=forced)


@dataclass
class Series:
    """The per-read quantity of every read and what was dropped."""

    reference: Value
    stress: list[tuple[float, Value]]
    recovery: list[tuple[float, Value]]
    t_stress: float

    def usable(self, kind: Literal["stress", "recovery"]) -> list[tuple[float, float]]:
        items = self.stress if kind == "stress" else self.recovery
        return [(t, v.value) for t, v in items if v.value is not None]

    def warnings(self) -> list[str]:
        out: list[str] = []
        for label, items in (("stress", self.stress), ("recovery", self.recovery)):
            out += [f"{label} read at t_s = {t:g} s left out: {v.why}" for t, v in items if v.value is None]
        for _, v in [(0.0, self.reference), *self.stress, *self.recovery]:
            out += v.warnings
        return out

    @property
    def forced(self) -> bool:
        return any(v.forced for _, v in [(0.0, self.reference), *self.stress, *self.recovery])


def _series(reads: list[Read], measure: Callable[[Read], Value], t_min: float | None,
            t_max: float | None) -> Series:
    reference = measure(reads[0])
    stress_reads_ = [r for r in reads[1:] if r.kind == "stress"]
    t_stress = stress_reads_[-1].t_s if stress_reads_ else 0.0
    stress = [(r.t_s, measure(r)) for r in stress_reads_
              if (t_min is None or r.t_s >= t_min) and (t_max is None or r.t_s <= t_max)]
    recovery = [(r.t_s - t_stress, measure(r)) for r in reads[1:] if r.kind == "recovery"]
    return Series(reference=reference, stress=stress, recovery=recovery, t_stress=t_stress)


def _power_law(points: list[tuple[float, float]], min_change: float) -> tuple[float, float, float, list[float]] | str:
    """``(exponent, prefactor at 1 s, r2, times used)`` of ``|Δ| = b·t^m``, or why it failed."""
    if not points:
        return "no stress read"
    signs = [math.copysign(1.0, d) for _, d in points if d != 0]
    majority = 1.0 if sum(signs) >= 0 else -1.0
    used = [(t, abs(d)) for t, d in points if t > 0 and d * majority > 0 and abs(d) >= min_change]
    if len(used) < MIN_FIT_READS:
        return (f"only {len(used)} stress read(s) change by at least {min_change:g} with the majority sign "
                f"(need {MIN_FIT_READS})")
    lt = np.log10([t for t, _ in used])
    ld = np.log10([v for _, v in used])
    slope, intercept, r2 = line_fit(lt, ld)
    return slope, 10.0 ** intercept * majority, r2, [t for t, _ in used]


def _recovery(changes: list[tuple[float, float]], end: float) -> tuple[float | None, float | None, list[float]]:
    """``(recovered fraction at the last recovery read, fraction per decade, recovery times used)`` from the
    recovery reads' changes ``(t_rec, Δ)`` and the change ``end`` at the last stress read."""
    points = [(t, v) for t, v in changes if t > 0]
    if not points or end == 0:
        return None, None, []
    fractions = [(t, v / end) for t, v in points]
    recovered = 1.0 - fractions[-1][1]
    if len(fractions) < 2:
        return recovered, None, [t for t, _ in points]
    slope, _, _ = line_fit(np.log10([t for t, _ in fractions]), np.array([f for _, f in fractions]))
    return recovered, -slope, [t for t, _ in points]


def _changes(series: Series, relative: bool) -> tuple[list[tuple[float, float]], list[tuple[float, float]]] | str:
    x0 = series.reference.value
    if x0 is None:
        return "reference read: " + series.reference.why
    scale = abs(x0) if relative else 1.0
    if scale == 0:
        return "the reference value is 0: the relative change is undefined"
    stress = [(t, (v - x0) / scale) for t, v in series.usable("stress")]
    recovery = [(t, (v - x0) / scale) for t, v in series.usable("recovery")]
    return stress, recovery


def _not_ok(out: Results, names: list[tuple[str, Unit]], why: str, refused: bool) -> list[ExtractionResult]:
    if refused:
        return [out.refused(q, u, [why], excluded={}) for q, u in names]
    return [out.failed(q, u, why, excluded={}) for q, u in names]


def _common_fit(series: Series, used: list[float]) -> dict[str, float]:
    fit = {"reads_stress": float(len(series.stress)), "reads_used": float(len(used)), "t_stress_s": series.t_stress}
    if used:
        fit.update({"t_first_s": min(used), "t_last_s": max(used)})
    return fit


def _with_recovery(out: Results, series: Series, changes: list[tuple[float, float]], change_end: float,
                   results: list[ExtractionResult], *, rate: bool) -> list[ExtractionResult]:
    if not series.recovery:
        return results
    recovered, per_decade, used = _recovery(changes, change_end)
    fit = {"t_rec_last_s": max(used) if used else 0.0, "reads_recovery": float(len(series.recovery))}
    if recovered is None:
        results.append(out.failed("recovery", "1", "no usable recovery read (or no shift to recover)", excluded={}))
        return results
    results.append(out.ok("recovery", recovered, "1", excluded={}, points_used=len(used), fit=fit))
    if rate:
        if per_decade is None:
            results.append(out.failed("recovery_rate", "1", "fewer than 2 recovery reads", excluded={}))
        else:
            results.append(out.ok("recovery_rate", per_decade, "1", excluded={}, points_used=len(used), fit=fit))
    return results


# -- bti_power_law ---------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def bti_power_law(
    d: RunData,
    *,
    vth_method: VthMethod = "constant_current",
    i_crit_a: float = Field(default=DEFAULT_I_CRIT_A, gt=0),
    w_over_l: float | None = Field(default=None, gt=0),
    x: str = "gate_V",
    y: str = "drain_I",
    t_min: float | None = Field(default=None, ge=0),
    t_max: float | None = Field(default=None, gt=0),
    min_change: float = Field(default=DEFAULT_MIN_SHIFT_V, ge=0),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """BTI threshold shift ``|ΔVth| = A·t^n`` from the reads of a stress-measure run, plus recovery (module
    docstring): ``n``, ``a``, ``dvth`` [+ ``recovery``, ``recovery_rate``]."""
    policy = trust_policy(criteria)
    reads = stress_reads(d, "bti_power_law")
    out = Results("bti_power_law", {"vth_method": vth_method, "i_crit_a": i_crit_a, "w_over_l": w_over_l, "x": x,
                                    "y": y, "t_min": t_min, "t_max": t_max, "min_change": min_change, "force": force,
                                    "trust_policy": policy_params(policy)})
    series = _series(reads, lambda r: _vth(d, r, method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x, y=y,
                                           force=force, policy=policy), t_min, t_max)
    names: list[tuple[str, Unit]] = [("n", "1"), ("a", "V"), ("dvth", "V")]
    changes = _changes(series, relative=False)
    if isinstance(changes, str):
        return _not_ok(out, names, changes, series.reference.refused)
    stress, recovery = changes
    out.warnings.extend(series.warnings())
    if series.forced:
        out.flag(["at least one read was extracted from untrusted data"])
    if not stress:
        return _not_ok(out, names, "no usable stress read", False)
    fitted = _power_law(stress, min_change)
    end = stress[-1][1]
    results: list[ExtractionResult] = []
    if isinstance(fitted, str):
        results += [out.failed(q, u, fitted, excluded={}) for q, u in names[:2]]
    else:
        exponent, prefactor, r2, used = fitted
        fit = {**_common_fit(series, used), "r2": r2, "vth0_v": series.reference.value or 0.0}
        results += [out.ok("n", exponent, "1", excluded={}, points_used=len(used), fit=fit),
                    out.ok("a", abs(prefactor), "V", excluded={}, points_used=len(used), fit=fit)]
    results.append(out.ok("dvth", end, "V", excluded={}, points_used=len(stress),
                          fit={"t_stress_s": series.t_stress, "vth0_v": series.reference.value or 0.0}))
    return _with_recovery(out, series, recovery, end, results, rate=True)


# -- degradation_vs_time ---------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def degradation_vs_time(
    d: RunData,
    *,
    quantity: ReadQuantity = "id",
    fit: StressFit = "power_law",
    relative: bool | None = None,
    x: str = "gate_V",
    y: str | None = None,
    at_v: float | None = None,
    vth_method: VthMethod = "constant_current",
    i_crit_a: float = Field(default=DEFAULT_I_CRIT_A, gt=0),
    w_over_l: float | None = Field(default=None, gt=0),
    t_min: float | None = Field(default=None, ge=0),
    t_max: float | None = Field(default=None, gt=0),
    min_change: float | None = Field(default=None, ge=0),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Degradation of one read quantity against stress time (module docstring): ``delta`` [+ ``b``, ``m`` or
    ``tau``, ``beta``, ``delta_inf``] [+ ``recovery``]."""
    policy = trust_policy(criteria)
    reads = stress_reads(d, "degradation_vs_time")
    column = y or ("gate_I" if quantity == "ig" else "drain_I")
    if column not in d.measured_columns:
        raise InvalidInputError(f"degradation_vs_time: {column!r} is not a measured column of run {d.run_id}; "
                                f"measured: {d.measured_columns}.")
    is_relative = relative if relative is not None else quantity != "vth"
    if min_change is None:
        min_change = DEFAULT_MIN_RELATIVE if is_relative else (DEFAULT_MIN_SHIFT_V if quantity == "vth"
                                                               else DEFAULT_MIN_CURRENT_A)
    out = Results("degradation_vs_time", {"quantity": quantity, "fit": fit, "relative": is_relative, "x": x,
                                          "y": column, "at_v": at_v, "vth_method": vth_method, "i_crit_a": i_crit_a,
                                          "w_over_l": w_over_l, "t_min": t_min, "t_max": t_max,
                                          "min_change": min_change, "force": force,
                                          "trust_policy": policy_params(policy)})
    if quantity == "vth":
        series = _series(reads, lambda r: _vth(d, r, method=vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l, x=x,
                                               y=column, force=force, policy=policy), t_min, t_max)
        unit: Unit = "V"
    else:
        series = _series(reads, lambda r: _current(d, r, x=x, y=column, at_v=at_v, force=force, policy=policy),
                         t_min, t_max)
        unit = "A"
    change_unit: Unit = "1" if is_relative else unit
    names: list[tuple[str, Unit]] = [("delta", change_unit)]
    names += {"power_law": [("b", change_unit), ("m", "1")], "stretched_exp": [("tau", "s"), ("beta", "1"),
                                                                              ("delta_inf", change_unit)],
              "none": []}[fit]
    changes = _changes(series, relative=is_relative)
    if isinstance(changes, str):
        return _not_ok(out, names, changes, series.reference.refused)
    stress, recovery = changes
    out.warnings.extend(series.warnings())
    if series.forced:
        out.flag(["at least one read was extracted from untrusted data"])
    if not stress:
        return _not_ok(out, names, "no usable stress read", False)
    end = stress[-1][1]
    results = [out.ok("delta", end, change_unit, excluded={}, points_used=len(stress),
                      fit={"t_stress_s": series.t_stress, "x0": series.reference.value or 0.0})]
    if fit == "power_law":
        fitted = _power_law(stress, min_change)
        if isinstance(fitted, str):
            results += [out.failed(q, u, fitted, excluded={}) for q, u in names[1:]]
        else:
            exponent, prefactor, r2, used = fitted
            details = {**_common_fit(series, used), "r2": r2}
            results += [out.ok("b", prefactor, change_unit, excluded={}, points_used=len(used), fit=details),
                        out.ok("m", exponent, "1", excluded={}, points_used=len(used), fit=details)]
    elif fit == "stretched_exp":
        ts = np.array([0.0, *(t for t, _ in stress)])
        ys = np.array([0.0, *(v for _, v in stress)])
        try:
            p = fit_stretched_exponential(ts, ys)
        except ValueError as exc:
            results += [out.failed(q, u, str(exc), excluded={}) for q, u in names[1:]]
        else:
            warnings = []
            if p["tau"] > 3.0 * float(ts[-1]):
                warnings.append(f"tau {p['tau']:.3g} s lies beyond 3x the last read {ts[-1]:.3g} s: poorly "
                                "constrained; stress longer.")
            if not BETA_GRID[0] + 0.01 < p["beta"] < BETA_GRID[1] - 0.01:
                warnings.append(f"beta {p['beta']:.3g} sits at the edge of the searched range {list(BETA_GRID)}.")
            details = {**_common_fit(series, [t for t, _ in stress]), "r2": p["r2"], "rms": p["rms"],
                       "y0": p["y0"], "tau_se": p["tau_se"], "beta_se": p["beta_se"]}
            common = {"excluded": {}, "points_used": len(stress), "fit": details, "warnings": warnings}
            results += [out.ok("tau", p["tau"], "s", **common), out.ok("beta", p["beta"], "1", **common),
                        out.ok("delta_inf", p["y_inf"], change_unit, **common)]
    return _with_recovery(out, series, recovery, end, results, rate=False)


# -- silc ------------------------------------------------------------------------------------------------------------


def _sense_level(d: RunData, v_sense: float | None) -> float | None:
    if v_sense is not None:
        return v_sense
    quantity = d.param(SENSE_PARAM)
    if quantity is not None and quantity.is_number:
        return quantity.as_float()
    return None


def _q_inj(d: RunData, y: str, policy: TrustPolicy) -> tuple[float, int] | None:
    """``(∫|y| dt over the stress monitor rows, rows used)`` (module docstring), ``None`` without monitor rows."""
    table = d.table
    rows = table[table[PHASE] == "stress"]
    if rows.empty or y not in rows.columns:
        return None
    ok = (trust_levels(rows, policy, columns=[y]) == "ok").to_numpy() & np.isfinite(rows[y].to_numpy(dtype=float))
    t = rows[T_S].to_numpy(dtype=float)[ok]
    i = np.abs(rows[y].to_numpy(dtype=float)[ok])
    if t.size == 0:
        return None
    order = np.argsort(t, kind="stable")
    t, i = np.concatenate([[0.0], t[order]]), np.concatenate([[i[order][0]], i[order]])
    return float(np.sum(0.5 * (i[1:] + i[:-1]) * np.diff(t))), int(ok.sum())


@validate_call(config=_CALL_CONFIG)
def silc(
    d: RunData,
    *,
    y: str = "gate_I",
    x: str = "gate_V",
    v_sense: float | None = None,
    min_ratio: float = Field(default=0.02, ge=0),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Stress-induced leakage current (module docstring): ``silc_ratio``, ``silc_exponent``, ``ig0``, ``q_inj``."""
    policy = trust_policy(criteria)
    reads = stress_reads(d, "silc")
    if y not in d.measured_columns:
        raise InvalidInputError(f"silc: {y!r} is not a measured column of run {d.run_id}; measured: "
                                f"{d.measured_columns}.")
    if status_column(y) not in d.table.columns:
        raise InvalidInputError(f"silc: {y!r} has no status column.")
    sense = _sense_level(d, v_sense)
    out = Results("silc", {"y": y, "x": x, "v_sense": sense, "min_ratio": min_ratio, "force": force,
                           "trust_policy": policy_params(policy)})
    series = _series(reads, lambda r: _magnitude(_current(d, r, x=x, y=y, at_v=sense, force=force, policy=policy)),
                     None, None)
    names: list[tuple[str, Unit]] = [("silc_ratio", "1"), ("silc_exponent", "1"), ("ig0", "A")]
    changes = _changes(series, relative=True)
    if isinstance(changes, str):
        return _not_ok(out, names, changes, series.reference.refused)
    stress, _ = changes
    out.warnings.extend(series.warnings())
    if series.forced:
        out.flag(["at least one read was extracted from untrusted data"])
    ig0 = float(series.reference.value or 0.0)
    samples = series.reference.samples
    sem0 = float(np.std(samples, ddof=1) / math.sqrt(len(samples))) if len(samples) >= 2 else 0.0
    threshold = max(min_ratio, SILC_SIGMAS * math.sqrt(2.0) * sem0 / ig0 if ig0 else 0.0)
    fit_info = {"v_sense_v": sense if sense is not None else math.nan, "sem0_a": sem0,
                "threshold_ratio": threshold, "t_stress_s": series.t_stress}
    results = [out.ok("ig0", ig0, "A", excluded={}, points_used=max(1, len(samples)), fit=fit_info)]
    if not stress:
        results += [out.failed(q, u, "no usable stress read", excluded={}) for q, u in names[:2]]
    else:
        results.append(out.ok("silc_ratio", stress[-1][1], "1", excluded={}, points_used=len(stress), fit=fit_info))
        fitted = _power_law(stress, threshold)
        if isinstance(fitted, str):
            results.append(out.failed("silc_exponent", "1", fitted, excluded={}))
        else:
            exponent, prefactor, r2, used = fitted
            results.append(out.ok("silc_exponent", exponent, "1", excluded={}, points_used=len(used),
                                  fit={**_common_fit(series, used), "r2": r2, "ratio_at_1s": prefactor,
                                       "threshold_ratio": threshold}))
    charge = _q_inj(d, y, policy)
    if charge is None:
        results.append(out.failed("q_inj", "C", "no trusted stress monitor row of the gate current", excluded={}))
    else:
        results.append(out.ok("q_inj", charge[0], "C", excluded={}, points_used=charge[1],
                              fit={"t_stress_s": series.t_stress}))
    return results


def _magnitude(value: Value) -> Value:
    if value.value is None:
        return value
    return Value(abs(value.value), why=value.why, samples=[abs(s) for s in value.samples], refused=value.refused,
                 forced=value.forced, warnings=value.warnings)


__all__ = ["Read", "bti_power_law", "degradation_vs_time", "silc", "stress_reads"]
