"""Every ``SimFault`` kind triggers as specified (blueprint 3; WP1.6 builds its safety matrix on these)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.sim import (
    FAULT_KINDS,
    CleanupFailure,
    ComplianceAt,
    Disconnect,
    ErrxFault,
    GarbageData,
    IdnOverride,
    IgnoreDz,
    InterlockOpen,
    ModulesOverride,
    Oscillation,
    SimFaultProfile,
    Slow,
    TimeoutFault,
    parse_fault,
)
from b1500_test_agent.models.station import SimSlot
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from tests.sim.helpers import errx_all, resistor_scenario, run, scenario_with

SETUP = ("CN 1,3", "DV 3,0,0,1E-2", "MM 2,1,3", "WV 1,1,0,0,1,5,1E-2")


def statuses(data: str) -> list[str]:
    return [e[0] for e in data.split(",")]


def test_every_kind_has_a_schema_and_parses_from_yaml_data() -> None:
    examples = {
        "compliance_at": {"step": 3, "ch": 1}, "errx": {"after_cmd": "XE", "code": 305},
        "timeout": {"on": "query:*OPC?"}, "garbage_data": {"at_step": 0}, "interlock_open": {},
        "disconnect": {"after_writes": 3}, "oscillation": {"steps": [1, 2]}, "idn_override": {"idn": "x"},
        "modules_override": {"slots": [{"slot": 1, "model": "B1517A"}]}, "ignore_dz": {"channels": [1]},
        "cleanup_failure": {"count": 1}, "slow": {"factor": 10},
    }  # fmt: skip
    assert set(examples) == set(FAULT_KINDS)
    for kind, fields in examples.items():
        assert parse_fault({"kind": kind, **fields}).kind == kind
    with pytest.raises(ValidationError):
        parse_fault({"kind": "meteor_strike"})
    with pytest.raises(ValidationError):
        parse_fault({"kind": "timeout", "on": "write"})
    with pytest.raises(ValidationError):
        SimFaultProfile.model_validate({"name": "x", "faults": []})


def test_compliance_at_forces_c_on_the_channel_and_t_on_the_others(make_sim) -> None:
    sim = make_sim(resistor_scenario(1e6), faults=[ComplianceAt(step=2, ch=3)])
    run(sim, *SETUP, "XE")
    data = sim.read().split(",")
    assert statuses(",".join(data)) == ["N", "N", "N", "N", "T", "C", "N", "N", "N", "N"]
    assert float(data[5][3:]) == pytest.approx(-1e-2)  # +/- Icomp with the sign of the current


def test_errx_queues_the_code_after_the_nth_command_once(make_sim) -> None:
    sim = make_sim(resistor_scenario(), faults=[ErrxFault(after_cmd="XE", code=305, nth=2)])
    run(sim, *SETUP, "XE")
    sim.read()
    sim.write("XE")
    sim.read()
    assert sim.query("ERRX?") == '305,"Excess current in HPSMU."'
    sim.write("XE")
    sim.read()
    assert errx_all(sim) == []


def test_timeout_on_xe_hangs_until_a_lone_ab(make_sim) -> None:
    sim = make_sim(resistor_scenario(), faults=[TimeoutFault(on="XE")])
    run(sim, *SETUP, "XE")
    with pytest.raises(TransportTimeout):
        sim.read(timeout_s=5)
    with pytest.raises(TransportTimeout):
        sim.query("*OPC?", timeout_s=5)  # queued behind the hung measurement
    sim.device_clear()
    run(sim, *SETUP, "XE")  # one-shot: the next measurement completes
    assert len(sim.read().split(",")) == 10


def test_timeout_on_another_command_keeps_the_instrument_busy(make_sim) -> None:
    sim = make_sim(faults=[TimeoutFault(on="CN")])
    sim.write("CN 1")
    assert not sim.serial_poll() & 16  # set-ready bit stays off
    sim.write("DV 1,0,0.5,1E-3")
    assert sim.instrument.commands(mnemonic="DV")[-1].outcome == "queued"
    with pytest.raises(TransportTimeout):
        sim.query("*OPC?", timeout_s=1)
    sim.write("AB")  # cannot pass the queued commands
    sim.device_clear()
    assert sim.query("*OPC?") == "1"
    sim.instrument.assert_safe()


def test_timeout_on_read_times_out_once_and_keeps_the_data(make_sim) -> None:
    sim = make_sim(resistor_scenario(), faults=[TimeoutFault(on="read")])
    run(sim, *SETUP, "XE")
    with pytest.raises(TransportTimeout):
        sim.read()
    assert len(sim.read().split(",")) == 10


def test_timeout_on_a_query_blocks_reads_until_device_clear(make_sim) -> None:
    sim = make_sim(faults=[TimeoutFault(on="query:*OPC?", nth=2)])
    assert sim.query("*OPC?") == "1"
    with pytest.raises(TransportTimeout):
        sim.query("*OPC?")
    with pytest.raises(TransportTimeout):
        sim.query("*IDN?")
    sim.device_clear()
    assert sim.query("*OPC?") == "1"


def test_garbage_data_makes_one_element_unparsable(make_sim) -> None:
    sim = make_sim(resistor_scenario(), faults=[GarbageData(at_step=1)])
    run(sim, *SETUP, "XE")
    data = sim.read().split(",")
    assert data[2] == GARBAGE_ELEMENT and len(data) == 10
    with pytest.raises(ValueError):
        float(data[2][3:])


def test_interlock_open_now_sets_stb_bit_3_and_blocks_high_voltage(make_sim) -> None:
    closed = scenario_with({"o": {"model": "open"}}, {"o": {"x": 1}}, interlock_closed=True)
    sim = make_sim(closed)
    assert not sim.serial_poll() & 8
    sim.inject(InterlockOpen())
    assert sim.serial_poll() & 8 and int(sim.query("*STB?")) & 8
    run(sim, "CN 1")
    sim.write("DV 1,0,50,1E-3")
    assert errx_all(sim) == [202]
    sim.clear_faults()
    assert not sim.serial_poll() & 8


def test_interlock_opening_mid_sweep_in_the_high_voltage_state_zeroes_outputs(make_sim) -> None:
    closed = resistor_scenario(1e6, interlock_closed=True)
    sim = make_sim(closed, faults=[InterlockOpen(at_step=2)])
    run(sim, "FMT 1,1", "CN 1,3", "DV 3,0,0,1E-2", "MM 2,3", "WV 1,1,0,40,60,5,1E-3")  # 40 45 50 55 60 V
    sim.write("XE")
    data = sim.read().split(",")
    assert statuses(",".join(data[0::2])) == ["N", "N", "V", "V", "V"]
    assert data[4] == "VCI+199.999E+99"
    assert sim.query("ERRX? 1") == "202"
    assert all(st.voltage == 0.0 for st in sim.instrument.outputs().values())
    assert sim.serial_poll() & 8


def test_interlock_opening_mid_sweep_at_low_voltage_only_sets_the_bit(make_sim) -> None:
    sim = make_sim(resistor_scenario(1e6, interlock_closed=True), faults=[InterlockOpen(at_step=1)])
    assert not sim.serial_poll() & 8
    run(sim, *SETUP, "XE")
    assert set(statuses(sim.read())) == {"N"}
    assert sim.serial_poll() & 8 and errx_all(sim) == []


def test_disconnect_drops_the_link_and_keeps_the_outputs(make_sim) -> None:
    sim = make_sim(faults=[Disconnect(after_writes=2)])
    run(sim, "CN 1", "DV 1,0,0.5,1E-3")
    with pytest.raises(TransportError, match="link lost"):
        sim.write("DZ")
    for action in (sim.read, sim.serial_poll, sim.device_clear, lambda: sim.query("*IDN?")):
        with pytest.raises(TransportError):
            action()
    assert sim.instrument.outputs()[1].voltage == 0.5  # nothing reached the instrument
    assert sim.instrument.commands(mnemonic="DZ")[-1].outcome == "dropped"
    sim.clear_faults()
    run(sim, "DZ", "CL")
    sim.instrument.assert_safe()


def test_oscillation_marks_steps_with_x(make_sim) -> None:
    sim = make_sim(resistor_scenario(), faults=[Oscillation(steps=[1, 3])])
    run(sim, *SETUP, "XE")
    assert statuses(sim.read()) == ["N", "N", "X", "X", "N", "N", "X", "X", "N", "N"]
    sim.clear_faults()
    sim.inject(Oscillation())
    run(sim, "XE")
    assert set(statuses(sim.read())) == {"X"}


def test_identity_and_module_overrides(make_sim) -> None:
    swapped = [SimSlot(slot=1, model="B1517A"), SimSlot(slot=3, model="B1511B")]
    sim = make_sim(faults=[IdnOverride(idn="Keysight Technologies,B1505A,0,A.01"), ModulesOverride(slots=swapped)])
    assert sim.query("*IDN?") == "Keysight Technologies,B1505A,0,A.01"
    assert sim.query("UNT?").split(";")[:4] == ["B1517A,0", "0,0", "B1511B,0", "0,0"]
    sim.write("CN 2")
    assert errx_all(sim) == [153]
    run(sim, "RI 1,9")  # slot 1 is now an HRSMU: the 10 pA range exists


def test_ignore_dz_leaves_the_output_stuck_so_verification_fails(make_sim) -> None:
    sim = make_sim(faults=[IgnoreDz(channels=[1])])
    run(sim, "CN 1,3", "DV 1,0,0.5,1E-3", "DV 3,0,0.1,1E-3", "DZ", "CL", "*RST")
    sim.device_clear()
    outputs = sim.instrument.outputs()
    assert outputs[1].output_on and outputs[1].voltage == 0.5
    assert not outputs[3].output_on and outputs[3].voltage == 0.0
    assert sim.query("LOP?").startswith("LOP01,")
    with pytest.raises(AssertionError, match="channel 1"):
        sim.instrument.assert_safe()
    assert all(r.outcome == "ok" for r in sim.instrument.commands(mnemonic="DZ"))  # accepted without error


def test_cleanup_failure_times_out_dz_and_cl_writes(make_sim) -> None:
    sim = make_sim(faults=[CleanupFailure(count=1)])
    run(sim, "CN 1", "DV 1,0,0.5,1E-3")
    with pytest.raises(TransportTimeout):
        sim.write("DZ")
    assert sim.instrument.outputs()[1].voltage == 0.5
    run(sim, "DZ", "CL")  # count=1: the retry gets through
    sim.instrument.assert_safe()
    always = make_sim(faults=[CleanupFailure()])
    run(always, "CN 1")
    for command in ("DZ", "CL", "CL 1", "DZ 1"):
        with pytest.raises(TransportTimeout):
            always.write(command)
    assert [r.outcome for r in always.instrument.command_log[-4:]] == ["dropped"] * 4


def test_slow_makes_reads_time_out_until_the_measurement_ends(make_sim) -> None:
    sim = make_sim(resistor_scenario(), faults=[Slow(factor=1000.0)])
    run(sim, *SETUP, "WT 0,0.01", "XE")  # 5 steps x (10 ms + 2 x 0.156 ms) x 1000 = 51.6 s (virtual)
    with pytest.raises(TransportTimeout):
        sim.read(timeout_s=15.0)
    assert sim.instrument.measurement_pending
    run(sim, "AB")  # abort after 15 s (virtual): the one step measured so far is returned
    assert len(sim.read().split(",")) == 2 * 1  # one step of two channels
    run(sim, "XE")
    assert len(sim.read(timeout_s=60.0).split(",")) == 10


def test_injected_faults_start_counting_at_injection(make_sim) -> None:
    sim = make_sim(resistor_scenario())
    run(sim, *SETUP, "XE")
    sim.read()
    sim.inject(ErrxFault(after_cmd="XE", code=305))
    run(sim, "BC")
    sim.write("XE")
    sim.read()
    assert errx_all(sim) == [305]
