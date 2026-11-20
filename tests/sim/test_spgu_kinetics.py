"""SPGU pulses drive the WP5.9 ``ferro`` FeFET model in virtual time (blueprint v2 4.2; WP9.1 "FeFET pulse kinetics
wired so later recipes see switching"): nucleation-limited switching from SPGU trains equals the model's closed form,
long trains stay fast and exact (steady state, aggregated periods), bipolar trains count endurance cycles, the pulse
switch and the SER level act on the device, and the switched state is readable by an SMU afterwards."""

from __future__ import annotations

import time

import pytest

from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from b1500_test_agent.transport.sim.devices.kinetics import stretched_step
from tests.sim.spgu_helpers import fefet_on_spgu, open_sim, send

pytestmark = pytest.mark.spgu


def fefet(sim) -> FefetDevice:
    device = sim.instrument.circuit.devices["dut"]
    assert isinstance(device, FefetDevice)
    return device


def program(sim, *, peak: float, width: float, count: int, period: float = 1e-5, ser: float = 1e6,
            base: float = 0.0) -> None:
    send(sim, "CN 101", "SIM 0", f"SPRM 1,{count}", f"SPPER {period}", f"SER 101,{ser}", "SPM 101,1",
         f"SPT 101,1,0,{width},2E-8,2E-8", f"SPV 101,1,{base},{peak}", "SPUPD 101", "SRP")


def expected_after(device: FefetDevice, p0: float, v_dut: float, on_time: float) -> float:
    target = device.polarization_after(v_dut, p0)
    origin = -device.scale if target > p0 else device.scale
    return stretched_step(p0, target, origin, on_time, device.tau(v_dut), device.params.beta_sw)


@pytest.mark.parametrize(("count", "width"), [(1, 5e-7), (5, 5e-7), (20, 2e-7), (3, 2e-6)])
def test_program_pulses_switch_as_the_nls_law(count: int, width: float) -> None:
    sim = open_sim(fefet_on_spgu())
    device = fefet(sim)
    p0 = device.polarization_after(0.0)  # CN and SPUPD hold the gate at 0 V first (the DC band clamps P)
    program(sim, peak=3.0, width=width, count=count)
    v_dut = sim.instrument.spgu_runs[-1].channels[1].delivered_v
    assert v_dut == pytest.approx(3.0 * (1e6 + 50) / 1e6, rel=1e-6)  # the gate is an open load: SER 1 MOhm, +50 ppm
    sim.wait(count * 1e-5)
    assert sim.query("SPST?") == "0"
    expected = expected_after(device, p0, v_dut, count * width)
    assert -1.0 < expected < device.polarization_after(v_dut, p0)  # partly switched: the law matters
    assert device.p == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert sim.instrument.state.devices["dut"]["p"] == device.p  # persisted with the simulator state


def test_partial_windows_add_up_to_the_same_switching() -> None:
    """Polling in the middle of pulses splits them across synchronisation windows; the effective-time law makes the
    result identical."""
    whole, split = open_sim(fefet_on_spgu()), open_sim(fefet_on_spgu())
    program(whole, peak=3.0, width=5e-7, count=6)
    whole.wait(6e-5)
    program(split, peak=3.0, width=5e-7, count=6)
    for _ in range(37):
        split.wait(6e-5 / 37)
        split.query("SPST?")
    split.wait(1e-6)
    assert fefet(split).p == pytest.approx(fefet(whole).p, rel=1e-12)


def test_ser_50_doubles_the_gate_level_and_switches_harder() -> None:
    matched, doubled = open_sim(fefet_on_spgu()), open_sim(fefet_on_spgu())
    program(matched, peak=2.0, width=1e-6, count=1, ser=1e6)
    program(doubled, peak=2.0, width=1e-6, count=1, ser=50.0)
    matched.wait(1e-4)
    doubled.wait(1e-4)
    assert fefet(doubled).p > fefet(matched).p + 0.5  # 4 V instead of 2 V at the gate
    assert doubled.instrument.spgu_runs[-1].channels[1].delivered_v == pytest.approx(4.0, rel=1e-9)


@pytest.mark.wall_clock
def test_a_long_unipolar_train_reaches_steady_state_fast() -> None:
    sim = open_sim(fefet_on_spgu())
    start = time.perf_counter()
    program(sim, peak=5.0, width=1e-6, count=1_000_000, period=1e-5)
    sim.wait(10.0)
    assert sim.query("SPST?") == "0"
    assert time.perf_counter() - start < 5.0
    device = fefet(sim)
    assert device.p == pytest.approx(device.polarization_after(5.0 * (1e6 + 50) / 1e6, -1.0), abs=1e-9)


def test_bipolar_three_level_pulses_count_endurance_cycles() -> None:
    sim = open_sim(fefet_on_spgu(wake_frac=0.3, wake_cycles=100.0))
    send(sim, "CN 101", "SIM 0", "SPRM 1,10000", "SPPER 1E-5", "SER 101,1E6", "SPM 101,3",
         "SPT 101,1,0,2E-6,2E-8,2E-8", "SPV 101,1,0,5", "SPT 101,2,4E-6,2E-6,2E-8,2E-8", "SPV 101,2,0,-5",
         "SPUPD 101", "SRP")
    sim.wait(0.1)
    device = fefet(sim)
    assert device.cycles == pytest.approx(10_000, abs=1)  # one program/erase cycle per period
    assert device.scale == pytest.approx(device.endurance_truth(10_000))  # woken up
    assert device.p < 0  # each period ends with the erase pulse


def test_an_open_pulse_switch_leaves_the_gate_floating() -> None:
    sim = open_sim(fefet_on_spgu())
    p0 = fefet(sim).p
    # normally open: closed only from 8 us to 9 us of each 10 us period, after the pulse
    send(sim, "SPPER 1E-5", "ODSW 101,1,0,8E-6,1E-6")
    program(sim, peak=5.0, width=2e-6, count=10)
    sim.wait(1e-3)
    assert fefet(sim).p == p0  # the pulse never reached the gate
    closed = open_sim(fefet_on_spgu())
    send(closed, "SPPER 1E-5", "ODSW 101,1,1,8E-6,1E-6")  # normally closed: open only after the pulse
    program(closed, peak=5.0, width=2e-6, count=10)
    closed.wait(1e-3)
    assert fefet(closed).p > 0.9


def test_an_smu_reads_the_switched_state_after_the_pulses() -> None:
    """Later recipes (pulse -> read) see the switching: a FeFET programmed by the SPGU conducts more at the same gate
    bias (gate back on 0 V via the SPGU base, drain read by HRSMU 4 at 0.1 V)."""
    sim = open_sim(fefet_on_spgu())
    send(sim, "CN 4", "DV 4,0,0.1,1E-3", "CN 101", "SIM 0", "SER 101,1E6", "SPM 101,1",
         "SPV 101,1,1.2,1.2", "SPT 101,1,0,1E-6,2E-8,2E-8", "SPPER 1E-5", "SPUPD 101")
    erased = sim.instrument._current(sim.instrument._on_levels())[4]
    send(sim, "SPRM 1,1", "SPV 101,1,1.2,5", "SPUPD 101", "SRP")
    sim.wait(1e-4)
    programmed = sim.instrument._current(sim.instrument._on_levels())[4]
    assert programmed > 10 * erased > 0
