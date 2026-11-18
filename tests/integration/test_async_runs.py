"""Asynchronous runs through ``B1500Service`` (blueprint v2 2.6, 2.9, 8.1 ``integration/``: async ``running`` →
``completed``/``cancelled``; WP5.6).

A v1 stepped plan (``mosfet.idvd``, 21 gate steps at long integration, ~9 min) runs as a scaled long run; the
test-only ``generic.stepped_long`` gives 20 min and 4 h plans. ``timing: instant`` keeps virtual time free (a 4 h run
in under 2 s of wall time), ``timing: scaled(f)`` makes the run observable while it runs.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.archive.runfiles import read_partial
from b1500_test_agent.catalog.kinds.smu_stepped import STEP_OVERHEAD_S
from b1500_test_agent.models.station import CorrectionRecord
from tests.integration.async_helpers import (
    IDVD_LONG,
    assert_async_invariant,
    idvd_long,
    manifest_of,
    progress_of,
    run_dir,
    run_events,
    stepped_long,
    timed_world,
    wait_for,
)
from tests.integration.helpers import World

# -- planning ---------------------------------------------------------------------------------------------------------


def test_planner_sets_the_mode_from_the_estimate_and_the_segment_length(world: World) -> None:
    timed_world(world)
    service = world.service()
    short = service.validate_plan(**idvd_long(vg_points=3))
    assert short.ok and short.resolved is not None and short.resolved.mode == "sync" and short.tier == "ok"
    long = service.validate_plan(**IDVD_LONG)
    assert long.tier == "ok" and long.resolved is not None and long.resolved.mode == "async", long.findings
    assert 300 < long.resolved.est_s < 600
    plan = world.executor().load_plan(long.plan_id or "")
    assert plan.mode == "async" and plan.estimate.max_segment_s is not None
    assert plan.estimate.max_segment_s <= 30 and "async ~" in plan.summary
    info = [f for f in long.findings if f.rule_id == "R-RUN-02"]
    assert [f.severity for f in info] == ["info"], info
    twenty = service.validate_plan(**stepped_long(46))
    assert twenty.tier == "needs_confirmation" and twenty.confirm_reasons == ["long_run"], twenty.findings
    assert twenty.resolved is not None and 1150 < twenty.resolved.est_s < 1300
    # one sweep longer than segment_max_s cannot be cancelled within a segment: blocked
    slow = service.validate_plan(**stepped_long(20, vd_points=40))
    assert slow.tier == "blocked" and any(f.rule_id == "R-RUN-02" and f.severity == "block" for f in slow.findings)


def test_stepped_estimate_has_one_segment_per_step(world: World) -> None:
    timed_world(world)
    plan = world.executor().load_plan(world.service().validate_plan(**IDVD_LONG).plan_id or "")
    program = plan.program
    assert plan.estimate.max_segment_s == pytest.approx(program["sweep_estimate_s"] + STEP_OVERHEAD_S)


# -- running → completed -----------------------------------------------------------------------------------------------


def test_v1_stepped_plan_runs_as_a_scaled_long_run(world: World) -> None:
    """``mosfet.idvd`` (a v1 recipe) as a ~9 min asynchronous run on ``timing: scaled(0.005)`` (~3 s wall)."""
    timed_world(world, timing="scaled(0.005)")
    service = world.service(adapter="mcp")
    plan = service.validate_plan(**IDVD_LONG)
    t0 = time.monotonic()
    started = service.run_plan(plan.plan_id or "")
    assert time.monotonic() - t0 < 1.0
    assert (started.ok, started.status, started.outcome) == (True, "ok", "running"), started.message
    run_id = started.run_id or ""
    assert started.eta_s == pytest.approx(plan.resolved.est_s if plan.resolved else 0)
    assert {"progress", "partial", "run_dir"} <= set(started.artifacts)
    busy = service.station_status(refresh=True)
    assert (busy.ok, busy.status, busy.error_code) == (False, "busy", "instrument_busy")
    assert busy.active_run is not None and busy.active_run.run_id == run_id and busy.active_run.mode == "async"
    assert busy.live in ("cached", "not_read") and f"busy: run {run_id}" in busy.message
    second = service.run_plan(plan.plan_id or "")
    assert (second.status, second.outcome, second.error_code) == ("busy", "refused", "instrument_busy")
    assert f"run {run_id}" in second.message and second.run_id is None
    running = service.list_runs(status="running")
    assert [r.run_id for r in running.runs] == [run_id] and running.runs[0].outcome == "running"
    seen = wait_for(lambda: (p := service.get_run(run_id, include=["summary", "progress"]).progress) and p.done >= 2
                    and p, timeout_s=30)
    assert seen.state == "running" and seen.total == 21 and seen.phase == "sweep" and seen.eta_s is not None
    # partial.csv is flushed with progress.json (throttled to 0.5 s of wall time); the in-process progress is live
    detail = wait_for(lambda: (d := service.get_run(run_id, include=["summary", "progress", "data"])).data and d,
                      timeout_s=30)
    assert detail.run is not None and detail.run.outcome == "running" and detail.run.recipe_id == "mosfet.idvd"
    assert detail.data is not None and "PARTIAL" in detail.data.note and detail.data.rows_total >= 40
    refused = service.analyze_run(run_id, "output_metrics")
    assert not refused.ok and "still running" in refused.message
    note = service.annotate_run(run_id, "during the run")
    assert not note.ok and "still running" in note.message
    final = service.follow_run(run_id)
    assert final is not None and final.outcome == "completed", final.message
    assert final.cleanup_verified == "sim_state"
    manifest = assert_async_invariant(world, run_id)
    assert manifest.outcome == "completed" and manifest.plan.mode == "async"
    progress = progress_of(world, run_id)
    assert progress is not None and (progress.state, progress.done, progress.total) == ("completed", 21, 21)
    assert progress.eta_s == 0 and "drain_I" in progress.last_values
    data = load_run(run_id, data_root=world.data).table
    partial = read_partial(run_dir(world, run_id))
    assert partial is not None
    pd.testing.assert_frame_equal(partial.reset_index(drop=True), data.reset_index(drop=True))
    assert {"progress.json", "partial.csv", "data.csv"} <= set(manifest.files)
    status = service.station_status(refresh=True)
    assert status.status == "ok" and status.active_run is None and status.live == "fresh"
    assert service.list_runs(status="running").runs == []
    assert [r.outcome for r in service.list_runs().runs] == ["completed"]


def test_four_hour_run_on_instant_timing_takes_seconds(world: World) -> None:
    """Blueprint v2 4.1: a 4 h run executes in < 2 s of wall time with ``timing: instant``."""
    timed_world(world)
    service = world.service()
    plan = service.validate_plan(**stepped_long(504, vd_points=2, delay=13.7))  # 504 segments of ~29.9 s
    assert plan.resolved is not None and plan.resolved.mode == "async" and plan.resolved.est_s >= 4 * 3600
    assert plan.tier == "needs_confirmation" and plan.confirm_reasons == ["long_run"]
    t0 = time.monotonic()
    started = service.run_confirmed_plan(plan.plan_id or "", plan.summary or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    wall = time.monotonic() - t0
    assert final is not None and final.outcome == "completed", final.message
    assert wall < 2.0, f"4 h run took {wall:.2f} s of wall time"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.total) == (504, 504)
    assert len(load_run(final.run_id or "", data_root=world.data).table) == 1008
    manifest = assert_async_invariant(world, final.run_id or "")
    assert manifest.confirmed_via == "cli --confirm" or manifest.confirmed_via == "run_confirmed_plan"


# -- R-CAL-02 ----------------------------------------------------------------------------------------------------------


def test_async_run_turns_auto_calibration_off_and_restores_it(world: World) -> None:
    timed_world(world, auto_calibration=True)
    service = world.service()
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed"
    manifest = assert_async_invariant(world, final.run_id or "")
    log = [r for r in world.sim_log("nmos_timed") if r.outcome == "ok"]
    commands = [r.command for r in log]
    first_cm = commands.index("CM 0")
    assert commands.index("*LRN? 31") < first_cm < commands.index("XE")  # read, then off before the kind starts
    assert commands[-1] == "CM 1"  # restored after the verified cleanup ...
    assert max(i for i, c in enumerate(commands) if c == "CL") < len(commands) - 1  # ... after the outputs are off
    restore = [s for s in manifest.cleanup.steps if s.step == "restore"] if manifest.cleanup else []
    assert len(restore) == 1 and restore[0].ok and "restored to on" in restore[0].detail
    pre = manifest.rules[1]
    cal2 = [f for f in pre.findings if f.rule_id == "R-CAL-02"]
    assert len(cal2) == 1 and cal2[0].observed is True and "auto-calibration is on" in cal2[0].message
    cal1 = [f for f in pre.findings if f.rule_id == "R-CAL-01" and "auto-calibration" in f.message]
    assert cal1 and cal1[0].severity == "info"
    assert any(e.ev == "checkpoint" and e.data and e.data.get("label") == "auto_calibration_off"
               for e in run_events(world, final.run_id or ""))


def test_sync_run_reads_but_never_changes_auto_calibration(world: World) -> None:
    timed_world(world, auto_calibration=True)
    service = world.service()
    result = service.run_plan(service.validate_plan(**idvd_long(vg_points=2)).plan_id or "")
    assert result.outcome == "completed"
    commands = [r.command for r in world.sim_log("nmos_timed") if r.outcome == "ok"]
    assert "*LRN? 31" in commands and not any(c.startswith("CM ") for c in commands)
    manifest = manifest_of(world, result.run_id or "")
    assert manifest is not None and manifest.cleanup is not None
    assert not any(s.step == "restore" for s in manifest.cleanup.steps)
    assert not (run_dir(world, result.run_id or "") / "progress.json").exists()
    assert not (run_dir(world, result.run_id or "") / "partial.csv").exists()


# -- correction store wiring (WP5.4 handoff) ---------------------------------------------------------------------------


def test_planner_reads_the_correction_store(world: World) -> None:
    """``Executor`` passes ``archive.corrections.records_for`` into ``Planner(corrections=...)``: the store's records
    reach R-CORR-01's context (``RuleContext.corrections``)."""
    from b1500_test_agent.archive.corrections import add_record
    from b1500_test_agent.models.plan import PlanRequest

    timed_world(world)
    executor = world.executor()
    bundle = executor.config.get()
    record = CorrectionRecord(kind="open", freqs_hz=[1e6], run_id="S20261118T010203Z-abcd",
                              ts=executor._clock(), idn="x", pin_map_sha="0" * 64, station_sha="0" * 64)
    add_record("CMU1", record, state_dir=world.state_dir)
    plan = executor.plan(PlanRequest.model_validate(IDVD_LONG))
    ctx = executor._planner(bundle).context(plan, bundle)
    assert [r.kind for r in ctx.corrections["CMU1"]] == ["open"]
