"""``moscap`` device truth (blueprint 4.2, WP5.9): Cox ±1 %, Vfb ±20 mV, Nsub ±10 %, Dit peak ±25 % and hysteresis
±10 mV recovered from simulated C-V/G-V output with textbook extractions; LF/HF, QSCV charge, deep depletion and
C-t recovery, series resistance, leakage and state persistence."""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.models.sim import MoscapParams
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from tests.sim.device_fits import EPS0_F_CM, Q_E, UT_300, crossing, linfit

pytestmark = pytest.mark.cmu

BASE = {"nsub_cm3": 3.0e16, "tox_nm": 12.0, "phi_ms_v": -0.85, "qf_cm2": 2.0e11, "area_um2": 4.0e4}
HF = 1.0e5


def moscap(**extra: float | str) -> MoscapDevice:
    return MoscapDevice("m", MoscapParams.model_validate({**BASE, **extra}))


def hf_cv(device: MoscapDevice, v: np.ndarray, f: float = HF) -> np.ndarray:
    """Quasi-static staircase: commit every step, then read the parallel capacitance."""
    out = []
    for x in v:
        device.commit({"gate": float(x), "bulk": 0.0})
        out.append(device.capacitance(float(x), f))
    return np.array(out)


def extract_cox(v: np.ndarray, c: np.ndarray, accumulation: np.ndarray) -> float:
    """Accumulation extrapolation: ``1/C = 1/Cox + b/(V0 - V)``, ``V0`` scanned, intercept → ``1/Cox``."""
    best: tuple[float, float] | None = None
    for v0 in np.linspace(v[accumulation].max() + 0.05, v[accumulation].max() + 3.0, 300):
        x = 1.0 / (v0 - v[accumulation])
        design = np.vstack([np.ones_like(x), x]).T
        sol, *_ = np.linalg.lstsq(design, 1.0 / c[accumulation], rcond=None)
        residual = float(np.sum((design @ sol - 1.0 / c[accumulation]) ** 2))
        if best is None or residual < best[0]:
            best = (residual, 1.0 / sol[0])
    assert best is not None
    return best[1]


def extract_p_type(device: MoscapDevice) -> dict[str, float]:
    """Cox (accumulation extrapolation), Nsub (1/C² slope in depletion), Vfb (flatband capacitance) of a p-type
    HF C-V from -4 V to +3 V."""
    v = np.linspace(-4.0, 3.0, 701)
    c = hf_cv(device, v)
    area = device.area
    cox = extract_cox(v, c, v <= -2.5)
    depletion = (c > 1.3 * c.min()) & (c < 0.4 * cox)
    slope, _ = linfit(v[depletion], 1.0 / c[depletion] ** 2)
    eps_s = 11.7 * EPS0_F_CM
    nsub = 2.0 / (Q_E * eps_s * area * area * slope)
    c_debye = eps_s / math.sqrt(eps_s * UT_300 / (Q_E * nsub)) * area
    c_fb = cox * c_debye / (cox + c_debye)
    return {"cox": cox, "nsub": nsub, "vfb": crossing(v, -c, -c_fb)}


def test_hf_cv_recovers_cox_vfb_and_nsub() -> None:
    device = moscap(rs_ohm=20.0)
    truth = device.truth()
    got = extract_p_type(device)
    assert got["cox"] == pytest.approx(truth["cox_f"], rel=0.01)
    assert got["nsub"] == pytest.approx(truth["nsub_cm3"], rel=0.10)
    assert got["vfb"] == pytest.approx(truth["vfb_v"], abs=0.020)
    # the truth itself: Cox = ε0·εox·A/tox, Vfb = φms - q·Qf/Cox (no interface traps here)
    cox_area = EPS0_F_CM * 3.9 / 12.0e-7
    assert truth["cox_f"] == pytest.approx(cox_area * 4.0e-4, rel=1e-12)
    assert truth["vfb_v"] == pytest.approx(-0.85 - Q_E * 2.0e11 / cox_area, rel=1e-12)


@pytest.mark.parametrize("nsub", [5.0e15, 1.0e17])
def test_extraction_holds_across_doping(nsub: float) -> None:
    device = moscap(nsub_cm3=nsub, qf_cm2=0.0, phi_ms_v=-0.5)
    got, truth = extract_p_type(device), device.truth()
    assert got["cox"] == pytest.approx(truth["cox_f"], rel=0.01)
    assert got["nsub"] == pytest.approx(nsub, rel=0.10)
    assert got["vfb"] == pytest.approx(truth["vfb_v"], abs=0.020)


