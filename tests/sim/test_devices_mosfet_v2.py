"""v2 ``mosfet`` device truth (blueprint 4.2, WP5.9): equal to ``mosfet_ekv`` with every effect off; self-heating
(DC vs pulsed = model ±10 %, Rth·P self-consistency, thermal transient); BTI n ±0.02 and A ±10 % with log recovery;
HCI m ±0.03; IGZO stretched-exponential drift τ ±15 % and β ±0.1; split C-V plateau = Cox·W·L ±2 %. Every value is
extracted from simulated currents or capacitances with small fits."""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.models.sim import MosfetEkvParams, MosfetParams
from b1500_test_agent.transport.sim.devices.mosfet import Mosfet, MosfetEkv
from tests.sim.device_fits import EPS0_F_CM, constant_current_vth, linfit
from tests.sim.helpers import run, scenario_with, values

EKV = {"vth0": 0.5, "slope_factor": 1.3, "beta": 2e-3, "theta": 0.2, "lambda": 0.05, "rs_ohm": 0.0}


def mosfet(**extra: float | str) -> Mosfet:
    return Mosfet("m", MosfetParams.model_validate({**EKV, **extra}))


def bias(vg: float, vd: float) -> dict[str, float | None]:
    return {"gate": vg, "drain": vd, "source": 0.0, "bulk": 0.0}


def read_vth(device: Mosfet, i_crit: float = 1e-7) -> float:
    """Constant-current threshold at Vd = 50 mV from reads that change nothing."""
    return constant_current_vth(lambda vg: device.instant_currents(bias(vg, 0.05))["drain"], i_crit)


def test_with_every_effect_off_it_equals_mosfet_ekv() -> None:
    v2, v1 = mosfet(), MosfetEkv("e", MosfetEkvParams.model_validate(EKV))
    for vg in (-0.5, 0.3, 0.5, 1.0, 2.0):
        for vd in (0.05, 0.5, 2.0, -0.3):
            v = bias(vg, vd)
            assert v2.terminal_currents(v) == v1.terminal_currents(v)
            assert v2.advance(1.0, v) == v1.terminal_currents(v)
    assert v2.vth == 0.5 and set(v2.export_state()) == set(Mosfet.STATE_KEYS)
    assert v2.terminal_currents({"gate": 1.0, "drain": None, "source": 0.0}) == {
        "gate": 0.0, "drain": 0.0, "source": 0.0, "bulk": 0.0}


# -- self-heating ----------------------------------------------------------------------------------------------------

SELFHEAT = {"rth_k_per_w": 4000.0, "tau_th_s": 1e-3, "vth_tc_v_per_k": 1e-3, "mobility_t_exp": 1.5}


def isothermal(dt_k: float) -> MosfetEkv:
    """An independent ``mosfet_ekv`` at the elevated temperature (Vth and β moved by the self-heating laws)."""
    t = 300.0 + dt_k
    return MosfetEkv("iso", MosfetEkvParams.model_validate(
        {**EKV, "vth0": 0.5 - 1e-3 * dt_k, "beta": 2e-3 * (t / 300.0) ** -1.5, "temperature_k": t}))


def test_dc_self_heating_is_self_consistent() -> None:
    device = mosfet(**SELFHEAT)
    v = bias(2.0, 2.0)
    truth = device.selfheat_truth(v)
    rise, id_dc = truth["delta_t_k"], truth["id_dc"]
    assert rise == pytest.approx(4000.0 * id_dc * 2.0, rel=1e-8)  # ΔT = Rth·P with the self-heated current
    assert 5.0 < rise < 200.0
    assert id_dc == pytest.approx(isothermal(rise).terminal_currents(v)["drain"], rel=1e-9)
    assert id_dc < truth["id_cold"]  # mobility loss wins over the Vth drop in strong inversion
    assert device.terminal_currents(v)["drain"] == pytest.approx(id_dc, rel=1e-12)  # DC trial = steady state


