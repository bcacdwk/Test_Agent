"""The WGFMU path of kind ``stress_measure`` (blueprint v2 2.7 "stress (SMU hold, chunked; or WGFMU stress) -> reads",
3.4 row ``wgfmu.fast_bti``; WP10.7): the WGFMU holds the stress and senses the device for a few microseconds between
the holds, so the shift hardly recovers before it is read (fast BTI); SMU roles hold a DC bias through the whole run
(WG Ex. 10) and, when they measure, are read once between two WGFMU executions (an SMU measurement in the same
session as the WGFMU, WG Ex. 11). ``StressMeasureKind`` hands every recipe with ``wgfmu`` roles to this module; the
schedule (``stress_measure.schedule`` on the 10 ns grid), the table contract and the analyses are the kind's.

Roles (bound through the pin map; a WGFMU role reaches its terminal only through its RSU, ``RSU<ch>.OUT``):

- ``wgfmu`` (one or more): settings ``stress`` (V, required: the level during the stress holds), ``recovery`` (V,
  default 0), ``range`` (current range of a role that measures, default ``1ma``) and its sense levels: exactly one
  *swept* role gives ``start``/``stop``/``points`` (the staircase of the reference read and of every staircase read)
  and ``v`` (its level in a spot read); every other WGFMU role gives ``v`` (its level during every read, e.g. the
  drain's read bias; default 0 V). A WGFMU role measures ``[I]`` or nothing (no compliance: a reading at full scale
  is saturated, status ``V``).
- ``bias_v`` (SMU; settings ``v``, ``icomp``; may measure ``[I]``: read once between two WGFMU executions) and
  ``ground`` (the GNDU, or an SMU at 0 V with ``icomp``).

Parameters read by name: the schedule of ``stress_measure`` (``schedule``, ``stress_time``, ``first_read`` from
``MIN_FIRST_READ_S``, ``reads_per_decade``, ``read_times``, ``recovery_time``), ``read_kind`` (``staircase``: every
read steps through the swept role's levels, the default; ``spot``: the stress and recovery reads sense once at the
levels ``v``, the reference read is still the staircase) and the sense timing ``edge`` (s between levels, default
100 ns), ``width`` (flat time per step, default 1 us) and ``settle`` (left out of each step's average, default
500 ns).

Compile (pure): the operations (reference read, then per cycle the hold and its read; ``t_s`` as the SMU path), the
``fast_bti`` program of the whole run (``catalog/fast_bti.py``: rule R-WG-02 checks it, the guard admits every pattern
of it), the WGFMU executions (``batches``; the first holds only the reference read, so a reference read that
saturates stops the run before any stress), the envelope (per WGFMU channel its largest |level| and
``WaveformLimits``, the RSU routes in phases ``waveform`` and ``rest``; the SMU bias channels), the source plan
(``DcStress`` per WGFMU channel and the ``StressSchedule``, shown in the confirmation summary), the estimate
(``max_segment_s`` from the checkpoints every ``CHECKPOINT_S`` of sequencer time) and the FLEX preview (the SMU writes).

Acquire: ``program.json``, then ``with tx.wgfmu_phase(flex_io=<SMU roles>) as wg:`` (FLEX lock released, library
session opened and initialized; the exit always runs the WGFMU safe state and relocks), the guard checks of the whole
program (``WgfmuDriver.check_program``: no execution starts when any later pattern would be refused), and per
execution: ``wg.load``
of its slice (every pattern guard-checked before the first library call); before the first one, in WG Ex. 10's order,
the SMU roles: ``CN``, ``ERRX?`` drain, on hardware the ``LOP?`` positive control, the guarded levels, the spot setup
of the measuring SMUs and an ``ERRX?`` drain; ``wg.run`` (update, RSU connect, execute, status polls at most 1 s apart
with abort checks, checkpoints every ``CHECKPOINT_S`` of sequencer time, readback); each channel's values archived as
``raw/wgfmu-<ch>-<n>.npz``; an ``ERRX?`` drain of the FLEX side while SMUs are on (an SMU error stops the run); the
measuring SMUs read once (``XE``) while the WGFMU holds the phase level; a checkpoint with the execution's rows. The
run stops after an execution with a saturated WGFMU value or an SMU reading with a ``STOP_STATUSES`` letter
(``kind_result.stop_reason``); the phase exit's safe state then ends the stress (``WGFMU_initialize``: every channel at
0 V, disconnected). Cleanup is the transaction's. The SMU readings are monitor values, not table rows (a row of the
run-table contract carries every measured column): ``kind_result`` holds per measuring SMU role ``<role>_I_first``,
``<role>_I_last``, ``<role>_I_max_abs`` (A), ``<role>_I_reads`` and the worst status letter ``<role>_I_status``; each
reading is also in the run's audit.

Table (the ``stress_measure`` contract): ``step``, ``t_s``, ``cycle``, ``phase`` (``read`` per sense step, ``stress``
or ``recovery`` for a hold's monitor point, which carries the cycle of the read it leads to), per WGFMU role
``<role>_V`` (the programmed level: the sense level on read rows, the hold level on hold rows) and, when it measures,
``<role>_I`` + ``_status``; per SMU role ``<role>_V`` (its level).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

import pandas as pd
from pydantic import Field, ValidationError

from b1500_test_agent.catalog import fast_bti as fb
from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.blocks import STOP_STATUSES, drain_or_raise, set_levels, spot_once
from b1500_test_agent.catalog.kinds.smu_staircase import READ_TIMEOUT_MARGIN_S, BiasOutput, MeasureColumn, bias_command
from b1500_test_agent.catalog.kinds.stress_measure import (
    READ_KIND_PARAM,
    RECOVERY_SETTING,
    STRESS_SETTING,
    schedule,
    segments_of,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.wgfmu import WgfmuTrace, warning_facts
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.plan import (
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    WaveformLimits,
)
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.run import ProgramEntry, RunProgram
from b1500_test_agent.models.sources import (
    SOURCE_PLAN_KEY,
    WGFMU_SEQUENCE_GAP_S,
    DcStress,
    SourcePlan,
    StressSchedule,
    WaveformProgram,
)
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING, wgfmu_status_letter
from b1500_test_agent.transport.wgfmu.api import CURRENT_RANGE_A

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

PATH_KEY: Final = "path"
PATH: Final = "wgfmu"
"""``plan.program["path"]`` of a WGFMU stress plan (the SMU path stores no such key)."""

WGFMU_FUNCTION: Final = "wgfmu"
SMU_FUNCTIONS: Final = frozenset({"bias_v", "ground"})
SWEEP_SETTINGS: Final = ("start", "stop", "points")
LEVEL_SETTING: Final = "v"
RANGE_SETTING: Final = "range"
DEFAULT_RANGE: Final = "1ma"

EDGE_PARAM, WIDTH_PARAM, SETTLE_PARAM = "edge", "width", "settle"
DEFAULT_TIMING: Final = {EDGE_PARAM: 1e-7, WIDTH_PARAM: 1e-6, SETTLE_PARAM: 5e-7}

CHECKPOINT_S: Final = 10.0
"""Sequencer time between two progress checkpoints inside one WGFMU execution (cancel latency is the 1 s poll)."""

RUN_OVERHEAD_S: Final = 0.5
"""Estimated host time per WGFMU execution (load, update, connect, status polls, readback setup)."""

READBACK_S_PER_VALUE: Final = 2e-6
"""Estimated readback time per stored value (TODO(verify) at bring-up L8, as kind ``wgfmu_waveform``)."""

SETUP_OVERHEAD_S: Final = 0.5
"""Estimated time of the library session (open, initialize) and the SMU setup."""

SMU_READ_S: Final = 0.05
"""Estimated time of one SMU spot reading between two executions (TODO(verify) at bring-up L9)."""

OVERRANGE_FRACTION: Final = 1.0 - 1e-9
"""A WGFMU reading at this fraction of its range's full scale or beyond is saturated (status ``V``)."""

