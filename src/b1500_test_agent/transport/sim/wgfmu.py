"""``SimWgfmu``: the WGFMU instrument library on the simulated B1500A (blueprint v2 2.4, 4.1, 4.2; WP10.1).

``SimWgfmu(instrument)`` implements ``transport.wgfmu.api.WgfmuApi`` on the same ``SimInstrument`` the FLEX link
drives: one virtual clock, one circuit, one persistent state. SMU bias set over FLEX and WGFMU waveforms therefore act
on one simulated DUT (WG Ex. 10/11), the SMU sees what the WGFMU channels drive through their RSUs, and the WGFMU
hardware state (applied modes and ranges, RSU connection, output level, a running sequencer) is saved and loaded with
the rest of the instrument state, so another process sees it (``SimPersistentState.wgfmu``).

What lives where, as in the real library (WG p43 (3-3) "Programming Overview"):

- **Software setup** (this object, per process): patterns of ``(dt, v)`` vectors on the 10 ns grid, measurement and
  range events, per-channel sequences, the pending channel settings, the error queue and summary, warnings, the
  session and its timeout. ``clear`` empties it; ``initialize`` resets only the hardware (and the pending settings).
- **Hardware** (``instrument.state.wgfmu``): settings are applied by ``update``, ``execute`` and the DC functions
  (WG p134 (4-64)); ``connect`` puts the RSU on the WGFMU path (unless the mode is ``smu``); ``execute`` runs the
  sequencers of the connected Fast IV/PG channels (WG p93 (4-23)); after the run the channels keep the last voltage,
  after ``abort`` the voltage of that moment (WG p79 (4-9)).

Checks (WG p147 (4-77)): lowest limits when a setup function is called (``-1`` and nothing added: dt below 10 ns,
interval below 10 ns, negative average, count below 1, |V| above 10 V ...); highest limits when the setup is applied
(``update``/``execute``), reported as firmware errors (WG p152-155 (4-82 to 4-85)): 3302 10 V range in PG mode, 3303
current measurement in PG mode, 3201 connected ALWG channel without a sequence, 3304 more than 2,048 vectors in a
pattern, 3305 more than 512 sequences on a channel, 3306 a sequenced pattern without vectors, 3309 count above 2^40,
3310 a level outside the force range, 3311 dt above 10995.11627775 s, 3312 interval above 1.34217728 s, 3313 a
measurement event ending after its pattern, 3314 a range event outside Fast IV current measurement, after its pattern
or inside an averaging window, 3315 average above 20.971512 ms, 3316 average above interval. Run-time errors are
raised by the next call that observes the run: 3050 when more than ``LIMITS["memory_points"]`` values are stored but
not yet read (values after that are lost), 3051 when adjacent events with different averaging start less than 100 ns
apart, 3052 when three or more range changes follow at 2 us or less. 3307 and 3308 cannot arise through this API (the
library's own checks come first); they, and any other code, come from the ``wgfmu_error`` fault. The mapping of each
condition to its firmware code is the simulator's reading of the manual's messages, TODO(verify) at bring-up L8.

Time: library calls take no virtual time except ``wait_until_completed`` (to the end of the run), polls (``status``,
``channel_status``, ``measure_value_size``: one poll quantum each, ``POLL_QUANTUM_S``), DC measurements
(``DC_MEASURE_S``) and a hung call (the session timeout). ``timing: scaled(f)`` sleeps ``f`` real seconds per
virtual second waited, as the FLEX link does. During a run the FLEX side drives the DUT with its DC solution at
``execute`` (compliance-limited SMU levels, output-on SPGU channels, MFCMU sides). Status codes (WG p149 (4-79)):
``idle`` before a run and after ``initialize``, ``running``, ``completed`` (data ready at once, so ``done`` is never
reported), ``abort_completed``, ``running_illegal`` after ``update``/``disconnect`` during a run (its data can no
longer be read).

Faults (``models.sim``): ``wgfmu_error`` (a call fails with a code, no effect), ``wgfmu_hang`` (a call blocks for the
timeout, then a communication error; on ``execute``/``wait_until_completed`` the sequencer never completes),
``wgfmu_disconnect_fails`` (stuck RSU relay), ``wgfmu_dll_missing`` (``open_session`` fails; ``make_bus`` leaves
``Bus.wgfmu`` empty when the fault is active from the start). Online calls fail with a communication error while the
FLEX link holds the exclusive bus lock (``flex_locked``): the transaction's WGFMU phase must release it first
(blueprint v2 2.6, ATV-14).

Extras beyond the protocol (simulator only, for the WG example fixtures and tests): ``session_open``,
``poll_quantum_s`` and the mixin ``transport/sim/wgfmu_extras.py`` (``set_warning_level``,
``treat_warnings_as_errors``, ``warnings``, ``error_summary``, ``completed_measure_event_size``,
``measure_event_completed``, ``measure_times``, ``force_levels``, ``rsu_path``). Setup checks: ``wgfmu_checks.py``;
waveform and measurement arithmetic: ``wgfmu_engine.py``.
"""

from __future__ import annotations

