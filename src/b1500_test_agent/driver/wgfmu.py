"""``WgfmuDriver``: guarded WGFMU operations over the instrument-library protocol (blueprint v2 2.5, 2.6; WP10.3).

The WGFMU is programmed only through its instrument library (``transport.wgfmu.api.WgfmuApi``: the simulated
library on the simulator, the ctypes binding on visa). ``WgfmuDriver(api, guard)`` is to the library what
``B1500Driver`` is to FLEX: every call that can put a level on the DUT passes the ``OutputGuard`` first, and a
refusal (``EnvelopeViolation``) means nothing of that operation reached the library.

- ``configure(ch, setup)``: channel allowlist, then operation mode, force range, measurement mode and range and
  measurement enable (WG p127 (4-57), p123 (4-53), p124 (4-54)). Settings are pending until ``update``/``execute``/a
  DC function applies them (WG p134 (4-64)).
- ``load(program)``: the whole ``WaveformProgram`` is checked before the first library call: every channel in the
  allowlist, ``check_waveform`` on every pattern of every channel that outputs it (each level including ``v0``, the
  10 ns grid, the vector count, the pattern time), ``check_sequence`` on every channel's sequence (time with every
  repeat, stored values) and every DC-mode level of the program (``WaveformProgram.dc``). Only then: ``clear`` (a
  load replaces any earlier software setup), ``configure`` per channel, ``create_pattern``/``add_vectors`` per
  pattern a channel outputs, its measure and range events, ``add_sequence`` per item. A pattern no channel outputs
  is not sent (nothing could output it).
- ``connect(ch)``: the channel's RSU route (``RSU<ch>.<output>`` -> ``wgfmu``, or ``smu`` for a channel in SMU mode)
  through ``check_route``, then ``WgfmuApi.connect`` (WG p85 (4-15): enables the channel and its RSU). The channel
  counts as connected from the attempt on, so the safe state disconnects it even when the call failed.
- ``run()``: every RSU route checked, then ``update`` -> ``connect`` per sequenced channel -> ``execute`` -> poll
  ``status`` with at most ``poll_s`` (1 s) between polls and an abort check before each -> chunked readback
  (``measure_value_size``, then ``measure_values`` in ``READBACK_CHUNK`` = 100,000-value chunks with an abort check
  before each; the lab's practice, blueprint v2 1.1) -> ``WgfmuBlock``. A sequencer that ends in any state but
  ``completed``/``done`` raises ``WgfmuRunFailed``; one still running after its total time plus a margin
  (``RUN_MARGIN_FRACTION``, ``RUN_MARGIN_S``) of host waiting raises ``WgfmuRunTimeout``.
- ``force_dc(ch, v)``/``measure_dc(ch)``: DC mode output (level through ``check_waveform`` as a pattern without
  vectors) and spot measurement (WG p89-90 (4-19, 4-20)).
- ``abort()``: stop every sequencer (WG p79 (4-9)).
- ``safe_state(channels)``: the WGFMU part of cleanup step 3 (blueprint v2 2.6): ``abort`` -> ``initialize`` (every
  channel reset: SMU mode, disconnected, 0 V; WG p120 (4-50)) -> ``disconnect`` each connected channel (and each of
  ``channels``). Every step runs whatever happened before; never raises (an interrupt caught meanwhile comes back in
  the report for the caller to re-raise once the cleanup is complete). The transaction closes the library session
  and relocks the FLEX link (``session/wgfmu_phase.py``).

RSU states (``rsu_states``): the library has no query for the RSU relay, so the driver reports what the library
accepted: ``wgfmu`` (or ``smu``) after a successful ``connect``, the RSU's normal path after a successful
``disconnect`` (``rsu_rest_path``: the station's ``rest``, i.e. ``open`` when nothing or an unknown SMU is cabled to
the RSU's SMU input; WG p19 (1-7) "Normally, the RSU makes the path from the SMU input"). An output whose last call
failed is unknown (left out). They fill ``LiveState.switch_states`` and ``CleanupReport.switches_after`` for the
RSUs (FLEX never reads an RSU; WP9.2).

Imports: ``transport`` and ``models`` (and the guard) only; the library's C names live in ``transport/wgfmu/``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from b1500_test_agent.driver.errors import DriverError, DriverStateError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.models.routing import Route, SwitchSpec, SwitchState
from b1500_test_agent.models.sources import ChannelSetup, MeasureEvent, WaveformProgram
from b1500_test_agent.transport.wgfmu.api import (
    READBACK_CHUNK,
    STATUS_COMPLETED,
    STATUS_DONE,
    STATUS_NAMES,
    STATUS_RUNNING,
    WgfmuApi,
)

POLL_S = 1.0
"""Longest host wait between two sequencer status polls, and so between two abort checks (blueprint v2 2.5)."""

MIN_POLL_S = 1e-3
"""Shortest host wait between two polls of a sequencer that should already have ended (no busy loop)."""

RUN_MARGIN_S = 10.0
RUN_MARGIN_FRACTION = 0.2
"""A sequencer still running after ``total x (1 + RUN_MARGIN_FRACTION) + RUN_MARGIN_S`` of host waiting has hung
(``WgfmuRunTimeout``): the library's status reports the run's total time (WG p117 (4-47))."""

_DETAIL_LIMIT = 400


class WgfmuRunFailed(DriverError):
    """The WGFMU sequencer run did not complete: it ended ``aborted``/``abort_completed``/``running_illegal``/``idle``
    (WG p149 (4-79) Table 4-17), or a channel's data are incomplete. ``status`` is the short status name."""

    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class WgfmuRunTimeout(WgfmuRunFailed):
    """The sequencer still reports ``running`` long after its total time (a hung run); the cleanup aborts it."""


