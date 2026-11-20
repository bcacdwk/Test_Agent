"""Binary blocks and host waits on the transports (WP9.1; ``transport.base.BlockWriter``/``HostClock``): the audit
records a block write with its size and digest, the read-only link refuses it, VISA sends the header then the raw
bytes (and sleeps for a host wait unless the resource manager simulates time), and the simulator's clock moves on a
host wait."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from b1500_test_agent.models.station import VisaSettings
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import BlockWriter, HostClock, TransportError
from b1500_test_agent.transport.readonly import ReadOnlyTransport, ReadOnlyViolation
from b1500_test_agent.transport.visa import VisaTransport
from tests.sim.spgu_helpers import open_sim
from tests.unit.driver_helpers import SpyTransport

pytestmark = pytest.mark.spgu

BLOCK = bytes(range(42))


def test_the_audit_names_the_block_and_forwards_it() -> None:
    sim = open_sim()
    sink = MemoryAuditSink()
    audited = AuditingTransport(sim, sink)
    assert isinstance(audited, BlockWriter) and isinstance(audited, HostClock)
    audited.write("SIM 1")
    audited.write_block("ALW 101,42", BLOCK)
    event = sink.events[-1]
    digest = hashlib.sha256(BLOCK).hexdigest()[:16]
    assert event.ev == "write" and event.cmd == f"ALW 101,42 <block 42 bytes sha256 {digest}>"
    assert sim.instrument.command_log[-1].mnemonic == "<block>"  # delivered (refused as data: 2156, see the sim)
    start = sim.instrument.clock
    audited.wait(0.25)
    assert sim.instrument.clock == pytest.approx(start + 0.25)
    assert not [e for e in sink.events if e.ev not in ("write",)]  # a host wait is not an I/O event


def test_a_link_without_blocks_fails_audited() -> None:
    sink = MemoryAuditSink()
    audited = AuditingTransport(SpyTransport(), sink)
    with pytest.raises(TransportError, match="binary data block"):
        audited.write_block("ALS 26", BLOCK[:26])
    assert sink.events[-1].error is not None


def test_the_read_only_link_refuses_blocks_and_passes_waits() -> None:
    sim = open_sim()
    readonly = ReadOnlyTransport(sim)
    with pytest.raises(ReadOnlyViolation):
        readonly.write_block("ALS 26", BLOCK[:26])
    readonly.wait(1.0)
    assert sim.instrument.clock == pytest.approx(1.0) and sim.instrument.command_log == []


class FakeResource:
    """The parts of a pyvisa resource ``VisaTransport`` uses, recording writes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.timeout = 1000

    def write(self, text: str) -> None:
        self.calls.append(("write", text))

    def write_raw(self, data: bytes) -> None:
        self.calls.append(("write_raw", data))

    def read(self) -> str:
        return ""

    def read_stb(self) -> int:
        return 0

    def clear(self) -> None: ...

    def lock_excl(self, timeout: float = 0) -> None: ...

    def unlock(self) -> None: ...

    def close(self) -> None: ...


class FakeManager:
    def __init__(self, resource: FakeResource, *, clock: list[float] | None = None) -> None:
        self.resource = resource
        if clock is not None:
            self.host_wait = clock.append  # type: ignore[method-assign]

    def open_resource(self, name: str, **_: Any) -> FakeResource:
        return self.resource

    def close(self) -> None: ...


def test_visa_sends_the_header_then_the_raw_block(monkeypatch: pytest.MonkeyPatch) -> None:
    resource = FakeResource()
    transport = VisaTransport(VisaSettings(), rm_factory=lambda _lib: FakeManager(resource))
    transport.open()
    transport.write_block("ALW 101,42", BLOCK)
    assert resource.calls == [("write", "ALW 101,42"), ("write_raw", BLOCK)]
    slept: list[float] = []
    monkeypatch.setattr("b1500_test_agent.transport.visa.time.sleep", slept.append)
    transport.wait(0.1)
    assert slept == [0.1]
    transport.close()


def test_a_simulating_resource_manager_takes_the_host_wait() -> None:
    clock: list[float] = []
    transport = VisaTransport(VisaSettings(), rm_factory=lambda _lib: FakeManager(FakeResource(), clock=clock))
    transport.open()
    transport.wait(0.2)
    assert clock == [0.2]
    transport.close()


class PlainResource(FakeResource):
    """A message-based resource without ``write_raw``."""

    write_raw = None  # type: ignore[assignment]


def test_a_resource_without_write_raw_cannot_send_blocks() -> None:
    resource = PlainResource()
    transport = VisaTransport(VisaSettings(), rm_factory=lambda _lib: FakeManager(resource))
    transport.open()
    with pytest.raises(TransportError, match="write_raw"):
        transport.write_block("ALS 26", BLOCK[:26])
    assert resource.calls == []
    transport.close()
