"""Noise analysis of sampled records (blueprint v2 2.10 ``noise.py``; WP10.5): ``it_statistics``, ``psd_welch``,
``rtn_levels`` and the plot ``plot_psd``; library helpers ``welch_psd``, ``log_bins``, ``fit_psd`` and ``two_level``
for agent scripts.

Definitions (the source of knowledge file ``10-wgfmu-fast-iv-noise.md``; a change to either changes both):

**Record.** One measured column ``y`` (default: the run's only measured current, else its first measured column; any
measured value column may be named) against ``t_s`` (s, required), the trusted rows inside ``[t_min, t_max]`` and,
with ``event``, of that measurement event only (default: the event with the most rows, named in a warning when a run
has several). The sampling interval ``dt`` is the median spacing of ``t_s``; the methods use the longest stretch whose
spacings all lie within 10 % of ``dt`` (a warning names how many points were left out; they count as
``non_uniform``). Untrusted points (WGFMU ``V``: over-range) refuse the call unless ``force`` (then only the trusted
points are used and a removed point splits the record); limited points (``C``/``T``) are excluded and counted. Noise
is the signal here, so no signal-to-noise refusal applies. A record needs at least 64 points.

**it_statistics.** ``mean`` (median, min, max, 1st/99th percentiles in ``fit``), ``std`` (sample standard deviation;
``fit``: ``white_estimate`` = std of the first differences / sqrt 2, which is the white part when the record is
oversampled, ``skewness``, ``excess_kurtosis`` and Sarle's ``bimodality`` coefficient (skew^2 + 1) / (excess
kurtosis + 3); above 5/9 the distribution is likely bimodal: a two-level RTN, warned), ``noise_rel`` = std / |mean|,
``drift_rel`` = slope of the least-squares line through ``y(t)`` x duration / |mean| (``fit``: ``slope`` per s,
``r2``) and ``sample_interval`` (``dt``; ``fit``: points, duration, ``jitter_rel`` = std of the spacings / dt).

**psd_welch.** One-sided power spectral density by Welch's method: ``segments`` (default 8) Hann-windowed segments of
equal length ``2 n / (segments + 1)`` overlapping by half, each with its mean removed; ``S(f) = 2 dt |X(f)|^2 /
sum(w^2)`` averaged over the segments (unit^2/Hz; white noise of variance s^2 gives ``2 s^2 dt``); ``S/mean^2`` (1/Hz)
is the normalized PSD. The frequency resolution is ``f_res = 1 / (segment length x dt)``. The fit window is ``[f_min,
f_max]`` (defaults ``3 f_res`` and ``1 / (10 dt)``: above it the averaging window's sinc^2 response and aliasing bend
the spectrum); there the PSD is averaged in log-spaced bins (10 per decade; bin value = mean of its FFT bins, bin
frequency = their geometric mean, ``ln`` corrected by ``+1/(2 K m)`` for the bias of the log of a mean of ``m`` bins
over ``K`` segments) and ``ln S`` is fitted by weighted least squares (weight = FFT bins in the log bin: the inverse
variance of its ``ln``) with the model ``S(f) = A / f^gamma + W`` (``power``) or ``A / f^gamma + B / (1 + (f/fc)^2) +
W`` (``power_lorentzian``: one random-telegraph Lorentzian of corner ``fc = (1/tau_c + 1/tau_e) / (2 pi)``); a coarse
grid over ``gamma`` (0.2..2.5) and ``fc`` with non-negative linear amplitudes (relative residuals), then
Levenberg-Marquardt in log space (numerics in ``spectrum.py``). ``model="auto"`` (default) takes ``power_lorentzian``
when its Bayesian information criterion is lower by more than 10, ``fc`` lies within the window (x/÷ 3) and the
Lorentzian at ``fc`` is at least twice the 1/f part (a visible bump). Results: ``gamma`` (1; ``fit``: ``gamma_se``,
``a`` = the 1/f part at 1 Hz, ``white``, ``rms_log`` residual, bins, segments; classification = the model),
``flicker_norm_1hz`` = A / mean^2 (1/Hz: the normalized 1/f part at 1 Hz, Hooge-type), ``psd_at_f_ref`` (the measured
log-binned PSD, log-log interpolated, at ``f_ref``; default the lowest power of ten inside the window, else its
geometric centre) and ``norm_psd_at_f_ref`` (1/Hz); with a Lorentzian ``corner_frequency`` (Hz; ``fit``: ``plateau``,
``plateau_norm``, ``tau_rtn_s`` = 1 / (2 pi fc)); with ``gm_s`` (the transconductance at the bias, S) on a current
record ``input_noise_at_f_ref`` = S_I / gm^2 (V^2/Hz, the input-referred gate-voltage noise). A ``gamma`` at a grid end
is flagged (poorly constrained); ``rms_log`` above 0.3 is warned (not a power law in the window).

**rtn_levels.** Two-level random telegraph noise: (1) the two levels and their spreads from a two-Gaussian mixture
(EM on a 512-bin histogram, started at the 10th and 90th percentiles) of the record and, unless ``baseline_s`` is 0,
of the record minus its moving mean over +-n/200 points (at least 128); the better separated mixture starts the
classification (a slow drift or strong 1/f wander hides the steps in the raw histogram); (2) each point is
classified with hysteresis (a Schmitt trigger: the state changes only when a point passes ``lo + (1 + h)/2 dI``
upwards or ``lo + (1 - h)/2 dI`` downwards, ``h`` = ``hysteresis``, default 0.5, i.e. thresholds at 25 % and 75 % of
the step); (3) unless ``baseline_s`` is 0, the levels are then followed in time: each level's moving mean over
``baseline_s`` (default 50 mean dwells, at least 64 points) of the points classified in it, interpolated where a
window holds fewer than 5, and the points are classified again against these local levels (twice; this removes
1/f wander and drift slower than the window); (4) ``smooth`` > 1 first takes a moving average over that many points.
The trap is empty in the state with the larger |y| unless ``occupied="high"`` (a captured carrier lowers the channel
current: number fluctuation). Dwell times run between transition times (midway between the last point of a state and
the first of the next); the first and the last dwell are censored and dropped. Results: ``tau_c`` (s) = mean dwell in
the trap-empty state (time to capture), ``tau_e`` (s) = mean dwell in the occupied state (time to emission; both
maximum-likelihood exponential means, ``fit``: dwells ``n``, ``se`` = tau / sqrt(n), ``tau_fit_s`` from a log-linear
fit of the dwell survival function above 2 dt, ``cv`` = std/mean of the dwells, 1 for a single Markov trap),
``delta_i`` (``delta_v`` for a voltage) = mean difference of the local levels and ``delta_i_rel`` = delta /
|empty-trap level|; ``fit`` of every result holds ``transitions``, ``occupancy`` (time fraction occupied),
``separation`` (delta / per-point noise sigma, robust), ``dt_s``, ``duration_s``, ``baseline_s``. Failed when no
mixture resolves two levels (less than 2 sigma apart or a level below 1 % of the points), when the tracked levels are
less than 3 sigma apart or a state has fewer than 3 complete dwells. Warned: fewer than 200 transitions (statistical
error 1/sqrt(n) per tau; the blueprint 4.2 target needs >= 200), a tau below 10 dt (dwells shorter than about 2
points are missed), separation below 5, a ``cv`` outside 0.6..1.4 (not one Markov trap: several traps or levels),
``tau_fit_s`` more than 25 % from ``tau``.

**plot_psd.** One figure ``psd``: S(f) and S/mean^2 against f on log-log axes: the Welch estimate (thin line), the
log-binned points used by the fit (markers), the fitted model and its parts (1/f, Lorentzian, white; dashed) and the
fit window (shaded). Plots never refuse: untrusted points are left out and noted; without a usable record the figure
says why. ``analyze_run`` stores it as ``plots/psd-<n>.png``; agent scripts call ``plot_psd`` with ``out_dir`` (default
``work/<run_id>/plots/``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, excluded_counts, policy_params, trust_policy
from b1500_test_agent.analysis.dataset import (
    EVENT,
    STEP,
    T_S,
    RunData,
    row_reasons,
    status_column,
    trust_levels,
    work_dir_for,
)
from b1500_test_agent.analysis.plots import PlotSet, RenderedPlot, figure_png, new_figure
from b1500_test_agent.analysis.spectrum import (
    GAMMA_RANGE,
    PsdFit,
    PsdModel,
    fit_psd,
    log_bins,
    welch_psd,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QuantityRange, TrustPolicy, Unit

Occupied = Literal["low", "high"]
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)

MIN_POINTS = 64
"""Fewest points of a record the noise methods accept."""
UNIFORM_TOL = 0.1
"""A spacing within this fraction of the median spacing counts as uniform sampling."""
F_MIN_RES = 3.0
"""Default lowest fitted frequency in units of the frequency resolution (Hann leakage at the first bins)."""
F_MAX_FRACTION = 0.1
"""Default highest fitted frequency as a fraction of the sampling rate."""
BIMODAL_BC = 5.0 / 9.0
"""Sarle's bimodality coefficient of a uniform distribution; larger values suggest two modes."""
MIN_TRANSITIONS = 200
"""Transitions below which ``rtn_levels`` warns (blueprint v2 4.2: tau_c, tau_e +-20 % with >= 200 transitions)."""
MIN_SEPARATION = 3.0
WARN_SEPARATION = 5.0
MIN_DWELLS = 3
BASELINE_DWELLS = 50
PREFILTER_FRACTION = 200
PREFILTER_MIN = 128
"""The mixture is also fitted to the record minus its moving mean over +-n/200 points (at least 128); the better
separated of the two starts the classification (a slow drift or strong 1/f wander hides the steps in the raw
histogram, or splits it into two false levels)."""
_TINY = 1e-300


