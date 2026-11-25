"""Dit over the band gap and the QSCV run (``analysis/dit.py``, ``analysis/qscv.py`` and their hooks in ``cv.py``;
WP8.5) on analytic curves of the ``moscap_dit`` device model (noise-free truth from ``MoscapDevice``): the high-low
profile within 5 % of the model's Dit(E) in its window and the conductance method within 5 % at every counted bias;
the refusals (untrusted points, no geometry, the wrong pair of runs, a sweep that misses flatband); ``cv_cox`` on a QSCV
run, nothing from an offset run, the other C-V methods refusing a QSCV run; ``plot_cv`` of a QSCV run."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from b1500_test_agent.analysis import RunData, run_method, with_trust
from b1500_test_agent.analysis.dit import dit_conductance, dit_high_low, high_low_profile
from b1500_test_agent.analysis.qscv import qscv_offset_run, quasi_static_role
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.policy import DutGeometry
from b1500_test_agent.models.recipe import QualityCriteria
from b1500_test_agent.models.sim import MoscapParams
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from tests.unit.analysis_helpers import manifest
from tests.unit.helpers import REPO_ROOT

pytestmark = pytest.mark.cmu

CRITERIA = QualityCriteria(limited=[], untrusted=["U", "D", "V", "X", "C", "T", "F", "G", "S"])
GEOMETRY = DutGeometry(area_um2=1.0e4, tox_nm=5.0)
FREQS = [1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6]


def device() -> MoscapDevice:
    data = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/moscap_dit.yaml").read_text(encoding="utf-8"))
    return MoscapDevice("dut", MoscapParams(**data["models"]["dut"]["params"]))


DEVICE = device()


def run_data(table: pd.DataFrame, recipe_id: str, kind: str, *, geometry: DutGeometry | None = GEOMETRY,
             run_id: str = "S20261124T000000Z-aaaa", params: dict[str, Quantity] | None = None) -> RunData:
    m = manifest(run_id, recipe_id=recipe_id, kind=kind, params=params or {})
    return RunData(manifest=m.model_copy(update={"dut_geometry": geometry}), table=with_trust(table, CRITERIA))


def qscv_run(*, step: float = 0.05, status: list[str] | None = None, geometry: DutGeometry | None = GEOMETRY,
             start: float = 2.0, stop: float = -2.5) -> RunData:
    """The quasi-static curve the instrument returns: ``dQ/dV`` over each transition, at the step voltages."""
    count = round(abs(stop - start) / step) - 1
    v = start + math.copysign(step, stop - start) * np.arange(1, count + 1)
    c = np.array([(DEVICE.charge(x + step / 2) - DEVICE.charge(x - step / 2)) / step for x in v])
    table = pd.DataFrame({"step": range(len(v)), "dc_v": v, "gate_Cp": c, "gate_Cp_status": status or ["N"] * len(v),
                          "gate_I": 1e-12 * v, "gate_I_status": "N"})
    return run_data(table, "moscap.qscv", "smu_qscv", geometry=geometry, run_id="S20261124T000000Z-0001")


def hf_run(freqs: list[float] = [1e6], *, geometry: DutGeometry | None = GEOMETRY,  # noqa: B006
           v: np.ndarray | None = None, recipe_id: str = "moscap.cv") -> RunData:
    """C-V (Cp-G) of the device in equilibrium at every frequency, series Rs removed."""
    v = np.linspace(2.0, -2.5, 181) if v is None else v
    rows: list[dict[str, Any]] = []
    for f in freqs:
        omega = 2 * math.pi * f
        for x in v:
            y = 1 / (1 / DEVICE._admittance(x, f, None, DEVICE.s_bt) - DEVICE.params.rs_ohm)
            rows.append({"freq_hz": f, "ac_vrms": 0.03, "dc_v": float(x), "gate_Cp": y.imag / omega,
                         "gate_Cp_status": "N", "gate_G": y.real, "gate_G_status": "N"})
    table = pd.DataFrame(rows)
    table.insert(0, "step", range(len(table)))
    params = {"freqs_hz": Quantity(value=freqs, unit="Hz")}
    return run_data(table, recipe_id, "cmu_measure", geometry=geometry, run_id="S20261124T000000Z-0002",
                    params=params)


def one(results: list[Any], quantity: str) -> Any:
    found = [r for r in results if r.quantity == quantity]
    assert len(found) == 1, results
    return found[0]


# -- dit_high_low ----------------------------------------------------------------------------------------------------


def test_high_low_recovers_the_model_dit_over_its_window() -> None:
    results = dit_high_low(qscv_run(), reference=hf_run())
    mid = one(results, "dit_mid")
    assert mid.outcome == "ok" and mid.value == pytest.approx(DEVICE.es.dit(0.0), rel=0.05)
    fit = mid.fit
    samples = [k for k in range(40) if f"e{k}" in fit]
    assert len(samples) >= 10 and fit["psi_min"] == pytest.approx(6 * 0.025852, rel=1e-3)
    for k in samples:
        assert fit[f"dit{k}"] == pytest.approx(DEVICE.es.dit(fit[f"e{k}"]), rel=0.10), fit[f"e{k}"]  # edges: < 7 %
    assert fit["cox_f"] == pytest.approx(DEVICE.cox, rel=0.01) and fit["nsub"] == pytest.approx(1e17, rel=0.05)
    for name in ("dit_mean", "dit_min", "dit_max"):
        assert one(results, name).outcome == "ok" and one(results, name).unit == "cm^-2 eV^-1"
    assert one(results, "dit_min").value <= mid.value <= one(results, "dit_max").value
    swapped = dit_high_low(hf_run(), reference=qscv_run())  # either order
    assert one(swapped, "dit_mid").value == pytest.approx(mid.value, rel=1e-9)


def test_high_low_profile_helper_and_options() -> None:
    lf, hf = qscv_run(), hf_run()
    profile = high_low_profile(np.sort(lf.table["dc_v"].to_numpy()),
                               lf.table.sort_values("dc_v")["gate_Cp"].to_numpy(), np.sort(hf.table["dc_v"].to_numpy()),
                               hf.table.sort_values("dc_v")["gate_Cp"].to_numpy(), cox=DEVICE.cox, vfb=DEVICE.vfb(),
                               phi_b=DEVICE.es.phi_b, s=1.0, area_cm2=1e-4)
    assert list(profile.columns) == ["v", "psi", "e", "c_lf", "c_hf", "dit"]
    assert np.all(np.diff(profile["v"]) > 0)
    narrow = dit_high_low(lf, reference=hf, psi_min=0.3, psi_margin=0.3)
    assert one(narrow, "dit_mid").fit["psi_max"] == pytest.approx(2 * one(narrow, "dit_mid").fit["phi_b"] - 0.3)
    assert one(narrow, "dit_mean").points_used < one(dit_high_low(lf, reference=hf), "dit_mean").points_used


def test_high_low_refusals_and_failures() -> None:
    bad = qscv_run(status=["N"] * 40 + ["C"] + ["N"] * 48)
    assert all(r.outcome == "refused" for r in dit_high_low(bad, reference=hf_run(), criteria=CRITERIA))
    forced = dit_high_low(bad, reference=hf_run(), force=True, criteria=CRITERIA)
    assert one(forced, "dit_mid").forced_on_untrusted
    no_area = dit_high_low(qscv_run(geometry=DutGeometry(tox_nm=5.0)), reference=hf_run())
    assert all(r.outcome == "refused" and "area_um2" in (r.error or "") for r in no_area)
    short = dit_high_low(qscv_run(start=2.0, stop=0.0), reference=hf_run())  # never reaches flatband
    assert all(r.outcome == "failed" and "flatband" in (r.error or "") for r in short)
    with pytest.raises(InvalidInputError, match="one quasi-static"):
        dit_high_low(hf_run(), reference=hf_run())
    with pytest.raises(InvalidInputError, match="one quasi-static"):
        dit_high_low(qscv_run(), reference=qscv_run())


# -- dit_conductance -------------------------------------------------------------------------------------------------


def test_conductance_method_recovers_the_model_dit_where_the_peak_is_in_band() -> None:
    v = np.round(np.arange(0.5, -1.5001, -0.025), 6)
    results = dit_conductance(hf_run(FREQS, v=v, recipe_id="moscap.cv_multi_freq"), rs_ohm=0.0)
    mean = one(results, "dit_mean")
    assert mean.outcome == "ok", mean.error
    counted = [k for k in range(200) if f"v{k}" in mean.fit]
    assert len(counted) >= 8
    for k in counted:
        truth = DEVICE.interface_trap_truth(mean.fit[f"v{k}"], 1e5)
        assert mean.fit[f"dit{k}"] == pytest.approx(truth["dit_cm2_ev"], rel=0.05)
        assert mean.fit[f"e{k}"] == pytest.approx(truth["e_minus_ei_ev"], abs=0.02)
    assert one(results, "tau_min").value < one(results, "tau_max").value
    assert -0.4 < mean.fit["e_min"] < mean.fit["e_max"] < -0.1  # the majority-band half of the gap only


def test_conductance_refusals() -> None:
    with pytest.raises(InvalidInputError, match="4 or more frequencies"):
        dit_conductance(hf_run([1e5, 1e6], recipe_id="moscap.cv_multi_freq"))
    with pytest.raises(InvalidInputError, match="quasi-static"):
        dit_conductance(qscv_run())
    flat = dit_conductance(hf_run(FREQS, v=np.linspace(2.0, 1.0, 11), recipe_id="moscap.cv_multi_freq"))
    assert all(r.outcome == "failed" for r in flat)  # only inversion/accumulation: no bias counted
    no_area = dit_conductance(hf_run(FREQS, geometry=None, v=np.linspace(0.5, -1.5, 41)))
    assert all(r.outcome == "refused" for r in no_area)


# -- QSCV runs in cv.py ----------------------------------------------------------------------------------------------


def test_cv_cox_takes_a_qscv_run_and_the_hf_methods_refuse_it() -> None:
    lf = qscv_run()
    assert quasi_static_role(lf) == "gate" and quasi_static_role(hf_run()) is None
    cox = one(run_method("cv_cox", lf, {}, criteria=CRITERIA), "cox")
    assert cox.outcome == "ok" and cox.value == pytest.approx(DEVICE.cox, rel=0.01)
    assert cox.method_record.params["freq_hz"] == 0.0
    for method in ("cv_flatband", "cv_doping_profile", "cv_vth", "cv_hysteresis"):
        with pytest.raises(InvalidInputError, match="does not apply"):  # the registry: HF C-V recipes only
            run_method(method, lf, {}, criteria=CRITERIA)
    from b1500_test_agent.analysis.cv import cv_flatband
    with pytest.raises(InvalidInputError, match="quasi-static"):  # called directly, the method refuses it too
        cv_flatband(lf)
    plots = run_method("plot_cv", lf, {}, criteria=CRITERIA)
    assert [p.name for p in plots.plots] == ["qscv"] and plots.y == ("gate_Cp", "gate_I")


def test_an_offset_run_gives_nothing_to_extract() -> None:
    table = pd.DataFrame({"step": [0], "gate_Cp": [2.5e-13], "gate_Cp_status": ["N"]})
    offset = run_data(table, "moscap.qscv", "smu_qscv")
    assert qscv_offset_run(offset) and quasi_static_role(offset) is None
    assert run_method("cv_cox", offset, {}, criteria=CRITERIA) == []
    from b1500_test_agent.analysis.cv import cv_flatband
    with pytest.raises(InvalidInputError, match="offset measurement"):
        cv_flatband(offset)
