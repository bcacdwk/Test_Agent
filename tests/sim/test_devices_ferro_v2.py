"""Ferroelectric device truth v2 (blueprint 4.2, WP5.9).

FeFET: memory window from program/erase pulses ±10 %, NLS kinetics τ0 and β ±20 % (fitted from switched fractions
read through the drain current), retention slope ±10 %, wake-up/fatigue, v1 DC loop and state unchanged.
FeCap: Pr, Ps, Ec ±5 % from a simulated PUND sequence, C-V butterfly peaks at ±Vc, displacement charge, state.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.models.sim import FecapParams, FefetParams
from b1500_test_agent.transport.sim.devices.ferro import FecapDevice, FefetDevice
from tests.sim.device_fits import constant_current_vth, crossing, linfit

FEFET = {"vth0": 0.6, "k_v": 0.5, "vc_v": 2.8, "delta_v": 0.45, "p_init": -1.0, "slope_factor": 1.3, "beta": 1e-3,
         "theta": 0.5, "rs_ohm": 20.0, "tau0_s": 1e-10, "va_v": 12.0, "alpha": 2.0, "beta_sw": 1.2}
VD = 0.05


def fefet(**extra: float) -> FefetDevice:
    return FefetDevice("f", FefetParams.model_validate({**FEFET, **extra}))


def gate(v: float) -> dict[str, float | None]:
    return {"gate": v, "drain": 0.0, "source": 0.0, "bulk": 0.0}


def read_vth(device: FefetDevice) -> float:
    """Constant-current threshold (100 nA at Vd = 50 mV) from instant reads that switch nothing."""
    return constant_current_vth(
        lambda vg: device.instant_currents({"gate": vg, "drain": VD, "source": 0.0, "bulk": 0.0})["drain"], 1e-7)


def erase(device: FefetDevice) -> None:
    device.advance(1.0, gate(-6.0))
    device.advance(1e-3, gate(0.0))


# -- FeFET -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [1e-6, 1e-4, 1e-8])
def test_memory_window_from_program_erase_pulses(width: float) -> None:
    programmed = fefet()
    erase(programmed)
    programmed.advance(width, gate(4.5))  # one program pulse from the erased saturation
    programmed.advance(1e-3, gate(0.0))
    erased = fefet()
    erased.advance(1.0, gate(5.0))  # programmed saturation, then one erase pulse
    erased.advance(width, gate(-4.5))
    erased.advance(1e-3, gate(0.0))
    window = read_vth(erased) - read_vth(programmed)
    truth = programmed.memory_window_truth(4.5, -4.5, width)
    assert window == pytest.approx(truth, rel=0.10)
    if width >= 1e-6:  # long pulses saturate: about 2·k_v·P_up(4.5), the erased state above the programmed one
        assert window > 0.9 and truth == pytest.approx(2 * 0.5 * math.tanh((4.5 - 2.8) / 0.45), rel=0.01)
    else:  # 10 ns ≪ τ(4.5 V) ≈ 120 ns: both states stay near their starting saturation (window inverted)
        assert window < -0.8


def test_nls_kinetics_tau0_and_beta_from_switched_fractions() -> None:
    device = fefet()
    taus: dict[float, float] = {}
    betas = []
    for amplitude in (3.5, 4.0, 4.5, 5.0):
        erase(device)
        v0 = read_vth(device)
        device.advance(10.0, gate(amplitude))
        v_sat = read_vth(device)
        widths, fractions = [], []
        tau_guess = device.tau(amplitude)
        for width in np.logspace(math.log10(tau_guess) - 1.5, math.log10(tau_guess) + 0.7, 12):
            erase(device)
            device.advance(float(width), gate(amplitude))
            s = (v0 - read_vth(device)) / (v0 - v_sat)
            if 0.02 < s < 0.98:
                widths.append(width)
                fractions.append(s)
        beta, intercept = linfit(np.log(widths), np.log(-np.log(1.0 - np.array(fractions))))
        betas.append(beta)
        taus[amplitude] = math.exp(-intercept / beta)
        assert device.switched_fraction(tau_guess, amplitude) == pytest.approx(1 - math.exp(-1))
    assert np.mean(betas) == pytest.approx(1.2, rel=0.20)
    v = np.array(list(taus))
    log_tau = np.log(np.array(list(taus.values())))
    best = None
    for alpha in np.arange(1.0, 3.0, 0.01):  # τ(V) = τ0·exp((Va/V)^α): grid in α, linear in V^-α
        slope, icpt = linfit(v ** -alpha, log_tau)
        residual = float(np.sum((icpt + slope * v ** -alpha - log_tau) ** 2))
        if best is None or residual < best[0]:
            best = (residual, alpha, icpt)
    assert best is not None
    assert math.exp(best[2]) == pytest.approx(1e-10, rel=0.20)
    assert best[1] == pytest.approx(2.0, abs=0.1)


def test_dc_commit_keeps_the_v1_loop_and_long_pulses_reach_it() -> None:
    device = fefet()
    device.commit(gate(3.5))
    dc = device.p
    other = fefet()
    other.advance(1e6, gate(3.5))
    assert other.p == pytest.approx(dc, rel=1e-9)  # a very long pulse ends on the DC loop
    short = fefet()
    short.advance(1e-9, gate(3.5))
    assert short.p == pytest.approx(-1.0, abs=1e-3)  # a ns pulse at 3.5 V barely switches
    assert fefet().loop_truth(-4.0, 4.0)["memory_window"] == pytest.approx(0.995, abs=0.005)
    assert fefet().export_state() == {"p": -1.0}  # v1 state shape while retention/endurance are off


def test_retention_log_decay_slope() -> None:
    device = fefet(retention_rate=0.05, retention_t0_s=1.0)
    erase(device)
    device.advance(1e-3, gate(5.0))
    p_written = device.p
    times = np.logspace(1, 5, 9)
    vths = []
    elapsed = 0.0
    for t in times:
        device.advance(float(t - elapsed), gate(0.0))
        elapsed = float(t)
        vths.append(read_vth(device))
    slope, _ = linfit(np.log10(times), vths)
    assert slope == pytest.approx(device.retention_slope(p_written), rel=0.10)
    assert device.p == pytest.approx(device.retention_truth(p_written, 1e5), rel=1e-9)
    assert set(device.export_state()) == {"p", "p_w", "t_ret"}
    device.advance(1e-3, gate(-5.0))  # a new write restarts the retention clock
    assert device.t_ret == 0.0 and device.p_w == device.p


def test_wake_up_and_fatigue_scale_the_window() -> None:
    device = fefet(wake_frac=0.3, wake_cycles=50.0, fatigue_cycles=1e5, fatigue_exp=0.5)
    assert device.scale == pytest.approx(0.7)

    def window() -> float:
        device.advance(1e-3, gate(5.0))
        low = read_vth(device)
        device.advance(1e-3, gate(-5.0))
        return read_vth(device) - low

    w0 = window()
    assert device.cycles == pytest.approx(1.0)  # one program + one erase = two zero crossings
    for _ in range(199):
        window()
    assert device.cycles == pytest.approx(200.0)
    w200 = window()
    truth = device.endurance_truth
    assert w200 / w0 == pytest.approx(truth(201.0) / truth(1.0), rel=0.02)  # wake-up opens the window
    device.add_cycles(1e7)
    w_fatigued = window()
    assert w_fatigued / w200 == pytest.approx(truth(1e7 + 202.0) / truth(201.0), rel=0.02)
    assert w_fatigued < 0.2 * w200
    state = device.export_state()
    assert set(state) == {"p", "cycles"}
    clone = fefet(wake_frac=0.3, wake_cycles=50.0, fatigue_cycles=1e5, fatigue_exp=0.5)
    clone.import_state(state)
    assert clone.cycles == device.cycles and clone.p == device.p


def test_fefet_state_validation_lists_the_expected_keys() -> None:
    device = fefet(retention_rate=0.02)
    with pytest.raises(ValueError, match="exactly 'p', 'p_w', 't_ret'"):
        device.import_state({"p": 0.0})
    with pytest.raises(ValueError, match="t_ret"):
        device.import_state({"p": 0.0, "p_w": 0.0, "t_ret": -1.0})
    device.import_state(None)
    assert device.p == -1.0 and device.t_ret == 0.0
    assert device.tau(0.0) == math.inf and device.tau(0.1) == math.inf  # no switching at tiny bias


# -- FeCap -----------------------------------------------------------------------------------------------------------

FECAP = {"area_um2": 1e4, "thickness_nm": 10.0, "pr_uc_cm2": 20.0, "ps_uc_cm2": 25.0, "ec_mv_cm": 1.0, "eps_r": 30.0}


def fecap(**extra: float) -> FecapDevice:
    return FecapDevice("c", FecapParams.model_validate({**FECAP, **extra}))


def triangle(device: FecapDevice, v_max: float, rise_s: float = 1e-6, steps: int = 400
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One triangular pulse 0 → v_max → 0: voltages, currents and the step time."""
    dt = rise_s / steps
    up = np.linspace(v_max / steps, v_max, steps)
    down = np.linspace(v_max - v_max / steps, 0.0, steps)
    volts = np.concatenate([up, down])
    amps = np.array([device.advance(dt, {"top": float(v), "bottom": 0.0})["top"] for v in volts])
    return volts, amps, np.full(volts.shape, dt)


