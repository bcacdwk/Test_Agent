"""SMU sampling unit of the simulator (WP7.4, blueprint v2 4.1, 4.2): ``MCC ML MT MSC MV MI TSR`` per the
Programming Guide (sampling operation PDF 112-114, ``MT`` PDF 474-476, ``MSC`` PDF 472-473, data block PDF 49),
the engine's timing, index gaps, log sampling, automatic abort, post-measurement levels, current sources, time
stamps, the ``breakdown_at`` fault and the device physics in time (IGZO drift, dielectric breakdown)."""

from __future__ import annotations

import math

import pytest

from b1500_test_agent.driver.parser import parse_data
from b1500_test_agent.driver.sampling import parse_sampling
from b1500_test_agent.models.sim import BreakdownAt, Slow
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.units.sampling import log_indices
from tests.sim.helpers import errx_all, load_scenario, noiseless, run, scenario_with

R_OHM = 1000.0


def resistor_to_ground(r_ohm: float = R_OHM):
    """A resistor from SMU1 (MPSMU of the test mainframe) to the GNDU; noiseless."""
    return scenario_with({"r": {"model": "resistor", "params": {"r_ohm": r_ohm}}}, {"r": {"a": 1, "b": "GNDU"}})


def sample(sim: SimTransport, channels: list[int], *, timeout_s: float = 1e6):
    sim.write("XE")
    return parse_sampling(parse_data(sim.read(timeout_s=timeout_s), 1), channels)


SETUP = ("FMT 1,1", "TSC 1", "CN 1", "MCC", "ML 1", "MSC 2,2")


# -- setup commands --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "code"),
    [("MT 0,0.00009,10", 120), ("MT 0,1,0", 120), ("MT 0,1,100002", 120), ("MT 0,1,10,656", 120),
     ("MT -0.01,0.01,10", 120), ("MT -0.1,0.001,10", 120), ("MT 0,1", 103), ("ML 0", 120), ("ML 8", 120),
     ("MSC 3", 120), ("MSC 2,3", 120), ("MV 1,0,0,1", None), ("MV 1,0,0,1,0", 212), ("MV 1,7,0,1,1E-3", 124),
     ("MV 1,0,0,101,1E-3", 120), ("MV 7,0,0,1,1E-3", 151), ("MI 1,0,-1E-6,1E-6,5", 120), ("MI 1,0,0,1E-6", 212),
     ("MI 1,8,0,1E-6,5", 124), ("MI 1,0,0,0.2,5", 120), ("MCC 1,3", None), ("TSR 1", 100), ("TSR", None)],
)
def test_setup_commands_check_their_parameters(make_sim, command: str, code: int | None) -> None:
    sim = make_sim(resistor_to_ground())
    sim.write("CN 1")
    sim.write(command)
    assert errx_all(sim) == ([] if code is None else [code])


def test_mt_rounds_to_the_instrument_resolution(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "MT 0.014,0.0041,10,0.106", "MT 0.014,0.0041,10,0.106")
    assert sim.instrument._mt == (0.01, 0.004, 10, 0.11)  # 10 ms holds, 1 ms interval from 2 ms
    run(sim, "MT -0.00012,0.000104,10,0")
    assert sim.instrument._mt == (-0.0001, 0.0001, 10, 0.0)  # 0.1 ms negative hold, 10 us interval below 2 ms


def test_rst_returns_the_sampling_setup_to_its_initial_settings(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "CN 1", "ML 3", "MT 0.1,0.5,7,0.2", "MSC 2,1", "MV 1,0,0,1,1E-3", "*RST")
    inst = sim.instrument
    assert (inst._ml, inst._mt, inst._msc, inst._sampling_sources) == (1, (0.0, 0.002, 1000, 0.0), (1, 2), {})


# -- timing, index and time stamps -----------------------------------------------------------------------------------


def test_linear_sampling_follows_the_manual_timing(make_sim) -> None:
    """Base from the trigger, bias after h_base, first sample h_bias later, then one per interval (PDF 475-476);
    each sample: index, then time stamp and value (PDF 46, 49)."""
    sim = make_sim(resistor_to_ground())
    run(sim, *SETUP, "MT 0.1,0.05,4,0.2", "MV 1,0,0,1,0.01", "MM 10,1", "CMM 1,1", "TSR")
    data = sample(sim, [1])
    assert [s.index for s in data.samples] == [1, 2, 3, 4]
    assert [s.time for s in data.samples] == pytest.approx([0.3, 0.35, 0.4, 0.45])
    assert [s.values[0].value for s in data.samples] == pytest.approx([1e-3] * 4)
    assert {str(s.values[0].status.value) for s in data.samples} == {"N"}
    assert sim.instrument.outputs()[1].voltage == 1.0  # MSC post 2: the bias value stays


