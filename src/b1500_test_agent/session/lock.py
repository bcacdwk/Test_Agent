"""Instrument lock: one OS file lock per instrument resource plus a JSON sidecar naming the holder (blueprint 2.4).

``<state_dir>/locks/<resource-slug>.lock`` is held with ``filelock`` (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on
Windows; no POSIX-only code here), so the operating system releases it when the holding process dies: there are
no stale locks to break (decision 18). ``<state_dir>/locks/<resource-slug>.json`` records who holds it
(``LockHolder``: pid, host, adapter, plan id, since); it is written right after the lock is acquired and removed
before it is released. A sidecar left behind by a dead process is ignored because ``holder()`` reports a holder
only while the OS lock is actually held.

The lock is not re-entrant: a second ``acquire`` in the same process (another thread or a nested call) waits like a
foreign process and times out with ``InstrumentBusy``.

Small file helpers shared by the session package (atomic JSON writes, host name) live here too.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import filelock
from pydantic import ValidationError

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.common import ErrorCode
from b1500_test_agent.models.run import LockHolder

_REPLACE_RETRIES = 5
_REPLACE_BACKOFF_S = 0.02


class InstrumentBusy(B1500Error):
    """The instrument lock is held by someone else (result code ``instrument_busy``); ``holder`` says who, when
    known."""

    code: ClassVar[ErrorCode] = "instrument_busy"

    def __init__(self, holder: LockHolder | None, message: str | None = None) -> None:
        self.holder = holder
        if message is None:
            if holder is None:
                message = "instrument busy: the lock is held by another process (holder unknown)"
            else:
                plan = f", plan {holder.plan_id}" if holder.plan_id else ""
                message = (f"instrument busy: held by pid {holder.pid} on {holder.host} ({holder.adapter}{plan}) "
                           f"since {holder.since.isoformat()}")
        super().__init__(message)


def resource_slug(resource: str) -> str:
    """File-name-safe slug of a resource name: ``GPIB0::17::INSTR`` -> ``gpib0-17-instr``,
    ``SIM::nmos_basic`` -> ``sim-nmos_basic`` (no ``:`` in file names, case-insensitive file systems)."""
    slug = re.sub(r"[^a-z0-9_.]+", "-", resource.lower()).strip("-.")
    if not slug:
        raise ValueError(f"Resource {resource!r} has no usable characters for a lock file name.")
    return slug


def host_name() -> str:
    """This machine's host name (``unknown`` when it cannot be determined)."""
    try:
        return socket.gethostname() or "unknown"
    except OSError:  # pragma: no cover - platform specific
        return "unknown"


def atomic_write_json(path: Path, data: Any) -> None:
    """Write ``data`` as UTF-8 JSON to ``path`` atomically (temporary file in the same directory + ``os.replace``).

    ``os.replace`` can fail transiently on Windows while another process has the target open for reading; it is
    retried a few times.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def remove_file(path: Path) -> None:
    """Delete ``path`` if it exists (retried briefly on Windows sharing violations)."""
    for attempt in range(_REPLACE_RETRIES):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))


class InstrumentLock:
    """Inter-process lock of one instrument resource (blueprint 2.4)."""

    def __init__(self, state_dir: Path, resource: str) -> None:
        self.resource = resource
        slug = resource_slug(resource)
        self.lock_file = Path(state_dir) / "locks" / f"{slug}.lock"
        self.sidecar = Path(state_dir) / "locks" / f"{slug}.json"

    def _file_lock(self) -> filelock.BaseFileLock:
        # A fresh, non-singleton lock object per attempt: its own file descriptor, so a second attempt in the same
        # process contends like a foreign process. No silent fallback to a soft (existence-based) lock, which
        # would survive a crash.
        return filelock.FileLock(self.lock_file, fallback_to_soft=False)

    @contextmanager
    def acquire(self, holder: LockHolder, *, timeout_s: float = 5.0) -> Iterator[None]:
        """Hold the lock for the ``with`` block and publish ``holder`` in the sidecar.

        Raises:
            InstrumentBusy: If the lock is not free within ``timeout_s`` (carries the current holder).
        """
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock = self._file_lock()
        try:
            lock.acquire(timeout=max(0.0, timeout_s))
        except filelock.Timeout:
            raise InstrumentBusy(self._read_sidecar()) from None
        try:
            atomic_write_json(self.sidecar, holder.model_dump(mode="json"))
            yield
        finally:
            try:
                remove_file(self.sidecar)
            finally:
                lock.release()

    def _read_sidecar(self) -> LockHolder | None:
        try:
            return LockHolder.model_validate_json(self.sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    def is_held(self) -> bool:
        """True while some process (this one included) holds the lock."""
        if not self.lock_file.exists():
            return False
        probe = self._file_lock()
        try:
            probe.acquire(timeout=0)
        except filelock.Timeout:
            return True
        probe.release()
        return False

    def holder(self) -> LockHolder | None:
        """The current holder, or ``None`` when the lock is free (a stale sidecar of a dead process is ignored)."""
        if not self.is_held():
            return None
        return self._read_sidecar()