def test_n_substrate_mirrors_the_p_substrate() -> None:
    p_dev = moscap(phi_ms_v=0.3, qf_cm2=0.0)
    n_dev = moscap(substrate="n", phi_ms_v=-0.3, qf_cm2=0.0)
    for v in (-2.0, -0.5, 0.0, 0.7, 2.0):
        assert n_dev.equilibrium_capacitance(-v, HF) == pytest.approx(p_dev.equilibrium_capacitance(v, HF), rel=1e-9)
    assert n_dev.vfb() == pytest.approx(-p_dev.vfb())
    # positive fixed charge shifts Vfb negative on both substrate types
    assert moscap(substrate="n", qf_cm2=1e11, phi_ms_v=0.0).vfb() < 0.0 < -moscap(qf_cm2=1e11, phi_ms_v=0.0).vfb()


def gp_over_omega(device: MoscapDevice, v: float, freqs: np.ndarray) -> np.ndarray:
    """Cox-corrected parallel conductance ``Gp/ω`` from the measured Cm-Gm (Nicollian & Goetzberger)."""
    out = []
    cox = device.cox
    for f in freqs:
        y = device.admittance(v, float(f))
        w = 2.0 * math.pi * f
        gm, cm = y.real, y.imag / w
        out.append(w * gm * cox * cox / (gm * gm + (w * (cox - cm)) ** 2))
    return np.array(out)


@pytest.mark.parametrize("vg", [-0.8, -0.7, -0.6, -0.5])
def test_conductance_method_recovers_dit_at_the_peak(vg: float) -> None:
    device = moscap(qf_cm2=0.0, dit_cm2_ev=2.0e11, dit_edge_cm2_ev=1.0e11, dit_width_ev=0.15)
    device.commit({"gate": vg, "bulk": 0.0})
    freqs = np.logspace(3.0, math.log10(5.0e6), 300)  # the MFCMU range
    gpw = gp_over_omega(device, vg, freqs)
    k = int(gpw.argmax())
    assert 0 < k < len(freqs) - 1  # the peak lies inside the frequency range
    dit = gpw[k] / (0.402 * Q_E * device.area)  # continuum: (Gp/ω)max = 0.402·q·Dit
    assert dit == pytest.approx(device.dit_at(vg), rel=0.25)
    # the probed energy moves towards midgap (slower traps) as the bias goes deeper into depletion
    psi = device.surface_potential(vg)
    assert device.es.tau_it(psi) == pytest.approx(1.98 / (2 * math.pi * freqs[k]), rel=0.1)


def test_interface_traps_stretch_the_cv_and_shift_vfb() -> None:
    clean, trapped = moscap(qf_cm2=0.0), moscap(qf_cm2=0.0, dit_cm2_ev=5e11)
    # at flatband the donor-like traps below midgap are empty: positive charge, Vfb moves negative by q·Dit·φB/Cox
    phi_b = trapped.es.phi_b
    assert trapped.vfb() - clean.vfb() == pytest.approx(-Q_E * 5e11 * phi_b / trapped.cox_area, rel=1e-9)
    # HF stretch-out: traps follow the DC bias, so dVg/dψ grows and the depletion transition spreads over more volts
    v = np.linspace(-2.0, 1.0, 601)
    c_clean, c_trap = hf_cv(clean, v), hf_cv(trapped, v)

    def span(c: np.ndarray) -> float:
        return crossing(v, -c, -0.3 * clean.cox) - crossing(v, -c, -0.6 * clean.cox)

    assert span(c_trap) > 1.05 * span(c_clean)
    for vg in (-1.0, -0.6, -0.2):  # gate equation: dψ/dVg = 1/(1 + (Cb + Cinv + Cit)/Cox)
        psi = trapped.surface_potential(vg)
        es = trapped.es
        h = 1e-5
        slope = (trapped.surface_potential(vg + h) - trapped.surface_potential(vg - h)) / (2 * h)
        expected = 1.0 / (1.0 + (es.c_bulk(psi) + es.c_inv_eq(psi) + es.c_it_lf(psi)) / es.cox)
        assert slope == pytest.approx(expected, rel=1e-4)
    # LF: interface traps add q·Dit to the semiconductor capacitance (the Dit "hump" of a QSCV curve)
    assert trapped.equilibrium_capacitance(-0.4, 1.0) > clean.equilibrium_capacitance(-0.4, 1.0)


