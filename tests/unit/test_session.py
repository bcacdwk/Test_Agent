"""Unit tests of ``session/``: lock, audit sink, inflight marker, cleanup on the hardware path (``LOP?``), snapshot,
shared simulator state, audit routing (blueprint 2.4, 2.7) and the per-transaction bus lifecycle (v2 2.4)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.run import LockHolder
from b1500_test_agent.models.station import Settings
from b1500_test_agent.session import (
    DailyAuditSink,
    InstrumentBusy,
    InstrumentLock,
    RunHandle,
    Session,
    read_inflight,
    resource_slug,
    run_cleanup,
    state_audit_sink,
)
from b1500_test_agent.session.transaction import new_tx_id
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import Bus, TransportError, TransportTimeout
from tests.safety.helpers import DRAIN, GATE, MemoryRun, acquire, make_harness
from tests.unit.driver_helpers import SpyTransport

LOP_OFF = "LOP" + ",".join(["00"] * 10)
LOP_ON = "LOP01," + ",".join(["00"] * 9)
NO_ERROR = '0,"No Error."'
UNT_NO_SPGU = ";".join(["B1511B,0", "B1511B,0", "B1517A,0", "B1517A,0"] + ["0,0"] * 6)
"""``UNT?`` of a mainframe without an HV-SPGU: the cleanup reads it once and skips its SPGU step (v2 step 2)."""


def holder(**changes: object) -> LockHolder:
    base = LockHolder(pid=1234, host="h", adapter="cli", since=datetime.now(UTC))
    return base.model_copy(update=changes)


class Recorder:
    """Collects ``run_cleanup`` emit calls."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object] | None, str | None]] = []

    def __call__(self, ev: str, data: dict[str, object] | None = None, *, error: str | None = None) -> None:
        self.events.append((ev, data, error))


class HwSpy(SpyTransport):
    """``SpyTransport`` posing as hardware; ``fail_writes`` maps a command to exceptions raised on its writes."""

    backend = "visa"

    def __init__(self, *args: object, fail_writes: dict[str, list[Exception]] | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fail_writes = fail_writes or {}
        self._fixed.setdefault("UNT?", UNT_NO_SPGU)  # no SPGU unless a test answers UNT? itself

    def write(self, cmd: str) -> None:
        failures = self.fail_writes.get(cmd)
        if failures:
            self.log.append(("write-failed", cmd))
            raise failures.pop(0)
        super().write(cmd)


# -- lock ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("resource", "slug"), [("GPIB0::17::INSTR", "gpib0-17-instr"),
                                                ("SIM::nmos_basic", "sim-nmos_basic"),
                                                ("TCPIP0::10.0.0.5::inst0::INSTR", "tcpip0-10.0.0.5-inst0-instr")])
def test_resource_slug_is_file_name_safe(resource: str, slug: str) -> None:
    assert resource_slug(resource) == slug
    assert ":" not in slug


def test_lock_sidecar_and_same_process_contention(tmp_path: Path) -> None:
    lock = InstrumentLock(tmp_path, "GPIB0::17::INSTR")
    assert lock.lock_file == tmp_path / "locks" / "gpib0-17-instr.lock"
    assert lock.holder() is None and not lock.is_held()
    with lock.acquire(holder(plan_id="P-ABCDEFGHIJ"), timeout_s=0.1):
        assert lock.is_held()
        current = lock.holder()
        assert current is not None and current.pid == 1234 and current.plan_id == "P-ABCDEFGHIJ"
        assert json.loads(lock.sidecar.read_text(encoding="utf-8"))["host"] == "h"
        with pytest.raises(InstrumentBusy) as caught, lock.acquire(holder(pid=99), timeout_s=0.05):
            pass  # pragma: no cover
        assert caught.value.holder == current and "pid 1234" in str(caught.value)
    assert lock.holder() is None and not lock.sidecar.exists()


def test_stale_sidecar_is_ignored(tmp_path: Path) -> None:
    lock = InstrumentLock(tmp_path, "SIM::x")
    lock.sidecar.parent.mkdir(parents=True)
    lock.sidecar.write_text(holder().model_dump_json(), encoding="utf-8")
    assert lock.holder() is None
    with lock.acquire(holder(pid=7), timeout_s=0.1):
        assert lock.holder() is not None and lock.holder().pid == 7  # type: ignore[union-attr]


# -- ids, markers, audit sink ----------------------------------------------------------------------------------------


