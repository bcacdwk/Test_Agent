"""Analyses of the C-V variants (blueprint v2 2.10 ``cv.py`` row; WP8.4; a module of its own because ``cv.py`` is
near the file-size limit): ``cf_dispersion`` (C-f), ``ct_recovery`` (C-t), ``cv_ac_dependence`` (C-V over the AC
level), ``cv_butterfly`` (FeCap C-V double sweep) and the two-run ``cv_pulsed_vs_dc`` (pulsed vs DC C-V). They reuse
``cv.py``'s impedance conversions, curve loading and the MOS-C fit ``moscap_fit``. The definitions below are the
source of knowledge file ``08-capacitance-cv.md`` (skill ``b1500-test``); change both together.

**cf_dispersion** (Nicollian & Brews, *MOS Physics and Technology*, 1982, ch. 5, the conductance method; not
page-checked). A C-f run at one DC bias in depletion: the measured parallel pair ``Cm``, ``Gm`` (after removing a
series ``rs_ohm``) gives the interface-trap conductance ``Gp/w = w Cox^2 Gm / (Gm^2 + w^2 (Cox - Cm)^2)``. ``Cox``
comes from ``cox_f`` (e.g. the ``cv_cox`` result of a C-V on the same device) or from the DUT geometry (``eps_ox eps0
area_um2 / tox_nm``, ``eps_ox`` 3.9 by default: an EOT estimate). The trap response is fitted over the
frequencies: ``model: continuum`` (traps spread in energy, ``Gp/w = q A Dit ln(1 + (w tau)^2) / (2 w tau)``, peak
``0.402 q A Dit`` at ``w tau = 1.98``) or ``single`` (one level, ``q A Dit w tau / (1 + (w tau)^2)``, peak
``q A Dit / 2`` at ``w tau = 1``), giving ``dit`` (cm^-2 eV^-1, needs ``geometry.area_um2``), ``tau_it`` (s),
``f_peak`` (Hz) and ``gp_w_max`` (F). The peak must lie inside the measured frequencies (else the bias is moved:
towards midgap the peak moves to lower, towards flatband to higher frequencies). ``c_dispersion`` = ``C(f_low) /
C(f_high) - 1``: the traps' (and minority carriers') capacitance that only low frequencies see. One bias gives Dit
at one energy; ``dit_conductance`` maps Dit(E) over biases.

**ct_recovery** (Zerbst 1966; Nicollian & Brews ch. 9; not page-checked). After a step from accumulation into
inversion the surface is in deep depletion; minority carriers are generated and the inversion layer forms. In the
depletion approximation ``1/C^2`` is linear in the inversion charge at a fixed gate bias, so its relaxation is fitted
directly: ``1/C^2 = y_inf + (y0 - y_inf) exp(-(t/tau)^beta)`` (``reliability.fit_stretched_exponential``; ``beta`` = 1
for a single time constant) over ``t_s`` (``t_min``..``t_max``), reporting ``tau_recovery`` (s), ``beta``,
``c_initial`` (the deep-depletion capacitance at the step, ``y0^-1/2``) and ``c_final`` (equilibrium, ``y_inf^-1/2``).
``tau`` is the inversion-layer formation time; turning it into a generation lifetime needs the doping and the Zerbst
plot (ad-hoc, ``work/``). A record shorter than three ``tau`` makes ``c_final`` an extrapolation (warning).

**cv_ac_dependence**. The MFCMU reports the fundamental of the current; on a curved C-V the capacitance at bias ``V0``
measured with an oscillator level ``Vac`` is ``C(V0) + C''(V0) Vac^2 / 4`` to second order (the describing function
over the swing ``sqrt(2) Vac``). A line of ``C`` against ``Vac^2`` gives ``c_small_signal`` (the intercept ``C0``)
and the curvature (``fit.d2c_dv2``); ``ac_limit`` (V rms) is the level where the fitted ``|C - C0| / C0`` reaches
``tolerance`` (default 1 %; a lower bound when the sweep stays inside it) and ``max_rel_change`` the largest measured
``|C / C0 - 1|``.

**cv_butterfly** (Miller et al., J. Appl. Phys. 68, 6463, 1990; not page-checked). A ferroelectric capacitor's
small-signal capacitance is the dielectric part plus the reversible polarization response of the branch being
travelled; it peaks near ``+Vc`` while the bias rises and near ``-Vc`` while it falls. Each branch of a double sweep
gives its peak (the maximum of ``C``, refined by the vertex of a parabola through the five points around it; a peak at
a branch end fails: sweep further): ``v_peak_up``, ``v_peak_down``, ``vc = (up - down) / 2``, the imprint ``v_imprint
= (up + down) / 2``, ``c_peak`` (F) and, with ``geometry.tox_nm`` as the film thickness, ``ec = vc / t`` (MV/cm).

**cv_pulsed_vs_dc** (two-run; ``options.reference_run`` = a DC C-V of the same device, e.g. ``moscap.cv`` swept from
accumulation). Both curves at one frequency are fitted with ``moscap_fit``: ``delta_vfb`` = Vfb(pulsed) - Vfb(DC)
(needs ``geometry.area_um2``; without it the crossing of the mid level ``(Cmax + Cmin) / 2``, flagged),
``cox_ratio`` = Cox(pulsed) / Cox(DC) and ``c_ratio_inversion`` = C(pulsed) / C(DC) at the inversion-side end of the
common bias range (below 1: deep depletion in the pulses; about 1: the inversion layer forms within the pulse or
the DC curve itself is in deep depletion). Pulses from an accumulation base also start every point with emptied
border traps, so a ``delta_vfb`` against a DC sweep that started in inversion is the C-V hysteresis, not an error.

Trust: untrusted points (MFCMU status ``U D V X``) refuse the extraction unless ``force`` (flagged), as in ``cv.py``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    excluded_counts,
    peak_index,
    policy_params,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.cv import (
    ACC_FRAC,
    EPS0_F_CM,
    EPS_SIO2,
    Q_E,
    FitError,
    area_cm2,
    frequencies,
    load_curve,
    moscap_fit,
    pair_of,
    remove_series_r,
    to_admittance,
)
from b1500_test_agent.analysis.dataset import AC_VRMS, DC_V, FREQ_HZ, SEGMENT, T_S, RunData, Segment
from b1500_test_agent.analysis.reliability import fit_stretched_exponential
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

TrapModel = Literal["continuum", "single"]

CONTINUUM_PEAK_WT = 1.9803
"""``w tau`` at the maximum of the continuum ``Gp/w`` (root of ``2x^2 = (1 + x^2) ln(1 + x^2)``)."""

CONTINUUM_PEAK = 0.40237
"""``max ln(1 + x^2) / (2x)``: the continuum peak is ``0.402 q A Dit``."""

TAU_GRID_POINTS = 400
GOLDEN_STEPS = 80
MIN_CF_POINTS = 4
MIN_LEVELS = 3
PEAK_HALF_WIDTH = 2
CT_MIN_TAUS = 3.0
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


# -- shared helpers --------------------------------------------------------------------------------------------------


def _rows_of(d: RunData, freq_hz: float | None, segment: Segment | None) -> tuple[pd.DataFrame, float]:
    """Rows of one loop frequency (default the first) and segment (``None``: all), acquisition order."""
    freqs = frequencies(d)
    if not freqs:
        raise InvalidInputError(f"run {d.run_id} has no frequency")
    freq = freqs[0] if freq_hz is None else freq_hz
    if not any(math.isclose(freq, f, rel_tol=1e-9) for f in freqs):
        raise InvalidInputError(f"run {d.run_id} has no frequency {freq:g} Hz; frequencies: {freqs}")
    rows = d.rows(segment) if segment is not None and d.has_segments else d.table
    return rows[np.isclose(rows[FREQ_HZ].to_numpy(dtype=float), freq, rtol=1e-9)], freq


def _parallel(d: RunData, rows: pd.DataFrame, omega: np.ndarray, rs_ohm: float = 0.0) -> tuple[np.ndarray,
                                                                                              np.ndarray]:
    """Parallel ``(C, G)`` of ``rows`` at ``omega`` (series ``rs_ohm`` removed)."""
    role, primary, secondary = pair_of(d)
    y = remove_series_r(to_admittance(primary, secondary, rows[f"{role}_{primary}"].to_numpy(dtype=float),
                                      rows[f"{role}_{secondary}"].to_numpy(dtype=float), omega), rs_ohm)
    return y.imag / omega, y.real


def _start(method: str, d: RunData, x: str, rows: pd.DataFrame, criteria: TrustPolicy | None, force: bool,
           **params: object) -> tuple[Results, np.ndarray, dict[str, int], list[str]]:
    """Results builder, the usable-row mask, excluded counts and the refusal problems (empty when forced)."""
    policy = trust_policy(criteria)
    role, primary, secondary = pair_of(d)
    analysed = analysed_rows(d, x, f"{role}_{primary}", policy, rows=rows)
    ok = analysed.ok & np.isfinite(rows[f"{role}_{secondary}"].to_numpy(dtype=float))
    out = Results(method, {**params, "force": force, "trust_policy": policy_params(policy)})
    problems = analysed.problems(f"{role}_{primary}", noise=False)
    if problems and force:
        out.flag(problems)
        problems = []
    return out, ok, analysed.excluded(), problems


def _all(out: Results, names: Sequence[tuple[str, Unit]], outcome: Literal["refused", "failed"], why: str | list[str],
         excluded: dict[str, int]) -> list[ExtractionResult]:
    if outcome == "refused":
        problems = why if isinstance(why, list) else [why]
        return [out.refused(n, u, problems, excluded=excluded) for n, u in names]
    return [out.failed(n, u, str(why), excluded=excluded) for n, u in names]


def _geometry_missing(d: RunData, field: str) -> str:
    profile = d.manifest.plan.request.dut_profile or "(none)"
    return f"Refused: DUT profile {profile} has no {field}; a human adds the device geometry to the DUT profile."


def _vertex(x: np.ndarray, y: np.ndarray, i: int) -> float:
    """``x`` of the parabola vertex through the points ``i - 2 .. i + 2`` (``x[i]`` when not concave), kept within
    those points (``x`` ascending or descending)."""
    lo, hi = max(0, i - PEAK_HALF_WIDTH), min(x.size, i + PEAK_HALF_WIDTH + 1)
    a, b, _ = np.polyfit(x[lo:hi] - x[i], y[lo:hi], 2)
    if a >= 0:
        return float(x[i])
    shift = -b / (2.0 * a)
    first, last = sorted((float(x[lo] - x[i]), float(x[hi - 1] - x[i])))
    return float(x[i] + min(max(shift, first), last))


# -- cf_dispersion ---------------------------------------------------------------------------------------------------


def gp_over_omega(cm: np.ndarray, gm: np.ndarray, omega: np.ndarray, cox: float) -> np.ndarray:
    """Interface-trap conductance ``Gp/w`` (F) from the measured parallel ``Cm``, ``Gm`` and ``Cox``
    (Nicollian-Goetzberger; module docstring). Shared with the multi-bias conductance method."""
    return omega * cox**2 * gm / (gm**2 + omega**2 * (cox - cm) ** 2)


def trap_shape(wt: np.ndarray, model: TrapModel) -> np.ndarray:
    """``Gp/w`` per ``q A Dit`` at ``w tau`` for the continuum or single-level model."""
    return np.log1p(wt * wt) / (2.0 * wt) if model == "continuum" else wt / (1.0 + wt * wt)


def fit_trap_response(omega: np.ndarray, gpw: np.ndarray, model: TrapModel) -> tuple[float, float, float]:
    """Least-squares ``Gp/w = K shape(w tau)``: ``(tau, K, r2)`` (log grid over tau, then golden-section
    refinement; ``K`` by linear least squares at each tau)."""

    def sse(log_tau: float) -> tuple[float, float]:
        shape = trap_shape(omega * 10.0**log_tau, model)
        k = float(shape @ gpw / (shape @ shape))
        residual = gpw - k * shape
        return float(residual @ residual), k

    lo = math.log10(0.05 / float(omega.max()))
    hi = math.log10(20.0 / float(omega.min()))
    grid = np.linspace(lo, hi, TAU_GRID_POINTS)
    costs = [sse(float(g))[0] for g in grid]
    best = int(np.argmin(costs))
    a, b = float(grid[max(best - 1, 0)]), float(grid[min(best + 1, grid.size - 1)])
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    for _ in range(GOLDEN_STEPS):
        c, e = b - ratio * (b - a), a + ratio * (b - a)
        if sse(c)[0] < sse(e)[0]:
            b = e
        else:
            a = c
    log_tau = 0.5 * (a + b)
    cost, k = sse(log_tau)
    spread = float(np.sum((gpw - gpw.mean()) ** 2))
    return 10.0**log_tau, k, 1.0 - cost / spread if spread > 0 else 1.0


@validate_call(config=_CALL_CONFIG)
def cf_dispersion(d: RunData, *, cox_f: float | None = Field(default=None, gt=0), eps_ox: float = Field(
                  default=EPS_SIO2, gt=1.0, le=100.0), rs_ohm: float = Field(default=0.0, ge=0.0),
                  model: TrapModel = "continuum", segment: Segment = "fwd", force: bool = False,
                  criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Frequency dispersion of a C-f run (module docstring): ``dit`` (cm^-2 eV^-1), ``tau_it`` (s), ``f_peak`` (Hz),
    ``gp_w_max`` (F) from the conductance peak and ``c_dispersion`` (1)."""
    names: list[tuple[str, Unit]] = [("dit", "cm^-2 eV^-1"), ("tau_it", "s"), ("f_peak", "Hz"), ("gp_w_max", "F"),
                                     ("c_dispersion", "1")]
    rows = d.rows(segment) if d.has_segments else d.table
    out, ok, excluded, problems = _start("cf_dispersion", d, FREQ_HZ, rows, criteria, force, cox_f=cox_f,
                                         eps_ox=eps_ox, rs_ohm=rs_ohm, model=model, segment=segment)
    if problems:
        return _all(out, names, "refused", problems, excluded)
    f = rows[FREQ_HZ].to_numpy(dtype=float)[ok]
    if np.unique(f).size < MIN_CF_POINTS:
        return _all(out, names, "failed", f"a C-f analysis needs at least {MIN_CF_POINTS} trusted frequencies "
                    f"(run {d.run_id} has {np.unique(f).size}); it applies to C-f runs (moscap.cf)", excluded)
    order = np.argsort(f, kind="stable")
    f = f[order]
    omega = 2.0 * math.pi * f
    cm, gm = _parallel(d, rows[ok].iloc[order], omega, rs_ohm)
    dc_v = float(np.median(rows[DC_V].to_numpy(dtype=float)[ok]))
    common: dict[str, object] = {"excluded": excluded, "points_used": int(f.size), "window": window_of(f, "Hz")}
    info = {"dc_v": dc_v, "c_low_f": float(cm[0]), "c_high_f": float(cm[-1])}
    results = [out.ok("c_dispersion", cm[0] / cm[-1] - 1.0, "1", fit=info, **common)]  # type: ignore[arg-type]
    area, _ = area_cm2(d, split=False)
    geometry = d.manifest.dut_geometry
    if cox_f is not None:
        cox, source = cox_f, 0.0
    elif area is not None and geometry is not None and geometry.tox_nm is not None:
        cox, source = eps_ox * EPS0_F_CM * area / (geometry.tox_nm * 1e-7), 1.0
    else:
        why = _geometry_missing(d, "geometry.area_um2 and geometry.tox_nm (or give options.cox_f, e.g. the "
                                   "cv_cox result of a C-V on the same device)")
        return [out.not_ok(n, u, "refused", why, excluded=excluded) for n, u in names[:4]] + results
    if np.any(cm >= cox):
        return [out.failed(n, u, f"the capacitance reaches Cox ({cox:.4g} F) at {dc_v:g} V: not a depletion bias; "
                           "choose a bias between Vfb and Vth of a C-V run", excluded=excluded)
                for n, u in names[:4]] + results
    gpw = gp_over_omega(cm, gm, omega, cox)
    tau, k, r2 = fit_trap_response(omega, gpw, model)
    peak_wt = CONTINUUM_PEAK_WT if model == "continuum" else 1.0
    f_peak = peak_wt / (2.0 * math.pi * tau)
    fit = {**info, "cox_f": cox, "cox_from_geometry": source, "r2": r2, "rs_ohm": rs_ohm,
           "gp_w_max_measured": float(gpw.max())}
    if not f[0] <= f_peak <= f[-1]:
        why = (f"the fitted Gp/w peak ({f_peak:.4g} Hz) lies outside the measured {f[0]:g}..{f[-1]:g} Hz; move the "
               "bias (towards midgap the peak moves to lower frequencies, towards flatband to higher ones)")
        return [out.failed(n, u, why, excluded=excluded, fit=fit) for n, u in names[:4]] + results
    peak_value = k * (CONTINUUM_PEAK if model == "continuum" else 0.5)
    geometry_note = ("Cox from the DUT geometry (eps_ox x eps0 x area / tox): an EOT estimate; give options.cox_f "
                     "from a C-V for a better value")
    warnings = [geometry_note] if source else []
    found = [out.ok("tau_it", tau, "s", fit=fit, warnings=warnings, **common),  # type: ignore[arg-type]
             out.ok("f_peak", f_peak, "Hz", fit=fit, warnings=warnings, **common),  # type: ignore[arg-type]
             out.ok("gp_w_max", peak_value, "F", fit=fit, warnings=warnings, **common)]  # type: ignore[arg-type]
    if area is None:
        found.insert(0, out.not_ok("dit", "cm^-2 eV^-1", "refused", _geometry_missing(d, "geometry.area_um2"),
                                   excluded=excluded, fit=fit))
    else:
        found.insert(0, out.ok("dit", k / (Q_E * area), "cm^-2 eV^-1", fit={**fit, "area_cm2": area},
                               warnings=warnings, **common))  # type: ignore[arg-type]
    return found + results