def test_pulsed_versus_dc_current_matches_the_model() -> None:
    v = bias(2.0, 2.0)
    pulsed = mosfet(**SELFHEAT)
    i_pulse = pulsed.advance(1e-6, v)["drain"]  # 1 µs ≪ τ_th = 1 ms: nearly isothermal
    dc = mosfet(**SELFHEAT)
    i_dc = dc.advance(0.1, v)["drain"]  # 100·τ_th: steady
    truth = dc.selfheat_truth(v)
    assert i_pulse - i_dc == pytest.approx(truth["id_cold"] - truth["id_dc"], rel=0.10)
    assert i_pulse == pytest.approx(pulsed.pulsed_truth(v, 1e-6), rel=1e-6)
    transient = mosfet(**SELFHEAT)
    transient.advance(1e-3, v)  # one thermal time constant
    assert transient.dt_k == pytest.approx((1 - math.exp(-1)) * truth["delta_t_k"], rel=0.02)
    transient.advance(1.0, bias(0.0, 0.0))  # power off: cools down
    assert transient.dt_k == pytest.approx(0.0, abs=1e-6)


def test_self_heating_through_the_simulator_dc_sweep(make_sim) -> None:
    params = {**EKV, **SELFHEAT, "lambda": 0.0}
    scenario = scenario_with({"dut": {"model": "mosfet", "params": params}},
                             {"dut": {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}})
    sim = make_sim(scenario)
    run(sim, "CN 3,4", "DV 4,0,2.0,1E-3", "MM 2,3", "WV 3,1,0,0,2.0,21,1E-1", "XE")
    ids = values(sim.read())
    device = sim.instrument.circuit.devices["dut"]
    assert isinstance(device, Mosfet)
    expected = device.selfheat_truth(bias(2.0, 2.0))
    assert ids[-1] == pytest.approx(expected["id_dc"], rel=1e-6)  # the SMU measures the self-heated DC current
    assert ids[-1] < expected["id_cold"]
    assert sim.instrument.state.devices["dut"]["dt_k"] == 0.0  # the sweep returned the drain to 0 V: no power


# -- BTI ----------------------------------------------------------------------------------------------------------

BTI = {"bti_a": 5e-3, "bti_gamma": 3.0, "bti_n": 0.16, "bti_recovery": 0.08, "bti_recovery_t0_s": 1e-6}


def stress_series(device: Mosfet, vg: float, times: np.ndarray) -> np.ndarray:
    """ΔVth (constant current) after cumulative gate stress ``vg`` at each time (no recovery between reads)."""
    v0 = read_vth(device)
    shifts, elapsed = [], 0.0
    for t in times:
        device.advance(float(t - elapsed), bias(vg, 0.0))
        elapsed = float(t)
        shifts.append(read_vth(device) - v0)
    return np.array(shifts)


def test_bti_power_law_exponent_prefactor_and_voltage_acceleration() -> None:
    times = np.logspace(0, 4, 13)
    fits = {}
    for vg in (1.5, 2.0):
        slope, intercept = linfit(np.log(times), np.log(stress_series(mosfet(**BTI), vg, times)))
        fits[vg] = (slope, math.exp(intercept))
    for slope, _ in fits.values():
        assert slope == pytest.approx(0.16, abs=0.02)
    gamma = math.log(fits[2.0][1] / fits[1.5][1]) / math.log(2.0 / 1.5)
    assert gamma == pytest.approx(3.0, abs=0.1)
    a = fits[2.0][1] / 2.0 ** gamma
    assert a == pytest.approx(5e-3, rel=0.10)
    assert mosfet(**BTI).bti_truth(2.0, 1e3) == pytest.approx(5e-3 * 8.0 * 1e3 ** 0.16)


