"""Safety rows of the ``bus_locked`` fault (blueprint v2 4.3: another client holds the instrument's exclusive bus
lock) on the simulator; the visa-loop rows are in ``tests/visa_loop/``.

Positions: inside a transaction (no effect on it: it holds the bus; ``test_fault_matrix.py``), then the next
transaction, a status snapshot, a safe shutdown and the recovery of a crashed transaction. Invariant: a refused
bus sends nothing, leaves no inflight marker of its own and removes no one else's, releases the instrument lock,
latches nothing, and the next transaction after the other client let go runs normally; a safe shutdown that cannot
take the bus cannot verify anything and latches the fault.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from b1500_test_agent.models.sim import BusLockedFault
from b1500_test_agent.service import B1500Service
from b1500_test_agent.session import FaultLatched, read_inflight
from b1500_test_agent.transport.base import BusLocked
from b1500_test_agent.transport.sim import sim_state_file
from tests.integration.helpers import make_world, plan, run
from tests.safety.helpers import GATE, Harness, MemoryRun, acquire, assert_global_invariant, make_harness
from tests.safety.test_fault_matrix import POSITIONS
from tests.safety.test_recovery_and_lock import _crash_child


def assert_refused_without_io(h: Harness, before: int) -> None:
    assert len(h.log) == before, "a command reached the instrument through a locked bus"
    assert h.session.lock.holder() is None and not h.session.lock.is_held()
    assert h.session.fault_latch.get() is None
    assert not h.session.bus_open and not h.sim.locked
    refused = [e for e in h.events(run=False) + h.events() if e.ev == "bus_lock" and e.error]
    assert refused and refused[-1].error.startswith("BusLocked")


@pytest.mark.parametrize("position", POSITIONS)
def test_another_client_taking_the_bus_mid_transaction_refuses_only_the_next_one(position: str,
                                                                              tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    fault = BusLockedFault(count=1)
    if position == "during_cleanup":
        with h.transaction() as tx:
            acquire(tx, h.hook)
            h.sim.inject(fault)
    else:
        h.at(position, lambda: h.sim.inject(fault))  # the hook moments carry the position names
        with h.transaction() as tx:
            acquire(tx, h.hook)
    assert_global_invariant(h)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"

    before = len(h.log)
    h.run = MemoryRun()
    nxt = h.transaction()
    with pytest.raises(BusLocked), nxt:
        pytest.fail("the body must not run")  # pragma: no cover
    assert nxt.cleanup is None and not (tmp_path / "inflight.json").exists()
    assert_refused_without_io(h, before)

    h.run = MemoryRun()
    with h.transaction() as again:
        acquire(again, h.hook)
    assert_global_invariant(h)


def test_a_status_snapshot_on_a_locked_bus_is_refused_without_io(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    h.sim.inject(BusLockedFault(count=1))
    before = len(h.log)
    with pytest.raises(BusLocked):
        h.session.snapshot()
    assert_refused_without_io(h, before)
    assert h.session.snapshot().identity is not None


def test_a_safe_shutdown_that_cannot_take_the_bus_latches_and_blocks_sourcing(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    h.sim.inject(BusLockedFault())
    before = len(h.log)
    report = h.session.safe_shutdown(reason="operator stop")
    assert report.verified == "unverified" and report.latched_fault
    assert "BusLocked" in report.steps[0].detail and len(h.log) == before
    record = h.session.fault_latch.get()
    assert record is not None and "transport unavailable" in record.reason
    with pytest.raises(FaultLatched), h.transaction():
        pytest.fail("a sourcing transaction must refuse while the fault is latched")  # pragma: no cover
    assert len(h.log) == before
    h.sim.clear_faults()  # the other client let go; the human clears the latch after a verified shutdown
    verified = h.session.safe_shutdown(reason="fault clear")
    assert verified.verified == "sim_state"
    h.session.fault_latch.clear(by="owner", shutdown=verified)
    with h.transaction() as tx:
        acquire(tx, h.hook)
    assert_global_invariant(h)


def test_a_locked_bus_keeps_a_crashed_transactions_marker_for_recovery(tmp_path: Path) -> None:
    _crash_child(tmp_path)  # outputs on (gate 1.2 V), inflight marker left behind
    marker = read_inflight(tmp_path / "inflight.json")
    assert marker is not None
    h = make_harness(tmp_path)
    h.sim.inject(BusLockedFault(count=1))
    with pytest.raises(BusLocked), h.transaction(run=False):
        pytest.fail("the body must not run")  # pragma: no cover
    still = read_inflight(tmp_path / "inflight.json")
    assert still is not None and still.tx == marker.tx  # recovery is still pending, nobody "cleaned" it away
    stored = json.loads(sim_state_file(tmp_path, "nmos_basic").read_text(encoding="utf-8"))
    assert stored["channels"][str(GATE)]["output_on"]  # nothing was sent: the stuck outputs wait for recovery
    with h.transaction(run=False) as tx:
        assert tx.recovery is not None and tx.recovery.verified == "sim_state"
        h.sim.instrument.assert_safe()
    assert not (tmp_path / "inflight.json").exists()


def test_service_reports_busy_and_refuses_the_run_without_io(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.use_faults("buslocked", [{"kind": "bus_locked", "count": 2}])
    executor = world.executor()
    record = plan(executor)
    marker = world.io_marker()
    service = B1500Service(paths=world.paths, registry=executor.registry(), clock=world.clock)
    status = service.station_status()
    assert (status.status, status.error_code, status.live) == ("busy", "instrument_busy", "unavailable")
    result = run(service.executor, record.plan_id)
    assert (result.status, result.outcome, result.error_code) == ("busy", "refused", "instrument_busy")
    assert world.io_marker()[0] == marker[0]  # no simulator command
    assert run(service.executor, record.plan_id).ok  # the fault is spent: the bus is free again
    service.close()
    executor.close()
