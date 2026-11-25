"""Executor tier and plan checks (blueprint 2.6 steps 1-4, 3 global invariant, 4.3): every refusal before the
transaction leaves the instrument untouched (no simulator command, no transport audit event, no run folder)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.catalog.kinds import SmuStaircaseKind
from b1500_test_agent.models.run import LockHolder
from b1500_test_agent.session import FaultLatch, InstrumentLock
from b1500_test_agent.transport.audit import NullAuditSink
from tests.integration.helpers import CLI, MCP, REPO_ROOT, World, plan, run, with_unrunnable_recipe

CONFIRM = {"vg_stop": 3.5}
"""Above the nmos-generic gate envelope (3 V): needs_confirmation (dut_envelope), within every hard limit."""


def assert_refused(world: World, before: tuple[int, int, int, bool], result, *, status: str, code: str,
                   outcome: str = "refused") -> None:
    assert not result.ok and result.run_id is None
    assert (result.status, result.error_code, result.outcome) == (status, code, outcome), result.message
    assert world.io_marker() == before, "a refusal before the transaction must do zero instrument I/O"


def test_recipes_not_runnable_on_the_backend_never_touch_the_instrument(world: World, tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """R-REC-01 (WP11.2): a recipe whose kind no registry knows, and a registered kind without a code path on this
    backend, are blocked at validation and refused at run time (with or without a summary) with zero I/O."""
    unknown = with_unrunnable_recipe(world, tmp_path)
    executor = world.executor()
    monkeypatch.setattr(SmuStaircaseKind, "implemented_on", frozenset({"visa"}))  # mosfet.idvg: no sim path
    for recipe_id, dut in ((unknown, "nmos-generic"), ("mosfet.idvg", "nmos-generic"), (unknown, None)):
        record = plan(executor, recipe_id=recipe_id, dut_profile=dut)
        assert record.tier == "blocked"
        rec01 = [f for f in record.rules.findings if f.rule_id == "R-REC-01" and f.severity == "block"]
        assert rec01 and "has no code path on backend sim" in rec01[0].message
        before = world.io_marker()
        for summary in (None, record.summary):
            assert_refused(world, before, run(executor, record.plan_id, summary), status="blocked",
                           code="blocked_by_rules")
    assert world.io_marker() == (0, 0, 0, False)


def test_needs_confirmation_via_run_plan_is_refused_without_io(world: World) -> None:
    executor = world.executor()
    record = plan(executor, params=CONFIRM)
    assert record.tier == "needs_confirmation" and record.rules.confirm_reasons == ["dut_envelope"]
    before = world.io_marker()
    result = run(executor, record.plan_id)
    assert_refused(world, before, result, status="needs_confirmation", code="confirmation_required",
                   outcome="confirmation_required")
    assert result.summary == record.summary and "R-DUT-01 dut_envelope" in record.summary


def test_wrong_summary_echo_is_a_mismatch_returning_the_fresh_summary(world: World) -> None:
    executor = world.executor()
    record = plan(executor, params=CONFIRM)
    before = world.io_marker()
    for wrong in ("yes", record.summary.replace("3.5", "2.5"), record.summary + " | extra"):
        result = run(executor, record.plan_id, wrong)
        assert_refused(world, before, result, status="refused", code="summary_mismatch")
        assert result.summary == record.summary


def test_blocked_plan_is_refused_with_or_without_summary(world: World) -> None:
    executor = world.executor()
    record = plan(executor, params={"vg_stop": 60.0})
    assert record.tier == "blocked"
    rules = {f.rule_id for f in record.rules.findings if f.severity == "block"}
    assert {"R-PARAM-01", "R-LIM-02"} <= rules
    before = world.io_marker()
    for summary in (None, record.summary):
        assert_refused(world, before, run(executor, record.plan_id, summary), status="blocked",
                       code="blocked_by_rules")


def test_confirmed_run_records_tier_summary_and_config_hashes(world: World) -> None:
    executor = world.executor()
    record = plan(executor, params=CONFIRM)
    for client, via in ((MCP, "run_confirmed_plan"), (CLI, "cli --confirm")):
        result = run(executor, record.plan_id, f"  {record.summary} ", client=client)
        assert result.ok and result.outcome == "completed", result.message
        assert result.summary == record.summary
        manifest = load_run(result.run_id, data_root=world.data).manifest
        assert manifest.tier == "needs_confirmation"
        assert manifest.confirmed_summary == record.summary and manifest.confirmed_via == via
        assert manifest.rules[0].confirm_reasons == ["dut_envelope"]
        files = {f.key: f for f in manifest.config_files}
        assert files["duts/nmos-generic"].sha256 == manifest.hashes["dut_profile"] == record.hashes["dut_profile"]
        assert files["policy"].sha256 == manifest.hashes["policy"]
        assert all(len(f.sha256) == 64 and f.path for f in manifest.config_files)


def test_ok_plan_accepts_the_right_echo_and_refuses_a_wrong_one(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    assert run(executor, record.plan_id, "not the summary").error_code == "summary_mismatch"
    assert run(executor, record.plan_id, record.summary).outcome == "completed"


def test_unknown_and_tampered_plans(world: World) -> None:
    executor = world.executor()
    before = world.io_marker()
    for plan_id in ("P-AAAAAAAAAA", "not-a-plan", "../../x"):
        assert_refused(world, before, run(executor, plan_id), status="refused", code="unknown_plan")
    record = plan(executor)
    path = world.state_dir / "plans" / f"{record.plan_id}.json"
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    data["envelope"]["channels"]["4"]["max_abs_v"] = 30.0  # the gate
    path.write_text(json.dumps(data), encoding="utf-8")
    before = world.io_marker()
    result = run(executor, record.plan_id)
    assert_refused(world, before, result, status="refused", code="unknown_plan")
    assert "does not match its hash" in result.message
    path.write_text("{not json", encoding="utf-8")
    assert_refused(world, before, run(executor, record.plan_id), status="refused", code="unknown_plan")


def test_stored_tier_is_never_trusted(world: World) -> None:
    executor = world.executor()
    record = plan(executor, params=CONFIRM)
    path = world.state_dir / "plans" / f"{record.plan_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"] = {**data["rules"], "tier": "ok", "findings": [], "confirm_reasons": []}
    data["tier"] = "ok"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert executor.load_plan(record.plan_id).tier == "ok"  # the edit does not touch the hash
    before = world.io_marker()
    assert_refused(world, before, run(executor, record.plan_id), status="needs_confirmation",
                   code="confirmation_required", outcome="confirmation_required")


def test_changed_config_makes_the_plan_stale(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    world.write_config("duts/nmos-generic.yaml", {
        "device_type": "nmos",
        "terminals": {t: {"max_abs_v": 5.0, "max_abs_i": 1e-3} for t in ("gate", "drain", "source", "bulk")},
    })
    before = world.io_marker()
    result = run(executor, record.plan_id)
    assert_refused(world, before, result, status="refused", code="plan_stale")
    assert "dut_profile" in result.message
    fresh = plan(executor)
    assert fresh.plan_id != record.plan_id and run(executor, fresh.plan_id).outcome == "completed"


def test_changed_policy_and_recipe_make_the_plan_stale(world: World, tmp_path: Path) -> None:
    recipes = tmp_path / "recipes"
    shutil.copytree(REPO_ROOT / "recipes", recipes)
    world.recipes = recipes
    executor = world.executor()
    record = plan(executor)
    idvg = recipes / "mosfet" / "idvg.yaml"
    idvg.write_text(idvg.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    before = world.io_marker()
    result = run(executor, record.plan_id)
    assert_refused(world, before, result, status="refused", code="plan_stale")
    assert "recipe mosfet.idvg changed" in result.message
    record = plan(executor)
    world.write_config("policy.yaml", {"soft_limits": {"voltage_v": 5.0, "compliance_a": 0.01}})
    assert_refused(world, before, run(executor, record.plan_id), status="refused", code="plan_stale")


def test_expired_plan(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    assert record.expires_at - record.created_at == timedelta(hours=24)
    world.clock.offset = timedelta(hours=24, seconds=1)
    before = world.io_marker()
    assert_refused(world, before, run(executor, record.plan_id), status="refused", code="plan_expired")
    world.clock.offset = timedelta(hours=23)
    assert run(executor, record.plan_id).outcome == "completed"


def test_latched_fault_blocks_validation_and_runs(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    FaultLatch(world.state_dir, audit=NullAuditSink(), backend="sim").set("test fault", None)
    before = world.io_marker()
    result = run(executor, record.plan_id)
    assert_refused(world, before, result, status="blocked", code="blocked_by_rules")
    assert "R-FAULT-01" in result.message
    assert plan(executor).tier == "blocked"


def test_busy_instrument_refuses_without_a_run_folder(world: World) -> None:
    executor = world.executor(lock_timeout_s=0.2)
    record = plan(executor)
    holder = LockHolder(pid=1, host="other", adapter="mcp", plan_id=None, since=datetime.now(UTC))
    with InstrumentLock(world.state_dir, "SIM::nmos_basic").acquire(holder):
        result = run(executor, record.plan_id)
    assert (result.status, result.error_code, result.outcome, result.run_id) == \
        ("busy", "instrument_busy", "refused", None)
    assert world.run_dirs() == [] and not any(world.runs_dir.glob("*/*/*/*"))
    assert run(executor, record.plan_id).outcome == "completed"


def test_pre_execute_rules_block_with_zero_source_commands(world: World) -> None:
    world.use_faults("swapped", [{"kind": "modules_override",
                                  "slots": [{"slot": 1, "model": "B1517A"}, {"slot": 3, "model": "B1511B"}]}])
    executor = world.executor()
    record = plan(executor)
    assert record.tier == "ok"
    result = run(executor, record.plan_id)
    assert (result.ok, result.status, result.error_code, result.outcome) == \
        (False, "blocked", "blocked_by_rules", "refused")
    assert "R-INV-01" in result.message and result.cleanup_verified == "sim_state"
    log = world.sim_log("nmos_swapped")
    assert log and not [r for r in log if r.source]
    manifest = json.loads((world.run_dirs()[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "refused" and [r["phase"] for r in manifest["rules"]] == ["plan", "pre_execute"]
    assert not (world.run_dirs()[0] / "data.csv").exists()


@pytest.mark.parametrize("summary", [None, "anything"])
def test_invalid_config_is_refused(world: World, summary: str | None) -> None:
    executor = world.executor()
    record = plan(executor)
    world.write_config("policy.yaml", {"hard_limits": {"max_abs_voltage_v": 100.0}})
    result = run(executor, record.plan_id, summary)
    assert (result.ok, result.error_code, result.outcome) == (False, "invalid_config", "refused")
    assert world.io_marker() == (0, 0, 0, False)


def test_dut_instance_is_validated_before_any_io(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    for bad in ("W1\nD2", "x" * 201):
        result = run(executor, record.plan_id, dut=bad)
        assert (result.ok, result.error_code, result.run_id) == (False, "invalid_input", None)
    assert world.io_marker() == (0, 0, 0, False)
