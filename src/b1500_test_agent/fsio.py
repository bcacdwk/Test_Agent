"""File primitives shared by every layer: atomic JSON writes, file removal, locked line appends, file digests and the
host name. A leaf of the package (it imports no other package module), so the session, the archive, the catalog,
the service and the maintainer tools use one implementation each.

- ``atomic_write_json``: the JSON goes to a temporary file of its own in the target's folder (``tempfile.mkstemp``,
  named ``.<name>.<random>.tmp``: no two writers share it, threads of one process included, and a state glob such as
  ``*.json`` or ``inflight-*`` never matches it; on POSIX it has ``mkstemp``'s owner-only mode, which the target
  keeps), then replaces the target with ``os.replace``, so a reader sees the old or the new file, never a partial
  one. With ``exclusive=True`` the file is published only if the target does not exist yet (``FileExistsError``
  otherwise): ``os.link`` on POSIX (``os.replace`` after an existence check where the file system has no hard
  links), ``os.rename`` on Windows; a crash before the publish leaves no target. The temporary file is removed on
  every path out, interrupts included; one left by a killed process is recognised by ``is_temp_name``.
- ``remove_file``: delete a file if it exists.
- ``append_line``: append one line (UTF-8, ``\\n``) under an inter-process file lock (``filelock``; the operating
  system releases it when the holder dies). The line may be computed under the lock (a callable), so a writer can
  derive it from the file's current content, e.g. the next id. A torn last line left by a killed writer is closed
  first, so the new line is well formed; readers skip the torn one.
- ``sha256_file``: streaming sha256 of a file.
- ``host_name``: this machine's host name.

Windows: a sync client (OneDrive), the search indexer or an antivirus scanner may hold a file open for a moment, and
``os.replace``, ``os.rename`` and ``unlink`` then fail with ``PermissionError`` (sharing violation). There these
calls are retried with a growing pause for up to ``RETRY_BUDGET_S`` seconds. On POSIX a ``PermissionError`` is a
real permission problem and is raised at once. ``_WINDOWS`` selects the branch (tests inject it).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import filelock

TEMP_SUFFIX = ".tmp"
"""Suffix of every temporary file ``atomic_write_json`` creates (``.<name>.<random>.tmp``)."""
LOCK_SUFFIX = ".lock"
"""Suffix of the default lock file of ``append_line`` (``<name>.lock`` beside the file)."""
RETRY_BUDGET_S = 2.0
"""Windows: how long a ``PermissionError`` of ``os.replace``/``os.rename``/``unlink`` is retried."""
APPEND_LOCK_TIMEOUT_S = 10.0
"""How long ``append_line`` waits for its file lock (``filelock.Timeout``, an ``OSError``, after that)."""

_WINDOWS = os.name == "nt"
_FIRST_PAUSE_S = 0.01
_MAX_PAUSE_S = 0.2
_CHUNK = 1 << 20

_T = TypeVar("_T")


def _retrying(action: Callable[[], _T]) -> _T:
    """Run ``action``; on Windows retry its ``PermissionError`` with a doubling pause (10 ms up to 200 ms) until
    ``RETRY_BUDGET_S`` has passed, then raise the last one. On POSIX one attempt."""
    if not _WINDOWS:
        return action()
    deadline = time.monotonic() + RETRY_BUDGET_S
    pause = _FIRST_PAUSE_S
    while True:
        try:
            return action()
        except PermissionError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(pause, remaining))
            pause = min(pause * 2, _MAX_PAUSE_S)


def is_temp_name(name: str) -> bool:
    """True for the name of a temporary file of ``atomic_write_json`` (``.<name>.<random>.tmp``)."""
    return name.startswith(".") and name.endswith(TEMP_SUFFIX)


def _publish_new(tmp: Path, path: Path) -> None:
    """Give the complete file ``tmp`` the name ``path`` atomically, only if ``path`` does not exist yet."""
    if _WINDOWS:
        _retrying(lambda: os.rename(tmp, path))  # never replaces an existing file on Windows
        return
    try:
        os.link(tmp, path)  # a second name for the complete file; refuses an existing one
    except FileExistsError:
        raise
    except OSError:
        # no hard links on this file system (e.g. FAT, some network shares): still atomic, exclusive up to the race
        # of two publishers of one file within this check
        if os.path.lexists(path):
            raise FileExistsError(f"{path} exists") from None
        os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any, *, exclusive: bool = False) -> None:
    """Write ``data`` as UTF-8 JSON (indent 1, ``\\n`` line ends) to ``path`` atomically (module docstring).

    Raises:
        FileExistsError: With ``exclusive``, when ``path`` exists already (it is left unchanged).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=TEMP_SUFFIX)
    tmp = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        if exclusive:
            _publish_new(tmp, path)
        else:
            _retrying(lambda: os.replace(tmp, path))
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def remove_file(path: Path) -> None:
    """Delete ``path`` if it exists (on Windows a ``PermissionError`` is retried, module docstring)."""
    _retrying(lambda: Path(path).unlink(missing_ok=True))


def append_line(path: Path, line: str | Callable[[], str], *, lock_path: Path | None = None,
                timeout_s: float = APPEND_LOCK_TIMEOUT_S) -> str:
    """Append one line to ``path`` (UTF-8, ``\\n``) while holding the file lock ``lock_path`` (default
    ``<path>.lock``) and return the line written (without its ``\\n``).

    ``line`` may be a callable: it is called under the lock (so it can read ``path``) and returns the line. A
    torn last line (no final ``\\n``, a writer killed mid-line) is closed with a ``\\n`` before the new line.

    Raises:
        ValueError: The line contains a line break.
        filelock.Timeout: The lock was not free within ``timeout_s`` (an ``OSError``; nothing written).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = filelock.FileLock(lock_path if lock_path is not None else path.with_name(path.name + LOCK_SUFFIX),
                             timeout=timeout_s, fallback_to_soft=False)
    with lock:
        text = line() if callable(line) else line
        if "\n" in text or "\r" in text:
            raise ValueError("append_line writes exactly one line: the text must not contain a line break")
        data = (text + "\n").encode("utf-8")
        try:
            with path.open("rb") as existing:
                if existing.seek(0, os.SEEK_END) > 0:
                    existing.seek(-1, os.SEEK_END)
                    if existing.read(1) != b"\n":
                        data = b"\n" + data
        except FileNotFoundError:
            pass
        with path.open("ab") as stream:
            stream.write(data)
    return text


def sha256_file(path: Path) -> str:
    """Streaming sha256 (hex) of the file ``path``."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_name() -> str:
    """This machine's host name (``unknown`` when it cannot be determined)."""
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"
