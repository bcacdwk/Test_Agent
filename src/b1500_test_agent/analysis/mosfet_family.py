"""MOSFET threshold families (blueprint v2 2.10 ``dibl``; WP7.2): transfer curves (Id-Vg) at several drain biases
(DIBL) or body biases (body effect), as recorded by kind ``smu_stepped`` (``mosfet.idvg_family``,
``mosfet.body_effect``).

Definitions (the single source of knowledge file ``06-analysis-extraction.md`` of skill ``b1500-test``; change both
together; trust, refusal and the constant-current criterion as in ``mosfet.py``):

- **Curves**: the rows grouped by the step column (default: the one varying source voltage column other than
  ``x``, e.g. ``drain_V`` or ``bulk_V``; with a single curve the one other source voltage column), in acquisition
  order; per curve the constant-current Vth of ``mosfet.py``
  (``i_crit_a`` x ``w_over_l``, default 100 nA: the ``mosfet.py`` convention, set it per device; interpolated in
  log10|Id|).
- **DIBL** (``dibl``, mV/V; the step is the drain bias): ``s·(Vth(Vd_lo) - Vth(Vd_hi)) / (|Vd_hi| - |Vd_lo|)``
  between the curves of the lowest and the highest |Vd| (s = +1 for n-type, -1 for p-type curves, so a barrier
  lowering is positive for both), plus ``vth_lin``/``vth_sat`` (V), the Vth of those two curves; ``fit`` adds every
  curve's Vth and, with three or more curves, the least-squares slope ``slope_mv_per_v``. The weak-inversion current
  carries the drain factor ``1 - exp(-|Vd|/U_T)`` (it raises Vth by ``-n U_T ln(1 - exp(-|Vd|/U_T))``: about 0.7 mV
  at Vd = 0.1 V and 5 mV at 50 mV for n ≈ 1.3 at 300 K) and channel-length modulation; this standard two-point
  definition counts both as DIBL, so a linear curve at Vd >= 0.1 V keeps them below a few mV/V.
- **Body effect** (``body_effect``, V/V; the step is the bulk bias): the least-squares slope dVth/dVsb over the
  curves, Vsb = V_source - V_bulk (``source_v``; default 0 V, the source on the GNDU; a constant ``source_V``
  column is used when the run has one), positive for an n- or p-channel device under reverse body bias, plus
  ``vth_vsb0`` (V), the fitted Vth at Vsb = 0; ``fit`` adds every curve's Vth, the Vsb range and r2 (r2 < 0.99 with
  three or more curves: a warning that the square-root law bends over the range).
- **Refusal**: a curve with untrusted rows or a noise-dominated current has no Vth (refused, unless ``force``); a
  curve without a crossing has none either (failed). Such curves are left out with a warning; each method needs two
  curves with a Vth (two different |Vd| for DIBL), and a DIBL end curve without one refuses or fails the result.

Both methods default to ``x="gate_V"``, ``y="drain_I"`` and analyse one sweep segment (``segment``, default ``fwd``)
of every curve; the curves are grouped by the step column in acquisition order (``table.groupby(step, sort=False)``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pydantic import validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    increasing_with_x,
    line_fit,
    require_iv,
    strictly_monotonic,
    trust_policy,
    varying_sources,
    window_of,
)
from b1500_test_agent.analysis.dataset import RunData, Segment
from b1500_test_agent.analysis.mosfet import (
    _CALL_CONFIG,
    DEFAULT_I_CRIT_A,
    MIN_R2,
    PositiveFloat,
    _base_params,
    _cc_crossing,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

# -- the threshold families --------------------------------------------------------------------------


def _family_step(d: RunData, rows: pd.DataFrame, x: str, step: str | None, method: str) -> str:
    """The step column of a transfer family: ``step``, else the only other varying source voltage column, else (a
    family of one curve) the only other source voltage column."""
    if step is None:
        others = [c for c in varying_sources(rows, d) if c != x]
        if not others:
            others = [c for c in d.source_columns if c.endswith("_V") and c != x]
        if len(others) != 1:
            raise InvalidInputError(f"{method}: cannot choose the step column of run {d.run_id} among {others}; "
                                    "pass step=<column>.")
        return others[0]
    if step not in d.source_columns:
        raise InvalidInputError(f"{method}: step {step!r} is not a source column of run {d.run_id} "
                                f"({d.source_columns}).")
    return step


@dataclass(frozen=True)
class _Curve:
    """One curve of a threshold family: its step level, Vth (``None`` when refused or failed, ``why``) and the
    excluded-point counts."""

    level: float
    vth: float | None
    why: str
    excluded: dict[str, int]

    @property
    def refused(self) -> bool:
        return self.why.startswith("refused")


def _family_vths(d: RunData, rows: pd.DataFrame, x: str, y: str, step: str, i_crit: float, force: bool,
                 policy: TrustPolicy, out: Results) -> list[_Curve]:
    """Constant-current Vth per curve, in acquisition order."""
    found = []
    for level, curve in rows.groupby(step, sort=False):
        where = f"curve {step} = {float(level):g}"
        r = analysed_rows(d, x, y, policy, rows=curve)
        if r.size >= 2 and not strictly_monotonic(r.xs):
            raise InvalidInputError(f"{x} is not strictly monotonic within {where}.")
        problems = r.problems(where)
        if problems and not force:
            found.append(_Curve(float(level), None, "refused: " + "; ".join(problems), r.excluded()))
            continue
        out.flag(problems)
        crossing = _cc_crossing(r, i_crit, y, where)
        if isinstance(crossing, str):
            found.append(_Curve(float(level), None, crossing, r.excluded()))
            continue
        value, (i0, i1), _, warnings = crossing
        out.warnings.extend(warnings)
        r.use([i0, i1])
        found.append(_Curve(float(level), value, "", r.excluded()))
    return found


def _vth(curve: _Curve) -> float:
    if curve.vth is None:
        raise ValueError(f"curve {curve.level:g} has no Vth")
    return curve.vth


def _merge_excluded(curves: list[_Curve]) -> dict[str, int]:
    total: dict[str, int] = {}
    for curve in curves:
        for key, count in curve.excluded.items():
            total[key] = total.get(key, 0) + count
    return dict(sorted(total.items()))


def _n_type(rows: pd.DataFrame, x: str, y: str) -> bool:
    """True when |y| grows with x over the finite rows of the family (n-type transfer curves)."""
    xs, ys = rows[x].to_numpy(dtype=float), rows[y].to_numpy(dtype=float)
    keep = np.isfinite(xs) & np.isfinite(ys)
    return increasing_with_x(xs[keep], ys[keep]) if keep.sum() >= 2 else True


def _not_ok(out: Results, quantities: tuple[tuple[str, Unit], ...], why: str, refused: bool,
            excluded: dict[str, int], fit: dict[str, float]) -> list[ExtractionResult]:
    if refused:
        return [out.refused(q, unit, [why], excluded=excluded, fit=fit) for q, unit in quantities]
    return [out.failed(q, unit, why, excluded=excluded, fit=fit) for q, unit in quantities]


DIBL_QUANTITIES: tuple[tuple[str, Unit], ...] = (("dibl", "mV/V"), ("vth_lin", "V"), ("vth_sat", "V"))


@validate_call(config=_CALL_CONFIG)
def dibl(
    d: RunData,
    *,
    step: str | None = None,
    x: str = "gate_V",
    y: str = "drain_I",
    i_crit_a: PositiveFloat = DEFAULT_I_CRIT_A,
    w_over_l: PositiveFloat | None = None,
    segment: Segment = "fwd",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Drain-induced barrier lowering of a transfer family (module docstring): ``dibl`` (mV/V), ``vth_lin`` and
    ``vth_sat`` (V) of the lowest- and highest-|Vd| curves; a refused or failed end curve makes all three non-ok."""
    policy = trust_policy(criteria)
    require_iv(d, x, y, "dibl")
    rows = d.rows(segment)
    step = _family_step(d, rows, x, step, "dibl")
    i_crit = i_crit_a * (w_over_l if w_over_l is not None else 1.0)
    out = Results("dibl", _base_params(policy, step=step, x=x, y=y, i_crit_a=i_crit_a, w_over_l=w_over_l,
                                       i_crit=i_crit, segment=segment, force=force))
    curves = _family_vths(d, rows, x, y, step, i_crit, force, policy, out)
    excluded = _merge_excluded(curves)
    fit = {f"{step}={c.level:g}": c.vth for c in curves if c.vth is not None}
    if len({abs(c.level) for c in curves}) < 2:
        why = f"dibl needs curves at two different |{step}|; run {d.run_id} has {[c.level for c in curves]}."
        return _not_ok(out, DIBL_QUANTITIES, why, False, excluded, fit)
    low = min(curves, key=lambda c: abs(c.level))
    high = max(curves, key=lambda c: abs(c.level))
    for end in (low, high):
        if end.vth is None:
            why = f"Vth of the end curve {step} = {end.level:g} V: {end.why}"
            return _not_ok(out, DIBL_QUANTITIES, why, end.refused, excluded, fit)
    vth_lo, vth_hi = _vth(low), _vth(high)
    sign = 1.0 if _n_type(rows, x, y) else -1.0
    value = sign * (vth_lo - vth_hi) / (abs(high.level) - abs(low.level)) * 1000.0
    valid = [c for c in curves if c.vth is not None]
    fit.update(vd_lo=low.level, vd_hi=high.level, vth_lo=vth_lo, vth_hi=vth_hi)
    if len(valid) >= 3:
        slope, _, r2 = line_fit(np.array([abs(c.level) for c in valid]), np.array([c.vth for c in valid]))
        fit.update(slope_mv_per_v=-sign * slope * 1000.0, slope_r2=r2)
    warnings = [f"{step} = {c.level:g} V: {c.why}" for c in curves if c.vth is None]
    window = window_of(np.array([abs(low.level), abs(high.level)]), "V")
    return [
        out.ok("dibl", value, "mV/V", excluded=excluded, points_used=2 * len(valid), window=window, fit=fit,
               warnings=warnings),
        out.ok("vth_lin", vth_lo, "V", excluded=excluded, points_used=2, fit={"vd": low.level}),
        out.ok("vth_sat", vth_hi, "V", excluded=excluded, points_used=2, fit={"vd": high.level}),
    ]


