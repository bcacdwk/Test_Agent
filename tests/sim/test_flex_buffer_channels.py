"""FLEX rows "Buffer/format" (``FMT 1|5[,mode]`` ``BC`` ``NUB?`` ``TSC``) and "Channel" (``CN`` ``CL`` ``DZ`` ``AB``)
of blueprint 3."""

from __future__ import annotations

import itertools

import pytest

from b1500_test_agent.models.sim import TimeoutFault
from tests.sim.helpers import elements, errx_all, resistor_scenario, run

SWEEP = ("CN 1,3", "DV 3,0,0,1E-2", "MM 2,3", "WV 1,1,0,0,1,5,1E-2")


# -- Buffer / format -------------------------------------------------------------------------------------------------


def test_fmt1_without_mode_returns_measurement_data_only(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 1", *SWEEP, "XE")
    data = elements(sim.read())
    assert len(data) == 5 and all(e[:3] == "NCI" for e in data)  # SMU3 measures the current it sinks
    assert [round(float(e[3:]), 9) for e in data] == [-0.0, -0.00025, -0.0005, -0.00075, -0.001]


def test_fmt1_mode1_appends_source_data_w_then_e(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 1,1", *SWEEP, "XE")
    data = elements(sim.read())
    assert len(data) == 10
    sources = data[1::2]
    assert [s[:3] for s in sources] == ["WAV"] * 4 + ["EAV"]  # Table 1-7: W intermediate, E last step
    assert [float(s[3:]) for s in sources] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_fmt5_uses_a_comma_terminator(make_sim) -> None:
    """FMT 5: same elements, terminator ``,`` instead of CR/LF (Table 4-24, PDF 437)."""
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 5,1", *SWEEP, "XE")
    raw = sim.instrument.read_message(1.0)
    assert raw.endswith(",") and "\r" not in raw
    assert len(raw.rstrip(",").split(",")) == 10


@pytest.mark.parametrize(("command", "code"), [("FMT 2", 100), ("FMT 21", 100), ("FMT 1,2", 100), ("FMT 6", 120),
                                               ("FMT 1,11", 120), ("FMT", 103)])
def test_fmt_other_formats_and_modes_are_refused(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]
    [record] = [r for r in sim.instrument.command_log if r.line == command]
    assert record.outcome == ("unsupported" if code == 100 else "error") and record.error == code


@pytest.mark.parametrize("command", ["FMT 1", "BC"])
def test_fmt_and_bc_clear_the_output_buffer_and_must_be_sent_alone(make_sim, command: str) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, *SWEEP, "XE", "*IDN?")  # measurement data and an unread query answer
    assert sim.serial_poll() & 1
    run(sim, command)
    assert not sim.serial_poll() & 1  # both buffers cleared (data-ready bit off, PG PDF 76)
    assert sim.query("NUB?") == "0"
    sim.write(f"{command};CN 2")
    assert errx_all(sim) == [103]
    assert not sim.instrument.outputs()[2].output_on


def test_nub_counts_data_elements(make_sim) -> None:
    """``NUB?`` counts data items, e.g. time + data + source = 3 per step in PG Table 3-7 (PDF 206)."""
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 1,1", "TSC 1", *SWEEP, "XE")
    assert sim.query("NUB?") == "15"
    assert len(elements(sim.read())) == 15
    assert sim.query("NUB?") == "0"


def test_tsc_puts_a_time_element_before_each_data_element(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "TSC 1", "WT 0,0.01", *SWEEP, "XE")
    data = elements(sim.read())
    times = [float(e[3:]) for e in data[0::2]]
    assert all(e[:3] == "NCT" for e in data[0::2]) and all(e[2] == "I" for e in data[1::2])
    steps = [b - a for a, b in itertools.pairwise(times)]
    assert steps == pytest.approx([0.01 + 1 / 50 / 128] * 4, rel=1e-4)
    sim.write("TSC 2")
    assert errx_all(sim) == [120]


# -- Channels --------------------------------------------------------------------------------------------------------


def test_cn_enables_at_zero_volts_and_cl_disables(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 1,3")
    outputs = sim.instrument.outputs()
    assert outputs[1].output_on and outputs[1].voltage == 0.0 and outputs[1].icomp == pytest.approx(1e-4)
    assert not outputs[2].output_on
    run(sim, "CL 1")
    assert not sim.instrument.outputs()[1].output_on and sim.instrument.outputs()[3].output_on
    run(sim, "CL")
    sim.instrument.assert_safe()


def test_cn_without_channels_enables_smu_spgu_and_cmu_but_not_wgfmu(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN")
    on = {ch for ch, st in sim.instrument.outputs().items() if st.output_on}
    assert on == {1, 2, 3, 4, 6, 602, 7}
    sim.write("CN 501")
    assert errx_all(sim) == [151]
    run(sim, "CL")
    sim.instrument.assert_safe()


@pytest.mark.parametrize(("command", "code"), [("CN 9", 153), ("CN 302", 153), ("CN 11", 121), ("DZ 1001", 153)])
def test_channel_numbers_are_checked(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]


def test_channel_101_is_channel_1(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 101", "DV 1,0,0.5,1E-3")
    assert sim.instrument.outputs()[1].voltage == 0.5
    run(sim, "CL 101")
    sim.instrument.assert_safe()


def test_dz_sets_zero_volts_but_keeps_the_switch_on(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 1,3", "DV 1,0,0.7,1E-2", "DV 3,0,0.1,1E-3")
    run(sim, "DZ 1")
    outputs = sim.instrument.outputs()
    assert outputs[1].voltage == 0.0 and outputs[1].output_on and outputs[1].icomp == pytest.approx(1e-4)
    assert outputs[3].voltage == 0.1
    run(sim, "DZ")
    assert sim.instrument.outputs()[3].voltage == 0.0
    with pytest.raises(AssertionError, match="output switch on"):
        sim.instrument.assert_safe()
    run(sim, "CL")
    sim.instrument.assert_safe()


def test_ab_aborts_a_running_measurement_and_keeps_partial_data(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 1,1", "WT 0,1.0", *SWEEP, "XE")  # 1 s per step
    sim.instrument.clock += 2.5  # host waited 2.5 s: steps 1 and 2 are done
    run(sim, "AB")
    assert not sim.instrument.measurement_pending
    data = elements(sim.read())
    assert len(data) == 4  # data of the steps measured before the abort, no dummy data (PG PDF 352)
    assert sim.instrument.outputs()[1].voltage == 0.0  # sweep source back to the start value


def test_ab_must_be_sent_alone(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 1", "DV 1,0,0.5,1E-3")
    sim.write("AB;DZ")
    assert errx_all(sim) == [103]
    assert sim.instrument.outputs()[1].voltage == 0.5
    assert [r.outcome for r in sim.instrument.command_log if r.line == "AB;DZ"] == ["rejected", "rejected"]


def test_ab_without_a_measurement_changes_nothing(make_sim) -> None:
    sim = make_sim()
    run(sim, "CN 1", "DV 1,0,0.5,1E-3", "AB")
    assert sim.instrument.outputs()[1].voltage == 0.5


def test_lone_ab_ends_a_hung_measurement_but_not_behind_other_commands(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0), faults=[TimeoutFault(on="XE")])
    run(sim, *SWEEP, "XE")
    run(sim, "AB")
    assert not sim.instrument.measurement_pending
    sim.inject(TimeoutFault(on="XE"))
    run(sim, "XE")
    sim.write("DZ")  # held in the input buffer behind the hung measurement
    sim.write("AB")  # cannot enter the input buffer either (PG PDF 352)
    assert sim.instrument.measurement_pending
    assert [r.outcome for r in sim.instrument.command_log[-2:]] == ["queued", "queued"]
    sim.device_clear()
    assert not sim.instrument.measurement_pending
    sim.instrument.assert_safe()  # device clear initialises the instrument (PG PDF 175)
