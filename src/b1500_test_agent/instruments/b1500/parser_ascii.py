"""ASCII measurement parsers for B1500A data formats."""

from dataclasses import dataclass
from enum import StrEnum


class MeasurementStatus(StrEnum):
    """Known B1500A measurement status flags for ASCII data."""

    NORMAL = "N"
    COMPLIANCE = "C"
    OTHER_COMPLIANCE = "T"
    OVERVOLTAGE_OR_UNSTABLE = "V"
    OSCILLATION = "X"
    INVALID = "D"
    INTERVAL_TOO_SHORT = "L"


@dataclass(frozen=True)
class MeasurementPoint:
    """One parsed measurement point."""

    status: MeasurementStatus
    channel: int
    quantity: str
    value: float
    raw: str


def parse_fmt1(raw: str) -> list[MeasurementPoint]:
    """Parse `FMT 1` output.

    TODO: Implement strict parsing after confirming exact field widths from the manual.
    """
    _ = raw
    return []