# -- the record ------------------------------------------------------------------------------------------------------


@dataclass
class NoiseRecord:
    """The analysed record (module docstring): times, values, sampling interval and the bookkeeping of what was
    left out."""

    y: str
    unit: Unit
    t: np.ndarray
    x: np.ndarray
    dt: float
    excluded: dict[str, int]
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    event: str | None = None

    @property
    def n(self) -> int:
        return int(self.x.size)

    @property
    def duration_s(self) -> float:
        return float(self.n * self.dt)


def _default_y(d: RunData, y: str | None, method: str) -> str:
    measured = d.measured_columns
    if y is not None:
        if y not in measured:
            raise InvalidInputError(f"{method}: {y!r} is not a measured column of run {d.run_id}; measured: "
                                    f"{measured}.")
        return y
    if not measured:
        raise InvalidInputError(f"{method}: run {d.run_id} has no measured column.")
    currents = [c for c in measured if c.endswith("_I")]
    if len(currents) > 1:
        raise InvalidInputError(f"{method}: run {d.run_id} measures several currents {currents}; pass y=<column>.")
    return currents[0] if currents else measured[0]


def _longest_uniform(t: np.ndarray, dt: float) -> tuple[int, int]:
    """``[a, b)`` of the longest run of points whose spacings all lie within ``UNIFORM_TOL`` of ``dt``."""
    good = np.abs(np.diff(t) - dt) <= UNIFORM_TOL * dt
    if good.all():
        return 0, t.size
    padded = np.concatenate([[False], good, [False]])
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    starts, stops = edges[0::2], edges[1::2]
    if starts.size == 0:
        return 0, min(1, t.size)
    k = int(np.argmax(stops - starts))
    return int(starts[k]), int(stops[k]) + 1


