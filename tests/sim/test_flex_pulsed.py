"""Simulator SMU pulsed unit (``transport/sim/units/pulsed.py``, WP7.3; Programming Guide Ed. 15 physical PDF pages):
pulsed spot MM 3 (p93), pulsed sweep MM 4 with a synchronous source (p100-101), staircase with pulsed bias MM 5
(p98-99), multi-channel pulsed spot/sweep MM 27/28 (p94-95, p104-105), ``PT``/``MCPT`` timing in virtual time, the data
format (FMT 1,1: the primary source's value per step; MM 28: source N), the post-measurement outputs, the errors of
PDF 579-580, and self-heating: a DC staircase reads the heated device, a short pulse reads it (almost) cold."""

from __future__ import annotations

import pytest

from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.devices import Circuit
from tests.sim.helpers import elements, errx_all, load_scenario, noiseless, resistor_scenario, run, values

R = 1000.0


@pytest.fixture
def sim(make_sim) -> SimTransport:
    """A 1 kOhm resistor between SMU1 (MPSMU) and SMU3 (HRSMU) with both switched on."""
    transport = make_sim(resistor_scenario(R))
    run(transport, "FMT 1,1", "CN 1,3", "DV 3,0,0,0.1")
    return transport


def test_mm3_pulsed_spot_reads_at_the_pulse_and_returns_to_base(sim: SimTransport) -> None:
    run(sim, "FMT 1,0", "AIT 2,3,0.0002", "MM 3,1", "CMM 1,1", "PT 0.1,0.001,0.01", "PV 1,0,0.1,0.5,0.01", "XE")
    data = sim.read()
    assert [e[:3] for e in elements(data)] == ["NAI"]
    assert values(data) == pytest.approx([0.5 / R])
    out = sim.instrument.outputs()[1]
    assert (out.mode, out.voltage) == ("V", 0.1)  # the pulse source keeps its base value (PDF 93)
    assert sim.instrument.clock >= 0.101  # hold + one pulse in virtual time


def test_mm4_pulsed_sweep_returns_the_pulse_level_per_step(sim: SimTransport) -> None:
    run(sim, "AIT 2,3,0.0002", "MM 4,1", "CMM 1,1", "PT 0,0.001,0.01", "PWV 1,1,0,0,0,1,3,0.01", "WM 2,1", "XE")
    data = sim.read()
    assert [e[:3] for e in elements(data)] == ["NAI", "WAV", "NAI", "WAV", "NAI", "EAV"]
    assert values(data) == pytest.approx([0.0, 0.0, 0.5 / R, 0.5, 1.0 / R, 1.0])
    assert sim.instrument.outputs()[1].voltage == 0.0  # base after the sweep (PDF 100)


def test_mm4_synchronous_source_follows_the_pulsed_sweep(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,1", "CN 1,3", "AIT 2,3,0.0002", "MM 4,1", "CMM 1,1", "PT 0,0.001,0.01",
        "PWV 1,1,0,0,0,1,3,0.01", "WSV 3,0,0,-1,0.01", "WM 2,2", "XE")
    assert values(sim.read())[0::2] == pytest.approx([0.0, 1.0 / R, 2.0 / R])  # a - b grows twice as fast
    assert sim.instrument.outputs()[3].voltage == -1.0  # WM post 2: the synchronous source at its stop value
    sim.write("PWV 1,1,0,0,0,1,3,0.01")
    assert sim.instrument._sync is None  # PWV clears WSV/WSI (PDF 492)


def test_mm5_staircase_with_pulsed_bias(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,1", "CN 1,3", "AIT 2,3,0.0002", "MM 5,3", "CMM 3,1", "PT 0,0.001,0.01", "WV 3,1,0,0,1,3,0.01",
        "PV 1,0,0,2,0.01", "WM 2,1", "XE")
    data = sim.read()
    assert [e[:3] for e in elements(data)] == ["NCI", "WCV", "NCI", "WCV", "NCI", "ECV"]
    assert values(data) == pytest.approx([-2.0 / R, 0.0, -1.5 / R, 0.5, -1.0 / R, 1.0])
    outputs = sim.instrument.outputs()
    assert outputs[1].voltage == 0.0 and outputs[3].voltage == 0.0  # pulse at base, staircase at its start value


def test_mm27_and_mm28_measure_in_parallel(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,0", "CN 1,3", "AIT 2,3,0.0002", "MCPT 0,0.01", "MCPNT 1,0,0.001", "MCPNT 3,0,0.001",
        "MCPNX 1,1,1,0,0,1,0.01", "MCPNX 2,3,1,0,0,-1,0.01", "MM 27,1,3", "CMM 1,1", "CMM 3,1", "XE")
    assert values(sim.read()) == pytest.approx([2.0 / R, -2.0 / R])
    run(sim, "FMT 1,1", "MCPWS 1,3", "MCPWNX 1,1,1,0,0,0,1,0.01", "WNX 2,3,1,0,0,-1,0.01", "MM 28,1,3", "WM 2,1",
        "XE")
    data = sim.read()
    assert values(data) == pytest.approx([0.0, 0.0, 0.0, 1.0 / R, -1.0 / R, 0.5, 2.0 / R, -2.0 / R, 1.0])
    assert [e[:3] for e in elements(data)][-1] == "EAV"  # FMT 1,1: source N = 1, the pulsed sweep


def test_mcpt_average_repeats_the_pulse(sim: SimTransport) -> None:
    run(sim, "FMT 1,0", "AIT 2,3,0.0002", "MCPT 0,0.01,0,4", "MCPNT 1,0,0.001", "MCPNX 1,1,1,0,0,1,0.01",
        "MM 27,1", "CMM 1,1", "XE")
    t0 = sim.instrument.clock
    assert values(sim.read()) == pytest.approx([1.0 / R])
    assert sim.instrument.clock - t0 >= 0.04 - 1e-9  # four periods


