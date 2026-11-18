"""Shared pieces of the simulator units and their dispatcher (blueprint 4.1).

- ``handles(*mnemonics)`` marks a unit method as the FLEX handler of the given mnemonics; ``handler_table(cls)``
  collects the marks over the class hierarchy into ``{mnemonic: method name}`` and refuses a mnemonic claimed twice.
  ``SimInstrument`` dispatches each parsed command through that table.
- ``Unsupported``: a supported command used with a form the simulator does not implement (error 100, logged
  ``unsupported``).
- ``Measurement``: a triggered measurement (per-step formatted data and completion times), produced by a unit at
  ``XE`` and completed, aborted or rolled back by the dispatcher.
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
