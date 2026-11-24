"""Pulse sources of kind ``pulse_read`` (blueprint v2 2.7: route -> pulse source (SPGU / SMU pulse / WGFMU) -> route
back -> read), one class per source family behind one small interface, so a source is added without touching the
kind's schedules, routes, reads or table (WP9.4 builds the HV-SPGU and SMU pulse sources; WP10.6 adds the WGFMU source
by registering a class in ``SOURCES``; until then a plan whose pulse role is a ``wgfmu`` role is refused at plan time:
``source_for``).

**Interface** (``PulseSourceKind``): ``family`` (the ``ProgramSource`` it drives: ``spgu``, ``smu``, ``wgfmu``),
``function`` (the pulse role function it serves: ``pgu``, ``pulse_v``, ``wgfmu``), ``compile(request)`` (pure: one
compiled ``op`` per ``OpRequest`` of the request, keyed by the request's ``key``; the channel's pulse trains for the
``SourcePlan``, its pulse envelope, extra program keys), ``seconds(op)``/``segment_s(op)`` (estimate: the whole
operation, the longest stretch between two checkpoints), ``preview(op, programs)`` (the FLEX writes of one operation)
and ``run(tx, op, programs, on_chunk, label)`` (one operation through the guarded driver: it calls ``on_chunk`` after
every intermediate checkpoint unit and returns an ``OpResult``; the caller records the operation's last unit).

**Operations** (``OpRequest``, built by the kind's schedule, WP9.5): ``name`` (``program`` or ``erase``: the table phase
of the read that follows), the peak set ``level`` and ``width``, how often the plan ``runs`` it, and optionally its own
pulse ``count`` and ``period`` (default: the recipe parameters ``count``, pulses per operation, default 1, and
``period``, s). ``setting_op`` reads an operation from the pulse role's settings (``$param`` resolved): ``program`` and
``erase`` (V, the peak set level of that operation's pulses), ``base`` (V, default 0, the level between pulses),
``width`` (s, the program width) and ``erase_width`` (s, default ``width``); the amplitude x width grid of the switching
kinetics gives its operations' levels and widths directly. A **bipolar cycling burst** (``then``: the second pulse's
level and width) is ``count`` periods of two pulses of opposite operations, the second half a period after the first:
one program/erase cycle per period (endurance cycling, wake-up pre-cycling); only the HV-SPGU source has one (a
three-level PG output, the sum of two pulse sources, PG p146 (2-58) "3-level"). Every operation is bounded by its
pulse count (free run cannot be expressed).

- **HV-SPGU** (role function ``pgu``): settings ``lead``/``trail`` (s, default 20 ns / the leading time) and
  ``load_ohm`` (the ``SER`` load, required: R-SPGU-01). One ``SpguPulseProgram`` per operation (``SPRM 1,count``,
  ``SPPER period``) in ``program["spgu_programs"]``: two-level for a pulse operation; three-level for a cycling burst
  (source 1: the first pulse at delay 0 on the role's ``base``; source 2: the second pulse at half the period on 0 V,
  its peak offset by the base so that the output reaches the second level), run by ``blocks.spgu_burst`` (setup,
  ``SPUPD``, ``SRP``, ``SPST?`` polls to the end with abort checks and a checkpoint every ``WAIT_SEGMENT_S`` of waiting,
  the ATV-19 ``SPP`` fallback). Pulse train per operation: its guard train (``SpguPulseProgram.guard_train``; a burst
  counts one guard pulse per cycle, spanning both pulse windows) repeated as often as the plan runs the operation;
  envelope from ``pulse_envelope`` with the SPGU's 50 Ohm output (open-load level, short-circuit current).
- **SMU pulse** (role function ``pulse_v``): settings ``icomp`` (A, required: R-COMP-01) and ``meas_time`` (s; the
  pulsed ADC's time at the end of the pulse, default half the width, at most 20 ms, on the 2 us grid). One ``MM 3``
  ``PulsedSetup`` per operation (``PT 0,width,period``, ``PV ch,0,base,level,icomp``), run by
  ``blocks.smu_pulse_burst``: ``count`` triggers of one pulse each (an SMU pulses once per ``XE`` in MM 3, PG p93
  (2-5)), the pulsed channel's current read at each pulse end (``kind_result``: largest |I| and the status letters; a
  compliance stops the run), a checkpoint every ``chunk`` pulses (at most ``WAIT_SEGMENT_S`` apart). Pulse train per
  operation: one pulse per start, repeated ``count`` x the operation's runs (the HR/MP/HPSMU ``PT`` table, 500 us to
  2 s, R-PULSE-01). The SMU stays the pulsed terminal's read source (``pulse_read``), so the kind merges the read's
  DC envelope into the channel's entry. An SMU has no cycling burst (one trigger per pulse would take hours for 10^6
  cycles): a plan that needs one is refused at plan time.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, Protocol

from pydantic import Field, ValidationError

from b1500_test_agent.catalog.blocks import smu_pulse_burst, smu_pulse_s, spgu_burst, spgu_poll_s
from b1500_test_agent.catalog.kinds.pulsed_roles import DEFAULT_MEAS_FRACTION, MAX_MEAS_TIME_S
from b1500_test_agent.catalog.kinds.spgu_train import CONFIGURE_OVERHEAD_S, DEFAULT_LEAD_S, WAIT_SEGMENT_S
from b1500_test_agent.catalog.schema import CompileError, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver, PulsedSetup, RawBlock
from b1500_test_agent.driver.b1500 import PulseSource as SmuPulse
from b1500_test_agent.driver.modules import SPGU_SPEC
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.plan import PulseEnvelope
from b1500_test_agent.models.recipe import RoleSpec
from b1500_test_agent.models.run import ProgramSource
from b1500_test_agent.models.sources import PulseTrain, pulse_envelope
from b1500_test_agent.models.spgu import SPGU_PROGRAMS_KEY, SpguChannel, SpguProgram, SpguPulseProgram, SpguSource

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

__all__ = [
    "MAX_COUNT",
    "OP_NAMES",
    "PENDING_SOURCES",
    "SOURCES",
    "WAIT_SEGMENT_S",
    "CompiledSource",
    "OpName",
    "OpRequest",
    "OpResult",
    "PulseOp",
    "PulseSourceKind",
    "SmuOp",
    "SmuPulseSourceKind",
    "SourceRequest",
    "SpguOp",
    "SpguSourceKind",
    "other_op",
    "setting_op",
    "source_for",
]

OpName = Literal["program", "erase"]
OP_NAMES: Final[tuple[OpName, ...]] = ("program", "erase")
"""The pulse operations of a program/read sequence (the read rows of each carry its name as ``phase``)."""


def other_op(name: OpName) -> OpName:
    """The opposite operation (``program`` <-> ``erase``)."""
    return "erase" if name == "program" else "program"

PERIOD_PARAM, COUNT_PARAM = "period", "count"
WIDTH_SETTING, ERASE_WIDTH_SETTING, BASE_SETTING = "width", "erase_width", "base"

MAX_COUNT: Final = 1_000_000
"""Most pulses of one operation (the HV-SPGU's ``SPRM 1`` count limit)."""

SMU_SETUP_OVERHEAD_S: Final = 0.05
"""Estimated bus time of one SMU pulse setup (``FMT``, ``AIT``, ``MM``, ``CMM``, ``PT``, ``PV``, the drain)."""


# -- operations ------------------------------------------------------------------------------------------------------


class SpguOp(StrictModel):
    """One HV-SPGU operation: ``count`` pulses at ``level`` (set level) of ``width``; ``program`` indexes the stored
    ``SpguPulseProgram``; ``chunks`` = checkpoint units (one per ``WAIT_SEGMENT_S`` of output, at least one).
    ``bipolar``: a cycling burst of ``count`` periods, each this operation's pulse and then the opposite operation's
    (the stored program is three-level; module docstring)."""

    source: Literal["spgu"] = "spgu"
    name: OpName
    level: float
    width: float = Field(gt=0)
    count: int = Field(ge=1, le=MAX_COUNT)
    program: int = Field(ge=0)
    output_s: float = Field(gt=0)
    chunks: int = Field(ge=1)
    bipolar: bool = False


class SmuOp(StrictModel):
    """One SMU pulse operation: ``count`` triggers of the ``MM 3`` ``setup`` (one pulse each); a checkpoint every
    ``chunk`` pulses (``chunks`` units)."""

    source: Literal["smu"] = "smu"
    name: OpName
    level: float
    width: float = Field(gt=0)
    count: int = Field(ge=1, le=MAX_COUNT)
    setup: PulsedSetup
    chunk: int = Field(ge=1)
    chunks: int = Field(ge=1)


PulseOp = Annotated[SpguOp | SmuOp, Field(discriminator="source")]
"""A compiled operation of any source (WP10.6 adds the WGFMU operation to this union)."""


@dataclass(frozen=True)
class OpRequest:
    """One operation the plan runs (module docstring): ``key`` in the compiled ``ops``, the operation ``name``, its
    peak set ``level`` (V) and ``width`` (s), how often the plan ``runs`` it, its pulse ``count`` and ``period``
    (``None``: the recipe parameters) and, for a bipolar cycling burst, ``then`` = the second pulse's ``(level,
    width)`` half a period later."""

    key: str
    name: OpName
    level: float
    width: float
    runs: int = 1
    count: int | None = None
    period: float | None = None
    then: tuple[float, float] | None = None


@dataclass(frozen=True)
class SourceRequest:
    """What a source compiles from: the pulse role, its channel, the recipe parameters and the operations the plan
    runs (``OpRequest``, in the order the ops are stored)."""

    role: str
    spec: RoleSpec
    channel: int
    params: dict[str, Quantity]
    ops: tuple[OpRequest, ...]

    def setting(self, key: str, default: object = None) -> object:
        return setting_value(self.spec, key, self.params, default)

    def param(self, name: str, default: object = None) -> object:
        quantity = self.params.get(name)
        return default if quantity is None else quantity.value


@dataclass
class CompiledSource:
    """A source's compiled part: the operations by key, the channel's pulse trains and envelope, the most |V| and
    |I| (``None``: no compliance) the channel outputs, and extra program keys (``spgu_programs``)."""

    ops: dict[str, SpguOp | SmuOp]
    trains: list[PulseTrain]
    pulse: PulseEnvelope
    max_abs_v: float
    max_abs_i: float | None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpResult:
    """What one operation did: pulses applied, the SMU readings (one block per pulse), the host time waited, the
    ATV-19 ``SPP`` fallback, the checkpoint units reported, and whether a reading stopped it (``reason``)."""

    pulses: int = 0
    blocks: list[RawBlock] = field(default_factory=list)
    waited_s: float = 0.0
    stopped_by_spp: bool = False
    chunks_reported: int = 0
    stopped: bool = False
    reason: str = ""


class PulseSourceKind(Protocol):
    """One pulse source family of ``pulse_read`` (module docstring)."""

    family: ProgramSource
    function: str

    def compile(self, request: SourceRequest) -> CompiledSource: ...

    def seconds(self, op: SpguOp | SmuOp) -> float: ...

    def segment_s(self, op: SpguOp | SmuOp) -> float: ...

    def preview(self, op: SpguOp | SmuOp, programs: Sequence[SpguProgram]) -> list[str]: ...

    def run(self, tx: Transaction, op: SpguOp | SmuOp, programs: Sequence[SpguProgram], *,
            on_chunk: Callable[[], None], label: str) -> OpResult: ...


# -- shared resolution -----------------------------------------------------------------------------------------------


def _real(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _int_param(request: SourceRequest, name: str, default: int, top: int, what: str) -> int:
    value = request.param(name, default)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= top:
        raise CompileError(f"{name} ({what}) must be an integer 1 to {top}, got {value!r}")
    return value


def _count(request: SourceRequest, op: OpRequest) -> int:
    """Pulses per run of ``op``: its own count or the recipe parameter ``count`` (default 1)."""
    if op.count is not None:
        if not 1 <= op.count <= MAX_COUNT:
            raise CompileError(f"operation {op.key}: {op.count} pulses per start is outside 1 to {MAX_COUNT}")
        return op.count
    return _int_param(request, COUNT_PARAM, 1, MAX_COUNT, "pulses per operation")


def _period(request: SourceRequest, op: OpRequest) -> float:
    """The pulse period of ``op``: its own or the recipe parameter ``period`` (required)."""
    if op.period is not None:
        return op.period
    value = request.param(PERIOD_PARAM)
    if value is None:
        raise CompileError(f"parameter {PERIOD_PARAM} (s) is required: the pulse period of every operation")
    period = _real(value, PERIOD_PARAM)
    if period <= 0:
        raise CompileError(f"{PERIOD_PARAM} must be positive, got {period:g}")
    return period


def setting_op(role: str, spec: RoleSpec, params: dict[str, Quantity], name: OpName, *, key: str | None = None,
               runs: int = 1) -> OpRequest:
    """The operation ``name`` as the pulse role's settings give it (module docstring): level ``program``/``erase``,
    width ``width`` (``erase_width`` for an erase, default ``width``).

    Raises:
        CompileError: If the level or the width is missing or not a positive number.
    """
    width = setting_value(spec, WIDTH_SETTING, params)
    if name == "erase":
        width = setting_value(spec, ERASE_WIDTH_SETTING, params, width)
    if width is None:
        raise CompileError(f"role {role}: setting {WIDTH_SETTING} (s) is required")
    width_s = _real(width, f"{role}.{ERASE_WIDTH_SETTING if name == 'erase' else WIDTH_SETTING}")
    level = setting_value(spec, name, params)
    if level is None:
        raise CompileError(f"role {role}: the plan runs {name} pulses, so setting {name} (V, the pulse level) is "
                           "required")
    if width_s <= 0:
        raise CompileError(f"role {role}: the {name} pulse width must be positive, got {width_s:g}")
    return OpRequest(key=key or name, name=name, level=_real(level, f"{role}.{name}"), width=width_s, runs=runs)


def _chunks(seconds: float) -> int:
    return max(1, math.ceil(seconds / WAIT_SEGMENT_S - 1e-9))


# -- HV-SPGU ---------------------------------------------------------------------------------------------------------


class SpguSourceKind:
    """HV-SPGU pulses through ``blocks.spgu_burst`` (module docstring)."""

    family: ProgramSource = "spgu"
    function = "pgu"

    def compile(self, request: SourceRequest) -> CompiledSource:
        base = _real(request.setting(BASE_SETTING, 0.0), f"{request.role}.{BASE_SETTING}")
        lead = _real(request.setting("lead", DEFAULT_LEAD_S), f"{request.role}.lead")
        trail_raw = request.setting("trail")
        trail = None if trail_raw is None else _real(trail_raw, f"{request.role}.trail")
        load = request.setting("load_ohm")
        if load is None:
            raise CompileError(f"role {request.role}: setting load_ohm (the SER load, Ohm) is required for an HV-SPGU "
                               "pulse (R-SPGU-01)")
        load_ohm = _real(load, f"{request.role}.load_ohm")
        ops: dict[str, SpguOp | SmuOp] = {}
        programs: list[SpguPulseProgram] = []
        trains: list[PulseTrain] = []
        for req in request.ops:
            count, period = _count(request, req), _period(request, req)
            first = SpguSource(width_s=round(req.width, 12), lead_s=lead, trail_s=trail, base_v=round(base, 9),
                               peak_v=round(req.level, 9))
            if req.then is None:
                channel = SpguChannel(load_ohm=load_ohm, sources={1: first})
            else:
                channel = self._bipolar_channel(request, req, first, period, load_ohm, base)
            try:
                program = SpguPulseProgram(period_s=period, count=count, channels={request.channel: channel})
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
                raise CompileError(f"role {request.role}: the {req.key} pulse is not a valid SPGU program "
                                   f"({problems})") from None
            output = program.output_time_s()
            ops[req.key] = SpguOp(name=req.name, level=req.level, width=req.width, count=count,
                                  program=len(programs), output_s=output, chunks=_chunks(output),
                                  bipolar=req.then is not None)
            programs.append(program)
            train = program.guard_train(request.channel).model_copy(update={"repeat": req.runs})
            same = next((i for i, t in enumerate(trains) if t.model_copy(update={"repeat": 1})
                         == train.model_copy(update={"repeat": 1})), None)
            if same is None:
                trains.append(train)
            else:
                trains[same] = trains[same].model_copy(update={"repeat": trains[same].repeat + train.repeat})
        envelope = pulse_envelope(trains, source_ohm=SPGU_SPEC.output_ohm)
        return CompiledSource(ops=ops, trains=trains, pulse=envelope, max_abs_v=envelope.max_abs_v_dut,
                              max_abs_i=None,
                              extra={SPGU_PROGRAMS_KEY: [p.model_dump(mode="json") for p in programs]})

    @staticmethod
    def _bipolar_channel(request: SourceRequest, req: OpRequest, first: SpguSource, period: float, load_ohm: float,
                         base: float) -> SpguChannel:
        """A cycling burst's three-level channel (module docstring): ``first`` at delay 0, the second pulse at half
        the period; both windows (with the trailing edge) must fit their half period.

        Raises:
            CompileError: If a pulse does not fit its half period.
        """
        assert req.then is not None
        level2, width2 = req.then
        half = round(period / 2.0, 12)
        need = max(req.width, width2) + first.trailing_s / SPGU_SPEC.edge_fraction
        if half < need - 1e-15:
            raise CompileError(f"role {request.role}: a cycling period of {period:g} s is too short for pulses of "
                               f"{req.width:g} s and {width2:g} s: each needs half a period of at least {need:g} s "
                               f"(width + trailing / 0.8), so the cycle period must be at least {2 * need:g} s")
        second = SpguSource(delay_s=half, width_s=round(width2, 12), lead_s=first.lead_s, trail_s=first.trail_s,
                            base_v=0.0, peak_v=round(level2 - base, 9))
        return SpguChannel(load_ohm=load_ohm, levels="three_level", sources={1: first, 2: second})

    def seconds(self, op: SpguOp | SmuOp) -> float:
        assert isinstance(op, SpguOp)
        return CONFIGURE_OVERHEAD_S + op.output_s + spgu_poll_s(op.output_s)

    def segment_s(self, op: SpguOp | SmuOp) -> float:
        assert isinstance(op, SpguOp)
        return CONFIGURE_OVERHEAD_S + min(op.output_s, WAIT_SEGMENT_S) + spgu_poll_s(op.output_s)

    def preview(self, op: SpguOp | SmuOp, programs: Sequence[SpguProgram]) -> list[str]:
        assert isinstance(op, SpguOp)
        return B1500Driver.spgu_preview(programs[op.program])

    def run(self, tx: Transaction, op: SpguOp | SmuOp, programs: Sequence[SpguProgram], *,
            on_chunk: Callable[[], None], label: str) -> OpResult:
        assert isinstance(op, SpguOp)
        result = OpResult(pulses=op.count)

        def on_wait(elapsed: float) -> None:
            reached = min(int(elapsed // WAIT_SEGMENT_S), op.chunks - 1)
            while result.chunks_reported < reached:
                result.chunks_reported += 1
                on_chunk()

        burst = spgu_burst(tx, programs[op.program], on_wait=on_wait, label=label)
        result.waited_s, result.stopped_by_spp = burst.waited_s, burst.stopped_by_spp
        return result


# -- SMU pulse -------------------------------------------------------------------------------------------------------


class SmuPulseSourceKind:
    """SMU voltage pulses through ``blocks.smu_pulse_burst`` (module docstring)."""

    family: ProgramSource = "smu"
    function = "pulse_v"

    def compile(self, request: SourceRequest) -> CompiledSource:
        base = _real(request.setting(BASE_SETTING, 0.0), f"{request.role}.{BASE_SETTING}")
        icomp = request.setting("icomp")
        if icomp is None:
            raise CompileError(f"role {request.role}: setting icomp (A) is required for an SMU pulse (R-COMP-01)")
        comp = _real(icomp, f"{request.role}.icomp")
        ops: dict[str, SpguOp | SmuOp] = {}
        trains: list[PulseTrain] = []
        for req in request.ops:
            if req.then is not None:
                raise CompileError(f"role {request.role}: bipolar cycling ({req.key}) needs the HV-SPGU source (a pgu "
                                   "pulse role); an SMU pulses once per trigger, far too slow for cycling bursts")
            count, period = _count(request, req), _period(request, req)
            level, width = req.level, req.width
            default_meas = min(width * DEFAULT_MEAS_FRACTION, MAX_MEAS_TIME_S)
            default_meas = max(flex.PULSE_WIDTH_GRID_S,
                               round(default_meas / flex.PULSE_WIDTH_GRID_S) * flex.PULSE_WIDTH_GRID_S)
            meas = _real(request.setting("meas_time", default_meas), f"{request.role}.meas_time")
            try:
                setup = PulsedSetup(mode=flex.PULSED_SPOT_MODE, measure=(request.channel,),
                                    operation={request.channel: 1}, period=period, meas_time=meas,
                                    pulses=(SmuPulse(channel=request.channel, base=base, peak=level, comp=comp,
                                                     width=width),))
            except ValidationError as exc:
                problems = "; ".join(e["msg"] for e in exc.errors())
                raise CompileError(f"role {request.role}: the {req.key} pulse is not a valid SMU pulse ({problems})") \
                    from None
            chunk = max(1, int(WAIT_SEGMENT_S // smu_pulse_s(setup)))
            ops[req.key] = SmuOp(name=req.name, level=level, width=width, count=count, setup=setup, chunk=chunk,
                                 chunks=math.ceil(count / chunk))
            train = PulseTrain(base_v=base, peak_v=level, width_s=width, period_s=period, count=1,
                               repeat=count * req.runs)
            same = next((i for i, t in enumerate(trains) if t.model_copy(update={"repeat": 1})
                         == train.model_copy(update={"repeat": 1})), None)
            if same is None:
                trains.append(train)
            else:
                trains[same] = trains[same].model_copy(update={"repeat": trains[same].repeat + train.repeat})
        envelope = pulse_envelope(trains, source_ohm=None)
        levels = [abs(base), *(abs(t.peak_v) for t in trains)]
        return CompiledSource(ops=ops, trains=trains, pulse=envelope, max_abs_v=max(levels), max_abs_i=abs(comp))

    def seconds(self, op: SpguOp | SmuOp) -> float:
        assert isinstance(op, SmuOp)
        return SMU_SETUP_OVERHEAD_S + op.count * smu_pulse_s(op.setup)

    def segment_s(self, op: SpguOp | SmuOp) -> float:
        assert isinstance(op, SmuOp)
        return SMU_SETUP_OVERHEAD_S + min(op.chunk, op.count) * smu_pulse_s(op.setup)

    def preview(self, op: SpguOp | SmuOp, programs: Sequence[SpguProgram]) -> list[str]:
        assert isinstance(op, SmuOp)
        return [flex.fmt(1, op.setup.format_mode), *op.setup.commands(), *([flex.XE] * op.count)]

    def run(self, tx: Transaction, op: SpguOp | SmuOp, programs: Sequence[SpguProgram], *,
            on_chunk: Callable[[], None], label: str) -> OpResult:
        assert isinstance(op, SmuOp)
        result = OpResult()

        def on_pulse(index: int, _block: RawBlock) -> None:
            if (index + 1) % op.chunk == 0 and index + 1 < op.count:
                result.chunks_reported += 1
                on_chunk()

        burst = smu_pulse_burst(tx, op.setup, op.count, on_pulse=on_pulse, label=label)
        result.blocks, result.pulses = burst.blocks, len(burst.blocks)
        result.stopped, result.reason = burst.stopped, burst.reason
        return result


# -- registry --------------------------------------------------------------------------------------------------------

SOURCES: Final[dict[str, PulseSourceKind]] = {"pgu": SpguSourceKind(), "pulse_v": SmuPulseSourceKind()}
"""The implemented sources by the pulse role function they serve."""

PENDING_SOURCES: Final[dict[str, str]] = {"wgfmu": "WP10.6"}
"""Pulse role functions of the blueprint's ``pulse_read`` row whose source arrives with a later work package: a plan
naming one is refused at plan time (``source_for``), never run by a stand-in."""


def source_for(role: str, function: str, kind_id: str) -> PulseSourceKind:
    """The source that serves pulse role ``role`` of ``function``.

    Raises:
        CompileError: For a source that arrives with a later work package (the WGFMU source: WP10.6) or a function no
            source serves.
    """
    source = SOURCES.get(function)
    if source is not None:
        return source
    if function in PENDING_SOURCES:
        raise CompileError(f"{kind_id}: role {role} ({function}) selects the WGFMU pulse source; the WGFMU source "
                           f"arrives in {PENDING_SOURCES[function]} (blueprint v2 10.6). Until then pulse with the "
                           "HV-SPGU (a pgu role) or an SMU (a pulse_v role)")
    raise CompileError(f"{kind_id}: no pulse source serves role {role} ({function}); sources: "
                       f"{', '.join(sorted(SOURCES))}")