BODY_QUANTITIES: tuple[tuple[str, Unit], ...] = (("body_effect", "1"), ("vth_vsb0", "V"))
SOURCE_COLUMN = "source_V"
"""A run's source-terminal voltage column, when the source is on an SMU (Vsb = V_source - V_bulk)."""


@validate_call(config=_CALL_CONFIG)
def body_effect(
    d: RunData,
    *,
    step: str | None = None,
    x: str = "gate_V",
    y: str = "drain_I",
    source_v: float | None = None,
    i_crit_a: PositiveFloat = DEFAULT_I_CRIT_A,
    w_over_l: PositiveFloat | None = None,
    segment: Segment = "fwd",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Body-effect coefficient of a transfer family over body biases (module docstring): ``body_effect`` = dVth/dVsb
    (V/V, least squares over the curves) and ``vth_vsb0`` (V), the fitted Vth at Vsb = 0."""
    policy = trust_policy(criteria)
    require_iv(d, x, y, "body_effect")
    rows = d.rows(segment)
    step = _family_step(d, rows, x, step, "body_effect")
    i_crit = i_crit_a * (w_over_l if w_over_l is not None else 1.0)
    if source_v is not None:
        vs, vs_source = float(source_v), "argument"
    elif SOURCE_COLUMN in d.source_columns and step != SOURCE_COLUMN:
        values = rows[SOURCE_COLUMN].dropna().unique()
        if len(values) != 1:
            raise InvalidInputError(f"body_effect: {SOURCE_COLUMN} varies in run {d.run_id}; pass source_v=<volts>.")
        vs, vs_source = float(values[0]), SOURCE_COLUMN
    else:
        vs, vs_source = 0.0, "default (source on the GNDU)"
    out = Results("body_effect", _base_params(policy, step=step, x=x, y=y, source_v=vs, source_v_from=vs_source,
                                              i_crit_a=i_crit_a, w_over_l=w_over_l, i_crit=i_crit, segment=segment,
                                              force=force))
    curves = _family_vths(d, rows, x, y, step, i_crit, force, policy, out)
    excluded = _merge_excluded(curves)
    valid = [c for c in curves if c.vth is not None]
    fit = {f"{step}={c.level:g}": c.vth for c in valid}
    warnings = [f"{step} = {c.level:g} V: {c.why}" for c in curves if c.vth is None]
    if len({c.level for c in valid}) < 2:
        why = f"body_effect needs a valid Vth at two body biases ({'; '.join(warnings) or 'one curve'})."
        return _not_ok(out, BODY_QUANTITIES, why, any(c.refused for c in curves), excluded, fit)
    vsb = np.array([vs - c.level for c in valid])
    vth = np.array([c.vth for c in valid], dtype=float)
    slope, intercept, r2 = line_fit(vsb, vth)
    fit.update(r2=r2, vsb_min=float(vsb.min()), vsb_max=float(vsb.max()))
    if r2 < MIN_R2 and len(valid) > 2:
        warnings.append(f"Vth against Vsb is not linear (r2 {r2:.4f}): the square-root law bends over this range; "
                        "the slope is an average coefficient.")
    window = window_of(vsb, "V")
    used = 2 * len(valid)
    return [
        out.ok("body_effect", slope, "1", excluded=excluded, points_used=used, window=window, fit=fit,
               warnings=warnings),
        out.ok("vth_vsb0", intercept, "V", excluded=excluded, points_used=used, window=window, fit={"r2": r2}),
    ]
