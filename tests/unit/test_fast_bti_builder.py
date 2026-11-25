"""Builder ``fast_bti`` (``catalog/fast_bti.py``; blueprint v2 2.7.1, WP10.7): pure and deterministic; one sequence
entry per operation on every channel plus the tail; read patterns step through the sense levels (``edge`` +
``width`` per step, back to the phase level), holds ramp to their level and carry one monitor point at their end; all
times on the 10 ns grid; the WGFMU executions (``batches``/``slice_program``) cover the program exactly once.
"""

from __future__ import annotations

import itertools

import pytest

from b1500_test_agent.catalog import fast_bti as fb
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.catalog.waveforms import WgRole, ticks
from b1500_test_agent.models.sources import MeasureEvent, WaveformProgram, on_grid

pytestmark = pytest.mark.wgfmu

GATE = WgRole(role="gate", channel=201)
DRAIN = WgRole(role="drain", channel=202, measure="I", current_range="100ua")
SWEEP = [0.2, 0.4, 0.6, 0.8, 1.0]
TIMING = fb.SenseTiming(edge=1e-7, width=1e-6, settle=5e-7)


def channels(stress: float = 2.0, recovery: float = 0.0) -> list[fb.BtiChannel]:
    return [fb.BtiChannel(role=GATE, stress=stress, recovery=recovery, sweep=SWEEP, spot=0.5),
            fb.BtiChannel(role=DRAIN, stress=0.0, recovery=0.0, sweep=[0.1] * len(SWEEP), spot=0.1)]


def ops(stress: list[float], recovery: list[float] = ()) -> list[fb.BtiOp]:  # type: ignore[assignment]
    out = [fb.BtiOp(kind="read", cycle=0, phase="reference")]
    t = 0.0
    cycle = 0
    for phase, times in (("stress", stress), ("recovery", recovery)):
        previous = 0.0
        for end in times:
            cycle += 1
            t = round(t + end - previous, 12)
            out += [fb.BtiOp(kind="hold", cycle=cycle, phase=phase, seconds=end - previous, t_s=t),  # type: ignore
                    fb.BtiOp(kind="read", cycle=cycle, phase=phase, t_s=t)]  # type: ignore[arg-type]
            previous = end
    return out


def build(**kw: object) -> WaveformProgram:
    built = fb.fast_bti(channels(), ops([1e-3, 1e-2, 0.1]), timing=TIMING, **kw)  # type: ignore[arg-type]
    return built.program


def test_one_entry_per_operation_and_the_tail_on_every_channel() -> None:
    program = build()
    assert program.builder == "fast_bti"
    for ch, role in ((201, "gate"), (202, "drain")):
        names = [name for name, _ in program.sequences[ch]]
        assert names == [f"{role}_ref", f"{role}_h1", f"{role}_rs", f"{role}_h2", f"{role}_rs", f"{role}_h3",
                         f"{role}_rs", f"{role}_tail"]
        assert all(count == 1.0 for _, count in program.sequences[ch])
    assert program.channels[201].mode == program.channels[202].mode == "fastiv"
    assert program.channels[201].force_range == "3v" and program.channels[202].current_range == "100ua"
    assert program.channels[201].measure_enabled is False and program.channels[202].measure_enabled is True


def test_read_patterns_step_through_the_sense_levels_and_return() -> None:
    program = build()
    ref, rs = program.patterns["gate_ref"], program.patterns["gate_rs"]
    assert ref.v0 == 0.0 and rs.v0 == 2.0
    assert [v for _, v in rs.vectors] == [0.2, 0.2, 0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 1.0, 1.0, 2.0]
    assert [dt for dt, _ in rs.vectors] == pytest.approx([1e-7, 1e-6] * 5 + [1e-7])
    assert rs.duration_s == pytest.approx(fb.read_seconds(TIMING, 5)) == pytest.approx(5.6e-6)
    drain = program.patterns["drain_rs"]
    assert drain.v0 == 0.0 and [v for _, v in drain.vectors] == [0.1] * 10 + [0.0]
    sense = [e for e in program.events if isinstance(e, MeasureEvent) and e.event == fb.READ_EVENT]
    assert {e.pattern for e in sense} == {"drain_ref", "drain_rs"}  # only the measuring channel
    event = next(e for e in sense if e.pattern == "drain_rs")
    assert (event.points, event.t, event.interval, event.average) == pytest.approx((5, 6e-7, 1.1e-6, 5e-7))
    assert event.end_s <= drain.duration_s


def test_holds_ramp_to_their_level_and_carry_one_monitor_point_at_the_end() -> None:
    program = build()
    h1, h2 = program.patterns["gate_h1"], program.patterns["gate_h2"]
    assert h1.v0 == 0.0 and h1.vectors[0] == pytest.approx((1e-7, 2.0))  # from 0 V after the reference read
    assert h2.v0 == 2.0 and h1.duration_s == pytest.approx(1e-3) and h2.duration_s == pytest.approx(9e-3)
    monitor = next(e for e in program.events if isinstance(e, MeasureEvent) and e.pattern == "drain_h2")
    assert monitor.points == 1 and monitor.average == pytest.approx(9e-4)  # a tenth of a 9 ms hold
    assert monitor.t + monitor.average == pytest.approx(9e-3)
    long_hold = next(e for e in program.events if isinstance(e, MeasureEvent) and e.pattern == "drain_h3")
    assert long_hold.average == pytest.approx(fb.MONITOR_AVERAGE_S)


