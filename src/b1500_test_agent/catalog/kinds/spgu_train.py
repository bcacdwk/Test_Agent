"""Pulse modes of kind ``spgu_pulse`` (blueprint v2 2.7, WP9.3): HV-SPGU pulse trains (``pg``: 2-/3-level pulses
bounded by a count or a duration) and arbitrary linear waveforms (``alwg``), through the 16440A selector when a role's
terminal hangs on one, optionally with SMU spot readings while the train runs (charge pumping).

**Roles.** At least one ``pgu`` role (an HV-SPGU channel, e.g. ``101``, or a selector output ``SEL1.OUT1`` whose PGU
input carries one); optional SMU roles ``bias_v``/``ground``/``measure_only`` (compiled by ``smu_spot``: levels,
compliances, ``integration``, ``samples``, ranging), of which at least one measures: they read during the train.

**pgu role settings** (``$param`` references allowed; V, s, Ohm):

- both modes: ``load_ohm`` (the ``SER`` load the output level is adjusted to; required: R-SPGU-01);
- ``pg``: ``base`` (default 0; a ``float_list`` on one pgu role steps the base level: base-level charge pumping),
  ``peak`` or ``amplitude`` (peak = base + amplitude, kept when the base steps), ``width`` or ``duty`` (width = duty x
  period on the 10 ns grid, kept when the frequency steps), ``delay`` (default 0), ``lead`` (default 20 ns) and
  ``trail`` (default = ``lead``); ``three_level`` (bool, default false) adds pulse source 2 with ``peak2``, ``width2``
  (or ``duty2``), ``base2`` (default 0) and ``delay2`` (default 0): the channel outputs the sum of both sources (PG
  p146 (2-58));
- ``alwg``: ``levels`` and ``times`` (``float_list``s of equal length: the vectors, each a linear ramp over its time
  to its level) and ``initial`` (the pattern's initial level, default 0); one pattern per channel, all patterns
  equally long (the channels run one shared sequence).

**Recipe parameters read by name:** ``period`` (s) or ``frequency`` (Hz, a ``float_list`` steps it; rounded to the
10 ns period resolution; PG); ``count`` (pulses, ALWG: sequences) or ``duration`` (s) bounds every output (free run
cannot be expressed): the one the enum parameter ``bound`` names, else the only one the recipe declares;
``repeat`` (ALWG pattern cycles per sequence, default 1); ``settle`` (s, the wait after ``SRP`` before a read; default
10 ms). With SMU roles every output must last at least ``settle + 2 x samples x read time + 50 ms``.

**Points.** One output per grid point, base levels outer and frequencies inner (one point without lists). Each point
is one ``SpguPulseProgram``/``AlwgProgram`` (``models/spgu.py``) in ``plan.program["spgu_programs"]`` (R-PULSE-01 checks
each against ``SPGU_SPEC.program_problems``); their per-channel guard trains form the ``SourcePlan``
(``plan.program["sources"]``: identical trains merged with ``repeat``), from which ``models.sources.pulse_envelope``
gives each pgu channel's pulse envelope (open-load level at the DUT, width span, duty, pulses and on-time per start,
short-circuit current) and R-PULSE-02/-03, R-SPGU-01 and the summary read the levels and totals.

**Routes.** Every role bound through a switch (``blocks.route_steps``: a pgu role through a selector takes ``pgu``)
is routed in phase ``pulse`` before the output switches go on and returned to its rest state in phase ``rest`` at the
end (both through ``Transaction.apply_routes``: guarded, settle time, read-back); the cleanup returns and verifies
every declared switch whatever happens.

**Acquire.** ``SPST?`` must read 0 (no output left running); phase ``pulse``; ``FMT``/``AAD``/``AIT`` of the SMU
read, ``CN`` of every SMU and SPGU channel, ``ERRX?`` drain, on hardware the ``LOP?`` positive control of the SMUs, the
SMU levels, ``MM 1``/``CMM``/``RI``, ``ERRX?`` drain; then per point ``blocks.spgu_burst`` (setup, ``SPUPD``, ``SRP``;
with SMU roles: ``settle``, then ``samples`` spot reads, and the train must still run afterwards; ``SPST?`` polls to the
end with abort checks and a checkpoint every ``WAIT_SEGMENT_S`` of waiting; the ATV-19 fallback ``SPP``); finally
phase ``rest``. ``kind_result``: mode, points, pulses planned, output time planned and waited, ``SPP`` fallbacks.

**Table** (with SMU roles only): one row per spot reading: ``step``, ``freq_hz`` (the pulse frequency: 1/period; ALWG:
1/sequence period), ``<pgu role>_V`` (the programmed base level; ALWG: the initial level; no status: a source value),
the SMU roles' measured ``<role>_<I|V>`` + status and their constant source columns.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import Field, ValidationError

from b1500_test_agent.catalog.blocks import (
    RouteStep,
    apply_routes,
    drain_or_raise,
    route_lines,
    route_steps,
    set_levels,
    spgu_burst,
    spgu_poll_s,
)
from b1500_test_agent.catalog.kinds.smu_spot import SPOT_FUNCTIONS, SmuSpotKind, SpotProgram
from b1500_test_agent.catalog.kinds.smu_staircase import SETUP_OVERHEAD_S, bias_command
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, B1500Driver, RawBlock
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.driver.modules import SPGU_SPEC
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import (
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
)
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.routing import SELECTOR_SETTLE_S, Route
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, PulseTrain, SourcePlan, pulse_envelope
from b1500_test_agent.models.spgu import (
    SPGU_PROGRAMS_KEY,
    AlwgChannel,
    AlwgPattern,
    AlwgProgram,
    AlwgVector,
    SpguChannel,
    SpguProgram,
    SpguPulseProgram,
    SpguSource,
    spgu_programs,
)
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

PG: Final = "pg"
ALWG: Final = "alwg"
PULSE_MODES: Final = (PG, ALWG)
"""The pulse modes of ``spgu_pulse`` this module compiles."""

PULSE_ROUTE: Final = "selector_16440a:pgu"
"""Card ``routes`` entry of a pgu role through a 16440A selector (skill lint)."""

PERIOD_PARAM, FREQUENCY_PARAM = "period", "frequency"
COUNT_PARAM, DURATION_PARAM, BOUND_PARAM = "count", "duration", "bound"
REPEAT_PARAM, SETTLE_PARAM = "repeat", "settle"

DEFAULT_SETTLE_S = 0.01
"""Default wait after ``SRP`` before the first read of a train (the gate reaches its periodic steady state within a
few periods; the SMU integrates over many)."""

READ_MARGIN_S = 0.05
"""Allowance per train for the trigger and the transfer of its reads (on top of ``2 x samples x read time``)."""

CONFIGURE_OVERHEAD_S = 0.05
"""Estimated bus time of one SPGU setup (``SIM`` ... ``SPUPD``, ``SRP``, the drains)."""

WAIT_SEGMENT_S = 10.0
"""Longest wait for an output's end between two checkpoints (cancel latency; R-RUN-02's ``segment_max_s``)."""

ROUTE_OVERHEAD_S = 0.05
"""Estimated bus time of one route phase besides the settle time (``ERMOD``, ``ERSSP``, read-back)."""

MAX_POINTS = 1001
"""Most outputs (grid points) of one plan."""

DEFAULT_LEAD_S = 2e-8
"""Initial SPGU transition time (PG Table 2-12)."""


class TrainPoint(StrictModel):
    """One output of the plan: its program (index into ``plan.program["spgu_programs"]``), its frequency (Hz) and
    each pgu role's base (PG) or initial (ALWG) level (V, the table's source columns)."""

    program: int = Field(ge=0)
    freq_hz: float = Field(gt=0)
    levels: dict[str, float]


class TrainProgram(StrictModel):
    """The compiled pulse-mode program (``PlanRecord.program`` without the ``spgu_programs``/``sources`` keys)."""

    mode: Literal["pg", "alwg"]
    pgu: dict[str, Channel] = Field(min_length=1)
    """pgu role -> SPGU channel."""
    points: list[TrainPoint] = Field(min_length=1, max_length=MAX_POINTS)
    spot: SpotProgram | None = None
    """The SMU read during every train (``None``: no SMU roles)."""
    settle_s: float = Field(default=DEFAULT_SETTLE_S, ge=0)
    routes: list[RouteStep] = Field(default_factory=list)
    """Phase ``pulse``: every role through a switch."""
    rest: list[RouteStep] = Field(default_factory=list)
    """Phase ``rest``: the same outputs back to their rest states."""
    chunks: list[int] = Field(default_factory=list)
    """Checkpoints per point (one per ``WAIT_SEGMENT_S`` of output time, at least one)."""

    @property
    def rows(self) -> int:
        """Table rows (spot readings) of the whole plan."""
        return len(self.points) * (self.spot.samples if self.spot is not None else 0)


def stored_program(plan: PlanRecord) -> tuple[TrainProgram, list[SpguProgram]]:
    """The ``TrainProgram`` and the SPGU programs stored in ``plan.program``.

    Raises:
        CompileError: If the stored program is not a pulse-mode program of this kind.
    """
    data = {k: v for k, v in plan.program.items() if k not in (SPGU_PROGRAMS_KEY, SOURCE_PLAN_KEY)}
    try:
        return TrainProgram.model_validate(data), spgu_programs(plan.program)
    except ValidationError as exc:
        raise CompileError(f"plan {plan.plan_id} has no valid spgu_pulse pulse program: {exc}") from None


# -- compile ---------------------------------------------------------------------------------------------------------


def _value(params: dict[str, Quantity], name: str) -> object:
    quantity = params.get(name)
    return None if quantity is None else quantity.value


def _real(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _reals(value: object, what: str) -> list[float]:
    """A float or a non-empty list of floats as a list."""
    if isinstance(value, list):
        if not value:
            raise CompileError(f"{what} must not be an empty list")
        return [_real(v, f"{what}[{i}]") for i, v in enumerate(value)]
    return [_real(value, what)]


def _setting(role: str, spec: RoleSpec, params: dict[str, Quantity], key: str, default: object = None) -> object:
    """Setting ``key`` of pgu role ``role`` (``$param`` resolved; ``default`` when absent)."""
    return setting_value(spec, key, params, default)


def _one_of(role: str, spec: RoleSpec, params: dict[str, Quantity], first: str, second: str) -> tuple[str, object]:
    """Exactly one of two alternative settings (e.g. ``peak``/``amplitude``)."""
    a, b = _setting(role, spec, params, first), _setting(role, spec, params, second)
    if (a is None) == (b is None):
        raise CompileError(f"role {role}: give exactly one of the settings {first} and {second}")
    return (first, a) if a is not None else (second, b)


def _bound(params: dict[str, Quantity]) -> tuple[int | None, float | None]:
    """``count`` or ``duration``: the one named by the enum parameter ``bound`` when the recipe declares it, else the
    one the recipe declares (exactly one; free run cannot be expressed)."""
    chosen = _value(params, BOUND_PARAM)
    count, duration = _value(params, COUNT_PARAM), _value(params, DURATION_PARAM)
    if chosen is not None:
        if chosen not in (COUNT_PARAM, DURATION_PARAM):
            raise CompileError(f"{BOUND_PARAM} must be {COUNT_PARAM} or {DURATION_PARAM}, got {chosen!r}")
        count, duration = (count, None) if chosen == COUNT_PARAM else (None, duration)
    if (count is None) == (duration is None):
        raise CompileError(f"give exactly one of the parameters {COUNT_PARAM} and {DURATION_PARAM}: every SPGU output "
                           "is bounded (free run is never used)")
    if count is not None:
        if isinstance(count, float) and count.is_integer():
            count = int(count)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise CompileError(f"{COUNT_PARAM} must be a positive integer, got {count!r}")
        return count, None
    return None, _real(duration, DURATION_PARAM)


def _on_grid(value: float, step: float = SPGU_SPEC.period_resolution_s) -> float:
    """``value`` rounded to a multiple of ``step`` (the SPGU's 10 ns period and duration resolution)."""
    return round(round(value / step) * step, 12)


def _periods(params: dict[str, Quantity]) -> list[float]:
    """The pulse periods: ``period`` as given, or ``1/frequency`` rounded to the 10 ns period resolution (the table
    records the frequency actually output, 1/period)."""
    period, frequency = _value(params, PERIOD_PARAM), _value(params, FREQUENCY_PARAM)
    if (period is None) == (frequency is None):
        raise CompileError(f"give exactly one of the parameters {PERIOD_PARAM} (s) and {FREQUENCY_PARAM} (Hz)")
    if period is not None:
        return [_real(period, PERIOD_PARAM)]
    values = _reals(frequency, FREQUENCY_PARAM)
    if any(f <= 0 for f in values):
        raise CompileError(f"{FREQUENCY_PARAM} must be positive, got {values}")
    return [_on_grid(1.0 / f) for f in values]


def _pg_channels(pgu: dict[str, tuple[RoleSpec, int]], params: dict[str, Quantity],
                 period: float, bases: dict[str, float]) -> dict[int, SpguChannel]:
    channels: dict[int, SpguChannel] = {}
    for role, (spec, channel) in pgu.items():
        base = bases[role]
        key, level = _one_of(role, spec, params, "peak", "amplitude")
        peak = _real(level, f"{role}.{key}") + (base if key == "amplitude" else 0.0)
        key, timing = _one_of(role, spec, params, "width", "duty")
        width = _real(timing, f"{role}.{key}")
        width = _on_grid(width * period) if key == "duty" else width
        lead = _real(_setting(role, spec, params, "lead", DEFAULT_LEAD_S), f"{role}.lead")
        trail = _setting(role, spec, params, "trail")
        sources = {1: SpguSource(delay_s=_real(_setting(role, spec, params, "delay", 0.0), f"{role}.delay"),
                                 width_s=_round_time(width), lead_s=lead,
                                 trail_s=None if trail is None else _real(trail, f"{role}.trail"),
                                 base_v=round(base, 9), peak_v=round(peak, 9))}
        levels: Literal["two_level", "three_level"] = "two_level"
        three = _setting(role, spec, params, "three_level", False)
        if not isinstance(three, bool):
            raise CompileError(f"role {role}: three_level must be a bool, got {three!r}")
        if three:
            key, timing = _one_of(role, spec, params, "width2", "duty2")
            width2 = _real(timing, f"{role}.{key}")
            width2 = _on_grid(width2 * period) if key == "duty2" else width2
            sources[2] = SpguSource(delay_s=_real(_setting(role, spec, params, "delay2", 0.0), f"{role}.delay2"),
                                    width_s=_round_time(width2), lead_s=lead,
                                    trail_s=None if trail is None else _real(trail, f"{role}.trail"),
                                    base_v=_real(_setting(role, spec, params, "base2", 0.0), f"{role}.base2"),
                                    peak_v=_real(_setting(role, spec, params, "peak2"), f"{role}.peak2"))
            levels = "three_level"
        load = _real(_setting(role, spec, params, "load_ohm"), f"{role}.load_ohm")
        channels[channel] = SpguChannel(load_ohm=load, levels=levels, sources=sources)
    return channels


def _round_time(value: float) -> float:
    """A time rounded to 1 ps (``duty x period`` products keep their 2.5 ns grid; no float residue)."""
    return round(value, 12)


def _alwg_program(pgu: dict[str, tuple[RoleSpec, int]], params: dict[str, Quantity], count: int | None,
                  duration: float | None) -> AlwgProgram:
    channels: dict[int, AlwgChannel] = {}
    for role, (spec, channel) in pgu.items():
        levels = _reals(_setting(role, spec, params, "levels"), f"{role}.levels")
        times = _reals(_setting(role, spec, params, "times"), f"{role}.times")
        if len(levels) != len(times):
            raise CompileError(f"role {role}: {len(levels)} levels but {len(times)} times (one time per vector)")
        initial = _real(_setting(role, spec, params, "initial", 0.0), f"{role}.initial")
        pattern = AlwgPattern(initial_v=initial, vectors=[AlwgVector(dt_s=_round_time(t), v=v)
                                                          for t, v in zip(times, levels, strict=True)])
        load = _real(_setting(role, spec, params, "load_ohm"), f"{role}.load_ohm")
        channels[channel] = AlwgChannel(load_ohm=load, patterns=[pattern])
    repeat = _value(params, REPEAT_PARAM)
    repeat = 1 if repeat is None else repeat
    if isinstance(repeat, float) and repeat.is_integer():
        repeat = int(repeat)
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise CompileError(f"{REPEAT_PARAM} must be a positive integer, got {repeat!r}")
    return AlwgProgram(count=count, duration_s=duration, sequence=[(1, repeat)], channels=channels)


def _merge_trains(programs: list[SpguProgram]) -> dict[int, list[PulseTrain]]:
    """Every program's guard train per channel; identical trains merged into one with ``repeat`` = occurrences."""
    found: dict[int, list[tuple[PulseTrain, int]]] = {}
    for program in programs:
        for ch, trains in program.trains().items():
            for train in trains:
                entries = found.setdefault(ch, [])
                for index, (known, times) in enumerate(entries):
                    if known == train:
                        entries[index] = (known, times + 1)
                        break
                else:
                    entries.append((train, 1))
    return {ch: [t.model_copy(update={"repeat": times}) for t, times in entries] for ch, entries in found.items()}


def _bases(pgu: dict[str, tuple[RoleSpec, int]], params: dict[str, Quantity]) -> tuple[dict[str, float], str | None,
                                                                                      list[float]]:
    """Constant base level per pgu role, and the one role (if any) whose ``base`` is a list, with its levels."""
    constant: dict[str, float] = {}
    listed: tuple[str, list[float]] | None = None
    for role, (spec, _) in pgu.items():
        raw = _setting(role, spec, params, "base", 0.0)
        if isinstance(raw, list):
            if listed is not None:
                raise CompileError(f"at most one pgu role steps its base level; {listed[0]} and {role} give lists")
            listed = (role, _reals(raw, f"{role}.base"))
        else:
            constant[role] = _real(raw, f"{role}.base")
    if listed is None:
        return constant, None, [0.0]
    return constant, listed[0], listed[1]


def compile_train(kind_id: str, mode: str, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                  station: StationProfile) -> CompiledKindPlan:
    """Envelope, estimate, FLEX preview, program and routes of a pulse-mode plan (module docstring).

    Raises:
        CompileError: For requests the kind cannot express (missing or conflicting settings, an output too short for
            its read, values the program models refuse).
    """
    pgu_specs = {name: role for name, role in recipe.roles.items() if role.function == "pgu"}
    smu_specs = {name: role for name, role in recipe.roles.items() if role.function in SPOT_FUNCTIONS}
    other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                   if name not in pgu_specs and name not in smu_specs)
    if other:
        raise CompileError(f"{kind_id} {mode}: cannot execute role(s) {', '.join(other)}; it supports pgu and "
                           f"{', '.join(sorted(SPOT_FUNCTIONS))}")
    if not pgu_specs:
        raise CompileError(f"{kind_id} {mode}: recipe {recipe.id} has no pgu role (an HV-SPGU output)")
    steps = route_steps(binding, station, kind_id=kind_id)
    pgu: dict[str, tuple[RoleSpec, int]] = {}
    for name, spec in pgu_specs.items():
        bound = binding.roles.get(name)
        if bound is None or bound.channel is None:  # unbound or wiring unknown: R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=CompiledEnvelope(channels={}, routes=frozenset(s.route for s in steps)),
                                    estimate=Estimate(points=0, duration_s=0.0))
        pgu[name] = (spec, bound.channel)
    count, duration = _bound(params)
    points: list[TrainPoint] = []
    programs: list[SpguProgram] = []
    try:
        if mode == PG:
            constant, listed, bases = _bases(pgu, params)
            for base in bases:
                levels = {**constant, **({listed: base} if listed is not None else {})}
                for period in _periods(params):
                    program = SpguPulseProgram(period_s=period, count=count, duration_s=duration,
                                               channels=_pg_channels(pgu, params, period, levels))
                    points.append(TrainPoint(program=len(programs), freq_hz=1.0 / period, levels=levels))
                    programs.append(program)
        else:
            for name in (FREQUENCY_PARAM, PERIOD_PARAM):
                if _value(params, name) is not None:
                    raise CompileError(f"{kind_id} alwg: the waveform sets its own timing; no parameter {name}")
            alwg = _alwg_program(pgu, params, count, duration)
            levels = {role: alwg.channels[ch].patterns[0].initial_v for role, (_, ch) in pgu.items()}
            points.append(TrainPoint(program=0, freq_hz=1.0 / alwg.repeat_period_s(), levels=levels))
            programs.append(alwg)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise CompileError(f"{kind_id} {mode}: the SPGU program is not valid ({problems})") from None
    if len(points) > MAX_POINTS:
        raise CompileError(f"{kind_id}: {len(points)} outputs exceed {MAX_POINTS}")
    channels: dict[int, ChannelEnvelope] = {}
    spot: SpotProgram | None = None
    if smu_specs:
        sub = recipe.model_copy(update={"roles": smu_specs})
        compiled = SmuSpotKind().compile(sub, params, binding, station)
        channels.update(compiled.envelope.channels)
        if compiled.program:
            spot = SpotProgram.model_validate(compiled.program)
    settle = _value(params, SETTLE_PARAM)
    settle_s = DEFAULT_SETTLE_S if settle is None else _real(settle, SETTLE_PARAM)
    if settle_s < 0:
        raise CompileError(f"{SETTLE_PARAM} must not be negative, got {settle_s}")
    if spot is not None:
        need = settle_s + 2.0 * spot.samples * spot.row_estimate_s + READ_MARGIN_S
        for point in points:
            output = programs[point.program].output_time_s()
            if output < need:
                raise CompileError(f"{kind_id}: an output of {output:g} s ends before its read ({need:g} s: settle "
                                   f"{settle_s:g} s + {spot.samples} x {spot.row_estimate_s:g} s twice + "
                                   f"{READ_MARGIN_S:g} s); raise {DURATION_PARAM} or {COUNT_PARAM}")
    trains = _merge_trains(programs)
    for role, (_, channel) in pgu.items():
        envelope = pulse_envelope(trains[channel], source_ohm=SPGU_SPEC.output_ohm)
        channels[channel] = ChannelEnvelope(role=role, max_abs_v=envelope.max_abs_v_dut, max_abs_i=None,
                                            function="pgu", v_start=None, v_stop=None, pulse=envelope)
    rest = _rest_steps(steps, station)
    chunks = [max(1, math.ceil(programs[p.program].output_time_s() / WAIT_SEGMENT_S)) for p in points]
    program = TrainProgram(mode=mode, pgu={role: ch for role, (_, ch) in pgu.items()}, points=points, spot=spot,
                           settle_s=settle_s, routes=steps, rest=rest, chunks=chunks)
    stored: dict[str, Any] = program.model_dump(mode="json")
    stored[SPGU_PROGRAMS_KEY] = [p.model_dump(mode="json") for p in programs]
    stored[SOURCE_PLAN_KEY] = SourcePlan(pulses=trains).model_dump(mode="json")
    phases = {"pulse": [s.route for s in steps], "rest": [s.route for s in rest]} if steps else {}
    return CompiledKindPlan(
        envelope=CompiledEnvelope(channels=channels, routes=frozenset(s.route for s in steps)),
        estimate=_estimate(program, programs), flex_preview=_preview(program, programs), program=stored,
        routes_by_phase=phases)


