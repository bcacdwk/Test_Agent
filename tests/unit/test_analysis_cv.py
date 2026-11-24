"""C-V analysis (``analysis/cv.py``; WP8.3) against analytic curves with known truth: the exact 1-D MOS
electrostatics of the simulator's ``moscap`` and ``mosfet`` models (no instrument, no noise unless stated) and
closed-form impedance conversions. Also the refusals: missing geometry (naming the field), untrusted points (and
``force``), a single sweep for ``cv_hysteresis``, an unknown frequency."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import RunData, run_method, with_trust
from b1500_test_agent.analysis.cv import (
    accumulation_rs,
    convert_table,
    cv_cox,
    cv_doping_profile,
    cv_flatband,
    cv_hysteresis,
    cv_vth,
    from_admittance,
    impedance_convert,
    moscap_fit,
    plot_cv,
    remove_series_r,
    render_cv,
    split_fit,
    to_admittance,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.policy import DutGeometry
from b1500_test_agent.models.recipe import QualityCriteria
from b1500_test_agent.models.sim import MoscapParams, MosfetParams
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from b1500_test_agent.transport.sim.devices.mosfet import Mosfet
from tests.unit.analysis_helpers import manifest

CRITERIA = QualityCriteria(limited=[], untrusted=["U", "D", "V", "X", "C", "T", "F", "G", "S"])
AREA = DutGeometry(area_um2=1.0e4, tox_nm=5.0)
F = 1e6


def moscap(**params: Any) -> MoscapDevice:
    defaults: dict[str, Any] = {"area_um2": 1e4, "tox_nm": 5.0, "nsub_cm3": 1e17, "phi_ms_v": -0.85}
    return MoscapDevice("m", MoscapParams(**{**defaults, **params}))


def cv_table(v: np.ndarray, y: np.ndarray, *, freq: float = F, role: str = "gate",
             segment: list[str] | None = None, status: list[str] | None = None) -> pd.DataFrame:
    """A ``cmu_measure`` Cp-G table of admittances ``y`` at biases ``v``."""
    omega = 2 * math.pi * freq
    table = pd.DataFrame({"step": range(len(v))})
    if segment is not None:
        table["segment"] = segment
    table["freq_hz"] = freq
    table["ac_vrms"] = 0.03
    table["dc_v"] = v
    table[f"{role}_Cp"] = y.imag / omega
    table[f"{role}_Cp_status"] = status or ["N"] * len(v)
    table[f"{role}_G"] = y.real
    table[f"{role}_G_status"] = "N"
    return table


def run_data(table: pd.DataFrame, *, recipe_id: str = "moscap.cv", geometry: DutGeometry | None = AREA) -> RunData:
    params = {"freqs_hz": Quantity(value=sorted(set(table["freq_hz"])), unit="Hz")}
    m = manifest(recipe_id=recipe_id, kind="cmu_measure", params=params)
    return RunData(manifest=m.model_copy(update={"dut_geometry": geometry}), table=with_trust(table, CRITERIA))


def sweep(device: MoscapDevice, start: float = 2.0, stop: float = -2.5, points: int = 91,
          freq: float = F) -> tuple[np.ndarray, np.ndarray]:
    v = np.linspace(start, stop, points)
    y = np.array([device._admittance(x, freq, None, device.s_bt) for x in v])
    return v, y


def one(results: list[Any], quantity: str) -> Any:
    found = [r for r in results if r.quantity == quantity]
    assert len(found) == 1, results
    return found[0]


# -- impedance models ------------------------------------------------------------------------------------------------


def test_impedance_pairs_round_trip_and_obey_the_textbook_relations() -> None:
    omega = np.full(3, 2 * math.pi * 1e5)
    y = np.array([1e-6 + 1j * omega[0] * 100e-12, 5e-8 + 1j * omega[0] * 1e-9, 2e-5 + 1j * omega[0] * 3e-12])
    for model in ("cp_g", "cp_d", "cs_rs", "cs_d", "z_theta"):
        values = from_admittance(model, y, omega)
        primary, secondary = (values[k] for k in values)
        back = to_admittance(*values.keys(), primary, secondary, omega)
        assert np.allclose(back, y, rtol=1e-12)
    cp = from_admittance("cp_d", y, omega)
    cs = from_admittance("cs_rs", y, omega)["Cs"]
    assert np.allclose(cs, cp["Cp"] * (1 + cp["D"] ** 2))  # Cs = Cp (1 + D^2)
    assert np.allclose(from_admittance("cs_d", y, omega)["D"], cp["D"])  # one dissipation factor
    z = from_admittance("z_theta", y, omega)
    assert np.allclose(z["theta"], np.angle(1 / y)) and np.all(z["theta"] < 0)  # capacitive


def test_series_resistance_is_estimated_in_accumulation_and_removed() -> None:
    omega, c, rs = 2 * math.pi * 1e6, 69e-12, 120.0
    y = 1 / (rs + 1 / (1j * omega * c))
    assert accumulation_rs(y.imag / omega, y.real, omega) == pytest.approx(rs, rel=1e-9)
    corrected = remove_series_r(np.array([y]), rs)[0]
    assert corrected.real == pytest.approx(0, abs=1e-15) and corrected.imag / omega == pytest.approx(c, rel=1e-12)


# -- MOS capacitor ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("params", [
    {}, {"nsub_cm3": 3e17, "tox_nm": 3.0}, {"nsub_cm3": 1e16, "tox_nm": 10.0}, {"substrate": "n", "phi_ms_v": 0.3},
])
def test_moscap_fit_recovers_cox_nsub_vfb_and_vth(params: dict[str, Any]) -> None:
    device = moscap(**params)
    n_type = params.get("substrate") == "n"
    v, y = sweep(device, *((-2.0, 2.5) if n_type else (2.0, -2.5)))
    truth = device.truth()
    order = np.argsort(v)
    c = y.imag[order] / (2 * math.pi * F)
    fit = moscap_fit(v[order], c, area_cm2=truth["area_cm2"])
    assert fit.s == (-1.0 if n_type else 1.0)
    assert c.max() < 0.985 * truth["cox_f"]  # Cmax is not Cox
    assert fit.cox == pytest.approx(truth["cox_f"], rel=0.005)
    assert fit.nsub == pytest.approx(truth["nsub_cm3"], rel=0.03)
    assert fit.vfb == pytest.approx(truth["vfb_v"], abs=0.005)
    vth = truth["vfb_v"] + (-1 if n_type else 1) * device.es.vth_offset
    assert fit.vth == pytest.approx(vth, abs=0.010)


def test_moscap_methods_report_derived_values_with_windows() -> None:
    device = moscap()
    v, y = sweep(device)
    d = run_data(cv_table(v, y))
    truth = device.truth()
    cox = cv_cox(d, criteria=CRITERIA)
    assert one(cox, "cox").value == pytest.approx(truth["cox_f"], rel=0.005)
    assert one(cox, "eot").value == pytest.approx(5e-9, rel=0.005) and one(cox, "eot").unit == "m"
    assert one(cox, "cox_per_area").unit == "F/m^2"
    nsub = one(cv_doping_profile(d, criteria=CRITERIA), "nsub")
    assert nsub.unit == "cm^-3" and nsub.derived and nsub.window is not None and nsub.points_used >= 5
    assert nsub.fit["depth_min_m"] < nsub.fit["depth_max_m"] < 2e-7
    flat = cv_flatband(d, criteria=CRITERIA)
    assert one(flat, "vfb").value == pytest.approx(truth["vfb_v"], abs=0.005)
    assert one(flat, "c_fb").value == pytest.approx(truth["c_fb_f"], rel=0.01)
    assert one(cv_vth(d, criteria=CRITERIA), "vth").method_record.name == "cv_vth"


def test_geometry_dependent_methods_refuse_and_name_the_field() -> None:
    v, y = sweep(moscap())
    d = run_data(cv_table(v, y), geometry=None)
    for method in (cv_doping_profile, cv_flatband, cv_vth):
        result = method(d, criteria=CRITERIA)[0]
        assert result.outcome == "refused" and result.value is None
        assert "has no geometry.area_um2" in (result.error or "")
    cox = cv_cox(d, criteria=CRITERIA)
    assert one(cox, "cox").outcome == "ok" and one(cox, "eot").outcome == "refused"
    widths_only = run_data(cv_table(v, y), geometry=DutGeometry(w_um=100.0, l_um=100.0))
    assert one(cv_flatband(widths_only, criteria=CRITERIA), "vfb").outcome == "ok"  # W x L is an area too


def test_untrusted_points_refuse_unless_forced() -> None:
    v, y = sweep(moscap())
    status = ["N"] * len(v)
    status[40] = "U"
    d = run_data(cv_table(v, y, status=status))
    refused = one(cv_cox(d, criteria=CRITERIA), "cox")
    assert refused.outcome == "refused" and "untrusted" in (refused.error or "")
    forced = one(cv_cox(d, force=True, criteria=CRITERIA), "cox")
    assert forced.outcome == "ok" and forced.forced_on_untrusted and forced.points_excluded == {"U": 1}


def test_series_resistance_option_restores_the_cox_of_a_lossy_contact() -> None:
    device = moscap(rs_ohm=300.0)
    v, y = sweep(device, freq=5e6)
    d = run_data(cv_table(v, y, freq=5e6))
    plain = one(cv_cox(d, criteria=CRITERIA), "cox").value
    estimated = one(impedance_convert(d, to="cp_g", series_r="accumulation", criteria=CRITERIA), "rs").value
    assert estimated == pytest.approx(300.0, rel=0.05)
    corrected = one(cv_cox(d, rs_ohm=estimated, criteria=CRITERIA), "cox").value
    truth = device.truth()["cox_f"]
    assert abs(corrected / truth - 1) < 0.005 < abs(plain / truth - 1)


def test_hysteresis_of_a_double_sweep() -> None:
    fwd_device, rev_device = moscap(), moscap(qf_cm2=-1.3e11)  # the return branch shifted by about +30 mV
    v_fwd, y_fwd = sweep(fwd_device)
    v_rev, y_rev = sweep(rev_device, -2.5, 2.0)
    table = cv_table(np.concatenate([v_fwd, v_rev]), np.concatenate([y_fwd, y_rev]),
                     segment=["fwd"] * len(v_fwd) + ["rev"] * len(v_rev))
    found = {r.quantity: r.value for r in cv_hysteresis(run_data(table), criteria=CRITERIA)}
    shift = rev_device.truth()["vfb_v"] - fwd_device.truth()["vfb_v"]
    assert found["hysteresis"] == pytest.approx(shift, abs=0.002) and found["vfb_fwd"] == pytest.approx(
        fwd_device.truth()["vfb_v"], abs=0.005)
    single = cv_hysteresis(run_data(cv_table(v_fwd, y_fwd)), criteria=CRITERIA)
    assert all(r.outcome == "failed" and "sweep_mode double" in (r.error or "") for r in single)


def test_frequency_selection() -> None:
    device = moscap()
    v1, y1 = sweep(device, freq=1e5)
    v2, y2 = sweep(device, freq=1e6)
    table = pd.concat([cv_table(v1, y1, freq=1e5), cv_table(v2, y2, freq=1e6)], ignore_index=True)
    table["step"] = range(len(table))
    d = run_data(table)
    assert one(cv_cox(d, freq_hz=1e6, criteria=CRITERIA), "cox").method_record.params["freq_hz"] == 1e6
    assert one(cv_cox(d, criteria=CRITERIA), "cox").method_record.params["freq_hz"] == 1e5  # the first one
    with pytest.raises(InvalidInputError, match="no frequency 200000 Hz"):
        cv_cox(d, freq_hz=2e5, criteria=CRITERIA)


# -- split C-V -------------------------------------------------------------------------------------------------------


def mosfet(**params: Any) -> Mosfet:
    defaults: dict[str, Any] = {"polarity": "n", "vth0": 0.45, "beta": 4e-3, "w_um": 100.0, "l_um": 10.0,
                                "tox_nm": 5.0, "nsub_cm3": 3e17, "cov_f_per_m": 2e-10}
    return Mosfet("m", MosfetParams.model_validate({**defaults, **params}))


@pytest.mark.parametrize("source", ["tied", "floating"])
def test_split_cv_plateau_is_cox_w_l_and_the_onset_is_vth(source: str) -> None:
    device = mosfet()
    truth = device.cv_truth()
    v = np.linspace(-1.5, 2.5, 81)
    low = ("source", "drain") if source == "tied" else ("drain",)
    bias = {"drain": 0.0, "source": 0.0 if source == "tied" else None, "bulk": 0.0}
    y = np.array([device.gate_admittance({"gate": x, **bias}, 1e5, low) for x in v])
    d = run_data(cv_table(v, y, freq=1e5), recipe_id="mosfet.cgc_cv",
                 geometry=DutGeometry(w_um=100.0, l_um=10.0, tox_nm=5.0))
    cox = cv_cox(d, criteria=CRITERIA)
    assert one(cox, "cox").value == pytest.approx(truth["cox_wl_f"], rel=0.015)
    floor = truth["c_overlap_f"] * (1.0 if source == "tied" else 0.5)
    assert one(cox, "c_floor").value == pytest.approx(floor, rel=0.01)
    assert one(cox, "eot").value == pytest.approx(5e-9, rel=0.015)
    assert one(cv_vth(d, criteria=CRITERIA), "vth").value == pytest.approx(truth["vth_v"], abs=0.05)
    assert one(cv_vth(d, criteria=CRITERIA), "vth").fit["method_onset"] == 1.0


def test_split_fit_mirrors_a_p_channel_device() -> None:
    device = mosfet(polarity="p", vth0=-0.45)
    v = np.linspace(-2.5, 1.5, 81)
    c = np.array([device.gate_capacitance({"gate": x, "drain": 0.0, "source": 0.0, "bulk": 0.0}, 1e5,
                                          ("source", "drain")) for x in v])
    fit = split_fit(v, c)
    assert fit.s == -1.0 and fit.plateau == pytest.approx(device.cv_truth()["cox_wl_f"], rel=0.015)
    assert fit.vth == pytest.approx(-0.45, abs=0.05) and fit.window[1] < fit.vth  # plateau on the negative side


# -- impedance_convert, plots, registry ------------------------------------------------------------------------------


def test_impedance_convert_of_a_spot_run_averages_the_samples() -> None:
    omega = 2 * math.pi * 1e5
    rng = np.random.default_rng(1)
    cp = 100e-12 * (1 + 1e-4 * rng.standard_normal(6))
    y = 1e-9 + 1j * omega * cp
    d = run_data(cv_table(np.zeros(6), y, freq=1e5, role="a"), recipe_id="cmu.spot", geometry=None)
    results = impedance_convert(d, to="cs_rs", criteria=CRITERIA)
    cs = one(results, "cs")
    assert cs.value == pytest.approx(float(np.mean(cp)) * (1 + (1e-9 / (omega * 100e-12)) ** 2), rel=1e-6)
    assert cs.points_used == 6 and cs.fit["std"] > 0 and cs.fit["freq_hz"] == 1e5
    table = convert_table(d, "z_theta")
    assert list(table.columns) == ["step", "freq_hz", "dc_v", "a_Z", "a_theta"]
    with pytest.raises(InvalidInputError, match="rs_ohm"):
        impedance_convert(d, series_r="value", criteria=CRITERIA)


def test_plot_cv_renders_cv_and_inverse_square_for_a_moscap(tmp_path: Any) -> None:
    v, y = sweep(moscap())
    d = run_data(cv_table(v, y))
    rendered = render_cv(d, criteria=CRITERIA)
    assert [p.name for p in rendered.plots] == ["cv", "cv-inverse-square"]
    assert all(p.png.startswith(b"\x89PNG") for p in rendered.plots)
    paths = plot_cv(d, model="cs_rs", out_dir=tmp_path, criteria=CRITERIA)
    assert [p.name for p in paths] == ["cv.png", "cv-inverse-square.png"]
    spot = run_data(pd.concat([cv_table(np.zeros(2), np.full(2, 1j * 2 * math.pi * f * 1e-10), freq=f, role="a")
                               for f in (1e5, 1e6)], ignore_index=True).assign(step=range(4)),
                    recipe_id="cmu.spot", geometry=None)
    assert [p.name for p in render_cv(spot, criteria=CRITERIA).plots] == ["cf"]


def test_registry_runs_the_cv_methods_on_cmu_measure_runs_only() -> None:
    v, y = sweep(moscap())
    d = run_data(cv_table(v, y))
    assert run_method("cv_cox", d, {}, criteria=CRITERIA)[0].outcome == "ok"  # type: ignore[index]
    with pytest.raises(InvalidInputError, match="does not apply"):
        run_method("plot_iv", d, {}, criteria=CRITERIA)
    with pytest.raises(InvalidInputError, match="does not apply"):
        run_method("cv_flatband", run_data(cv_table(v, y), recipe_id="mosfet.cgd_cv"), {}, criteria=CRITERIA)
