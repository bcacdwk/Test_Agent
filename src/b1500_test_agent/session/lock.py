"""Instrument lock: one OS file lock per instrument resource plus a JSON sidecar naming the holder (blueprint 2.4).

``<state_dir>/locks/<resource-slug>.lock`` is held with ``filelock`` (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on
Windows; no POSIX-only code here), so the operating system releases it when the holding process dies: there are
no stale locks to break (decision 18). ``<state_dir>/locks/<resource-slug>.json`` records who holds it
(``LockHolder``: pid, host, adapter, plan id, since); it is written right after the lock is acquired and removed
before it is released. A sidecar left behind by a dead process is ignored because ``holder()`` reports a holder
only while the OS lock is actually held.

The lock is not re-entrant: a second ``acquire`` in the same process (another thread or a nested call) waits like a
foreign process and times out with ``InstrumentBusy``. The sidecar is written and removed with the file
primitives of ``fsio``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

import filelock
from pydantic import ValidationError

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.fsio import atomic_write_json, remove_file
from b1500_test_agent.models.common import ErrorCode
from b1500_test_agent.models.run import LockHolder


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
