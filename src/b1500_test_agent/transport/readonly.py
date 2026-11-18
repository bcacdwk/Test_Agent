"""``ReadOnlyTransport``: a FLEX link that only lets queries through (blueprint v2 7.1 ``doctor --probe``).

The bring-up probe, the station proposal and the status snapshot only read the instrument. This wrapper makes that
structural instead of a convention: a command is passed on only when its header (the text up to the first blank) is
a mnemonic ending with ``?`` (an IEEE 488.2 query such as ``*IDN?``, ``UNT?``, ``ERSSP? 0``), one command per write
(no ``;``).
Anything else (``CN``, ``CL``, ``DZ``, ``*RST``, ``ERMOD 1`` ...), a device clear (it re-initialises the instrument)
and a serial poll (it clears status bits) raise ``ReadOnlyViolation`` and nothing reaches the instrument. Opening,
locking, unlocking, closing and reading pass through.

``transcript`` keeps every query with its answer (or the error text) in order: the raw record of a probe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from b1500_test_agent.models.common import Backend
from b1500_test_agent.transport.base import Transport, TransportError

_QUERY_HEADER = re.compile(r"^\*?[A-Za-z][A-Za-z0-9]*\?$")
"""A query header: an optional ``*``, a mnemonic and ``?`` (``*IDN?``, ``ERSSP?``)."""


class ReadOnlyViolation(TransportError):
    """A command that is not a single query was refused by ``ReadOnlyTransport``; nothing was sent."""


def is_query(cmd: str) -> bool:
    """True when ``cmd`` is one query: no ``;``, no line break, and its header is a mnemonic ending with ``?``."""
    text = cmd.strip()
    if not text or ";" in text or "\n" in text or "\r" in text:
        return False
    return _QUERY_HEADER.match(text.split()[0]) is not None


@dataclass
class Exchange:
    """One query of a read-only session: the command, the answer (``None`` when it failed) and the error text."""

    cmd: str
    resp: str | None = None
    error: str | None = None


class ReadOnlyTransport:
    """Wraps a ``Transport`` (normally the session's ``AuditingTransport``) and refuses everything but queries."""

    def __init__(self, inner: Transport) -> None:
        self.inner = inner
        self.transcript: list[Exchange] = []
        self._pending: Exchange | None = None

    @property
    def backend(self) -> Backend:
        return self.inner.backend

    @property
    def resource(self) -> str:
        return self.inner.resource

    def _refuse(self, what: str) -> ReadOnlyViolation:
        return ReadOnlyViolation(f"read-only session: {what} refused; only single queries are sent")

    # -- lifecycle (passed through) ---------------------------------------------------------------------------------

    def open(self) -> None:
        self.inner.open()

    def close(self) -> None:
        self.inner.close()

    def lock(self) -> None:
        self.inner.lock()

    def unlock(self) -> None:
        self.inner.unlock()

    # -- I/O ----------------------------------------------------------------------------------------------------------

    def write(self, cmd: str) -> None:
        """Send a query whose answer the next ``read`` returns; any other command is refused."""
        if not is_query(cmd):
            raise self._refuse(f"command {cmd.strip()[:40]!r}")
        exchange = Exchange(cmd=cmd)
        self.transcript.append(exchange)
        try:
            self.inner.write(cmd)
        except TransportError as exc:
            exchange.error = f"{type(exc).__name__}: {exc}"
            raise
        self._pending = exchange

    def read(self, *, timeout_s: float | None = None) -> str:
        exchange, self._pending = self._pending, None
        try:
            text = self.inner.read(timeout_s=timeout_s)
        except TransportError as exc:
            if exchange is not None:
                exchange.error = f"{type(exc).__name__}: {exc}"
            raise
        if exchange is not None:
            exchange.resp = text
        return text

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        if not is_query(cmd):
            raise self._refuse(f"command {cmd.strip()[:40]!r}")
        exchange = Exchange(cmd=cmd)
        self.transcript.append(exchange)
        try:
            text = self.inner.query(cmd, timeout_s=timeout_s)
        except TransportError as exc:
            exchange.error = f"{type(exc).__name__}: {exc}"
            raise
        exchange.resp = text
        return text

    def serial_poll(self) -> int:
        raise self._refuse("serial poll (it clears status bits)")

    def device_clear(self) -> None:
        raise self._refuse("device clear (it re-initialises the instrument)")
