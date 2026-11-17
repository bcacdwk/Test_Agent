"""Run audit log ``<run>/audit.jsonl`` (blueprint 2.7): the run's transport I/O and lifecycle events.

The transaction routes every event of a run to the run's sink (``RunHandle.audit``); events of actions without a
run go to the session's daily file ``<state_dir>/audit/YYYY-MM-DD.jsonl``. Line format: ``models/audit.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.transport.audit import JsonlAuditSink

RUN_AUDIT_FILE = "audit.jsonl"


class RunAuditSink(JsonlAuditSink):
    """Appends the events of one run to ``<run_dir>/audit.jsonl`` (one UTF-8 JSON line each, ``\\n``)."""

    def __init__(self, run_dir: Path) -> None:
        super().__init__(Path(run_dir) / RUN_AUDIT_FILE)


def read_audit(run_dir: Path, *, events: Iterable[str] | None = None, limit: int | None = None) -> list[AuditEvent]:
    """The run's audit events in order, optionally only ``events`` names and only the last ``limit`` of them.

    Unparsable lines are skipped (the file is append-only and never rewritten)."""
    path = Path(run_dir) / RUN_AUDIT_FILE
    if not path.is_file():
        return []
    wanted = None if events is None else set(events)
    found: list[AuditEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = AuditEvent.from_json_line(line)
        except ValueError:
            continue
        if wanted is None or event.ev in wanted:
            found.append(event)
    return found if limit is None else found[-limit:] if limit > 0 else []