def noise_record(d: RunData, *, y: str | None, event: str | None, t_min: float | None, t_max: float | None,
                 criteria: TrustPolicy | None, method: str) -> NoiseRecord:
    """The record a noise method analyses (module docstring "Record").

    Raises:
        InvalidInputError: Without ``t_s``, for an unknown column or event.
    """
    policy = trust_policy(criteria)
    if T_S not in d.table.columns:
        raise InvalidInputError(f"{method}: run {d.run_id} has no t_s column (a sampled record is needed).")
    y = _default_y(d, y, method)
    table = d.table
    warnings: list[str] = []
    if EVENT in table.columns:
        labels = table[EVENT].astype(str)
        if event is not None:
            if not (labels == event).any():
                raise InvalidInputError(f"{method}: run {d.run_id} has no event {event!r}; events: "
                                        f"{sorted(labels.unique())}.")
        elif labels.nunique() > 1:
            event = str(labels.value_counts().idxmax())
            warnings.append(f"run {d.run_id} has several measurement events; analysed event {event!r} (most points)")
        if event is not None:
            table = table[(labels == event).to_numpy()]
    elif event is not None:
        raise InvalidInputError(f"{method}: run {d.run_id} has no event column.")
    columns = [STEP, y] + ([status_column(y)] if status_column(y) in table.columns else [])
    levels = trust_levels(table, policy, columns=[y]).to_numpy()
    reasons = row_reasons(table[columns], policy)
    t = table[T_S].to_numpy(dtype=float)
    x = table[y].to_numpy(dtype=float)
    inside = np.isfinite(t) & np.isfinite(x)
    if t_min is not None:
        inside &= t >= t_min
    if t_max is not None:
        inside &= t <= t_max
    reasons = reasons.where(inside | (reasons != "N"), "outside_window")
    untrusted = (levels == "untrusted") & inside
    problems = []
    if untrusted.any():
        letters = ", ".join(f"{k}: {v}" for k, v in excluded_counts(reasons[untrusted]).items())
        problems.append(f"{int(untrusted.sum())} untrusted point(s) in {y} ({letters})")
    usable = (levels == "ok") & inside
    ts, xs = t[usable], x[usable]
    order = np.argsort(ts, kind="stable")
    ts, xs = ts[order], xs[order]
    dt = float(np.median(np.diff(ts))) if ts.size > 1 else math.nan
    if ts.size > 1 and dt > 0:
        a, b = _longest_uniform(ts, dt)
        if b - a < ts.size:
            left = ts.size - (b - a)
            warnings.append(f"used the longest uniformly sampled stretch: {b - a} of {ts.size} points "
                            f"({ts[a]:.6g}..{ts[b - 1]:.6g} s); {left} point(s) left out")
            reasons = reasons.copy()
            kept = np.zeros(ts.size, dtype=bool)
            kept[a:b] = True
            left_rows = np.flatnonzero(usable)[order][~kept]
            reasons.iloc[left_rows] = "non_uniform"
            ts, xs = ts[a:b], xs[a:b]
    return NoiseRecord(y=y, unit=d.unit(y), t=ts, x=xs, dt=dt, excluded=excluded_counts(reasons), problems=problems,
                       warnings=warnings, event=event)


def _gate(out: Results, rec: NoiseRecord, force: bool, quantities: Sequence[tuple[str, Unit]]
          ) -> list[ExtractionResult] | None:
    """Refusal (untrusted without ``force``) or failure (too short a record) of every quantity, else ``None``."""
    if rec.problems and not force:
        return [out.refused(q, u, rec.problems, excluded=rec.excluded) for q, u in quantities]
    out.flag(rec.problems if force else [])
    out.warnings.extend(rec.warnings)
    if rec.n < MIN_POINTS or not (math.isfinite(rec.dt) and rec.dt > 0):
        error = f"{rec.n} uniformly sampled trusted point(s) of {rec.y}; at least {MIN_POINTS} are needed"
        return [out.failed(q, u, error, excluded=rec.excluded) for q, u in quantities]
    return None


def _window(rec: NoiseRecord) -> QuantityRange | None:
    low, high = float(rec.t[0]), float(rec.t[-1])
    return QuantityRange(low=low, high=high, unit="s") if high > low else None


