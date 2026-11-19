"""``Transaction``: one locked, audited instrument transaction with guaranteed cleanup (blueprint 2.4, 2.7, 3).

``__enter__``: fault-latch check (a sourcing transaction refuses with ``fault_latched``, zero I/O), instrument lock,
bus open + exclusive lock (blueprint v2 2.4: per transaction; ``BusLocked`` when another client holds the bus, zero
I/O, marker untouched), simulator state load, ``<state_dir>/inflight.json``; if a previous marker is still there its
transaction never finished (crash), so a recovery cleanup runs first (``AB``, ``DZ``, ``CL``, verify; audit
``recovery_cleanup``); then a baseline ``ERRX?`` drain. The body uses ``tx.driver``, guarded by an ``OutputGuard``
of the plan's envelope (no envelope: no guard, so every source operation refuses).

``__exit__`` runs for ANY exit, ``BaseException`` and ``EnvelopeViolation`` included:
1 ``AB`` if ``XE`` was issued and its read did not complete (sent alone; on timeout device clear, then ``AB``)
2 ``DZ`` 3 ``CL`` 4 ``ERRX?`` drain 5 verify outputs off (``LOP?`` on hardware, simulator state on sim; on hardware
a failed ``LOP?`` positive control makes the verification fail whatever ``LOP?`` reads)
6 on any step error: device clear, retry the sequence once
7 still unverified (``DZ``, ``CL`` or the verification failed in the last attempt) -> ``FaultLatch.set`` + audit
``cleanup_unverified`` 8 save the simulator state, remove the inflight marker, unlock and close the bus (``process``
mode: unlock only), release the lock.
The original exception is never suppressed. When the body succeeded, ``__exit__`` raises a
``KeyboardInterrupt``/``SystemExit`` caught during cleanup (cleanup completes first), else ``CleanupUnverified``
if the fault latch was set.

Audit: every event of the transaction carries its ``tx`` id and intent; with a ``RunHandle`` the transport I/O and
the lifecycle events go to the run's sink (``audit.jsonl`` of the run folder) and every measurement read is handed to
``RunHandle.save_raw`` before it is parsed, so raw data survives parser errors and later failures. Without a run
they go to the session's sink (``<state_dir>/audit/YYYY-MM-DD.jsonl``).

Runs (blueprint v2 2.6): kinds call ``checkpoint(done, total, phase, rows)`` between segments and long readback
loops call ``check_abort()``; with a ``RunControl`` (``session/runner.py``) this records the progress of an
asynchronous run and raises ``RunCancelled`` when ``safe_shutdown`` asked (any process, abort file), which the exit
path handles like any other exception: full cleanup, verified. ``suspend_auto_calibration`` (R-CAL-02) sends
``CM 0`` and makes the cleanup restore the state read before the run (``restore`` step after the verification;
skipped when the cleanup could not verify the outputs). A recovery cleanup of a stale in-flight marker is reported
to ``Session.on_recovery`` (the executor finalizes the orphaned run folder).

``LOP?`` positive control (blueprint v2 10.2 row 6.2; v1 ATV-1, ATV-23): on hardware a kind calls
``lop_positive_control(channels)`` right after ``CN`` (outputs on at 0 V, before any level): ``LOP?`` must report a
non-``00`` code for every slot it switched on. The reading goes to the audit (``checkpoint``
``lop_positive_control``) and into ``CleanupReport.positive_control`` (the run manifest), next to the cleanup's
all-``00`` reading, as the evidence behind ``verified: lop``. A slot reading ``00`` raises ``PositiveControlFailed``
before any level is applied, and the cleanup then cannot verify (``LOP?`` has shown that it does not see the output
switches), so the fault latches. The simulator needs no control (its cleanup reads the simulated state).
"""

from __future__ import annotations