class WgfmuSafeStateFailed(DriverError):
    """The WGFMU safe state (abort, initialize, every connected channel disconnected, session closed, FLEX relocked)
    could not be confirmed; the transaction cleanup tries again and latches the fault if it still fails."""


# -- results ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WgfmuTrace:
    """One channel's readback: ``time_s`` (from the run start) and ``value`` (V or A, ``quantity``)."""

    channel: int
    quantity: Literal["V", "I"]
    time_s: np.ndarray
    value: np.ndarray

    def __len__(self) -> int:
        return len(self.value)


@dataclass(frozen=True)
class WgfmuBlock:
    """What ``WgfmuDriver.run`` returns: per measuring channel its trace, the final sequencer status and times, and
    the number of status polls."""

    traces: dict[int, WgfmuTrace]
    status: str
    elapsed_s: float
    total_s: float
    polls: int


@dataclass(frozen=True)
class SafeStateReport:
    """Result of ``WgfmuDriver.safe_state``: ``steps`` = ``(name, ok, detail)`` in order; ``ok`` = every step
    succeeded; ``deferred`` = an interrupt (``KeyboardInterrupt``, ``SystemExit``) caught during it, which the caller
    re-raises once its own cleanup is complete."""

    steps: tuple[tuple[str, bool, str], ...]
    deferred: BaseException | None = None
    disconnected: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.steps)

    @property
    def detail(self) -> str:
        parts = [name if ok else f"{name} FAILED ({detail})" for name, ok, detail in self.steps]
        return ", ".join(parts) or "nothing to do"


# -- RSU helpers -----------------------------------------------------------------------------------------------------


def find_rsu(switches: Sequence[SwitchSpec], ch: int) -> tuple[SwitchSpec, str] | None:
    """The declared RSU (not recorded absent) and its output that serve WGFMU channel ``ch`` (port index = ``ch``)."""
    for switch in switches:
        if switch.kind != "rsu" or switch.present is False:
            continue
        for output, port in switch.ports.items():
            if port.index == ch:
                return switch, output
    return None


def rsu_rest_path(switch: SwitchSpec) -> SwitchState:
    """The state an RSU output is in while its WGFMU channel is disconnected: its normal path (WG p19 (1-7)), which
    the station records as ``rest`` (``open`` or ``smu``)."""
    return switch.rest if switch.rest in ("open", "smu") else "open"


def rsu_state_for_mode(mode: str) -> SwitchState:
    """The RSU state a connected channel in ``mode`` puts its RSU in: ``smu`` in SMU mode, else ``wgfmu``."""
    return "smu" if mode == "smu" else "wgfmu"


# -- the driver ------------------------------------------------------------------------------------------------------


@dataclass
class _Tracked:
    setups: dict[int, ChannelSetup] = field(default_factory=dict)
    connected: set[int] = field(default_factory=set)
    rsu: dict[int, SwitchState] = field(default_factory=dict)


