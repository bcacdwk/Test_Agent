"""MOSFET charge pumping and SMU readings during an HV-SPGU train in the simulator (WP9.3, blueprint v2 3.3 / 4.4
``nmos_cv``; 9.1 handoff: the SMU solve used the SPGU's static base level): the device model
(``Mosfet.charge_pumping_current``/``pumped_currents``/``charge_pumping_truth``), ``Circuit.pumped_currents`` and the
instrument's time-averaged spot readings while a run is active."""

from __future__ import annotations

import math

import pytest

from b1500_test_agent.models.sim import MosfetParams
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.devices import Circuit, PeriodicDrive, PumpedDevice
from b1500_test_agent.transport.sim.devices.base import BOLTZMANN_OVER_Q
from b1500_test_agent.transport.sim.devices.mosfet import CP_THERMAL_VELOCITY_CM_S, Mosfet
from tests.sim.helpers import load_scenario, noiseless
from tests.sim.spgu_helpers import send, spgu_scenario

pytestmark = pytest.mark.spgu

PARAMS = {"polarity": "n", "vth0": 0.7, "slope_factor": 1.3, "beta": 1.4e-3, "theta": 0.2, "lambda": 0.02,
          "rs_ohm": 20.0, "gate_leak_s": 0.0, "temperature_k": 300.0, "w_um": 100.0, "l_um": 10.0, "tox_nm": 10.0,
          "nsub_cm3": 1e17, "dit_cm2_ev": 5e10, "cp_sigma_cm2": 1e-16, "cp_edge_v": 0.1}  # fmt: skip


def mosfet(**changes: object) -> Mosfet:
    return Mosfet("dut", MosfetParams.model_validate({**PARAMS, **changes}))


# -- device model ----------------------------------------------------------------------------------------------------


def test_icp_is_q_f_area_dit_delta_e_and_proportional_to_f() -> None:
    m = mosfet()
    ut = BOLTZMANN_OVER_Q * 300.0
    vth, vfb = 0.7, m.charge_pumping_truth(-2, 2, 1e5, 1e-7, 1e-7)["vfb_v"]
    t_em = 1e-7 * (vth - vfb) / 4.0
    delta_e = 2 * ut * math.log(1.0 / (CP_THERMAL_VELOCITY_CM_S * 1e10 * 1e-16 * t_em))
    for f in (1e3, 1e5, 1e7):
        t = m.charge_pumping_truth(-2.0, 2.0, f, 1e-7, 1e-7)
        assert t["delta_e_ev"] == pytest.approx(delta_e, rel=1e-12)
        assert t["icp_a"] == pytest.approx(1.602176634e-19 * f * 1e-5 * 5e10 * delta_e, rel=1e-5)  # steps ~1
        assert t["qcp_c"] == pytest.approx(t["icp_a"] / f) and t["nit_cm2"] == pytest.approx(5e10 * delta_e)
    assert -0.7 < vfb < -0.5 and m.charge_pumping_truth(-2, 2, 1e5, 1e-7, 1e-7)["area_cm2"] == pytest.approx(1e-5)


def test_slower_edges_shrink_the_energy_window_logarithmically() -> None:
    m = mosfet()
    fast = m.charge_pumping_truth(-2, 2, 1e5, 1e-8, 1e-8)["delta_e_ev"]
    slow = m.charge_pumping_truth(-2, 2, 1e5, 1e-6, 1e-6)["delta_e_ev"]
    assert fast - slow == pytest.approx(2 * BOLTZMANN_OVER_Q * 300.0 * math.log(100.0), rel=1e-9)