import math
import os
import secrets
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, ValidationError

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.discovery import all_outputs_off
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.models.audit import AuditEvent, AuditEventName
from b1500_test_agent.models.common import Backend, JsonScalar, StrictModel
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.run import Adapter, CleanupReport, CleanupStep, LockHolder, PositiveControl
from b1500_test_agent.models.station import InstrumentError, LiveState, channel_slot
from b1500_test_agent.session.fault import CleanupUnverified, FaultLatched, PositiveControlFailed
from b1500_test_agent.session.lock import atomic_write_json, host_name, remove_file
from b1500_test_agent.transport.audit import AuditingTransport, AuditSink
from b1500_test_agent.transport.base import Transport, TransportTimeout, state_hooks, unwrap

if TYPE_CHECKING:
    from b1500_test_agent.session.runner import RowsSource, RunControl
    from b1500_test_agent.session.session import Session

CleanupStepName = Literal["abort", "zero", "disconnect", "drain_errors", "verify", "device_clear", "restore"]

STATE_SAVE_INTERVAL_S = 1.0
"""Least wall time between two saves of the simulator state at checkpoints (the persisted state then shows what a
killed run left on, as the real instrument would, without a save per segment of a fast simulated run)."""
Emit = Callable[..., None]

_DETAIL_LIMIT = 500


# -- The run seen from a transaction --------------------------------------------------------------------------------


@runtime_checkable
class RunHandle(Protocol):
    """What a transaction needs from a run folder; implemented by the archive (WP1.7).

    ``run_id`` is stamped on every audit event; ``audit`` is the run's own sink (``<run>/audit.jsonl``), which
    receives the transport I/O and lifecycle events of the transaction; ``save_raw`` stores the exact text of one
    measurement read (``raw/block-NNN.txt``) and returns where it went (run-relative path). It is called for every
    read after ``XE``, before parsing, so raw data is kept even when parsing or the rest of the run fails.
    """

    run_id: str
    audit: AuditSink

    def save_raw(self, raw: str) -> str:
        """Store one raw measurement response; returns its run-relative path."""
        ...


# -- Inflight marker --------------------------------------------------------------------------------------------------


class InflightMarker(StrictModel):
    """``<state_dir>/inflight.json``: written under the lock when a transaction starts, removed when it ends. A marker
    found by the next transaction means the previous one never finished (process crash), so it recovers first."""

    tx: str = "unknown"
    run: str | None = None
    intent: str = ""
    plan_id: str | None = None
    resource: str = "unknown"
    backend: Backend | None = None
    pid: int = 0
    host: str = "unknown"
    adapter: Adapter | None = None
    since: AwareDatetime | None = None


