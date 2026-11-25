"""Bulk repeats of the simulated WGFMU (blueprint v2 4.2 "WGFMU engine"; WP10.6, the bulk-cycling hook the WGFMU
engine left to the device models): a sequence entry that repeats one pattern many times with no measurement point
(the bipolar cycling of an endurance run: 10^6 to 10^9 periods of a few microseconds) is not stepped vertex by vertex.
Simulator convention, as the HV-SPGU's output engine (``units/spgu_output.py``):

- A *bulk window* is a stretch where every run channel repeats one entry (same start, period and count on every
  channel: the aligned entries the builders write) of at least ``MIN_REPEATS`` repeats whose pattern stores no value.
- Its first ``EXACT_REPEATS`` repeats are stepped exactly (every vertex, ``Evaluator._step_exact``); the device cycle
  counts gained over the last of them are the cycles of one repeat (a bipolar cycle: 1).
- The remaining whole repeats are applied in at most ``CHUNKS`` aggregated chunks: one repeat's vertices with every
  segment held ``k`` times as long (exact for effective-time laws of a periodic drive: nucleation-limited switching,
  ageing) plus ``add_cycles((k - 1) x cycles per repeat)`` on every device that counts cycles (wake-up and fatigue of
  FeCap and FeFET); retention between pulses is then approximate. A partial repeat at either end is stepped exactly.

The engine records one zero-current step at the end of a bulk chunk, so the current integrals of later points stay
consistent (no point lies inside a bulk window).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from b1500_test_agent.transport.sim.wgfmu_engine import ChannelProgram

EXACT_REPEATS = 3
"""Repeats of a bulk window stepped exactly before the bulk chunks (the last one gives the cycles per repeat)."""

MIN_REPEATS = 64
"""Fewest repeats of an entry treated as a bulk window (shorter entries are stepped exactly)."""

CHUNKS = 64
"""Most aggregated chunks the bulk repeats of one evaluation are applied in."""


@dataclass(frozen=True)
class BulkWindow:
    """An aligned entry repeated ``count`` times from tick ``start`` with period ``period`` (ticks) on every channel."""

    start: int
    period: int
    count: int

    @property
    def end(self) -> int:
        return self.start + self.period * self.count

    def repeat_at(self, tick: float) -> float:
        """Repeats elapsed by ``tick`` (fractional)."""
        return (tick - self.start) / self.period


class CycleCounter(Protocol):
    cycles: float

    def add_cycles(self, count: float) -> None: ...


def window_at(programs: Mapping[int, ChannelProgram], tick: float) -> BulkWindow | None:
    """The bulk window containing ``tick`` or starting after it before the next entry boundary, else ``None``."""
    if not programs:
        return None
    found: BulkWindow | None = None
    for prog in programs.values():
        entry = next((e for e in prog.entries if e.end > tick), None)
        if entry is None or entry.count < MIN_REPEATS:
            return None
        if prog.measure_enabled and entry.pattern.n_points:
            return None
        window = BulkWindow(start=entry.start, period=entry.pattern.period, count=entry.count)
        if found is not None and window != found:
            return None
        found = window
    return found


def counters(stateful: Mapping[str, object]) -> dict[str, CycleCounter]:
    """The devices that count bipolar cycles (``cycles`` and ``add_cycles``)."""
    return {name: dev for name, dev in stateful.items()  # type: ignore[misc]
            if hasattr(dev, "cycles") and callable(getattr(dev, "add_cycles", None))}


def repeat_marks(programs: Mapping[int, ChannelProgram], window: BulkWindow) -> np.ndarray:
    """The vertex ticks of one repeat relative to its start (every channel's vertices, the repeat end included)."""
    marks = [np.asarray([float(window.period)])]
    for prog in programs.values():
        entry = next(e for e in prog.entries if e.start == window.start)
        marks.append(entry.pattern.bp_t[1:])
    out = np.unique(np.concatenate(marks))
    return out[out > 0]


def chunks(repeats: int) -> list[int]:
    """``repeats`` whole repeats as at most ``CHUNKS`` chunk sizes."""
    if repeats <= 0:
        return []
    size = -(-repeats // CHUNKS)
    full, rest = divmod(repeats, size)
    return [size] * full + ([rest] if rest else [])


__all__ = ["CHUNKS", "EXACT_REPEATS", "MIN_REPEATS", "BulkWindow", "chunks", "counters", "repeat_marks",
           "window_at"]
