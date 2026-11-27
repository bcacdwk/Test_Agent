"""Persistent fault latch ``<state_dir>/fault.json`` and the session's refusal errors (blueprint 2.4, 4.3 point 5).

The latch is set when a cleanup cannot verify the safe state (transaction cleanup, inflight recovery or
``safe_shutdown``). While it is set every sourcing transaction refuses with ``fault_latched``; read-only work
(snapshots) and ``safe_shutdown`` still run. Only ``FaultLatch.clear`` removes it, and only with the report of a
verified safe shutdown: verification succeeded, every output reads off/zero, the error queue was read successfully
and was empty (``b1500 fault clear``, WP1.8, is the human entry point). Because the shutdown drains the queue, a
refused clear that listed errors succeeds when repeated after the human has reviewed them.

A ``fault.json`` that cannot be read counts as a latched fault (fail safe).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.fsio import atomic_write_json, remove_file
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.common import Backend, ErrorCode
from b1500_test_agent.models.run import CleanupReport, FaultRecord, PositiveControl
from b1500_test_agent.transport.audit import AuditSink

OUTPUT_OFF_STATES: frozenset[str] = frozenset({"00", "off"})
"""``CleanupReport.outputs_after`` values meaning output off at 0 V: ``LOP?`` code ``00`` (hardware) or ``off``
(simulator state)."""


class FaultLatched(B1500Error):
    """A sourcing action was refused because the fault latch is set (result code ``fault_latched``)."""

    code: ClassVar[ErrorCode] = "fault_latched"

    def __init__(self, record: FaultRecord, message: str | None = None) -> None:
        self.record = record
        super().__init__(message or f"fault latched since {record.set_at.isoformat()}: {record.reason}")


class CleanupUnverified(B1500Error):
    """A cleanup could not verify the safe state; the fault latch is set (result code ``cleanup_unverified``)."""

    code: ClassVar[ErrorCode] = "cleanup_unverified"

    def __init__(self, report: CleanupReport, message: str | None = None) -> None:
        self.report = report
        super().__init__(message or "cleanup could not verify the safe state; the fault latch is set")


class PositiveControlFailed(B1500Error):
    """The hardware ``LOP?`` positive control failed: a slot whose output switch the run had just turned on read
    ``00`` (result code ``cleanup_unverified``, because ``LOP?`` then cannot prove the outputs off). Raised before
    any source level is applied; the transaction's cleanup stays unverified and latches the fault (v1 ATV-1)."""

    code: ClassVar[ErrorCode] = "cleanup_unverified"

    def __init__(self, control: PositiveControl) -> None:
        self.control = control
        super().__init__(f"LOP? positive control failed: {control.detail}; LOP? cannot prove that the outputs are "
                         "off on this instrument (v1 ATV-1), so the run stopped before applying any level and its "
                         "cleanup stays unverified (fault latched)")


class FaultClearRefused(B1500Error):
    """``FaultLatch.clear`` refused: the shutdown report does not prove the safe state (``reasons`` lists why)."""

    code: ClassVar[ErrorCode] = "cleanup_unverified"

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("fault clear refused: " + "; ".join(self.reasons))


def outputs_zero(outputs: Mapping[int, str]) -> bool:
    """True when ``outputs`` is non-empty and every entry reads off at 0 V (``OUTPUT_OFF_STATES``)."""
    return bool(outputs) and all(state in OUTPUT_OFF_STATES for state in outputs.values())


def clear_refusals(shutdown: CleanupReport) -> list[str]:
    """Why ``shutdown`` cannot clear the fault latch (empty when it can)."""
    reasons: list[str] = []
    if shutdown.verified == "unverified":
        reasons.append("the safe shutdown could not verify the outputs")
    if shutdown.latched_fault:
        reasons.append("the safe shutdown itself latched a fault")
    if not outputs_zero(shutdown.outputs_after):
        on = {ch: state for ch, state in shutdown.outputs_after.items() if state not in OUTPUT_OFF_STATES}
        reasons.append(f"outputs are not all off at 0 V: {on}" if on else "no output state was read back")
    if not any(step.step == "drain_errors" and step.ok for step in shutdown.steps):
        reasons.append("ERRX? could not be read")
    if shutdown.errors:
        listed = ", ".join(f"{e.code} {e.message}".strip() for e in shutdown.errors)
        reasons.append(f"ERRX? was not empty ({listed}); review the errors, then run fault clear again")
    return reasons


class FaultLatch:
    """The fault latch of one ``state_dir`` (blueprint 2.4); ``audit`` receives ``fault``/``fault_cleared``."""

    def __init__(self, state_dir: Path, *, audit: AuditSink, backend: Backend) -> None:
        self.path = Path(state_dir) / "fault.json"
        self.audit = audit
        self.backend = backend

    def get(self) -> FaultRecord | None:
        """The latched fault, or ``None``. An unreadable ``fault.json`` is reported as a latched fault."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            return FaultRecord(reason=f"fault.json unreadable: {exc}", set_at=datetime.now(UTC))
        try:
            return FaultRecord.model_validate_json(text)
        except (ValueError, ValidationError) as exc:
            first = str(exc).splitlines()[0]
            return FaultRecord(reason=f"fault.json is corrupt ({first}); treated as latched", set_at=datetime.now(UTC))

    def set(self, reason: str, run_id: str | None) -> None:
        """Latch a fault. A fault that is already latched keeps its original record (the first cause); the new
        reason is still audited."""
        reason = reason.strip() or "unspecified fault"
        existing = self.get()
        record = FaultRecord(reason=reason, run_id=run_id, set_at=datetime.now(UTC))
        if existing is None:
            atomic_write_json(self.path, record.model_dump(mode="json"))
        self.audit.emit(AuditEvent.now("fault", self.backend, run=run_id,
                                       data={"reason": reason, "already_latched": existing is not None}))

    def clear(self, *, by: str, shutdown: CleanupReport) -> None:
        """Clear the latch with the report of a safe shutdown run just before (``Session.safe_shutdown``).

        Does nothing when no fault is latched.

        Raises:
            FaultClearRefused: Unless the shutdown is verified, all outputs are off at 0 V and ``ERRX?`` was read
                and empty.
        """
        record = self.get()
        if record is None:
            return
        reasons = clear_refusals(shutdown)
        if reasons:
            raise FaultClearRefused(reasons)
        remove_file(self.path)
        self.audit.emit(AuditEvent.now("fault_cleared", self.backend, run=record.run_id, data={
            "by": by, "reason": record.reason, "set_at": record.set_at.isoformat(), "verified": shutdown.verified,
        }))
