"""``safe_shutdown`` of the service facade and the human-only CLI operations (blueprint 5.1; v2 2.6, 2.9).

``safe_shutdown`` first cancels the run holding the instrument, whichever process runs it: it writes the abort file
(``<state_dir>/abort.json``, audited ``abort_requested``), waits for the run to stop at its next checkpoint and finish
its verified cleanup (at most one segment, ``policy.run_limits.segment_max_s``, plus ``CANCEL_MARGIN_S``), then runs
the full safe shutdown as in v1 (``AB`` → ``DZ`` → ``CL`` → ``ERRX?`` → verify under the instrument lock; never gated,
also with a latched fault). It withdraws its abort request when no run took it, unless a run is still running (then
the request stays for it). The result names the cancelled run and its outcome.

``B1500Admin`` holds the human-only CLI operations (``b1500 fault clear``, ``b1500 lock status``); they are never
MCP tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from b1500_test_agent.analysis.dataset import MANIFEST_FILE, load_manifest
from b1500_test_agent.archive.store import RunStore
from b1500_test_agent.catalog.running import CANCEL_MARGIN_S, ActiveRun
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.errors import B1500Error, InvalidConfigError
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.results import FaultClearResult, LockStatus, ShutdownResult
from b1500_test_agent.service.common import REASON_MAX, clip
from b1500_test_agent.session import FaultClearRefused, Session

if TYPE_CHECKING:
    from b1500_test_agent.service.core import B1500Service


def clean_reason(reason: str) -> str:
    """One line of at most ``REASON_MAX`` characters (``no reason given`` when empty)."""
    text = " ".join(str(reason or "").split())
    return clip(text, REASON_MAX) or "no reason given"


def _cancelled_outcome(bundle: ConfigBundle, run_id: str) -> str | None:
    """``<outcome>, cleanup <verified>`` of a run that has finalized, else ``None``."""
    try:
        folder = RunStore(bundle.paths.runs_dir).open(run_id, unfinished=True)
        if not (folder.path / MANIFEST_FILE).is_file():
            return None
        manifest = load_manifest(folder.path)
    except B1500Error:
        return None
    cleanup = manifest.cleanup.verified if manifest.cleanup is not None else "not run"
    return f"{manifest.outcome}, cleanup {cleanup}"


def safe_shutdown(svc: B1500Service, bundle: ConfigBundle, reason: str, *, fallback: bool = False) -> ShutdownResult:
    """Cancel the running run (any process), then the full verified safe shutdown (see the module docstring)."""
    executor = svc.executor
    session = executor.session(bundle)
    active: ActiveRun | None = executor.active_run(bundle)
    request = None
    if active is not None or session.lock.is_held():
        request = session.abort_file.request(reason, adapter=svc.adapter,
                                             run_id=active.run_id if active is not None else None)
        session.audit.emit(AuditEvent.now("abort_requested", bundle.backend,
                                          run=active.run_id if active is not None else None, data={
            "request": request.id, "reason": request.reason, "by": svc.adapter,
            "target": active.run_id if active is not None else None}))
    cancel_wait = bundle.policy.run_limits.segment_max_s + CANCEL_MARGIN_S
    if active is not None and active.job is not None:
        active.job.wait(cancel_wait)
    lock_wait = svc.lock_timeout_s + (cancel_wait if request is not None else 0.0)
    try:
        result = shutdown_with(svc, session, bundle.backend, reason, lock_timeout_s=lock_wait)
    finally:
        if request is not None and executor.active_run(bundle) is None:
            session.abort_file.withdraw(request.id)
    if active is None:
        return result
    outcome = _cancelled_outcome(bundle, active.run_id)
    first = (f"cancelled {active.describe()} ({outcome})" if outcome is not None
             else f"asked {active.describe()} to stop")
    return result.model_copy(update={"message": clip(f"{first}; {result.message}"), "cancelled_run": active.run_id,
                                     "next_steps": [*result.next_steps,
                                                    (f"get_run({active.run_id}, include=[progress, data]) shows the "
                                                    "partial data of the cancelled run")]})


def shutdown_invalid(svc: B1500Service, exc: InvalidConfigError, reason: str) -> ShutdownResult:
    """``safe_shutdown`` while the configuration is invalid: with this process's last valid configuration."""
    bundle = svc._last_bundle
    if bundle is None:
        raise exc
    result = safe_shutdown(svc, bundle, reason)
    return result.model_copy(update={"message": clip(
        result.message + " (the configuration is now invalid; the shutdown used this process's last valid "
                         "configuration)")})