SATURATED: Final = wgfmu_status_letter(range_overflow=True, error=False)
NORMAL: Final = wgfmu_status_letter(range_overflow=False, error=False)


class WgfmuStressProgram(StrictModel):
    """The kind's part of ``PlanRecord.program`` for the WGFMU path (next to ``sources``)."""

    path: Literal["wgfmu"] = PATH
    read_kind: fb.ReadKind
    channels: list[fb.BtiChannel] = Field(min_length=1)
    ops: list[fb.BtiOp] = Field(min_length=1)
    runs: list[tuple[int, int]] = Field(min_length=1)
    """Sequence-entry ranges ``[start, stop)`` of the WGFMU executions (entry ``i`` = operation ``i``; the last
    entry is the tail)."""
    biases: list[BiasOutput] = Field(default_factory=list)
    smu_measure: list[MeasureColumn] = Field(default_factory=list)
    columns: list[str] = Field(min_length=4)
    read_s: float = Field(gt=0)
    """Time one stress or recovery read keeps the channels off their phase level (s)."""
    reference_read_s: float = Field(gt=0)
    timing: fb.SenseTiming

    def steps(self, op: fb.BtiOp) -> int:
        """Sense steps of a read (the staircase for the reference read and staircase reads, else one)."""
        return len(self.channels[0].sweep) if op.phase == "reference" or self.read_kind == "staircase" else 1

    def levels(self, channel: fb.BtiChannel, op: fb.BtiOp) -> list[float]:
        """The programmed level of ``channel`` during each row of ``op`` (sense levels or the hold level)."""
        if op.kind == "hold":
            return [channel.stress if op.phase == "stress" else channel.recovery]
        if op.phase == "reference" or self.read_kind == "staircase":
            return list(channel.sweep)
        return [channel.spot]

    @property
    def measuring(self) -> list[fb.BtiChannel]:
        return [c for c in self.channels if c.role.measure is not None]


