"""``SimInstrument`` (deterministic FLEX state machine) and ``SimTransport`` (its ``Transport`` adapter), blueprint 3.

Behaviour follows the Keysight B1500 Series Programming Guide, Edition 15 ("PG", physical PDF pages) for the v1
FLEX subset (``flex.SUPPORTED``); anything else queues error 100 and is logged ``unsupported``.

Time is virtual: ``clock`` (s) advances only when the host waits (a read, a serial poll). A measurement started by
``XE`` at ``t0`` ends at ``t0 + duration``, where the duration comes from ``WT`` and the ADC settings (times the
``slow`` fault factor). Commands other than a lone ``AB`` that arrive while a measurement runs are executed after
it (the B1500 executes commands sequentially, PG PDF 352), so their responses become readable only at its end. A
read whose data is not ready within its timeout raises ``TransportTimeout``. ``timing: scaled`` additionally
sleeps ``SCALED_TIME_FACTOR`` times every virtual wait; ``instant`` never sleeps.

Manual references used here: ``*IDN?`` PDF 440; ``UNT?`` PDF 545; ``ERRX?`` PDF 431-432; status byte PDF 76-77;
``*STB?`` PDF 523; ``*OPC?`` PDF 480; ``LOP?`` PDF 446-447 (Table 4-26); ``*TST?`` PDF 540-541; ``*CAL?``
PDF 377; ``*RST``/device clear initialise like power-on (PDF 175, 502); ``NUB?`` PDF 478; ``FMT`` PDF 436-438;
``BC`` PDF 364; ``TSC`` PDF 538-539; ``CN`` PDF 380-381; ``CL`` PDF 378; ``DZ`` PDF 397; ``AB`` PDF 351-352;
``AAD`` PDF 351; ``AIT`` PDF 356-359; ``AV`` PDF 362-363; ``RI`` PDF 501; ``RV`` PDF 503; ``MM`` PDF 470-471;
``CMM`` PDF 380; ``DV`` PDF 396; ``WV`` PDF 568-569; ``WT`` PDF 564-565; ``WM`` PDF 552-553; ``XE`` PDF 570.

Simulator conventions (not from the manual): STB bit 3 tracks the interlock state continuously (the blueprint's
reading, verified on hardware as ATV-10; the PG describes a latched bit, PDF 76); compliance is symmetric
(|I| ≤ |Icomp|); a fixed current range overflows above 115 % of full scale; voltage measurements are noiseless.

Device state (FeFET polarization): the voltages actually applied are committed to the circuit after every DC output
change (``DC_COMMIT_COMMANDS``) and after every measured sweep step (all steps are evaluated at ``XE``; an ``AB`` or
device clear before the end rolls the state back to the last completed step). ``state.devices`` mirrors the circuit
state, so it is saved and loaded with the rest of the persistent state.
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal

from b1500_test_agent.models.measurement import CHANNEL_NUMBERS
from b1500_test_agent.models.sim import SimFault
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL, SMU_TYPES, TWO_CHANNEL_TYPES, SimScenario, SimSlot
from b1500_test_agent.transport.base import TransportClosed, TransportError, TransportTimeout
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import Circuit, canonical_channel
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT, FaultEngine
from b1500_test_agent.transport.sim.format import DUMMY_VALUE, Element, frame, worst_status
from b1500_test_agent.transport.sim.state import (
    COMMAND_LOG_LIMIT,
    ChannelState,
    CommandRecord,
    Outcome,
    SimPersistentState,
    load_state_file,
    save_state_file,
)

SCALED_TIME_FACTOR = 0.01
"""Real seconds slept per virtual second with ``timing: scaled``."""

POLL_ADVANCE_S = 0.01
"""Virtual time a serial poll takes (so polling loops see measurements finish)."""

DEFAULT_ICOMP = 1e-4
"""Current compliance after ``CN``/``CL``: 100 uA (PG PDF 378)."""

OVERRANGE = 1.15
"""Fixed current range overflow threshold, as a fraction of full scale (simulator convention)."""

NOISE_MULTIPLIERS = ((0.25, 3.0), (4.0, 1.0), (math.inf, 0.3))
"""(integration time in PLC below which, noise multiplier): short 3x, medium 1x, long 0.3x (blueprint 3)."""

DC_COMMIT_COMMANDS = frozenset({"CN", "CL", "DZ", "DV", "*RST", "*TST?", "*CAL?"})
"""Commands after which the DC output levels are committed to stateful devices."""

_CMU_TYPES = frozenset({"MFCMU"})
_SPGU_TYPES = frozenset({"HVSPGU"})
_FOREVER = math.inf


class SimSafetyError(AssertionError):
    """``assert_safe()`` failed: an output is on or non-zero, or a measurement is still pending."""


class _Unsupported(flex.FlexError):
    """A supported command used with a form the v1 simulator does not implement (error 100, logged unsupported)."""

    def __init__(self, detail: str) -> None:
        super().__init__(flex.ERR_UNDEFINED, detail)


@dataclass
class _Message:
    text: str
    ready_at: float


@dataclass(frozen=True)
class _Sweep:
    """``WV`` settings (PG PDF 568-569)."""

    channel: int
    mode: int
    vrange: int
    start: float
    stop: float
    steps: int
    icomp: float

    def values(self) -> list[float]:
        """Output values: linear or log, single (start→stop) or double (start→stop→start, 2·steps points)."""
        n = self.steps
        if n == 1:
            forward = [self.start]
        elif self.mode in (1, 3):
            forward = [self.start + (self.stop - self.start) * i / (n - 1) for i in range(n)]
        else:
            ratio = self.stop / self.start
            forward = [self.start * ratio ** (i / (n - 1)) for i in range(n)]
        return forward + forward[::-1] if self.mode in (3, 4) else forward


@dataclass
class _Measurement:
    """A triggered measurement: per-step data (already formatted) and completion times."""

    start: float
    end: float
    step_ends: list[float]
    blocks: list[list[str]]
    sweep: _Sweep | None
    post_level: float | None
    zero_at: float | None
    device_states: list[dict[str, dict[str, float | int | bool | str]]] = field(default_factory=list)
    """Stateful-device state before the first step (index 0) and after each measured step (index k)."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _quick_mnemonic(part: str) -> str:
    try:
        return flex.parse_command(part).mnemonic
    except flex.FlexError:
        return ""


