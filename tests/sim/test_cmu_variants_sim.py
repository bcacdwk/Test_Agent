"""Simulator physics behind the C-V variants (blueprint v2 4.1, 4.2; WP8.4): the MFCMU's large-signal response (the
describing function over the oscillator swing; a linear element is unchanged), the oscillator-level dependence of the
measurement noise, the interface traps of ``moscap`` limited to the band gap and their minority-band exchange
following the minority carriers (no trap capacitance in HF inversion; deep depletion stays finite), the C-t sampling
(MM 26) with time stamps on a recovering MOS capacitor, and the FeCap butterfly through an MM 18 double sweep."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest

from b1500_test_agent.driver.cmu_data import CmuLayout, parse_cmu_blocks
from b1500_test_agent.driver.parser import parse_data
from b1500_test_agent.models.sim import FecapParams, MoscapParams
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.devices.ferro import FecapDevice
from b1500_test_agent.transport.sim.devices.moscap import GAP_HALF_EV, MoscapDevice
from b1500_test_agent.transport.sim.units.cmu_engine import AC_QUADRATURE
from tests.sim.helpers import load_scenario, noiseless, run

CMU = 7
DIT = {"dit_cm2_ev": 2.0e11, "dit_edge_cm2_ev": 1.0e10, "dit_width_ev": 0.1}


def moscap(**extra: float | str) -> MoscapDevice:
    base: dict[str, float | str] = {"area_um2": 1e4, "tox_nm": 5.0, "nsub_cm3": 1e17, "phi_ms_v": -0.85,
                                    "qf_cm2": 5e10, "tau_inv_s": 0.5}
    return MoscapDevice("m", MoscapParams.model_validate({**base, **extra}))


def readings(sim: SimTransport, layout: CmuLayout) -> list[float]:
    """Cp values of the data block ``XE`` just produced."""
    return [r.table_values()["Cp"][0] for r in parse_cmu_blocks(parse_data(sim.read(timeout_s=60), 1), layout)]


def cmu_sim(make_sim: Callable[..., SimTransport], name: str, *, noise: bool = False) -> SimTransport:
    scenario: SimScenario = load_scenario(name)
    return make_sim(scenario if noise else noiseless(scenario))


# -- large-signal response -------------------------------------------------------------------------------------------


def test_quadrature_is_the_semicircle_average() -> None:
    assert sum(w for _, w in AC_QUADRATURE) == pytest.approx(1.0)
    assert sum(w * u * u for u, w in AC_QUADRATURE) == pytest.approx(0.25)  # <u^2> over (2/pi) sqrt(1 - u^2)
    assert sum(w * u**4 for u, w in AC_QUADRATURE) == pytest.approx(0.125)


def ac_level_sweep(sim: SimTransport, dc: float, levels: tuple[float, float], steps: int) -> list[float]:
    run(sim, f"CN {CMU}", "FMT 1,1", "IMP 100", f"FC {CMU},1000000", f"DCV {CMU},{dc}", "WTACV 0.1,0",
        "WMACV 2,1", f"WACV {CMU},1,{levels[0]},{levels[1]},{steps}", f"MM 23,{CMU}", "XE")
    return readings(sim, CmuLayout(imp=100, mode=23, source=True))


def test_a_linear_capacitor_reads_the_same_at_every_level(make_sim: Callable[..., SimTransport]) -> None:
    c = ac_level_sweep(cmu_sim(make_sim, "capacitor_100p"), 0.0, (0.01, 0.25), 7)
    assert np.allclose(c, c[0], rtol=1e-12)


def test_a_curved_cv_moves_with_the_level_as_the_describing_function(make_sim: Callable[..., SimTransport]) -> None:
    sim = cmu_sim(make_sim, "moscap_basic")
    c = np.array(ac_level_sweep(sim, -0.6, (0.01, 0.25), 7))
    vac = np.linspace(0.01, 0.25, 7)
    fit = np.polyfit(vac**2, c, 1)  # C = C0 + C'' Vac^2 / 4 for small levels
    device = MoscapDevice("dut", MoscapParams.model_validate(load_scenario("moscap_basic").models["dut"].params))
    device.commit({"gate": -0.6, "bulk": 0.0})
    h = 1e-3
    c0 = device.capacitance(-0.6, 1e6)
    curvature = (device.capacitance(-0.6 + h, 1e6) - 2 * c0 + device.capacitance(-0.6 - h, 1e6)) / h**2
    assert fit[1] == pytest.approx(c0 + 0.3e-12, rel=2e-3)  # + the uncorrected 0.3 pF open of the fixture
    assert 4 * fit[0] == pytest.approx(curvature, rel=0.15)  # higher orders add a little at 250 mVrms
    assert c[-1] / c[0] - 1 > 0.05  # 250 mVrms leaves the small-signal regime


def test_noise_falls_with_the_oscillator_level(make_sim: Callable[..., SimTransport]) -> None:
    sim = cmu_sim(make_sim, "capacitor_100p", noise=True)
    spread = {}
    for level in (0.01, 0.1):
        run(sim, f"CN {CMU}", "FMT 1,1", "IMP 100", f"FC {CMU},100000", f"ACV {CMU},{level}", f"DCV {CMU},0",
            f"MM 17,{CMU}")
        values = []
        for _ in range(80):
            run(sim, "XE")
            values += readings(sim, CmuLayout(imp=100, mode=17))
        spread[level] = float(np.std(values) / np.mean(values))
    assert spread[0.01] / spread[0.1] == pytest.approx(10.0, rel=0.35)


# -- interface traps -------------------------------------------------------------------------------------------------


def test_interface_traps_exist_only_inside_the_band_gap() -> None:
    es = moscap(**DIT).es
    assert es.dit(GAP_HALF_EV + 0.01) == 0.0 and es.dit(-GAP_HALF_EV - 0.01) == 0.0 and es.dit(0.0) == 2e11
    edge = es.q_it(es.phi_b + GAP_HALF_EV)
    assert es.q_it(es.phi_b + 2.0) == pytest.approx(edge) and es.q_it(es.phi_b - 2.0) == pytest.approx(-edge)
    assert es.c_it_lf(es.phi_b + 1.0) == 0.0


def test_deep_depletion_is_finite_and_recovers_with_tau_inv() -> None:
    device = moscap(**DIT)
    device.commit({"gate": -2.5, "bulk": 0.0})
    start = device.deep_depletion_capacitance(2.0, 1e6)
    final = device.equilibrium_capacitance(2.0, 1e6)
    assert 0.5 * final < start < final  # deep depletion below the inversion minimum
    assert device.transient_capacitance(2.0, 1e6, 0.0) == pytest.approx(start)
    assert device.transient_capacitance(2.0, 1e6, 50.0) == pytest.approx(final, rel=1e-6)
    y = [device.transient_capacitance(2.0, 1e6, t) ** -2 for t in (0.0, 0.5, 1.0)]
    assert (y[1] - y[2]) / (y[0] - y[1]) == pytest.approx(math.exp(-1.0), rel=0.02)  # 1/C^2 relaxes with tau_inv


def test_hf_inversion_shows_no_trap_capacitance_but_lf_does() -> None:
    traps, clean = moscap(**DIT), moscap()
    for v in (0.5, 1.0, 1.5):
        for device in (traps, clean):
            device.commit({"gate": v, "bulk": 0.0})
        assert traps.capacitance(v, 1e6) == pytest.approx(clean.capacitance(v, 1e6), rel=0.03)  # HF: flat Cmin
    v = 0.3  # weak inversion, near-edge traps: they follow quasi-statically
    traps.commit({"gate": v, "bulk": 0.0})
    truth = traps.interface_trap_truth(v)
    assert truth["e_minus_ei_ev"] > 0 and truth["dit_cm2_ev"] > 2e11
    assert traps.interface_trap_truth(v, 1e6)["tau_s"] > truth["tau_s"]  # HF: only the majority exchange


def test_interface_trap_truth_matches_the_conductance_peak() -> None:
    device = moscap(**DIT)
    device.commit({"gate": -0.6, "bulk": 0.0})
    truth = device.interface_trap_truth(-0.6, 1e5)
    freqs = np.geomspace(1e3, 1e7, 2001)
    cox = device.cox
    gpw = []
    for f in freqs:
        y = device.admittance(-0.6, float(f))
        y = 1 / (1 / y - device.params.rs_ohm)
        w = 2 * math.pi * f
        gpw.append(w * cox**2 * y.real / (y.real**2 + w**2 * (cox - y.imag / w) ** 2))
    assert freqs[int(np.argmax(gpw))] == pytest.approx(truth["f_peak_hz"], rel=0.02)
    assert max(gpw) / (0.4024 * 1.602176634e-19 * device.area) == pytest.approx(truth["dit_cm2_ev"], rel=0.02)


# -- C-t and the butterfly through FLEX ------------------------------------------------------------------------------


def test_ct_sampling_records_the_recovery_with_time_stamps(make_sim: Callable[..., SimTransport]) -> None:
    sim = cmu_sim(make_sim, "moscap_dit")  # landed through the SCUU of CMU1 (WP8.5): SSP connects the MFCMU
    run(sim, f"SSP {CMU},4", "FMT 1,1", "TSC 1", "IMP 100", "ACT 0,1", f"FC {CMU},1000000", f"ACV {CMU},0.03",
        "MTDCV 0,0.05,101,1", f"MDCV {CMU},-2.5,2,2", f"MM 26,{CMU}", "TSR", "XE")
    layout = CmuLayout(imp=100, mode=26, index=True, timestamp=True)
    blocks = parse_cmu_blocks(parse_data(sim.read(timeout_s=60), 1), layout)
    times = np.array([b.time.value for b in blocks if b.time is not None])
    c = np.array([b.table_values()["Cp"][0] for b in blocks])
    assert [b.index.value for b in blocks[:3] if b.index is not None] == [1, 2, 3]
    assert np.allclose(np.diff(times), 0.05, atol=1e-6) and times[0] == pytest.approx(1.0, abs=1e-3)
    assert np.all(np.diff(c) > 0) and c[-1] / c[0] > 1.3  # deep depletion recovering
    assert sim.instrument.state.channels[CMU].voltage == 2.0  # MDCV post


def test_fecap_double_sweep_peaks_at_plus_minus_vc(make_sim: Callable[..., SimTransport]) -> None:
    sim = cmu_sim(make_sim, "fecap_basic")
    run(sim, f"CN {CMU}", "FMT 1,1", "IMP 100", f"FC {CMU},100000", f"ACV {CMU},0.03", "WTDCV 1,0", "WMDCV 2,1",
        f"WDCV {CMU},3,-3,3,121", f"MM 18,{CMU}", "XE")
    layout = CmuLayout(imp=100, mode=18, source=True)
    blocks = parse_cmu_blocks(parse_data(sim.read(timeout_s=60), 1), layout)
    v = np.array([b.source.value for b in blocks if b.source is not None])
    c = np.array([b.table_values()["Cp"][0] for b in blocks])
    vc = FecapDevice("cv", FecapParams.model_validate(load_scenario("fecap_basic").models["cv"].params)).vc
    assert v[int(np.argmax(c[:121]))] == pytest.approx(vc, abs=0.05)  # rising branch: +Vc
    assert v[121 + int(np.argmax(c[121:]))] == pytest.approx(-vc, abs=0.05)  # falling branch: -Vc
