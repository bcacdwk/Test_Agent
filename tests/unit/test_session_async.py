"""Session building blocks of asynchronous runs (blueprint v2 2.6; WP5.6): the abort file and its watch
(``session/abort.py``), the run control with throttled progress and partial rows, the runner's worker thread
(``session/runner.py``) and the transaction's checkpoint, abort and auto-calibration hooks."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from b1500_test_agent.models.plan import RunProgress
from b1500_test_agent.session import (
    ABORT_FILE,
    AbortFile,
    AbortWatch,
    RunCancelled,
    RunControl,
    RunJob,
    Runner,
    RunnerBusy,
)
from b1500_test_agent.session.abort import CORRUPT_ID
from b1500_test_agent.session.runner import last_values
from tests.safety.helpers import DRAIN, GATE, make_harness

RUN = "S20261118T010203Z-abcd"


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# -- abort file ------------------------------------------------------------------------------------------------------


def test_request_read_consume_and_withdraw(tmp_path: Path) -> None:
    abort = AbortFile(tmp_path)
    assert abort.read() is None and abort.path.name == ABORT_FILE
    request = abort.request("stop it", adapter="mcp", run_id=RUN)
    assert abort.read() == request and request.pid == os.getpid() and request.run_id == RUN
    assert not abort.consume("f" * 16)  # another request id: left alone
    assert abort.consume(request.id) and abort.read() is None
    second = abort.request("", adapter=None)
    assert second.reason == "abort requested" and abort.withdraw(second.id) and not abort.withdraw(second.id)


def test_a_newer_request_replaces_the_older_one(tmp_path: Path) -> None:
    abort = AbortFile(tmp_path)
    first = abort.request("one", adapter="cli")
    second = abort.request("two", adapter="mcp")
    assert abort.read() == second and not abort.withdraw(first.id) and abort.read() == second


def test_a_corrupt_abort_file_is_a_request_stamped_with_its_mtime(tmp_path: Path) -> None:
    abort = AbortFile(tmp_path)
    abort.path.write_text("{not json", encoding="utf-8")
    request = abort.read()
    assert request is not None and request.id == CORRUPT_ID and "corrupt" in request.reason
    assert abs((request.requested_at - datetime.now(UTC)).total_seconds()) < 60
    assert abort.consume(CORRUPT_ID) and abort.read() is None


def test_watch_honours_only_requests_for_this_run_made_after_it_started(tmp_path: Path) -> None:
    abort = AbortFile(tmp_path)
    since = datetime.now(UTC)
    watch = AbortWatch(abort, run_id=RUN, since=since)
    abort.request("old", adapter="cli", now=since - timedelta(seconds=1))
    assert watch.pending() is None
    abort.request("other run", adapter="cli", run_id="S20261118T000000Z-0000")
    assert watch.pending() is None
    watch.check()  # nothing applies
    mine = abort.request("mine", adapter="cli", run_id=RUN)
    assert watch.pending() == mine
    with pytest.raises(RunCancelled) as caught:
        watch.check()
    assert caught.value.code == "run_cancelled" and caught.value.request == mine and "mine" in str(caught.value)
    abort.path.unlink()
    assert watch.pending() == mine  # sticky once seen
    abort.request("any run", adapter="mcp")
    assert watch.consume() is False  # the file now holds another request, which stays
    assert abort.read() is not None


def test_watch_rate_limits_its_file_reads(tmp_path: Path) -> None:
    abort = AbortFile(tmp_path)
    clock = Clock()
    watch = AbortWatch(abort, run_id=RUN, since=datetime.now(UTC) - timedelta(seconds=1), min_interval_s=1.0,
                       clock=clock)
    assert watch.pending() is None
    abort.request("now", adapter="cli")
    assert watch.pending() is None  # read again only after 1 s
    clock.t += 1.0
    assert watch.pending() is not None


# -- run control -----------------------------------------------------------------------------------------------------


def rows(start: int, n: int = 2) -> list[dict[str, object]]:
    return [{"step": start + i, "drain_V": 0.1 * i, "drain_I": 1e-6 * (i + 1), "drain_I_status": "N"}
            for i in range(n)]


def control(tmp_path: Path, mode: str, clock: Clock, **kwargs: object) -> tuple[RunControl, list, list]:
    written: list[RunProgress] = []
    chunks: list[pd.DataFrame] = []
    watch = AbortWatch(AbortFile(tmp_path), run_id=RUN, since=datetime.now(UTC) - timedelta(seconds=1))
    run = RunControl(run_id=RUN, mode=mode, abort=watch,  # type: ignore[arg-type]
                     progress_sink=written.append if mode == "async" else None, partial_sink=chunks.append,
                     estimate_s=100.0, clock=clock, **kwargs)  # type: ignore[arg-type]
    return run, written, chunks


def test_async_control_writes_throttled_progress_and_flushes_rows(tmp_path: Path) -> None:
    clock = Clock()
    run, written, chunks = control(tmp_path, "async", clock, progress_interval_s=0.5)
    run.begin(total=4)
    assert [p.done for p in written] == [0] and written[0].eta_s == 100.0
    clock.t += 1.0
    run.checkpoint(1, 4, "sweep", rows(0))
    clock.t += 0.1
    run.checkpoint(2, 4, "sweep", lambda: rows(2))  # within the interval: buffered
    assert [p.done for p in written] == [0, 1] and len(chunks) == 1
    assert run.latest is not None and run.latest.done == 2 and run.latest.eta_s == pytest.approx(1.1)
    clock.t += 1.0
    run.checkpoint(3, 4, "sweep", rows(4))
    assert len(chunks) == 2 and list(chunks[1]["step"]) == [2, 3, 4, 5]  # the buffered segment came along
    final = run.finish("completed")
    assert final is not None and (final.state, final.done, final.total, final.eta_s) == ("completed", 3, 4, 0.0)
    assert written[-1] == final and final.last_values == {"drain_V": 0.1, "drain_I": 2e-6}


def test_buffered_rows_become_one_table_equal_to_per_segment_frames(tmp_path: Path) -> None:
    """Row lists are kept as given and turned into a DataFrame only when written (WP6.5: one DataFrame per
    checkpoint cost a 4 h simulated run a fifth of its wall time); the table equals the per-segment frames
    concatenated, also with a kind's own DataFrame in between and a column that appears later."""
    clock = Clock()
    run, _written, chunks = control(tmp_path, "async", clock, progress_interval_s=60)
    run.begin(total=4)
    late = [{**row, "gate_V": 1.0} for row in rows(4)]
    parts: list[object] = [rows(0), pd.DataFrame(rows(2)), late, []]
    for index, part in enumerate(parts, start=1):
        run.checkpoint(index, 4, "sweep", part)  # type: ignore[arg-type]
    assert chunks == []  # nothing written within the interval
    assert run.latest is not None and run.latest.last_values == last_values(late)
    run.finish("completed")
    expected = pd.concat([pd.DataFrame(rows(0)), pd.DataFrame(rows(2)), pd.DataFrame(late)], ignore_index=True)
    assert len(chunks) == 1
    pd.testing.assert_frame_equal(chunks[0], expected)
    assert last_values(late) == last_values(pd.DataFrame(late)) == {"drain_V": 0.1, "drain_I": 2e-6, "gate_V": 1.0}


