"""``RawCapture``: the raw-data tap of a transaction with a run (blueprint 2.4, 2.7; moved out of ``transaction.py``).

Every ``read`` (measurement data; queries use ``query``) is stored with ``RunHandle.save_raw`` and audited as
``data_block`` before the driver parses it, so raw data survive parser errors and later failures.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from b1500_test_agent.models.common import Backend
from b1500_test_agent.transport.base import Transport, TransportError

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import RunHandle

Emit = Callable[..., None]


class RawCapture:
    """Transport wrapper under the transaction driver: every ``read`` (measurement data; queries use ``query``) is
    stored with ``RunHandle.save_raw`` and audited as ``data_block`` before the driver parses it."""

    def __init__(self, inner: Transport, run: RunHandle, emit: Emit) -> None:
        self.inner = inner
        self._run = run
        self._emit = emit
        self.blocks = 0

    @property
    def backend(self) -> Backend:
        return self.inner.backend

    @property
    def resource(self) -> str:
        return self.inner.resource

    def open(self) -> None:
        self.inner.open()

    def close(self) -> None:
        self.inner.close()

    def lock(self) -> None:
        self.inner.lock()

    def unlock(self) -> None:
        self.inner.unlock()

    def write(self, cmd: str) -> None:
        self.inner.write(cmd)

    def read(self, *, timeout_s: float | None = None) -> str:
        text = self.inner.read(timeout_s=timeout_s)
        index = self.blocks
        self.blocks += 1
        where = self._run.save_raw(text)
        self._emit("data_block", {"index": index, "chars": len(text), "file": where})
        return text

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        return self.inner.query(cmd, timeout_s=timeout_s)

    def serial_poll(self) -> int:
        return self.inner.serial_poll()

    def device_clear(self) -> None:
        self.inner.device_clear()

    def write_block(self, cmd: str, data: bytes) -> None:
        writer = getattr(self.inner, "write_block", None)
        if not callable(writer):
            raise TransportError(f"{cmd!r}: the link cannot send a binary data block")
        writer(cmd, data)

    def wait(self, seconds: float) -> None:
        waiter = getattr(self.inner, "wait", None)
        if callable(waiter):
            waiter(seconds)
        else:
            time.sleep(seconds)