def test_tsr_resets_the_time_stamps_and_fmt_mode_0_drops_the_index(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "FMT 1,0", "TSC 1", "CN 1", "MT 0,1,2,0", "MV 1,0,1,1,0.01", "MM 10,1")
    sim.instrument.clock += 5.0  # the timer runs from power-on
    first = sample(sim, [1])
    run(sim, "TSR")
    second = sample(sim, [1])
    assert [s.index for s in first.samples] == [None, None] and not first.has_index
    assert first.samples[0].time is not None and first.samples[0].time > 0.5  # since power-on, not since TSR
    assert second.samples[0].time == pytest.approx(0.0, abs=1e-4)


def test_a_slow_measurement_skips_indices(make_sim) -> None:
    """Measurement longer than the interval: the busy channel skips grid points (Sampling_no jumps, PDF 49)."""
    sim = make_sim(resistor_to_ground(), faults=[Slow(factor=2.5)])
    run(sim, *SETUP, "AIT 0,2,16", "MT 0,0.1,4,0", "MV 1,0,1,1,0.01", "MM 10,1")
    data = sample(sim, [1])
    assert [s.index for s in data.samples] == [1, 4, 7, 10]
    assert [s.time for s in data.samples] == pytest.approx([0.0, 0.3, 0.6, 0.9], abs=1e-4)


def test_log_sampling_holds_log_spaced_indices(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, *SETUP, "ML 2", "MT 0,0.01,21,0", "MV 1,0,1,1,0.01", "MM 10,1", "TSR")
    data = sample(sim, [1])
    expected = log_indices(10, 21)
    assert [s.index for s in data.samples] == expected and expected[:6] == [1, 2, 3, 4, 5, 6]
    assert expected[-1] == 200  # the first indices round to repeats: 21 distinct points span 2.3 decades
    assert [s.time for s in data.samples] == pytest.approx([(k - 1) * 0.01 for k in expected], abs=1e-6)


def test_log_sampling_limits(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, *SETUP, "MV 1,0,1,1,0.01", "MM 10,1", "ML 2", "MT 0,0.001,10,0")
    sim.write("XE")
    assert errx_all(sim) == [120]  # log sampling needs an interval of at least 2 ms
    run(sim, "MT 0,0.01,112,0")
    sim.write("XE")
    assert errx_all(sim) == [120]  # more than 1 + 10 x 11 points
    assert sim.instrument._measurement is None


def test_fast_sampling_measures_channels_in_parallel(make_sim) -> None:
    scenario = scenario_with({"r1": {"model": "resistor", "params": {"r_ohm": 1000.0}},
                              "r3": {"model": "resistor", "params": {"r_ohm": 2000.0}}},
                             {"r1": {"a": 1, "b": "GNDU"}, "r3": {"a": 3, "b": "GNDU"}})
    sim = make_sim(scenario)
    run(sim, "FMT 1,1", "TSC 1", "CN 1,3", "MT 0,0.0005,5,0", "MV 1,0,1,1,0.01", "MV 3,0,1,1,0.01", "MM 10,1,3",
        "TSR")
    data = sample(sim, [1, 3])
    assert [s.index for s in data.samples] == [1, 2, 3, 4, 5]
    assert all(s.times[0] == s.times[1] for s in data.samples)  # simultaneous below 2 ms
    assert [s.values[1].value for s in data.samples] == pytest.approx([5e-4] * 5)
    run(sim, "MT 0,0.0001,5,0")
    sim.write("XE")
    assert errx_all(sim) == [120]  # 2 channels need >= 0.1 ms + 20 us


def test_the_source_and_measurement_channels_must_be_on(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "CN 1", "MV 1,0,0,1,1E-3", "MM 10,1", "CL 1")
    sim.write("XE")
    assert errx_all(sim) == [200]


# -- abort and post-measurement output -------------------------------------------------------------------------------


@pytest.mark.parametrize(("msc", "post", "expected"), [("MSC 2,2", "bias", 2.0), ("MSC 2,1", "base", 0.5)])
def test_the_msc_post_value_after_a_normal_end(make_sim, msc: str, post: str, expected: float) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "FMT 1,1", "CN 1", msc, "MT 0,0.01,3,0", "MV 1,0,0.5,2,0.01", "MM 10,1")
    sample(sim, [1])
    assert sim.instrument.outputs()[1].voltage == expected, post


