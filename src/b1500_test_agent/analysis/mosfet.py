"""MOSFET extraction (blueprint 2.8; v2 2.10): transconductance, threshold voltage (three methods), subthreshold
swing, maximum gm, Ion/Ioff of a transfer curve (Id-Vg), the output metrics of an Id-Vd family and the threshold
families of transfer curves at several drain or body biases (DIBL, body effect).

Definitions (the single source of knowledge file ``06-analysis-extraction.md`` of skill ``b1500-test``; change both
together). Transfer-curve methods default to ``x="gate_V"``, ``y="drain_I"`` and analyse one sweep segment
(``segment``, default ``fwd``; a single sweep is ``fwd``):

- **gm** = dId/dVg, the slope of a local quadratic least-squares fit over ``smooth`` neighbouring trusted points
  (Savitzky-Golay equivalent on a uniform grid, exact on a non-uniform one; ``smooth=1`` = central differences).
- **Vth, linear extrapolation** (``vth_linear_extrapolation``; linear region, small Vd): fit a straight line
  Id = a + b Vg through the window, take its Vg-axis intercept Vg0 = -a/b and report Vth = Vg0 - Vd/2
  (``subtract_half_vd``), because the linear-region current is beta (Vg - Vth - Vd/2) Vd. Default window: the
  ``fit_points`` trusted points centred on the maximum of |gm| (the tangent at maximum gm); or an explicit
  ``(lo, hi)`` gate-voltage window.
- **Vth, constant current** (``vth_constant_current``): the gate voltage at which |Id| first reaches the critical
  current I_crit = ``i_crit_a`` x ``w_over_l`` (``i_crit_a`` alone without ``w_over_l``; default 100 nA, a common
  convention and an example criterion: set it per device and report it), walking
  the trusted points in the direction of increasing |Id| (rising Vg for n-type, falling Vg for p-type); log10|Id|
  is interpolated linearly in Vg between the two bracketing points. More than one crossing → warning.
- **Vth, maximum gm change** (``vth_max_gm``; the second-derivative or transconductance-change method): the gate
  voltage where gm rises fastest, i.e. the maximum of s·dgm/dVg (s = +1 when |Id| grows with Vg, -1 otherwise;
  both derivatives with ``smooth`` points), refined by a parabola through the peak and its two neighbours, minus
  Vd/2 (``subtract_half_vd``: in the linear region gm turns on between Vth and Vth + Vd). ``fit`` also reports the
  gate voltage of maximum gm.
- **Drain bias Vd** for the Vd/2 corrections: the ``vd`` argument if given; else the run plan's resolved parameter
  named ``vd_param`` (default ``vd``, the parameter the drain role's bias setting references in ``mosfet.idvg``),
  which must be a scalar in volts. Missing → ``InvalidInputError`` (pass ``vd=`` or ``subtract_half_vd=False``).
- **Subthreshold swing** (``subthreshold_swing``, mV/dec): SS = 1000 / |d log10|Id| / dVg| from a straight-line fit
  of log10|Id| against Vg over a sliding window, reported for the window with the smallest SS (the steepest part of
  the subthreshold region). Window: ``fit_points`` consecutive trusted points, or, with ``decades``, the shortest
  run of consecutive points whose |Id| spans at least ``decades`` decades. A window counts only when |Id| is non-zero
  and strictly monotonic in it, grows in the transfer direction and its fit has r2 >= ``min_r2`` (this rejects the
  noise floor, where log10|Id| scatters).
- **Maximum gm** (``gm_max``, S): gm at the trusted point of maximum |gm| (signed value), with its gate voltage and
  drain current in ``fit``.
- **Ion/Ioff** (``ion_ioff``): Ion = |Id| at ``v_on``, Ioff = |Id| at ``v_off`` (linear interpolation between the
  bracketing trusted points), on/off ratio = Ion/Ioff. Defaults: ``v_on`` = the sweep end with the larger |Id|,
  ``v_off`` = the other end. A current at the noise floor (log10|Id| rough around the point, see
  ``common.floor_limit``) is reported as an upper bound of 3 noise standard deviations (``bound="upper"``; the ratio
  is then a lower bound).
- **Output metrics** (``output_metrics``; Id-Vd family, ``x="drain_V"``, ``y="drain_I"``, curves grouped by the
  step column ``step``, default the other varying source voltage, e.g. ``gate_V``): per curve, **Ron** = 1/gd at the
  lowest |Vd| (gd = dId/dVd, local quadratic fit over ``smooth`` points: the deep-linear-region on-resistance incl.
  series resistance); **gds** = slope of a straight-line fit of Id against Vd over the trusted points in the top
  ``sat_window`` fraction of the |Vd| span (saturation output conductance); **Vd_sat** = the first |Vd| (walking
  away from Vd = 0) at which gd falls to ``sat_ratio`` x gd(Vd_min), interpolated linearly (saturation onset).
  The results are those of one curve (``curve`` = its step level; default the strongest drive, the largest |step|,
  in ``fit["step_v"]``); each also lists that quantity for every curve of the family in ``fit`` under
  ``<step>=<level>`` (e.g. ``gate_V=1.5``), and the other curves' refusals or failures as warnings.
- **Threshold families** (``dibl``, ``body_effect``): transfer curves at several drain or body biases, defined in
  ``mosfet_family.py`` (constant-current Vth per curve as above).

Trust and refusal (every method; ``criteria``, default ``QualityCriteria()``): a row's level is the worst of its
measured values. Limited (``C``/``T``) and untrusted rows never enter a derivative, a fit or an interpolation;
``points_excluded`` counts them by deciding status letter, rows with missing values as ``missing`` and trusted rows
outside the window as ``outside_window`` (``points_used`` + excluded = rows of the analysed segment). The extraction
is **refused** (``outcome="refused"``, ``value=None``) when the analysed segment (curve) contains any untrusted row
or its trusted response is noise-dominated (range < ``MIN_SNR`` x noise), unless ``force=True``: then the value is
computed from the trusted rows only and flagged (``forced_on_untrusted=True`` + warning). More limited rows inside
the window than ``criteria.max_limited_fraction_in_fit`` → warning. Data that do not allow the method (too few
points, no crossing, no subthreshold region) → ``outcome="failed"``. A refused or failed call returns one result for
its primary quantity (``output_metrics``: its three quantities). Derived numbers (values, windows, ``fit``) of the
M2 methods are rounded to 7 significant digits (``common.SIGNIFICANT_DIGITS``), finer than the instrument resolves.
The classifying methods ``resistance`` and ``leakage_at`` (``resistor.py``, ``leakage.py``) apply the same refusal
rule but read a compliance stop as a result (short, leakage above the compliance) and a noise-dominated response as a
measurement at the floor.
"""