def _rest_steps(steps: list[RouteStep], station: StationProfile) -> list[RouteStep]:
    rest: list[RouteStep] = []
    for step in steps:
        switch = station.switch(step.route.switch)
        if switch is None:
            continue
        route = Route(switch=switch.id, output=step.route.output, state=switch.rest)
        rest.append(step.model_copy(update={"route": route}))
    return rest


def _estimate(program: TrainProgram, programs: list[SpguProgram]) -> Estimate:
    route_s = (SELECTOR_SETTLE_S + ROUTE_OVERHEAD_S) * (2 if program.routes else 0)
    duration = SETUP_OVERHEAD_S + route_s
    segment = 0.0
    for point in program.points:
        output = programs[point.program].output_time_s()
        duration += CONFIGURE_OVERHEAD_S + output + spgu_poll_s(output)
        segment = max(segment, min(output, WAIT_SEGMENT_S) + CONFIGURE_OVERHEAD_S + spgu_poll_s(output))
    return Estimate(points=program.rows, duration_s=round(duration, 6), max_segment_s=round(segment, 6))


def _preview(program: TrainProgram, programs: list[SpguProgram]) -> list[str]:
    """The writes ``acquire_train`` sends, in order (the ``ERRX?``/``SPST?``/``ERSSP?`` queries, the ``LOP?`` control
    and the fallback ``SPP`` are not listed)."""
    lines = route_lines(program.routes)
    spot = program.spot
    smu = list(spot.enable) if spot is not None else []
    if spot is not None:
        integration = spot.integration
        adc = ADC_TYPE_CODES[integration.adc]
        lines.append(flex.fmt(*spot.data_format))
        lines += [flex.aad(m.channel, adc) for m in spot.measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n))
    lines.append(flex.cn([*smu, *sorted(program.pgu.values())]))
    if spot is not None:
        lines += [bias_command(o) for o in spot.outputs]
        lines.append(flex.mm(1, [m.channel for m in spot.measure]))
        lines += [flex.cmm(m.channel, 1 if m.quantity == "I" else 2) for m in spot.measure]
        lines += [flex.ri(r.channel, r.code) for r in spot.ranges]
    for point in program.points:
        lines += B1500Driver.spgu_preview(programs[point.program])
        if spot is not None:
            lines += [flex.XE] * spot.samples
    if program.rest:
        lines += [flex.erssp(s.index, flex.ERSSP_CODES[s.route.state]) for s in program.rest]
    return lines


