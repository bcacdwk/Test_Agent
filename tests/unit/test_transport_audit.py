"""Audit events and ``AuditingTransport`` (blueprint 2.2, 2.7, v2 2.4): line shape, sinks, one event per I/O and
per bus lifecycle call."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.audit import AuditEvent, format_ts
from b1500_test_agent.models.sim import BusLockedFault, Disconnect, TimeoutFault
from b1500_test_agent.transport.audit import AuditingTransport, JsonlAuditSink, MemoryAuditSink, NullAuditSink
from b1500_test_agent.transport.base import BusLocked, Transport, TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.unit.helpers import CONFIG_DIR, read_yaml

BLUEPRINT_KEYS = ["ts", "seq", "run", "tx", "ev", "cmd", "resp", "dur_ms", "intent", "backend"]


def sim() -> SimTransport:
    from b1500_test_agent.models.station import SimScenario

    data = read_yaml(CONFIG_DIR / "sim" / "scenarios" / "nmos_basic.yaml")
    return SimTransport(SimScenario.model_validate({**data, "name": "nmos_basic"}), state_file=None)


def test_line_has_the_blueprint_shape() -> None:
    event = AuditEvent(ts=datetime(2026, 11, 17, 6, 30, 12, 123456, tzinfo=UTC), seq=17, run="S1", tx="T1",
                       ev="write", cmd="WV 1,1,0,-1.0,3.0,101,1E-6", dur_ms=1.23456, intent="gate sweep",
                       backend="sim")
    line = event.to_json_line()
    assert line == ('{"ts":"2026-11-17T06:30:12.123Z","seq":17,"run":"S1","tx":"T1","ev":"write",'
                    '"cmd":"WV 1,1,0,-1.0,3.0,101,1E-6","resp":null,"dur_ms":1.235,"intent":"gate sweep",'
                    '"backend":"sim"}')
    assert list(json.loads(line)) == BLUEPRINT_KEYS
    assert AuditEvent.from_json_line(line).cmd == event.cmd


def test_timestamps_are_utc_with_milliseconds() -> None:
    local = datetime(2026, 11, 17, 14, 30, 12, 999999, tzinfo=timezone(timedelta(hours=8)))
    assert format_ts(local) == "2026-11-17T06:30:12.999Z"
    with pytest.raises(ValidationError):
        AuditEvent(ts=datetime(2026, 11, 17), ev="write", backend="sim")  # naive time
    with pytest.raises(ValidationError):
        AuditEvent.now("teleport", "sim")  # type: ignore[arg-type]


def test_optional_keys_appear_only_when_set() -> None:
    event = AuditEvent.now("cleanup_step", "sim", data={"step": "zero", "ok": True}, error="TransportTimeout: x")
    record = json.loads(event.to_json_line())
    assert list(record)[:10] == BLUEPRINT_KEYS and record["data"] == {"step": "zero", "ok": True}
    assert record["error"] == "TransportTimeout: x"
    with pytest.raises(ValueError):
        AuditEvent.from_json_line('{"ev":"write"}')


def test_sinks_number_events_in_order(tmp_path: Path) -> None:
    memory = MemoryAuditSink()
    for _ in range(3):
        memory.emit(AuditEvent.now("checkpoint", "sim"))
    assert [e.seq for e in memory.events] == [0, 1, 2]
    kept = memory.emit(AuditEvent.now("checkpoint", "sim", seq=10))
    assert kept.seq == 10 and memory.emit(AuditEvent.now("checkpoint", "sim")).seq == 11
    assert NullAuditSink().emit(AuditEvent.now("checkpoint", "sim")).seq == 0


def test_jsonl_sink_appends_utf8_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit" / "2026-11-17.jsonl"
    sink = JsonlAuditSink(path)
    sink.emit(AuditEvent.now("tool_call", "sim", intent="station_status — 状态"))
    JsonlAuditSink(path).emit(AuditEvent.now("tool_call", "sim"))  # a second process appends
    raw = path.read_bytes()
    assert raw.count(b"\n") == 2 and b"\r\n" not in raw
    lines = raw.decode("utf-8").splitlines()
    assert "状态" in lines[0]
    assert [AuditEvent.from_json_line(line).ev for line in lines] == ["tool_call", "tool_call"]


def _count_opens(monkeypatch: pytest.MonkeyPatch, path: Path) -> list[str]:
    opened: list[str] = []
    real = Path.open

    def spy(self: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        mode = str(args[0]) if args else str(kwargs.get("mode", "r"))
        if self == path and "r" not in mode:  # the sink's writes, not the test's reads
            opened.append(mode)
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", spy)
    return opened


def test_held_sink_opens_once_and_flushes_every_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside ``held()`` the file is opened once (Windows pays ~0.3-1 ms per open/close, WP6.5), yet every event is
    on disk as soon as it is emitted (another process reading the file, or a killed process, loses nothing)."""
    path = tmp_path / "run" / "audit.jsonl"
    sink = JsonlAuditSink(path)
    opened = _count_opens(monkeypatch, path)
    with sink.held():
        for index in range(50):
            sink.emit(AuditEvent.now("checkpoint", "sim", data={"i": index}))
            assert len(path.read_bytes().splitlines()) == index + 1  # flushed at once
        with sink.held():  # nested holds share the handle
            sink.emit(AuditEvent.now("checkpoint", "sim"))
        assert sink._handle is not None
    assert opened == ["a"] and sink._handle is None  # closed when the outermost hold ends
    sink.emit(AuditEvent.now("checkpoint", "sim"))  # outside a hold: one open per event again
    assert opened == ["a", "a"]
    lines = path.read_bytes().split(b"\n")
    assert len(lines) == 53 and lines[-1] == b"" and b"\r" not in path.read_bytes()
    assert [AuditEvent.from_json_line(line.decode()).seq for line in lines[:-1]] == list(range(52))


