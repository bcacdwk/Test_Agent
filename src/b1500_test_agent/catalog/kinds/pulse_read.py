"""``pulse_read``: composite program/read kind (blueprint v2 2.7, decision table row 5; 3.3 rows
``fefet.pulse_write_read``, ``spgu.program_smu_read``; WP9.4): route -> pulse source -> route back -> read, per cycle,
built from the shared blocks of ``catalog/blocks.py`` and the sources of ``catalog/kinds/pulse_sources.py``. No step
language: recipes choose the source (by the pulse role's function), the operations, the read and the schedule by
parameters only.

**Roles.** Exactly one pulse role: ``pgu`` (HV-SPGU source), ``pulse_v`` (SMU pulse source) or ``wgfmu`` (the WGFMU
source arrives in WP10.6: refused at plan time, ``pulse_sources.source_for``); its settings give the operations
(``pulse_sources`` docstring: ``program``, ``erase``, ``base``, ``width``, ``erase_width``, and per source ``lead``,
``trail``, ``load_ohm`` or ``icomp``, ``meas_time``). The read roles are SMU roles ``sweep_v`` (the read sweep:
``start``, ``stop``, ``points``, ``icomp``, optional ``scale``, ``hold``, ``delay``; a spot read holds it at its ``v``),
``bias_v`` (read level ``v``, ``icomp``; ``pulse_bias``, V, default 0: its level while the pulses run), ``ground`` and
``measure_only`` (0 V), at least one of which measures. A read role may sit on the pulse role's pad: it declares that
terminal (``RoleSpec.terminal``, e.g. ``gate_read`` with ``terminal: gate``) and the pin map's switch target routes
each role to its own resource (``SEL1.OUT1`` -> ``pgu`` for the pulses, -> ``smu`` for the reads). An SMU pulse role is
also its pad's read source (an SMU can pulse and read): ``start``/``stop``/``points`` make it the read sweep, ``v``
its spot read level, ``icomp`` holds for both. Every other function is refused.

**Recipe parameters read by name:** ``schedule`` (``cycles``, ``grid``, ``retention``) and the schedule's own
parameters (``catalog/kinds/pulse_schedules.py``: ``sequence``, ``cycles``, ``cycle_reads``, ``reads_per_decade``,
``read_cycles``, ``cycle_period``, ``precycles``, ``amplitudes``, ``widths``, ``grid_mode``, ``reset_read``,
``retention_time``, ``first_read``, ``initial_read``: a reference read before the first pulse, default true),
``read_kind`` (``staircase``, the default with a sweep: one single sweep per read, compiled by ``smu_staircase``;
``spot``: ``samples`` spot measurements per read, compiled by ``smu_spot``; ``wgfmu`` arrives in WP10.6), ``settle``
(s, default 0: the wait between the route back and the read, in segments of at most ``WAIT_SEGMENT_S`` with a
checkpoint after each and abort checks every second; schedule ``retention`` times its reads by holds instead),
``integration``, ``samples``, and the sources' ``period`` and ``count``.

**Schedules** (WP9.5 adds ``grid`` and ``retention`` and the endurance checkpoints of ``cycles``): ``cycles`` repeats
the sequence with a read after every operation, or (endurance, ``cycle_reads`` ``log``/``list``) reads at checkpoint
cycle counts with the cycles in between run as bipolar cycling bursts of the HV-SPGU (three-level programs; ``bursts``
of at most 1,000,000 periods, ``cycle`` of the checkpoint reads = the cumulative cycle count); ``grid`` resets with the
sequence's first operation and pulses its second at each amplitude x width point (``reset`` or ``ispp``), the points
stored as ``grid`` (``GridPoint``; ``cycle`` of a point's reads = its index); ``retention`` writes each state of the
sequence once and reads it at log-spaced times after the write, holding the read SMUs at their pulse levels in ``MM 10``
hold blocks between the reads (``blocks.hold_bias``, monitor = the read's measured channels; one checkpoint per block).
``precycles`` runs cycling bursts before the first read.

**Routes** (``routes_by_phase``, in this order): one phase per operation of the sequence (``erase``, ``program``: the
pulse role's route, HV-SPGU source only), ``read`` (every read role's route, and an SMU pulse role's), ``rest`` (each
routed output back to its switch's rest state). The run applies ``read`` before ``CN``, then per operation its phase
before and ``read`` after the pulses, and ``rest`` at the end; every application is guarded, settled and read back
(``Transaction.apply_routes``), audited as checkpoint ``routes`` and logged per cycle in ``kind_result.routes``
(``start read SEL1.OUT1->smu; c1 erase SEL1.OUT1->pgu; c1 read SEL1.OUT1->smu; c1 program SEL1.OUT1->pgu; c1 read
SEL1.OUT1->smu; ...; end rest SEL1.OUT1->open``: PGU -> SMU per operation, rest at the end). The cleanup returns every
declared switch to rest and verifies it whatever happens.

**Run** (one transaction, guarded driver only): with an HV-SPGU ``SPST?`` must read 0; phase ``read``; ``TSC 0``,
``AAD``/``AIT`` of the measured channels, ``CN`` of the SMUs and the pulse channel, ``ERRX?`` drain, on hardware the
``LOP?`` positive control of the SMUs; then the steps in order (``pulse_schedules.build_steps``). A pulse operation or
cycling burst: every SMU output to its pulse level (falling first, ``blocks.ordered``: the read role on the pulsed pad
to 0 V before its relay switches, an SMU pulse role to its base), its phase's routes (an operation's own phase, a burst
``cycling``), the source's operation (``SpguSourceKind``/``SmuPulseSourceKind`` ``run``), phase ``read``, ``settle``
(pulse operations only). A read: the read levels, the sweep or spot setup, ``XE`` (``blocks.read``). A retention hold:
``blocks.hold_bias`` at the pulse levels. Finally phase ``rest``. Checkpoints: one per read, one per ``WAIT_SEGMENT_S``
of pulse output (at least one per operation or burst) and one per hold block; long plans run asynchronously (R-RUN-02)
and ``safe_shutdown`` cancels at the next checkpoint. A read, an SMU pulse reading or a hold block that reports
compliance, overflow or oscillation (``STOP_STATUSES``) stops the run (``kind_result.stop_reason``; the rest phase
still runs).

**Table** (``data.csv`` contract): one row per read point: ``step`` (0-based over the run), ``t_s`` (schedule
``retention`` only: the time after the write in seconds, empty for the reference read), ``cycle`` (0 = the reference
read; ``cycles``: 1..``cycles``, or the cumulative cycle count of an endurance checkpoint; ``grid``: the grid point;
``retention``: the read's index after its write), ``phase`` (``read`` for the reference read, else the operation the
read follows: ``program`` or ``erase``), ``<role>_range`` labels of ranged spot reads, the read's source columns (the
sweep value ``<sweep role>_V``, constant bias levels) and every measured ``<role>_<I|V>`` + ``_status``. The SMU pulse
readings (the pulsed channel's current at each pulse end) and the hold monitor samples are summarised in
``kind_result`` (``pulse_i_max_a``, ``pulse_statuses``; ``hold_blocks``, ``hold_i_max_a``), their raw blocks kept in
the audit log; the grid's amplitude and width per point are the stored program's ``grid`` (``analysis/nvm.py`` reads
them from the run manifest).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final, Literal

import pandas as pd
from pydantic import Field, ValidationError

from b1500_test_agent.catalog.blocks import (
    HOLD_OVERHEAD_S,
    Monitor,
    ReadSpec,
    RouteStep,
    apply_routes,
    drain_or_raise,
    flagged_statuses,
    hold_bias,
    hold_chunks,
    ordered,
    read,
    read_blocks,
    route_lines,
    route_steps,
    set_levels,
)
from b1500_test_agent.catalog.kinds.pulse_schedules import (
    CYCLING_PHASE,
    MAX_CYCLES,
    MAX_STRESS_CYCLES,
    RETENTION_PHASE,
    GridPoint,
    ReadStep,
    Schedule,
    build_steps,
    parse_schedule,
)
from b1500_test_agent.catalog.kinds.pulse_sources import (
    SOURCES,
    WAIT_SEGMENT_S,
    CompiledSource,
    OpName,
    OpResult,
    PulseOp,
    PulseSourceKind,
    SourceRequest,
    source_for,
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
from b1500_test_agent.catalog.kinds.stress_measure import StressMeasureKind
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, RawBlock
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.routing import SELECTOR_SETTLE_S, Route
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, SourcePlan
from b1500_test_agent.models.spgu import SPGU_PROGRAMS_KEY, SpguProgram, spgu_programs
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

__all__ = ["MAX_CYCLES", "MAX_STRESS_CYCLES", "PulseReadKind", "PulseReadProgram", "ReadStep", "stored_program"]

PULSE_FUNCTIONS: Final = frozenset({"pgu", "pulse_v", "wgfmu"})
"""Role functions of a pulse role (one per plan): HV-SPGU, SMU pulse, WGFMU (WP10.6)."""

READ_FUNCTIONS: Final = frozenset({"sweep_v", "bias_v", "ground", "measure_only"})
"""Role functions of the read roles."""

READ_KINDS: Final = ("staircase", "spot")
PENDING_READ_KINDS: Final[dict[str, str]] = {"wgfmu": "WP10.6"}
"""Read kinds of the blueprint's row that arrive with a later work package (refused at plan time)."""

