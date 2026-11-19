"""Cross-process abort of a running run: ``<state_dir>/abort.json`` (blueprint v2 2.6, decision 10).

Any process may ask the run that holds the instrument to stop: ``safe_shutdown`` (MCP tool or ``b1500 shutdown``),
the MCP server's shutdown hook (stdin EOF, SIGTERM, exit) and the CLI's Ctrl-C write an ``AbortRequest``
(``models/run.py``) with ``AbortFile.request``. The run polls it with an ``AbortWatch`` at every checkpoint
(``Transaction.checkpoint``, between segments of at most ``policy.run_limits.segment_max_s``) and in readback loops
(``Transaction.check_abort``, at least once a second), raises ``RunCancelled``, lets the transaction run its verified
cleanup and then removes the file (``consume``). A writer removes its own request when no run took it
(``withdraw``), so no request outlives the shutdown that wrote it.

A run honours only requests made after it started and addressed to it (``run_id``) or to whichever run is running
(``run_id`` ``None``); an older request (a writer that died before withdrawing it) is ignored, never deleted by a
reader. A file that exists but cannot be read counts as a request made when the file was last written (fail safe:
somebody wanted the run to stop).

Writes are atomic (temporary file + ``os.replace``); the file is tiny JSON, so polling it costs one ``stat`` and, when
it exists, one read.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.common import ErrorCode
from b1500_test_agent.models.run import AbortRequest, Adapter
from b1500_test_agent.session.lock import atomic_write_json, host_name, remove_file

ABORT_FILE = "abort.json"
REASON_MAX = 300
CORRUPT_ID = "0" * 16
"""``AbortRequest.id`` given to an abort file that cannot be read (``consume``/``withdraw`` of this id remove it)."""


class RunCancelled(B1500Error):
    """The run stopped at a checkpoint because an abort was requested (result code ``run_cancelled``). The transaction
    runs its full verified cleanup on the way out; ``request`` says who asked and why."""

    code: ClassVar[ErrorCode] = "run_cancelled"

    def __init__(self, request: AbortRequest, message: str | None = None) -> None:
        self.request = request
        who = f"{request.adapter or 'unknown'} pid {request.pid}"
        super().__init__(message or f"cancelled by an abort request ({request.reason}; {who})")


class AbortFile:
    """The abort file of one ``state_dir``."""

    def __init__(self, state_dir: Path) -> None:
        self.path = Path(state_dir) / ABORT_FILE

    def request(self, reason: str, *, adapter: Adapter | None, run_id: str | None = None,
                now: datetime | None = None) -> AbortRequest:
        """Write a new request (replacing any older one) and return it."""
        text = " ".join(str(reason or "").split())[:REASON_MAX] or "abort requested"
        request = AbortRequest(id=secrets.token_hex(8), requested_at=now or datetime.now(UTC), reason=text,
                               adapter=adapter, pid=os.getpid(), host=host_name(), run_id=run_id)
        atomic_write_json(self.path, request.model_dump(mode="json"))
        return request

    def read(self) -> AbortRequest | None:
        """The pending request, ``None`` without one; an unreadable or corrupt file is a request (``CORRUPT_ID``)
        stamped with the file's modification time. Checked at every checkpoint, so the usual case (no file) is one
        ``os.path.exists``: an attribute lookup on Windows (Python 3.12), where a failed open costs ~0.1 ms."""
        if not os.path.exists(self.path):
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            return self._corrupt(f"abort.json unreadable: {exc}")
        try:
            return AbortRequest.model_validate_json(text)
        except (ValueError, ValidationError) as exc:
            return self._corrupt(f"abort.json corrupt: {str(exc).splitlines()[0]}")

    def _corrupt(self, reason: str) -> AbortRequest | None:
        try:
            stamp = datetime.fromtimestamp(self.path.stat().st_mtime, UTC)
        except OSError:
            return None  # vanished meanwhile: consumed or withdrawn
        return AbortRequest(id=CORRUPT_ID, requested_at=stamp, reason=reason[:REASON_MAX])

    def remove(self, request_id: str) -> bool:
        """Delete the file if it still holds request ``request_id``; True when it did."""
        current = self.read()
        if current is None or current.id != request_id:
            return False
        remove_file(self.path)
        return True

    consume = remove
    """The run that honoured ``request_id`` removes it after its verified cleanup."""

    withdraw = remove
    """The writer removes its own request when no run took it."""


class AbortWatch:
    """What one run checks: requests to it (or to any run) made at or after ``since``.

    ``min_interval_s`` rate-limits the file reads (0 = read at every check); the clock is injectable for tests.
    """

    def __init__(self, file: AbortFile, *, run_id: str | None, since: datetime, min_interval_s: float = 0.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.file = file
        self.run_id = run_id
        self.since = since
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._checked_at: float | None = None
        self._seen: AbortRequest | None = None

    def applies(self, request: AbortRequest) -> bool:
        """True when ``request`` targets this run (or any run) and was made after the run started."""
        return request.run_id in (None, self.run_id) and request.requested_at >= self.since

    def pending(self) -> AbortRequest | None:
        """The request this run must honour, if any (sticky once seen)."""
        if self._seen is not None:
            return self._seen
        now = self._clock()
        if self._checked_at is not None and now - self._checked_at < self.min_interval_s:
            return None
        self._checked_at = now
        request = self.file.read()
        if request is not None and self.applies(request):
            self._seen = request
        return self._seen

    def check(self) -> None:
        """Raise ``RunCancelled`` when a request applies."""
        request = self.pending()
        if request is not None:
            raise RunCancelled(request)

    def consume(self) -> bool:
        """Remove the honoured request (after the cleanup); True when this removed the file."""
        return self._seen is not None and self.file.consume(self._seen.id)
