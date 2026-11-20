"""The ``Transport`` protocol, the instrument ``Bus`` and the transport errors (blueprint v2 2.4).

A transport moves FLEX text to and from one instrument and knows nothing about FLEX semantics, plans or policy.
Implementations: ``VisaTransport`` (real B1500A over VISA), ``SimTransport`` (in-process simulator) and the
``AuditingTransport`` wrapper. Every method raises only ``TransportError`` subclasses on I/O problems.

Bus lifecycle (blueprint v2 2.4, decision 7): the session opens the link per transaction and per status snapshot
and closes it afterwards, ``open -> lock -> ... -> unlock -> close``, so no process holds the VISA session or its
exclusive lock between calls and the CLI and the MCP server coexist. ``lock()``/``unlock()`` also release the bus
temporarily inside an open session (the WGFMU library phase, WP10.3, and the ``visa.session: process`` fallback of
ATV-13); on the simulator they are no-ops apart from the ``bus_locked`` fault.

Reads return the message text with the read termination and any trailing ``\\r`` removed (ATV-2).
"""

from __future__ import annotations

from typing import ClassVar, NamedTuple, Protocol, runtime_checkable

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.common import Backend, ErrorCode


class TransportError(B1500Error):
    """An I/O problem with the instrument link (result code ``transport_error``)."""

    code: ClassVar[ErrorCode] = "transport_error"


class TransportTimeout(TransportError):
    """The instrument did not answer (or accept a command) within the timeout."""


class TransportClosed(TransportError):
    """The transport is not open (never opened, or already closed)."""


class BusLocked(TransportError):
    """Another client holds the instrument's exclusive bus lock (EasyEXPERT, a second VISA program, the simulated
    ``bus_locked`` fault); nothing was sent. Result code ``instrument_busy``."""

    code: ClassVar[ErrorCode] = "instrument_busy"


@runtime_checkable
class Transport(Protocol):
    """Message-based link to one instrument; ``resource`` is e.g. ``GPIB0::17::INSTR`` or ``SIM::<scenario>``."""

    backend: Backend
    resource: str

    def open(self) -> None:
        """Connect (without taking the exclusive lock); calling it on an open transport does nothing."""
        ...

    def close(self) -> None:
        """Release the lock if held and disconnect; calling it on a closed transport does nothing; never raises."""
        ...

    def lock(self) -> None:
        """Take the exclusive bus lock (VISA ``lock_excl`` when ``visa.exclusive_lock``; a no-op otherwise and on
        the simulator). Raises ``BusLocked`` when another client holds it; calling it while locked does nothing."""
        ...

    def unlock(self) -> None:
        """Release the exclusive bus lock; calling it while unlocked does nothing."""
        ...

    def write(self, cmd: str) -> None:
        """Send one command line (the write termination is added by the transport)."""
        ...

    def read(self, *, timeout_s: float | None = None) -> str:
        """Read one message; ``timeout_s`` overrides the default I/O timeout for this call."""
        ...

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        """``write(cmd)`` then ``read()``."""
        ...

    def serial_poll(self) -> int:
        """The status byte, read without touching the output buffer."""
        ...

    def device_clear(self) -> None:
        """Selected device clear (SDC); recovery path only."""
        ...


@runtime_checkable
class BlockWriter(Protocol):
    """A link that sends a command header followed by a binary data block (the HV-SPGU ``ALW``/``ALS`` ALWG data,
    blueprint v2 2.5): ``VisaTransport``, ``SimTransport`` and the wrappers that forward to them."""

    def write_block(self, cmd: str, data: bytes) -> None:
        """Send ``cmd`` (with the write termination), then ``data`` as raw bytes right after it."""
        ...


@runtime_checkable
class HostClock(Protocol):
    """A link that lets time pass on the host side without bus traffic (between status polls of an SPGU output, a
    held bias): the simulator advances its virtual clock, the VISA link sleeps."""

    def wait(self, seconds: float) -> None:
        """Let ``seconds`` (>= 0) pass."""
        ...


class Bus(NamedTuple):
    """The instrument links of one station (blueprint v2 2.4): ``flex`` carries FLEX text (VISA or simulator);
    ``wgfmu`` is the WGFMU instrument-library session (``WgfmuApi``, WP10.1), ``None`` until then and whenever no
    WGFMU library is available. ``make_bus`` builds it; the session opens and closes ``flex`` per transaction."""

    flex: Transport
    wgfmu: object | None = None


@runtime_checkable
class StatefulTransport(Protocol):
    """A transport whose instrument state persists outside the process (the simulator, blueprint 3).

    The session calls ``load_state()`` right after acquiring the instrument lock and ``save_state()`` right before
    releasing it, so the MCP server and the CLI see one instrument.
    """

    def load_state(self) -> None:
        """Replace the persistent part of the instrument state with the stored one (no-op if nothing is stored)."""
        ...

    def save_state(self) -> None:
        """Store the persistent part of the instrument state (atomic write)."""
        ...


def unwrap(transport: object) -> object:
    """The innermost transport behind wrappers that expose ``inner`` (such as ``AuditingTransport``)."""
    seen: set[int] = set()
    while id(transport) not in seen and hasattr(transport, "inner"):
        seen.add(id(transport))
        transport = transport.inner
    return transport


def state_hooks(transport: object) -> StatefulTransport | None:
    """The persistent-state hooks of ``transport`` (looking through wrappers), or ``None`` for stateless links."""
    inner = unwrap(transport)
    return inner if isinstance(inner, StatefulTransport) else None
