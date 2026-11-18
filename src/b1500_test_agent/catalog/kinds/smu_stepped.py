"""``smu_stepped``: a host loop over a step role, one SMU staircase sweep per step value (blueprint 2.6, M2).

Typical use is an output family (Id-Vd): the drain sweeps (``sweep_v``) for each gate level of the ``step_v`` role.

Roles: everything ``smu_staircase`` accepts (one ``sweep_v``, ``bias_v``, ``ground``, ``measure_only``; same
settings and the same ``integration`` parameter) plus exactly one ``step_v`` role on an SMU with settings ``icomp``
(required) and either ``values`` (a ``$param`` of type ``float_list``) or ``start``, ``stop``, ``points`` (linear,
``points`` = 1 gives ``start`` only). Step values are rounded to 1 nV and must be distinct (each curve is identified
by its step value). The step role may measure ``I``; measuring ``V`` is refused because its programmed level is the
step column of the table.

Compile (pure): the staircase compiled with the step role as a bias at the first value, then the step channel's
envelope widened to every step value (``function: step_v``, ``v_start``/``v_stop`` = first/last value), the
estimate ``points`` = steps x sweep steps, ``duration`` = 1 s + steps x (sweep time + 0.2 s) and ``max_segment_s`` =
one sweep with its setup allowance + 0.2 s (each step is one segment between checkpoints, blueprint v2 2.6), and the
FLEX preview = the staircase setup followed by ``DV <step>`` and ``XE`` per step value.

Acquire (inside ONE transaction, through the guarded driver): the staircase setup (``configure_staircase``: FMT,
ADC, CN, ``ERRX?`` drain, bias DVs, MM/CMM/WV/WT/WM, ``ERRX?`` drain), then for each step value: ``DV`` on the step
channel, ``ERRX?`` drain (any error aborts before ``XE``), ``XE`` and one read (timeout ``2 x sweep estimate +
10 s``). Each sweep runs with ``WM 2,1`` as in ``smu_staircase`` (automatic abort on compliance, overflow or
oscillation); in addition the host loop stops after a sweep that reported any of ``STOP_STATUSES`` (the later steps
usually drive harder), and ``kind_result`` records it: ``steps_planned``, ``steps_done``, ``stopped_early``,
``stop_reason``. After every step ``tx.checkpoint(step, steps, "sweep", rows)`` hands over the curve's table rows:
an asynchronous run (longer than ``max_sync_run_s``, e.g. many gate steps at long integration) records them in
``progress.json``/``partial.csv``, and any run stops there when ``safe_shutdown`` asked (``RunCancelled``).
Cleanup is the transaction's (``AB → DZ → CL → verify``).

Table (``data.csv`` contract of ``analysis/dataset.py``): the rows of each sweep in acquisition order with
``step`` running over the whole run (0-based, strictly increasing across curves), ``segment`` for double sweeps
(per curve), the sweep source column ``<sweep role>_V``, measured ``<role>_<I|V>`` + ``_status``, constant bias
source columns, and the step source column ``<step role>_V`` (e.g. ``gate_V``): the programmed step level,
constant within a curve and distinct between curves, so ``table.groupby("gate_V", sort=False)`` yields the family
in acquisition order. Skipped steps have no rows.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_staircase import (
    SETUP_OVERHEAD_S,
    SmuStaircaseKind,
    StaircaseProgram,
    configure_staircase,
    drain_or_raise,
    read_timeout_s,
    staircase_rows,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

STEP_OVERHEAD_S = 0.2
"""Allowance per step for the step ``DV``, the ``ERRX?`` drain and the data transfer in the duration estimate."""

MAX_STEP_VALUES = 1001
"""Most step values one plan may hold (R-RUN-01 limits the points and the duration on top of this)."""

STOP_STATUSES = frozenset("CTVX")
"""Status letters after which the host loop stops: compliance (``C``, other channel ``T``), overflow or invalid
data (``V``) and oscillation (``X``), the same conditions that make ``WM 2`` abort a sweep."""

STEP_DIGITS = 9
"""Step values are rounded to this many decimal places (1 nV)."""


class SteppedProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    staircase: StaircaseProgram
    """The sweep run at every step; its biases and source columns exclude the step role."""
    step_role: str
    step_channel: Channel
    step_icomp: float
    step_values: list[float] = Field(min_length=1, max_length=MAX_STEP_VALUES)
    sweep_estimate_s: float = Field(ge=0)
    """Estimated duration of one sweep (with the setup allowance): the base of the per-read timeout."""

    @property
    def points(self) -> int:
        """Points of the whole run (every step, every sweep step)."""
        return len(self.step_values) * self.staircase.steps

    @property
    def step_column(self) -> str:
        """The step source column of the table, ``<step role>_V``."""
        return f"{self.step_role}_V"


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def step_values(name: str, role: RoleSpec, params: dict[str, Quantity]) -> list[float]:
    """The step levels of role ``name``: setting ``values`` (a ``float_list``) or ``start``/``stop``/``points``
    (linear); rounded to ``STEP_DIGITS`` decimals; non-empty and distinct. Raises ``CompileError``."""
    listed = setting_value(role, "values", params)
    ranged = [key for key in ("start", "stop", "points") if key in role.settings]
    if listed is not None or "values" in role.settings:
        if ranged:
            raise CompileError(f"{name}: give either values or start/stop/points, not both")
        if not isinstance(listed, list) or not listed:
            raise CompileError(f"{name}.values must be a non-empty list of voltages, got {listed!r}")
        raw = [_number(v, f"{name}.values[{i}]") for i, v in enumerate(listed)]
    else:
        start = _number(setting_value(role, "start", params), f"{name}.start")
        stop = _number(setting_value(role, "stop", params), f"{name}.stop")
        points = setting_value(role, "points", params)
        if isinstance(points, float) and points.is_integer():
            points = int(points)  # a literal role setting is stored as a float
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise CompileError(f"{name}.points must be a positive integer, got {points!r}")
        if points > MAX_STEP_VALUES:
            raise CompileError(f"{name}.points {points} exceeds {MAX_STEP_VALUES}")
        raw = [start] if points == 1 else [start + (stop - start) * i / (points - 1) for i in range(points)]
    if len(raw) > MAX_STEP_VALUES:
        raise CompileError(f"{name}: {len(raw)} step values exceed {MAX_STEP_VALUES}")
    values = [round(v, STEP_DIGITS) + 0.0 for v in raw]  # + 0.0 turns -0.0 into 0.0
    if len(set(values)) != len(values):
        raise CompileError(f"{name}: step values must be distinct (each curve is identified by its step value), "
                           f"got {values}")
    return values


class SmuSteppedKind:
    """Host loop over a ``step_v`` role with one staircase sweep per step (sim and visa code path)."""

    kind_id = "smu_stepped"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program; see the module docstring."""
        steps = [name for name, role in recipe.roles.items() if role.function == "step_v"]
        if len(steps) != 1:
            raise CompileError(f"{self.kind_id} needs exactly one step_v role; recipe {recipe.id} has {steps}")
        step_name = steps[0]
        step_role = recipe.roles[step_name]
        if "V" in step_role.measure:
            raise CompileError(f"step role {step_name} must not measure V: its programmed level is the "
                               f"{step_name}_V column")
        values = step_values(step_name, step_role, params)
        icomp = _number(setting_value(step_role, COMPLIANCE_SETTING, params),
                        f"{step_name}.{COMPLIANCE_SETTING}")
        as_bias = step_role.model_copy(update={"function": "bias_v",
                                               "settings": {"v": values[0], COMPLIANCE_SETTING: icomp}})
        base_recipe = recipe.model_copy(update={"roles": {**recipe.roles, step_name: as_bias}})
        try:
            base = SmuStaircaseKind().compile(base_recipe, params, binding, station)
        except CompileError as exc:
            raise CompileError(f"{self.kind_id} (per-step sweep): {exc}") from None
        channels = dict(base.envelope.channels)
        bound = binding.roles.get(step_name)
        step_channel = bound.channel if bound is not None else None
        if step_channel is not None:
            channels[step_channel] = ChannelEnvelope(
                role=step_name, max_abs_v=max(abs(v) for v in values), max_abs_i=abs(icomp), function="step_v",
                v_start=values[0], v_stop=values[-1])
        envelope = CompiledEnvelope(channels=channels)
        if not base.program or step_channel is None:
            # The sweep or the step role is not bound to a channel: the plan-phase rules block the plan (R-PIN-01).
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
        sweep = StaircaseProgram.model_validate(base.program)
        sweep_estimate = base.estimate.duration_s
        staircase = StaircaseProgram.model_validate({
            **sweep.model_dump(mode="json"),
            "biases": [b.model_dump(mode="json") for b in sweep.biases if b.role != step_name],
            "source_columns": {r: v for r, v in sweep.source_columns.items() if r != step_name},
        })
        program = SteppedProgram(staircase=staircase, step_role=step_name, step_channel=step_channel,
                                 step_icomp=icomp, step_values=values, sweep_estimate_s=sweep_estimate)
        duration = SETUP_OVERHEAD_S + len(values) * (sweep_estimate - SETUP_OVERHEAD_S + STEP_OVERHEAD_S)
        estimate = Estimate(points=program.points, duration_s=round(duration, 6),
                            max_segment_s=round(sweep_estimate + STEP_OVERHEAD_S, 6))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self.preview(program),
                                program=program.model_dump(mode="json"))

    @staticmethod
    def preview(program: SteppedProgram) -> list[str]:
        """The writes ``acquire`` sends, in order: the staircase setup, then ``DV`` + ``XE`` per step value
        (``ERRX?`` drains are not listed)."""
        lines = SmuStaircaseKind.preview(program.staircase)[:-1]  # everything but the final XE
        for value in program.step_values:
            lines.append(flex.dv(program.step_channel, 0, value, program.step_icomp))
            lines.append(flex.XE)
        return lines

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints ``acquire`` reports: one per step value (fewer when the loop stops early)."""
        return len(SteppedProgram.model_validate(plan.program).step_values) if plan.program else 0

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (see the module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = SteppedProgram.model_validate(plan.program)
        sweep = program.staircase
        configure_staircase(tx, sweep)
        timeout = read_timeout_s(Estimate(points=sweep.steps, duration_s=program.sweep_estimate_s))
        blocks: list[RawBlock] = []
        stop_reason = ""
        last = len(program.step_values) - 1
        total = len(program.step_values)
        for index, value in enumerate(program.step_values):
            tx.driver.force_v(program.step_channel, value, icomp=program.step_icomp)
            drain_or_raise(tx, f"setting {program.step_role} to step {index}")
            tx.mark(f"step {index}: {program.step_role} = {value:g} V")
            block = tx.driver.execute_and_read(expected_points=sweep.steps * sweep.width, timeout_s=timeout)
            blocks.append(block)
            tx.checkpoint(index + 1, total, "sweep",
                          rows=lambda i=index, v=value, b=block: self.curve_rows(program, i, v, b))
            flagged = sorted({str(p.status.value) for p in block.points if str(p.status.value) in STOP_STATUSES})
            if flagged and index < last:
                stop_reason = (f"step {index} ({program.step_role} = {value:g} V) reported status "
                               f"{','.join(flagged)}; the remaining {last - index} step(s) were not run")
                tx.mark("stopped: " + stop_reason)
                break
        tx.mark("data read")
        result: dict[str, Any] = {"steps_planned": len(program.step_values), "steps_done": len(blocks),
                                  "stopped_early": bool(stop_reason), "stop_reason": stop_reason}
        return RawAcquisition(blocks=blocks, kind_result=result)

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """Tidy table over every acquired curve (see the module docstring for the columns).

        Raises:
            ValueError: If there is no block, more blocks than step values, or a block does not hold the programmed
                elements.
        """
        program = SteppedProgram.model_validate(plan.program)
        if not raw.blocks or len(raw.blocks) > len(program.step_values):
            raise ValueError(f"{self.kind_id} expects 1..{len(program.step_values)} data blocks, got "
                             f"{len(raw.blocks)}")
        rows: list[dict[str, object]] = []
        for index, (block, value) in enumerate(zip(raw.blocks, program.step_values, strict=False)):
            rows += self.curve_rows(program, index, value, block)
        return pd.DataFrame(rows)

    @staticmethod
    def curve_rows(program: SteppedProgram, index: int, value: float, block: RawBlock) -> list[dict[str, object]]:
        """Table rows of curve ``index`` (step level ``value``): ``staircase_rows`` with ``step`` continuing over the
        run and the step source column right after the sweep source column (also the ``partial.csv`` rows)."""
        sweep = program.staircase
        sweep_source = f"{sweep.sweep_role}_V"
        rows: list[dict[str, object]] = []
        for row in staircase_rows(sweep, block, first_step=index * sweep.steps):
            ordered: dict[str, object] = {}
            for key, cell in row.items():
                ordered[key] = cell
                if key == sweep_source:
                    ordered[program.step_column] = value
            if program.step_column not in ordered:
                ordered[program.step_column] = value
            rows.append(ordered)
        return rows
