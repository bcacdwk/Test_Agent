"""The WGFMU path of kind ``pulse_read`` (blueprint v2 2.7 "route -> pulse source (SPGU / SMU pulse / WGFMU) -> route
back -> read (SMU spot/staircase or WGFMU)"; 3.4 row ``fecap.endurance_pund``; WP10.6), and the recipe inputs of
the WGFMU builders ``pund`` and ``program_read`` (``catalog/ferro_waveforms.py``; kind ``wgfmu_waveform``).
``PulseReadKind`` hands every recipe with ``wgfmu`` roles to this module; the schedules (``pulse_schedules.py``),
the operations (``pulse_sources.WgfmuSourceKind``), the table contract and the analyses are the kind's.

**Roles** (a WGFMU role reaches its terminal only through its RSU, ``RSU<ch>.OUT``):

- the *pulse role*: the one ``wgfmu`` role whose settings give an operation level (``program`` and/or ``erase``; with
  ``width``, ``erase_width``, ``base``, ``lead``, ``trail``: ``pulse_sources``); for a PUND read also ``amplitude``
  (V, the PUND level);
- every other ``wgfmu`` role: ``v`` (V, its level during a staircase read, default 0), ``pulse_bias`` (V, its level
  during the operations, cycling bursts and holds, default 0), ``range`` (current range when it measures, default
  ``1ma``); a role measures ``[I]``, ``[V]`` or nothing (no compliance: a reading at full scale is status ``V``);
- exactly one WGFMU role with ``start``/``stop``/``points`` is the *swept role* of a staircase read (often the pulse
  role itself: the FeFET gate);
- ``bias_v`` (SMU, ``v``, ``icomp``) and ``ground`` (the GNDU, or an SMU at 0 V with ``icomp``): held through the run
  (WG Ex. 10); they do not measure (the WGFMU reads).

**Reads** (``read_kind`` must be ``wgfmu``: an SMU read through the RSU's SMU input is not a route these kinds set;
SMU reads belong to the HV-SPGU and SMU pulse sources), ``wgfmu_read``:

- ``sweep`` (default): the swept role steps through its levels (``read_edge`` between levels, ``read_width`` flat,
  ``read_settle`` left out of each step's average: ``ferro_waveforms.read_vectors``), every other channel at its
  ``v``; one row per step. Every schedule (``cycles``, ``grid``, ``retention``) applies.
- ``pund``: a PUND sequence on the pulse role (``amplitude``, parameters ``rise``, ``plateau``, ``delay``, ``interval``,
  ``preset``; ``ferro_waveforms.pund``) with every other channel at 0 V; one row per sample (``event`` P/U/N/D,
  ``t_s`` = the sample's time in its read). It switches the film itself: a *switching read*
  (``pulse_schedules``): schedule ``cycles`` only, the reads are the cycles, no separate reference read.

**Program** (pure): every step of the schedule (``ReadStep``: read, pulse operation, cycling burst, hold) is ONE
WGFMU execution of one sequence entry per channel, all channels aligned (same duration); the first execution starts
with a ``lead`` entry (0 V to the rest levels) and the last ends with a ``tail`` entry when a rest level is not 0.
The *catalog* (``SourcePlan.waveform``: what R-WG-02 checks and the guard admits as a whole before the first
execution) holds each distinct entry once in this order: ``lead``, the operations (by key; a burst's count is its
sequence count), ``read``, the holds (``h<n>``, one per distinct length), ``tail``; an execution is the catalog
restricted to its entries (``execution``). Every pattern starts and ends at its channel's rest level (the pulse
role's ``base``, else ``pulse_bias``), which the WGFMU keeps between executions. Envelope: per WGFMU channel its
largest |level|, the pulse role's pulse envelope (operations, bursts and PUND pulses), ``WaveformLimits`` of the
catalog; RSU routes in phases ``waveform`` and ``rest``.

**Run** (``acquire``): ``program.json``; ``with tx.wgfmu_phase(flex_io=<SMU roles>) as wg:`` the whole catalog
guard-checked (``check_program``), the SMU roles switched on and set (``CN``, ``ERRX?``, ``LOP?`` on hardware, levels),
then per step ``wg.load`` + ``wg.run`` (status polls at most 1 s apart with abort checks; a checkpoint every
``WGFMU_CHECKPOINT_S`` of sequencer time), the measured values archived (``raw/wgfmu-<ch>-<n>.npz``), a checkpoint
after each step (a read's rows with it) and after each ``settle`` segment (host waits after a pulse operation). A
read with a saturated value (status ``V``) stops the run (``kind_result.stop_reason``); the phase exit always runs
the WGFMU safe state (abort, initialize: 0 V, disconnect; close; FLEX relocked). Long plans run asynchronously
(R-RUN-02) and ``safe_shutdown`` cancels within one status poll.

**Table** (the ``pulse_read`` contract): ``step``, ``t_s`` (retention: the time after the write; PUND: the time in
the read), ``cycle``, ``phase``, ``event`` (PUND), per WGFMU role ``<role>_V`` (the programmed level: the read level
of the row, or the PUND level at the sample's time) and, when it measures, ``<role>_<I|V>`` + ``_status``; per SMU
role ``<role>_V``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
import pandas as pd
from pydantic import Field, ValidationError

from b1500_test_agent.catalog import ferro_waveforms as fw
from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.blocks import STOP_STATUSES, drain_or_raise, set_levels
from b1500_test_agent.catalog.fast_bti import SenseTiming
from b1500_test_agent.catalog.kinds.pulse_schedules import (
    MAX_STRESS_CYCLES,
    SEQUENCES,
    GridPoint,
    ReadStep,
    build_steps,
    parse_schedule,
)
from b1500_test_agent.catalog.kinds.pulse_sources import (
    WAIT_SEGMENT_S,
    WGFMU_CHECKPOINT_S,
    WGFMU_EDGE_S,
    WGFMU_RUN_OVERHEAD_S,
    OpName,
    SourceRequest,
    WgfmuOp,
    WgfmuSourceKind,
    setting_op,
)
from b1500_test_agent.catalog.kinds.smu_staircase import BiasOutput, bias_command
from b1500_test_agent.catalog.kinds.wgfmu_waveform import _wg_role
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.driver.wgfmu import WgfmuTrace, warning_facts
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
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
    Pattern,
    SourcePlan,
    WaveformEvent,
    WaveformProgram,
    pulse_envelope,
)
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING, wgfmu_status_letter
from b1500_test_agent.transport.wgfmu.api import CURRENT_RANGE_A, VOLTAGE_RANGE_V

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

PATH_KEY: Final = "path"
PATH: Final = "wgfmu"
"""``plan.program["path"]`` of a WGFMU ``pulse_read`` plan (the FLEX path stores no such key)."""

WGFMU_FUNCTION: Final = "wgfmu"
SMU_FUNCTIONS: Final = frozenset({"bias_v", "ground"})
OP_SETTINGS: Final = ("program", "erase")
SWEEP_SETTINGS: Final = ("start", "stop", "points")
LEVEL_SETTING, PULSE_BIAS_SETTING, AMPLITUDE_SETTING = "v", "pulse_bias", "amplitude"

READ_KIND_PARAM, WGFMU_READ_PARAM, SETTLE_PARAM = "read_kind", "wgfmu_read", "settle"
WGFMU_READS: Final = ("sweep", "pund")
READ_TIMING: Final = {"read_edge": 1e-7, "read_width": 1e-6, "read_settle": 5e-7}
"""Staircase read timing parameters and their defaults (s): edge between levels, flat width, settle."""
PUND_DEFAULTS: Final[dict[str, Any]] = {"rise": 1e-5, "plateau": 0.0, "delay": 1e-5, "interval": 1e-7, "preset": True}
"""PUND read parameters and their defaults (``ferro_waveforms.PundTiming``)."""

SETUP_OVERHEAD_S: Final = 0.5
"""Estimated time of the library session (open, initialize) and the SMU setup."""
READBACK_S_PER_VALUE: Final = 2e-6
"""Estimated readback time per stored value (same fact as ``kinds/wgfmu_waveform.py`` ``READBACK_S_PER_VALUE``)."""
OVERRANGE_FRACTION: Final = 1.0 - 1e-9
SATURATED: Final = wgfmu_status_letter(range_overflow=True, error=False)
NORMAL: Final = wgfmu_status_letter(range_overflow=False, error=False)
LEAD, READ, TAIL = "lead", "read", "tail"


# -- recipe inputs ---------------------------------------------------------------------------------------------------


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


def _one(roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], keys: Sequence[str], what: str) -> str:
    """The one WGFMU role whose settings give any of ``keys``."""
    found = [name for name, (_, spec) in roles.items() if any(k in spec.settings for k in keys)]
    if len(found) != 1:
        raise CompileError(f"exactly one WGFMU role gives {what} (settings {', '.join(keys)}), found "
                           f"{found or 'none'}")
    return found[0]


def sense_timing(params: Mapping[str, Quantity]) -> SenseTiming:
    """The staircase read timing (``read_edge``, ``read_width``, ``read_settle``)."""
    values = {k: _real(_value(params, k, default), k) for k, default in READ_TIMING.items()}
    try:
        return SenseTiming(edge=values["read_edge"], width=values["read_width"], settle=values["read_settle"])
    except ValidationError as exc:
        raise CompileError(f"read timing: {exc.errors()[0]['msg']} ({values})") from None


def pund_timing(name: str, spec: RoleSpec, params: Mapping[str, Quantity]) -> fw.PundTiming:
    """The PUND sequence of the forcing role ``name`` (its ``amplitude``) and the PUND parameters."""
    amplitude = _setting(spec, params, AMPLITUDE_SETTING)
    if amplitude is None:
        raise CompileError(f"role {name}: a PUND needs setting {AMPLITUDE_SETTING} (V, the pulse level)")
    preset = _value(params, "preset", PUND_DEFAULTS["preset"])
    if not isinstance(preset, bool):
        raise CompileError(f"preset must be a bool, got {preset!r}")
    values = {k: _real(_value(params, k, PUND_DEFAULTS[k]), k) for k in ("rise", "plateau", "delay", "interval")}
    try:
        return fw.PundTiming(amplitude=abs(_real(amplitude, f"{name}.{AMPLITUDE_SETTING}")), preset=preset,
                             rise=values["rise"], top=values["plateau"], delay=values["delay"],
                             interval=values["interval"])
    except ValidationError as exc:
        raise CompileError(f"PUND timing: {exc.errors()[0]['msg']} ({values})") from None


def _sweep(name: str, spec: RoleSpec, params: Mapping[str, Quantity]) -> list[float]:
    start = _real(_setting(spec, params, "start"), f"{name}.start")
    stop = _real(_setting(spec, params, "stop"), f"{name}.stop")
    points = _int(_setting(spec, params, "points"), f"{name}.points")
    if points < 1:
        raise CompileError(f"{name}.points must be >= 1, got {points}")
    if points == 1:
        return [start]
    return [round(start + (stop - start) * i / (points - 1), 12) for i in range(points)]


def _shape(name: str, spec: RoleSpec, params: Mapping[str, Quantity]) -> fw.PulseShape:
    lead = _real(_setting(spec, params, "lead", WGFMU_EDGE_S), f"{name}.lead")
    trail = _real(_setting(spec, params, "trail", lead), f"{name}.trail")
    try:
        return fw.PulseShape(base=_real(_setting(spec, params, "base", 0.0), f"{name}.base"), lead=lead, trail=trail)
    except ValidationError as exc:
        raise CompileError(f"role {name}: {exc.errors()[0]['msg']}") from None


def build_waveform(builder: str, roles: Mapping[str, tuple[wf.WgRole, RoleSpec]],
                   params: Mapping[str, Quantity]) -> wf.BuiltWaveform:
    """The ``pund`` or ``program_read`` program of kind ``wgfmu_waveform`` from a recipe's WGFMU roles and parameters
    (``ferro_waveforms``): ``pund``: the role with ``amplitude`` forces; ``program_read``: the role with ``program``
    or ``erase`` pulses and sweeps (``start``/``stop``/``points``), parameters ``sequence``, ``cycles``, ``count``,
    ``period``, ``initial_read`` and the read timing; every other role reads at ``v`` and pulses at ``pulse_bias``."""
    if builder == fw.PUND:
        force = _one(roles, (AMPLITUDE_SETTING,), "the PUND level")
        role, spec = roles[force]
        return fw.pund(role, [r for name, (r, _) in roles.items() if name != force], pund_timing(force, spec, params))
    gate = _one(roles, OP_SETTINGS, "the program/erase pulses")
    role, spec = roles[gate]
    sequence = _value(params, "sequence", "erase_program")
    if sequence not in SEQUENCES:
        raise CompileError(f"sequence must be one of {list(SEQUENCES)}, got {sequence!r}")
    ops = []
    for name in SEQUENCES[sequence]:
        req = setting_op(gate, spec, dict(params), name)
        ops.append(fw.ProgramOp(name=name, level=req.level, width=req.width))
    period = _value(params, "period")
    if period is None:
        raise CompileError("parameter period (s) is required: the pulse period of every operation")
    initial = _value(params, "initial_read", True)
    if not isinstance(initial, bool):
        raise CompileError(f"initial_read must be a bool, got {initial!r}")
    others = [fw.ReadChannel(role=r, read_level=_real(_setting(s, params, LEVEL_SETTING, 0.0), f"{n}.v"),
                             pulse_level=_real(_setting(s, params, PULSE_BIAS_SETTING, 0.0), f"{n}.pulse_bias"))
              for n, (r, s) in roles.items() if n != gate]
    return fw.program_read(role, others, sweep=_sweep(gate, spec, params), ops=ops, shape=_shape(gate, spec, params),
                           period=_real(period, "period"), count=_int(_value(params, "count", 1), "count"),
                           timing=sense_timing(params), cycles=_int(_value(params, "cycles", 1), "cycles"),
                           initial_read=initial)


# -- the stored program ----------------------------------------------------------------------------------------------


class WgChannel(StrictModel):
    """One WGFMU channel of the run: its role, rest level (between steps) and level per read row (staircase read: the
    swept role's levels, else its ``v`` repeated; PUND: unused)."""

    role: wf.WgRole
    rest: float = 0.0
    read: list[float] = Field(default_factory=list)


class WgfmuRead(StrictModel):
    """The WGFMU read: ``sweep`` (``timing``, rows per read = ``steps``) or ``pund`` (``pund``, forcing role ``force``,
    rows = 4 x points)."""

    kind: Literal["sweep", "pund"]
    steps: int = Field(ge=1)
    timing: SenseTiming | None = None
    pund: fw.PundTiming | None = None
    force: str | None = None


class WgfmuPulseReadProgram(StrictModel):
    """The compiled WGFMU ``pulse_read`` program stored in ``PlanRecord.program`` next to ``sources`` (the catalog);
    the schedule fields are those of the FLEX program (``pulse_schedules.ScheduledProgram``), so the ``nvm.py``
    analyses read both alike."""

    path: Literal["wgfmu"] = PATH
    source: Literal["wgfmu"] = "wgfmu"
    pulse_role: str
    pulse_channel: Channel
    channels: list[WgChannel] = Field(min_length=1)
    ops: dict[str, WgfmuOp] = Field(default_factory=dict)
    sequence: list[OpName] = Field(min_length=1)
    cycles: int = Field(ge=1, le=MAX_STRESS_CYCLES)
    initial_read: bool = True
    schedule: Literal["cycles", "grid", "retention"] = "cycles"
    cycle_reads: Literal["every", "log", "list"] = "every"
    checkpoints: list[int] = Field(default_factory=list)
    cycle_period: float | None = Field(default=None, gt=0)
    grid: list[GridPoint] = Field(default_factory=list)
    grid_mode: Literal["reset", "ispp"] = "reset"
    reset_read: bool = True
    read_times: list[float] = Field(default_factory=list)
    precycles: int = Field(default=0, ge=0)
    switching_read: bool = False
    read: WgfmuRead
    settle_s: float = Field(default=0.0, ge=0)
    biases: list[BiasOutput] = Field(default_factory=list)
    entries: list[str] = Field(min_length=2)
    """Catalog entry keys in catalog order (module docstring)."""
    columns: list[str] = Field(min_length=3)
    monitor: None = None
    """No ``MM 10`` monitor: WGFMU holds are one sequencer entry (one checkpoint unit) each."""

    def steps(self) -> list[ReadStep]:
        return build_steps(self)

    def op_chunks(self, key: str) -> int:
        return 1

    @property
    def settle_chunks(self) -> int:
        return math.ceil(self.settle_s / WAIT_SEGMENT_S - 1e-9) if self.settle_s > 0 else 0

    def settle_segments(self) -> list[float]:
        count = self.settle_chunks
        if not count:
            return []
        return [WAIT_SEGMENT_S] * (count - 1) + [round(self.settle_s - WAIT_SEGMENT_S * (count - 1), 9)]

    @property
    def measuring(self) -> list[WgChannel]:
        return [c for c in self.channels if c.role.measure is not None]

    def entry(self, step: ReadStep) -> str:
        """The catalog entry a step runs."""
        if step.action == "read":
            return READ
        if step.action == "hold":
            return hold_key(step.seconds)
        return step.op


def hold_key(seconds: float) -> str:
    """Catalog key of a hold of ``seconds`` (on the 10 ns grid)."""
    return f"h{wf.ticks(seconds)}"


def is_wgfmu_plan(plan: PlanRecord) -> bool:
    """Whether ``plan`` holds a WGFMU ``pulse_read`` program."""
    return plan.program.get(PATH_KEY) == PATH


def stored(plan: PlanRecord) -> tuple[WgfmuPulseReadProgram, WaveformProgram, SourcePlan]:
    """The kind program, the catalog waveform program and the source plan of ``plan``.

    Raises:
        CompileError: If the plan holds no valid WGFMU ``pulse_read`` program.
    """
    data = {k: v for k, v in plan.program.items() if k != SOURCE_PLAN_KEY}
    try:
        program = WgfmuPulseReadProgram.model_validate(data)
        sources = SourcePlan.model_validate(plan.program.get(SOURCE_PLAN_KEY) or {})
    except ValidationError as exc:
        raise CompileError(f"plan {plan.plan_id} has no valid WGFMU pulse_read program: {exc}") from None
    if sources.waveform is None:
        raise CompileError(f"plan {plan.plan_id} has no waveform program")
    return program, sources.waveform, sources


# -- the catalog and the executions ----------------------------------------------------------------------------------


def _patterns(program: WgfmuPulseReadProgram, channel: WgChannel) -> dict[str, Pattern]:
    """The channel's pattern per catalog entry (module docstring); every pattern starts and ends at its rest level
    (``lead``: from 0 V; ``tail``: to 0 V; a PUND read: at 0 V)."""
    rest, name = channel.rest, channel.role.role
    is_pulse = name == program.pulse_role
    edge = fw.duration_ticks([(WGFMU_EDGE_S, 0.0)]) * wf.TICK_S
    out: dict[str, Pattern] = {}
    for key in program.entries:
        if key == LEAD:
            out[key] = Pattern(v0=0.0, vectors=[(edge, rest)])
        elif key == TAIL:
            out[key] = Pattern(v0=rest, vectors=[(edge, 0.0)])
        elif key == READ:
            read = program.read
            if read.kind == "sweep":
                assert read.timing is not None
                out[key] = Pattern(v0=rest, vectors=fw.read_vectors(channel.read, rest, read.timing))
            else:
                assert read.pund is not None
                vectors, _ = fw.pund_vectors(read.pund)
                out[key] = Pattern(v0=0.0, vectors=vectors if name == read.force else
                                   fw.hold_vectors(0.0, fw.duration_ticks(vectors) * wf.TICK_S))
        elif key.startswith("h") and key[1:].isdigit():
            out[key] = Pattern(v0=rest, vectors=fw.hold_vectors(rest, int(key[1:]) * wf.TICK_S))
        else:
            op = program.ops[key]
            vectors = op.vectors()
            out[key] = Pattern(v0=rest, vectors=vectors if is_pulse else
                               fw.hold_vectors(rest, fw.duration_ticks(vectors) * wf.TICK_S))
    return out


def _count(program: WgfmuPulseReadProgram, key: str) -> float:
    return float(program.ops[key].count) if key in program.ops else 1.0


def build_catalog(program: WgfmuPulseReadProgram) -> WaveformProgram:
    """The catalog program (module docstring).

    Raises:
        CompileError: For unusable timing or levels.
    """
    patterns: dict[str, Pattern] = {}
    events: list[WaveformEvent] = []
    sequences: dict[int, list[tuple[str, float]]] = {}
    setups = {}
    for channel in program.channels:
        name = channel.role.role
        own = _patterns(program, channel)
        for key, pattern in own.items():
            patterns[f"{name}_{key}"] = pattern
        sequences[channel.role.channel] = [(f"{name}_{key}", _count(program, key)) for key in program.entries]
        levels = [v for p in own.values() for v in p.levels()]
        setups[channel.role.channel] = wf._setup(channel.role, levels)
        if channel.role.measure is not None:
            pattern = f"{name}_{READ}"
            if program.read.kind == "sweep":
                assert program.read.timing is not None
                events.append(fw.read_event(pattern, READ, 0.0, program.read.steps, program.read.timing))
            else:
                assert program.read.pund is not None
                events += fw.pund_events(pattern, program.read.pund)
    return wf._program("pulse_read", channels=setups, patterns=patterns, events=events, sequences=sequences)


def execution(program: WgfmuPulseReadProgram, catalog: WaveformProgram, keys: Sequence[str]) -> WaveformProgram:
    """The catalog restricted to the entries ``keys`` (in this order) on every channel: one WGFMU execution."""
    sequences = {c.role.channel: [(f"{c.role.role}_{k}", _count(program, k)) for k in keys]
                 for c in program.channels}
    used = {name for items in sequences.values() for name, _ in items}
    return catalog.model_copy(update={
        "patterns": {n: p for n, p in catalog.patterns.items() if n in used},
        "events": [e for e in catalog.events if e.pattern in used],
        "sequences": sequences,
    })


def step_keys(program: WgfmuPulseReadProgram, steps: Sequence[ReadStep], index: int) -> list[str]:
    """The catalog entries of execution ``index``: the step's entry, the ``lead`` before the first and the ``tail``
    after the last."""
    keys = [program.entry(steps[index])]
    if index == 0 and LEAD in program.entries:
        keys.insert(0, LEAD)
    if index == len(steps) - 1 and TAIL in program.entries:
        keys.append(TAIL)
    return keys


# -- compile ---------------------------------------------------------------------------------------------------------


def _wgfmu_roles(recipe: Recipe, params: Mapping[str, Quantity], binding: ChannelBinding
                 ) -> tuple[dict[str, tuple[wf.WgRole, RoleSpec]], list[Route], bool]:
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
    return roles, routes, bool(wanted) and len(roles) == wanted


def _smu_roles(recipe: Recipe, params: Mapping[str, Quantity], binding: ChannelBinding
               ) -> tuple[list[BiasOutput], dict[int, ChannelEnvelope]]:
    biases: list[BiasOutput] = []
    envelopes: dict[int, ChannelEnvelope] = {}
    for name, spec in recipe.roles.items():
        if spec.function not in SMU_FUNCTIONS:
            continue
        if spec.measure:
            raise CompileError(f"role {name}: an SMU role of a WGFMU pulse read holds a bias and measures nothing "
                               "(the WGFMU reads)")
        bound = binding.roles.get(name)
        if bound is None or bound.channel is None:
            continue  # GNDU (nothing sent) or unbound: R-PIN-01 decides
        icomp = _setting(spec, params, COMPLIANCE_SETTING)
        if icomp is None:
            raise CompileError(f"role {name}: an SMU {spec.function} role needs setting {COMPLIANCE_SETTING}")
        comp = _real(icomp, f"{name}.{COMPLIANCE_SETTING}")
        level = _real(_setting(spec, params, LEVEL_SETTING, 0.0), f"{name}.v") if spec.function == "bias_v" else 0.0
        biases.append(BiasOutput(role=name, channel=bound.channel, level=level, comp=comp))
        envelopes[bound.channel] = ChannelEnvelope(role=name, max_abs_v=abs(level), max_abs_i=abs(comp),
                                                   function=spec.function, v_start=level, v_stop=level)
    return biases, envelopes


def _read_spec(roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], params: Mapping[str, Quantity], kind: str,
               pulse_role: str) -> tuple[WgfmuRead, dict[str, list[float]]]:
    """The read and each role's read levels (sweep: the swept role's staircase, every other role's ``v``)."""
    if kind == "pund":
        timing = pund_timing(pulse_role, roles[pulse_role][1], params)
        points = round((2 * timing.rise + timing.top) / timing.interval)
        return WgfmuRead(kind="pund", steps=4 * points, pund=timing, force=pulse_role), {}
    swept = _one(roles, SWEEP_SETTINGS, "the read staircase")
    sweep = _sweep(swept, roles[swept][1], params)
    levels = {name: sweep if name == swept else
              [_real(_setting(spec, params, LEVEL_SETTING, 0.0), f"{name}.v")] * len(sweep)
              for name, (_, spec) in roles.items()}
    return WgfmuRead(kind="sweep", steps=len(sweep), timing=sense_timing(params)), levels


