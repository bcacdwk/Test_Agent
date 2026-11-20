"""``smu_sampling``: SMU sampling measurement (``MM 10``) with a base→bias step, automatic abort and time stamps;
long runs as repeated ``MM 10`` blocks (blueprint v2 2.7, 3.1 rows ``generic.smu_sampling``,
``mosfet.id_t_sampling``, ``reliability.tddb_cvs``).

Roles (bound to channels through the pin map; each measured role measures one quantity, ``[I]`` or ``[V]``):

- ``bias_v``: settings ``v`` (bias level, V) and ``icomp`` (A), both required; with a ``base`` setting the role is
  a synchronous source (``MV``): ``base`` from the trigger, ``v`` from ``hold_base`` seconds later (the time origin
  of the run, ``t_s = 0``); without it a DC source (``DV``) set before the trigger.
- ``bias_i``: settings ``i`` (A) and ``vcomp`` (V), both required, optional ``base`` (default ``i``): always a
  synchronous current source (``MI``; no ``DI``: it starts with the measurement).
- ``ground`` / ``measure_only``: the GNDU (nothing sent) or an SMU at 0 V (``DV``) whose compliance is setting
  ``icomp`` or, when absent, the sum of the sourcing roles' compliances and currents.
- every other function is refused (sweeps belong to ``smu_staircase``/``smu_stepped``).

Recipe parameters read by the kind (fixed names): ``interval`` (s, required), ``points`` (samples) or ``duration``
(s; ``points = floor(duration / interval) + 1``), ``hold_bias`` (s from the bias step to the first sample, default 0;
negative values, sampling before the step, are not supported because ``t_s`` counts from the step), ``hold_base``
(s of base output, default 0), ``sampling_mode`` (``linear``, the default, or ``log10``/``log25``/``log50``/
``log100``/``log250``/``log500`` = ``ML`` 2-7, data per decade) and ``integration`` (the ``smu_staircase`` ADC
presets). Intervals: 2 ms to 65.535 s in 1 ms steps, or (linear, one block) 0.1-2 ms in 10 us steps with
``interval >= 0.1 ms + 20 us x (channels - 1)``; holds in 10 ms steps (``MT``, PG p475 (4-157)). Log sampling holds
at most ``1 + density x 11`` points.

Blocks (blueprint v2 2.6, R-RUN-02): a linear run whose sampling lasts at most ``SINGLE_BLOCK_MAX_S`` (60 s), and
every log or sub-2 ms run, is one ``MM 10`` block (one ``XE``; the lab's 40 s Id(t) run is one block). A longer
linear run is a chain of blocks of at most ``SEGMENT_S`` (25 s) of sampling each: the first with the step (``MT
h_bias,interval,n,h_base``), then continuation blocks whose synchronous sources hold their bias level as base too
(``MV``/``MI`` base = bias: the stress never drops between blocks, ``MSC`` post = bias keeps it there) and whose
first sample comes one interval (rounded to 10 ms) after their trigger (``MT`` sent only when it changes). The time
stamps run on through the whole chain (one ``TSR`` before the first trigger), so ``t_s`` stays exact across block
boundaries; the gap between blocks is the host round trip (a few ms on GPIB). FMT 1 time stamps keep six
significant digits (0.1 s resolution beyond 10,000 s; PG p539 (4-221) remarks): TODO(verify) at bring-up stages
L5/L9 that the timer runs on over hours without a reset (else ``t_s`` falls back to the index, flagged). Each block
is one checkpoint (``tx.checkpoint``: progress, ``partial.csv``, cancel via ``safe_shutdown``). Real-time reading of
one block while it samples (lwp's unproven path, ATV-30) is not used: progress is per block (the ATV-30 fallback, by
design).

Acquisition (through the guarded driver): ``FMT 1,1`` (each sample carries its sampling index), ``TSC 1``,
``AAD``/``AIT``, ``CN``, ``ERRX?`` drain, on hardware the ``LOP?`` positive control, ``DV`` per DC bias/ground SMU,
``MCC``, ``ML``, ``MT``, ``MSC 2,2`` (automatic abort on compliance of any channel, overflow or oscillation; sources
at bias after a normal end), ``MV``/``MI`` per synchronous source, ``MM 10,<measured>``, ``CMM``, ``ERRX?`` drain
(any error aborts before ``XE``), ``TSR``, then per block (later blocks: ``MT``/``MV``/``MI`` when they change and an
``ERRX?`` drain, so an error of the previous block stops the chain) ``XE`` and one read (timeout ``2 x block
estimate + 10 s``). A block that aborted (a sample with ``C``/``T``/``V``/``X``; the instrument then forces the
sources' base values and returns ``199.999E+99`` for the rest) ends the run:
``kind_result`` says why and when (``abort_t_s``); later blocks are not triggered. Cleanup is the transaction's.

Table (``data.csv`` contract of ``analysis/dataset.py``): one row per measured sample in time order: ``step``
(0-based over the run), ``t_s`` (seconds since the bias step: time stamp minus the origin ``T1 - hold_bias -
(index1 - 1) x interval`` of the first sample; without time stamps the sampling index, with the host's trigger times
between blocks, ``kind_result.time_source`` says which: ATV-22 fallback), measured ``<role>_<I|V>`` + ``_status``,
and the programmed source columns of the bias roles not measuring that quantity (``<role>_V`` at the bias level,
``<role>_I`` for current sources). The dummy samples after an automatic abort carry no information and are left out
(counted in ``kind_result.samples_after_abort``; the raw blocks keep them). Index gaps (a sample skipped because the
measurement took longer than the interval, or discarded by auto ranging, PG p49 (1-29)) show as larger ``t_s``
steps and are counted in ``kind_result.index_gaps``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_staircase import (
    DEFAULT_PRESET,
    INTEGRATION_PARAM,
    INTEGRATION_PRESETS,
    READ_TIMEOUT_MARGIN_S,
    SETUP_OVERHEAD_S,
    BiasOutput,
    MeasureColumn,
    bias_command,
    drain_or_raise,
    force_bias,
    measurement_time_s,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, RawBlock, SamplingSetup, SamplingSource
from b1500_test_agent.driver.sampling import Sample, parse_sampling
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING, VOLTAGE_COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

SAMPLING_FUNCTIONS = frozenset({"bias_v", "bias_i", "ground", "measure_only"})
"""Role functions this kind executes."""

INTERVAL_PARAM = "interval"
POINTS_PARAM = "points"
DURATION_PARAM = "duration"
HOLD_BIAS_PARAM = "hold_bias"
HOLD_BASE_PARAM = "hold_base"
MODE_PARAM = "sampling_mode"
SAMPLING_MODES: dict[str, int] = {"linear": flex.LINEAR_SAMPLING, **{
    f"log{density}": code for code, density in flex.LOG_SAMPLING_DENSITY.items()}}
"""``sampling_mode`` parameter values → ``ML`` code (PG p470 (4-152))."""

DATA_FORMAT = (1, 1)
"""``FMT 1,1``: ASCII with header; mode 1 adds the sampling index to every sample (PG p49 (1-29), p437 (4-119))."""

SINGLE_BLOCK_MAX_S = 60.0
"""A linear run whose sampling (``hold_bias + (points - 1) x interval``) is at most this long is one ``MM 10``
block; longer runs are chains of blocks."""

SEGMENT_S = 25.0
"""Longest sampling span of one block of a chain (s): with ``SEGMENT_OVERHEAD_S`` it keeps the checkpoints within
the default ``policy.run_limits.segment_max_s`` (30 s) of R-RUN-02."""

SEGMENT_OVERHEAD_S = 0.5
"""Allowance per block for the trigger, the data transfer and the checkpoint in the duration estimate."""

ABORT_STATUSES = frozenset("CTVX")
"""Sample statuses after which ``MSC 2`` stops the measurement (compliance of this or another channel, A/D overflow
or invalid data, oscillation; PG p472-473 (4-154))."""

_TIME_STEP = flex.MT_HOLD_RESOLUTION_S


class SourceRole(StrictModel):
    """A synchronous (``MV``/``MI``) source and its recipe role."""

    role: str
    source: SamplingSource


class Block(StrictModel):
    """One ``MM 10`` block of the run: ``MT`` values, whether the block re-sends ``MT`` (``timing``) or the sources
    at their bias level (``hold_sources``) before its ``XE``."""

    number: int = Field(ge=1, le=flex.MT_MAX_NUMBER)
    h_bias: float = Field(ge=0)
    h_base: float = Field(ge=0)
    timing: bool = False
    hold_sources: bool = False


class SamplingProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    data_format: tuple[int, int] = DATA_FORMAT
    integration: Integration
    enable: list[Channel] = Field(min_length=1)
    biases: list[BiasOutput] = Field(default_factory=list)
    synchronous: list[SourceRole] = Field(default_factory=list)
    """The ``MV``/``MI`` sources (not ``sources``: that program key is the typed ``SourcePlan`` of pulse and
    waveform kinds, blueprint v2 2.8 R-PULSE-01)."""
    mode: int = flex.LINEAR_SAMPLING
    interval: float = Field(gt=0)
    h_bias: float = Field(ge=0)
    h_base: float = Field(ge=0)
    points: int = Field(ge=1)
    blocks: list[Block] = Field(min_length=1)
    measure: list[MeasureColumn] = Field(min_length=1, max_length=flex.MAX_CHANNELS_MM)
    source_columns: dict[str, float] = Field(default_factory=dict)
    """Programmed bias levels written as source columns (``drain_V``, ``gate_V`` at its bias, ``stress_I``)."""

    @property
    def width(self) -> int:
        """Elements per sample: index, then time stamp and value per measured channel."""
        return 1 + 2 * len(self.measure)

    def setup(self, block: Block, *, hold: bool) -> SamplingSetup:
        """The driver setup of ``block``; ``hold`` forces the sources' base to their bias (continuation blocks)."""
        sources = tuple(s.source.model_copy(update={"base": s.source.bias}) if hold else s.source
                        for s in self.synchronous)
        return SamplingSetup(mode=self.mode, h_bias=block.h_bias, interval=self.interval, number=block.number,
                             h_base=block.h_base, abort=True, post="bias", sources=sources,
                             measure=tuple(m.channel for m in self.measure),
                             operation={m.channel: (1 if m.quantity == "I" else 2) for m in self.measure})


