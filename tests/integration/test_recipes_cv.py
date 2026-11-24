"""The capacitance recipes of kind ``cmu_measure`` on the simulator (blueprint v2 10.4 row 8.3 AC, per-recipe AC;
WP8.3): ``cmu.spot`` (MM 17), ``moscap.cv`` (MM 18, single/double), ``mosfet.cgc_cv`` and ``mosfet.cgd_cv`` (split
C-V) through ``B1500Service``, each after the phase/open/short corrections of its pin map (R-CORR-01).

Fidelity (blueprint v2 4.2) against the model truth of the scenario's device (built from the committed scenario):
``moscap_basic`` Cox +-1 %, Vfb +-20 mV (the forward branch's flatband: border traps charged at the start),
Nsub +-10 %, hysteresis +-10 mV; ``nmos_cv`` (its split C-V transistor ``cv``) Cgc plateau = Cox*W*L +-2 %, Cgd =
the model's Cgd; the 100 pF
standard within 0.1 %. 0.3 Vrms is blocked (R-CMU-01 and the recipe range). The SCUU path routes both outputs to
the MFCMU and back to rest (scenario variant with an SCUU, pin map ``moscap-scuu``).
"""

from __future__ import annotations

import json
import shutil
from typing import Any

import numpy as np
import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.models.sim import MoscapParams, MosfetParams
from b1500_test_agent.rules.builtin.cmu import CORRECTION_NEXT_STEP
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from b1500_test_agent.transport.sim.devices.mosfet import Mosfet
from tests.integration.helpers import REPO_ROOT, World

CORRECTIONS = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")
MOSCAP = {"recipe_id": "moscap.cv", "pin_map": "moscap-cmu", "dut_profile": "moscap-generic"}
SPLIT = {"pin_map": "mosfet-split-cv", "dut_profile": "nmos-cv"}
SPOT = {"recipe_id": "cmu.spot", "pin_map": "capacitor-cmu", "dut_profile": "capacitor-100p"}


def recipe(recipe_id: str) -> pytest.MarkDecorator:
    """Parametrize with the recipe id, so ``pytest tests/integration -k <recipe id>`` selects the test."""
    return pytest.mark.parametrize("recipe_id", [recipe_id])


def scenario(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / f"config/sim/scenarios/{name}.yaml").read_text(encoding="utf-8"))


def moscap_truth() -> MoscapDevice:
    return MoscapDevice("dut", MoscapParams(**scenario("moscap_basic")["models"]["dut"]["params"]))


def mosfet_truth() -> Mosfet:
    return Mosfet("cv", MosfetParams.model_validate(scenario("nmos_cv")["models"]["cv"]["params"]))


def correct(svc: B1500Service, pin_map: str, **params: Any) -> None:
    """Phase compensation, open and short with ``pin_map`` (each confirmed with its own summary: the test stands in
    for the human who set the probes up)."""
    for name in CORRECTIONS:
        extra = {} if name == "cmu.phase_compensation" else params
        plan = svc.validate_plan(recipe_id=name, params=extra or None, pin_map=pin_map)
        assert plan.tier == "needs_confirmation" and plan.summary is not None, plan.message
        result = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]
        assert result.ok, result.message


def run(svc: B1500Service, request: dict[str, Any], **params: Any) -> tuple[PlanValidation, RunSummary]:
    plan = svc.validate_plan(**request, params=params or None)
    assert plan.tier == "needs_confirmation" and plan.summary is not None, (plan.message, plan.findings)
    return plan, svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]


def value(result: RunSummary, method: str, quantity: str) -> float:
    found = next(a for a in result.analyses if a.method == method and a.quantity == quantity)
    assert found.outcome == "ok" and found.value is not None, found.error
    return found.value


def manifest(world: World, run_id: str) -> dict[str, Any]:
    folder = next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def svc(world: World) -> B1500Service:
    return world.service()


# -- moscap.cv -------------------------------------------------------------------------------------------------------


