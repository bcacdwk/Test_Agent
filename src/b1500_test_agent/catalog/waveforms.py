"""WGFMU waveform builders (blueprint v2 2.7.1; WP10.4): pure, deterministic functions that turn the inputs of a
recipe (levels, times, CSV tables) into the typed ``WaveformProgram`` of ``models/sources.py`` that rule R-WG-02
checks, the ``OutputGuard`` admits vector by vector and the WGFMU driver loads. No I/O: a ``file`` parameter's bytes
are read by the kind through ``catalog.files.read_param_file`` (sha256 re-verified) and handed in.

Time: every vector time, event time, interval and average lies on the WGFMU's 10 ns grid (WG p125 (4-55)); the
builders round to it (the library would round too, WG p126 (4-56)) and refuse a time that rounds to zero. Channels run
their sequences side by side from the same start; a channel repeats a pattern without delay and spends 50 ns between
two different sequence entries (10 ns at the last level, 40 ns at the next initial level; WG p80 (4-10)). Ranges: each
channel gets the smallest force range that holds every level it outputs (3 V, 5 V, -10..0 V, 0..10 V; WG p123
(4-53)), a voltage-measuring channel the 5 V or 10 V measurement range, a current-measuring channel the recipe's
range (Table 4-9, WG p142 (4-72)).

Builders (``BUILDERS``; the other names of blueprint 2.7.1 arrive with WP10.5-10.7):

- ``pulsed_iv``: one pulse per level on the pulsed channel (base -> level in ``edge``, ``width`` flat top, back to
  base in ``edge``, rest of the ``period`` at base), the other channels hold their bias; every measuring channel takes
  one averaged point per pulse over the flat top minus ``settle`` at both ends (WG Ex. 9 timing, pulsed).
- ``pulse_train``: ``count`` identical pulses (one pattern repeated by the sequence count) with ``samples`` contiguous
  averaged points per pulse over the flat top minus ``settle``.
- ``fast_iv_ramp``: the ramped channel ramps start -> stop in ``ramp`` (and back with ``double``) ``cycles`` times;
  the measuring channels sample every ``interval`` with averaging over the whole interval (events ``up``/``down``).
- ``dc_spot``: DC mode (no sequencer): every channel forces its level(s) with ``WGFMU_dcforceVoltage`` step by step
  (``WaveformProgram.dc``; WG p89 (4-19)).
- ``table``: the lab's CSV layout (lwp ``LFN_noise_meas.cpp``): per channel a waveform file of absolute-time rows
  ``t,level`` (first time 0, strictly increasing; ``#`` comments, blank lines and one header row skipped) giving the
  initial level and one vector per further row; one events file of rows ``t,points,interval,average,range1,range2,..``
  (one range column per channel in role order; 0 = no change; 1..5 = 1 uA, 10 uA, 100 uA, 1 mA, 10 mA). Every row
  with ``points`` > 0 is a measurement event ``E<row>`` on every measuring channel's pattern, averaged when
  ``average`` > 0, else raw. A range code applies from the row's time: at time 0 it is the channel's initial
  current range (a range event there would fall inside the first averaging window, which the library forbids, WG
  p128 (4-58)); later it is a range event ``E<row>r`` (rule R-WG-02 checks it lies outside every averaging window).

Data layout (``point_layout``): the values a channel stores, in the library's order (every repeat of every sequence
entry; inside one repeat the events by start time, each event's points in turn; a RAW point gives ``1 + average / 5
ns`` values every 5 ns), with the event name, the repeat index, the point index inside its event, the start and the
current range of each value. ``program_levels`` evaluates the programmed output of a channel at any time (the table's
source columns).
"""

from __future__ import annotations

import csv
import io
import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
from pydantic import Field, ValidationError

from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.sources import (
    WGFMU_GRID_S,
    ChannelSetup,
    MeasureEvent,
    Pattern,
    PulseTrain,
    RangeEvent,
    WaveformEvent,
    WaveformProgram,
    WgfmuCurrentRange,
    WgfmuForceRange,
    WgfmuMode,
    WgfmuVoltageRange,
)

BUILDERS: Final = ("pulse_train", "pulsed_iv", "fast_iv_ramp", "dc_spot", "table")
"""The builders this module implements (blueprint v2 2.7.1 lists ``dc_sample``, ``pund``, ``program_read`` and
``fast_bti`` too: WP10.5-10.7)."""