class SimInstrument:
    """In-process B1500A: ``handle(line)`` executes one command line and returns the query response, if any.

    Query responses and measurement data are buffered as on the instrument and read with ``read_message``.
    ``state`` is the persistent part (outputs, DUT state, command log); ``faults`` the active fault engine.
    """

    def __init__(self, scenario: SimScenario, *, faults: Iterable[SimFault] = ()) -> None:
        self.scenario = scenario
        self.faults = FaultEngine(faults)
        self.circuit = Circuit(scenario)
        self.state = SimPersistentState(scenario=scenario.name)
        self.state.devices = self.circuit.export_state()
        self.clock = 0.0
        self._busy_until = 0.0
        self._timer_zero = 0.0
        self._errors: deque[int] = deque()
        self._error_flag = False
        self._queries: deque[_Message] = deque()
        self._buffer: list[str] = []
        self._measurement: _Measurement | None = None
        self._input_queue: list[str] = []
        self._interlock_open = not scenario.interlock_closed
        self._reset_settings()
        self._sync_channels()
        self._handlers: dict[str, Callable[[flex.Command], str | None]] = {
            mnemonic: getattr(self, "_cmd_" + mnemonic.strip("*?").lower()) for mnemonic in flex.SUPPORTED
        }

    # -- settings ------------------------------------------------------------------------------------------------------

    def _reset_settings(self) -> None:
        """Measurement setup to its initial settings (PG Table 2-13, PDF 180)."""
        self._fmt = 1
        self._fmt_mode = 0
        self._tsc = False
        self._mm: tuple[int, list[int]] | None = None
        self._cmm: dict[int, int] = {}
        self._adc: dict[int, int] = {}
        self._ait: dict[int, tuple[int, float]] = {0: (0, 1), 1: (0, 6), 2: (2, 1)}
        self._ri: dict[int, int] = {}
        self._rv: dict[int, int] = {}
        self._sweep: _Sweep | None = None
        self._wt = (0.0, 0.0, 0.0, 0.0, 0.0)
        self._wm = (1, 1)

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

    def _switchable(self) -> frozenset[str]:
        return SMU_TYPES | _CMU_TYPES | _SPGU_TYPES

    def _channels_arg(self, cmd: flex.Command) -> list[int]:
        if len(cmd.args) > 15:
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT, f"{len(cmd.args)} channels")
        if cmd.args:
            return [self._channel(a, kinds=self._switchable()) for a in cmd.args]
        return [ch for ch in self.installed_channels() if self._channel_type(ch) in self._switchable()]

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
            seq=self.state.next_seq, ts=_utc_now(), clock_s=round(self.clock if now == _FOREVER else now, 9),
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
            if measurement is not None and measurement.end == _FOREVER:
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
                self._fail(line, cmd.text, cmd.mnemonic, cmd.args, _Unsupported(cmd.mnemonic), parts[index + 1:])
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
            self._queries.append(_Message("", _FOREVER))
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
            measurement = _Measurement(now, _FOREVER, [], [], None, None, None)
            self._measurement = measurement
        measurement.end = _FOREVER
        measurement.step_ends = [_FOREVER] * len(measurement.step_ends)
        self._busy_until = _FOREVER

    def _reject(self, line: str, parts: list[str], code: int) -> None:
        self._queue_error(code)
        self._log(line, parts[0], _quick_mnemonic(parts[0]), (), "rejected", code)
        for part in parts[1:]:
            self._log_unexecuted(line, part, "rejected")

    def _fail(self, line: str, text: str, mnemonic: str, args: Iterable[str], exc: flex.FlexError,
              rest: list[str]) -> None:
        self._queue_error(exc.code)
        outcome: Outcome = "unsupported" if isinstance(exc, _Unsupported) else "error"
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
        for channel in list(self.state.channels):
            if not self.faults.stuck(channel):
                self.state.channels[channel] = ChannelState()
        self._commit_dc()

    # -- identity and status -------------------------------------------------------------------------------------------

    def _cmd_idn(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return self.faults.idn() or self.scenario.idn

    def _cmd_unt(self, cmd: flex.Command) -> str:
        """``UNT?``: ``model,revision`` per slot 1-10 (``0,0`` when empty), ``;``-separated (PG PDF 545)."""
        flex.arity(cmd, 0, 1)
        mode = flex.integer(cmd.args[0]) if cmd.args else 0
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        slots = self._slots()
        entries = [f"{slots[s].model},{slots[s].revision}" if s in slots else "0,0" for s in range(1, 11)]
        if mode == 1:
            entries.insert(0, "B1500A,0")
        return ";".join(entries)

    def _cmd_errx(self, cmd: flex.Command) -> str:
        """``ERRX?``: ``code,"message"`` or ``0,"No Error."``; mode 1 = code only (PG PDF 431-432)."""
        flex.arity(cmd, 0, 1)
        mode = flex.integer(cmd.args[0]) if cmd.args else 0
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._error_flag = False
        code = self._errors.popleft() if self._errors else 0
        if mode == 1:
            return str(code)
        return f'{code},"{flex.error_message(code) if code else "No Error."}"'

    def _cmd_stb(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return str(self._status_byte(busy=False))

    def _cmd_opc(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return "1"

    def _cmd_rst(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 0, 0)
        self._initialize()

    def _current(self, levels: dict[int, float]) -> dict[int, float]:
        return self.circuit.channel_currents(levels)

    def _on_levels(self) -> dict[int, float]:
        return {ch: st.voltage for ch, st in self.state.channels.items() if st.output_on and self._is_smu(ch)}

    def _cmd_lop(self, cmd: flex.Command) -> str:
        """``LOP?``: ``LOP`` + ten two-digit slot codes (Table 4-26, PDF 446-447).

        The response is written as in the manual's example ``LOP00,11,00,...`` (PDF 447; the syntax line on PDF 446
        shows a blank after ``LOP``). SMU: 00 off, 01 forcing voltage, 12/13 positive/negative current compliance;
        MFCMU on: 40; HVSPGU/WGFMU: 00 (Table 4-26 has no code for them).
        """
        flex.arity(cmd, 0, 0)
        levels = self._on_levels()
        currents = self._current(levels)
        codes = []
        for slot in range(1, 11):
            module = self._module_type(slot)
            state = self.state.channels.get(slot)
            if module is None or state is None or not state.output_on:
                codes.append("00")
            elif module in SMU_TYPES:
                current = currents.get(slot, 0.0)
                limit = state.icomp if state.icomp is not None else DEFAULT_ICOMP
                codes.append(("12" if current > 0 else "13") if abs(current) > limit * (1 + 1e-9) else "01")
            elif module in _CMU_TYPES:
                codes.append("40")
            else:
                codes.append("00")
        return "LOP" + ",".join(codes)

    def _selftest_slot(self, arg: str) -> None:
        slot = flex.integer(arg)
        if not 0 <= slot <= 11:
            raise flex.FlexError(flex.ERR_PARAMETER, f"slot {slot}")
        if 1 <= slot <= 10 and slot not in self._slots():
            raise flex.FlexError(flex.ERR_NO_MODULE, f"slot {slot}")

    def _selftest(self) -> str:
        if self._high_voltage(self._on_levels()):
            raise flex.FlexError(flex.ERR_HV_SELFTEST)
        self._error_flag = False
        for channel in list(self.state.channels):
            self._close_channel(channel)
        return "0"

    def _cmd_tst(self, cmd: flex.Command) -> str:
        """``*TST?``: self-test + self-calibration; always passes (0); leaves modules as after ``CL`` (PDF 540)."""
        flex.arity(cmd, 0, 2)
        if cmd.args:
            self._selftest_slot(cmd.args[0])
        if len(cmd.args) > 1 and flex.integer(cmd.args[1]) not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        return self._selftest()

    def _cmd_cal(self, cmd: flex.Command) -> str:
        """``*CAL?``: self-calibration; always passes (0) (PDF 377)."""
        flex.arity(cmd, 0, 1)
        if cmd.args:
            self._selftest_slot(cmd.args[0])
        return self._selftest()

    def _cmd_nub(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return str(len(self._buffer))

    # -- buffer and format ---------------------------------------------------------------------------------------------

    def _clear_buffers(self) -> None:
        self._buffer = []
        self._queries.clear()

    def _cmd_fmt(self, cmd: flex.Command) -> None:
        """``FMT format[,mode]``: only ASCII 1 and 5, modes 0 and 1 (PDF 436-438); clears the output buffer."""
        flex.arity(cmd, 1, 2)
        fmt = flex.integer(cmd.args[0])
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 0
        if fmt not in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 21, 22, 25) or not 0 <= mode <= 10:
            raise flex.FlexError(flex.ERR_PARAMETER)
        if fmt not in (1, 5):
            raise _Unsupported(f"FMT {fmt}")
        if mode not in (0, 1):
            raise _Unsupported(f"FMT mode {mode}")
        self._fmt, self._fmt_mode = fmt, mode
        self._clear_buffers()

    def _cmd_bc(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 0, 0)
        self._clear_buffers()

    def _cmd_tsc(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._tsc = mode == 1

    # -- channels ------------------------------------------------------------------------------------------------------

    def _close_channel(self, channel: int) -> None:
        """``CL`` condition: switch off, 0 V, 100 uA compliance (PDF 378), unless the output is stuck."""
        if not self.faults.stuck(channel):
            self.state.channels[channel] = ChannelState(icomp=None)

    def _cmd_cn(self, cmd: flex.Command) -> None:
        for channel in self._channels_arg(cmd):
            state = self.state.channels[channel]
            if not state.output_on:
                self.state.channels[channel] = ChannelState(output_on=True, voltage=0.0, icomp=DEFAULT_ICOMP)

    def _cmd_cl(self, cmd: flex.Command) -> None:
        for channel in self._channels_arg(cmd):
            self._close_channel(channel)

    def _cmd_dz(self, cmd: flex.Command) -> None:
        """``DZ``: 0 V on the channels (all with the switch on by default); the switch stays on (PDF 397)."""
        for channel in self._channels_arg(cmd):
            state = self.state.channels[channel]
            if state.output_on and not self.faults.stuck(channel):
                state.voltage = 0.0
                if state.icomp is not None and state.icomp > DEFAULT_ICOMP:
                    state.icomp = DEFAULT_ICOMP

    def _cmd_ab(self, cmd: flex.Command) -> None:
        """``AB``: abort a running measurement; data measured so far stays, sweep sources go to the start value
        (PDF 351-352). Without a running measurement nothing changes."""
        flex.arity(cmd, 0, 0)
        measurement = self._measurement
        if measurement is None:
            return
        if self.clock >= measurement.end:
            self._finish(measurement)
            return
        done = [block for block, end in zip(measurement.blocks, measurement.step_ends, strict=True)
                if end <= self.clock]
        for block in done:
            self._buffer.extend(block)
        self._rollback_devices(measurement)
        self._apply_end(measurement, aborted=True, at=self.clock)
        self._busy_until = self.clock

    # -- ADC, ranges, modes --------------------------------------------------------------------------------------------

    def _cmd_aad(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        adc = flex.integer(cmd.args[1])
        if adc not in (0, 1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        if adc != 2:  # the pulsed-measurement ADC is never used for DC measurements (PDF 351)
            self._adc[channel] = adc

    _AIT_LIMITS: ClassVar[dict[tuple[int, int], tuple[float, float, float]]] = {
        (0, 0): (1, 1023, 1), (0, 1): (1, 1023, 1), (0, 2): (1, 100, 1), (0, 3): (2e-6, 0.02, 2e-6),
        (1, 0): (1, 127, 6), (1, 1): (1, 127, 3), (1, 2): (1, 100, 1),
        (2, 2): (1, 100, 1), (2, 3): (2e-6, 0.02, 2e-6),
    }  # fmt: skip
    """(type, mode) → (min N, max N, default N) per Table 4-21 (PDF 358-359)."""

    def _cmd_ait(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 3)
        adc, mode = flex.integer(cmd.args[0]), flex.integer(cmd.args[1])
        limits = self._AIT_LIMITS.get((adc, mode))
        if limits is None:
            raise flex.FlexError(flex.ERR_PARAMETER, f"AIT type {adc} mode {mode}")
        low, high, default = limits
        n = (flex.number(cmd.args[2]) if mode == 3 else flex.integer(cmd.args[2])) if len(cmd.args) > 2 else default
        if not low <= n <= high:
            raise flex.FlexError(flex.ERR_PARAMETER, f"AIT N {n}")
        self._ait[adc] = (mode, n)

    def _cmd_av(self, cmd: flex.Command) -> None:
        """``AV number[,mode]``: high-speed ADC averaging, same as ``AIT 0,...`` (PDF 362)."""
        flex.arity(cmd, 1, 2)
        number = flex.integer(cmd.args[0])
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 0
        if mode not in (0, 1) or not (1 <= number <= 1023 or -100 <= number <= -1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._ait[0] = (2, -number) if number < 0 else (mode, number)

    def _cmd_ri(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        code = flex.integer(cmd.args[1])
        module = self._channel_type(channel) or ""
        if code != 0 and abs(code) not in flex.I_CODES.get(module, range(0)):
            raise flex.FlexError(flex.ERR_RANGE, f"RI {code} on {module}")
        self._ri[channel] = code

    def _cmd_rv(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        code = flex.integer(cmd.args[1])
        if code not in flex.V_MEAS_CODES:
            raise flex.FlexError(flex.ERR_RANGE, f"RV {code}")
        self._rv[channel] = code

    def _cmd_mm(self, cmd: flex.Command) -> None:
        """``MM 1|2,ch...``: spot or staircase sweep; other modes are unsupported in v1 (PDF 470-471)."""
        if not cmd.args:
            raise flex.FlexError(flex.ERR_TERMINATOR)
        mode = flex.integer(cmd.args[0])
        if not 1 <= mode <= 28:
            raise flex.FlexError(flex.ERR_PARAMETER)
        if mode not in (1, 2):
            raise _Unsupported(f"MM {mode}")
        channels = [self._smu(a) for a in cmd.args[1:]]
        if not 1 <= len(channels) <= 10 or len(set(channels)) != len(channels):
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT)
        self._mm = (mode, channels)

    def _cmd_cmm(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1, 2, 3):  # mode 4 is not available for HP/MP/HRSMU (PDF 380)
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._cmm[channel] = mode

    # -- sources -------------------------------------------------------------------------------------------------------

    def _cmd_dv(self, cmd: flex.Command) -> None:
        """``DV chnum,vrange,voltage[,Icomp[,comp_polarity[,irange]]]`` (PDF 396)."""
        flex.arity(cmd, 3, 6)
        channel = self._smu(cmd.args[0])
        state = self.state.channels[channel]
        if not state.output_on:
            raise flex.FlexError(flex.ERR_OUTPUT_OFF)
        vrange = flex.integer(cmd.args[1])
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"vrange {vrange}")
        voltage = flex.number(cmd.args[2])
        if abs(voltage) > flex.SMU_MAX_V:
            raise flex.FlexError(flex.ERR_PARAMETER, f"{voltage} V")
        icomp = flex.number(cmd.args[3]) if len(cmd.args) > 3 else state.icomp
        if icomp is None or icomp == 0 or abs(icomp) > flex.max_icomp(voltage):
            raise flex.FlexError(flex.ERR_DV_COMPLIANCE, f"Icomp {icomp}")
        polarity = flex.integer(cmd.args[4]) if len(cmd.args) > 4 else 0
        if polarity not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        irange = flex.integer(cmd.args[5]) if len(cmd.args) > 5 else 0
        module = self._channel_type(channel) or ""
        if irange != 0 and irange not in flex.I_CODES.get(module, range(0)):
            raise flex.FlexError(flex.ERR_RANGE, f"irange {irange}")
        self._check_interlock(voltage)
        state.voltage, state.icomp, state.comp_polarity = voltage, abs(icomp), polarity
        state.vrange, state.irange = vrange, irange

    def _cmd_wv(self, cmd: flex.Command) -> None:
        """``WV chnum,mode,range,start,stop,step[,Icomp[,Pcomp]]`` (PDF 568-569); Pcomp is unsupported in v1."""
        flex.arity(cmd, 6, 8)
        channel = self._smu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (1, 2, 3, 4):
            raise flex.FlexError(flex.ERR_PARAMETER, f"mode {mode}")
        vrange = flex.integer(cmd.args[2])
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"range {vrange}")
        start, stop = flex.number(cmd.args[3]), flex.number(cmd.args[4])
        peak = max(abs(start), abs(stop))
        if peak > flex.SMU_MAX_V:
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} V")
        steps = flex.integer(cmd.args[5])
        if not 1 <= steps <= 10001:
            raise flex.FlexError(flex.ERR_PARAMETER, f"step {steps}")
        if mode in (2, 4) and (start == 0 or stop == 0 or (start > 0) != (stop > 0)):
            raise flex.FlexError(flex.ERR_LOG_POLARITY)
        if len(cmd.args) > 7:
            raise _Unsupported("WV power compliance (Pcomp)")
        icomp = flex.number(cmd.args[6]) if len(cmd.args) > 6 else self.state.channels[channel].icomp
        if icomp is None or icomp == 0 or abs(icomp) > flex.max_icomp(peak):
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"Icomp {icomp}")
        self._check_interlock(peak)
        self._sweep = _Sweep(channel, mode, vrange, start, stop, steps, abs(icomp))

    def _cmd_wt(self, cmd: flex.Command) -> None:
        """``WT hold,delay[,Sdelay[,Tdelay[,Mdelay]]]`` (PDF 564-565)."""
        flex.arity(cmd, 2, 5)
        values = [flex.number(a) for a in cmd.args] + [0.0] * (5 - len(cmd.args))
        hold, delay, sdelay, tdelay, mdelay = values
        if not (0 <= hold <= 655.35 and 0 <= delay <= 65.535 and 0 <= sdelay <= 1.0 and 0 <= tdelay <= delay
                and 0 <= mdelay <= 65.535):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._wt = (hold, delay, sdelay, tdelay, mdelay)

    def _cmd_wm(self, cmd: flex.Command) -> None:
        """``WM abort[,post]``: automatic abort 1 off / 2 on; post 1 start / 2 stop (PDF 552-553)."""
        flex.arity(cmd, 1, 2)
        abort = flex.integer(cmd.args[0])
        post = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if abort not in (1, 2) or post not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._wm = (abort, post)

    # -- measurement ---------------------------------------------------------------------------------------------------

    def integration_time(self, channel: int) -> float:
        """Nominal time (s) of one measurement on ``channel`` from ``AAD``/``AIT``/``AV`` (Table 4-21)."""
        adc = self._adc.get(channel, 0)
        mode, n = self._ait[adc]
        plc = 1.0 / flex.LINE_FREQUENCY_HZ
        if adc == 1:
            if mode == 0:
                return n * flex.HR_AUTO_UNIT_S
            if mode == 1:
                return n * flex.HR_MANUAL_UNIT_S
            return n * plc
        if mode == 3:
            return float(n)
        samples = n * flex.SAMPLES_PER_PLC if mode == 2 else n
        return samples * plc / flex.SAMPLES_PER_PLC

    def noise_multiplier(self, channel: int) -> float:
        """Noise multiplier of ``channel``: 3x below 0.25 PLC, 1x below 4 PLC, else 0.3x (blueprint 3)."""
        plcs = self.integration_time(channel) * flex.LINE_FREQUENCY_HZ
        return next(mult for limit, mult in NOISE_MULTIPLIERS if plcs < limit)

    def _icomp(self, channel: int) -> float:
        icomp = self.state.channels[channel].icomp
        return icomp if icomp is not None else DEFAULT_ICOMP

    def solve(self, levels: dict[int, float], icomps: dict[int, float]) -> tuple[dict[int, float], dict[int, float],
                                                                                    set[int]]:
        """Applied voltages, channel currents and the channels in compliance for programmed ``levels``.

        A channel whose |I| would exceed its compliance has its applied voltage bisected (between the programmed
        level and 0 V, or beyond 0 V when another biased terminal still drives more than Icomp there, e.g. through a
        gate-drain short) until |I| = Icomp; this repeats for the next channel in compliance. The devices are
        passive, so a channel's current rises monotonically with its own voltage.
        """
        applied = dict(levels)
        clamped: set[int] = set()
        for _ in range(len(applied)):
            currents = self._current(applied)
            over = [ch for ch in applied
                    if ch not in clamped and abs(currents.get(ch, 0.0)) > icomps[ch] * (1 + 1e-12)]
            if not over:
                break
            channel = max(over, key=lambda ch: abs(currents[ch]) / icomps[ch])
            applied[channel] = self._bisect(applied, channel, icomps[channel])
            clamped.add(channel)
        return applied, self._current(applied), clamped

    def _bisect(self, applied: dict[int, float], channel: int, icomp: float) -> float:
        def current(voltage: float) -> float:
            trial = dict(applied)
            trial[channel] = voltage
            return self._current(trial).get(channel, 0.0)

        sign = 1.0 if current(applied[channel]) >= 0 else -1.0  # direction of the excess current

        def excess(voltage: float) -> float:
            return sign * current(voltage) - icomp

        lo, hi = 0.0, applied[channel]
        step = max(abs(hi), 0.1)
        while excess(lo) > 0:  # 0 V still drives more than Icomp: move against the current's direction
            if step > 4 * flex.SMU_MAX_V:
                return lo  # cannot be limited within the output range (never reached by passive devices)
            hi, lo = lo, lo - sign * step
            step *= 2
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if excess(mid) > 0:
                hi = mid
            else:
                lo = mid
            if abs(hi - lo) < 1e-12:
                break
        return lo

    def _cmd_xe(self, cmd: flex.Command) -> None:
        """``XE``: trigger the ``MM`` measurement (PDF 570); errors 214, 220, 200."""
        flex.arity(cmd, 0, 0)
        if self._mm is None:
            raise flex.FlexError(flex.ERR_NO_MM)
        mode, channels = self._mm
        sweep = self._sweep if mode == 2 else None
        if mode == 2 and sweep is None:
            raise flex.FlexError(flex.ERR_NO_SWEEP)
        for channel in [*channels, *([sweep.channel] if sweep else [])]:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        self._measurement = self._measure(channels, sweep, self._now())
        self._busy_until = self._measurement.end

    def _measure(self, channels: list[int], sweep: _Sweep | None, t0: float) -> _Measurement:
        factor = self.faults.slow_factor()
        hold, delay, sdelay = self._wt[0], self._wt[1], self._wt[2]
        tmeas = {ch: self.integration_time(ch) for ch in channels}
        meas_total = sum(tmeas.values())
        values: list[float | None] = list(sweep.values()) if sweep else [None]
        levels0 = self._on_levels()
        icomps = {ch: self._icomp(ch) for ch in levels0}
        if sweep:
            icomps[sweep.channel] = sweep.icomp
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        blocks: list[list[str]] = []
        step_ends: list[float] = []
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        aborted = False
        zero_at: float | None = None
        last = len(values) - 1
        period = delay + max(meas_total, sdelay)
        for i, value in enumerate(values):
            if sweep:  # hold, then per step: force, wait delay, measure; next step after max(meas, Sdelay)
                meas_start, nominal_end = hold + i * period + delay, hold + (i + 1) * period
            else:
                meas_start, nominal_end = 0.0, meas_total
            end = t0 + factor * nominal_end
            step_ends.append(end)
            stamp = t0 + factor * meas_start - self._timer_zero
            levels = dict(levels0)
            if sweep and value is not None:
                levels[sweep.channel] = value
            if not aborted and self.faults.interlock_opens_at(i):
                self._interlock_open = True
            if not aborted and self.interlock_open() and self._high_voltage(levels):
                # interlock opened in the high-voltage state: all outputs to 0 V, error 202 (PG PDF 577)
                self._queue_error(flex.ERR_INTERLOCK)
                zero_at = end
                aborted = True
            if aborted:
                blocks.append(self._dummy_block(channels, sweep, stamp, i == last))
                continue
            block, statuses, applied = self._block(channels, sweep, value, levels, icomps, tmeas, stamp, i, last, rng)
            blocks.append(block)
            if self.circuit.has_state:  # the step's voltages act on the device before the next step
                self.circuit.commit(applied)
                device_states.append(self.circuit.export_state())
            if self._wm[0] == 2 and any(s in "CTVX" for s in statuses):
                aborted = True  # automatic abort: later steps carry dummy data (PDF 553)
        post: float | None = None
        if sweep is not None:
            post = sweep.start if (self._wm[1] == 1 or aborted) else sweep.stop
        self._sync_devices()
        return _Measurement(t0, step_ends[-1], step_ends, blocks, sweep, post, zero_at, device_states)

    def _block(self, channels: list[int], sweep: _Sweep | None, value: float | None, levels: dict[int, float],
               icomps: dict[int, float], tmeas: dict[int, float], stamp: float, step: int, last: int,
               rng: random.Random) -> tuple[list[str], list[str], dict[int, float]]:
        applied, currents, clamped = self.solve(levels, icomps)
        forced = {canonical_channel(ch) for ch in self.faults.compliance_channels(step)}
        limited = clamped | forced
        oscillating = self.faults.oscillating(step)
        texts: list[str] = []
        statuses: list[str] = []
        offset = 0.0
        for channel in channels:
            quantity = "V" if self._cmm.get(channel, 0) in (2, 3) else "I"
            status = "C" if channel in limited else ("T" if limited else "N")
            if quantity == "I":
                reading = currents.get(channel, 0.0)
                if channel in forced:
                    sign = reading if reading != 0 else (applied.get(channel, 0.0) or 1.0)
                    reading = math.copysign(icomps.get(channel, DEFAULT_ICOMP), sign)
                else:
                    reading += self._noise(channel, reading, rng)
                code = self._ri.get(channel, 0)
                if code < 0 and abs(reading) > OVERRANGE * flex.current_range(code):
                    status = worst_status([status, "V"])
            else:
                reading = applied.get(channel, 0.0)
            if oscillating:
                status = worst_status([status, "X"])
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp + offset).text())
            texts.append(Element(status, channel, quantity, reading).text())
            statuses.append(status)
            offset += tmeas[channel]
        if self.faults.garbage_at(step):
            texts[1 if self._tsc else 0] = GARBAGE_ELEMENT
        if sweep is not None and value is not None and self._fmt_mode == 1:
            texts.append(Element("E" if step == last else "W", sweep.channel, "V", value).text())
        return texts, statuses, applied

    def _dummy_block(self, channels: list[int], sweep: _Sweep | None, stamp: float, is_last: bool) -> list[str]:
        texts: list[str] = []
        for channel in channels:
            quantity = "V" if self._cmm.get(channel, 0) in (2, 3) else "I"
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp).text())
            texts.append(Element("V", channel, quantity, DUMMY_VALUE).text())
        if sweep is not None and self._fmt_mode == 1:
            texts.append(Element("E" if is_last else "W", sweep.channel, "V", DUMMY_VALUE).text())
        return texts

    def _noise(self, channel: int, current: float, rng: random.Random) -> float:
        noise = self.scenario.noise
        module = self._channel_type(channel)
        floor = noise.floor_a.get(module, 0.0) if module else 0.0
        sigma = self.noise_multiplier(channel) * math.hypot(floor, noise.rel * current)
        return rng.gauss(0.0, sigma) if sigma > 0 else 0.0

    def _finish(self, measurement: _Measurement) -> None:
        """Complete ``measurement``: all data into the output buffer, sources to their post-measurement level."""
        for block in measurement.blocks:
            self._buffer.extend(block)
        self._apply_end(measurement, aborted=False, at=measurement.end)

    def _apply_end(self, measurement: _Measurement, *, aborted: bool, at: float) -> None:
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

    def _rollback_devices(self, measurement: _Measurement) -> None:
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
    lock. ``faults`` are active from the start (the scenario's fault profile); ``inject()`` adds more.
    """

    backend: Literal["sim"] = "sim"

    def __init__(self, scenario: SimScenario, *, state_file: Path | None, faults: Iterable[SimFault] = (),
                 timeout_s: float = 10.0) -> None:
        self.scenario = scenario
        self.resource = f"SIM::{scenario.name}"
        self.state_file = None if state_file is None else Path(state_file)
        self.timeout_s = timeout_s
        self.instrument = SimInstrument(scenario, faults=faults)
        self.time_scale = SCALED_TIME_FACTOR if scenario.timing == "scaled" else 0.0
        self._open = False

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