def _entries(steps: Sequence[ReadStep], ops: Mapping[str, WgfmuOp], ramp: bool) -> list[str]:
    holds = list(dict.fromkeys(hold_key(s.seconds) for s in steps if s.action == "hold"))
    return [*([LEAD] if ramp else []), *ops, READ, *holds, *([TAIL] if ramp else [])]


def _columns(program: WgfmuPulseReadProgram) -> list[str]:
    timed = program.schedule == "retention" or program.read.kind == "pund"
    head = ["step", *(["t_s"] if timed else []), "cycle", "phase", *(["event"] if program.read.kind == "pund" else [])]
    sources = [f"{c.role.role}_V" for c in program.channels if c.role.measure != "V"]
    sources += [f"{b.role}_V" for b in program.biases]
    measured: list[str] = []
    for c in program.measuring:
        column = f"{c.role.role}_{c.role.measure}"
        measured += [column, f"{column}_status"]
    return [*head, *sources, *measured]


def _rest_routes(routes: Sequence[Route], station: StationProfile) -> list[Route]:
    rest = []
    for route in routes:
        switch = station.switch(route.switch)
        if switch is not None:
            rest.append(Route(switch=route.switch, output=route.output, state=switch.rest))
    return rest


def compile_plan(kind_id: str, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                 station: StationProfile) -> CompiledKindPlan:
    """The WGFMU ``pulse_read`` plan (module docstring)."""
    other = sorted(f"{n} ({r.function})" for n, r in recipe.roles.items()
                   if r.function != WGFMU_FUNCTION and r.function not in SMU_FUNCTIONS)
    if other:
        raise CompileError(f"{kind_id} with the WGFMU source cannot execute role(s) {', '.join(other)}; it supports "
                           "wgfmu, bias_v and ground (reads are WGFMU reads)")
    read_kind = _value(params, READ_KIND_PARAM, "wgfmu")
    if read_kind != "wgfmu":
        raise CompileError(f"{kind_id}: the WGFMU source reads with the WGFMU ({READ_KIND_PARAM} wgfmu), got "
                           f"{read_kind!r}: an SMU read through the RSU's SMU input is not a route this kind sets; SMU "
                           "reads go with an HV-SPGU (pgu) or SMU (pulse_v) pulse role")
    roles, routes, complete = _wgfmu_roles(recipe, params, binding)
    if not complete:  # unbound or wiring unknown: R-PIN-01 blocks the plan
        return CompiledKindPlan(envelope=CompiledEnvelope(channels={}, routes=frozenset(routes)),
                                estimate=Estimate(points=0, duration_s=0.0))
    pulse_role = _one(roles, OP_SETTINGS, "the program/erase pulses")
    role, spec = roles[pulse_role]
    wgfmu_read = _value(params, WGFMU_READ_PARAM, "sweep")
    if wgfmu_read not in WGFMU_READS:
        raise CompileError(f"{WGFMU_READ_PARAM} must be one of {list(WGFMU_READS)}, got {wgfmu_read!r}")
    plan = parse_schedule(params, source="wgfmu", switching_read=wgfmu_read == "pund")
    compiled = WgfmuSourceKind().compile(SourceRequest(role=pulse_role, spec=spec, channel=role.channel,
                                                       params=params,
                                                       ops=tuple(plan.op_requests(pulse_role, spec, params))))
    read, read_levels = _read_spec(roles, params, str(wgfmu_read), pulse_role)
    base = _real(_setting(spec, params, "base", 0.0), f"{pulse_role}.base")
    channels = []
    for name, (wg_role, own) in roles.items():
        rest = base if name == pulse_role else _real(_setting(own, params, PULSE_BIAS_SETTING, 0.0),
                                                       f"{name}.{PULSE_BIAS_SETTING}")
        channels.append(WgChannel(role=wg_role, rest=rest, read=read_levels.get(name, [])))
    if read.kind == "pund" and any(c.rest != 0.0 for c in channels):
        raise CompileError("a PUND read starts and ends at 0 V on every WGFMU channel (the bottom electrode is the "
                           "virtual ground of the current measurement): base and pulse_bias must be 0")
    if not any(c.role.measure is not None for c in channels):
        raise CompileError(f"recipe {recipe.id}: no WGFMU role measures (give the read role measure: [I])")
    settle = _real(_value(params, SETTLE_PARAM, 0.0), SETTLE_PARAM)
    if settle < 0:
        raise CompileError(f"{SETTLE_PARAM} must not be negative, got {settle:g}")
    biases, smu_envelopes = _smu_roles(recipe, params, binding)
    ops = {k: op for k, op in compiled.ops.items() if isinstance(op, WgfmuOp)}
    fields = {"pulse_role": pulse_role, "pulse_channel": role.channel, "channels": channels, "ops": ops,
              "sequence": plan.sequence, "cycles": plan.cycles, "initial_read": plan.initial_read,
              "schedule": plan.kind, "cycle_reads": plan.cycle_reads, "checkpoints": plan.checkpoints,
              "cycle_period": plan.cycle_period, "grid": plan.grid, "grid_mode": plan.grid_mode,
              "reset_read": plan.reset_read, "read_times": plan.read_times, "precycles": plan.precycles,
              "switching_read": plan.switching_read, "read": read, "settle_s": settle, "biases": biases}
    draft = WgfmuPulseReadProgram(**fields, entries=[READ, TAIL], columns=["step", "cycle", "phase"])
    steps = draft.steps()
    program = draft.model_copy(update={"entries": _entries(steps, ops, any(c.rest != 0.0 for c in channels))})
    program = program.model_copy(update={"columns": _columns(program)})
    catalog = build_catalog(program)
    if max(len(items) for items in catalog.sequences.values()) > WGFMU_SPEC.max_sequences:
        raise CompileError(f"the plan needs {len(program.entries)} distinct WGFMU sequence entries, more than "
                           f"{WGFMU_SPEC.max_sequences}; use fewer grid points or retention reads")
    reads = sum(1 for s in steps if s.action == "read")
    trains = list(compiled.trains) + (fw.pund_trains(read.pund, repeat=reads) if read.pund is not None else [])
    envelopes: dict[int, ChannelEnvelope] = dict(smu_envelopes)
    limits: dict[int, WaveformLimits] = {}
    for channel in channels:
        ch = channel.role.channel
        pulse = pulse_envelope(trains, source_ohm=None, short_circuit_a=WGFMU_SPEC.max_output_a) \
            if channel.role.role == pulse_role else None
        envelopes[ch] = ChannelEnvelope(role=channel.role.role, max_abs_v=max(abs(v) for v in catalog.levels(ch)),
                                        max_abs_i=None, function=WGFMU_FUNCTION, pulse=pulse)
        limits[ch] = WaveformLimits(max_vectors=max(1, wf.max_vectors(catalog, ch)), max_points=catalog.points(ch),
                                    total_time_s=catalog.sequence_time_s(ch))
    data: dict[str, Any] = program.model_dump(mode="json")
    data[SOURCE_PLAN_KEY] = SourcePlan(pulses={role.channel: trains}, waveform=catalog).model_dump(mode="json")
    ordered = sorted(set(routes), key=Route.sort_key)
    phases = {"waveform": ordered, "rest": _rest_routes(ordered, station)} if ordered else {}
    return CompiledKindPlan(envelope=CompiledEnvelope(channels=envelopes, routes=frozenset(ordered), waveform=limits),
                            estimate=_estimate(program, catalog, steps), flex_preview=preview(program), program=data,
                            routes_by_phase=phases)


