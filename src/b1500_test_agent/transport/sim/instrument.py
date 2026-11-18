"""``SimInstrument`` (deterministic FLEX state machine, dispatcher over the units) and ``SimTransport`` (its
``Transport`` adapter), blueprint 4.

Behaviour follows the Keysight B1500 Series Programming Guide, Edition 15 ("PG", physical PDF pages) for the v1
FLEX subset (``flex.SUPPORTED``); anything else queues error 100 and is logged ``unsupported``. ``SimInstrument``
keeps the clock, the persistent state, the error queue, the command log, the measurement lifecycle and the dispatch;
the FLEX handlers live in units registered by mnemonic (``units/core.py``: identity, status, buffer, format,
output switches, A/D converters; ``units/smu.py``: ranging, modes, sources and the measurement engine). Each
supported mnemonic has exactly one handler (``units.base.handler_table``; test ``tests/sim/test_units.py``).

Time is virtual: ``clock`` (s) advances only when the host waits (a read, a serial poll). A measurement started by
``XE`` at ``t0`` ends at ``t0 + duration``, where the duration comes from ``WT`` and the ADC settings (times the
``slow`` fault factor). Commands other than a lone ``AB`` that arrive while a measurement runs are executed after
it (the B1500 executes commands sequentially, PG PDF 352), so their responses become readable only at its end. A
read whose data is not ready within its timeout raises ``TransportTimeout``. ``timing: scaled(f)`` additionally
sleeps ``f`` real seconds per virtual second waited (``scaled`` = ``SCALED_TIME_FACTOR``); ``instant`` never sleeps
(blueprint v2 4.1). Status byte: PDF 76-77; device clear initialises like power-on (PDF 175).

Simulator conventions (not from the manual): STB bit 3 tracks the interlock state continuously (the blueprint's
reading, verified on hardware as ATV-10; the PG describes a latched bit, PDF 76); compliance is symmetric
(|I| ≤ |Icomp|); a fixed current range overflows above 115 % of full scale; voltage measurements are noiseless.

Device state (FeFET polarization): the voltages actually applied are committed to the circuit after every DC output
change (``DC_COMMIT_COMMANDS``) and after every measured sweep step (all steps are evaluated at ``XE``; an ``AB`` or
device clear before the end rolls the state back to the last completed step). ``state.devices`` mirrors the circuit
state, so it is saved and loaded with the rest of the persistent state.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from b1500_test_agent.models.measurement import CHANNEL_NUMBERS
from b1500_test_agent.models.sim import SimFault
from b1500_test_agent.models.station import (
    MODULE_TYPE_BY_MODEL,
    SIM_SCALED_DEFAULT,
    SMU_TYPES,
    TWO_CHANNEL_TYPES,
    SimScenario,
    SimSlot,
)
from b1500_test_agent.transport.base import BusLocked, TransportClosed, TransportError, TransportTimeout
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import Circuit, canonical_channel
from b1500_test_agent.transport.sim.faults import FaultEngine
from b1500_test_agent.transport.sim.format import frame
from b1500_test_agent.transport.sim.state import (
    COMMAND_LOG_LIMIT,
    ChannelState,
    CommandRecord,
    Outcome,
    SimPersistentState,
    load_state_file,
    save_state_file,
)
from b1500_test_agent.transport.sim.units.base import DEFAULT_ICOMP, FOREVER, Measurement, Unsupported, handler_table
from b1500_test_agent.transport.sim.units.core import CoreUnit
from b1500_test_agent.transport.sim.units.smu import SmuUnit

SCALED_TIME_FACTOR = SIM_SCALED_DEFAULT
"""Real seconds slept per virtual second with ``timing: scaled`` (no factor); ``scaled(f)`` sleeps ``f``."""

POLL_ADVANCE_S = 0.01
"""Virtual time a serial poll takes (so polling loops see measurements finish)."""

DC_COMMIT_COMMANDS = frozenset({"CN", "CL", "DZ", "DV", "*RST", "*TST?", "*CAL?"})
"""Commands after which the DC output levels are committed to stateful devices."""


class SimSafetyError(AssertionError):
    """``assert_safe()`` failed: an output is on or non-zero, or a measurement is still pending."""


class SimulatedInterrupt(KeyboardInterrupt):
    """The ``run_interrupt`` fault: the host process is interrupted (Ctrl-C, a signal stopping the server) while a
    measurement runs (blueprint v2 4.3)."""


@dataclass
class _Message:
    text: str
    ready_at: float


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _quick_mnemonic(part: str) -> str:
    try:
        return flex.parse_command(part).mnemonic
    except flex.FlexError:
        return ""


class SimInstrument(CoreUnit, SmuUnit):
    """In-process B1500A: ``handle(line)`` executes one command line and returns the query response, if any.

    Query responses and measurement data are buffered as on the instrument and read with ``read_message``.
    ``state`` is the persistent part (outputs, DUT state, command log); ``faults`` the active fault engine.
    """

    def __init__(self, scenario: SimScenario, *, faults: Iterable[SimFault] = ()) -> None:
        self.scenario = scenario
        self.faults = FaultEngine(faults)
        self.circuit = Circuit(scenario)
        self.state = SimPersistentState(scenario=scenario.name, auto_calibration=scenario.auto_calibration)
        self.state.devices = self.circuit.export_state()
        self.interrupt_pending = False
        """Set by ``XE`` when a ``run_interrupt`` fault fires for that measurement; the link raises at its read."""
        self.clock = 0.0
        self._busy_until = 0.0
        self._timer_zero = 0.0
        self._errors: deque[int] = deque()
        self._error_flag = False
        self._queries: deque[_Message] = deque()
        self._buffer: list[str] = []
        self._measurement: Measurement | None = None
        self._input_queue: list[str] = []
        self._interlock_open = not scenario.interlock_closed
        self._reset_settings()
        self._sync_channels()
        self._handlers: dict[str, Callable[[flex.Command], str | None]] = {
            mnemonic: getattr(self, name) for mnemonic, name in handler_table(type(self)).items()
        }

    # -- settings ------------------------------------------------------------------------------------------------------

    def _reset_settings(self) -> None:
        """Measurement setup of every unit to its initial settings (PG Table 2-13, PDF 180)."""
        self._reset_core_settings()
        self._reset_smu_settings()

    def _slots(self) -> dict[int, SimSlot]:
        override = self.faults.modules()
        return {s.slot: s for s in (override if override is not None else self.scenario.slots)}

    def _module_type(self, slot: int) -> str | None:
        module = self._slots().get(slot)
        return None if module is None else MODULE_TYPE_BY_MODEL[module.model]

    def installed_channels(self) -> list[int]:
        """Canonical channel numbers of the installed modules (two-channel modules: ``slot`` and ``slot*100+2``)."""
        channels: list[int] = []
        for slot in sorted(self._slots()):
            channels.append(slot)
            if self._module_type(slot) in TWO_CHANNEL_TYPES:
                channels.append(slot * 100 + 2)
        return channels

    def _sync_channels(self) -> None:
        for channel in self.installed_channels():
            self.state.channels.setdefault(channel, ChannelState())

    def _channel_type(self, channel: int) -> str | None:
        slot = channel if channel <= 10 else channel // 100
        module = self._module_type(slot)
        if module is None or (channel > 10 and module not in TWO_CHANNEL_TYPES):
            return None
        return module

    def _channel(self, arg: str, *, kinds: frozenset[str] | None = None) -> int:
        """Parse a channel argument (PG Table 4-1); errors 121 (number), 153 (no module), 151 (wrong module)."""
        number = flex.integer(arg)
        if number not in CHANNEL_NUMBERS:
            raise flex.FlexError(flex.ERR_CHANNEL_NUMBER, f"channel {number}")
        channel = canonical_channel(number)
        module = self._channel_type(channel)
        if module is None:
            raise flex.FlexError(flex.ERR_NO_MODULE, f"channel {number}")
        if kinds is not None and module not in kinds:
            raise flex.FlexError(flex.ERR_NOT_ALLOWED, f"channel {number} is a {module}")
        self.state.channels.setdefault(channel, ChannelState())
        return channel

    def _smu(self, arg: str) -> int:
        return self._channel(arg, kinds=SMU_TYPES)

    def _is_smu(self, channel: int) -> bool:
        return self._channel_type(channel) in SMU_TYPES

    def interlock_open(self) -> bool:
        """Whether the simulated interlock circuit is open."""
        return self._interlock_open or self.faults.interlock_opens_now()

    def _high_voltage(self, levels: dict[int, float]) -> bool:
        return any(abs(v) > flex.INTERLOCK_OPEN_MAX_V for v in levels.values())

    def _check_interlock(self, voltage: float) -> None:
        if abs(voltage) > flex.INTERLOCK_OPEN_MAX_V and self.interlock_open():
            raise flex.FlexError(flex.ERR_INTERLOCK, f"{voltage} V with the interlock open")

    # -- errors, log, time ---------------------------------------------------------------------------------------------

    def _queue_error(self, code: int) -> None:
        if len(self._errors) < flex.ERROR_QUEUE_SIZE:
            self._errors.append(code)
        self._error_flag = True

    @property
    def errors(self) -> list[int]:
        """Queued error codes (oldest first), without draining them."""
        return list(self._errors)

    def _now(self) -> float:
        return max(self.clock, self._busy_until)

    def _log(self, line: str, command: str, mnemonic: str, args: Iterable[str], outcome: Outcome,
             error: int | None = None) -> None:
        now = self._now()
        record = CommandRecord(
            seq=self.state.next_seq, ts=_utc_now(), clock_s=round(self.clock if now == FOREVER else now, 9),
            line=line, command=command, mnemonic=mnemonic, args=list(args), outcome=outcome, error=error,
            source=mnemonic in flex.SOURCE_COMMANDS,
        )
        self.state.next_seq += 1
        self.state.command_log.append(record)
        if len(self.state.command_log) > 2 * COMMAND_LOG_LIMIT:
            self.state.trim_log()

    def _log_unexecuted(self, line: str, part: str, outcome: Outcome) -> None:
        try:
            cmd = flex.parse_command(part)
        except flex.FlexError:
            self._log(line, part, "", (), outcome)
        else:
            self._log(line, cmd.text, cmd.mnemonic, cmd.args, outcome)

    def record_dropped(self, line: str) -> None:
        """Log every command of ``line`` as ``dropped`` (written by the host, never received; link faults)."""
        for part in flex.split_line(line) or [line]:
            self._log_unexecuted(line, part, "dropped")

    @property
    def command_log(self) -> list[CommandRecord]:
        """Every command the instrument saw (and dropped writes), oldest first."""
        return self.state.command_log

    def commands(self, mnemonic: str | None = None, outcome: Outcome | None = None) -> list[CommandRecord]:
        """Command records filtered by mnemonic and/or outcome."""
        return [r for r in self.state.command_log
                if (mnemonic is None or r.mnemonic == mnemonic) and (outcome is None or r.outcome == outcome)]

    def source_commands(self) -> list[CommandRecord]:
        """Executed commands that set an output level (``DV``, ``WV``)."""
        return [r for r in self.state.command_log if r.source and r.outcome == "ok"]

    # -- the command-line entry point ----------------------------------------------------------------------------------

    def handle(self, line: str) -> str | None:
        """Execute one command line (commands separated by ``;``); returns the query response text, if any.

        The response (all query responses of the line joined by ``;``) is also queued for ``read_message``.
        """
        self._settle()
        parts = flex.split_line(line)
        if not parts:
            return None
        if len(line) + 1 > flex.INPUT_BUFFER_CHARS:
            self._reject(line, parts, flex.ERR_BUFFER_FULL)
            return None
        mnemonics = [_quick_mnemonic(p) for p in parts]
        if len(parts) > 1 and any(m in flex.ALONE_ONLY for m in mnemonics):
            self._reject(line, parts, flex.ERR_TERMINATOR)
            return None
        responses: list[str] = []
        hung_response = False
        for index, part in enumerate(parts):
            measurement = self._measurement
            if measurement is not None and measurement.end == FOREVER:
                if mnemonics[index] == "AB" and len(parts) == 1 and not self._input_queue:
                    pass  # a lone AB reaches the hung instrument and aborts the measurement
                else:  # held in the input buffer behind the hung measurement (PG PDF 352)
                    self._input_queue.extend(parts[index:])
                    for rest in parts[index:]:
                        self._log_unexecuted(line, rest, "queued")
                    break
            elif measurement is not None and mnemonics[index] != "AB":
                self._finish(measurement)
            try:
                cmd = flex.parse_command(part)
            except flex.FlexError as exc:
                self._fail(line, part, "", (), exc, parts[index + 1:])
                break
            if cmd.mnemonic not in flex.SUPPORTED:
                self._fail(line, cmd.text, cmd.mnemonic, cmd.args, Unsupported(cmd.mnemonic), parts[index + 1:])
                break
            try:
                response = self._handlers[cmd.mnemonic](cmd)
            except flex.FlexError as exc:
                self._fail(line, cmd.text, cmd.mnemonic, cmd.args, exc, parts[index + 1:])
                for code in self.faults.errors_after(cmd.mnemonic):
                    self._queue_error(code)
                break
            self._log(line, cmd.text, cmd.mnemonic, cmd.args, "ok")
            if cmd.mnemonic in DC_COMMIT_COMMANDS:
                self._commit_dc()
            for code in self.faults.errors_after(cmd.mnemonic):
                self._queue_error(code)
            if self.faults.command_hangs(cmd.mnemonic):
                self._hang()
            if response is not None:
                if self.faults.query_hangs(cmd.mnemonic):
                    hung_response = True
                else:
                    responses.append(response)
        if hung_response:
            self._queries.append(_Message("", FOREVER))
        if not responses:
            return None
        text = ";".join(responses)
        self._queries.append(_Message(text, self._now()))
        return text

    def _hang(self) -> None:
        """The command just executed never completes (``timeout`` fault): the instrument stays busy; a measurement it
        started returns no data. Only ``AB`` sent alone or a device clear ends this."""
        measurement = self._measurement
        if measurement is None:
            now = self._now()
            measurement = Measurement(now, FOREVER, [], [], None, None, None)
            self._measurement = measurement
        measurement.end = FOREVER
        measurement.step_ends = [FOREVER] * len(measurement.step_ends)
        self._busy_until = FOREVER

    def _reject(self, line: str, parts: list[str], code: int) -> None:
        self._queue_error(code)
        self._log(line, parts[0], _quick_mnemonic(parts[0]), (), "rejected", code)
        for part in parts[1:]:
            self._log_unexecuted(line, part, "rejected")

    def _fail(self, line: str, text: str, mnemonic: str, args: Iterable[str], exc: flex.FlexError,
              rest: list[str]) -> None:
        self._queue_error(exc.code)
        outcome: Outcome = "unsupported" if isinstance(exc, Unsupported) else "error"
        self._log(line, text, mnemonic, args, outcome, exc.code)
        for part in rest:
            self._log_unexecuted(line, part, "rejected")

    # -- reading -------------------------------------------------------------------------------------------------------

    def _settle(self) -> None:
        """Complete a running measurement whose end time has passed."""
        m = self._measurement
        if m is not None and self.clock >= m.end:
            self._finish(m)

    def read_message(self, timeout_s: float) -> str:
        """The next message as sent on the wire (query response + CR/LF, or measurement data with the FMT
        terminator); waits up to ``timeout_s`` of virtual time, else raises ``TransportTimeout``."""
        self._settle()
        if self._queries:
            message = self._queries[0]
            if message.ready_at - self.clock > timeout_s:
                self.clock += timeout_s
                raise TransportTimeout(f"No response within {timeout_s} s (virtual).")
            self.clock = max(self.clock, message.ready_at)
            self._queries.popleft()
            self._settle()
            return message.text + "\r\n"
        if not self._buffer and self._measurement is not None:
            measurement = self._measurement
            if measurement.end - self.clock > timeout_s:
                self.clock += timeout_s
                raise TransportTimeout(f"Measurement not complete within {timeout_s} s (virtual).")
            self.clock = max(self.clock, measurement.end)
            self._finish(measurement)
        if self._buffer:
            text = frame(self._buffer, self._fmt)
            self._buffer = []
            return text
        self.clock += timeout_s
        raise TransportTimeout(f"Nothing to read within {timeout_s} s (virtual).")

    def _status_byte(self, busy: bool) -> int:
        """Status byte (PG PDF 76-77): bit 0 data ready, 3 interlock open, 4 set ready, 5 error."""
        value = 0
        if self._buffer or any(m.ready_at <= self.clock for m in self._queries):
            value |= 1
        if self.interlock_open():
            value |= 8
        if not busy:
            value |= 16
        if self._error_flag:
            value |= 32
        return value

    def serial_poll(self) -> int:
        """Serial poll: the status byte without touching the buffers; clears the error bit (PG PDF 77)."""
        self.clock += POLL_ADVANCE_S
        self._settle()
        value = self._status_byte(busy=self._measurement is not None)
        self._error_flag = False
        return value

    def device_clear(self) -> None:
        """Selected device clear: aborts everything and initialises the instrument (PG PDF 175)."""
        self._log("", "<device_clear>", "<device_clear>", (), "ok")
        self._initialize()

    def _initialize(self) -> None:
        """Power-on state (``*RST``/device clear): outputs off at 0 V, setup, buffers and errors cleared."""
        if self._measurement is not None:
            self._rollback_devices(self._measurement)
        self._measurement = None
        self._input_queue.clear()
        self._queries.clear()
        self._buffer = []
        self._errors.clear()
        self._error_flag = False
        self._busy_until = self.clock
        self._timer_zero = self.clock
        self._reset_settings()
        self.state.auto_calibration = False  # CM initial setting OFF (PG p379 (4-61), PDF 180)
        self.interrupt_pending = False
        for channel in list(self.state.channels):
            if not self.faults.stuck(channel):
                self.state.channels[channel] = ChannelState()
        self._commit_dc()

    # -- circuit and measurement lifecycle -----------------------------------------------------------------------------

    def _current(self, levels: dict[int, float]) -> dict[int, float]:
        return self.circuit.channel_currents(levels)

    def _on_levels(self) -> dict[int, float]:
        return {ch: st.voltage for ch, st in self.state.channels.items() if st.output_on and self._is_smu(ch)}

    def _icomp(self, channel: int) -> float:
        icomp = self.state.channels[channel].icomp
        return icomp if icomp is not None else DEFAULT_ICOMP

    def _finish(self, measurement: Measurement) -> None:
        """Complete ``measurement``: all data into the output buffer, sources to their post-measurement level."""
        for block in measurement.blocks:
            self._buffer.extend(block)
        self._apply_end(measurement, aborted=False, at=measurement.end)

    def _apply_end(self, measurement: Measurement, *, aborted: bool, at: float) -> None:
        sweep = measurement.sweep
        if sweep is not None:
            state = self.state.channels[sweep.channel]
            level = sweep.start if aborted else measurement.post_level
            if state.output_on and level is not None:
                state.voltage, state.icomp = level, sweep.icomp
        if measurement.zero_at is not None and measurement.zero_at <= at:
            for channel, state in self.state.channels.items():
                if state.output_on and not self.faults.stuck(channel):
                    state.voltage = 0.0
        self._measurement = None
        self._commit_dc()

    # -- stateful devices ----------------------------------------------------------------------------------------------

    def _sync_devices(self) -> None:
        """Mirror the circuit's device state into the persistent state."""
        if self.circuit.has_state:
            self.state.devices = self.circuit.export_state()

    def _commit_dc(self) -> None:
        """Commit the DC output levels (compliance-limited, as ``solve`` applies them) to stateful devices."""
        if not self.circuit.has_state:
            return
        levels = self._on_levels()
        if levels:
            applied, _, _ = self.solve(levels, {ch: self._icomp(ch) for ch in levels})
            self.circuit.commit(applied)
        self._sync_devices()

    def _rollback_devices(self, measurement: Measurement) -> None:
        """A measurement ended early (``AB``, device clear): device state as after its last completed step."""
        if not measurement.device_states:
            return
        done = sum(1 for end in measurement.step_ends if end <= self.clock)
        self.circuit.import_state(measurement.device_states[min(done, len(measurement.device_states) - 1)])
        self._sync_devices()

    @property
    def measurement_pending(self) -> bool:
        """True while a triggered measurement has not completed or been aborted."""
        return self._measurement is not None

    # -- faults, safety, persistence -----------------------------------------------------------------------------------

    def inject(self, fault: SimFault) -> None:
        """Activate ``fault`` now (blueprint 3)."""
        self.faults.add(fault)
        self._sync_channels()

    def clear_faults(self) -> None:
        """Deactivate all faults; the interlock returns to the scenario state."""
        self.faults.clear()
        self._interlock_open = not self.scenario.interlock_closed
        self.interrupt_pending = False

    def take_interrupt(self) -> bool:
        """True once when the measurement being read was marked by a ``run_interrupt`` fault (link side)."""
        pending, self.interrupt_pending = self.interrupt_pending, False
        return pending

    def outputs(self) -> dict[int, ChannelState]:
        """A copy of every channel's output state (canonical channel numbers)."""
        return {ch: st.model_copy() for ch, st in self.state.channels.items()}

    def unsafe_reasons(self) -> list[str]:
        """Why the instrument is not in the safe state (empty when safe)."""
        reasons = []
        for channel, state in sorted(self.state.channels.items()):
            if state.output_on:
                reasons.append(f"channel {channel}: output switch on")
            if state.voltage != 0.0:
                reasons.append(f"channel {channel}: output {state.voltage} V")
        if self._measurement is not None:
            reasons.append("measurement pending")
        if self._input_queue:
            reasons.append(f"{len(self._input_queue)} command(s) held in the input buffer")
        return reasons

    def assert_safe(self) -> None:
        """All channels at 0 V with relays open and no measurement pending; raises ``SimSafetyError``."""
        reasons = self.unsafe_reasons()
        if reasons:
            raise SimSafetyError("Simulator not safe: " + "; ".join(reasons))

    def export_state(self) -> SimPersistentState:
        """A deep copy of the persistent state."""
        return self.state.model_copy(deep=True)

    def import_state(self, state: SimPersistentState) -> None:
        """Replace the persistent state (outputs, DUT state, command log, counters)."""
        if state.scenario != self.scenario.name:
            raise ValueError(f"State belongs to scenario {state.scenario!r}, not {self.scenario.name!r}.")
        state = state.model_copy(deep=True)
        self.circuit.import_state(state.devices)
        self.state = state
        self._sync_devices()
        self._sync_channels()


