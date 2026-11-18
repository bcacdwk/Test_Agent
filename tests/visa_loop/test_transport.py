"""The real ``VisaTransport`` over the visa-loop resource (blueprint v2 2.4, 7.1): terminations, chunked reads,
timeouts, device clear, the exclusive lock across sessions and processes, ``bus_locked``, link loss, the signed
``ERRX?`` answers of the lab firmware, open failures and a close that never raises."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.models.sim import BusLockedFault, Disconnect, ErrxFault, TimeoutFault
from b1500_test_agent.models.station import VisaSettings
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import BusLocked, Transport, TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.visa import VisaTransport, visa_status_codes
from tests.sim.helpers import load_scenario, noiseless
from tests.visa_loop.loop import DEFAULT_RESOURCE, LoopBus, LoopVisaError, codes

SETUP = ("CN 3", "DV 3,0,0.1,1E-3", "MM 1,3")
SWEEP_FMT5 = ("FMT 5", "CN 3,4", "DV 3,0,0.1,1E-3", "MM 2,3", "WV 4,1,0,0,1.5,151,1E-4", "XE")
"""A 151-step gate sweep of nmos_basic (gate SMU4, drain SMU3) in FMT 5: one long comma-terminated data message."""


def visa(bus: LoopBus, **cfg: object) -> VisaTransport:
    settings = VisaSettings(**{"resource": DEFAULT_RESOURCE, "timeout_ms": 1000, "lock_timeout_ms": 200, **cfg})
    return VisaTransport(settings, rm_factory=bus.manager)


def opened(bus: LoopBus, **cfg: object) -> VisaTransport:
    transport = visa(bus, **cfg)
    transport.open()
    transport.lock()
    return transport


@pytest.fixture
def bus(tmp_path: Path) -> LoopBus:
    return LoopBus(tmp_path / "bus", noiseless(load_scenario("nmos_basic")))


def test_status_codes_are_pyvisas_own() -> None:
    assert codes() == visa_status_codes()
    assert codes()["timeout"] == 0xBFFF0015 - (1 << 32)  # VI_ERROR_TMO
    assert codes()["resource_locked"] == 0xBFFF000F - (1 << 32)  # VI_ERROR_RSRC_LOCKED
    assert LoopVisaError("timeout", "x").error_code == codes()["timeout"]


def test_open_does_not_lock_and_the_lock_is_exclusive_across_processes(bus: LoopBus) -> None:
    first = visa(bus)
    assert isinstance(first, Transport)
    first.open()
    assert first.is_open and not first.locked and bus.lock_is_free()
    first.lock()
    first.lock()  # idempotent while locked
    assert first.locked and not bus.lock_is_free()
    other = visa(LoopBus(bus.directory, bus.scenario))  # another process: its own VISA library, same instrument
    other.open()
    start = time.monotonic()
    with pytest.raises(BusLocked, match="200 ms") as caught:
        other.lock()
    assert time.monotonic() - start >= 0.15 and caught.value.code == "instrument_busy"
    with pytest.raises(BusLocked, match="another VISA client"):
        other.query("*IDN?")  # I/O without the lock while another session holds it: VI_ERROR_RSRC_LOCKED
    first.unlock()
    assert not first.locked and bus.lock_is_free()
    other.lock()
    assert other.query("*IDN?").startswith("Keysight Technologies,B1500A")
    other.close()
    first.close()
    assert bus.lock_is_free() and not first.is_open


def test_close_releases_the_lock_and_never_raises(bus: LoopBus) -> None:
    transport = opened(bus)
    assert not bus.lock_is_free()
    transport.close()
    transport.close()
    assert bus.lock_is_free() and not transport.locked
    broken = opened(bus)
    broken._inst.close()  # the session died underneath (power cycle, cable): close still succeeds
    broken.close()
    assert bus.lock_is_free()
    broken.unlock()  # not locked any more: nothing to do


def test_terminations_strip_the_carriage_return(bus: LoopBus) -> None:
    resource = bus.manager("@ivi").open_resource(DEFAULT_RESOURCE)
    resource.lock_excl(timeout=100)
    resource.write_termination = "\n"
    for termination, expected in (("\n", "1\r"), ("\r\n", "1"), (None, "1\r\n")):
        resource.read_termination = termination
        resource.write("*OPC?")
        assert resource.read() == expected
    resource.close()
    for read_termination, write_termination in (("\n", "\n"), ("\r\n", "\r\n")):
        transport = opened(bus, read_termination=read_termination, write_termination=write_termination)
        assert transport.query("*OPC?") == "1"
        transport.write("CN 3")
        assert bus.instrument.commands("CN")[-1].outcome == "ok"
        transport.close()


def test_fmt5_data_end_at_eoi_and_long_answers_come_in_chunks(tmp_path: Path) -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    reference = SimTransport(scenario, state_file=None)
    reference.open()
    for cmd in SWEEP_FMT5:
        reference.write(cmd)
    assert reference.instrument.errors == []
    expected = reference.read(timeout_s=30.0)
    bus = LoopBus(tmp_path / "bus", scenario, chunk_size=64)
    transport = opened(bus)
    for cmd in SWEEP_FMT5:
        transport.write(cmd)
    text = transport.read(timeout_s=30.0)
    assert text == expected and text.endswith(",")  # no LF: the message ends at EOI
    assert bus.stats.max_chunks >= len(text) // 64
    transport.close()


def test_a_read_timeout_restores_the_timeout_and_the_session_survives(bus: LoopBus) -> None:
    transport = opened(bus, timeout_ms=300)
    clock = bus.instrument.clock
    with pytest.raises(TransportTimeout):
        transport.read(timeout_s=0.05)
    assert bus.instrument.clock == pytest.approx(clock + 0.05)  # waited 50 ms of virtual time
    assert transport._inst.timeout == 300
    assert transport.query("*OPC?") == "1"
    transport.close()


def test_a_hung_measurement_times_out_and_device_clear_recovers(bus: LoopBus) -> None:
    bus.inject(TimeoutFault(on="XE"))
    transport = opened(bus)
    for cmd in (*SETUP, "XE"):
        transport.write(cmd)
    with pytest.raises(TransportTimeout):
        transport.read(timeout_s=1.0)
    assert bus.instrument.measurement_pending
    transport.device_clear()
    assert not bus.instrument.measurement_pending and bus.stats.clears == 1
    bus.instrument.assert_safe()  # device clear initialises like power-on (PG PDF 175)
    assert transport.query("*OPC?") == "1"
    transport.close()


def test_bus_locked_fault_refuses_the_lock_and_nothing_is_sent(bus: LoopBus) -> None:
    bus.inject(BusLockedFault(count=1))
    transport = visa(bus)
    transport.open()
    before = len(bus.instrument.command_log)
    with pytest.raises(BusLocked, match="nothing was sent"):
        transport.lock()
    assert not transport.locked and bus.stats.lock_refusals == 1 and len(bus.instrument.command_log) == before
    transport.lock()
    assert transport.query("*OPC?") == "1"
    transport.close()


def test_exclusive_lock_off_never_locks_but_a_foreign_holder_still_blocks_io(bus: LoopBus) -> None:
    transport = opened(bus, exclusive_lock=False)
    assert not transport.locked and bus.lock_is_free() and bus.stats.locks == 0
    assert transport.query("*OPC?") == "1"
    with bus.foreign_lock(), pytest.raises(BusLocked):
        transport.query("*IDN?")  # EasyEXPERT holds the instrument
    assert transport.query("*OPC?") == "1"
    transport.close()


def test_a_lost_link_is_a_transport_error_not_a_timeout(bus: LoopBus) -> None:
    bus.inject(Disconnect(after_writes=0))
    transport = opened(bus)
    with pytest.raises(TransportError, match="connection_lost") as caught:
        transport.write("CN 3")
    assert not isinstance(caught.value, TransportTimeout)
    assert bus.instrument.command_log[-1].outcome == "dropped"
    transport.close()


@pytest.mark.parametrize("signed", [True, False])
def test_errx_answers_parse_in_both_success_forms(tmp_path: Path, signed: bool) -> None:
    bus = LoopBus(tmp_path / "bus", noiseless(load_scenario("nmos_basic")), signed_errx=signed)
    sink = MemoryAuditSink()
    transport = AuditingTransport(opened(bus), sink)
    driver = B1500Driver(transport)
    assert driver.errors() == []
    bus.inject(ErrxFault(after_cmd="CN", code=305))
    transport.write("CN 3")
    assert [(e.code, e.message) for e in driver.errors()] == [(305, "Excess current in HPSMU.")]
    answers = [e.resp for e in sink.events if e.ev == "query" and e.cmd == "ERRX?"]
    prefix = "+" if signed else ""
    assert answers == [f'{prefix}0,"No Error."', f'{prefix}305,"Excess current in HPSMU."',
                       f'{prefix}0,"No Error."']
    assert bus.stats.signed_errx == (3 if signed else 0)
    transport.close()


def test_open_failures_are_transport_errors(bus: LoopBus) -> None:
    with pytest.raises(TransportError, match="resource_not_found"):
        visa(bus, resource="GPIB0::18::INSTR").open()

    def no_library(library: str) -> object:
        raise OSError(f"no VISA library {library}")

    with pytest.raises(TransportError, match="Cannot load VISA library"):
        VisaTransport(VisaSettings(), rm_factory=no_library).open()
    assert bus.manager("@ivi").list_resources() == (DEFAULT_RESOURCE,)  # what the bring-up probe lists


def test_two_buses_share_one_instrument_through_the_state_file(bus: LoopBus) -> None:
    """Two processes (two ``LoopBus`` objects) see one instrument: outputs set by one are what the other reads."""
    other_bus = LoopBus(bus.directory, bus.scenario)
    first = opened(bus)
    first.write("CN 3")
    first.write("DV 3,0,0.2,1E-3")
    first.unlock()
    first.close()
    second = opened(other_bus)
    assert second.query("LOP?").startswith("LOP00,00,")  # slot 3 on: not all zero
    assert other_bus.instrument.outputs()[3].output_on and other_bus.instrument.outputs()[3].voltage == 0.2
    second.write("DZ")
    second.write("CL")
    second.close()
    third = opened(bus)
    bus.instrument.assert_safe()  # reloaded the state the other process saved
    seqs = [r.seq for r in bus.instrument.command_log]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    third.close()
    assert bus.stats.loads == 1 and other_bus.stats.loads == 1