def _execution_s(program: WgfmuPulseReadProgram, catalog: WaveformProgram, keys: Sequence[str]) -> float:
    return execution(program, catalog, keys).total_time_s()


def _estimate(program: WgfmuPulseReadProgram, catalog: WaveformProgram, steps: Sequence[ReadStep]) -> Estimate:
    per_read = sum(read_values(catalog, c.role.channel) for c in program.measuring) * READBACK_S_PER_VALUE
    duration = SETUP_OVERHEAD_S
    segment = 0.0
    for index, step in enumerate(steps):
        seconds = _execution_s(program, catalog, step_keys(program, steps, index))
        readback = per_read if step.action == "read" else 0.0
        duration += seconds + WGFMU_RUN_OVERHEAD_S + readback
        segment = max(segment, min(seconds, WGFMU_CHECKPOINT_S) + WGFMU_RUN_OVERHEAD_S + readback)
        if step.action == "pulse":
            duration += program.settle_s
            segment = max(segment, *program.settle_segments(), 0.0)
    rows = sum(program.read.steps for s in steps if s.action == "read")
    return Estimate(points=rows, duration_s=round(duration, 6), max_segment_s=round(segment, 6))


def read_values(catalog: WaveformProgram, ch: int) -> int:
    """Values channel ``ch`` stores in one read (the catalog's ``read`` pattern)."""
    name = next((n for n, _ in catalog.sequences.get(ch, []) if n.endswith(f"_{READ}")), None)
    return 0 if name is None else sum(e.data_points for e in catalog.measure_events(name))