@dataclass
class WgfmuStressAcquisition(RawAcquisition):
    """``RawAcquisition`` plus the readings of each completed WGFMU execution: the traces of the measuring channels
    and the block of the SMU reading after it (``None`` when none was taken)."""

    traces: list[dict[int, WgfmuTrace]] = field(default_factory=list)
    smu: list[RawBlock | None] = field(default_factory=list)


def is_wgfmu_plan(plan: PlanRecord) -> bool:
    """Whether ``plan`` holds a WGFMU stress program."""
    return plan.program.get(PATH_KEY) == PATH


def stored(plan: PlanRecord) -> tuple[WgfmuStressProgram, WaveformProgram]:
    """The kind program and the whole fast-BTI waveform program of ``plan``.

    Raises:
        CompileError: If the plan holds no valid WGFMU stress program.
    """
    data = {k: v for k, v in plan.program.items() if k != SOURCE_PLAN_KEY}
    try:
        program = WgfmuStressProgram.model_validate(data)
        sources = SourcePlan.model_validate(plan.program.get(SOURCE_PLAN_KEY) or {})
    except ValidationError as exc:
        raise CompileError(f"plan {plan.plan_id} has no valid WGFMU stress program: {exc}") from None
    if sources.waveform is None:
        raise CompileError(f"plan {plan.plan_id} has no waveform program")
    return program, sources.waveform


# -- compile ---------------------------------------------------------------------------------------------------------


def _value(params: Mapping[str, Quantity], name: str, default: Any = None) -> Any:
    quantity = params.get(name)
    return default if quantity is None else quantity.value


def _real(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _int(value: object, what: str) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompileError(f"{what} must be an integer, got {value!r}")
    return value


def _setting(spec: RoleSpec, params: Mapping[str, Quantity], key: str, default: Any = None) -> Any:
    return setting_value(spec, key, dict(params), default)


def _sweep(name: str, spec: RoleSpec, params: Mapping[str, Quantity]) -> list[float]:
    start = _real(_setting(spec, params, "start"), f"{name}.start")
    stop = _real(_setting(spec, params, "stop"), f"{name}.stop")
    points = _int(_setting(spec, params, "points"), f"{name}.points")
    if points < 2:
        raise CompileError(f"{name}.points must be >= 2 (the staircase of the reference read), got {points}")
    return [round(start + (stop - start) * i / (points - 1), 12) for i in range(points)]


def bti_channels(roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], params: Mapping[str, Quantity],
                 read_kind: str) -> list[fb.BtiChannel]:
    """The ``BtiChannel`` of each WGFMU role (module docstring: exactly one swept role).

    Raises:
        CompileError: Without exactly one swept role, without a stress level or with unusable settings.
    """
    swept = [name for name, (_, spec) in roles.items() if all(k in spec.settings for k in SWEEP_SETTINGS)]
    if len(swept) != 1:
        raise CompileError(f"fast_bti: exactly one WGFMU role gives the sense staircase (settings start, stop, "
                           f"points), found {swept or 'none'}")
    sweep = _sweep(swept[0], roles[swept[0]][1], params)
    out: list[fb.BtiChannel] = []
    for name, (role, spec) in roles.items():
        stress = _setting(spec, params, STRESS_SETTING)
        if stress is None:
            raise CompileError(f"{name}: a WGFMU stress role needs setting {STRESS_SETTING} (its level during the "
                               "stress, V)")
        recovery = _real(_setting(spec, params, RECOVERY_SETTING, 0.0), f"{name}.{RECOVERY_SETTING}")
        if name == swept[0]:
            spot = _setting(spec, params, LEVEL_SETTING)
            if spot is None and read_kind == "spot":
                raise CompileError(f"read_kind spot senses the swept role {name} at its setting {LEVEL_SETTING}, "
                                   "which it lacks")
            levels, level = sweep, _real(sweep[0] if spot is None else spot, f"{name}.{LEVEL_SETTING}")
        else:
            level = _real(_setting(spec, params, LEVEL_SETTING, 0.0), f"{name}.{LEVEL_SETTING}")
            levels = [level] * len(sweep)
        out.append(fb.BtiChannel(role=role, stress=_real(stress, f"{name}.{STRESS_SETTING}"), recovery=recovery,
                                 sweep=levels, spot=level))
    return out


