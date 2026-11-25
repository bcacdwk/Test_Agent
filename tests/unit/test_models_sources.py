"""``models/sources.py`` (pulse trains, ``pulse_envelope``, WGFMU waveform programs, the source plan) and the v2
additions WP5.4 makes to shared models (``LiveState`` fields, ``DllProbe``, ``RoleSpec.kelvin``,
``Estimate.max_segment_s``)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.plan import Estimate
from b1500_test_agent.models.recipe import RoleSpec
from b1500_test_agent.models.sources import (
    SOURCE_PLAN_KEY,
    MeasureEvent,
    PulseTrain,
    SourcePlan,
    WaveformProgram,
    on_grid,
    pulse_envelope,
    source_plan,
    total_on_time_s,
    total_pulses,
)
from b1500_test_agent.models.station import CmuCorrectionLive, DllProbe
from tests.unit.rules_factory import live_state


def test_a_train_is_bounded_and_never_free_running() -> None:
    with pytest.raises(ValidationError, match="never free-run"):
        PulseTrain(base_v=0, peak_v=1, width_s=1e-6, period_s=1e-5)
    with pytest.raises(ValidationError, match="never free-run"):
        PulseTrain(base_v=0, peak_v=1, width_s=1e-6, period_s=1e-5, count=1, duration_s=1.0)
    with pytest.raises(ValidationError, match="shorter than period"):
        PulseTrain(base_v=0, peak_v=1, width_s=1e-5, period_s=1e-5, count=1)
    with pytest.raises(ValidationError):
        PulseTrain(base_v=0, peak_v=1, width_s=1e-6, period_s=1e-5, count=0)


def test_train_totals() -> None:
    by_count = PulseTrain(base_v=-1, peak_v=3, width_s=1e-6, period_s=1e-5, count=100, repeat=3)
    by_time = PulseTrain(base_v=0, peak_v=2, width_s=1e-6, period_s=1e-5, duration_s=1.05e-4)
    assert (by_count.max_abs_set_v, by_count.pulses, by_count.total_pulses) == (3, 100, 300)
    assert by_count.duty == pytest.approx(0.1) and by_count.total_on_time_s == pytest.approx(3e-4)
    assert by_time.pulses == 11  # 10.5 periods begin -> 11 pulses
    assert total_pulses([by_count, by_time]) == 311
    assert total_on_time_s([by_count, by_time]) == pytest.approx(3.11e-4)


def test_pulse_envelope_from_trains() -> None:
    trains = [PulseTrain(base_v=0, peak_v=4, width_s=1e-6, period_s=1e-4, count=1000, load_ohm=1e6),
              PulseTrain(base_v=0, peak_v=-2, width_s=1e-7, period_s=1e-6, count=5, load_ohm=50)]
    env = pulse_envelope(trains, source_ohm=50.0)
    assert env.max_abs_v_dut == pytest.approx(4.0002)
    assert (env.min_width_s, env.max_width_s, env.max_count) == (1e-7, 1e-6, 1000)
    assert env.max_duty == pytest.approx(0.1) and env.max_on_time_s == pytest.approx(1e-3)
    assert env.max_short_circuit_a == pytest.approx(4.0002 / 50)
    smu = pulse_envelope([PulseTrain(base_v=0, peak_v=2, width_s=1e-3, period_s=1e-2, count=10)], source_ohm=None)
    assert smu.max_abs_v_dut == 2.0 and smu.max_short_circuit_a == 0.0
    assert pulse_envelope(trains[:1], source_ohm=None, short_circuit_a=0.1).max_short_circuit_a == 0.1
    with pytest.raises(ValueError):
        pulse_envelope([], source_ohm=50.0)


@pytest.mark.parametrize(("value", "step", "ok"), [(1e-6, 1e-8, True), (1.5e-8, 1e-8, False), (2.5e-9, 2.5e-9, True),
                                                   (0.1, 1e-8, True), (0.10000001, 1e-8, True), (1e-9, 1e-8, False)])
def test_on_grid(value: float, step: float, ok: bool) -> None:
    assert on_grid(value, step) is ok


def _program(**changes: object) -> WaveformProgram:
    data: dict[str, object] = {
        "builder": "table",
        "channels": {101: {"mode": "fastiv", "measure": "current", "current_range": "1ma"}},
        "patterns": {"a": {"v0": 0.0, "vectors": [(1e-5, 1.0)]}, "b": {"v0": 1.0, "vectors": [(5e-5, -1.0)]},
                     "c": {"v0": 0.0, "vectors": [(2e-5, 0.0)]}},
        "events": [{"kind": "measure", "pattern": "a", "event": "e", "t": 0.0, "points": 10, "interval": 1e-6,
                    "average": 1e-8, "raw": True},
                   {"kind": "measure", "pattern": "c", "event": "f", "t": 0.0, "points": 5, "interval": 1e-6}],
        "sequences": {101: [("a", 3), ("b", 1), ("c", 2)]},
    }
    data.update(changes)
    return WaveformProgram.model_validate(data)


@pytest.mark.wgfmu
def test_waveform_time_matches_the_manual_example() -> None:
    """WG ch. 4 channel-status example: 3 x 10 us + 50 ns + 1 x 50 us + 50 ns + 2 x 20 us = 120.1 us."""
    program = _program()
    assert program.sequence_time_s(101) == pytest.approx(120.1e-6)
    assert program.total_time_s() == pytest.approx(120.1e-6)


@pytest.mark.wgfmu
def test_waveform_points_count_raw_samples_and_repeats() -> None:
    program = _program()
    assert MeasureEvent(pattern="a", event="e", t=0, points=10, interval=1e-6, average=1e-8, raw=True).data_points == 30
    assert program.points(101) == 3 * 30 + 2 * 5
    assert program.levels(101) == [0.0, 1.0, 1.0, -1.0, 0.0, 0.0]
    assert program.intervals(101) == [1e-6, 1e-6]
    assert program.channel_patterns(101) == ["a", "b", "c"]
    preview = program.preview()
    assert preview[0] == "builder table" and any(line.startswith("sequence 101: a x3, b x1, c x2") for line in preview)


def test_measure_event_end_includes_the_10_ns_tail() -> None:
    assert MeasureEvent(pattern="a", event="e", t=1e-6, points=11, interval=1e-7).end_s == pytest.approx(2.01e-6)
    assert MeasureEvent(pattern="a", event="e", t=0, points=2, interval=1e-6, average=5e-7).end_s == pytest.approx(
        1.5e-6)


@pytest.mark.parametrize(
    "changes",
    [{"sequences": {102: [("a", 1)]}}, {"sequences": {101: [("zzz", 1)]}},
     {"events": [{"kind": "range", "pattern": "zzz", "event": "r", "t": 0, "range": "1ma"}]}, {"channels": {}},
     {"builder": "Bad Name"}],
)
@pytest.mark.wgfmu
def test_waveform_references_resolve(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _program(**changes)


def test_source_plan_round_trip_through_the_program_json() -> None:
    plan = SourcePlan(pulses={101: [PulseTrain(base_v=0, peak_v=1, width_s=1e-6, period_s=1e-5, count=1)]},
                      waveform=_program())
    program = {SOURCE_PLAN_KEY: plan.model_dump(mode="json"), "other": 1}
    assert source_plan(program) == plan
    assert source_plan({}) == SourcePlan()
    assert plan.trains(1) == plan.trains(101) and plan.trains(102) == []
    with pytest.raises(ValidationError):
        source_plan({SOURCE_PLAN_KEY: {"pulses": {"101": [{"base_v": 0}]}}})


def test_live_state_v2_fields_default_to_not_read() -> None:
    state = live_state()
    assert (state.switch_states, state.cmu_corrections, state.wgfmu_library, state.wgfmu_channels) == (None,) * 4
    filled = state.model_copy(update={"switch_states": {"SEL1.OUT1": "open"}, "wgfmu_channels": [201],
                                      "cmu_corrections": {"CMU1": CmuCorrectionLive(corr_state={"open": True})},
                                      "wgfmu_library": DllProbe(machine="x86", message="install >= A.03.00")})
    restored = type(state).model_validate_json(filled.model_dump_json())
    assert restored == filled and restored.wgfmu_library is not None and not restored.wgfmu_library.loadable


def test_kelvin_is_an_smu_role_property() -> None:
    assert RoleSpec(function="bias_i", kelvin=True).kelvin
    with pytest.raises(ValidationError, match="Kelvin"):
        RoleSpec(function="pgu", kelvin=True)


def test_estimate_segment() -> None:
    assert Estimate(points=1, duration_s=1.0).max_segment_s is None
    assert Estimate(points=1, duration_s=600.0, max_segment_s=30.0).max_segment_s == 30.0
    with pytest.raises(ValidationError):
        Estimate(points=1, duration_s=1.0, max_segment_s=-1.0)


def test_dc_levels_of_a_dc_spot_program() -> None:
    """WP10.4: ``WaveformProgram.dc``: DC-mode channels only, no sequence, equal step counts, part of ``levels``."""
    base = {"builder": "dc_spot", "channels": {201: {"mode": "dc", "measure": "current", "current_range": "10ua"},
                                               202: {"mode": "dc"}}}
    program = WaveformProgram.model_validate({**base, "dc": {201: [-0.1, 0.1], 202: [0.0, 0.0]}})
    assert program.dc_steps == 2 and program.levels(201) == [-0.1, 0.1] and program.points(201) == 0
    assert program.preview()[-2:] == ["dc 201: 2 levels -0.1..0.1 V", "dc 202: 2 levels 0..0 V"]
    for dc, match in (({201: [0.1], 202: [0.0, 0.1]}, "same number"), ({301: [0.1]}, "dc mode"),
                      ({}, "at least one pattern or DC channel")):
        with pytest.raises(ValidationError, match=match):
            WaveformProgram.model_validate({**base, "dc": dc})
    with pytest.raises(ValidationError, match="cannot also run a sequence"):
        WaveformProgram.model_validate({**base, "patterns": {"p": {"v0": 0.0, "vectors": [[1e-6, 0.0]]}},
                                        "sequences": {201: [["p", 1]]}, "dc": {201: [0.1]}})