def shutdown_with(svc: B1500Service, session: Session, backend: Backend, reason: str, *,
                  lock_timeout_s: float | None = None) -> ShutdownResult:
    """The v1 safe shutdown under the instrument lock and its result."""
    timeout = svc.lock_timeout_s if lock_timeout_s is None else lock_timeout_s
    report = session.safe_shutdown(reason=reason, lock_timeout_s=timeout)
    fault = session.fault_latch.get()
    if report.verified == "unverified":
        return ShutdownResult(ok=False, status="fault", error_code="cleanup_unverified", **svc._envelope(backend),
                              cleanup=report, fault=fault,
                              message="safe shutdown could NOT verify that all outputs are off; the fault latch is set",
                              next_steps=[("do not measure; load skill b1500-debug; a human checks the station and "
                                          "runs b1500 fault clear")])
    message = f"all outputs zeroed and disconnected (verified: {report.verified})"
    next_steps: list[str] = []
    if fault is not None:
        message += f"; the fault latch is still set ({fault.reason}): only a human clears it (b1500 fault clear)"
        next_steps = ["load skill b1500-debug and report the fault to the human"]
    return ShutdownResult(ok=True, status="ok", **svc._envelope(backend), cleanup=report, fault=fault,
                          message=clip(message), next_steps=next_steps)


class B1500Admin:
    """Human-only operations of the CLI (``b1500 fault clear``, ``b1500 lock status``); never MCP tools.

    They share the service's configuration, session, error mapping and ``tool_call`` audit (tool names
    ``fault_clear`` and ``lock_status``).
    """

    def __init__(self, service: B1500Service) -> None:
        self.service = service

    def fault_clear(self, by: str) -> FaultClearResult:
        """Run a safe shutdown and clear the fault latch only when it verified the safe state (outputs off at 0 V,
        ``ERRX?`` read and empty); otherwise refuse with the reasons (``cleanup_unverified``)."""
        who = " ".join(str(by or "").split())[:80] or "unknown"
        return self.service._call("fault_clear", {"by": who}, FaultClearResult,
                                      lambda bundle: self._fault_clear(bundle, who))

    def _fault_clear(self, bundle: ConfigBundle, by: str) -> FaultClearResult:
        service = self.service
        session = service.executor.session(bundle)
        envelope = service._envelope(bundle.backend)
        record = session.fault_latch.get()
        if record is None:
            return FaultClearResult(ok=True, status="ok", **envelope, message="no fault is latched; nothing to clear")
        report = session.safe_shutdown(reason=f"fault clear by {by}", lock_timeout_s=service.lock_timeout_s)
        try:
            session.fault_latch.clear(by=by, shutdown=report)
        except FaultClearRefused as exc:
            return FaultClearResult(ok=False, status="fault", error_code="cleanup_unverified", **envelope,
                                    message=clip(str(exc)), reasons=list(exc.reasons),
                                    fault=session.fault_latch.get(), cleanup=report,
                                    next_steps=[("fix the cause on the station (see the reasons), then run "
                                                "b1500 fault clear again")])
        return FaultClearResult(ok=True, status="ok", **envelope, cleared=True, cleanup=report, fault=None,
                                message=f"fault latch cleared by {by} after a verified safe shutdown "
                                        f"({report.verified}); it was: {clip(record.reason, 300)}")

    def lock_status(self) -> LockStatus:
        """The instrument lock holder, the inflight marker, the running run and the fault latch (file reads only,
        no I/O)."""
        return self.service._call("lock_status", {}, LockStatus, self._lock_status)

    def _lock_status(self, bundle: ConfigBundle) -> LockStatus:
        session = self.service.executor.session(bundle)
        lock = session.lock
        holder = lock.holder()
        held = lock.is_held()
        inflight = session.inflight() is not None
        fault = session.fault_latch.get()
        active = self.service.executor.active_run(bundle)
        parts = [f"lock {'held' if held else 'free'}" + (f" by pid {holder.pid} on {holder.host} ({holder.adapter})"
                                                         if holder is not None else "")]
        if active is not None:
            parts.append(f"running: {active.describe()}")
        if inflight:
            parts.append("inflight marker present" + ("" if held else " (stale: the next transaction recovers it)"))
        if fault is not None:
            parts.append(f"FAULT LATCHED: {fault.reason}")
        return LockStatus(ok=True, status="ok", **self.service._envelope(bundle.backend), resource=lock.resource,
                          held=held, holder=holder, inflight_marker=inflight, fault=fault,
                          message=clip("; ".join(parts)))