def test_tx_id_shape() -> None:
    assert re.fullmatch(r"T\d{8}T\d{6}Z-[0-9a-f]{4}", new_tx_id())
    assert new_tx_id(datetime(2026, 11, 17, 6, 30, 12, tzinfo=UTC)).startswith("T20261117T063012Z-")
    # unique within the process even for many transactions in one second (a duplicate merged two snapshots of the
    # ATV-13 visa-loop test in the audit, WP6.5)
    second = datetime(2026, 11, 17, 6, 30, 13, tzinfo=UTC)
    ids = [new_tx_id(second) for _ in range(3000)]
    assert len(set(ids)) == len(ids)


def test_inflight_marker_absent_valid_and_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "inflight.json"
    assert read_inflight(path) is None
    path.write_text("[]", encoding="utf-8")
    corrupt = read_inflight(path)
    assert corrupt is not None and "corrupt" in corrupt.intent  # still counts: recovery runs


def test_daily_audit_sink_writes_one_file_per_utc_day(tmp_path: Path) -> None:
    sink = state_audit_sink(tmp_path)
    assert isinstance(sink, DailyAuditSink) and sink.audit_dir == tmp_path / "audit"
    late = AuditEvent(ts=datetime(2026, 11, 17, 23, 59, 59, tzinfo=UTC), ev="tool_call", backend="sim")
    early = AuditEvent(ts=datetime(2026, 11, 18, 0, 0, 1, tzinfo=UTC), ev="tool_call", backend="sim")
    sink.emit(late)
    sink.emit(early)
    first = (tmp_path / "audit" / "2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
    second = (tmp_path / "audit" / "2026-11-18.jsonl").read_text(encoding="utf-8").splitlines()
    assert [AuditEvent.from_json_line(line).seq for line in first + second] == [0, 1]


def test_session_routes_events_to_the_daily_file(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    sink = state_audit_sink(tmp_path)
    session = Session(h.session.settings, lambda: h.hook, sink, state_dir=tmp_path)
    with session.transaction(intent="daily", envelope=None, run=None):
        pass
    lines = [AuditEvent.from_json_line(line) for path in sorted((tmp_path / "audit").glob("*.jsonl"))
             for line in path.read_text(encoding="utf-8").splitlines()]
    names = [e.ev for e in lines]
    assert names[0] == "lock_acquired" and "session_open" in names and names[-1] == "lock_released"
    assert "query" in names and {e.tx for e in lines if e.ev != "session_open"} == {lines[0].tx}


def test_run_transaction_logs_to_the_run_and_restores_the_sink(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    assert isinstance(h.run, RunHandle)
    with h.transaction() as tx:
        acquire(tx, h.hook)
    assert h.session.transport.sink is h.daily
    assert {e.run for e in h.run.audit.events} == {h.run.run_id}
    assert [e.ev for e in h.daily.events] == ["session_open"]
    assert len(h.run.raw) == 1 and h.run.raw[0].count(",") == 21
    with h.transaction(run=False, envelope=None):
        pass
    assert h.run.audit.events[-1].ev == "lock_released"
    assert h.daily.events[-1].ev == "lock_released" and h.daily.events[-1].run is None


def test_audit_failure_never_blocks_cleanup_or_release(tmp_path: Path) -> None:
    """A run sink that cannot write (disk full): every audited I/O raises after reaching the instrument, so the
    transaction fails at its baseline drain; cleanup still runs (the commands do reach the simulator), cannot
    prove itself (its steps raise), latches the fault, and the lock and marker are released."""
    h = make_harness(tmp_path)
    run = MemoryRun()

    def full(event: AuditEvent) -> None:
        raise OSError("disk full")

    run.audit._record = full  # type: ignore[method-assign]
    tx = h.session.transaction(intent="x", envelope=None, run=run)
    with pytest.raises(OSError, match="disk full"), tx:
        pytest.fail("the body must not run")  # pragma: no cover
    assert tx.audit_failures and any(f.startswith("lock_acquired") for f in tx.audit_failures)
    assert tx.cleanup is not None and tx.cleanup.latched_fault
    assert {"DZ", "CL"} <= {r.mnemonic for r in h.log if r.outcome == "ok"}
    h.sim.instrument.assert_safe()
    assert h.session.fault_latch.get() is not None
    assert h.session.lock.holder() is None and not (tmp_path / "inflight.json").exists()


# -- snapshot, shared state --------------------------------------------------------------------------------------------


def test_snapshot_is_read_only_and_cached(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    live = h.session.snapshot()
    assert live.identity is not None and live.identity.model == "B1500A"
    assert live.inventory is not None and live.inventory.model_in_slot(3) == "B1517A"
    assert live.status_byte is not None and live.status_byte.interlock_open  # nmos_basic: interlock open
    assert not any(o.output_on for o in live.outputs.values()) and live.errors == []
    assert {r.mnemonic for r in h.log} == {"*IDN?", "UNT?", "ERRX?", "*STB?", "LOP?"}
    count = len(h.log)
    assert h.session.snapshot(refresh=False) is live and len(h.log) == count
    assert h.session.lock.holder() is None


def test_two_sessions_share_the_simulator_state(tmp_path: Path) -> None:
    first = make_harness(tmp_path)
    with first.transaction(run=False) as tx:
        tx.driver.enable([GATE, DRAIN])
        tx.driver.force_v(DRAIN, 0.2, icomp=1e-3)
        mid = first.sim.instrument.outputs()[DRAIN]
        assert mid.output_on and mid.voltage == 0.2
    second = make_harness(tmp_path)  # another process's simulator: it loads the state saved under the lock
    live = second.session.snapshot()
    assert not live.outputs[DRAIN].output_on  # the first transaction's cleanup is what the second one sees
    commands = [r.mnemonic for r in second.log]
    assert "DV" in commands and commands.index("CL") > commands.index("DV")


# -- cleanup on the hardware path -----------------------------------------------------------------------------------


def test_hardware_cleanup_verifies_with_lop() -> None:
    spy = HwSpy(answers={"ERRX?": ['305,"Excess current"', NO_ERROR], "LOP?": LOP_OFF})
    events = Recorder()
    outcome = run_cleanup(B1500Driver(spy), always_abort=True, emit=events)
    report = outcome.report
    assert spy.sent == ["AB", "UNT?", "DZ", "CL", "ERRX?", "ERRX?", "LOP?"]  # inventory unknown: read once
    assert report.verified == "lop" and report.outputs_after == {slot: "00" for slot in range(1, 11)}
    assert [e.code for e in report.errors] == [305] and outcome.deferred is None
    assert [d["step"] for ev, d, _ in events.events if ev == "cleanup_step" and d] == [
        "abort", "zero", "disconnect", "drain_errors", "verify"]


def test_hardware_cleanup_retries_once_then_reports_unverified() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_ON})
    outcome = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder())
    report = outcome.report
    assert report.verified == "unverified" and report.outputs_after[1] == "01"
    assert [(s.attempt, s.step, s.ok) for s in report.steps] == [
        (1, "zero", True), (1, "disconnect", True), (1, "drain_errors", True), (1, "verify", False),
        (2, "device_clear", True), (2, "zero", True), (2, "disconnect", True), (2, "drain_errors", True),
        (2, "verify", False)]
    assert ("device_clear", "") in spy.log
    assert sum(1 for kind, cmd in spy.log if kind == "query" and cmd == "LOP?") == 2


def test_abort_timeout_triggers_device_clear_then_abort() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF}, fail_writes={"AB": [TransportTimeout("stuck")]})
    driver = B1500Driver(spy)
    driver._measurement_pending = True  # XE was issued and its read never completed
    outcome = run_cleanup(driver, always_abort=False, emit=Recorder())
    assert outcome.report.verified == "lop"
    kinds = [entry for entry in spy.log if entry[0] in {"write", "write-failed", "device_clear"}]
    assert kinds[:4] == [("write-failed", "AB"), ("device_clear", ""), ("write", "AB"), ("write", "DZ")]
    assert outcome.report.steps[0].step == "abort" and outcome.report.steps[0].ok
    assert "device clear" in outcome.report.steps[0].detail


