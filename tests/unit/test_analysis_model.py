"""Compact models (``analysis/model.py``, WP7.7; knowledge file 07 "Compact models"): the EKV and level-1 fits recover
known parameters from analytic curves with measurement-like noise (blueprint v2 10.3 AC: EKV Vth +-10 mV, n +-5 %),
p-type mirroring, the comparison metrics, the point selection (floor, limited and untrusted rows), refusals and
failures, parameter options, the SPICE export's sweep reconstruction and the registry entries."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import run_method
from b1500_test_agent.analysis.model import (
    CompactModel,
    compact_model_fit,
    export_spice_netlist,
    model_compare,
    model_from_params,
    model_points,
)
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.analysis.spice import SpiceExport, SweepError, sweep_plan
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import iv_table, run_of

pytestmark = pytest.mark.smu

TRUTH = {"vt0": 0.42, "n": 1.3, "beta": 2.0e-3, "theta": 0.2, "lambda": 0.05, "rs": 20.0}
VG = np.round(np.linspace(-1.0, 3.0, 101), 9)
FLOOR_A = 1e-13
REL_NOISE = 1e-3


def noisy(current: np.ndarray, seed: int = 1) -> np.ndarray:
    """Current with the simulator's noise model: sigma = sqrt(floor^2 + (rel I)^2)."""
    rng = np.random.default_rng(seed)
    return current + rng.normal(0.0, 1.0, current.size) * np.sqrt(FLOOR_A**2 + (REL_NOISE * current) ** 2)


def idvg(model: CompactModel, *, vd: float = 0.05, sign: float = 1.0, status: list[str] | None = None,
         seed: int = 1) -> pd.DataFrame:
    vg = sign * VG
    current = noisy(model.current(vg, sign * vd, 0.0), seed)
    source = {"gate_V": vg, "drain_V": np.full(vg.size, sign * vd)}
    return iv_table(source, {"drain_I": current}, status={"drain_I": status} if status else None)


def idvd(model: CompactModel, levels: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5)) -> pd.DataFrame:
    vd = np.round(np.linspace(0.0, 3.0, 101), 9)
    gate = np.repeat(levels, vd.size)
    drain = np.tile(vd, len(levels))
    current = noisy(model.current(gate, drain, 0.0), seed=3)
    return iv_table({"drain_V": drain, "gate_V": gate}, {"drain_I": current})


def by_quantity(results):
    return {r.quantity: r for r in results}


# -- EKV -------------------------------------------------------------------------------------------------------------


def test_ekv_fit_of_a_transfer_curve_recovers_vth_and_n() -> None:
    truth = CompactModel("ekv", TRUTH)
    found = by_quantity(compact_model_fit(run_of(idvg(truth), "mosfet.idvg")))
    assert set(found) == {"vth", "n", "beta", "theta"}  # lambda and rs held at 0 (small Vd, fit_rs false)
    assert found["vth"].value == pytest.approx(0.42, abs=0.010)  # AC: Vth +-10 mV
    assert found["n"].value == pytest.approx(1.3, rel=0.05)  # AC: n +-5 %
    assert found["beta"].value == pytest.approx(2e-3, rel=0.05)
    assert found["theta"].value == pytest.approx(0.2 + 2 * 2e-3 * 20.0, rel=0.15)  # theta absorbs 2 beta rs
    vth = found["vth"]
    assert vth.unit == "V" and vth.derived and vth.outcome == "ok" and vth.fit["rms_log"] < 0.02
    assert vth.fit["vt0_se"] > 0 and vth.fit["lambda"] == 0.0 and vth.fit["rs"] == 0.0
    assert vth.method_record.params["polarity_used"] == "n" and vth.window is not None
    assert vth.points_excluded.get("outside_window", 0) > 0  # the noise floor stays out of the fit
    assert any("lambda held at 0" in w for w in vth.warnings)
    assert found["beta"].unit == "A/V^2" and found["theta"].unit == "1/V" and found["n"].unit == "1"


