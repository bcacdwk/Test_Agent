"""WGFMU waveform builder ``fast_bti`` (blueprint v2 2.7.1, 3.4 row ``wgfmu.fast_bti``; WP10.7): stress with interleaved
microsecond senses, pure and deterministic like the builders of ``catalog/waveforms.py`` (which lists it in
``BUILDERS``; the module is separate only to keep ``waveforms.py`` small).

Inputs: the WGFMU channels (``BtiChannel``: role, stress level, recovery level, the sense levels of a staircase read
and the level of a spot read) and the run's operations in time order (``BtiOp``): the reference read (cycle 0,
before any stress), then per cycle a hold at the stress (or recovery) level and the read that ends it; ``t_s`` is the
cumulative hold time (stress, then stress plus recovery) at the end of each operation, as in kind ``stress_measure``.

Program (one sequence entry per operation on every channel, then one ``tail`` entry; every channel has the same
entries, so they stay aligned and the 50 ns gap between two entries (WG p80 (4-10)) falls at the same level on both
sides):

- read: pattern ``<role>_ref`` (reference: from 0 V), ``<role>_rs`` (from the stress level) or ``<role>_rr`` (from the
  recovery level): per sense step ``edge`` to the step's level and ``width`` flat, then ``edge`` back to the level it
  came from. A swept channel steps through its levels; every other channel holds its one sense level for the whole
  read (the drain's read bias). Each measuring channel takes one point per step (event ``sense``), averaged over the
  flat ``width`` minus ``settle`` (the edge and the first ``settle`` of each step are left out). Stress reads are
  staircases (``read_kind`` ``staircase``) or one step at the spot level (``spot``); the reference read is always the
  staircase (the curve a spot read is compared with).
- hold: pattern ``<role>_h<cycle>``: ``edge`` from the level before to the hold level, then the hold level for the rest
  of the hold (in vectors of at most ``MAX_VECTOR_S``); event ``monitor``: one point averaged over the last
  ``min(MONITOR_AVERAGE_S, hold / 10)`` of the hold (the stress current of each measuring channel).
- tail: ``edge`` back to 0 V.

The gate leaves its stress level only for one read, ``read_s`` = steps x (edge + width) + edge (a few microseconds),
so the shift hardly recovers before it is sensed; the recovery during a read is ``read_s`` long, not the seconds of
an SMU sweep. Holds are timed by the sequencer; ``t_s`` counts the programmed holds (the edges, ``edge`` at a time,
and the 50 ns entry gaps around a read add at most ``edge + 100 ns`` of partial stress per read; ``MIN_FIRST_READ_S``
keeps that below 1 % of the first stress interval with the default 100 ns edges).

Runs (``batches``): the kind runs the program in WGFMU executions of whole operations (``slice_program``: entries
``[start, stop)`` with the patterns and events they use), each ending after a read, at most ``BATCH_S`` of
sequencer time unless one hold is longer; the first starts with the reference read, the last ends with the tail. Every
run starts at the level the previous one ended at (the stress or recovery level, which the WGFMU keeps between runs),
so a run boundary interrupts nothing; it only adds the host's readback and setup time to the hold
(TODO(verify)[L9.A9]: duration per boundary, and that ``WGFMU_update`` of the next run leaves the output at its
level; the level only with the step's optional scope).

Data (``entry_values``): per measuring channel in sequence order, a read stores one value per step and a hold one
value; the tail stores none.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import Final, Literal

from pydantic import Field

from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.catalog.waveforms import (
    MAX_AVERAGE_S,
    TICK_S,
    BuiltWaveform,
    WgRole,
    _program,
    _setup,
    on_grid_s,
    ticks,
)
from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.sources import WGFMU_SEQUENCE_GAP_S, MeasureEvent, Pattern, WaveformEvent, WaveformProgram

FAST_BTI: Final = "fast_bti"

MIN_FIRST_READ_S: Final = 1e-5
"""Shortest stress before the first read (and shortest recovery before the first recovery read)."""

MONITOR_AVERAGE_S: Final = 1e-3
"""Longest averaging window of a hold's monitor point (shorter holds average a tenth of their length)."""

MAX_VECTOR_S: Final = 1e4
"""Longest vector of a hold pattern (the library takes at most 10995.11627775 s per vector, WG5 p24 (1-14))."""

BATCH_S: Final = 25.0
"""Sequencer time of one WGFMU execution, unless a single hold is longer (``batches``)."""

ReadKind = Literal["staircase", "spot"]
READ_KINDS: Final[tuple[ReadKind, ...]] = ("staircase", "spot")
OpPhase = Literal["reference", "stress", "recovery"]

READ_EVENT: Final = "sense"
MONITOR_EVENT: Final = "monitor"


class BtiChannel(StrictModel):
    """One WGFMU channel of a fast-BTI program: its role, the stress and recovery levels (V), the levels of a staircase
    read (``sweep``: one level per step; a non-swept channel repeats its sense level) and the level of a spot read."""

    role: WgRole
    stress: float
    recovery: float = 0.0
    sweep: list[float] = Field(min_length=1)
    spot: float