import math
import time
from collections import Counter, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from b1500_test_agent.models.sources import WgfmuCurrentRange, WgfmuForceRange, WgfmuMode, WgfmuVoltageRange
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.state import WgfmuChannelState
from b1500_test_agent.transport.sim.wgfmu_checks import (
    range_bounds,
    runtime_error,
    sequence_problem,
    setup_problem,
    static_drive,
)
from b1500_test_agent.transport.sim.wgfmu_engine import (
    TICK_S,
    ChannelProgram,
    Evaluator,
    MeasureSpec,
    NoiseSpec,
    PatternSpec,
    RangeSpec,
    compile_program,
    to_ticks,
)
from b1500_test_agent.transport.sim.wgfmu_extras import WgfmuExtras
from b1500_test_agent.transport.wgfmu.api import (
    ALWG_MODES,
    CHANNEL_NOT_FOUND,
    COMMUNICATION_ERROR,
    CONTEXT_ERROR,
    CURRENT_RANGE_A,
    FORCE_VOLTAGE_RANGES,
    FUNCTION_NOT_SUPPORTED,
    FW_ERROR,
    ILLEGAL_STRING,
    LIBRARY_ERROR,
    LIMITS,
    MEASURE_CURRENT_RANGES,
    MEASURE_MODES,
    MEASURE_VOLTAGE_RANGES,
    OPERATION_MODES,
    PARAMETER_OUT_OF_RANGE,
    PATTERN_ALREADY_EXISTS,
    PATTERN_NOT_FOUND,
    RESULT_NOT_READY,
    RESULT_OUT_OF_DATE,
    SEQUENCER_NOT_RUNNING,
    STATUS_ABORT_COMPLETED,
    STATUS_COMPLETED,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_RUNNING_ILLEGAL,
    UNIDENTIFIED_ERROR,
    VOLTAGE_RANGE_V,
    WARNING_LEVELS,
    WgfmuError,
    WgfmuMeasureMode,
    channel_ids_of,
    error_text,
    is_channel_id,
)

if TYPE_CHECKING:
    from b1500_test_agent.transport.sim.instrument import SimInstrument

POLL_QUANTUM_S = (0.001, 1.0)
"""Virtual time one status poll represents: 1 % of the run's total time, at least 1 ms, at most 1 s (a host polling
about once a second, blueprint v2 2.5; simulator convention)."""

DC_MEASURE_S = 1e-3
"""Virtual duration of one DC spot measurement (simulator convention, TODO(verify) at bring-up L8)."""

_MEMORY = int(LIMITS["memory_points"])
_GRID = LIMITS["grid_s"]


@dataclass
class _Run:
    """One sequencer run: compiled programs of the run channels, start time and its evaluation."""

    t0: float
    programs: dict[int, ChannelProgram]
    evaluator: Evaluator
    end_tick: int
    aborted_tick: float | None = None
    hung_tick: float | None = None
    illegal: set[int] = field(default_factory=set)
    out_of_date: bool = False
    finished: bool = False
    read_upto: dict[int, int] = field(default_factory=dict)
    overflow: dict[int, int] = field(default_factory=dict)
    runtime: dict[int, tuple[int, int, float, str]] = field(default_factory=dict)  # ch -> code, cap, tick, detail
    runtime_hit: set[int] = field(default_factory=set)
    pending: list[tuple[int, str]] = field(default_factory=list)  # run-time errors to raise once each

    def stop_tick(self) -> float:
        """Run tick at which the sequencers stop (end, abort or hang; a hung run never stops)."""
        if self.aborted_tick is not None:
            return self.aborted_tick
        if self.hung_tick is not None:
            return self.hung_tick
        return float(self.end_tick)