def test_held_sink_follows_the_daily_file_and_a_vanished_folder(tmp_path: Path) -> None:
    from b1500_test_agent.session.session import DailyAuditSink

    sink = DailyAuditSink(tmp_path / "audit")
    day1 = AuditEvent(ts=datetime(2026, 11, 17, 23, 59, 59, tzinfo=UTC), ev="checkpoint", backend="sim")
    day2 = AuditEvent(ts=datetime(2026, 11, 18, 0, 0, 1, tzinfo=UTC), ev="checkpoint", backend="sim")
    with sink.held():
        sink.emit(day1)
        sink.emit(day2)  # UTC midnight inside one hold: the next daily file
    assert len((tmp_path / "audit" / "2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert len((tmp_path / "audit" / "2026-11-18.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    for file in (tmp_path / "audit").iterdir():
        file.unlink()  # every handle is closed after the hold (Windows refuses to delete an open file)
    (tmp_path / "audit").rmdir()
    sink.emit(day2)  # the folder made before is gone: made again
    assert (tmp_path / "audit" / "2026-11-18.jsonl").is_file()


def test_auditing_transport_records_every_io_call() -> None:
    sink = MemoryAuditSink()
    transport = AuditingTransport(sim(), sink)
    assert isinstance(transport, Transport) and transport.backend == "sim" and transport.resource == "SIM::nmos_basic"
    transport.open()
    with transport.bind(run="S20261117T063012Z-7f3a", tx="T1", intent="gate sweep"):
        transport.write("CN 1,3")
        idn = transport.query("*IDN?")
        transport.write("*OPC?")
        assert transport.read() == "1"
        status = transport.serial_poll()
        transport.device_clear()
    transport.write("CL")
    transport.close()
    events = sink.events
    assert [e.ev for e in events] == ["bus_open", "write", "query", "write", "read", "poll", "device_clear", "write",
                                      "bus_close"]
    io = events[1:-1]
    assert io[1].cmd == "*IDN?" and io[1].resp == idn
    assert io[3].cmd is None and io[3].resp == "1"
    assert io[4].resp == str(status)
    assert all(e.run == "S20261117T063012Z-7f3a" and e.intent == "gate sweep" for e in io[:6])
    assert io[6].run is None and io[6].tx is None  # context restored after the block
    assert all(e.dur_ms is not None and e.backend == "sim" for e in events)
    assert all(e.cmd is None and e.resp is None and e.error is None for e in (events[0], events[-1]))
    assert [e.seq for e in events] == list(range(9))


def test_failed_io_is_audited_with_the_error_and_reraised() -> None:
    sink = MemoryAuditSink()
    inner = sim()
    transport = AuditingTransport(inner, sink)
    transport.open()
    inner.inject(TimeoutFault(on="read"))
    with pytest.raises(TransportTimeout):
        transport.read(timeout_s=1.0)
    inner.inject(Disconnect(after_writes=0))
    with pytest.raises(TransportError):
        transport.write("DZ")
    events = sink.events[1:]  # after bus_open
    assert [(e.ev, e.cmd) for e in events] == [("read", None), ("write", "DZ")]
    assert events[0].error.startswith("TransportTimeout") and events[1].error.startswith("TransportError")


def test_bus_lifecycle_is_audited_and_a_refused_lock_carries_the_error() -> None:
    sink = MemoryAuditSink()
    inner = sim()
    transport = AuditingTransport(inner, sink)
    inner.inject(BusLockedFault(count=1))
    transport.open()
    with pytest.raises(BusLocked):
        transport.lock()
    assert not inner.locked
    transport.lock()
    assert inner.locked
    transport.unlock()
    transport.close()
    assert [(e.ev, e.error is None) for e in sink.events] == [
        ("bus_open", True), ("bus_lock", False), ("bus_lock", True), ("bus_unlock", True), ("bus_close", True)]
    assert "bus_locked" in (sink.events[1].error or "")
    assert BusLocked.code == "instrument_busy"


def test_a_failing_sink_never_desynchronizes_the_bus_lifecycle() -> None:
    """Lifecycle auditing is best-effort (an I/O audit failure still raises): the link opens and closes anyway."""

    class Broken(MemoryAuditSink):
        def _record(self, event: AuditEvent) -> None:
            raise OSError("disk full")

    inner = sim()
    transport = AuditingTransport(inner, Broken())
    transport.open()
    transport.lock()
    assert inner.locked
    with pytest.raises(OSError, match="disk full"):
        transport.query("*IDN?")
    transport.unlock()
    transport.close()
    assert not inner.locked
    with pytest.raises(TransportError):
        inner.write("CL")  # closed


def test_nested_bind_restores_the_outer_context() -> None:
    transport = AuditingTransport(sim(), MemoryAuditSink())
    with transport.bind(run="S1", intent="outer"):
        with transport.bind(tx="T9"):
            assert (transport.context.run, transport.context.tx, transport.context.intent) == ("S1", "T9", "outer")
        assert transport.context.tx is None
    assert transport.context.run is None
