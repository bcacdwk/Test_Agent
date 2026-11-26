"""Interface-trap density over the band gap (blueprint v2 2.10 ``cv.py`` row: ``dit_high_low``, ``dit_conductance``;
WP8.5; a module of its own because ``cv.py`` is near the file-size limit). Both reuse ``cv.py``'s curve loading and
the MOS-C fit ``moscap_fit`` (Cox, Vfb, Nsub, phi_B of a high-frequency C-V) and ``cv_variants.py``'s conductance
pieces. The definitions are the source of knowledge file ``08-capacitance-cv.md`` (skill ``b1500-test``); change both
together. Energies ``e`` are ``E_F - E_i`` at the surface in the p-substrate frame (mirrored for an n substrate:
there ``e > 0`` is towards the valence band), the frame of the simulator's truth.

**dit_high_low** (two-run, Castagne & Vapaille 1971; Nicollian & Brews, *MOS Physics and Technology*, 1982, ch. 8;
not page-checked). A quasi-static C-V (QSCV, ``moscap.qscv``: interface traps follow) and a high-frequency C-V
(``moscap.cv``: they do not) of the same device, one the analysed run, the other ``options.reference_run`` (either
order). The HF curve's fit gives ``Cox`` (accumulation extrapolation; option ``cox_f`` overrides it), ``Vfb``, ``Nsub``
and ``phi_B``; at every QSCV bias inside the common range, with the HF capacitance interpolated there,
``Dit = [C_LF Cox / (Cox - C_LF) - C_HF Cox / (Cox - C_HF)] / (q A)`` (the semiconductor capacitance cancels; ``A`` from
``geometry.area_um2``), and the band bending comes from the LF curve (Berglund integral) ``psi = s int_Vfb^V (1 -
C_LF/Cox) dV``, ``e = psi - phi_B``. Valid where both curves are in depletion: ``psi_min`` (default 6 kT/q: closer to
flatband the fast traps already respond at the HF frequency) to ``2 phi_B - psi_margin`` (default 4 kT/q: beyond it the
minority carriers add to the LF curve). Results: ``dit_mid`` (at ``e = 0``, interpolated; failed when midgap lies
outside the window), ``dit_mean``, ``dit_min``, ``dit_max`` (cm^-2 eV^-1); ``fit`` holds the profile every
``e_step`` eV (``e<k>``, ``dit<k>``), the window and the HF fit.

**dit_conductance** (Nicollian & Goetzberger 1967; Nicollian & Brews ch. 5; not page-checked). A C-V at many frequencies
(``moscap.cv_multi_freq``): at every bias the parallel ``Cm``, ``Gm`` over the frequencies (series ``rs_ohm`` removed)
give ``Gp/w = w Cox^2 Gm / (Gm^2 + w^2 (Cox - Cm)^2)`` (``gp_over_omega``); the continuum model ``Gp/w = q A Dit ln(1 +
(w tau)^2) / (2 w tau)`` (or ``model: single``) is fitted (``fit_trap_response``) for ``Dit`` and ``tau``. A bias counts
when its fitted peak lies inside the measured frequencies, the highest-frequency capacitance is below Cox and the fit
explains the data (``r2 >= min_r2``). ``Cox``, ``Nsub``, ``phi_B`` come from the fit of the highest-frequency curve
(``cox_f`` overrides Cox); the band bending from that HF capacitance in the depletion approximation, ``W = eps_s A (1/C
- 1/Cox)``, ``psi = q N W^2 / (2 eps_s) + kT/q``. Results: ``dit_mean``, ``dit_min``, ``dit_max`` (cm^-2 eV^-1) over
the counted biases, ``tau_min``/``tau_max`` (s); ``fit`` holds per bias ``v<k>``, ``e<k>``, ``dit<k>``, ``tau<k>``. At
room temperature the 1 kHz..5 MHz band reaches only the traps about 0.15 to 0.37 eV from midgap on the majority side
(textbook estimate for an assumed capture cross-section of 1e-16 cm^2, v_th 1e7 cm/s and ni 1e10 cm^-3, as knowledge
``08``; each decade of the cross-section shifts the window by about 0.06 eV, and the trap time constant grows by e per
kT/q towards midgap); the high-low method covers midgap.

Trust: untrusted points refuse the extraction unless ``force`` (flagged), as in ``cv.py``. Geometry: both methods need
``geometry.area_um2`` (refused naming the field).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, excluded_counts, policy_params, trust_policy, window_of
from b1500_test_agent.analysis.cv import (
    ACC_FRAC,
    DEFAULT_NI_CM3,
    DEFAULT_T_K,
    EPS0_F_CM,
    EPS_SI,
    K_B,
    Q_E,
    FitError,
    MoscapFit,
    area_cm2,
    frequencies,
    load_curve,
    moscap_fit,
    pair_of,
    remove_series_r,
    to_admittance,
)
from b1500_test_agent.analysis.cv_variants import (
    CONTINUUM_PEAK_WT,
    TrapModel,
    fit_trap_response,
    gp_over_omega,
)
from b1500_test_agent.analysis.dataset import DC_V, FREQ_HZ, RunData, Segment
from b1500_test_agent.analysis.qscv import qscv_curve, quasi_static_role
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

DIT_UNIT: Unit = "cm^-2 eV^-1"
MIN_PROFILE_POINTS = 3
MIN_CONDUCTANCE_FREQS = 4
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


def _thermal_v(temperature_k: float) -> float:
    return K_B * temperature_k / Q_E


def _all(out: Results, names: Sequence[tuple[str, Unit]], outcome: str, why: str | list[str],
         excluded: dict[str, int], fit: dict[str, float] | None = None) -> list[ExtractionResult]:
    if outcome == "refused":
        problems = why if isinstance(why, list) else [why]
        return [out.refused(n, u, problems, excluded=excluded, fit=fit) for n, u in names]
    return [out.failed(n, u, str(why), excluded=excluded, fit=fit) for n, u in names]


def _hf_fit(v: np.ndarray, c: np.ndarray, area: float, *, ni_cm3: float, temperature_k: float,
            cox_f: float | None) -> MoscapFit:
    fit = moscap_fit(v, c, area_cm2=area, acc_frac=ACC_FRAC, ni_cm3=ni_cm3, temperature_k=temperature_k)
    if cox_f is not None:
        fit.cox = cox_f
    if fit.vfb is None or fit.nsub is None or fit.phi_b is None:
        raise FitError("the high-frequency fit gave no flatband voltage or doping")
    return fit


def _summary(out: Results, values: np.ndarray, x: np.ndarray, fit: dict[str, float], excluded: dict[str, int],
             warnings: list[str]) -> list[ExtractionResult]:
    common = {"excluded": excluded, "points_used": int(values.size), "window": window_of(x, "V"), "fit": fit,
              "warnings": warnings}
    return [out.ok("dit_mean", float(np.mean(values)), DIT_UNIT, **common),  # type: ignore[arg-type]
            out.ok("dit_min", float(np.min(values)), DIT_UNIT, **common),  # type: ignore[arg-type]
            out.ok("dit_max", float(np.max(values)), DIT_UNIT, **common)]  # type: ignore[arg-type]


# -- high-low --------------------------------------------------------------------------------------------------------


def high_low_profile(v_lf: np.ndarray, c_lf: np.ndarray, v_hf: np.ndarray, c_hf: np.ndarray, *, cox: float,
                     vfb: float, phi_b: float, s: float, area_cm2: float) -> pd.DataFrame:
    """The high-low profile at the LF biases inside the HF range (module docstring): columns ``v``, ``psi`` (V),
    ``e`` (eV), ``c_lf``, ``c_hf`` (F) and ``dit`` (cm^-2 eV^-1); ``v`` ascending (both inputs sorted by bias). For
    ad-hoc scripts too (results to ``work/<run_id>/``)."""
    inside = (v_lf >= v_hf.min()) & (v_lf <= v_hf.max())
    v, c = v_lf[inside], c_lf[inside]
    hf = np.interp(v, v_hf, c_hf)
    cit = c * cox / (cox - c) - hf * cox / (cox - hf)
    integral = np.concatenate([[0.0], np.cumsum(0.5 * ((1 - c[1:] / cox) + (1 - c[:-1] / cox)) * np.diff(v))])
    psi = s * (integral - float(np.interp(vfb, v, integral)))
    return pd.DataFrame({"v": v, "psi": psi, "e": psi - phi_b, "c_lf": c, "c_hf": hf, "dit": cit / (Q_E * area_cm2)})


def _profile_samples(e: np.ndarray, dit: np.ndarray, step: float) -> dict[str, float]:
    order = np.argsort(e)
    e, dit = e[order], dit[order]
    grid = np.arange(math.ceil(e[0] / step) * step, e[-1] + 1e-12, step)
    out: dict[str, float] = {}
    for k, energy in enumerate(grid):
        out[f"e{k}"] = round(float(energy), 6)
        out[f"dit{k}"] = float(np.interp(energy, e, dit))
    return out


@validate_call(config=_CALL_CONFIG)
def dit_high_low(d: RunData, *, reference: RunData, freq_hz: float | None = None, segment: Segment = "fwd",
                 cox_f: float | None = Field(default=None, gt=0), psi_min: float | None = Field(default=None, gt=0),
                 psi_margin: float | None = Field(default=None, ge=0), e_step: float = Field(default=0.05, gt=0),
                 ni_cm3: float = Field(default=DEFAULT_NI_CM3, gt=0),
                 temperature_k: float = Field(default=DEFAULT_T_K, gt=0, le=600), force: bool = False,
                 criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Dit over the band gap from a QSCV and an HF C-V of one device (module docstring): ``dit_mid``, ``dit_mean``,
    ``dit_min``, ``dit_max`` (cm^-2 eV^-1)."""
    names: list[tuple[str, Unit]] = [("dit_mid", DIT_UNIT), ("dit_mean", DIT_UNIT), ("dit_min", DIT_UNIT),
                                     ("dit_max", DIT_UNIT)]
    lf_run, hf_run = (d, reference) if quasi_static_role(d) is not None else (reference, d)
    if quasi_static_role(lf_run) is None or quasi_static_role(hf_run) is not None:
        raise InvalidInputError("dit_high_low needs one quasi-static C-V run (moscap.qscv) and one high-frequency C-V "
                                f"run (moscap.cv) of the same device; got {d.run_id} ({d.manifest.recipe_id}) and "
                                f"{reference.run_id} ({reference.manifest.recipe_id})")
    if len(pd.unique(hf_run.table[DC_V])) < 6:
        raise InvalidInputError(f"run {hf_run.run_id} ({hf_run.manifest.recipe_id}) is not a C-V (DC bias) sweep")
    policy = trust_policy(criteria)
    ut = _thermal_v(temperature_k)
    lo = psi_min if psi_min is not None else 6.0 * ut
    margin = psi_margin if psi_margin is not None else 4.0 * ut
    freq = frequencies(hf_run)[0] if freq_hz is None else freq_hz
    out = Results("dit_high_low", {"reference_run": reference.run_id, "lf_run": lf_run.run_id,
                                   "hf_run": hf_run.run_id, "freq_hz": freq, "segment": segment, "cox_f": cox_f,
                                   "psi_min": lo, "psi_margin": margin, "e_step": e_step, "ni_cm3": ni_cm3,
                                   "temperature_k": temperature_k, "force": force,
                                   "trust_policy": policy_params(policy)})
    lf_rows, v_lf, c_lf, lf_problems = qscv_curve(lf_run, policy, segment=segment)
    hf = load_curve(hf_run, policy, freq_hz=freq, segment=segment if hf_run.has_segments else None, rs_ohm=0.0)
    excluded = excluded_counts(pd.concat([lf_rows.reasons, hf.rows.reasons]))
    problems = lf_problems + [f"HF {p}" for p in hf.problems]
    if problems and not force:
        return _all(out, names, "refused", problems, excluded)
    out.flag(problems)
    area, missing = area_cm2(lf_run, split=False)
    if area is None:
        return [out.not_ok(n, u, "refused", f"Refused: {missing}.", excluded=excluded) for n, u in names]
    try:
        fit = _hf_fit(hf.v, hf.c, area, ni_cm3=ni_cm3, temperature_k=temperature_k, cox_f=cox_f)
    except FitError as exc:
        return _all(out, names, "failed", f"high-frequency C-V fit: {exc}", excluded)
    assert fit.vfb is not None and fit.phi_b is not None and fit.nsub is not None
    if not v_lf.min() <= fit.vfb <= v_lf.max():
        return _all(out, names, "failed", f"the QSCV sweep ({v_lf.min():g}..{v_lf.max():g} V) does not reach the "
                    f"flatband voltage {fit.vfb:.4g} V of the HF fit (the band bending integral starts there)",
                    excluded)
    profile = high_low_profile(v_lf, c_lf, hf.v, hf.c, cox=fit.cox, vfb=fit.vfb, phi_b=fit.phi_b, s=fit.s,
                               area_cm2=area)
    hi = 2.0 * fit.phi_b - margin
    window = profile[(profile["psi"] >= lo) & (profile["psi"] <= hi) & (profile["c_lf"] < fit.cox)
                     & (profile["c_hf"] < fit.cox)]
    info: dict[str, float] = {"cox_f": fit.cox, "vfb": fit.vfb, "nsub": fit.nsub, "phi_b": fit.phi_b,
                              "substrate_p": fit.s, "psi_min": lo, "psi_max": hi, "area_cm2": area, "hf_freq_hz": freq}
    if len(window) < MIN_PROFILE_POINTS:
        return _all(out, names, "failed", f"fewer than {MIN_PROFILE_POINTS} QSCV points with band bending {lo:.3g}.."
                    f"{hi:.3g} V (depletion); use a finer QSCV step or sweep through depletion", excluded, info)
    e = window["e"].to_numpy()
    dit = window["dit"].to_numpy()
    info |= {"e_min": float(e.min()), "e_max": float(e.max()), **_profile_samples(e, dit, e_step)}
    warnings = ["Cox from options.cox_f"] if cox_f is not None else []
    if np.any(dit <= 0):
        warnings.append("negative Dit at some energies: noise or the two curves are not of one device/state")
    v = window["v"].to_numpy()
    results = _summary(out, dit, v, info, excluded, warnings)
    if not e.min() <= 0.0 <= e.max():
        mid = out.failed("dit_mid", DIT_UNIT, f"midgap (e = 0) lies outside the depletion window {e.min():.3g}.."
                         f"{e.max():.3g} eV", excluded=excluded, fit=info)
    else:
        order = np.argsort(e)
        mid = out.ok("dit_mid", float(np.interp(0.0, e[order], dit[order])), DIT_UNIT, excluded=excluded,
                     points_used=int(dit.size), window=window_of(v, "V"), fit=info, warnings=warnings)
    return [mid, *results]