class SimTransport:
    """``Transport`` over an in-process ``SimInstrument`` (blueprint 2.2, 3); ``resource`` is ``SIM::<scenario>``.

    ``state_file`` (usually ``sim_state_file(state_dir, scenario.name)``) holds the persistent state shared by all
    processes; ``open()`` loads it, and the session calls ``load_state()``/``save_state()`` under the instrument
    lock. ``faults`` are active from the start (the scenario's fault profile); ``inject()`` adds more. The session
    opens and closes it per transaction like the VISA link (blueprint v2 2.4); ``lock()``/``unlock()`` are no-ops
    except that an active ``bus_locked`` fault refuses ``lock()``.
    """

    backend: Literal["sim"] = "sim"

    def __init__(self, scenario: SimScenario, *, state_file: Path | None, faults: Iterable[SimFault] = (),
                 timeout_s: float = 10.0) -> None:
        self.scenario = scenario
        self.resource = f"SIM::{scenario.name}"
        self.state_file = None if state_file is None else Path(state_file)
        self.timeout_s = timeout_s
        self.instrument = SimInstrument(scenario, faults=faults)
        self.time_scale = scenario.time_scale
        self._open = False
        self.locked = False
        """True between a successful ``lock()`` and the next ``unlock()``/``close()`` (tests read it)."""

    # -- helpers -------------------------------------------------------------------------------------------------------

    def _require_open(self) -> None:
        if not self._open:
            raise TransportClosed(f"{self.resource} is not open.")

    def _check_link(self, action: str, line: str | None = None) -> None:
        if self.instrument.faults.link_down():
            if line is not None:
                self.instrument.record_dropped(line)
            raise TransportError(f"{action} on {self.resource} failed: link lost (simulated disconnect).")

    def _waited(self, start: float) -> None:
        if self.time_scale > 0:
            time.sleep(max(0.0, self.instrument.clock - start) * self.time_scale)

    # -- Transport protocol --------------------------------------------------------------------------------------------

    def open(self) -> None:
        if self._open:
            return
        self._check_link("open")
        self.load_state()
        self._open = True

    def close(self) -> None:
        self._open = False
        self.locked = False

    def lock(self) -> None:
        """No bus lock exists in the simulator; an active ``bus_locked`` fault refuses the request (``BusLocked``),
        as a VISA exclusive lock held by another client would."""
        self._require_open()
        if self.locked:
            return
        if self.instrument.faults.lock_refused():
            raise BusLocked(f"{self.resource} is locked by another client (simulated bus_locked fault); "
                            "nothing was sent")
        self.locked = True

    def unlock(self) -> None:
        self.locked = False

    def write(self, cmd: str) -> None:
        self._require_open()
        self._check_link(f"write {cmd!r}", cmd)
        zeroing = any(_quick_mnemonic(p) in flex.ZEROING_COMMANDS for p in flex.split_line(cmd))
        if zeroing and self.instrument.faults.zeroing_times_out():
            self.instrument.record_dropped(cmd)
            raise TransportTimeout(f"write {cmd!r} on {self.resource} timed out (simulated cleanup failure).")
        self.instrument.handle(cmd)
        self.instrument.faults.count_write()

    def read(self, *, timeout_s: float | None = None) -> str:
        self._require_open()
        self._check_link("read")
        timeout = self.timeout_s if timeout_s is None else timeout_s
        start = self.instrument.clock
        if self.instrument.take_interrupt():
            raise SimulatedInterrupt(f"host interrupted while reading a measurement from {self.resource} "
                                     "(simulated run_interrupt)")
        try:
            if self.instrument.faults.read_times_out():
                self.instrument.clock += timeout
                raise TransportTimeout(f"read on {self.resource} timed out (simulated).")
            return self.instrument.read_message(timeout).rstrip("\r\n")
        finally:
            self._waited(start)

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        self.write(cmd)
        return self.read(timeout_s=timeout_s)

    def serial_poll(self) -> int:
        self._require_open()
        self._check_link("serial poll")
        start = self.instrument.clock
        value = self.instrument.serial_poll()
        self._waited(start)
        return value

    def device_clear(self) -> None:
        self._require_open()
        self._check_link("device clear")
        self.instrument.device_clear()

    # -- simulator extras ----------------------------------------------------------------------------------------------

    def load_state(self) -> None:
        """Load the persistent state from ``state_file`` (no-op without a file); a corrupt file is a
        ``TransportError``."""
        if self.state_file is None:
            return
        try:
            state = load_state_file(self.state_file)
            if state is not None:
                self.instrument.import_state(state)
        except ValueError as exc:
            raise TransportError(str(exc)) from exc

    def save_state(self) -> None:
        """Atomically write the persistent state to ``state_file`` (no-op without a file)."""
        if self.state_file is not None:
            save_state_file(self.state_file, self.instrument.export_state())

    def inject(self, fault: SimFault) -> None:
        """Activate ``fault`` on the instrument now."""
        self.instrument.inject(fault)

    def clear_faults(self) -> None:
        """Deactivate every fault (also restores a dropped link)."""
        self.instrument.clear_faults()