# -- helpers ---------------------------------------------------------------------------------------------------------


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _param(params: dict[str, Quantity], name: str, default: Any = None) -> Any:
    quantity = params.get(name)
    return default if quantity is None else quantity.value


def _on_grid(value: float, step: float) -> bool:
    return abs(value / step - round(value / step)) < 1e-6


def log_indices(density: int, number: int) -> list[int]:
    """The first ``number`` distinct sampling indices ``round(10^(j/density))`` of log sampling (the estimate's
    reading of PG p476 (4-158); TODO(verify) at bring-up stage L5 which points the instrument holds)."""
    held: list[int] = []
    j = 0
    while len(held) < number:
        index = round(10.0 ** (j / density))
        j += 1
        if not held or index > held[-1]:
            held.append(index)
    return held


def _timing(params: dict[str, Quantity], channels: int) -> tuple[int, float, int, float, float]:
    """``(ML code, interval, points, hold_bias, hold_base)`` from the parameters, checked against ``MT``."""
    mode_name = _param(params, MODE_PARAM, "linear")
    if mode_name not in SAMPLING_MODES:
        raise CompileError(f"{MODE_PARAM} must be one of {sorted(SAMPLING_MODES)}, got {mode_name!r}")
    mode = SAMPLING_MODES[mode_name]
    interval = _number(_param(params, INTERVAL_PARAM), INTERVAL_PARAM)
    if not flex.MT_MIN_INTERVAL_S <= interval <= flex.MT_MAX_INTERVAL_S:
        raise CompileError(f"{INTERVAL_PARAM} must be {flex.MT_MIN_INTERVAL_S} to {flex.MT_MAX_INTERVAL_S} s")
    fast = interval < flex.MT_FAST_INTERVAL_S
    if not _on_grid(interval, 0.00001 if fast else 0.001):
        raise CompileError(f"{INTERVAL_PARAM} {interval} s is off the MT resolution ({'10 us' if fast else '1 ms'})")
    if fast and (mode != flex.LINEAR_SAMPLING
                 or interval < flex.MT_MIN_INTERVAL_S + 0.00002 * (channels - 1) - 1e-12):
        raise CompileError(f"an interval below 2 ms needs linear sampling and at least "
                           f"{flex.MT_MIN_INTERVAL_S + 0.00002 * (channels - 1):g} s for {channels} channel(s)")
    hold_bias = _number(_param(params, HOLD_BIAS_PARAM, 0.0), HOLD_BIAS_PARAM)
    hold_base = _number(_param(params, HOLD_BASE_PARAM, 0.0), HOLD_BASE_PARAM)
    if hold_bias < 0:
        raise CompileError(f"{HOLD_BIAS_PARAM} must be >= 0 (t_s counts from the bias step; sampling before the "
                           "step is not supported)")
    for name, value in ((HOLD_BIAS_PARAM, hold_bias), (HOLD_BASE_PARAM, hold_base)):
        if value > flex.MT_MAX_HOLD_S or not _on_grid(value, _TIME_STEP):
            raise CompileError(f"{name} must be 0 to {flex.MT_MAX_HOLD_S} s in 10 ms steps, got {value}")
    points = _param(params, POINTS_PARAM)
    duration = _param(params, DURATION_PARAM)
    if (points is None) == (duration is None):
        raise CompileError(f"give exactly one of {POINTS_PARAM} and {DURATION_PARAM}")
    if duration is not None:
        duration = _number(duration, DURATION_PARAM)
        if duration < 0:
            raise CompileError(f"{DURATION_PARAM} must be >= 0 s, got {duration}")
        points = math.floor(duration / interval + 1e-9) + 1
    if isinstance(points, float) and points.is_integer():
        points = int(points)
    if isinstance(points, bool) or not isinstance(points, int) or points < 1:
        raise CompileError(f"{POINTS_PARAM} must be a positive integer, got {points!r}")
    if mode != flex.LINEAR_SAMPLING:
        limit = 1 + flex.LOG_SAMPLING_DENSITY[mode] * flex.LOG_SAMPLING_DECADES
        if points > limit:
            raise CompileError(f"{mode_name} sampling holds at most {limit} points (11 decades), got {points}")
    return mode, interval, points, hold_bias, hold_base


