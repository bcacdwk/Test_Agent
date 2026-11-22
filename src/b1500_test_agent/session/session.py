"""``Session``: one per process; owns the instrument bus, the instrument lock, the fault latch and the audit sink
(blueprint 2.4, 2.7; bus lifecycle v2 2.4).

Layering: session -> driver -> transport. The bus comes from ``bus_factory`` (normally ``make_bus(bundle.settings,
sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults, state_dir=bundle.paths.state_dir)``; a factory may
also return a bare ``Transport``), is created lazily, and its FLEX link is wrapped in an ``AuditingTransport`` with
the session's sink unless it already is one. Every instrument action holds the instrument lock and, on the
simulator, loads the shared state right after acquiring it and saves it right before releasing it, so the MCP
server and the CLI see one instrument.

Bus lifecycle (blueprint v2 2.4, decision 7): every transaction and status snapshot opens the FLEX link, takes its
exclusive lock, and unlocks and closes it at the end (``_bus_begin``/``_bus_end``, under the instrument lock and
inside the transaction's audit binding), so no process holds the VISA session or its lock between calls. With
``visa.session: process`` (ATV-13 fallback, backend visa only) the VISA session stays open for the process and only
the lock is taken and released per transaction. ``session_open`` is audited once per process (first open); the
``bus_*`` events of every open/lock/unlock/close go to the transaction's sink.

``state_dir`` layout (blueprint 2.7): ``locks/`` (``InstrumentLock``), ``fault.json`` (``FaultLatch``),
``inflight.json`` (``Transaction``), ``abort.json`` (``session/abort.py``, v2 2.6), ``sim/<scenario>.state.json``
(simulator), ``audit/YYYY-MM-DD.jsonl`` (``DailyAuditSink``: non-run actions and lifecycle events; runs log to their
own ``audit.jsonl``).

A run is *running* while its transaction's in-flight marker names it and the instrument lock is held
(``running_marker``): any process can see it (``station_status``, ``list_runs``) without touching the instrument.

WGFMU library (blueprint v2 2.4, 7.1; WP10.2): on visa every snapshot carries the DLL probe of the bus's library
binding (``LiveState.wgfmu_library``; a file read, never a load). ``check_wgfmu_session`` opens the library's own
session with the FLEX link closed, under the instrument lock (``doctor --probe --wgfmu-session``).
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.routing import SwitchSpec
from b1500_test_agent.models.run import Adapter, CleanupReport, CleanupStep, LockHolder
from b1500_test_agent.models.station import DllProbe, LiveState, Settings
from b1500_test_agent.paths import Paths
from b1500_test_agent.session.abort import AbortFile
from b1500_test_agent.session.fault import FaultLatch
from b1500_test_agent.session.lock import InstrumentLock, host_name
from b1500_test_agent.session.runner import RunControl
from b1500_test_agent.session.transaction import (
    InflightMarker,
    RunHandle,
    Transaction,
    new_tx_id,
    read_inflight,
    read_live_state,
)
from b1500_test_agent.session.wgfmu_live import SessionCheck, bound, check_session, library_probe
from b1500_test_agent.transport.audit import AuditingTransport, AuditSink, JsonlAuditSink
from b1500_test_agent.transport.base import Bus, BusLocked, Transport, TransportError, state_hooks
from b1500_test_agent.transport.readonly import ReadOnlyTransport
from b1500_test_agent.transport.wgfmu.api import LIBRARY_ERROR, WgfmuError, error_text

BusMode = Literal["transaction", "process"]
BusFactory = Callable[[], Bus | Transport]
RecoveryHook = Callable[[InflightMarker, CleanupReport], None]


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
    """One per process; lazy bus (blueprint 2.4, v2 2.4).

    ``bus_factory`` returns the ``Bus`` (or a bare FLEX ``Transport``); ``state_dir`` defaults to the configured one
    (``Paths.from_env().with_settings(settings.paths).state_dir``); ``adapter`` is recorded as the lock holder's
    adapter.
    """

    def __init__(self, settings: Settings, bus_factory: BusFactory, audit: AuditSink, *,
                 state_dir: Path | None = None, adapter: Adapter = "cli",
                 switches: Sequence[SwitchSpec] = ()) -> None:
        self.settings = settings
        self.audit = audit
        self.adapter: Adapter = adapter
        self.switches: tuple[SwitchSpec, ...] = tuple(switches)
        """The station's declared switches (``StationProfile.switches``): every transaction's ``OutputGuard`` admits
        their ``rest`` states, its cleanup returns them to rest and verifies them, snapshots read their states
        (blueprint v2 2.6 steps 5 and 8; WP9.2). Empty: no switch is touched."""
        self.state_dir = (Path(state_dir) if state_dir is not None
                          else Paths.from_env().with_settings(settings.paths).state_dir)
        self.fault_latch = FaultLatch(self.state_dir, audit=audit, backend=settings.backend)
        self.last_live: LiveState | None = None
        """The most recent snapshot (``snapshot(refresh=False)`` returns it)."""
        self.on_recovery: RecoveryHook | None = None
        """Called after a recovery cleanup of a stale in-flight marker that names a run (the executor finalizes the
        orphaned run folder); exceptions are audited, never raised."""
        self.abort_file = AbortFile(self.state_dir)
        """``<state_dir>/abort.json``: cancel requests to the running run (v2 2.6)."""
        self._factory = bus_factory
        self._bus: Bus | None = None
        self._lock: InstrumentLock | None = None
        self._bus_open = False
        self._announced = False

    # -- plumbing ---------------------------------------------------------------------------------------------------

    @property
    def backend(self) -> Backend:
        return self._bus.flex.backend if self._bus is not None else self.settings.backend

    @property
    def bus(self) -> Bus:
        """The instrument bus (created by the factory on first use, not yet opened); ``flex`` is audited."""
        if self._bus is None:
            made = self._factory()
            bus = made if isinstance(made, Bus) else Bus(flex=made)
            flex = bus.flex if isinstance(bus.flex, AuditingTransport) else AuditingTransport(bus.flex, self.audit)
            self._bus = bus._replace(flex=flex)
        return self._bus

    @property
    def transport(self) -> AuditingTransport:
        """The audited FLEX link of the bus."""
        return cast(AuditingTransport, self.bus.flex)  # the bus property wraps it

    @property
    def bus_mode(self) -> BusMode:
        """``transaction`` (open/lock/unlock/close per transaction and snapshot) or ``process`` (``visa.session:
        process``: the VISA session stays open, the lock is per transaction); always ``transaction`` off visa."""
        return self.settings.visa.session if self.backend == "visa" else "transaction"

    @property
    def bus_open(self) -> bool:
        """True while the FLEX link is open (inside a transaction, or between transactions in ``process`` mode)."""
        return self._bus_open

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

    def running_marker(self) -> InflightMarker | None:
        """The in-flight marker of a run that is running now (in this or another process): the marker names a run
        and the instrument lock is held. File reads only, no instrument I/O."""
        marker = self.inflight()
        if marker is None or marker.run is None or not self.lock.is_held():
            return None
        return marker

    def _bus_begin(self) -> None:
        """Open (if needed) and lock the FLEX link for one transaction or snapshot; called under the instrument lock
        inside the audit binding. Raises ``BusLocked`` when another client holds the bus (the link is then closed
        again, except a ``process``-mode session, which stays open) and ``TransportError`` when it cannot open."""
        transport = self.transport
        if self._bus_open:  # process mode: the VISA session stayed open; take the lock again
            try:
                transport.lock()
                return
            except BusLocked:
                raise
            except Exception:  # noqa: BLE001 - a stale session (lost link, invalid session) is reopened below
                self._bus_close()
            except BaseException:
                self._bus_close()
                raise
        transport.open()
        self._bus_open = True
        try:
            self._announce()
            transport.lock()
        except BaseException:
            self._bus_close()
            raise

    def _bus_end(self) -> None:
        """Release the FLEX link after a transaction or snapshot: unlock, and close unless in ``process`` mode. Never
        raises an ``Exception`` (failures are audited by ``AuditingTransport``; the link is then closed)."""
        if not self._bus_open:
            return
        try:
            self.transport.unlock()
        except Exception:  # noqa: BLE001 - recorded as a failed bus_unlock; closing releases the lock anyway
            self._bus_close()
            return
        if self.bus_mode == "transaction":
            self._bus_close()

    def _bus_close(self) -> None:
        self._bus_open = False
        with contextlib.suppress(Exception):  # Transport.close never raises; a broken wrapper must not either
            self.transport.close()

    def _announce(self) -> None:
        """Audit ``session_open`` once per process (the first time the bus opens)."""
        if self._announced:
            return
        transport = self.transport
        self.audit.emit(AuditEvent.now("session_open", transport.backend, data={
            "resource": transport.resource, "adapter": self.adapter, "state_dir": self.state_dir.as_posix(),
            "bus": self.bus_mode,
        }))
        self._announced = True

    def close(self) -> None:
        """Close the bus if it is open (``process`` mode, or an interrupted call); a later action opens it again."""
        if self._bus is not None and self._bus_open:
            self._bus_close()

    def _holder(self, plan_id: str | None = None) -> LockHolder:
        return LockHolder(pid=os.getpid(), host=host_name(), adapter=self.adapter, plan_id=plan_id,
                          since=datetime.now(UTC))

    # -- public API -------------------------------------------------------------------------------------------------

    @contextlib.contextmanager
    def read_only(self, intent: str, *, lock_timeout_s: float = 5.0) -> Iterator[B1500Driver]:
        """A driver whose link lets only single queries through (``ReadOnlyTransport``), for the duration of the
        block: instrument lock (``InstrumentBusy`` when held elsewhere), audit binding (one transaction id,
        ``intent``), bus open + exclusive lock, simulator state loaded; on exit the state is saved and the bus
        unlocked and closed. Any other command, a device clear or a serial poll raises ``ReadOnlyViolation`` and
        nothing is sent. ``driver.transport.transcript`` lists every query and answer. No guard: source operations
        refuse. A stale inflight marker is left for the next transaction to recover. Used by ``snapshot`` and the
        bring-up probe (blueprint v2 7.1)."""
        transport = self.transport
        with (
            self.lock.acquire(self._holder(), timeout_s=lock_timeout_s),
            transport.bind(tx=new_tx_id(), intent=intent),
        ):
            self._bus_begin()
            try:
                hooks = state_hooks(transport)
                if hooks is not None:
                    hooks.load_state()
                try:
                    yield B1500Driver(ReadOnlyTransport(transport))
                finally:
                    if hooks is not None:
                        hooks.save_state()
            finally:
                self._bus_end()

    def snapshot(self, *, refresh: bool = True, lock_timeout_s: float = 5.0) -> LiveState:
        """IDN, UNT, ERRX drain, STB, outputs and the declared switches' states that queries can read (selectors only
        while their control mode is on); read-only (``read_only``: queries only, no source or channel commands).

        Runs under the instrument lock (``InstrumentBusy`` when held elsewhere); with ``refresh=False`` the last
        snapshot is returned without I/O when there is one. A stale inflight marker is left for the next
        transaction to recover.
        """
        if not refresh and self.last_live is not None:
            return self.last_live
        transport = self.transport
        with self.read_only("snapshot", lock_timeout_s=lock_timeout_s) as driver:
            live = read_live_state(driver, backend=transport.backend, resource=transport.resource,
                                   switches=self.switches)
        library = self.wgfmu_library()
        if library is not None:
            live = live.model_copy(update={"wgfmu_library": library})
        self.last_live = live
        return live

    def wgfmu_library(self) -> DllProbe | None:
        """The probe of the WGFMU library binding on visa (``WgfmuDll.probe``: a file read, never a load); ``None``
        on the simulator and without a library."""
        if self.backend != "visa":
            return None
        return library_probe(self.bus.wgfmu)

    def check_wgfmu_session(self, intent: str, *, lock_timeout_s: float = 5.0) -> SessionCheck:
        """The WGFMU library's own session, read only, with the FLEX link closed (blueprint v2 7.1
        ``--wgfmu-session``, ATV-16): instrument lock (``InstrumentBusy`` when held elsewhere), the FLEX link closed
        (also in ``process`` mode), simulator state loaded, ``open_session`` -> ``channel_ids`` -> ``status`` ->
        ``close_session`` audited in the session sink with one transaction id, state saved. Library failures are in
        the result, never raised."""
        wgfmu = self.bus.wgfmu
        if wgfmu is None:
            return SessionCheck(error=WgfmuError(LIBRARY_ERROR, error_text(LIBRARY_ERROR, "no WGFMU instrument "
                                                                           "library on this bus"),
                                                 function="open_session"))
        transport = self.transport
        with self.lock.acquire(self._holder(), timeout_s=lock_timeout_s):
            self.close()  # the library opens its own session to the B1500A: the FLEX link stays closed meanwhile
            hooks = state_hooks(transport)
            if hooks is not None:
                hooks.load_state()
            try:
                with bound(wgfmu, self.audit, tx=new_tx_id(), intent=intent):
                    return check_session(wgfmu, transport.resource)
            finally:
                if hooks is not None:
                    hooks.save_state()

    def transaction(self, *, intent: str, envelope: CompiledEnvelope | None, run: RunHandle | None,
                    lock_timeout_s: float = 5.0, plan_id: str | None = None,
                    control: RunControl | None = None) -> Transaction:
        """A transaction context manager (see ``Transaction``); ``envelope=None`` means no source operation is
        allowed (no ``OutputGuard``), and such a transaction also runs while the fault latch is set. ``control``
        carries a run's checkpoint state (progress, abort watch; ``session/runner.py``)."""
        return Transaction(self, intent=intent, envelope=envelope, run=run, lock_timeout_s=lock_timeout_s,
                           plan_id=plan_id, control=control)

    def safe_shutdown(self, *, reason: str, abort: bool = True, lock_timeout_s: float = 5.0) -> CleanupReport:
        """``AB`` (when ``abort``) -> ``SPP`` (with an SPGU) -> ``DZ`` -> switches to rest -> ``CL`` -> ``ERRX?`` drain
        -> verify (outputs and declared switches), with device clear and one retry;
        never gated (runs with a latched fault). An unverified result latches the fault. A stale inflight marker is
        recovered (audited ``recovery_cleanup``). It still takes the instrument lock, so a transaction in another
        process finishes its own cleanup first (``InstrumentBusy`` after ``lock_timeout_s``).

        When the transport cannot even be opened, or another client holds the bus lock (``BusLocked``), nothing can
        be verified: the report is unverified and the fault is latched.
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
