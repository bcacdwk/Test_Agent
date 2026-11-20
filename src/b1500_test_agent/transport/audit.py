"""Audit sinks and the ``AuditingTransport`` wrapper (blueprint 2.2, 2.7).

Every I/O call through ``AuditingTransport`` becomes one ``AuditEvent`` (``write``, ``read``, ``query``, ``poll``,
``device_clear``) carrying the command, the response, the duration and the current run/transaction/intent
context; a failed call is recorded with ``error`` set and the exception is re-raised unchanged. The bus lifecycle
calls ``open``/``lock``/``unlock``/``close`` are audited the same way as ``bus_open``/``bus_lock``/``bus_unlock``/
``bus_close`` (blueprint v2 2.4; their ``dur_ms`` is the per-transaction overhead of ATV-13), best-effort: a
failing sink never changes whether the link is open or locked. The session (WP1.6) writes its lifecycle events
(``session_open``, ``cleanup_step`` ...) to the same sink with ``AuditEvent.now``.

Sinks number events (``seq``) in the order they record them. ``JsonlAuditSink`` appends one UTF-8 line per event,
``\\n``-terminated, opening the file per event so no handle stays open between operations (Windows-safe, several
processes may append to the same daily file). Inside ``JsonlAuditSink.held()`` (``hold_audit``; the transaction holds
its sink for its lifetime) the file is opened once and every event is still written and flushed at once, so readers in
other processes and a killed process lose nothing, while a long run no longer pays one open/close per event: on
Windows each open/close of a written file costs ~0.3-1 ms (anti-virus scan on close), i.e. seconds for the thousands
of events of a 4 h simulated run (WP6.5, blueprint v2 4.1: < 2 s wall).
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, TextIO, TypeVar, runtime_checkable

from b1500_test_agent.models.audit import AuditEvent, AuditEventName
from b1500_test_agent.models.common import Backend
from b1500_test_agent.transport.base import Transport, TransportError

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
    """Appends one JSON line per event to ``path`` (parents created on first write; see the module docstring for
    ``held``)."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self._ready_dir: Path | None = None
        self._holds = 0
        self._handle: TextIO | None = None
        self._handle_path: Path | None = None

    def _ensure_dir(self) -> None:
        parent = self.path.parent
        if self._ready_dir != parent:
            parent.mkdir(parents=True, exist_ok=True)
            self._ready_dir = parent

    def _open(self) -> TextIO:
        self._ensure_dir()
        try:
            return self.path.open("a", encoding="utf-8", newline="\n")
        except FileNotFoundError:  # the folder vanished since it was made (cleanup, tests): make it again
            self._ready_dir = None
            self._ensure_dir()
            return self.path.open("a", encoding="utf-8", newline="\n")

    def _close_handle(self) -> None:
        handle, self._handle, self._handle_path = self._handle, None, None
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()

    @contextmanager
    def held(self) -> Iterator[None]:
        """Keep the file open inside the block (one open instead of one per event; nested holds share it). Each
        event is still written and flushed when it is emitted; the file is closed when the outermost hold ends."""
        with self._lock:
            self._holds += 1
        try:
            yield
        finally:
            with self._lock:
                self._holds -= 1
                if self._holds == 0:
                    self._close_handle()

    def _record(self, event: AuditEvent) -> None:
        line = event.to_json_line() + "\n"
        if not self._holds:
            with self._open() as handle:
                handle.write(line)
            return
        if self._handle is None or self._handle_path != self.path:  # first event, or a new daily file
            self._close_handle()
            self._handle, self._handle_path = self._open(), self.path
        try:
            self._handle.write(line)
            self._handle.flush()
        except OSError:
            self._close_handle()  # a broken handle is never reused; the next event reopens
            raise


def hold_audit(sink: AuditSink) -> AbstractContextManager[object]:
    """``sink.held()`` for a file sink (see ``JsonlAuditSink``), else a no-op context."""
    return sink.held() if isinstance(sink, JsonlAuditSink) else nullcontext()


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

    def _lifecycle(self, ev: AuditEventName, action: Callable[[], None]) -> None:
        """Run a bus lifecycle call and audit it best-effort: a failing sink never changes whether the link is open
        or locked (the I/O events still fail loudly, and the transaction's own lifecycle events are best-effort
        too)."""
        start = time.perf_counter()
        try:
            action()
        except BaseException as exc:
            with contextlib.suppress(Exception):
                self._emit(ev, None, None, start, error=f"{type(exc).__name__}: {exc}")
            raise
        with contextlib.suppress(Exception):
            self._emit(ev, None, None, start)

    def open(self) -> None:
        self._lifecycle("bus_open", self.inner.open)

    def close(self) -> None:
        self._lifecycle("bus_close", self.inner.close)

    def lock(self) -> None:
        self._lifecycle("bus_lock", self.inner.lock)

    def unlock(self) -> None:
        self._lifecycle("bus_unlock", self.inner.unlock)

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

    def write_block(self, cmd: str, data: bytes) -> None:
        """``cmd`` + binary block (``BlockWriter``), audited as one ``write`` whose command names the block size and
        the first 16 hex digits of its sha256."""
        text = f"{cmd} <block {len(data)} bytes sha256 {hashlib.sha256(data).hexdigest()[:16]}>"
        self._call("write", text, lambda: _block_writer(self.inner, cmd)(cmd, data), lambda _: None)

    def wait(self, seconds: float) -> None:
        """Host wait (``HostClock``; not an I/O, not audited): forwarded, or a real sleep for links without one."""
        waiter = getattr(self.inner, "wait", None)
        if callable(waiter):
            waiter(seconds)
        else:
            time.sleep(seconds)


def _block_writer(inner: Transport, cmd: str) -> Callable[[str, bytes], None]:
    writer = getattr(inner, "write_block", None)
    if not callable(writer):
        raise TransportError(f"{cmd!r}: the link {type(inner).__name__} cannot send a binary data block")
    return writer