def test_interrupt_inside_cleanup_is_deferred() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF}, fail_writes={"DZ": [KeyboardInterrupt()]})  # type: ignore[list-item]
    outcome = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder())
    assert isinstance(outcome.deferred, KeyboardInterrupt)
    assert outcome.report.verified == "lop"  # the retry completed the cleanup
    assert next(s.step for s in outcome.report.steps if s.attempt == 2) == "device_clear"


def test_safe_shutdown_with_an_unopenable_transport_latches(tmp_path: Path) -> None:
    class Unreachable(SpyTransport):
        backend = "visa"
        resource = "GPIB0::17::INSTR"

        def open(self) -> None:
            raise TransportError("VISA library not found")

    daily = MemoryAuditSink()
    session = Session(Settings(), Unreachable, daily, state_dir=tmp_path)
    report = session.safe_shutdown(reason="test")
    assert report.verified == "unverified" and report.latched_fault and "VISA library" in report.steps[0].detail
    record = session.fault_latch.get()
    assert record is not None and "transport unavailable" in record.reason
    assert session.lock.holder() is None
    assert [e.ev for e in daily.events][-2:] == ["cleanup_unverified", "fault"]


# -- bus lifecycle (blueprint v2 2.4) ----------------------------------------------------------------------------------


def test_the_bus_is_opened_and_closed_per_transaction_and_snapshot(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    assert not h.session.bus_open
    with h.transaction() as tx:
        assert h.session.bus_open and h.sim.locked
        acquire(tx, h.hook)
    assert not h.session.bus_open and not h.sim._open and not h.sim.locked
    run_events = [e.ev for e in h.run.audit.events]
    assert run_events[:3] == ["lock_acquired", "bus_open", "bus_lock"]
    assert run_events[-3:] == ["bus_unlock", "bus_close", "lock_released"]
    h.session.snapshot()
    assert not h.session.bus_open and not h.sim._open
    snapshot = [e.ev for e in h.daily.events if e.ev.startswith("bus_")]
    assert snapshot == ["bus_open", "bus_lock", "bus_unlock", "bus_close"]
    with h.transaction(run=False, envelope=None):
        pass
    opens = [e for e in h.daily.events if e.ev == "session_open"]
    assert len(opens) == 1 and opens[0].data is not None and opens[0].data["bus"] == "transaction"
    assert h.session.bus_mode == "transaction"


def test_process_mode_opens_once_and_locks_per_transaction(tmp_path: Path) -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    settings = Settings.model_validate({"visa": {"session": "process"}})
    session = Session(settings, lambda: spy, MemoryAuditSink(), state_dir=tmp_path)
    for _ in range(2):
        with session.transaction(intent="x", envelope=None, run=None) as tx:
            assert session.bus_open
        assert tx.cleanup is not None and tx.cleanup.verified == "lop"
        assert session.bus_open and not session.lock.is_held()  # the session stays, the locks do not
    assert session.bus_mode == "process"
    assert [kind for kind, _ in spy.log if kind in ("open", "lock", "unlock", "close")] == [
        "open", "lock", "unlock", "lock", "unlock"]
    session.close()
    assert not session.bus_open and spy.closed


def test_a_failing_unlock_closes_the_bus_and_never_escapes(tmp_path: Path) -> None:
    class StuckLock(HwSpy):
        def unlock(self) -> None:
            super().unlock()
            raise TransportError("unlock failed")

    spy = StuckLock(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    settings = Settings.model_validate({"visa": {"session": "process"}})
    session = Session(settings, lambda: spy, MemoryAuditSink(), state_dir=tmp_path)
    with session.transaction(intent="x", envelope=None, run=None):
        pass
    assert not session.bus_open and spy.closed and session.lock.holder() is None
    with session.transaction(intent="again", envelope=None, run=None):  # reopened
        assert session.bus_open
    assert [kind for kind, _ in spy.log if kind == "open"] == ["open", "open"]


def test_a_bus_that_cannot_open_leaves_nothing_held(tmp_path: Path) -> None:
    class Unreachable(SpyTransport):
        backend = "visa"
        resource = "GPIB0::17::INSTR"

        def open(self) -> None:
            raise TransportError("VISA library not found")

    daily = MemoryAuditSink()
    session = Session(Settings(), Unreachable, daily, state_dir=tmp_path)
    with pytest.raises(TransportError), session.transaction(intent="x", envelope=None, run=None):
        pytest.fail("the body must not run")  # pragma: no cover
    with pytest.raises(TransportError):
        session.snapshot()
    assert not session.bus_open and session.lock.holder() is None
    assert not (tmp_path / "inflight.json").exists()
    failed = [e for e in daily.events if e.ev == "bus_open"]
    assert len(failed) == 2 and all(e.error and "VISA library" in e.error for e in failed)
    assert not any(e.ev == "session_open" for e in daily.events)  # announced only once the bus really opened


def test_a_factory_may_return_a_bus_with_an_audited_link(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    sink = MemoryAuditSink()
    session = Session(h.session.settings, lambda: Bus(flex=AuditingTransport(h.hook, sink)), sink,
                      state_dir=tmp_path / "other")
    assert session.bus.wgfmu is None and session.transport.sink is sink
    assert session.snapshot().identity is not None
