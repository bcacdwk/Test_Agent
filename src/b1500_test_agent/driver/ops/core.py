"""Core driver operations: plumbing, queries, state, data format, ``CN`` and ``XE`` (blueprint 2.5).

``DriverBase`` owns the transport, the optional ``OutputGuard`` and the write/query discipline every family mixin
uses: one command per write (never ``;``-joined), and between ``XE`` and the end of its read nothing but ``AB`` is
sent (PG ``AB`` remarks, PDF 352). ``CoreOps`` holds the family-independent methods, grouped as A (queries), B (state)
and C (measurement). Every command text comes from ``driver/flex/``. ``zero``/``disconnect`` send ``AB`` first while
a measurement is pending so cleanup never stalls; the cleanup order itself (``AB`` -> ``DZ`` -> ``CL`` -> ``ERRX?``
drain -> verify) belongs to ``session/transaction.py``. ``reset`` (``*RST``) is called only by kind ``system`` (lint
``tests/unit/test_lint_rst.py``).

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
from typing import TYPE_CHECKING

from b1500_test_agent.driver import flex
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
from b1500_test_agent.models.station import ChannelOutput, Identity, InstrumentError, ModuleInventory, StatusByte

if TYPE_CHECKING:
    from b1500_test_agent.transport.base import Transport


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


class DriverBase:
    """Transport, guard and the write/query discipline shared by every operations mixin of ``B1500Driver``."""

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


class CoreOps(DriverBase):
    """Family-independent operations: A queries, B state, C data format, ``CN`` and ``XE`` + read."""

    # -- A: queries -------------------------------------------------------------------------------------------

    def identify(self) -> Identity:
        """``*IDN?`` -> ``Identity`` (PG PDF 440)."""
        return parse_idn(self._query(flex.IDN_Q))

    def modules(self) -> ModuleInventory:
        """``UNT?`` -> ``ModuleInventory`` of occupied slots (PG PDF 545)."""
        return parse_unt(self._query(flex.UNT_Q))

    def errors(self, drain: bool = True) -> list[InstrumentError]:
        """``ERRX?`` entries (PG PDF 431-432). ``drain=True`` reads until the queue answers code 0.

        Raises:
            DriverError: If the queue still reports errors after more queries than it can hold.
        """
        found: list[InstrumentError] = []
        for _ in range(ERRX_QUEUE_SIZE + 2 if drain else 1):
            error = parse_errx(self._query(flex.ERRX_Q))
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
        return parse_status_byte(self._query(flex.STB_Q))

    def output_state(self) -> dict[int, ChannelOutput]:
        """``LOP?`` -> ``{slot: ChannelOutput}`` (PG PDF 446-447; ATV-1, see ``driver/discovery.py``)."""
        return parse_lop(self._query(flex.LOP_Q))

    def wait_complete(self, *, timeout_s: float | None = None) -> None:
        """``*OPC?``: block until all pending operations are complete (PG PDF 479-480; the answer is ``1``)."""
        answer = self._query(flex.OPC_Q, timeout_s=timeout_s)
        if answer != "1":
            raise FlexParseError(f"*OPC? answered {answer!r}, expected '1'", raw=answer)

    # -- B: state ---------------------------------------------------------------------------------------------

    def abort(self) -> None:
        """Send ``AB`` alone (PG PDF 351-352); allowed at any time and ends a pending measurement."""
        self.transport.write(flex.AB)
        self._measurement_pending = False

    def device_clear(self) -> None:
        """Device clear on the transport (recovery path only); ends a pending measurement."""
        self.transport.device_clear()
        self._measurement_pending = False

    def zero(self, chs: Sequence[int] = ()) -> None:
        """``DZ``: set the channels (all when empty) to 0 V (PG PDF 397). Never gated; aborts a pending measurement
        first."""
        cmd = flex.dz(chs)
        if self._measurement_pending:
            self.abort()
        self._write(cmd)

    def disconnect(self, chs: Sequence[int] = ()) -> None:
        """``CL``: output switches OFF (all when empty; PG PDF 378). Never gated; aborts a pending measurement first."""
        cmd = flex.cl(chs)
        if self._measurement_pending:
            self.abort()
        self._write(cmd)

    def reset(self) -> None:
        """``*RST`` alone (PG PDF 502); the data format returns to ``FMT 1,0``."""
        self._write(flex.RST)
        self._format = (1, 0)

    def self_test(self, *, timeout_s: float | None = None) -> int:
        """``*TST?``: self-test and self-calibration of all modules (PG PDF 540-541); 0 = passed, else failure bits
        (``driver.errors.failed_units``). Modules end in the ``CL`` state."""
        return parse_self_test_result(self._query(flex.TST_Q, timeout_s=timeout_s))

    def self_calibrate(self, *, timeout_s: float | None = None) -> int:
        """``*CAL?``: self-calibration of all modules (PG PDF 376-377); 0 = passed, else failure bits."""
        return parse_self_test_result(self._query(flex.CAL_Q, timeout_s=timeout_s))

    # -- C: measurement ---------------------------------------------------------------------------------------

    def set_format(self, fmt: int = 1, mode: int = 1) -> None:
        """``FMT fmt,mode`` (PG PDF 436-438): 1 or 5; mode 1 adds the sweep source output to each step."""
        self._write(flex.fmt(fmt, mode))
        self._format = (fmt, mode)

    def enable(self, chs: Sequence[int]) -> None:
        """``CN`` for the channels (PG PDF 380-381). Every channel must be in the guard's allowlist."""
        if not chs:
            raise ValueError("enable needs at least one channel")
        for ch in chs:
            self._require_guard("enable", ch).check_channel(ch)
        self._write(flex.cn(chs))

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
        self._require_idle(flex.XE)
        self._measurement_pending = True  # set before writing: a failed write may still have triggered
        self.transport.write(flex.XE)
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
