"""QSCV and Dit over the band gap on the simulator (blueprint v2 10.4 row 8.5 AC, per-recipe AC; WP8.5):
``moscap.qscv`` (kind ``smu_qscv``, MM 13) and ``moscap.cv_multi_freq`` (kind ``cmu_measure``, MM 18 per frequency) on
``moscap_dit``, whose MOS capacitor is landed through the SCUU of CMU1 (pin map ``moscap-scuu``): the same landing
serves the SMUs (``SSP 7,3``) and the MFCMU (``SSP 7,4``).

Fidelity against the model truth of the scenario's device (blueprint v2 4.2; WP AC): QSCV Cox within 2 %, Dit within
30 % (high-low at midgap and over its energy window; conductance at every counted bias), the leakage the instrument
compensates (the fixture's 1 GOhm path plus the oxide) within 2 %. The offset measurement asks for ``physical_setup``
and stores the path's guard capacitance; ``offset: cancel`` removes it. The SCUU I-V -> C-V same-landing test routes
the SMU path, then the MFCMU path, and the cleanup leaves the SCUU at rest after both.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.models.sim import MoscapParams
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from b1500_test_agent.transport.sim.units.qscv import QSCV_STRAY_F
from tests.integration.helpers import REPO_ROOT, World

pytestmark = pytest.mark.cmu

CORRECTIONS = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")
DIT = {"pin_map": "moscap-scuu", "dut_profile": "moscap-generic"}
QSCV = {"recipe_id": "moscap.qscv", **DIT}
HF = {"recipe_id": "moscap.cv", **DIT}
MULTI = {"recipe_id": "moscap.cv_multi_freq", **DIT}


def recipe(recipe_id: str) -> pytest.MarkDecorator:
    """Parametrize with the recipe id, so ``pytest tests/integration -k <recipe id>`` selects the test."""
    return pytest.mark.parametrize("recipe_id", [recipe_id])


def device() -> MoscapDevice:
    data = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/moscap_dit.yaml").read_text(encoding="utf-8"))
    return MoscapDevice("dut", MoscapParams(**data["models"]["dut"]["params"]))


def correct(svc: B1500Service) -> None:
    """Phase compensation, open and short through the SCUU (each confirmed with its own summary)."""
    for name in CORRECTIONS:
        plan = svc.validate_plan(recipe_id=name, pin_map="moscap-scuu")
        assert plan.tier == "needs_confirmation" and plan.summary is not None, plan.message
        assert svc.run_confirmed_plan(plan.plan_id, summary=plan.summary).ok  # type: ignore[arg-type]


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


def sent(world: World) -> list[str]:
    return [r.command for r in world.sim_log("moscap_dit") if r.outcome == "ok"]


@pytest.fixture
def svc(world: World) -> B1500Service:
    world.use_scenario("moscap_dit")
    return world.service()


# -- moscap.qscv ------------------------------------------------------------------------------------------------------


@recipe("moscap.qscv")
def test_qscv_meets_the_cox_target_with_its_leakage_compensated(recipe_id: str, world: World,
                                                                svc: B1500Service) -> None:
    plan, result = run(svc, QSCV)
    assert set(plan.confirm_reasons) == {"unverified_pin_map", "unverified_topology"}
    assert plan.summary is not None and "gate=SMU6(MPSMU) via SCUU1.OUT1 sweep 2..-2.5 V Icomp 1 uA" in plan.summary
    assert result.ok and result.outcome == "completed" and result.simulated, result.message
    assert result.cleanup_verified == "sim_state" and result.quality_verdict == "ok"
    truth = device()
    assert value(result, "cv_cox", "cox") == pytest.approx(truth.cox, rel=0.02)  # WP AC: QSCV Cox +-2 %
    assert value(result, "cv_cox", "eot") == pytest.approx(5e-9, rel=0.02)
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert list(table.columns) == ["step", "dc_v", "gate_Cp", "gate_Cp_status", "gate_I", "gate_I_status", "trust"]
    assert len(table) == 89 and table["dc_v"].iloc[0] == pytest.approx(1.95) and table["dc_v"].iloc[-1] == -2.45
    assert set(table["gate_Cp_status"]) == {"N"} and set(table["gate_I_status"]) == {"N"}
    g = 1.0 / 1.0e9 + truth.params.leak_s  # the fixture's open path (1 GOhm) and the oxide, both linear
    assert np.allclose(table["gate_I"], g * table["dc_v"], rtol=0.02, atol=2e-12)
    depletion = table[(table["dc_v"] > -0.8) & (table["dc_v"] < 0.1)]  # quasi-static dQ/dV, the leakage removed
    q = np.array([(truth.charge(v + 0.025) - truth.charge(v - 0.025)) / 0.05 for v in depletion["dc_v"]])
    assert np.allclose(depletion["gate_Cp"] - QSCV_STRAY_F, q, rtol=0.03)
    record = manifest(world, result.run_id)  # type: ignore[arg-type]
    assert record["kind_result"]["measurement_mode"] == 13 and record["kind_result"]["aborted"] is False
    leak_max = float(np.max(np.abs(table["gate_I"])))  # the L6 QSCV leakage check reads it (WP8.6)
    assert record["kind_result"]["leakage_max_a"] == pytest.approx(leak_max, rel=1e-6) and leak_max < 3e-9  # 1 GOhm
    plots = svc.analyze_run(result.run_id, "plot_cv")  # type: ignore[arg-type]
    assert plots.ok and [p.rsplit("/", 1)[-1] for p in plots.plots] == ["qscv-1.png"], plots.message
    refused = svc.analyze_run(result.run_id, "cv_flatband")  # type: ignore[arg-type]
    assert not refused.ok


@recipe("moscap.qscv")
def test_offset_measurement_needs_the_probes_lifted_and_cancel_removes_it(recipe_id: str, world: World,
                                                                          svc: B1500Service) -> None:
    plan, result = run(svc, QSCV, offset="measure")
    assert "physical_setup" in plan.confirm_reasons
    assert any(f.rule_id == "R-ALWAYS-01" and "lift the probes" in f.message for f in plan.findings)
    assert result.ok, result.message
    offset = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(offset) == 1 and offset["gate_Cp"].iloc[0] == pytest.approx(QSCV_STRAY_F, rel=0.5)
    commands = sent(world)
    assert "QSZ 2" in commands and "XE" not in commands[commands.index("QSZ 2") - 12:]
    _, plain = run(svc, QSCV)
    _, cancelled = run(svc, QSCV, offset="cancel")
    assert "QSZ 1" in sent(world)
    a = load_run(plain.run_id, data_root=world.data).table  # type: ignore[arg-type]
    b = load_run(cancelled.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert float(np.median(a["gate_Cp"] - b["gate_Cp"])) == pytest.approx(offset["gate_Cp"].iloc[0], abs=0.1e-12)


@recipe("moscap.qscv")
def test_high_low_dit_meets_the_truth_over_the_gap(recipe_id: str, world: World, svc: B1500Service) -> None:
    run(svc, QSCV, offset="measure")
    _, lf = run(svc, QSCV, offset="cancel")
    correct(svc)
    _, hf = run(svc, HF)
    assert lf.ok and hf.ok
    analysed = svc.analyze_run(lf.run_id, "dit_high_low", {"reference_run": hf.run_id})  # type: ignore[arg-type]
    assert analysed.ok, analysed.message
    found = {r.quantity: r for r in analysed.results}
    truth = device()
    assert found["dit_mid"].value == pytest.approx(truth.es.dit(0.0), rel=0.30)  # WP AC: Dit +-30 %
    fit = found["dit_mid"].fit
    samples = [k for k in range(40) if f"e{k}" in fit]
    assert len(samples) >= 8 and fit["e_min"] < -0.2 and fit["e_max"] > 0.2
    for k in samples:
        assert fit[f"dit{k}"] == pytest.approx(truth.es.dit(fit[f"e{k}"]), rel=0.30), fit[f"e{k}"]
    assert found["dit_mean"].value == pytest.approx(np.mean([truth.es.dit(fit[f"e{k}"]) for k in samples]), rel=0.30)
    swapped = svc.analyze_run(hf.run_id, "dit_high_low", {"reference_run": lf.run_id})  # type: ignore[arg-type]
    assert swapped.ok and next(r.value for r in swapped.results if r.quantity == "dit_mid") == pytest.approx(
        found["dit_mid"].value, rel=1e-6)


# -- moscap.cv_multi_freq ---------------------------------------------------------------------------------------------


@recipe("moscap.cv_multi_freq")
def test_multi_frequency_cv_gives_dit_by_the_conductance_method(recipe_id: str, world: World,
                                                                svc: B1500Service) -> None:
    blocked = svc.validate_plan(**MULTI)
    assert blocked.tier == "blocked" and any(f.rule_id == "R-CORR-01" for f in blocked.findings)
    correct(svc)
    plan, result = run(svc, MULTI)
    assert set(plan.confirm_reasons) == {"unverified_pin_map", "dut_envelope", "unverified_topology"}
    assert result.ok and result.outcome == "completed", result.message
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 10 * 81 and sorted(set(table["freq_hz"])) == [1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5,
                                                                         1e6]
    truth = device()
    assert value(result, "cv_cox", "cox") == pytest.approx(truth.cox, rel=0.02)
    dit = next(a for a in result.analyses if a.method == "dit_conductance" and a.quantity == "dit_mean")
    assert dit.outcome == "ok", dit.error
    counted = [k for k in range(200) if f"v{k}" in dit.fit]
    assert len(counted) >= 5
    for k in counted:
        bias = dit.fit[f"v{k}"]
        expected = truth.interface_trap_truth(bias, 1e5)
        assert dit.fit[f"dit{k}"] == pytest.approx(expected["dit_cm2_ev"], rel=0.30), bias  # WP AC: Dit +-30 %
        assert dit.fit[f"e{k}"] == pytest.approx(expected["e_minus_ei_ev"], abs=0.03), bias
    assert value(result, "dit_conductance", "tau_min") < value(result, "dit_conductance", "tau_max")


# -- SCUU I-V -> C-V on one landing -----------------------------------------------------------------------------------


@recipe("moscap.qscv")
def test_scuu_routes_the_smus_then_the_mfcmu_on_the_same_landing(recipe_id: str, world: World,
                                                                 svc: B1500Service) -> None:
    _, qscv = run(svc, QSCV)
    record = manifest(world, qscv.run_id)  # type: ignore[arg-type]
    smu = [{"switch": "SCUU1", "output": "OUT1", "state": "smu"}, {"switch": "SCUU1", "output": "OUT2", "state": "smu"}]
    assert record["plan"]["routes_by_phase"] == {"measure": smu}
    after = record["cleanup"]["switches_after"]
    assert (after["SCUU1.OUT1"], after["SCUU1.OUT2"]) == ("smu", "smu")
    commands = sent(world)
    part = commands[commands.index("SSP 7,3"):]
    assert part.index("SSP 7,3") < part.index("DV 5,0,0,1E-06") < part.index("MM 13,6") < part.index("XE")
    assert not any(c.startswith("CN") for c in commands)  # the SCUU's modules are switched by SSP only
    correct(svc)
    _, cv = run(svc, HF)
    record = manifest(world, cv.run_id)  # type: ignore[arg-type]
    assert [r["state"] for r in record["plan"]["routes_by_phase"]["measure"]] == ["cmu", "cmu"]
    assert [r["state"] for r in record["plan"]["routes_by_phase"]["rest"]] == ["smu", "smu"]
    after = record["cleanup"]["switches_after"]
    assert (after["SCUU1.OUT1"], after["SCUU1.OUT2"]) == ("smu", "smu")
    commands = sent(world)
    part = commands[len(commands) - 1 - commands[::-1].index("SSP 7,4"):]
    assert part.index("SSP 7,4") < part.index("MM 18,7") < part.index("XE") < part.index("SSP 7,3")
    # one device, one landing: the quasi-static and the 1 MHz curve agree in accumulation
    assert value(qscv, "cv_cox", "cox") == pytest.approx(value(cv, "cv_cox", "cox"), rel=0.01)
    assert world.sim_log("moscap_dit") and not [c for c in sent(world) if c.startswith("CN")]
