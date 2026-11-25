"""Analyses of the C-V variants (``analysis/cv_variants.py``; WP8.4) against analytic data with known truth:
``cf_dispersion`` on the continuum (and single-level) trap admittance behind an oxide capacitance, ``ct_recovery`` on
an exponential 1/C^2 relaxation, ``cv_ac_dependence`` on the describing function of a curved C-V, ``cv_butterfly`` on
sech^2 peaks, ``cv_pulsed_vs_dc`` on MOS-C curves of the simulator's model; plus the refusals (missing geometry,
untrusted points and ``force``, a peak outside the frequencies, a single sweep) and the registry entries."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import ANALYSIS_METHODS, RunData, run_method, with_trust
from b1500_test_agent.analysis.cv_variants import (
    CONTINUUM_PEAK,
    CONTINUUM_PEAK_WT,
    cf_dispersion,
    ct_recovery,
    cv_ac_dependence,
    cv_butterfly,
    cv_pulsed_vs_dc,
    fit_trap_response,
    gp_over_omega,
    trap_shape,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.policy import DutGeometry
from b1500_test_agent.models.recipe import QualityCriteria
from b1500_test_agent.models.sim import MoscapParams
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from tests.unit.analysis_helpers import manifest

pytestmark = pytest.mark.cmu

CRITERIA = QualityCriteria(limited=[], untrusted=["U", "D", "V", "X", "C", "T", "F", "G", "S"])
GEOMETRY = DutGeometry(area_um2=1.0e4, tox_nm=5.0)
Q = 1.602176634e-19
AREA_CM2 = 1e-4
COX = 3.9 * 8.8541878128e-14 * AREA_CM2 / 5e-7  # 69.06 pF: eps_ox eps0 A / tox


def table_of(columns: dict[str, Any], c: np.ndarray, g: np.ndarray, *, role: str = "gate",
             status: list[str] | None = None) -> pd.DataFrame:
    n = len(c)
    table = pd.DataFrame({"step": range(n), **{k: v for k, v in columns.items()}})
    table[f"{role}_Cp"] = c
    table[f"{role}_Cp_status"] = status or ["N"] * n
    table[f"{role}_G"] = g
    table[f"{role}_G_status"] = "N"
    return table


def run_data(table: pd.DataFrame, recipe_id: str, geometry: DutGeometry | None = GEOMETRY,
             run_id: str = "S20261124T000000Z-aaaa") -> RunData:
    params = {"freqs_hz": Quantity(value=sorted(set(table["freq_hz"])), unit="Hz")}
    m = manifest(run_id, recipe_id=recipe_id, kind="cmu_measure", params=params)
    return RunData(manifest=m.model_copy(update={"dut_geometry": geometry}), table=with_trust(table, CRITERIA))


def one(results: list[Any], quantity: str) -> Any:
    found = [r for r in results if r.quantity == quantity]
    assert len(found) == 1, results
    return found[0]


# -- cf_dispersion ---------------------------------------------------------------------------------------------------


def cf_run(dit: float = 2.5e11, tau: float = 8e-6, *, cd: float = 1.2e-11, model: str = "continuum",
           rs: float = 0.0, geometry: DutGeometry | None = GEOMETRY, status: list[str] | None = None) -> RunData:
    """C-f data of Cox in series with (Cd || trap admittance) at 4 points per decade, 1 kHz..1 MHz."""
    f = 1e3 * 10 ** (np.arange(13) / 4)
    w = 2 * math.pi * f
    wt = w * tau
    k = Q * AREA_CM2 * dit
    gp = w * k * trap_shape(wt, model)  # type: ignore[arg-type]
    cit = k * np.arctan(wt) / wt if model == "continuum" else k / (1 + wt * wt)
    y_s = gp + 1j * w * (cd + cit)
    y = 1 / (1 / (1j * w * COX) + 1 / y_s)
    y = 1 / (1 / y + rs)
    return run_data(table_of({"freq_hz": f, "ac_vrms": 0.03, "dc_v": -0.6}, y.imag / w, y.real, status=status),
                    "moscap.cf", geometry)


def test_conductance_and_the_continuum_peak_constants() -> None:
    x = np.linspace(0.1, 10, 20001)
    shape = trap_shape(x, "continuum")
    assert x[int(np.argmax(shape))] == pytest.approx(CONTINUUM_PEAK_WT, abs=1e-3)
    assert float(shape.max()) == pytest.approx(CONTINUUM_PEAK, abs=1e-5)
    single = trap_shape(x, "single")
    assert x[int(np.argmax(single))] == pytest.approx(1.0, abs=1e-3) and float(single.max()) == pytest.approx(0.5)
    omega = 2 * math.pi * np.geomspace(1e3, 1e6, 7)
    gm = np.full(7, 1e-7)
    cm = np.full(7, 20e-12)
    # Nicollian-Goetzberger inverted by hand for one point
    expected = omega * COX**2 * gm / (gm**2 + omega**2 * (COX - cm) ** 2)
    assert np.allclose(gp_over_omega(cm, gm, omega, COX), expected)


@pytest.mark.parametrize("model", ["continuum", "single"])
def test_cf_dispersion_recovers_dit_and_tau_exactly(model: str) -> None:
    results = cf_dispersion(cf_run(model=model), model=model, criteria=CRITERIA)  # type: ignore[arg-type]
    assert one(results, "dit").value == pytest.approx(2.5e11, rel=1e-3)
    assert one(results, "tau_it").value == pytest.approx(8e-6, rel=1e-3)
    peak = CONTINUUM_PEAK_WT if model == "continuum" else 1.0
    assert one(results, "f_peak").value == pytest.approx(peak / (2 * math.pi * 8e-6), rel=1e-3)
    assert one(results, "c_dispersion").value > 0.05 and one(results, "dit").window.unit == "Hz"
    assert any("geometry" in w for w in one(results, "dit").warnings)  # the Cox estimate is named


def test_cf_dispersion_options_and_refusals() -> None:
    with_rs = cf_run(rs=50.0)
    plain = one(cf_dispersion(with_rs, criteria=CRITERIA), "dit").value
    corrected = one(cf_dispersion(with_rs, rs_ohm=50.0, cox_f=COX, criteria=CRITERIA), "dit")
    assert corrected.value == pytest.approx(2.5e11, rel=1e-3) and abs(plain - 2.5e11) > abs(corrected.value - 2.5e11)
    assert not corrected.warnings  # Cox given: no geometry estimate
    bare = cf_dispersion(cf_run(geometry=None), criteria=CRITERIA)
    assert one(bare, "dit").outcome == "refused" and "geometry.area_um2 and geometry.tox_nm" in one(bare, "dit").error
    assert one(bare, "c_dispersion").outcome == "ok"
    area_only = cf_dispersion(cf_run(geometry=None), cox_f=COX, criteria=CRITERIA)
    assert one(area_only, "dit").outcome == "refused" and one(area_only, "tau_it").outcome == "ok"
    outside = cf_dispersion(cf_run(tau=1e-2), criteria=CRITERIA)  # peak near 30 Hz
    assert one(outside, "dit").outcome == "failed" and "lies outside the measured" in one(outside, "dit").error
    bad = ["N"] * 13
    bad[4] = "U"
    refused = cf_dispersion(cf_run(status=bad), criteria=CRITERIA)
    assert all(r.outcome == "refused" for r in refused)
    forced = cf_dispersion(cf_run(status=bad), force=True, criteria=CRITERIA)
    assert one(forced, "dit").outcome == "ok" and one(forced, "dit").forced_on_untrusted


def test_fit_trap_response_handles_noise() -> None:
    rng = np.random.default_rng(3)
    omega = 2 * math.pi * np.geomspace(1e3, 1e6, 13)
    gpw = 1e-12 * trap_shape(omega * 2e-5, "continuum") * (1 + rng.normal(0, 0.02, 13))
    tau, k, r2 = fit_trap_response(omega, gpw, "continuum")
    assert tau == pytest.approx(2e-5, rel=0.05) and k == pytest.approx(1e-12, rel=0.05) and r2 > 0.99


# -- ct_recovery -----------------------------------------------------------------------------------------------------


def ct_run(tau: float = 0.5, beta: float = 1.0, *, c0: float = 5.4e-12, c_inf: float = 8.0e-12,
           points: int = 301, interval: float = 0.02) -> RunData:
    t = np.arange(points) * interval
    y = c_inf**-2 + (c0**-2 - c_inf**-2) * np.exp(-((t / tau) ** beta))
    c = y**-0.5
    return run_data(table_of({"t_s": t, "freq_hz": 1e6, "ac_vrms": 0.03, "dc_v": 2.0}, c, np.full(points, 1e-9)),
                    "moscap.ct")


def test_ct_recovery_recovers_tau_and_the_end_capacitances() -> None:
    results = ct_recovery(ct_run(), criteria=CRITERIA)
    assert one(results, "tau_recovery").value == pytest.approx(0.5, rel=1e-3)
    assert one(results, "beta").value == pytest.approx(1.0, abs=1e-3)
    assert one(results, "c_initial").value == pytest.approx(5.4e-12, rel=1e-3)
    assert one(results, "c_final").value == pytest.approx(8.0e-12, rel=1e-3)
    stretched = ct_recovery(ct_run(beta=0.7), criteria=CRITERIA)
    assert one(stretched, "beta").value == pytest.approx(0.7, abs=0.01)
    short = ct_recovery(ct_run(points=40), criteria=CRITERIA)  # 0.78 s of a 0.5 s recovery
    assert any("extrapolation" in w for w in one(short, "c_final").warnings)
    windowed = ct_recovery(ct_run(), t_min=0.1, t_max=3.0, criteria=CRITERIA)
    assert one(windowed, "tau_recovery").window.low >= 0.1


def test_ct_recovery_needs_a_time_axis() -> None:
    with pytest.raises(InvalidInputError, match="t_s"):
        ct_recovery(cf_run(), criteria=CRITERIA)


# -- cv_ac_dependence ------------------------------------------------------------------------------------------------


def test_ac_dependence_fits_c0_and_the_curvature() -> None:
    vac = np.linspace(0.01, 0.1, 10)
    c0, d2c = 18e-12, 2e-10
    c = c0 + d2c * vac**2 / 4
    results = cv_ac_dependence(run_data(table_of({"freq_hz": 1e6, "ac_vrms": vac, "dc_v": -0.6}, c, 1e-9 + 0 * c),
                                        "moscap.cv_ac_level"), criteria=CRITERIA)
    assert one(results, "c_small_signal").value == pytest.approx(c0, rel=1e-6)
    assert one(results, "c_small_signal").fit["d2c_dv2"] == pytest.approx(d2c, rel=1e-6)
    limit = one(results, "ac_limit")
    assert limit.value == pytest.approx(math.sqrt(0.01 * 4 * c0 / d2c), rel=1e-6) and limit.bound == "exact"
    assert one(results, "max_rel_change").value == pytest.approx(d2c * 0.01 / 4 / c0, rel=1e-6)
    flat = cv_ac_dependence(run_data(table_of({"freq_hz": 1e6, "ac_vrms": vac, "dc_v": -2.0}, c0 + 1e-17 * vac,
                                              1e-9 + 0 * c), "moscap.cv_ac_level"), criteria=CRITERIA)
    assert one(flat, "ac_limit").bound == "lower" and one(flat, "ac_limit").value == pytest.approx(0.1)


# -- cv_butterfly ----------------------------------------------------------------------------------------------------


def butterfly_run(vc: float = 1.0, shift: float = 0.0, *, start: float = -3.0, stop: float = 3.0,
                  points: int = 121, double: bool = True, geometry: DutGeometry | None = None) -> RunData:
    up = np.linspace(start, stop, points)
    v = np.concatenate([up, up[::-1]]) if double else up
    rising = np.concatenate([np.full(points, start < stop), np.full(points, start > stop)]) if double else \
        np.full(points, start < stop)
    centre = np.where(rising, vc + shift, -vc + shift)
    c = 66e-12 + 34e-12 / np.cosh((v - centre) / 0.9) ** 2
    columns: dict[str, Any] = {"freq_hz": 1e5, "ac_vrms": 0.03, "dc_v": v}
    if double:
        columns = {"segment": ["fwd"] * points + ["rev"] * points, **columns}
    return run_data(table_of(columns, c, np.full(v.size, 1e-9)), "fecap.cv_butterfly",
                    geometry or DutGeometry(area_um2=2500.0, tox_nm=10.0))


@pytest.mark.parametrize(("start", "stop"), [(-3.0, 3.0), (3.0, -3.0)])
def test_butterfly_peaks_give_vc_imprint_and_ec(start: float, stop: float) -> None:
    results = cv_butterfly(butterfly_run(1.05, 0.1, start=start, stop=stop), criteria=CRITERIA)
    assert one(results, "v_peak_up").value == pytest.approx(1.15, abs=2e-3)
    assert one(results, "v_peak_down").value == pytest.approx(-0.95, abs=2e-3)
    assert one(results, "vc").value == pytest.approx(1.05, abs=2e-3)
    assert one(results, "v_imprint").value == pytest.approx(0.1, abs=2e-3)
    assert one(results, "ec").value == pytest.approx(1.05, abs=2e-3) and one(results, "ec").unit == "MV/cm"
    assert one(results, "c_peak").value == pytest.approx(100e-12, rel=1e-3)


def test_butterfly_refusals() -> None:
    single = cv_butterfly(butterfly_run(double=False), criteria=CRITERIA)
    assert all(r.outcome == "failed" and "single sweep" in r.error for r in single)
    narrow = cv_butterfly(butterfly_run(start=-0.5, stop=0.5, points=21), criteria=CRITERIA)
    assert all(r.outcome == "failed" and "peaks at its end" in r.error for r in narrow)
    thin = cv_butterfly(butterfly_run(geometry=DutGeometry(area_um2=2500.0)), criteria=CRITERIA)
    assert one(thin, "ec").outcome == "refused" and "geometry.tox_nm" in one(thin, "ec").error
    assert one(thin, "vc").outcome == "ok"


# -- cv_pulsed_vs_dc -------------------------------------------------------------------------------------------------


def moscap_curve(device: MoscapDevice, v: np.ndarray, *, q_inv: float | None) -> np.ndarray:
    return np.array([device._admittance(x, 1e6, q_inv, device.s_bt) for x in v])


def test_pulsed_vs_dc_compares_two_mos_c_curves() -> None:
    device = MoscapDevice("m", MoscapParams(area_um2=1e4, tox_nm=5.0, nsub_cm3=1e17, phi_ms_v=-0.85))
    v = np.linspace(-2.5, 2.0, 91)
    w = 2 * math.pi * 1e6
    columns = {"freq_hz": 1e6, "ac_vrms": 0.03, "dc_v": v}
    dc_y, pulsed_y = moscap_curve(device, v, q_inv=None), moscap_curve(device, v, q_inv=0.0)
    dc = run_data(table_of(columns, dc_y.imag / w, dc_y.real), "moscap.cv", run_id="S20261124T000000Z-bbbb")
    pulsed = run_data(table_of(columns, pulsed_y.imag / w, pulsed_y.real), "moscap.pulsed_cv")
    results = cv_pulsed_vs_dc(pulsed, reference=dc, criteria=CRITERIA)
    assert abs(one(results, "delta_vfb").value) < 2e-3 and one(results, "cox_ratio").value == pytest.approx(1, abs=1e-3)
    expected = device.deep_depletion_capacitance(2.0, 1e6) / device.equilibrium_capacitance(2.0, 1e6)
    assert one(results, "c_ratio_inversion").value == pytest.approx(expected, rel=1e-3)
    via_registry = run_method("cv_pulsed_vs_dc", pulsed, {"reference_run": dc.run_id},
                              load_reference=lambda run_id: dc, criteria=CRITERIA)
    assert one(via_registry, "delta_vfb").value == one(results, "delta_vfb").value  # type: ignore[arg-type]
    spot = run_data(table_of({"freq_hz": 1e6, "ac_vrms": 0.03, "dc_v": 0.0}, np.full(3, 1e-11), np.full(3, 1e-9)),
                    "cmu.spot", run_id="S20261124T000000Z-cccc")
    with pytest.raises(InvalidInputError, match="compares two C-V"):
        cv_pulsed_vs_dc(pulsed, reference=spot, criteria=CRITERIA)


# -- registry --------------------------------------------------------------------------------------------------------


def test_registry_entries_of_the_variants() -> None:
    expected = {"cf_dispersion": ("moscap.cf", ("cmu",)), "ct_recovery": ("moscap.ct", ("cmu",)),
                "cv_ac_dependence": ("moscap.cv_ac_level", ("cmu",)), "cv_butterfly": ("fecap.cv_butterfly", ("nvm",)),
                "cv_pulsed_vs_dc": ("moscap.pulsed_cv", ("cmu",))}
    for name, (recipe_id, families) in expected.items():
        method = ANALYSIS_METHODS[name]
        assert method.applies_to(recipe_id, "cmu_measure") and method.families == families, name
        assert not method.applies_to("moscap.cv", "cmu_measure"), name
    assert ANALYSIS_METHODS["cv_pulsed_vs_dc"].two_run
    assert ANALYSIS_METHODS["cv_pulsed_vs_dc"].options[0] == "reference_run"
    assert ANALYSIS_METHODS["cf_dispersion"].options == ("cox_f", "eps_ox", "rs_ohm", "model", "segment", "force")
    for name in ("cv_cox", "cv_flatband", "cv_doping_profile"):
        assert ANALYSIS_METHODS[name].applies_to("moscap.pulsed_cv", "cmu_measure")
        assert not any(ANALYSIS_METHODS[name].applies_to(r, "cmu_measure")
                       for r in ("moscap.cf", "moscap.ct", "moscap.cv_ac_level"))
    assert ANALYSIS_METHODS["plot_cv"].applies_to("fecap.cv_butterfly", "cmu_measure")
    assert "nvm" in ANALYSIS_METHODS["plot_cv"].families