# -- it_statistics ---------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def it_statistics(
    d: RunData,
    *,
    y: str | None = None,
    event: str | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Statistics of a sampled record (module docstring): ``mean``, ``std``, ``noise_rel``, ``drift_rel``,
    ``sample_interval``."""
    rec = noise_record(d, y=y, event=event, t_min=t_min, t_max=t_max, criteria=criteria, method="it_statistics")
    out = Results("it_statistics", {"y": rec.y, "event": rec.event, "t_min": t_min, "t_max": t_max, "force": force,
                                    "trust_policy": policy_params(trust_policy(criteria))})
    names: list[tuple[str, Unit]] = [("mean", rec.unit), ("std", rec.unit), ("noise_rel", "1"), ("drift_rel", "1"),
                                     ("sample_interval", "s")]
    stop = _gate(out, rec, force, names)
    if stop is not None:
        return stop
    x, t = rec.x, rec.t
    mean, std = float(np.mean(x)), float(np.std(x, ddof=1))
    centred = x - mean
    m2 = float(np.mean(centred**2))
    skew = float(np.mean(centred**3)) / m2**1.5 if m2 > 0 else 0.0
    kurt = float(np.mean(centred**4)) / m2**2 - 3.0 if m2 > 0 else 0.0
    bimodality = (skew**2 + 1.0) / (kurt + 3.0) if kurt > -3.0 else math.inf
    slope, intercept = (float(c) for c in np.polyfit(t - t[0], x, 1))
    fitted = intercept + slope * (t - t[0])
    spread = float(np.sum(centred**2))
    r2 = 1.0 - float(np.sum((x - fitted) ** 2)) / spread if spread > 0 else 1.0
    spacing = np.diff(t)
    common = {"excluded": rec.excluded, "points_used": rec.n, "window": _window(rec)}
    shape = {"points": rec.n, "duration_s": rec.duration_s}
    warnings = []
    if bimodality > BIMODAL_BC:
        warnings.append(f"the distribution of {rec.y} looks bimodal (bimodality coefficient {bimodality:.3g} > 5/9): "
                        "two-level random telegraph noise? run rtn_levels")
    results = [
        out.ok("mean", mean, rec.unit, fit={"median": float(np.median(x)), "min": float(x.min()),
                                            "max": float(x.max()), "p01": float(np.percentile(x, 1)),
                                            "p99": float(np.percentile(x, 99)), **shape}, **common),
        out.ok("std", std, rec.unit, fit={"white_estimate": float(np.std(np.diff(x), ddof=1)) / math.sqrt(2.0),
                                          "skewness": skew, "excess_kurtosis": kurt, "bimodality": bimodality},
               warnings=warnings, **common),
    ]
    if mean != 0:
        results += [out.ok("noise_rel", std / abs(mean), "1", **common),
                    out.ok("drift_rel", slope * rec.duration_s / abs(mean), "1", fit={"slope": slope, "r2": r2},
                           **common)]
    else:
        results += [out.failed(q, "1", f"the mean of {rec.y} is 0; relative values are undefined",
                               excluded=rec.excluded) for q in ("noise_rel", "drift_rel")]
    results.append(out.ok("sample_interval", rec.dt, "s",
                          fit={"jitter_rel": float(np.std(spacing)) / rec.dt, **shape}, **common))
    return results


# -- psd_welch -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PsdAnalysis:
    """Welch PSD of a record, its log bins inside the fit window and the fit (``None`` when it failed)."""

    f: np.ndarray
    s: np.ndarray
    nperseg: int
    f_lo: float
    f_hi: float
    fb: np.ndarray
    sb: np.ndarray
    counts: np.ndarray
    fit: PsdFit | None
    error: str | None
    segments: int


def analyse_psd(rec: NoiseRecord, *, segments: int, f_min: float | None, f_max: float | None,
                model: PsdModel) -> PsdAnalysis:
    """Welch PSD, log bins and fit of a record (module docstring "psd_welch")."""
    f, s, nper = welch_psd(rec.x, rec.dt, segments=segments)
    f_res = 1.0 / (nper * rec.dt)
    f_lo = f_min if f_min is not None else F_MIN_RES * f_res
    f_hi = min(f_max if f_max is not None else F_MAX_FRACTION / rec.dt, 0.5 / rec.dt)
    if not f_hi > f_lo:
        return PsdAnalysis(f, s, nper, f_lo, f_hi, np.zeros(0), np.zeros(0), np.zeros(0, dtype=int), None,
                           f"empty fit window {f_lo:g}..{f_hi:g} Hz", segments)
    fb, sb, counts = log_bins(f, s, f_lo, f_hi)
    positive = sb > 0
    fb, sb, counts = fb[positive], sb[positive], counts[positive]
    corrected = sb * np.exp(1.0 / (2.0 * segments * counts))
    try:
        fit = fit_psd(fb, corrected, counts.astype(float), model=model)
    except ValueError as exc:
        return PsdAnalysis(f, s, nper, f_lo, f_hi, fb, sb, counts, None, str(exc), segments)
    return PsdAnalysis(f, s, nper, f_lo, f_hi, fb, sb, counts, fit, None, segments)


def _f_ref(f_lo: float, f_hi: float) -> float:
    decade = 10.0 ** math.ceil(math.log10(f_lo) - 1e-12)
    if decade <= f_hi:
        return decade
    centre = math.sqrt(f_lo * f_hi)
    return float(f"{centre:.2g}")


def _psd_unit(unit: Unit) -> Unit:
    return "A^2/Hz" if unit == "A" else "V^2/Hz"


@validate_call(config=_CALL_CONFIG)
def psd_welch(
    d: RunData,
    *,
    y: str | None = None,
    event: str | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
    segments: int = Field(default=8, ge=1, le=1024),
    f_min: float | None = Field(default=None, gt=0),
    f_max: float | None = Field(default=None, gt=0),
    f_ref: float | None = Field(default=None, gt=0),
    model: PsdModel = "auto",
    gm_s: float | None = Field(default=None, gt=0),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Welch PSD of a record and its 1/f^gamma fit (module docstring): ``gamma``, ``flicker_norm_1hz``,
    ``psd_at_f_ref``, ``norm_psd_at_f_ref`` [+ ``corner_frequency``] [+ ``input_noise_at_f_ref``]."""
    rec = noise_record(d, y=y, event=event, t_min=t_min, t_max=t_max, criteria=criteria, method="psd_welch")
    if gm_s is not None and rec.unit != "A":
        raise InvalidInputError(f"psd_welch: gm_s refers a drain-current PSD to the gate; {rec.y} is not a current.")
    psd_unit = _psd_unit(rec.unit)
    out = Results("psd_welch", {"y": rec.y, "event": rec.event, "t_min": t_min, "t_max": t_max,
                                "segments": segments, "f_min": f_min, "f_max": f_max, "f_ref": f_ref, "model": model,
                                "gm_s": gm_s, "force": force, "trust_policy": policy_params(trust_policy(criteria))})
    names: list[tuple[str, Unit]] = [("gamma", "1"), ("flicker_norm_1hz", "1/Hz"), ("psd_at_f_ref", psd_unit),
                                     ("norm_psd_at_f_ref", "1/Hz")]
    stop = _gate(out, rec, force, names)
    if stop is not None:
        return stop
    try:
        psd = analyse_psd(rec, segments=segments, f_min=f_min, f_max=f_max, model=model)
    except ValueError as exc:
        return [out.failed(q, u, str(exc), excluded=rec.excluded) for q, u in names]
    if psd.fit is None:
        return [out.failed(q, u, f"no PSD fit: {psd.error}", excluded=rec.excluded) for q, u in names]
    fit = psd.fit
    mean = float(np.mean(rec.x))
    window = QuantityRange(low=float(psd.fb.min()), high=float(psd.fb.max()), unit="Hz")
    common = {"excluded": rec.excluded, "points_used": rec.n, "window": window}
    shape = {"bins": fit.bins, "segments": segments, "nperseg": psd.nperseg, "f_res_hz": 1.0 / (psd.nperseg * rec.dt),
             "f_lo_hz": psd.f_lo, "f_hi_hz": psd.f_hi, "dt_s": rec.dt, "mean": mean}
    warnings = []
    if not GAMMA_RANGE[0] + 0.01 < fit.gamma < GAMMA_RANGE[1] - 0.01:
        warnings.append(f"gamma {fit.gamma:.3g} sits at the edge of the search range {GAMMA_RANGE}: poorly "
                        "constrained")
    if fit.rms_log > 0.3:
        warnings.append(f"rms log residual {fit.rms_log:.2g}: the spectrum is not {fit.model} in the window (line "
                        "pickup, several Lorentzians?); narrow f_min/f_max or change model")
    gamma_fit = {"gamma_se": fit.gamma_se, "a": fit.a, "white": fit.w, "rms_log": fit.rms_log, **shape}
    if fit.model == "power_lorentzian":
        gamma_fit.update(corner_hz=fit.fc, plateau=fit.b)
    reference = f_ref if f_ref is not None else _f_ref(float(psd.fb.min()), float(psd.fb.max()))
    at_ref = float(np.exp(np.interp(math.log(reference), np.log(psd.fb), np.log(psd.sb))))
    ref_fit = {"f_ref_hz": reference, "model_at_f_ref": float(fit.evaluate(np.asarray([reference]))[0])}
    if not psd.fb.min() <= reference <= psd.fb.max():
        warnings.append(f"f_ref {reference:g} Hz lies outside the fitted bins {psd.fb.min():.3g}..{psd.fb.max():.3g} "
                        "Hz: psd_at_f_ref is the nearest bin's value")
    results = [out.ok("gamma", fit.gamma, "1", fit=gamma_fit, classification=fit.model, warnings=warnings, **common)]
    if mean != 0:
        results.append(out.ok("flicker_norm_1hz", fit.a / mean**2, "1/Hz", fit={"a": fit.a, "mean": mean}, **common))
    else:
        results.append(out.failed("flicker_norm_1hz", "1/Hz", f"the mean of {rec.y} is 0", excluded=rec.excluded))
    results.append(out.ok("psd_at_f_ref", at_ref, psd_unit, fit=ref_fit, **common))
    if mean != 0:
        results.append(out.ok("norm_psd_at_f_ref", at_ref / mean**2, "1/Hz", fit=ref_fit, **common))
    else:
        results.append(out.failed("norm_psd_at_f_ref", "1/Hz", f"the mean of {rec.y} is 0", excluded=rec.excluded))
    if fit.model == "power_lorentzian":
        results.append(out.ok("corner_frequency", fit.fc, "Hz", fit={
            "plateau": fit.b, "plateau_norm": fit.b / mean**2 if mean else math.nan,
            "tau_rtn_s": 1.0 / (2.0 * math.pi * fit.fc)}, **common))
    if gm_s is not None:
        results.append(out.ok("input_noise_at_f_ref", at_ref / gm_s**2, "V^2/Hz", fit={**ref_fit, "gm_s": gm_s},
                              **common))
    return results


