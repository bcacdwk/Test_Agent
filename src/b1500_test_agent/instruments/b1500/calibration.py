"""Calibration and correction state tracking."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CorrectionRecord:
    """Metadata for a capacitance correction or phase compensation run."""

    correction_type: str
    timestamp: datetime
    frequency_hz: float | None = None
    operator: str | None = None
    notes: str | None = None


def correction_is_current(record: CorrectionRecord | None) -> bool:
    """Return whether a correction record is acceptable for use.

    TODO: Add station-specific freshness and frequency coverage checks.
    """
    return record is not None
