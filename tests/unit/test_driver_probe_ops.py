"""Driver queries of the read-only probe (``SwitchOps``, ``SpguOps``, ``CmuOps``; blueprint v2 2.5, 7.1) and the
``ReadOnlyTransport`` that lets only queries reach the instrument."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.ops.cmu import CmuOps
from b1500_test_agent.driver.ops.spgu import SpguOps
from b1500_test_agent.driver.ops.switch import SwitchOps
from b1500_test_agent.models.station import CmuCorrectionLive
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.readonly import ReadOnlyTransport, ReadOnlyViolation, is_query
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.state import CmuPersistent
from tests.sim.helpers import load_scenario, noiseless


@pytest.fixture
def sim() -> SimTransport:
    transport = SimTransport(noiseless(load_scenario("lab_station")), state_file=None)
    transport.open()
    return transport


def test_the_driver_carries_the_family_query_mixins() -> None:
    assert issubclass(B1500Driver, CmuOps) and issubclass(B1500Driver, SpguOps) and issubclass(B1500Driver, SwitchOps)


def test_family_queries_parse_the_simulator_answers(sim: SimTransport) -> None:
    driver = B1500Driver(sim)
    assert driver.selector_control_mode() == 0
    assert driver.selector_state(2) == "open"
    assert driver.pulse_output_active() is False
    assert driver.correction_state(7) == CmuCorrectionLive(corr_state={"open": False, "short": False,
                                                                       "load": False}, phase=False)
    state = sim.instrument.state
    state.selector_mode, state.selector_ports[2], state.spgu_output_active = 1, 3, True
    state.cmu_corrections[7] = {1: True, 3: True}
    state.cmu_phase_results[7] = 0
    assert (driver.selector_control_mode(), driver.selector_state(2), driver.pulse_output_active()) == (
        1, "pgu_open", True)
    # a completed compensation is in effect only in the manual (or load adaptive) mode; auto is the *RST state
    assert driver.correction_state(7).phase is False
    state.cmu[7] = CmuPersistent(adj_mode=1)
    assert driver.correction_state(7) == CmuCorrectionLive(corr_state={"open": True, "short": False, "load": True},
                                                           phase=True)
    assert driver.phase_compensation_result(7) == 0
    state.cmu[7] = CmuPersistent(adj_mode=2)
    state.cmu_phase_results[7] = 3
    assert driver.correction_state(7).phase is True  # load adaptive: compensated before every measurement
    sent = [r.command for r in sim.instrument.command_log]
    assert "ADJ? 7,0" in sent and all(not c.startswith("ADJ? 7,1") and c != "ADJ? 7" for c in sent)


def test_a_malformed_answer_is_a_parse_error() -> None:
    class Garbage:
        backend, resource = "sim", "SIM::x"

        def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
            return "x"

    with pytest.raises(FlexParseError):
        B1500Driver(Garbage()).selector_control_mode()  # type: ignore[arg-type]


@pytest.mark.parametrize(("cmd", "query"), [
    ("*IDN?", True), ("UNT?", True), ("ERSSP? 0", True), ("CORRST? 7,1", True), ("*LRN? 31", True),
    (" LOP? ", True), ("CN 3", False), ("CL", False), ("*RST", False), ("ERMOD 1", False), ("DZ", False),
    ("ERRX?;CN 1", False), ("*IDN?\nCN 1", False), ("", False), ("? CN", False),
])
def test_is_query(cmd: str, query: bool) -> None:
    assert is_query(cmd) is query


def test_read_only_transport_refuses_everything_but_queries(sim: SimTransport) -> None:
    sink = MemoryAuditSink()
    reader = ReadOnlyTransport(AuditingTransport(sim, sink))
    assert reader.query("*IDN?").startswith("Agilent Technologies,B1500A")
    reader.write("UNT?")
    assert reader.read().startswith("B1525A")
    for call in (lambda: reader.write("CN 3"), lambda: reader.query("DZ"), lambda: reader.write("*RST"),
                 lambda: reader.query("ERRX?;CN 3"), reader.device_clear, reader.serial_poll):
        with pytest.raises(ReadOnlyViolation):
            call()
    assert [(e.cmd, e.resp is not None) for e in reader.transcript] == [("*IDN?", True), ("UNT?", True)]
    assert [r.command for r in sim.instrument.command_log] == ["*IDN?", "UNT?"]  # nothing else reached it
    assert {e.ev for e in sink.events} <= {"query", "write", "read"}
    assert reader.backend == "sim" and reader.resource == sim.resource


def test_read_only_transcript_records_a_failed_query(sim: SimTransport) -> None:
    reader = ReadOnlyTransport(sim)
    sim.close()
    with pytest.raises(Exception, match="not open"):
        reader.query("*IDN?")
    assert reader.transcript[0].cmd == "*IDN?" and reader.transcript[0].resp is None
    assert reader.transcript[0].error and "TransportClosed" in reader.transcript[0].error
