"""Spot IV recipe placeholder."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SpotIVRecipe:
    """Parameters for a future spot IV measurement."""

    channel: int
    force_value: float
    force_quantity: str = "voltage"
    compliance_a: float = 0.001