# -- ct_recovery -----------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def ct_recovery(d: RunData, *, freq_hz: float | None = None, t_min: float | None = Field(default=None, ge=0.0),
                t_max: float | None = Field(default=None, gt=0.0), force: bool = False,
                criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Deep-depletion recovery of a C-t run (module docstring): ``tau_recovery`` (s), ``beta``, ``c_initial`` and
    ``c_final`` (F)."""
    names: list[tuple[str, Unit]] = [("tau_recovery", "s"), ("beta", "1"), ("c_initial", "F"), ("c_final", "F")]
    if T_S not in d.table.columns:
        raise InvalidInputError(f"ct_recovery needs a C-t run with t_s (moscap.ct); run {d.run_id} has none")
    rows, freq = _rows_of(d, freq_hz, None)
    out, ok, excluded, problems = _start("ct_recovery", d, T_S, rows, criteria, force, freq_hz=freq, t_min=t_min,
                                         t_max=t_max)
    if problems:
        return _all(out, names, "refused", problems, excluded)
    t = rows[T_S].to_numpy(dtype=float)
    inside = ok & (t >= (t_min or 0.0)) & (t <= (t_max if t_max is not None else math.inf))
    t = t[inside]
    c, _ = _parallel(d, rows[inside], np.full(t.size, 2.0 * math.pi * freq))
    try:
        fit = fit_stretched_exponential(t, 1.0 / c**2)
    except ValueError as exc:
        return _all(out, names, "failed", f"{exc} (run {d.run_id})", excluded)
    if fit["y0"] <= 0 or fit["y_inf"] <= 0:
        return _all(out, names, "failed", "the 1/C^2 relaxation has no positive end values (not a C-t recovery)",
                    excluded)
    tau = fit["tau"]
    warnings = [f"the record covers {float(t.max()) / tau:.1f} tau; c_final is an extrapolation"] \
        if float(t.max()) < CT_MIN_TAUS * tau else []
    info = {"freq_hz": freq, "dc_v": float(np.median(rows[DC_V].to_numpy(dtype=float))), "r2": fit["r2"],
            "tau_se": fit.get("tau_se", math.nan), "beta_se": fit.get("beta_se", math.nan)}
    common: dict[str, object] = {"excluded": excluded, "points_used": int(t.size), "window": window_of(t, "s"),
                                 "fit": info, "warnings": warnings}
    return [out.ok("tau_recovery", tau, "s", **common), out.ok("beta", fit["beta"], "1", **common),  # type: ignore[arg-type]
            out.ok("c_initial", fit["y0"] ** -0.5, "F", **common),  # type: ignore[arg-type]
            out.ok("c_final", fit["y_inf"] ** -0.5, "F", **common)]  # type: ignore[arg-type]


# -- cv_ac_dependence ------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def cv_ac_dependence(d: RunData, *, freq_hz: float | None = None, tolerance: float = Field(default=0.01, gt=0.0,
                                                                                          lt=0.5),
                     segment: Segment = "fwd", force: bool = False,
                     criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Capacitance against the oscillator level (module docstring): ``c_small_signal`` (F), ``ac_limit`` (V rms) and
    ``max_rel_change`` (1)."""
    names: list[tuple[str, Unit]] = [("c_small_signal", "F"), ("ac_limit", "V"), ("max_rel_change", "1")]
    rows, freq = _rows_of(d, freq_hz, segment)
    out, ok, excluded, problems = _start("cv_ac_dependence", d, AC_VRMS, rows, criteria, force, freq_hz=freq,
                                         tolerance=tolerance, segment=segment)
    if problems:
        return _all(out, names, "refused", problems, excluded)
    vac = rows[AC_VRMS].to_numpy(dtype=float)[ok]
    if np.unique(vac).size < MIN_LEVELS:
        return _all(out, names, "failed", f"needs at least {MIN_LEVELS} oscillator levels (an AC level sweep, "
                    "moscap.cv_ac_level)", excluded)
    c, _ = _parallel(d, rows[ok], np.full(vac.size, 2.0 * math.pi * freq))
    k, c0 = (float(v) for v in np.polyfit(vac**2, c, 1))
    residual = c - (c0 + k * vac**2)
    spread = float(np.sum((c - c.mean()) ** 2))
    r2 = 1.0 - float(residual @ residual) / spread if spread > 0 else 1.0
    info = {"freq_hz": freq, "dc_v": float(np.median(rows[DC_V].to_numpy(dtype=float)[ok])), "c_per_v2": k,
            "d2c_dv2": 4.0 * k, "r2": r2}
    common: dict[str, object] = {"excluded": excluded, "points_used": int(vac.size), "window": window_of(vac, "V"),
                                 "fit": info}
    top = float(vac.max())
    limit = math.sqrt(tolerance * abs(c0) / abs(k)) if k != 0 else math.inf
    warnings: list[str] = []
    bound: Literal["exact", "lower"] = "exact"
    if limit > top:
        limit, bound = top, "lower"
        warnings.append(f"C stays within {tolerance:.3g} of C0 up to the largest level measured ({top:g} V rms)")
    return [out.ok("c_small_signal", c0, "F", **common),  # type: ignore[arg-type]
            out.ok("ac_limit", limit, "V", bound=bound, warnings=warnings, **common),  # type: ignore[arg-type]
            out.ok("max_rel_change", float(np.max(np.abs(c / c0 - 1.0))), "1", **common)]  # type: ignore[arg-type]


