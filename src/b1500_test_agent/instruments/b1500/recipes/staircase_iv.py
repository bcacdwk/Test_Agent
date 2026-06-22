"""Staircase IV recipe placeholder."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StaircaseIVRecipe:
    """Parameters for a future staircase IV sweep."""

    sweep_channel: int
    measure_channel: int
    start_v: float
    stop_v: float
    steps: int = 101
    compliance_a: float = 0.001
