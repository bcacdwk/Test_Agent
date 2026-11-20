"""``smu_stepped``: a host loop over a step role, one SMU staircase sweep per step value (blueprint v1 2.6, M2; v2
2.7: ``step_i``).

Typical uses: an output family (Id-Vd: the drain sweeps for each gate level of a ``step_v`` role), a transfer family
(Id-Vg at several drain or bulk biases: DIBL, body effect) or a bipolar output family (the collector sweeps for each
base current of a ``step_i`` role).

Roles: everything ``smu_staircase`` accepts (sweep, synchronous, bias, ground and measure-only roles; same settings
and the same ``integration`` parameter) plus exactly one step role on an SMU: ``step_v`` (``DV`` per step, setting
``icomp`` required) or ``step_i`` (``DI`` per step, setting ``vcomp`` required), with either ``values`` (a
``$param`` of type ``float_list``) or ``start``, ``stop``, ``points`` (linear, ``points`` = 1 gives ``start`` only).
Step values are rounded to 1 nV (``step_v``) or 1 fA (``step_i``) and must be distinct (each curve is identified by
its step value). The step role may measure the other quantity (``I`` for ``step_v``, ``V`` for ``step_i``); measuring
what it forces is refused because its programmed level is the step column of the table.

Compile (pure): the staircase compiled with the step role as a bias at the first value, then the step channel's
envelope widened to every step value (``function: step_v``, ``v_start``/``v_stop`` = first/last value; ``step_i``:
|I| up to the largest step, |V| up to ``vcomp``), the estimate ``points`` = steps x sweep steps, ``duration`` = 1 s
+ steps x (sweep time + 0.2 s) and ``max_segment_s`` = one sweep with its setup allowance + 0.2 s (each step is one
segment between checkpoints, blueprint v2 2.6), and the FLEX preview = the staircase setup followed by
``DV``/``DI <step>`` and ``XE`` per step value.

Acquire (inside ONE transaction, through the guarded driver): the staircase setup (``configure_staircase``: FMT,
ADC, CN, ``ERRX?`` drain, bias DV/DIs, the sweep setup, ``ERRX?`` drain), then for each step value: ``DV``/``DI``
on the step channel, ``ERRX?`` drain (any error aborts before ``XE``), ``XE`` and one read (timeout ``2 x sweep
estimate + 10 s``). Each sweep runs with ``WM 2,1`` as in ``smu_staircase`` (automatic abort on compliance, overflow
or oscillation); in addition the host loop stops after a sweep that reported any of ``STOP_STATUSES`` (the later
steps usually drive harder), and ``kind_result`` records it: ``steps_planned``, ``steps_done``, ``stopped_early``,
``stop_reason``. After every step ``tx.checkpoint(step, steps, "sweep", rows)`` hands over the curve's table rows:
an asynchronous run (longer than ``max_sync_run_s``, e.g. many gate steps at long integration) records them in
``progress.json``/``partial.csv``, and any run stops there when ``safe_shutdown`` asked (``RunCancelled``).
Cleanup is the transaction's (``AB → DZ → CL → verify``).

Table (``data.csv`` contract of ``analysis/dataset.py``): the rows of each sweep in acquisition order with
``step`` running over the whole run (0-based, strictly increasing across curves), ``segment`` for double sweeps
(per curve), the sweep source columns (``staircase_rows``), measured ``<role>_<I|V>`` + ``_status``, constant bias
source columns, and the step source column ``<step role>_V`` or ``<step role>_I`` (e.g. ``gate_V``, ``base_I``):
the programmed step level, constant within a curve and distinct between curves, right after the primary sweep
column, so ``table.groupby("gate_V", sort=False)`` yields the family in acquisition order. Skipped steps have no
rows.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_staircase import (
    COMP_SETTINGS,
    LEVEL_SETTINGS,
    SETUP_OVERHEAD_S,
    SmuStaircaseKind,
    Source,
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

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

STEP_OVERHEAD_S = 0.2
"""Allowance per step for the step ``DV``, the ``ERRX?`` drain and the data transfer in the duration estimate."""

MAX_STEP_VALUES = 1001
"""Most step values one plan may hold (R-RUN-01 limits the points and the duration on top of this)."""

STOP_STATUSES = frozenset("CTVX")
"""Status letters after which the host loop stops: compliance (``C``, other channel ``T``), overflow or invalid
data (``V``) and oscillation (``X``), the same conditions that make ``WM 2`` abort a sweep."""

STEP_FUNCTIONS: dict[str, Source] = {"step_v": "V", "step_i": "I"}
"""Step role functions and what they force per step (``DV``/``DI``)."""

STEP_DIGITS: dict[Source, int] = {"V": 9, "I": 15}
"""Step values are rounded to this many decimal places (1 nV, 1 fA)."""


class SteppedProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    staircase: StaircaseProgram
    """The sweep run at every step; its biases and source columns exclude the step role."""
    step_role: str
    step_channel: Channel
    step_source: Source = "V"
    step_comp: float
    """Compliance of the step role: A for ``step_v`` (``DV``), V for ``step_i`` (``DI``)."""
    step_values: list[float] = Field(min_length=1, max_length=MAX_STEP_VALUES)
    sweep_estimate_s: float = Field(ge=0)
    """Estimated duration of one sweep (with the setup allowance): the base of the per-read timeout."""

    @property
    def points(self) -> int:
        """Points of the whole run (every step, every sweep step)."""
        return len(self.step_values) * self.staircase.steps

    @property
    def step_column(self) -> str:
        """The step source column of the table, ``<step role>_V`` or ``<step role>_I``."""
        return f"{self.step_role}_{self.step_source}"

    def step_command(self, value: float) -> str:
        """The FLEX text that sets the step role to ``value`` (preview)."""
        build = flex.dv if self.step_source == "V" else flex.di
        return build(self.step_channel, 0, value, self.step_comp)


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def step_values(name: str, role: RoleSpec, params: dict[str, Quantity], source: Source = "V") -> list[float]:
    """The step levels of role ``name``: setting ``values`` (a ``float_list``) or ``start``/``stop``/``points``
    (linear); rounded to ``STEP_DIGITS[source]`` decimals; non-empty and distinct. Raises ``CompileError``."""
    listed = setting_value(role, "values", params)
    ranged = [key for key in ("start", "stop", "points") if key in role.settings]
    if listed is not None or "values" in role.settings:
        if ranged:
            raise CompileError(f"{name}: give either values or start/stop/points, not both")
        if not isinstance(listed, list) or not listed:
            raise CompileError(f"{name}.values must be a non-empty list of levels, got {listed!r}")
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
    values = [round(v, STEP_DIGITS[source]) + 0.0 for v in raw]  # + 0.0 turns -0.0 into 0.0
    if len(set(values)) != len(values):
        raise CompileError(f"{name}: step values must be distinct (each curve is identified by its step value), "
                           f"got {values}")
    return values


class SmuSteppedKind:
    """Host loop over a ``step_v``/``step_i`` role with one staircase sweep per step (sim and visa code path)."""

    kind_id = "smu_stepped"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program; see the module docstring."""
        steps = [name for name, role in recipe.roles.items() if role.function in STEP_FUNCTIONS]
        if len(steps) != 1:
            raise CompileError(f"{self.kind_id} needs exactly one step_v or step_i role; recipe {recipe.id} has "
                               f"{steps}")
        step_name = steps[0]
        step_role = recipe.roles[step_name]
        source = STEP_FUNCTIONS[step_role.function]
        if source in step_role.measure:
            raise CompileError(f"step role {step_name} must not measure {source}: its programmed level is the "
                               f"{step_name}_{source} column")
        values = step_values(step_name, step_role, params, source)
        comp_name = COMP_SETTINGS[source]
        comp = _number(setting_value(step_role, comp_name, params), f"{step_name}.{comp_name}")
        as_bias = step_role.model_copy(update={"function": "bias_v" if source == "V" else "bias_i",
                                               "settings": {LEVEL_SETTINGS[source]: values[0], comp_name: comp}})
        base_recipe = recipe.model_copy(update={"roles": {**recipe.roles, step_name: as_bias}})
        try:
            base = SmuStaircaseKind().compile(base_recipe, params, binding, station)
        except CompileError as exc:
            raise CompileError(f"{self.kind_id} (per-step sweep): {exc}") from None
        channels = dict(base.envelope.channels)
        bound = binding.roles.get(step_name)
        step_channel = bound.channel if bound is not None else None
        if step_channel is not None:
            peak = max(abs(v) for v in values)
            if source == "V":
                channels[step_channel] = ChannelEnvelope(role=step_name, max_abs_v=peak, max_abs_i=abs(comp),
                                                         function="step_v", v_start=values[0], v_stop=values[-1])
            else:
                channels[step_channel] = ChannelEnvelope(role=step_name, max_abs_v=abs(comp), max_abs_i=peak,
                                                         function="step_i")
        envelope = CompiledEnvelope(channels=channels)
        if not base.program or step_channel is None:
            # The sweep or the step role is not bound to a channel: the plan-phase rules block the plan (R-PIN-01).
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
        sweep = StaircaseProgram.model_validate(base.program)
        sweep_estimate = base.estimate.duration_s
        step_column = f"{step_name}_{source}"
        staircase = StaircaseProgram.model_validate({
            **sweep.dump(),
            "biases": [b.model_dump(mode="json") for b in sweep.biases if b.role != step_name],
            "source_columns": {c: v for c, v in sweep.source_columns.items() if c != step_column},
        })
        program = SteppedProgram(staircase=staircase, step_role=step_name, step_channel=step_channel,
                                 step_source=source, step_comp=comp, step_values=values,
                                 sweep_estimate_s=sweep_estimate)
        duration = SETUP_OVERHEAD_S + len(values) * (sweep_estimate - SETUP_OVERHEAD_S + STEP_OVERHEAD_S)
        estimate = Estimate(points=program.points, duration_s=round(duration, 6),
                            max_segment_s=round(sweep_estimate + STEP_OVERHEAD_S, 6))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self.preview(program),
                                program=program.model_dump(mode="json", exclude=None if program.staircase.ranges
                                                           else {"staircase": {"ranges"}}))

    @staticmethod
    def preview(program: SteppedProgram) -> list[str]:
        """The writes ``acquire`` sends, in order: the staircase setup, then ``DV``/``DI`` + ``XE`` per step value
        (``ERRX?`` drains are not listed)."""
        lines = SmuStaircaseKind.preview(program.staircase)[:-1]  # everything but the final XE
        for value in program.step_values:
            lines.append(program.step_command(value))
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
        unit = "V" if program.step_source == "V" else "A"
        for index, value in enumerate(program.step_values):
            if program.step_source == "V":
                tx.driver.force_v(program.step_channel, value, icomp=program.step_comp)
            else:
                tx.driver.force_i(program.step_channel, value, vcomp=program.step_comp)
            drain_or_raise(tx, f"setting {program.step_role} to step {index}")
            tx.mark(f"step {index}: {program.step_role} = {value:g} {unit}")
            block = tx.driver.execute_and_read(expected_points=sweep.steps * sweep.width, timeout_s=timeout)
            blocks.append(block)
            tx.checkpoint(index + 1, total, "sweep",
                          rows=lambda i=index, v=value, b=block: self.curve_rows(program, i, v, b))
            flagged = sorted({str(p.status.value) for p in block.points if str(p.status.value) in STOP_STATUSES})
            if flagged and index < last:
                stop_reason = (f"step {index} ({program.step_role} = {value:g} {unit}) reported status "
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
        run and the step source column right after the primary sweep column (also the ``partial.csv`` rows)."""
        sweep = program.staircase
        sweep_source = f"{sweep.sweep_role}_{sweep.sweep.source}"
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
