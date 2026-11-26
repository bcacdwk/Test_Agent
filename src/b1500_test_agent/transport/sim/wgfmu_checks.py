"""Setup checks of the simulated WGFMU and the RSU drive (blueprint v2 4.2; used by ``transport/sim/wgfmu.py``).

The library checks parameters twice (WG p147 (4-77) "WGFMU Setup Functions"): lowest limits when a setup function is
called (``SimWgfmu`` itself, error ``-1``), highest limits when the setup is applied by ``update``/``execute``. The
latter are the firmware errors of WG p152-155 (4-82 to 4-85); this module decides which condition reports which code
(the simulator's reading of the messages, TODO(verify)[L8.A10, L8.A11]):

=====  ===========================================================================================================
code   condition (checked at ``update``/``execute``)
=====  ===========================================================================================================
3302   a -10 V or +10 V force range in PG mode (WG p140 (4-70) Table 4-6: not available for PG)
3303   current measurement in PG mode (WG p141 (4-71) Table 4-7)
3304   a pattern with more than 2,048 vectors (WG5 p24 (1-14) Table 1-6)
3305   more than 512 sequences on one channel (WG5 p24 (1-14) Table 1-6)
3306   a sequenced pattern without vectors ("ALWG Waveform Data is empty")
3309   a sequence count above 1,099,511,627,776 (WG p80 (4-10))
3310   a pattern level outside the channel's force range (auto: no fixed range holds every level)
3311   a vector time above 10995.11627775 s (WG p82 (4-12))
3312   a sampling interval above 1.34217728 s (WG p125 (4-55))
3313   a measurement event ending after its pattern (``time``/``eventEndTime`` within the pattern, WG p125 (4-55))
3314   a range event without Fast IV current measurement, after its pattern or inside an averaging window (WG p128
       (4-58))
3315   an averaging time above 20.971512 ms (WG p126 (4-56))
3316   an averaging time above the sampling interval (WG p154 (4-84) 3316)
=====  ===========================================================================================================

Run-time errors (raised by the next call that observes the run): 3051 when adjacent measurement events change the
averaging less than 100 ns apart (WG p126 (4-56) NOTE), 3052 when three or more range changes follow 2 us apart or
closer (WG p128 (4-58) NOTE); 3050 (memory overflow) is decided by ``SimWgfmu`` from the values not yet read.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence

from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.state import WgfmuChannelState
from b1500_test_agent.transport.sim.wgfmu_engine import TICK_S, ChannelProgram, PatternSpec, to_ticks
from b1500_test_agent.transport.wgfmu.api import (
    AUTO_RANGE_ORDER,
    CURRENT_MODES,
    FORCE_RANGE_BOUNDS,
    LIMITS,
    PG_FORCE_RANGES,
)

Problem = tuple[int, str]
"""A failed check: firmware code and detail."""

_TOL = 1e-12


def range_bounds(mode: str, force_range: str) -> list[tuple[float, float]]:
    """Output bounds a force range allows (``auto``: every fixed range the mode has, WG p136 (4-66) Table 4-2)."""
    if force_range != "auto":
        return [FORCE_RANGE_BOUNDS[force_range]]  # type: ignore[index]
    return [FORCE_RANGE_BOUNDS[r] for r in AUTO_RANGE_ORDER if mode != "pg" or r in PG_FORCE_RANGES]


def setup_problem(ch: int, setup: Mapping[str, object]) -> Problem | None:
    """Channel settings the hardware refuses when they are applied (3302, 3303)."""
    if setup["mode"] == "pg" and setup["force_range"] not in PG_FORCE_RANGES:
        return 3302, f"channel {ch}: force range {setup['force_range']} in PG mode"
    if setup["measure_mode"] == "current" and setup["mode"] not in CURRENT_MODES | {"smu"}:
        return 3303, f"channel {ch}: current measurement in {setup['mode']} mode"
    return None


def sequence_problem(ch: int, hw: WgfmuChannelState, sequence: Sequence[tuple[str, int]],
                     patterns: Mapping[str, PatternSpec]) -> Problem | None:
    """The first highest-limit problem of one ALWG channel's sequence (table in the module docstring)."""
    if len(sequence) > LIMITS["max_sequences"]:
        return 3305, f"channel {ch}: {len(sequence)} sequences (at most {LIMITS['max_sequences']:g})"
    for name, count in sequence:
        if count > LIMITS["count_max"]:
            return 3309, f"channel {ch}: count {count} of pattern {name!r}"
    bounds = range_bounds(hw.mode, hw.force_range)
    for name in dict.fromkeys(n for n, _ in sequence):
        found = _pattern_problem(f"channel {ch}, pattern {name!r}", patterns[name], hw, bounds)
        if found is not None:
            return found
    return None