TICK_S: Final = WGFMU_GRID_S
GAP_HOLD_TICKS: Final = 1
GAP_TICKS: Final = 5
"""Between two different sequence entries: 10 ns at the last level, then 40 ns at the next initial level."""

MAX_AVERAGE_S: Final = WGFMU_SPEC.average_s[1]
"""Longest averaging time of one point (about 20.97 ms, WG p126 (4-56))."""

RANGE_CODES: Final[dict[int, WgfmuCurrentRange]] = {1: "1ua", 2: "10ua", 3: "100ua", 4: "1ma", 5: "10ma"}
"""Events-file range codes: ``WGFMU_MEASURE_CURRENT_RANGE_*`` 6001..6005 minus 6000 (Table 4-9, WG p142 (4-72)), as
the lab's code writes them."""

FORCE_RANGES: Final[tuple[WgfmuForceRange, ...]] = ("3v", "5v", "-10v", "10v")
"""Force ranges from the finest; a channel takes the first that holds all its levels."""

TABLE_MAX_ROWS: Final = 4096
"""Most rows of one waveform or events file (a pattern holds at most 2,048 vectors; R-WG-02 blocks longer ones)."""

Quantity = Literal["V", "I"]
CycleBy = Literal["repeat", "point", "none"]


def ticks(seconds: float) -> int:
    """``seconds`` in 10 ns ticks, rounded to the nearest (the library rounds 32 ns to 30 ns, WG p126 (4-56))."""
    return math.floor(seconds / TICK_S + 0.5)


