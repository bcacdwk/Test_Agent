"""Shared pieces of the simulator device models: the ``Device``/``StatefulDevice`` protocols, voltage and state
types, physical constants and numerically safe helpers (blueprint 4.2).

Sign convention: currents flow from the instrument into the device terminal (an SMU forcing +V into a resistor
to ground measures a positive current). A terminal voltage of ``None`` is floating.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

BOLTZMANN_OVER_Q = 8.617333262e-5
"""k/q in V/K (thermal voltage U_T = k·T/q)."""

EXP_LIMIT = 80.0
"""Exponent above which the diode exponentials continue linearly (no overflow at any SMU voltage; far beyond any
current a compliance allows)."""

Voltages = Mapping[str, float | None]
"""Terminal name → voltage (V), ``None`` = floating."""

DeviceState = dict[str, float | int | bool | str]
"""Persisted internal state of one device (JSON scalars, stored in ``SimPersistentState.devices``)."""


class Device(Protocol):
    """A two- or multi-terminal device."""

    name: str
    model: str
    params: object

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        """Current (A) into each terminal for terminal voltages ``v``; floating terminals carry no current."""
        ...


@runtime_checkable
class StatefulDevice(Protocol):
    """A device whose currents depend on its voltage history (FeFET polarization).

    ``terminal_currents`` evaluates a trial voltage set as if it were applied now, without changing the state;
    ``commit`` applies a voltage set for real.
    """

    name: str

    def terminal_currents(self, v: Voltages) -> dict[str, float]: ...

    def commit(self, v: Voltages) -> None:
        """Update the internal state for the voltages ``v`` that were actually applied."""
        ...

    def export_state(self) -> DeviceState:
        """The internal state as JSON scalars."""
        ...

    def import_state(self, data: Mapping[str, object] | None) -> None:
        """Restore the state (``None``: the initial state). Raises ``ValueError`` for malformed data."""
        ...


def softplus(x: float) -> float:
    """ln(1 + e^x) without overflow."""
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


def exp_lin(x: float) -> tuple[float, float]:
    """``exp(x)`` and its derivative, continued linearly above ``EXP_LIMIT`` (monotonic, never overflows)."""
    if x <= EXP_LIMIT:
        value = math.exp(x)
        return value, value
    edge = math.exp(EXP_LIMIT)
    return edge * (1.0 + x - EXP_LIMIT), edge


