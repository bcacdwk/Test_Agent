"""``SimTransport`` implements the ``Transport`` protocol (blueprint 2.2) and the timing modes of blueprint 3."""

from __future__ import annotations

import time

import pytest

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.base import Transport, TransportClosed, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import load_scenario, noiseless, resistor_scenario, run


def test_sim_transport_is_a_transport() -> None:
    transport = SimTransport(noiseless(load_scenario("nmos_basic")), state_file=None)
    assert isinstance(transport, Transport)
    assert transport.backend == "sim" and transport.resource == "SIM::nmos_basic"


def test_io_before_open_and_after_close_raises_transport_closed() -> None:
    transport = SimTransport(noiseless(load_scenario("nmos_basic")), state_file=None)
    for action in (lambda: transport.write("*IDN?"), transport.read, transport.serial_poll, transport.device_clear,
                   lambda: transport.query("*IDN?")):
        with pytest.raises(TransportClosed):
            action()
    transport.open()
    transport.open()  # idempotent
    assert transport.query("*OPC?") == "1"
    transport.close()
    transport.close()
    with pytest.raises(TransportClosed):
        transport.write("*IDN?")


def test_read_with_nothing_buffered_times_out(make_sim) -> None:
    sim = make_sim(timeout_s=2.0)
    start = sim.instrument.clock
    with pytest.raises(TransportTimeout):
        sim.read()
    assert sim.instrument.clock - start == pytest.approx(2.0)
    with pytest.raises(TransportTimeout):
        sim.read(timeout_s=0.5)


def test_reads_strip_crlf_but_keep_the_fmt5_comma(make_sim) -> None:
    sim = make_sim(resistor_scenario())
    sim.write("*IDN?")
    assert not sim.read().endswith(("\r", "\n"))
    run(sim, "FMT 5", "CN 1,3", "DV 3,0,0,1E-2", "MM 1,3", "XE")
    assert sim.read().endswith(",")


def test_query_responses_come_before_measurement_data(make_sim) -> None:
    """As in the PG example (PDF 206): ``*OPC?``, ``NUB?`` answers are read before the data."""
    sim = make_sim(resistor_scenario())
    run(sim, "CN 1,3", "DV 3,0,0,1E-2", "MM 2,3", "WV 1,1,0,0,1,4,1E-2", "XE")
    assert sim.query("*OPC?") == "1"
    assert sim.query("NUB?") == "4"
    assert len(sim.read().split(",")) == 4


def test_instant_timing_never_sleeps_and_scaled_timing_does() -> None:
    commands = ("CN 1,3", "DV 3,0,0,1E-2", "WT 0,0.5", "MM 2,3", "WV 1,1,0,0,1,10,1E-2", "XE")  # 5 s virtual
    instant = SimTransport(resistor_scenario(), state_file=None)
    instant.open()
    run(instant, *commands)
    began = time.perf_counter()
    instant.read()
    assert time.perf_counter() - began < 0.04
    scenario = SimScenario.model_validate({**resistor_scenario().model_dump(), "timing": "scaled"})
    scaled = SimTransport(scenario, state_file=None)
    scaled.open()
    run(scaled, *commands)
    began = time.perf_counter()
    scaled.read()
    assert time.perf_counter() - began >= 0.045  # 5 s x SCALED_TIME_FACTOR (0.01)


def test_serial_poll_advances_time_so_polling_sees_completion(make_sim) -> None:
    sim = make_sim(resistor_scenario())
    run(sim, "CN 1,3", "DV 3,0,0,1E-2", "WT 0,0.05", "MM 2,3", "WV 1,1,0,0,1,4,1E-2", "XE")
    polls = 0
    while not sim.serial_poll() & 16:  # bit 4 "set ready"
        polls += 1
        assert polls < 1000
    assert polls >= 10 and sim.serial_poll() & 1  # data ready once the sweep is done


def test_handle_returns_the_query_response(nmos: SimScenario) -> None:
    transport = SimTransport(nmos, state_file=None)
    assert transport.instrument.handle("*IDN?") == nmos.idn
    assert transport.instrument.handle("CN 1") is None
    assert transport.instrument.handle("") is None
