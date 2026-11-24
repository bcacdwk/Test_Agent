"""WGFMU waveform builders (``catalog/waveforms.py``; blueprint v2 2.7.1, WP10.4): vector counts, the 10 ns grid,
channel alignment, event timing, nominal pulse trains, determinism, the lab CSV layout (waveform and events files),
the range-code semantics, the data layout and the programmed levels, and the requests the builders refuse."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.models.sources import MeasureEvent, RangeEvent, on_grid

pytestmark = pytest.mark.wgfmu

ROOT = Path(__file__).resolve().parents[2]
GATE = wf.WgRole(role="gate", channel=201)
DRAIN = wf.WgRole(role="drain", channel=202, measure="I", current_range="1ma")
LEVELS = [0.5, 1.0, 1.5]


def pulsed(**changes: object) -> wf.BuiltWaveform:
    args: dict[str, object] = {"base": 0.0, "levels": LEVELS, "width": 1e-5, "period": 1e-3, "edge": 1e-7,
                               "settle": 1e-6}
    args.update(changes)
    return wf.pulsed_iv(GATE, [(DRAIN, 1.0)], **args)  # type: ignore[arg-type]


def all_on_grid(program: object) -> bool:
    return all(on_grid(dt, wf.TICK_S) and dt >= wf.TICK_S for p in program.patterns.values()  # type: ignore[attr-defined]
               for dt, _ in p.vectors)


# -- ranges and grid -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("levels", "expected"), [
    ([0.0, 3.0], "3v"), ([-3.0, 0.0], "3v"), ([0.0, 4.0], "5v"), ([-4.0, 4.0], "5v"), ([-8.0, 0.0], "-10v"),
    ([0.0, 9.5], "10v"),
])  # fmt: skip
def test_the_finest_force_range_holds_every_level(levels: list[float], expected: str) -> None:
    assert wf.force_range_for(levels) == expected


def test_levels_spanning_two_ten_volt_ranges_fit_none() -> None:
    with pytest.raises(CompileError, match="fit no WGFMU force range"):
        wf.force_range_for([-6.0, 6.0])


def test_times_round_to_the_10_ns_grid_and_zero_is_refused() -> None:
    assert wf.ticks(32e-9) == 3 and wf.on_grid_s(32e-9, "t") == pytest.approx(30e-9)
    with pytest.raises(CompileError, match="shorter than 1 x 10 ns"):
        wf.on_grid_s(4e-9, "edge")
    assert wf.on_grid_s(0.0, "settle", minimum=0) == 0.0


# -- pulsed_iv -------------------------------------------------------------------------------------------------------


def test_pulsed_iv_programs_one_pulse_per_level_on_the_grid() -> None:
    built = pulsed()
    program = built.program
    gate, drain = program.patterns["gate"], program.patterns["drain"]
    assert len(gate.vectors) == 2 + 4 * len(LEVELS) + 1 and len(drain.vectors) == 3
    assert all_on_grid(program)
    assert gate.v0 == drain.v0 == 0.0 and gate.vectors[-1][1] == drain.vectors[-1][1] == 0.0  # starts/ends at 0 V
    assert program.sequence_time_s(201) == pytest.approx(program.sequence_time_s(202), abs=1e-15)
    assert [v for _, v in gate.vectors[2:-1]] == [0.5, 0.5, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.5, 1.5, 0.0, 0.0]
    setup = program.channels
    assert (setup[201].measure_enabled, setup[202].measure, setup[202].current_range) == (False, "current", "1ma")
    assert setup[201].force_range == setup[202].force_range == "3v"
    (event,) = program.events
    assert isinstance(event, MeasureEvent) and (event.pattern, event.event, event.points) == ("drain", "plateau", 3)
    assert event.t == pytest.approx(1e-7 + 1e-6 + 1e-7 + 1e-6)  # ramp, settle, rising edge, settle
    assert event.interval == pytest.approx(1e-3) and event.average == pytest.approx(1e-5 - 2e-6)
    assert built.cycle_by == "point" and program.points(202) == 3 and program.points(201) == 0


def test_pulsed_iv_trains_one_per_level_merged_and_deterministic() -> None:
    built = pulsed(levels=[1.0, 1.0, 2.0])
    trains = built.pulses[201]
    assert [(t.peak_v, t.repeat, t.count) for t in trains] == [(1.0, 2, 1), (2.0, 1, 1)]
    assert all((t.width_s, t.period_s, t.lead_s, t.trail_s) == pytest.approx((1e-5, 1e-3, 1e-7, 1e-7))
               for t in trains)
    again = pulsed(levels=[1.0, 1.0, 2.0])
    assert again.model_dump_json() == built.model_dump_json()


@pytest.mark.parametrize(("changes", "match"), [
    ({"period": 1e-5}, "must exceed width"),
    ({"settle": 5e-6}, "no averaging window"),
    ({"levels": []}, "at least one pulse level"),
    ({"edge": 1e-9}, "shorter than 1 x 10 ns"),
])  # fmt: skip
def test_pulsed_iv_refuses_impossible_timing(changes: dict[str, object], match: str) -> None:
    with pytest.raises(CompileError, match=match):
        pulsed(**changes)


def test_pulsed_iv_needs_a_measuring_role() -> None:
    with pytest.raises(CompileError, match="no role measures"):
        wf.pulsed_iv(GATE, [(DRAIN.model_copy(update={"measure": None}), 1.0)], base=0.0, levels=[1.0], width=1e-5,
                     period=1e-3, edge=1e-7, settle=1e-6)


def test_the_averaging_window_is_capped_at_the_longest_average() -> None:
    built = pulsed(width=5e-2, period=0.2)
    (event,) = built.program.events
    assert isinstance(event, MeasureEvent) and event.average == pytest.approx(wf.MAX_AVERAGE_S)


# -- pulse_train and fast_iv_ramp ------------------------------------------------------------------------------------


def test_pulse_train_repeats_one_period_with_aligned_entries() -> None:
    built = wf.pulse_train(GATE, [(DRAIN, 0.5)], base=0.0, peak=2.0, width=1e-5, period=1e-4, edge=1e-7, count=50,
                           settle=1e-6, samples=4)
    program = built.program
    assert program.sequences[201] == [("gate_lead", 1.0), ("gate", 50.0), ("gate_tail", 1.0)]
    assert program.sequences[202] == [("drain_lead", 1.0), ("drain", 50.0), ("drain_tail", 1.0)]
    assert program.patterns["gate"].duration_s == pytest.approx(program.patterns["drain"].duration_s)
    assert program.sequence_time_s(201) == pytest.approx(program.sequence_time_s(202))
    (event,) = program.events
    assert isinstance(event, MeasureEvent) and event.points == 4 and event.interval == pytest.approx(2e-6)
    assert program.points(202) == 200 and built.cycle_by == "repeat"
    (train,) = built.pulses[201]
    assert (train.count, train.peak_v, train.duty) == (50, 2.0, pytest.approx(0.1))
    assert all_on_grid(program)


def test_pulse_train_refuses_more_samples_than_ten_ns_slots() -> None:
    with pytest.raises(CompileError, match="do not fit"):
        wf.pulse_train(GATE, [(DRAIN, 0.5)], base=0.0, peak=2.0, width=1e-7, period=1e-6, edge=1e-8, count=1,
                       settle=0.0, samples=11)


def test_fast_iv_ramp_samples_both_ramps_continuously() -> None:
    built = wf.fast_iv_ramp(GATE, [(DRAIN, 0.1)], start=0.0, stop=2.0, ramp=1e-5, interval=1e-7, edge=1e-7,
                            settle=1e-6, double=True, cycles=3)
    program = built.program
    up, down = program.events
    assert isinstance(up, MeasureEvent) and isinstance(down, MeasureEvent)
    assert (up.points, down.points, up.average, down.t) == (100, 100, pytest.approx(1e-7), pytest.approx(1e-5))
    assert down.end_s == pytest.approx(program.patterns["drain"].duration_s)
    assert built.segments == {"up": "fwd", "down": "rev"} and program.points(202) == 600


@pytest.mark.parametrize(("changes", "match"), [
    ({"ramp": 1.005e-5}, "whole number"), ({"interval": 5e-2, "ramp": 1.0}, "longest averaging"),
    ({"double": False, "cycles": 2}, "single ramp"),
])  # fmt: skip
def test_fast_iv_ramp_refusals(changes: dict[str, object], match: str) -> None:
    args: dict[str, object] = {"start": 0.0, "stop": 2.0, "ramp": 1e-5, "interval": 1e-7, "edge": 1e-7,
                               "settle": 1e-6, "double": True, "cycles": 1, **changes}
    with pytest.raises(CompileError, match=match):
        wf.fast_iv_ramp(GATE, [(DRAIN, 0.1)], **args)  # type: ignore[arg-type]


# -- dc_spot ---------------------------------------------------------------------------------------------------------


def test_dc_spot_repeats_a_constant_level_for_every_step() -> None:
    a = wf.WgRole(role="a", channel=201, measure="I", current_range="10ua")
    c = wf.WgRole(role="c", channel=202, measure="I")
    built = wf.dc_spot([(a, [-0.1, 0.0, 0.1]), (c, [0.2])])
    program = built.program
    assert program.dc == {201: [-0.1, 0.0, 0.1], 202: [0.2, 0.2, 0.2]} and program.dc_steps == 3
    assert {ch: s.mode for ch, s in program.channels.items()} == {201: "dc", 202: "dc"}
    assert not program.patterns and not program.sequences and program.levels(201) == [-0.1, 0.0, 0.1]
    with pytest.raises(CompileError, match="same number of levels"):
        wf.dc_spot([(a, [0.0, 0.1]), (c, [0.0, 0.1, 0.2])])
    with pytest.raises(CompileError, match="no role measures"):
        wf.dc_spot([(a.model_copy(update={"measure": None}), [0.1])])


# -- table: the lab CSV layout ---------------------------------------------------------------------------------------


def test_the_library_sample_is_the_lab_layout() -> None:
    pattern = wf.parse_wave_csv((ROOT / "recipes/waveforms/lwp_sample.csv").read_bytes(), name="sample")
    assert len(pattern.vectors) == 199 and pattern.duration_s == pytest.approx(5.52e-3)  # 200 rows
    assert (min(pattern.levels()), max(pattern.levels())) == (-4.0, 4.0)
    assert all(on_grid(dt, wf.TICK_S) for dt, _ in pattern.vectors)
    events = wf.parse_events_csv((ROOT / "recipes/waveforms/lwp_sample_events.csv").read_bytes(), name="e",
                                 channels=2)
    assert events == [wf.EventRow(t=0.0, points=55200, interval=1e-7, average=1e-7, ranges=(0, 3))]


def test_wave_csv_accepts_one_header_comments_and_whitespace() -> None:
    text = b"# lab file\ntime,voltage\n0,0\n\n1e-6, 1.5\n2.000000001e-06\t0\n"
    pattern = wf.parse_wave_csv(text.replace(b"\t", b" ").replace(b"2.000000001e-06 0", b"2.000000001e-06,0"),
                                name="w")
    assert pattern.v0 == 0.0 and [v for _, v in pattern.vectors] == [1.5, 0.0]
    assert [dt for dt, _ in pattern.vectors] == pytest.approx([1e-6, 1e-6])  # rounded to the grid
    spaced = wf.parse_wave_csv(b"0 0\n1e-6 2\n", name="w")
    assert spaced.vectors == [(pytest.approx(1e-6), 2.0)]


@pytest.mark.parametrize(("text", "match"), [
    (b"0,0\n", "at least two rows"), (b"1e-6,0\n2e-6,1\n", "first time must be 0"),
    (b"0,0\n1e-6,1\n1e-6,2\n", "increase by at least 10 ns"), (b"0,0\n1e-6,x\n", "line 2"),
    (b"\xff\xfe0,0", "not UTF-8"),
])  # fmt: skip
def test_malformed_wave_files_are_refused(text: bytes, match: str) -> None:
    with pytest.raises(CompileError, match=match):
        wf.parse_wave_csv(text, name="w")


def test_events_csv_pads_missing_range_codes_and_checks_them() -> None:
    rows = wf.parse_events_csv(b"t,points,interval,average\n0,10,1e-6,0\n1e-4,0,0,0,0,2\n", name="e", channels=2)
    assert [r.ranges for r in rows] == [(0, 0), (0, 2)] and rows[1].points == 0
    for text, match in ((b"0,1,1e-6,0,7\n", "range codes"), (b"0,1,1e-6,0,1,1,1\n", "3 range columns"),
                        (b"-1,1,1e-6,0\n", ">= 0"), (b"0,1.5,1e-6,0\n", "whole number"), (b"# none\n", "no event")):
        with pytest.raises(CompileError, match=match):
            wf.parse_events_csv(text, name="e", channels=2)


def test_table_maps_range_codes_and_measures_every_measuring_channel() -> None:
    gate = wf.WgRole(role="gate", channel=201, measure="V")
    drain = wf.WgRole(role="drain", channel=202, measure="I", current_range="1ma")
    pattern = wf.parse_wave_csv(b"0,0\n1e-3,1\n2e-3,1\n", name="g")
    rows = wf.parse_events_csv(b"0,100,1e-5,1e-5,0,3\n1.5e-3,0,0,0,0,4\n1.6e-3,10,1e-5,0,0,0\n", name="e", channels=2)
    program = wf.table([(gate, pattern), (drain, pattern)], rows).program
    assert program.channels[202].current_range == "100ua"  # the code at time 0 is the initial range
    assert program.channels[201].measure == "voltage" and program.channels[201].voltage_range == "5v"
    ranges = [e for e in program.events if isinstance(e, RangeEvent)]
    assert [(r.pattern, r.event, r.range) for r in ranges] == [("drain", "E2r", "1ma")]
    assert ranges[0].t == pytest.approx(1.5e-3)
    measures = [e for e in program.events if isinstance(e, MeasureEvent)]
    assert sorted((m.pattern, m.event, m.raw) for m in measures) == [
        ("drain", "E1", False), ("drain", "E3", True), ("gate", "E1", False), ("gate", "E3", True)]
    assert program.points(201) == program.points(202) == 110


# -- layout and programmed levels ------------------------------------------------------------------------------------


def test_point_layout_follows_events_repeats_and_range_changes() -> None:
    gate = wf.WgRole(role="gate", channel=201, measure="V")
    drain = wf.WgRole(role="drain", channel=202, measure="I", current_range="1ma")
    pattern = wf.parse_wave_csv(b"0,0\n2e-5,1\n", name="g")
    rows = wf.parse_events_csv(b"1e-5,2,1e-6,0,0,0\n0,3,1e-6,5e-7,0,0\n9e-6,0,0,0,0,2\n", name="e", channels=2)
    program = wf.table([(gate, pattern), (drain, pattern)], rows).program
    layout = wf.point_layout(program, 202)
    assert list(layout.event) == ["E2", "E2", "E2", "E1", "E1"]  # by start time
    assert layout.start_s == pytest.approx([0.0, 1e-6, 2e-6, 1e-5, 1.1e-5])
    assert layout.average_s == pytest.approx([5e-7, 5e-7, 5e-7, 0.0, 0.0])
    assert layout.range is not None and list(layout.range) == ["1ma", "1ma", "1ma", "10ua", "10ua"]
    assert wf.point_layout(program, 201).range is None


def test_raw_points_expand_into_five_ns_samples() -> None:
    gate = wf.WgRole(role="gate", channel=201, measure="V")
    program = wf.table([(gate, wf.parse_wave_csv(b"0,0\n1e-5,1\n", name="g"))],
                       [wf.EventRow(t=0.0, points=2, interval=1e-6, average=0.0, ranges=(0,))]).program
    raw = program.model_copy(update={"events": [MeasureEvent(pattern="gate", event="r", t=0.0, points=2,
                                                              interval=1e-6, average=2e-8, raw=True)]})
    layout = wf.point_layout(raw, 201)
    assert len(layout) == raw.points(201) == 10
    assert layout.start_s[:5] == pytest.approx([0.0, 5e-9, 1e-8, 1.5e-8, 2e-8])
    assert list(layout.point) == [0] * 5 + [1] * 5


def test_program_levels_cover_ramps_repeats_gaps_and_the_end() -> None:
    built = wf.pulse_train(GATE, [(DRAIN, 0.5)], base=0.0, peak=2.0, width=1e-5, period=1e-4, edge=1e-7, count=3,
                           settle=1e-6, samples=2)
    program = built.program
    lead = 1e-7 + 1e-6
    start = lead + 5e-8  # the 50 ns gap after the lead entry
    times = np.asarray([0.0, 5e-8, lead + 1e-8, start + 5e-8, start + 1e-6, start + 1e-4 + 1e-6, 1.0])
    levels = wf.program_levels(program, 201, times)
    assert levels == pytest.approx([0.0, 0.0, 0.0, 1.0, 2.0, 2.0, 0.0])  # 0 V; gap at base; mid-edge 1 V; plateau
    assert wf.program_levels(program, 202, np.asarray([start + 5e-5])) == pytest.approx([0.5])
    assert wf.program_levels(program, 999, np.asarray([1.0])) == pytest.approx([0.0])
    dc = wf.dc_spot([(wf.WgRole(role="a", channel=201, measure="I"), [0.3, 0.4])]).program
    assert wf.program_levels(dc, 201, np.asarray([0.0])) == pytest.approx([0.3])


def test_builders_never_produce_a_time_off_the_grid() -> None:
    for built in (pulsed(width=3.33e-6, period=7.77e-5, edge=1.3e-8, settle=4.4e-7),
                  wf.fast_iv_ramp(GATE, [(DRAIN, 0.1)], start=-1.0, stop=1.0, ramp=3e-6, interval=3e-8, edge=1e-8,
                                  settle=0.0, double=True, cycles=2)):
        assert all_on_grid(built.program)
        assert all(on_grid(e.t, wf.TICK_S) for e in built.program.events)
        assert math.isfinite(built.program.total_time_s())