# -- rtn_levels ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TwoLevels:
    """Two-Gaussian mixture of a record: lower and upper level, their spreads and the lower level's weight."""

    low: float
    high: float
    sigma_low: float
    sigma_high: float
    weight_low: float

    @property
    def separation(self) -> float:
        spread = max(self.sigma_low, self.sigma_high)
        return (self.high - self.low) / spread if spread > 0 else math.inf


def two_level(x: np.ndarray, *, bins: int = 512, iterations: int = 300) -> TwoLevels:
    """Two-Gaussian mixture by EM on a histogram of ``x`` (module docstring "rtn_levels", step 1)."""
    lo_q, hi_q = np.percentile(x, [0.05, 99.95])
    if not hi_q > lo_q:
        return TwoLevels(float(lo_q), float(lo_q), 0.0, 0.0, 1.0)
    counts, edges = np.histogram(x, bins=bins, range=(float(lo_q), float(hi_q)))
    c = 0.5 * (edges[1:] + edges[:-1])
    h = counts.astype(float)
    mu = np.asarray(np.percentile(x, [10, 90]), dtype=float)
    width = float(edges[1] - edges[0])
    sig = np.full(2, max((mu[1] - mu[0]) / 4.0, width))
    wgt = np.array([0.5, 0.5])
    for _ in range(iterations):
        dens = wgt[:, None] / sig[:, None] * np.exp(-0.5 * ((c[None, :] - mu[:, None]) / sig[:, None]) ** 2)
        resp = dens / np.maximum(dens.sum(0), _TINY)
        nk = (resp * h).sum(1)
        if np.any(nk <= 0):
            break
        mu_new = (resp * h * c).sum(1) / nk
        sig_new = np.sqrt(np.maximum((resp * h * (c[None, :] - mu_new[:, None]) ** 2).sum(1) / nk,
                                     width**2 / 12.0))
        wgt = nk / nk.sum()
        done = np.allclose(mu_new, mu, rtol=0, atol=1e-9 * (abs(hi_q) + abs(lo_q))) and np.allclose(sig_new, sig)
        mu, sig = mu_new, sig_new
        if done:
            break
    order = np.argsort(mu)
    mu, sig, wgt = mu[order], sig[order], wgt[order]
    return TwoLevels(float(mu[0]), float(mu[1]), float(sig[0]), float(sig[1]), float(wgt[0]))


