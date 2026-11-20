"""Output engine of the simulated HV-SPGU (blueprint v2 4.2 "SPGU output"): ALWG data blocks, the output timeline of
one pulse period or ALWG sequence, and a run that drives the circuit in virtual time.

Manual (Programming Guide Ed. 15, physical PDF pages): PG pulse parameters Figure 2-31 (PDF 145), three-level pulses
Figure 2-33 (PDF 146: the channel outputs the sum of its two pulse sources), ALWG timing and the 50 ns setup delay
between patterns of different numbers (PDF 147-148), pattern data Table 2-4 (PDF 150), sequence data Table 2-5 (PDF
151), the pulse switch (``ODSW``, PDF 478-479).

Simulator conventions (not from the manual):

- A pulse is a rectangle of its programmed width at the peak level (the 50 %-width equivalent of the trapezoid; the
  transition times only enter the module-spec checks). An ALWG ramp is held as ``RAMP_STEPS`` equal steps at their
  mid levels. A pulse switch that is open leaves the terminal floating (the device sees no drive); in PG mode its
  ``delay``/``width`` count from the period start.
- A run drives the stateful devices with ``Circuit.advance`` segment by segment. The first ``EXACT_UNITS`` periods
  (sequences) of a run are applied one by one; a period that leaves every device state exactly unchanged ends the
  kinetics (every later period would too). Beyond that, the remaining periods of each synchronisation window are
  applied in at most ``CHUNKS`` aggregated chunks (each segment held ``k`` times as long), which reproduces
  effective-time laws exactly for a unipolar train (nucleation-limited switching, BTI, ageing) and counts the
  bipolar cycles of the last exact period ``k`` times (``add_cycles``) for wake-up/fatigue; retention between pulses
  is then approximate. An ALWG sequence whose repeats would expand to more than ``MAX_UNIT_SEGMENTS`` segments holds
  each pattern cycle once with its time multiplied by the repeat count.
- The level at the DUT comes from the caller (``SpguUnit``: ``V_set (SER + 50) / SER`` divided by the load, solved on
  the circuit once per run for each distinct set level).
"""

from __future__ import annotations

import itertools
import math
import struct
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from b1500_test_agent.transport.sim import flex

ALWG_SETUP_DELAY_S = 5e-8
"""Delay when the ALWG output changes to a pattern of a different number; the last level is held (PDF 148)."""

RAMP_STEPS = 4
"""Steps an ALWG ramp is held as (simulator convention)."""

MAX_UNIT_SEGMENTS = 4096
"""Largest number of segments one ALWG sequence expands to before pattern repeats are time-compressed."""

EXACT_UNITS = 256
"""Periods (sequences) of a run applied one by one before aggregation (simulator convention)."""

CHUNKS = 64
"""Aggregated chunks per synchronisation window after the exact periods (simulator convention)."""

ALWG_MAX_PATTERNS = 512
ALWG_MAX_VECTORS = 1024
ALWG_MAX_REPEAT = 1_048_576
ALWG_LEVEL_UV = 40_000_000
ALWG_DT_NS = (10, 671_088_630)


@dataclass
class Source:
    """One PG pulse source (initial values from PG Table 2-12, PDF 179)."""

    delay: float = 0.0
    width: float = 1e-7
    lead: float = 2e-8
    trail: float = 2e-8
    base: float = -0.5
    peak: float = 0.5


@dataclass(frozen=True)
class Pattern:
    """One decoded ALWG pattern: initial level and ``(dt, level, switch closed)`` vectors."""

    initial: float
    vectors: tuple[tuple[float, float, bool], ...]

    @property
    def duration(self) -> float:
        return math.fsum(dt for dt, _, _ in self.vectors)


# -- ALWG data blocks (Tables 2-4 and 2-5) -------------------------------------------------------------------------


