"""Shared pieces of the simulator device models: the ``Device``/``StatefulDevice``/``DynamicDevice``/``AcDevice``
protocols, voltage and state types, physical constants and numerically safe helpers (blueprint 4.1, 4.2).

Sign convention: currents flow from the instrument into the device terminal (an SMU forcing +V into a resistor
to ground measures a positive current). A terminal voltage of ``None`` is floating.

Time (v2): ``commit(v)`` applies a voltage set quasi-statically (a DC level held long against every switching or
settling time, but no time passes for ageing); ``advance(dt, v)`` holds ``v`` for ``dt`` seconds of virtual time, so
time-dependent physics (traps, polarization kinetics, self-heating, breakdown, ageing) evolves, and returns the
terminal currents at the end of the interval plus the mean displacement current over it (the change of stored
charge since the previously applied voltages, divided by ``dt``; none for ``dt = 0``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

BOLTZMANN_OVER_Q = 8.617333262e-5
"""k/q in V/K (thermal voltage U_T = k·T/q)."""

Q_E = 1.602176634e-19
"""Elementary charge (C)."""

EPS0_F_CM = 8.8541878128e-14
"""Vacuum permittivity (F/cm)."""

UM2_TO_CM2 = 1.0e-8
"""µm² → cm²."""

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


@runtime_checkable
class DynamicDevice(Protocol):
    """A device with time-dependent physics (v2): ``advance`` holds a voltage set for ``dt`` seconds."""

    name: str

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        """Hold ``v`` for ``dt`` seconds (``dt`` ≥ 0) and return the terminal currents at the end of the interval plus
        the mean displacement current over it."""
        ...


@runtime_checkable
class AcDevice(Protocol):
    """A two-terminal device with a small-signal admittance (CMU measurements; v2)."""

    name: str
    terminals: tuple[str, str]

    def admittance(self, v: float, f: float) -> complex:
        """Small-signal admittance (S) between its two terminals at DC bias ``v`` (V, first minus second terminal) and
        frequency ``f`` (Hz, > 0), for the present internal state."""
        ...

    def capacitance(self, v: float, f: float) -> float:
        """Parallel capacitance ``Im(Y)/(2πf)`` (F)."""
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




def two_terminal(v: Voltages, first: str, second: str) -> float | None:
    """``V(first) - V(second)``, or ``None`` when either terminal floats."""
    a, b = v.get(first), v.get(second)
    return None if a is None or b is None else a - b


def parallel_capacitance(y: complex, f: float) -> float:
    """Parallel capacitance ``Im(Y)/(2πf)`` of admittance ``y`` at frequency ``f``."""
    return y.imag / (2.0 * math.pi * f)


def check_frequency(f: float) -> float:
    """``f`` if it is a positive finite frequency; raises ``ValueError`` otherwise."""
    if not (math.isfinite(f) and f > 0.0):
        raise ValueError(f"frequency must be positive and finite, got {f!r}")
    return f


def state_number(data: Mapping[str, object], key: str, owner: str, *, lo: float = -math.inf,
                 hi: float = math.inf) -> float:
    """``data[key]`` as a finite float in ``[lo, hi]``; raises ``ValueError`` naming ``owner`` otherwise."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) \
            or not lo <= value <= hi:
        raise ValueError(f"{owner}: state {key!r} = {value!r} is not a number in [{lo}, {hi}]")
    return float(value)


def state_flag(data: Mapping[str, object], key: str, owner: str) -> bool:
    """``data[key]`` as a bool; raises ``ValueError`` naming ``owner`` otherwise."""
    value = data.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{owner}: state {key!r} = {value!r} is not a boolean")  # malformed state is a ValueError


def check_state_keys(data: Mapping[str, object], expected: set[str], owner: str) -> None:
    """Raise ``ValueError`` unless ``data`` holds exactly the keys ``expected``."""
    if set(data) != expected:
        raise ValueError(f"{owner}: state must hold exactly {sorted(expected)}, got {sorted(data)}")
