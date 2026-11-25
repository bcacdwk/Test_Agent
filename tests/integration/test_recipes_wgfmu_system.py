"""Recipe validation of ``system.wgfmu_self_test`` and ``system.wgfmu_self_cal`` (kind ``system`` through the WGFMU
instrument library; WP10.7, blueprint v2 3.4) on the simulator. These tests set their ``status: sim_validated``.

- Tier: ``needs_confirmation`` with the v1 system reasons (open terminals and RSU outputs); no FLEX command, an empty
  envelope; the plan says ``library: true`` so the pre-execute snapshot reads the library's channel ids.
- Run: a WGFMU phase (FLEX lock released, open_session, initialize, the library's self-test or self-calibration,
  abort, initialize, close_session, FLEX relocked); ``kind_result`` names the result and the library path; no table.
- A library failure during the self-test fails the run with the WGFMU safe state verified; a scenario without a
  WGFMU (no channel listed) is blocked before execution (R-WG-01).
"""

from __future__ import annotations

import json

import pytest
import yaml

from b1500_test_agent.analysis.dataset import find_run
from tests.integration.async_helpers import run_events
from tests.integration.helpers import REPO_ROOT, World, plan, run

pytestmark = pytest.mark.wgfmu

CASES = [("system.wgfmu_self_test", "system_self_test", "self_test", "wgfmu_self_test"),
         ("system.wgfmu_self_cal", "system_self_cal", "self_calibration", "wgfmu_self_cal")]


def library_calls(world: World, run_id: str) -> list[str]:
    return [str((e.data or {}).get("fn")) for e in run_events(world, run_id) if e.ev == "wgfmu_call"]


@pytest.mark.parametrize(("recipe_id", "reason", "call", "operation"), CASES)
def test_wgfmu_system_recipes_on_the_simulator(world: World, recipe_id: str, reason: str, call: str,
                                               operation: str) -> None:
    world.use_scenario("nmos_bti")
    executor = world.executor()
    record = plan(executor, recipe_id=recipe_id, pin_map="mosfet-wgfmu", dut_profile=None)
    assert record.tier == "needs_confirmation" and record.rules.confirm_reasons == [reason]
    assert record.flex_preview == [] and record.envelope.channels == {}
    assert record.program["sources"]["library"] is True
    assert record.summary == f"{recipe_id}@1 | no outputs | DUT none | pins mosfet-wgfmu | sim | R-ALWAYS-01 {reason}"
    assert run(executor, record.plan_id).error_code == "confirmation_required"
    result = run(executor, record.plan_id, record.summary)
    assert result.ok and result.outcome == "completed" and result.cleanup_verified == "sim_state", result.message
    assert result.quality_verdict is None and result.analyses == []
    folder = find_run(result.run_id, data_root=world.data)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind_result"] == {"operation": operation, "result": 0, "failed_units": "",
                                       "via": "WGFMU instrument library"}
    assert not (folder / "data.csv").exists()
    pre = next(r for r in manifest["rules"] if r["phase"] == "pre_execute")
    assert not [f for f in pre["findings"] if f["rule_id"] == "R-WG-01" and f["severity"] == "block"]
    calls = library_calls(world, result.run_id)
    phase = calls[calls.index("open_session", calls.index("close_session")):]  # after the snapshot's channel read
    assert phase[:3] == ["open_session", "initialize", call]
    assert phase[-1] == "close_session" and {"abort", "initialize"} <= set(phase[3:])
    assert manifest["assumptions"] and any("WGFMU phase" in a or "unlocked" in a for a in manifest["assumptions"])
    assert not [r for r in world.sim_log("nmos_bti") if r.command.startswith(("CN", "DV", "*TST?", "*CAL?"))]


def test_a_library_failure_during_the_self_test_fails_the_run_with_a_safe_state(world: World) -> None:
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_bti.yaml").read_text(encoding="utf-8"))
    scenario["faults"] = "selftest_error"
    world.write_config("sim/faults/selftest_error.yaml", {"description": "test", "faults": [
        {"kind": "wgfmu_error", "fn": "self_test", "code": -11}]})
    world.write_config("sim/scenarios/nmos_bti_selftest.yaml", scenario)
    world.use_scenario("nmos_bti_selftest")
    executor = world.executor()
    record = plan(executor, recipe_id="system.wgfmu_self_test", pin_map="mosfet-wgfmu", dut_profile=None)
    result = run(executor, record.plan_id, record.summary)
    assert not result.ok and result.outcome == "failed" and result.cleanup_verified == "sim_state", result.message
    calls = library_calls(world, result.run_id)
    assert calls[-1] == "close_session" and "abort" in calls[calls.index("self_test"):]


def test_a_mainframe_without_a_wgfmu_is_blocked_before_execution(world: World) -> None:
    """R-WG-01 for a library plan: the pre-execute snapshot lists no WGFMU channel (no B1530A on this mainframe)."""
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_bti.yaml").read_text(encoding="utf-8"))
    scenario["slots"] = [s for s in scenario["slots"] if s["model"] != "B1530A"]
    scenario.pop("rsu_smu")
    scenario["wiring"]["dut"].update(gate=4, drain=3)
    scenario["wiring"]["gox"]["top"] = 4
    world.write_config("sim/scenarios/nmos_no_wgfmu.yaml", scenario)
    world.use_scenario("nmos_no_wgfmu")
    executor = world.executor()
    record = plan(executor, recipe_id="system.wgfmu_self_test", pin_map="mosfet-4t", dut_profile=None)
    result = run(executor, record.plan_id, record.summary)
    assert not result.ok and result.error_code in ("blocked_by_rules", "precondition_failed"), result
    assert "R-WG-01" in (result.message or "")