def _header(data: bytes, error: int, limit: int) -> int:
    if len(data) < 20:
        raise flex.FlexError(error, f"{len(data)} bytes: no 20-byte header")
    _module, _revision, count = struct.unpack_from(">BBH", data, 0)
    if not 1 <= count <= limit:
        raise flex.FlexError(error, f"{count} entries (1 to {limit})")
    return count


def decode_patterns(data: bytes) -> list[Pattern]:
    """The patterns of one ``ALW`` block; ``FlexError`` 2156 (size, counts), 2157 (time), 2158 (level)."""
    count = _header(data, flex.ERR_ALWG_PATTERN_SIZE, ALWG_MAX_PATTERNS)
    offset, patterns, vectors = 20, [], 0
    for _ in range(count):
        if offset + 6 > len(data):
            raise flex.FlexError(flex.ERR_ALWG_PATTERN_SIZE, "block ends inside a pattern header")
        n, initial = struct.unpack_from(">Hi", data, offset)
        offset += 6
        if offset + 8 * n > len(data) or n < 1:
            raise flex.FlexError(flex.ERR_ALWG_PATTERN_SIZE, f"pattern with {n} vectors does not fit the block")
        items: list[tuple[float, float, bool]] = []
        for _ in range(n):
            level, word = struct.unpack_from(">iI", data, offset)
            offset += 8
            dt_ns = word & 0x7FFF_FFFF
            if not ALWG_DT_NS[0] <= dt_ns <= ALWG_DT_NS[1] or dt_ns % 10:
                raise flex.FlexError(flex.ERR_ALWG_TIME, f"{dt_ns} ns")
            if abs(level) > ALWG_LEVEL_UV or level % 1000:
                raise flex.FlexError(flex.ERR_ALWG_LEVEL, f"{level} uV")
            items.append((dt_ns * 1e-9, level * 1e-6, bool(word >> 31)))
        if abs(initial) > ALWG_LEVEL_UV or initial % 1000:
            raise flex.FlexError(flex.ERR_ALWG_LEVEL, f"initial {initial} uV")
        vectors += n
        patterns.append(Pattern(initial * 1e-6, tuple(items)))
    if offset != len(data) or vectors > ALWG_MAX_VECTORS - count:
        raise flex.FlexError(flex.ERR_ALWG_PATTERN_SIZE, f"{len(data) - offset} bytes left, {vectors} vectors")
    return patterns


def decode_sequence(data: bytes) -> list[tuple[int, int]]:
    """The ``(pattern number, repeat)`` cycles of one ``ALS`` block; ``FlexError`` 2152 (size), 2153 (index),
    2154 (repeat)."""
    count = _header(data, flex.ERR_ALWG_SEQUENCE_SIZE, ALWG_MAX_PATTERNS)
    if len(data) != 20 + 6 * count:
        raise flex.FlexError(flex.ERR_ALWG_SEQUENCE_SIZE, f"{len(data)} bytes for {count} cycles")
    cycles = []
    for index in range(count):
        number, repeat = struct.unpack_from(">HI", data, 20 + 6 * index)
        if not 1 <= number <= ALWG_MAX_PATTERNS:
            raise flex.FlexError(flex.ERR_ALWG_INDEX, f"pattern {number}")
        if not 1 <= repeat <= ALWG_MAX_REPEAT:
            raise flex.FlexError(flex.ERR_ALWG_REPEAT, f"repeat {repeat}")
        cycles.append((number, repeat))
    return cycles


# -- Output timeline ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Piece:
    """A stretch of one channel's output within a period: ``[t0, t1)`` ramping ``v0`` -> ``v1`` (set levels);
    ``connected`` False = pulse switch open (terminal floating)."""

    t0: float
    t1: float
    v0: float
    v1: float
    connected: bool = True


def _window_connected(t: float, switch: tuple[int, int, float, float] | None) -> bool:
    if switch is None or switch[0] == 0:
        return True
    _state, normal, delay, width = switch
    inside = delay <= t < delay + width
    return inside if normal == 0 else not inside


def pg_pieces(mode: int, sources: Mapping[int, Source], period: float,
              switch: tuple[int, int, float, float] | None) -> list[Piece]:
    """One period of a PG channel (``SPM`` mode 1/2: one source; 3: the sum of both) as constant pieces."""
    used = [sources[1]] if mode == 1 else [sources[2]] if mode == 2 else [sources[1], sources[2]]
    edges = {0.0, period}
    for source in used:
        edges.update(t for t in (source.delay, source.delay + source.width) if 0.0 < t < period)
    if switch is not None and switch[0] == 1:
        edges.update(t for t in (switch[2], switch[2] + switch[3]) if 0.0 < t < period)
    times = sorted(edges)
    pieces = []
    for a, b in itertools.pairwise(times):
        mid = 0.5 * (a + b)
        level = math.fsum(s.peak if s.delay <= mid < s.delay + s.width else s.base for s in used)
        pieces.append(Piece(a, b, level, level, _window_connected(mid, switch)))
    return pieces


def alwg_pieces(patterns: list[Pattern], sequence: list[tuple[int, int]], switch_enabled: bool,
                normally_closed: bool) -> tuple[list[Piece], float]:
    """One ALWG sequence of a channel (repeats expanded, setup delays included, the wrap-around delay last) and its
    duration; pattern numbers beyond the channel's patterns raise ``FlexError`` 2153."""
    for number, _ in sequence:
        if number > len(patterns):
            raise flex.FlexError(flex.ERR_ALWG_INDEX, f"pattern {number} of {len(patterns)}")
    expanded = sum(repeat * len(patterns[n - 1].vectors) for n, repeat in sequence)
    compress = expanded > MAX_UNIT_SEGMENTS
    pieces: list[Piece] = []
    t = 0.0
    held = patterns[sequence[0][0] - 1].initial
    held_connected = normally_closed or not switch_enabled
    previous: int | None = None

    def hold(duration: float) -> None:
        nonlocal t
        pieces.append(Piece(t, t + duration, held, held, held_connected))
        t += duration

    for number, repeat in sequence:
        if previous is not None and number != previous:
            hold(ALWG_SETUP_DELAY_S)
        pattern = patterns[number - 1]
        for _ in range(1 if compress else repeat):
            level = pattern.initial
            for dt, target, closed in pattern.vectors:
                span = dt * (repeat if compress else 1)
                connected = closed if switch_enabled else True
                pieces.append(Piece(t, t + span, level, target, connected))
                t += span
                level = target
                held_connected = connected
        held, previous = pattern.vectors[-1][1], number
    if sequence[-1][0] != sequence[0][0]:
        hold(ALWG_SETUP_DELAY_S)
    return pieces, t


def merge(pieces: Mapping[int, list[Piece]], unit: float) -> list[tuple[float, dict[int, float | None]]]:
    """The common segments of every channel over ``[0, unit)``: ``(dt, {channel: set level or None})`` (ramps held
    as ``RAMP_STEPS`` mid-level steps; a channel past its own pieces holds its last level)."""
    stepped: dict[int, list[Piece]] = {}
    edges = {0.0, unit}
    for ch, items in pieces.items():
        out = []
        for piece in items:
            if piece.v0 == piece.v1:
                out.append(piece)
                continue
            for k in range(RAMP_STEPS):
                a = piece.t0 + (piece.t1 - piece.t0) * k / RAMP_STEPS
                b = piece.t0 + (piece.t1 - piece.t0) * (k + 1) / RAMP_STEPS
                level = piece.v0 + (piece.v1 - piece.v0) * (k + 0.5) / RAMP_STEPS
                out.append(Piece(a, b, level, level, piece.connected))
        stepped[ch] = out
        edges.update(p.t0 for p in out if 0.0 < p.t0 < unit)
    times = sorted(edges)
    cursor = {ch: 0 for ch in stepped}
    segments: list[tuple[float, dict[int, float | None]]] = []
    for a, b in itertools.pairwise(times):
        mid = 0.5 * (a + b)
        levels: dict[int, float | None] = {}
        for ch, items in stepped.items():
            i = cursor[ch]
            while i + 1 < len(items) and items[i].t1 <= mid:
                i += 1
            cursor[ch] = i
            piece = items[i]
            levels[ch] = piece.v0 if piece.connected else None
        if b > a:
            segments.append((b - a, levels))
    return segments


# -- Runs --------------------------------------------------------------------------------------------------------

Advance = Callable[[float, dict[int, float]], None]
"""Hold the given SPGU levels (canonical channel -> level at the DUT) for a time (the unit adds the SMU levels)."""


@dataclass
class Run:
    """One started SPGU output: ``start``/``end`` in virtual seconds (``end`` ``None`` = free run), the delivered
    segments of one period/sequence (``unit`` long), the running channels, and the kinetics bookkeeping. A
    ``foreign`` run was started by another process (only its end time is known: no kinetics)."""

    seq: int
    start: float
    end: float | None
    unit: float = 0.0
    segments: list[tuple[float, dict[int, float | None]]] = field(default_factory=list)
    channels: set[int] = field(default_factory=set)
    applied_until: float = 0.0
    exact_left: int = EXACT_UNITS
    steady: bool = False
    unit_cycles: dict[str, float] = field(default_factory=dict)
    foreign: bool = False

    def apply(self, t0: float, t1: float, live: Iterable[int], advance: Advance,
              snapshot: Callable[[], object], cycles: Callable[[], dict[str, float]],
              add_cycles: Callable[[dict[str, float]], None]) -> None:
        """Drive the circuit through ``[t0, t1)`` (absolute virtual time) for the ``live`` channels."""
        if self.foreign or self.steady or not self.segments or self.unit <= 0.0 or t1 <= t0:
            return
        channels = set(live) & self.channels
        a, b = t0 - self.start, t1 - self.start
        index = math.floor(a / self.unit + 1e-12)
        offset = a - index * self.unit
        if offset > 1e-15 * max(1.0, self.unit):
            stop = min(self.unit, b - index * self.unit)
            self._partial(offset, stop, channels, advance)
            a = (index + 1) * self.unit
        if b <= a:
            return
        full = math.floor((b - a) / self.unit + 1e-9)
        self._units(full, channels, advance, snapshot, cycles, add_cycles)
        rest = b - (a + full * self.unit)
        if rest > 1e-15 * max(1.0, self.unit) and not self.steady:
            self._partial(0.0, rest, channels, advance)

    def _partial(self, o1: float, o2: float, channels: set[int], advance: Advance, scale: float = 1.0) -> None:
        t = 0.0
        for dt, levels in self.segments:
            lo, hi = max(t, o1), min(t + dt, o2)
            if hi > lo:
                advance((hi - lo) * scale, {ch: v for ch, v in levels.items() if ch in channels and v is not None})
            t += dt
            if t >= o2:
                break

    def _units(self, count: int, channels: set[int], advance: Advance, snapshot: Callable[[], object],
               cycles: Callable[[], dict[str, float]], add_cycles: Callable[[dict[str, float]], None]) -> None:
        left = count
        while left > 0 and not self.steady and self.exact_left > 0:
            before, counted = snapshot(), cycles()
            self._partial(0.0, self.unit, channels, advance)
            after = cycles()
            self.unit_cycles = {name: after[name] - counted.get(name, 0.0) for name in after}
            self.exact_left -= 1
            left -= 1
            if snapshot() == before:
                self.steady = True
        if left <= 0 or self.steady:
            return
        chunk = max(1, math.ceil(left / CHUNKS))
        while left > 0:
            k = min(chunk, left)
            self._partial(0.0, self.unit, channels, advance, scale=float(k))
            extra = {name: (k - 1) * delta for name, delta in self.unit_cycles.items() if delta > 0}
            if extra:
                add_cycles(extra)
            left -= k