READ_KIND_PARAM, SETTLE_PARAM = "read_kind", "settle"
PULSE_BIAS_SETTING, READ_LEVEL_SETTING = "pulse_bias", "v"

ROUTE_OVERHEAD_S: Final = 0.05
"""Estimated bus time of one route phase besides the relay settle time (``ERMOD``, ``ERSSP``, read-back)."""

READ_OVERHEAD_S: Final = 0.2
"""Allowance per read for its level and setup commands and the ``ERRX?`` drain in the duration estimate."""

LEVEL_OVERHEAD_S: Final = 0.05
"""Allowance per operation for setting the SMU outputs to their pulse levels."""

PHASE_READ, PHASE_PULSE, PHASE_REST = "read", "pulse", "rest"


class PulseReadProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed; the ``SourcePlan`` and the SPGU programs are
    stored beside it under their own keys) and executed by ``acquire``. The schedule fields default to WP9.4's
    every-cycle ``cycles`` schedule, so programs stored before WP9.5 still validate."""

    source: Literal["spgu", "smu"]
    pulse_role: str
    pulse_channel: Channel
    ops: dict[str, PulseOp] = Field(min_length=1)
    """Compiled operations by key: ``program``/``erase`` (from the role's settings), ``g<n>`` (grid point n),
    ``cycling_<count>`` (a bipolar cycling burst of ``count`` periods)."""
    sequence: list[OpName] = Field(min_length=1)
    cycles: int = Field(ge=1, le=MAX_STRESS_CYCLES)
    initial_read: bool = True
    read: ReadSpec
    integration: Integration
    smu: list[Channel] = Field(min_length=1)
    """SMU output switches (the read roles' and an SMU pulse role's channels)."""
    pulse_levels: list[BiasOutput] = Field(default_factory=list)
    """Every SMU output while the pulses run (read roles at their pulse level, an SMU pulse role at its base); the
    retention holds keep these levels too."""
    routes: dict[str, list[RouteStep]] = Field(default_factory=dict)
    """Route steps per kind of phase: ``read``, ``pulse`` (applied as an operation's phase or as ``cycling``),
    ``rest``."""
    settle_s: float = Field(default=0.0, ge=0)
    read_estimate_s: float = Field(ge=0)
    schedule: Literal["cycles", "grid", "retention"] = "cycles"
    cycle_reads: Literal["every", "log", "list"] = "every"
    checkpoints: list[int] = Field(default_factory=list)
    """Endurance: the cumulative cycle count of each checkpoint (``cycle_reads`` log or list)."""
    cycle_period: float | None = Field(default=None, gt=0)
    """Period of one bipolar cycle of the cycling bursts (s)."""
    grid: list[GridPoint] = Field(default_factory=list)
    grid_mode: Literal["reset", "ispp"] = "reset"
    reset_read: bool = True
    read_times: list[float] = Field(default_factory=list)
    """Retention: the read times after each write (s, on the 10 ms grid)."""
    monitor: Monitor | None = None
    """Retention: the monitor sample of the hold blocks (the read's measured channels)."""
    precycles: int = Field(default=0, ge=0)

    def steps(self) -> list[ReadStep]:
        """Every checkpoint step in run order (``pulse_schedules.build_steps``)."""
        return build_steps(self)

    def op_chunks(self, key: str) -> int:
        """Checkpoint units of operation ``key``."""
        return self.ops[key].chunks

    @property
    def settle_chunks(self) -> int:
        """Checkpoint units of one settle wait (one per ``WAIT_SEGMENT_S``; none without a wait)."""
        return math.ceil(self.settle_s / WAIT_SEGMENT_S - 1e-9) if self.settle_s > 0 else 0

    def settle_segments(self) -> list[float]:
        """The settle wait cut into segments of at most ``WAIT_SEGMENT_S`` (one checkpoint after each)."""
        count = self.settle_chunks
        if not count:
            return []
        return [WAIT_SEGMENT_S] * (count - 1) + [round(self.settle_s - WAIT_SEGMENT_S * (count - 1), 9)]

    @property
    def reads(self) -> int:
        return sum(1 for s in self.steps() if s.action == "read")

    @property
    def pulse_source(self) -> PulseSourceKind:
        return next(s for s in SOURCES.values() if s.family == self.source)

    @property
    def enable(self) -> list[Channel]:
        """``CN`` channels: the SMUs and, for the HV-SPGU source, the pulse channel."""
        return [*self.smu, *([self.pulse_channel] if self.source == "spgu" else [])]


def stored_program(plan: PlanRecord) -> tuple[PulseReadProgram, list[SpguProgram]]:
    """The ``PulseReadProgram`` and the SPGU programs stored in ``plan.program``.

    Raises:
        CompileError: If the stored program is not a ``pulse_read`` program.
    """
    data = {k: v for k, v in plan.program.items() if k not in (SOURCE_PLAN_KEY, SPGU_PROGRAMS_KEY)}
    try:
        return PulseReadProgram.model_validate(data), spgu_programs(plan.program)
    except ValidationError as exc:
        raise CompileError(f"plan {plan.plan_id} has no valid pulse_read program: {exc}") from None


# -- helpers ---------------------------------------------------------------------------------------------------------


def _param(params: dict[str, Quantity], name: str, default: Any = None) -> Any:
    quantity = params.get(name)
    return default if quantity is None else quantity.value


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _choice(params: dict[str, Quantity], name: str, choices: Sequence[str], default: str,
            pending: dict[str, str] | None = None) -> str:
    value = _param(params, name, default)
    if pending and value in pending:
        raise CompileError(f"pulse_read: {name} {value} arrives in {pending[value]} (blueprint v2 10.6); use one of "
                           f"{list(choices)}")
    if value not in choices:
        raise CompileError(f"{name} must be one of {list(choices)}, got {value!r}")
    return str(value)


def _sub_binding(binding: ChannelBinding, names: Sequence[str]) -> ChannelBinding:
    return ChannelBinding(pin_map=binding.pin_map, roles={n: b for n, b in binding.roles.items() if n in names})


def _rest_steps(steps: Sequence[RouteStep], station: StationProfile) -> list[RouteStep]:
    """Each routed output back to its switch's rest state (once per output)."""
    rest: list[RouteStep] = []
    seen: set[tuple[str, str]] = set()
    for step in steps:
        switch = station.switch(step.route.switch)
        key = (step.route.switch, step.route.output)
        if switch is None or key in seen:
            continue
        seen.add(key)
        rest.append(step.model_copy(update={"route": Route(switch=switch.id, output=step.route.output,
                                                            state=switch.rest)}))
    return rest


def _route_text(steps: Sequence[RouteStep]) -> str:
    return ",".join(str(s.route) for s in steps)


class _Rows:
    """Turns read blocks into table rows (``read_blocks`` + ``t_s`` for retention, ``cycle`` and ``phase``), step by
    step; shared by the checkpoints (``partial.csv``) and ``to_table``."""

    def __init__(self, program: PulseReadProgram) -> None:
        self.program = program
        self.step = 0

    def of(self, step: ReadStep, blocks: Sequence[RawBlock]) -> list[dict[str, object]]:
        rows = read_blocks(self.program.read, blocks, first_step=self.step)
        timed = {"t_s": step.t_s} if self.program.schedule == "retention" else {}
        out = [{"step": row["step"], **timed, "cycle": step.cycle, "phase": step.phase,
                **{k: v for k, v in row.items() if k != "step"}} for row in rows]
        self.step += len(out)
        return out


def _hold_lines(program: PulseReadProgram, seconds: float) -> list[str]:
    """The writes of one retention hold (the levels are set before): ``FMT 1,1``, the monitor's ``MM 10`` setup, an
    ``MT`` when a block's length changes, ``XE`` per block (``blocks.hold_bias``)."""
    monitor = program.monitor
    assert monitor is not None
    lines = [flex.fmt(1, 1)]
    previous: float | None = None
    for h_bias in hold_chunks(seconds, monitor.period):
        setup = monitor.setup(h_bias)
        if previous is None:
            lines += [flex.mcc(), flex.ml(setup.mode), flex.mt(h_bias, setup.interval, 1, 0.0),
                      flex.msc(setup.abort, setup.post), flex.mm(flex.SAMPLING_MODE, setup.measure),
                      *(flex.cmm(ch, op) for ch, op in setup.operation.items())]
        elif h_bias != previous:
            lines.append(flex.mt(h_bias, setup.interval, 1, 0.0))
        previous = h_bias
        lines.append(flex.XE)
    return lines


def _schedule_fields(plan: Schedule, spec: ReadSpec, integration: Integration) -> dict[str, Any]:
    """The schedule part of a ``PulseReadProgram`` (``pulse_schedules.Schedule``; retention: the hold monitor)."""
    fields: dict[str, Any] = {"schedule": plan.kind, "cycle_reads": plan.cycle_reads, "checkpoints": plan.checkpoints,
                              "cycle_period": plan.cycle_period, "grid": plan.grid, "grid_mode": plan.grid_mode,
                              "reset_read": plan.reset_read, "read_times": plan.read_times,
                              "precycles": plan.precycles}
    if plan.kind == "retention":
        fields["monitor"] = Monitor.of(spec.measure, integration)
    return fields


# -- the kind --------------------------------------------------------------------------------------------------------


class PulseReadKind:
    """Composite route -> pulse source -> route back -> read (sim and visa code path; see the module docstring)."""

    kind_id = "pulse_read"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview, program and routes per phase; see the module docstring."""
        pulse_role, reads = self._check_roles(recipe)
        spec = recipe.roles[pulse_role]
        source = source_for(pulse_role, spec.function, self.kind_id)
        smu_source = source.family == "smu"
        plan = parse_schedule(params, source=source.family)
        sweeps = [n for n in reads if recipe.roles[n].function == "sweep_v"]
        sweeps += [pulse_role] if smu_source and "start" in spec.settings else []
        read_kind = _choice(params, READ_KIND_PARAM, READ_KINDS, "staircase" if sweeps else "spot",
                            PENDING_READ_KINDS)
        settle = _number(_param(params, SETTLE_PARAM, 0.0), SETTLE_PARAM)
        if settle < 0:
            raise CompileError(f"{SETTLE_PARAM} must not be negative, got {settle:g}")
        read_names = [*reads, *([pulse_role] if smu_source else [])]
        all_steps = route_steps(binding, station, kind_id=self.kind_id)
        read_routes = route_steps(_sub_binding(binding, read_names), station, kind_id=self.kind_id)
        pulse_routes = [] if smu_source else route_steps(_sub_binding(binding, [pulse_role]), station,
                                                         kind_id=self.kind_id)
        allowed = frozenset(s.route for s in all_steps)
        bound = binding.roles.get(pulse_role)
        base = self._read_plan(recipe, params, binding, station, read_kind, reads, pulse_role if smu_source else None)
        if bound is None or bound.channel is None or not base.program:
            # A role is unbound or its wiring is unknown: the plan-phase rules block the plan (R-PIN-01).
            return CompiledKindPlan(envelope=CompiledEnvelope(channels=dict(base.envelope.channels), routes=allowed),
                                    estimate=Estimate(points=0, duration_s=0.0))
        compiled = source.compile(SourceRequest(role=pulse_role, spec=spec, channel=bound.channel, params=params,
                                                ops=tuple(plan.op_requests(pulse_role, spec, params))))
        read_spec, integration, read_points, read_s = self._read_spec(read_kind, base)
        channels = self._channels(recipe, params, base.envelope.channels, pulse_role, bound.channel, compiled,
                                  smu_source)
        smu = [b.channel for name in recipe.roles if name in read_names and (b := binding.roles.get(name)) is not None
               and b.channel is not None]
        program = PulseReadProgram(
            source=source.family, pulse_role=pulse_role, pulse_channel=bound.channel,  # type: ignore[arg-type]
            ops=compiled.ops, sequence=plan.sequence, cycles=plan.cycles, initial_read=plan.initial_read,
            read=read_spec, integration=integration, smu=list(dict.fromkeys(smu)),
            pulse_levels=self._pulse_levels(recipe, params, read_spec, pulse_role, smu_source, compiled),
            routes={phase: steps for phase, steps in ((PHASE_READ, read_routes), (PHASE_PULSE, pulse_routes),
                                                      (PHASE_REST, _rest_steps(all_steps, station))) if steps},
            settle_s=settle, read_estimate_s=round(read_s, 6), **_schedule_fields(plan, read_spec, integration))
        programs = spgu_programs(compiled.extra)
        stored: dict[str, Any] = program.model_dump(mode="json")
        stored.update(compiled.extra)
        stored[SOURCE_PLAN_KEY] = SourcePlan(pulses={bound.channel: compiled.trains}).model_dump(mode="json")
        return CompiledKindPlan(envelope=CompiledEnvelope(channels=channels, routes=allowed),
                                estimate=self._estimate(program, read_s, read_points),
                                flex_preview=self.preview(program, programs), program=stored,
                                routes_by_phase=self._phases(program, pulse_routes))

    @staticmethod
    def _phases(program: PulseReadProgram, pulse_routes: Sequence[RouteStep]) -> dict[str, list[Route]]:
        """``routes_by_phase``: the pulse phases (``cycling`` first when the plan bursts, then the operations in
        the sequence's order), ``read``, ``rest`` (the S12 contract order)."""
        names: list[str] = []
        if pulse_routes:
            if any(s.action == "burst" for s in program.steps()):
                names.append(CYCLING_PHASE)
            names += list(dict.fromkeys(program.sequence))
        phases: dict[str, list[Route]] = {name: [s.route for s in pulse_routes] for name in names}
        phases.update({phase: [s.route for s in program.routes[phase]] for phase in (PHASE_READ, PHASE_REST)
                       if program.routes.get(phase)})
        return phases

    def _check_roles(self, recipe: Recipe) -> tuple[str, list[str]]:
        """``(pulse role, read roles)`` after the role-function checks (``CompileError``)."""
        pulses = [name for name, role in recipe.roles.items() if role.function in PULSE_FUNCTIONS]
        if len(pulses) != 1:
            raise CompileError(f"{self.kind_id} needs exactly one pulse role (pgu: HV-SPGU, pulse_v: SMU pulse, "
                               f"wgfmu: WGFMU); recipe {recipe.id} has {pulses or 'none'}")
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if name not in pulses and role.function not in READ_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; read roles are "
                               f"{', '.join(sorted(READ_FUNCTIONS))}")
        pulse = recipe.roles[pulses[0]]
        if pulse.function != "pulse_v" and pulse.measure:
            raise CompileError(f"role {pulses[0]} ({pulse.function}) cannot measure; reads belong to SMU roles (a read "
                               "role on the same pad declares terminal)")
        reads = [name for name in recipe.roles if name != pulses[0]]
        if not any(role.measure for name, role in recipe.roles.items() if name in reads or role.function == "pulse_v"):
            raise CompileError(f"recipe {recipe.id}: no read role measures anything")
        return pulses[0], reads

    def _read_plan(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                   station: StationProfile, read_kind: str, reads: list[str], smu_pulse: str | None) \
            -> CompiledKindPlan:
        """The read compiled by its own kind: ``smu_staircase`` with exactly one sweep, or ``smu_spot`` with every
        sweep held at its read level ``v`` (an SMU pulse role reads as the sweep or at its ``v``)."""
        roles: dict[str, RoleSpec] = {}
        sweeps: list[str] = []
        for name in [*reads, *([smu_pulse] if smu_pulse else [])]:
            role = recipe.roles[name]
            if "values" in role.settings or "ranges" in role.settings:
                raise CompileError(f"{name}: level lists and range surveys belong to smu_spot, not to a pulse read")
            sweeping = role.function == "sweep_v" or (name == smu_pulse and "start" in role.settings)
            if read_kind == "staircase" and sweeping:
                role = role.model_copy(update={"function": "sweep_v"})
                sweeps.append(name)
            elif sweeping or name == smu_pulse:
                if READ_LEVEL_SETTING not in role.settings:
                    raise CompileError(f"{READ_KIND_PARAM} {read_kind} holds role {name} at its read level setting "
                                       f"{READ_LEVEL_SETTING}, which it lacks")
                role = role.model_copy(update={"function": "bias_v"})
            roles[name] = role
        sub = recipe.model_copy(update={"roles": roles})
        if read_kind == "staircase":
            if len(sweeps) != 1:
                raise CompileError(f"{READ_KIND_PARAM} staircase sweeps exactly one role per read; recipe {recipe.id} "
                                   f"gives {sweeps or 'none'} (a sweep_v role, or start/stop on an SMU pulse role)")
            return SmuStaircaseKind().compile(sub, params, binding, station)
        return SmuSpotKind().compile(sub, params, binding, station)

    @staticmethod
    def _read_spec(read_kind: str, base: CompiledKindPlan) -> tuple[ReadSpec, Integration, int, float]:
        """The read spec, integration, points and estimated duration (s) of one read."""
        seconds = base.estimate.duration_s - SETUP_OVERHEAD_S + READ_OVERHEAD_S
        if read_kind == "staircase":
            staircase = StaircaseProgram.model_validate(base.program)
            if staircase.sweep.double:
                raise CompileError("a pulse read is a single sweep (mode single): a double sweep would program the "
                                   "device on its way back")
            spec = ReadSpec(kind="staircase", staircase=staircase, timeout_s=read_timeout_s(base.estimate))
            return spec, staircase.integration, staircase.steps, seconds
        spot = SpotProgram.model_validate(base.program)
        spec = ReadSpec(kind="spot", spot=spot, timeout_s=2.0 * spot.row_estimate_s + READ_TIMEOUT_MARGIN_S)
        return spec, spot.integration, spot.rows, seconds

    @staticmethod
    def _channels(recipe: Recipe, params: dict[str, Quantity], read_channels: dict[int, ChannelEnvelope],
                  pulse_role: str, pulse_channel: int, compiled: CompiledSource,
                  smu_source: bool) -> dict[int, ChannelEnvelope]:
        """The read envelope, widened by the bias roles' pulse levels, plus the pulse channel (an SMU pulse role's
        entry merges its read and its pulses)."""
        channels = dict(read_channels)
        for channel, entry in read_channels.items():
            role = recipe.roles.get(entry.role)
            if role is not None and role.function == "bias_v":
                level = _number(setting_value(role, PULSE_BIAS_SETTING, params, 0.0),
                                f"{entry.role}.{PULSE_BIAS_SETTING}")
                channels[channel] = entry.model_copy(update={"max_abs_v": max(entry.max_abs_v, abs(level))})
        if smu_source:
            entry = channels.get(pulse_channel)
            assert entry is not None and entry.max_abs_i is not None and compiled.max_abs_i is not None
            channels[pulse_channel] = entry.model_copy(update={
                "function": "pulse_v", "max_abs_v": max(entry.max_abs_v, compiled.max_abs_v),
                "max_abs_i": max(entry.max_abs_i, compiled.max_abs_i), "pulse": compiled.pulse})
        else:
            channels[pulse_channel] = ChannelEnvelope(role=pulse_role, max_abs_v=compiled.max_abs_v, max_abs_i=None,
                                                      function="pgu", v_start=None, v_stop=None, pulse=compiled.pulse)
        return channels

    @staticmethod
    def _pulse_levels(recipe: Recipe, params: dict[str, Quantity], spec: ReadSpec, pulse_role: str,
                      smu_source: bool, compiled: CompiledSource) -> list[BiasOutput]:
        """Every SMU output while the pulses run: the read's constant outputs and sweep source at their pulse level
        (``pulse_bias`` of a bias role, else 0 V; an SMU pulse role at its base level)."""
        outputs = list(spec.outputs)
        if spec.kind == "staircase":
            assert spec.staircase is not None
            sweep = spec.staircase.sweep
            outputs.append(BiasOutput(role=spec.staircase.sweep_role, channel=sweep.channel, level=sweep.start,
                                      comp=sweep.icomp if sweep.icomp is not None else 0.0))
        base = next((op.setup.pulses[0].base for op in compiled.ops.values() if op.source == "smu"), 0.0)
        levels: list[BiasOutput] = []
        for output in outputs:
            role = recipe.roles[output.role]
            if smu_source and output.role == pulse_role:
                level = base
            elif role.function == "bias_v":
                level = _number(setting_value(role, PULSE_BIAS_SETTING, params, 0.0),
                                f"{output.role}.{PULSE_BIAS_SETTING}")
            else:
                level = 0.0
            levels.append(output.model_copy(update={"level": level}))
        return levels

    @staticmethod
    def _estimate(program: PulseReadProgram, read_s: float, read_points: int) -> Estimate:
        route_s = SELECTOR_SETTLE_S + ROUTE_OVERHEAD_S
        source = program.pulse_source
        pulse_routes = 2 * route_s if program.routes.get(PHASE_PULSE) else 0.0
        duration = SETUP_OVERHEAD_S + sum(route_s for phase in (PHASE_READ, PHASE_REST) if program.routes.get(phase))
        segment = read_s
        reads = 0
        for step in program.steps():
            if step.action == "read":
                duration += read_s
                reads += 1
                continue
            if step.action == "hold":
                assert program.monitor is not None
                spans = [h + program.monitor.period + HOLD_OVERHEAD_S
                         for h in hold_chunks(step.seconds, program.monitor.period)]
                duration += LEVEL_OVERHEAD_S + sum(spans)
                segment = max(segment, *spans)
                continue
            op = program.ops[step.op]
            extra = LEVEL_OVERHEAD_S + pulse_routes
            settle = program.settle_s if step.action == "pulse" else 0.0
            duration += extra + source.seconds(op) + settle
            segment = max(segment, extra + source.segment_s(op),
                          *(program.settle_segments() if step.action == "pulse" else []))
        return Estimate(points=reads * read_points, duration_s=round(duration, 6), max_segment_s=round(segment, 6))

    @staticmethod
    def preview(program: PulseReadProgram, programs: Sequence[SpguProgram]) -> list[str]:
        """Every write ``acquire`` sends, in order (``ERRX?``/``SPST?``/``ERSSP?`` queries, the ``LOP?`` control and the
        ATV-19 ``SPP`` fallback are not listed)."""
        source = program.pulse_source
        adc = ADC_TYPE_CODES[program.integration.adc]
        lines = route_lines(program.routes.get(PHASE_READ, []))
        lines.append(flex.tsc(False))
        lines += [flex.aad(m.channel, adc) for m in program.read.measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[program.integration.mode], program.integration.n))
        lines.append(flex.cn(program.enable))
        previous: dict[int, float] | None = None
        pulse_levels = {o.channel: o.level for o in program.pulse_levels}
        for step in program.steps():
            if step.action == "read":
                lines += StressMeasureKind._read_lines(program.read, previous)
                previous = program.read.levels_after()
                continue
            lines += [bias_command(o) for o in ordered(program.pulse_levels, previous)]
            previous = pulse_levels
            if step.action == "hold":
                lines += _hold_lines(program, step.seconds)
                continue
            if program.routes.get(PHASE_PULSE):
                lines += route_lines(program.routes[PHASE_PULSE])
            lines += source.preview(program.ops[step.op], programs)
            if program.routes.get(PHASE_PULSE):
                lines += route_lines(program.routes.get(PHASE_READ, []))
        return lines + route_lines(program.routes.get(PHASE_REST, []))

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints ``acquire`` reports: one per read and one per pulse chunk (fewer when the run stops early)."""
        return sum(s.chunks for s in stored_program(plan)[0].steps()) if plan.program else 0

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (module docstring); every source, pulse and route passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program, programs = stored_program(plan)
        driver = tx.driver
        if program.source == "spgu" and driver.pulse_output_active():
            raise DriverError("an SPGU output is already running (SPST? 1); run safe_shutdown first")
        steps = program.steps()
        run = _Run(tx, program, programs, total=sum(s.chunks for s in steps))
        run.route(PHASE_READ, "start")
        driver.set_time_stamp(False)
        driver.apply_integration(program.integration, [m.channel for m in program.read.measure])
        driver.enable(program.enable)
        drain_or_raise(tx, "enabling the outputs")
        tx.mark("outputs enabled")
        tx.lop_positive_control(program.smu)
        rows = _Rows(program)
        for step in steps:
            if step.action == "read":
                taken = read(tx, program.read, run.previous)
                run.blocks.extend(taken)
                run.reads_done += 1
                run.done += 1
                tx.checkpoint(run.done, run.total, step.phase, rows=lambda s=step, t=taken: rows.of(s, t))
                run.previous = program.read.levels_after()
                flagged = flagged_statuses(taken)
                if flagged:
                    run.stop_reason = (f"read {run.reads_done} (cycle {step.cycle}, {step.phase}) reported status "
                                       f"{','.join(flagged)}")
                    break
            elif step.action == "hold":
                run.hold(step)
            else:
                run.operation(step)
            if run.stop_reason:
                break
        run.route(PHASE_REST, "end")
        if run.stop_reason:
            tx.mark("stopped: " + run.stop_reason)
        tx.mark("data read")
        return RawAcquisition(blocks=run.blocks, kind_result=run.facts(steps), message=run.message())

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame | None:
        """Tidy table over every read (module docstring); ``None`` when the run stopped before its first read.

        Raises:
            ValueError: If the blocks are not whole reads of the plan or do not hold the programmed elements.
        """
        program, _ = stored_program(plan)
        reads = [s for s in program.steps() if s.action == "read"]
        width = program.read.blocks
        if len(raw.blocks) % width or len(raw.blocks) > len(reads) * width:
            raise ValueError(f"{self.kind_id} expects whole reads of {width} block(s) (at most {len(reads)}), got "
                             f"{len(raw.blocks)} blocks")
        if not raw.blocks:
            return None
        rows = _Rows(program)
        table: list[dict[str, object]] = []
        for index, step in enumerate(reads[:len(raw.blocks) // width]):
            table += rows.of(step, raw.blocks[index * width:(index + 1) * width])
        return pd.DataFrame(table)


def _wait(tx: Transaction, seconds: float) -> None:
    """Host wait of ``seconds`` in pieces of at most one second, each followed by an abort check."""
    left = seconds
    while left > 1e-12:
        piece = min(1.0, left)
        tx.driver.host_wait(piece)
        tx.check_abort()
        left -= piece


class _Run:
    """What one ``acquire`` does and did: the checkpoint count, the read blocks, the routes it applied
    (``kind_result.routes``), the pulse operations, bursts and holds and their readings, and why it stopped early."""

    def __init__(self, tx: Transaction, program: PulseReadProgram, programs: Sequence[SpguProgram], *,
                 total: int) -> None:
        self.tx = tx
        self.program = program
        self.programs = programs
        self.total = total
        self.done = 0
        self.previous: dict[int, float] | None = None
        self.blocks: list[RawBlock] = []
        self.log: list[str] = []
        self.reads_done = 0
        self.ops_done = 0
        self.bursts_done = 0
        self.burst_cycles = 0
        self.precycles_done = 0
        self.pulses = 0
        self.waited_s = 0.0
        self.spp = 0
        self.readings: list[tuple[float, str]] = []
        self.holds = 0
        self.held_s = 0.0
        self.monitor_max = 0.0
        self.stop_reason = ""

    def route(self, phase: str, when: str, label: str | None = None) -> None:
        """Apply the routes of ``phase`` (``read``, ``pulse``, ``rest``) as plan phase ``label`` (default ``phase``;
        a pulse phase is named after its operation, or ``cycling``) and log it."""
        steps = self.program.routes.get(phase, [])
        if steps:
            name = label or phase
            apply_routes(self.tx, steps, phase=name)
            self.log.append(f"{when} {name} {_route_text(steps)}")

    def operation(self, step: ReadStep) -> None:
        """One pulse operation or cycling burst: pulse levels, its route phase, the source, back to ``read``, the
        settle wait (operations only); one checkpoint per chunk."""
        tx, program = self.tx, self.program
        op = program.ops[step.op]
        burst = step.action == "burst"
        what = f"{op.count} cycle(s) at {op.level:g} V / opposite, {op.width:g} s" if burst else \
            f"{op.count} pulse(s) at {op.level:g} V, {op.width:g} s"
        tx.mark(f"cycle {step.cycle}: {step.phase}, {what}")
        set_levels(tx, program.pulse_levels, self.previous)
        self.previous = {o.channel: o.level for o in program.pulse_levels}
        self.route(PHASE_PULSE, f"c{step.cycle}", step.phase)
        reported = 0

        def on_chunk() -> None:
            nonlocal reported
            self.done += 1
            reported += 1
            tx.checkpoint(self.done, self.total, step.phase)

        result = program.pulse_source.run(tx, op, self.programs, on_chunk=on_chunk,
                                          label=f"cycle {step.cycle} {step.phase}")
        self.record(result, burst=burst, count=op.count, pre=burst and step.cycle == 0)
        if program.routes.get(PHASE_PULSE):
            self.route(PHASE_READ, f"c{step.cycle}")
        settle = [] if burst or result.stopped else program.settle_segments()
        self.done += step.chunks - (0 if burst else program.settle_chunks) - reported
        tx.checkpoint(self.done, self.total, step.phase)
        for seconds in settle:
            _wait(tx, seconds)
            self.done += 1
            tx.checkpoint(self.done, self.total, step.phase)
        if result.stopped:
            self.stop_reason = result.reason

    def hold(self, step: ReadStep) -> None:
        """One retention hold: the read SMUs at their pulse levels for ``step.seconds`` in ``MM 10`` blocks, one
        checkpoint per block; a flagged block stops the run."""
        tx, program = self.tx, self.program
        assert program.monitor is not None
        monitor = program.monitor
        tx.mark(f"retention: hold {step.seconds:g} s before read {step.cycle}")

        def on_block(_index: int, h_bias: float, block: RawBlock) -> None:
            self.holds += 1
            self.held_s += h_bias + monitor.period
            self.monitor_max = max([self.monitor_max, *(abs(v) for _, v, _ in monitor.values(block))])
            self.done += 1
            tx.checkpoint(self.done, self.total, RETENTION_PHASE)

        held = hold_bias(tx, program.pulse_levels, step.seconds, monitor, on_block=on_block,
                         label=f"retention hold {step.cycle}", previous=self.previous)
        self.previous = {o.channel: o.level for o in program.pulse_levels}
        if held.stopped:
            self.stop_reason = held.reason

    def record(self, result: OpResult, *, burst: bool, count: int, pre: bool) -> None:
        if burst:
            self.bursts_done += 1
            self.burst_cycles += count
            self.precycles_done += count if pre else 0
        else:
            self.ops_done += 1
        self.pulses += result.pulses * (2 if burst else 1)
        self.waited_s += result.waited_s
        self.spp += int(result.stopped_by_spp)
        for block in result.blocks:
            self.readings += [(abs(p.value), str(p.status.value)) for p in block.points]

    def facts(self, steps: list[ReadStep]) -> dict[str, Any]:
        program = self.program
        pulse_steps = [s for s in steps if s.action == "pulse"]
        read_steps = [s for s in steps if s.action == "read"][:self.reads_done]
        facts: dict[str, Any] = {
            "source": program.source, "schedule": program.schedule, "sequence": ",".join(program.sequence),
            "cycles_planned": self._cycles_planned(), "cycles_done": self._cycles_done(read_steps),
            "reads_planned": len([s for s in steps if s.action == "read"]), "reads_done": self.reads_done,
            "pulse_ops_planned": len(pulse_steps), "pulse_ops_done": self.ops_done, "pulses_applied": self.pulses,
            "routes": "; ".join(self.log), "route_phases": len(self.log),
            "stopped_early": self.reads_done < len([s for s in steps if s.action == "read"]),
            "stop_reason": self.stop_reason,
        }
        bursts = [s for s in steps if s.action == "burst"]
        if bursts:
            facts.update(bursts_planned=len(bursts), bursts_done=self.bursts_done,
                         burst_cycles_done=self.burst_cycles, precycles=program.precycles)
        if program.schedule == "cycles" and program.cycle_reads != "every":
            facts.update(cycle_reads=program.cycle_reads, checkpoints_planned=len(program.checkpoints))
        if program.schedule == "grid":
            facts.update(grid_mode=program.grid_mode, grid_points_planned=len(program.grid),
                         grid_points_done=len({s.cycle for s in read_steps
                                               if s.cycle > 0 and s.phase == program.sequence[1]}))
        if program.schedule == "retention":
            facts.update(hold_blocks=self.holds, held_s=round(self.held_s, 6), hold_i_max_a=self.monitor_max,
                         retention_s_planned=program.read_times[-1])
        if program.source == "spgu":
            facts.update(waited_s=round(self.waited_s, 6), spp_fallbacks=self.spp)
        else:
            facts.update(pulse_readings=len(self.readings),
                         pulse_i_max_a=max((v for v, _ in self.readings), default=None),
                         pulse_statuses="".join(sorted({s for _, s in self.readings})))
        return facts

    def _cycles_planned(self) -> int:
        """Program/erase cycles the plan applies: the precycles plus, for schedule ``cycles``, its cycles."""
        program = self.program
        return program.precycles + (program.cycles if program.schedule == "cycles" else 0)

    def _cycles_done(self, read_steps: list[ReadStep]) -> int:
        """Cycles applied and accounted for: the precycles run, plus for schedule ``cycles`` the cycles whose reads all
        ran (every cycle: their number, WP9.4; endurance: the cumulative count of the last such checkpoint)."""
        program = self.program
        if program.schedule != "cycles":
            return self.precycles_done
        per_cycle = [s.cycle for s in read_steps if s.cycle > 0]
        complete = [c for c in set(per_cycle) if per_cycle.count(c) == len(program.sequence)]
        reached = len(complete) if program.cycle_reads == "every" else max(complete, default=0)
        return self.precycles_done + reached

    def message(self) -> str:
        text = (f"{self.ops_done} pulse operation(s) ({self.pulses} pulses, {self.program.source}) and "
                f"{self.reads_done} read(s)")
        if self.bursts_done:
            text += f"; {self.bursts_done} cycling burst(s), {self.burst_cycles} bipolar cycle(s)"
        if self.holds:
            text += f"; {self.holds} retention hold block(s), {self.held_s:g} s"
        if self.spp:
            text += f"; {self.spp} output(s) stopped by SPP after SPST? stayed 1 (ATV-19)"
        return text + (f"; stopped: {self.stop_reason}" if self.stop_reason else "")
