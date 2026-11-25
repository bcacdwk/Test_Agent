"""The MFCMU driver path through the real ``VisaTransport`` (blueprint v2 7.1 visa-loop; WP8.1): phase compensation
(a 30 s query), open/short correction, an FMT 5 C-V sweep read as one comma-terminated message, the cleanup zeroing
by ``LOP?`` and the read-back queries. The recipes that use it (WP8.2/8.3) add their visa-loop cases to
``helpers.MEASUREMENT_CASES``."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver, CmuSignal, CvSweepSetup
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.station import VisaSettings
from b1500_test_agent.transport.visa import VisaTransport
from tests.sim.helpers import load_scenario, noiseless
from tests.visa_loop.loop import DEFAULT_RESOURCE, LoopBus

pytestmark = pytest.mark.cmu

CMU = 7
ENVELOPE = CompiledEnvelope(channels={CMU: ChannelEnvelope(
    role="a", max_abs_v=2.0, max_abs_i=1e-3, function="cmu_high",
    ac=AcEnvelope(max_vrms=0.05, max_dc_v=2.0, f_min_hz=1e4, f_max_hz=1e6))})


@pytest.fixture
def driver(tmp_path: Path) -> B1500Driver:
    bus = LoopBus(tmp_path / "bus", noiseless(load_scenario("capacitor_100p")))
    settings = VisaSettings(resource=DEFAULT_RESOURCE, timeout_ms=2000, lock_timeout_ms=200)
    transport = VisaTransport(settings, rm_factory=bus.manager)
    transport.open()
    transport.lock()
    return B1500Driver(transport, OutputGuard(ENVELOPE))


def test_corrected_cv_sweep_over_visa(driver: B1500Driver) -> None:
    driver.enable([CMU])
    driver.set_phase_compensation_mode(CMU, 1)
    assert driver.measure_phase_compensation(CMU, timeout_s=60) == 0
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03))
    driver.set_correction_frequencies(CMU, [1e5])
    driver.set_correction_standard(CMU, "open", 0.0, 0.0)
    assert [driver.measure_correction(CMU, corr) for corr in ("open", "short")] == [0, 0]
    driver.set_correction(CMU, "open", True)
    driver.set_correction(CMU, "short", True)
    assert driver.correction_state(CMU).phase is True
    driver.set_format(5, 1)
    driver.set_cmu_monitor(True)
    setup = CvSweepSetup(channel=CMU, start=-1, stop=1, points=101, freq_hz=1e5, ac_vrms=0.03)
    driver.cv_sweep(setup)
    block = driver.measure_cmu(driver.cmu_layout(18), steps=setup.steps, timeout_s=30)
    assert block.raw.raw.endswith(",") and block.raw.complete  # FMT 5: every element comma-terminated
    assert len(block.readings) == 101
    assert all(r.table_values()["Cp"][0] == pytest.approx(100e-12, rel=1e-3) for r in block.readings)
    assert [r.source.value for r in block.readings][::50] == [-1.0, 0.0, 1.0]  # type: ignore[union-attr]
    assert driver.zero_cmu() == [CMU]
    driver.zero()
    driver.disconnect()
    assert all(not out.output_on for out in driver.output_state().values())
    assert driver.phase_compensation_mode(CMU) == 1 and driver.errors() == []
