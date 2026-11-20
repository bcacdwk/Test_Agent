"""MFCMU and SCUU driver operations (``driver/ops/cmu.py``, ``driver/ops/switch.py``; blueprint v2 2.5, WP8.1):
every source-like call passes ``OutputGuard.check_ac``/``check_route`` before anything is written, the setups write
the manual's command sequences, the measurement reads parse into ``CmuReading``s, correction and phase compensation
work end to end against the simulator, and the cleanup zeroing reaches exactly the MFCMUs that are still on."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.driver.b1500 import (
    AcLevelSweepSetup,
    B1500Driver,
    CfSweepSetup,
    CmuSignal,
    CmuSweepTiming,
    CtSamplingSetup,
    CvSweepSetup,
    PulsedCvSweepSetup,
    PulsedSpotCSetup,
)
from b1500_test_agent.driver.errors import DriverError, DriverStateError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops.switch import scuu_geometry, scuu_path
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.routing import Route, SwitchPort, SwitchSpec
from b1500_test_agent.models.sim import CmuOverload
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.driver_helpers import SpyTransport

CMU = 7
AC = AcEnvelope(max_vrms=0.05, max_dc_v=3.0, f_min_hz=1e3, f_max_hz=1e6)
ENVELOPE = CompiledEnvelope(channels={CMU: ChannelEnvelope(role="a", max_abs_v=3.0, max_abs_i=1e-3,
                                                           function="cmu_high", ac=AC)})
SCUU = SwitchSpec(id="SCUU1", kind="scuu", present=True, ports={
    "OUT1": SwitchPort(index=6, inputs={"smu": 6, "cmu": 7}), "OUT2": SwitchPort(index=5, inputs={"smu": 5, "cmu": 7}),
}, rest="smu")


def sim_driver(guard: bool = True, faults: tuple = ()) -> tuple[B1500Driver, SimTransport]:
    transport = SimTransport(noiseless(load_scenario("capacitor_100p")), state_file=None, faults=faults)
    transport.open()
    driver = B1500Driver(transport, OutputGuard(ENVELOPE) if guard else None)
    driver.enable([CMU])
    return driver, transport


def sent(transport: SimTransport) -> list[str]:
    return [r.command for r in transport.instrument.command_log]


# -- guard --------------------------------------------------------------------------------------------------------


def test_sources_refuse_without_a_guard() -> None:
    transport = SimTransport(noiseless(load_scenario("capacitor_100p")), state_file=None)
    transport.open()
    driver = B1500Driver(transport)
    with pytest.raises(EnvelopeViolation) as info:
        driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03))
    assert info.value.reason == "no_guard" and transport.instrument.command_log == []


@pytest.mark.parametrize(("call", "reason"), [
    (lambda d: d.apply_cmu_signal(CMU, CmuSignal(freq_hz=2e6, ac_vrms=0.03)), "frequency_outside_envelope"),
    (lambda d: d.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.06)), "ac_exceeds_envelope"),
    (lambda d: d.set_cmu_dc(CMU, 3.5), "dc_exceeds_envelope"),
    (lambda d: d.set_cmu_ac(CMU, 0.03), None),  # at the CN frequency 1 kHz: inside
    (lambda d: d.cv_sweep(CvSweepSetup(channel=CMU, start=-1, stop=4, points=11, freq_hz=1e5, ac_vrms=0.03)),
     "dc_exceeds_envelope"),
    (lambda d: d.cf_sweep(CfSweepSetup(channel=CMU, start_hz=1e3, stop_hz=2e6, points=5, ac_vrms=0.03)),
     "frequency_outside_envelope"),
    (lambda d: d.ac_level_sweep(AcLevelSweepSetup(channel=CMU, start_vrms=0.01, stop_vrms=0.1, points=5,
                                                  freq_hz=1e5)), "ac_exceeds_envelope"),
    (lambda d: d.pulsed_spot_c(PulsedSpotCSetup(channel=CMU, base=0, pulse=5, freq_hz=1e5, ac_vrms=0.03,
                                                width_s=0.01)), "dc_exceeds_envelope"),
    (lambda d: d.pulsed_cv_sweep(PulsedCvSweepSetup(channel=CMU, base=-4, start=-1, stop=1, points=3, freq_hz=1e5,
                                                    ac_vrms=0.03, width_s=0.01)), "dc_exceeds_envelope"),
    (lambda d: d.ct_sampling(CtSamplingSetup(channel=CMU, base=0, bias=1, post=-3.1, freq_hz=1e5, ac_vrms=0.03)),
     "dc_exceeds_envelope"),
    (lambda d: d.apply_cmu_signal(3, CmuSignal()), "channel_not_allowed"),
])
def test_every_source_passes_check_ac_before_writing(call, reason: str | None) -> None:
    driver, transport = sim_driver()
    before = len(transport.instrument.command_log)
    if reason is None:
        call(driver)
        return
    with pytest.raises(EnvelopeViolation) as info:
        call(driver)
    assert info.value.reason == reason
    assert len(transport.instrument.command_log) == before  # nothing was sent


def test_setups_write_the_manual_sequences() -> None:
    spy = SpyTransport()
    driver = B1500Driver(spy, OutputGuard(ENVELOPE))  # type: ignore[arg-type]
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03, dc_v=-1))
    driver.cv_sweep(CvSweepSetup(channel=CMU, start=-2, stop=2, points=21, freq_hz=1e5, ac_vrms=0.03,
                                 timing=CmuSweepTiming(hold_s=0.5, delay_s=0.01), post="stop", measure_smu=(3,)))
    driver.cf_sweep(CfSweepSetup(channel=CMU, start_hz=1e3, stop_hz=1e6, points=31, sweep="log", ac_vrms=0.03,
                                 dc_v=1.0))
    driver.ac_level_sweep(AcLevelSweepSetup(channel=CMU, start_vrms=0.01, stop_vrms=0.05, points=5, freq_hz=1e5))
    driver.pulsed_spot_c(PulsedSpotCSetup(channel=CMU, base=0, pulse=1, freq_hz=1e5, ac_vrms=0.03, width_s=0.01))
    driver.pulsed_cv_sweep(PulsedCvSweepSetup(channel=CMU, base=0, start=-1, stop=1, points=11, freq_hz=1e5,
                                              ac_vrms=0.03, width_s=0.01, period_s=0.02, double=True))
    driver.ct_sampling(CtSamplingSetup(channel=CMU, base=0, bias=1, post=0, freq_hz=1e5, ac_vrms=0.03,
                                       interval_s=0.01, number=100))
    assert spy.sent == [
        "FC 7,100000", "ACV 7,0.03", "DCV 7,-1",
        "MM 18,7,3", "FC 7,100000", "ACV 7,0.03", "WTDCV 0.5,0.01", "WMDCV 2,2", "WDCV 7,1,-2,2,21",
        "MM 22,7", "FC 7,1000", "ACV 7,0.03", "DCV 7,1", "WTFC 0,0", "WMFC 2,1", "WFC 7,2,1000,1000000,31",
        "MM 23,7", "FC 7,100000", "DCV 7,0", "WTACV 0,0", "WMACV 2,1", "WACV 7,1,0.01,0.05,5",
        "MM 19,7", "FC 7,100000", "ACV 7,0.03", "PTDCV 0,0.01,0", "PDCV 7,0,1",
        "MM 20,7", "FC 7,100000", "ACV 7,0.03", "WMDCV 2,1", "PTDCV 0,0.01,0.02", "PWDCV 7,3,0,-1,1,11",
        "MM 26,7", "FC 7,100000", "ACV 7,0.03", "MTDCV 0,0.01,100", "MDCV 7,0,1,0",
    ]
    assert driver.cmu_channels_in_use == [CMU]


def test_setup_models_check_the_manual_domains() -> None:
    with pytest.raises(ValidationError):
        CvSweepSetup(channel=CMU, start=-1, stop=1, points=1002, freq_hz=1e5, ac_vrms=0.03)
    with pytest.raises(ValidationError):
        CvSweepSetup(channel=CMU, start=-1, stop=1, points=3, freq_hz=1e5, ac_vrms=0.03, sweep="log")
    with pytest.raises(ValidationError):
        CmuSignal(freq_hz=500.0)
    with pytest.raises(ValidationError):
        CtSamplingSetup(channel=CMU, base=0, bias=1, freq_hz=1e5, ac_vrms=0.03, interval_s=0.001)


# -- measurement through the simulator ----------------------------------------------------------------------------


def test_spot_c_reads_the_uncorrected_standard() -> None:
    driver, _ = sim_driver()
    driver.set_impedance_model(100)
    driver.set_cmu_monitor(True)
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03, dc_v=0.5))
    driver.spot_c(CMU)
    block = driver.measure_cmu(driver.cmu_layout(17), steps=1, timeout_s=5)
    [reading] = block.readings
    assert reading.table_values()["Cp"][0] == pytest.approx(100.3e-12, rel=1e-4)
    assert (reading.osc.value, reading.dc.value) == (0.03, 0.5)  # type: ignore[union-attr]
    assert block.raw.complete


def test_cv_sweep_with_source_data_and_post() -> None:
    driver, transport = sim_driver()
    driver.set_format(1, 1)
    setup = CvSweepSetup(channel=CMU, start=-2, stop=2, points=5, freq_hz=1e5, ac_vrms=0.03, double=True)
    driver.cv_sweep(setup)
    block = driver.measure_cmu(driver.cmu_layout(18), steps=setup.steps, timeout_s=5)
    assert [r.source.value for r in block.readings] == [-2, -1, 0, 1, 2, 2, 1, 0, -1, -2]  # type: ignore[union-attr]
    assert transport.instrument.outputs()[CMU].voltage == -2  # WMDCV post 1 = start


def test_an_aborted_sweep_returns_its_readings_before_the_abort() -> None:
    driver, _ = sim_driver(faults=(CmuOverload(at_step=2, condition="unbalance"),))
    setup = CvSweepSetup(channel=CMU, start=-2, stop=2, points=5, freq_hz=1e5, ac_vrms=0.03)
    driver.cv_sweep(setup)
    block = driver.measure_cmu(driver.cmu_layout(18), steps=5, timeout_s=5)
    assert [r.status for r in block.readings] == ["N", "N", "U", "V", "V"]


def test_correction_and_phase_compensation_end_to_end() -> None:
    driver, transport = sim_driver()
    driver.set_phase_compensation_mode(CMU, 1)
    assert driver.measure_phase_compensation(CMU, timeout_s=60) == 0
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03))
    with pytest.raises(DriverStateError, match="frequency list"):
        driver.measure_correction(CMU, "open")
    driver.set_correction_frequencies(CMU, [1e5])
    driver.set_correction_standard(CMU, "open", 0.0, 0.0)
    assert driver.measure_correction(CMU, "open") == 0
    assert driver.measure_correction(CMU, "short") == 0
    driver.set_correction(CMU, "open", True)
    driver.set_correction(CMU, "short", True)
    live = driver.correction_state(CMU)
    assert live.corr_state == {"open": True, "short": True, "load": False} and live.phase is True
    driver.spot_c(CMU)
    [reading] = driver.measure_cmu(driver.cmu_layout(17), steps=1, timeout_s=5).readings
    assert reading.table_values()["Cp"][0] == pytest.approx(100e-12, rel=1e-3)
    assert "DCORR 7,1,100,0,0" in sent(transport) and "ADJ? 7,1" in sent(transport)


def test_a_correction_frequency_outside_the_envelope_is_refused() -> None:
    driver, transport = sim_driver()
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03))
    driver.set_correction_frequencies(CMU, defaults=True)  # the defaults reach 5 MHz, the envelope 1 MHz
    before = len(transport.instrument.command_log)
    with pytest.raises(EnvelopeViolation, match="Hz is outside"):
        driver.measure_correction(CMU, "open")
    assert len(transport.instrument.command_log) == before


def test_phase_compensation_needs_the_channel_in_the_allowlist() -> None:
    driver, _ = sim_driver()
    with pytest.raises(EnvelopeViolation):
        driver.measure_phase_compensation(3)


# -- cleanup zeroing ----------------------------------------------------------------------------------------------


def test_zero_cmu_reaches_the_mfcmus_still_on() -> None:
    driver, transport = sim_driver()
    assert driver.zero_cmu() == []  # nothing driven: no I/O at all
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03, dc_v=1))
    log_start = len(transport.instrument.command_log)
    assert driver.zero_cmu() == [CMU]
    assert sent(transport)[log_start:] == ["LOP?", "DCV 7,0", "ACV 7,0"]
    state = transport.instrument.outputs()[CMU]
    assert (state.voltage, state.ac_vrms, state.output_on) == (0.0, 0.0, True)
    assert driver.cmu_channels_in_use == []
    driver.set_cmu_ac(CMU, 0.02)
    driver.disconnect([CMU])
    log_start = len(transport.instrument.command_log)
    assert driver.zero_cmu() == []  # the switch is off: LOP? 00, no DCV/ACV (they need it on)
    assert sent(transport)[log_start:] == ["LOP?"] and transport.instrument.errors == []


# -- SCUU ---------------------------------------------------------------------------------------------------------


def test_scuu_geometry_and_paths() -> None:
    assert scuu_geometry(SCUU) == (7, {"OUT1": 0, "OUT2": 1})
    assert [scuu_path(p) for p in (("smu", "open"), ("open", "smu"), ("smu", "smu"), ("cmu", "cmu"))] == [1, 2, 3, 4]
    with pytest.raises(ValueError):
        scuu_path(("open", "open"))
    with pytest.raises(ValueError):
        scuu_path(("cmu", "smu"))
    unknown = SCUU.model_copy(update={"ports": {"OUT1": SwitchPort(index=6, inputs={"smu": 6, "cmu": None})}})
    with pytest.raises(DriverError, match="MFCMU input"):
        scuu_geometry(unknown)
    selector = SwitchSpec(id="SEL1", kind="selector_16440a", present=True, ports={"OUT1": SwitchPort(index=0)})
    with pytest.raises(DriverError, match="not an SCUU"):
        scuu_geometry(selector)


def test_scuu_route_is_guarded() -> None:
    to_cmu = [Route(switch="SCUU1", output="OUT1", state="cmu"), Route(switch="SCUU1", output="OUT2", state="cmu")]
    envelope = ENVELOPE.model_copy(update={"routes": frozenset(to_cmu)})
    spy = SpyTransport(answers={"*LRN? 81": "SSP7,4"})
    driver = B1500Driver(spy, OutputGuard(envelope, switches=[SCUU]))  # type: ignore[arg-type]
    assert driver.scuu_route(SCUU, to_cmu) == 4
    back = [Route(switch="SCUU1", output="OUT1", state="smu"), Route(switch="SCUU1", output="OUT2", state="smu")]
    assert driver.scuu_route(SCUU, back) == 3  # the rest state is always allowed
    with pytest.raises(EnvelopeViolation):
        driver.scuu_route(SCUU, [Route(switch="SCUU1", output="OUT1", state="smu")])  # OUT2 open: not planned
    assert spy.sent == ["SSP 7,4", "SSP 7,3"]
    assert driver.scuu_path(7) == 4
    with pytest.raises(ValueError):
        driver.scuu_route(SCUU, [Route(switch="SCUU1", output="OUT9", state="cmu")])
    driver.set_scuu_indicator(7, False)
    assert spy.sent[-1] == "SSL 7,0"