def test_bti_log_recovery_and_restress() -> None:
    device = mosfet(**BTI)
    v_fresh = read_vth(device)
    device.advance(1e3, bias(2.0, 0.0))
    dv0 = device.bti_dv
    assert read_vth(device) - v_fresh == pytest.approx(dv0, abs=1e-6)
    recovery = []
    times = np.logspace(-3, 2, 6)
    elapsed = 0.0
    for t in times:
        device.advance(float(t - elapsed), bias(0.0, 0.0))
        elapsed = float(t)
        recovery.append(read_vth(device) - v_fresh)
    for t, dv in zip(times, recovery, strict=True):
        assert dv == pytest.approx(device.bti_recovery_truth(dv0, float(t)), rel=1e-3)
    slope, _ = linfit(np.log10(times), recovery)
    assert slope == pytest.approx(-0.08 * dv0, rel=0.10)  # recovery per decade
    partial = device.bti_dv
    device.advance(10.0, bias(2.0, 0.0))  # re-stress continues from the effective time of the remaining shift
    t_eq = (partial / (5e-3 * 8.0)) ** (1 / 0.16)
    assert device.bti_dv == pytest.approx(5e-3 * 8.0 * (t_eq + 10.0) ** 0.16, rel=1e-9)


def test_p_channel_bti_makes_the_threshold_more_negative() -> None:
    device = Mosfet("p", MosfetParams.model_validate({**EKV, "polarity": "p", "vth0": -0.5, **BTI}))
    device.advance(100.0, {"gate": -2.0, "drain": 0.0, "source": 0.0, "bulk": 0.0})
    assert device.vth == pytest.approx(-0.5 - device.bti_truth(2.0, 100.0), rel=1e-9)


# -- HCI ----------------------------------------------------------------------------------------------------------

HCI = {"hci_b": 1e-3, "hci_m": 0.45, "hci_vd_ref_v": 1.0, "hci_vd_exp": 4.0}


def test_hci_degradation_power_law() -> None:
    device = mosfet(**HCI)
    read = bias(1.5, 0.05)
    id0 = device.instant_currents(read)["drain"]
    times = np.logspace(0, 3, 10)
    elapsed, degradation = 0.0, []
    for t in times:
        device.advance(float(t - elapsed), bias(2.0, 2.0))
        elapsed = float(t)
        degradation.append(1.0 - device.instant_currents(read)["drain"] / id0)
    slope, intercept = linfit(np.log(times), np.log(degradation))
    assert slope == pytest.approx(0.45, abs=0.03)
    assert math.exp(intercept) == pytest.approx(1e-3 * 2.0 ** 4, rel=0.10)
    assert degradation[-1] == pytest.approx(device.hci_truth(2.0, 1e3), rel=1e-6)
    off = mosfet(**HCI)
    off.advance(1e3, bias(0.0, 2.0))  # channel off: no hot carriers
    assert off.hci_d == 0.0


# -- IGZO stretched-exponential drift -----------------------------------------------------------------------------

IGZO = {"igzo_dvth_per_v": 0.05, "igzo_tau_s": 100.0, "igzo_beta": 0.45}


def test_igzo_bias_stress_tau_and_beta() -> None:
    device = mosfet(**IGZO)
    times = np.logspace(-1, 4, 21)
    shifts = stress_series(device, 10.0, times)
    plateau = mosfet(**IGZO)
    dv_inf = stress_series(plateau, 10.0, np.array([1e9]))[0]  # ΔV∞ from a very long stress
    assert dv_inf == pytest.approx(0.5, rel=1e-3)
    usable = (shifts > 0.02 * dv_inf) & (shifts < 0.98 * dv_inf)
    beta, intercept = linfit(np.log(times[usable]), np.log(-np.log(1 - shifts[usable] / dv_inf)))
    tau = math.exp(-intercept / beta)
    assert beta == pytest.approx(0.45, abs=0.1)
    assert tau == pytest.approx(100.0, rel=0.15)
    assert shifts[10] == pytest.approx(device.igzo_truth(10.0, float(times[10])), rel=1e-3)


