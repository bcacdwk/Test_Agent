"""``system.selector_check`` and the live route rules through ``B1500Service`` on the simulator (blueprint v2 3.3,
2.8 R-ROUTE-01/02, 2.6 steps 5 and 8; WP9.2 per-recipe AC): tier as the card says, the confirmed run steps every
declared output through its states with each read back, the cleanup verifies every selector at rest; a stuck selector
fails the run and latches the fault (``cleanup_unverified``); a selector left switched blocks the plan before the run;
``pgu_open`` on a CH 2 port and a Kelvin role through a selector are blocked."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from b1500_test_agent.models.plan import PlanRequest
from b1500_test_agent.models.routing import Route
from b1500_test_agent.rules.engine import RulesEngine
from b1500_test_agent.rules.tiers import with_rules
from tests.integration.helpers import REPO_ROOT, World
from tests.sim.helpers import load_scenario
from tests.sim.selector_helpers import recorded_station

RECIPE = "system.selector_check"
pytestmark = [pytest.mark.spgu, pytest.mark.parametrize("recipe_id", [RECIPE])]
"""Every test carries the recipe id, so ``pytest tests/integration -k system.selector_check`` selects them (per-recipe
AC of blueprint v2 10)."""

REQUEST: dict[str, Any] = {"recipe_id": RECIPE, "params": {}, "pin_map": "fefet-sel"}  # the card's example plan
SEQUENCE = ("SEL1.OUT1 smu,pgu,pgu_open,open; SEL1.OUT2 smu,pgu,open; SEL2.OUT1 smu,pgu,pgu_open,open; "
            "SEL2.OUT2 smu,pgu,open")
AT_REST = {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open",
           "SCUU1.OUT1": "not installed", "SCUU1.OUT2": "not installed", "ASU3.OUT": "not installed",
           "ASU4.OUT": "not installed"}


def lab_station_with(world: World, faults: list[dict[str, Any]] | None = None) -> str:
    """Select ``lab_station`` (with a fault profile copy when ``faults`` are given); returns the scenario name."""
    if not faults:
        world.use_scenario("lab_station")
        return "lab_station"
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/lab_station.yaml").read_text(encoding="utf-8"))
    scenario["faults"] = "selector_faults"
    world.write_config("sim/faults/selector_faults.yaml", {"description": "test", "faults": faults})
    world.write_config("sim/scenarios/lab_selector_faults.yaml", scenario)
    world.use_scenario("lab_selector_faults")
    return "lab_selector_faults"


def confirmed(world: World) -> Any:
    service = world.service()
    validation = service.validate_plan(**REQUEST)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    return service, validation, service.run_confirmed_plan(validation.plan_id, summary=validation.summary)


def manifest(world: World, run_id: str) -> dict[str, Any]:
    folder = next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def test_card_example_needs_the_topology_confirmation(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    validation = world.service().validate_plan(**REQUEST)
    assert validation.ok and validation.tier == "needs_confirmation"
    assert sorted(validation.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    assert validation.summary is not None and "no outputs" in validation.summary
    assert "routes SEL1.OUT1->pgu,pgu_open,smu; SEL1.OUT2->pgu,smu" in validation.summary


def test_a_recorded_station_with_a_verified_pin_map_is_tier_ok(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    world.write_config("station.yaml", recorded_station())
    pin_map = yaml.safe_load((REPO_ROOT / "config/pinmaps/fefet-sel.example.yaml").read_text(encoding="utf-8"))
    world.write_config("pinmaps/fefet-sel.yaml", {**pin_map, "certainty": "verified"})
    validation = world.service().validate_plan(**REQUEST)
    assert validation.ok and validation.tier == "ok", validation.message


def test_selector_check_steps_every_declared_output_and_ends_at_rest(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    _, validation, result = confirmed(world)
    assert result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state" and result.backend == "sim"
    data = manifest(world, str(result.run_id))
    assert data["kind_result"] == {"mode": "route_only", "outputs_checked": 4, "states_verified": 14,
                                   "sequence": SEQUENCE}
    assert data["cleanup"]["switches_after"] == AT_REST and not data["cleanup"]["latched_fault"]
    assert data["confirmed_summary"] == validation.summary
    routes = [e for e in world.audit_events() if e.ev == "checkpoint" and e.data and e.data.get("label") == "routes"]
    assert len(routes) == 14 and all(e.error is None for e in routes)
    assert [e.data["routes"] for e in routes[:4]] == [  # type: ignore[index]
        "SEL1.OUT1->smu", "SEL1.OUT1->pgu", "SEL1.OUT1->pgu_open", "SEL1.OUT1->open"]
    log = world.sim_log("lab_station")
    assert not [r for r in log if r.source] and not [r for r in log if r.mnemonic in ("CN", "SRP", "DV")]
    erssp = [r.command for r in log if r.mnemonic == "ERSSP" and r.outcome == "ok"]
    planned = {f"ERSSP {p},{c}" for p, codes in ((0, (1, 2, 3)), (1, (1, 2)), (2, (1, 2, 3)), (3, (1, 2)))
               for c in codes}
    assert {c for c in erssp if not c.endswith(",0")} == planned  # no route outside the plan reached the instrument


def test_a_stuck_selector_fails_the_run_and_latches_the_fault(recipe_id: str, world: World) -> None:
    lab_station_with(world, [{"kind": "selector_stuck", "port": 2, "state": "pgu"}])
    service = world.service()
    validation = service.validate_plan(**REQUEST)
    # the stuck port reads pgu before the run: the pre-execute check of R-ROUTE-01 refuses with zero routes, and the
    # refused transaction's cleanup cannot return the port: cleanup_unverified, fault latched
    result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert not result.ok and result.status == "fault" and result.error_code == "cleanup_unverified"
    assert result.cleanup_verified == "unverified"
    data = manifest(world, str(result.run_id))
    pre = next(r for r in data["rules"] if r["phase"] == "pre_execute")
    assert pre["tier"] == "blocked" and any("SEL2.OUT1 is pgu" in f["message"] for f in pre["findings"])
    assert data["cleanup"]["switches_after"]["SEL2.OUT1"] == "pgu" and data["cleanup"]["latched_fault"]
    log = world.sim_log("lab_selector_faults")
    assert [r.command for r in log if r.mnemonic == "ERSSP" and not r.command.endswith(",0")] == []
    status = service.station_status()
    assert status.status == "fault" and status.fault is not None
    assert status.switches["SEL2.OUT1"] == "off rest: pgu (rest open)"


def test_a_selector_that_sticks_during_the_check_stops_it(recipe_id: str, world: World) -> None:
    """The check itself finds the stuck relay: port 1 does not follow ERSSP once switched (``RouteNotVerified``)."""
    lab_station_with(world, [{"kind": "selector_stuck", "port": 1, "state": "open"}])
    _, _, result = confirmed(world)
    assert not result.ok and result.outcome == "failed" and "SEL1.OUT2 reads open, set smu" in result.message
    assert result.cleanup_verified == "sim_state"  # a port stuck open is at rest: the cleanup verifies


def test_a_selector_left_switched_blocks_the_plan_until_the_cleanup_returns_it(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    service = world.service()
    validation = service.validate_plan(**REQUEST)
    session = service.executor.session(service.config.get())
    with session.transaction(intent="human leaves SEL1.OUT1 on PGU", envelope=None, run=None) as tx:
        tx.driver.transport.write("ERMOD 1")
        tx.driver.transport.write("ERSSP 0,2")
        tx._cleanup_done = True  # a human at the front panel: no cleanup of this "transaction"
    status = service.station_status()
    assert status.switches["SEL1.OUT1"] == "off rest: pgu (rest open)" and "off rest" in status.message
    refused = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert refused.error_code == "blocked_by_rules" and "SEL1.OUT1 is pgu, not its rest state open" in refused.message
    assert service.station_status().switches["SEL1.OUT1"] == "open"  # the refusal's cleanup returned it
    rerun = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert rerun.ok and rerun.outcome == "completed", rerun.message


def test_pgu_open_on_a_ch2_port_is_blocked(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    executor = world.executor()
    bundle = executor.config.get()
    planner = executor._planner(bundle)
    draft, error = planner.draft(PlanRequest.model_validate(REQUEST), bundle)
    assert error is None
    bad = Route(switch="SEL1", output="OUT2", state="pgu_open")  # port 1 = CH 2 of the first selector
    tampered = draft.model_copy(update={
        "envelope": draft.envelope.model_copy(update={"routes": draft.envelope.routes | {bad}}),
        "routes_by_phase": {**draft.routes_by_phase, "check-99": [bad]}})
    report = RulesEngine(bundle).evaluate(planner.context(tampered, bundle), "plan")
    assert with_rules(tampered, report).tier == "blocked"
    blocks = [f for f in report.findings if f.rule_id == "R-ROUTE-01" and f.severity == "block"]
    assert any("PGU-open state exists only on selector CH 1 (ports 0, 2), not port 1" in f.message for f in blocks)


def test_a_kelvin_role_through_a_selector_is_blocked(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    world.write_config("station.yaml", recorded_station())
    world.write_config("pinmaps/kelvin-sel.yaml", {"description": "Kelvin a behind SEL1", "certainty": "verified",
                                                    "terminals": {"a": "SEL1.OUT1", "b": "GNDU"}})
    validation = world.service().validate_plan(recipe_id="resistor.kelvin_4w", pin_map="kelvin-sel",
                                               dut_profile="resistor-1r")
    assert validation.tier == "blocked"
    rules = {f.rule_id for f in validation.findings if f.severity == "block"}
    assert "R-ROUTE-01" in rules
    assert any("Kelvin role but reaches its terminal through selector SEL1" in f.message for f in validation.findings)


def test_a_station_without_selectors_cannot_compile_the_check(recipe_id: str, world: World) -> None:
    lab_station_with(world)
    station = recorded_station()
    for switch in station["switches"]:
        if switch["kind"] == "selector_16440a":
            switch["present"] = False
    world.write_config("station.yaml", station)
    validation = world.service().validate_plan(**REQUEST)
    assert not validation.ok and validation.error_code == "invalid_input"
    assert "declares no 16440A selector" in validation.message


def test_lab_station_scenario_cables_both_selectors(recipe_id: str) -> None:
    scenario = load_scenario("lab_station")
    assert {p: (c.smu, c.pgu) for p, c in scenario.selectors.items()} == {
        0: (3, 101), 1: (None, 102), 2: (5, None), 3: (6, None)}
    fefet = load_scenario("fefet_lab")
    assert fefet.wiring["dut"]["gate"] == "SELPORT0" and fefet.selectors == scenario.selectors
