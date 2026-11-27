"""The in-flight marker ``<state_dir>/inflight.json`` (``InflightMarker``, ``read_inflight``) and the transaction
ids (``new_tx_id``) that the marker and every audit event of a transaction carry.

A transaction writes the marker under the instrument lock when it starts and removes it when it ends
(``session/transaction.py``); a marker that is still there means its transaction never finished, so the next one runs
a recovery cleanup first. Any process can read it without touching the instrument (``Session.running_marker``).
"""

from __future__ import annotations

import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, ValidationError

from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.run import Adapter


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