def test_pund_recovers_pr_ps_and_ec() -> None:
    device = fecap()
    v_max = 4.0  # 4·Vc: the branches are within 2.4 % of Ps
    triangle(device, -v_max)  # preset (negative)
    vp, ip, dtp = triangle(device, v_max)  # P: switching
    vu, iu, dtu = triangle(device, v_max)  # U: no switching
    n = len(vp) // 2
    area = 1e4 * 1e-8
    q_p, q_u = float(np.sum(ip[:n] * dtp[:n])), float(np.sum(iu[:n] * dtu[:n]))
    pr = (q_p - q_u) / 2 / area * 1e6
    c_lin = iu[n + 1] / ((vu[n] - vu[n + 1]) / dtu[n + 1]) * -1  # U falling edge near the top: dielectric only
    ps = ((q_p + q_u) / 2 - c_lin * v_max) / area * 1e6
    switching = ip[:n] - iu[:n]
    ec = vp[int(np.argmax(switching))] / (10.0 * 1e-7) / 1e6
    truth = device.pund_truth(v_max)
    assert pr == pytest.approx(truth["pr_uc_cm2"], rel=0.05)
    assert ps == pytest.approx(truth["ps_uc_cm2"], rel=0.05)
    assert ec == pytest.approx(truth["ec_mv_cm"], rel=0.05)
    assert c_lin == pytest.approx(8.8541878128e-14 * 30.0 * area / 1e-6, rel=1e-6)
    # against the parameters (the loop saturates at 4·Vc)
    assert pr == pytest.approx(20.0, rel=0.05) and ps == pytest.approx(25.0, rel=0.05) and ec == pytest.approx(1.0,
                                                                                                             rel=0.05)
    # N and D mirror P and U
    _, i_n, dt_n = triangle(device, -v_max)
    _, i_d, dt_d = triangle(device, -v_max)
    assert (np.sum(i_n[:n] * dt_n[:n]) - np.sum(i_d[:n] * dt_d[:n])) / 2 / area * 1e6 == pytest.approx(-pr, rel=1e-6)


