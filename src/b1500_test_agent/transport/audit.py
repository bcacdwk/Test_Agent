"""Audit sinks and the ``AuditingTransport`` wrapper (blueprint 2.2, 2.7).

Every I/O call through ``AuditingTransport`` becomes one ``AuditEvent`` (``write``, ``read``, ``query``, ``poll``,
``device_clear``) carrying the command, the response, the duration and the current run/transaction/intent
context; a failed call is recorded with ``error`` set and the exception is re-raised unchanged. The session
(WP1.6) writes its lifecycle events (``session_open``, ``cleanup_step`` ...) to the same sink with
``AuditEvent.now``.

Sinks number events (``seq``) in the order they record them. ``JsonlAuditSink`` appends one UTF-8 line per event,
``\\n``-terminated, opening the file per event so no handle stays open (Windows-safe, several processes may
append to the same daily file).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from b1500_test_agent.models.audit import AuditEvent, AuditEventName
from b1500_test_agent.models.common import Backend
from b1500_test_agent.transport.base import Transport

T = TypeVar("T")


@runtime_checkable
class AuditSink(Protocol):
    """Destination of audit events."""

    def emit(self, event: AuditEvent) -> AuditEvent:
        """Record ``event``; returns it with ``seq`` assigned (an event that already has one keeps it)."""
        ...


class _NumberingSink:
    """Assigns ``seq`` (0, 1, 2 ...) under a lock; subclasses implement ``_record``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_seq = 0

    def emit(self, event: AuditEvent) -> AuditEvent:
        with self._lock:
            if event.seq is None:
                event = event.model_copy(update={"seq": self._next_seq})
            self._next_seq = max(self._next_seq, (event.seq or 0) + 1)
            self._record(event)
        return event

    def _record(self, event: AuditEvent) -> None:
        raise NotImplementedError


class MemoryAuditSink(_NumberingSink):
    """Keeps events in ``events`` (tests, dry runs)."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[AuditEvent] = []

    def _record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def lines(self) -> list[str]:
        """The events as JSONL lines (without newlines)."""
        return [e.to_json_line() for e in self.events]


class JsonlAuditSink(_NumberingSink):
    """Appends one JSON line per event to ``path`` (parents created on first write)."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)

    def _record(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.to_json_line() + "\n")


class NullAuditSink(_NumberingSink):
    """Discards events (still numbers them)."""

    def _record(self, event: AuditEvent) -> None:
        return None


@dataclass(frozen=True)
class AuditContext:
    """Run id, transaction id and intent stamped on every transport event."""

    run: str | None = None
    tx: str | None = None
    intent: str | None = None


class AuditingTransport:
    """Wraps any ``Transport``; every I/O call is recorded in ``sink`` (blueprint 2.2)."""

    def __init__(self, inner: Transport, sink: AuditSink) -> None:
        self.inner = inner
        self.sink = sink
        self.context = AuditContext()

    @property
    def backend(self) -> Backend:
        return self.inner.backend

    @property
    def resource(self) -> str:
        return self.inner.resource

    @contextmanager
    def bind(self, *, run: str | None = None, tx: str | None = None, intent: str | None = None) -> Iterator[None]:
        """Stamp ``run``/``tx``/``intent`` (those given) on events inside the block, then restore the context."""
        previous = self.context
        updates = {k: v for k, v in (("run", run), ("tx", tx), ("intent", intent)) if v is not None}
        self.context = replace(previous, **updates)
        try:
            yield
        finally:
            self.context = previous

    def _call(self, ev: AuditEventName, cmd: str | None, action: Callable[[], T],
              render: Callable[[T], str | None]) -> T:
        start = time.perf_counter()
        try:
            result = action()
        except BaseException as exc:
            self._emit(ev, cmd, None, start, error=f"{type(exc).__name__}: {exc}")
            raise
        self._emit(ev, cmd, render(result), start)
        return result

    def _emit(self, ev: AuditEventName, cmd: str | None, resp: str | None, start: float,
              error: str | None = None) -> None:
        dur_ms = (time.perf_counter() - start) * 1000.0
        ctx = self.context
        self.sink.emit(AuditEvent.now(ev, self.backend, run=ctx.run, tx=ctx.tx, intent=ctx.intent, cmd=cmd,
                                      resp=resp, dur_ms=dur_ms, error=error))

    def open(self) -> None:
        self.inner.open()

    def close(self) -> None:
        self.inner.close()

    def write(self, cmd: str) -> None:
        self._call("write", cmd, lambda: self.inner.write(cmd), lambda _: None)

    def read(self, *, timeout_s: float | None = None) -> str:
        return self._call("read", None, lambda: self.inner.read(timeout_s=timeout_s), lambda text: text)

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        return self._call("query", cmd, lambda: self.inner.query(cmd, timeout_s=timeout_s), lambda text: text)

    def serial_poll(self) -> int:
        return self._call("poll", None, self.inner.serial_poll, str)

    def device_clear(self) -> None:
        self._call("device_clear", None, self.inner.device_clear, lambda _: None)