def _resolved(levels: TwoLevels) -> bool:
    """A mixture that may be a two-level signal (the final test uses the noise after the level tracking)."""
    return levels.separation >= MIN_SEPARATION - 1.0 and min(levels.weight_low, 1.0 - levels.weight_low) >= 0.01


def _schmitt(x: np.ndarray, low_th: np.ndarray, high_th: np.ndarray, start: bool) -> np.ndarray:
    """Upper-state flags with hysteresis: a point above ``high_th`` sets the state, below ``low_th`` clears it."""
    code = np.where(x > high_th, 1, np.where(x < low_th, -1, 0))
    index = np.where(code != 0, np.arange(x.size), -1)
    last = np.maximum.accumulate(index)
    state = np.where(last >= 0, code[np.maximum(last, 0)] > 0, start)
    return state.astype(bool)


def _local_mean(x: np.ndarray, mask: np.ndarray, half: int) -> np.ndarray:
    """Moving mean of ``x`` over the points where ``mask`` inside ``+-half`` points, interpolated where a window
    holds fewer than 5 such points."""
    n = x.size
    csum = np.concatenate([[0.0], np.cumsum(np.where(mask, x, 0.0))])
    cnt = np.concatenate([[0], np.cumsum(mask.astype(np.int64))])
    i = np.arange(n)
    a, b = np.clip(i - half, 0, n), np.clip(i + half + 1, 0, n)
    k = cnt[b] - cnt[a]
    good = k >= 5
    out = np.full(n, np.nan)
    out[good] = (csum[b] - csum[a])[good] / k[good]
    if not good.any():
        return np.full(n, float(np.mean(x[mask])) if mask.any() else math.nan)
    return np.interp(i, i[good], out[good])