def bti_ops(params: Mapping[str, Quantity]) -> list[fb.BtiOp]:
    """The run's operations from the ``stress_measure`` schedule on the 10 ns grid (module docstring)."""
    stress, recovery = schedule(dict(params), grid=wf.TICK_S, min_read=fb.MIN_FIRST_READ_S)
    ops = [fb.BtiOp(kind="read", cycle=0, phase="reference")]
    t = 0.0
    for segment in segments_of(stress, recovery, grid=wf.TICK_S):
        t = round(t + segment.seconds, 12)
        ops.append(fb.BtiOp(kind="hold", cycle=segment.cycle, phase=segment.phase, seconds=segment.seconds, t_s=t))
        ops.append(fb.BtiOp(kind="read", cycle=segment.cycle, phase=segment.phase, t_s=t))
    return ops


def timing_of(params: Mapping[str, Quantity]) -> fb.SenseTiming:
    """The sense timing parameters (``edge``, ``width``, ``settle``; module docstring)."""
    values = {k: _real(_value(params, k, default), k) for k, default in DEFAULT_TIMING.items()}
    try:
        return fb.SenseTiming(**values)
    except ValidationError as exc:
        raise CompileError(f"sense timing: {exc.errors()[0]['msg']} ({values})") from None


def build(roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], params: Mapping[str, Quantity]
          ) -> tuple[wf.BuiltWaveform, list[fb.BtiChannel], list[fb.BtiOp], fb.SenseTiming, fb.ReadKind]:
    """The ``fast_bti`` program of a recipe's WGFMU roles and parameters (also kind ``wgfmu_waveform``'s builder
    ``fast_bti``, which runs it in one execution)."""
    read_kind = _value(params, READ_KIND_PARAM, "staircase")
    if read_kind not in fb.READ_KINDS:
        raise CompileError(f"{READ_KIND_PARAM} must be one of {list(fb.READ_KINDS)} for a WGFMU stress, got "
                           f"{read_kind!r}")
    channels = bti_channels(roles, params, str(read_kind))
    ops = bti_ops(params)
    timing = timing_of(params)
    return fb.fast_bti(channels, ops, timing=timing, read_kind=read_kind), channels, ops, timing, read_kind


def _wg_role(name: str, spec: RoleSpec, params: Mapping[str, Quantity], channel: int) -> wf.WgRole:
    if spec.measure not in ([], ["I"]):
        raise CompileError(f"role {name}: a WGFMU stress role measures [I] (the current at the sense levels and "
                           f"the stress monitor) or nothing, not {spec.measure}")
    rng = _setting(spec, params, RANGE_SETTING, DEFAULT_RANGE)
    if rng not in CURRENT_RANGE_A:
        raise CompileError(f"role {name}: {RANGE_SETTING} must be one of {sorted(CURRENT_RANGE_A)}, got {rng!r}")
    return wf.WgRole(role=name, channel=channel, measure="I" if spec.measure else None, current_range=rng)


def _smu_roles(recipe: Recipe, params: Mapping[str, Quantity], binding: ChannelBinding
               ) -> tuple[list[BiasOutput], list[MeasureColumn], dict[int, ChannelEnvelope]]:
    biases: list[BiasOutput] = []
    measure: list[MeasureColumn] = []
    envelopes: dict[int, ChannelEnvelope] = {}
    for name, spec in recipe.roles.items():
        if spec.function not in SMU_FUNCTIONS:
            continue
        bound = binding.roles.get(name)
        if bound is None or bound.channel is None:
            continue  # GNDU (nothing sent) or unbound: R-PIN-01 decides
        if spec.measure not in ([], ["I"]) or (spec.measure and spec.function != "bias_v"):
            raise CompileError(f"role {name}: an SMU role of a WGFMU stress measures [I] (bias_v only) or nothing")
        icomp = _setting(spec, params, COMPLIANCE_SETTING)
        if icomp is None:
            raise CompileError(f"role {name}: an SMU {spec.function} role needs setting {COMPLIANCE_SETTING}")
        comp = _real(icomp, f"{name}.{COMPLIANCE_SETTING}")
        level = _real(_setting(spec, params, LEVEL_SETTING, 0.0), f"{name}.{LEVEL_SETTING}") \
            if spec.function == "bias_v" else 0.0
        biases.append(BiasOutput(role=name, channel=bound.channel, level=level, comp=comp))
        if spec.measure:
            measure.append(MeasureColumn(channel=bound.channel, role=name, quantity="I"))
        envelopes[bound.channel] = ChannelEnvelope(role=name, max_abs_v=abs(level), max_abs_i=abs(comp),
                                                   function=spec.function, v_start=level, v_stop=level)
    return biases, measure, envelopes


