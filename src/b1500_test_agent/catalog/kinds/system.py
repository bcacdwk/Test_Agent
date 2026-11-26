"""``system``: instrument self-test (``*TST?``) and self-calibration (``*CAL?``) as recipes (blueprint 0 #1, 2.6), and
the same through the WGFMU instrument library (WP10.7; blueprint v2 2.7 row ``system``, 3.4 rows
``system.wgfmu_self_test``, ``system.wgfmu_self_cal``).

The recipe selects the operation through its single-choice enum parameter ``operation`` (``self_test``,
``self_cal``, ``wgfmu_self_test`` or ``wgfmu_self_cal``), so the agent cannot switch it. No DUT roles, no source
commands: the envelope is empty, so the transaction's ``OutputGuard`` refuses every source operation, and the fault
latch still gates the run. Both FLEX operations end with the modules in the ``CL`` state (PG p540 (4-222), PG p376
(4-58)); the human confirms each run (``always_confirm``: the measurement terminals must be open, PG p377 (4-59); for
the WGFMU the RSU outputs too, WG p36 (2-14)).

Backends (blueprint v2 2.7, WP6.2): ``implemented_on = {"sim", "visa"}``. The same code path serves both: one query
through the transaction's driver with a read timeout of ``2 x estimate + 10 s``, then the transaction's verified
cleanup (``DZ``, ``CL``, ``ERRX?`` drain, ``LOP?`` all ``00`` on hardware). On hardware every run is also
``needs_confirmation (first_hw_run)`` until a reviewed validation record exists (blueprint v2 7.2). No output switch
is turned on, so there is no ``LOP?`` positive control in these transactions. ``*RST`` is not sent: the self-test
already leaves every module in the ``CL`` state, and ``*RST`` would also drop the MFCMU corrections, set the SPGU to
free-run and reset the switch paths (PG p179-180 (2-91), Tables 2-12 and 2-13); the ``*RST`` lint
(``tests/unit/test_lint_rst.py``) still keeps that command inside this kind.

WGFMU operations (WP10.7): ``with tx.wgfmu_phase() as wg:`` (FLEX exclusive lock released or the link closed, library
session opened and initialized; the exit always runs the WGFMU safe state, closes the session and relocks), then
``WgfmuDriver.maintenance`` (``WGFMU_doSelfTest`` or ``WGFMU_doSelfCalibration``: the mainframe and every module,
WG p91-92 (4-21, 4-22); the library raises its own timeout to 600 s for the call, WG p129 (4-59) "600 s"). The plan's
source plan says ``library: true``, so rule R-WG-01 needs a loadable library (visa) and a library that lists a WGFMU
channel before execution. The result bitmask is the ``*TST?`` one (``2^(N-1)`` slot N, 1024 mainframe).

No measurement data is read, so there is no ``data.csv``; the result code and the failed units are recorded in the
manifest's ``kind_result`` and the audit log keeps the exact query (or library call) and response. A failed module is
disabled by the instrument until ``RCV`` (PG p541 (4-223)): the run fails and names the slots; the human decides
about service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.errors import failed_units
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import ChannelBinding, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, SourcePlan
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

OPERATION_PARAM: Final = "operation"

OPERATIONS: dict[str, tuple[str, float]] = {
    "self_test": (flex.TST_Q, 120.0),
    "self_cal": (flex.CAL_Q, 60.0),
    "wgfmu_self_test": ("library self_test", 120.0),
    "wgfmu_self_cal": ("library self_calibration", 60.0),
}
"""Operation -> (FLEX query or ``WgfmuApi`` method, estimated duration in s). The durations are conservative
placeholders, TODO(verify)[L1.A3, L8.A2] (FLEX at L1, WGFMU library at L8; blueprint v2 7.6 item 10: self-test/cal
durations); the FLEX read timeout is ``2 x estimate + 10 s`` (250 s for ``*TST?``, 130 s for ``*CAL?``); the library
times its calls out after 600 s by itself."""

LIBRARY_OPERATIONS: Final[dict[str, Literal["self_test", "self_calibration"]]] = {
    "wgfmu_self_test": "self_test", "wgfmu_self_cal": "self_calibration"}
"""The operations that run through the WGFMU instrument library (``WgfmuDriver.maintenance``)."""


class SystemKind:
    """Self-test / self-calibration, FLEX or WGFMU library (no DUT, no source commands)."""

    kind_id = "system"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

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
        program: dict[str, object] = {"operation": operation}
        preview = [query]
        if operation in LIBRARY_OPERATIONS:
            program[SOURCE_PLAN_KEY] = SourcePlan(library=True).model_dump(mode="json")
            preview = []  # a library call is no FLEX command (the summary and the audit name it)
        return CompiledKindPlan(envelope=CompiledEnvelope(channels={}),
                                estimate=Estimate(points=0, duration_s=duration), flex_preview=preview,
                                program=program)

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        operation = plan.program.get("operation")
        if operation not in OPERATIONS:
            raise CompileError(f"plan {plan.plan_id} has no {self.kind_id} operation")
        timeout = 2.0 * plan.estimate.duration_s + 10.0
        tx.mark(f"{operation} started")
        if operation in LIBRARY_OPERATIONS:
            with tx.wgfmu_phase() as wg:
                result = wg.maintenance(LIBRARY_OPERATIONS[operation])
        elif operation == "self_test":
            result = tx.driver.self_test(timeout_s=timeout)
        else:
            result = tx.driver.self_calibrate(timeout_s=timeout)
        failed = failed_units(result)
        tx.mark(f"{operation} result {result}")
        message = "" if result == 0 else f"{operation} failed: {', '.join(failed)} (result {result})"
        facts: dict[str, object] = {"operation": operation, "result": result, "failed_units": ", ".join(failed)}
        if operation in LIBRARY_OPERATIONS:
            facts["via"] = "WGFMU instrument library"
        return RawAcquisition(kind_result=facts, ok=result == 0, message=message)

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> None:
        return None