def _blocks(mode: int, interval: float, points: int, hold_bias: float, hold_base: float,
            channels: int) -> list[Block]:
    """Split the run into ``MM 10`` blocks (module docstring)."""
    per_block_max = flex.MT_MAX_NUMBER // channels
    span = hold_bias + (points - 1) * interval
    if mode != flex.LINEAR_SAMPLING or interval < flex.MT_FAST_INTERVAL_S or span <= SINGLE_BLOCK_MAX_S:
        if points > per_block_max:
            raise CompileError(f"{points} points exceed {per_block_max} per block for {channels} channel(s)")
        return [Block(number=points, h_bias=hold_bias, h_base=hold_base)]
    per = max(1, min(per_block_max, int(SEGMENT_S // interval)))
    first = max(1, min(per, int((SEGMENT_S - hold_bias) // interval) + 1))
    blocks = [Block(number=min(first, points), h_bias=hold_bias, h_base=hold_base)]
    left = points - blocks[0].number
    h_next = round(round(interval / _TIME_STEP) * _TIME_STEP, 2)
    previous = blocks[0]
    while left > 0:
        number = min(per, left)
        block = Block(number=number, h_bias=h_next, h_base=0.0, hold_sources=len(blocks) == 1)
        block = block.model_copy(update={"timing": (number, h_next, 0.0) != (previous.number, previous.h_bias,
                                                                             previous.h_base)})
        blocks.append(block)
        previous = block
        left -= number
    return blocks


def _block_span_s(program: SamplingProgram, block: Block) -> float:
    """Nominal time from a block's trigger to the end of its last sample."""
    if program.mode != flex.LINEAR_SAMPLING:
        last = log_indices(flex.LOG_SAMPLING_DENSITY[program.mode], block.number)[-1]
        sampling = (last - 1) * program.interval
    else:
        sampling = (block.number - 1) * program.interval
    last_measurement = min(measurement_time_s(program.integration) * len(program.measure), program.interval)
    return block.h_base + block.h_bias + sampling + last_measurement


def read_timeout_for(program: SamplingProgram, block: Block) -> float:
    """Read timeout of one block: ``2 x (block span + allowance) + 10 s`` (blueprint 7)."""
    return 2.0 * (_block_span_s(program, block) + SEGMENT_OVERHEAD_S) + READ_TIMEOUT_MARGIN_S


# -- table -----------------------------------------------------------------------------------------------------------


class _Rows:
    """Turns the blocks of one run, in order, into table rows (shared by ``acquire``'s checkpoints and
    ``to_table``): time origin, ``t_s`` per sample, dropped dummy samples, index gaps."""

    def __init__(self, program: SamplingProgram) -> None:
        self.program = program
        self.origin: float | None = None
        self.time_source: Literal["timestamp", "index", "host"] = "timestamp"
        self.first_xe: float | None = None
        self.step = 0
        self.dummies = 0
        self.gaps = 0
        self.aborted = False
        self.abort_reason = ""
        self.abort_t_s: float | None = None
        self.last_t_s: float | None = None
        self.blocks = 0

    def _t_s(self, sample: Sample, block: Block, first_block: bool, raw: RawBlock) -> float:
        program = self.program
        index = sample.index if sample.index is not None else 1
        nominal = block.h_bias + (index - 1) * program.interval
        if self.time_source == "timestamp" and sample.time is not None:
            if self.origin is None:
                self.origin = sample.time - nominal
            t_s = sample.time - self.origin
            if self.last_t_s is None or t_s >= self.last_t_s - 1e-9:
                return max(t_s, 0.0)
        # ATV-22 fallback: no usable time stamp (missing, or running backwards): the sampling index, and between
        # blocks the host's trigger times (the bias step of the first block is hold_base after its trigger)
        xe = raw.xe_at.timestamp()
        if self.first_xe is None:
            self.first_xe = xe
        self.time_source = "index" if first_block and self.time_source != "host" else "host"
        offset = 0.0 if first_block else xe - self.first_xe - self.program.blocks[0].h_base
        return max(offset + nominal, 0.0)

    def add(self, block: Block, raw: RawBlock) -> list[dict[str, object]]:
        """Rows of one block (after the previous ones)."""
        program = self.program
        first_block = self.blocks == 0
        self.blocks += 1
        if first_block:
            self.first_xe = raw.xe_at.timestamp()
        data = parse_sampling(raw.points, [m.channel for m in program.measure])
        rows: list[dict[str, object]] = []
        previous_index: int | None = None
        for sample in data.samples:
            if sample.dummy:
                self.dummies += 1
                if not self.aborted:  # dummy data without a flagged sample: the instrument stopped the sampling
                    self.aborted = True
                    self.abort_t_s = self.last_t_s
                    after = "the start" if self.last_t_s is None else f"t_s = {self.last_t_s:g} s"
                    self.abort_reason = (f"the instrument returned dummy data (199.999E+99) after {after}: "
                                         "automatic abort or outputs zeroed (interlock)")
                continue
            if previous_index is not None and sample.index is not None and program.mode == flex.LINEAR_SAMPLING:
                self.gaps += max(0, sample.index - previous_index - 1)
            previous_index = sample.index
            t_s = self._t_s(sample, block, first_block, raw)
            self.last_t_s = t_s
            row: dict[str, object] = {"step": self.step, "t_s": t_s}
            flagged = []
            for column, element in zip(program.measure, sample.values, strict=True):
                name = f"{column.role}_{column.quantity}"
                row[name] = element.value
                status = str(element.status.value)
                row[f"{name}_status"] = status
                if status in ABORT_STATUSES:
                    flagged.append(f"{name} {status}")
            for column, level in program.source_columns.items():
                row[column] = level
            rows.append(row)
            self.step += 1
            if flagged and not self.aborted:
                self.aborted = True
                self.abort_t_s = t_s
                self.abort_reason = f"automatic abort at t_s = {t_s:g} s ({', '.join(flagged)})"
        if data.trailing:
            self.abort_reason = self.abort_reason or f"{data.trailing} element(s) of an incomplete sample"
        return rows


def _source_columns(sources: list[SourceRole], biases: list[BiasOutput], measured: set[tuple[str, str]],
                    recipe: Recipe) -> dict[str, float]:
    columns: dict[str, float] = {}
    for item in sources:
        quantity = item.source.quantity
        if (item.role, quantity) not in measured:
            columns[f"{item.role}_{quantity}"] = item.source.bias
    for bias in biases:
        if recipe.roles[bias.role].function == "bias_v" and (bias.role, "V") not in measured:
            columns[f"{bias.role}_V"] = bias.level
    return columns


# -- the kind --------------------------------------------------------------------------------------------------------


class SmuSamplingKind:
    """SMU sampling (``MM 10``) with step, abort, time stamps and block chains (sim and visa code path)."""

    kind_id = "smu_sampling"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program; see the module docstring for the role semantics."""
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in SAMPLING_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(SAMPLING_FUNCTIONS))}")
        integration = self._integration(params)
        channels: dict[int, ChannelEnvelope] = {}
        biases: list[BiasOutput] = []
        sources: list[SourceRole] = []
        grounds: list[tuple[str, int, RoleSpec]] = []
        sourcing = 0.0
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue  # unbound or GNDU: R-PIN-01 decides whether that is allowed
            channel = bound.channel
            if role.function == "bias_v":
                v = _number(setting_value(role, "v", params), f"{name}.v")
                icomp = _number(setting_value(role, COMPLIANCE_SETTING, params), f"{name}.{COMPLIANCE_SETTING}")
                base = setting_value(role, "base", params)
                if base is None:
                    biases.append(BiasOutput(role=name, channel=channel, level=v, comp=icomp))
                    channels[channel] = ChannelEnvelope(role=name, max_abs_v=abs(v), max_abs_i=abs(icomp),
                                                        function="bias_v", v_start=v, v_stop=v)
                else:
                    base = _number(base, f"{name}.base")
                    try:
                        source = SamplingSource(channel=channel, quantity="V", base=base, bias=v, compliance=icomp)
                    except ValueError as exc:
                        raise CompileError(f"{name}: {exc}") from None
                    sources.append(SourceRole(role=name, source=source))
                    channels[channel] = ChannelEnvelope(role=name, max_abs_v=max(abs(base), abs(v)),
                                                        max_abs_i=abs(icomp), function="bias_v", v_start=base,
                                                        v_stop=v)
                sourcing += abs(icomp)
            elif role.function == "bias_i":
                i = _number(setting_value(role, "i", params), f"{name}.i")
                vcomp = _number(setting_value(role, VOLTAGE_COMPLIANCE_SETTING, params),
                                f"{name}.{VOLTAGE_COMPLIANCE_SETTING}")
                base = _number(setting_value(role, "base", params, i), f"{name}.base")
                try:
                    source = SamplingSource(channel=channel, quantity="I", base=base, bias=i, compliance=vcomp)
                except ValueError as exc:
                    raise CompileError(f"{name}: {exc}") from None
                sources.append(SourceRole(role=name, source=source))
                channels[channel] = ChannelEnvelope(role=name, max_abs_v=abs(vcomp),
                                                    max_abs_i=max(abs(base), abs(i)), function="bias_i")
                sourcing += max(abs(base), abs(i))
            else:  # ground or measure_only on an SMU: 0 V
                grounds.append((name, channel, role))
        for name, channel, role in grounds:
            explicit = setting_value(role, COMPLIANCE_SETTING, params)
            icomp = _number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else sourcing
            channels[channel] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(icomp),
                                                function=role.function, v_start=0.0, v_stop=0.0)
            if icomp != 0:
                biases.append(BiasOutput(role=name, channel=channel, level=0.0, comp=icomp))
        envelope = CompiledEnvelope(channels=channels)
        measure = self._measure(recipe, binding)
        if not measure:
            # nothing bound measures: the plan-phase rules block it (R-PIN-01) unless the recipe measures nothing
            if any(role.measure for role in recipe.roles.values()):
                return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
            raise CompileError(f"recipe {recipe.id}: no role measures anything")
        mode, interval, points, hold_bias, hold_base = _timing(params, len(measure))
        blocks = _blocks(mode, interval, points, hold_bias, hold_base, len(measure))
        enable = [b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                  and b.channel is not None]
        measured = {(m.role, m.quantity) for m in measure}
        program = SamplingProgram(
            integration=integration, enable=enable, biases=biases, synchronous=sources, mode=mode, interval=interval,
            h_bias=hold_bias, h_base=hold_base, points=points, blocks=blocks, measure=measure,
            source_columns=_source_columns(sources, biases, measured, recipe))
        try:
            preview = self.preview(program)
        except ValueError as exc:
            raise CompileError(f"invalid sampling setup: {exc}") from None
        spans = [_block_span_s(program, block) + SEGMENT_OVERHEAD_S for block in blocks]
        estimate = Estimate(points=points, duration_s=round(SETUP_OVERHEAD_S + sum(spans), 6),
                            max_segment_s=round(max(spans), 6))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=preview,
                                program=program.model_dump(mode="json"))

    @staticmethod
    def _integration(params: dict[str, Quantity]) -> Integration:
        name = _param(params, INTEGRATION_PARAM, DEFAULT_PRESET)
        if not isinstance(name, str) or name not in INTEGRATION_PRESETS:
            raise CompileError(f"{INTEGRATION_PARAM} must be one of {sorted(INTEGRATION_PRESETS)}, got {name!r}")
        return INTEGRATION_PRESETS[name]

    def _measure(self, recipe: Recipe, binding: ChannelBinding) -> list[MeasureColumn]:
        measure: list[MeasureColumn] = []
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if not role.measure or bound is None or bound.channel is None:
                continue
            if len(role.measure) > 1:
                raise CompileError(f"role {name} measures {role.measure}; {self.kind_id} measures one quantity per "
                                   "channel")
            measure.append(MeasureColumn(channel=bound.channel, role=name, quantity=role.measure[0]))
        return measure

    @staticmethod
    def preview(program: SamplingProgram) -> list[str]:
        """The setup and trigger commands ``acquire`` writes, in order (``ERRX?``/``LOP?`` queries not listed)."""
        integration = program.integration
        adc = ADC_TYPE_CODES[integration.adc]
        lines = [flex.fmt(*program.data_format), flex.tsc(True)]
        lines += [flex.aad(m.channel, adc) for m in program.measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n))
        lines.append(flex.cn(program.enable))
        lines += [bias_command(b) for b in program.biases]
        first = program.setup(program.blocks[0], hold=False)
        lines += [flex.mcc(), flex.ml(first.mode), flex.mt(first.h_bias, first.interval, first.number, first.h_base),
                  flex.msc(first.abort, first.post), *(s.command() for s in first.sources),
                  flex.mm(flex.SAMPLING_MODE, first.measure),
                  *(flex.cmm(ch, op) for ch, op in first.operation.items()), flex.tsr(), flex.XE]
        for block in program.blocks[1:]:
            setup = program.setup(block, hold=True)
            if block.timing:
                lines.append(flex.mt(setup.h_bias, setup.interval, setup.number, setup.h_base))
            if block.hold_sources:
                lines += [s.command() for s in setup.sources]
            lines.append(flex.XE)
        return lines

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints ``acquire`` reports: one per block (fewer when the run aborts)."""
        return len(SamplingProgram.model_validate(plan.program).blocks) if plan.program else 0

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (see the module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = SamplingProgram.model_validate(plan.program)
        driver = tx.driver
        driver.set_format(*program.data_format)
        driver.set_time_stamp(True)
        driver.apply_integration(program.integration, [m.channel for m in program.measure])
        driver.enable(program.enable)
        drain_or_raise(tx, "enabling the outputs")
        tx.mark("outputs enabled")
        tx.lop_positive_control(program.enable)
        for bias in program.biases:
            force_bias(tx, bias)
        driver.sampling_setup(program.setup(program.blocks[0], hold=False))
        drain_or_raise(tx, "the sampling setup")
        tx.mark("configured")
        driver.reset_timer()
        rows = _Rows(program)
        raws: list[RawBlock] = []
        total = len(program.blocks)
        for number, block in enumerate(program.blocks):
            if number:
                if block.timing or block.hold_sources:
                    driver.sampling_update(program.setup(block, hold=True), timing=block.timing,
                                           sources=block.hold_sources)
                drain_or_raise(tx, f"block {number} (before block {number + 1})")
            raw = driver.execute_and_read(expected_points=block.number * program.width,
                                          timeout_s=read_timeout_for(program, block))
            raws.append(raw)
            block_rows = rows.add(block, raw)
            tx.checkpoint(number + 1, total, "sampling", rows=block_rows)
            if rows.aborted and number + 1 < total:
                tx.mark(f"stopped: {rows.abort_reason}; {total - number - 1} block(s) not triggered")
                break
        tx.mark("data read")
        return RawAcquisition(blocks=raws, kind_result=self._result(program, rows, len(raws)))

    @staticmethod
    def _result(program: SamplingProgram, rows: _Rows, done: int) -> dict[str, Any]:
        return {"blocks_planned": len(program.blocks), "blocks_done": done, "samples_planned": program.points,
                "samples_measured": rows.step, "samples_after_abort": rows.dummies, "index_gaps": rows.gaps,
                "aborted": rows.aborted, "abort_reason": rows.abort_reason, "abort_t_s": rows.abort_t_s,
                "stopped_early": done < len(program.blocks), "time_source": rows.time_source}

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """Tidy table over every block read (module docstring).

        Raises:
            ValueError: If there is no block, more blocks than planned, or no measured sample.
        """
        program = SamplingProgram.model_validate(plan.program)
        if not raw.blocks or len(raw.blocks) > len(program.blocks):
            raise ValueError(f"{self.kind_id} expects 1..{len(program.blocks)} data blocks, got {len(raw.blocks)}")
        rows = _Rows(program)
        table: list[dict[str, object]] = []
        for block, data in zip(program.blocks, raw.blocks, strict=False):
            table += rows.add(block, data)
        if not table:
            raise ValueError("no measured sample: every sample of the first block is dummy data")
        return pd.DataFrame(table)

