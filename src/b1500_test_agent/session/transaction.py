"""``Transaction``: one locked, audited instrument transaction with guaranteed cleanup (blueprint 2.4, 2.7, 3).

``__enter__``: fault-latch check (a sourcing transaction refuses with ``fault_latched``, zero I/O), instrument lock,
bus open + exclusive lock (blueprint v2 2.4: per transaction; ``BusLocked`` when another client holds the bus, zero
I/O, marker untouched), simulator state load, ``<state_dir>/inflight.json``; if a previous marker is still there its
transaction never finished (crash), so a recovery cleanup runs first (``AB``, ``DZ``, ``CL``, verify; audit
``recovery_cleanup``); then a baseline ``ERRX?`` drain. The body uses ``tx.driver``, guarded by an ``OutputGuard``
of the plan's envelope (no envelope: no guard, so every source operation refuses).

``__exit__`` runs for ANY exit, ``BaseException`` and ``EnvelopeViolation`` included:
1 ``AB`` if ``XE`` was issued and its read did not complete (sent alone; on timeout device clear, then ``AB``)
1b (v2 step 2, on instruments with an HV-SPGU, WP9.1) ``SPST?`` and ``SPP`` if an SPGU output is active
1c (v2 step 3, WP10.3: after a WGFMU phase whose safe state is unconfirmed; in ``safe_shutdown`` and recovery on a
mainframe with a WGFMU when the library is available) WGFMU ``abort``, ``initialize``, every channel disconnected,
library session closed, FLEX link locked again (``session/wgfmu_phase.py``)
2 ``DZ`` (v2 step 4: first ``DCV ch,0`` and ``ACV ch,0`` on every MFCMU the transaction drove whose ``LOP?`` code
still shows its output switch on, WP8.1) 2b ``routes`` (v2 step 5, WP9.2; on stations that declare switches): every
declared 16440A selector, SCUU and ASU back to its ``rest`` state (``session/routes.py``) 3 ``CL`` 4 ``ERRX?`` drain
5 verify outputs off (``LOP?`` plus ``SPST?`` = 0 with an SPGU on hardware, simulator state on sim, which includes
the MFCMU DC bias and AC level and the SPGU output; on hardware a failed ``LOP?`` positive control makes the
verification fail whatever ``LOP?`` reads) and every declared switch output at rest (``ERSSP?`` per declared port,
``*LRN? 81``/``62``; v2 step 8, ``CleanupReport.switches_after``)
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

Routes (blueprint v2 2.6, WP9.2): the ``OutputGuard`` knows the station's switches (their ``rest`` states may always
be restored); kinds switch with ``apply_routes(routes, phase=...)`` (one phase of the plan's ``routes_by_phase``:
guarded, ``ERMOD 1`` first, settle wait, read-back verified, audited as checkpoint ``routes``); ``snapshot`` fills
``LiveState.switch_states`` for the pre-execute rule R-ROUTE-01 (``ERMOD 1`` first when the station declares a
selector).

WGFMU (blueprint v2 0 #7, 2.6; WP10.3): ``with tx.wgfmu_phase() as wg:`` releases the FLEX exclusive lock, opens and
initializes the library session and yields the guarded ``WgfmuDriver``; its exit always runs step 3 and relocks
(``session/wgfmu_phase.py``). ``snapshot(wgfmu=True)`` reads the library's channel ids and the RSU states.

Runs (blueprint v2 2.6): kinds call ``checkpoint(done, total, phase, rows)`` between segments and long readback
loops call ``check_abort()``; with a ``RunControl`` (``session/runner.py``) this records the progress of an
asynchronous run and raises ``RunCancelled`` when ``safe_shutdown`` asked (any process, abort file), which the exit
path handles like any other exception: full cleanup, verified. ``suspend_auto_calibration`` (R-CAL-02) sends
``CM 0`` and makes the cleanup restore the state read before the run (``restore`` step after the verification;
skipped when the cleanup could not verify the outputs). The in-flight marker records that state first
(``auto_calibration_before``), so when the process dies mid-run (a harness that kills the MCP server, WP7.7) the next
transaction's recovery cleanup restores it too (WP11.1; bring-up L9 ``autocal_restored`` after the kill drill). A
recovery cleanup of a stale in-flight marker is reported to ``Session.on_recovery`` (the executor finalizes the
orphaned run folder).

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
import threading
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
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.fsio import atomic_write_json, host_name, remove_file
from b1500_test_agent.models.audit import AuditEvent, AuditEventName
from b1500_test_agent.models.common import Backend, JsonScalar, StrictModel
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.routing import Route, SwitchSpec, SwitchState
from b1500_test_agent.models.run import Adapter, CleanupReport, CleanupStep, LockHolder, PositiveControl
from b1500_test_agent.models.station import (
    MODULE_TYPE_BY_MODEL,
    InstrumentError,
    LiveState,
    ModuleInventory,
    channel_slot,
)
from b1500_test_agent.session.fault import CleanupUnverified, FaultLatched, PositiveControlFailed
from b1500_test_agent.session.raw_capture import RawCapture
from b1500_test_agent.session.routes import apply_phase, cleanup_scope, read_states, restore_routes, verify_routes
from b1500_test_agent.session.wgfmu_phase import WgfmuLink, WgfmuPhase
from b1500_test_agent.transport.audit import AuditingTransport, AuditSink, hold_audit
from b1500_test_agent.transport.base import Transport, TransportTimeout, state_hooks, unwrap

if TYPE_CHECKING:
    from b1500_test_agent.session.runner import RowsSource, RunControl
    from b1500_test_agent.session.session import Session

CleanupStepName = Literal["abort", "spgu_stop", "wgfmu", "zero", "routes", "disconnect", "drain_errors", "verify",
                          "device_clear", "restore"]

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
    auto_calibration_before: Literal["on", "off", "unknown"] | None = None
    """Written by ``Transaction.suspend_auto_calibration`` before it sends ``CM 0`` (R-CAL-02): the auto-calibration
    state the recovery cleanup restores when this transaction never finishes; ``None`` = auto-calibration untouched."""


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


_TX_IDS_LOCK = threading.Lock()
_TX_IDS_ISSUED: dict[str, set[str]] = {}
"""Suffixes this process issued per second stamp, in insertion order (only the last few stamps are kept)."""
_TX_IDS_KEEP = 4


def new_tx_id(now: datetime | None = None) -> str:
    """Transaction id ``T`` + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 hex digits (the run-id shape, blueprint 0 #9).

    Unique within the process: 20 snapshots in one second drew a duplicate suffix in about 1 of 350 test runs
    (birthday bound over 65,536 suffixes), which merged two transactions in the audit (WP6.5); a suffix is redrawn
    until it is new for its second. Two processes would need a transaction in the same second with the same suffix
    (1 in 65,536)."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    with _TX_IDS_LOCK:
        issued = _TX_IDS_ISSUED.setdefault(stamp, set())
        suffix = secrets.token_hex(2)
        while suffix in issued and len(issued) < 0x10000:
            suffix = secrets.token_hex(2)
        issued.add(suffix)
        for old in list(_TX_IDS_ISSUED)[:-_TX_IDS_KEEP]:  # oldest stamps first (insertion order)
            if old != stamp:
                del _TX_IDS_ISSUED[old]
    return f"T{stamp}-{suffix}"


# -- Live state -------------------------------------------------------------------------------------------------------


def read_live_state(driver: B1500Driver, *, backend: Backend, resource: str,
                    earlier_errors: list[InstrumentError] | None = None, switches: Sequence[SwitchSpec] = (),
                    set_selector_control: bool = False) -> LiveState:
    """Snapshot through ``driver``: ``*IDN?``, ``UNT?``, ``ERRX?`` drain, ``*STB?``, ``LOP?`` and, when the station
    declares switches, their states (``switch_states``: the outputs that could be read, ``session/routes.py``).

    ``earlier_errors`` (e.g. a transaction's baseline drain) are listed before the newly drained ones. Read-only
    unless ``set_selector_control`` (a transaction's pre-execute snapshot), which sends ``ERMOD 1`` first when a
    declared selector's control mode is off, since ``ERSSP?`` is defined only with it (R-ROUTE-01 pre).
    """
    identity = driver.identify()
    inventory = driver.modules()
    errors = [*(earlier_errors or []), *driver.errors(drain=True)]
    status = driver.status_byte()
    outputs = driver.output_state()
    states: dict[str, SwitchState] | None = None
    scope = cleanup_scope(switches)
    if scope:
        try:
            states = read_states(driver, scope, set_control=set_selector_control)
        except DriverError:
            states = None  # not read: R-ROUTE-01 blocks plans that route, other plans are unaffected
    return LiveState(backend=backend, resource=resource, taken_at=datetime.now(UTC), identity=identity,
                     inventory=inventory, errors=errors, status_byte=status, outputs=outputs, switch_states=states)


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
    if getattr(state, "mode", "V") == "I":
        return f"{on} {state.current:g} A"
    return on if state.voltage == 0 else f"{on} {state.voltage:g} V"


SPGU_MODULE_TYPE = "HVSPGU"
"""Module type whose installation adds cleanup step 2 (``SPP`` when ``SPST?`` reads 1; blueprint v2 2.6)."""


def spgu_installed(inventory: ModuleInventory | None) -> bool | None:
    """Whether ``inventory`` (an ``UNT?`` reading) lists an HV-SPGU; ``None`` when no inventory is known."""
    if inventory is None:
        return None
    return any(MODULE_TYPE_BY_MODEL.get(m.model) == SPGU_MODULE_TYPE for m in inventory.modules)


@dataclass
class CleanupOutcome:
    """A cleanup report plus a ``KeyboardInterrupt``/``SystemExit`` caught while cleaning up (re-raised by the
    caller once everything is released)."""

    report: CleanupReport
    deferred: BaseException | None


def run_cleanup(driver: B1500Driver, *, always_abort: bool, emit: Emit,
                positive: PositiveControl | None = None, spgu: bool | None = None,
                switches: Sequence[SwitchSpec] = (), wgfmu: WgfmuLink | None = None,
                shutdown: bool = False) -> CleanupOutcome:
    """``AB`` (when ``always_abort`` or a measurement is pending) -> SPGU stop -> MFCMU ``DCV 0``/``ACV 0`` (channels
    the driver drove) + ``DZ`` -> switches to rest -> ``CL`` -> ``ERRX?`` drain -> verify; after any failed step a
    device clear and one retry of the whole sequence (blueprint 2.4 steps 1-6, v2 2.6 steps 1, 2, 4-10).

    ``switches``: the station's declared switches; those in ``routes.cleanup_scope`` are returned to rest (step 5,
    ``routes``) and verified (step 8, part of ``verify``; ``CleanupReport.switches_after``).

    ``spgu``: whether an HV-SPGU is installed (``None`` = unknown: ``UNT?`` is read once after the abort step, and an
    unreadable inventory counts as installed). With an SPGU the ``spgu_stop`` step reads ``SPST?`` and sends ``SPP``
    when an output is active (``SPP`` also when ``SPST?`` cannot be read), and the hardware verification also needs
    ``SPST?`` = 0; an SPGU that will not stop (``spgu_no_stop``) is stopped by the retry's ``SPP`` or latches the
    fault.

    ``wgfmu``: the transaction's WGFMU link; step 3 (``wgfmu``) runs when it is ``needed`` (a phase left the safe
    state unconfirmed, or ``shutdown``, i.e. safe shutdown and recovery, on a mainframe with a WGFMU and an available
    library); the verification then also needs the FLEX link relocked and, on hardware, step 3 complete.

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
    switches_after: dict[str, str] = {}
    deferred: list[BaseException] = []
    scope = cleanup_scope(switches)

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

    def spgu_stop() -> tuple[bool, str]:
        try:
            active = driver.pulse_output_active()
        except Exception as exc:  # noqa: BLE001 - state unknown: stop anyway (SPP is harmless when nothing runs)
            driver.stop_pulses()
            return False, f"{flex.SPST_Q} unreadable ({type(exc).__name__}: {exc}); {flex.SPP} sent anyway"
        if not active:
            return True, f"{flex.SPST_Q} 0: no SPGU output active"
        driver.stop_pulses()
        return True, f"{flex.SPST_Q} 1: {flex.SPP} sent"

    def abort() -> tuple[bool, str]:
        try:
            driver.abort()
        except TransportTimeout as exc:
            driver.device_clear()
            driver.abort()
            return True, f"abort timed out ({exc}); device clear, then abort again"
        return True, "sent alone"

    def zero() -> tuple[bool, str]:
        # v2 step 4 (blueprint 2.6): the MFCMUs this driver drove get DCV 0 and ACV 0 (AC off before the relays
        # open), then DZ zeros every channel. DZ is sent even when the MFCMU zeroing failed; the step then fails.
        cmu_error: Exception | None = None
        zeroed: list[int] = []
        try:
            zeroed = driver.zero_cmu()
        except Exception as exc:  # noqa: BLE001 - recorded after DZ; the retry repeats both
            cmu_error = exc
        driver.zero()
        if cmu_error is not None:
            raise cmu_error
        cmu = f"; MFCMU {', '.join(str(ch) for ch in zeroed)} DC 0 V, AC 0 V" if zeroed else ""
        return True, "all channels" + cmu

    def routes() -> tuple[bool, str]:
        return restore_routes(driver, scope)

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
        ok, detail = verify_outputs()
        switches_after.clear()
        if wgfmu is not None:
            switches_after.update(wgfmu.rsu_states())  # what the library accepted (FLEX never reads an RSU)
        if wgfmu is not None and wgfmu_ran:
            w_ok, w_detail = wgfmu.verification(sim=sim is not None)
            ok, detail = ok and w_ok, f"{detail}; {w_detail}"
        if not scope:
            return ok, detail
        routed_ok, routed_detail, after = verify_routes(driver, scope)
        switches_after.update(after)
        return ok and routed_ok, f"{detail}; {routed_detail}"

    def verify_outputs() -> tuple[bool, str]:
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
        if spgu and driver.pulse_output_active():
            return False, f"SPGU output still active ({flex.SPST_Q} 1)"
        if positive is not None and not positive.ok:
            return False, (f"all slots report 00, but the LOP? positive control failed ({positive.detail}): 00 does "
                           "not prove the outputs off")
        evidence = "" if positive is None else f"; positive control with the outputs on: {positive.detail}"
        spst = f"; {flex.SPST_Q} 0" if spgu else ""
        return all_outputs_off(states), "all slots report 00" + spst + evidence

    def clear() -> tuple[bool, str]:
        driver.device_clear()
        return True, "before the retry"

    verified = False
    wgfmu_ran = False
    for attempt in (1, 2):
        if attempt == 2:
            step("device_clear", attempt, clear)
        results: dict[str, bool] = {}
        if always_abort or driver.measurement_pending:
            results["abort"] = step("abort", attempt, abort)
        if spgu is None:
            spgu = _read_spgu_installed(driver, deferred)
        if spgu:
            results["spgu_stop"] = step("spgu_stop", attempt, spgu_stop)
        if wgfmu is not None and wgfmu.needed(driver.last_inventory, all_channels=shutdown):
            wgfmu_ran = True
            results["wgfmu"] = step("wgfmu", attempt, wgfmu.cleanup_step)
        results["zero"] = step("zero", attempt, zero)
        if scope:
            results["routes"] = step("routes", attempt, routes)
        results["disconnect"] = step("disconnect", attempt, disconnect)
        results["drain_errors"] = step("drain_errors", attempt, drain)
        results["verify"] = step("verify", attempt, verify)
        verified = results["zero"] and results["disconnect"] and results["verify"]
        if all(results.values()):
            break
    report = CleanupReport(steps=steps, verified=method if verified else "unverified", outputs_after=dict(outputs),
                           latched_fault=False, errors=errors, positive_control=positive,
                           switches_after=dict(switches_after))
    return CleanupOutcome(report=report, deferred=deferred[0] if deferred else None)


def _read_spgu_installed(driver: B1500Driver, deferred: list[BaseException]) -> bool:
    """``UNT?`` once (cleanup without a known inventory); an unreadable answer counts as an installed SPGU, and an
    interrupt is deferred like one inside a cleanup step."""
    try:
        return bool(spgu_installed(driver.modules()))
    except BaseException as exc:  # noqa: BLE001 - the SPGU step then runs and reports what fails
        if not isinstance(exc, Exception):
            deferred.append(exc)
        return True


def _codes_text(codes: dict[int, str]) -> str:
    """``slot 3 01, slot 4 01`` (``LOP?`` codes by slot) for audit details and messages."""
    return ", ".join(f"slot {slot} {code}" for slot, code in sorted(codes.items()))


# -- Transaction ------------------------------------------------------------------------------------------------------


def _on_off(state: bool | None) -> Literal["on", "off", "unknown"]:
    """An auto-calibration state as the marker and the audit spell it."""
    return "unknown" if state is None else ("on" if state else "off")


def _scalar(value: object) -> JsonScalar:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value if value is None or isinstance(value, bool | int | float | str) else str(value)


class Transaction:
    """__enter__: fault-latch check, lock, write <state_dir>/inflight.json, recover if a previous inflight marker
    exists (AB, DZ, CL, verify), baseline ERRX drain. Body uses tx.driver (guarded).
    __exit__ runs for ANY exit incl. BaseException/EnvelopeViolation: 1 AB if XE issued and not complete
    (sent alone; on timeout device_clear then AB) 2 DZ (2b declared switches to rest, WP9.2) 3 CL 4 ERRX drain
    5 verify outputs off (LOP? on hw, sim_state on sim) and switches at rest 6 on any step error: device_clear, retry
    once 7 still unverified → FaultLatch.set +
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
        self._holder: LockHolder | None = None
        self._pending_restore: Literal["on", "off", "unknown"] | None = None
        """A crashed transaction's auto-calibration state not restored yet: carried in this transaction's marker until
        the recovery restored it, so a crash during the recovery itself does not lose it."""
        self._state_saved_at: float | None = None
        self._wgfmu: WgfmuLink | None = None

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
            # one open of the audit file for the whole transaction (each event still flushed at once): WP6.5
            with hold_audit(self._sink), transport.bind(run=self.run_id, tx=self.tx_id, intent=self.intent):
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
            target: Transport = transport if self.run is None else RawCapture(transport, self.run, self._emit)
            guard = None if self.envelope is None else OutputGuard(self.envelope, switches=session.switches)
            self.driver = B1500Driver(target, guard)
        except BaseException:
            self._release(save_state=False)
            raise
        try:
            self.previous_marker = read_inflight(session.inflight_path)
            if self.previous_marker is not None:
                self._pending_restore = self.previous_marker.auto_calibration_before
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
        self._holder = holder
        restore = _on_off(self.auto_calibration_before) if self._auto_calibration_suspended else self._pending_restore
        marker = InflightMarker(tx=self.tx_id, run=self.run_id, intent=self.intent, plan_id=self.plan_id,
                                resource=self._session.transport.resource, backend=self._session.backend,
                                pid=holder.pid, host=holder.host, adapter=holder.adapter, since=holder.since,
                                auto_calibration_before=restore)
        atomic_write_json(self._session.inflight_path, marker.model_dump(mode="json"))
        self._marker_written = True

    def _spgu_hint(self) -> bool | None:
        """Whether an HV-SPGU is installed, from the inventory this transaction's driver or the session's last
        snapshot read (``None``: unknown, the cleanup reads ``UNT?``)."""
        known = spgu_installed(self.driver.last_inventory)
        if known is not None:
            return known
        live = self._session.last_live
        return spgu_installed(live.inventory if live is not None else None)

    def _recover(self, previous: InflightMarker) -> None:
        outcome = run_cleanup(self.driver, always_abort=True, emit=self._emit, spgu=self._spgu_hint(),
                              switches=self._session.switches, wgfmu=self.wgfmu_link, shutdown=True)
        report = outcome.report
        self._emit("recovery_cleanup", {"previous_tx": previous.tx, "previous_run": previous.run,
                                        "previous_pid": previous.pid, "previous_intent": previous.intent,
                                        "verified": report.verified})
        if report.verified == "unverified":
            report = self._latch(report, f"inflight recovery unverified (stale transaction {previous.tx})")
            report = self._restore_previous_auto_calibration(previous, report)
            self.recovery = report
            self.cleanup = report
            self._cleanup_done = True
            self._notify_recovery(previous, report)
            raise CleanupUnverified(report, "inflight recovery could not verify the safe state; fault latched")
        report = self._restore_previous_auto_calibration(previous, report)
        if self._pending_restore is not None and self._holder is not None:
            self._pending_restore = None  # restored: this transaction's own marker no longer carries it
            self._write_marker(self._holder)
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
        ``None`` = unknown, left off) in the cleanup, after the outputs are verified off. The in-flight marker records
        ``before`` first, so a recovery after a crash restores it as well (module docstring)."""
        self.auto_calibration_before = before
        self._auto_calibration_suspended = True
        if self._marker_written and self._holder is not None:
            self._write_marker(self._holder)
        self.driver.set_auto_calibration(False)
        self._emit("checkpoint", {"label": "auto_calibration_off", "before": _on_off(before)})

    def _restore_previous_auto_calibration(self, previous: InflightMarker, report: CleanupReport) -> CleanupReport:
        """The ``restore`` step of a recovery cleanup: the auto-calibration state the crashed transaction had
        suspended (its marker's ``auto_calibration_before``); nothing when it had not."""
        if previous.auto_calibration_before is None:
            return report
        before = {"on": True, "off": False}.get(previous.auto_calibration_before)
        return self._restore_auto_calibration(report, before, recovery=True)

    def _restore_auto_calibration(self, report: CleanupReport, before: bool | None = None, *,
                                  recovery: bool = False) -> CleanupReport:
        """The ``restore`` step: put the auto-calibration switch back as it was before the run (only after a verified
        cleanup; an unverified one leaves it off, the safer state while a human investigates). ``recovery``: the run
        was another (crashed) transaction's, ``before`` is from its marker."""
        if not recovery:
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
        if recovery:
            detail = f"recovery of the crashed run: {detail}"
        step = CleanupStep(step="restore", ok=ok, attempt=attempt, detail=detail[:_DETAIL_LIMIT])
        self._emit("cleanup_step", {"step": "restore", "ok": ok, "attempt": attempt, "detail": step.detail},
                   error=error)
        return report.model_copy(update={"steps": [*report.steps, step]})

    def snapshot(self, *, wgfmu: bool = False) -> LiveState:
        """Live state under this transaction's lock (for pre-execute rules); its ``errors`` start with the baseline
        drain of ``__enter__``. Queries only, except ``ERMOD 1`` when a declared selector's control mode is off
        (``switch_states`` needs ``ERSSP?``; WP9.2). On visa it carries the WGFMU library probe (``wgfmu_library``);
        ``wgfmu=True`` (a plan with WGFMU roles) also reads the library's channel ids (``wgfmu_channels``) through a
        short library session while the FLEX link's exclusive lock is released (R-WG-01 pre-execute; WP10.2), and the
        states of the declared RSUs as the library accepts their rest path (``switch_states``; WP10.3)."""
        session = self._session
        live = read_live_state(self.driver, backend=session.backend, resource=session.transport.resource,
                               earlier_errors=self.baseline_errors, switches=session.switches,
                               set_selector_control=True)
        library = session.wgfmu_library()
        update: dict[str, object] = {} if library is None else {"wgfmu_library": library}
        if wgfmu:
            read = self.wgfmu_link.read_live()
            update["wgfmu_channels"] = read.channels
            if read.rsu_states:
                update["switch_states"] = {**(live.switch_states or {}), **read.rsu_states}
        if update:
            live = live.model_copy(update=update)
        session.last_live = live
        return live

    def apply_routes(self, routes: Sequence[Route], *, phase: str) -> dict[str, SwitchState]:
        """Switch one phase of routes (a list of the plan's ``routes_by_phase``) through the guarded driver, wait the
        selector settle time and verify the read-back (``routes.apply_phase``); audited as checkpoint ``routes``.
        Returns the states read back. The cleanup returns every declared switch to rest whatever happens.

        Raises:
            EnvelopeViolation: If a route is neither one of the plan's nor a rest state (nothing of the phase sent).
            RouteNotVerified: If an output does not read the state just set.
            ValueError: If a route names an undeclared switch or output, an RSU, or one output twice.
        """
        listed = ", ".join(str(r) for r in routes)
        try:
            states = apply_phase(self.driver, routes, {s.id: s for s in self._session.switches})
        except Exception as exc:
            self._emit("checkpoint", {"label": "routes", "phase": phase, "routes": listed},
                       error=f"{type(exc).__name__}: {exc}")
            raise
        self._emit("checkpoint", {"label": "routes", "phase": phase, "routes": listed,
                                  "readback": ", ".join(f"{t} {s}" for t, s in sorted(states.items()))})
        return states

    @property
    def wgfmu_link(self) -> WgfmuLink:
        """The WGFMU side of this transaction (library session, FLEX release, safe state; created on first use)."""
        if self._wgfmu is None:
            self._wgfmu = WgfmuLink(self)
        return self._wgfmu

    @property
    def wgfmu_phases(self) -> list[str]:
        """How the FLEX link made room in each WGFMU phase of this transaction (``unlocked``, ``closed``, ``unlocked
        (flex_io)``); the run manifest lists them (ATV-14)."""
        return [] if self._wgfmu is None else list(self._wgfmu.phases)

    def wgfmu_phase(self, *, flex_io: bool = False) -> WgfmuPhase:
        """``with tx.wgfmu_phase() as wg:`` (blueprint v2 2.6): FLEX lock released (or the link closed with
        ``settings.wgfmu.flex_during_phase: close`` unless ``flex_io``, a kind that sends FLEX commands inside the
        phase), library session opened and initialized, the guarded ``WgfmuDriver`` yielded; the exit always runs
        cleanup step 3 and relocks (``session/wgfmu_phase.py``).

        Raises:
            WgfmuError: If no library is available (nothing was released) or the library fails on entry.
            WgfmuSafeStateFailed: At the exit of a successful body when the safe state could not be confirmed.
        """
        how = self._session.settings.wgfmu.flex_during_phase
        return WgfmuPhase(self.wgfmu_link, self.driver.guard, how=how, flex_io=flex_io)

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
                                      positive=self.positive_control, spgu=self._spgu_hint(),
                                      switches=self._session.switches, wgfmu=self.wgfmu_link,
                                      shutdown=self.mode == "shutdown")
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
                if self.mode == "shutdown" and self.previous_marker is not None:
                    report = self._restore_previous_auto_calibration(self.previous_marker, report)
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
