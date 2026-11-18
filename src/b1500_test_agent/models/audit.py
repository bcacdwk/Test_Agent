"""Audit event: one line of an audit JSONL file (blueprint 2.7).

Line shape (UTF-8 JSONL, ``\\n``, ISO-8601 UTC with milliseconds), keys in this order::

    {"ts":"2026-11-17T06:30:12.123Z","seq":17,"run":"S…","tx":"T…","ev":"write",
     "cmd":"WV 1,1,0,-1.0,3.0,101,1E-6","resp":null,"dur_ms":1.2,"intent":"gate sweep","backend":"sim"}

The ten keys above are always present. ``error`` (the exception text of a failed I/O) and ``data`` (structured
payload of lifecycle events such as ``cleanup_step``) are appended only when set, so plain I/O lines keep exactly
the blueprint shape. ``seq`` is assigned by the sink that records the event (one counter per sink).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator

from b1500_test_agent.models.common import Backend, JsonScalar, StrictModel

AuditEventName = Literal[
    "session_open", "lock_acquired", "recovery_cleanup", "rule_report", "tier_check", "checkpoint",
    "write", "read", "query", "poll", "device_clear",
    "data_block", "instrument_error", "envelope_violation", "fault", "fault_cleared",
    "cleanup_step", "cleanup_verified", "cleanup_unverified", "lock_released", "run_status", "tool_call",
    "bus_open", "bus_lock", "bus_unlock", "bus_close", "abort_requested", "run_cancelled", "probe",
]  # fmt: skip
"""Event names of blueprint 2.7 plus ``device_clear`` (the transport-level SDC, which 2.7 does not name), the bus
lifecycle events of blueprint v2 2.4 (``bus_*``: open, exclusive lock, unlock, close of the instrument link per
transaction; ``dur_ms`` measures the per-transaction overhead, ATV-13) and the async-run events of v2 2.6
(``abort_requested``: an abort file was written; ``run_cancelled``: a run honoured it at a checkpoint) and the
read-only bring-up probe of v2 7.1 (``probe``: the verdict of every probe line and where its raw record went)."""

TRANSPORT_EVENTS: frozenset[str] = frozenset({"write", "read", "query", "poll", "device_clear"})
"""Events emitted by ``AuditingTransport`` for instrument I/O (one per I/O call)."""

BUS_EVENTS: frozenset[str] = frozenset({"bus_open", "bus_lock", "bus_unlock", "bus_close"})
"""Bus lifecycle events emitted by ``AuditingTransport`` (no instrument command; one per lifecycle call)."""

_LINE_KEYS = ("ts", "seq", "run", "tx", "ev", "cmd", "resp", "dur_ms", "intent", "backend")
_OPTIONAL_KEYS = ("error", "data")


def format_ts(ts: datetime) -> str:
    """``ts`` as ISO-8601 UTC with milliseconds and a ``Z`` suffix, e.g. ``2026-11-17T06:30:12.123Z``."""
    utc = ts.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


class AuditEvent(StrictModel):
    """One audit record. ``seq`` stays ``None`` until a sink records the event and numbers it."""

    ts: AwareDatetime
    seq: int | None = Field(default=None, ge=0)
    run: str | None = None
    tx: str | None = None
    ev: AuditEventName
    cmd: str | None = None
    resp: str | None = None
    dur_ms: float | None = Field(default=None, ge=0)
    intent: str | None = None
    backend: Backend
    error: str | None = None
    data: dict[str, JsonScalar] | None = None

    @field_validator("ts")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @classmethod
    def now(cls, ev: AuditEventName, backend: Backend, **fields: Any) -> AuditEvent:
        """A new event stamped with the current UTC time (``seq`` is left to the sink)."""
        return cls(ts=datetime.now(UTC), ev=ev, backend=backend, **fields)

    def to_record(self) -> dict[str, Any]:
        """The JSON object of the audit line, keys in blueprint order (``error``/``data`` only when set)."""
        record: dict[str, Any] = {
            "ts": format_ts(self.ts),
            "seq": self.seq,
            "run": self.run,
            "tx": self.tx,
            "ev": self.ev,
            "cmd": self.cmd,
            "resp": self.resp,
            "dur_ms": None if self.dur_ms is None else round(self.dur_ms, 3),
            "intent": self.intent,
            "backend": self.backend,
        }
        for key in _OPTIONAL_KEYS:
            value = getattr(self, key)
            if value is not None:
                record[key] = value
        return record

    def to_json_line(self) -> str:
        """One JSONL line without the trailing newline (compact separators, UTF-8 text kept as is)."""
        return json.dumps(self.to_record(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json_line(cls, line: str) -> AuditEvent:
        """Parse a line written by ``to_json_line``; unknown keys are rejected."""
        record = json.loads(line)
        if not isinstance(record, dict) or any(key not in record for key in _LINE_KEYS):
            raise ValueError("An audit line is a JSON object with the keys " + ", ".join(_LINE_KEYS) + ".")
        return cls.model_validate(record)
