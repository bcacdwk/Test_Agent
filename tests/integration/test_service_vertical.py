"""Service-level integration (blueprint 2.9, 8.1 ``integration/``): the vertical path through ``B1500Service``,
``tool_call`` audit events, config reload and ``invalid_config``, ``b1500 fault clear`` refusing while the
cleanup is unverified, and the recipe index (overview by family, family listings) within the response budget."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.analysis import load_run
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.recipe import RecipeSummary
from b1500_test_agent.service import TOOL_NAMES, B1500Admin, approx_tokens, args_digest
from b1500_test_agent.service.common import TRIM_TARGET
from b1500_test_agent.service.core import RECIPE_FAMILIES
from tests.integration.helpers import IDVG, World, with_unrunnable_recipe

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
                               "moscap-cmu": "unverified", "mosfet-4t-body": "verified", "resistor-4w": "verified",
                               "open-smus": "verified", "capacitor-cmu": "unverified", "mosfet-cp": "unverified",
                               "moscap-scuu": "unverified", "mosfet-split-cv": "unverified",  # WP8.3
                               "fecap-cmu": "unverified",  # WP8.4
                               "mosfet-wgfmu": "verified", "mosfet-wgfmu-body": "verified",
                               "resistor-wgfmu": "verified",  # WP10.4 (through the unverified RSUs)
                               "fefet-wgfmu": "unverified"}  # WP10.6
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


def test_blocked_and_unrunnable_plans(world: World, tmp_path: Path) -> None:
    unrunnable_id = with_unrunnable_recipe(world, tmp_path)  # WP11.2: no reserved slot is left
    service = world.service()
    blocked = service.validate_plan(**IDVG, params={"vg_stop": 60.0})
    assert not blocked.ok and (blocked.status, blocked.error_code) == ("blocked", "blocked_by_rules")
    assert {f.rule_id for f in blocked.findings if f.severity == "block"} >= {"R-PARAM-01", "R-LIM-02"}
    unrunnable = service.validate_plan(recipe_id=unrunnable_id, pin_map="mosfet-4t", dut_profile="nmos-generic")
    assert (unrunnable.status, unrunnable.error_code, unrunnable.tier) == ("blocked", "blocked_by_rules", "blocked")
    assert "R-REC-01" in unrunnable.message and "has no code path on backend sim" in unrunnable.message
    detail = service.list_recipes(recipe_id=unrunnable_id)
    assert detail.recipe is not None and not detail.recipe.runnable and "not runnable on sim" in detail.message
    assert detail.next_steps[0].startswith("not runnable here")
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


def test_recipe_overview_lists_every_family_within_the_budget(world: World) -> None:
    """The default index (blueprint v2 2.9, WP7.3): every family with its runnable ids, within the response budget;
    ``family`` lists that family's entries (card ids), ``device_type`` filters both; an unknown family is invalid
    input."""
    service = world.service()
    index = service.list_recipes()
    assert index.ok and index.recipes == [] and approx_tokens(index.model_dump_json()) <= TRIM_TARGET
    every = service.executor.registry().list()
    assert list(index.families) == [f for f in RECIPE_FAMILIES if any(r.family == f for r in every)]
    for name, family in index.families.items():
        members = [r for r in every if r.family == name]
        assert family.recipes == len(members)
        assert family.runnable == [r.id for r in members]  # every shipped kind runs on sim (WP11.2)
    assert index.message.startswith(f"{len(every)} recipes in {len(index.families)} families, ")
    assert index.next_steps[0].startswith("list_recipes(family=")
    smu = service.list_recipes(family="smu")
    assert smu.ok and smu.families == {} and approx_tokens(smu.model_dump_json()) <= TRIM_TARGET
    assert [r.id for r in smu.recipes] == [r.id for r in every if r.family == "smu"]  # every smu row is shown
    cards = {r.id: r.card for r in smu.recipes}
    assert cards["mosfet.idvg"] == "smu/mosfet-idvg" and cards["mosfet.idvg_pulsed"] == "smu/smu-pulsed-iv"
    assert service.list_recipes(recipe_id="mosfet.idvg").recipe.card.endswith("cards/smu/mosfet-idvg.md")
    nvm = service.list_recipes(device_type="fefet").families["nvm"]
    assert {"fefet.dual_sweep_mw", "fefet.pulse_write_read"} <= set(nvm.runnable)  # WP9.4: pulse_read
    fefet = service.list_recipes(family="nvm", device_type="fefet")
    assert {r.id for r in fefet.recipes} >= {"fefet.dual_sweep_mw", "fefet.pulse_write_read", "spgu.program_smu_read"}
    assert all(r.family == "nvm" for r in fefet.recipes)
    bad = service.list_recipes(family="pulse")
    assert not bad.ok and bad.error_code == "invalid_input" and "smu, cmu, spgu, wgfmu, nvm" in bad.message


def test_recipe_index_fallbacks_stay_within_the_budget(world: World) -> None:
    """Large catalogues: the overview drops the runnable ids of the largest families (named in the message); a family
    listing names the recipes not runnable on the backend, drops the device types, then trims like ``list_runs``
    (``showing N of M``) and names the rest, always within the budget."""
    service = world.service()

    def entry(n: int, status: str, family: str = "smu") -> RecipeSummary:
        return RecipeSummary(id=f"generic.r{n:03d}", title=f"Recipe {n} with a title of a typical length, V and I",
                             family=family, kind="smu_staircase", status=status, card="smu/diode-iv",
                             device_types=["nmos", "pmos"])

    small = [entry(1, "sim_validated"), entry(2, "draft")]
    result = service._recipe_index(small, {"generic.r001"}, "sim", "", family="smu")
    assert [r.id for r in result.recipes] == ["generic.r001", "generic.r002"]
    assert result.message == "2 recipes in family smu, 1 runnable on sim; not runnable on sim: generic.r002"
    assert result.next_steps == ["list_recipes(recipe_id) for params, roles and the test card"]
    families = ("smu", "cmu", "spgu", "wgfmu", "nvm", "reliability", "system")
    big = [entry(n, "sim_validated", families[n % 7]) for n in range(900)]
    overview = service._family_overview(big, {r.id for r in big if int(r.id[-3:]) % 3}, "sim", "")
    assert approx_tokens(overview.model_dump_json()) <= TRIM_TARGET and list(overview.families) == list(families)
    assert sum(f.recipes for f in overview.families.values()) == 900
    assert overview.message.startswith("900 recipes in 7 families, 600 runnable on sim; runnable ids omitted for ")
    medium = [entry(n, "sim_validated") for n in range(26)]
    result = service._recipe_index(medium, {r.id for r in medium}, "sim", "", family="smu")
    assert len(result.recipes) == 26 and "device types omitted" in result.message
    assert all(r.device_types == [] for r in result.recipes)
    assert approx_tokens(result.model_dump_json()) <= TRIM_TARGET
    runnable = [entry(n, "sim_validated") for n in range(40)]
    blocked = [entry(n, "draft") for n in range(100, 130)]
    ids = {r.id for r in runnable}
    result = service._recipe_index(runnable + blocked, ids, "sim", "", family="smu")
    shown = len(result.recipes)
    assert 1 <= shown < 70 and [r.id for r in result.recipes] == [r.id for r in (runnable + blocked)[:shown]]
    assert f"showing {shown} of 70 (not shown: generic.r{shown:03d}, " in result.message
    assert all(r.id in result.message for r in runnable[shown:] + blocked)  # every id stays visible
    assert "not runnable on sim: generic.r100, " in result.message
    assert approx_tokens(result.model_dump_json()) <= TRIM_TARGET
    many = [entry(n, "sim_validated") for n in range(200)]
    others = [entry(n, "draft") for n in range(300, 330)]
    result = service._recipe_index(many + others, {r.id for r in many}, "sim", "", family="smu")
    assert 1 <= len(result.recipes) < 200 and f"showing {len(result.recipes)} of 230" in result.message
    assert result.message.startswith("230 recipes in family smu, 200 runnable on sim")
    assert approx_tokens(result.model_dump_json()) <= TRIM_TARGET
