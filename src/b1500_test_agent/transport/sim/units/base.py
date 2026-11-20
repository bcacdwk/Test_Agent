"""Shared pieces of the simulator units and their dispatcher (blueprint 4.1).

- ``handles(*mnemonics)`` marks a unit method as the FLEX handler of the given mnemonics; ``handler_table(cls)``
  collects the marks over the class hierarchy into ``{mnemonic: method name}`` and refuses a mnemonic claimed twice.
  ``SimInstrument`` dispatches each parsed command through that table.
- ``Unsupported``: a supported command used with a form the simulator does not implement (error 100, logged
  ``unsupported``).
- ``learns(*types)`` marks a unit method as the answer of ``*LRN?`` types (``learn_table(cls)``), so each family
  answers its own settings groups (WP8.1: the MFCMU types 70-73, 90 and the SCUU types 80, 81).
- ``Measurement``: a triggered measurement (per-step formatted data and completion times), produced by a unit at
  ``XE`` and completed, aborted or rolled back by the dispatcher; ``on_end`` lets a family apply its own
  post-measurement output (the MFCMU sources, WP8.1).
- Module-type sets and instrument constants shared by several units.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from b1500_test_agent.transport.sim import flex

if TYPE_CHECKING:
    from b1500_test_agent.transport.sim.units.smu import Sweep

HANDLES_ATTR = "_sim_handles"
"""Attribute ``handles`` sets on a handler function: the tuple of mnemonics it handles."""

LEARNS_ATTR = "_sim_learns"
"""Attribute ``learns`` sets on a ``*LRN?`` answer function: the tuple of types it answers."""

DEFAULT_ICOMP = 1e-4
"""Current compliance after ``CN``/``CL``: 100 uA (PG PDF 378)."""

CMU_TYPES = frozenset({"MFCMU"})
SPGU_TYPES = frozenset({"HVSPGU"})
FOREVER = math.inf
"""End time of a hung measurement (``timeout`` fault)."""

F = TypeVar("F", bound=Callable[..., Any])


def handles(*mnemonics: str) -> Callable[[F], F]:
    """Register the decorated unit method as the handler of ``mnemonics`` (each in ``flex.SUPPORTED``)."""
    if not mnemonics:
        raise ValueError("handles() needs at least one mnemonic")

    def mark(function: F) -> F:
        setattr(function, HANDLES_ATTR, tuple(mnemonics))
        return function

    return mark


def handler_table(cls: type) -> dict[str, str]:
    """``{mnemonic: method name}`` of every ``@handles`` method of ``cls`` and its bases.

    Raises:
        TypeError: If two methods claim the same mnemonic.
    """
    table: dict[str, str] = {}
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if name in seen:
                continue  # overridden in a subclass: the subclass attribute counts
            seen.add(name)
            for mnemonic in getattr(value, HANDLES_ATTR, ()):
                if mnemonic in table:
                    raise TypeError(f"{cls.__name__}: {mnemonic} is handled by both {table[mnemonic]} and {name}")
                table[mnemonic] = name
    return table


def learns(*types: int) -> Callable[[F], F]:
    """Register the decorated unit method (``(self, kind) -> str``) as the ``*LRN?`` answer of ``types``."""
    if not types:
        raise ValueError("learns() needs at least one *LRN? type")

    def mark(function: F) -> F:
        setattr(function, LEARNS_ATTR, tuple(types))
        return function

    return mark


def learn_table(cls: type) -> dict[int, str]:
    """``{*LRN? type: method name}`` of every ``@learns`` method of ``cls`` and its bases.

    Raises:
        TypeError: If two methods claim the same type.
    """
    table: dict[int, str] = {}
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if name in seen:
                continue
            seen.add(name)
            for kind in getattr(value, LEARNS_ATTR, ()):
                if kind in table:
                    raise TypeError(f"{cls.__name__}: *LRN? {kind} is answered by both {table[kind]} and {name}")
                table[kind] = name
    return table


class Unsupported(flex.FlexError):
    """A supported command used with a form the v1 simulator does not implement (error 100, logged unsupported)."""

    def __init__(self, detail: str) -> None:
        super().__init__(flex.ERR_UNDEFINED, detail)


@dataclass
class Measurement:
    """A triggered measurement: per-step data (already formatted) and completion times."""

    start: float
    end: float
    step_ends: list[float]
    blocks: list[list[str]]
    sweep: Sweep | None
    post_level: float | None
    zero_at: float | None
    device_states: list[dict[str, dict[str, float | int | bool | str]]] = field(default_factory=list)
    """Stateful-device state before the first step (index 0) and after each measured step (index k)."""
    source_levels: dict[int, tuple[float, float]] | None = None
    """Sampling (``MM 10``): ``{channel: (voltage, compliance)}`` the synchronous sources hold after the measurement
    ends (``MSC`` post value, or base after an automatic abort)."""
    abort_source_levels: dict[int, tuple[float, float]] | None = None
    """Sampling: what the synchronous sources hold after an ``AB`` or device clear ends the measurement early
    (their base values)."""
    post_at_stop: bool = False
    """After a normal end, the sweep sources keep their stop values (``WM`` post 2); otherwise their start values."""
    on_end: Callable[[bool], None] | None = None
    """Called once when the measurement ends (``True`` = aborted): a family's post-measurement output."""
