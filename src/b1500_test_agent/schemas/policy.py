"""Safety and approval policy schemas."""

from pydantic import BaseModel


class SafetyPolicy(BaseModel):
    """Top-level executable safety policy model."""

    max_voltage_v: float
    max_current_a: float
    require_interlock_above_v: float = 42.0
    approval_required: list[str] = []