def test_base_level_curve_has_a_plateau_between_vth_minus_amplitude_and_vfb() -> None:
    m = mosfet()
    icp = {b: m.charge_pumping_truth(b, b + 3.0, 1e5, 1e-7, 1e-7)["icp_a"] for b in (-4.0, -2.0, -1.2, 0.5)}
    top = max(icp.values())
    assert icp[-1.2] == pytest.approx(top) and icp[-2.0] > 0.9 * top  # top 1 V is 0.3 V above Vth (0.7 V)
    assert icp[-4.0] < 1e-3 * top  # the top (-1 V) stays below Vth: no inversion
    assert icp[0.5] < 1e-3 * top  # the base (0.5 V) stays above Vfb: no accumulation


def test_pumped_currents_need_bulk_and_source_or_drain_and_mirror_for_p_channel() -> None:
    drive = {"gate": PeriodicDrive(low_v=-2.0, high_v=2.0, freq_hz=1e5, rise_s=1e-7, fall_s=1e-7)}
    m = mosfet()
    assert isinstance(m, PumpedDevice)
    out = m.pumped_currents({"gate": None, "drain": 0.0, "source": 0.0, "bulk": 0.0}, drive)
    icp = m.charge_pumping_truth(-2.0, 2.0, 1e5, 1e-7, 1e-7)["icp_a"]
    assert out == pytest.approx({"bulk": icp, "drain": -icp / 2, "source": -icp / 2})
    assert m.pumped_currents({"gate": None, "drain": 0.0, "source": 0.0, "bulk": None}, drive) == {}
    assert m.pumped_currents({"gate": None, "drain": None, "source": None, "bulk": 0.0}, drive) == {}
    assert mosfet(dit_cm2_ev=0.0).pumped_currents({"drain": 0.0, "source": 0.0, "bulk": 0.0}, drive) == {}
    p = mosfet(polarity="p", vth0=-0.7)
    mirrored = p.pumped_currents({"drain": 0.0, "source": 0.0, "bulk": 0.0},
                                 {"gate": PeriodicDrive(low_v=-2.0, high_v=2.0, freq_hz=1e5, rise_s=1e-7, fall_s=1e-7)})
    assert mirrored["bulk"] == pytest.approx(-p.charge_pumping_truth(-2, 2, 1e5, 1e-7, 1e-7)["icp_a"])


def test_reverse_bias_raises_the_threshold_the_top_must_pass() -> None:
    m = mosfet()
    at_zero = m.charge_pumping_current(PeriodicDrive(-2.0, 1.0, 1e5, 1e-7, 1e-7), vsb=0.0)
    reverse = m.charge_pumping_current(PeriodicDrive(-2.0, 1.0, 1e5, 1e-7, 1e-7), vsb=0.5)
    assert reverse["vth_v"] == pytest.approx(0.7 + 1.3 * 0.5) and reverse["icp_a"] < 0.1 * at_zero["icp_a"]


def test_charge_pumping_needs_the_geometry() -> None:
    with pytest.raises(ValueError, match="charge pumping"):
        MosfetParams.model_validate({k: v for k, v in PARAMS.items() if k not in ("w_um", "l_um", "tox_nm")})


def test_circuit_adds_pumping_only_for_driven_nodes() -> None:
    circuit = Circuit(noiseless(load_scenario("nmos_cv")))
    circuit.router = lambda: {"SELPORT0": 1}  # SEL1.OUT1 on the PGU input (SPGU 101 = canonical 1)
    drive = PeriodicDrive(low_v=-2.0, high_v=2.0, freq_hz=1e5, rise_s=1e-7, fall_s=1e-7)
    levels = {4: 0.0, 5: 0.0, 6: 0.0}
    pumped = circuit.pumped_currents(levels, {1: drive})
    icp = circuit.devices["dut"].charge_pumping_truth(-2.0, 2.0, 1e5, 1e-7, 1e-7)["icp_a"]  # type: ignore[attr-defined]
    assert pumped == pytest.approx({4: icp, 5: -icp / 2, 6: -icp / 2})
    circuit.router = lambda: {"SELPORT0": 3}  # on the SMU input: the SPGU drives nothing
    assert circuit.pumped_currents(levels, {1: drive}) == {}


