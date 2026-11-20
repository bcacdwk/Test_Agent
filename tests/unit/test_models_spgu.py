"""HV-SPGU programs (``models/spgu.py``, WP9.1): validation, output time, the guard view of two-level, three-level and
ALWG channels, and the module-spec checks of a whole program (``driver.modules.SPGU_SPEC.program_problems``)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from b1500_test_agent.driver.modules import SPGU_SPEC
from b1500_test_agent.models.sources import pulse_envelope
from b1500_test_agent.models.spgu import (
    ALWG_SETUP_DELAY_S,
    AlwgChannel,
    AlwgPattern,
    AlwgProgram,
    AlwgVector,
    PulseSwitch,
    SpguChannel,
    SpguPulseProgram,
    SpguSource,
)

pytestmark = pytest.mark.spgu


def lwp_config_b(count: int = 2) -> SpguPulseProgram:
    """lwp ``test_SPGU.m`` configuration B: 101 and 102 three-level, 0 -> +3 V (delay 0, 2 us) then 0 -> -3 V (delay
    3 us, 2 us), transitions 100 ns, period 10 us, ``count`` pulses, load 1 MOhm."""
    sources = {1: SpguSource(delay_s=0.0, width_s=2e-6, lead_s=1e-7, trail_s=1e-7, base_v=0.0, peak_v=3.0),
               2: SpguSource(delay_s=3e-6, width_s=2e-6, lead_s=1e-7, trail_s=1e-7, base_v=0.0, peak_v=-3.0)}
    channel = SpguChannel(load_ohm=1e6, levels="three_level", sources=sources)
    return SpguPulseProgram(period_s=1e-5, count=count, channels={101: channel, 102: channel})


def two_level(peak: float = 4.0, *, load: float = 1e6, count: int | None = 1000,
              duration: float | None = None) -> SpguPulseProgram:
    source = SpguSource(width_s=1e-6, base_v=0.0, peak_v=peak)
    return SpguPulseProgram(period_s=1e-4, count=count, duration_s=duration,
                            channels={101: SpguChannel(load_ohm=load, sources={1: source})})


def test_two_level_guard_train_is_the_source() -> None:
    program = two_level()
    train = program.guard_train(101)
    assert (train.base_v, train.peak_v, train.width_s, train.period_s, train.count, train.load_ohm) == (
        0.0, 4.0, 1e-6, 1e-4, 1000, 1e6)
    assert train.lead_s == 2e-8 and train.trail_s == 2e-8  # SPT: the leading time serves as trailing time
    assert program.output_time_s() == pytest.approx(0.1)
    assert program.trains() == {101: [train]}


def test_three_level_guard_train_covers_both_pulses() -> None:
    program = lwp_config_b()
    train = program.guard_train(101)
    assert train.base_v == 0.0 and abs(train.peak_v) == 3.0
    assert train.width_s == pytest.approx(4e-6)  # the union of [0, 2 us) and [3 us, 5 us)
    assert train.duty == pytest.approx(0.4) and train.count == 2 and train.load_ohm == 1e6
    assert [t.peak_v for t in program.source_trains(101)] == [3.0, -3.0]
    assert program.output_time_s() == pytest.approx(2e-5)
    envelope = pulse_envelope(program.trains()[101], source_ohm=50.0)
    assert envelope.max_abs_v_dut == pytest.approx(3.0 * (1e6 + 50) / 1e6)


def test_three_level_overlap_counts_once_and_sums_the_levels() -> None:
    sources = {1: SpguSource(delay_s=0.0, width_s=3e-6, base_v=1.0, peak_v=2.0),
               2: SpguSource(delay_s=2e-6, width_s=3e-6, base_v=0.5, peak_v=3.0)}
    channel = SpguChannel(load_ohm=1e3, levels="three_level", sources=sources)
    assert channel.base_v == 1.5 and channel.extreme_v == 5.0 and channel.away_s == pytest.approx(5e-6)
    assert sorted(channel.level_set()) == [1.5, 2.5, 4.0, 5.0]


@pytest.mark.parametrize(
    "build",
    [
        lambda: SpguChannel(load_ohm=50.0, sources={1: SpguSource(width_s=1e-6, base_v=0, peak_v=1),
                                                    2: SpguSource(width_s=1e-6, base_v=0, peak_v=1)}),
        lambda: SpguChannel(load_ohm=50.0, levels="three_level",
                            sources={1: SpguSource(width_s=1e-6, base_v=0, peak_v=1)}),
        lambda: SpguChannel(load_ohm=0.0, sources={1: SpguSource(width_s=1e-6, base_v=0, peak_v=1)}),
        lambda: two_level(count=None),  # free run cannot be expressed
        lambda: two_level(count=10, duration=1.0),
        lambda: SpguPulseProgram(period_s=1e-6, count=1, channels={
            101: SpguChannel(load_ohm=50.0, sources={1: SpguSource(delay_s=5e-7, width_s=5e-7, base_v=0,
                                                                   peak_v=1)})}),  # delay + width = period
    ],
)
def test_invalid_programs_do_not_construct(build) -> None:
    with pytest.raises(ValidationError):
        build()


def alwg(sequence: list[tuple[int, int]], *, count: int | None = 3, duration: float | None = None,
         second: AlwgPattern | None = None) -> AlwgProgram:
    pulse = AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=1e-6, v=2.0), AlwgVector(dt_s=2e-6, v=2.0),
                                                AlwgVector(dt_s=1e-6, v=0.0), AlwgVector(dt_s=6e-6, v=0.0)])
    rest = second or AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=5e-6, v=0.0)])
    return AlwgProgram(sequence=sequence, count=count, duration_s=duration,
                       channels={101: AlwgChannel(load_ohm=1e6, patterns=[pulse, rest])})


def test_alwg_timing_counts_the_setup_delays() -> None:
    program = alwg([(1, 2), (2, 1)])
    assert program.sequence_time_s() == pytest.approx(2 * 10e-6 + 5e-6 + ALWG_SETUP_DELAY_S)
    assert program.wraps and program.repeat_period_s() == pytest.approx(program.sequence_time_s() + 5e-8)
    assert program.output_time_s() == pytest.approx(3 * program.sequence_time_s() + 2 * 5e-8)
    same = alwg([(1, 4)])
    assert not same.wraps and same.output_time_s() == pytest.approx(3 * 40e-6)


def test_alwg_guard_train_is_the_time_away_from_the_initial_level() -> None:
    program = alwg([(1, 2), (2, 1)])
    train = program.guard_train(101)
    assert train.base_v == 0.0 and train.peak_v == 2.0 and train.count == 3 and train.load_ohm == 1e6
    assert train.width_s == pytest.approx(2 * 4e-6)  # ramp up, hold, ramp down; twice per sequence
    assert train.period_s == pytest.approx(program.repeat_period_s())
    by_duration = alwg([(1, 1)], count=None, duration=1e-3)
    assert by_duration.guard_train(101).pulses == 100


def test_alwg_validation() -> None:
    with pytest.raises(ValidationError, match="names pattern 3"):
        alwg([(3, 1)])
    flat = AlwgPattern(initial_v=1.0, vectors=[AlwgVector(dt_s=1e-6, v=1.0)])
    with pytest.raises(ValidationError, match="never leaves"):
        AlwgProgram(sequence=[(1, 1)], count=1, channels={101: AlwgChannel(load_ohm=50.0, patterns=[flat])})
    ramp = AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=1e-6, v=1.0)])
    with pytest.raises(ValidationError, match="return to its initial level"):
        AlwgProgram(sequence=[(1, 1)], count=1, channels={101: AlwgChannel(load_ohm=50.0, patterns=[ramp])})
    other = AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=2e-6, v=1.0), AlwgVector(dt_s=1e-6, v=0.0)])
    base = alwg([(1, 1)]).channels[101]
    with pytest.raises(ValidationError, match="in step"):
        AlwgProgram(sequence=[(1, 1)], count=1,
                    channels={101: base, 102: AlwgChannel(load_ohm=50.0, patterns=[other])})


def test_program_problems_of_a_valid_program_are_empty() -> None:
    assert SPGU_SPEC.program_problems(lwp_config_b()) == []
    assert SPGU_SPEC.program_problems(alwg([(1, 2), (2, 1)])) == []


def test_program_problems_name_spec_violations() -> None:
    fast = SpguSource(width_s=1e-6, lead_s=1e-6, base_v=0.0, peak_v=1.0)  # width < leading / 0.8 (error 2111)
    program = SpguPulseProgram(period_s=1e-5, count=1, channels={101: SpguChannel(load_ohm=50.0, sources={1: fast})})
    assert any("2111" in p.message for p in SPGU_SPEC.program_problems(program))
    doubled = two_level(peak=25.0, load=50.0)  # 25 V x 2 at 50 Ohm = 50 V open load (error 2107)
    assert any("2107" in p.message for p in SPGU_SPEC.program_problems(doubled))
    assert SPGU_SPEC.program_problems(two_level(peak=20.0, load=50.0)) == []  # exactly 40 V
    big = {1: SpguSource(width_s=1e-6, base_v=0.0, peak_v=25.0), 2: SpguSource(delay_s=5e-6, width_s=1e-6,
                                                                              base_v=0.0, peak_v=25.0)}
    three = SpguPulseProgram(period_s=1e-5, count=1, channels={
        101: SpguChannel(load_ohm=1e6, levels="three_level", sources=big)})
    assert any("2106" in p.message for p in SPGU_SPEC.program_problems(three))
    off_grid = alwg([(1, 1)], second=AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=1.5e-8, v=0.0005)]))
    messages = [p.message for p in SPGU_SPEC.program_problems(off_grid)]
    assert any("1 mV" in m for m in messages) and any("10 ns grid" in m for m in messages)


def test_pulse_switch_defaults_follow_table_2_12() -> None:
    switch = PulseSwitch()
    assert (switch.normally_closed, switch.delay_s, switch.width_s) == (False, 0.0, 1e-7)
    assert math.isclose(SPGU_SPEC.open_load_v(3.0, 1e6), 3.0 * (1e6 + 50) / 1e6)
