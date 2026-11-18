"""Service-level integration (blueprint 2.9, 8.1 ``integration/``): the vertical path through ``B1500Service``,
``tool_call`` audit events, config reload and ``invalid_config``, and ``b1500 fault clear`` refusing while the
cleanup is unverified."""

from __future__ import annotations

import json

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.analysis import load_run
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.service import TOOL_NAMES, B1500Admin, args_digest
from tests.integration.helpers import IDVG, World

VTH0 = 0.42
"""Truth of config/sim/scenarios/nmos_basic.yaml."""

runner = CliRunner()


def tool_calls(world: World) -> list[AuditEvent]:
    return [e for e in world.audit_events() if e.ev == "tool_call"]


def test_vertical_path_status_validate_run_get_analyze(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1500_SESSION_TAG", "s1-vertical")
    service = world.service(adapter="mcp")
    status = service.station_status()
    assert status.ok and status.simulated and status.backend == "sim" and status.live == "fresh"
    assert status.identity is not None and "B1500A" in status.identity
    assert all(m.match for m in status.modules) and status.fault is None and status.lock_holder is None
    assert status.pin_maps == {"mosfet-4t": "verified", "diode-2t": "verified", "resistor-2t": "verified",
                               "mosfet-3t-lab": "unverified", "fefet-sel": "unverified", "fecap-wgfmu": "unverified",
                               "moscap-cmu": "unverified"}
    assert "nmos-generic" in status.dut_profiles
    assert status.config is not None and status.config.ok and status.limits is not None

    plan = service.validate_plan(**IDVG, label="W3 batch")
    assert plan.ok and plan.status == "ok" and plan.tier == "ok" and plan.plan_id
    assert plan.resolved is not None and plan.resolved.channels == {"drain": "SMU3(HRSMU)", "gate": "SMU4(HRSMU)",
                                                                    "source": "GNDU"}
    assert plan.resolved.points == 101 and plan.resolved.max_v == 3.0

    run = service.run_plan(plan.plan_id, dut_instance="W3-D12")
    assert run.ok and run.outcome == "completed" and run.cleanup_verified == "sim_state", run.message
    assert run.run_id is not None and run.simulated

    detail = service.get_run(run.run_id, include=["summary", "quality", "data", "audit", "notes"])
    assert detail.ok and detail.run is not None and detail.run.outcome == "completed"
    assert detail.run.dut_instance == "W3-D12" and detail.run.client == "mcp:s1-vertical"
    assert detail.quality is not None and detail.quality.verdict == "ok"
    assert detail.data is not None and detail.data.rows_total == 101 and 2 <= detail.data.rows_returned <= 101
    assert detail.data.rows[0][0] == 0 and detail.data.rows[-1][0] == 100  # first and last row kept
    assert detail.notes == [] and detail.audit

    analysis = service.analyze_run(run.run_id, "vth_linear_extrapolation")
    assert analysis.ok and analysis.status == "ok" and analysis.simulated
    vth = analysis.results[0]
    assert vth.quantity == "vth" and vth.unit == "V" and vth.derived
    assert vth.value == pytest.approx(VTH0, abs=0.100)
    assert analysis.artifact is not None and analysis.artifact.endswith("analysis/vth_linear_extrapolation-2.json")
    stored = json.loads((world.run_dirs()[0] / "analysis" / "vth_linear_extrapolation-2.json").read_text("utf-8"))
    assert stored["source"] == "analyze_run" and stored["results"][0]["value"] == vth.value

    calls = tool_calls(world)
    assert [e.data["tool"] for e in calls if e.data] == ["station_status", "validate_plan", "run_plan", "get_run",
                                                         "analyze_run"]
    for event in calls:
        assert event.data is not None and event.data["adapter"] == "mcp"
        assert event.data["session_tag"] == "s1-vertical" and len(str(event.data["args_sha256"])) == 16
    run_call = calls[2].data
    assert run_call is not None and run_call["plan_id"] == plan.plan_id and run_call["run_id"] == run.run_id
    assert run_call["args_sha256"] == args_digest({"plan_id": plan.plan_id, "dut_instance": "W3-D12"})
    assert load_run(run.run_id, data_root=world.data).manifest.client.session_tag == "s1-vertical"


def test_needs_confirmation_flow_and_summary_echo(world: World) -> None:
    service = world.service(adapter="mcp")
    plan = service.validate_plan(**IDVG, params={"vg_stop": 3.5})
    assert plan.ok and plan.status == "needs_confirmation" and plan.confirm_reasons == ["dut_envelope"]
    before = world.io_marker()
    refused = service.run_plan(plan.plan_id)
    assert not refused.ok and refused.error_code == "confirmation_required" and refused.summary == plan.summary
    wrong = service.run_confirmed_plan(plan.plan_id, summary="yes")
    assert wrong.error_code == "summary_mismatch" and wrong.summary == plan.summary
    assert world.io_marker() == before
    again = service.validate_plan(plan_id=plan.plan_id)
    assert again.summary == plan.summary and again.tier == "needs_confirmation"
    confirmed = service.run_confirmed_plan(plan.plan_id, summary=plan.summary)
    assert confirmed.ok and confirmed.outcome == "completed"
    manifest = load_run(confirmed.run_id, data_root=world.data).manifest  # type: ignore[arg-type]
    assert manifest.confirmed_via == "run_confirmed_plan" and manifest.confirmed_summary == plan.summary


def test_blocked_and_not_implemented_plans(world: World) -> None:
    service = world.service()
    blocked = service.validate_plan(**IDVG, params={"vg_stop": 60.0})
    assert not blocked.ok and (blocked.status, blocked.error_code) == ("blocked", "blocked_by_rules")
    assert {f.rule_id for f in blocked.findings if f.severity == "block"} >= {"R-PARAM-01", "R-LIM-02"}
    reserved = service.validate_plan(recipe_id="wgfmu.pulsed_iv", pin_map="mosfet-4t", dut_profile="nmos-generic")
    assert (reserved.status, reserved.error_code, reserved.tier) == ("not_implemented", "not_implemented", "blocked")
    both = service.validate_plan(recipe_id="mosfet.idvg", plan_id=blocked.plan_id)
    assert (both.status, both.error_code) == ("refused", "invalid_input")
    unknown = service.validate_plan(recipe_id="mosfet.nope", pin_map="mosfet-4t")
    assert (unknown.status, unknown.error_code) == ("refused", "invalid_input")
    bad_type = service.validate_plan(recipe_id="mosfet.idvg", pin_map="Not A Name!")
    assert bad_type.error_code == "invalid_input" and "pin_map" in bad_type.message
    assert world.io_marker() == (0, 0, 0, False)


def test_config_is_reloaded_on_every_call(world: World) -> None:
    service = world.service()
    assert service.validate_plan(**IDVG).tier == "ok"
    world.write_config("policy.yaml", {"soft_limits": {"voltage_v": 2.0, "compliance_a": 0.01}})
    tightened = service.validate_plan(**IDVG)
    assert tightened.tier == "needs_confirmation" and "soft_limit" in tightened.confirm_reasons
    status = service.station_status(refresh=False)
    assert status.limits is not None and status.limits.soft_voltage_v == 2.0
    assert status.live == "not_read" and status.config is not None
    assert {f.key: f.source for f in status.config.files}["policy"] == "override"


def test_invalid_config_refuses_execution_but_status_answers(world: World) -> None:
    service = world.service()
    good = service.validate_plan(**IDVG)
    assert good.ok
    world.write_config("policy.yaml", {"hard_limits": {"max_abs_voltage_v": 60.0}})  # above the code ceiling
    before = world.io_marker()
    status = service.station_status()
    assert not status.ok and (status.status, status.error_code) == ("error", "invalid_config")
    assert status.config is not None and not status.config.ok and status.config.problems
    assert any("ceiling" in p.message for p in status.config.problems)
    for result in (service.validate_plan(**IDVG), service.run_plan(good.plan_id or ""),
                   service.run_confirmed_plan(good.plan_id or "", summary="x"), service.list_recipes(),
                   service.list_runs(), service.get_run("S20261117T000000Z-0000"),
                   service.analyze_run("S20261117T000000Z-0000", "quality_report"),
                   service.annotate_run("S20261117T000000Z-0000", "x")):
        assert not result.ok and result.error_code == "invalid_config", type(result).__name__
        assert result.backend == "sim" and result.simulated
    assert world.io_marker() == before  # nothing reached the instrument
    # safe_shutdown is never gated: it uses this process's last valid configuration
    shutdown = service.safe_shutdown(reason="config broke")
    assert shutdown.ok and shutdown.cleanup is not None and shutdown.cleanup.verified == "sim_state"
    assert "last valid configuration" in shutdown.message
    events = tool_calls(world)
    assert {e.data["tool"] for e in events if e.data} == set(TOOL_NAMES)
    assert any(e.data and e.data["error_code"] == "invalid_config" for e in events)


def test_safe_shutdown_without_any_valid_config_refuses(world: World) -> None:
    world.write_config("policy.yaml", {"hard_limits": {"max_abs_voltage_v": 60.0}})
    result = world.service().safe_shutdown(reason="x")
    assert not result.ok and result.error_code == "invalid_config"


def test_fault_clear_refuses_while_cleanup_is_unverified(world: World) -> None:
    world.use_faults("stuck_gate", [{"kind": "ignore_dz", "channels": [4]}])
    env = world.env()
    planned = runner.invoke(app, ["plan", "mosfet.idvg", "--pin-map", "mosfet-4t", "--dut", "nmos-generic",
                                  "--json"], env=env)
    assert planned.exit_code == 0, planned.output
    plan_id = json.loads(planned.stdout)["plan_id"]
    ran = runner.invoke(app, ["run", plan_id, "--json"], env=env)
    assert ran.exit_code == 1
    result = json.loads(ran.stdout)
    assert result["status"] == "fault" and result["cleanup_verified"] == "unverified"

    status = runner.invoke(app, ["status", "--json"], env=env)
    assert status.exit_code == 1 and json.loads(status.stdout)["error_code"] == "fault_latched"
    again = runner.invoke(app, ["run", plan_id, "--json"], env=env)
    assert again.exit_code == 1 and json.loads(again.stdout)["error_code"] in ("blocked_by_rules", "fault_latched")

    refused = runner.invoke(app, ["fault", "clear", "--by", "owner", "--json"], env=env)
    assert refused.exit_code == 1, refused.output
    payload = json.loads(refused.stdout)
    assert payload["error_code"] == "cleanup_unverified" and not payload["cleared"]
    assert payload["fault"] is not None and payload["cleanup"]["verified"] == "unverified"
    assert any("could not verify" in r for r in payload["reasons"])

    scenario = yaml.safe_load((world.cfg / "sim/scenarios/nmos_stuck_gate.yaml").read_text(encoding="utf-8"))
    scenario["faults"] = None  # the stuck relay was repaired; same scenario, same persisted instrument state
    world.write_config("sim/scenarios/nmos_stuck_gate.yaml", scenario)
    cleared = runner.invoke(app, ["fault", "clear", "--by", "owner"], env=env)
    assert cleared.exit_code == 0, cleared.output
    assert "fault latch cleared by owner" in cleared.stdout
    assert any(e.ev == "fault_cleared" and e.data and e.data["by"] == "owner" for e in world.audit_events())
    nothing = runner.invoke(app, ["fault", "clear", "--json"], env=env)
    assert nothing.exit_code == 0 and json.loads(nothing.stdout)["cleared"] is False
    rerun = runner.invoke(app, ["run", plan_id, "--json"], env=env)
    assert rerun.exit_code == 0 and json.loads(rerun.stdout)["outcome"] == "completed"
    tools = [e.data["tool"] for e in tool_calls(world) if e.data]
    assert tools.count("fault_clear") == 3 and all(
        e.data["adapter"] == "cli" for e in tool_calls(world) if e.data)


def test_admin_lock_status(world: World) -> None:
    admin = B1500Admin(world.service())
    status = admin.lock_status()
    assert status.ok and not status.held and status.holder is None and status.resource == "SIM::nmos_basic"
    assert not status.inflight_marker and status.fault is None
