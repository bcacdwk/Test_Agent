"""``stress_measure``: composite stress -> reads at log or list times -> optional recovery reads, built from the shared
blocks of ``catalog/blocks.py`` (blueprint v2 2.7, decision table row 5; 3.1 rows ``reliability.bti_sms``,
``igzo.bias_stress``, ``reliability.hci``, ``reliability.silc``). No step language: recipes choose the read, the
schedule and the levels by parameters only.

Roles (bound through the pin map; every role is an SMU forcing voltage, each measured role measures one quantity):

- ``sweep_v`` (at most one): the read sweep of a staircase read (settings ``start``, ``stop``, ``points``, ``icomp``,
  optional ``scale``, ``hold``, ``delay``; single sweeps only: a double sweep's ``segment`` column has no meaning on a
  stress row) and, for a spot read, the read level ``v``;
- ``bias_v``: the read level ``v`` and ``icomp``;
- both: ``stress`` (V, required: the level during the stress holds) and ``recovery`` (V, default 0: the level during
  the recovery holds); the compliance ``icomp`` holds in every phase;
- ``ground`` / ``measure_only``: the GNDU or an SMU at 0 V in every phase (compliance ``icomp`` or the sum of the
  sourcing compliances, as ``smu_staircase``);
- every other function is refused (pulse, WGFMU and current-forcing stress arrive with their kinds).

Recipe parameters read by name: ``read_kind`` (``staircase``, the default with a ``sweep_v`` role: one Id-Vg-like
sweep per read, compiled exactly as ``smu_staircase``; ``spot``: ``samples`` spot measurements per read at the read
levels, compiled as ``smu_spot`` with the sweep role at its ``v``), ``schedule`` (``log``, the default: reads at
``first_read x 10^(k/reads_per_decade)`` below ``stress_time`` and at ``stress_time``; ``list``: the cumulative stress
times ``read_times``, plus ``stress_time`` when it is later), ``stress_time`` (s), ``first_read`` (s, at least
``MIN_READ_S``), ``reads_per_decade``, ``read_times`` (s), ``recovery_time`` (s, 0 = no recovery; recovery reads
log-spaced from ``first_read`` to it), ``integration`` and ``samples`` (the read kinds' parameters). Times lie on the
10 ms grid of the instrument's hold timer; at most ``MAX_READS`` reads after the reference read.

Run (one transaction, guarded driver only, blocks of ``catalog/blocks.py``): ``apply_routes`` (ASU paths of roles
bound through an ASU), ``open_outputs`` (``TSC 0``, ``AAD``/``AIT``, ``CN``, ``ERRX?`` drain, ``LOP?`` positive control
on hardware), the reference read (cycle 0, before any stress), then per cycle ``k``: ``hold_bias`` at the stress (or
recovery) levels for the time to the next read (at every phase change the outputs whose level falls are set first:
``blocks.ordered``), in instrument-timed ``MM 10`` blocks of at most 25 s with one monitor
sample of every measured role at the end of each block (the stress current: gate leakage under BTI, drain current
under HCI, the injected current under a SILC stress), and the read ``k``. Checkpoints: one per hold block and one
per read (``tx.checkpoint``: progress, ``partial.csv``, cancel via ``safe_shutdown``; long stresses run
asynchronously). The run stops after a hold block or a read that reported compliance, overflow or oscillation
(``STOP_STATUSES``: a broken gate, a changed device or wrong read compliances; the later cycles would stress a device
that already failed): ``kind_result`` says why (``stop_reason``, also when the flagged read was the last one;
``stopped_early`` when reads or hold blocks were left). Cleanup is the transaction's; the outputs never return to
0 V between phases (the stress is interrupted only by the reads).

Table (``data.csv`` contract): every row has ``step`` (0-based over the run), ``t_s`` (the cumulative hold time in
seconds at the row: stress time for the stress holds and reads, stress plus recovery time afterwards; the reads
interrupt this clock, so it is the stress time of a stress-measure-stress test), ``cycle`` (the read index; hold rows
carry the cycle of the read they lead to; 0 = the reference read), ``phase`` (``read`` for read rows, ``stress`` or
``recovery`` for the monitor rows of a hold), the programmed source columns ``<role>_V`` (read rows: the read's
sweep or bias values; hold rows: the hold levels), ``<role>_range`` labels of ranged spot reads (empty on hold rows)
and every measured ``<role>_<I|V>`` + ``_status``. A read is a stress read or a recovery read by the phase of the hold
rows of its cycle (``analysis/stress.py``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.blocks import (
    HOLD_GRID_S,
    HOLD_OVERHEAD_S,
    STOP_STATUSES,
    HoldResult,
    Monitor,
    ReadSpec,
    RouteStep,
    apply_routes,
    flagged_statuses,
    hold_bias,
    hold_chunks,
    open_outputs,
    ordered,
    read,
    read_blocks,
    route_steps,
)
from b1500_test_agent.catalog.kinds.smu_spot import SmuSpotKind, SpotProgram
from b1500_test_agent.catalog.kinds.smu_staircase import (
    READ_TIMEOUT_MARGIN_S,
    SETUP_OVERHEAD_S,
    BiasOutput,
    SmuStaircaseKind,
    StaircaseProgram,
    bias_command,
    read_timeout_s,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, RawBlock
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration
from b1500_test_agent.models.plan import ChannelBinding, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.sources import DcStress, SourcePlan, StressSchedule
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

STRESS_FUNCTIONS = frozenset({"sweep_v", "bias_v", "ground", "measure_only"})
"""Role functions this kind executes."""

LEVELED_FUNCTIONS = frozenset({"sweep_v", "bias_v"})
"""Roles with a level per phase (settings ``stress``, ``recovery`` and the read levels)."""

STRESS_SETTING = "stress"
RECOVERY_SETTING = "recovery"
READ_LEVEL_SETTING = "v"

READ_KIND_PARAM = "read_kind"
SCHEDULE_PARAM = "schedule"
STRESS_TIME_PARAM = "stress_time"
FIRST_READ_PARAM = "first_read"
READS_PER_DECADE_PARAM = "reads_per_decade"
READ_TIMES_PARAM = "read_times"
RECOVERY_TIME_PARAM = "recovery_time"
READ_KINDS = ("staircase", "spot")
SCHEDULES = ("log", "list")

MAX_READS = 200
"""Most reads of one plan after the reference read (stress and recovery reads together)."""

MIN_READ_S = 0.02
"""Shortest time to the first read (s): one hold block of the monitor interval."""

MAX_READS_PER_DECADE = 20

READ_OVERHEAD_S = 0.2
"""Allowance per read for its level and setup commands and the ``ERRX?`` drain in the duration estimate."""

Phase = Literal["stress", "recovery"]


class HoldSegment(StrictModel):
    """The hold before read ``cycle``: its phase and programmed length (s, on the 10 ms grid)."""

    cycle: int = Field(ge=1)
    phase: Phase
    seconds: float = Field(gt=0)


class StressProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    integration: Integration
    enable: list[Channel] = Field(min_length=1)
    routes: list[RouteStep] = Field(default_factory=list)
    read: ReadSpec
    monitor: Monitor
    stress: list[BiasOutput] = Field(default_factory=list)
    """Levels of the ``sweep_v``/``bias_v`` roles during a stress hold (grounded SMUs stay at 0 V from the reads)."""
    recovery: list[BiasOutput] = Field(default_factory=list)
    hold_columns: dict[str, dict[str, float]] = Field(default_factory=dict)
    """Source columns of the hold rows per phase (``<role>_V`` at the hold level)."""
    segments: list[HoldSegment] = Field(default_factory=list)
    sources: SourcePlan = Field(default_factory=SourcePlan)
    """The typed stress levels and schedule (``plan.program["sources"]``, ``models.sources``) the plan summary shows."""
    columns: list[str] = Field(min_length=2)
    """Every column of every row, in order (``partial.csv`` keeps one header)."""
    read_estimate_s: float = Field(ge=0)

    @property
    def reads(self) -> int:
        """Reads including the reference read."""
        return 1 + len(self.segments)

    def outputs(self, phase: Phase) -> list[BiasOutput]:
        return self.stress if phase == "stress" else self.recovery

    def timeline(self) -> list[Op]:
        """Every checkpoint of the run in order: the reference read, then per segment its hold blocks and its read,
        with the cumulative hold time ``t_s`` at the end of each."""
        ops = [Op(0, "read", 0, "read")]
        t = 0.0
        for segment in self.segments:
            for h_bias in hold_chunks(segment.seconds, self.monitor.period):
                t += h_bias + self.monitor.period
                ops.append(Op(len(ops), "hold", segment.cycle, segment.phase, h_bias, round(t, 9)))
            ops.append(Op(len(ops), "read", segment.cycle, "read", 0.0, round(t, 9)))
        return ops


@dataclass(frozen=True)
class Op:
    """One checkpoint unit of the run: a read or one hold block (``h_bias``), its cycle and phase, and the cumulative
    hold time ``t_s`` at its end."""

    index: int
    kind: Literal["read", "hold"]
    cycle: int
    phase: Literal["read", "stress", "recovery"]
    h_bias: float = 0.0
    t_s: float = 0.0


# -- helpers ---------------------------------------------------------------------------------------------------------


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _param(params: dict[str, Quantity], name: str, default: Any = None) -> Any:
    quantity = params.get(name)
    return default if quantity is None else quantity.value


def _grid(value: float) -> float:
    return round(round(value / HOLD_GRID_S) * HOLD_GRID_S, 2)


def _seconds(params: dict[str, Quantity], name: str, default: float | None = None, *, minimum: float) -> float:
    value = _number(_param(params, name, default), name)
    if value < minimum:
        raise CompileError(f"{name} must be at least {minimum:g} s, got {value:g}")
    return _grid(value)


def log_times(first: float, last: float, per_decade: int) -> list[float]:
    """Read times ``first x 10^(k/per_decade)`` below ``last``, then ``last``; on the 10 ms grid, increasing."""
    times: list[float] = []
    k = 0
    while True:
        t = _grid(first * 10.0 ** (k / per_decade))
        if t >= last - 1e-9:
            break
        if t > 0 and (not times or t > times[-1]):
            times.append(t)
        k += 1
    times.append(_grid(last))
    return times


def schedule(params: dict[str, Quantity]) -> tuple[list[float], list[float]]:
    """``(stress read times, recovery read times)``: cumulative stress times, then cumulative recovery times (s)."""
    mode = _param(params, SCHEDULE_PARAM, "log")
    if mode not in SCHEDULES:
        raise CompileError(f"{SCHEDULE_PARAM} must be one of {list(SCHEDULES)}, got {mode!r}")
    stress_time = _seconds(params, STRESS_TIME_PARAM, minimum=MIN_READ_S)
    first = _seconds(params, FIRST_READ_PARAM, 1.0, minimum=MIN_READ_S)
    per_decade = _param(params, READS_PER_DECADE_PARAM, 3)
    if isinstance(per_decade, float) and per_decade.is_integer():
        per_decade = int(per_decade)
    if isinstance(per_decade, bool) or not isinstance(per_decade, int) or not 1 <= per_decade <= MAX_READS_PER_DECADE:
        raise CompileError(f"{READS_PER_DECADE_PARAM} must be an integer 1 to {MAX_READS_PER_DECADE}, got "
                           f"{per_decade!r}")
    if mode == "log":
        stress = log_times(first, stress_time, per_decade)
    else:
        listed = _param(params, READ_TIMES_PARAM)
        if not isinstance(listed, list) or not listed:
            raise CompileError(f"{SCHEDULE_PARAM} list needs {READ_TIMES_PARAM} (cumulative stress times, s)")
        stress = [_grid(_number(v, f"{READ_TIMES_PARAM}[{i}]")) for i, v in enumerate(listed)]
        if any(t < MIN_READ_S for t in stress) or any(b <= a for a, b in pairwise(stress)):
            raise CompileError(f"{READ_TIMES_PARAM} must increase strictly from at least {MIN_READ_S:g} s on the "
                               f"10 ms grid, got {listed}")
        if stress[-1] > stress_time + 1e-9:
            raise CompileError(f"{READ_TIMES_PARAM} ends at {stress[-1]:g} s, after {STRESS_TIME_PARAM} "
                               f"{stress_time:g} s")
        if stress[-1] < stress_time - 1e-9:
            stress.append(stress_time)
    recovery_time = _number(_param(params, RECOVERY_TIME_PARAM, 0.0), RECOVERY_TIME_PARAM)
    if recovery_time < 0:
        raise CompileError(f"{RECOVERY_TIME_PARAM} must be >= 0 s, got {recovery_time:g}")
    recovery = log_times(first, _grid(recovery_time), per_decade) if recovery_time > 0 else []
    if recovery and recovery[-1] < MIN_READ_S:
        raise CompileError(f"{RECOVERY_TIME_PARAM} must be 0 or at least {MIN_READ_S:g} s")
    if len(stress) + len(recovery) > MAX_READS:
        raise CompileError(f"{len(stress) + len(recovery)} reads exceed {MAX_READS}; use fewer "
                           f"{READS_PER_DECADE_PARAM} or a shorter list")
    return stress, recovery


def segments_of(stress: Sequence[float], recovery: Sequence[float]) -> list[HoldSegment]:
    """The holds between consecutive reads (cumulative times -> lengths)."""
    out: list[HoldSegment] = []
    for phase, times in (("stress", stress), ("recovery", recovery)):
        previous = 0.0
        for t in times:
            out.append(HoldSegment(cycle=len(out) + 1, phase=phase, seconds=_grid(t - previous)))  # type: ignore[arg-type]
            previous = t
    return out


# -- table -----------------------------------------------------------------------------------------------------------


class _Rows:
    """Turns the blocks of one run, op by op, into table rows with one column set (shared by ``acquire``'s
    checkpoints and ``to_table``)."""

    def __init__(self, program: StressProgram) -> None:
        self.program = program
        self.step = 0

    def _uniform(self, row: dict[str, object]) -> dict[str, object]:
        missing = [c for c in self.program.columns if c not in row and not c.endswith("_range")]
        if missing:
            raise ValueError(f"row {row.get('step')} lacks {missing}")
        return {c: row.get(c, "") for c in self.program.columns}

    def read(self, op: Op, blocks: Sequence[RawBlock]) -> list[dict[str, object]]:
        """Rows of one read (``read_blocks``) with the context columns."""
        rows = read_blocks(self.program.read, blocks, first_step=self.step)
        out = [self._uniform({**row, "t_s": op.t_s, "cycle": op.cycle, "phase": "read"}) for row in rows]
        self.step += len(out)
        return out

    def hold(self, op: Op, block: RawBlock) -> list[dict[str, object]]:
        """The monitor row of one hold block: hold levels and the measured values at its end."""
        row: dict[str, object] = {"step": self.step, "t_s": op.t_s, "cycle": op.cycle, "phase": op.phase,
                                  **self.program.hold_columns.get(op.phase, {})}
        for column, value, status in self.program.monitor.values(block):
            name = f"{column.role}_{column.quantity}"
            row[name] = value
            row[f"{name}_status"] = status
        self.step += 1
        return [self._uniform(row)]


# -- the kind --------------------------------------------------------------------------------------------------------


class StressMeasureKind:
    """Composite stress -> reads -> recovery reads (sim and visa code path; see the module docstring)."""

    kind_id = "stress_measure"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope (every phase), estimate, FLEX preview and program; see the module docstring."""
        sweeps = self._check_roles(recipe)
        read_kind = _param(params, READ_KIND_PARAM, "staircase" if sweeps else "spot")
        if read_kind not in READ_KINDS:
            raise CompileError(f"{READ_KIND_PARAM} must be one of {list(READ_KINDS)}, got {read_kind!r}")
        levels = self._levels(recipe, params)
        base = self._read_plan(recipe, params, binding, station, read_kind, sweeps)
        channels = dict(base.envelope.channels)
        stress: list[BiasOutput] = []
        recovery: list[BiasOutput] = []
        hold_columns: dict[str, dict[str, float]] = {"stress": {}, "recovery": {}}
        measured = {(name, q) for name, role in recipe.roles.items() for q in role.measure}
        for name, (stress_v, recovery_v, icomp) in levels.items():
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue
            entry = channels.get(bound.channel)
            if entry is not None:
                peak = max(entry.max_abs_v, abs(stress_v), abs(recovery_v))
                channels[bound.channel] = entry.model_copy(update={"max_abs_v": peak})
            stress.append(BiasOutput(role=name, channel=bound.channel, level=stress_v, comp=icomp))
            recovery.append(BiasOutput(role=name, channel=bound.channel, level=recovery_v, comp=icomp))
            if (name, "V") not in measured:
                hold_columns["stress"][f"{name}_V"] = stress_v
                hold_columns["recovery"][f"{name}_V"] = recovery_v
        routes = route_steps(binding, station, kind_id=self.kind_id)
        envelope = CompiledEnvelope(channels=channels, routes=frozenset(s.route for s in routes))
        if not base.program:
            # A read role is not bound to a channel: the plan-phase rules block the plan (R-PIN-01).
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
        spec, integration, read_points, read_s = self._read_spec(read_kind, base)
        stress_times, recovery_times = schedule(params)
        monitor = Monitor.of(spec.measure, integration)
        enable = [b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                  and b.channel is not None]
        sources = SourcePlan(
            stress={o.channel: DcStress(level_v=o.level, recovery_v=r.level) for o, r in zip(stress, recovery,
                                                                                              strict=True)},
            schedule=StressSchedule(stress_s=stress_times[-1], reads=len(stress_times),
                                    recovery_s=recovery_times[-1] if recovery_times else 0.0,
                                    recovery_reads=len(recovery_times)))
        program = StressProgram(
            integration=integration, enable=enable, routes=routes, read=spec, monitor=monitor, stress=stress,
            recovery=recovery, hold_columns={k: v for k, v in hold_columns.items() if v},
            segments=segments_of(stress_times, recovery_times), sources=sources,
            columns=self._columns(spec, hold_columns), read_estimate_s=round(read_s, 6))
        ops = program.timeline()
        holds = [op for op in ops if op.kind == "hold"]
        spans = [op.h_bias + monitor.period + HOLD_OVERHEAD_S for op in holds]
        duration = SETUP_OVERHEAD_S + program.reads * read_s + sum(spans)
        estimate = Estimate(points=program.reads * read_points + len(holds), duration_s=round(duration, 6),
                            max_segment_s=round(max([read_s, *spans]), 6))
        routes_by_phase = {"setup": [s.route for s in routes]} if routes else {}
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self.preview(program),
                                program=program.model_dump(mode="json"), routes_by_phase=routes_by_phase)

    def _check_roles(self, recipe: Recipe) -> list[str]:
        """The ``sweep_v`` role names after the role-function checks (``CompileError``)."""
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in STRESS_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(STRESS_FUNCTIONS))}")
        sweeps = [name for name, role in recipe.roles.items() if role.function == "sweep_v"]
        if len(sweeps) > 1:
            raise CompileError(f"{self.kind_id} reads with at most one sweep_v role; recipe {recipe.id} has {sweeps}")
        if not any(role.measure for role in recipe.roles.values()):
            raise CompileError(f"recipe {recipe.id}: no role measures anything")
        return sweeps

    @staticmethod
    def _levels(recipe: Recipe, params: dict[str, Quantity]) -> dict[str, tuple[float, float, float]]:
        """``{role: (stress level, recovery level, icomp)}`` of every ``sweep_v``/``bias_v`` role."""
        levels: dict[str, tuple[float, float, float]] = {}
        for name, role in recipe.roles.items():
            if role.function not in LEVELED_FUNCTIONS:
                continue
            stress = setting_value(role, STRESS_SETTING, params)
            if stress is None:
                raise CompileError(f"{name}: a {role.function} role needs setting {STRESS_SETTING} (its level during "
                                   "the stress, V)")
            icomp = _number(setting_value(role, COMPLIANCE_SETTING, params), f"{name}.{COMPLIANCE_SETTING}")
            levels[name] = (_number(stress, f"{name}.{STRESS_SETTING}"),
                            _number(setting_value(role, RECOVERY_SETTING, params, 0.0), f"{name}.{RECOVERY_SETTING}"),
                            icomp)
        return levels

    def _read_plan(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                   station: StationProfile, read_kind: str, sweeps: list[str]) -> CompiledKindPlan:
        """The read compiled by its own kind: ``smu_staircase`` as is, or ``smu_spot`` with the sweep role held at its
        read level ``v``."""
        if read_kind == "staircase":
            if not sweeps:
                raise CompileError(f"{READ_KIND_PARAM} staircase needs a sweep_v role (the read sweep)")
            return SmuStaircaseKind().compile(recipe, params, binding, station)
        roles: dict[str, RoleSpec] = {}
        for name, role in recipe.roles.items():
            if role.function == "sweep_v":
                if READ_LEVEL_SETTING not in role.settings:
                    raise CompileError(f"{READ_KIND_PARAM} spot reads the sweep role {name} at its setting "
                                       f"{READ_LEVEL_SETTING}, which it lacks")
                role = role.model_copy(update={"function": "bias_v"})
            if "values" in role.settings or "ranges" in role.settings:
                raise CompileError(f"{name}: level lists and range surveys belong to smu_spot, not to a stress read")
            roles[name] = role
        return SmuSpotKind().compile(recipe.model_copy(update={"roles": roles}), params, binding, station)

    @staticmethod
    def _read_spec(read_kind: str, base: CompiledKindPlan) -> tuple[ReadSpec, Integration, int, float]:
        """The read spec, integration, points and estimated duration (s) of one read."""
        if read_kind == "staircase":
            staircase = StaircaseProgram.model_validate(base.program)
            if staircase.sweep.double:
                raise CompileError("a stress read is a single sweep (mode single): the segment of a double sweep has "
                                   "no meaning on the stress rows")
            seconds = base.estimate.duration_s - SETUP_OVERHEAD_S + READ_OVERHEAD_S
            spec = ReadSpec(kind="staircase", staircase=staircase, timeout_s=read_timeout_s(base.estimate))
            return spec, staircase.integration, staircase.steps, seconds
        spot = SpotProgram.model_validate(base.program)
        seconds = base.estimate.duration_s - SETUP_OVERHEAD_S + READ_OVERHEAD_S
        spec = ReadSpec(kind="spot", spot=spot, timeout_s=2.0 * spot.row_estimate_s + READ_TIMEOUT_MARGIN_S)
        return spec, spot.integration, spot.rows, seconds

    @staticmethod
    def _columns(spec: ReadSpec, hold_columns: dict[str, dict[str, float]]) -> list[str]:
        """The run's columns: context, range labels (ranged spot reads), source columns, measured values + status."""
        ranges = [f"{r.role}_range" for r in spec.spot.ranges] if spec.spot is not None else []
        sources = list(hold_columns["stress"])
        measured: list[str] = []
        for m in spec.measure:
            measured += [f"{m.role}_{m.quantity}", f"{m.role}_{m.quantity}_status"]
        return ["step", "t_s", "cycle", "phase", *ranges, *sources, *measured]

    @staticmethod
    def preview(program: StressProgram) -> list[str]:
        """Every write ``acquire`` sends, in order (``ERRX?`` drains and the ``LOP?`` control are not listed)."""
        integration = program.integration
        adc = ADC_TYPE_CODES[integration.adc]
        measure = program.read.measure
        lines = [flex.sap(s.index, flex.ASU_PATH_CODES[s.route.state]) for s in program.routes]
        lines.append(flex.tsc(False))
        lines += [flex.aad(m.channel, adc) for m in measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n))
        lines.append(flex.cn(program.enable))
        monitor = program.monitor
        after_read = program.read.levels_after()
        lines += StressMeasureKind._read_lines(program.read, None)
        for segment in program.segments:
            outputs = program.outputs(segment.phase)
            lines += [bias_command(o) for o in ordered(outputs, after_read)]
            lines.append(flex.fmt(1, 1))
            previous: float | None = None
            for h_bias in hold_chunks(segment.seconds, monitor.period):
                setup = monitor.setup(h_bias)
                if previous is None:
                    lines += [flex.mcc(), flex.ml(setup.mode), flex.mt(h_bias, setup.interval, 1, 0.0),
                              flex.msc(setup.abort, setup.post), flex.mm(flex.SAMPLING_MODE, setup.measure),
                              *(flex.cmm(ch, op) for ch, op in setup.operation.items())]
                elif h_bias != previous:
                    lines.append(flex.mt(h_bias, setup.interval, 1, 0.0))
                previous = h_bias
                lines.append(flex.XE)
            lines += StressMeasureKind._read_lines(program.read, {o.channel: o.level for o in outputs})
        return lines

    @staticmethod
    def _read_lines(spec: ReadSpec, previous: dict[int, float] | None) -> list[str]:
        if spec.kind == "staircase":
            assert spec.staircase is not None
            staircase = spec.staircase
            return [flex.fmt(*staircase.data_format), *(bias_command(b) for b in ordered(staircase.biases, previous)),
                    *staircase.sweep.commands(), *(flex.ri(r.channel, r.code) for r in staircase.ranges), flex.XE]
        assert spec.spot is not None
        spot = spec.spot
        return [flex.fmt(*spot.data_format), *(bias_command(o) for o in ordered(spot.outputs, previous)),
                flex.mm(1, [m.channel for m in spot.measure]),
                *(flex.cmm(m.channel, 1 if m.quantity == "I" else 2) for m in spot.measure),
                *(flex.ri(r.channel, r.code) for r in spot.ranges), *([flex.XE] * spot.samples)]

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints ``acquire`` reports: one per read and one per hold block (fewer when the run stops early)."""
        return len(StressProgram.model_validate(plan.program).timeline()) if plan.program else 0

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = StressProgram.model_validate(plan.program)
        ops = program.timeline()
        total = len(ops)
        rows = _Rows(program)
        blocks: list[RawBlock] = []
        position = 0
        stop_reason = ""
        apply_routes(tx, program.routes)
        open_outputs(tx, program.integration, program.read.measure, program.enable)

        def do_read(op: Op, previous: dict[int, float] | None) -> list[RawBlock]:
            taken = read(tx, program.read, previous)
            blocks.extend(taken)
            tx.checkpoint(op.index + 1, total, "read", rows=lambda: rows.read(op, taken))
            return taken

        reference = do_read(ops[0], None)
        after_read = program.read.levels_after()
        flagged = flagged_statuses(reference)
        if flagged:
            stop_reason = f"the reference read reported status {','.join(flagged)}"
        for segment in [] if stop_reason else program.segments:
            position = next(i for i, op in enumerate(ops) if op.cycle == segment.cycle and op.kind == "hold")
            tx.mark(f"cycle {segment.cycle}: {segment.phase} {segment.seconds:g} s")

            def on_block(index: int, _h_bias: float, block: RawBlock, first: int = position) -> None:
                op = ops[first + index]
                tx.checkpoint(op.index + 1, total, op.phase, rows=lambda: rows.hold(op, block))

            outputs = program.outputs(segment.phase)
            held: HoldResult = hold_bias(tx, outputs, segment.seconds, program.monitor, on_block=on_block,
                                         label=f"{segment.phase} cycle {segment.cycle}", previous=after_read)
            blocks.extend(held.blocks)
            if held.stopped:
                stop_reason = held.reason
                break
            taken = do_read(ops[position + len(held.blocks)], {o.channel: o.level for o in outputs})
            flagged = flagged_statuses(taken)
            if flagged:
                stop_reason = f"read {segment.cycle} reported status {','.join(flagged)}"
                break
        if stop_reason:
            tx.mark("stopped: " + stop_reason)
        tx.mark("data read")
        return RawAcquisition(blocks=blocks, kind_result=self._result(program, ops, len(blocks), stop_reason))

    @staticmethod
    def _result(program: StressProgram, ops: list[Op], read_blocks_done: int, stop_reason: str) -> dict[str, Any]:
        done = _replay(program, ops, read_blocks_done)
        holds = [op for op in ops if op.kind == "hold"]
        stress_end = max((op.t_s for op in holds if op.phase == "stress"), default=0.0)
        recovery_end = max((op.t_s for op in holds if op.phase == "recovery"), default=stress_end)
        finished = [op for op in done if op.kind == "hold"]
        stress_done = max((op.t_s for op in finished if op.phase == "stress"), default=0.0)
        recovery_done = max((op.t_s for op in finished if op.phase == "recovery"), default=stress_done)
        return {"read_kind": program.read.kind, "reads_planned": program.reads,
                "reads_done": sum(1 for op in done if op.kind == "read"), "holds_planned": len(holds),
                "holds_done": len(finished), "stress_s_planned": stress_end, "stress_s_done": stress_done,
                "recovery_s_planned": round(recovery_end - stress_end, 9),
                "recovery_s_done": round(max(0.0, recovery_done - stress_end), 9),
                "stopped_early": len(done) < len(ops), "stop_reason": stop_reason}

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """Tidy table over every read and hold block (module docstring).

        Raises:
            ValueError: If the blocks do not end at a read or hold boundary or do not hold the programmed elements.
        """
        program = StressProgram.model_validate(plan.program)
        ops = program.timeline()
        rows = _Rows(program)
        table: list[dict[str, object]] = []
        cursor = 0
        for op in _replay(program, ops, len(raw.blocks)):
            width = program.read.blocks if op.kind == "read" else 1
            chunk = raw.blocks[cursor:cursor + width]
            cursor += width
            table += rows.read(op, chunk) if op.kind == "read" else rows.hold(op, chunk[0])
        if not table:
            raise ValueError(f"{self.kind_id}: no data block")
        return pd.DataFrame(table)


def _replay(program: StressProgram, ops: list[Op], blocks: int) -> list[Op]:
    """The ops completed by ``blocks`` data blocks, in order.

    Raises:
        ValueError: If ``blocks`` does not end at an op boundary or exceeds the plan.
    """
    left = blocks
    done: list[Op] = []
    for op in ops:
        width = program.read.blocks if op.kind == "read" else 1
        if left <= 0:
            break
        if left < width:
            raise ValueError(f"{left} block(s) left for {op.kind} {op.index} ({width} expected)")
        done.append(op)
        left -= width
    if left:
        raise ValueError(f"{blocks} blocks exceed the {len(ops)} reads and hold blocks of the plan")
    return done


__all__ = ["STOP_STATUSES", "HoldSegment", "Op", "StressMeasureKind", "StressProgram", "log_times", "schedule",
           "segments_of"]
