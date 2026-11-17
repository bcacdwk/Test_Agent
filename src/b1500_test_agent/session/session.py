"""``Session``: one per process; owns the transport, the instrument lock, the fault latch and the audit sink
(blueprint 2.4, 2.7).

Layering: session -> driver -> transport. The transport comes from ``transport_factory`` (normally
``make_transport(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
state_dir=bundle.paths.state_dir)``), is created lazily and opened at the first locked operation; a factory result
that is not an ``AuditingTransport`` is wrapped in one with the session's sink. Every instrument action holds the
instrument lock and, on the simulator, loads the shared state right after acquiring it and saves it right before
releasing it, so the MCP server and the CLI see one instrument.

``state_dir`` layout (blueprint 2.7): ``locks/`` (``InstrumentLock``), ``fault.json`` (``FaultLatch``),
``inflight.json`` (``Transaction``), ``sim/<scenario>.state.json`` (simulator), ``audit/YYYY-MM-DD.jsonl``
(``DailyAuditSink``: non-run actions and lifecycle events; runs log to their own ``audit.jsonl``).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.run import Adapter, CleanupReport, CleanupStep, LockHolder
from b1500_test_agent.models.station import LiveState, Settings
from b1500_test_agent.paths import Paths
from b1500_test_agent.session.fault import FaultLatch
from b1500_test_agent.session.lock import InstrumentLock, host_name
from b1500_test_agent.session.transaction import (
    InflightMarker,
    RunHandle,
    Transaction,
    new_tx_id,
    read_inflight,
    read_live_state,
)
from b1500_test_agent.transport.audit import AuditingTransport, AuditSink, JsonlAuditSink
from b1500_test_agent.transport.base import Transport, TransportError, state_hooks


class DailyAuditSink(JsonlAuditSink):
    """Appends each event to ``<audit_dir>/YYYY-MM-DD.jsonl`` by the event's UTC date (blueprint 2.7)."""

    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = Path(audit_dir)
        super().__init__(self.path_for(datetime.now(UTC)))

    def path_for(self, ts: datetime) -> Path:
        """The daily file that holds events stamped ``ts``."""
        return self.audit_dir / f"{ts.astimezone(UTC):%Y-%m-%d}.jsonl"

    def _record(self, event: AuditEvent) -> None:
        self.path = self.path_for(event.ts)
        super()._record(event)


def state_audit_sink(state_dir: Path) -> DailyAuditSink:
    """The session audit sink of ``state_dir``: ``<state_dir>/audit/YYYY-MM-DD.jsonl``."""
    return DailyAuditSink(Path(state_dir) / "audit")