def _pattern_problem(where: str, spec: PatternSpec, hw: WgfmuChannelState,
                     bounds: list[tuple[float, float]]) -> Problem | None:
    if not spec.dts:
        return 3306, f"{where} has no vectors"
    if len(spec.dts) > LIMITS["max_vectors"]:
        return 3304, f"{where}: {len(spec.dts)} vectors (at most {LIMITS['max_vectors']:g})"
    if max(spec.dts) * TICK_S > LIMITS["vector_dt_max_s"] * (1 + _TOL):
        return 3311, f"{where}: dt {max(spec.dts) * TICK_S:g} s"
    levels = [spec.v0, *spec.volts]
    if not any(lo - 1e-9 <= min(levels) and max(levels) <= hi + 1e-9 for lo, hi in bounds):
        return 3310, f"{where}: levels {min(levels):g}..{max(levels):g} V outside the {hw.force_range} force range"
    period = spec.period
    for ev in spec.measures:
        label = f"{where}, event {ev.name!r}"
        if ev.interval * TICK_S > LIMITS["interval_max_s"] * (1 + _TOL):
            return 3312, f"{label}: interval {ev.interval * TICK_S:g} s"
        if ev.average * TICK_S > LIMITS["average_max_s"] * (1 + _TOL):
            return 3315, f"{label}: average {ev.average * TICK_S:g} s"
        if ev.average > ev.interval:
            return 3316, f"{label}: average {ev.average * TICK_S:g} s > interval {ev.interval * TICK_S:g} s"
        if ev.end > period:
            return 3313, f"{label} ends at {ev.end * TICK_S:g} s, after the pattern ({period * TICK_S:g} s)"
    for rv in spec.ranges:
        label = f"{where}, range event {rv.name!r}"
        if not (hw.mode == "fastiv" and hw.measure_mode == "current"):
            return 3314, f"{label}: needs Fast IV current measurement"
        if rv.t + 1 > period:
            return 3314, f"{label} after the pattern end"
        for ev in spec.measures:
            if ev.average and ev.t <= rv.t < ev.end and (rv.t - ev.t) % ev.interval < ev.average:
                return 3314, f"{label} inside an averaging window of {ev.name!r}"
    return None


def runtime_error(ch: int, prog: ChannelProgram) -> tuple[int, int, float, str] | None:
    """The first run-time error of a channel program: 3051 or 3052 (module docstring); returns the code, the points
    completed before it, its run tick and the detail."""
    spacing_avg = to_ticks(LIMITS["averaging_event_spacing_s"])
    spacing_rng = to_ticks(LIMITS["range_event_spacing_s"])
    for entry in prog.entries:
        pat = entry.pattern
        for a, b in itertools.pairwise(pat.events):
            if a.average != b.average and b.t - a.t < spacing_avg:
                tick = float(entry.start + b.t)
                return 3051, prog.completed_points(tick), tick, (
                    f"channel {ch}, pattern {pat.name!r}: events {a.name!r} and {b.name!r} change the averaging "
                    "less than 100 ns apart")
        times = pat.range_t
        for k in range(len(times) - 2):
            if times[k + 1] - times[k] <= spacing_rng and times[k + 2] - times[k + 1] <= spacing_rng:
                tick = float(entry.start + times[k + 2])
                return 3052, prog.completed_points(tick), tick, (
                    f"channel {ch}, pattern {pat.name!r}: three range changes within 2 us")
    return None


def static_drive(state: Mapping[int, WgfmuChannelState], rsu_smu: Mapping[int, int]) -> tuple[dict[int, float],
                                                                                            dict[int, int]]:
    """Levels the WGFMU channels drive through their RSUs (canonical channel -> V) and the RSUs on their SMU path
    whose "From SMU" input is cabled (canonical WGFMU channel -> canonical SMU channel). An RSU is on the WGFMU path
    while its channel is connected in a mode other than ``smu``, else on its SMU path (WG p19 (1-7)), also before
    any library session recorded a state for the channel (power-on: disconnected)."""
    levels: dict[int, float] = {}
    aliases: dict[int, int] = {}
    for ch in sorted(set(state) | set(rsu_smu)):
        hw = state.get(ch)
        if hw is not None and hw.connected and hw.mode != "smu":
            levels[canonical_channel(ch)] = hw.voltage
        elif ch in rsu_smu:
            aliases[canonical_channel(ch)] = canonical_channel(rsu_smu[ch])
    return levels, aliases
