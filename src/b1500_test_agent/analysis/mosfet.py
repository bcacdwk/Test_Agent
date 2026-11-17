"""MOSFET extraction (blueprint 2.8, M1): transconductance ``gm`` and threshold voltage by linear extrapolation.

Definitions (must match knowledge file ``06-analysis-extraction.md`` of skill ``b1500-test``):

- **gm** = dId/dVg, the slope of a local quadratic least-squares fit over ``smooth`` neighbouring trusted points
  (Savitzky-Golay equivalent on a uniform grid, exact on a non-uniform one; ``smooth=1`` = central differences).
- **Vth, linear extrapolation** (linear region, small Vd): fit a straight line Id = a + b Vg through the window, take
  its Vg-axis intercept Vg0 = -a/b and report Vth = Vg0 - Vd/2 (``subtract_half_vd``), because the linear-region
  current is beta (Vg - Vth - Vd/2) Vd. Default window: the ``fit_points`` trusted points centred on the maximum of
  |gm| (the tangent at maximum gm); or an explicit ``(lo, hi)`` gate-voltage window.
- **Drain bias Vd** for the correction: the ``vd`` argument if given; else the run plan's resolved parameter named
  ``vd_param`` (default ``vd``, the parameter the drain role's bias setting references in ``mosfet.idvg``), which
  must be a scalar in volts. Missing → ``InvalidInputError`` (pass ``vd=`` or ``subtract_half_vd=False``).

Trust (``criteria``, default ``QualityCriteria()``): a row's level is the worst of its measured values. Limited
(``C``/``T``) and untrusted rows never enter a derivative or a fit; ``points_excluded`` counts them by deciding status
letter, rows with missing values as ``missing`` and trusted rows outside the window as ``outside_window``
(``points_used`` + excluded = rows of the analysed segment). The extraction is **refused** (``outcome="refused"``,
``value=None``) when the analysed segment contains any untrusted row or its trusted response is noise-dominated
(range < ``MIN_SNR`` x noise), unless ``force=True``: then the value is computed from the trusted rows only and
flagged (``forced_on_untrusted=True`` + warning). More limited rows inside the window than
``criteria.max_limited_fraction_in_fit`` → warning.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import AfterValidator, ConfigDict, Field, validate_call

from b1500_test_agent.analysis.dataset import RunData, Segment, row_reasons, trust_levels
from b1500_test_agent.analysis.quality import MIN_SNR, noise_sigma, signal_to_noise
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import (
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
        peak = int(np.argmax(np.abs(slopes)))
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