# -- instrument: readings during a train -------------------------------------------------------------------------------


def cp_setup(f: float, *, route: int = 2) -> list[str]:
    period = 1.0 / f
    return ["ERMOD 1", f"ERSSP 0,{route}", "FMT 1,0", "CN 101,4,5,6", "DV 4,0,0,1E-6", "DV 5,0,0,1E-4",
            "DV 6,0,0,1E-4", "SIM 0", "SPRM 2,0.2", f"SPPER {period:.6E}", "SER 101,1E6", "SPM 101,1",
            f"SPT 101,1,0,{period / 2:.6E},1E-7,1E-7", "SPV 101,1,-2,2", "SPUPD 101", "SRP"]


def spot(sim: SimTransport) -> list[float]:
    send(sim, "MM 1,4,5,6", "CMM 4,1", "CMM 5,1", "CMM 6,1")
    sim.write("XE")
    return [float(item[3:]) for item in sim.read(timeout_s=5).strip().split(",")]


@pytest.mark.parametrize("f", [1e4, 1e5, 1e6])
def test_bulk_reads_the_model_icp_while_the_train_runs(f: float) -> None:
    sim = SimTransport(noiseless(load_scenario("nmos_cv")), state_file=None)
    sim.open()
    send(sim, *cp_setup(f))
    sim.instrument.advance(0.02)
    bulk, drain, source = spot(sim)
    level = (1e6 + 50) / 1e6  # the open gate sees the set level x (SER + 50) / SER
    icp = sim.instrument.circuit.devices["dut"].charge_pumping_truth(  # type: ignore[attr-defined]
        -2 * level, 2 * level, f, 1e-7, 1e-7)["icp_a"]
    assert bulk == pytest.approx(icp, rel=1e-4) and drain == pytest.approx(-icp / 2, rel=1e-3)
    assert source == pytest.approx(drain, rel=1e-6)
    sim.instrument.advance(0.5)  # the 0.2 s train has ended: the static solve again (no pumping)
    assert abs(spot(sim)[0]) < 1e-3 * icp


def test_no_pumping_when_the_selector_is_on_the_smu_input() -> None:
    sim = SimTransport(noiseless(load_scenario("nmos_cv")), state_file=None)
    sim.open()
    send(sim, *cp_setup(1e5, route=1))  # SEL1.OUT1 -> SMU 3 (off): the train reaches nothing
    sim.instrument.advance(0.02)
    assert abs(spot(sim)[0]) < 1e-15


def test_a_resistor_on_the_spgu_reads_the_time_average_of_the_train() -> None:
    """SPGU 101 -> 1 MOhm -> SMU 4 at 0 V: the SMU reads -(duty x peak + (1 - duty) x base) / R (the 9.1 solve read
    only the base level)."""
    scenario = spgu_scenario({"r": {"model": "resistor", "params": {"r_ohm": 1e6}}}, {"r": {"a": 101, "b": 4}})
    sim = SimTransport(scenario, state_file=None)
    sim.open()
    send(sim, "FMT 1,0", "CN 101,4", "DV 4,0,0,1E-3", "SIM 0", "SPRM 2,0.2", "SPPER 1E-4", "SER 101,1E6",
         "SPM 101,1", "SPT 101,1,0,2.5E-5,2E-8,2E-8", "SPV 101,1,-1,3", "SPUPD 101")
    send(sim, "MM 1,4", "CMM 4,1")
    sim.write("XE")
    static = float(sim.read(timeout_s=5).strip()[3:])
    assert static == pytest.approx(1.0 / 1e6, rel=1e-6)  # the base level -1 V before SRP
    send(sim, "SRP")
    sim.instrument.advance(0.01)
    sim.write("XE")
    averaged = float(sim.read(timeout_s=5).strip()[3:])
    assert averaged == pytest.approx(-(0.25 * 3.0 + 0.75 * -1.0) / 1e6, rel=1e-6, abs=1e-15)
