"""``smu_spot``: SMU spot measurements (``MM 1``) of every measured role at once, with an optional host list of
levels on one role and an optional range survey (blueprint v2 2.7, WP7.1).

Roles (recipe ``roles``, bound to channels through the pin map; ``$param`` references allowed in every setting):

- ``bias_v``: ``DV`` at setting ``v`` with compliance ``icomp`` (both required);
- ``bias_i``: ``DI`` at setting ``i`` with voltage compliance ``vcomp`` (both required; ``i: 0`` makes the SMU a
  voltmeter, the "sense" side of a four-terminal measurement);
- ``ground``: the GNDU (nothing is sent) or an SMU at 0 V (``DV``) whose compliance is setting ``icomp`` or, when
  absent, the sum of what the sourcing roles can drive (their current compliances and forced currents);
- ``measure_only``: an SMU at 0 V like a grounded SMU, measuring current (``measure: [I]``; for a voltage reading use a
  ``bias_i`` role at ``i: 0``).

Host list: at most one ``bias_v``/``bias_i`` role gives setting ``values`` (a ``float_list``) instead of ``v``/``i``;
the kind then repeats the measurement at each level in the given order (levels need not be distinct, so a current
reversal ``[-I, +I, -I, +I]`` is fine). Each role measures one quantity (``measure: [I]`` or ``[V]``) with ``CMM`` 1 or
2; the measured channels form the ``MM 1`` list in recipe order. Ranging (``catalog/kinds/ranging.py``): ``irange`` or
``asu_1pa`` = limited auto ranging from that range (``RI ch,+code``, rule R-ASU-01 for the ASU ranges); ``ranges``
(a list) = a range survey, one group of measurements per entry on a fixed range (``RI ch,-code``; the zero check).
Recipe parameters read by name: ``integration`` (``short``|``medium``|``long`` ADC preset, as ``smu_staircase``) and
``samples`` (spot measurements per level and range group, default 1).

Compile (pure): per channel envelope (``bias_v``: the largest |v| and |icomp|; ``bias_i``: the largest |i| as the
current and |vcomp| as the voltage; ground/measure-only: 0 V and the compliance), estimate (rows = levels x range
groups x samples; per row one ``XE`` of every measured channel plus 10 ms, 50 ms per level or range change, 1 s
setup), checkpoint segments of at most about ``SEGMENT_TARGET_S`` (``Estimate.max_segment_s``), the exact FLEX
preview and the program.

Acquire (one transaction, guarded driver only): ``FMT 1,0`` (one element per measured channel), ``AAD``/``AIT``,
``CN``, ``ERRX?`` drain (interlock or any error aborts), on hardware the ``LOP?`` positive control (WP6.2), ``DV``/
``DI`` of every constant output (``BiasOutput``/``force_bias`` of ``smu_staircase``: one DC source path for both
kinds), ``MM 1``/``CMM``, ``RI`` of the limited ranges, ``ERRX?`` drain; then per level:
``DV``/``DI`` of the list role, per range group the survey's ``RI``, ``ERRX?`` drain (a range the SMU lacks, e.g. 1 pA
without an ASU, is an instrument error and aborts before ``XE``), and per sample ``XE`` + one read (timeout ``2 x``
the row estimate ``+ 10 s``) followed by ``tx.check_abort()``. After each chunk of samples ``tx.checkpoint`` hands
over its rows (asynchronous runs record them; ``safe_shutdown`` cancels there). Like ``smu_stepped`` the host loop
stops after a point that reported any of ``STOP_STATUSES`` (compliance, overflow, oscillation: the next levels
usually drive harder), recorded in ``kind_result`` (``points_planned``, ``points_done``, ``stopped_early``,
``stop_reason``). Cleanup is the transaction's (``AB`` -> ``DZ`` -> ``CL`` -> verify).

Table (``data.csv`` contract, ``analysis/dataset.py``): one row per spot measurement in acquisition order: ``step``,
``<role>_range`` (label of the range used, for every ranged role: ``10pA`` fixed, ``1pA+`` limited auto), the list
role's level ``<role>_V``/``<role>_I`` (unless the role measures that quantity), constant source columns of the other
``bias_v``/``bias_i`` roles, and ``<role>_<I|V>`` + ``_status`` per measured role.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.ranging import RangeSetting, limited_range, survey_ranges
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
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, RawBlock
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING, VOLTAGE_COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

SPOT_FUNCTIONS = frozenset({"bias_v", "bias_i", "ground", "measure_only"})
"""Role functions this kind executes."""

LIST_SETTING = "values"
"""Role setting of the host list (``float_list``) of a ``bias_v``/``bias_i`` role."""

SAMPLES_PARAM = "samples"
"""Recipe parameter: spot measurements per level and range group (int >= 1, default 1)."""

DATA_FORMAT = (1, 0)
"""``FMT 1,0``: ASCII with header, measurement data only (PG PDF 436-438); a spot point has no sweep source value."""

XE_OVERHEAD_S = 0.01
"""Allowance per spot measurement for the trigger and the data transfer in the duration estimate."""

LEVEL_OVERHEAD_S = 0.05
"""Allowance per level or range change (``DV``/``DI``/``RI`` and the ``ERRX?`` drain) in the estimate."""

SEGMENT_TARGET_S = 10.0
"""Longest stretch of samples between two checkpoints (cancel latency; R-RUN-02 allows ``segment_max_s``)."""

MAX_LIST_VALUES = 1001
"""Most levels of one host list (R-RUN-01 bounds the points and the duration on top of this)."""

MAX_SAMPLES = 10001
"""Most samples per level and range group."""

STOP_STATUSES = frozenset("CTVX")
"""Status letters after which the host loop stops: compliance (``C``, other channel ``T``), overflow or invalid data
(``V``) and oscillation (``X``)."""

_SOURCE_FUNCTIONS = {"bias_v": ("V", "v", COMPLIANCE_SETTING), "bias_i": ("I", "i", VOLTAGE_COMPLIANCE_SETTING)}


class SpotList(StrictModel):
    """The host list: the role whose level steps through ``values`` (V or A) with compliance ``comp``."""

    role: str
    channel: Channel
    source: Literal["V", "I"]
    values: list[float] = Field(min_length=1, max_length=MAX_LIST_VALUES)
    comp: float

    def at(self, level: float) -> BiasOutput:
        """The list role held at one of its levels (forced like any constant output: ``force_bias``)."""
        return BiasOutput(role=self.role, channel=self.channel, source=self.source, level=level, comp=self.comp)


class SpotProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    data_format: tuple[int, int] = DATA_FORMAT
    integration: Integration
    enable: list[Channel] = Field(min_length=1)
    outputs: list[BiasOutput] = Field(default_factory=list)
    """Constant ``DV``/``DI`` outputs (bias, grounded and measure-only SMUs), the staircase kind's model."""
    level_list: SpotList | None = None
    measure: list[MeasureColumn] = Field(min_length=1)
    ranges: list[RangeSetting] = Field(default_factory=list)
    """Limited auto ranging (``irange``/``asu_1pa``), sent once in the setup."""
    groups: list[list[RangeSetting]] = Field(default_factory=list)
    """Range survey: per group the fixed ``RI`` of every surveyed role (empty: no survey)."""
    samples: int = Field(ge=1, le=MAX_SAMPLES)
    chunk: int = Field(ge=1)
    """Samples between two checkpoints."""
    source_columns: dict[str, float] = Field(default_factory=dict)
    row_estimate_s: float = Field(ge=0)
    """Estimated duration of one spot measurement (all measured channels + the transfer allowance)."""

    @property
    def levels(self) -> list[float | None]:
        return list(self.level_list.values) if self.level_list is not None else [None]

    @property
    def group_count(self) -> int:
        return max(1, len(self.groups))

    @property
    def rows(self) -> int:
        """Planned spot measurements (rows of the table)."""
        return len(self.levels) * self.group_count * self.samples

    @property
    def chunks_per_group(self) -> int:
        return math.ceil(self.samples / self.chunk)

    @property
    def checkpoints(self) -> int:
        return len(self.levels) * self.group_count * self.chunks_per_group

    def points(self) -> list[tuple[int, int]]:
        """``(level index, group index)`` of every planned row, in acquisition order."""
        return [(li, gi) for li in range(len(self.levels)) for gi in range(self.group_count)
                for _ in range(self.samples)]

    @property
    def list_column(self) -> str | None:
        """The table column of the list level (``None`` without a list or when the role measures that quantity)."""
        spot = self.level_list
        if spot is None or any(m.role == spot.role and m.quantity == spot.source for m in self.measure):
            return None
        return f"{spot.role}_{spot.source}"


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _levels(name: str, role: RoleSpec, params: dict[str, Quantity], key: str) -> list[float] | None:
    """The role's host list (``values``) or ``None``; ``values`` and the single level are exclusive."""
    if LIST_SETTING not in role.settings:
        return None
    if key in role.settings:
        raise CompileError(f"{name}: give either {key} or {LIST_SETTING}, not both")
    listed = setting_value(role, LIST_SETTING, params)
    if not isinstance(listed, list) or not listed:
        raise CompileError(f"{name}.{LIST_SETTING} must be a non-empty list, got {listed!r}")
    if len(listed) > MAX_LIST_VALUES:
        raise CompileError(f"{name}: {len(listed)} levels exceed {MAX_LIST_VALUES}")
    return [_number(v, f"{name}.{LIST_SETTING}[{i}]") + 0.0 for i, v in enumerate(listed)]