def test_hysteresis_of_a_double_sweep_matches_the_truth() -> None:
    device = moscap(qf_cm2=0.0, hysteresis_v=0.08, hysteresis_vc_v=1.5, hysteresis_width_v=0.1)
    truth = device.hysteresis_truth(-4.0, 3.0)
    assert truth["hysteresis"] == pytest.approx(0.08, abs=0.002)  # full charge/discharge of the border traps
    v = np.linspace(-4.0, 3.0, 701)
    forward = hf_cv(device, v)
    reverse = hf_cv(device, v[::-1])[::-1]
    c_fb = device.flatband_capacitance
    vfb_fwd, vfb_rev = crossing(v, -forward, -c_fb), crossing(v, -reverse, -c_fb)
    assert vfb_fwd == pytest.approx(truth["vfb_fwd"], abs=0.010)
    assert vfb_rev == pytest.approx(truth["vfb_rev"], abs=0.010)
    assert vfb_rev - vfb_fwd == pytest.approx(truth["hysteresis"], abs=0.010)
    # a sweep that stays inside the band does not charge the traps
    small = moscap(qf_cm2=0.0, hysteresis_v=0.08, hysteresis_vc_v=1.5, hysteresis_width_v=0.1)
    assert small.hysteresis_truth(-1.0, 1.0)["hysteresis"] == pytest.approx(0.0, abs=1e-3)


def test_low_frequency_inversion_and_qscv_charge() -> None:
    device = moscap(f_inv_hz=10.0)
    cox = device.cox
    assert device.equilibrium_capacitance(2.5, 0.1) > 0.95 * cox  # LF: inversion layer follows the signal
    assert device.equilibrium_capacitance(2.5, 1.0e5) < 0.2 * cox  # HF: only the depletion edge responds
    for v in (-2.0, -0.8, 0.0, 1.0, 2.5):  # QSCV: dQ/dV of the quasi-static charge = LF capacitance
        h = 1e-4
        dq_dv = (device.charge(v + h) - device.charge(v - h)) / (2 * h)
        assert dq_dv == pytest.approx(device.equilibrium_capacitance(v, 1e-6), rel=2e-3)


def test_deep_depletion_and_c_t_recovery() -> None:
    device = moscap(tau_inv_s=2.0)
    accumulate = {"gate": -3.0, "bulk": 0.0}
    invert = {"gate": 2.0, "bulk": 0.0}
    device.commit(accumulate)
    device.advance(1e-6, invert)  # a fast step into inversion: no minority carriers yet
    c0 = device.capacitance(2.0, HF)
    c_eq = device.equilibrium_capacitance(2.0, HF)
    assert c0 == pytest.approx(device.deep_depletion_capacitance(2.0, HF), rel=1e-3) and c0 < 0.85 * c_eq
    q_eq = device.es.q_inv_eq(device.surface_potential(2.0))
    device.advance(2.0, invert)  # one time constant
    assert device.q_inv == pytest.approx(q_eq * (1 - math.exp(-(2.0 + 1e-6) / 2.0)), rel=1e-3)
    c_mid = device.capacitance(2.0, HF)
    device.advance(40.0, invert)
    assert c0 < c_mid < device.capacitance(2.0, HF) == pytest.approx(c_eq, rel=1e-6)


def test_series_resistance_leakage_and_displacement_current() -> None:
    device = moscap(rs_ohm=500.0, leak_s=1e-9)
    f = 1.0e6
    ideal = moscap(leak_s=1e-9)
    y_ideal = ideal.admittance(-3.0, f)
    y = device.admittance(-3.0, f)
    assert y == pytest.approx(1.0 / (500.0 + 1.0 / y_ideal), rel=1e-12)
    assert device.capacitance(-3.0, f) < 0.9 * ideal.capacitance(-3.0, f)  # Rs·ωC ≈ 0.35 lowers the parallel C
    assert device.terminal_currents({"gate": 2.0, "bulk": 0.0}) == {"gate": 2e-9, "bulk": -2e-9}
    ramp = moscap()
    ramp.commit({"gate": -2.0, "bulk": 0.0})
    q0 = ramp.q_gate
    total = 0.0
    for v in np.linspace(-1.99, 0.0, 200):
        total += ramp.advance(0.01, {"gate": float(v), "bulk": 0.0})["gate"] * 0.01
    assert total == pytest.approx(ramp.q_gate - q0, rel=1e-9)  # ∫I·dt = ΔQ
    assert ramp.advance(0.0, {"gate": 0.0, "bulk": None}) == {"gate": 0.0, "bulk": 0.0}  # floating: no current


def test_state_round_trip_and_validation() -> None:
    device = moscap(hysteresis_v=0.05)
    device.commit({"gate": 3.0, "bulk": 0.0})
    device.advance(0.5, {"gate": -1.0, "bulk": 0.0})
    state = device.export_state()
    clone = moscap(hysteresis_v=0.05)
    clone.import_state(state)
    assert clone.export_state() == state
    assert clone.capacitance(0.5, HF) == device.capacitance(0.5, HF)
    clone.import_state(None)
    assert clone.export_state() == moscap(hysteresis_v=0.05).export_state()
    with pytest.raises(ValueError, match="exactly"):
        clone.import_state({**state, "x": 1.0})
    with pytest.raises(ValueError, match="s_bt"):
        clone.import_state({**state, "s_bt": 2.0})
    with pytest.raises(ValueError, match="positive"):
        device.capacitance(0.0, 0.0)
