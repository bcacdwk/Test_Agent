"""Simulator-only extras of ``SimWgfmu`` (``transport/sim/wgfmu.py``; blueprint v2 8.1 "SimWgfmu vs WG Examples
1-11"): library functions outside the ``WgfmuApi`` protocol that the WG example fixtures and the tests use (warning
levels, the error summary, event completion, measurement times, interpolated force values) and the RSU path.

``WgfmuExtras`` is a mixin of ``SimWgfmu``; it reads the library state that class owns (the run, the channel
hardware state, the warnings and the error summary). The DLL binding (WP10.2) can add the matching C functions to the
protocol later; until then the driver uses only ``WgfmuApi``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from b1500_test_agent.transport.sim.wgfmu_engine import TICK_S
from b1500_test_agent.transport.wgfmu.api import (
    CONTEXT_ERROR,
    EVENT_NOT_FOUND,
    PARAMETER_OUT_OF_RANGE,
    WARNING_LEVELS,
    WgfmuError,
)

if TYPE_CHECKING:
    from b1500_test_agent.transport.sim.state import WgfmuChannelState


class WgfmuExtras:
    """Simulator-only library functions of ``SimWgfmu`` (see the module docstring)."""

    if TYPE_CHECKING:
        _run: Any
        _warnings: list[tuple[str, str]]
        _summary: list[str]
        warning_level: str
        treat_level: str

        def _fail(self, fn: str, code: int, detail: str = "", *, rc: int | None = None) -> WgfmuError: ...
        def _tick(self) -> float: ...
        def _hw(self, ch: int) -> WgfmuChannelState: ...

    def set_warning_level(self, level: str) -> None:
        """``WGFMU_setWarningLevel`` (``off``, ``severe``, ``normal``, ``information``)."""
        if level not in WARNING_LEVELS:
            raise self._fail("set_warning_level", PARAMETER_OUT_OF_RANGE, f"level {level!r}")
        self.warning_level = level

    def treat_warnings_as_errors(self, level: str) -> None:
        """``WGFMU_treatWarningsAsErrors``: warnings at or above ``level`` fail the call (WG p133 (4-63))."""
        if level not in WARNING_LEVELS:
            raise self._fail("treat_warnings_as_errors", PARAMETER_OUT_OF_RANGE, f"level {level!r}")
        self.treat_level = level

    def warnings(self) -> list[tuple[str, str]]:
        """``(level, text)`` of every reported warning since ``clear``."""
        return list(self._warnings)

    def error_summary(self) -> str:
        """``WGFMU_getErrorSummary``: every error since ``clear``, one per line."""
        return "\n".join(self._summary)

    def completed_measure_event_size(self, ch: int) -> tuple[int, int]:
        """``WGFMU_getCompletedMeasureEventSize``: (completed, total) measurement events of ``ch``."""
        run = self._run
        if run is None or ch not in run.programs or not run.programs[ch].measure_enabled:
            return 0, 0
        tick = min(self._tick(), run.stop_tick())
        done = total = 0
        for entry in run.programs[ch].entries:
            for ev in entry.pattern.events:
                total += entry.count
                reached = (tick - entry.start - ev.end) // entry.pattern.period + 1
                done += min(entry.count, max(0, int(reached)))
        return done, total

    def measure_event_completed(self, ch: int, pattern: str, event: str, cycle: int = 0, loop: int = 0,
                                count: int = 0) -> tuple[bool, int, int]:
        """``WGFMU_isMeasureEventCompleted``: (completed, first value index, values) of the ``count``-th event named
        ``event`` in the ``loop``-th repeat of the ``cycle``-th use of ``pattern`` on ``ch``."""
        fn = "measure_event_completed"
        run = self._run
        if run is None or ch not in run.programs:
            raise self._fail(fn, CONTEXT_ERROR, f"channel {ch} has no run")
        prog = run.programs[ch]
        uses = [e for e in prog.entries if e.pattern.name == pattern]
        if cycle >= len(uses) or loop >= uses[cycle].count:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"cycle {cycle}, loop {loop} of pattern {pattern!r}")
        entry = uses[cycle]
        named = [i for i, ev in enumerate(entry.pattern.events) if ev.name == event]
        if count >= len(named):
            raise self._fail(fn, EVENT_NOT_FOUND if not named else PARAMETER_OUT_OF_RANGE, f"event {event!r} #{count}")
        idx = named[count]
        pat = entry.pattern
        first_point_local = int(np.searchsorted(pat.p_event, idx, side="left"))
        point = entry.first_point + loop * pat.n_points + first_point_local
        first = prog.values_before_point(point)
        size = pat.events[idx].values
        end_tick = entry.start + loop * pat.period + pat.events[idx].end
        return bool(min(self._tick(), run.stop_tick()) >= end_tick), first, size

    def measure_times(self, ch: int) -> np.ndarray:
        """``WGFMU_getMeasureTimes``: the report time (s) of every point of ``ch`` (no run needed beyond setup)."""
        run = self._run
        if run is None or ch not in run.programs:
            return np.zeros(0)
        block = run.programs[ch].points(0, run.programs[ch].total_points)
        return (block.start + block.avg / 2.0) * TICK_S

    def force_levels(self, ch: int, t_s: Sequence[float]) -> np.ndarray:
        """``WGFMU_getInterpolatedForceValue``: the output of ``ch`` at run times ``t_s`` (s)."""
        run = self._run
        if run is None or ch not in run.programs:
            return np.full(len(t_s), self._hw(ch).voltage)
        return run.programs[ch].levels_at(np.asarray(t_s, dtype=float) / TICK_S)

    def rsu_path(self, ch: int) -> str:
        """Where the RSU of ``ch`` connects the DUT: ``wgfmu`` or ``smu`` (WG p19 (1-7))."""
        hw = self._hw(ch)
        return "wgfmu" if hw.connected and hw.mode != "smu" else "smu"