def on_grid_s(seconds: float, what: str, *, minimum: int = 1) -> float:
    """``seconds`` rounded to the 10 ns grid (at least ``minimum`` ticks).

    Raises:
        CompileError: If the value is not finite or rounds below ``minimum`` ticks.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or not math.isfinite(seconds):
        raise CompileError(f"{what} must be a finite time in seconds, got {seconds!r}")
    count = ticks(float(seconds))
    if count < minimum:
        raise CompileError(f"{what} {seconds:g} s is shorter than {minimum} x 10 ns on the WGFMU grid")
    return count * TICK_S


def force_range_for(levels: Iterable[float]) -> WgfmuForceRange:
    """The finest force range that holds every level (WG p123 (4-53)).

    Raises:
        CompileError: If the levels span more than one 10 V range (e.g. -6 V and +6 V).
    """
    values = list(levels) or [0.0]
    for name in FORCE_RANGES:
        low, high = WGFMU_SPEC.force_ranges[name]
        if all(low <= v <= high for v in values):
            return name
    raise CompileError(f"levels {min(values):g}..{max(values):g} V fit no WGFMU force range (3 V, 5 V, -10..0 V, "
                       "0..10 V)")


def voltage_range_for(levels: Iterable[float]) -> WgfmuVoltageRange:
    """The voltage measurement range of a channel measuring its own output: 5 V when every level is within +-5 V."""
    return "5v" if max((abs(v) for v in levels), default=0.0) <= 5.0 else "10v"


# -- inputs and output -----------------------------------------------------------------------------------------------


class WgRole(StrictModel):
    """One WGFMU role of a builder: recipe role, bound channel, what it measures (``None`` = measurement disabled)
    and, for a current measurement, its (initial) current range."""

    role: str = Field(min_length=1)
    channel: Channel
    measure: Quantity | None = None
    current_range: WgfmuCurrentRange = "1ma"


class BuiltWaveform(StrictModel):
    """What a builder returns: the program, the nominal pulse trains of its pulse channels (``SourcePlan.pulses``),
    the sweep segment of each measure event (``fwd``/``rev``; ``fast_iv_ramp``) and what the table's ``cycle`` column
    counts (``repeat``: the sequence repeat of a pattern, ``point``: the point of an event, one per pulse; ``none``)."""

    program: WaveformProgram
    pulses: dict[Channel, list[PulseTrain]] = Field(default_factory=dict)
    segments: dict[str, Literal["fwd", "rev"]] = Field(default_factory=dict)
    cycle_by: CycleBy = "none"


def _setup(role: WgRole, levels: Sequence[float], mode: WgfmuMode = "fastiv",
           current_range: WgfmuCurrentRange | None = None) -> ChannelSetup:
    measure = "current" if role.measure == "I" else "voltage"
    return ChannelSetup(
        mode=mode, force_range=force_range_for(levels), measure=measure,
        current_range=(current_range or role.current_range) if measure == "current" else None,
        voltage_range=voltage_range_for(levels) if measure == "voltage" else None,
        measure_enabled=role.measure is not None)


def _program(builder: str, **fields: object) -> WaveformProgram:
    try:
        return WaveformProgram.model_validate({"builder": builder, **fields})
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise CompileError(f"{builder}: the waveform program is not valid ({problems})") from None


def _train(base: float, peak: float, width: float, period: float, edge: float, count: int) -> PulseTrain:
    try:
        return PulseTrain(base_v=base, peak_v=peak, width_s=width, period_s=period, lead_s=edge, trail_s=edge,
                          count=count)
    except ValidationError as exc:
        raise CompileError(f"pulse train not valid: {exc.errors()[0]['msg']}") from None


def _merge(trains: Sequence[PulseTrain]) -> list[PulseTrain]:
    """Identical trains merged into one with ``repeat`` = occurrences (first-seen order)."""
    found: list[tuple[PulseTrain, int]] = []
    for train in trains:
        for index, (known, times) in enumerate(found):
            if known == train:
                found[index] = (known, times + 1)
                break
        else:
            found.append((train, 1))
    return [t.model_copy(update={"repeat": times}) if times > 1 else t for t, times in found]


def _s(count: int) -> float:
    """``count`` ticks in seconds (exactly a grid value)."""
    return count * TICK_S


@dataclass(frozen=True)
class _Timing:
    """Pulse timing in ticks: flat top ``width``, ``period``, transition ``edge`` and ``settle`` (from each edge to
    the averaging window)."""

    width: int
    period: int
    edge: int
    settle: int

    @property
    def window(self) -> int:
        """Ticks of the flat top left for averaging: ``width - 2 settle``."""
        return self.width - 2 * self.settle

    @property
    def off(self) -> int:
        """Ticks at base per period: ``period - width - 2 edge``."""
        return self.period - self.width - 2 * self.edge


def _pulse_timing(width: float, period: float, edge: float, settle: float) -> _Timing:
    timing = _Timing(width=ticks(on_grid_s(width, "width")), period=ticks(on_grid_s(period, "period")),
                     edge=ticks(on_grid_s(edge, "edge")), settle=ticks(on_grid_s(settle, "settle", minimum=0)))
    if timing.off < 1:
        raise CompileError(f"period {_s(timing.period):g} s must exceed width + 2 x edge = "
                           f"{_s(timing.width + 2 * timing.edge):g} s (the pulse returns to base before the next one)")
    if timing.window < 1:
        raise CompileError(f"width {_s(timing.width):g} s leaves no averaging window after settle "
                           f"{_s(timing.settle):g} s at both ends (need width > 2 x settle + 10 ns)")
    return timing


# -- pulsed_iv -------------------------------------------------------------------------------------------------------


def pulsed_iv(pulsed: WgRole, biases: Sequence[tuple[WgRole, float]], *, base: float, levels: Sequence[float],
              width: float, period: float, edge: float, settle: float) -> BuiltWaveform:
    """One pulse per level on ``pulsed`` with ``biases`` held, one averaged point per pulse (module docstring).

    Timeline: every channel starts at 0 V and reaches its base/bias in ``edge``; after ``settle`` the first pulse
    rises; after the last pulse every channel returns to 0 V in ``edge``.

    Raises:
        CompileError: For timing that leaves no averaging window, too many levels or unusable values.
    """
    if not levels:
        raise CompileError("pulsed_iv needs at least one pulse level")
    tm = _pulse_timing(width, period, edge, settle)
    hold = max(tm.settle, 1)
    vectors: list[tuple[float, float]] = [(_s(tm.edge), base), (_s(hold), base)]
    for level in levels:
        vectors += [(_s(tm.edge), level), (_s(tm.width), level), (_s(tm.edge), base), (_s(tm.off), base)]
    vectors.append((_s(tm.edge), 0.0))
    body = hold + len(levels) * tm.period  # ticks between the two 0 V transitions
    patterns = {pulsed.role: Pattern(v0=0.0, vectors=vectors)}
    channels = {pulsed.channel: _setup(pulsed, [0.0, base, *levels])}
    for role, level in biases:
        patterns[role.role] = Pattern(v0=0.0, vectors=[(_s(tm.edge), level), (_s(body), level), (_s(tm.edge), 0.0)])
        channels[role.channel] = _setup(role, [0.0, level])
    average = _s(min(tm.window, ticks(MAX_AVERAGE_S)))
    start = _s(tm.edge + hold + tm.edge + tm.settle)
    events: list[WaveformEvent] = [
        MeasureEvent(pattern=r.role, event="plateau", t=start, points=len(levels), interval=_s(tm.period),
                     average=average)
        for r in (pulsed, *(b for b, _ in biases)) if r.measure is not None]
    if not events:
        raise CompileError("pulsed_iv: no role measures (give the drain role measure: [I])")
    sequences = {r.channel: [(r.role, 1.0)] for r in (pulsed, *(b for b, _ in biases))}
    program = _program("pulsed_iv", channels=channels, patterns=patterns, events=events, sequences=sequences)
    trains = _merge([_train(base, level, _s(tm.width), _s(tm.period), _s(tm.edge), 1) for level in levels])
    return BuiltWaveform(program=program, pulses={pulsed.channel: trains}, cycle_by="point")


# -- pulse_train -----------------------------------------------------------------------------------------------------


def pulse_train(pulsed: WgRole, biases: Sequence[tuple[WgRole, float]], *, base: float, peak: float, width: float,
                period: float, edge: float, count: int, settle: float, samples: int) -> BuiltWaveform:
    """``count`` identical pulses with ``samples`` averaged points on each flat top (module docstring).

    Sequence per channel: ``lead`` (0 V -> base/bias in ``edge``, held ``settle``), the one-period pattern repeated
    ``count`` times, ``tail`` (back to 0 V in ``edge``); every channel has the same entries, so the 50 ns gaps line up.

    Raises:
        CompileError: For timing that leaves no window for ``samples`` points or unusable values.
    """
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise CompileError(f"count must be a positive integer, got {count!r}")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise CompileError(f"samples must be a positive integer, got {samples!r}")
    tm = _pulse_timing(width, period, edge, settle)
    step = tm.window // samples
    if step < 1:
        raise CompileError(f"{samples} points do not fit into the {_s(tm.window):g} s flat top left after settle "
                           f"{_s(tm.settle):g} s (at least 10 ns each)")
    interval = _s(step)
    average = _s(min(step, ticks(MAX_AVERAGE_S)))
    hold = max(tm.settle, 1)
    patterns: dict[str, Pattern] = {}
    channels: dict[int, ChannelSetup] = {}
    sequences: dict[int, list[tuple[str, float]]] = {}
    events: list[WaveformEvent] = []
    for role, low, high in ((pulsed, base, peak), *((b, v, v) for b, v in biases)):
        name = role.role
        patterns[f"{name}_lead"] = Pattern(v0=0.0, vectors=[(_s(tm.edge), low), (_s(hold), low)])
        if role is pulsed:
            body = [(_s(tm.edge), high), (_s(tm.width), high), (_s(tm.edge), low), (_s(tm.off), low)]
        else:
            body = [(_s(tm.period), low)]
        patterns[name] = Pattern(v0=low, vectors=body)
        patterns[f"{name}_tail"] = Pattern(v0=low, vectors=[(_s(tm.edge), 0.0)])
        channels[role.channel] = _setup(role, [0.0, low, high])
        sequences[role.channel] = [(f"{name}_lead", 1.0), (name, float(count)), (f"{name}_tail", 1.0)]
        if role.measure is not None:
            events.append(MeasureEvent(pattern=name, event="pulse", t=_s(tm.edge + tm.settle), points=samples,
                                       interval=interval, average=average))
    if not events:
        raise CompileError("pulse_train: no role measures (give a role measure: [I] or [V])")
    program = _program("pulse_train", channels=channels, patterns=patterns, events=events, sequences=sequences)
    trains = [_train(base, peak, _s(tm.width), _s(tm.period), _s(tm.edge), count)]
    return BuiltWaveform(program=program, pulses={pulsed.channel: trains}, cycle_by="repeat")


# -- fast_iv_ramp ----------------------------------------------------------------------------------------------------


def fast_iv_ramp(ramped: WgRole, biases: Sequence[tuple[WgRole, float]], *, start: float, stop: float, ramp: float,
                 interval: float, edge: float, settle: float, double: bool, cycles: int) -> BuiltWaveform:
    """Linear ramps start -> stop (-> start with ``double``) of ``ramp`` seconds each, ``cycles`` times, sampled every
    ``interval`` with averaging over the whole interval (module docstring); events ``up`` (segment ``fwd``) and
    ``down`` (segment ``rev``).

    Raises:
        CompileError: If ``ramp`` is not a whole number (>= 2) of intervals or a value is unusable.
    """
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
        raise CompileError(f"cycles must be a positive integer, got {cycles!r}")
    if not double and cycles > 1:
        raise CompileError("a single ramp jumps back from stop to start between cycles; use double ramps for cycles")
    ramp_t = ticks(on_grid_s(ramp, "ramp"))
    step = ticks(on_grid_s(interval, "interval"))
    edge_t = ticks(on_grid_s(edge, "edge"))
    hold = max(ticks(on_grid_s(settle, "settle", minimum=0)), 1)
    points, rest = divmod(ramp_t, step)
    if rest or points < 2:
        raise CompileError(f"ramp {_s(ramp_t):g} s must be a whole number (>= 2) of sampling intervals {_s(step):g} s")
    if step > ticks(MAX_AVERAGE_S):
        raise CompileError(f"interval {_s(step):g} s exceeds the longest averaging time {MAX_AVERAGE_S:g} s")
    patterns: dict[str, Pattern] = {}
    channels: dict[int, ChannelSetup] = {}
    sequences: dict[int, list[tuple[str, float]]] = {}
    events: list[WaveformEvent] = []
    for role, low in ((ramped, start), *((b, v) for b, v in biases)):
        name = role.role
        patterns[f"{name}_lead"] = Pattern(v0=0.0, vectors=[(_s(edge_t), low), (_s(hold), low)])
        if role is ramped:
            body = [(_s(ramp_t), stop), (_s(ramp_t), start)] if double else [(_s(ramp_t), stop)]
            end = start if double else stop
        else:
            body, end = [(_s(ramp_t * (2 if double else 1)), low)], low
        patterns[name] = Pattern(v0=low, vectors=body)
        patterns[f"{name}_tail"] = Pattern(v0=end, vectors=[(_s(edge_t), 0.0)])
        channels[role.channel] = _setup(role, [0.0, low, stop] if role is ramped else [0.0, low])
        sequences[role.channel] = [(f"{name}_lead", 1.0), (name, float(cycles)), (f"{name}_tail", 1.0)]
        if role.measure is not None:
            events.append(MeasureEvent(pattern=name, event="up", t=0.0, points=points, interval=_s(step),
                                       average=_s(step)))
            if double:
                events.append(MeasureEvent(pattern=name, event="down", t=_s(ramp_t), points=points,
                                           interval=_s(step), average=_s(step)))
    if not events:
        raise CompileError("fast_iv_ramp: no role measures (give the drain role measure: [I])")
    program = _program("fast_iv_ramp", channels=channels, patterns=patterns, events=events, sequences=sequences)
    segments: dict[str, Literal["fwd", "rev"]] = {"up": "fwd", "down": "rev"} if double else {}
    return BuiltWaveform(program=program, segments=segments, cycle_by="repeat")


# -- dc_spot ---------------------------------------------------------------------------------------------------------


def dc_spot(channels: Sequence[tuple[WgRole, Sequence[float]]]) -> BuiltWaveform:
    """DC mode on every channel (module docstring): each channel's levels, one per DC step; a channel with one level
    holds it for every step (at most one channel may list several).

    Raises:
        CompileError: Without channels, with no level, or with two channels listing several levels of different
            lengths.
    """
    if not channels:
        raise CompileError("dc_spot needs at least one WGFMU channel")
    steps = max(len(levels) for _, levels in channels)
    if any(len(levels) not in (1, steps) for _, levels in channels) or steps < 1:
        raise CompileError("dc_spot: every channel gives one level or the same number of levels")
    setups = {role.channel: _setup(role, [0.0, *levels], mode="dc") for role, levels in channels}
    dc = {role.channel: [float(v) for v in levels] * (steps if len(levels) == 1 else 1) for role, levels in channels}
    if not any(role.measure is not None for role, _ in channels):
        raise CompileError("dc_spot: no role measures (give a role measure: [I] or [V])")
    return BuiltWaveform(program=_program("dc_spot", channels=setups, dc=dc))


# -- table (lab CSV layout) ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EventRow:
    """One row of an events file: time, points, interval, average (s) and one range code per channel."""

    t: float
    points: int
    interval: float
    average: float
    ranges: tuple[int, ...]


def _rows(data: bytes, name: str) -> list[tuple[int, list[str]]]:
    """``(line number, cells)`` of a CSV file (comma or whitespace separated; ``#`` comments and blank lines out)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CompileError(f"{name} is not UTF-8 text ({exc.reason})") from None
    rows: list[tuple[int, list[str]]] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = next(csv.reader(io.StringIO(stripped))) if "," in stripped else stripped.split()
        rows.append((number, [c.strip() for c in cells]))
    if len(rows) > TABLE_MAX_ROWS + 1:
        raise CompileError(f"{name} has {len(rows)} rows, more than {TABLE_MAX_ROWS}")
    return rows


def _numbers(cells: Sequence[str]) -> list[float] | None:
    try:
        values = [float(c) for c in cells]
    except ValueError:
        return None
    return values if all(math.isfinite(v) for v in values) else None


def parse_wave_csv(data: bytes, *, name: str) -> Pattern:
    """A waveform file (module docstring) as a pattern: the first row's level is ``v0``, every further row one vector
    ``(t_i - t_(i-1), level_i)``; times are rounded to the 10 ns grid.

    Raises:
        CompileError: For a malformed file (columns, numbers, first time not 0, times not strictly increasing on the
            10 ns grid, fewer than two rows).
    """
    points: list[tuple[int, float]] = []
    for index, (number, cells) in enumerate(_rows(data, name)):
        values = _numbers(cells[:2]) if len(cells) >= 2 else None
        if values is None:
            if index == 0:
                continue  # one header row ("time,voltage")
            raise CompileError(f"{name} line {number}: expected 'time,level' numbers, got {','.join(cells)!r}")
        points.append((ticks(values[0]), values[1]))
    if len(points) < 2:
        raise CompileError(f"{name}: a waveform needs at least two rows (time 0 and one more)")
    if points[0][0] != 0:
        raise CompileError(f"{name}: the first time must be 0, got {points[0][0] * TICK_S:g} s")
    vectors: list[tuple[float, float]] = []
    for (t0, _), (t1, level) in itertools.pairwise(points):
        if t1 <= t0:
            raise CompileError(f"{name}: times must increase by at least 10 ns (at {t1 * TICK_S:g} s)")
        vectors.append(((t1 - t0) * TICK_S, level))
    return Pattern(v0=points[0][1], vectors=vectors)


def parse_events_csv(data: bytes, *, name: str, channels: int) -> list[EventRow]:
    """An events file (module docstring): rows ``t,points,interval,average`` plus one range code per channel (missing
    trailing codes are 0).

    Raises:
        CompileError: For a malformed row, a negative time, a range code outside 0..5 or more codes than channels.
    """
    rows: list[EventRow] = []
    for index, (number, cells) in enumerate(_rows(data, name)):
        values = _numbers(cells) if len(cells) >= 4 else None
        if values is None:
            if index == 0:
                continue  # one header row
            raise CompileError(f"{name} line {number}: expected t,points,interval,average[,range...] numbers")
        t, points, interval, average, *codes = values
        if len(codes) > channels:
            raise CompileError(f"{name} line {number}: {len(codes)} range columns for {channels} channels")
        if t < 0 or points < 0 or points != int(points) or interval < 0 or average < 0:
            raise CompileError(f"{name} line {number}: time, interval and average must be >= 0 and points a whole "
                               "number")
        if any(c != int(c) or int(c) not in (0, *RANGE_CODES) for c in codes):
            raise CompileError(f"{name} line {number}: range codes are 0 (none) or 1..5 (1 uA .. 10 mA)")
        ranges = tuple(int(c) for c in codes) + (0,) * (channels - len(codes))
        rows.append(EventRow(t=t, points=int(points), interval=interval, average=average, ranges=ranges))
    if not rows:
        raise CompileError(f"{name} has no event row")
    return rows


def table(waves: Sequence[tuple[WgRole, Pattern]], events: Sequence[EventRow]) -> BuiltWaveform:
    """The lab layout (module docstring): one pattern per channel (named by its role, sequence count 1), measure and
    range events from the events rows.

    Raises:
        CompileError: For unusable event timing (an interval or average that rounds to 0 where needed).
    """
    if not waves:
        raise CompileError("table needs at least one waveform")
    initial: dict[str, WgfmuCurrentRange] = {}
    program_events: list[WaveformEvent] = []
    for number, row in enumerate(events, 1):
        label = f"E{number}"
        for (role, _), code in zip(waves, row.ranges, strict=True):
            if code == 0:
                continue
            if ticks(row.t) == 0:
                initial[role.role] = RANGE_CODES[code]
            else:
                program_events.append(RangeEvent(pattern=role.role, event=f"{label}r", t=ticks(row.t) * TICK_S,
                                                 range=RANGE_CODES[code]))
        if row.points == 0:
            continue
        interval = on_grid_s(row.interval, f"events row {number} interval")
        average = on_grid_s(row.average, f"events row {number} average", minimum=0)
        for role, _ in waves:
            if role.measure is not None:
                program_events.append(MeasureEvent(pattern=role.role, event=label, t=ticks(row.t) * TICK_S,
                                                   points=row.points, interval=interval, average=average,
                                                   raw=average == 0))
    channels = {role.channel: _setup(role, pattern.levels(), current_range=initial.get(role.role))
                for role, pattern in waves}
    patterns = {role.role: pattern for role, pattern in waves}
    sequences = {role.channel: [(role.role, 1.0)] for role, _ in waves}
    program = _program("table", channels=channels, patterns=patterns, events=program_events, sequences=sequences)
    return BuiltWaveform(program=program)


# -- data layout and programmed levels -------------------------------------------------------------------------------


@dataclass(frozen=True)
class PointLayout:
    """Per stored value of one channel, in the library's value order (module docstring): ``event`` name, ``repeat``
    (sequence repeat of its pattern), ``point`` (index inside its event), ``start_s`` (start of its averaging window
    or raw sample, s from the run start), ``average_s`` and ``range`` (active current range; ``None`` for a voltage
    channel)."""

    event: np.ndarray
    repeat: np.ndarray
    point: np.ndarray
    start_s: np.ndarray
    average_s: np.ndarray
    range: np.ndarray | None

    def __len__(self) -> int:
        return len(self.event)


def _entries(program: WaveformProgram, ch: int) -> list[tuple[str, int, int]]:
    """``(pattern, count, start tick)`` of each sequence entry of channel ``ch``."""
    out: list[tuple[str, int, int]] = []
    start = 0
    for index, (name, count) in enumerate(program.sequences.get(ch, [])):
        if index:
            start += GAP_TICKS
        out.append((name, round(count), start))
        start += round(count) * sum(ticks(dt) for dt, _ in program.patterns[name].vectors)
    return out


def point_layout(program: WaveformProgram, ch: int) -> PointLayout:
    """Where every value channel ``ch`` stores comes from (module docstring); empty when its measurement is off."""
    setup = program.channels.get(ch)
    names: list[np.ndarray] = []
    repeats: list[np.ndarray] = []
    points: list[np.ndarray] = []
    starts: list[np.ndarray] = []
    averages: list[np.ndarray] = []
    ranges: list[np.ndarray] = []
    current = setup is not None and setup.measure == "current"
    active: str = (setup.current_range or "10ma") if setup is not None else "10ma"
    if setup is not None and setup.measure_enabled:
        for name, count, entry_start in _entries(program, ch):
            period = sum(ticks(dt) for dt, _ in program.patterns[name].vectors)
            events = sorted(program.measure_events(name), key=lambda e: ticks(e.t))
            local_start, local_avg, local_event, local_point = [], [], [], []
            for event in events:
                t0, step, avg = ticks(event.t), ticks(event.interval), ticks(event.average)
                per = 1 + 2 * avg if event.raw else 1
                begin = t0 + step * np.arange(event.points, dtype=np.int64)
                if per > 1:  # raw samples every 5 ns inside each averaging window
                    sub = np.arange(per, dtype=float) * 0.5
                    local_start.append((begin[:, None] + sub[None, :]).ravel())
                    local_avg.append(np.zeros(event.points * per))
                    local_point.append(np.repeat(np.arange(event.points), per))
                else:
                    local_start.append(begin.astype(float))
                    local_avg.append(np.full(event.points, float(avg)))
                    local_point.append(np.arange(event.points))
                local_event.append(np.full(event.points * per, event.event, dtype=object))
            if not local_start or count < 1:
                continue
            within = np.concatenate(local_start)
            changes = sorted(program.range_events(name), key=lambda e: ticks(e.t))
            if current:
                change_t = np.asarray([ticks(e.t) for e in changes], dtype=float)
                labels = np.asarray([active, *(e.range for e in changes)], dtype=object)
                local_range = labels[np.searchsorted(change_t, within, side="right")]
            n = len(within)
            reps = np.arange(count, dtype=np.int64)
            starts.append(((entry_start + reps[:, None] * period) + within[None, :]).ravel() * TICK_S)
            averages.append(np.tile(np.concatenate(local_avg), count) * TICK_S)
            names.append(np.tile(np.concatenate(local_event), count))
            points.append(np.tile(np.concatenate(local_point), count))
            repeats.append(np.repeat(reps, n))
            if current:
                ranges.append(np.tile(local_range, count))
                if changes:
                    active = changes[-1].range
    if not starts:
        empty = np.zeros(0)
        return PointLayout(np.zeros(0, dtype=object), empty.astype(np.int64), empty.astype(np.int64), empty, empty,
                           np.zeros(0, dtype=object) if current else None)
    return PointLayout(event=np.concatenate(names), repeat=np.concatenate(repeats), point=np.concatenate(points),
                       start_s=np.concatenate(starts), average_s=np.concatenate(averages),
                       range=np.concatenate(ranges) if current else None)


def program_levels(program: WaveformProgram, ch: int, times_s: np.ndarray) -> np.ndarray:
    """The programmed output (V) of channel ``ch`` at ``times_s`` (s from the run start): linear between vectors,
    patterns repeated without delay, 10 ns at the last level and 40 ns at the next initial level between entries, the
    last level after the end (WG p80 (4-10)); a DC channel's first level; 0 V without a program."""
    t = np.asarray(times_s, dtype=float) / TICK_S
    if ch in program.dc:
        return np.full(t.shape, program.dc[ch][0])
    entries = _entries(program, ch)
    if not entries:
        return np.zeros(t.shape)
    knots: list[tuple[np.ndarray, np.ndarray, int]] = []
    for name, _, _ in entries:
        pattern = program.patterns[name]
        bp_t = np.concatenate([[0.0], np.cumsum([ticks(dt) for dt, _ in pattern.vectors])]).astype(float)
        knots.append((bp_t, np.asarray(pattern.levels(), dtype=float), int(bp_t[-1])))
    starts = np.asarray([start for _, _, start in entries], dtype=float)
    out = np.full(t.shape, knots[-1][1][-1])
    which = np.clip(np.searchsorted(starts, t, side="right") - 1, 0, len(entries) - 1)
    for e in np.unique(which):
        index = int(e)
        bp_t, bp_v, period = knots[index]
        span = entries[index][1] * period
        sel = which == e
        rel = t[sel] - starts[index]
        values = np.empty(rel.shape)
        body = rel < span
        if period > 0:
            values[body] = np.interp(np.fmod(np.maximum(rel[body], 0.0), period), bp_t, bp_v)
        gap = ~body
        nxt = knots[index + 1][1][0] if index + 1 < len(knots) else None
        hold = (rel[gap] - span < GAP_HOLD_TICKS) | (nxt is None)
        values[gap] = np.where(hold, bp_v[-1], bp_v[-1] if nxt is None else nxt)
        out[sel] = values
    return out


def max_vectors(program: WaveformProgram, ch: int) -> int:
    """Most vectors of a pattern channel ``ch`` outputs (0 without one)."""
    return max((len(program.patterns[name].vectors) for name in program.channel_patterns(ch)), default=0)