def preview(program: WgfmuPulseReadProgram) -> list[str]:
    """The FLEX writes of the SMU roles (``CN``, ``DV``); the WGFMU library calls are no FLEX."""
    if not program.biases:
        return []
    return [flex.cn([b.channel for b in program.biases]), *(bias_command(b) for b in program.biases)]


def checkpoint_total(plan: PlanRecord) -> int:
    """Progress units of a WGFMU pulse read: one per step and one per settle segment."""
    program, _, _ = stored(plan)
    return sum(s.chunks for s in program.steps())


# -- table -----------------------------------------------------------------------------------------------------------


class _Rows:
    """Table rows of the reads in order (shared by the checkpoints and ``to_table``)."""

    def __init__(self, program: WgfmuPulseReadProgram, catalog: WaveformProgram) -> None:
        self.program = program
        self.step = 0
        self.read_program = execution(program, catalog, [READ])
        self.values = {c.role.channel: read_values(catalog, c.role.channel) for c in program.measuring}

    def read(self, step: ReadStep, traces: Mapping[int, WgfmuTrace]) -> list[dict[str, object]]:
        """The rows of one read (``sweep``: one per step; ``pund``: one per sample).

        Raises:
            ValueError: If a measuring channel returned another number of values than one read stores.
        """
        program = self.program
        for c in program.measuring:
            trace = traces.get(c.role.channel)
            if trace is None or len(trace) != self.values[c.role.channel]:
                got = "no readback" if trace is None else f"{len(trace)} values"
                raise ValueError(f"WGFMU read (step {step.index}): channel {c.role.channel} returned {got}, one read "
                                 f"stores {self.values[c.role.channel]}")
        count = program.read.steps
        common: dict[str, object] = {"cycle": step.cycle, "phase": step.phase,
                                     **{f"{b.role}_V": b.level for b in program.biases}}
        if program.schedule == "retention":
            common["t_s"] = step.t_s if step.t_s is not None else ""
        times = self._times() if program.read.kind == "pund" else None
        rows: list[dict[str, object]] = []
        for k in range(count):
            row: dict[str, object] = dict(common)
            if times is not None:
                t, event, levels = times
                row.update(t_s=float(t[k]), event=str(event[k]))
                for c in program.channels:
                    if c.role.measure != "V":
                        row[f"{c.role.role}_V"] = float(levels[c.role.channel][k])
            else:
                for c in program.channels:
                    if c.role.measure != "V":
                        row[f"{c.role.role}_V"] = c.read[k]
            for c in program.measuring:
                value = float(traces[c.role.channel].value[k])
                column = f"{c.role.role}_{c.role.measure}"
                full = CURRENT_RANGE_A[c.role.current_range] if c.role.measure == "I" else \
                    VOLTAGE_RANGE_V[self.read_program.channels[c.role.channel].voltage_range or "10v"]
                row[column] = value
                row[f"{column}_status"] = SATURATED if abs(value) >= full * OVERRANGE_FRACTION else NORMAL
            row["step"] = self.step
            self.step += 1
            rows.append({col: row.get(col, "") for col in program.columns})
        return rows

    def _times(self) -> tuple[np.ndarray, np.ndarray, dict[int, np.ndarray]]:
        """PUND samples of one read: time in the read (window centres), event and every channel's programmed level."""
        ch = self.program.measuring[0].role.channel
        layout = wf.point_layout(self.read_program, ch)
        t = layout.start_s + layout.average_s / 2.0
        levels = {c.role.channel: wf.program_levels(self.read_program, c.role.channel, t)
                  for c in self.program.channels}
        return t, layout.event, levels