class SimWgfmu(WgfmuExtras):
    """``WgfmuApi`` on a ``SimInstrument`` (see the module docstring). ``flex_locked`` reports whether the FLEX
    link holds the exclusive bus lock; ``time_scale`` defaults to the scenario's ``timing``."""

    def __init__(self, instrument: SimInstrument, *, flex_locked: Callable[[], bool] | None = None,
                 time_scale: float | None = None) -> None:
        self._inst = instrument
        self._flex_locked = flex_locked
        self.time_scale = instrument.scenario.time_scale if time_scale is None else time_scale
        self._patterns: dict[str, PatternSpec] = {}
        self._sequences: dict[int, list[tuple[str, int]]] = {}
        self._pending: dict[int, dict[str, object]] = {}
        self._errors: deque[str] = deque()
        self._summary: list[str] = []
        self._warnings: list[tuple[str, str]] = []
        self.warning_level = "normal"
        self.treat_level = "off"
        self.timeout_s = LIMITS["timeout_default_s"]
        self.session: str | None = None
        self._run: _Run | None = None
        self._calls: Counter[str] = Counter()
        self.evaluating = False
        self._synced_at: float | None = None
        self.poll_quantum_s: float | None = None
        """Virtual time per status poll; ``None`` = ``POLL_QUANTUM_S`` (tests set 0 to read a run at exact times)."""
        instrument.wgfmu_unit = self

    # -- helpers: errors, warnings, faults -----------------------------------------------------------------------------

    def _fail(self, fn: str, code: int, detail: str = "", *, rc: int | None = None) -> WgfmuError:
        text = f"{fn}: {error_text(code, detail)}"
        if len(self._errors) < 1000:
            self._errors.append(text)
        self._summary.append(text)
        return WgfmuError(code, text, rc=rc, function=fn)

    def _warn(self, fn: str, level: str, detail: str) -> None:
        """Record a warning of ``level`` (severe/normal/information; WG p138 (4-68) Table 4-4)."""
        rank = WARNING_LEVELS[level]
        if self.treat_level != "off" and rank <= WARNING_LEVELS[self.treat_level]:
            raise self._fail(fn, UNIDENTIFIED_ERROR, f"warning treated as error: {detail}")
        if self.warning_level != "off" and rank <= WARNING_LEVELS[self.warning_level]:
            self._warnings.append((level, f"{fn}: {detail}"))

    def _gate(self, fn: str) -> None:
        """Count one call of ``fn`` and apply the ``wgfmu_error``/``wgfmu_hang`` faults."""
        self._calls[fn] += 1
        code, hang = self._inst.faults.wgfmu_call(fn)
        if hang:
            if fn == "execute":
                self._start_run(fn)
                if self._run is not None:
                    self._run.hung_tick = 0.0
            elif fn == "wait_until_completed" and self._run is not None and self._run.hung_tick is None:
                self._sync()
                self._run.hung_tick = self._tick()
            self._wait(self.timeout_s)
            raise self._fail(fn, COMMUNICATION_ERROR, f"no answer within the {self.timeout_s:g} s timeout "
                             "(simulated wgfmu_hang)")
        if code is not None:
            raise self._fail(fn, code, "(simulated wgfmu_error)", rc=None if code < 0 else FW_ERROR)

    def _online(self, fn: str) -> None:
        if self.session is None:
            raise self._fail(fn, CONTEXT_ERROR, "no session: call open_session first")
        if self._flex_locked is not None and self._flex_locked():
            raise self._fail(fn, COMMUNICATION_ERROR, "the B1500A is locked by another VISA session (the FLEX "
                             "link's exclusive lock)")

    def _channel(self, fn: str, ch: object) -> int:
        if not is_channel_id(ch) or ch not in self._installed():
            raise self._fail(fn, CHANNEL_NOT_FOUND, f"channel {ch!r} is not a WGFMU channel of this B1500A "
                             f"({', '.join(str(c) for c in self._installed()) or 'none'})")
        assert isinstance(ch, int)
        return ch

    def _installed(self) -> list[int]:
        slots = self._inst._slots()
        return channel_ids_of([s for s, m in slots.items() if MODULE_TYPE_BY_MODEL[m.model] == "WGFMU"])

    def _hw(self, ch: int) -> WgfmuChannelState:
        return self._inst.state.wgfmu.setdefault(ch, WgfmuChannelState())

    def _setup(self, ch: int) -> dict[str, object]:
        """Pending settings of ``ch`` (initially those of the hardware)."""
        if ch not in self._pending:
            hw = self._hw(ch)
            self._pending[ch] = {k: getattr(hw, k) for k in ("mode", "force_range", "measure_mode",
                                                            "current_range", "voltage_range", "measure_enabled")}
        return self._pending[ch]

    def _wait(self, seconds: float) -> None:
        """The host waits inside a library call: the shared clock moves on (a running SPGU output and a FLEX
        measurement progress too, ``SimInstrument.advance``)."""
        if seconds <= 0:
            return
        self._inst.advance(seconds)
        if self.time_scale > 0:
            time.sleep(seconds * self.time_scale)

    def _tick(self) -> float:
        run = self._run
        return 0.0 if run is None else max(0.0, (self._inst.clock - run.t0) / TICK_S)

    # -- session -------------------------------------------------------------------------------------------------------

    def open_session(self, address: str) -> None:
        fn = "open_session"
        self._gate(fn)
        if self._inst.faults.wgfmu_dll_missing():
            raise self._fail(fn, LIBRARY_ERROR, "the instrument library could not be loaded (simulated "
                             "wgfmu_dll_missing)")
        if not isinstance(address, str) or not address.strip():
            raise self._fail(fn, ILLEGAL_STRING, "empty address")
        if self.session is not None and self.session != address:
            raise self._fail(fn, CONTEXT_ERROR, f"a session to {self.session} is already open")
        if self._flex_locked is not None and self._flex_locked():
            raise self._fail(fn, COMMUNICATION_ERROR, "the B1500A is locked by another VISA session (the FLEX "
                             "link's exclusive lock)")
        self.session = address
        if self._inst.errors:
            self._warn(fn, "normal", f"the instrument error queue is not empty ({len(self._inst.errors)} error(s))")

    def close_session(self) -> None:
        fn = "close_session"
        self._gate(fn)
        if self.session is not None and self._inst.errors:
            self._warn(fn, "normal", f"the instrument error queue is not empty ({len(self._inst.errors)} error(s))")
        self.session = None

    @property
    def session_open(self) -> bool:
        """True between ``open_session`` and ``close_session``."""
        return self.session is not None

    def initialize(self) -> None:
        fn = "initialize"
        self._gate(fn)
        self._online(fn)
        self._sync()
        self._run = None
        self._pending.clear()
        self._reset_channels()
        self._commit_static()

    def _reset_channels(self) -> None:
        """Every channel to its initial state; a stuck RSU relay (``wgfmu_disconnect_fails``) stays connected."""
        for ch in self._installed():
            hw = self._hw(ch)
            if hw.connected and self._inst.faults.wgfmu_relay_stuck(ch):
                self._inst.state.wgfmu[ch] = WgfmuChannelState(mode=hw.mode, connected=True, voltage=hw.voltage)
            else:
                self._inst.state.wgfmu[ch] = WgfmuChannelState()

    def clear(self) -> None:
        fn = "clear"
        self._gate(fn)
        self._patterns.clear()
        self._sequences.clear()
        self._errors.clear()
        self._summary.clear()
        self._warnings.clear()
        self.warning_level, self.treat_level = "normal", "off"
        if self._run is not None:
            self._run.out_of_date = True

    def set_timeout(self, s: float) -> None:
        fn = "set_timeout"
        self._gate(fn)
        self._online(fn)
        if not isinstance(s, int | float) or not math.isfinite(s) or s < LIMITS["timeout_min_s"]:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"timeout {s!r} s is below 1 s")
        self.timeout_s = float(s)

    def channel_ids(self) -> list[int]:
        fn = "channel_ids"
        self._gate(fn)
        self._online(fn)
        return self._installed()

    # -- channel setup (pending until update/execute/DC) ---------------------------------------------------------------

    def _set(self, fn: str, ch: int, key: str, value: object, allowed: dict[str, int]) -> None:
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        if value not in allowed:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"{key} {value!r} (allowed: {', '.join(allowed)})")
        self._setup(ch)[key] = value

    def set_operation_mode(self, ch: int, mode: WgfmuMode) -> None:
        self._set("set_operation_mode", ch, "mode", mode, OPERATION_MODES)

    def set_force_voltage_range(self, ch: int, rng: WgfmuForceRange) -> None:
        self._set("set_force_voltage_range", ch, "force_range", rng, FORCE_VOLTAGE_RANGES)

    def set_measure_mode(self, ch: int, mode: WgfmuMeasureMode) -> None:
        self._set("set_measure_mode", ch, "measure_mode", mode, MEASURE_MODES)
        if mode == "current":
            self._setup(ch)["voltage_range"] = "5v"  # Table 4-7: current mode sets the 5 V voltage range

    def set_measure_current_range(self, ch: int, rng: WgfmuCurrentRange) -> None:
        self._set("set_measure_current_range", ch, "current_range", rng, MEASURE_CURRENT_RANGES)

    def set_measure_voltage_range(self, ch: int, rng: WgfmuVoltageRange) -> None:
        self._set("set_measure_voltage_range", ch, "voltage_range", rng, MEASURE_VOLTAGE_RANGES)

    def set_measure_enabled(self, ch: int, on: bool) -> None:
        fn = "set_measure_enabled"
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        if not isinstance(on, bool):
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"status {on!r}")
        if self._setup(ch)["mode"] == "dc":
            raise self._fail(fn, FUNCTION_NOT_SUPPORTED, f"channel {ch} is in DC mode")
        self._setup(ch)["measure_enabled"] = on

    # -- waveform setup (offline) --------------------------------------------------------------------------------------

    def _pattern(self, fn: str, name: object) -> PatternSpec:
        if not isinstance(name, str) or not name:
            raise self._fail(fn, ILLEGAL_STRING, "empty pattern name")
        spec = self._patterns.get(name)
        if spec is None:
            raise self._fail(fn, PATTERN_NOT_FOUND, f"pattern {name!r}")
        return spec

    def create_pattern(self, name: str, v0: float) -> None:
        fn = "create_pattern"
        self._gate(fn)
        if not isinstance(name, str) or not name:
            raise self._fail(fn, ILLEGAL_STRING, "empty pattern name")
        if name in self._patterns:
            raise self._fail(fn, PATTERN_ALREADY_EXISTS, f"pattern {name!r}")
        if not _finite(v0) or abs(v0) > LIMITS["max_abs_v"]:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"initial voltage {v0!r} V")
        self._patterns[name] = PatternSpec(float(v0))

    def add_vectors(self, name: str, dt: Sequence[float], v: Sequence[float]) -> None:
        fn = "add_vectors"
        self._gate(fn)
        spec = self._pattern(fn, name)
        dts, volts = np.asarray(dt, dtype=float).ravel(), np.asarray(v, dtype=float).ravel()
        if len(dts) == 0 or len(dts) != len(volts):
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"{len(dts)} times and {len(volts)} voltages")
        if not (np.all(np.isfinite(dts)) and np.all(np.isfinite(volts))):
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, "non-finite time or voltage")
        ticks = np.floor(dts / _GRID + 0.5)
        if np.any(ticks < 1):
            k = int(np.argmax(ticks < 1))
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"dt[{k}] = {dts[k]:g} s is below 10 ns")
        if np.any(np.abs(volts) > LIMITS["max_abs_v"]):
            k = int(np.argmax(np.abs(volts) > LIMITS["max_abs_v"]))
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"v[{k}] = {volts[k]:g} V")
        spec.dts.extend(int(t) for t in ticks)
        spec.volts.extend(float(x) for x in volts)

    def set_measure_event(self, pattern: str, event: str, t: float, points: int, interval: float, average: float,
                          raw: bool) -> None:
        fn = "set_measure_event"
        self._gate(fn)
        spec = self._pattern(fn, pattern)
        if not isinstance(event, str) or not event:
            raise self._fail(fn, ILLEGAL_STRING, "empty event name")
        if isinstance(points, bool) or not isinstance(points, int | np.integer) or points < 1:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"points {points!r}")
        for label, value in (("time", t), ("interval", interval), ("average", average)):
            if not _finite(value) or value < 0:
                raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"{label} {value!r} s")
        if to_ticks(interval) < 1:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"interval {interval:g} s is below 10 ns")
        new = MeasureSpec(event, to_ticks(t), int(points), to_ticks(interval), to_ticks(average), bool(raw))
        kept = [e for e in spec.measures if not e.overlaps(new)]
        if len(kept) != len(spec.measures):
            self._warn(fn, "severe", f"event {event!r} overwrites {len(spec.measures) - len(kept)} overlapping "
                       f"measurement event(s) of pattern {pattern!r}")
        spec.measures = [*kept, new]

    def set_range_event(self, pattern: str, event: str, t: float, rng: WgfmuCurrentRange) -> None:
        fn = "set_range_event"
        self._gate(fn)
        spec = self._pattern(fn, pattern)
        if not isinstance(event, str) or not event:
            raise self._fail(fn, ILLEGAL_STRING, "empty event name")
        if rng not in MEASURE_CURRENT_RANGES:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"range {rng!r}")
        if not _finite(t) or t < 0:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"time {t!r} s")
        tick = to_ticks(t)
        kept = [r for r in spec.ranges if r.t != tick]
        if len(kept) != len(spec.ranges):
            self._warn(fn, "severe", f"range event {event!r} overwrites the range event at {t:g} s of {pattern!r}")
        spec.ranges = [*kept, RangeSpec(event, tick, rng)]

    def add_sequence(self, ch: int, pattern: str, count: float) -> None:
        fn = "add_sequence"
        self._gate(fn)
        if not is_channel_id(ch):
            raise self._fail(fn, CHANNEL_NOT_FOUND, f"channel {ch!r}")
        self._pattern(fn, pattern)
        if not _finite(count):
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"count {count!r}")
        rounded = math.floor(float(count) + 0.5)
        if rounded < LIMITS["count_min"]:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"count {count!r} is below 1")
        self._sequences.setdefault(int(ch), []).append((pattern, rounded))

    # -- applying the setup --------------------------------------------------------------------------------------------

    def _apply(self, fn: str, ch: int) -> WgfmuChannelState:
        """Apply the pending settings of ``ch`` to the hardware (3302/3303 for settings PG cannot take)."""
        problem = setup_problem(ch, self._setup(ch))
        if problem is not None:
            raise self._fail(fn, *problem)
        hw = self._hw(ch)
        for key, value in self._setup(ch).items():
            setattr(hw, key, value)
        return hw

    def _check_sequence(self, fn: str, ch: int, hw: WgfmuChannelState) -> None:
        """Highest-limit checks of one ALWG channel's sequence (``wgfmu_checks.sequence_problem``)."""
        problem = sequence_problem(ch, hw, self._sequences.get(ch, []), self._patterns)
        if problem is not None:
            raise self._fail(fn, *problem)

    def update(self) -> None:
        fn = "update"
        self._gate(fn)
        self._online(fn)
        self._sync()
        run = self._run
        if run is not None and not run.finished:
            run.illegal.update(run.programs)  # a setup change while the sequencer runs (Table 4-17 note b)
            return
        if run is not None:
            run.out_of_date = True
        for ch in self._installed():
            hw = self._apply(fn, ch)
            if hw.mode in ALWG_MODES and self._sequences.get(ch):
                self._check_sequence(fn, ch, hw)
                hw.voltage = self._patterns[self._sequences[ch][0][0]].v0
        self._commit_static()

    def connect(self, ch: int) -> None:
        fn = "connect"
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        self._sync()
        self._hw(ch).connected = True
        self._commit_static()

    def disconnect(self, ch: int) -> None:
        fn = "disconnect"
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        self._sync()
        if self._inst.faults.wgfmu_disconnect_fails(ch):
            raise self._fail(fn, UNIDENTIFIED_ERROR, f"channel {ch}: the RSU relay did not open (simulated "
                             "wgfmu_disconnect_fails)")
        run = self._run
        if run is not None and not run.finished and ch in run.programs:
            run.illegal.add(ch)
        self._hw(ch).connected = False
        self._commit_static()

    # -- execution -----------------------------------------------------------------------------------------------------

    def execute(self) -> None:
        fn = "execute"
        self._gate(fn)
        self._online(fn)
        self._start_run(fn)

    def _start_run(self, fn: str) -> None:
        self._sync()
        if self._run is not None and not self._run.finished:
            self._finish_run(abort_at=self._tick())
        self._run = None
        chans = []
        for ch in self._installed():
            hw = self._apply(fn, ch)
            if hw.connected and hw.mode in ALWG_MODES:
                chans.append(ch)
        if not chans:
            self._warn(fn, "normal", "no connected channel is in Fast IV or PG mode")
            return
        programs: dict[int, ChannelProgram] = {}
        for ch in chans:
            hw = self._hw(ch)
            if not self._sequences.get(ch):
                raise self._fail(fn, 3201, f"channel {ch} has no sequence")
            self._check_sequence(fn, ch, hw)
            programs[ch] = compile_program(ch, hw.model_dump(), self._sequences[ch], self._patterns)
        state = self._inst.state
        state.wgfmu_runs += 1
        noise = self._inst.scenario.noise
        rngs = {ch: np.random.default_rng([noise.seed, 0x5767, state.wgfmu_runs, ch]) for ch in programs}
        evaluator = Evaluator(self._inst.circuit, programs, self._fixed_levels(exclude=programs),
                              NoiseSpec(float(noise.floor_a.get("WGFMU", 0.0)), float(noise.rel)), rngs)
        end = max(p.end for p in programs.values())
        run = _Run(self._inst.clock, programs, evaluator, end, read_upto={ch: 0 for ch in programs})
        for ch, prog in programs.items():
            error = runtime_error(ch, prog)
            if error is not None:
                run.runtime[ch] = error
            self._hw(ch).running = True
            self._hw(ch).voltage = prog.first_level
        self._run = run
        self._synced_at = None

    def wait_until_completed(self) -> None:
        fn = "wait_until_completed"
        self._gate(fn)
        self._online(fn)
        self._sync()
        run = self._run
        if run is None or not any(self._hw(ch).connected for ch in run.programs):
            raise self._fail(fn, SEQUENCER_NOT_RUNNING, "no sequencer has run on a connected Fast IV/PG channel")
        if run.hung_tick is not None and run.aborted_tick is None:
            self._wait(self.timeout_s)
            raise self._fail(fn, COMMUNICATION_ERROR, f"no answer within the {self.timeout_s:g} s timeout (the "
                             "sequencer does not complete)")
        remaining = run.t0 + run.stop_tick() * TICK_S - self._inst.clock
        self._wait(max(0.0, remaining))
        self._sync()
        self._raise_runtime(fn)

    def abort(self) -> None:
        fn = "abort"
        self._gate(fn)
        self._online(fn)
        self._sync()
        run = self._run
        if run is not None and not run.finished:
            self._finish_run(abort_at=self._tick())
        for ch in self._installed():
            self._hw(ch).running = False  # also a sequencer another process left running
        self._commit_static()

    def _finish_run(self, *, abort_at: float | None = None) -> None:
        run = self._run
        assert run is not None
        if abort_at is not None:  # a hung sequencer stopped producing at its hang
            run.aborted_tick = min(abort_at, run.stop_tick())
            run.hung_tick = None
        stop = run.stop_tick()
        self.evaluating = True
        try:
            run.evaluator.evaluate_until(stop)
        finally:
            self.evaluating = False
        for ch, prog in run.programs.items():
            hw = self._hw(ch)
            hw.running = False
            hw.voltage = prog.level_at(stop)
        run.finished = True
        self._check_overflow(run, stop)
        self._commit_static()

    def _sync(self) -> None:
        """Bring the run up to the instrument clock: evaluate the points complete by now (and step dynamic devices),
        detect memory overflow, update the channels' output levels and finish a run that has ended."""
        run = self._run
        if run is None or run.finished or self.evaluating:
            return
        now = self._inst.clock
        if self._synced_at == now:
            return
        self._synced_at = now
        tick = self._tick()
        stop = run.stop_tick()
        if run.hung_tick is None and tick >= stop:
            self._finish_run()
            return
        self.evaluating = True
        try:
            run.evaluator.evaluate_until(min(tick, stop))
        finally:
            self.evaluating = False
        for ch, prog in run.programs.items():
            self._hw(ch).voltage = prog.level_at(min(tick, stop))
        self._inst._sync_devices()
        self._check_overflow(run, min(tick, stop))

    def _check_overflow(self, run: _Run, tick: float) -> None:
        """Queue the run-time errors the sequencers reached by ``tick``: 3051/3052 and memory overflow (3050)."""
        for ch, (code, _, at, detail) in run.runtime.items():
            if ch not in run.runtime_hit and tick >= at:
                run.runtime_hit.add(ch)
                run.pending.append((code, detail))
        for ch in run.programs:
            if ch in run.overflow:
                continue
            done = self._measured(run, ch, tick)
            if done - run.read_upto[ch] > _MEMORY:
                cap = run.read_upto[ch] + _MEMORY
                run.overflow[ch] = cap
                run.pending.append((3050, (f"channel {ch}: {done - run.read_upto[ch]} values not read yet "
                                           f"(memory about {_MEMORY}); values from index {cap} are lost")))

    def _measured(self, run: _Run, ch: int, tick: float | None = None) -> int:
        """Values of ``ch`` stored by ``tick`` (default: now): complete points, up to a run-time error, at most the
        memory overflow cap."""
        prog = run.programs[ch]
        points = prog.completed_points(min(self._tick() if tick is None else tick, run.stop_tick()))
        runtime = run.runtime.get(ch)
        if runtime is not None:
            points = min(points, runtime[1])
        values = prog.values_before_point(points)
        return min(values, run.overflow.get(ch, values))

    def _raise_runtime(self, fn: str) -> None:
        run = self._run
        if run is not None and run.pending:
            code, detail = run.pending.pop(0)
            raise self._fail(fn, code, detail, rc=FW_ERROR)

    # -- status and data -----------------------------------------------------------------------------------------------

    def _poll(self) -> None:
        if self.poll_quantum_s is not None:
            self._wait(self.poll_quantum_s)
            return
        run = self._run
        total = run.end_tick * TICK_S if run is not None else 0.0
        self._wait(min(POLL_QUANTUM_S[1], max(POLL_QUANTUM_S[0], total / 100.0)))

    def _channel_state(self, ch: int) -> tuple[int, float, float]:
        run = self._run
        if run is None or ch not in run.programs:
            if self._hw(ch).running:
                return STATUS_RUNNING, 0.0, 0.0  # a sequencer started by another process
            return STATUS_IDLE, 0.0, 0.0
        prog = run.programs[ch]
        total = prog.total_s
        if ch in run.illegal:
            return STATUS_RUNNING_ILLEGAL, min(self._tick(), prog.end) * TICK_S, total
        if run.aborted_tick is not None:
            return STATUS_ABORT_COMPLETED, min(run.aborted_tick, prog.end) * TICK_S, total
        if run.hung_tick is not None:
            return STATUS_RUNNING, min(run.hung_tick, prog.end) * TICK_S, total
        tick = self._tick()
        if tick >= prog.end:
            return STATUS_COMPLETED, total, total
        return STATUS_RUNNING, tick * TICK_S, total

    def status(self) -> tuple[int, float, float]:
        fn = "status"
        self._gate(fn)
        self._online(fn)
        self._poll()
        self._sync()
        self._raise_runtime(fn)
        run = self._run
        chans = list(run.programs) if run is not None else [ch for ch in self._installed() if self._hw(ch).running]
        states = [self._channel_state(ch) for ch in chans]
        if not states:
            return STATUS_IDLE, 0.0, 0.0
        return max(s[0] for s in states), max(s[1] for s in states), max(s[2] for s in states)

    def channel_status(self, ch: int) -> tuple[int, float, float]:
        fn = "channel_status"
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        self._alwg_only(fn, ch)
        self._poll()
        self._sync()
        self._raise_runtime(fn)
        return self._channel_state(ch)

    def _alwg_only(self, fn: str, ch: int) -> None:
        if self._hw(ch).mode not in ALWG_MODES:
            self._warn(fn, "severe", f"channel {ch} is not in Fast IV or PG mode")

    def measure_value_size(self, ch: int) -> tuple[int, int]:
        fn = "measure_value_size"
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        self._alwg_only(fn, ch)
        self._poll()
        self._sync()
        self._raise_runtime(fn)
        run = self._run
        if run is None or ch not in run.programs:
            return 0, 0
        return self._measured(run, ch), run.programs[ch].total_values

    def measure_values(self, ch: int, offset: int, size: int) -> tuple[np.ndarray, np.ndarray]:
        fn = "measure_values"
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        self._sync()
        run = self._run
        if run is None or ch not in run.programs:
            raise self._fail(fn, CONTEXT_ERROR, f"channel {ch} has no measurement data (idle)")
        if run.out_of_date or ch in run.illegal:
            raise self._fail(fn, RESULT_OUT_OF_DATE, f"channel {ch}: the setup changed after the run")
        total = run.programs[ch].total_values
        if isinstance(offset, bool) or not isinstance(offset, int | np.integer) or total == 0 \
                or not 0 <= offset < total:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"offset {offset!r} (total {total})")
        if not isinstance(size, int | np.integer) or size < 1:
            raise self._fail(fn, PARAMETER_OUT_OF_RANGE, f"size {size!r}")
        measured = self._measured(run, ch)
        if offset >= measured:
            if ch in run.overflow and offset >= run.overflow[ch]:
                raise self._fail(fn, 3050, f"channel {ch}: value {offset} was lost (memory overflow)", rc=FW_ERROR)
            raise self._fail(fn, RESULT_NOT_READY, f"channel {ch}: {measured} of {total} values measured")
        stop = min(offset + int(size), measured)
        if offset + int(size) > total:
            self._warn(fn, "normal", f"offset + size = {offset + int(size)} exceeds the {total} values")
        times, values = run.evaluator.values(ch, int(offset), stop)
        run.read_upto[ch] = max(run.read_upto[ch], stop)
        return times, values

    # -- DC measurement ------------------------------------------------------------------------------------------------

    def _dc_channel(self, fn: str, ch: int) -> WgfmuChannelState:
        self._gate(fn)
        self._online(fn)
        ch = self._channel(fn, ch)
        self._sync()
        hw = self._apply(fn, ch)
        if hw.mode != "dc":
            raise self._fail(fn, FUNCTION_NOT_SUPPORTED, f"channel {ch} is not in DC mode ({hw.mode})")
        return hw

    def dc_force_voltage(self, ch: int, v: float) -> None:
        fn = "dc_force_voltage"
        hw = self._dc_channel(fn, ch)
        if not _finite(v) or not any(lo - 1e-12 <= v <= hi + 1e-12 for lo, hi in range_bounds("dc", hw.force_range)):
            raise self._fail(fn, 3301, f"channel {ch}: {v!r} V in the {hw.force_range} range", rc=FW_ERROR)
        hw.voltage = float(v)
        self._commit_static()

    def dc_measure_value(self, ch: int) -> float:
        fn = "dc_measure_value"
        hw = self._dc_channel(fn, ch)
        levels = self._fixed_levels()
        canon = canonical_channel(ch)
        self.evaluating = True
        try:
            if self._inst.circuit.dynamic:
                currents = self._inst.circuit.raw_advance(DC_MEASURE_S, levels)
            else:
                currents = self._inst.circuit.raw_currents(levels)
        finally:
            self.evaluating = False
        self._wait(DC_MEASURE_S)
        self._inst._sync_devices()
        if hw.measure_mode == "voltage" or canon not in levels:
            full = VOLTAGE_RANGE_V[hw.voltage_range]  # type: ignore[index]
            return float(np.clip(levels.get(canon, 0.0) if hw.connected else 0.0, -full, full))
        full = CURRENT_RANGE_A[hw.current_range]  # type: ignore[index]
        value = currents.get(canon, 0.0)
        noise = self._inst.scenario.noise
        sigma = math.hypot(noise.floor_a.get("WGFMU", 0.0) * full / 1e-2, noise.rel * abs(value))
        if sigma > 0:
            rng = np.random.default_rng([noise.seed, 0x4443, self._inst.state.wgfmu_runs, self._calls[fn], ch])
            value += float(rng.normal(0.0, sigma))
        return float(np.clip(value, -full, full))

    # -- self-test, self-calibration, errors ---------------------------------------------------------------------------

    def _maintenance(self, fn: str) -> int:
        self._gate(fn)
        self._online(fn)
        try:
            self._inst._selftest()  # mainframe self-test: closes the SMUs (refused above 42 V)
        except flex.FlexError as exc:
            raise self._fail(fn, exc.code, "refused by the mainframe (high voltage output)", rc=FW_ERROR) from None
        self._inst._commit_dc()
        self._run = None
        self._reset_channels()
        self._pending.clear()
        self._commit_static()
        return 0

    def self_test(self) -> int:
        return self._maintenance("self_test")

    def self_calibration(self) -> int:
        return self._maintenance("self_calibration")

    def errors(self) -> list[str]:
        self._gate("errors")
        found = list(self._errors)
        self._errors.clear()
        return found

    # -- circuit coupling ----------------------------------------------------------------------------------------------

    def _host_levels(self) -> dict[int | str, float]:
        """Levels the FLEX side applies to the DUT now: the SMUs as their DC solution applies them (voltage and
        current forcing, compliance-limited), the output-on HV-SPGU channels and the MFCMU sides (``"7H"``)."""
        inst = self._inst
        applied: dict[int, float] = {}
        if inst._on_levels() or inst._on_currents():
            applied, _, _ = inst.dc_solution()
        sides, _ = inst._route_sides(applied)
        return {**applied, **sides}

    def _fixed_levels(self, exclude: dict[int, ChannelProgram] | None = None) -> dict[int | str, float]:
        """Every level that drives the DUT now except the run channels: the FLEX side (``_host_levels``) and the
        WGFMU channels connected outside a run (DC mode, a held last voltage)."""
        levels = self._host_levels()
        driven, _ = self.drive()
        for canon, v in driven.items():
            if exclude is None or not any(canonical_channel(ch) == canon for ch in exclude):
                levels[canon] = v
        return levels

    def drive(self) -> tuple[dict[int, float], dict[int, int]]:
        """Levels the WGFMU channels drive through their RSUs now and the RSU SMU paths (``DrivenCircuit``)."""
        if not self.evaluating and self._run is not None:
            self._sync()
        state = self._inst.state.wgfmu
        if not state and not self._inst.scenario.rsu_smu:
            return {}, {}
        return static_drive(state, self._inst.scenario.rsu_smu)

    def _commit_static(self) -> None:
        """Apply the present static levels (the FLEX side + WGFMU-driven terminals) to stateful devices."""
        circuit = self._inst.circuit
        if circuit.has_state:
            levels = self._host_levels()
            driven, aliases = static_drive(self._inst.state.wgfmu, self._inst.scenario.rsu_smu)
            levels.update(driven)
            for wg, smu in aliases.items():
                if smu in levels:
                    levels[wg] = levels[smu]
            circuit.raw_commit(levels)
            self._inst._sync_devices()

    def on_state_import(self) -> None:
        """The persistent state was replaced (a transaction loaded it): a run another process stopped is over."""
        run = self._run
        if run is not None and not run.finished and not any(self._hw(ch).running for ch in run.programs):
            run.finished = True
            run.out_of_date = True
        self._synced_at = None


def _finite(value: object) -> bool:
    return isinstance(value, int | float | np.integer | np.floating) and not isinstance(value, bool) and math.isfinite(
        float(value))  # type: ignore[arg-type]