# -- cv_butterfly ----------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def cv_butterfly(d: RunData, *, freq_hz: float | None = None, force: bool = False,
                 criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """C-V butterfly of a ferroelectric capacitor (module docstring): ``vc``, ``v_imprint``, ``v_peak_up``,
    ``v_peak_down`` (V), ``c_peak`` (F) and ``ec`` (MV/cm, with ``geometry.tox_nm`` as the film thickness)."""
    names: list[tuple[str, Unit]] = [("vc", "V"), ("v_imprint", "V"), ("v_peak_up", "V"), ("v_peak_down", "V"),
                                     ("c_peak", "F"), ("ec", "MV/cm")]
    rows, freq = _rows_of(d, freq_hz, None)
    out, ok, excluded, problems = _start("cv_butterfly", d, DC_V, rows, criteria, force, freq_hz=freq)
    if problems:
        return _all(out, names, "refused", problems, excluded)
    if not d.has_segments:
        return _all(out, names, "failed", f"run {d.run_id} is a single sweep; the butterfly needs sweep_mode "
                    "double (one rising and one falling branch)", excluded)
    peaks: dict[str, tuple[float, float]] = {}
    for segment in ("fwd", "rev"):
        part = ok & (rows[SEGMENT] == segment).to_numpy()
        v = rows[DC_V].to_numpy(dtype=float)[part]
        if v.size < 2 * PEAK_HALF_WIDTH + 1:
            return _all(out, names, "failed", f"the {segment} branch has fewer than {2 * PEAK_HALF_WIDTH + 1} "
                        "trusted points", excluded)
        c, _ = _parallel(d, rows[part], np.full(v.size, 2.0 * math.pi * freq))
        i = peak_index(c)
        if i < PEAK_HALF_WIDTH or i > v.size - 1 - PEAK_HALF_WIDTH:
            return _all(out, names, "failed", f"the {segment} branch peaks at its end ({v[i]:g} V): sweep beyond the "
                        "coercive voltage on both sides", excluded)
        direction = "up" if v[-1] > v[0] else "down"
        if direction in peaks:
            return _all(out, names, "failed", "both branches run in the same direction; a double sweep rises and "
                        "falls", excluded)
        peaks[direction] = (_vertex(v, c, i), float(c[i]))
    up, down = peaks["up"][0], peaks["down"][0]
    vc = 0.5 * (up - down)
    info = {"freq_hz": freq, "c_peak_up": peaks["up"][1], "c_peak_down": peaks["down"][1]}
    v_all = rows[DC_V].to_numpy(dtype=float)[ok]
    common: dict[str, object] = {"excluded": excluded, "points_used": int(v_all.size),
                                 "window": window_of(v_all, "V"), "fit": info}
    results = [out.ok("vc", vc, "V", **common), out.ok("v_imprint", 0.5 * (up + down), "V", **common),  # type: ignore[arg-type]
               out.ok("v_peak_up", up, "V", **common), out.ok("v_peak_down", down, "V", **common),  # type: ignore[arg-type]
               out.ok("c_peak", max(peaks["up"][1], peaks["down"][1]), "F", **common)]  # type: ignore[arg-type]
    geometry = d.manifest.dut_geometry
    if geometry is None or geometry.tox_nm is None:
        results.append(out.not_ok("ec", "MV/cm", "refused", _geometry_missing(d, "geometry.tox_nm (the film "
                                                                                  "thickness)"), excluded=excluded))
    else:
        results.append(out.ok("ec", vc / (geometry.tox_nm * 1e-7) * 1e-6, "MV/cm",
                              **{**common, "fit": {**info, "thickness_nm": geometry.tox_nm}}))  # type: ignore[arg-type]
    return results