def read_inflight(path: Path) -> InflightMarker | None:
    """The marker at ``path``, ``None`` when absent; an unreadable marker still counts (recovery runs)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        return InflightMarker(intent=f"unreadable inflight marker: {exc}")
    try:
        return InflightMarker.model_validate_json(text)
    except (ValueError, ValidationError) as exc:
        return InflightMarker(intent=f"corrupt inflight marker: {str(exc).splitlines()[0]}")


def new_tx_id(now: datetime | None = None) -> str:
    """Transaction id ``T`` + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 hex digits (the run-id shape, blueprint 0 #9)."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"T{stamp}-{secrets.token_hex(2)}"


# -- Live state -------------------------------------------------------------------------------------------------------


def read_live_state(driver: B1500Driver, *, backend: Backend, resource: str,
                    earlier_errors: list[InstrumentError] | None = None) -> LiveState:
    """Read-only snapshot through ``driver``: ``*IDN?``, ``UNT?``, ``ERRX?`` drain, ``*STB?``, ``LOP?``.

    ``earlier_errors`` (e.g. a transaction's baseline drain) are listed before the newly drained ones.
    """
    identity = driver.identify()
    inventory = driver.modules()
    errors = [*(earlier_errors or []), *driver.errors(drain=True)]
    status = driver.status_byte()
    outputs = driver.output_state()
    return LiveState(backend=backend, resource=resource, taken_at=datetime.now(UTC), identity=identity,
                     inventory=inventory, errors=errors, status_byte=status, outputs=outputs)


# -- Cleanup ----------------------------------------------------------------------------------------------------------


def sim_instrument(transport: object) -> Any | None:
    """The simulated instrument behind ``transport`` (looking through wrappers), or ``None`` on hardware.

    Verification on the simulator reads its state directly (``unsafe_reasons()``/``outputs()``, blueprint 3)."""
    if getattr(transport, "backend", None) != "sim":
        return None
    instrument = getattr(unwrap(transport), "instrument", None)
    if callable(getattr(instrument, "unsafe_reasons", None)) and callable(getattr(instrument, "outputs", None)):
        return instrument
    return None


def _sim_output_text(state: Any) -> str:
    on = "on" if state.output_on else "off"
    return on if state.voltage == 0 else f"{on} {state.voltage:g} V"


@dataclass
class CleanupOutcome:
    """A cleanup report plus a ``KeyboardInterrupt``/``SystemExit`` caught while cleaning up (re-raised by the
    caller once everything is released)."""

    report: CleanupReport
    deferred: BaseException | None


def run_cleanup(driver: B1500Driver, *, always_abort: bool, emit: Emit,
                positive: PositiveControl | None = None) -> CleanupOutcome:
    """``AB`` (when ``always_abort`` or a measurement is pending) -> ``DZ`` -> ``CL`` -> ``ERRX?`` drain -> verify;
    after any failed step a device clear and one retry of the whole sequence (blueprint 2.4 steps 1-6).

    Every step continues after a failure of an earlier one (``CL`` turns outputs off even when ``DZ`` failed) and
    is audited as ``cleanup_step``. The result is verified only when ``DZ``, ``CL`` and the verification all
    succeeded in the last attempt; the caller latches the fault otherwise. ``positive`` is the transaction's
    hardware ``LOP?`` positive control: it is copied into the report, and a failed one fails the verification
    (``LOP?`` reading ``00`` proves nothing then). Never raises: exceptions inside steps, ``BaseException``
    included, are recorded (interrupts are returned as ``deferred``).
    """
    sim = sim_instrument(driver.transport)
    method: Literal["sim_state", "lop"] = "sim_state" if sim is not None else "lop"
    steps: list[CleanupStep] = []
    errors: list[InstrumentError] = []
    outputs: dict[int, str] = {}
    deferred: list[BaseException] = []

    def step(name: CleanupStepName, attempt: int, action: Callable[[], tuple[bool, str]]) -> bool:
        error: str | None = None
        try:
            ok, detail = action()
        except BaseException as exc:  # noqa: BLE001 - cleanup must survive anything; interrupts are deferred
            if not isinstance(exc, Exception):
                deferred.append(exc)
            ok, detail = False, f"{type(exc).__name__}: {exc}"
            error = detail
        record = CleanupStep(step=name, ok=ok, attempt=attempt, detail=detail[:_DETAIL_LIMIT])
        steps.append(record)
        emit("cleanup_step", {"step": name, "ok": ok, "attempt": attempt, "detail": record.detail}, error=error)
        return ok

    def abort() -> tuple[bool, str]:
        try:
            driver.abort()
        except TransportTimeout as exc:
            driver.device_clear()
            driver.abort()
            return True, f"abort timed out ({exc}); device clear, then abort again"
        return True, "sent alone"

    def zero() -> tuple[bool, str]:
        driver.zero()
        return True, "all channels"

    def disconnect() -> tuple[bool, str]:
        driver.disconnect()
        return True, "all channels"

    def drain() -> tuple[bool, str]:
        found = driver.errors(drain=True)
        errors.extend(found)
        for item in found:
            emit("instrument_error", {"code": item.code, "message": item.message, "phase": "cleanup"})
        return True, ", ".join(f"{e.code} {e.message}".strip() for e in found) or "queue empty"

    def verify() -> tuple[bool, str]:
        outputs.clear()
        if sim is not None:
            reasons = sim.unsafe_reasons()
            outputs.update({ch: _sim_output_text(state) for ch, state in sorted(sim.outputs().items())})
            return not reasons, "; ".join(reasons) or "simulator state safe"
        states = driver.output_state()
        outputs.update({slot: out.state for slot, out in sorted(states.items())})
        on = {slot: code for slot, code in outputs.items() if states[slot].output_on}
        if on:
            return False, f"outputs on: {on}"
        if positive is not None and not positive.ok:
            return False, (f"all slots report 00, but the LOP? positive control failed ({positive.detail}): 00 does "
                           "not prove the outputs off")
        evidence = "" if positive is None else f"; positive control with the outputs on: {positive.detail}"
        return all_outputs_off(states), "all slots report 00" + evidence

    def clear() -> tuple[bool, str]:
        driver.device_clear()
        return True, "before the retry"

    verified = False
    for attempt in (1, 2):
        if attempt == 2:
            step("device_clear", attempt, clear)
        results: dict[str, bool] = {}
        if always_abort or driver.measurement_pending:
            results["abort"] = step("abort", attempt, abort)
        results["zero"] = step("zero", attempt, zero)
        results["disconnect"] = step("disconnect", attempt, disconnect)
        results["drain_errors"] = step("drain_errors", attempt, drain)
        results["verify"] = step("verify", attempt, verify)
        verified = results["zero"] and results["disconnect"] and results["verify"]
        if all(results.values()):
            break
    report = CleanupReport(steps=steps, verified=method if verified else "unverified", outputs_after=dict(outputs),
                           latched_fault=False, errors=errors, positive_control=positive)
    return CleanupOutcome(report=report, deferred=deferred[0] if deferred else None)


def _codes_text(codes: dict[int, str]) -> str:
    """``slot 3 01, slot 4 01`` (``LOP?`` codes by slot) for audit details and messages."""
    return ", ".join(f"slot {slot} {code}" for slot, code in sorted(codes.items()))


# -- Raw-data tap -----------------------------------------------------------------------------------------------------


class _RawCapture:
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


# -- Transaction ------------------------------------------------------------------------------------------------------


def _scalar(value: object) -> JsonScalar:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value if value is None or isinstance(value, bool | int | float | str) else str(value)


class Transaction:
    """__enter__: fault-latch check, lock, write <state_dir>/inflight.json, recover if a previous inflight marker
    exists (AB, DZ, CL, verify), baseline ERRX drain. Body uses tx.driver (guarded).
    __exit__ runs for ANY exit incl. BaseException/EnvelopeViolation: 1 AB if XE issued and not complete
    (sent alone; on timeout device_clear then AB) 2 DZ 3 CL 4 ERRX drain 5 verify outputs off (LOP? on hw,
    sim_state on sim) 6 on any step error: device_clear, retry once 7 still unverified → FaultLatch.set +
    audit cleanup_unverified 8 remove inflight marker, unlock + close the bus, release lock. Never suppresses the
    original exception.

    Created by ``Session.transaction`` (and, in ``shutdown`` mode, by ``Session.safe_shutdown``: no latch check,
    no recovery or baseline drain, cleanup with an unconditional ``AB`` when ``abort``, never raises
    ``CleanupUnverified``). Single use; not re-entrant.
    """

    driver: B1500Driver
    cleanup: CleanupReport | None

    def __init__(self, session: Session, *, intent: str, envelope: CompiledEnvelope | None, run: RunHandle | None,
                 lock_timeout_s: float = 5.0, plan_id: str | None = None,
                 mode: Literal["transaction", "shutdown"] = "transaction", abort: bool = True,
                 control: RunControl | None = None) -> None:
        self._session = session
        self.intent = intent
        self.envelope = envelope
        self.run = run
        self.control = control
        """Checkpoint state of the run (progress, abort watch); ``None`` = checkpoints only audit."""
        self.lock_timeout_s = lock_timeout_s
        self.plan_id = plan_id
        self.mode = mode
        self._always_abort = mode == "shutdown" and abort
        self.tx_id = new_tx_id()
        self.cleanup = None
        self.recovery: CleanupReport | None = None
        """Report of the recovery cleanup run at ``__enter__`` for a stale inflight marker (else ``None``)."""
        self.previous_marker: InflightMarker | None = None
        self.baseline_errors: list[InstrumentError] = []
        self._stack: ExitStack | None = None
        self._sink: AuditSink | None = None
        self._transport: AuditingTransport | None = None
        self._marker_written = False
        self._bus_begun = False
        self._cleanup_done = False
        self._used = False
        self.latch_error: Exception | None = None
        """Why ``FaultLatch.set`` failed, if it did (raised after release unless the body already raised)."""
        self.audit_failures: list[str] = []
        """Lifecycle events that could not be recorded (an audit failure never stops cleanup or release)."""
        self.auto_calibration_before: bool | None = None
        """Auto-calibration state read before ``suspend_auto_calibration`` (``None`` = unknown)."""
        self.positive_control: PositiveControl | None = None
        """The hardware ``LOP?`` positive control of this transaction (``lop_positive_control``), if one ran."""
        self._auto_calibration_suspended = False
        self._state_saved_at: float | None = None

    # -- audit ------------------------------------------------------------------------------------------------------

    @property
    def run_id(self) -> str | None:
        return None if self.run is None else self.run.run_id

    def _emit(self, ev: AuditEventName, data: dict[str, object] | None = None, *, error: str | None = None) -> None:
        sink = self._sink or self._session.audit
        try:
            payload = None if data is None else {key: _scalar(value) for key, value in data.items()}
            sink.emit(AuditEvent.now(ev, self._session.backend, run=self.run_id, tx=self.tx_id, intent=self.intent,
                                     data=payload, error=error))
        except Exception as exc:  # noqa: BLE001 - auditing must never block cleanup or the lock release
            self.audit_failures.append(f"{ev}: {type(exc).__name__}: {exc}")

    def mark(self, label: str) -> None:
        """Audit checkpoint ``label`` (event ``checkpoint``)."""
        self._emit("checkpoint", {"label": label})

    @contextmanager
    def _bind(self, transport: AuditingTransport) -> Iterator[None]:
        previous = transport.sink
        if self.run is not None:
            transport.sink = self.run.audit
        self._sink = transport.sink
        try:
            with transport.bind(run=self.run_id, tx=self.tx_id, intent=self.intent):
                yield
        finally:
            transport.sink = previous

    # -- enter ------------------------------------------------------------------------------------------------------

    def __enter__(self) -> Self:
        if self._used:
            raise RuntimeError("a Transaction can be entered only once")
        self._used = True
        session = self._session
        if self.mode == "transaction" and self.envelope is not None:
            record = session.fault_latch.get()
            if record is not None:
                raise FaultLatched(record)
        transport = session.transport
        self._transport = transport
        holder = LockHolder(pid=os.getpid(), host=host_name(), adapter=session.adapter, plan_id=self.plan_id,
                            since=datetime.now(UTC))
        stack = ExitStack()
        stack.enter_context(session.lock.acquire(holder, timeout_s=self.lock_timeout_s))
        self._stack = stack
        try:
            stack.enter_context(self._bind(transport))
            self._emit("lock_acquired", {"resource": transport.resource, "pid": holder.pid, "host": holder.host,
                                         "adapter": holder.adapter, "plan_id": holder.plan_id})
            if self.mode == "transaction" and self.envelope is not None:
                record = session.fault_latch.get()  # re-checked under the lock
                if record is not None:
                    raise FaultLatched(record)
            session._bus_begin()
            self._bus_begun = True
            hooks = state_hooks(transport)
            if hooks is not None:
                hooks.load_state()
            target: Transport = transport if self.run is None else _RawCapture(transport, self.run, self._emit)
            self.driver = B1500Driver(target, None if self.envelope is None else OutputGuard(self.envelope))
        except BaseException:
            self._release(save_state=False)
            raise
        try:
            self.previous_marker = read_inflight(session.inflight_path)
            self._write_marker(holder)
            if self.mode == "transaction":
                if self.previous_marker is not None:
                    self._recover(self.previous_marker)
                self.baseline_errors = self.driver.errors(drain=True)
                for item in self.baseline_errors:
                    self._emit("instrument_error", {"code": item.code, "message": item.message, "phase": "baseline"})
        except BaseException as exc:
            self.__exit__(type(exc), exc, exc.__traceback__)
            raise
        return self

    def _write_marker(self, holder: LockHolder) -> None:
        marker = InflightMarker(tx=self.tx_id, run=self.run_id, intent=self.intent, plan_id=self.plan_id,
                                resource=self._session.transport.resource, backend=self._session.backend,
                                pid=holder.pid, host=holder.host, adapter=holder.adapter, since=holder.since)
        atomic_write_json(self._session.inflight_path, marker.model_dump(mode="json"))
        self._marker_written = True

    def _recover(self, previous: InflightMarker) -> None:
        outcome = run_cleanup(self.driver, always_abort=True, emit=self._emit)
        report = outcome.report
        self._emit("recovery_cleanup", {"previous_tx": previous.tx, "previous_run": previous.run,
                                        "previous_pid": previous.pid, "previous_intent": previous.intent,
                                        "verified": report.verified})
        if report.verified == "unverified":
            report = self._latch(report, f"inflight recovery unverified (stale transaction {previous.tx})")
            self.recovery = report
            self.cleanup = report
            self._cleanup_done = True
            self._notify_recovery(previous, report)
            raise CleanupUnverified(report, "inflight recovery could not verify the safe state; fault latched")
        self.recovery = report
        self._notify_recovery(previous, report)
        if outcome.deferred is not None:
            raise outcome.deferred

    def _notify_recovery(self, previous: InflightMarker, report: CleanupReport) -> None:
        """Hand a recovery to ``Session.on_recovery`` (the executor finalizes the orphaned run); never raises."""
        hook = self._session.on_recovery
        if hook is None or previous.run is None:
            return
        try:
            hook(previous, report)
        except Exception as exc:  # noqa: BLE001 - archiving an orphan must never stop a recovery
            self._emit("checkpoint", {"label": "orphan_finalize_failed", "previous_run": previous.run},
                       error=f"{type(exc).__name__}: {exc}")

    def _latch(self, report: CleanupReport, reason: str) -> CleanupReport:
        report = report.model_copy(update={"latched_fault": True})
        self._emit("cleanup_unverified", {"outputs": str(report.outputs_after), "fault_latched": True})
        try:
            self._session.fault_latch.set(reason, self.run_id)
        except Exception as exc:  # noqa: BLE001 - surfaced below without replacing the original exception
            self.latch_error = exc
            self._emit("checkpoint", {"label": "fault_latch_write_failed"}, error=f"{type(exc).__name__}: {exc}")
        return report

    # -- body helpers -----------------------------------------------------------------------------------------------

    def checkpoint(self, done: int, total: int, phase: str = "", rows: RowsSource = None) -> None:
        """A segment of the run ended (``done`` of ``total`` checkpoint units, e.g. steps of a stepped sweep): audit
        it and, with a ``RunControl``, record progress and the segment's ``rows`` (asynchronous runs), then raise
        ``RunCancelled`` when an abort was requested. ``rows`` may be a callable (built only when recorded)."""
        self._emit("checkpoint", {"label": "progress", "done": done, "total": total, "phase": phase})
        if self.control is not None:
            self._save_state_now()
            self.control.checkpoint(done, total, phase, rows, warn=self._warn)

    def _save_state_now(self) -> None:
        """Persist the simulator state mid-run (throttled; no-op on hardware) so that other processes see the outputs
        a killed run leaves on until the in-flight recovery (blueprint v2 2.6 residual); never raises."""
        hooks = state_hooks(self._transport) if self._transport is not None else None
        if hooks is None:
            return
        now = time.monotonic()
        if self._state_saved_at is not None and now - self._state_saved_at < STATE_SAVE_INTERVAL_S:
            return
        self._state_saved_at = now
        try:
            hooks.save_state()
        except Exception as exc:  # noqa: BLE001 - recorded; the run goes on
            self._emit("checkpoint", {"label": "save_state_failed"}, error=f"{type(exc).__name__}: {exc}")

    def check_abort(self) -> None:
        """Raise ``RunCancelled`` when an abort was requested (readback loops call this at least once a second)."""
        if self.control is not None:
            self.control.check_abort()

    def lop_positive_control(self, channels: Sequence[int]) -> PositiveControl | None:
        """The ``LOP?`` positive control (module docstring): call right after ``CN`` of ``channels`` (SMU or MFCMU
        channels; Table 4-26 has no code for SPGU/WGFMU slots, ATV-23) and before any source level. Returns ``None``
        on the simulator (no I/O) and the first result when called again in the same transaction.

        Raises:
            PositiveControlFailed: If a slot of ``channels`` reads ``00`` (output switch apparently off).
        """
        if self.positive_control is not None:
            return self.positive_control
        if sim_instrument(self.driver.transport) is not None or not channels:
            return None
        states = self.driver.output_state()
        slots = sorted({channel_slot(int(ch)) for ch in channels})
        codes = {slot: states[slot].state if slot in states else "missing" for slot in slots}
        off = [slot for slot in slots if slot not in states or not states[slot].output_on]
        listed = ", ".join(str(ch) for ch in channels)
        detail = (f"{_codes_text(codes)} with the output switches of channels {listed} on" if not off else
                  f"slot(s) {', '.join(str(slot) for slot in off)} read 00 although the run had switched on the "
                  f"output switches of channels {listed} ({_codes_text(codes)})")
        control = PositiveControl(channels=[int(ch) for ch in channels], codes=codes, ok=not off, detail=detail)
        self.positive_control = control
        self._emit("checkpoint", {"label": "lop_positive_control", "ok": control.ok, "detail": detail},
                   error=None if control.ok else f"PositiveControlFailed: {detail}")
        if not control.ok:
            raise PositiveControlFailed(control)
        return control

    def _warn(self, what: str, exc: BaseException) -> None:
        self._emit("checkpoint", {"label": what}, error=f"{type(exc).__name__}: {exc}")

    def suspend_auto_calibration(self, before: bool | None) -> None:
        """R-CAL-02 (asynchronous runs): send ``CM 0`` now and restore ``before`` (the state read before the run;
        ``None`` = unknown, left off) in the cleanup, after the outputs are verified off."""
        self.driver.set_auto_calibration(False)
        self.auto_calibration_before = before
        self._auto_calibration_suspended = True
        state = "unknown" if before is None else ("on" if before else "off")
        self._emit("checkpoint", {"label": "auto_calibration_off", "before": state})

    def _restore_auto_calibration(self, report: CleanupReport) -> CleanupReport:
        """The ``restore`` step: put the auto-calibration switch back as it was before the run (only after a verified
        cleanup; an unverified one leaves it off, the safer state while a human investigates)."""
        before = self.auto_calibration_before
        attempt = max((s.attempt for s in report.steps), default=1)
        error: str | None = None
        if report.verified == "unverified":
            ok, detail = False, "skipped: cleanup unverified; auto-calibration stays off (CM 0)"
        elif before is None:
            ok, detail = True, "auto-calibration state before the run unknown; left off (CM 0, initial setting)"
        elif not before:
            ok, detail = True, "auto-calibration stays off (it was off before the run)"
        else:
            command = flex.cm(1)
            try:
                self.driver.set_auto_calibration(True)
                ok, detail = True, f"{command}: auto-calibration restored to on"
            except Exception as exc:  # noqa: BLE001 - recorded; the outputs are already verified off
                ok, detail = False, f"{command} failed ({type(exc).__name__}: {exc}); auto-calibration stays off"
                error = detail
        step = CleanupStep(step="restore", ok=ok, attempt=attempt, detail=detail[:_DETAIL_LIMIT])
        self._emit("cleanup_step", {"step": "restore", "ok": ok, "attempt": attempt, "detail": step.detail},
                   error=error)
        return report.model_copy(update={"steps": [*report.steps, step]})

    def snapshot(self) -> LiveState:
        """Read-only live state under this transaction's lock (for pre-execute rules); its ``errors`` start with
        the baseline drain of ``__enter__``."""
        live = read_live_state(self.driver, backend=self._session.backend, resource=self._session.transport.resource,
                               earlier_errors=self.baseline_errors)
        self._session.last_live = live
        return live

    # -- exit -------------------------------------------------------------------------------------------------------

    def _note_exception(self, exc: BaseException) -> None:
        text = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, EnvelopeViolation):
            self._emit("envelope_violation", {"reason": exc.reason, "channel": exc.channel, "quantity": exc.quantity,
                                              "level": exc.level, "compliance": exc.compliance, "limit": exc.limit},
                       error=text)
        else:
            self._emit("checkpoint", {"label": "exception", "type": type(exc).__name__}, error=text)

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        deferred: BaseException | None = None
        try:
            if exc is not None:
                self._note_exception(exc)
            if not self._cleanup_done:
                self._cleanup_done = True
                outcome = run_cleanup(self.driver, always_abort=self._always_abort, emit=self._emit,
                                      positive=self.positive_control)
                deferred = outcome.deferred
                report = outcome.report
                if report.verified == "unverified":
                    reason = (f"safe shutdown unverified ({self.intent})" if self.mode == "shutdown"
                              else f"cleanup unverified after '{self.intent}' (transaction {self.tx_id})")
                    if self.positive_control is not None and not self.positive_control.ok:
                        reason += f"; LOP? positive control failed: {self.positive_control.detail} (v1 ATV-1)"
                    report = self._latch(report, reason)
                else:
                    self._emit("cleanup_verified", {"method": report.verified, "errors": len(report.errors)})
                if self._auto_calibration_suspended:
                    report = self._restore_auto_calibration(report)
                self.cleanup = report
                if self.mode == "shutdown" and self.previous_marker is not None:
                    self._emit("recovery_cleanup", {"previous_tx": self.previous_marker.tx,
                                                    "previous_run": self.previous_marker.run,
                                                    "previous_pid": self.previous_marker.pid,
                                                    "previous_intent": self.previous_marker.intent,
                                                    "verified": report.verified})
                    self._notify_recovery(self.previous_marker, report)
        finally:
            self._release(save_state=True)
        if self.latch_error is not None:
            if exc is None:
                raise self.latch_error
            exc.add_note(f"cleanup unverified and the fault latch could not be written: {self.latch_error}")
        if exc is None and self.mode == "transaction":
            if deferred is not None:
                raise deferred
            if self.cleanup is not None and self.cleanup.latched_fault:
                raise CleanupUnverified(self.cleanup)
        elif exc is None and deferred is not None:
            raise deferred
        return False

    def _release(self, *, save_state: bool) -> None:
        """Step 8: save the simulator state, remove the inflight marker, unlock and close the bus, release the lock
        (each step attempted even when an earlier one fails; the bus events still go to this transaction's sink)."""
        stack, self._stack = self._stack, None
        if stack is None:
            return
        try:
            if save_state and self._transport is not None:
                hooks = state_hooks(self._transport)
                if hooks is not None:
                    try:
                        hooks.save_state()
                    except Exception as exc:  # noqa: BLE001 - recorded; the lock must still be released
                        self._emit("checkpoint", {"label": "save_state_failed"}, error=f"{type(exc).__name__}: {exc}")
            if self._marker_written:
                try:
                    remove_file(self._session.inflight_path)
                    self._marker_written = False
                except OSError as exc:
                    self._emit("checkpoint", {"label": "inflight_remove_failed"}, error=str(exc))
            if self._bus_begun:
                self._bus_begun = False
                self._session._bus_end()
            self._emit("lock_released", {"resource": self._session.transport.resource})
        finally:
            stack.close()