def test_msc_abort_stops_at_compliance_with_dummy_data_and_base_output(make_sim) -> None:
    """MSC 2: compliance at sample 3 -> later data 199.999E+99 (status V) and the source forces its base value
    (PDF 473). The current crosses the 1 mA compliance when the bias rises above 1 V."""
    sim = make_sim(resistor_to_ground())
    run(sim, *SETUP, "MT 0,0.01,6,0", "MV 1,0,0.5,1.5,1E-3", "MM 10,1")
    data = sample(sim, [1])
    statuses = [str(s.values[0].status.value) for s in data.samples]
    assert statuses == ["C", "V", "V", "V", "V", "V"]  # the bias (1.5 V) already exceeds 1 mA at the first sample
    assert [s.dummy for s in data.samples] == [False] + [True] * 5
    assert data.samples[0].values[0].value == pytest.approx(1e-3)
    assert sim.instrument.outputs()[1].voltage == 0.5  # base value after the automatic abort


def test_without_abort_every_sample_reports_compliance(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "FMT 1,1", "CN 1", "MSC 1", "MT 0,0.01,4,0", "MV 1,0,0.5,1.5,1E-3", "MM 10,1")
    data = sample(sim, [1])
    assert [str(s.values[0].status.value) for s in data.samples] == ["C"] * 4
    assert sim.instrument.outputs()[1].voltage == 1.5


def test_ab_ends_the_sampling_with_the_sources_at_base(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "FMT 1,1", "CN 1", "MSC 2,2", "MT 0,1,100,0", "MV 1,0,0.2,1,0.01", "MM 10,1", "XE")
    sim.instrument.clock += 10.5  # ten samples into the measurement
    sim.write("AB")
    data = parse_sampling(parse_data(sim.read(timeout_s=1.0), 1), [1])
    assert 10 <= len(data.samples) <= 11
    assert sim.instrument.outputs()[1].voltage == 0.2 and not sim.instrument.measurement_pending


# -- current sources -------------------------------------------------------------------------------------------------


def test_mi_forces_its_current_and_reports_the_voltage(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "FMT 1,1", "CN 1", "MSC 2,2", "MT 0,0.01,3,0", "MI 1,0,0,1E-3,5", "MM 10,1", "CMM 1,2")
    data = sample(sim, [1])
    assert [s.values[0].value for s in data.samples] == pytest.approx([1.0] * 3, rel=1e-6)
    assert {s.values[0].data_type for s in data.samples} == {"V"}
    assert sim.instrument.outputs()[1].voltage == pytest.approx(1.0, rel=1e-6)  # held at the post current


def test_mi_at_its_voltage_compliance_aborts(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "FMT 1,1", "CN 1", "MSC 2,2", "MT 0,0.01,3,0", "MI 1,0,0,1E-3,0.5", "MM 10,1", "CMM 1,1")
    data = sample(sim, [1])
    first = data.samples[0].values[0]
    assert str(first.status.value) == "C" and first.value == pytest.approx(0.5e-3, rel=1e-6)
    assert [s.dummy for s in data.samples] == [False, True, True]


def test_mv_and_mi_replace_each_other_and_mcc_clears_them(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "CN 1", "MV 1,0,0,1,1E-3", "MI 1,0,0,1E-6,2")
    assert sim.instrument._sampling_sources[1].quantity == "I"
    run(sim, "MV 1,0,0,1,1E-3")
    assert sim.instrument._sampling_sources[1].quantity == "V"
    run(sim, "MCC")
    assert sim.instrument._sampling_sources == {}


def test_a_synchronous_source_above_42_v_needs_the_interlock(make_sim) -> None:
    sim = make_sim(resistor_to_ground(1e6))
    sim.write("CN 1")
    sim.write("MV 1,0,0,50,1E-4")
    assert errx_all(sim) == [202]


def test_sampling_sources_are_logged_as_source_commands(make_sim) -> None:
    sim = make_sim(resistor_to_ground())
    run(sim, "CN 1", "MV 1,0,0,1,1E-3", "MI 1,0,0,1E-6,2")
    assert [r.mnemonic for r in sim.instrument.source_commands()] == ["MV", "MI"]


# -- device physics in time ------------------------------------------------------------------------------------------