# -- cv_pulsed_vs_dc (two-run) ---------------------------------------------------------------------------------------


def _mid_crossing(v: np.ndarray, c: np.ndarray) -> float | None:
    level = 0.5 * (float(c.max()) + float(c.min()))
    for i in range(v.size - 1):
        a, b = c[i] - level, c[i + 1] - level
        if a == 0:
            return float(v[i])
        if a * b < 0:
            return float(v[i] + (v[i + 1] - v[i]) * a / (a - b))
    return None


@validate_call(config=_CALL_CONFIG)
def cv_pulsed_vs_dc(d: RunData, *, reference: RunData, freq_hz: float | None = None,
                    acc_frac: float = Field(default=ACC_FRAC, gt=0.5, lt=1.0), force: bool = False,
                    criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Pulsed against DC C-V (module docstring): ``delta_vfb`` (V), ``cox_ratio`` and ``c_ratio_inversion`` (1)."""
    names: list[tuple[str, Unit]] = [("delta_vfb", "V"), ("cox_ratio", "1"), ("c_ratio_inversion", "1")]
    for run in (d, reference):
        if len(pd.unique(run.table[DC_V])) < 2 * 3:
            raise InvalidInputError(f"cv_pulsed_vs_dc compares two C-V (DC bias) sweeps; run {run.run_id} "
                                    f"({run.manifest.recipe_id}) is not one")
    policy = trust_policy(criteria)
    freq = frequencies(d)[0] if freq_hz is None else freq_hz
    pulsed = load_curve(d, policy, freq_hz=freq, segment="fwd" if d.has_segments else None, rs_ohm=0.0)
    dc = load_curve(reference, policy, freq_hz=freq, segment="fwd" if reference.has_segments else None, rs_ohm=0.0)
    out = Results("cv_pulsed_vs_dc", {"reference_run": reference.run_id, "freq_hz": freq, "acc_frac": acc_frac,
                                      "force": force, "trust_policy": policy_params(policy)})
    excluded = excluded_counts(pd.concat([pulsed.rows.reasons, dc.rows.reasons]))
    problems = pulsed.problems + [f"reference {p}" for p in dc.problems]
    if problems and not force:
        return _all(out, names, "refused", problems, excluded)
    out.flag(problems)
    area, _ = area_cm2(d, split=False)
    try:
        fit_p = moscap_fit(pulsed.v, pulsed.c, area_cm2=area, acc_frac=acc_frac)
        fit_r = moscap_fit(dc.v, dc.c, area_cm2=area, acc_frac=acc_frac)
    except FitError as exc:
        return _all(out, names, "failed", str(exc), excluded)
    warnings: list[str] = []
    if fit_p.vfb is not None and fit_r.vfb is not None:
        delta = fit_p.vfb - fit_r.vfb
    else:
        a, b = _mid_crossing(pulsed.v, pulsed.c), _mid_crossing(dc.v, dc.c)
        if a is None or b is None:
            return _all(out, names, "failed", "a curve never crosses its mid level (Cmax + Cmin)/2", excluded)
        delta = a - b
        warnings.append("delta_vfb from the mid-level crossings: no geometry.area_um2 for the flatband capacitance")
    low, high = max(pulsed.v.min(), dc.v.min()), min(pulsed.v.max(), dc.v.max())
    if not low < high:
        return _all(out, names, "failed", "the two sweeps share no bias range", excluded)
    v_inv = high if fit_p.s > 0 else low
    ratio = float(np.interp(v_inv, pulsed.v, pulsed.c)) / float(np.interp(v_inv, dc.v, dc.c))
    info = {"vfb_pulsed": fit_p.vfb if fit_p.vfb is not None else math.nan,
            "vfb_dc": fit_r.vfb if fit_r.vfb is not None else math.nan, "cox_pulsed_f": fit_p.cox,
            "cox_dc_f": fit_r.cox, "v_inversion": v_inv, "freq_hz": freq}
    common: dict[str, object] = {"excluded": excluded, "points_used": int(pulsed.v.size + dc.v.size),
                                 "window": window_of(np.array([low, high]), "V"), "fit": info}
    return [out.ok("delta_vfb", delta, "V", warnings=warnings, **common),  # type: ignore[arg-type]
            out.ok("cox_ratio", fit_p.cox / fit_r.cox, "1", **common),  # type: ignore[arg-type]
            out.ok("c_ratio_inversion", ratio, "1", **common)]  # type: ignore[arg-type]


__all__ = [
    "cf_dispersion",
    "ct_recovery",
    "cv_ac_dependence",
    "cv_butterfly",
    "cv_pulsed_vs_dc",
    "fit_trap_response",
    "gp_over_omega",
    "trap_shape",
]