@pytest.mark.parametrize(("setup", "code"), [
    (("MM 3,1",), 230),  # no PV/PI
    (("MM 5,1", "WV 3,1,0,0,1,3,0.01"), 222),  # no PV/PI for the pulsed bias
    (("MM 4,1",), 221),  # no PWV/PWI
    (("MM 5,1", "PV 1,0,0,1,0.01"), 220),  # no WV/WI staircase
    (("MM 4,1", "PWV 1,2,0,0.1,0.1,1,3,0.01"), 226),  # MM 4 sweeps linearly only
    (("MM 3,3", "PT 0,0.0004,0.01", "PV 3,0,0,1,0.01"), 233),  # an HRSMU pulse below 500 us
    (("MM 3,1", "PT 0,0.009,0.01", "PV 1,0,0,1,0.01"), 233),  # period < width + 2 ms
    (("MM 27,1",), 232),  # no MCPNX source
    (("MM 28,1", "MCPNX 1,1,1,0,0,1,0.01"), 232),  # MM 28 without a sweep source
    (("MM 28,1", "MCPWS 1,3", "MCPWNX 2,1,1,0,0,0,1,0.01"), 225),  # FMT 1,1 names source 1: none
])
def test_trigger_errors(sim: SimTransport, setup: tuple[str, ...], code: int) -> None:
    for command in setup:
        sim.write(command)
    assert errx_all(sim) == []
    sim.write("XE")
    assert errx_all(sim) == [code]
    assert not sim.instrument.measurement_pending


@pytest.mark.parametrize(("command", "code"), [
    ("PT 0,0.000005,0.01", 239), ("PT 0,2.5,5", 238), ("PT 0,0.001,0", 233), ("PV 1,0,0,1", 231),
    ("PV 1,0,0,1,0.5", 231), ("PI 1,0,-1E-6,1E-6,1", 120), ("PWI 1,1,0,0,-1E-6,1E-6,3,1", 120),
    ("WSV 3,0,0,1,0.01", 220), ("MCPNX 11,1,1,0,0,1,0.01", 120), ("MM 3,1,3", 122), ("MCPT 0,0.01,0,1024", 120),
])
def test_setup_errors(sim: SimTransport, command: str, code: int) -> None:
    sim.write(command)
    assert errx_all(sim) == [code]


def test_pv_and_pi_clear_each_other_and_wnx_shares_numbers_with_mcp(sim: SimTransport) -> None:
    run(sim, "PV 1,0,0,1,0.01", "PI 1,0,0,1E-4,2")
    assert sim.instrument._pulse_bias is not None and sim.instrument._pulse_bias.source == "I"
    run(sim, "MCPNX 2,1,1,0,0,1,0.01", "WNX 2,3,1,0,0,1,0.01")
    assert 2 not in sim.instrument._mcp and 2 in sim.instrument._wnx  # the same N replaces (PDF 463)
    run(sim, "MCPWNX 1,3,1,0,0,0,1,0.01")
    assert sim.instrument._wnx == {}  # the same channel replaces


def test_mm16_refuses_a_wnx_source_numbered_1(sim: SimTransport) -> None:
    run(sim, "MM 16,1", "WV 1,1,0,0,1,3,0.01", "WNX 1,3,1,0,0,1,0.01")
    sim.write("XE")
    assert errx_all(sim) == [120]


def test_current_pulse_source_is_solved_like_a_current_source(sim: SimTransport) -> None:
    run(sim, "FMT 1,0", "AIT 2,3,0.0002", "MM 3,1", "CMM 1,2", "PT 0,0.001,0.01", "PI 1,0,0,1E-4,2", "XE")
    assert values(sim.read()) == pytest.approx([1e-4 * R], rel=1e-6)  # V = I x R
    out = sim.instrument.outputs()[1]
    assert (out.mode, out.current) == ("I", 0.0)  # base current after the pulse


def test_pulses_read_the_self_heated_device_cold(make_sim) -> None:
    """DC (MM 2): the steady self-heated current; a 1 ms pulse (tau_th 10 ms): within 1 % of the model's pulse
    response, about 16 % above DC at Vg = Vd = 3 V (scenario ``nmos_selfheat``)."""
    scenario = noiseless(load_scenario("nmos_selfheat"))
    device = Circuit(scenario).devices["dut"]
    on = {"gate": 3.0, "drain": 3.0, "source": 0.0, "bulk": 0.0}
    dc_truth = device.selfheat_truth(on)["id_dc"]
    device.reset()
    device.advance(1e-3 - 2e-4, on)
    pulse_truth = 0.5 * (device.advance(0.0, on)["drain"] + device.advance(2e-4, on)["drain"])
    sim = make_sim(scenario)
    run(sim, "FMT 1,0", "CN 3,4", "DV 3,0,3,0.001", "DV 4,0,3,1E-4", "MM 1,3", "CMM 3,1", "XE")
    (dc,) = values(sim.read())
    run(sim, "DV 4,0,0,1E-4", "AIT 2,3,0.0002", "MM 3,3", "PT 0,0.001,0.1", "PV 4,0,0,3,1E-4", "XE")
    (pulsed,) = values(sim.read())
    assert dc == pytest.approx(dc_truth, rel=1e-6)
    assert pulsed == pytest.approx(pulse_truth, rel=0.01)
    assert pulsed / dc == pytest.approx(1.16, abs=0.01)
