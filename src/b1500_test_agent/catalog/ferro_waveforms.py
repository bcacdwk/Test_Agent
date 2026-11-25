"""WGFMU waveform builders ``pund`` and ``program_read`` (blueprint v2 2.7.1; 3.4 rows ``fecap.pund``,
``fefet.fast_program_read``; WP10.6) and the pattern pieces the WGFMU path of kind ``pulse_read`` builds its
executions from (``catalog/kinds/pulse_wgfmu.py``). Pure and deterministic like ``catalog/waveforms.py``, which lists
both builders in ``BUILDERS`` (the module is separate only to keep that one small). Times lie on the WGFMU's 10 ns
grid (WG p125 (4-55)); a time that does not is rounded (``waveforms.on_grid_s``) and one that rounds to nothing is a
compile error.

**PUND** (positive-up-negative-down; the switching-current method of the ferroelectric capacitor, knowledge 04): the
forcing channel (the top electrode) outputs, from 0 V, an optional *preset* pulse of the negative polarity (it poles
the film into the negative remanent state, so P switches it), then the pulses ``P`` (+A), ``U`` (+A), ``N`` (-A),
``D`` (-A). Every pulse is a trapezoid: ``rise`` from 0 V to the level, ``top`` flat (0 = a triangle), ``rise`` back
to 0 V, then ``delay`` at 0 V before the next pulse. Every other WGFMU channel holds 0 V (the virtual ground of the
current measurement on the bottom electrode). Each measuring channel samples every measured pulse contiguously:
one measure event per pulse (named ``P``, ``U``, ``N``, ``D``) from the pulse start, ``points = (2 rise + top) /
interval`` points every ``interval``, each averaged over the whole ``interval``, so the sum of the readings times
``interval`` is the charge the pulse moved (``analysis/pund.py``). The pulse span must be a whole number (>= 4) of
intervals. ``P`` and ``U`` see the same voltage, so ``I_P - I_U`` is the switching current (2 Pr on its integral).

**Program/read** (``program_read``: the FeFET's microsecond program and fast read in ONE sequencer run): the gate
channel outputs per operation of the sequence (``erase``, ``program``) ``count`` trapezoid pulses (``lead`` to the
level, ``width`` flat, ``trail`` back to ``base``, the rest of ``period`` at ``base``) and then a read: per read
level ``edge`` to the level and ``width`` flat (a staircase, ``SenseTiming``), then ``edge`` back to ``base``; every
other WGFMU channel holds its pulse level (``pulse_bias``, default 0 V) during the pulses and its read level ``v``
(e.g. the drain's 50 mV) during the reads. Each measuring channel takes one point per read step, averaged over the
step's flat ``width`` minus ``settle``. Patterns: an optional reference read ``<role>_ref`` (event ``read``) and the
cycle ``<role>_cycle`` (per operation its pulses and its read, event = the operation's name), repeated ``cycles``
times by the sequence count; with a non-zero rest level a ``<role>_lead``/``<role>_tail`` entry ramps from and to
0 V. The read follows the pulse after the rest of its period only, microseconds instead of the milliseconds of a
pulse source and an SMU read.

**Pieces** (``pulse_wgfmu``): ``op_vectors`` (``count`` pulses as one period, the sequence repeats it),
``burst_vectors`` (one bipolar program/erase cycle: the second pulse half a period after the first), ``read_vectors``
(the staircase read), ``pund_vectors`` (the PUND read) and ``hold_vectors`` (a constant level for a time).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

from pydantic import Field

from b1500_test_agent.catalog.fast_bti import SenseTiming
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.catalog.waveforms import (
    HOLD_VECTOR_MAX_S,
    MAX_AVERAGE_S,
    TICK_S,
    BuiltWaveform,
    WgRole,
    _merge,
    _program,
    _setup,
    _train,
    on_grid_s,
    ticks,
)
from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.sources import MeasureEvent, Pattern, PulseTrain, WaveformEvent

PUND: Final = "pund"
PROGRAM_READ: Final = "program_read"

PUND_EVENTS: Final = ("P", "U", "N", "D")
"""The measured pulses of a PUND sequence, in output order (event names)."""

PRESET: Final = "preset"
MIN_PUND_POINTS: Final = 4
"""Fewest points per measured PUND pulse (the switching peak needs a few points on each side)."""

READ_EVENT: Final = "read"
"""Event of the reference read of ``program_read`` (table phase ``read``, cycle 0)."""

OpName = Literal["program", "erase"]
Vector = tuple[float, float]


def _s(count: int) -> float:
    return count * TICK_S


def _ticks(seconds: float, what: str, *, minimum: int = 1) -> int:
    return ticks(on_grid_s(seconds, what, minimum=minimum))


def _real(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CompileError(f"{what} must be a number, got {value!r}")
    return float(value)


# -- pieces ----------------------------------------------------------------------------------------------------------


class PulseShape(StrictModel):
    """Trapezoid pulses of an operation: ``lead``/``trail`` transition times, ``base`` level between pulses (V)."""

    base: float = 0.0
    lead: float = Field(gt=0)
    trail: float = Field(gt=0)


def op_vectors(level: float, width: float, period: float, shape: PulseShape) -> list[Vector]:
    """One pulse period from ``shape.base``: ``lead`` to ``level``, ``width`` flat, ``trail`` back to the base, the
    rest of ``period`` at the base (the sequence count repeats it).

    Raises:
        CompileError: If the period does not exceed lead + width + trail by at least 10 ns.
    """
    lead, flat, trail = (_ticks(shape.lead, "lead"), _ticks(width, "width"), _ticks(shape.trail, "trail"))
    rest = _ticks(period, "period") - lead - flat - trail
    if rest < 1:
        raise CompileError(f"period {period:g} s must exceed lead + width + trail = {_s(lead + flat + trail):g} s "
                           "(the pulse returns to its base before the next one)")
    return [(_s(lead), level), (_s(flat), level), (_s(trail), shape.base), (_s(rest), shape.base)]


def burst_vectors(first: tuple[float, float], second: tuple[float, float], period: float,
                  shape: PulseShape) -> list[Vector]:
    """One bipolar cycle: the ``first`` ``(level, width)`` pulse at the start of ``period``, the ``second`` half a
    period later (each a trapezoid of ``shape`` back to its base).

    Raises:
        CompileError: If a pulse does not fit its half period.
    """
    total = _ticks(period, "cycle_period")
    halves = (total // 2, total - total // 2)
    out: list[Vector] = []
    for (level, width), half in zip((first, second), halves, strict=True):
        try:
            out += op_vectors(level, width, _s(half), shape)
        except CompileError:
            need = _ticks(shape.lead, "lead") + _ticks(width, "width") + _ticks(shape.trail, "trail") + 1
            raise CompileError(f"a cycle period of {period:g} s is too short for a pulse of {width:g} s: each half "
                               f"period needs at least {_s(need):g} s (lead + width + trail + 10 ns), so the cycle "
                               f"period must be at least {_s(2 * need):g} s") from None
    return out


def read_vectors(levels: Sequence[float], end: float, timing: SenseTiming) -> list[Vector]:
    """A staircase read: per level ``edge`` to it and ``width`` flat, then ``edge`` to ``end`` (fast_bti's sense
    shape)."""
    edge, width = _ticks(timing.edge, "edge"), _ticks(timing.width, "width")
    vectors: list[Vector] = []
    for level in levels:
        vectors += [(_s(edge), level), (_s(width), level)]
    vectors.append((_s(edge), end))
    return vectors


def read_event(pattern: str, event: str, offset: float, steps: int, timing: SenseTiming) -> MeasureEvent:
    """The measure event of a staircase read starting ``offset`` seconds into ``pattern``: one point per step,
    averaged over the step's ``width`` minus ``settle``.

    Raises:
        CompileError: For timing that leaves no averaging window or one longer than the WGFMU averages.
    """
    edge, width = _ticks(timing.edge, "edge"), _ticks(timing.width, "width")
    settle = _ticks(timing.settle, "settle", minimum=0)
    if width - settle < 1:
        raise CompileError(f"read width {_s(width):g} s leaves no averaging window after settle {_s(settle):g} s")
    if width - settle > ticks(MAX_AVERAGE_S):
        raise CompileError(f"read width - settle = {_s(width - settle):g} s exceeds the longest averaging time "
                           f"{MAX_AVERAGE_S:g} s")
    return MeasureEvent(pattern=pattern, event=event, t=_s(ticks(offset) + edge + settle), points=steps,
                        interval=_s(edge + width), average=_s(width - settle))


def hold_vectors(level: float, seconds: float) -> list[Vector]:
    """``level`` for ``seconds`` (vectors of at most ``HOLD_VECTOR_MAX_S``, the library's longest vector)."""
    total = _ticks(seconds, "hold")
    limit = ticks(HOLD_VECTOR_MAX_S)
    out: list[Vector] = []
    while total > 0:
        step = min(total, limit)
        out.append((_s(step), level))
        total -= step
    return out


def duration_ticks(vectors: Sequence[Vector]) -> int:
    """Length of ``vectors`` in 10 ns ticks."""
    return sum(ticks(dt) for dt, _ in vectors)


# -- PUND ------------------------------------------------------------------------------------------------------------


class PundTiming(StrictModel):
    """A PUND sequence (module docstring): ``amplitude`` (V, > 0), ``rise`` and ``top`` (s; ``top`` 0 = triangular
    pulses), ``delay`` at 0 V after each pulse, sampling ``interval`` (s; averaging = interval) and ``preset``."""

    amplitude: float = Field(gt=0)
    rise: float = Field(gt=0)
    top: float = Field(default=0.0, ge=0)
    delay: float = Field(gt=0)
    interval: float = Field(gt=0)
    preset: bool = True

    def pulses(self) -> list[tuple[str, float]]:
        """``(name, level)`` of every pulse in output order (the preset first when set)."""
        a = self.amplitude
        return [*([(PRESET, -a)] if self.preset else []), ("P", a), ("U", a), ("N", -a), ("D", -a)]


class _PundTicks:
    """``PundTiming`` in ticks, checked (module docstring)."""

    def __init__(self, timing: PundTiming) -> None:
        self.rise = _ticks(timing.rise, "rise")
        self.top = _ticks(timing.top, "top", minimum=0)
        self.delay = _ticks(timing.delay, "delay")
        self.interval = _ticks(timing.interval, "interval")
        span = 2 * self.rise + self.top
        self.points, rest = divmod(span, self.interval)
        if rest:
            raise CompileError(f"a PUND pulse lasts 2 x rise + top = {_s(span):g} s, which is not a whole number of "
                               f"sampling intervals {_s(self.interval):g} s")
        if self.points < MIN_PUND_POINTS:
            raise CompileError(f"a PUND pulse of {_s(span):g} s gives {self.points} points at {_s(self.interval):g} "
                               f"s; use an interval of at most {_s(span // MIN_PUND_POINTS):g} s")
        if self.interval > ticks(MAX_AVERAGE_S):
            raise CompileError(f"interval {_s(self.interval):g} s exceeds the longest averaging time "
                               f"{MAX_AVERAGE_S:g} s")
        if timing.amplitude > WGFMU_SPEC.max_abs_v:
            raise CompileError(f"PUND amplitude {timing.amplitude:g} V exceeds the WGFMU's {WGFMU_SPEC.max_abs_v:g} V")

    @property
    def span(self) -> int:
        return 2 * self.rise + self.top

    @property
    def period(self) -> int:
        return self.span + self.delay


def pund_vectors(timing: PundTiming) -> tuple[list[Vector], dict[str, int]]:
    """The forcing channel's PUND vectors from 0 V and the start tick of each pulse by name (module docstring)."""
    tk = _PundTicks(timing)
    vectors: list[Vector] = []
    starts: dict[str, int] = {}
    at = 0
    for name, level in timing.pulses():
        starts[name] = at
        vectors.append((_s(tk.rise), level))
        if tk.top:
            vectors.append((_s(tk.top), level))
        vectors += [(_s(tk.rise), 0.0), (_s(tk.delay), 0.0)]
        at += tk.period
    return vectors, starts


def pund_events(pattern: str, timing: PundTiming, *, offset: float = 0.0) -> list[MeasureEvent]:
    """The four measure events of a PUND sequence starting ``offset`` seconds into ``pattern``."""
    tk = _PundTicks(timing)
    _, starts = pund_vectors(timing)
    base = ticks(offset)
    return [MeasureEvent(pattern=pattern, event=name, t=_s(base + starts[name]), points=tk.points,
                         interval=_s(tk.interval), average=_s(tk.interval)) for name in PUND_EVENTS]


def pund_trains(timing: PundTiming, *, repeat: int = 1) -> list[PulseTrain]:
    """The PUND pulses as nominal trains (positive: P, U; negative: N, D and the preset), ``repeat`` sequences:
    width = rise + top (the time above half the amplitude), period = 2 rise + top + delay."""
    tk = _PundTicks(timing)
    width, period, rise = _s(tk.rise + tk.top), _s(tk.period), _s(tk.rise)
    positive = _train(0.0, timing.amplitude, width, period, rise, 2)
    negative = _train(0.0, -timing.amplitude, width, period, rise, 3 if timing.preset else 2)
    return [t.model_copy(update={"repeat": repeat}) for t in (positive, negative)]


def pund_seconds(timing: PundTiming) -> float:
    """Output time of one PUND sequence (s)."""
    tk = _PundTicks(timing)
    return _s(tk.period * len(timing.pulses()))


def pund(force: WgRole, others: Sequence[WgRole], timing: PundTiming) -> BuiltWaveform:
    """The PUND program (module docstring): ``force`` outputs the sequence, ``others`` hold 0 V; every measuring role
    samples the four measured pulses (events ``P``, ``U``, ``N``, ``D``).

    Raises:
        CompileError: For unusable timing or levels, or when no role measures.
    """
    vectors, _ = pund_vectors(timing)
    total = duration_ticks(vectors)
    patterns = {force.role: Pattern(v0=0.0, vectors=vectors)}
    channels = {force.channel: _setup(force, [0.0, timing.amplitude, -timing.amplitude])}
    for role in others:
        patterns[role.role] = Pattern(v0=0.0, vectors=hold_vectors(0.0, _s(total)))
        channels[role.channel] = _setup(role, [0.0])
    events: list[WaveformEvent] = []
    for role in (force, *others):
        if role.measure is not None:
            events += pund_events(role.role, timing)
    if not events:
        raise CompileError("pund: no role measures (give the bottom electrode's role measure: [I])")
    sequences = {r.channel: [(r.role, 1.0)] for r in (force, *others)}
    program = _program(PUND, channels=channels, patterns=patterns, events=events, sequences=sequences)
    return BuiltWaveform(program=program, pulses={force.channel: pund_trains(timing)})


# -- program_read ----------------------------------------------------------------------------------------------------


class ReadChannel(StrictModel):
    """A non-gate WGFMU channel of ``program_read``: its role, read level ``v`` and pulse level (V)."""

    role: WgRole
    read_level: float = 0.0
    pulse_level: float = 0.0


class ProgramOp(StrictModel):
    """One operation of ``program_read``: its name (the table phase of the read after it), level (V), width (s)."""

    name: OpName
    level: float
    width: float = Field(gt=0)


def program_read(gate: WgRole, others: Sequence[ReadChannel], *, sweep: Sequence[float], ops: Sequence[ProgramOp],
                 shape: PulseShape, period: float, count: int, timing: SenseTiming, cycles: int,
                 initial_read: bool = True) -> BuiltWaveform:
    """The fast program/read program (module docstring).

    Raises:
        CompileError: For unusable timing, levels or counts, an operation named twice, or when no role measures.
    """
    if not ops:
        raise CompileError("program_read needs at least one operation (program or erase)")
    if len({op.name for op in ops}) != len(ops):
        raise CompileError("program_read: each operation appears once per cycle")
    if not sweep:
        raise CompileError("program_read: the read needs at least one gate level")
    for name, value in (("count", count), ("cycles", cycles)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise CompileError(f"{name} must be a positive integer, got {value!r}")
    rests = {gate.role: shape.base, **{c.role.role: c.pulse_level for c in others}}
    reads = {gate.role: list(sweep), **{c.role.role: [c.read_level] * len(sweep) for c in others}}
    roles = [gate, *(c.role for c in others)]
    patterns: dict[str, Pattern] = {}
    events: list[WaveformEvent] = []
    sequences: dict[int, list[tuple[str, float]]] = {}
    ramp = any(level != 0.0 for level in rests.values())
    edge = _s(_ticks(timing.edge, "edge"))
    for role in roles:
        name, rest = role.role, rests[role.role]
        read = read_vectors(reads[name], rest, timing)
        cycle: list[Vector] = []
        offsets: dict[str, float] = {}
        for op in ops:
            pulse = op_vectors(op.level, op.width, period, shape)
            cycle += pulse * count if role is gate else hold_vectors(rest, _s(duration_ticks(pulse) * count))
            offsets[op.name] = _s(duration_ticks(cycle))
            cycle += read
        entries: list[tuple[str, float]] = []
        if ramp:
            patterns[f"{name}_lead"] = Pattern(v0=0.0, vectors=[(edge, rest)])
            entries.append((f"{name}_lead", 1.0))
        if initial_read:
            patterns[f"{name}_ref"] = Pattern(v0=rest, vectors=read)
            entries.append((f"{name}_ref", 1.0))
        patterns[f"{name}_cycle"] = Pattern(v0=rest, vectors=cycle)
        entries.append((f"{name}_cycle", float(cycles)))
        if ramp:
            patterns[f"{name}_tail"] = Pattern(v0=rest, vectors=[(edge, 0.0)])
            entries.append((f"{name}_tail", 1.0))
        sequences[role.channel] = entries
        if role.measure is not None:
            if initial_read:
                events.append(read_event(f"{name}_ref", READ_EVENT, 0.0, len(sweep), timing))
            events += [read_event(f"{name}_cycle", op_name, offset, len(sweep), timing)
                       for op_name, offset in offsets.items()]
    if not events:
        raise CompileError("program_read: no role measures (give the drain role measure: [I])")
    setups = {gate.channel: _setup(gate, [0.0, shape.base, *sweep, *(op.level for op in ops)])}
    for c in others:
        setups[c.role.channel] = _setup(c.role, [0.0, c.read_level, c.pulse_level])
    program = _program(PROGRAM_READ, channels=setups, patterns=patterns, events=events, sequences=sequences)
    trains = _merge([_train(shape.base, op.level, _s(_ticks(op.width, "width")), _s(_ticks(period, "period")),
                            shape.lead, count).model_copy(update={"trail_s": shape.trail, "repeat": cycles})
                     for op in ops])
    return BuiltWaveform(program=program, pulses={gate.channel: trains}, cycle_by="op",
                         phases={READ_EVENT: "read", **{op.name: op.name for op in ops}})


__all__ = ["MIN_PUND_POINTS", "PRESET", "PROGRAM_READ", "PUND", "PUND_EVENTS", "READ_EVENT", "ProgramOp",
           "PulseShape", "PundTiming", "ReadChannel", "burst_vectors", "duration_ticks", "hold_vectors", "op_vectors",
           "program_read", "pund", "pund_events", "pund_seconds", "pund_trains", "pund_vectors", "read_event",
           "read_vectors"]
