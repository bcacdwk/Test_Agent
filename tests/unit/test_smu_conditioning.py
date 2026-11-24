"""SMU conditioning (WP7.7; blueprint v2 1.2 "ranging RI/RV/RM; ADC AAD/AIT/AV/AZ; FL/SSR", 2.5 smu builders): the
driver operations ``set_filter``/``set_series_resistor`` check the channel allowlist (they change the output path),
``set_adc_zero``/``set_averaging``/``set_range_mode``/``clear_sweep_sources`` change no output, and the simulator keeps
the settings with the manual's parameter domains (``tests/sim/test_smu_conditioning.py``; golden strings:
``tests/fixtures/flex/smu/builders.yaml``, checked by ``test_driver_spot_asu.py``)."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from tests.unit.driver_helpers import SpyTransport

pytestmark = pytest.mark.smu

ENVELOPE = CompiledEnvelope(channels={3: ChannelEnvelope(role="gate", max_abs_v=2.0, max_abs_i=1e-3),
                                      4: ChannelEnvelope(role="drain", max_abs_v=1.0, max_abs_i=1e-3)})


def _driver(*, guard: bool = True) -> tuple[B1500Driver, SpyTransport]:
    spy = SpyTransport()
    return B1500Driver(spy, OutputGuard(ENVELOPE) if guard else None), spy  # type: ignore[arg-type]


def test_filter_and_series_resistor_need_the_channel_allowlist() -> None:
    driver, spy = _driver()
    driver.set_filter(True, [3, 4])
    driver.set_series_resistor(3, True)
    assert spy.sent == ["FL 1,3,4", "SSR 3,1"]
    with pytest.raises(EnvelopeViolation, match="not in the plan allowlist"):
        driver.set_series_resistor(5, True)
    with pytest.raises(EnvelopeViolation, match="not in the plan allowlist"):
        driver.set_filter(False, [3, 5])
    with pytest.raises(ValueError, match="needs the channels"):
        driver.set_filter(True, [])
    assert spy.sent == ["FL 1,3,4", "SSR 3,1"]  # nothing refused reached the transport
    unguarded, spy2 = _driver(guard=False)
    with pytest.raises(EnvelopeViolation) as caught:
        unguarded.set_series_resistor(3, False)
    assert caught.value.reason == "no_guard" and spy2.sent == []


def test_adc_and_ranging_settings_need_no_guard() -> None:
    driver, spy = _driver(guard=False)
    driver.set_adc_zero(True)
    driver.set_averaging(-2)
    driver.set_averaging(4, 1)
    driver.set_range_mode(3, 3, 60)
    driver.clear_sweep_sources()
    assert spy.sent == ["AZ 1", "AV -2", "AV 4,1", "RM 3,3,60", "WNCC"]