def test_ekv_fit_of_an_output_family_recovers_every_parameter_with_rs() -> None:
    truth = CompactModel("ekv", TRUTH)
    found = by_quantity(compact_model_fit(run_of(idvd(truth), "mosfet.idvd", kind="smu_stepped"), fit_rs=True))
    assert found["vth"].value == pytest.approx(0.42, abs=0.010)
    assert found["n"].value == pytest.approx(1.3, rel=0.05)
    assert found["lambda"].value == pytest.approx(0.05, rel=0.10)
    assert found["rs"].value == pytest.approx(20.0, rel=0.25)
    assert found["theta"].value == pytest.approx(0.2, rel=0.15)
    assert found["vth"].method_record.params["step"] == "gate_V"
    assert any("Fewer than 5 used points below the threshold" in w for w in found["vth"].warnings)


def test_p_channel_is_mirrored() -> None:
    truth = CompactModel("ekv", {**TRUTH, "vt0": -0.42}, polarity="p")
    data = run_of(idvg(truth, sign=-1.0), "mosfet.idvg")
    found = by_quantity(compact_model_fit(data))
    assert found["vth"].value == pytest.approx(-0.42, abs=0.010)
    assert found["n"].value == pytest.approx(1.3, rel=0.05)
    assert found["vth"].method_record.params["polarity_used"] == "p"
    assert np.all(truth.current(-VG, -0.05) <= 0)  # current into the drain of a conducting p-FET is negative


def test_series_resistance_drop_is_solved_self_consistently() -> None:
    plain = CompactModel("ekv", {**TRUTH, "rs": 0.0})
    with_rs = CompactModel("ekv", TRUTH)
    i = float(with_rs.current(3.0, 0.05))
    assert i < float(plain.current(3.0, 0.05))
    # the intrinsic device sees the drain lowered and the source raised by I rs (bulk and gate unchanged)
    intrinsic = float(plain.current(3.0, 0.05 - i * 20.0, i * 20.0, 0.0))
    assert i == pytest.approx(intrinsic, rel=1e-9)


# -- level 1 ---------------------------------------------------------------------------------------------------------


def test_level1_fit_recovers_its_own_parameters_from_an_output_family() -> None:
    truth = CompactModel("level1", {"vto": 0.5, "beta": 1e-3, "lambda": 0.04})
    found = by_quantity(compact_model_fit(run_of(idvd(truth), "mosfet.idvd", kind="smu_stepped"), model="level1",
                                          w_um=10.0, l_um=1.0))
    assert set(found) == {"vth", "beta", "lambda", "kp"}
    assert found["vth"].value == pytest.approx(0.5, abs=0.005)
    assert found["beta"].value == pytest.approx(1e-3, rel=0.02)
    assert found["lambda"].value == pytest.approx(0.04, rel=0.05)
    assert found["kp"].value == pytest.approx(1e-4, rel=0.02) and found["kp"].fit["w_um"] == 10.0


def test_level1_uses_only_the_strong_inversion_points() -> None:
    truth = CompactModel("ekv", TRUTH)
    data = run_of(idvg(truth), "mosfet.idvg")
    pts = model_points(data, model="level1")
    assert np.min(np.abs(pts.current)) >= 0.05 * np.max(np.abs(pts.current))
    [vth, beta] = compact_model_fit(data, model="level1")
    assert vth.quantity == "vth" and 0.2 < vth.value < 0.5 and beta.quantity == "beta"


def test_level1_has_no_current_below_vto_and_is_symmetric() -> None:
    m = CompactModel("level1", {"vto": 0.5, "beta": 1e-3, "lambda": 0.0})
    assert float(m.current(0.4, 1.0)) == 0.0
    assert float(m.current(1.5, 0.2)) == pytest.approx(1e-3 * (1.0 * 0.2 - 0.02))
    assert float(m.current(1.5, 2.0)) == pytest.approx(0.5e-3)
    assert float(m.current(1.5, -0.2, 0.0)) == pytest.approx(-float(m.current(1.7, 0.2, 0.0)))


# -- comparison ------------------------------------------------------------------------------------------------------


def test_compare_with_the_true_parameters_is_at_the_noise_level() -> None:
    truth = CompactModel("ekv", TRUTH)
    data = run_of(idvd(truth), "mosfet.idvd", kind="smu_stepped")
    found = by_quantity(model_compare(data, params=TRUTH))
    assert found["rms_rel"].value < 3 * REL_NOISE and found["rms_log"].value < 0.002
    assert found["rms_error"].unit == "A" and found["max_rel"].value < 0.01
    assert "rms_rel@gate_V=1.5" in found["rms_rel"].fit and found["rms_rel"].warnings == []
    worse = by_quantity(model_compare(data, params={**TRUTH, "vt0": 0.47}))
    assert worse["rms_rel"].value > 10 * found["rms_rel"].value