def _dwells(t: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Complete dwells ``(durations, upper-state flags)`` between transition times, and the transition count."""
    change = np.flatnonzero(state[1:] != state[:-1]) + 1
    times = 0.5 * (t[change - 1] + t[change])
    return np.diff(times), state[change[:-1]], int(change.size)


def _survival_tau(dwells: np.ndarray, t0: float) -> float:
    """``tau`` from a weighted log-linear fit of the empirical survival of the dwells longer than ``t0``."""
    d = np.sort(dwells[dwells > t0])
    n = d.size
    if n < 10:
        return math.nan
    keep = n - 5
    surv = (n - np.arange(keep)) / n
    weights = (n - np.arange(keep)).astype(float)
    slope = np.polyfit(d[:keep] - t0, np.log(surv), 1, w=np.sqrt(weights))[0]
    return -1.0 / slope if slope < 0 else math.nan


@validate_call(config=_CALL_CONFIG)
def rtn_levels(
    d: RunData,
    *,
    y: str | None = None,
    event: str | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
    hysteresis: float = Field(default=0.5, gt=0.0, lt=1.0),
    baseline_s: float | None = Field(default=None, ge=0.0),
    smooth: int = Field(default=1, ge=1, le=1000),
    occupied: Occupied = "low",
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Two-level random telegraph noise of a record (module docstring): ``tau_c``, ``tau_e``, ``delta_i`` and
    ``delta_i_rel`` (``delta_v`` ... for a voltage record)."""
    rec = noise_record(d, y=y, event=event, t_min=t_min, t_max=t_max, criteria=criteria, method="rtn_levels")
    delta = {"A": "delta_i", "V": "delta_v"}.get(rec.unit, "delta")
    out = Results("rtn_levels", {"y": rec.y, "event": rec.event, "t_min": t_min, "t_max": t_max,
                                 "hysteresis": hysteresis, "baseline_s": baseline_s, "smooth": smooth,
                                 "occupied": occupied, "force": force,
                                 "trust_policy": policy_params(trust_policy(criteria))})
    names: list[tuple[str, Unit]] = [("tau_c", "s"), ("tau_e", "s"), (delta, rec.unit), (f"{delta}_rel", "1")]
    stop = _gate(out, rec, force, names)
    if stop is not None:
        return stop
    x, t = rec.x, rec.t
    if smooth > 1:
        x = np.convolve(x, np.ones(smooth) / smooth, mode="same")
    levels = two_level(x)
    base = np.zeros(x.size)
    if baseline_s is None or baseline_s > 0:
        trend = _local_mean(x, np.ones(x.size, dtype=bool), max(PREFILTER_MIN, x.size // PREFILTER_FRACTION))
        detrended = two_level(x - trend)
        if _resolved(detrended) and (not _resolved(levels) or detrended.separation > levels.separation):
            levels, base = detrended, trend
    if not _resolved(levels):
        return [out.failed(q, u, f"no two-level signal in {rec.y}: the levels are {levels.separation:.2g} sigma "
                           f"apart and the lower one holds {levels.weight_low:.1%} of the points",
                           excluded=rec.excluded) for q, u in names]
    low = base + levels.low
    high = base + levels.high

    def classify(start: bool) -> np.ndarray:
        step = high - low
        return _schmitt(x, low + (1.0 - hysteresis) / 2.0 * step, low + (1.0 + hysteresis) / 2.0 * step, start)

    state = classify(bool(x[0] > base[0] + 0.5 * (levels.low + levels.high)))
    if baseline_s is None or baseline_s > 0:
        if baseline_s is None:
            _, _, flips = _dwells(t, state)
            mean_dwell = x.size / max(flips + 1, 1)
            half = int(np.clip(BASELINE_DWELLS * mean_dwell / 2.0, 32, max(32, x.size // 8)))
        else:
            half = max(1, round(baseline_s / rec.dt / 2.0))
        for _ in range(2):
            if state.all() or not state.any():
                break
            low, high = _local_mean(x, ~state, half), _local_mean(x, state, half)
            state = classify(bool(state[0]))
        used_baseline = 2 * half * rec.dt
    else:
        used_baseline = 0.0
    step_local = high - low
    residual = x - np.where(state, high, low)
    sigma = 1.4826 * float(np.median(np.abs(residual - np.median(residual))))
    d_level = float(np.mean(step_local))
    separation = d_level / sigma if sigma > 0 else math.inf
    dwells, upper, transitions = _dwells(t, state)
    upper_is_empty = (np.mean(x) >= 0) == (occupied == "low")
    empty = upper == upper_is_empty
    d_empty, d_occ = dwells[empty], dwells[~empty]
    empty_level = float(np.mean(high if upper_is_empty else low))
    shared = {"transitions": transitions, "occupancy": float(np.mean(state != upper_is_empty)),
              "separation": separation, "dt_s": rec.dt, "duration_s": rec.duration_s, "baseline_s": used_baseline,
              "level_empty": empty_level, "level_occupied": float(np.mean(low if upper_is_empty else high)),
              "sigma": sigma}
    if separation < MIN_SEPARATION or min(d_empty.size, d_occ.size) < MIN_DWELLS:
        error = (f"two levels not resolved in {rec.y}: separation {separation:.2g} sigma (>= {MIN_SEPARATION:g} "
                 f"needed), {d_empty.size} empty and {d_occ.size} occupied complete dwells (>= {MIN_DWELLS})")
        return [out.failed(q, u, error, excluded=rec.excluded, fit=shared) for q, u in names]
    warnings = []
    if transitions < MIN_TRANSITIONS:
        warnings.append(f"only {transitions} transitions: tau has a statistical error of about 1/sqrt(n) per state "
                        f"(the blueprint target needs >= {MIN_TRANSITIONS}); record longer")
    if separation < WARN_SEPARATION:
        warnings.append(f"the levels are only {separation:.2g} sigma apart: some transitions may be false or missed")
    common = {"excluded": rec.excluded, "points_used": rec.n, "window": _window(rec)}
    results = []
    for name, sample, state_name in (("tau_c", d_empty, "empty"), ("tau_e", d_occ, "occupied")):
        tau = float(np.mean(sample))
        own = []
        cv = float(np.std(sample, ddof=1) / tau) if sample.size > 1 and tau > 0 else math.nan
        tau_fit = _survival_tau(sample, 2.0 * rec.dt)
        if tau < 10.0 * rec.dt:
            own.append(f"{name} = {tau / rec.dt:.3g} sampling intervals: dwells shorter than about 2 points are "
                       "missed; sample faster")
        if sample.size >= 20 and not 0.6 <= cv <= 1.4:
            own.append(f"dwells in the {state_name} state are not exponential (cv {cv:.2g}): several traps or levels?")
        if math.isfinite(tau_fit) and abs(tau_fit - tau) > 0.25 * tau:
            own.append(f"{name}: the survival fit gives {tau_fit:.3g} s against the mean {tau:.3g} s")
        fit = {"n": sample.size, "se": tau / math.sqrt(sample.size), "tau_fit_s": tau_fit, "cv": cv, **shared}
        results.append(out.ok(name, tau, "s", fit=fit, warnings=[*warnings, *own], **common))
    results.append(out.ok(delta, abs(d_level), rec.unit, fit=shared, warnings=warnings, **common))
    if empty_level != 0:
        results.append(out.ok(f"{delta}_rel", abs(d_level) / abs(empty_level), "1", fit=shared, warnings=warnings,
                              **common))
    else:
        results.append(out.failed(f"{delta}_rel", "1", "the empty-trap level is 0", excluded=rec.excluded,
                                  fit=shared))
    return results


# -- plot_psd --------------------------------------------------------------------------------------------------------


def render_psd(d: RunData, *, y: str | None = None, event: str | None = None, t_min: float | None = None,
               t_max: float | None = None, segments: int = 8, f_min: float | None = None, f_max: float | None = None,
               model: PsdModel = "auto", criteria: TrustPolicy | None = None) -> PlotSet:
    """Render the PSD plot of ``d`` (module docstring "plot_psd") as PNG bytes; nothing is written."""
    rec = noise_record(d, y=y, event=event, t_min=t_min, t_max=t_max, criteria=criteria, method="plot_psd")
    notes = list(rec.warnings)
    if rec.problems:
        notes.append("left out: " + "; ".join(rec.problems))
    figure = new_figure(width_in=7.0, height_in=6.4)
    title = f"{d.run_id} {d.manifest.recipe_id} ({'SIMULATED' if d.manifest.simulated else 'measured'}) {rec.y}"
    psd: PsdAnalysis | None = None
    if rec.n >= MIN_POINTS and math.isfinite(rec.dt) and rec.dt > 0:
        try:
            psd = analyse_psd(rec, segments=segments, f_min=f_min, f_max=f_max, model=model)
        except ValueError as exc:
            notes.append(f"no PSD: {exc}")
    else:
        notes.append(f"no PSD: {rec.n} uniformly sampled trusted points (at least {MIN_POINTS})")
    if psd is not None and psd.error:
        notes.append(f"no fit: {psd.error}")
    mean = float(np.mean(rec.x)) if rec.n else 0.0
    psd_unit = "A^2/Hz" if rec.unit == "A" else "V^2/Hz"
    for panel, scale, label in ((1, 1.0, f"S ({psd_unit})"), (2, mean**2, "S / mean^2 (1/Hz)")):
        axes = figure.add_subplot(2, 1, panel)
        if psd is not None and scale > 0:
            keep = psd.f > 0
            axes.loglog(psd.f[keep], psd.s[keep] / scale, "-", linewidth=0.5, color="0.6", label="Welch")
            axes.axvspan(psd.f_lo, psd.f_hi, color="0.9", zorder=0)
            if psd.fb.size:
                axes.loglog(psd.fb, psd.sb / scale, "o", markersize=3, label="log bins (fit)")
            if psd.fit is not None:
                fit = psd.fit
                fl = np.geomspace(psd.f_lo, psd.f_hi, 200)
                axes.loglog(fl, fit.evaluate(fl) / scale, "-", linewidth=1.5,
                            label=f"fit {fit.model}: gamma {fit.gamma:.3g}")
                axes.loglog(fl, fit.flicker(fl) / scale, "--", linewidth=0.8, label="1/f^gamma")
                if fit.b > 0:
                    axes.loglog(fl, fit.lorentzian(fl) / scale, "--", linewidth=0.8,
                                label=f"Lorentzian fc {fit.fc:.3g} Hz")
                if fit.w > 0:
                    axes.loglog(fl, np.full_like(fl, fit.w / scale), ":", linewidth=0.8, label="white")
            axes.legend(fontsize=7)
        axes.set_xlabel("f (Hz)")
        axes.set_ylabel(label)
        axes.grid(True, which="both", alpha=0.3)
    figure.suptitle(title, fontsize=9)
    if notes:
        figure.text(0.01, 0.005, " ".join(notes)[:400], fontsize=6)
    return PlotSet(plots=(RenderedPlot(name="psd", png=figure_png(figure)),), x="f", y=(rec.y,), scale="log",
                   warnings=tuple(notes))


@validate_call(config=_CALL_CONFIG)
def plot_psd_method(
    d: RunData,
    *,
    y: str | None = None,
    event: str | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
    segments: int = Field(default=8, ge=1, le=1024),
    f_min: float | None = Field(default=None, gt=0),
    f_max: float | None = Field(default=None, gt=0),
    model: PsdModel = "auto",
    criteria: TrustPolicy | None = None,
) -> PlotSet:
    """The registered ``plot_psd`` method: ``render_psd`` with JSON options; the caller stores the ``PlotSet``."""
    return render_psd(d, y=y, event=event, t_min=t_min, t_max=t_max, segments=segments, f_min=f_min, f_max=f_max,
                      model=model, criteria=criteria)


@validate_call(config=_CALL_CONFIG)
def plot_psd(
    d: RunData,
    *,
    y: str | None = None,
    event: str | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
    segments: int = Field(default=8, ge=1, le=1024),
    f_min: float | None = Field(default=None, gt=0),
    f_max: float | None = Field(default=None, gt=0),
    model: PsdModel = "auto",
    out_dir: Path | None = None,
    criteria: TrustPolicy | None = None,
) -> list[Path]:
    """Render the PSD plot of ``d`` into ``out_dir`` (default ``work/<run_id>/plots/``) and return the PNG paths. For
    agent scripts; ``analyze_run`` stores it in the run folder instead."""
    rendered = render_psd(d, y=y, event=event, t_min=t_min, t_max=t_max, segments=segments, f_min=f_min,
                          f_max=f_max, model=model, criteria=criteria)
    target = out_dir if out_dir is not None else work_dir_for(d.run_id) / "plots"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for plot in rendered.plots:
        path = target / f"{plot.name}.png"
        path.write_bytes(plot.png)
        paths.append(path)
    return paths