def _columns(channels: Sequence[fb.BtiChannel], biases: Sequence[BiasOutput]) -> list[str]:
    sources = [f"{c.role.role}_V" for c in channels] + [f"{b.role}_V" for b in biases]
    measured: list[str] = []
    for c in channels:
        if c.role.measure is not None:
            measured += [f"{c.role.role}_I", f"{c.role.role}_I_status"]
    return ["step", "t_s", "cycle", "phase", *sources, *measured]


def run_ranges(program: WaveformProgram, ops: Sequence[fb.BtiOp]) -> list[tuple[int, int]]:
    """The WGFMU executions: the reference read alone, then ``fast_bti.batches`` of the rest."""
    if len(ops) == 1:
        return [(0, 2)]
    rest = fb.batches(program, ops)
    first, *others = rest
    return [(0, 1), (1, first[1]), *others] if first[1] > 1 else [(0, 1), *others]


def _rest_routes(routes: Sequence[Route], station: StationProfile) -> list[Route]:
    rest = []
    for route in routes:
        switch = station.switch(route.switch)
        if switch is not None:
            rest.append(Route(switch=route.switch, output=route.output, state=switch.rest))
    return rest


def compile_plan(kind_id: str, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                 station: StationProfile) -> CompiledKindPlan:
    """The WGFMU stress plan (module docstring)."""
    other = sorted(f"{n} ({r.function})" for n, r in recipe.roles.items()
                   if r.function != WGFMU_FUNCTION and r.function not in SMU_FUNCTIONS)
    if other:
        raise CompileError(f"{kind_id} with WGFMU roles cannot execute role(s) {', '.join(other)}; it supports "
                           "wgfmu, bias_v and ground")
    roles: dict[str, tuple[wf.WgRole, RoleSpec]] = {}
    routes: list[Route] = []
    wanted = 0
    for name, spec in recipe.roles.items():
        if spec.function != WGFMU_FUNCTION:
            continue
        bound = binding.roles.get(name)
        if bound is None and spec.optional:
            continue
        wanted += 1
        if bound is not None and bound.via is not None:
            routes.append(bound.via)
        if bound is None or bound.channel is None:
            continue
        roles[name] = (_wg_role(name, spec, params, bound.channel), spec)
    if not wanted or len(roles) != wanted:  # unbound or wiring unknown: R-PIN-01 blocks the plan
        return CompiledKindPlan(envelope=CompiledEnvelope(channels={}, routes=frozenset(routes)),
                                estimate=Estimate(points=0, duration_s=0.0))
    biases, measure, smu_envelopes = _smu_roles(recipe, params, binding)
    built, channels, ops, timing, read_kind = build(roles, params)
    program = built.program
    runs = run_ranges(program, ops)
    envelopes: dict[int, ChannelEnvelope] = dict(smu_envelopes)
    limits: dict[int, WaveformLimits] = {}
    for channel in channels:
        ch = channel.role.channel
        envelopes[ch] = ChannelEnvelope(role=channel.role.role, max_abs_v=max(abs(v) for v in program.levels(ch)),
                                        max_abs_i=None, function=WGFMU_FUNCTION)
        limits[ch] = WaveformLimits(max_vectors=max(1, wf.max_vectors(program, ch)), max_points=program.points(ch),
                                    total_time_s=program.sequence_time_s(ch))
    stress_times = [op.t_s for op in ops if op.kind == "read" and op.phase == "stress"]
    recovery_times = [op.t_s for op in ops if op.kind == "read" and op.phase == "recovery"]
    t_stress = stress_times[-1]
    sources = SourcePlan(
        waveform=program,
        stress={c.role.channel: DcStress(level_v=c.stress, recovery_v=c.recovery) for c in channels},
        schedule=StressSchedule(stress_s=t_stress, reads=len(stress_times),
                                recovery_s=round(recovery_times[-1] - t_stress, 12) if recovery_times else 0.0,
                                recovery_reads=len(recovery_times)))
    read_steps = len(channels[0].sweep) if read_kind == "staircase" else 1
    stored_program = WgfmuStressProgram(
        read_kind=read_kind, channels=channels, ops=ops, runs=runs, biases=biases, smu_measure=measure,
        columns=_columns(channels, biases), read_s=fb.read_seconds(timing, read_steps),
        reference_read_s=fb.read_seconds(timing, len(channels[0].sweep)), timing=timing)
    data: dict[str, Any] = stored_program.model_dump(mode="json")
    data[SOURCE_PLAN_KEY] = sources.model_dump(mode="json")
    ordered = sorted(set(routes), key=Route.sort_key)
    phases = {"waveform": ordered, "rest": _rest_routes(ordered, station)} if ordered else {}
    return CompiledKindPlan(
        envelope=CompiledEnvelope(channels=envelopes, routes=frozenset(ordered), waveform=limits),
        estimate=_estimate(stored_program, program), flex_preview=preview(stored_program), program=data,
        routes_by_phase=phases)


