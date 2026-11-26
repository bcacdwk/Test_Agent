"""Driver exceptions, the ``ERRX?`` error queue, the status byte and self-test/self-calibration results.

Sources are the Keysight B1500 Series Programming Guide, Edition 15 ("PG"); PDF page numbers are physical 1-based
pages of ``B1500A Programming Guide.pdf`` (chapter 4: PDF page = printed 4-N + 318).

- ``ERRX?``: PG PDF 431-432 (printed 4-113 to 4-114). Response ``error_code,message`` with the message in double
  quotes, e.g. ``305,"Excess current in HPSMU.; SLOT1"``; ``0,"No Error."`` when the queue is empty. The queue holds
  30 entries and each query removes one. The lab's own code (``lwp/matlab_B1500/lib/IV_sweep.m``, ``SPGU_pulse.m``)
  tests success with ``startsWith(response, '+0,')``, i.e. the firmware signs the code; a parser that expects one
  form misreads the other (lab pitfall, blueprint v2 1.1), so every success form counts: ``0,"No Error."``,
  ``+0,"No Error."``, ``0,`` and a bare ``0``/``+0`` (TODO(verify)[L0.A3, L0.A7]: the exact firmware text,
  blueprint 7.6 item 3).
- Status byte: PG PDF 76-77 (printed 1-56 to 1-57), ``*STB?`` PDF 523 (printed 4-205). Bit 3 (value 8) = interlock
  open. Per the manual it is set when the interlock is open *and* a voltage output or voltage compliance above the
  interlock-open limit is requested, and it is cleared by a serial poll, ``*RST`` or a device clear, i.e. it latches
  an event rather than mirroring the interlock continuously (ATV-10, verified at M4 L0).
- ``*TST?`` PDF 540-541 (Table 4-32, printed 4-222 to 4-223) and ``*CAL?`` PDF 376-377 (printed 4-58 to 4-59):
  the result is the sum of failure bits, 0 = passed.

Integer answers (``*STB?``, ``*TST?``, ``*CAL?``) may carry an explicit ``+`` sign for the same reason as ``ERRX?``.
"""

from __future__ import annotations

import re
from typing import ClassVar

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.common import ErrorCode
from b1500_test_agent.models.station import InstrumentError, StatusByte

ERRX_QUEUE_SIZE = 30
"""Capacity of the ``ERRX?`` error queue (PG PDF 432)."""

STATUS_BYTE_BITS: dict[int, str] = {
    0: "data_ready",
    1: "wait",
    3: "interlock_open",
    4: "set_ready",
    5: "error",
    6: "rqs",
}
"""Meaning of the assigned status-byte bits (PG PDF 76-77); bits 2 and 7 are always 0."""

SELF_TEST_FAILURE_BITS: dict[int, str] = {
    **{1 << (slot - 1): f"slot {slot}" for slot in range(1, 11)},
    1024: "mainframe",
}
"""``*TST?``/``*CAL?`` result bits (PG Table 4-32, PDF 541; PDF 377): value -> failed unit."""


class DriverError(B1500Error):
    """Base class of driver-level failures that are not transport errors or guard refusals."""

    code: ClassVar[ErrorCode] = "instrument_error"


class FlexParseError(DriverError, ValueError):
    """An instrument response does not match the manual's format. ``raw`` keeps the exact text for the archive."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class DriverStateError(DriverError):
    """The driver refused an operation in its current state (for example a command while a measurement started by
    ``XE`` is still pending: the manual says to send nothing but ``AB`` until the data is read, PG PDF 352)."""

    code: ClassVar[ErrorCode] = "internal"


class SpguStillActive(DriverError):
    """The SPGU output did not stop (``SPST?`` still 1) within the time the run allowed (blueprint v2 ATV-19); the
    caller stops it with ``SPP`` (and the transaction cleanup verifies ``SPST?`` = 0 or latches the fault)."""

    def __init__(self, message: str, *, waited_s: float) -> None:
        super().__init__(message)
        self.waited_s = waited_s


class RouteNotVerified(DriverError):
    """A switch output does not read back the state a route just set (``ERSSP?``, ``*LRN? 81``/``62``; blueprint v2
    2.6): a stuck relay, a selector without control or wrong wiring of the control cable. ``readback`` maps each
    target (``SEL1.OUT1``) to what was read (``None`` = not readable). The run stops; the cleanup returns every
    declared output to rest and verifies it, or latches the fault."""

    def __init__(self, message: str, *, readback: dict[str, str | None]) -> None:
        super().__init__(message)
        self.readback = dict(readback)


_ERRX_RE = re.compile(r"^\s*(?P<code>[+-]?\d+)\s*(?:,\s*(?P<msg>.*?))?\s*$", re.DOTALL)
_UNSIGNED_RE = re.compile(r"^\+?(?P<value>\d+)$")


def _unsigned(text: str) -> int | None:
    """The value of a non-negative integer answer with an optional ``+`` sign, else ``None``."""
    match = _UNSIGNED_RE.match(text.strip())
    return None if match is None else int(match.group("value"))


def parse_errx(text: str) -> InstrumentError | None:
    """Parse one ``ERRX?`` (mode 0) or ``ERRX? 1`` response; ``None`` for code 0 (no error), signed or not, with or
    without a message (``0,"No Error."``, ``+0,"No Error."``, ``0,``, ``+0``).

    Raises:
        FlexParseError: If the response does not start with an integer error code.
    """
    match = _ERRX_RE.match(text)
    if match is None:
        raise FlexParseError(f"ERRX? response is not 'code[,\"message\"]': {text!r}", raw=text)
    code = int(match.group("code"))
    if code == 0:
        return None
    message = (match.group("msg") or "").strip()
    if len(message) >= 2 and message[0] == message[-1] == '"':
        message = message[1:-1]
    return InstrumentError(code=code, message=message)


def parse_status_byte(text: str) -> StatusByte:
    """Parse the decimal ``*STB?`` response (PG PDF 523), e.g. ``40`` = bits 3 and 5.

    Raises:
        FlexParseError: If the response is not an integer from 0 to 255.
    """
    value = _unsigned(text)
    if value is None or value > 255:
        raise FlexParseError(f"*STB? response is not a status byte (0-255): {text!r}", raw=text)
    return StatusByte(value=value)


def status_flags(status: StatusByte | int) -> list[str]:
    """Names of the set bits of a status byte, lowest bit first (``STATUS_BYTE_BITS``)."""
    value = status.value if isinstance(status, StatusByte) else status
    return [name for bit, name in sorted(STATUS_BYTE_BITS.items()) if value & (1 << bit)]


def parse_self_test_result(text: str) -> int:
    """Parse a ``*TST?``/``*CAL?`` response: the sum of failure bits (0 = passed).

    Raises:
        FlexParseError: If the response is not an integer from 0 to 2047.
    """
    value = _unsigned(text)
    if value is None or value > 2047:
        raise FlexParseError(f"*TST?/*CAL? response is not a result sum (0-2047): {text!r}", raw=text)
    return value


def failed_units(result: int) -> list[str]:
    """Units reported as failed by a ``*TST?``/``*CAL?`` result, e.g. ``1028`` -> ``['slot 3', 'mainframe']``."""
    if result < 0 or result > 2047:
        raise ValueError(f"self-test result {result} is outside 0-2047")
    return [name for bit, name in sorted(SELF_TEST_FAILURE_BITS.items()) if result & bit]