class WgfmuDriver:
    """Guarded WGFMU operations (module docstring). ``guard`` is the transaction's ``OutputGuard`` (``None``: every
    operation that can put a level on the DUT refuses, only ``abort``/``safe_state``/reads run); ``switches`` are the
    station's switches (default: the guard's), where each channel's RSU is found; ``wait`` lets host time pass
    between status polls (the transaction gives the FLEX link's host clock; default ``time.sleep``)."""

    def __init__(self, api: WgfmuApi, guard: OutputGuard | None, *, switches: Sequence[SwitchSpec] | None = None,
                 wait: Callable[[float], None] | None = None) -> None:
        self.api = api
        self.guard = guard
        self.switches: tuple[SwitchSpec, ...] = tuple(switches if switches is not None else
                                                      (guard.switches if guard is not None else ()))
        self._wait = wait or time.sleep
        self._program: WaveformProgram | None = None
        self._tracked = _Tracked()

    # -- state ---------------------------------------------------------------------------------------------------------

    @property
    def connected(self) -> frozenset[int]:
        """Channels connected (or attempted) and not yet disconnected by this driver."""
        return frozenset(self._tracked.connected)

    @property
    def program(self) -> WaveformProgram | None:
        """The program ``load`` set up last (``None`` before)."""
        return self._program

    def rsu_states(self) -> dict[str, SwitchState]:
        """``"<RSU>.<output>"`` -> the state the library last accepted for it (module docstring)."""
        found: dict[str, SwitchState] = {}
        for ch, state in sorted(self._tracked.rsu.items()):
            rsu = find_rsu(self.switches, ch)
            if rsu is not None:
                found[f"{rsu[0].id}.{rsu[1]}"] = state
        return found

    def _require_guard(self, operation: str, ch: int | None = None) -> OutputGuard:
        if self.guard is None:
            raise EnvelopeViolation("no_guard", f"{operation} refused: no OutputGuard is installed (a plan's compiled "
                                    "envelope is required for any WGFMU output)", channel=ch)
        return self.guard

    # -- setup ---------------------------------------------------------------------------------------------------------

    def configure(self, ch: int, setup: ChannelSetup) -> None:
        """Channel allowlist, then the channel settings (pending until applied; module docstring).

        Raises:
            EnvelopeViolation: If ``ch`` is not in the plan allowlist (or no guard is installed).
        """
        self._require_guard("configure", ch).check_channel(ch)
        api = self.api
        api.set_operation_mode(ch, setup.mode)
        api.set_force_voltage_range(ch, setup.force_range)
        if setup.mode != "smu":  # the measurement settings mean nothing in SMU pass-through mode (Table 4-7)
            api.set_measure_mode(ch, setup.measure)
            if setup.measure == "current" and setup.current_range is not None:
                api.set_measure_current_range(ch, setup.current_range)
            if setup.measure == "voltage" and setup.voltage_range is not None:
                api.set_measure_voltage_range(ch, setup.voltage_range)
            if setup.mode in ("fastiv", "pg"):  # not available in DC mode (WG p124 (4-54))
                api.set_measure_enabled(ch, setup.measure_enabled)
        self._tracked.setups[ch] = setup

    def check_program(self, program: WaveformProgram) -> None:
        """Every guard check of ``load`` (module docstring), without any library call.

        Raises:
            EnvelopeViolation: The first check that fails.
        """
        guard = self._require_guard("load")
        for ch in sorted(program.channels):
            guard.check_channel(ch)
        for ch in sorted(program.sequences):
            for name in program.channel_patterns(ch):
                pattern = program.patterns[name]
                dts = [dt for dt, _ in pattern.vectors]
                levels = [v for _, v in pattern.vectors]
                guard.check_waveform(ch, dts, levels, v0=pattern.v0)
            guard.check_sequence(ch, time_s=program.sequence_time_s(ch), points=program.points(ch))
        for ch, levels in sorted(program.dc.items()):  # DC-mode levels (dc_spot): each checked like force_dc's
            for level in levels:
                guard.check_waveform(ch, (), (), v0=level)

    def load(self, program: WaveformProgram) -> None:
        """Check the whole program, then set it up in the library (module docstring).

        Raises:
            EnvelopeViolation: If any check fails; nothing was sent to the library.
            WgfmuError: If the library refuses a setup call.
        """
        self.check_program(program)
        api = self.api
        api.clear()
        self._program = None
        for ch, setup in sorted(program.channels.items()):
            self.configure(ch, setup)
        used = list(dict.fromkeys(name for ch in sorted(program.sequences) for name in program.channel_patterns(ch)))
        for name in used:
            pattern = program.patterns[name]
            api.create_pattern(name, pattern.v0)
            if pattern.vectors:
                api.add_vectors(name, [dt for dt, _ in pattern.vectors], [v for _, v in pattern.vectors])
        for event in program.events:
            if event.pattern not in used:
                continue
            if isinstance(event, MeasureEvent):
                api.set_measure_event(event.pattern, event.event, event.t, event.points, event.interval,
                                      event.average, event.raw)
            else:
                api.set_range_event(event.pattern, event.event, event.t, event.range)
        for ch, items in sorted(program.sequences.items()):
            for name, count in items:
                api.add_sequence(ch, name, count)
        self._program = program

    # -- output --------------------------------------------------------------------------------------------------------

    def rsu_route(self, ch: int) -> Route:
        """The route ``connect(ch)`` needs: the channel's RSU output in ``wgfmu`` (``smu`` in SMU mode).

        Raises:
            EnvelopeViolation: ``route_not_allowed`` when the station declares no RSU for ``ch``.
            DriverStateError: If ``ch`` was not configured by this driver (its mode is unknown).
        """
        rsu = find_rsu(self.switches, ch)
        if rsu is None:
            raise EnvelopeViolation("route_not_allowed", f"channel {ch}: the station declares no RSU for this WGFMU "
                                    "channel (a WGFMU reaches the DUT only through its RSU)", channel=ch,
                                    quantity="route")
        setup = self._tracked.setups.get(ch)
        if setup is None:
            raise DriverStateError(f"connect {ch} refused: configure the channel first (its mode decides the RSU path)")
        return Route(switch=rsu[0].id, output=rsu[1], state=rsu_state_for_mode(setup.mode))

    def connect(self, ch: int) -> None:
        """Connect channel ``ch`` through its RSU (guarded route; module docstring).

        Raises:
            EnvelopeViolation: If the channel or its RSU route is outside the plan (nothing sent).
            WgfmuError: If the library refuses (e.g. firmware 3001 "RSU is not connected").
        """
        guard = self._require_guard("connect", ch)
        guard.check_channel(ch)
        route = self.rsu_route(ch)
        guard.check_route(route)
        self._tracked.connected.add(ch)  # from the attempt on: the safe state disconnects it whatever happens
        self._tracked.rsu.pop(ch, None)
        self.api.connect(ch)
        self._tracked.rsu[ch] = route.state

    def force_dc(self, ch: int, v: float) -> None:
        """DC output of ``v`` on a channel in DC mode (WG p89 (4-19)); the level is checked like a pattern level.

        Raises:
            EnvelopeViolation: If ``v`` is outside the channel's envelope (nothing sent).
        """
        self._require_guard("force_dc", ch).check_waveform(ch, (), (), v0=v)
        self.api.dc_force_voltage(ch, v)

    def measure_dc(self, ch: int) -> float:
        """One DC spot measurement (voltage or current, by the channel's measurement mode; WG p90 (4-20))."""
        return self.api.dc_measure_value(ch)

    def run(self, *, check_abort: Callable[[], None] | None = None,
            on_poll: Callable[[float, float], None] | None = None, poll_s: float = POLL_S) -> WgfmuBlock:
        """Run the loaded program and read its data back (module docstring).

        ``check_abort`` is called before every status poll and every readback chunk (``Transaction.check_abort``:
        raises ``RunCancelled``); ``on_poll(elapsed_s, total_s)`` after every poll.

        Raises:
            DriverStateError: If no program is loaded.
            EnvelopeViolation: If an RSU route is outside the plan (nothing of the run sent).
            WgfmuRunFailed: The sequencer ended without completing (``WgfmuRunTimeout``: it never ended).
            WgfmuError: If the library fails.
        """
        program = self._program
        if program is None:
            raise DriverStateError("run refused: no waveform program is loaded")
        guard = self._require_guard("run")
        channels = sorted(program.sequences)
        for ch in channels:
            guard.check_channel(ch)
            guard.check_route(self.rsu_route(ch))
        api = self.api
        api.update()
        for ch in channels:
            self.connect(ch)
        api.execute()
        status, elapsed, total, polls = self._poll(check_abort, on_poll, poll_s)
        traces: dict[int, WgfmuTrace] = {}
        for ch in channels:
            if program.points(ch) > 0:
                traces[ch] = self.read(ch, check_abort=check_abort)
        return WgfmuBlock(traces=traces, status=STATUS_NAMES.get(status, str(status)), elapsed_s=elapsed,
                          total_s=total, polls=polls)

    def _poll(self, check_abort: Callable[[], None] | None, on_poll: Callable[[float, float], None] | None,
              poll_s: float) -> tuple[int, float, float, int]:
        waited = 0.0
        polls = 0
        while True:
            if check_abort is not None:
                check_abort()
            status, elapsed, total = self.api.status()
            polls += 1
            if on_poll is not None:
                on_poll(elapsed, total)
            if status in (STATUS_COMPLETED, STATUS_DONE):
                return status, elapsed, total, polls
            name = STATUS_NAMES.get(status, str(status))
            if status != STATUS_RUNNING:
                raise WgfmuRunFailed(f"the WGFMU sequencer ended {name} after {elapsed:g} of {total:g} s", status=name)
            limit = total * (1.0 + RUN_MARGIN_FRACTION) + RUN_MARGIN_S
            if waited > limit:
                raise WgfmuRunTimeout(f"the WGFMU sequencer still runs after {waited:g} s of waiting (total {total:g} "
                                      f"s, elapsed {elapsed:g} s reported)", status=name)
            step = min(poll_s, max(total - elapsed, MIN_POLL_S))
            self._wait(step)
            waited += step

    def read(self, ch: int, *, check_abort: Callable[[], None] | None = None) -> WgfmuTrace:
        """All values of channel ``ch`` in ``READBACK_CHUNK`` chunks (an abort check before each chunk).

        Raises:
            WgfmuRunFailed: If fewer values were measured than the run stores.
        """
        measured, total = self.api.measure_value_size(ch)
        if measured < total:
            raise WgfmuRunFailed(f"channel {ch}: {measured} of {total} values measured")
        times: list[np.ndarray] = []
        values: list[np.ndarray] = []
        for offset in range(0, total, READBACK_CHUNK):
            if check_abort is not None:
                check_abort()
            t, v = self.api.measure_values(ch, offset, min(READBACK_CHUNK, total - offset))
            times.append(np.asarray(t, dtype=float))
            values.append(np.asarray(v, dtype=float))
        setup = self._tracked.setups.get(ch)
        quantity: Literal["V", "I"] = "I" if setup is not None and setup.measure == "current" else "V"
        empty = np.zeros(0, dtype=float)
        return WgfmuTrace(channel=ch, quantity=quantity, time_s=np.concatenate(times) if times else empty,
                          value=np.concatenate(values) if values else empty)

    # -- stop and safe state -------------------------------------------------------------------------------------------

    def abort(self) -> None:
        """Stop every sequencer; the channels keep the level of that moment (WG p79 (4-9))."""
        self.api.abort()

    def safe_state(self, channels: Sequence[int] = ()) -> SafeStateReport:
        """``abort`` -> ``initialize`` -> ``disconnect`` each connected channel and each of ``channels`` (module
        docstring); never raises."""
        steps: list[tuple[str, bool, str]] = []
        deferred: list[BaseException] = []

        def attempt(name: str, action: Callable[[], object]) -> bool:
            try:
                action()
            except BaseException as exc:  # noqa: BLE001 - every step runs; interrupts are handed back
                if not isinstance(exc, Exception):
                    deferred.append(exc)
                steps.append((name, False, f"{type(exc).__name__}: {exc}"[:_DETAIL_LIMIT]))
                return False
            steps.append((name, True, ""))
            return True

        attempt("abort", self.api.abort)
        if attempt("initialize", self.api.initialize):
            self._tracked.setups.clear()  # every channel back in SMU mode (WG p120 (4-50)); the software setup stays
        done: list[int] = []
        for ch in sorted(self._tracked.connected | {int(c) for c in channels}):
            if attempt(f"disconnect {ch}", lambda ch=ch: self.api.disconnect(ch)):
                self._tracked.connected.discard(ch)
                done.append(ch)
                rsu = find_rsu(self.switches, ch)
                if rsu is not None:
                    self._tracked.rsu[ch] = rsu_rest_path(rsu[0])
            else:
                self._tracked.rsu.pop(ch, None)
        return SafeStateReport(steps=tuple(steps), deferred=deferred[0] if deferred else None, disconnected=tuple(done))


def rsu_targets(switches: Sequence[SwitchSpec], channels: Sequence[int]) -> Mapping[int, str]:
    """WGFMU channel -> ``"<RSU>.<output>"`` for the channels of ``channels`` that have a declared RSU."""
    found: dict[int, str] = {}
    for ch in channels:
        rsu = find_rsu(switches, ch)
        if rsu is not None:
            found[ch] = f"{rsu[0].id}.{rsu[1]}"
    return found