def test_minor_pund_has_a_smaller_remanence() -> None:
    device = fecap()
    small = device.pund_truth(1.2)
    assert small["pr_uc_cm2"] < 0.6 * device.pund_truth(4.0)["pr_uc_cm2"]
    assert device.pund_truth(4.0)["vc_v"] == pytest.approx(1.0)


def test_cv_butterfly_peaks_at_plus_minus_vc() -> None:
    device = fecap(k_rev=0.1)
    v = np.linspace(-3.0, 3.0, 601)
    device.commit({"top": -3.0, "bottom": 0.0})
    up = []
    for x in v:
        device.commit({"top": float(x), "bottom": 0.0})
        up.append(device.capacitance(float(x), 1e5))
    down = []
    for x in v[::-1]:
        device.commit({"top": float(x), "bottom": 0.0})
        down.append(device.capacitance(float(x), 1e5))
    truth = device.butterfly_truth()
    assert v[int(np.argmax(up))] == pytest.approx(truth["v_peak_up"], rel=0.05)
    assert v[::-1][int(np.argmax(down))] == pytest.approx(truth["v_peak_down"], rel=0.05)
    assert min(up) == pytest.approx(device.c_lin, rel=0.05)  # far from Vc only the linear dielectric
    assert device.admittance(0.0, 1e5).imag == pytest.approx(2 * math.pi * 1e5 * device.capacitance(0.0, 1e5))


def test_fecap_charge_balance_endurance_and_state() -> None:
    device = fecap(wake_frac=0.2, wake_cycles=10.0)
    triangle(device, -4.0)
    p_before = device.p
    _, amps, dt = triangle(device, 4.0)
    q = float(np.sum(amps * dt))
    assert q == pytest.approx((device.p - p_before) * device.ps_c, rel=1e-9)  # back at 0 V: only switched charge
    assert device.cycles == pytest.approx(1.0)
    pr_early = device.pund_truth(4.0)["pr_uc_cm2"]
    for _ in range(20):
        triangle(device, 4.0, steps=20)
        triangle(device, -4.0, steps=20)
    assert device.pund_truth(4.0)["pr_uc_cm2"] > pr_early  # woken up
    state = device.export_state()
    assert set(state) == {"p", "v", "dir", "cycles"}
    clone = fecap(wake_frac=0.2, wake_cycles=10.0)
    clone.import_state(state)
    assert clone.export_state() == state
    with pytest.raises(ValueError, match="dir"):
        clone.import_state({**state, "dir": 0.5})
    clone.import_state(None)
    assert clone.cycles == 0.0 and clone.v == 0.0
    assert fecap().export_state() == {"p": 0.0, "v": 0.0, "dir": 1.0}
    assert device.terminal_currents({"top": 1.0, "bottom": 0.0}) == {"top": 0.0, "bottom": -0.0}


def test_fecap_crossing_helper_sanity() -> None:
    device = fecap()
    v = np.linspace(-3, 3, 601)
    branch = np.array([device.p_up(float(x)) for x in v])
    assert crossing(v, branch, 0.0) == pytest.approx(device.vc, rel=1e-3)  # P+ crosses zero at +Vc
