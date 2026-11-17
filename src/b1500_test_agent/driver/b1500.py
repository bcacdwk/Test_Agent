"""``B1500Driver``: the internal "atom" API over a ``Transport`` (blueprint 2.3; legacy map in
``references/driver-map/flex-driver-map.yaml``).

Methods are grouped as A (queries), B (state) and C (measurement). Every command comes from ``driver/commands.py`` and
is written alone (one command per write, never ``;``-joined). Source operations (``enable``, ``force_v``,
``staircase_v``) refuse without an ``OutputGuard`` and check every channel and value against it before the first
byte is written. Between ``XE`` and the end of the read nothing but ``AB`` is sent (PG ``AB`` remarks, PDF 352);
``zero``/``disconnect`` send ``AB`` first in that state so cleanup never stalls. The driver orchestrates nothing
else: cleanup order (``AB`` -> ``DZ`` -> ``CL`` -> ``ERRX?`` drain -> verify) belongs to ``session/transaction.py``.

The transport is only typed here; ``transport/`` is imported for type checking only, so the driver has no runtime
dependency on it. Query responses go through ``Transport.query``; measurement data is read with ``Transport.read``
after ``XE`` (query and measurement buffers stay separate).
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import commands
from b1500_test_agent.driver.discovery import parse_idn, parse_lop, parse_unt
from b1500_test_agent.driver.errors import (
    ERRX_QUEUE_SIZE,
    DriverError,
    DriverStateError,
    FlexParseError,
    parse_errx,
    parse_self_test_result,
    parse_status_byte,
)
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.parser import MeasurementPoint, parse_data
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel, Integration, SweepTiming
from b1500_test_agent.models.station import ChannelOutput, Identity, InstrumentError, ModuleInventory, StatusByte

if TYPE_CHECKING:
    from b1500_test_agent.transport.base import Transport

ADC_TYPE_CODES: dict[str, int] = {"high_speed": 0, "high_resolution": 1}
"""``Integration.adc`` -> ``AAD``/``AIT`` type (PG PDF 351, 356)."""

ADC_MODE_CODES: dict[str, int] = {"auto": 0, "manual": 1, "plc": 2}
"""``Integration.mode`` -> ``AIT`` mode (PG PDF 357)."""

CmmMode = Annotated[int, Field(ge=0, le=4)]


class StaircaseSetup(StrictModel):
    """One staircase voltage sweep (``MM 2``, ``CMM``, ``WV``, ``WT``, ``WM``; PG PDF 470, 380, 568-569, 564-565,
    552-553).

    ``channel`` sweeps from ``start`` to ``stop`` (V) in ``points`` steps with current compliance ``icomp`` (A,
    non-zero; polarity follows the output) on voltage output range code ``vrange`` (Table 4-4; 0 = auto).
    ``measure`` lists the measurement channels in measurement order (data order in each step). ``operation`` sets
    ``CMM`` for some of them (0 compliance side, 1 current, 2 voltage, 3 force side, 4 synchronous I/V); unlisted
    channels keep their mode. ``auto_abort`` enables ``WM`` abort (stop on compliance, overflow or oscillation; data
    after the abort read ``199.999E+99``) and ``post`` chooses the output after a normal end.
    """

    channel: Channel
    start: float
    stop: float
    points: int = Field(ge=1, le=10001)
    icomp: float
    vrange: int = 0
    sweep: Literal["linear", "log"] = "linear"
    double: bool = False
    measure: tuple[Channel, ...] = Field(min_length=1, max_length=commands.MAX_CHANNELS_MM)
    operation: dict[Channel, CmmMode] = Field(default_factory=dict)
    timing: SweepTiming = Field(default_factory=SweepTiming)
    auto_abort: bool = True
    post: Literal["start", "stop"] = "start"

    @model_validator(mode="after")
    def _consistent(self) -> StaircaseSetup:
        if self.icomp == 0:
            raise ValueError("icomp must be non-zero.")
        if self.vrange not in commands.V_RANGE_CODES:
            raise ValueError(f"vrange {self.vrange} is not a PG Table 4-4 voltage output ranging code.")
        if len(set(self.measure)) != len(self.measure):
            raise ValueError("A measurement channel is listed twice.")
        if not set(self.operation) <= set(self.measure):
            raise ValueError("operation names a channel that is not measured.")
        if self.sweep == "log" and (self.start == 0 or self.stop == 0 or (self.start > 0) != (self.stop > 0)):
            raise ValueError("A log sweep needs non-zero start and stop of the same polarity.")
        return self

    @property
    def wv_mode(self) -> int:
        """``WV`` mode: 1 linear, 2 log, 3 linear double, 4 log double."""
        return (1 if self.sweep == "linear" else 2) + (2 if self.double else 0)


@dataclass(frozen=True)
class RawBlock:
    """One measurement read after ``XE``: the exact text received, the parsed elements and timing.

    ``points`` holds every element in order (measurement data, then ``Source_data`` when ``FMT`` mode requests it;
    ``Time`` elements first when ``TSC`` is on). ``complete`` is false when fewer or more elements arrived than
    ``expected_points`` (for example after ``AB``, which returns only the data measured before the abort).
    """

    raw: str
    points: tuple[MeasurementPoint, ...]
    fmt: int
    expected_points: int
    xe_at: datetime
    read_at: datetime
    duration_s: float

    @property
    def complete(self) -> bool:
        """True when exactly ``expected_points`` elements were received."""
        return len(self.points) == self.expected_points

    def steps(self, width: int) -> list[tuple[MeasurementPoint, ...]]:
        """Split the elements into consecutive groups of ``width`` (elements per sweep step).

        Raises:
            ValueError: If ``width`` is not positive or does not divide the number of elements.
        """
        if width < 1 or len(self.points) % width:
            raise ValueError(f"{len(self.points)} elements cannot be split into steps of {width}")
        return [self.points[i : i + width] for i in range(0, len(self.points), width)]


class B1500Driver:
    """FLEX driver of one B1500A. ``guard`` is required for every source operation (blueprint 2.3)."""

    def __init__(self, transport: Transport, guard: OutputGuard | None = None) -> None:
        self.transport = transport
        self.guard = guard
        self._measurement_pending = False
        self._format: tuple[int, int] = (1, 0)  # instrument default without FMT: FMT 1,0 (PG PDF 436)

    # -- internal ---------------------------------------------------------------------------------------------

    @property
    def measurement_pending(self) -> bool:
        """True after ``XE`` was written until its data was read (or ``AB``/device clear ended it)."""
        return self._measurement_pending

    @property
    def data_format(self) -> tuple[int, int]:
        """The ``FMT`` format and mode last sent (``(1, 0)`` until ``set_format`` or after ``reset``)."""
        return self._format

    def _require_idle(self, what: str) -> None:
        if self._measurement_pending:
            raise DriverStateError(f"{what} refused: a measurement started by XE is pending (send AB first)")

    def _write(self, cmd: str) -> None:
        if ";" in cmd:  # defensive: builders never join commands
            raise DriverStateError(f"refusing a combined command string: {cmd!r}")
        self._require_idle(f"write {cmd!r}")
        self.transport.write(cmd)

    def _query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        self._require_idle(f"query {cmd!r}")
        return self.transport.query(cmd, timeout_s=timeout_s).strip()

    def _require_guard(self, operation: str, ch: int) -> OutputGuard:
        if self.guard is None:
            raise EnvelopeViolation("no_guard", f"{operation} refused: no OutputGuard installed", channel=ch)
        return self.guard

    # -- A: queries -------------------------------------------------------------------------------------------

    def identify(self) -> Identity:
        """``*IDN?`` -> ``Identity`` (PG PDF 440)."""
        return parse_idn(self._query(commands.IDN_Q))

    def modules(self) -> ModuleInventory:
        """``UNT?`` -> ``ModuleInventory`` of occupied slots (PG PDF 545)."""
        return parse_unt(self._query(commands.UNT_Q))

    def errors(self, drain: bool = True) -> list[InstrumentError]:
        """``ERRX?`` entries (PG PDF 431-432). ``drain=True`` reads until the queue answers code 0.

        Raises:
            DriverError: If the queue still reports errors after more queries than it can hold.
        """
        found: list[InstrumentError] = []
        for _ in range(ERRX_QUEUE_SIZE + 2 if drain else 1):
            error = parse_errx(self._query(commands.ERRX_Q))
            if error is None:
                return found
            found.append(error)
        if not drain:
            return found
        raise DriverError(f"ERRX? queue did not drain after {len(found)} entries")

    def status_byte(self, *, poll: bool = False) -> StatusByte:
        """Status byte: ``*STB?`` (non-destructive, PG PDF 523) or, with ``poll=True``, a serial poll (allowed while a
        measurement is pending; clears bits 3, 5 and 6, PG PDF 76-77). Bit 3 = interlock open (ATV-10)."""
        if poll:
            value = self.transport.serial_poll()
            if not 0 <= value <= 255:
                raise FlexParseError(f"serial poll returned {value}, not a status byte", raw=str(value))
            return StatusByte(value=value)
        return parse_status_byte(self._query(commands.STB_Q))

    def output_state(self) -> dict[int, ChannelOutput]:
        """``LOP?`` -> ``{slot: ChannelOutput}`` (PG PDF 446-447; ATV-1, see ``driver/discovery.py``)."""
        return parse_lop(self._query(commands.LOP_Q))

    def wait_complete(self, *, timeout_s: float | None = None) -> None:
        """``*OPC?``: block until all pending operations are complete (PG PDF 479-480; the answer is ``1``)."""
        answer = self._query(commands.OPC_Q, timeout_s=timeout_s)
        if answer != "1":
            raise FlexParseError(f"*OPC? answered {answer!r}, expected '1'", raw=answer)

    # -- B: state ---------------------------------------------------------------------------------------------

    def abort(self) -> None:
        """Send ``AB`` alone (PG PDF 351-352); allowed at any time and ends a pending measurement."""
        self.transport.write(commands.AB)
        self._measurement_pending = False

    def device_clear(self) -> None:
        """Device clear on the transport (recovery path only); ends a pending measurement."""
        self.transport.device_clear()
        self._measurement_pending = False

    def zero(self, chs: Sequence[int] = ()) -> None:
        """``DZ``: set the channels (all when empty) to 0 V (PG PDF 397). Never gated; aborts a pending measurement
        first."""
        cmd = commands.dz(chs)
        if self._measurement_pending:
            self.abort()
        self._write(cmd)

    def disconnect(self, chs: Sequence[int] = ()) -> None:
        """``CL``: output switches OFF (all when empty; PG PDF 378). Never gated; aborts a pending measurement first."""
        cmd = commands.cl(chs)
        if self._measurement_pending:
            self.abort()
        self._write(cmd)

    def reset(self) -> None:
        """``*RST`` alone (PG PDF 502); the data format returns to ``FMT 1,0``."""
        self._write(commands.RST)
        self._format = (1, 0)

    def self_test(self, *, timeout_s: float | None = None) -> int:
        """``*TST?``: self-test and self-calibration of all modules (PG PDF 540-541); 0 = passed, else failure bits
        (``driver.errors.failed_units``). Modules end in the ``CL`` state."""
        return parse_self_test_result(self._query(commands.TST_Q, timeout_s=timeout_s))

    def self_calibrate(self, *, timeout_s: float | None = None) -> int:
        """``*CAL?``: self-calibration of all modules (PG PDF 376-377); 0 = passed, else failure bits."""
        return parse_self_test_result(self._query(commands.CAL_Q, timeout_s=timeout_s))

    # -- C: measurement ---------------------------------------------------------------------------------------

    def set_format(self, fmt: int = 1, mode: int = 1) -> None:
        """``FMT fmt,mode`` (PG PDF 436-438): 1 or 5; mode 1 adds the sweep source output to each step."""
        self._write(commands.fmt(fmt, mode))
        self._format = (fmt, mode)

    def set_integration(self, adc: int, mode: int, n: float, *, chs: Sequence[int] = ()) -> None:
        """``AAD ch,adc`` for each of ``chs``, then ``AIT adc,mode,n`` (PG PDF 351, 356-359)."""
        cmds = [commands.aad(ch, adc) for ch in chs] + [commands.ait(adc, mode, n)]
        for cmd in cmds:
            self._write(cmd)

    def apply_integration(self, integration: Integration, chs: Sequence[int]) -> None:
        """``set_integration`` from an ``Integration`` model (ADC type, mode and N)."""
        self.set_integration(ADC_TYPE_CODES[integration.adc], ADC_MODE_CODES[integration.mode], integration.n, chs=chs)

    def set_range(self, ch: int, quantity: Literal["I", "V"], code: int) -> None:
        """``RI``/``RV`` measurement ranging (PG PDF 501, 503); codes via ``driver.modules.ranging_code``."""
        if quantity == "I":
            self._write(commands.ri(ch, code))
        elif quantity == "V":
            self._write(commands.rv(ch, code))
        else:
            raise ValueError(f"quantity must be 'I' or 'V', got {quantity!r}")

    def enable(self, chs: Sequence[int]) -> None:
        """``CN`` for the channels (PG PDF 380-381). Every channel must be in the guard's allowlist."""
        if not chs:
            raise ValueError("enable needs at least one channel")
        for ch in chs:
            self._require_guard("enable", ch).check_channel(ch)
        self._write(commands.cn(chs))

    def force_v(self, ch: int, v: float, *, icomp: float, rng: int = 0) -> None:
        """Guarded ``DV ch,rng,v,icomp`` (PG PDF 396)."""
        self._require_guard("force_v", ch).check(ch, "V", v, icomp)
        self._write(commands.dv(ch, rng, v, icomp))

    def staircase_v(self, setup: StaircaseSetup) -> None:
        """Guarded staircase voltage sweep setup: ``MM 2,<measure>``, ``CMM`` per ``operation``, ``WV``, ``WT``,
        ``WM`` (PG PDF 470, 380, 568-569, 564-565, 552-553). Both sweep end points are checked before anything is
        written; ``XE`` is sent by ``execute_and_read``."""
        guard = self._require_guard("staircase_v", setup.channel)
        guard.check(setup.channel, "V", setup.start, setup.icomp)
        guard.check(setup.channel, "V", setup.stop, setup.icomp)
        timing = setup.timing
        cmds = [
            commands.mm(2, setup.measure),
            *(commands.cmm(ch, op) for ch, op in setup.operation.items()),
            commands.wv(setup.channel, setup.wv_mode, setup.vrange, setup.start, setup.stop, setup.points, setup.icomp),
            commands.wt(
                timing.hold_s, timing.delay_s, timing.step_delay_s, timing.trigger_delay_s, timing.measure_delay_s
            ),
            commands.wm(2 if setup.auto_abort else 1, 1 if setup.post == "start" else 2),
        ]
        for cmd in cmds:
            self._write(cmd)

    def execute_and_read(self, *, expected_points: int, timeout_s: float) -> RawBlock:
        """``XE``, then read one data response and parse it in the current ``FMT`` format (PG PDF 570-572, 45-55).

        ``expected_points`` is the number of data elements the response should hold (steps x elements per step).
        While the read is outstanding the driver refuses everything but ``abort``/``device_clear``; if the read
        raises (timeout, closed transport) the measurement stays pending so the caller's cleanup sends ``AB``.

        Raises:
            FlexParseError: If the response is malformed; ``raw`` holds the exact text for the archive.
        """
        if isinstance(expected_points, bool) or not isinstance(expected_points, int) or expected_points < 1:
            raise ValueError(f"expected_points must be a positive integer, got {expected_points!r}")
        if not (isinstance(timeout_s, int | float) and math.isfinite(timeout_s) and timeout_s > 0):
            raise ValueError(f"timeout_s must be a positive number of seconds, got {timeout_s!r}")
        fmt, _mode = self._format
        self._require_idle(commands.XE)
        self._measurement_pending = True  # set before writing: a failed write may still have triggered
        self.transport.write(commands.XE)
        xe_at = datetime.now(UTC)
        started = time.monotonic()
        raw = self.transport.read(timeout_s=timeout_s)
        duration = time.monotonic() - started
        read_at = datetime.now(UTC)
        self._measurement_pending = False
        try:
            points = parse_data(raw, fmt)
        except FlexParseError as exc:
            raise FlexParseError(str(exc), raw=raw) from exc
        return RawBlock(
            raw=raw,
            points=tuple(points),
            fmt=fmt,
            expected_points=expected_points,
            xe_at=xe_at,
            read_at=read_at,
            duration_s=duration,
        )