def _run_seconds(program: WaveformProgram, start: int, stop: int) -> float:
    return fb.slice_program(program, start, stop).total_time_s()


def _estimate(program: WgfmuStressProgram, waveform: WaveformProgram) -> Estimate:
    values = {c.role.channel: fb.entry_values(waveform, c.role.channel) for c in program.measuring}
    duration = SETUP_OVERHEAD_S
    segment = 0.0
    for index, (start, stop) in enumerate(program.runs):
        seconds = _run_seconds(waveform, start, stop)
        readback = sum(sum(v[start:stop]) for v in values.values()) * READBACK_S_PER_VALUE
        smu = SMU_READ_S if program.smu_measure and index < len(program.runs) - 1 else 0.0
        duration += seconds + RUN_OVERHEAD_S + readback + smu
        segment = max(segment, min(seconds, CHECKPOINT_S) + RUN_OVERHEAD_S + readback + smu)
    return Estimate(points=_row_count(program), duration_s=round(duration, 6), max_segment_s=round(segment, 6))


def _row_count(program: WgfmuStressProgram) -> int:
    return sum(program.steps(op) if op.kind == "read" else 1 for op in program.ops)


def preview(program: WgfmuStressProgram) -> list[str]:
    """The FLEX writes of the SMU roles: ``CN``, the levels, the spot setup and one ``XE`` per reading between two
    WGFMU executions (the library calls are no FLEX)."""
    if not program.biases:
        return []
    lines = [flex.cn([b.channel for b in program.biases]), *(bias_command(b) for b in program.biases)]
    if program.smu_measure:
        lines += [flex.fmt(1, 0), flex.mm(1, [m.channel for m in program.smu_measure]),
                  *(flex.cmm(m.channel, 1) for m in program.smu_measure)]
        lines += [flex.XE] * (len(program.runs) - 1)
    return lines


def checkpoint_total(plan: PlanRecord) -> int:
    """Progress units of a WGFMU stress run: its operations (reads and holds)."""
    program, _ = stored(plan)
    return len(program.ops)


# -- table -----------------------------------------------------------------------------------------------------------


class _Rows:
    """Table rows of the WGFMU executions in order (shared by the checkpoints and ``to_table``)."""

    def __init__(self, program: WgfmuStressProgram, waveform: WaveformProgram) -> None:
        self.program = program
        self.waveform = waveform
        self.step = 0
        self.values = {c.role.channel: fb.entry_values(waveform, c.role.channel) for c in program.measuring}

    def _row(self, **fields: object) -> dict[str, object]:
        row = {c: fields.get(c, "") for c in self.program.columns}
        row["step"] = self.step
        self.step += 1
        return row

    def run(self, index: int, traces: Mapping[int, WgfmuTrace]) -> list[dict[str, object]]:
        """Rows of execution ``index`` (one per sense step of each read, one per hold).

        Raises:
            ValueError: If a measuring channel returned another number of values than the execution stores.
        """
        program = self.program
        start, stop = program.runs[index]
        cursor: dict[int, int] = {}
        for channel in program.measuring:
            ch = channel.role.channel
            trace = traces.get(ch)
            expected = sum(self.values[ch][start:stop])
            if trace is None or len(trace) != expected:
                got = "no readback" if trace is None else f"{len(trace)} values"
                raise ValueError(f"WGFMU stress execution {index + 1}: channel {ch} returned {got}, the program stores "
                                 f"{expected}")
            cursor[ch] = 0
        rows: list[dict[str, object]] = []
        biases = {f"{b.role}_V": b.level for b in program.biases}
        for op in program.ops[start:min(stop, len(program.ops))]:
            count = program.steps(op) if op.kind == "read" else 1
            for k in range(count):
                fields: dict[str, object] = {"t_s": op.t_s, "cycle": op.cycle,
                                             "phase": "read" if op.kind == "read" else op.phase, **biases}
                for channel in program.channels:
                    fields[f"{channel.role.role}_V"] = program.levels(channel, op)[k]
                    if channel.role.measure is None:
                        continue
                    ch = channel.role.channel
                    value = float(traces[ch].value[cursor[ch]])
                    cursor[ch] += 1
                    full = CURRENT_RANGE_A[channel.role.current_range]
                    fields[f"{channel.role.role}_I"] = value
                    fields[f"{channel.role.role}_I_status"] = SATURATED if abs(value) >= full * OVERRANGE_FRACTION \
                        else NORMAL
                rows.append(self._row(**fields))
        return rows