from __future__ import annotations

import itertools
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import AfterValidator, ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    Rows,
    analysed_rows,
    floor_limit,
    increasing_with_x,
    interpolate,
    line_fit,
    peak_index,
    policy_params,
    require_iv,
    strictly_monotonic,
    trust_policy,
    varying_sources,
    window_of,
)
from b1500_test_agent.analysis.dataset import RunData, Segment, row_reasons, trust_levels
from b1500_test_agent.analysis.quality import MIN_SNR, noise_sigma, signal_to_noise
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import (
    Bound,
    DerivativeMethod,
    ExtractionResult,
    MethodRecord,
    QuantityRange,
    TrustPolicy,
    Unit,
)
from b1500_test_agent.models.recipe import QualityCriteria

METHOD_VERSION = "1"
DRAIN_BIAS_PARAM = "vd"
"""Resolved plan parameter holding the drain bias (V) of a transfer-curve recipe."""

MIN_R2 = 0.99
"""A linear fit with a lower coefficient of determination gets a warning."""

_FLAT = 1e-9
"""A fitted line whose change across the window is below this fraction of the current level counts as flat."""

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


def _odd_or_one(value: int) -> int:
    if value != 1 and value % 2 == 0:
        raise ValueError("smooth must be 1 (central differences) or an odd number of points >= 3.")
    return value


def _ordered(window: tuple[float, float]) -> tuple[float, float]:
    if not window[0] < window[1]:
        raise ValueError("window must be (lo, hi) with lo < hi.")
    return window


Smooth = Annotated[int, Field(ge=1, le=101), AfterValidator(_odd_or_one)]
FitPoints = Annotated[int, Field(ge=2, le=101)]
FitWindow = Annotated[tuple[float, float], AfterValidator(_ordered)]


def derivative_method(smooth: int) -> DerivativeMethod:
    """The declared derivative that ``local_derivative`` computes for ``smooth``."""
    if smooth < 3:
        return DerivativeMethod(name="central_difference")
    return DerivativeMethod(name="savitzky_golay", window_points=smooth, polyorder=2)