def test_async_control_flushes_before_raising_run_cancelled(tmp_path: Path) -> None:
    clock = Clock()
    run, written, chunks = control(tmp_path, "async", clock, progress_interval_s=60)
    run.begin(total=10)
    run.checkpoint(1, 10, "sweep", rows(0))  # throttled: nothing written yet
    assert len(written) == 1 and not chunks
    AbortFile(tmp_path).request("cancel", adapter="cli")
    with pytest.raises(RunCancelled):
        run.checkpoint(2, 10, "sweep", rows(2))
    assert written[-1].done == 2 and sum(len(c) for c in chunks) == 4
    assert run.finish("cancelled").state == "cancelled"  # type: ignore[union-attr]


def test_sync_control_keeps_rows_for_an_unfinished_run_only(tmp_path: Path) -> None:
    clock = Clock()
    run, _, chunks = control(tmp_path, "sync", clock)
    assert not run.records_progress and run.collects_rows
    run.checkpoint(1, 3, "sweep", rows(0))
    run.checkpoint(2, 3, "sweep", rows(2))
    assert not chunks
    run.finish("completed")
    assert not chunks  # a completed synchronous run writes data.csv, never partial.csv
    run2, _, chunks2 = control(tmp_path, "sync", clock)
    run2.checkpoint(1, 3, "sweep", rows(0))
    run2.finish("failed")
    assert len(chunks2) == 1 and len(chunks2[0]) == 2


def test_rows_that_cannot_be_built_never_stop_the_run(tmp_path: Path) -> None:
    clock = Clock()
    run, _, _ = control(tmp_path, "async", clock)
    warnings: list[str] = []

    def broken() -> list[dict[str, object]]:
        raise ValueError("malformed block")

    run.checkpoint(1, 2, "sweep", broken, warn=lambda what, exc: warnings.append(f"{what}: {exc}"))
    assert warnings == ["partial rows could not be built: malformed block"] and run.write_failures == 1


