"""``system``: instrument self-test (``*TST?``) and self-calibration (``*CAL?``) as recipes (blueprint 0 #1, 2.6).

The recipe selects the operation through its single-choice enum parameter ``operation`` (``self_test`` or
``self_cal``), so the agent cannot switch it. No DUT roles, no source commands: the envelope is empty, so the
transaction's ``OutputGuard`` refuses every source operation, and the fault latch still gates the run. Both
operations end with the modules in the ``CL`` state (PG PDF 540, 377); the human confirms each run
(``always_confirm``: the measurement terminals should be open). ``implemented_on = {"sim"}`` in v1: on hardware the
recipes stay ``not_implemented`` until the M4 bring-up has checked their duration and terminal requirements.

No measurement data is read, so there is no ``data.csv``; the result code and the failed units are recorded in the
manifest's ``kind_result`` and the audit log keeps the exact query and response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition
from b1500_test_agent.driver import commands
from b1500_test_agent.driver.errors import failed_units
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import ChannelBinding, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

OPERATION_PARAM: Final = "operation"

OPERATIONS: dict[str, tuple[str, float]] = {
    "self_test": (commands.TST_Q, 120.0),
    "self_cal": (commands.CAL_Q, 60.0),
}
"""Operation -> (query, estimated duration in s). The durations are conservative placeholders (TODO(verify) at
M4 bring-up); the read timeout is ``2 x estimate + 10 s``."""


class SystemKind:
    """Self-test / self-calibration (no DUT, no source commands)."""

    kind_id = "system"
    implemented_on: frozenset[Backend] = frozenset({"sim"})

    @staticmethod
    def _operation(params: dict[str, Quantity]) -> str:
        quantity = params.get(OPERATION_PARAM)
        operation = None if quantity is None else quantity.value
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise CompileError(f"{OPERATION_PARAM} must be one of {sorted(OPERATIONS)}, got {operation!r}")
        return operation

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        if recipe.roles:
            raise CompileError(f"{self.kind_id} recipes have no DUT roles; {recipe.id} declares {sorted(recipe.roles)}")
        operation = self._operation(params)
        query, duration = OPERATIONS[operation]
        return CompiledKindPlan(envelope=CompiledEnvelope(channels={}),
                                estimate=Estimate(points=0, duration_s=duration), flex_preview=[query],
                                program={"operation": operation})

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        operation = plan.program.get("operation")
        if operation not in OPERATIONS:
            raise CompileError(f"plan {plan.plan_id} has no {self.kind_id} operation")
        timeout = 2.0 * plan.estimate.duration_s + 10.0
        tx.mark(f"{operation} started")
        result = tx.driver.self_test(timeout_s=timeout) if operation == "self_test" \
            else tx.driver.self_calibrate(timeout_s=timeout)
        failed = failed_units(result)
        tx.mark(f"{operation} result {result}")
        message = "" if result == 0 else f"{operation} failed: {', '.join(failed)} (result {result})"
        return RawAcquisition(kind_result={"operation": operation, "result": result, "failed_units": ", ".join(failed)},
                              ok=result == 0, message=message)

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> None:
        return None
