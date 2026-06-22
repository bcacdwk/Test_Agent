"""Safety policy validation for B1500A operations."""

from dataclasses import dataclass


class SafetyViolationError(ValueError):
    """Raised when a requested operation violates safety policy."""


@dataclass(frozen=True)
class Limit:
    """Voltage and current limits for a module or station."""

    max_voltage_v: float | None = None
    max_current_a: float | None = None


def validate_voltage(voltage_v: float, limit: Limit) -> None:
    """Validate a source voltage against a configured limit."""
    if limit.max_voltage_v is not None and abs(voltage_v) > limit.max_voltage_v:
        raise SafetyViolationError(
            f"Voltage {voltage_v} V exceeds limit {limit.max_voltage_v} V."
        )


def validate_current(current_a: float, limit: Limit) -> None:
    """Validate a source current against a configured limit."""
    if limit.max_current_a is not None and abs(current_a) > limit.max_current_a:
        raise SafetyViolationError(
            f"Current {current_a} A exceeds limit {limit.max_current_a} A."
        )