# -- conductance -----------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def dit_conductance(d: RunData, *, cox_f: float | None = Field(default=None, gt=0),
                    rs_ohm: float = Field(default=0.0, ge=0.0), model: TrapModel = "continuum",
                    segment: Segment = "fwd", min_r2: float = Field(default=0.9, ge=0.0, le=1.0),
                    ni_cm3: float = Field(default=DEFAULT_NI_CM3, gt=0),
                    temperature_k: float = Field(default=DEFAULT_T_K, gt=0, le=600), force: bool = False,
                    criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Dit(E) by the conductance method over the biases of a multi-frequency C-V (module docstring): ``dit_mean``,
    ``dit_min``, ``dit_max`` (cm^-2 eV^-1), ``tau_min``, ``tau_max`` (s)."""
    names: list[tuple[str, Unit]] = [("dit_mean", DIT_UNIT), ("dit_min", DIT_UNIT), ("dit_max", DIT_UNIT),
                                     ("tau_min", "s"), ("tau_max", "s")]
    if quasi_static_role(d) is not None:
        raise InvalidInputError(f"run {d.run_id} is a quasi-static run; dit_conductance needs a C-V at several "
                                "frequencies (moscap.cv_multi_freq)")
    freqs = sorted(frequencies(d))
    if len(freqs) < MIN_CONDUCTANCE_FREQS or len(pd.unique(d.table[DC_V])) < 6:
        raise InvalidInputError(f"dit_conductance needs C-V sweeps at {MIN_CONDUCTANCE_FREQS} or more frequencies "
                                f"(moscap.cv_multi_freq); run {d.run_id} has {len(freqs)} frequencies")
    policy = trust_policy(criteria)
    out = Results("dit_conductance", {"cox_f": cox_f, "rs_ohm": rs_ohm, "model": model, "segment": segment,
                                      "min_r2": min_r2, "ni_cm3": ni_cm3, "temperature_k": temperature_k,
                                      "force": force, "trust_policy": policy_params(policy)})
    seg = segment if d.has_segments else None
    curves = [load_curve(d, policy, freq_hz=f, segment=seg, rs_ohm=rs_ohm) for f in freqs]
    excluded = excluded_counts(pd.concat([c.rows.reasons for c in curves]))
    problems = [p for c in curves for p in c.problems]
    if problems and not force:
        return _all(out, names, "refused", problems, excluded)
    out.flag(problems)
    area, missing = area_cm2(d, split=False)
    if area is None:
        return [out.not_ok(n, u, "refused", f"Refused: {missing}.", excluded=excluded) for n, u in names]
    top = curves[-1]
    try:
        fit = _hf_fit(top.v, top.c, area, ni_cm3=ni_cm3, temperature_k=temperature_k, cox_f=cox_f)
    except FitError as exc:
        return _all(out, names, "failed", f"fit of the {freqs[-1]:g} Hz curve: {exc}", excluded)
    assert fit.nsub is not None and fit.phi_b is not None
    eps_s = EPS_SI * EPS0_F_CM
    ut = _thermal_v(temperature_k)
    omega = 2.0 * math.pi * np.asarray(freqs)
    biases = sorted(set.intersection(*(set(np.round(c.v, 9)) for c in curves)))
    peak_wt = CONTINUUM_PEAK_WT if model == "continuum" else 1.0
    counted: list[tuple[float, float, float, float]] = []
    for bias in biases:
        cm = np.array([c.c[np.isclose(c.v, bias, atol=1e-9)][0] for c in curves])
        gm = np.array([c.g[np.isclose(c.v, bias, atol=1e-9)][0] for c in curves])
        c_hf = cm[-1]
        if not 0 < c_hf < fit.cox or np.any(cm >= fit.cox):
            continue
        gpw = gp_over_omega(cm, gm, omega, fit.cox)
        tau, k, r2 = fit_trap_response(omega, gpw, model)
        f_peak = peak_wt / (2.0 * math.pi * tau)
        if not freqs[0] <= f_peak <= freqs[-1] or r2 < min_r2 or k <= 0:
            continue
        width = eps_s * area * (1.0 / c_hf - 1.0 / fit.cox)
        psi = Q_E * fit.nsub * width**2 / (2.0 * eps_s) + ut
        counted.append((float(bias), psi - fit.phi_b, k / (Q_E * area), tau))
    info: dict[str, float] = {"cox_f": fit.cox, "nsub": fit.nsub, "phi_b": fit.phi_b, "area_cm2": area,
                              "f_min_hz": freqs[0], "f_max_hz": freqs[-1], "biases_tried": float(len(biases))}
    if len(counted) < 1:
        return _all(out, names, "failed", f"no bias has its Gp/w peak inside {freqs[0]:g}..{freqs[-1]:g} Hz with r2 >= "
                    f"{min_r2:g}; sweep through depletion (between Vfb and Vth) with a finer step", excluded, info)
    v = np.array([c[0] for c in counted])
    dit = np.array([c[2] for c in counted])
    taus = np.array([c[3] for c in counted])
    for k, (bias, energy, value, tau) in enumerate(counted):
        info |= {f"v{k}": bias, f"e{k}": energy, f"dit{k}": value, f"tau{k}": tau}
    info |= {"e_min": float(min(c[1] for c in counted)), "e_max": float(max(c[1] for c in counted))}
    warnings = ["Cox from options.cox_f"] if cox_f is not None else []
    common = {"excluded": excluded, "points_used": int(v.size), "window": window_of(v, "V"), "fit": info,
              "warnings": warnings}
    return [*_summary(out, dit, v, info, excluded, warnings),
            out.ok("tau_min", float(taus.min()), "s", **common),  # type: ignore[arg-type]
            out.ok("tau_max", float(taus.max()), "s", **common)]  # type: ignore[arg-type]


def admittance_at(d: RunData, freq_hz: float, rs_ohm: float = 0.0) -> pd.DataFrame:
    """The parallel ``C``/``G`` of every row of one frequency (series ``rs_ohm`` removed), with ``dc_v``: the
    per-frequency input of the conductance method, for ad-hoc scripts."""
    role, primary, secondary = pair_of(d)
    rows = d.table[np.isclose(d.table[FREQ_HZ].to_numpy(dtype=float), freq_hz)]
    omega = 2.0 * math.pi * freq_hz
    y = remove_series_r(to_admittance(primary, secondary, rows[f"{role}_{primary}"].to_numpy(dtype=float),
                                      rows[f"{role}_{secondary}"].to_numpy(dtype=float), np.full(len(rows), omega)),
                        rs_ohm)
    return pd.DataFrame({DC_V: rows[DC_V].to_numpy(dtype=float), "c": y.imag / omega, "g": y.real})


__all__ = ["admittance_at", "dit_conductance", "dit_high_low", "high_low_profile"]