def test_compare_without_params_fits_first_and_says_so() -> None:
    truth = CompactModel("ekv", TRUTH)
    found = by_quantity(model_compare(run_of(idvg(truth), "mosfet.idvg")))
    assert found["rms_rel"].value < 0.05
    assert any("goodness of fit, not a validation" in w for w in found["rms_rel"].warnings)


def test_params_accept_vth_and_kp_aliases_and_check_bounds() -> None:
    m = model_from_params("level1", {"vth": 0.5, "kp": 1e-4, "w_um": 10, "l_um": 1}, polarity="n",
                          temperature_k=300.0)
    assert m.params == {"vto": 0.5, "beta": pytest.approx(1e-3)}
    with pytest.raises(InvalidInputError, match="kp needs model level1"):
        model_from_params("ekv", {"vth": 0.4, "n": 1.3, "kp": 1e-4}, polarity="n", temperature_k=300.0)
    with pytest.raises(InvalidInputError, match="no parameter"):
        CompactModel("ekv", {**TRUTH, "gamma": 0.4})
    with pytest.raises(InvalidInputError, match="outside"):
        CompactModel("ekv", {**TRUTH, "n": 0.5})
    with pytest.raises(InvalidInputError, match="needs the parameter"):
        CompactModel("ekv", {"vt0": 0.4})


# -- points, trust, refusal ------------------------------------------------------------------------------------------


def test_untrusted_rows_refuse_and_limited_rows_stay_out() -> None:
    truth = CompactModel("ekv", TRUTH)
    status = ["N"] * VG.size
    status[90] = "X"
    [refused] = compact_model_fit(run_of(idvg(truth, status=status), "mosfet.idvg"))
    assert refused.outcome == "refused" and refused.value is None and "untrusted" in (refused.error or "")
    forced = by_quantity(compact_model_fit(run_of(idvg(truth, status=status), "mosfet.idvg"), force=True))
    assert forced["vth"].forced_on_untrusted and forced["vth"].value == pytest.approx(0.42, abs=0.010)
    status[90] = "C"
    limited = by_quantity(compact_model_fit(run_of(idvg(truth, status=status), "mosfet.idvg")))
    assert limited["vth"].points_excluded.get("C") == 1 and limited["vth"].value == pytest.approx(0.42, abs=0.010)
    [refused_compare] = model_compare(run_of(idvg(truth, status=["X"] * VG.size), "mosfet.idvg"))
    assert refused_compare.quantity == "rms_rel" and refused_compare.outcome == "refused"


def test_floor_estimate_and_explicit_i_min() -> None:
    truth = CompactModel("ekv", TRUTH)
    data = run_of(idvg(truth), "mosfet.idvg")
    auto = model_points(data)
    assert 1e-13 < auto.i_min < 1e-11  # a few times the 1e-13 A noise floor
    strict = model_points(data, i_min_a=1e-8)
    assert strict.size < auto.size and np.min(np.abs(strict.current)) >= 1e-8


def test_too_few_points_fail_and_missing_columns_are_invalid() -> None:
    truth = CompactModel("ekv", TRUTH)
    [failed] = compact_model_fit(run_of(idvg(truth), "mosfet.idvg"), i_min_a=2e-3)
    assert failed.outcome == "failed" and "fit impossible" in (failed.error or "")
    table = iv_table({"gate_V": VG}, {"drain_I": truth.current(VG, 0.05)})
    with pytest.raises(InvalidInputError, match="drain_V"):
        compact_model_fit(run_of(table, "mosfet.idvg"))
    with pytest.raises(InvalidInputError, match="measured current"):
        compact_model_fit(run_of(idvg(truth), "mosfet.idvg"), y="gate_V")


# -- export ----------------------------------------------------------------------------------------------------------