def test_last_values_skip_step_status_and_non_finite_cells() -> None:
    frame = pd.DataFrame([{"step": 3, "a_I": float("nan"), "a_I_status": "N", "b_V": 1.5, "trust": "ok",
                           "flag": True}])
    assert last_values(frame) == {"b_V": 1.5}
    assert last_values(pd.DataFrame()) == {}


# -- runner ----------------------------------------------------------------------------------------------------------


def job(tmp_path: Path, run_id: str = RUN) -> RunJob:
    watch = AbortWatch(AbortFile(tmp_path), run_id=run_id, since=datetime.now(UTC))
    return RunJob(run_id=run_id, plan_id="P-ABCDEFGHIJ", recipe_id="mosfet.idvd",
                  control=RunControl(run_id=run_id, mode="async", abort=watch), adapter="mcp")


def test_runner_runs_one_job_on_a_non_daemon_thread(tmp_path: Path) -> None:
    runner = Runner()
    release = threading.Event()
    first = job(tmp_path)

    def body(started: object) -> str:
        started()  # type: ignore[operator]
        release.wait(10)
        return "done"

    runner.start(first, body)
    assert first.wait_started(5) and first.thread is not None and not first.thread.daemon
    assert runner.active() is first and first.describe() == f"run {RUN} (starting)"
    with pytest.raises(RunnerBusy) as caught:
        runner.start(job(tmp_path, "S20261118T010203Z-ffff"), body)
    assert caught.value.job is first
    release.set()
    assert first.wait(5) and first.result == "done" and runner.active() is None and runner.last() is first


def test_runner_keeps_a_worker_exception_on_the_job(tmp_path: Path) -> None:
    runner = Runner()
    failing = job(tmp_path)

    def body(started: object) -> str:
        raise KeyboardInterrupt  # recorded, never escapes the worker

    runner.start(failing, body)
    assert failing.wait(5) and isinstance(failing.error, KeyboardInterrupt) and failing.result is None
    assert failing.wait_started(0.1)  # finished counts as "started or finished"


def test_wait_started_times_out(tmp_path: Path) -> None:
    pending = job(tmp_path)
    t0 = time.monotonic()
    assert pending.wait_started(0.1) is False and time.monotonic() - t0 < 2


# -- transaction hooks -----------------------------------------------------------------------------------------------


def test_transaction_checkpoint_and_auto_calibration_restore(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    h.sim.instrument.state.auto_calibration = True
    watch = AbortWatch(AbortFile(tmp_path), run_id=RUN, since=datetime.now(UTC))
    run = RunControl(run_id=RUN, mode="async", abort=watch)
    with h.session.transaction(intent="hooks", envelope=None, run=None, control=run) as tx:
        assert tx.driver.auto_calibration() is True
        tx.suspend_auto_calibration(True)
        assert h.sim.instrument.state.auto_calibration is False
        tx.checkpoint(1, 2, "phase-a", rows(0))
        tx.check_abort()
    assert h.sim.instrument.state.auto_calibration is True
    assert tx.cleanup is not None and tx.cleanup.steps[-1].step == "restore" and tx.cleanup.steps[-1].ok
    labels = [e.data.get("label") for e in h.daily.events if e.ev == "checkpoint" and e.data]
    assert "auto_calibration_off" in labels and "progress" in labels
    assert run.latest is not None and run.latest.done == 1


def test_a_cancel_inside_a_transaction_still_runs_the_verified_cleanup(tmp_path: Path) -> None:
    from tests.safety.helpers import ENVELOPE

    h = make_harness(tmp_path)
    watch = AbortWatch(AbortFile(tmp_path), run_id=RUN, since=datetime.now(UTC))
    run = RunControl(run_id=RUN, mode="sync", abort=watch)
    AbortFile(tmp_path).request("cancel", adapter="cli")
    with pytest.raises(RunCancelled), h.session.transaction(intent="cancel", envelope=ENVELOPE, run=None,
                                                            control=run) as tx:
        tx.driver.enable([GATE, DRAIN])
        tx.driver.force_v(DRAIN, 0.1, icomp=1e-3)
        tx.checkpoint(1, 3, "sweep")
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    h.sim.instrument.assert_safe()
    assert not any(s.step == "restore" for s in tx.cleanup.steps)  # nothing to restore on a synchronous run