def stop_reason(rows: Sequence[Mapping[str, object]], index: int) -> str:
    """Why the run stops after execution ``index`` (a saturated WGFMU value), or ``""``."""
    flagged = sorted({str(v) for row in rows for k, v in row.items()
                      if k.endswith("_status") and str(v) in STOP_STATUSES})
    if not flagged:
        return ""
    first = next(row for row in rows for k, v in row.items() if k.endswith("_status") and str(v) in STOP_STATUSES)
    where = f"cycle {first['cycle']} ({first['phase']}, t_s {first['t_s']} s)"
    return (f"WGFMU execution {index + 1} reported status {','.join(flagged)} first at {where}: a saturated range "
            "(V: a broken gate, a short or a range below the current)")


class SmuMonitor:
    """The SMU readings between executions (module docstring: ``kind_result`` facts, never table rows)."""

    def __init__(self, columns: Sequence[MeasureColumn]) -> None:
        self.columns = list(columns)
        self.values: dict[str, list[float]] = {f"{c.role}_I": [] for c in self.columns}
        self.letters: dict[str, list[str]] = {f"{c.role}_I": [] for c in self.columns}

    def add(self, block: RawBlock, index: int) -> str:
        """Record one reading; returns the stop reason (``""`` when the reading is fine).

        Raises:
            ValueError: If the block does not hold one element per measuring SMU.
        """
        if len(block.points) != len(self.columns):
            raise ValueError(f"SMU reading: expected {len(self.columns)} elements, got {len(block.points)}")
        flagged = []
        for column, element in zip(self.columns, block.points, strict=True):
            name = f"{column.role}_I"
            letter = str(element.status.value)
            self.values[name].append(float(element.value))
            self.letters[name].append(letter)
            if letter in STOP_STATUSES:
                flagged.append(f"{name} {letter}")
        if not flagged:
            return ""
        return (f"the SMU reading after WGFMU execution {index + 1} reported {', '.join(flagged)} (compliance, "
                "overflow or oscillation of the bias SMU)")

    def facts(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, values in self.values.items():
            out[f"{name}_reads"] = len(values)
            if values:
                letters = self.letters[name]
                out.update({f"{name}_first": values[0], f"{name}_last": values[-1],
                            f"{name}_max_abs": max(abs(v) for v in values),
                            f"{name}_status": next((x for x in letters if x != "N"), "N")})
        return out


def to_table(raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
    """The run table of a WGFMU stress run (module docstring).

    Raises:
        ValueError: If no execution completed or the readings do not match the program.
    """
    program, waveform = stored(plan)
    if not isinstance(raw, WgfmuStressAcquisition) or not raw.traces:
        raise ValueError("WGFMU stress: no completed WGFMU execution")
    builder = _Rows(program, waveform)
    rows: list[dict[str, object]] = []
    for index, traces in enumerate(raw.traces):
        rows += builder.run(index, traces)
    return pd.DataFrame(rows, columns=program.columns)


# -- acquire ---------------------------------------------------------------------------------------------------------


def _smu_on(tx: Transaction, program: WgfmuStressProgram) -> None:
    """The SMU roles in WG Ex. 10's order inside the phase: ``CN``, ``ERRX?`` drain, ``LOP?`` (hardware), the guarded
    levels, the spot setup of the measuring roles and an ``ERRX?`` drain."""
    driver = tx.driver
    channels = [b.channel for b in program.biases]
    driver.enable(channels)
    drain_or_raise(tx, "enabling the SMU bias")
    tx.mark("SMU bias outputs enabled")
    tx.lop_positive_control(channels)
    set_levels(tx, program.biases)
    if program.smu_measure:
        driver.set_format(1, 0)
        driver.spot_setup([m.channel for m in program.smu_measure], {m.channel: 1 for m in program.smu_measure})
    drain_or_raise(tx, "the SMU bias levels")


def _done_by(program: WgfmuStressProgram, waveform: WaveformProgram, start: int, stop: int, elapsed: float) -> int:
    """Operations complete ``elapsed`` seconds into execution ``[start, stop)``."""
    times = fb.entry_seconds(waveform, program.channels[0].role.channel)
    end = 0.0
    done = start
    for index in range(start, min(stop, len(program.ops))):
        end += times[index] + (WGFMU_SEQUENCE_GAP_S if index > start else 0.0)
        if end > elapsed + 1e-12:
            break
        done = index + 1
    return done


def acquire(kind_id: str, tx: Transaction, plan: PlanRecord) -> WgfmuStressAcquisition:
    """Execute the stored WGFMU stress program (module docstring); every level passes the guard."""
    program, waveform = stored(plan)
    ops = program.ops
    total = len(ops)
    channels = sorted(c.role.channel for c in program.channels)
    archive = getattr(tx.run, "save_wgfmu_raw", None)
    writer = getattr(tx.run, "write_program", None)
    if writer is not None:
        writer(RunProgram(kind=kind_id, programs={"stress": ProgramEntry(
            source="wgfmu", channels=channels, spec=waveform.model_dump(mode="json"),
            preview=waveform.preview())}, files=dict(plan.files)))
    rows = _Rows(program, waveform)
    monitor = SmuMonitor(program.smu_measure)
    result = WgfmuStressAcquisition()
    reason = ""
    warnings: list[str] = []
    offsets = dict.fromkeys(channels, 0)
    timeout = 2.0 * SMU_READ_S + READ_TIMEOUT_MARGIN_S
    with tx.wgfmu_phase(flex_io=bool(program.biases)) as wg:
        wg.check_program(waveform)  # the whole schedule before its first pattern reaches the library
        for index, (start, stop) in enumerate(program.runs):
            wg.load(fb.slice_program(waveform, start, stop))
            if index == 0 and program.biases:
                _smu_on(tx, program)
            tx.mark(f"WGFMU execution {index + 1} of {len(program.runs)}: operations {start + 1}..{min(stop, total)}")
            mark = [CHECKPOINT_S]

            def on_poll(elapsed: float, _total: float, start: int = start, stop: int = stop,
                        mark: list[float] = mark) -> None:
                if elapsed < mark[0]:
                    return
                mark[0] = (math.floor(elapsed / CHECKPOINT_S) + 1) * CHECKPOINT_S
                done = _done_by(program, waveform, start, stop, elapsed)
                running = ops[done] if done < total else ops[-1]
                tx.checkpoint(done, total, "read" if running.kind == "read" else running.phase)

            block = wg.run(check_abort=tx.check_abort, on_poll=on_poll)
            traces = dict(block.traces)
            warnings.extend(block.warnings)
            if archive is not None:
                for ch, trace in sorted(traces.items()):
                    archive(ch, trace.time_s, trace.value, offset=offsets[ch], quantity=trace.quantity)
                    offsets[ch] += len(trace)
            smu: RawBlock | None = None
            if program.biases:
                drain_or_raise(tx, f"the SMU bias after WGFMU execution {index + 1}")
            if program.smu_measure and stop < total:
                smu = spot_once(tx, program.smu_measure, timeout)
            result.traces.append(traces)
            result.smu.append(smu)
            taken = rows.run(index, traces)
            done = min(stop, total)
            tx.checkpoint(done, total, "read", rows=taken)
            reason = stop_reason(taken, index) or (monitor.add(smu, index) if smu is not None else "")
            if reason:
                tx.mark("stopped: " + reason)
                break
    tx.mark("data read")
    result.kind_result = {**_result(program, len(result.traces), reason), **monitor.facts(), **warning_facts(warnings)}
    return result


def _result(program: WgfmuStressProgram, runs_done: int, reason: str) -> dict[str, Any]:
    ops = program.ops
    done = ops[:min(program.runs[runs_done - 1][1], len(ops))] if runs_done else []
    holds = [op for op in ops if op.kind == "hold"]
    finished = [op for op in done if op.kind == "hold"]
    stress_end = max((op.t_s for op in holds if op.phase == "stress"), default=0.0)
    recovery_end = max((op.t_s for op in holds if op.phase == "recovery"), default=stress_end)
    stress_done = max((op.t_s for op in finished if op.phase == "stress"), default=0.0)
    recovery_done = max((op.t_s for op in finished if op.phase == "recovery"), default=stress_done)
    return {"path": PATH, "read_kind": program.read_kind, "reads_planned": sum(op.kind == "read" for op in ops),
            "reads_done": sum(op.kind == "read" for op in done), "holds_planned": len(holds),
            "holds_done": len(finished), "stress_s_planned": stress_end, "stress_s_done": stress_done,
            "recovery_s_planned": round(recovery_end - stress_end, 12),
            "recovery_s_done": round(max(0.0, recovery_done - stress_end), 12),
            "stopped_early": len(done) < len(ops), "stop_reason": reason, "runs_planned": len(program.runs),
            "runs_done": runs_done, "read_s": program.read_s, "reference_read_s": program.reference_read_s,
            "edge_s": program.timing.edge}


__all__ = ["CHECKPOINT_S", "PATH", "WgfmuStressAcquisition", "WgfmuStressProgram", "acquire", "bti_channels",
           "bti_ops", "build", "checkpoint_total", "compile_plan", "is_wgfmu_plan", "preview", "run_ranges",
           "stop_reason", "stored", "timing_of", "to_table"]