class SmuSpotKind:
    """``MM 1`` spot measurements with constant outputs, an optional host list and an optional range survey (sim
    and visa code path; see the module docstring)."""

    kind_id = "smu_spot"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program; see the module docstring for the role semantics."""
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in SPOT_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(SPOT_FUNCTIONS))}")
        listed = [name for name, role in recipe.roles.items() if LIST_SETTING in role.settings]
        if len(listed) > 1:
            raise CompileError(f"{self.kind_id} steps at most one role through a list of levels; {listed} give "
                               f"{LIST_SETTING}")
        integration = self._integration(params)
        samples = self._samples(params)
        channels: dict[int, ChannelEnvelope] = {}
        outputs: list[BiasOutput] = []
        level_list: SpotList | None = None
        grounds: list[tuple[str, int, RoleSpec]] = []
        drive = 0.0  # what the sourcing roles can push into a grounded terminal (A)
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if role.function in _SOURCE_FUNCTIONS:
                source, key, comp_key = _SOURCE_FUNCTIONS[role.function]
                values = _levels(name, role, params, key)
                levels = values if values is not None else [_number(setting_value(role, key, params), f"{name}.{key}")]
                comp = _number(setting_value(role, comp_key, params), f"{name}.{comp_key}")
                if comp == 0:
                    raise CompileError(f"{name}.{comp_key} must be non-zero")
                drive += abs(comp) if source == "V" else max(abs(v) for v in levels)
                if bound is None or bound.channel is None:
                    continue  # unbound or GNDU: R-PIN-01 decides
                peak = max(abs(v) for v in levels)
                if source == "V":
                    channels[bound.channel] = ChannelEnvelope(role=name, max_abs_v=peak, max_abs_i=abs(comp),
                                                              function=role.function, v_start=levels[0],
                                                              v_stop=levels[-1])
                else:
                    channels[bound.channel] = ChannelEnvelope(role=name, max_abs_v=abs(comp), max_abs_i=peak,
                                                              function=role.function, v_start=None, v_stop=None)
                if values is not None:
                    level_list = SpotList(role=name, channel=bound.channel, source=source, values=values, comp=comp)
                else:
                    outputs.append(BiasOutput(role=name, channel=bound.channel, source=source, level=levels[0],
                                              comp=comp))
            elif bound is not None and bound.channel is not None:  # ground or measure_only on an SMU: 0 V
                grounds.append((name, bound.channel, role))
        for name, channel, role in grounds:
            explicit = setting_value(role, COMPLIANCE_SETTING, params)
            icomp = _number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else drive
            if icomp == 0:
                raise CompileError(f"{name} holds 0 V without a compliance: set {COMPLIANCE_SETTING} (no sourcing role "
                                   "bounds its current)")
            channels[channel] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(icomp), function=role.function,
                                                v_start=0.0, v_stop=0.0)
            outputs.append(BiasOutput(role=name, channel=channel, source="V", level=0.0, comp=icomp))
        envelope = CompiledEnvelope(channels=channels)
        measure = self._measure(recipe, binding)
        if not measure:
            # Nothing measurable is bound: the plan-phase rules block it (R-PIN-01) unless the recipe measures nothing.
            if any(role.measure for role in recipe.roles.values()):
                return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
            raise CompileError(f"recipe {recipe.id}: no role measures anything")
        ranges, groups = self._ranging(recipe, params, binding, station, measure)
        enable = [b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                  and b.channel is not None]
        row_s = round(len(measure) * measurement_time_s(integration) + XE_OVERHEAD_S, 9)
        chunk = max(1, min(samples, math.floor(SEGMENT_TARGET_S / row_s) if row_s > 0 else samples))
        source_columns = {f"{o.role}_{o.source}": o.level for o in outputs if recipe.roles[o.role].function
                          in _SOURCE_FUNCTIONS and not any(m.role == o.role and m.quantity == o.source
                                                           for m in measure)}
        program = SpotProgram(integration=integration, enable=enable, outputs=outputs, level_list=level_list,
                              measure=measure, ranges=ranges, groups=groups, samples=samples, chunk=chunk,
                              source_columns=source_columns, row_estimate_s=row_s)
        return CompiledKindPlan(envelope=envelope, estimate=self._estimate(program),
                                flex_preview=self.preview(program), program=program.model_dump(mode="json"))

    @staticmethod
    def _integration(params: dict[str, Quantity]) -> Integration:
        preset = params.get(INTEGRATION_PARAM)
        name = DEFAULT_PRESET if preset is None else preset.value
        if not isinstance(name, str) or name not in INTEGRATION_PRESETS:
            raise CompileError(f"{INTEGRATION_PARAM} must be one of {sorted(INTEGRATION_PRESETS)}, got {name!r}")
        return INTEGRATION_PRESETS[name]

    @staticmethod
    def _samples(params: dict[str, Quantity]) -> int:
        quantity = params.get(SAMPLES_PARAM)
        value = 1 if quantity is None else quantity.value
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_SAMPLES:
            raise CompileError(f"{SAMPLES_PARAM} must be an integer 1 to {MAX_SAMPLES}, got {value!r}")
        return value

    def _measure(self, recipe: Recipe, binding: ChannelBinding) -> list[MeasureColumn]:
        measure: list[MeasureColumn] = []
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if not role.measure:
                continue
            if len(role.measure) > 1:
                raise CompileError(f"role {name} measures {role.measure}; {self.kind_id} measures one quantity per "
                                   "channel")
            quantity = role.measure[0]
            if role.function in ("measure_only", "ground") and quantity != "I":
                raise CompileError(f"role {name} ({role.function}) holds 0 V and measures I only; measure a voltage "
                                   "with a bias_i role at i: 0 (a voltmeter)")
            if bound is None or bound.channel is None:
                continue
            measure.append(MeasureColumn(channel=bound.channel, role=name, quantity=quantity))
        return measure

    @staticmethod
    def _ranging(recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding, station: StationProfile,
                 measure: list[MeasureColumn]) -> tuple[list[RangeSetting], list[list[RangeSetting]]]:
        measures_i = {m.role for m in measure if m.quantity == "I"}
        ranges: list[RangeSetting] = []
        surveys: list[list[RangeSetting]] = []
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue
            limited = limited_range(name, role, params, bound)
            survey = survey_ranges(name, role, params, bound, station)
            if limited is None and survey is None:
                continue
            if name not in measures_i:
                raise CompileError(f"role {name} sets a current measurement range but does not measure I")
            if limited is not None and survey is not None:
                raise CompileError(f"role {name}: give either a range (irange/asu_1pa) or a range survey (ranges)")
            if limited is not None:
                ranges.append(limited)
            elif survey is not None:
                surveys.append(survey)
        if len({len(s) for s in surveys}) > 1:
            raise CompileError("every surveyed role must list the same number of ranges")
        groups = [list(group) for group in zip(*surveys, strict=True)] if surveys else []
        return ranges, groups

    @staticmethod
    def _estimate(program: SpotProgram) -> Estimate:
        levels = len(program.levels)
        changes = levels + (levels * len(program.groups))
        duration = SETUP_OVERHEAD_S + changes * LEVEL_OVERHEAD_S + program.rows * program.row_estimate_s
        segment = program.chunk * program.row_estimate_s + 2 * LEVEL_OVERHEAD_S
        return Estimate(points=program.rows, duration_s=round(duration, 6), max_segment_s=round(segment, 6))

    @staticmethod
    def preview(program: SpotProgram) -> list[str]:
        """The writes ``acquire`` sends, in order (``ERRX?`` drains and the ``LOP?`` control are not listed)."""
        integration = program.integration
        adc = ADC_TYPE_CODES[integration.adc]
        lines = [flex.fmt(*program.data_format)]
        lines += [flex.aad(m.channel, adc) for m in program.measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n))
        lines.append(flex.cn(program.enable))
        lines += [bias_command(o) for o in program.outputs]
        lines.append(flex.mm(1, [m.channel for m in program.measure]))
        lines += [flex.cmm(m.channel, 1 if m.quantity == "I" else 2) for m in program.measure]
        lines += [flex.ri(r.channel, r.code) for r in program.ranges]
        for level in program.levels:
            if program.level_list is not None and level is not None:
                lines.append(bias_command(program.level_list.at(level)))
            for group in program.groups or [[]]:
                lines += [flex.ri(r.channel, r.code) for r in group]
                lines += [flex.XE] * program.samples
        return lines

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints ``acquire`` reports: one per chunk of samples (fewer when the loop stops early)."""
        return SpotProgram.model_validate(plan.program).checkpoints if plan.program else 0

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (see the module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = SpotProgram.model_validate(plan.program)
        driver = tx.driver
        measured = [m.channel for m in program.measure]
        driver.set_format(*program.data_format)
        driver.apply_integration(program.integration, measured)
        driver.enable(program.enable)
        drain_or_raise(tx, "enabling the outputs")
        tx.mark("outputs enabled")
        tx.lop_positive_control(program.enable)
        for output in program.outputs:
            force_bias(tx, output)
        driver.spot_setup(measured, {m.channel: 1 if m.quantity == "I" else 2 for m in program.measure})
        for ranged in program.ranges:
            driver.set_range(ranged.channel, "I", ranged.code)
        drain_or_raise(tx, "the spot setup")
        tx.mark("configured")
        timeout = 2.0 * program.row_estimate_s + READ_TIMEOUT_MARGIN_S
        blocks: list[RawBlock] = []
        total, done = program.checkpoints, 0
        stop_reason = ""
        for li, level in enumerate(program.levels):
            if program.level_list is not None and level is not None:
                force_bias(tx, program.level_list.at(level))
                drain_or_raise(tx, f"setting {program.level_list.role} to level {li}")
                tx.mark(f"level {li}: {program.level_list.role} = {level:g} {program.level_list.source}")
            for gi, group in enumerate(program.groups or [[]]):
                for ranged in group:
                    driver.set_range(ranged.channel, "I", ranged.code)
                if group:
                    drain_or_raise(tx, f"range group {gi}")
                    tx.mark(f"range group {gi}: " + ", ".join(f"{r.role} {r.label}" for r in group))
                taken = 0
                while taken < program.samples and not stop_reason:
                    count = min(program.chunk, program.samples - taken)
                    first = len(blocks)
                    for _ in range(count):
                        block = driver.execute_and_read(expected_points=len(program.measure), timeout_s=timeout)
                        blocks.append(block)
                        tx.check_abort()
                        flagged = sorted({str(p.status.value) for p in block.points
                                          if str(p.status.value) in STOP_STATUSES})
                        if flagged:
                            stop_reason = (f"point {len(blocks) - 1} (level {li}, range group {gi}) reported status "
                                           f"{','.join(flagged)}; the remaining "
                                           f"{program.rows - len(blocks)} point(s) were not measured")
                            break
                    taken += count
                    done += 1
                    tx.checkpoint(done, total, "spot",
                                  rows=lambda a=first, b=blocks[first:]: self.rows_of(program, b, first_index=a))
                if stop_reason:
                    break
            if stop_reason:
                tx.mark("stopped: " + stop_reason)
                break
        tx.mark("data read")
        result: dict[str, Any] = {"points_planned": program.rows, "points_done": len(blocks),
                                  "stopped_early": bool(stop_reason), "stop_reason": stop_reason}
        return RawAcquisition(blocks=blocks, kind_result=result)

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """Tidy table over every acquired spot measurement (see the module docstring for the columns).

        Raises:
            ValueError: If there is no block, more blocks than planned rows, or a block does not hold one element per
                measured channel in the programmed order.
        """
        program = SpotProgram.model_validate(plan.program)
        if not raw.blocks or len(raw.blocks) > program.rows:
            raise ValueError(f"{self.kind_id} expects 1..{program.rows} data blocks, got {len(raw.blocks)}")
        return pd.DataFrame(self.rows_of(program, raw.blocks))

    @staticmethod
    def rows_of(program: SpotProgram, blocks: list[RawBlock], *, first_index: int = 0) -> list[dict[str, object]]:
        """Table rows of consecutive blocks starting at planned row ``first_index`` (also the ``partial.csv`` rows).

        Raises:
            ValueError: If a block does not hold one element per measured channel in the programmed order.
        """
        points = program.points()
        levels = program.levels
        rows: list[dict[str, object]] = []
        for offset, block in enumerate(blocks):
            index = first_index + offset
            li, gi = points[index]
            if len(block.points) != len(program.measure):
                raise ValueError(f"point {index}: expected {len(program.measure)} elements, got {len(block.points)}")
            row: dict[str, object] = {"step": index}
            for ranged in [*program.ranges, *(program.groups[gi] if program.groups else [])]:
                row[f"{ranged.role}_range"] = ranged.label
            if program.list_column is not None:
                row[program.list_column] = levels[li]
            row.update(program.source_columns)
            for column, element in zip(program.measure, block.points, strict=True):
                number = element.channel_number
                if element.is_source or number is None or _norm(number) != _norm(column.channel) \
                        or element.data_type != column.quantity:
                    raise ValueError(f"point {index}: element {element.raw!r} is not {column.quantity} of channel "
                                     f"{column.channel}")
                name = f"{column.role}_{column.quantity}"
                row[name] = element.value
                row[f"{name}_status"] = str(element.status.value)
            rows.append(row)
        return rows


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel
