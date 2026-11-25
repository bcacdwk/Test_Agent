"""WGFMU engine of the simulator (blueprint v2 4.2 "WGFMU engine"): compiled channel programs, piecewise-linear
output, measurement-point layout and the evaluation of measured values on the shared circuit.

``transport/sim/wgfmu.py`` (``SimWgfmu``, the library facade) owns the library state and the run; this module holds
the arithmetic it needs and the circuit wrapper the whole instrument uses:

- Time is counted in **ticks** of 10 ns (the WGFMU grid, WG p82 (4-12)): pattern vectors, event times, intervals and
  averaging times are integers, so event timing is exact on the grid. Raw averaging samples lie every 5 ns
  (half a tick; WG p126 (4-56)).
- ``ChannelProgram``: one channel's sequence compiled at ``execute``: entries ``(pattern, count)`` back to back,
  repeats without delay and 50 ns between different entries, 10 ns at the last voltage then 40 ns at the next initial
  voltage (WG p80 (4-10)); after the last entry the channel keeps its last voltage. ``levels_at`` evaluates the output
  at any times without expanding repeats (counts reach 2^40).
- Measurement points: every repeat of every measurement event of every entry, in time order. A point starting at
  ``s`` with averaging ``a`` averages ``[s, s + a]`` and reports the time ``s + a/2`` (WG p126 (4-56)); without
  averaging it reports ``s``. RAW events return ``1 + int(a / 5 ns)`` values per point at ``s + k 5 ns`` (WG p145
  (4-75) Table 4-14). A point is complete at ``s + a`` (``s + 10 ns`` without averaging, WG p125 (4-55)); data values
  are indexed in that order (``value index``).
- ``Evaluator``: measured values, computed lazily in time order up to the instrument clock. Static circuits are
  evaluated at the point times (one circuit solve per distinct set of channel levels); circuits with time-dependent
  devices (``DynamicDevice``: FeCap/FeFET polarization, traps, ageing) are stepped with ``Circuit.advance`` over every
  waveform vertex and every averaging window, so displacement currents (``I = A dP/dt + C dV/dt``) and kinetics
  appear in the data; constant-level stretches are stepped in blocks (``DYNAMIC_STEP_BUDGET``); an entry repeated
  many times without measurement points (bipolar cycling) is stepped in aggregated chunks with the device models'
  bulk-cycle hook (``wgfmu_bulk.py``, WP10.6). Current readings
  saturate at +-full scale of the range active at the point (range events), the WGFMU's "no compliance, covers the
  full scale" behaviour (WG p16 (1-4)); voltage readings at +-the voltage range. PG mode divides the output by its
  50 Ohm and the load (WG p139 (4-69)). Noise: white noise of rms ``noise.floor_a["WGFMU"]`` per 5 ns sample on the
  10 mA range (scaled by the range's full scale) plus ``noise.rel`` x |I|, averaged as 1/sqrt(n) over the n samples
  of a point; attached ``noise`` devices (1/f, RTN) per event run (simulator conventions).
- ``DrivenCircuit``: the instrument's circuit; every evaluation (also the SMU's) sees the DUT terminals the WGFMU
  channels drive through their RSUs and, while an RSU is on its SMU path, the SMU cabled to its "From SMU" input
  (``SimScenario.rsu_smu``).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from b1500_test_agent.transport.sim.devices import Circuit, canonical_channel
from b1500_test_agent.transport.sim.devices.noise import NoiseSource
from b1500_test_agent.transport.wgfmu.api import CURRENT_RANGE_A, PG_OUTPUT_OHM, VOLTAGE_RANGE_V

TICK_S = 1e-8
"""One tick: the 10 ns WGFMU time grid."""

GAP_HOLD_TICKS = 1
"""Ticks the output holds the last voltage between two different sequence entries (10 ns of the 50 ns)."""

GAP_TICKS = 5
"""Ticks between two different sequence entries (50 ns)."""

DYNAMIC_STEP_BUDGET = 20_000
"""Most ``Circuit.advance`` steps per evaluated chunk: constant-level stretches with more sampling points are
stepped in blocks of points (simulator convention)."""

VERTEX_BUDGET = 200_000
"""Most waveform vertices stepped exactly per chunk; beyond it a stretch without points is held at its end level
(huge pulse counts without measurements; bulk cycling belongs to the device hooks, simulator convention)."""

EXACT_SAMPLES = 4096
"""Samples of one evaluated series solved exactly on a static circuit; longer series are solved at anchors and
interpolated (``Evaluator._static_series``)."""

NOISE_REFERENCE_RANGE_A = 1e-2
"""Range at which ``noise.floor_a["WGFMU"]`` is the rms of one 5 ns sample (other ranges scale by full scale)."""


def to_ticks(seconds: float) -> int:
    """``seconds`` rounded to the nearest 10 ns tick (72 ns -> 70 ns, WG p82 (4-12))."""
    return math.floor(seconds / TICK_S + 0.5)


def ticks_to_s(ticks: float) -> float:
    """Ticks to seconds."""
    return ticks * TICK_S


# -- Library-side setup (mutable, per process) -----------------------------------------------------------------------


@dataclass(frozen=True)
class MeasureSpec:
    """A measurement event in ticks: ``points`` from ``t`` every ``interval``, each averaged over ``average``."""

    name: str
    t: int
    points: int
    interval: int
    average: int
    raw: bool

    @property
    def end(self) -> int:
        """Event end: ``t + interval (points - 1) + average`` (+10 ns if ``average`` is 0; WG p125 (4-55))."""
        return self.t + self.interval * (self.points - 1) + (self.average if self.average else 1)

    @property
    def per_point(self) -> int:
        """Values per point: 1 averaged, ``1 + int(average / 5 ns)`` raw (WG p145 (4-75))."""
        return 1 + 2 * self.average if self.raw else 1

    @property
    def values(self) -> int:
        return self.points * self.per_point

    def overlaps(self, other: MeasureSpec) -> bool:
        return self.t < other.end and other.t < self.end


@dataclass(frozen=True)
class RangeSpec:
    """A current-range change at tick ``t`` (event end ``t + 10 ns``, WG p128 (4-58))."""

    name: str
    t: int
    rng: str


@dataclass
class PatternSpec:
    """A pattern being built: initial voltage, ``(dt ticks, v)`` vectors, measurement and range events."""

    v0: float
    dts: list[int] = field(default_factory=list)
    volts: list[float] = field(default_factory=list)
    measures: list[MeasureSpec] = field(default_factory=list)
    ranges: list[RangeSpec] = field(default_factory=list)

    @property
    def period(self) -> int:
        """Pattern length in ticks."""
        return sum(self.dts)


# -- Compiled programs -----------------------------------------------------------------------------------------------


@dataclass
class PatternLayout:
    """A pattern frozen at ``execute``: vertices and the measurement points of one repeat."""

    name: str
    period: int
    bp_t: np.ndarray            # vertex ticks (float), strictly increasing, bp_t[0] = 0
    bp_v: np.ndarray            # vertex voltages
    p_start: np.ndarray         # point start ticks (int64), time order
    p_avg: np.ndarray           # averaging ticks per point
    p_event: np.ndarray         # index into ``events``
    p_per: np.ndarray           # values per point
    p_comp: np.ndarray          # completion ticks per point (start + average, or + 1 tick)
    p_first: np.ndarray         # first value index of each point within one repeat
    events: list[MeasureSpec]
    range_t: np.ndarray         # range-event ticks, ascending
    range_rng: list[str]

    @property
    def n_points(self) -> int:
        return len(self.p_start)

    @property
    def n_values(self) -> int:
        return int(self.p_per.sum()) if len(self.p_per) else 0

    @property
    def v_first(self) -> float:
        return float(self.bp_v[0])

    @property
    def v_last(self) -> float:
        return float(self.bp_v[-1])

    def levels(self, within: np.ndarray) -> np.ndarray:
        """Output at pattern-relative ticks ``within`` (0 <= within <= period): linear between vertices."""
        return np.interp(within, self.bp_t, self.bp_v)


def layout(name: str, spec: PatternSpec) -> PatternLayout:
    """Freeze ``spec`` (events sorted by time)."""
    bp_t = np.concatenate([[0.0], np.cumsum(np.asarray(spec.dts, dtype=float))])
    bp_v = np.asarray([spec.v0, *spec.volts], dtype=float)
    events = sorted(spec.measures, key=lambda e: e.t)
    starts, avgs, idx, per = [], [], [], []
    for i, ev in enumerate(events):
        starts.append(ev.t + ev.interval * np.arange(ev.points, dtype=np.int64))
        avgs.append(np.full(ev.points, ev.average, dtype=np.int64))
        idx.append(np.full(ev.points, i, dtype=np.int64))
        per.append(np.full(ev.points, ev.per_point, dtype=np.int64))
    p_start = np.concatenate(starts) if starts else np.zeros(0, dtype=np.int64)
    p_avg = np.concatenate(avgs) if avgs else np.zeros(0, dtype=np.int64)
    p_event = np.concatenate(idx) if idx else np.zeros(0, dtype=np.int64)
    p_per = np.concatenate(per) if per else np.zeros(0, dtype=np.int64)
    p_comp = p_start + np.where(p_avg > 0, p_avg, 1)
    p_first = np.concatenate([[0], np.cumsum(p_per)[:-1]]).astype(np.int64) if len(p_per) else p_per.copy()
    ranges = sorted(spec.ranges, key=lambda r: r.t)
    return PatternLayout(name, spec.period, bp_t, bp_v, p_start, p_avg, p_event, p_per, p_comp, p_first, events,
                         np.asarray([r.t for r in ranges], dtype=float), [r.rng for r in ranges])


@dataclass
class Entry:
    """One sequence entry of a channel: ``count`` repeats of ``pattern`` from tick ``start``."""

    pattern: PatternLayout
    count: int
    start: int
    first_point: int = 0
    first_value: int = 0
    start_range: str = "10ma"

    @property
    def span(self) -> int:
        return self.count * self.pattern.period

    @property
    def end(self) -> int:
        return self.start + self.span


@dataclass
class ChannelProgram:
    """One channel's compiled sequence and measurement setup (applied settings at ``execute``)."""

    ch: int
    mode: str
    measure: str
    current_range: str
    voltage_range: str
    measure_enabled: bool
    entries: list[Entry]

    def __post_init__(self) -> None:
        start, point, value = 0, 0, 0
        rng = self.current_range
        for i, entry in enumerate(self.entries):
            if i:
                start += GAP_TICKS
            entry.start, entry.first_point, entry.first_value, entry.start_range = start, point, value, rng
            start += entry.span
            if self.measure_enabled:
                point += entry.count * entry.pattern.n_points
                value += entry.count * entry.pattern.n_values
            if entry.pattern.range_rng and entry.count > 0:
                rng = entry.pattern.range_rng[-1]
        self.end = start
        self.total_points = point
        self.total_values = value
        self._starts = np.asarray([e.start for e in self.entries], dtype=float)
        self._first_points = np.asarray([e.first_point for e in self.entries], dtype=np.int64)
        self._first_values = np.asarray([e.first_value for e in self.entries], dtype=np.int64)

    @property
    def total_s(self) -> float:
        return ticks_to_s(self.end)

    @property
    def last_level(self) -> float:
        return self.entries[-1].pattern.v_last if self.entries else 0.0

    @property
    def first_level(self) -> float:
        return self.entries[0].pattern.v_first if self.entries else 0.0

    def levels_at(self, t: np.ndarray) -> np.ndarray:
        """Output (V) at run ticks ``t`` (floats >= 0); after the end the last voltage."""
        t = np.asarray(t, dtype=float)
        out = np.full(t.shape, self.last_level)
        if not self.entries:
            return out
        idx = np.clip(np.searchsorted(self._starts, t, side="right") - 1, 0, len(self.entries) - 1)
        for e in np.unique(idx):
            entry = self.entries[int(e)]
            sel = idx == e
            rel = t[sel] - entry.start
            vals = np.empty(rel.shape)
            body = rel < entry.span
            if np.any(body):
                within = np.fmod(np.maximum(rel[body], 0.0), entry.pattern.period)
                vals[body] = entry.pattern.levels(within)
            gap = ~body
            if np.any(gap):
                after = rel[gap] - entry.span
                nxt = self.entries[int(e) + 1].pattern.v_first if int(e) + 1 < len(self.entries) else None
                hold = (after < GAP_HOLD_TICKS) | (nxt is None)
                vals[gap] = np.where(hold, entry.pattern.v_last, nxt if nxt is not None else entry.pattern.v_last)
            out[sel] = vals
        return out

    def level_at(self, tick: float) -> float:
        return float(self.levels_at(np.asarray([tick]))[0])

    def completed_points(self, t: float) -> int:
        """Points complete by run tick ``t``."""
        if not self.measure_enabled:
            return 0
        done = 0
        for entry in self.entries:
            n = entry.pattern.n_points
            if n == 0 or t < entry.start:
                if t < entry.start:
                    break
                continue
            if t >= entry.end:
                done += entry.count * n
                continue
            period = entry.pattern.period
            r = min(int((t - entry.start) // period), entry.count - 1)
            within = t - entry.start - r * period
            done += r * n + int(np.searchsorted(entry.pattern.p_comp, within, side="right"))
            break
        return done

    def values_before_point(self, point: int) -> int:
        """Value index of the first value of point ``point`` (or the total for ``point == total_points``)."""
        if point >= self.total_points:
            return self.total_values
        e = int(np.searchsorted(self._first_points, point, side="right") - 1)
        entry = self.entries[e]
        local = point - entry.first_point
        r, j = divmod(local, entry.pattern.n_points)
        return int(entry.first_value + r * entry.pattern.n_values + entry.pattern.p_first[j])

    def point_of_value(self, value: int) -> int:
        """Index of the point that holds data value ``value``."""
        e = int(np.searchsorted(self._first_values, value, side="right") - 1)
        entry = self.entries[e]
        r, rest = divmod(value - entry.first_value, entry.pattern.n_values)
        j = int(np.searchsorted(entry.pattern.p_first, rest, side="right") - 1)
        return int(entry.first_point + r * entry.pattern.n_points + j)

    def points(self, p0: int, p1: int) -> PointBlock:
        """Layout of points ``[p0, p1)`` in run ticks (vectorized over entries and repeats)."""
        starts, avgs, pers, rngs, keys = [], [], [], [], []
        p = p0
        while p < p1:
            e = int(np.searchsorted(self._first_points, p, side="right") - 1)
            entry = self.entries[e]
            pat = entry.pattern
            n = pat.n_points
            stop = min(p1, entry.first_point + entry.count * n)
            local = np.arange(p - entry.first_point, stop - entry.first_point, dtype=np.int64)
            r, j = np.divmod(local, n)
            starts.append(entry.start + r * pat.period + pat.p_start[j])
            avgs.append(pat.p_avg[j])
            pers.append(pat.p_per[j])
            rngs.append(self._ranges(entry, r, pat.p_start[j]))
            keys.append(np.stack([np.full(len(j), e), r, pat.p_event[j]], axis=1))
            p = stop
        if not starts:
            empty = np.zeros(0, dtype=np.int64)
            return PointBlock(empty, empty, empty, np.zeros(0, dtype=float), np.zeros((0, 3), dtype=np.int64))
        return PointBlock(np.concatenate(starts), np.concatenate(avgs), np.concatenate(pers),
                          np.concatenate(rngs), np.concatenate(keys))

    def _ranges(self, entry: Entry, r: np.ndarray, within: np.ndarray) -> np.ndarray:
        """Current-range full scale (A) at each point: the last range event before it, else the entry's start."""
        pat = entry.pattern
        base = CURRENT_RANGE_A[entry.start_range]  # type: ignore[index]
        if not pat.range_rng:
            return np.full(len(r), base)
        scales = np.asarray([CURRENT_RANGE_A[x] for x in pat.range_rng])  # type: ignore[index]
        k = np.searchsorted(pat.range_t, within, side="right") - 1
        out = np.where(k >= 0, scales[np.maximum(k, 0)], np.where(r > 0, scales[-1], base))
        return out

    def vertices(self, t0: float, t1: float, budget: int) -> np.ndarray:
        """Vertex ticks (pattern vertices of every repeat, entry boundaries, gap steps) in ``(t0, t1]``, at most
        ``budget`` of them (the earliest)."""
        found: list[np.ndarray] = []
        total = 0
        for i, entry in enumerate(self.entries):
            if entry.end + GAP_TICKS < t0 or entry.start > t1 or total >= budget:
                continue
            pat = entry.pattern
            r0 = max(0, int((t0 - entry.start) // pat.period))
            r1 = min(entry.count - 1, int((t1 - entry.start) // pat.period))
            if r1 >= r0:
                reps = min(r1 - r0 + 1, max(1, (budget - total) // len(pat.bp_t)))
                rr = np.arange(r0, r0 + reps, dtype=float)
                ts = (entry.start + rr[:, None] * pat.period + pat.bp_t[None, :]).ravel()
                ts = ts[(ts > t0) & (ts <= t1)]
                found.append(ts)
                total += len(ts)
            if i + 1 < len(self.entries):
                gap = np.asarray([entry.end + GAP_HOLD_TICKS, entry.end + GAP_TICKS], dtype=float)
                found.append(gap[(gap > t0) & (gap <= t1)])
        if not found:
            return np.zeros(0)
        out = np.unique(np.concatenate(found))
        return out[:budget]


@dataclass
class PointBlock:
    """Measurement points: start and averaging ticks, values per point, current full scale, (entry, repeat, event)."""

    start: np.ndarray
    avg: np.ndarray
    per: np.ndarray
    range_a: np.ndarray
    key: np.ndarray

    def __len__(self) -> int:
        return len(self.start)


def compile_program(ch: int, setup: Mapping[str, object], sequence: Sequence[tuple[str, int]],
                    patterns: Mapping[str, PatternSpec]) -> ChannelProgram:
    """The ``ChannelProgram`` of channel ``ch`` (``setup``: applied mode, measure mode, ranges, enable)."""
    layouts: dict[str, PatternLayout] = {}
    entries = []
    for name, count in sequence:
        if name not in layouts:
            layouts[name] = layout(name, patterns[name])
        entries.append(Entry(layouts[name], int(count), 0))
    return ChannelProgram(ch, str(setup["mode"]), str(setup["measure_mode"]), str(setup["current_range"]),
                          str(setup["voltage_range"]), bool(setup["measure_enabled"]), entries)


# -- Circuit wrapper -------------------------------------------------------------------------------------------------

Drive = Callable[[], tuple[dict[int, float], dict[int, int]]]
"""Returns ``(levels, aliases)``: canonical channel -> level the WGFMU drives now, and canonical WGFMU channel ->
canonical SMU channel whose output reaches the DUT through that channel's RSU."""


class DrivenCircuit(Circuit):
    """The instrument's circuit: every evaluation also sees what the WGFMU channels drive (see the module
    docstring). Levels passed explicitly win over driven ones; currents are returned for the passed channels, an SMU
    reaching the DUT through an RSU including the current of the terminals behind it."""

    def __init__(self, scenario: object, drive: Drive | None = None) -> None:
        super().__init__(scenario)  # type: ignore[arg-type]
        self.drive = drive

    def _merge(self, levels: Mapping[int, float]) -> tuple[Mapping[int, float], dict[int, int]]:
        if self.drive is None:
            return levels, {}
        driven, aliases = self.drive()
        if not driven and not aliases:  # nothing driven through an RSU: the SMU-only fast path
            return levels, {}
        merged = {**driven, **levels}
        active = {}
        for wg, smu in aliases.items():
            if wg not in levels and smu in levels:
                merged[wg] = levels[smu]
                active[wg] = smu
        return merged, active

    @staticmethod
    def _fold(currents: dict[int, float], levels: Mapping[int, float], aliases: Mapping[int, int]) -> dict[int, float]:
        out = {ch: currents.get(ch, 0.0) for ch in levels}
        for wg, smu in aliases.items():
            out[smu] = out.get(smu, 0.0) + currents.get(wg, 0.0)
        return out

    def channel_currents(self, levels: Mapping[int, float]) -> dict[int, float]:
        merged, aliases = self._merge(levels)
        if merged is levels:
            return super().channel_currents(levels)
        return self._fold(super().channel_currents(merged), levels, aliases)

    def commit(self, levels: Mapping[int, float]) -> None:
        merged, _ = self._merge(levels)
        super().commit(merged)

    def advance(self, dt: float, levels: Mapping[int, float]) -> dict[int, float]:
        merged, aliases = self._merge(levels)
        if merged is levels:
            return super().advance(dt, levels)
        return self._fold(super().advance(dt, merged), levels, aliases)

    def raw_currents(self, levels: Mapping[int, float]) -> dict[int, float]:
        """Currents for exactly ``levels`` (no driven levels merged; the WGFMU engine passes complete sets)."""
        return Circuit.channel_currents(self, levels)

    def raw_advance(self, dt: float, levels: Mapping[int, float]) -> dict[int, float]:
        return Circuit.advance(self, dt, levels)

    def raw_commit(self, levels: Mapping[int, float]) -> None:
        Circuit.commit(self, levels)


# -- Evaluation ------------------------------------------------------------------------------------------------------


@dataclass
class NoiseSpec:
    """White-noise parameters of one run: rms of a 5 ns current sample on the 10 mA range, relative noise."""

    floor_a: float
    rel: float


class Evaluator:
    """Measured values of one run, computed in time order (see the module docstring).

    ``programs``: the channels of the run; ``fixed``: canonical channel -> level of everything else that drives the
    DUT during the run (SMU outputs, DC-mode WGFMU channels); ``pg``: run channels in PG mode; ``rngs``: one noise
    generator per measured channel.
    """

    def __init__(self, circuit: DrivenCircuit, programs: Mapping[int, ChannelProgram], fixed: Mapping[int, float],
                 noise: NoiseSpec, rngs: Mapping[int, np.random.Generator]) -> None:
        self.circuit = circuit
        self.programs = dict(programs)
        self.fixed = dict(fixed)
        self.noise = noise
        self.rngs = dict(rngs)
        self.dynamic = bool(circuit.dynamic)
        self.cursor = 0.0
        self.done_points = {ch: 0 for ch in programs}
        self.data_t: dict[int, list[np.ndarray]] = {ch: [] for ch in programs}
        self.data_v: dict[int, list[np.ndarray]] = {ch: [] for ch in programs}
        self.stored = {ch: 0 for ch in programs}
        self._steps_t = [np.zeros(1)]
        self._steps_i: dict[int, list[np.ndarray]] = {ch: [np.zeros(1)] for ch in programs}
        self._cum: dict[int, list[np.ndarray]] = {ch: [np.zeros(1)] for ch in programs}
        self._levels_cache: dict[tuple[float, ...], dict[int, float]] = {}
        self._noise_cache: dict[tuple[int, ...], tuple[np.ndarray, int]] = {}
        self._bulk_cycles: dict[tuple[int, int], dict[str, float]] = {}

    # -- levels ----------------------------------------------------------------------------------------------------

    def driven_levels(self, t: np.ndarray) -> dict[int, np.ndarray]:
        """Forced level of every run channel (canonical number) at run ticks ``t``."""
        return {canonical_channel(ch): prog.levels_at(t) for ch, prog in self.programs.items()}

    def _solve_pg(self, levels: dict[int, float]) -> dict[int, float]:
        """PG channels: output = set level - 50 Ohm x I(output) (Gauss-Seidel over the PG channels, bisection each)."""
        pg = [canonical_channel(ch) for ch, p in self.programs.items() if p.mode == "pg"]
        if not pg:
            return levels
        out = dict(levels)
        for _ in range(3):  # Gauss-Seidel over the PG channels
            for c in pg:
                v_set = levels[c]

                def residual(v: float, c: int = c, v_set: float = v_set) -> float:
                    trial = dict(out)
                    trial[c] = v
                    return v - v_set + PG_OUTPUT_OHM * self.circuit.raw_currents(trial).get(c, 0.0)

                v = out[c]
                for _ in range(30):  # Newton: residual' = 1 + 50 Ohm x dI/dV >= 1 for passive loads
                    f = residual(v)
                    if abs(f) <= 1e-12 * max(1.0, abs(v_set)):
                        break
                    h = 1e-6 * max(1.0, abs(v))
                    slope = (residual(v + h) - f) / h
                    v -= f / (slope if slope > 1e-9 else 1.0)
                out[c] = v
        return out

    def _static(self, row: tuple[float, ...], chans: list[int]) -> dict[int, float]:
        """Applied levels and currents of one distinct level set (cached): ``{"v<ch>": V, ch: I}``."""
        cached = self._levels_cache.get(row)
        if cached is not None:
            return cached
        levels = {**self.fixed, **dict(zip(chans, row, strict=True))}
        levels = self._solve_pg(levels)
        currents = self.circuit.raw_currents(levels)
        result: dict[int, float] = {}
        for c in chans:
            result[c] = currents.get(c, 0.0)
            result[-c - 1] = levels[c]  # applied level under key -c-1
        if len(self._levels_cache) < 200_000:
            self._levels_cache[row] = result
        return result

    # -- public ----------------------------------------------------------------------------------------------------

    def evaluate_until(self, tick: float) -> None:
        """Compute every point complete by run tick ``tick`` and step dynamic devices up to ``tick``."""
        if tick <= self.cursor:
            return
        targets = {ch: prog.completed_points(tick) for ch, prog in self.programs.items()}
        if self.dynamic:
            self._step_dynamic(self.cursor, tick, targets)
        for ch, prog in self.programs.items():
            p0, p1 = self.done_points[ch], targets[ch]
            if p1 > p0:
                self._compute(ch, prog, p0, p1)
                self.done_points[ch] = p1
        self.cursor = tick

    def final_levels(self, tick: float) -> dict[int, float]:
        """Forced level of every run channel (canonical) at run tick ``tick``."""
        return {canonical_channel(ch): prog.level_at(tick) for ch, prog in self.programs.items()}

    def values(self, ch: int, i0: int, i1: int) -> tuple[np.ndarray, np.ndarray]:
        """Stored values ``[i0, i1)`` of ``ch`` (times in s, values)."""
        t = np.concatenate(self.data_t[ch]) if self.data_t[ch] else np.zeros(0)
        v = np.concatenate(self.data_v[ch]) if self.data_v[ch] else np.zeros(0)
        if len(self.data_t[ch]) > 1:
            self.data_t[ch], self.data_v[ch] = [t], [v]
        return t[i0:i1].copy(), v[i0:i1].copy()

    # -- computing values ------------------------------------------------------------------------------------------

    def _compute(self, ch: int, prog: ChannelProgram, p0: int, p1: int) -> None:
        block = prog.points(p0, p1)
        start = block.start.astype(float)
        avg = block.avg.astype(float)
        canon = canonical_channel(ch)
        current = prog.measure == "current"
        # point-level reading (mean over the averaging window), used for the noise sources and averaged data
        if self.dynamic:
            base = self._window_mean(ch, canon, start, start + avg, current)
        else:
            base = self._static_series(canon, start + avg / 2.0, current)
        offset = self._source_noise(ch, prog, block, base) if current else np.zeros(len(base))
        mean = base + offset
        raw = block.per > 1
        n_avg = np.maximum(1.0, 2.0 * avg)
        if not np.any(raw):
            times = (start + avg / 2.0) * TICK_S
            values = self._finish(ch, mean, block.range_a, n_avg, current, prog)
        else:
            reps = block.per
            first = np.repeat(np.cumsum(reps) - reps, reps)
            sub = (np.arange(int(reps.sum())) - first) * 0.5  # ticks of the 5 ns sub-samples
            base = np.repeat(start, reps)
            t_sub = base + sub
            point_mean = np.repeat(mean, reps)
            if self.dynamic:
                inst = self._instant(ch, canon, t_sub, current)
            else:
                inst = self._static_series(canon, t_sub, current)
            averaged = np.repeat(~raw, reps)
            reading = np.where(averaged, point_mean, inst + np.repeat(offset, reps))
            times = np.where(averaged, np.repeat((start + avg / 2.0) * TICK_S, reps), t_sub * TICK_S)
            n_eff = np.where(averaged, np.repeat(n_avg, reps), 1.0)
            values = self._finish(ch, reading, np.repeat(block.range_a, reps), n_eff, current, prog)
        self.data_t[ch].append(times)
        self.data_v[ch].append(values)
        self.stored[ch] += len(values)

    def _finish(self, ch: int, reading: np.ndarray, range_a: np.ndarray, n_avg: np.ndarray, current: bool,
                prog: ChannelProgram) -> np.ndarray:
        """White noise (averaged over ``n_avg`` samples) and saturation at the range."""
        rng = self.rngs[ch]
        if current:
            sigma = np.hypot(self.noise.floor_a * range_a / NOISE_REFERENCE_RANGE_A, self.noise.rel * np.abs(reading))
            if np.any(sigma > 0):
                reading = reading + rng.normal(0.0, 1.0, len(reading)) * sigma / np.sqrt(n_avg)
            return np.clip(reading, -range_a, range_a)
        full = VOLTAGE_RANGE_V[prog.voltage_range]  # type: ignore[index]
        return np.clip(reading, -full, full)

    def _source_noise(self, ch: int, prog: ChannelProgram, block: PointBlock, mean: np.ndarray) -> np.ndarray:
        """Attached noise devices (1/f, RTN): one realisation per event repeat (all its points at once on a static
        circuit, so a long capture keeps its spectrum however the host polls; per evaluated chunk on a dynamic
        circuit, whose future currents are not known yet)."""
        sources: list[NoiseSource] = self.circuit.noise_on(canonical_channel(ch))
        if not sources or len(block) == 0:
            return np.zeros(len(mean))
        out = np.zeros(len(mean))
        keys = block.key
        change = np.nonzero(np.any(np.diff(keys, axis=0) != 0, axis=1))[0] + 1
        bounds = [0, *change.tolist(), len(keys)]
        for a, b in itertools.pairwise(bounds):
            key = (ch, *(int(x) for x in keys[a]))
            cached = self._noise_cache.get(key)
            if cached is None:
                if self.dynamic:
                    cached = (self._draw(sources, block.start[a:b], mean[a:b], float(block.range_a[a])), 0)
                else:
                    cached = (self._event_noise(ch, prog, key, sources), 0)
            noise, used = cached
            out[a:b] = noise[used:used + (b - a)]
            if used + (b - a) >= len(noise):
                self._noise_cache.pop(key, None)
            else:
                self._noise_cache[key] = (noise, used + (b - a))
        return out

    def _event_noise(self, ch: int, prog: ChannelProgram, key: tuple[int, ...],
                     sources: list[NoiseSource]) -> np.ndarray:
        """Source noise of every point of one event repeat ``key = (ch, entry, repeat, event)`` (static circuit),
        starting at the event's first point."""
        _, e, r, k = key
        entry = prog.entries[e]
        pat = entry.pattern
        local = np.nonzero(pat.p_event == k)[0]
        first = entry.first_point + r * pat.n_points + int(local[0])
        block = prog.points(first, first + len(local))
        base = self._static_series(canonical_channel(ch), block.start + block.avg / 2.0, True)
        return self._draw(sources, block.start, base, float(block.range_a[0]))

    @staticmethod
    def _draw(sources: list[NoiseSource], start: np.ndarray, base: np.ndarray, range_a: float) -> np.ndarray:
        n = len(base)
        dt = float(start[1] - start[0]) * TICK_S if n > 1 else TICK_S
        out = np.zeros(n)
        for source in sources:
            out += source.sample(base, dt, n, range_a=range_a) - base
        return out

    def _static_series(self, canon: int, t: np.ndarray, current: bool) -> np.ndarray:
        """Current into (or applied level of) channel ``canon`` at run ticks ``t`` (non-decreasing), static circuit.

        The circuit is solved exactly at anchor samples: every sample up to ``EXACT_SAMPLES``; beyond, every sample
        where a level's slope changes (waveform vertices, jumps) and a regular grid of ``EXACT_SAMPLES``. Between
        anchors every level is linear in time, so the values are interpolated: exact on plateaus and for linear
        devices, within ~1e-5 relative on a nonlinear device swept by a ramp."""
        n = len(t)
        if not n:
            return np.zeros(0)
        levels = self.driven_levels(t)
        chans = sorted(levels)
        matrix = np.stack([levels[c] for c in chans], axis=1)
        if n <= EXACT_SAMPLES:
            anchors = np.arange(n)
        else:
            bend = np.abs(np.diff(matrix, n=2, axis=0)).max(axis=1)
            kinks = np.nonzero(bend > 1e-12 * (1.0 + np.abs(matrix[1:-1]).max(axis=1)))[0] + 1
            grid = np.arange(0, n, max(1, n // EXACT_SAMPLES))
            anchors = np.unique(np.concatenate([[0, n - 1], kinks, grid]))
        key = canon if current else -canon - 1
        rows = np.round(matrix[anchors], 12).tolist()
        values = np.fromiter((self._static(tuple(row), chans)[key] for row in rows), dtype=float, count=len(rows))
        if len(anchors) == n:
            return values
        return np.interp(np.arange(n, dtype=float), anchors.astype(float), values)

    # -- dynamic devices ---------------------------------------------------------------------------------------------

    def _step_dynamic(self, t0: float, t1: float, targets: Mapping[int, int]) -> None:
        """Advance the circuit from run tick ``t0`` to ``t1``: bulk windows (``wgfmu_bulk``) in aggregated chunks
        after their exact repeats, everything else exactly (``_step_exact``)."""
        from b1500_test_agent.transport.sim import wgfmu_bulk as bulk

        cursor = t0
        while cursor < t1:
            window = bulk.window_at(self.programs, cursor)
            if window is None or window.start >= t1:
                self._step_exact(cursor, t1, targets)
                return
            if cursor < window.start:
                self._step_exact(cursor, window.start, targets)
                cursor = float(window.start)
            stop = min(t1, float(window.end))
            key = (window.start, window.period)
            counted = bulk.counters(self.circuit.stateful)
            while cursor < stop and (key not in self._bulk_cycles or window.repeat_at(cursor) < bulk.EXACT_REPEATS):
                r = math.floor(window.repeat_at(cursor) + 1e-9)
                repeat_start, repeat_end = window.start + r * window.period, window.start + (r + 1) * window.period
                end = min(stop, float(repeat_end))
                before = {name: float(dev.cycles) for name, dev in counted.items()}
                self._step_exact(cursor, end, targets)
                if cursor == repeat_start and end == repeat_end and r >= bulk.EXACT_REPEATS - 1:
                    self._bulk_cycles[key] = {name: float(dev.cycles) - before[name] for name, dev in counted.items()}
                cursor = end
            boundary = window.start + math.ceil(window.repeat_at(cursor) - 1e-9) * window.period
            if cursor < min(stop, boundary):  # the rest of a repeat a previous evaluation stopped inside
                self._step_exact(cursor, min(stop, float(boundary)), targets)
                cursor = min(stop, float(boundary))
            whole = math.floor(window.repeat_at(stop) + 1e-9) - round(window.repeat_at(cursor))
            if cursor < stop and whole > 0:
                cursor = self._step_bulk(window, round(window.repeat_at(cursor)), whole, self._bulk_cycles[key],
                                         counted)
            if cursor < stop:
                self._step_exact(cursor, stop, targets)
                cursor = stop

    def _step_bulk(self, window: object, first: int, repeats: int, per_repeat: Mapping[str, float],
                   counted: Mapping[str, object]) -> float:
        """``repeats`` whole repeats of a bulk window from repeat ``first`` in aggregated chunks (``wgfmu_bulk``);
        returns the tick reached."""
        from b1500_test_agent.transport.sim import wgfmu_bulk as bulk

        assert isinstance(window, bulk.BulkWindow)
        rel = bulk.repeat_marks(self.programs, window)
        base = window.start + first * window.period
        levels = self.driven_levels(base + rel)
        chans = sorted(levels)
        widths = np.diff(np.concatenate([[0.0], rel]))
        rows = [self._solve_pg({**self.fixed, **{c: float(levels[c][j]) for c in chans}}) for j in range(len(rel))]
        for k in bulk.chunks(repeats):
            for width, applied in zip(widths, rows, strict=True):
                self.circuit.raw_advance(float(width) * k * TICK_S, applied)
            for name, delta in per_repeat.items():
                if delta > 0 and k > 1:
                    counted[name].add_cycles((k - 1) * delta)  # type: ignore[attr-defined]
        end = float(base + repeats * window.period)
        self._steps_t.append(np.asarray([end]))
        for ch in self.programs:
            self._steps_i[ch].append(np.zeros(1))
            self._cum[ch].append(np.asarray([self._cum[ch][-1][-1]]))
        return end

    def _step_exact(self, t0: float, t1: float, targets: Mapping[int, int]) -> None:
        """Advance the circuit from run tick ``t0`` to ``t1`` over vertices and averaging windows."""
        marks = [np.asarray([t1])]
        for ch, prog in self.programs.items():
            marks.append(prog.vertices(t0, t1, VERTEX_BUDGET))
            p0, p1 = self.done_points[ch], targets[ch]
            if p1 > p0:
                block = prog.points(p0, p1)
                s = block.start.astype(float)
                e = s + block.avg
                pts = np.concatenate([s, e])
                if len(pts) > DYNAMIC_STEP_BUDGET:
                    stride = math.ceil(len(pts) / DYNAMIC_STEP_BUDGET)
                    pts = np.sort(pts)[::stride]
                marks.append(pts)
        steps = np.unique(np.concatenate(marks))
        steps = steps[(steps > t0) & (steps <= t1)]
        if len(steps) > DYNAMIC_STEP_BUDGET + VERTEX_BUDGET:
            steps = steps[:: math.ceil(len(steps) / (DYNAMIC_STEP_BUDGET + VERTEX_BUDGET))]
            if steps[-1] != t1:
                steps = np.append(steps, t1)
        levels = self.driven_levels(steps)
        chans = sorted(levels)
        prev = t0
        step_i = {ch: np.empty(len(steps)) for ch in self.programs}
        for k, tk in enumerate(steps):
            applied = {**self.fixed, **{c: float(levels[c][k]) for c in chans}}
            applied = self._solve_pg(applied)
            currents = self.circuit.raw_advance((tk - prev) * TICK_S, applied)
            for ch in self.programs:
                prog = self.programs[ch]
                c = canonical_channel(ch)
                step_i[ch][k] = currents.get(c, 0.0) if prog.measure == "current" else applied[c]
            prev = tk
        widths = np.diff(np.concatenate([[t0], steps]))
        self._steps_t.append(steps)
        for ch in self.programs:
            last = self._cum[ch][-1][-1]
            self._steps_i[ch].append(step_i[ch])
            self._cum[ch].append(last + np.cumsum(step_i[ch] * widths))

    def _arrays(self, ch: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if len(self._steps_t) > 1:
            self._steps_t = [np.concatenate(self._steps_t)]
        for store in (self._steps_i, self._cum):
            if len(store[ch]) > 1:
                store[ch] = [np.concatenate(store[ch])]
        return self._steps_t[0], self._steps_i[ch][0], self._cum[ch][0]

    def _integral(self, ch: int, t: np.ndarray) -> np.ndarray:
        """Integral of the step values of ``ch`` from tick 0 to ``t`` (piecewise constant per step)."""
        ends, vals, cum = self._arrays(ch)
        k = np.clip(np.searchsorted(ends, t, side="left"), 1, len(ends) - 1)
        return cum[k - 1] + vals[k] * (t - ends[k - 1])

    def _window_mean(self, ch: int, canon: int, s: np.ndarray, e: np.ndarray, current: bool) -> np.ndarray:
        wide = e > s
        out = self._instant(ch, canon, s, current)
        if np.any(wide):
            out[wide] = (self._integral(ch, e[wide]) - self._integral(ch, s[wide])) / (e[wide] - s[wide])
        return out

    def _instant(self, ch: int, canon: int, t: np.ndarray, current: bool) -> np.ndarray:
        """Value of the step containing each tick (the step ending at or after it)."""
        ends, vals, _ = self._arrays(ch)
        k = np.clip(np.searchsorted(ends, t, side="left"), 1, len(ends) - 1)
        return vals[k].copy()