def test_igzo_recovery_and_negative_bias() -> None:
    device = mosfet(**IGZO, igzo_recovery_tau_s=50.0)
    device.advance(1e3, bias(10.0, 0.0))
    stressed = device.igzo_dv
    device.advance(50.0, bias(0.0, 0.0))  # one recovery time constant
    assert device.igzo_dv == pytest.approx(stressed * math.exp(-1.0), rel=1e-6)
    negative = mosfet(**IGZO)
    negative.advance(100.0, bias(-10.0, 0.0))  # NBS: the threshold moves negative
    assert negative.igzo_dv == pytest.approx(negative.igzo_truth(-10.0, 100.0), rel=1e-9) and negative.igzo_dv < 0


# -- split C-V ----------------------------------------------------------------------------------------------------

GEOMETRY = {"w_um": 20.0, "l_um": 10.0, "tox_nm": 10.0, "nsub_cm3": 3e17, "cov_f_per_m": 2e-10}


def test_split_cv_plateau_overlap_and_threshold() -> None:
    device = mosfet(**GEOMETRY)
    truth = device.cv_truth()
    cox_wl = EPS0_F_CM * 3.9 / 10e-7 * 20.0 * 10.0 * 1e-8
    assert truth["cox_wl_f"] == pytest.approx(cox_wl, rel=1e-12)
    vg = np.linspace(-2.0, 4.0, 241)
    cgc = np.array([device.split_cv(float(v), 1e4)["cgc"] for v in vg])
    cgb = np.array([device.split_cv(float(v), 1e4)["cgb"] for v in vg])
    floor = cgc[:20].mean()  # accumulation: only the two overlaps
    assert floor == pytest.approx(truth["c_overlap_f"], rel=0.01)
    assert cgc.max() - floor == pytest.approx(cox_wl, rel=0.02)  # the Cgc plateau
    assert cgb[0] == pytest.approx(cox_wl, rel=0.05) and cgb[-1] < 0.05 * cox_wl  # bulk shielded in inversion
    dcgc = np.gradient(cgc, vg)
    assert vg[int(np.argmax(dcgc))] == pytest.approx(truth["vth_v"], abs=0.15)  # C-V threshold near vth0


def test_long_channel_rolls_off_at_high_frequency() -> None:
    long_channel = mosfet(**{**GEOMETRY, "l_um": 200.0, "w_um": 200.0}, beta=2e-5)
    low = long_channel.split_cv(2.5, 1e3)["cgc"]
    high = long_channel.split_cv(2.5, 5e6)["cgc"]
    assert high < 0.9 * low  # distributed channel RC: the far channel no longer follows
    short = mosfet(**GEOMETRY)
    assert short.split_cv(2.5, 5e6)["cgc"] == pytest.approx(short.split_cv(2.5, 1e3)["cgc"], rel=0.01)
    v = bias(1.5, 0.0)
    assert short.gate_capacitance(v, 1e4, ("drain",)) == pytest.approx(
        0.5 * (short.gate_capacitance(v, 1e4, ("source", "drain")) - 2 * 2e-10 * 20e-6) + 2e-10 * 20e-6, rel=1e-6)
    with pytest.raises(ValueError, match="no AC terminal"):
        short.gate_admittance(v, 1e4, ("gate",))
    with pytest.raises(ValueError, match="w_um, l_um and tox_nm"):
        mosfet().split_cv(1.0, 1e4)


def test_state_round_trip_and_validation() -> None:
    device = mosfet(**SELFHEAT, **BTI, **HCI, **IGZO)
    device.advance(10.0, bias(2.0, 1.5))
    device.advance(1.0, bias(0.0, 0.0))
    state = device.export_state()
    clone = mosfet(**SELFHEAT, **BTI, **HCI, **IGZO)
    clone.import_state(state)
    assert clone.export_state() == state and clone.vth == device.vth
    clone.import_state(None)
    assert clone.export_state() == mosfet().export_state()
    with pytest.raises(ValueError, match="exactly"):
        clone.import_state({"dt_k": 0.0})
    with pytest.raises(ValueError, match="bti_recovering"):
        clone.import_state({**state, "bti_recovering": 0.0})