@recipe("moscap.cv")
def test_moscap_cv_needs_corrections_then_meets_the_fidelity_targets(recipe_id: str, world: World,
                                                                     svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    blocked = svc.validate_plan(**MOSCAP)
    assert blocked.tier == "blocked" and CORRECTION_NEXT_STEP in blocked.next_steps
    assert {f.subject for f in blocked.findings if f.rule_id == "R-CORR-01" and f.severity == "block"} == {
        "CMU1.phase", "CMU1.open", "CMU1.short"}
    correct(svc, "moscap-cmu")
    plan, result = run(svc, MOSCAP)
    assert set(plan.confirm_reasons) == {"unverified_pin_map", "dut_envelope"}  # the MFCMU has no compliance
    assert plan.summary is not None and "gate=CMU1:H 1 MHz 30 mVrms DC -2.5..2 V corr <1h" in plan.summary
    assert result.ok and result.outcome == "completed" and result.simulated, result.message
    assert result.cleanup_verified == "sim_state" and result.quality_verdict == "ok"
    device = moscap_truth()
    truth = device.truth()
    forward = device.hysteresis_truth(2.0, -2.5)  # the sweep starts at +2 V: border traps charged
    assert value(result, "cv_cox", "cox") == pytest.approx(truth["cox_f"], rel=0.01)
    assert value(result, "cv_flatband", "vfb") == pytest.approx(forward["vfb_fwd"], abs=0.020)
    assert value(result, "cv_doping_profile", "nsub") == pytest.approx(truth["nsub_cm3"], rel=0.10)
    assert value(result, "cv_cox", "eot") == pytest.approx(5e-9, rel=0.01)
    vth_truth = forward["vfb_fwd"] + device.es.vth_offset
    assert value(result, "cv_vth", "vth") == pytest.approx(vth_truth, abs=0.030)
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert list(table.columns[:4]) == ["step", "freq_hz", "ac_vrms", "dc_v"] and len(table) == 91
    assert table["dc_v"].iloc[0] == pytest.approx(2.0) and table["dc_v"].iloc[-1] == pytest.approx(-2.5)
    assert set(table["gate_Cp_status"]) == {"N"}
    assert manifest(world, result.run_id)["dut_geometry"] == {"w_um": None, "l_um": None,  # type: ignore[arg-type]
                                                               "area_um2": 10000.0, "tox_nm": 5.0}


@recipe("moscap.cv")
def test_moscap_double_sweep_gives_the_border_trap_hysteresis(recipe_id: str, world: World,
                                                              svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    correct(svc, "moscap-cmu")
    _, result = run(svc, MOSCAP, sweep_mode="double", delay_s=0.05)
    assert result.ok, result.message
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert list(table["segment"].unique()) == ["fwd", "rev"] and len(table) == 182
    analysis = svc.analyze_run(result.run_id, "cv_hysteresis")  # type: ignore[arg-type]
    assert analysis.ok, analysis.message
    found = {r.quantity: r.value for r in analysis.results}
    truth = moscap_truth().hysteresis_truth(2.0, -2.5)
    assert found["hysteresis"] == pytest.approx(truth["hysteresis"], abs=0.010)
    assert found["vfb_fwd"] == pytest.approx(truth["vfb_fwd"], abs=0.020)


@recipe("moscap.cv")
def test_moscap_host_frequency_loop_measures_every_listed_frequency(recipe_id: str, world: World,
                                                                    svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    correct(svc, "moscap-cmu")
    _, result = run(svc, MOSCAP, freqs_hz=[1e5, 1e6], points=41)
    assert result.ok, result.message
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert list(table["freq_hz"].unique()) == [1e5, 1e6] and len(table) == 82
    assert list(table["step"]) == list(range(82))
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    events = [json.loads(line) for line in (folder / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    progress = [e["data"] for e in events if e.get("ev") == "checkpoint" and (e.get("data") or {}).get("label")
                == "progress"]
    assert [(p["done"], p["total"]) for p in progress] == [(1, 2), (2, 2)]
    cox = svc.analyze_run(result.run_id, "cv_cox", {"freq_hz": 1e5})  # type: ignore[arg-type]
    assert cox.ok and cox.results[0].value == pytest.approx(moscap_truth().cox, rel=0.01)


@recipe("moscap.cv")
def test_a_frequency_outside_the_corrections_and_03_vrms_are_blocked(recipe_id: str, world: World,
                                                                     svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    correct(svc, "moscap-cmu", freqs_hz=[1e6])
    uncovered = svc.validate_plan(**MOSCAP, params={"freqs_hz": [1e5]})
    assert uncovered.tier == "blocked" and any("does not cover 100000 Hz" in f.message for f in uncovered.findings)
    for request in (MOSCAP, SPOT):
        loud = svc.validate_plan(**request, params={"ac_vrms": 0.3})
        assert loud.tier == "blocked", request
        assert any(f.rule_id == "R-PARAM-01" and f.subject == "ac_vrms" for f in loud.findings)
    # the module limit holds on its own: a recipe copy whose range allows 0.3 Vrms cannot even compile (the MFCMU
    # setup and the ACV syntax end at 0.25 V), so no plan exists
    widened = shutil.copytree(REPO_ROOT / "recipes", world.root / "recipes-wide")
    text = (widened / "moscap/cv.yaml").read_text(encoding="utf-8")
    (widened / "moscap/cv.yaml").write_text(text.replace("range: [0.01, 0.25]", "range: [0.01, 0.5]"),
                                            encoding="utf-8")
    wide = world.service(registry=RecipeRegistry.load(widened, repo_root=REPO_ROOT))
    loud = wide.validate_plan(**MOSCAP, params={"ac_vrms": 0.3})
    assert not loud.ok and loud.plan_id is None and loud.error_code == "invalid_input"
    assert "less than or equal to 0.25" in loud.message


def test_geometry_dependent_methods_refuse_without_the_area(world: World, svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    profile = yaml.safe_load((REPO_ROOT / "config/duts/moscap-generic.example.yaml").read_text(encoding="utf-8"))
    profile.pop("geometry")
    world.write_config("duts/moscap-bare.yaml", profile)
    correct(svc, "moscap-cmu")
    _, result = run(svc, {**MOSCAP, "dut_profile": "moscap-bare"})
    assert result.outcome == "completed_with_flags", result.message
    refused = [a for a in result.analyses if a.outcome == "refused"]
    assert {a.method for a in refused} == {"cv_cox", "cv_flatband", "cv_doping_profile", "cv_vth"}
    assert all("moscap-bare has no geometry.area_um2" in (a.error or "") for a in refused)
    assert value(result, "cv_cox", "cox") == pytest.approx(moscap_truth().cox, rel=0.01)  # Cox needs no area


# -- split C-V -------------------------------------------------------------------------------------------------------


@recipe("mosfet.cgc_cv")
def test_cgc_plateau_is_cox_w_l(recipe_id: str, world: World, svc: B1500Service) -> None:
    world.use_scenario("nmos_cv")
    correct(svc, "mosfet-split-cv")
    plan, result = run(svc, {"recipe_id": recipe_id, **SPLIT})
    assert plan.confirm_reasons == ["unverified_pin_map"]
    assert result.ok and result.outcome == "completed", result.message
    truth = mosfet_truth().cv_truth()
    assert value(result, "cv_cox", "cox") == pytest.approx(truth["cox_wl_f"], rel=0.02)
    assert value(result, "cv_cox", "c_floor") == pytest.approx(truth["c_overlap_f"] / 2, rel=0.02)  # floating source
    assert value(result, "cv_cox", "eot") == pytest.approx(10e-9, rel=0.02)  # 10 nm SiO2
    assert value(result, "cv_vth", "vth") == pytest.approx(truth["vth_v"], abs=0.050)
    sent = [r for r in world.sim_log("nmos_cv") if r.outcome == "ok"]
    assert not any(r.mnemonic in ("CN", "DV") and "6" in r.args for r in sent)  # the source floats (SMU6 untouched)
    assert any(r.mnemonic == "DV" and r.args[:2] == ["4", "0"] for r in sent)  # the substrate SMU at 0 V


@recipe("mosfet.cgd_cv")
def test_cgd_sees_the_drain_half_of_the_channel(recipe_id: str, world: World, svc: B1500Service) -> None:
    world.use_scenario("nmos_cv")
    correct(svc, "mosfet-split-cv")
    plan, result = run(svc, {"recipe_id": recipe_id, **SPLIT})
    assert plan.summary is not None and "source=SMU6(MPSMU) ground 0 V" in plan.summary
    assert result.ok and result.outcome == "completed", result.message
    device = mosfet_truth()
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    expected = [device.gate_capacitance({"gate": v, "drain": 0.0, "source": 0.0, "bulk": 0.0}, 1e5, ("drain",))
                for v in table["dc_v"]]
    assert np.allclose(table["gate_Cp"], expected, rtol=0.01, atol=1e-15)
    truth = device.cv_truth()
    assert table["gate_Cp"].max() == pytest.approx(truth["cox_wl_f"] / 2, rel=0.03)
    assert value(result, "cv_vth", "vth") == pytest.approx(truth["vth_v"], abs=0.050)


# -- cmu.spot --------------------------------------------------------------------------------------------------------


@recipe("cmu.spot")
def test_spot_reads_the_100pf_standard_within_0_1_percent(recipe_id: str, world: World, svc: B1500Service) -> None:
    world.use_scenario("capacitor_100p")
    correct(svc, "capacitor-cmu")
    plan, result = run(svc, SPOT, samples=4)
    assert result.ok and result.outcome == "completed", result.message
    assert plan.summary is not None and "a=CMU1:H 100 kHz..1 MHz 30 mVrms DC 0 V" in plan.summary
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 8 and list(table.groupby("freq_hz").size()) == [4, 4]
    assert np.allclose(table["a_Cp"], 100e-12, rtol=1e-3)
    by_freq = {a.fit["freq_hz"]: a.value for a in result.analyses if a.method == "impedance_convert"
               and a.quantity == "cp"}
    assert by_freq == {1e5: pytest.approx(100e-12, rel=1e-3), 1e6: pytest.approx(100e-12, rel=1e-3)}
    series = svc.analyze_run(result.run_id, "impedance_convert", {"to": "cs_rs"})  # type: ignore[arg-type]
    assert series.ok and {r.quantity for r in series.results} == {"cs", "rs"}


@recipe("cmu.spot")
def test_spot_in_another_pair_writes_its_columns(recipe_id: str, world: World, svc: B1500Service) -> None:
    world.use_scenario("capacitor_100p")
    correct(svc, "capacitor-cmu")
    _, result = run(svc, SPOT, model="z_theta", samples=1, freqs_hz=[1e6])
    assert result.ok, result.message
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert {"a_Z", "a_theta"} <= set(table.columns)
    assert table["a_Z"].iloc[0] == pytest.approx(1 / (2 * np.pi * 1e6 * 100e-12), rel=1e-3)
    assert table["a_theta"].iloc[0] == pytest.approx(-np.pi / 2, abs=2e-3)


# -- SCUU path ---------------------------------------------------------------------------------------------------------


def with_scuu(world: World) -> None:
    """``moscap_basic`` behind an SCUU on CMU1 (``scuu: [7]``) and a station profile that records SCUU1 present."""
    data = scenario("moscap_basic")
    data["scuu"] = [7]
    world.write_config("sim/scenarios/moscap_scuu.yaml", data)
    world.use_scenario("moscap_scuu")
    station = yaml.safe_load((REPO_ROOT / "config/station.example.yaml").read_text(encoding="utf-8"))
    for switch in station["switches"]:
        if switch["id"] == "SCUU1":
            switch["present"] = True
    world.write_config("station.yaml", station)


@recipe("moscap.cv")
def test_moscap_cv_through_the_scuu_routes_to_the_mfcmu_and_back(recipe_id: str, world: World,
                                                                 svc: B1500Service) -> None:
    with_scuu(world)
    correct(svc, "moscap-scuu")
    plan, result = run(svc, {**MOSCAP, "pin_map": "moscap-scuu"})
    assert "unverified_topology" in plan.confirm_reasons
    assert plan.summary is not None and "gate=CMU1 via SCUU1.OUT1" in plan.summary
    assert result.ok and result.outcome == "completed", result.message
    record = manifest(world, result.run_id)  # type: ignore[arg-type]
    phases = record["plan"]["routes_by_phase"]
    assert [r["state"] for r in phases["measure"]] == ["cmu", "cmu"] and [r["state"] for r in phases["rest"]] == [
        "smu", "smu"]
    assert record["cleanup"]["switches_after"]["SCUU1.OUT1"] == "smu"
    sent = [r.command for r in world.sim_log("moscap_scuu") if r.outcome == "ok"]
    run_part = sent[sent.index("SSP 7,4"):]
    assert "SSP 7,3" in run_part and not any(c.startswith("CN") and "7" in c for c in run_part)
    assert value(result, "cv_cox", "cox") == pytest.approx(moscap_truth().cox, rel=0.01)


def test_corrections_of_the_direct_map_do_not_cover_the_scuu_map(world: World, svc: B1500Service) -> None:
    with_scuu(world)
    blocked = svc.validate_plan(**{**MOSCAP, "pin_map": "moscap-scuu"})
    assert blocked.tier == "blocked" and CORRECTION_NEXT_STEP in blocked.next_steps
    half = yaml.safe_load((REPO_ROOT / "config/pinmaps/moscap-scuu.example.yaml").read_text(encoding="utf-8"))
    half["terminals"]["bulk"] = "SCUU1.OUT1"  # both roles on the CMUH output
    world.write_config("pinmaps/moscap-scuu-bad.yaml", half)
    wrong = svc.validate_plan(**{**MOSCAP, "pin_map": "moscap-scuu-bad"})
    assert wrong.tier is None or wrong.tier == "blocked"