def local_derivative(x: np.ndarray, y: np.ndarray, smooth: int = 5) -> np.ndarray:
    """dy/dx at every point: slope at x[i] of a quadratic least-squares fit over the ``smooth`` points around i
    (window shifted inward at the ends); ``smooth < 3`` or fewer than 3 points → ``numpy.gradient``. ``x`` must be
    strictly monotonic."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    if n < 2:
        raise ValueError("A derivative needs at least two points.")
    if smooth < 3 or n < 3:
        return np.gradient(y, x)
    width = min(smooth, n if n % 2 else n - 1)
    half = width // 2
    start = np.clip(np.arange(n) - half, 0, n - width)
    index = start[:, None] + np.arange(width)[None, :]
    dx = x[index] - x[:, None]
    scale = np.abs(dx).max(axis=1, keepdims=True)
    u = dx / scale
    basis = np.stack([np.ones_like(u), u, u * u], axis=-1)
    normal = np.einsum("nwi,nwj->nij", basis, basis)
    rhs = np.einsum("nwi,nw->ni", basis, y[index])
    coefficients = np.linalg.solve(normal, rhs[..., None])[..., 0]
    return coefficients[:, 1] / scale[:, 0]


def _ratio_unit(y_unit: Unit, x_unit: Unit) -> Unit:
    if y_unit == "A" and x_unit == "V":
        return "S"
    if y_unit == "V" and x_unit == "A":
        return "Ohm"
    return "1"


def _strictly_monotonic(x: np.ndarray) -> bool:
    steps = np.diff(x)
    return bool(np.all(steps > 0) or np.all(steps < 0))


def _finite_xy(rows: pd.DataFrame, x: str, y: str) -> np.ndarray:
    return np.isfinite(rows[x].to_numpy(dtype=float)) & np.isfinite(rows[y].to_numpy(dtype=float))


@validate_call(config=_CALL_CONFIG)
def gm(
    d: RunData,
    *,
    x: str = "gate_V",
    y: str = "drain_I",
    smooth: Smooth = 5,
    segment: Segment | None = None,
    policy: TrustPolicy | None = None,
) -> pd.Series:
    """Transconductance dy/dx per row (``local_derivative`` over the trusted rows of each segment, or only of
    ``segment``); ``NaN`` for limited, untrusted, missing or other-segment rows. ``attrs["unit"]`` is ``S`` for
    A over V. The table itself is never modified."""
    x_unit, y_unit = d.unit(x), d.unit(y)
    out = pd.Series(np.nan, index=d.table.index, name="gm", dtype=float)
    for seg in [segment] if segment is not None else d.segments():
        rows = d.rows(seg)
        keep = (trust_levels(rows, policy) == "ok").to_numpy(dtype=bool) & _finite_xy(rows, x, y)
        used = rows[keep]
        if len(used) < 2:
            continue
        xs, ys = used[x].to_numpy(dtype=float), used[y].to_numpy(dtype=float)
        if not _strictly_monotonic(xs):
            raise InvalidInputError(f"{x} is not strictly monotonic within segment {seg or 'fwd'}.")
        out.loc[used.index] = local_derivative(xs, ys, smooth)
    out.attrs["unit"] = _ratio_unit(y_unit, x_unit)
    return out


def _drain_bias(d: RunData, vd: float | None, vd_param: str) -> tuple[float, str]:
    if vd is not None:
        return vd, "argument"
    quantity = d.param(vd_param)
    if quantity is None:
        raise InvalidInputError(
            f"subtract_half_vd needs the drain bias, but run {d.run_id} has no resolved plan parameter "
            f"{vd_param!r}; pass vd=<volts> (or vd_param=<name>), or subtract_half_vd=False."
        )
    if not quantity.is_number or quantity.unit != "V":
        raise InvalidInputError(f"Plan parameter {vd_param!r} is not a voltage: {quantity.value!r} {quantity.unit}.")
    return quantity.as_float(), f"plan.resolved_params.{vd_param}"


def _excluded(reasons: pd.Series) -> dict[str, int]:
    counts = reasons.value_counts()
    return {str(k): int(v) for k, v in sorted(counts.items())}


@validate_call(config=_CALL_CONFIG)
def vth_linear_extrapolation(
    d: RunData,
    *,
    window: Literal["max_gm"] | FitWindow = "max_gm",
    subtract_half_vd: bool = True,
    segment: Segment = "fwd",
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    vd: float | None = None,
    vd_param: str = DRAIN_BIAS_PARAM,
    smooth: Smooth = 5,
    fit_points: FitPoints = 5,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Threshold voltage by linear extrapolation of the linear-region transfer curve (see the module docstring for
    the definition, window rule, Vd source, exclusions and refusal). Returns one ``ExtractionResult``
    (``quantity="vth"``, unit of ``x``); refusals and failures come back with ``value=None``, never as exceptions.
    Raises ``InvalidInputError`` for unusable arguments (unknown column, missing Vd, non-monotonic sweep)."""
    policy = criteria if criteria is not None else QualityCriteria()
    max_limited = getattr(policy, "max_limited_fraction_in_fit", QualityCriteria().max_limited_fraction_in_fit)
    x_unit, y_unit = d.unit(x), d.unit(y)
    if x_unit != "V" or y_unit != "A":
        raise InvalidInputError(f"vth_linear_extrapolation needs a voltage x and a current y; got {x}, {y}.")
    bias, bias_source = _drain_bias(d, vd, vd_param) if subtract_half_vd else (None, None)
    params: dict[str, Any] = {
        "x": x, "y": y, "window": window if window == "max_gm" else list(window), "subtract_half_vd": subtract_half_vd,
        "segment": segment, "force": force, "smooth": smooth, "fit_points": fit_points,
        "derivative": derivative_method(smooth).model_dump(exclude_none=True),
        "vd": bias, "vd_source": bias_source, "trust_policy": policy.model_dump(),
    }  # fmt: skip
    record = MethodRecord(name="vth_linear_extrapolation", version=METHOD_VERSION, params=params)

    rows = d.rows(segment)
    levels = trust_levels(rows, policy)
    reasons = row_reasons(rows, policy)
    finite = pd.Series(_finite_xy(rows, x, y), index=rows.index)
    reasons = reasons.where(~((reasons == "N") & ~finite), "missing")
    ok = (levels == "ok") & finite

    def result(**fields: Any) -> ExtractionResult:
        base: dict[str, Any] = {
            "method": "vth_linear_extrapolation", "quantity": "vth", "value": None, "unit": x_unit,
            "method_record": record, "window": None, "points_used": 0,
            "points_excluded": _excluded(reasons[reasons != "N"]), "fit": {}, "warnings": [],
        }  # fmt: skip
        base.update(fields)
        return ExtractionResult(**base)

    xs = rows.loc[ok, x].to_numpy(dtype=float)
    ys = rows.loc[ok, y].to_numpy(dtype=float)
    problems: list[str] = []
    untrusted = reasons[levels == "untrusted"]
    if len(untrusted):
        letters = ", ".join(f"{k}: {v}" for k, v in _excluded(untrusted).items())
        problems.append(f"{len(untrusted)} untrusted point(s) in segment {segment} ({letters})")
    snr = signal_to_noise(ys, noise_sigma(ys))
    if snr is not None and snr < MIN_SNR:
        problems.append(f"{y} is noise-dominated (range {snr:.1f}x the noise estimate, < {MIN_SNR:g})")
    warnings: list[str] = []
    if problems and not force:
        return result(
            outcome="refused",
            error="Refused: " + "; ".join(problems) + ". Re-check the data (quality report); force=True extracts "
            "from the trusted points anyway and flags the result.",
        )
    if problems:
        warnings.append("Forced on untrusted data: " + "; ".join(problems) + ".")
    forced = bool(problems)

    if xs.size >= 2 and not _strictly_monotonic(xs):
        raise InvalidInputError(f"{x} is not strictly monotonic within segment {segment}; is it a double sweep "
                                "without a segment column?")
    if window == "max_gm":
        if xs.size < max(fit_points, 3):
            return result(outcome="failed", forced_on_untrusted=forced, warnings=warnings,
                          error=f"Only {xs.size} trusted point(s); the max_gm window needs {max(fit_points, 3)}.")
        slopes = local_derivative(xs, ys, smooth)
        peak = peak_index(np.abs(slopes))
        first = min(max(peak - fit_points // 2, 0), xs.size - fit_points)
        chosen = np.arange(first, first + fit_points)
        extra = {"gm_max": float(slopes[peak]), "x_at_gm_max": float(xs[peak])}
        if peak in (0, xs.size - 1):
            warnings.append("The |gm| maximum is at the end of the sweep; the sweep may not reach the gm peak.")
    else:
        lo, hi = window
        chosen = np.flatnonzero((xs >= lo) & (xs <= hi))
        extra = {}
        if chosen.size < 2:
            return result(outcome="failed", forced_on_untrusted=forced, warnings=warnings,
                          error=f"Only {chosen.size} trusted point(s) in the window [{lo}, {hi}] {x_unit}.")

    fx, fy = xs[chosen], ys[chosen]
    slope, intercept = (float(c) for c in np.polyfit(fx, fy, 1))
    if abs(slope) * float(np.ptp(fx)) <= _FLAT * float(np.abs(fy).max()):
        return result(outcome="failed", forced_on_untrusted=forced, warnings=warnings,
                      error="The fitted line is flat; no intercept with the voltage axis.")
    residual = fy - (intercept + slope * fx)
    spread = float(np.sum((fy - fy.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / spread if spread > 0 else 1.0
    x_intercept = -intercept / slope
    value = x_intercept - bias / 2.0 if bias is not None else x_intercept

    used_index = rows.index[ok.to_numpy()][chosen]
    reasons = reasons.copy()
    reasons[ok & ~rows.index.isin(used_index)] = "outside_window"
    low, high = float(fx.min()), float(fx.max())
    in_range = rows[x].between(low, high).to_numpy()
    limited = int(((levels == "limited").to_numpy() & in_range).sum())
    if in_range.sum() and limited / in_range.sum() > max_limited:
        warnings.append(f"{limited} of {int(in_range.sum())} points inside the window are limited (C/T), above "
                        f"max_limited_fraction_in_fit {max_limited:g}.")
    if r2 < MIN_R2:
        warnings.append(f"Poor linear fit in the window (r2 = {r2:.4f} < {MIN_R2}).")
    all_x = rows[x].to_numpy(dtype=float)
    if not np.nanmin(all_x) <= value <= np.nanmax(all_x):
        warnings.append(f"Extracted Vth {value:.4g} {x_unit} lies outside the swept range of {x}.")
    fit = {"slope": slope, "intercept": intercept, "r2": r2, "x_intercept": x_intercept, **extra}
    if bias is not None:
        fit["vd"] = bias
    return result(
        value=float(value),
        window=QuantityRange(low=low, high=high, unit=x_unit),
        points_used=int(chosen.size),
        points_excluded=_excluded(reasons[reasons != "N"]),
        fit=fit,
        warnings=warnings,
        forced_on_untrusted=forced,
    )


# -- M2 transfer-curve methods ---------------------------------------------------------------------------------------

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(gt=0, lt=1)]
Decades = Annotated[float, Field(gt=0, le=12)]
MinR2 = Annotated[float, Field(ge=0, le=1)]
WindowPoints = Annotated[int, Field(ge=3, le=101)]

DEFAULT_I_CRIT_A = 1e-7
"""Default critical current of the constant-current method (100 nA, per square when ``w_over_l`` is given; a common
convention, not a device value: set ``i_crit_a``/``w_over_l`` per device)."""


def _transfer_rows(d: RunData, x: str, y: str, segment: Segment, policy: TrustPolicy, method: str) -> Rows:
    require_iv(d, x, y, method)
    r = analysed_rows(d, x, y, policy, segment=segment)
    if r.size >= 2 and not strictly_monotonic(r.xs):
        raise InvalidInputError(f"{x} is not strictly monotonic within segment {segment}; is it a double sweep "
                                "without a segment column?")
    return r


def _base_params(policy: TrustPolicy, **options: Any) -> dict[str, Any]:
    return {**options, "trust_policy": policy_params(policy)}


@validate_call(config=_CALL_CONFIG)
def vth_constant_current(
    d: RunData,
    *,
    i_crit_a: PositiveFloat = DEFAULT_I_CRIT_A,
    w_over_l: PositiveFloat | None = None,
    segment: Segment = "fwd",
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Threshold voltage by the constant-current criterion (module docstring). One ``ExtractionResult``
    (``quantity="vth"``); refusals and failures come back with ``value=None``."""
    policy = trust_policy(criteria)
    r = _transfer_rows(d, x, y, segment, policy, "vth_constant_current")
    i_crit = i_crit_a * (w_over_l if w_over_l is not None else 1.0)
    out = Results("vth_constant_current", _base_params(policy, i_crit_a=i_crit_a, w_over_l=w_over_l, i_crit=i_crit,
                                                       segment=segment, force=force, x=x, y=y))
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return out.refused("vth", "V", problems, excluded=r.excluded())
    out.flag(problems)
    found = _cc_crossing(r, i_crit, y, f"segment {segment}")
    if isinstance(found, str):
        return out.failed("vth", "V", found, excluded=r.excluded())
    value, (i0, i1), fit, warnings = found
    r.use([i0, i1])
    return out.ok("vth", value, "V", excluded=r.excluded(), points_used=2,
                  window=window_of(np.array([r.xs[i0], r.xs[i1]]), "V"), fit=fit, warnings=warnings)


def _cc_crossing(r: Rows, i_crit: float, y: str, where: str
                 ) -> tuple[float, tuple[int, int], dict[str, float], list[str]] | str:
    """The constant-current crossing of the usable rows (module docstring): ``(Vth, (i0, i1) positions in xs,
    fit, warnings)``, or why it failed."""
    xs, ys = r.xs, r.ys
    if xs.size < 2:
        return f"Only {xs.size} trusted point(s) in {where}."
    order = np.argsort(xs) if increasing_with_x(xs, ys) else np.argsort(xs)[::-1]
    a = np.abs(ys[order])
    below = a < i_crit
    crossings = np.flatnonzero(below[:-1] & ~below[1:])
    if not crossings.size:
        return (f"|{y}| never rises through I_crit = {i_crit:.3g} A within the trusted points of {where} "
                f"(|{y}| spans {a.min():.3g}..{a.max():.3g} A).")
    k = int(crossings[0])
    i0, i1 = int(order[k]), int(order[k + 1])
    lo_i, hi_i = max(a[k], 1e-300), a[k + 1]
    frac = (np.log10(i_crit) - np.log10(lo_i)) / (np.log10(hi_i) - np.log10(lo_i)) if hi_i > lo_i else 1.0
    value = float(xs[i0] + frac * (xs[i1] - xs[i0]))
    warnings = []
    if crossings.size > 1:
        warnings.append(f"|{y}| crosses I_crit {crossings.size} times (noise near I_crit?); the first crossing in "
                        "the direction of increasing current is used.")
    return value, (i0, i1), {"i_crit": i_crit, "i_below": float(a[k]), "i_above": float(a[k + 1])}, warnings


@validate_call(config=_CALL_CONFIG)
def vth_max_gm(
    d: RunData,
    *,
    subtract_half_vd: bool = True,
    segment: Segment = "fwd",
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    vd: float | None = None,
    vd_param: str = DRAIN_BIAS_PARAM,
    smooth: Smooth = 5,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Threshold voltage at the maximum of the transconductance change dgm/dVg (module docstring). One
    ``ExtractionResult`` (``quantity="vth"``)."""
    policy = trust_policy(criteria)
    r = _transfer_rows(d, x, y, segment, policy, "vth_max_gm")
    bias, bias_source = _drain_bias(d, vd, vd_param) if subtract_half_vd else (None, None)
    out = Results("vth_max_gm", _base_params(
        policy, subtract_half_vd=subtract_half_vd, segment=segment, force=force, x=x, y=y, smooth=smooth,
        derivative=derivative_method(smooth).model_dump(exclude_none=True), vd=bias, vd_source=bias_source))
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return out.refused("vth", "V", problems, excluded=r.excluded())
    out.flag(problems)
    xs, ys = r.xs, r.ys
    need = max(smooth, 3) + 2
    if xs.size < need:
        return out.failed("vth", "V", f"Only {xs.size} trusted point(s); vth_max_gm needs {need}.",
                          excluded=r.excluded())
    slopes = local_derivative(xs, ys, smooth)
    change = local_derivative(xs, slopes, smooth)
    sign = 1.0 if increasing_with_x(xs, ys) else -1.0
    score = sign * change
    k = peak_index(score)
    peak = float(xs[k])
    warnings = []
    if 0 < k < xs.size - 1:
        coeffs = np.polyfit(xs[k - 1:k + 2], score[k - 1:k + 2], 2)
        if coeffs[0] < 0:
            vertex = float(-coeffs[1] / (2 * coeffs[0]))
            if min(xs[k - 1], xs[k + 1]) <= vertex <= max(xs[k - 1], xs[k + 1]):
                peak = vertex
    else:
        warnings.append("The dgm/dVg maximum is at the end of the sweep; the sweep may not cover the turn-on.")
    value = peak - bias / 2.0 if bias is not None else peak
    half = max(smooth, 3) // 2
    used = np.arange(max(0, k - half), min(xs.size, k + half + 1))
    r.use(used)
    g_peak = peak_index(np.abs(slopes))
    fit = {"x_peak": peak, "dgm_max": float(change[k]), "gm_at_peak": float(slopes[k]),
           "gm_max": float(slopes[g_peak]), "x_at_gm_max": float(xs[g_peak])}
    if bias is not None:
        fit["vd"] = bias
    return out.ok("vth", value, "V", excluded=r.excluded(), points_used=int(used.size),
                  window=window_of(xs[used], "V"), fit=fit, warnings=warnings)


@validate_call(config=_CALL_CONFIG)
def subthreshold_swing(
    d: RunData,
    *,
    decades: Decades | None = None,
    fit_points: WindowPoints = 5,
    min_r2: MinR2 = 0.99,
    segment: Segment = "fwd",
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Minimum subthreshold swing in mV/dec (module docstring). One ``ExtractionResult`` (``quantity="ss"``)."""
    policy = trust_policy(criteria)
    r = _transfer_rows(d, x, y, segment, policy, "subthreshold_swing")
    out = Results("subthreshold_swing", _base_params(policy, decades=decades, fit_points=fit_points, min_r2=min_r2,
                                                     segment=segment, force=force, x=x, y=y))
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return out.refused("ss", "mV/dec", problems, excluded=r.excluded())
    out.flag(problems)
    xs, ys = r.xs, r.ys
    order = np.argsort(xs)
    sx, logs = xs[order], np.log10(np.maximum(np.abs(ys[order]), 1e-300))
    nonzero = np.abs(ys[order]) > 0
    sign = 1.0 if increasing_with_x(xs, ys) else -1.0
    best: tuple[float, int, int, float, float] | None = None
    for start in range(sx.size):
        if decades is None:
            stop = start + fit_points
            if stop > sx.size:
                break
        else:
            span = np.abs(logs[start:] - logs[start])
            reach = np.flatnonzero(span >= decades)
            if not reach.size:
                continue
            stop = start + int(reach[0]) + 1
            if stop - start < 3:
                continue
        wx, wl = sx[start:stop], logs[start:stop]
        if not nonzero[start:stop].all():
            continue
        steps = np.diff(wl) * sign
        if not np.all(steps > 0):
            continue
        slope, _, r2 = line_fit(wx, wl)
        if r2 < min_r2 or slope * sign <= 0:
            continue
        ss = 1000.0 / abs(slope)
        if best is None or ss < best[0]:
            best = (ss, start, stop, slope, r2)
    if best is None:
        rule = f"{decades:g} decade(s)" if decades is not None else f"{fit_points} points"
        return out.failed("ss", "mV/dec", f"No subthreshold window: no run of {rule} with |{y}| rising strictly "
                          f"monotonically and r2 >= {min_r2:g} (log10|I| vs V).", excluded=r.excluded())
    ss, start, stop, slope, r2 = best
    used = order[start:stop]
    r.use(used)
    window = window_of(sx[start:stop], "V")
    i_low, i_high = sorted((float(abs(ys[used[0]])), float(abs(ys[used[-1]]))))
    return out.ok("ss", ss, "mV/dec", excluded=r.excluded(), points_used=int(stop - start), window=window,
                  fit={"slope_dec_per_v": slope, "r2": r2, "i_low": i_low, "i_high": i_high,
                       "decades": float(np.log10(i_high / i_low)) if i_low > 0 else 0.0})


@validate_call(config=_CALL_CONFIG)
def gm_max(
    d: RunData,
    *,
    segment: Segment = "fwd",
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    smooth: Smooth = 5,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Maximum transconductance (module docstring). One ``ExtractionResult`` (``quantity="gm_max"``, unit S)."""
    policy = trust_policy(criteria)
    r = _transfer_rows(d, x, y, segment, policy, "gm_max")
    out = Results("gm_max", _base_params(policy, segment=segment, force=force, x=x, y=y, smooth=smooth,
                                         derivative=derivative_method(smooth).model_dump(exclude_none=True)))
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return out.refused("gm_max", "S", problems, excluded=r.excluded())
    out.flag(problems)
    xs, ys = r.xs, r.ys
    if xs.size < 3:
        return out.failed("gm_max", "S", f"Only {xs.size} trusted point(s); gm_max needs 3.", excluded=r.excluded())
    slopes = local_derivative(xs, ys, smooth)
    k = peak_index(np.abs(slopes))
    half = max(smooth, 3) // 2
    used = np.arange(max(0, k - half), min(xs.size, k + half + 1))
    r.use(used)
    warnings = []
    if k in (0, xs.size - 1):
        warnings.append("The |gm| maximum is at the end of the sweep; the sweep may not reach the gm peak.")
    return out.ok("gm_max", float(slopes[k]), "S", excluded=r.excluded(), points_used=int(used.size),
                  window=window_of(xs[used], "V"), fit={"x_at_gm_max": float(xs[k]), "y_at_gm_max": float(ys[k])},
                  warnings=warnings)


@validate_call(config=_CALL_CONFIG)
def ion_ioff(
    d: RunData,
    *,
    v_on: float | None = None,
    v_off: float | None = None,
    segment: Segment = "fwd",
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """On current, off current and on/off ratio (module docstring): three ``ExtractionResult``s ``ion``, ``ioff``
    (A) and ``on_off_ratio`` (1); one non-ok ``ion`` result on refusal or failure."""
    policy = trust_policy(criteria)
    r = _transfer_rows(d, x, y, segment, policy, "ion_ioff")
    xs, ys = r.xs, r.ys
    if xs.size >= 2 and (v_on is None or v_off is None):
        ends = (float(np.min(xs)), float(np.max(xs)))
        high_end = ends[1] if increasing_with_x(xs, ys) else ends[0]
        low_end = ends[0] if high_end == ends[1] else ends[1]
        v_on = high_end if v_on is None else v_on
        v_off = low_end if v_off is None else v_off
    out = Results("ion_ioff", _base_params(policy, v_on=v_on, v_off=v_off, segment=segment, force=force, x=x, y=y))
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return [out.refused("ion", "A", problems, excluded=r.excluded())]
    out.flag(problems)
    if xs.size < 2 or v_on is None or v_off is None:
        return [out.failed("ion", "A", f"Only {xs.size} trusted point(s) in segment {segment}.",
                           excluded=r.excluded())]
    on = interpolate(xs, ys, v_on)
    off = interpolate(xs, ys, v_off)
    if on is None or off is None:
        missing = v_on if on is None else v_off
        return [out.failed("ion", "A", f"{x} = {missing:g} V lies outside the trusted sweep range "
                           f"{xs.min():g}..{xs.max():g} V.", excluded=r.excluded())]
    i_on, i_off = abs(on[0]), abs(off[0])
    near = sorted({on[1], off[1]})
    order = np.argsort(xs, kind="stable")
    r.use([int(order[p]) for p in near])
    excluded = r.excluded()
    floor_on, floor_off = floor_limit(xs, ys, on[1]), floor_limit(xs, ys, off[1])
    on_bound: Bound = "exact"
    off_bound: Bound = "exact"
    warnings_off: list[str] = []
    if floor_off is not None and i_off <= floor_off:
        i_off, off_bound = floor_off, "upper"
        warnings_off.append(f"Ioff at {v_off:g} V is at the noise floor; reported as the upper bound "
                            f"{floor_off:.3g} A.")
    warnings_on = []
    if floor_on is not None and i_on <= floor_on:
        warnings_on.append(f"Ion at {v_on:g} V is at the noise floor (< {floor_on:.3g} A): no on state.")
        on_bound = "upper"
        i_on = floor_on
    results = [
        out.ok("ion", i_on, "A", excluded=excluded, points_used=1, fit={"v": v_on}, warnings=warnings_on,
               bound=on_bound),
        out.ok("ioff", i_off, "A", excluded=excluded, points_used=1, fit={"v": v_off}, warnings=warnings_off,
               bound=off_bound),
    ]
    ratio_bound: Bound = {("exact", "exact"): "exact", ("exact", "upper"): "lower",
                          ("upper", "exact"): "upper"}.get((on_bound, off_bound), "exact")
    if on_bound == off_bound == "upper":
        results.append(out.failed("on_off_ratio", "1", "Ion and Ioff are both at the noise floor.", excluded=excluded))
    elif i_off <= 0:
        results.append(out.failed("on_off_ratio", "1", "Ioff is exactly zero; no ratio.", excluded=excluded))
    else:
        results.append(out.ok("on_off_ratio", i_on / i_off, "1", excluded=excluded, points_used=2,
                              window=window_of(np.array([v_on, v_off]), "V"), bound=ratio_bound))
    return results


# -- Output family (Id-Vd) -------------------------------------------------------------------------------------------


OUTPUT_QUANTITIES: tuple[tuple[str, Unit], ...] = (("ron", "Ohm"), ("gds", "S"), ("vd_sat", "V"))


@validate_call(config=_CALL_CONFIG)
def output_metrics(
    d: RunData,
    *,
    x: str = "drain_V",
    y: str = "drain_I",
    step: str | None = None,
    curve: float | None = None,
    smooth: Smooth = 5,
    sat_window: Fraction = 0.2,
    sat_ratio: Fraction = 0.1,
    segment: Segment = "fwd",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Ron, gds and Vd_sat of an output family (module docstring): three ``ExtractionResult``s (``ron`` Ohm, ``gds``
    S, ``vd_sat`` V) of the reported curve (``curve`` = its step level; default the strongest drive, the largest
    |step|), each with the same quantity of every curve in ``fit`` keyed ``<step>=<level>`` (e.g. ``gate_V=1.5``)."""
    policy = trust_policy(criteria)
    require_iv(d, x, y, "output_metrics")
    rows = d.rows(segment)
    if step is None:
        others = [c for c in varying_sources(rows, d) if c != x]
        if len(others) > 1:
            raise InvalidInputError(f"output_metrics: several step columns {others}; pass step=<column>.")
        step = others[0] if others else None
    elif step not in d.source_columns:
        raise InvalidInputError(f"output_metrics: step {step!r} is not a source column of run {d.run_id} "
                                f"({d.source_columns}).")
    curves = list(rows.groupby(step, sort=False)) if step is not None else [(None, rows)]
    levels = [None if level is None else float(level) for level, _ in curves]
    if curve is None:
        chosen = max(range(len(levels)), key=lambda i: abs(levels[i] or 0.0))
    else:
        matches = [i for i, level in enumerate(levels) if level is not None and abs(level - curve) <= 1e-6]
        if not matches:
            raise InvalidInputError(f"output_metrics: no curve at {step} = {curve:g} V; levels: {levels}.")
        chosen = matches[0]
    params = _base_params(policy, x=x, y=y, step=step, curve=levels[chosen], smooth=smooth, sat_window=sat_window,
                          sat_ratio=sat_ratio, segment=segment, force=force,
                          derivative=derivative_method(smooth).model_dump(exclude_none=True))
    per_curve = [_output_curve(d, rows_, x, y, step, level, smooth, sat_window, sat_ratio, force, policy,
                               Results("output_metrics", params)) for (_, rows_), level in zip(curves, levels,
                                                                                                strict=True)]
    results = []
    for quantity, _ in OUTPUT_QUANTITIES:
        main = per_curve[chosen][quantity]
        family = {f"{step}={level:g}": res.value for level, metrics in zip(levels, per_curve, strict=True)
                  if level is not None and (res := metrics[quantity]).value is not None}
        notes = [f"{step} = {level:g} V: {res.error}" for i, (level, metrics) in enumerate(zip(levels, per_curve,
                 strict=True)) if i != chosen and level is not None and (res := metrics[quantity]).error]
        results.append(main.model_copy(update={"fit": {**main.fit, **family}, "warnings": [*main.warnings, *notes]}))
    return results


def _output_curve(d: RunData, curve: pd.DataFrame, x: str, y: str, step: str | None, level: float | None,
                  smooth: int, sat_window: float, sat_ratio: float, force: bool, policy: TrustPolicy, out: Results
                  ) -> dict[str, ExtractionResult]:
    """Ron, gds and Vd_sat of one curve (module docstring), by quantity; non-ok results say why."""
    tag = {"step_v": level} if level is not None else {}
    where = f"curve {step} = {level:g} V" if level is not None else "the curve"
    r = analysed_rows(d, x, y, policy, rows=curve)
    problems = r.problems(where)
    if problems and not force:
        return {q: out.refused(q, unit, problems, excluded=r.excluded(), fit=tag) for q, unit in OUTPUT_QUANTITIES}
    out.flag(problems)
    xs, ys = r.xs, r.ys
    need = max(smooth, 3) + 2
    if xs.size < need:
        error = f"Only {xs.size} trusted point(s) in {where}; output_metrics needs {need}."
        return {q: out.failed(q, unit, error, excluded=r.excluded(), fit=tag) for q, unit in OUTPUT_QUANTITIES}
    if not strictly_monotonic(xs):
        raise InvalidInputError(f"{x} is not strictly monotonic within {where}.")
    gd = local_derivative(xs, ys, smooth)
    distance = np.abs(xs)
    k0 = int(np.argmin(distance))
    g0 = float(gd[k0])
    first = max(0, min(k0 - max(smooth, 3) // 2, xs.size - smooth))
    ron_pts = np.arange(first, min(xs.size, first + smooth))
    span_lo, span_hi = float(distance.min()), float(distance.max())
    sat_start = span_hi - sat_window * (span_hi - span_lo)
    sat_pts = np.flatnonzero(distance >= sat_start)
    used = set(ron_pts.tolist())
    found: dict[str, tuple[float, np.ndarray, dict[str, float], list[str]] | str] = {}
    if g0 <= 0:
        found["ron"] = f"Non-positive output conductance {g0:.3g} S at the lowest |Vd| in {where}: no on state."
    else:
        found["ron"] = (1.0 / g0, ron_pts, {"gd0": g0, "x_at_gd0": float(xs[k0])}, [])
    if sat_pts.size < 3:
        found["gds"] = f"Only {sat_pts.size} trusted point(s) in the saturation window of {where}."
    else:
        used |= set(sat_pts.tolist())
        slope, _, r2 = line_fit(xs[sat_pts], ys[sat_pts])
        warnings = ["Negative output conductance in saturation (self-heating?)."] if slope < 0 else []
        found["gds"] = (slope, sat_pts, {"r2": r2}, warnings)
    found["vd_sat"] = f"gd never falls to {sat_ratio:g} x gd(Vd_min) in {where}: not saturated within the sweep."
    if g0 > 0:
        walk = range(k0, xs.size) if distance[-1] >= distance[0] else range(k0, -1, -1)
        for prev, cur in itertools.pairwise(walk):
            if gd[cur] <= sat_ratio * g0:
                frac = (gd[prev] - sat_ratio * g0) / (gd[prev] - gd[cur]) if gd[prev] != gd[cur] else 1.0
                value = float(xs[prev] + frac * (xs[cur] - xs[prev]))
                used |= {prev, cur}
                warnings = []
                if abs(value) > sat_start:
                    warnings.append(f"Saturation onset |Vd| {abs(value):.3g} V lies inside the gds window (from "
                                    f"{sat_start:.3g} V); gds may include the knee.")
                found["vd_sat"] = (value, np.array([prev, cur]), {"sat_ratio": sat_ratio, "gd0": g0}, warnings)
                break
    r.use(sorted(used))
    excluded = r.excluded()
    results: dict[str, ExtractionResult] = {}
    for quantity, unit in OUTPUT_QUANTITIES:
        item = found[quantity]
        if isinstance(item, str):
            results[quantity] = out.failed(quantity, unit, item, excluded=excluded, fit=tag)
        else:
            value, points, fit, warnings = item
            results[quantity] = out.ok(quantity, value, unit, excluded=excluded, points_used=int(points.size),
                                       window=window_of(xs[points], "V"), fit={**tag, **fit}, warnings=warnings)
    return results
