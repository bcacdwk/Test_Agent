"""FLEX row "Identity/status" of blueprint 3: ``*IDN?`` ``UNT?`` ``ERRX?`` ``*STB?`` (+serial poll) ``*OPC?``
``*RST`` ``LOP?`` ``*TST?`` ``*CAL?``."""

from __future__ import annotations

import re

import pytest

from b1500_test_agent.models.station import SimScenario
from tests.sim.helpers import errx_all, noiseless, resistor_scenario, run, scenario_with


def test_idn_returns_the_scenario_identity(make_sim, nmos: SimScenario) -> None:
    sim = make_sim(nmos)
    assert sim.query("*IDN?") == nmos.idn
    assert sim.backend == "sim" and sim.resource == "SIM::nmos_basic"


def test_unt_lists_ten_slots_model_revision(make_sim) -> None:
    """``UNT?``: Slot1Model,Slot1Revision;...;Slot10Model,Slot10Revision; empty slots ``0,0`` (PG PDF 545)."""
    sim = make_sim()
    answer = sim.query("UNT?")
    entries = answer.split(";")
    assert len(entries) == 10
    assert entries[:7] == ["B1511B,0", "B1511B,0", "B1517A,0", "B1517A,0", "B1530A,0", "B1525A,0", "B1520A,0"]
    assert entries[7:] == ["0,0"] * 3
    assert sim.query("UNT? 1").split(";")[0] == "B1500A,0"  # mode 1 adds the mainframe
    sim.write("UNT? 2")
    assert errx_all(sim) == [120]


def test_errx_drains_the_queue_in_order_with_messages(make_sim) -> None:
    sim = make_sim()
    assert sim.query("ERRX?") == '0,"No Error."'
    sim.write("NOPE")
    sim.write("DV 1,0,1.0,1E-3")  # output switch off -> 200
    assert sim.query("ERRX?") == '100,"Undefined GPIB command."'
    assert sim.query("ERRX? 1") == "200"
    assert sim.query("ERRX? 0") == '0,"No Error."'


def test_stb_bits_interlock_ready_error_and_data(make_sim, nmos: SimScenario) -> None:
    """Bit 0 data ready, bit 3 interlock open (an event: a refused request above 42 V), bit 4 set ready, bit 5 error
    (PG PDF 76-77). An open interlock alone leaves bit 3 clear (WP11.1, ATV-10)."""
    sim = make_sim(nmos)  # interlock_closed: false
    assert int(sim.query("*STB?")) == 16
    closed = make_sim(nmos.model_copy(update={"interlock_closed": True}))
    assert int(closed.query("*STB?")) == 16
    sim.write("CN 3")
    sim.write("DV 3,0,43,1E-3")  # above the interlock-open limit: refused, error 202, bit 3
    assert int(sim.query("*STB?")) == 8 | 16 | 32
    assert sim.query("ERRX? 1") == "202" and int(sim.query("*STB?")) == 8 | 16  # ERRX? clears bit 5 only
    sim.write("NOPE")
    assert int(sim.query("*STB?")) & 32
    sim.write("*IDN?")  # unread response -> data ready
    assert sim.serial_poll() & 1
    assert sim.read() == nmos.idn


def test_serial_poll_reads_without_touching_the_buffer_and_clears_the_error_bit(make_sim) -> None:
    sim = make_sim()
    sim.write("NOPE")
    sim.write("*OPC?")
    first = sim.serial_poll()
    assert first & 32 and first & 1 and not first & 8  # no high-voltage request: bit 3 clear
    assert not sim.serial_poll() & 32  # serial poll clears bit 5
    assert sim.read() == "1"  # the buffered *OPC? answer is still there
    assert errx_all(sim) == [100]  # the error itself stays queued


def test_opc_answers_one_after_the_measurement(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 1,3", "WT 0.5,0.01", "MM 2,3", "WV 1,1,0,0,1,11,1E-4", "XE")
    start = sim.instrument.clock
    assert sim.query("*OPC?") == "1"
    assert sim.instrument.clock - start == pytest.approx(0.5 + 11 * (0.01 + 1 / 50 / 128))


def test_rst_initialises_and_must_be_sent_alone(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 1,3", "DV 1,0,1.0,1E-3", "FMT 5,1")
    sim.write("*RST;CN 1")
    assert errx_all(sim) == [103]
    assert sim.instrument.outputs()[1].output_on  # nothing of the combined line ran
    assert [r.outcome for r in sim.instrument.command_log if r.line == "*RST;CN 1"] == ["rejected", "rejected"]
    run(sim, "*RST")
    sim.instrument.assert_safe()
    run(sim, "CN 1", "MM 1,1", "XE")
    data = sim.read()
    assert len(data) == 15 and not data.endswith(",")  # FMT back to 1,0: one element, CR/LF terminator


def test_lop_reports_slot_status_codes(make_sim) -> None:
    """``LOP?`` = ``LOP`` + 10 two-digit codes (Table 4-26, PDF 446-447): 00 off, 01 V source, 12/13 compliance,
    40 MFCMU."""
    sim = make_sim(resistor_scenario(1000.0))
    assert sim.query("LOP?") == "LOP" + ",".join(["00"] * 10)
    run(sim, "CN 1,3,7", "DV 3,0,0,1E-1", "DV 1,0,1.0,1E-1")
    answer = sim.query("LOP?")
    assert re.fullmatch(r"LOP\d\d(,\d\d){9}", answer)
    codes = answer[3:].split(",")
    assert codes[0] == "01" and codes[2] == "01" and codes[6] == "40" and codes[4] == "00"
    run(sim, "DV 1,0,1.0,1E-4")  # 1 mA would flow: positive current compliance on SMU1 (SMU3 sinks it)
    codes = sim.query("LOP?")[3:].split(",")
    assert codes[0] == "12"
    run(sim, "DV 1,0,-1.0,1E-4")
    assert sim.query("LOP?")[3:].split(",")[0] == "13"
    run(sim, "DZ", "CL")
    assert sim.query("LOP?") == "LOP" + ",".join(["00"] * 10)


@pytest.mark.parametrize("query", ["*TST?", "*CAL?", "*TST? 0,1", "*CAL? 3", "*TST? 11"])
def test_selftest_and_selfcal_pass_and_leave_outputs_closed(make_sim, query: str) -> None:
    sim = make_sim()
    run(sim, "CN 1,3", "DV 1,0,0.5,1E-3")
    assert sim.query(query) == "0"
    sim.instrument.assert_safe()
    assert errx_all(sim) == []


def test_selftest_of_an_empty_slot_is_an_error(make_sim) -> None:
    sim = make_sim()
    sim.write("*TST? 9")
    sim.write("*CAL? 12")
    assert errx_all(sim) == [153, 120]


def test_selftest_refused_in_the_high_voltage_state() -> None:
    from b1500_test_agent.transport.sim import SimTransport

    scenario = noiseless(scenario_with({"o": {"model": "open"}}, {"o": {"x": 1}}, interlock_closed=True))
    sim = SimTransport(scenario, state_file=None)
    sim.open()
    run(sim, "CN 1", "DV 1,0,50,1E-3")
    sim.write("*TST?")
    assert errx_all(sim) == [213]
