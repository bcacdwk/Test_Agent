"""Instrument session, file lock, transaction with guaranteed cleanup, and fault latch (blueprint 2.4).

``Session`` (one per process) -> ``Transaction`` (lock, inflight marker, recovery, guarded driver, cleanup
``AB -> DZ -> CL -> ERRX? -> verify``) -> ``driver`` -> ``transport``. ``RunHandle`` is the protocol the archive
(WP1.7) implements so that a run's transport I/O and raw data land in its run folder.
"""

from b1500_test_agent.session.fault import (
    OUTPUT_OFF_STATES,
    CleanupUnverified,
    FaultClearRefused,
    FaultLatch,
    FaultLatched,
    clear_refusals,
    outputs_zero,
)
from b1500_test_agent.session.lock import InstrumentBusy, InstrumentLock, resource_slug
from b1500_test_agent.session.session import DailyAuditSink, Session, state_audit_sink
from b1500_test_agent.session.transaction import (
    InflightMarker,
    RunHandle,
    Transaction,
    read_inflight,
    read_live_state,
    run_cleanup,
)

__all__ = [
    "OUTPUT_OFF_STATES",
    "CleanupUnverified",
    "DailyAuditSink",
    "FaultClearRefused",
    "FaultLatch",
    "FaultLatched",
    "InflightMarker",
    "InstrumentBusy",
    "InstrumentLock",
    "RunHandle",
    "Session",
    "Transaction",
    "clear_refusals",
    "outputs_zero",
    "read_inflight",
    "read_live_state",
    "resource_slug",
    "run_cleanup",
    "state_audit_sink",
]
