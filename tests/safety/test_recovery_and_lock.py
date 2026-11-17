"""Inflight-marker recovery after a crash and two-process lock contention (blueprint 2.4, 8.1).

The child processes use the ``spawn`` start method (the only one on Windows), so their targets live in
``tests/safety/helpers.py``.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from b1500_test_agent.models.sim import IgnoreDz
from b1500_test_agent.session import CleanupUnverified, InstrumentBusy, InstrumentLock, read_inflight
from b1500_test_agent.transport.sim import sim_state_file
from tests.safety.helpers import (
    DRAIN,
    GATE,
    PLAN_ID,
    acquire,
    assert_cleanup_order,
    assert_global_invariant,
    crash_inside_transaction,
    hold_lock,
    make_harness,
)

SPAWN = multiprocessing.get_context("spawn")
RESOURCE = "SIM::nmos_basic"


def _crash_child(state_dir: Path) -> None:
    ready = SPAWN.Event()
    child = SPAWN.Process(target=crash_inside_transaction, args=(str(state_dir), ready))
    child.start()
    child.join(60)
    assert ready.is_set() and child.exitcode == 4


def test_crash_leaves_marker_and_live_outputs_and_the_next_transaction_recovers(tmp_path: Path) -> None:
    _crash_child(tmp_path)
    marker = read_inflight(tmp_path / "inflight.json")
    assert marker is not None and marker.intent == "crashing body" and marker.pid > 0
    stored = json.loads(sim_state_file(tmp_path, "nmos_basic").read_text(encoding="utf-8"))
    assert stored["channels"][str(GATE)]["output_on"] and stored["channels"][str(GATE)]["voltage"] == 1.2
    assert InstrumentLock(tmp_path, RESOURCE).holder() is None  # the OS released the dead child's lock

    h = make_harness(tmp_path)
    assert h.session.inflight() is not None
    with h.transaction(run=False, intent="after the crash") as tx:
        assert tx.recovery is not None and tx.recovery.verified == "sim_state"
        h.sim.instrument.assert_safe()  # recovered before the body runs
        acquire(tx, h.hook)
    events = h.events(run=False)
    recovery = next(e for e in events if e.ev == "recovery_cleanup")
    assert recovery.data is not None
    assert recovery.data["previous_tx"] == marker.tx and recovery.data["verified"] == "sim_state"
    recovery_steps = [e.data["step"] for e in events[: events.index(recovery)] if e.ev == "cleanup_step"]
    assert recovery_steps == ["abort", "zero", "disconnect", "drain_errors", "verify"]
    exit_events = events[events.index(recovery) + 1:]
    assert_cleanup_order(exit_events)
    h.sim.instrument.assert_safe()
    assert not (tmp_path / "inflight.json").exists()
    assert h.session.lock.holder() is None
    assert h.session.fault_latch.get() is None


def test_unverified_recovery_latches_and_refuses_the_transaction(tmp_path: Path) -> None:
    _crash_child(tmp_path)
    h = make_harness(tmp_path)
    h.sim.inject(IgnoreDz(channels=[GATE]))  # the gate output is stuck: recovery cannot verify
    body_ran = False
    with pytest.raises(CleanupUnverified), h.transaction(run=False):
        body_ran = True
    assert not body_ran
    record = h.session.fault_latch.get()
    assert record is not None and "inflight recovery" in record.reason
    events = h.events(run=False)
    assert [e.ev for e in events].count("cleanup_unverified") == 1
    assert not (tmp_path / "inflight.json").exists()
    assert h.session.lock.holder() is None and not h.session.lock.is_held()


def test_recovery_marker_in_process(tmp_path: Path) -> None:
    """A marker without a process behind it (e.g. left by a killed CLI) is recovered too, and a safe_shutdown also
    counts as recovery."""
    h = make_harness(tmp_path)
    (tmp_path / "inflight.json").write_text("{not json", encoding="utf-8")
    report = h.session.safe_shutdown(reason="operator stop")
    assert report.verified == "sim_state"
    assert any(e.ev == "recovery_cleanup" for e in h.daily.events)
    assert not (tmp_path / "inflight.json").exists()


def test_two_processes_contend_for_the_lock(tmp_path: Path) -> None:
    ready, release = SPAWN.Event(), SPAWN.Event()
    child = SPAWN.Process(target=hold_lock, args=(str(tmp_path), RESOURCE, ready, release, False))
    child.start()
    try:
        assert ready.wait(60)
        h = make_harness(tmp_path)
        with pytest.raises(InstrumentBusy) as caught, h.transaction(lock_timeout_s=0.2):
            pytest.fail("the body must not run while another process holds the lock")
        holder = caught.value.holder
        assert holder is not None
        assert (holder.pid, holder.host, holder.adapter, holder.plan_id) == (child.pid, "child-host", "mcp", PLAN_ID)
        assert caught.value.code == "instrument_busy"
        assert h.session.lock.holder() == holder
        assert not h.log and not h.events()  # zero I/O, nothing audited for the refused transaction
        with pytest.raises(InstrumentBusy):
            h.session.snapshot(lock_timeout_s=0.1)
    finally:
        release.set()
        child.join(60)
    assert child.exitcode == 0
    assert h.session.lock.holder() is None
    with h.transaction() as tx:
        acquire(tx, h.hook)
    assert_global_invariant(h)


def test_lock_of_a_dead_process_is_released_by_the_os(tmp_path: Path) -> None:
    ready, release = SPAWN.Event(), SPAWN.Event()
    child = SPAWN.Process(target=hold_lock, args=(str(tmp_path), RESOURCE, ready, release, True))
    child.start()
    child.join(60)
    assert ready.is_set() and child.exitcode == 3
    lock = InstrumentLock(tmp_path, RESOURCE)
    assert lock.sidecar.exists()  # the dead holder never removed its sidecar ...
    assert lock.holder() is None  # ... but it is ignored: the OS lock is free
    h = make_harness(tmp_path)
    with h.transaction(lock_timeout_s=1.0) as tx:
        tx.driver.enable([GATE, DRAIN])
    assert_global_invariant(h)