class BtiOp(StrictModel):
    """One operation in time order: a ``read`` (cycle 0 = the reference read) or the ``hold`` before read ``cycle``;
    ``phase``: the level the operation leaves from and returns to (reads) or holds (holds); ``seconds``: the hold time;
    ``t_s``: the cumulative hold time at the operation's end."""

    kind: Literal["read", "hold"]
    cycle: int = Field(ge=0)
    phase: OpPhase
    seconds: float = Field(default=0.0, ge=0)
    t_s: float = Field(default=0.0, ge=0)


class SenseTiming(StrictModel):
    """Read timing (s, on the 10 ns grid): ``edge`` between levels, ``width`` flat per step, ``settle`` from the end of
    an edge to the averaging window of the step."""

    edge: float = Field(gt=0)
    width: float = Field(gt=0)
    settle: float = Field(ge=0)


def _ticks_of(seconds: float, what: str, *, minimum: int = 1) -> int:
    return ticks(on_grid_s(seconds, what, minimum=minimum))


def _s(count: int) -> float:
    return count * TICK_S


class _Timing:
    """``SenseTiming`` in ticks, checked."""

    def __init__(self, timing: SenseTiming) -> None:
        self.edge = _ticks_of(timing.edge, "edge")
        self.width = _ticks_of(timing.width, "width")
        self.settle = _ticks_of(timing.settle, "settle", minimum=0)
        if self.width - self.settle < 1:
            raise CompileError(f"width {_s(self.width):g} s leaves no averaging window after settle "
                               f"{_s(self.settle):g} s (need width > settle + 10 ns)")
        if self.width - self.settle > ticks(MAX_AVERAGE_S):
            raise CompileError(f"width - settle = {_s(self.width - self.settle):g} s exceeds the longest averaging "
                               f"time {MAX_AVERAGE_S:g} s")

    def read_ticks(self, steps: int) -> int:
        return steps * (self.edge + self.width) + self.edge


def read_seconds(timing: SenseTiming, steps: int) -> float:
    """Time one read of ``steps`` sense steps keeps the channels off their phase level (s)."""
    return _s(_Timing(timing).read_ticks(steps))


def _read_pattern(level: float, levels: Sequence[float], tm: _Timing) -> Pattern:
    vectors: list[tuple[float, float]] = []
    for value in levels:
        vectors += [(_s(tm.edge), value), (_s(tm.width), value)]
    vectors.append((_s(tm.edge), level))
    return Pattern(v0=level, vectors=vectors)


def _hold_pattern(start: float, level: float, seconds: float, tm: _Timing) -> Pattern:
    total = _ticks_of(seconds, "hold")
    if total <= tm.edge:
        raise CompileError(f"a hold of {seconds:g} s is not longer than the edge {_s(tm.edge):g} s")
    vectors: list[tuple[float, float]] = [(_s(tm.edge), level)]
    left = total - tm.edge
    chunk = ticks(MAX_VECTOR_S)
    while left > 0:
        step = min(left, chunk)
        vectors.append((_s(step), level))
        left -= step
    return Pattern(v0=start, vectors=vectors)