def test_every_time_lies_on_the_10_ns_grid_and_the_build_is_deterministic() -> None:
    program = build()
    for pattern in program.patterns.values():
        assert all(on_grid(dt, 1e-8) for dt, _ in pattern.vectors)
    for event in program.events:
        assert isinstance(event, MeasureEvent)
        assert on_grid(event.t, 1e-8) and on_grid(event.interval, 1e-8) and on_grid(event.average, 1e-8)
    assert build().model_dump() == program.model_dump()
    assert program.points(202) == 5 + 3 * (1 + 5) and program.points(201) == 0


def test_spot_reads_sense_one_level_but_the_reference_read_stays_a_staircase() -> None:
    program = build(read_kind="spot")
    assert len(program.patterns["gate_ref"].vectors) == 11
    assert [v for _, v in program.patterns["gate_rs"].vectors] == [0.5, 0.5, 2.0]
    assert program.points(202) == 5 + 3 * (1 + 1)


def test_recovery_reads_use_the_recovery_level() -> None:
    built = fb.fast_bti(channels(recovery=-0.2), ops([1e-3, 1e-2], [1e-3]), timing=TIMING)
    program = built.program
    names = [name for name, _ in program.sequences[201]]
    assert names[-3:] == ["gate_h3", "gate_rr", "gate_tail"]
    assert program.patterns["gate_h3"].v0 == 2.0 and program.patterns["gate_h3"].vectors[0][1] == -0.2
    assert program.patterns["gate_rr"].v0 == -0.2 and program.patterns["gate_tail"].v0 == -0.2


def test_a_hold_longer_than_one_vector_is_split() -> None:
    built = fb.fast_bti(channels(), ops([25_000.0]), timing=TIMING)
    hold = built.program.patterns["gate_h1"]
    assert [dt for dt, _ in hold.vectors] == pytest.approx([1e-7, 1e4, 1e4, 5e3 - 1e-7])
    assert all(dt <= fb.MAX_VECTOR_S for dt, _ in hold.vectors)


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"timing": fb.SenseTiming(edge=1e-7, width=5e-7, settle=5e-7)}, "no averaging window"),
    ({"timing": fb.SenseTiming(edge=1e-7, width=0.05, settle=0.0)}, "longest averaging time"),
    ({"read_kind": "sweep"}, "read_kind must be"),
])
def test_unusable_inputs_are_compile_errors(kwargs: dict[str, object], message: str) -> None:
    args: dict[str, object] = {"timing": TIMING, **kwargs}
    with pytest.raises(CompileError, match=message):
        fb.fast_bti(channels(), ops([1e-3]), **args)  # type: ignore[arg-type]


def test_inputs_are_checked() -> None:
    with pytest.raises(CompileError, match="same number of sense levels"):
        fb.fast_bti([channels()[0], channels()[1].model_copy(update={"sweep": [0.1]})], ops([1e-3]), timing=TIMING)
    with pytest.raises(CompileError, match="no WGFMU role measures"):
        fb.fast_bti([channels()[0]], ops([1e-3]), timing=TIMING)
    with pytest.raises(CompileError, match="start with the reference read"):
        fb.fast_bti(channels(), ops([1e-3])[1:], timing=TIMING)
    with pytest.raises(CompileError, match="alternate"):
        bad = ops([1e-3]) + ops([1e-3])[-1:]
        fb.fast_bti(channels(), bad, timing=TIMING)


def test_batches_cover_the_program_once_and_end_after_reads() -> None:
    schedule = [round(1e-3 * 10 ** (k / 3), 9) for k in range(13)]  # up to 10 s: one execution after the reference
    schedule += [30.0, 100.0]  # holds of 20 s (no longer fits the first) and 70 s (longer than 25 s)
    program = fb.fast_bti(channels(), ops(schedule), timing=TIMING).program
    runs = fb.batches(program, ops(schedule))
    entries = len(program.sequences[201])
    assert runs[0][0] == 0 and runs[-1][1] == entries
    assert all(a[1] == b[0] for a, b in itertools.pairwise(runs))
    assert [stop - start for start, stop in runs] == [27, 2, 3]  # 20 s, then 70 s (+ the tail) run alone
    for start, stop in runs[:-1]:
        assert stop % 2 == 1  # the entry before ``stop`` is a read (reads have even indices)
    total = 0
    for start, stop in runs:
        piece = fb.slice_program(program, start, stop)
        assert set(piece.patterns) == {name for items in piece.sequences.values() for name, _ in items}
        assert {e.pattern for e in piece.events} <= set(piece.patterns)
        total += piece.points(202)
        assert piece.points(202) == sum(fb.entry_values(program, 202)[start:stop])
    assert total == program.points(202)


def test_monitor_average_is_a_tenth_of_the_hold_within_the_bounds() -> None:
    assert fb.monitor_average_ticks(ticks(1e-6)) == 10
    assert fb.monitor_average_ticks(5) == 1
    assert fb.monitor_average_ticks(ticks(100.0)) == ticks(fb.MONITOR_AVERAGE_S)