def stop_reason(rows: Sequence[Mapping[str, object]], step: ReadStep) -> str:
    """Why the run stops after a read (a saturated WGFMU value), or ``""``."""
    flagged = sorted({str(v) for row in rows for k, v in row.items()
                      if k.endswith("_status") and str(v) in STOP_STATUSES})
    if not flagged:
        return ""
    return (f"read of cycle {step.cycle} ({step.phase}) reported status {','.join(flagged)}: a saturated WGFMU range "
            "(V: a range below the current, a short or a broken film)")


@dataclass
class WgfmuPulseAcquisition(RawAcquisition):
    """``RawAcquisition`` plus the traces of every completed read: ``(step index, traces)``."""

    reads: list[tuple[int, dict[int, WgfmuTrace]]] = field(default_factory=list)


def to_table(raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame | None:
    """The run table (module docstring); ``None`` when the run stopped before its first read.

    Raises:
        ValueError: If the readings do not match the program.
    """
    program, catalog, _ = stored(plan)
    reads = raw.reads if isinstance(raw, WgfmuPulseAcquisition) else []
    if not reads:
        return None
    steps = program.steps()
    builder = _Rows(program, catalog)
    rows: list[dict[str, object]] = []
    for index, traces in reads:
        rows += builder.read(steps[index], traces)
    return pd.DataFrame(rows, columns=program.columns)


# -- acquire ---------------------------------------------------------------------------------------------------------


def _smu_on(tx: Transaction, program: WgfmuPulseReadProgram) -> None:
    """The SMU roles in WG Ex. 10's order inside the phase: ``CN``, ``ERRX?`` drain, ``LOP?`` (hardware), the
    guarded levels and an ``ERRX?`` drain."""
    channels = [b.channel for b in program.biases]
    tx.driver.enable(channels)
    drain_or_raise(tx, "enabling the SMU bias")
    tx.mark("SMU bias outputs enabled")
    tx.lop_positive_control(channels)
    set_levels(tx, program.biases)
    drain_or_raise(tx, "the SMU bias levels")


def _wait(tx: Transaction, seconds: float) -> None:
    """Host wait of ``seconds`` in pieces of at most one second, each followed by an abort check."""
    left = seconds
    while left > 1e-12:
        piece = min(1.0, left)
        tx.wgfmu_link.host_wait(piece)
        tx.check_abort()
        left -= piece


class _Facts:
    """What one ``acquire`` did (``kind_result``)."""

    def __init__(self, program: WgfmuPulseReadProgram, steps: Sequence[ReadStep]) -> None:
        self.program = program
        self.steps = list(steps)
        self.done: list[ReadStep] = []
        self.pulses = 0
        self.burst_cycles = 0
        self.precycles = 0
        self.held_s = 0.0
        self.stop_reason = ""
        self.warnings: list[str] = []
        """The library warnings every execution read (``WgfmuBlock.warnings``; WP10.8)."""

    def add(self, step: ReadStep) -> None:
        self.done.append(step)
        if step.action in ("pulse", "burst"):
            op = self.program.ops[step.op]
            self.pulses += op.count * (2 if op.then is not None else 1)
            if step.action == "burst":
                self.burst_cycles += op.count
                self.precycles += op.count if step.cycle == 0 else 0
        elif step.action == "hold":
            self.held_s += step.seconds

    def _cycles_done(self, reads_done: Sequence[ReadStep]) -> int:
        """Cycles whose reads all ran (every cycle: their number; checkpoints: the last such count)."""
        program = self.program
        per = 1 if program.switching_read else len(program.sequence)
        counted = [s.cycle for s in reads_done if s.cycle > 0]
        complete = [c for c in set(counted) if counted.count(c) == per]
        return len(complete) if program.cycle_reads == "every" else max(complete, default=0)

    def result(self) -> dict[str, Any]:
        program = self.program
        reads = [s for s in self.steps if s.action == "read"]
        reads_done = [s for s in self.done if s.action == "read"]
        bursts = [s for s in self.steps if s.action == "burst"]
        facts: dict[str, Any] = {
            "source": "wgfmu", "path": PATH, "wgfmu_read": program.read.kind, "schedule": program.schedule,
            "sequence": ",".join(program.sequence), "reads_planned": len(reads), "reads_done": len(reads_done),
            "pulse_ops_planned": sum(s.action == "pulse" for s in self.steps),
            "pulse_ops_done": sum(s.action == "pulse" for s in self.done), "pulses_applied": self.pulses,
            "executions": len(self.done), "stopped_early": len(reads_done) < len(reads),
            "stop_reason": self.stop_reason, **warning_facts(self.warnings)}
        if program.schedule == "cycles":
            planned = program.checkpoints[-1] if program.checkpoints else program.cycles
            facts.update(cycles_planned=program.precycles + planned,
                         cycles_done=self.precycles + self._cycles_done(reads_done))
        if bursts:
            facts.update(bursts_planned=len(bursts), bursts_done=sum(s.action == "burst" for s in self.done),
                         burst_cycles_done=self.burst_cycles, precycles=program.precycles)
        if program.schedule == "retention":
            facts.update(held_s=round(self.held_s, 9), retention_s_planned=program.read_times[-1])
        if program.schedule == "grid":
            facts.update(grid_mode=program.grid_mode, grid_points_planned=len(program.grid))
        return facts


def acquire(kind_id: str, tx: Transaction, plan: PlanRecord) -> WgfmuPulseAcquisition:
    """Execute the stored WGFMU pulse read (module docstring); every level passes the guard."""
    program, catalog, _ = stored(plan)
    steps = program.steps()
    total = sum(s.chunks for s in steps)
    channels = sorted(c.role.channel for c in program.channels)
    archive = getattr(tx.run, "save_wgfmu_raw", None)
    writer = getattr(tx.run, "write_program", None)
    if writer is not None:
        writer(RunProgram(kind=kind_id, programs={"waveform": ProgramEntry(
            source="wgfmu", channels=channels, spec=catalog.model_dump(mode="json"),
            preview=catalog.preview())}, files=dict(plan.files)))
    rows = _Rows(program, catalog)
    facts = _Facts(program, steps)
    result = WgfmuPulseAcquisition()
    offsets = dict.fromkeys(channels, 0)
    done = 0
    with tx.wgfmu_phase(flex_io=bool(program.biases)) as wg:
        wg.check_program(catalog)  # every pattern of the plan before the first one reaches the library
        if program.biases:
            _smu_on(tx, program)
        for index, step in enumerate(steps):
            keys = step_keys(program, steps, index)
            wg.load(execution(program, catalog, keys))
            tx.mark(f"step {index + 1} of {len(steps)}: {step.action} {program.entry(step)} (cycle {step.cycle}, "
                    f"{step.phase})")
            mark = [WGFMU_CHECKPOINT_S]

            def on_poll(elapsed: float, _total: float, phase: str = step.phase, mark: list[float] = mark,
                        at: int = done) -> None:
                if elapsed >= mark[0]:
                    mark[0] = (math.floor(elapsed / WGFMU_CHECKPOINT_S) + 1) * WGFMU_CHECKPOINT_S
                    tx.checkpoint(at, total, phase)

            block = wg.run(check_abort=tx.check_abort, on_poll=on_poll)
            traces = dict(block.traces)
            facts.warnings.extend(block.warnings)
            if archive is not None:
                for ch, trace in sorted(traces.items()):
                    archive(ch, trace.time_s, trace.value, offset=offsets[ch], quantity=trace.quantity)
                    offsets[ch] += len(trace)
            if program.biases:
                drain_or_raise(tx, f"the SMU bias after step {index + 1}")
            facts.add(step)
            if step.action == "read":
                taken = rows.read(step, traces)
                result.reads.append((index, traces))
                done += 1
                tx.checkpoint(done, total, step.phase, rows=taken)
                facts.stop_reason = stop_reason(taken, step)
                if facts.stop_reason:
                    tx.mark("stopped: " + facts.stop_reason)
                    break
                continue
            done += 1
            tx.checkpoint(done, total, step.phase)
            if step.action == "pulse":
                for seconds in program.settle_segments():
                    _wait(tx, seconds)
                    done += 1
                    tx.checkpoint(done, total, step.phase)
    tx.mark("data read")
    result.kind_result = facts.result()
    result.message = (f"{result.kind_result['pulse_ops_done']} pulse operation(s), {facts.burst_cycles} cycling "
                      f"burst cycle(s) and {result.kind_result['reads_done']} WGFMU {program.read.kind} read(s)"
                      + (f"; stopped: {facts.stop_reason}" if facts.stop_reason else ""))
    return result


__all__ = ["PATH", "WGFMU_READS", "WgfmuPulseAcquisition", "WgfmuPulseReadProgram", "WgfmuRead", "acquire",
           "build_catalog", "build_waveform", "checkpoint_total", "compile_plan", "execution", "is_wgfmu_plan",
           "pund_timing", "sense_timing", "step_keys", "stored", "to_table"]

