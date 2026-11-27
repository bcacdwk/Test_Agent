"""Cancelling runs through the abort file, orphaned runs and the async faults at the executor/service level
(blueprint v2 2.6, 4.3, 8.1; WP5.6).

The abort request is injected exactly when segment ``k`` ends (as a ``safe_shutdown`` of another process would write
it), so "cancels within one checkpoint" is checked deterministically: the run stops at checkpoint ``k`` with the rows
of ``k`` segments in ``partial.csv`` and a verified cleanup.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from b1500_test_agent.archive.store import RunStore
from b1500_test_agent.fsio import atomic_write_json
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import PlanRequest, RunProgress
from b1500_test_agent.session import AbortFile, Transaction
from b1500_test_agent.session.inflight import InflightMarker
from b1500_test_agent.transport.sim.state import load_state_file, save_state_file, sim_state_file
from tests.integration.async_helpers import (
    IDVD_LONG,
    SCENARIO,
    assert_async_invariant,
    idvd_long,
    manifest_of,
    partial_rows,
    progress_of,
    run_dir,
    run_events,
    sim_state_safe,
    timed_world,
)
from tests.integration.helpers import World

POINTS = 40  # drain points per IDVD_LONG curve


def abort_at(monkeypatch: pytest.MonkeyPatch, world: World, k: int, *, run_id: Callable[[], str | None] = lambda: None,
             reason: str = "test abort") -> list[datetime]:
    """Write an abort request (as another process would) when the run reaches checkpoint ``k``."""
    original = Transaction.checkpoint
    written: list[datetime] = []

    def checkpoint(self: Transaction, done: int, total: int, phase: str = "", rows: Any = None) -> None:
        if done == k and not written:
            written.append(AbortFile(world.state_dir).request(reason, adapter="cli", run_id=run_id()).requested_at)
        original(self, done, total, phase, rows)

    monkeypatch.setattr(Transaction, "checkpoint", checkpoint)
    return written


@pytest.mark.parametrize("k", [1, 7, 20])
def test_async_run_cancels_at_the_checkpoint_after_the_request(world: World, monkeypatch: pytest.MonkeyPatch,
                                                               k: int) -> None:
    timed_world(world)
    service = world.service(adapter="mcp")
    abort_at(monkeypatch, world, k)
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None
    assert (final.ok, final.status, final.outcome, final.error_code) == (False, "error", "cancelled", "run_cancelled")
    assert final.cleanup_verified == "sim_state" and "partial" in final.artifacts and "data" not in final.artifacts
    run_id = final.run_id or ""
    progress = progress_of(world, run_id)
    assert progress is not None and (progress.state, progress.done, progress.total) == ("cancelled", k, 21)
    assert partial_rows(world, run_id) == k * POINTS
    assert not (run_dir(world, run_id) / "data.csv").exists()
    manifest = assert_async_invariant(world, run_id)
    assert manifest.outcome == "cancelled" and manifest.error_code == "run_cancelled"
    assert f"at {k}/21" in manifest.message and "partial.csv" in manifest.message
    events = run_events(world, run_id)
    cancelled = [e for e in events if e.ev == "run_cancelled"]
    assert len(cancelled) == 1 and cancelled[0].data and cancelled[0].data["consumed"] is True
    assert cancelled[0].data["done"] == k
    # no XE after the cancelling checkpoint: the next segment never started
    xe = [e for e in events if e.ev == "write" and e.cmd == "XE"]
    assert len(xe) == k
    detail = service.get_run(run_id, include=["summary", "progress", "data"])
    assert detail.run is not None and detail.run.outcome == "cancelled" and detail.run.cleanup_verified == "sim_state"
    assert detail.data is not None and "PARTIAL" in detail.data.note and detail.data.rows_total == k * POINTS
    assert detail.progress is not None and detail.progress.state == "cancelled"
    refused = service.analyze_run(run_id, "output_metrics")
    assert not refused.ok and "partial" in refused.message
    listed = service.list_runs()
    assert [(r.run_id, r.outcome) for r in listed.runs] == [(run_id, "cancelled")]


def test_sync_run_honours_the_abort_file_and_keeps_its_rows(world: World,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world)
    service = world.service()
    abort_at(monkeypatch, world, 2)
    plan = service.validate_plan(**idvd_long(vg_points=5))
    assert plan.resolved is not None and plan.resolved.mode == "sync"
    result = service.run_plan(plan.plan_id or "")
    assert (result.outcome, result.error_code, result.cleanup_verified) == ("cancelled", "run_cancelled", "sim_state")
    run_id = result.run_id or ""
    assert partial_rows(world, run_id) == 2 * POINTS  # written at the end because the run did not complete
    assert not (run_dir(world, run_id) / "progress.json").exists()
    assert_async_invariant(world, run_id)


def test_stale_and_foreign_abort_requests_are_ignored(world: World) -> None:
    timed_world(world)
    service = world.service()
    abort = AbortFile(world.state_dir)
    stale = abort.request("left by a dead writer", adapter="cli", now=datetime.now(UTC) - timedelta(minutes=5))
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed"
    assert abort.read() == stale  # never deleted by a reader
    foreign = abort.request("for another run", adapter="cli", run_id="S20261118T000000Z-0000")
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed"
    assert abort.read() == foreign
    assert abort.withdraw(foreign.id) and abort.read() is None


def test_a_corrupt_abort_file_cancels_the_run(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world)
    service = world.service()
    holder: dict[str, str] = {}
    original = Transaction.checkpoint

    def checkpoint(self: Transaction, done: int, total: int, phase: str = "", rows: Any = None) -> None:
        if done == 3:
            (world.state_dir / "abort.json").write_text("{not json", encoding="utf-8")  # corrupt: fail safe
        original(self, done, total, phase, rows)

    monkeypatch.setattr(Transaction, "checkpoint", checkpoint)
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    holder["run"] = started.run_id or ""
    final = service.follow_run(holder["run"])
    assert final is not None and final.outcome == "cancelled" and "corrupt" in final.message
    assert_async_invariant(world, holder["run"])


# -- safe_shutdown and stop_runs (same process) ------------------------------------------------------------------------


def test_safe_shutdown_cancels_the_running_run_then_runs_the_full_cleanup(world: World) -> None:
    timed_world(world, timing="scaled(0.01)")
    service = world.service(adapter="mcp")
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    run_id = started.run_id or ""
    world_progress = lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1
    from tests.integration.async_helpers import wait_for

    wait_for(world_progress, timeout_s=30)
    result = service.safe_shutdown("operator stop")
    assert result.ok and result.cancelled_run == run_id and result.cleanup is not None
    assert result.cleanup.verified == "sim_state" and f"cancelled run {run_id}" in result.message
    assert "(cancelled, cleanup sim_state)" in result.message
    manifest = assert_async_invariant(world, run_id)
    assert manifest.outcome == "cancelled"
    state_audit = [e for e in world.audit_events() if e.ev == "abort_requested"]
    assert len(state_audit) == 1 and state_audit[0].data and state_audit[0].data["target"] == run_id
    assert service.station_status().status == "ok"


def test_stop_runs_is_the_shutdown_hook_path(world: World) -> None:
    timed_world(world, timing="scaled(0.01)")
    service = world.service(adapter="mcp")
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    assert service.stop_runs("MCP server stopping (test)", wait_s=10)
    manifest = assert_async_invariant(world, started.run_id or "")
    assert manifest.outcome == "cancelled" and "MCP server stopping" in manifest.message
    assert service.stop_runs("nothing running") is True


def test_safe_shutdown_without_a_run_leaves_no_abort_request(world: World) -> None:
    timed_world(world)
    service = world.service()
    result = service.safe_shutdown("idle")
    assert result.ok and result.cancelled_run is None
    assert not (world.state_dir / "abort.json").exists()
    assert not [e for e in world.audit_events() if e.ev == "abort_requested"]


# -- orphaned runs -----------------------------------------------------------------------------------------------------


def _orphan(world: World, *, confirmed: bool = False) -> tuple[str, str]:
    """A run folder and in-flight marker as a killed async run leaves them: progress running, rows so far,
    outputs on in the simulator state; ``confirmed``: the run's ``tier_check`` audit event says the human confirmed
    it (``run_confirmed_plan``)."""
    service = world.service()
    plan = service.validate_plan(**IDVD_LONG)
    folder = RunStore(world.runs_dir).create("sim")
    if confirmed:
        folder.audit.emit(AuditEvent.now("tier_check", "sim", run=folder.run_id, data={
            "plan_id": plan.plan_id, "tier": "needs_confirmation", "confirm_reasons": "long_run", "confirmed": True,
            "mode": "async"}))
    folder.write_progress(RunProgress(state="running", done=3, total=21, phase="sweep", elapsed_s=1.0, eta_s=5.0,
                                      updated_at=datetime.now(UTC)))
    marker = InflightMarker(tx="T20261118T000000Z-dead", run=folder.run_id, intent="run mosfet.idvd",
                            plan_id=plan.plan_id, resource=f"SIM::{SCENARIO}", backend="sim", pid=999_999,
                            host="lab", adapter="mcp", since=datetime.now(UTC))
    atomic_write_json(world.state_dir / "inflight.json", marker.model_dump(mode="json"))
    world.service().station_status()  # creates the state file
    path = sim_state_file(world.state_dir, SCENARIO)
    state = load_state_file(path)
    assert state is not None
    for ch in (3, 4):
        state.channels[ch].output_on, state.channels[ch].voltage = True, 1.0
    save_state_file(path, state)
    return folder.run_id, plan.plan_id or ""


def test_the_next_transaction_recovers_and_finalizes_an_orphaned_run(world: World) -> None:
    """A run of a killed process: R-FAULT-01 refuses new runs with zero I/O until ``safe_shutdown``, whose transaction
    runs the in-flight recovery (v1 mechanism) and finalizes the orphaned run as ``aborted``."""
    timed_world(world)
    run_id, _ = _orphan(world)
    service = world.service()
    listed = service.get_run(run_id, include=["summary", "progress"])
    assert listed.run is None and "no manifest" in listed.message and listed.progress is not None
    assert service.station_status(refresh=False).inflight_marker
    marker = world.io_marker()
    refused = service.run_plan(service.validate_plan(**idvd_long(vg_points=2)).plan_id or "")
    assert refused.outcome == "refused" and "in-flight marker" in refused.message
    assert world.io_marker()[0] == marker[0]  # zero instrument I/O
    assert service.safe_shutdown("after a crash").ok
    recovered = [e for e in world.audit_events() if e.ev == "recovery_cleanup"]
    assert recovered and recovered[0].data and recovered[0].data["previous_run"] == run_id
    manifest = manifest_of(world, run_id)
    assert manifest is not None and manifest.outcome == "aborted"
    assert manifest.cleanup is not None and manifest.cleanup.verified == "sim_state"
    assert "without finalizing" in manifest.message and "pid 999999" in manifest.message
    progress = progress_of(world, run_id)
    assert progress is not None and progress.state == "failed" and progress.done == 3
    assert [r.outcome for r in service.list_runs().runs if r.run_id == run_id] == ["aborted"]
    assert sim_state_safe(world) == []
    after = service.run_plan(service.validate_plan(**idvd_long(vg_points=2)).plan_id or "")
    assert after.outcome == "completed"
    assert manifest.confirmed_summary is None and manifest.confirmed_via is None  # never confirmed


def test_an_orphaned_confirmed_run_keeps_its_consent_record(world: World) -> None:
    """WP7.7 (acceptance S15 on Codex: the harness killed the MCP server mid-run): the recovery finalizes a run the
    human had confirmed with ``confirmed_summary`` = the plan summary and ``confirmed_via`` from the adapter."""
    timed_world(world)
    run_id, plan_id = _orphan(world, confirmed=True)
    service = world.service()
    assert service.safe_shutdown("after a crash").ok
    manifest = manifest_of(world, run_id)
    assert manifest is not None and manifest.outcome == "aborted"
    assert manifest.confirmed_summary == manifest.plan.summary and manifest.plan.plan_id == plan_id
    assert manifest.confirmed_via == "run_confirmed_plan"


# -- faults (blueprint v2 4.3) -----------------------------------------------------------------------------------------


def test_run_interrupt_aborts_the_run_with_a_verified_cleanup(world: World) -> None:
    timed_world(world, faults=[{"kind": "run_interrupt", "segment": 4}])
    service = world.service()
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "aborted" and final.cleanup_verified == "sim_state"
    run_id = final.run_id or ""
    manifest = assert_async_invariant(world, run_id)
    assert "SimulatedInterrupt" in manifest.message
    assert partial_rows(world, run_id) == 4 * POINTS
    steps = [s.step for s in manifest.cleanup.steps] if manifest.cleanup else []
    assert steps[0] == "abort"  # the measurement was pending: AB first
    progress = progress_of(world, run_id)
    assert progress is not None and progress.state == "failed"


def test_abort_ignored_still_ends_verified_or_latched(world: World) -> None:
    timed_world(world, faults=[{"kind": "run_interrupt", "segment": 1}, {"kind": "abort_ignored"}])
    service = world.service()
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "aborted"
    manifest = assert_async_invariant(world, final.run_id or "")
    assert manifest.cleanup is not None and manifest.cleanup.verified in ("sim_state", "unverified")
    log = world.sim_log(SCENARIO)
    assert any(r.mnemonic == "AB" for r in log)


def test_slow_instrument_times_out_the_segment_and_cleans_up(world: World) -> None:
    timed_world(world, faults=[{"kind": "slow", "factor": 5.0}])
    service = world.service()
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "failed" and final.error_code == "transport_error"
    manifest = assert_async_invariant(world, final.run_id or "")
    assert manifest.cleanup is not None and manifest.cleanup.verified == "sim_state"


def test_ignore_dz_during_a_cancelled_run_latches_the_fault(world: World,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world, faults=[{"kind": "ignore_dz", "channels": [3]}])
    service = world.service()
    abort_at(monkeypatch, world, 2)
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "cancelled" and final.status == "fault"
    manifest = assert_async_invariant(world, final.run_id or "")
    assert manifest.cleanup is not None and manifest.cleanup.latched_fault
    restore = [s for s in manifest.cleanup.steps if s.step == "restore"]
    assert restore and not restore[0].ok and "skipped" in restore[0].detail
    plan = world.executor().load_plan(started.plan_id or "")
    assert plan.mode == "async"
    refused = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    assert refused.status in ("blocked", "fault")  # the latch refuses every sourcing plan


def test_the_request_object_records_who_asked(world: World) -> None:
    abort = AbortFile(world.state_dir)
    request = abort.request("  why\nnot  ", adapter="mcp", run_id="S20261118T000000Z-0000")
    assert request.reason == "why not" and request.adapter == "mcp" and request.pid > 0
    assert abort.read() == request
    assert not abort.consume("0" * 16) and abort.consume(request.id) and abort.read() is None


def test_plan_request_round_trip_for_the_fixture_recipe(world: World) -> None:
    from tests.integration.async_helpers import stepped_long

    timed_world(world)
    request = PlanRequest.model_validate(stepped_long(3))
    plan = world.executor().plan(request)
    assert plan.recipe_id == "generic.stepped_long" and plan.mode == "sync" and plan.tier == "ok"
