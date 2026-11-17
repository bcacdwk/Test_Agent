"""The ``MeasurementKind`` protocol (blueprint 2.6) and helpers shared by the kinds.

A kind turns a recipe into instrument work in three steps:

- ``compile(recipe, params, binding, station)`` is pure (no I/O): the per-channel envelope the ``OutputGuard`` will
  enforce, the estimate, the exact FLEX preview (built with ``driver/commands.py``) and a JSON program;
- ``acquire(tx, plan)`` executes the stored program through the transaction's guarded driver;
- ``to_table(raw, plan)`` turns the raw blocks into the tidy ``data.csv`` table (``None`` for kinds that measure
  no data, such as self-test).

``implemented_on`` lists the backends the kind has a validated code path for; on any other backend the registry
reports the recipe's effective status as ``not_implemented`` and the executor refuses with zero I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pandas as pd

from b1500_test_agent.catalog.schema import CompiledKindPlan, RawAcquisition
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import ChannelBinding, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

ALL_BACKENDS: frozenset[Backend] = frozenset({"sim", "visa"})


@runtime_checkable
class MeasurementKind(Protocol):
    """One measurement kind (``smu_staircase``, ``system`` ...)."""

    kind_id: str
    implemented_on: frozenset[Backend]

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Pure: envelope, estimate, FLEX preview and program. Raises ``CompileError`` for requests the kind
        cannot express; missing bindings are skipped (the plan-phase rules block them)."""
        ...

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute ``plan.program`` through ``tx.driver`` (guarded); raises on any failure (the transaction
        cleans up)."""
        ...

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame | None:
        """The tidy table of the ``data.csv`` contract (``analysis/dataset.py``) without the ``trust`` column, or
        ``None`` when the kind measures no data."""
        ...


def implemented_on(kind: MeasurementKind | None, backend: Backend) -> bool:
    """True when ``kind`` exists and has a code path for ``backend``."""
    return kind is not None and backend in kind.implemented_on