# -- acquire ---------------------------------------------------------------------------------------------------------


def acquire_train(tx: Transaction, plan: PlanRecord) -> RawAcquisition:
    """Execute a pulse-mode plan (module docstring); every output, level and route passes the guard."""
    program, programs = stored_program(plan)
    if len(programs) <= max(p.program for p in program.points):
        raise CompileError(f"plan {plan.plan_id}: a point names an SPGU program the plan does not store")
    driver = tx.driver
    if driver.pulse_output_active():
        raise DriverError("an SPGU output is already running (SPST? 1); run safe_shutdown first")
    apply_routes(tx, program.routes, phase="pulse")
    spot = program.spot
    smu = list(spot.enable) if spot is not None else []
    if spot is not None:
        driver.set_format(*spot.data_format)
        driver.apply_integration(spot.integration, [m.channel for m in spot.measure])
    driver.enable([*smu, *sorted(program.pgu.values())])
    drain_or_raise(tx, "enabling the outputs")
    tx.mark("outputs enabled")
    tx.lop_positive_control(smu)
    if spot is not None:
        set_levels(tx, spot.outputs)
        driver.spot_setup([m.channel for m in spot.measure],
                          {m.channel: 1 if m.quantity == "I" else 2 for m in spot.measure})
        for ranged in spot.ranges:
            driver.set_range(ranged.channel, "I", ranged.code)
        drain_or_raise(tx, "the SMU read setup")
    blocks: list[RawBlock] = []
    total, done = sum(program.chunks), 0
    waited = 0.0
    fallbacks = 0
    for index, point in enumerate(program.points):
        spgu = programs[point.program]
        first = len(blocks)
        chunk = 0

        def on_wait(elapsed: float, limit: int = program.chunks[index]) -> None:
            nonlocal chunk, done
            reached = min(int(elapsed // WAIT_SEGMENT_S), limit - 1)
            while chunk < reached:
                chunk += 1
                done += 1
                tx.checkpoint(done, total, "pulse")

        result = spgu_burst(tx, spgu, during=_reader(tx, spot, program.settle_s, blocks) if spot is not None else None,
                            on_wait=on_wait, label=f"output {index + 1}/{len(program.points)}")
        waited += result.waited_s
        fallbacks += int(result.stopped_by_spp)
        done += program.chunks[index] - chunk
        rows: Callable[[], list[dict[str, object]]] | None = None
        if spot is not None:
            rows = (lambda i=index, b=blocks[first:]: point_rows(program, i, b))
        tx.checkpoint(done, total, "pulse", rows=rows)
    apply_routes(tx, program.rest, phase="rest")
    planned = sum(t.total_pulses for trains in SourcePlan.model_validate(plan.program[SOURCE_PLAN_KEY]).pulses.values()
                  for t in trains)
    result_facts: dict[str, Any] = {
        "mode": program.mode, "outputs": len(program.points), "pulses_planned": planned,
        "output_s_planned": round(sum(programs[p.program].output_time_s() for p in program.points), 9),
        "waited_s": round(waited, 6), "spp_fallbacks": fallbacks, "readings": len(blocks),
    }
    message = (f"{len(program.points)} SPGU output(s) ran to their end" if not fallbacks else
               f"{len(program.points)} SPGU output(s); {fallbacks} stopped by SPP after SPST? stayed 1 (ATV-19)")
    return RawAcquisition(blocks=blocks, kind_result=result_facts, message=message)


def _reader(tx: Transaction, spot: SpotProgram, settle_s: float, blocks: list[RawBlock]) -> Callable[[], None]:
    """The read during one train: ``settle_s``, then ``samples`` spot measurements (``XE`` + read, abort check)."""
    timeout = 2.0 * spot.row_estimate_s + 10.0

    def read() -> None:
        if settle_s > 0:
            tx.driver.host_wait(settle_s)
        for _ in range(spot.samples):
            blocks.append(tx.driver.execute_and_read(expected_points=len(spot.measure), timeout_s=timeout))
            tx.check_abort()

    return read


def point_rows(program: TrainProgram, index: int, blocks: list[RawBlock]) -> list[dict[str, object]]:
    """Table rows of point ``index`` (its ``samples`` spot readings).

    Raises:
        ValueError: If a block does not hold one element per measured channel in the programmed order.
    """
    spot = program.spot
    assert spot is not None
    point = program.points[index]
    rows: list[dict[str, object]] = []
    for offset, read in enumerate(SmuSpotKind.rows_of(spot, blocks)):
        row: dict[str, object] = {"step": index * spot.samples + offset, "freq_hz": point.freq_hz}
        row.update({f"{role}_V": level for role, level in point.levels.items()})
        row.update({k: v for k, v in read.items() if k != "step"})
        rows.append(row)
    return rows


def train_table(program: TrainProgram, blocks: list[RawBlock]) -> list[dict[str, object]]:
    """Every row of a pulse-mode run's readings (``samples`` blocks per point, in point order).

    Raises:
        ValueError: If there are more blocks than planned readings or a point's blocks are incomplete.
    """
    spot = program.spot
    assert spot is not None
    if len(blocks) > program.rows or len(blocks) % spot.samples:
        raise ValueError(f"spgu_pulse expects whole points of {spot.samples} readings (at most {program.rows}), got "
                         f"{len(blocks)} blocks")
    rows: list[dict[str, object]] = []
    for index in range(len(blocks) // spot.samples):
        rows += point_rows(program, index, blocks[index * spot.samples:(index + 1) * spot.samples])
    return rows
