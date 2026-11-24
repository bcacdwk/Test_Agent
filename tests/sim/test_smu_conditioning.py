"""Simulator side of the SMU conditioning commands (WP7.7; PG ``FL`` p436 (4-118), ``SSR`` p521 (4-203), ``RM``
p501-502 (4-183), ``AZ`` p363 (4-45)): settings kept per channel and reset by ``*RST``, parameter domains as error
120 / 121, the ADC zero function doubling a high-resolution measurement."""

from __future__ import annotations

import pytest

from tests.sim.helpers import errx_all, resistor_scenario, run

pytestmark = pytest.mark.smu


def test_simulator_keeps_the_conditioning_settings(make_sim) -> None:
    sim = make_sim(resistor_scenario())
    run(sim, "FL 1,1,3", "SSR 3,1", "RM 1,2", "RM 3,3,60", "AZ 1")
    instrument = sim.instrument
    assert instrument._filter == {1: True, 3: True} and instrument._series_r == {3: True}
    assert instrument._rm == {1: (2, 50), 3: (3, 60)} and instrument._adc_zero
    run(sim, "FL 0")  # no channel: every SMU
    assert set(instrument._filter.values()) == {False} and len(instrument._filter) >= 2
    assert errx_all(sim) == []
    run(sim, "*RST")
    assert instrument._filter == {} and instrument._series_r == {} and instrument._rm == {}
    assert not instrument._adc_zero


@pytest.mark.parametrize(("command", "code"), [
    ("FL 2", 120), ("SSR 1,2", 120), ("RM 1,4", 120), ("RM 1,1,50", 120), ("RM 1,2,10", 120), ("AZ 2", 120),
    ("SSR 9,1", 153),  # no module in slot 9 of the test mainframe
])
def test_simulator_refuses_values_outside_the_manual_domain(make_sim, command: str, code: int) -> None:
    sim = make_sim(resistor_scenario())
    sim.write(command)
    assert errx_all(sim) == [code]


def test_adc_zero_doubles_a_high_resolution_measurement(make_sim) -> None:
    sim = make_sim(resistor_scenario())
    run(sim, "AAD 1,1", "AIT 1,1,10")
    without = sim.instrument.integration_time(1)
    run(sim, "AZ 1")
    assert sim.instrument.integration_time(1) == pytest.approx(2 * without)
    run(sim, "AAD 1,0")
    run(sim, "AZ 0")
    assert sim.instrument.integration_time(1) == sim.instrument.integration_time(3)  # high-speed ADC: no effect
