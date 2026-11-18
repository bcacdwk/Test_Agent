"""Simulator support of asynchronous runs (blueprint v2 4.1, 4.3; WP5.6): virtual time ``timing: instant|scaled(f)``,
the auto-calibration switch ``CM`` and its read-back ``*LRN? 31`` (PG p379 (4-61), p448 (4-130)), ``*LRN? 0``, and
the faults ``run_interrupt(segment)`` and ``abort_ignored``."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from b1500_test_agent.driver.discovery import parse_auto_calibration, parse_lrn_settings
from b1500_test_agent.models.sim import AbortIgnored, RunInterrupt
from b1500_test_agent.models.station import SIM_SCALED_DEFAULT, SimScenario, timing_scale
from b1500_test_agent.transport.sim import SimTransport, SimulatedInterrupt
from b1500_test_agent.transport.sim.instrument import SCALED_TIME_FACTOR
from tests.sim.helpers import errx_all, load_scenario, noiseless, on_test_mainframe, run

SWEEP = ("CN 1,3", "DV 3,0,0.1,1E-3", "MM 2,3", "AIT 0,2,1", "WV 1,1,0,0,1,11,1E-3", "WT 0,1")
"""An 11-step sweep with 1 s delay per step (~11 s of virtual time)."""


def scenario(**changes: object) -> SimScenario:
    return noiseless(on_test_mainframe(load_scenario("nmos_basic"))).model_copy(update=changes)


# -- timing ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("timing", "scale"), [("instant", 0.0), ("scaled", SIM_SCALED_DEFAULT),
                                               ("scaled(0.5)", 0.5), ("scaled(1e-3)", 1e-3), (" scaled(2) ", 2.0)])
def test_timing_values(timing: str, scale: float) -> None:
    assert timing_scale(timing) == pytest.approx(scale)
    data = load_scenario("nmos_basic").model_dump()
    assert SimScenario.model_validate({**data, "timing": timing}).time_scale == pytest.approx(scale)
    assert SCALED_TIME_FACTOR == SIM_SCALED_DEFAULT


@pytest.mark.parametrize("timing", ["fast", "scaled()", "scaled(0)", "scaled(11)", "scaled(-1)", "instant(1)"])
def test_bad_timing_is_refused(timing: str) -> None:
    data = load_scenario("nmos_basic").model_dump()
    with pytest.raises(ValidationError):
        SimScenario.model_validate({**data, "timing": timing})


def test_scaled_timing_sleeps_f_per_virtual_second_and_instant_never(tmp_path: Path) -> None:
    for timing, low, high in (("instant", 0.0, 0.2), ("scaled(0.03)", 0.3, 1.5)):
        sim = SimTransport(scenario(timing=timing), state_file=None)
        sim.open()
        run(sim, *SWEEP)
        t0 = time.monotonic()
        sim.write("XE")
        sim.read(timeout_s=60)
        wall = time.monotonic() - t0
        assert sim.instrument.clock > 10.0  # ~11 s of virtual time passed
        assert low <= wall <= high, (timing, wall)


# -- CM and *LRN? ------------------------------------------------------------------------------------------------------


def test_cm_sets_the_auto_calibration_switch_and_lrn_31_reports_it(make_sim) -> None:
    sim = make_sim()
    assert parse_auto_calibration(sim.query("*LRN? 31")) is False  # initial setting OFF (PG p379)
    sim.write("CM 1")
    answer = sim.query("*LRN? 31")
    assert parse_auto_calibration(answer) is True
    settings = parse_lrn_settings(answer)
    assert list(settings)[:4] == ["TM", "AV", "CM", "FMT"] and settings["FMT"] == ["1", "0"]
    run(sim, "MM 2,3", "FMT 1,1")
    assert parse_lrn_settings(sim.query("*LRN? 31"))["MM"] == ["2", "3"]
    sim.write("CM 0")
    assert parse_auto_calibration(sim.query("*LRN? 31")) is False
    assert errx_all(sim) == []


def test_cm_rejects_other_modes_and_rst_turns_it_off(make_sim) -> None:
    sim = make_sim(scenario(auto_calibration=True))
    assert sim.instrument.state.auto_calibration is True
    sim.write("CM 2")
    assert errx_all(sim) == [120]
    sim.write("*RST")
    assert parse_auto_calibration(sim.query("*LRN? 31")) is False
    sim.write("CM 1")
    sim.device_clear()
    assert sim.instrument.state.auto_calibration is False


def test_auto_calibration_persists_across_processes(tmp_path: Path) -> None:
    state = tmp_path / "sim.state.json"
    first = SimTransport(scenario(), state_file=state)
    first.open()
    first.write("CM 1")
    first.save_state()
    second = SimTransport(scenario(), state_file=state)
    second.open()
    assert parse_auto_calibration(second.query("*LRN? 31")) is True


def test_lrn_0_lists_the_output_switches_and_other_types_are_not_simulated(make_sim) -> None:
    sim = make_sim()
    assert sim.query("*LRN? 0") == "CL"
    sim.write("CN 1,3")
    assert sim.query("*LRN? 0") == "CN1,3"
    sim.write("*LRN? 33")
    [record] = [r for r in sim.instrument.command_log if r.line == "*LRN? 33"]
    assert record.outcome == "unsupported"
    sim.write("*LRN? 111")
    assert errx_all(sim) == [100, 120]


# -- faults ------------------------------------------------------------------------------------------------------------


def test_run_interrupt_raises_at_the_read_of_its_segment(make_sim) -> None:
    sim = make_sim(faults=[RunInterrupt(segment=1)])
    run(sim, *SWEEP[:-1], "WT 0,0")
    sim.write("XE")
    sim.read(timeout_s=60)  # measurement 0
    sim.write("XE")
    with pytest.raises(SimulatedInterrupt):
        sim.read(timeout_s=60)  # measurement 1: interrupted, still pending
    assert sim.instrument.measurement_pending
    sim.write("AB")
    assert not sim.instrument.measurement_pending
    sim.write("XE")
    assert sim.read(timeout_s=60)  # one-shot


def test_abort_ignored_keeps_the_measurement_running(make_sim) -> None:
    sim = make_sim(faults=[AbortIgnored(nth=1, count=1)])
    run(sim, *SWEEP)
    sim.write("XE")
    sim.write("AB")  # ignored: the 11 s sweep goes on
    assert sim.instrument.measurement_pending
    sim.write("AB")  # the second AB works again (count 1)
    assert not sim.instrument.measurement_pending


def test_abort_ignored_without_count_ignores_every_ab(make_sim) -> None:
    sim = make_sim(faults=[AbortIgnored()])
    run(sim, *SWEEP)
    sim.write("XE")
    for _ in range(3):
        sim.write("AB")
    assert sim.instrument.measurement_pending
    sim.device_clear()  # the recovery path: a device clear still ends it
    assert not sim.instrument.measurement_pending
    sim.instrument.assert_safe()