def test_export_writes_a_library_and_a_netlist_with_the_run_sweep() -> None:
    truth = CompactModel("ekv", TRUTH)
    data = run_of(idvd(truth), "mosfet.idvd", kind="smu_stepped")
    export = export_spice_netlist(data, fit_rs=True)
    assert isinstance(export, SpiceExport) and export.stem == "spice-ekv"
    lib, netlist = export.files
    assert (lib.suffix, netlist.suffix) == (".lib", ".sp")
    assert ".subckt nch_ekv d g s b" in lib.text and "B1 di si I=" in lib.text and "ln(1+exp(" in lib.text
    assert ".dc VD 0 3 0.03 VG 0.5 1.5 0.25" in netlist.text and netlist.text.rstrip().endswith(".end")
    assert "SIMULATED data" in netlist.text and "-I(VD)" in netlist.text
    [rms_rel, rms_log] = export.results
    assert rms_rel.quantity == "rms_rel" and rms_rel.value < 0.01 and rms_log.unit == "1"
    hspice = export_spice_netlist(data, params=TRUTH, dialect="hspice")
    assert "G1 di si CUR='" in hspice.files[0].text and "log(1+exp(" in hspice.files[0].text
    assert "parameters given to export_spice_netlist" in hspice.files[1].text and hspice.results[0].warnings == []


def test_export_of_a_level1_model_is_a_model_card_scaled_by_geometry() -> None:
    truth = CompactModel("level1", {"vto": 0.5, "beta": 1e-3, "lambda": 0.04})
    data = run_of(idvd(truth), "mosfet.idvd", kind="smu_stepped")
    export = export_spice_netlist(data, model="level1", params={"vto": 0.5, "beta": 1e-3, "lambda": 0.04},
                                  w_um=10.0, l_um=1.0)
    lib = export.files[0].text
    assert ".model nch_level1 NMOS (LEVEL=1 VTO=0.5 KP=0.0001 LAMBDA=0.04" in lib
    assert "M1 d g s s nch_level1 W=10u L=1u" in export.files[1].text


def test_sweep_plan_reproduces_grids_and_refuses_synchronous_or_log_sweeps() -> None:
    truth = CompactModel("ekv", TRUTH)
    data = run_of(idvg(truth), "mosfet.idvg")
    plan = sweep_plan(data, data.table, "gate_V", None)
    assert (plan.inner.terminal, plan.inner.start, plan.inner.stop, plan.inner.step) == ("g", -1.0, 3.0,
                                                                                        pytest.approx(0.04))
    assert plan.outer is None and plan.constants == {"d": 0.05, "s": 0.0} and plan.bulk_tied
    sync = iv_table({"gate_V": VG, "drain_V": 0.2 + 0.25 * VG}, {"drain_I": truth.current(VG, 0.2 + 0.25 * VG)})
    with pytest.raises(SweepError, match="synchronous"):
        sweep_plan(run_of(sync, "mosfet.idvg_sync"), sync, "gate_V", None)
    log_vg = np.geomspace(0.1, 3.0, 31)
    log = iv_table({"gate_V": log_vg, "drain_V": np.full(31, 0.05)}, {"drain_I": truth.current(log_vg, 0.05)})
    with pytest.raises(SweepError, match="uniform grid"):
        sweep_plan(run_of(log, "generic.smu_staircase"), log, "gate_V", None)
    [failed] = export_spice_netlist(run_of(sync, "mosfet.idvg_sync")).results
    assert failed.outcome == "failed" and "No netlist" in (failed.error or "")


# -- registry --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["compact_model_fit", "model_compare", "export_spice_netlist"])
def test_registry_entries(name: str) -> None:
    method = ANALYSIS_METHODS[name]
    assert method.families == ("smu",) and method.milestone == "M7"
    for recipe, kind in (("mosfet.idvg", "smu_staircase"), ("mosfet.idvd", "smu_stepped"),
                         ("mosfet.idvg_pulsed", "smu_pulsed"), ("mosfet.body_effect", "smu_stepped")):
        assert method.applies_to(recipe, kind), (recipe, kind)
    assert not method.applies_to("basic.diode_iv", "smu_staircase")
    assert "params" in method.options or name == "compact_model_fit"
    assert ANALYSIS_METHODS["export_spice_netlist"].output == "files"


def test_run_method_returns_the_export_and_rejects_unknown_options() -> None:
    truth = CompactModel("ekv", TRUTH)
    data = run_of(idvg(truth), "mosfet.idvg")
    assert isinstance(run_method("export_spice_netlist", data, {"model": "ekv"}), SpiceExport)
    with pytest.raises(InvalidInputError, match="no option"):
        run_method("compact_model_fit", data, {"gamma": 1})
    with pytest.raises(InvalidInputError, match="Invalid options"):
        run_method("compact_model_fit", data, {"model": "bsim4"})
