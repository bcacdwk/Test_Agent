"""Live WGFMU facts for snapshots, the pre-execute rules and the read-only probe (blueprint v2 2.4, 2.8 R-WG-01, 7.1
``doctor --probe --wgfmu-session``; WP10.2).

- ``library_probe(bus.wgfmu)``: the DLL probe of the bus's library binding (``WgfmuDll.probe``: a file read, cached,
  never a load), ``None`` for the simulated library. It fills ``LiveState.wgfmu_library`` on visa.
- ``read_channels(wgfmu, resource)``: ``open_session`` -> ``channel_ids`` -> ``close_session``, the close always
  attempted. It fills ``LiveState.wgfmu_channels`` in a transaction's pre-execute snapshot of a plan with WGFMU roles.
- ``check_session(wgfmu, resource)``: ``open_session`` -> ``channel_ids`` -> ``status`` -> ``close_session`` for the
  probe's ``--wgfmu-session`` line; never raises a ``WgfmuError``.
- ``bound(wgfmu, sink, ...)``: library calls in the block go to ``sink`` stamped with the run, transaction and intent
  (as ``AuditingTransport.bind`` does for the FLEX link).

All of them only read (ATV-16: opening a library session, reading the channel ids and the status changes no output;
TODO(verify) at bring-up L0). The library needs the B1500A without the FLEX link's exclusive VISA lock: callers
release it first (``Transaction.snapshot``) or close the FLEX link (``Session.wgfmu_session``); the simulator refuses
online calls while the lock is held, as the lab's VISA would (ATV-14).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

from b1500_test_agent.models.station import DllProbe
from b1500_test_agent.transport.audit import AuditSink
from b1500_test_agent.transport.base import unwrap
from b1500_test_agent.transport.wgfmu.api import WgfmuApi, WgfmuError
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu
from b1500_test_agent.transport.wgfmu.dll import WgfmuDll


def library_probe(wgfmu: WgfmuApi | None) -> DllProbe | None:
    """The DLL probe of ``wgfmu`` when it is the ctypes binding (looking through wrappers), else ``None``."""
    inner = unwrap(wgfmu) if wgfmu is not None else None
    return inner.probe() if isinstance(inner, WgfmuDll) else None


@contextlib.contextmanager
def bound(wgfmu: WgfmuApi, sink: AuditSink | None, *, run: str | None = None, tx: str | None = None,
          intent: str | None = None) -> Iterator[None]:
    """Audit the library calls of the block into ``sink`` with ``run``/``tx``/``intent`` (an ``AuditingWgfmu``;
    other implementations are used as they are)."""
    if not isinstance(wgfmu, AuditingWgfmu):
        yield
        return
    previous = wgfmu.sink
    if sink is not None:
        wgfmu.sink = sink
    try:
        with wgfmu.bind(run=run, tx=tx, intent=intent):
            yield
    finally:
        wgfmu.sink = previous


def read_channels(wgfmu: WgfmuApi, resource: str) -> list[int]:
    """``open_session(resource)`` -> ``channel_ids()`` -> ``close_session()``; the close is attempted after a
    failure too, and a close failure after a successful read raises."""
    wgfmu.open_session(resource)
    try:
        channels = wgfmu.channel_ids()
    except BaseException:
        with contextlib.suppress(Exception):
            wgfmu.close_session()
        raise
    wgfmu.close_session()
    return channels


@dataclass(frozen=True)
class SessionCheck:
    """What the probe's library session found: the channel ids and ``(status, elapsed_s, total_s)`` (``None`` where
    not read), the first failure, and a failure of the closing ``close_session``."""

    channels: list[int] | None = None
    status: tuple[int, float, float] | None = None
    error: WgfmuError | None = None
    close_error: WgfmuError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.close_error is None


def check_session(wgfmu: WgfmuApi, resource: str) -> SessionCheck:
    """``open_session`` -> ``channel_ids`` -> ``status`` -> ``close_session`` (blueprint v2 7.1); never raises a
    ``WgfmuError``. The close runs whenever the open succeeded."""
    try:
        wgfmu.open_session(resource)
    except WgfmuError as exc:
        return SessionCheck(error=exc)
    channels: list[int] | None = None
    status: tuple[int, float, float] | None = None
    error: WgfmuError | None = None
    try:
        channels = wgfmu.channel_ids()
        status = wgfmu.status()
    except WgfmuError as exc:
        error = exc
    close_error = None
    try:
        wgfmu.close_session()
    except WgfmuError as exc:
        close_error = exc
    return SessionCheck(channels=channels, status=status, error=error, close_error=close_error)
