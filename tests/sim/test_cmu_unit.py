"""MFCMU unit of the simulator (``transport/sim/units/cmu.py`` + ``cmu_engine.py``; blueprint v2 4.1-4.3, WP8.1):
the fixture parasitics (an uncorrected 100 pF reads +0.3 pF; phase compensation and open/short correction recover
it within 0.1 %), the correction state machine (``*RST`` switches the corrections off and the compensation mode to
auto, data stay; ``CORRL``/``CLCORR``/``DCORR`` clear them; persisted across processes), the measurement modes
17-26 (timing, sources, monitors, post values, automatic abort), the ``cmu_overload``/``cmu_correction_lost`` faults
and the manual's error codes."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import pytest

from b1500_test_agent.models.sim import CmuCorrectionLost, CmuOverload, MoscapParams
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from tests.sim.helpers import errx_all, load_scenario, noiseless, run, scenario_with

CMU = 7
F = 1.0e5


def cap() -> SimScenario:
    """The committed ``capacitor_100p`` scenario without noise (100 pF behind the default fixture)."""
    return noiseless(load_scenario("capacitor_100p"))


def moscap(**params: float) -> SimScenario:
    return scenario_with({"mos": {"model": "moscap", "params": {"tox_nm": 5.0, "nsub_cm3": 1e17, **params}}},
                         {"mos": {"gate": "7H", "bulk": "7L"}})


def elements(text: str) -> list[str]:
    return text.split(",") if text else []


def spot(sim: SimTransport, f: float = F, *, imp: int = 100) -> tuple[float, float, str]:
    run(sim, f"FC {CMU},{f}", f"IMP {imp}", f"MM 17,{CMU}", "XE")
    first, second = elements(sim.read())
    return float(first[3:]), float(second[3:]), first[0] + second[0]


def corrected(sim: SimTransport, freqs: tuple[float, ...] = (F,), *, adjust: bool = True) -> None:
    """Phase compensation (optional) and open + short correction at ``freqs``, as the human-guided recipe does."""
    if adjust:
        run(sim, f"ADJ {CMU},1")
        assert sim.query(f"ADJ? {CMU},1", timeout_s=60) == "0"
    run(sim, f"ACV {CMU},0.03", f"CLCORR {CMU},1", *(f"CORRL {CMU},{f}" for f in freqs), f"DCORR {CMU},1,100,0,0")
    assert sim.query(f"CORR? {CMU},1") == "0"
    assert sim.query(f"CORR? {CMU},2") == "0"
    run(sim, f"CORRST {CMU},1,1", f"CORRST {CMU},2,1")


@pytest.fixture
def cap_sim(make_sim: Callable[..., SimTransport]) -> SimTransport:
    sim = make_sim(cap())
    run(sim, f"CN {CMU}", f"ACV {CMU},0.03")
    return sim


# -- fixture parasitics and corrections -------------------------------------------------------------------------------


def test_uncorrected_100pf_reads_plus_0_3pf(cap_sim: SimTransport) -> None:
    cp, g, status = spot(cap_sim)
    assert status == "NN"
    assert cp - 100e-12 == pytest.approx(0.3e-12, abs=0.005e-12)
    assert g > 0  # the cable phase error turns into a false conductance until phase compensation


@pytest.mark.parametrize("f", [1e3, 1e4, 1e5, 1e6, 5e6])
def test_phase_compensation_and_open_short_correction_recover_100pf(cap_sim: SimTransport, f: float) -> None:
    corrected(cap_sim, (f,))
    cp, g, _ = spot(cap_sim, f)
    assert cp == pytest.approx(100e-12, rel=1e-3)  # blueprint 4.2: corrected +-0.1 %
    assert abs(g) < 1e-6 * 2 * math.pi * f * 100e-12


def test_open_short_without_phase_compensation_leave_a_false_conductance(cap_sim: SimTransport) -> None:
    corrected(cap_sim, (2e6,), adjust=False)
    cp, g, _ = spot(cap_sim, 2e6)
    assert cp == pytest.approx(100e-12, rel=1e-3)
    assert g / (2 * math.pi * 2e6 * 100e-12) == pytest.approx(math.sin(math.radians(2.0)), rel=1e-3)


def test_load_correction_also_removes_the_phase_error(cap_sim: SimTransport) -> None:
    corrected(cap_sim, (2e6,), adjust=False)
    run(cap_sim, f"DCORR {CMU},3,400,0,1000")  # a 1 kOhm load standard; DCORR clears the data
    for corr in (1, 2, 3):
        assert cap_sim.query(f"CORR? {CMU},{corr}") == "0"
    run(cap_sim, f"CORRST {CMU},1,1", f"CORRST {CMU},2,1", f"CORRST {CMU},3,1")
    cp, g, _ = spot(cap_sim, 2e6)
    assert cp == pytest.approx(100e-12, rel=1e-6) and abs(g) < 1e-9


def test_corrections_apply_only_at_listed_frequencies(cap_sim: SimTransport) -> None:
    corrected(cap_sim, (F,))
    assert spot(cap_sim, 2 * F)[0] - 100e-12 == pytest.approx(0.3e-12, abs=0.01e-12)


def test_rst_clears_corrections_in_sim(cap_sim: SimTransport) -> None:
    """``*RST``: every correction function OFF and the compensation mode auto (PG PDF 388, Table 2-13 PDF 180); the
    correction data and the compensation result stay (re-enabling needs no new measurement)."""
    corrected(cap_sim)
    assert [cap_sim.query(f"CORRST? {CMU},{c}") for c in (1, 2, 3)] == ["1", "1", "0"]
    run(cap_sim, "*RST")
    assert [cap_sim.query(f"CORRST? {CMU},{c}") for c in (1, 2, 3)] == ["0", "0", "0"]
    assert cap_sim.query("*LRN? 90") == f"ADJ{CMU},0" and cap_sim.query(f"ADJ? {CMU},0") == "0"
    run(cap_sim, f"CN {CMU}", f"ACV {CMU},0.03")
    assert spot(cap_sim)[0] - 100e-12 == pytest.approx(0.3e-12, abs=0.005e-12)  # uncorrected again
    run(cap_sim, f"CORRST {CMU},1,1", f"CORRST {CMU},2,1")  # the data survived *RST
    assert spot(cap_sim)[0] == pytest.approx(100e-12, rel=1e-3)


@pytest.mark.parametrize("command", [f"CORRL {CMU},2000", f"CLCORR {CMU},2", f"DCORR {CMU},1,100,0,0"])
def test_list_and_standard_changes_clear_the_data(cap_sim: SimTransport, command: str) -> None:
    corrected(cap_sim)
    run(cap_sim, command)
    assert cap_sim.query(f"CORRST? {CMU},1") == "0"
    cap_sim.write(f"CORRST {CMU},1,1")
    assert errx_all(cap_sim) == [685]  # CMU correction is not complete (PG PDF 587)


def test_clcorr_2_loads_the_default_frequencies(cap_sim: SimTransport) -> None:
    run(cap_sim, f"CLCORR {CMU},2")
    assert len(cap_sim.instrument.state.cmu[CMU].freqs) == 23


def test_corrdt_sets_data_directly(cap_sim: SimTransport) -> None:
    run(cap_sim, f"CORRDT {CMU},100000,0,0,0,0,0,0", f"CORRST {CMU},2,1")
    assert cap_sim.instrument.state.cmu[CMU].freqs == [1e5]
    assert spot(cap_sim)[0] - 100e-12 == pytest.approx(0.3e-12, abs=0.005e-12)  # a zero short changes nothing


def test_corrections_persist_across_processes(make_sim: Callable[..., SimTransport], tmp_path: Path) -> None:
    state_file = sim_state_file(tmp_path, "capacitor_100p")
    first = make_sim(cap(), state_file=state_file)
    run(first, f"CN {CMU}")
    corrected(first)
    first.save_state()
    second = make_sim(cap(), state_file=state_file)
    assert second.query(f"CORRST? {CMU},1") == "1" and second.query("*LRN? 90") == f"ADJ{CMU},1"
    run(second, f"ACV {CMU},0.03")
    assert spot(second)[0] == pytest.approx(100e-12, rel=1e-3)


def test_cmu_correction_lost_fault(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(cap(), faults=[CmuCorrectionLost(after_cmd="UNT?")])
    run(sim, f"CN {CMU}")
    corrected(sim)
    sim.query("UNT?")
    assert [sim.query(f"CORRST? {CMU},{c}") for c in (1, 2)] == ["0", "0"]
    assert sim.query(f"ADJ? {CMU},0") == "3" and sim.query("*LRN? 90") == f"ADJ{CMU},0"
    sim.write(f"CORRST {CMU},1,1")
    assert errx_all(sim) == [685]


# -- errors -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("commands", "error"), [
    ([f"ADJ? {CMU},1"], 680),  # manual mode first (PG PDF 587)
    ([f"ACV {CMU},0", f"CLCORR {CMU},1", f"CORRL {CMU},1000", f"CORR? {CMU},1"], 684),
    ([f"CLCORR {CMU},1", f"CORRL {CMU},1000", f"CORR? {CMU},3"], 682),  # a load needs its reference
    ([f"DCORR {CMU},1,400,0,0"], 682),
    ([f"MM 18,{CMU}", "XE"], 280),
    ([f"MM 19,{CMU}", "XE"], 281),
    ([f"MM 20,{CMU}", "XE"], 282),
    ([f"PWDCV {CMU},2,0,1,2,3"], 283),
    ([f"FC {CMU},10000", "PTDCV 0,0.01", f"PDCV {CMU},0,1", f"MM 19,{CMU}", "XE"], 284),  # 50 ms up to 10 kHz
    ([f"MM 22,{CMU}", "XE"], 290),
    (["MM 17,3"], 322),  # an SMU is not an MFCMU
    ([f"MM 17,{CMU},3"], 122),
    ([f"FC {CMU},500"], 120),
    ([f"ACV {CMU},0.3"], 120),
    ([f"WDCV {CMU},1,0,1,3,0.01"], 120),  # a compliance is for an SMU sweep source only
    (["IMP 99"], 120),
    (["ACT 0,1024"], 120),
    ([f"RC {CMU},1"], 120),
    (["WTDCV 0,66"], 120),
    (["MTDCV 0,0.005,10"], 120),
])
def test_error_codes(cap_sim: SimTransport, commands: list[str], error: int) -> None:
    for command in commands:
        cap_sim.write(command)
    assert errx_all(cap_sim) == [error]


def test_signal_needs_the_output_switch(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(cap())
    for command in (f"FC {CMU},1E5", f"ACV {CMU},0.01", f"DCV {CMU},1", f"CORR? {CMU},1"):
        sim.write(command)
    assert errx_all(sim) == [200, 200, 200, 200]


def test_dc_bias_beyond_25v_is_the_scuu_smu_form(cap_sim: SimTransport) -> None:
    cap_sim.write(f"DCV {CMU},30")
    assert cap_sim.instrument.command_log[-1].outcome == "unsupported" and errx_all(cap_sim) == [100]


# -- measurement modes ------------------------------------------------------------------------------------------------


def test_imp_modes_convert_one_impedance(cap_sim: SimTransport) -> None:
    run(cap_sim, f"ADJ {CMU},2", f"ACV {CMU},0.03")  # load adaptive: no phase error
    cp = spot(cap_sim, F, imp=100)[0]
    z, theta, _ = spot(cap_sim, F, imp=10)
    assert z == pytest.approx(1 / (2 * math.pi * F * cp), rel=1e-5) and theta == pytest.approx(-math.pi / 2, abs=1e-4)
    _, deg, _ = spot(cap_sim, F, imp=11)
    assert deg == pytest.approx(math.degrees(theta), rel=1e-5)
    cs, rs, _ = spot(cap_sim, F, imp=200)
    assert cs == pytest.approx(cp, rel=1e-3) and abs(rs) < 1.0
    run(cap_sim, f"FC {CMU},{F}", "IMP 400", f"MM 17,{CMU}", "XE")
    ls, _ = elements(cap_sim.read())
    assert ls[:3] == "NGL" and float(ls[3:]) < 0  # a capacitor as Ls-Rs: negative inductance


def test_monitors_time_stamps_and_layout_of_spot_c(cap_sim: SimTransport) -> None:
    run(cap_sim, "TSC 1", "LMN 1", f"DCV {CMU},1.5", f"FC {CMU},{F}", f"MM 17,{CMU}", "XE")
    data = elements(cap_sim.read())
    assert [e[:3] for e in data] == ["NGT", "NGC", "NGY", "NGV", "NGV"]
    assert (float(data[3][3:]), float(data[4][3:])) == (0.03, 1.5)


def test_cv_sweep_sources_monitors_and_post_value(cap_sim: SimTransport) -> None:
    run(cap_sim, "FMT 1,1", "LMN 1", "WTDCV 0.5,0.01", "WMDCV 1,2", f"WDCV {CMU},3,-1,1,3", f"MM 18,{CMU}", "XE")
    data = elements(cap_sim.read())
    assert len(data) == 6 * 5  # double sweep of 3 points: -1 0 1 1 0 -1 (as the SMU's WV double sweep)
    sources = [float(e[3:]) for e in data[4::5]]
    assert sources == [-1, 0, 1, 1, 0, -1] and data[4][0] == "W" and data[-1][0] == "E"
    assert [float(e[3:]) for e in data[3::5]] == sources  # the DC bias monitor follows the sweep
    assert cap_sim.instrument.outputs()[CMU].voltage == 1.0  # post 2 = the stop value (PG PDF 555)
    run(cap_sim, "FMT 1,0", "WMDCV 1,1", f"WDCV {CMU},1,-1,1,3", "XE")
    cap_sim.read()
    assert cap_sim.instrument.outputs()[CMU].voltage == -1.0  # post 1 = the start value


def test_cv_sweep_timing(cap_sim: SimTransport) -> None:
    run(cap_sim, "TSC 1", "ACT 2,1", "WTDCV 1,0.1,0.5", f"WDCV {CMU},1,0,1,3", f"MM 18,{CMU}", "XE")
    stamps = [float(e[3:]) for e in elements(cap_sim.read()) if e[2] == "T"]
    assert stamps == pytest.approx([1.1, 1.7, 2.3])  # hold + delay, then period delay + max(20 ms, Sdelay)


def test_mm18_measures_smu_channels_with_the_cmu_bias(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(scenario_with({"r": {"model": "resistor", "params": {"r_ohm": 1e6}}}, {"r": {"a": "7H", "b": 3}}))
    run(sim, f"CN 3,{CMU}", "DV 3,0,0.5,1E-4", "WDCV 7,1,-1,1,3", f"MM 18,{CMU},3", "XE")
    data = elements(sim.read())
    currents = [float(e[3:]) for e in data[2::3]]
    assert [e[:3] for e in data[:3]] == ["NGC", "NGY", "NCI"]
    assert currents == pytest.approx([(0.5 - v) / 1e6 for v in (-1, 0, 1)])  # SMU3 sees the MFCMU's High side
    assert sim.query("*LRN? 31").endswith(f"MM18,{CMU},3")


def test_cf_and_ac_level_sweeps(cap_sim: SimTransport) -> None:
    run(cap_sim, "FMT 1,1", "LMN 1", "WMFC 1,2", f"WFC {CMU},2,1000,100000,3", f"MM 22,{CMU}", "XE")
    data = elements(cap_sim.read())
    assert [e[:3] for e in data[4::5]] == ["WGF", "WGF", "EGF"]  # Cp, G, Osc, Dc, Source (no time stamp)
    assert [float(e[3:]) for e in data[4::5]] == pytest.approx([1e3, 1e4, 1e5])
    assert cap_sim.instrument.outputs()[CMU].freq_hz == 1e5
    run(cap_sim, "WMACV 1,1", f"WACV {CMU},1,0.01,0.05,5", f"MM 23,{CMU}", "XE")
    data = elements(cap_sim.read())
    assert [float(e[3:]) for e in data[2::5]] == pytest.approx([0.01, 0.02, 0.03, 0.04, 0.05])  # osc monitor
    assert cap_sim.instrument.outputs()[CMU].ac_vrms == 0.01  # post 1 = start


def test_pulsed_modes(cap_sim: SimTransport) -> None:
    run(cap_sim, f"FC {CMU},1E6", f"DCV {CMU},0.2", "PTDCV 0.1,0.01", f"PDCV {CMU},0,2", f"MM 19,{CMU}", "XE")
    assert len(elements(cap_sim.read())) == 2
    assert cap_sim.instrument.outputs()[CMU].voltage == 0.0  # back to the base
    run(cap_sim, "FMT 1,1", "LMN 1", "PTDCV 0,0.01,0.02", f"PWDCV {CMU},1,0,-1,1,3", f"MM 20,{CMU}", "XE")
    data = elements(cap_sim.read())
    assert len(data) == 3 * 3 and [float(e[3:]) for e in data[2::3]] == [-1, 0, 1]  # no monitors in MM 20


def test_ct_sampling_index_and_time(cap_sim: SimTransport) -> None:
    run(cap_sim, "FMT 1,1", "TSC 1", "ACT 0,1", "MTDCV 0.1,0.05,4,0.2", f"MDCV {CMU},0,1,0.5", f"MM 26,{CMU}", "XE")
    data = elements(cap_sim.read())
    assert [float(e[3:]) for e in data[0::4]] == [1, 2, 3, 4]
    assert [float(e[3:]) for e in data[1::4]] == pytest.approx([0.3, 0.35, 0.4, 0.45])  # h_base + h_bias + k*interval
    assert cap_sim.instrument.outputs()[CMU].voltage == 0.5  # post
    run(cap_sim, "ACT 2,1", "MTDCV 0,0.008,3", "XE")  # 20 ms per point > 8 ms interval: the index skips
    assert [float(e[3:]) for e in elements(cap_sim.read())[0::4]] == [1, 4, 7]


def test_fixed_range_saturates_on_a_small_impedance(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(scenario_with({"c": {"model": "capacitor", "params": {"c_f": 1e-8}}}, {"c": {"a": "7H", "b": "7L"}}))
    run(sim, f"CN {CMU}", f"ACV {CMU},0.03")
    assert spot(sim, 1e6)[2] == "NN"
    run(sim, f"RC {CMU},2,10000")
    assert spot(sim, 1e6)[2] == "DD"
    run(sim, f"CL {CMU}", f"CN {CMU}", f"ACV {CMU},0.03")  # CL clears the range (PG PDF 500)
    assert spot(sim, 1e6)[2] == "NN"


@pytest.mark.parametrize(("abort", "expected"), [(1, "NNDNN"), (2, "NNDVV")])
def test_overload_and_automatic_abort(make_sim: Callable[..., SimTransport], abort: int, expected: str) -> None:
    sim = make_sim(cap(), faults=[CmuOverload(at_step=2, condition="saturation")])
    run(sim, f"CN {CMU}", f"ACV {CMU},0.03", f"WMDCV {abort},2", f"WDCV {CMU},1,-2,2,5", f"MM 18,{CMU}", "XE")
    data = elements(sim.read())
    assert "".join(e[0] for e in data[0::2]) == expected
    assert sim.instrument.outputs()[CMU].voltage == (2.0 if abort == 1 else -2.0)  # an abort returns to start


def test_unbalance_and_excess_current(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(cap(), faults=[CmuOverload(at_step=0, condition="unbalance")])
    run(sim, f"CN {CMU}", f"ACV {CMU},0.03")
    assert spot(sim)[2] == "UU"
    sim = make_sim(cap(), faults=[CmuOverload(at_step=1, condition="excess_current")])
    run(sim, f"CN {CMU}", f"ACV {CMU},0.03", f"WDCV {CMU},1,0,1,3", f"MM 18,{CMU}")
    sim.write("XE")
    data = elements(sim.read())
    assert "".join(e[0] for e in data[0::2]) == "NVV"
    assert errx_all(sim) == [320] and not sim.instrument.outputs()[CMU].output_on  # output switch set OFF
    assert sim.query("LOP?").split(",")[6] == "00"


def test_abort_returns_the_sweep_to_its_start(cap_sim: SimTransport) -> None:
    run(cap_sim, "ACT 2,10", f"WDCV {CMU},1,0,2,5", "WMDCV 1,2", f"MM 18,{CMU}", "XE")
    cap_sim.instrument.clock += 0.45  # two of five 200 ms steps done
    run(cap_sim, "AB")
    assert len(elements(cap_sim.read())) == 2 * 2
    assert cap_sim.instrument.outputs()[CMU].voltage == 0.0


def test_fast_cv_sweep_into_inversion_shows_deep_depletion(make_sim: Callable[..., SimTransport]) -> None:
    """``Circuit.advance`` through every step: swept faster than ``tau_inv_s`` the inversion layer cannot form, so
    the capacitance keeps falling below the equilibrium high-frequency minimum (blueprint v2 4.2 ``moscap``)."""
    readings = {}
    for name, delay in (("fast", 0.0), ("slow", 5.0)):
        sim = make_sim(moscap(tau_inv_s=1.0))
        run(sim, f"CN {CMU}", f"FC {CMU},1E5", f"ACV {CMU},0.03", f"DCV {CMU},-2", f"WTDCV 0,{delay}",
            f"WDCV {CMU},1,-2,3,11", f"MM 18,{CMU}", "XE")
        readings[name] = [float(e[3:]) for e in elements(sim.read(timeout_s=200))[0::2]]
    fast, slow = readings["fast"], readings["slow"]
    assert fast[0] == pytest.approx(slow[0], rel=1e-3)  # accumulation: the same either way
    assert fast[-1] < 0.9 * slow[-1]  # deep depletion
    truth = MoscapDevice("truth", MoscapParams(tox_nm=5.0, nsub_cm3=1e17, tau_inv_s=1.0))
    assert slow[0] == pytest.approx(truth.equilibrium_capacitance(-2.0, 1e5), rel=1e-3)  # no fixture: the model
    assert slow[0] == pytest.approx(truth.cox, rel=0.05) and slow[0] < truth.cox


def test_learn_answers_and_lop(cap_sim: SimTransport) -> None:
    run(cap_sim, f"ADJ {CMU},2", "IMP 11", "LMN 1", "ACT 2,3", f"RC {CMU},2,1000")
    assert [cap_sim.query(f"*LRN? {t}") for t in (70, 71, 72, 73, 90)] == [
        "IMP11", "LMN1", "ACT2,3", f"RC{CMU},2,1000", f"ADJ{CMU},2"]
    assert cap_sim.query("LOP?").split(",")[6] == "40"


def test_safe_state_covers_the_mfcmu(cap_sim: SimTransport) -> None:
    run(cap_sim, f"DCV {CMU},1")
    reasons = cap_sim.instrument.unsafe_reasons()
    assert any("AC level 0.03" in r for r in reasons) and any("output 1.0 V" in r for r in reasons)
    run(cap_sim, "DZ")
    assert cap_sim.instrument.outputs()[CMU].voltage == 0.0  # DZ zeroes the MFCMU DC bias (PG PDF 397)
    run(cap_sim, f"ADJ {CMU},0")  # ADJ initializes the MFCMU: AC 0 too
    assert cap_sim.instrument.outputs()[CMU].ac_vrms == 0.0
    run(cap_sim, f"ACV {CMU},0.05", "CL")
    cap_sim.instrument.assert_safe()


def test_dc_bias_reaches_stateful_devices(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(moscap(hysteresis_v=0.3))
    run(sim, f"CN {CMU}", f"DCV {CMU},3")
    assert sim.instrument.state.devices["mos"]["v"] == 3.0  # DCV commits the bias (border traps charge)
    assert sim.instrument.state.devices["mos"]["s_bt"] > 0.5