def lab(name: str) -> SimTransport:
    scenario = noiseless(load_scenario(name))
    sim = SimTransport(scenario, state_file=None)
    sim.open()
    return sim


def test_the_igzo_drift_follows_the_model_in_virtual_time() -> None:
    """Gate 0 -> 3 V at t = h_base; after the sampling the device's drift equals the stretched exponential of the
    time spent at 3 V (the engine advances the circuit between samples)."""
    sim = lab("igzo_transient")
    run(sim, "FMT 1,1", "TSC 1", "CN 3,4", "DV 3,0,0.1,1E-3", "MSC 2,2", "MT 0.01,0.01,1001,0.1",
        "MV 4,0,0,3,1E-6", "MM 10,3", "TSR")
    data = sample(sim, [3])
    device = sim.instrument.circuit.devices["dut"]
    at_bias = data.samples[-1].time - 0.1 + 0.01  # from the step (h_base 0.1 s) to the end of the last 10 ms sample
    assert device.igzo_dv == pytest.approx(device.igzo_truth(3.0, at_bias), rel=1e-3)
    currents = [s.values[0].value for s in data.samples]
    assert currents[0] > currents[-1] > 0  # positive bias stress: Vth up, Id down


def test_dielectric_breaks_at_its_weibull_life_and_the_sampling_aborts() -> None:
    sim = lab("dielectric_tddb")
    t_bd = Circuit(sim.scenario).devices["dut"].t_bd(5.5)
    run(sim, "FMT 1,1", "TSC 1", "CN 4", "MSC 2,2", "MT 0,1,200,0", "MV 4,0,0,5.5,1E-3", "MM 10,4", "TSR")
    data = sample(sim, [4])
    measured = data.measured
    assert str(measured[-1].values[0].status.value) == "C"
    t_hit = measured[-1].time
    assert t_hit - 1.0 < t_bd <= t_hit  # detected at the first sample after the true life
    assert measured[-2].values[0].value < 1e-5  # leakage (uA) before, compliance (1 mA) at breakdown
    assert all(s.dummy for s in data.samples[len(measured):])
    assert sim.instrument.circuit.devices["dut"].broken
    assert sim.instrument.outputs()[4].voltage == 0.0  # base value after the abort


def test_a_chain_of_blocks_stresses_continuously() -> None:
    """Two triggers, the second with base = bias: the damage equals the stress time (no gap at 0 V)."""
    sim = lab("dielectric_tddb")
    device = sim.instrument.circuit.devices["dut"]
    run(sim, "FMT 1,1", "TSC 1", "CN 4", "MSC 2,2", "MT 0,1,25,0", "MV 4,0,0,4.5,1E-3", "MM 10,4", "TSR")
    first = sample(sim, [4])
    run(sim, "MT 1,1,25,0", "MV 4,0,4.5,4.5,1E-3")
    second = sample(sim, [4])
    end = second.samples[-1].time
    assert first.samples[-1].time < second.samples[0].time
    assert device.damage == pytest.approx(end * device._rate(4.5), rel=0.01)


def test_breakdown_at_breaks_the_dielectric_on_time() -> None:
    sim = lab("dielectric_tddb")
    sim.inject(BreakdownAt(t_s=7.0))
    run(sim, "FMT 1,1", "TSC 1", "CN 4", "MSC 2,2", "MT 0,1,20,0", "MV 4,0,0,3,1E-3", "MM 10,4", "TSR")
    data = sample(sim, [4])
    measured = data.measured
    assert len(measured) == 8 and measured[-1].time == pytest.approx(7.0, abs=1e-4)
    assert str(measured[-1].values[0].status.value) == "C"
    assert sim.instrument.faults.breakdowns_due(100.0) == []  # one-shot


def test_device_state_is_persisted_after_the_sampling(tmp_path) -> None:
    from b1500_test_agent.transport.sim.state import load_state_file

    scenario = noiseless(load_scenario("igzo_transient"))
    path = tmp_path / "state.json"
    sim = SimTransport(scenario, state_file=path)
    sim.open()
    run(sim, "FMT 1,1", "CN 3,4", "DV 3,0,0.1,1E-3", "MT 0,0.1,50,0", "MV 4,0,3,3,1E-6", "MM 10,3")
    sample(sim, [3])
    sim.save_state()
    state = load_state_file(path)
    assert state is not None and state.devices["dut"]["igzo_dv"] > 0.0
    assert math.isclose(state.devices["dut"]["igzo_dv"], sim.instrument.circuit.devices["dut"].igzo_dv)