def monitor_average_ticks(hold_ticks: int) -> int:
    """Averaging window (ticks) of a hold's monitor point: ``min(MONITOR_AVERAGE_S, hold / 10)``, at least 10 ns."""
    return max(1, min(ticks(MONITOR_AVERAGE_S), hold_ticks // 10))


def _levels(channel: BtiChannel, phase: OpPhase) -> float:
    return {"reference": 0.0, "stress": channel.stress, "recovery": channel.recovery}[phase]


def _check(channels: Sequence[BtiChannel], ops: Sequence[BtiOp]) -> int:
    """The steps of a staircase read after the input checks."""
    if not channels:
        raise CompileError("fast_bti needs at least one WGFMU channel")
    steps = {len(c.sweep) for c in channels}
    if len(steps) != 1:
        raise CompileError(f"fast_bti: every channel lists the same number of sense levels, got {sorted(steps)}")
    if not any(c.role.measure is not None for c in channels):
        raise CompileError("fast_bti: no WGFMU role measures (give the drain role measure: [I])")
    if not ops or ops[0].kind != "read" or ops[0].phase != "reference" or ops[0].cycle != 0:
        raise CompileError("fast_bti: the operations start with the reference read (cycle 0)")
    if ops[-1].kind != "read":
        raise CompileError("fast_bti: the operations end with a read")
    for before, after in pairwise(ops):
        if before.kind == after.kind:
            raise CompileError("fast_bti: reads and holds alternate")
        if after.kind == "read" and after.phase != before.phase:
            raise CompileError("fast_bti: a read returns to the level of the hold before it")
    return steps.pop()


def fast_bti(channels: Sequence[BtiChannel], ops: Sequence[BtiOp], *, timing: SenseTiming,
             read_kind: ReadKind = "staircase") -> BuiltWaveform:
    """The fast-BTI program of ``ops`` on ``channels`` (module docstring).

    Raises:
        CompileError: For unusable inputs (timing, levels, an operation order other than reference read, then
            alternating holds and reads).
    """
    if read_kind not in READ_KINDS:
        raise CompileError(f"read_kind must be one of {list(READ_KINDS)}, got {read_kind!r}")
    steps = _check(channels, ops)
    tm = _Timing(timing)
    patterns: dict[str, Pattern] = {}
    events: list[WaveformEvent] = []
    sequences: dict[int, list[tuple[str, float]]] = {}
    setups = {}
    for channel in channels:
        role = channel.role
        name = role.role
        reads = {"reference": _read_pattern(0.0, channel.sweep, tm)}
        sense = channel.sweep if read_kind == "staircase" else [channel.spot]
        entries: list[tuple[str, float]] = []
        level = 0.0
        for op in ops:
            if op.kind == "read":
                key = {"reference": "ref", "stress": "rs", "recovery": "rr"}[op.phase]
                pattern_name = f"{name}_{key}"
                if pattern_name not in patterns:
                    pattern = reads[op.phase] if op.phase == "reference" else _read_pattern(_levels(channel, op.phase),
                                                                                           sense, tm)
                    patterns[pattern_name] = pattern
                    if role.measure is not None:
                        points = len(pattern.vectors) // 2
                        events.append(MeasureEvent(pattern=pattern_name, event=READ_EVENT,
                                                   t=_s(tm.edge + tm.settle), points=points,
                                                   interval=_s(tm.edge + tm.width), average=_s(tm.width - tm.settle)))
            else:
                pattern_name = f"{name}_h{op.cycle}"
                target = _levels(channel, op.phase)
                patterns[pattern_name] = _hold_pattern(level, target, op.seconds, tm)
                if role.measure is not None:
                    hold = _ticks_of(op.seconds, "hold")
                    average = monitor_average_ticks(hold)
                    events.append(MeasureEvent(pattern=pattern_name, event=MONITOR_EVENT, t=_s(hold - average),
                                               points=1, interval=_s(average), average=_s(average)))
                level = target
            entries.append((pattern_name, 1.0))
        patterns[f"{name}_tail"] = Pattern(v0=level, vectors=[(_s(tm.edge), 0.0)])
        entries.append((f"{name}_tail", 1.0))
        sequences[role.channel] = entries
        all_levels = [0.0, channel.stress, channel.recovery, *channel.sweep, channel.spot]
        setups[role.channel] = _setup(role, all_levels)
    if steps < 1 or (read_kind == "staircase" and steps > (WGFMU_SPEC.max_vectors - 1) // 2):
        raise CompileError(f"fast_bti: {steps} sense steps do not fit one pattern of "
                           f"{WGFMU_SPEC.max_vectors} vectors")
    program = _program(FAST_BTI, channels=setups, patterns=patterns, events=events, sequences=sequences)
    return BuiltWaveform(program=program)


# -- runs and data ---------------------------------------------------------------------------------------------------


def entry_seconds(program: WaveformProgram, ch: int) -> list[float]:
    """Output time (s) of every sequence entry of channel ``ch``."""
    return [round(count) * program.patterns[name].duration_s for name, count in program.sequences.get(ch, [])]


def batches(program: WaveformProgram, ops: Sequence[BtiOp], *, batch_s: float = BATCH_S) -> list[tuple[int, int]]:
    """Entry ranges ``[start, stop)`` of the WGFMU executions (module docstring): each ends after a read and lasts at
    most ``batch_s`` of sequencer time unless its one hold is longer; the last includes the tail entry."""
    ch = min(program.sequences)
    times = entry_seconds(program, ch)
    out: list[tuple[int, int]] = []
    start, used = 0, times[0]
    index = 1
    while index < len(ops):
        pair = times[index] + times[index + 1] + 2 * WGFMU_SEQUENCE_GAP_S
        if used + pair > batch_s:
            out.append((start, index))
            start, used = index, pair - WGFMU_SEQUENCE_GAP_S
        else:
            used += pair
        index += 2
    out.append((start, len(times)))
    return out


def slice_program(program: WaveformProgram, start: int, stop: int) -> WaveformProgram:
    """The entries ``[start, stop)`` of every channel's sequence with the patterns and events they use."""
    sequences = {ch: items[start:stop] for ch, items in program.sequences.items()}
    used = {name for items in sequences.values() for name, _ in items}
    return program.model_copy(update={
        "patterns": {name: p for name, p in program.patterns.items() if name in used},
        "events": [e for e in program.events if e.pattern in used],
        "sequences": sequences,
    })


def entry_values(program: WaveformProgram, ch: int) -> list[int]:
    """Values channel ``ch`` stores per sequence entry (one per read step, one per hold, none for the tail)."""
    return [round(count) * sum(e.data_points for e in program.measure_events(name))
            for name, count in program.sequences.get(ch, [])]


__all__ = ["BATCH_S", "FAST_BTI", "MIN_FIRST_READ_S", "MONITOR_AVERAGE_S", "BtiChannel", "BtiOp", "SenseTiming",
           "batches", "entry_seconds", "entry_values", "fast_bti", "monitor_average_ticks", "read_seconds",
           "slice_program"]