class Session:
    """One per process; lazy open (blueprint 2.4).

    ``state_dir`` defaults to the configured one (``Paths.from_env().with_settings(settings.paths).state_dir``);
    ``adapter`` is recorded as the lock holder's adapter.
    """

    def __init__(self, settings: Settings, transport_factory: Callable[[], Transport], audit: AuditSink, *,
                 state_dir: Path | None = None, adapter: Adapter = "cli") -> None:
        self.settings = settings
        self.audit = audit
        self.adapter: Adapter = adapter
        self.state_dir = (Path(state_dir) if state_dir is not None
                          else Paths.from_env().with_settings(settings.paths).state_dir)
        self.fault_latch = FaultLatch(self.state_dir, audit=audit, backend=settings.backend)
        self.last_live: LiveState | None = None
        """The most recent snapshot (``snapshot(refresh=False)`` returns it)."""
        self._factory = transport_factory
        self._transport: AuditingTransport | None = None
        self._lock: InstrumentLock | None = None
        self._opened = False

    # -- plumbing ---------------------------------------------------------------------------------------------------

    @property
    def backend(self) -> Backend:
        return self._transport.backend if self._transport is not None else self.settings.backend

    @property
    def transport(self) -> AuditingTransport:
        """The audited transport (created by the factory on first use, not yet opened)."""
        if self._transport is None:
            transport = self._factory()
            self._transport = (transport if isinstance(transport, AuditingTransport)
                               else AuditingTransport(transport, self.audit))
        return self._transport

    @property
    def lock(self) -> InstrumentLock:
        """The instrument lock of this session's resource."""
        if self._lock is None:
            self._lock = InstrumentLock(self.state_dir, self.transport.resource)
        return self._lock

    @property
    def inflight_path(self) -> Path:
        return self.state_dir / "inflight.json"

    def inflight(self) -> InflightMarker | None:
        """The inflight marker, if one is present (a transaction is running or a process died inside one)."""
        return read_inflight(self.inflight_path)

    def _open(self) -> None:
        """Open the transport once (called under the instrument lock)."""
        if self._opened:
            return
        transport = self.transport
        transport.open()
        self._opened = True
        self.audit.emit(AuditEvent.now("session_open", transport.backend, data={
            "resource": transport.resource, "adapter": self.adapter, "state_dir": self.state_dir.as_posix(),
        }))

    def close(self) -> None:
        """Close the transport (a later action opens it again)."""
        if self._transport is not None and self._opened:
            self._transport.close()
        self._opened = False

    def _holder(self, plan_id: str | None = None) -> LockHolder:
        return LockHolder(pid=os.getpid(), host=host_name(), adapter=self.adapter, plan_id=plan_id,
                          since=datetime.now(UTC))

    # -- public API -------------------------------------------------------------------------------------------------

    def snapshot(self, *, refresh: bool = True, lock_timeout_s: float = 5.0) -> LiveState:
        """IDN, UNT, ERRX drain, STB, outputs; read-only (queries only, no source or channel commands).

        Runs under the instrument lock (``InstrumentBusy`` when held elsewhere); with ``refresh=False`` the last
        snapshot is returned without I/O when there is one. A stale inflight marker is left for the next
        transaction to recover.
        """
        if not refresh and self.last_live is not None:
            return self.last_live
        transport = self.transport
        tx_id = new_tx_id()
        with (
            self.lock.acquire(self._holder(), timeout_s=lock_timeout_s),
            transport.bind(tx=tx_id, intent="snapshot"),
        ):
            self._open()
            hooks = state_hooks(transport)
            if hooks is not None:
                hooks.load_state()
            try:
                live = read_live_state(B1500Driver(transport), backend=transport.backend,
                                       resource=transport.resource)
            finally:
                if hooks is not None:
                    hooks.save_state()
        self.last_live = live
        return live

    def transaction(self, *, intent: str, envelope: CompiledEnvelope | None, run: RunHandle | None,
                    lock_timeout_s: float = 5.0, plan_id: str | None = None) -> Transaction:
        """A transaction context manager (see ``Transaction``); ``envelope=None`` means no source operation is
        allowed (no ``OutputGuard``), and such a transaction also runs while the fault latch is set."""
        return Transaction(self, intent=intent, envelope=envelope, run=run, lock_timeout_s=lock_timeout_s,
                           plan_id=plan_id)

    def safe_shutdown(self, *, reason: str, abort: bool = True, lock_timeout_s: float = 5.0) -> CleanupReport:
        """``AB`` (when ``abort``) -> ``DZ`` -> ``CL`` -> ``ERRX?`` drain -> verify, with device clear and one retry;
        never gated (runs with a latched fault). An unverified result latches the fault. A stale inflight marker is
        recovered (audited ``recovery_cleanup``). It still takes the instrument lock, so a transaction in another
        process finishes its own cleanup first (``InstrumentBusy`` after ``lock_timeout_s``).

        When the transport cannot even be opened, the report is unverified and the fault is latched.
        """
        tx = Transaction(self, intent=f"safe_shutdown: {reason}", envelope=None, run=None,
                         lock_timeout_s=lock_timeout_s, mode="shutdown", abort=abort)
        try:
            with tx:
                pass
        except TransportError as exc:
            if tx.cleanup is not None:
                raise
            detail = f"transport unavailable: {type(exc).__name__}: {exc}"
            report = CleanupReport(steps=[CleanupStep(step="verify", ok=False, detail=detail[:500])],
                                   verified="unverified", outputs_after={}, latched_fault=True)
            self.audit.emit(AuditEvent.now("cleanup_unverified", self.backend, tx=tx.tx_id, intent=tx.intent,
                                           error=detail, data={"fault_latched": True}))
            self.fault_latch.set(f"safe shutdown unverified ({reason}): {detail}", None)
            return report
        if tx.cleanup is None:  # pragma: no cover - __exit__ always records a report in shutdown mode
            raise RuntimeError("safe shutdown produced no cleanup report")
        return tx.cleanup
