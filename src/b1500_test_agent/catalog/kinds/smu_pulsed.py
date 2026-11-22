"""``smu_pulsed``: SMU pulsed measurements, ``MM 3`` pulsed spot, ``MM 4`` pulsed sweep, ``MM 5`` staircase sweep with
pulsed bias, ``MM 27``/``MM 28`` multi-channel pulsed spot/sweep (blueprint v2 2.7, WP7.3).

Roles and mode selection: ``catalog/kinds/pulsed_roles.py`` (pulse roles ``pulse_v`` with base, peak / host list
``values`` / pulsed sweep, compliance and the shared timing; ``sweep_v``/``sweep_i`` staircase roles (MM 5 primary,
MM 28 ``WNX``), ``sync_v``/``sync_i`` (MM 4/5), ``bias_v``/``bias_i`` DC outputs, ``ground`` and ``measure_only`` as
in ``smu_staircase``). Each measuring role measures one quantity (``CMM`` 1 or 2; MM 3/4/5: exactly one measured role,
PG p93 (2-5)); ``irange``/``asu_1pa`` set limited auto ranging (``catalog/kinds/ranging.py``; in pulsed measurements
auto ranging means the compliance range, PG Table 4-3 p337 (4-19)). Current pulses (``PI``/``PWI``) exist in the driver
but have no role function (the plan names ``pulse_v`` only).

Compile (pure): per channel envelope (pulse roles: |V| up to the largest level, |I| = icomp, ``function: pulse_v`` and
the ``PulseEnvelope`` of its trains, ``models.sources.pulse_envelope``; staircase, synchronous and bias roles as in
``smu_staircase``; ground/measure-only 0 V at the sum of what the sourcing roles can drive), the ``SourcePlan`` in
``program["sources"]`` (one ``PulseTrain`` per pulse channel: base, the extreme level, width, period, pulses per
trigger = steps x average, repeated once per host value; R-PULSE-01 checks it against ``SMU_PULSE_SPECS``, e.g. HR/MP
widths 500 us-2 s, R-PULSE-02/03 against the DUT profile and ``policy.pulse``), the estimate (1 s setup; per trigger
hold + steps x average x period + 0.2 s; one checkpoint per trigger) and the exact FLEX preview.

Acquire (one transaction, guarded driver only): ``FMT 1,<mode>`` (MM 4/5: the primary sweep source's value per step;
MM 28: that of source N, the first sweeping one; MM 3/27: data only), ``CN``, ``ERRX?`` drain (interlock or any error
aborts), on hardware the ``LOP?`` positive control, ``DV``/``DI`` of every constant output (``force_bias``), the pulsed
setup (``B1500Driver.pulsed_setup``: ``AIT 2,3``, ``MM``, ``CMM``, ``PT``/``MCPT``/``MCPNT``, sources, ``WM``),
``RI`` of the limited ranges, ``ERRX?`` drain; then per trigger (one, or one per host value: ``pulsed_update``
re-programs the pulse sources first, ``ERRX?`` drain) ``XE`` and one read (timeout ``2 x`` the trigger estimate
``+ 10 s``), ``tx.checkpoint`` with the trigger's rows. Like ``smu_stepped`` the host loop stops after a trigger that
reported compliance, overflow or oscillation (``kind_result``: ``triggers_planned``, ``triggers_done``,
``stopped_early``, ``stop_reason``). The sweep modes run with ``WM 2,1`` (automatic abort; the sources return to base
and start). Cleanup is the transaction's.

Table (``data.csv`` contract): one row per step (per trigger for the spot modes), ``step`` over the whole run,
``segment`` for double sweeps, the returned source column ``<role>_V``/``<role>_I`` (the value the instrument returns
with each step), the programmed per-step values of the other sweeping sources, the pulse level of each pulsed bias
role (``<role>_V``: its ``peak``, or the host value of the trigger), constant bias columns, and ``<role>_<I|V>`` +
``_status`` per measured role. A role that measures what it forces gets no source column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds import pulsed_roles as roles_
from b1500_test_agent.catalog.kinds.pulsed_roles import (
    BIAS_FUNCTIONS,
    PULSE_FUNCTION,
    SWEEP_FUNCTIONS,
    SYNC_FUNCTIONS,
    PulseRole,
    Steps,
    Timing,
)
from b1500_test_agent.catalog.kinds.ranging import RangeSetting, limited_range
from b1500_test_agent.catalog.kinds.smu_staircase import (
    COMP_SETTINGS,
    LEVEL_SETTINGS,
    READ_TIMEOUT_MARGIN_S,
    SETUP_OVERHEAD_S,
    BiasOutput,
    MeasureColumn,
    bias_command,
    drain_or_raise,
    force_bias,
    source_values,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import PulsedSetup, PulseSource, RawBlock, SweepSource
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, PulseTrain, SourcePlan, pulse_envelope
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

Source = Literal["V", "I"]

TRIGGER_OVERHEAD_S = 0.2
"""Allowance per trigger for the source update, the ``ERRX?`` drain and the data transfer in the estimate."""

STOP_STATUSES = frozenset("CTVX")
"""Status letters after which the host loop stops (as ``smu_stepped``)."""


class PulsedProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    data_format: tuple[int, int]
    enable: list[Channel] = Field(min_length=1)
    biases: list[BiasOutput] = Field(default_factory=list)
    setup: PulsedSetup
    pulse_roles: list[str]
    """Roles of ``setup.pulses`` (same order)."""
    stair_roles: list[str] = Field(default_factory=list)
    """Roles of ``setup.followers`` (MM 5 staircase, synchronous source, MM 28 ``WNX``; same order)."""
    measure: list[MeasureColumn] = Field(min_length=1)
    host_role: str | None = None
    host_values: list[float] = Field(default_factory=list)
    """A host list of pulse levels of one pulsed bias role (one trigger per value), else empty."""
    source_columns: dict[str, float] = Field(default_factory=dict)
    ranges: list[RangeSetting] = Field(default_factory=list)
    trigger_estimate_s: float = Field(ge=0)
    sources: SourcePlan

    @property
    def triggers(self) -> list[float | None]:
        """The host values (one trigger each), or one trigger."""
        return list(self.host_values) if self.host_values else [None]

    @property
    def width(self) -> int:
        """Elements per step: one per measured channel plus the returned source value."""
        return len(self.measure) + (1 if self.data_format[1] != 0 else 0)

    def setup_for(self, value: float | None) -> PulsedSetup:
        """The setup of the trigger with host value ``value`` (``None``: as compiled)."""
        if value is None or self.host_role is None:
            return self.setup
        index = self.pulse_roles.index(self.host_role)
        pulses = list(self.setup.pulses)
        pulses[index] = pulses[index].with_peak(value)
        return self.setup.model_copy(update={"pulses": tuple(pulses)})

    def dump(self) -> dict[str, Any]:
        """The JSON program (the source plan under ``SOURCE_PLAN_KEY``)."""
        data = self.model_dump(mode="json", exclude={"sources"})
        data[SOURCE_PLAN_KEY] = self.sources.model_dump(mode="json")
        return data

    @classmethod
    def load(cls, program: dict[str, Any]) -> PulsedProgram:
        data = dict(program)
        data["sources"] = data.pop(SOURCE_PLAN_KEY)
        return cls.model_validate(data)


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel


def _envelope(role: str, function: str, source: Source, levels: list[float], comp: float) -> ChannelEnvelope:
    peak = max(abs(v) for v in levels)
    if source == "V":
        return ChannelEnvelope(role=role, max_abs_v=peak, max_abs_i=abs(comp), function=function,  # type: ignore[arg-type]
                               v_start=levels[0], v_stop=levels[-1])
    return ChannelEnvelope(role=role, max_abs_v=abs(comp), max_abs_i=peak, function=function)  # type: ignore[arg-type]


def _drive(source: Source, levels: list[float], comp: float) -> float:
    return abs(comp) if source == "V" else max(abs(v) for v in levels)


class SmuPulsedKind:
    """SMU pulsed measurements MM 3/4/5/27/28 (sim and visa code path)."""

    kind_id = "smu_pulsed"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, source plan, estimate, FLEX preview and program (module docstrings)."""
        pulse_names, sweep_names, sync_names = roles_.check_roles(self.kind_id, recipe)
        multi = roles_.is_multi(recipe, pulse_names)
        bound = {name: b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                 and b.channel is not None}
        pulses = {name: roles_.pulse_role(name, recipe.roles[name], params) for name in pulse_names if name in bound}
        hosts = [p.name for p in pulses.values() if p.values is not None]
        if len(hosts) > 1:
            raise CompileError(f"{self.kind_id}: at most one pulse role gives a host list (values), got {hosts}")
        sweeping_pulses = [n for n in pulse_names if n in pulses and pulses[n].sweeping]
        stairs = [n for n in sweep_names if n in bound]
        mode = self._mode(multi, sweeping_pulses, stairs, sync_names)
        primary_pulse = next((n for n in pulse_names if n in pulses), None)
        channels: dict[int, ChannelEnvelope] = {}
        if primary_pulse is None:  # no pulse role bound: R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=CompiledEnvelope(channels={}), estimate=Estimate(points=0, duration_s=0))
        timing = roles_.timing(primary_pulse, recipe.roles, list(pulses), params)
        sweeping = [n for n in recipe.roles if n in sweeping_pulses or n in stairs]
        step_info = roles_.steps(sweeping[0], recipe.roles, sweeping, params) if sweeping else roles_.Steps()
        if mode in (4, 5) and step_info.scale != "linear":
            raise CompileError(f"mode {mode} sweeps linearly only (PG error 226, p579 (5-7)); log sweeps need a "
                               "multi-channel pulsed sweep")
        followers: list[tuple[str, SweepSource]] = []
        for name in [*stairs, *(n for n in sync_names if n in bound)]:
            role = recipe.roles[name]
            source = SWEEP_FUNCTIONS.get(role.function) or SYNC_FUNCTIONS[role.function]
            comp_name = COMP_SETTINGS[source]
            start = roles_.number(setting_value(role, "start", params), f"{name}.start")
            stop = roles_.number(setting_value(role, "stop", params), f"{name}.stop")
            comp = roles_.number(setting_value(role, comp_name, params), f"{name}.{comp_name}")
            try:
                followers.append((name, SweepSource(channel=bound[name], source=source, start=start, stop=stop,
                                                    comp=comp)))
            except ValueError as exc:
                raise CompileError(f"{name}: {exc}") from None
        if sync_names and (mode not in (4, 5)):
            raise CompileError(f"{self.kind_id}: a synchronous role belongs to mode 4 or mode 5, not mode {mode}")
        sourcing = 0.0
        pulse_sources: list[PulseSource] = []
        for name in pulse_names:
            if name not in pulses:
                continue
            role = pulses[name]
            peak = role.values[0] if role.values is not None else role.peak
            try:
                pulse_sources.append(PulseSource(channel=bound[name], base=role.base, peak=peak, start=role.start,
                                                 stop=role.stop, comp=role.icomp, width=timing.width))
            except ValueError as exc:
                raise CompileError(f"{name}: {exc}") from None
            sourcing += abs(role.icomp)
        for name, follower in followers:
            channels[follower.channel] = _envelope(name, recipe.roles[name].function, follower.source,
                                                   [follower.start, follower.stop], follower.comp)
            sourcing += _drive(follower.source, [follower.start, follower.stop], follower.comp)
        biases: list[BiasOutput] = []
        grounds: list[tuple[str, int]] = []
        for name, role in recipe.roles.items():
            if name not in bound or role.function in (PULSE_FUNCTION, *SWEEP_FUNCTIONS, *SYNC_FUNCTIONS):
                continue
            if role.function in BIAS_FUNCTIONS:
                source = BIAS_FUNCTIONS[role.function]
                level = roles_.number(setting_value(role, LEVEL_SETTINGS[source], params),
                                      f"{name}.{LEVEL_SETTINGS[source]}")
                comp = roles_.number(setting_value(role, COMP_SETTINGS[source], params),
                                     f"{name}.{COMP_SETTINGS[source]}")
                biases.append(BiasOutput(role=name, channel=bound[name], source=source, level=level, comp=comp))
                channels[bound[name]] = _envelope(name, role.function, source, [level], comp)
                sourcing += _drive(source, [level], comp)
            else:
                grounds.append((name, bound[name]))
        for name, channel in grounds:
            explicit = setting_value(recipe.roles[name], "icomp", params)
            icomp = roles_.number(explicit, f"{name}.icomp") if explicit is not None else sourcing
            channels[channel] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(icomp),
                                                function=recipe.roles[name].function, v_start=0.0, v_stop=0.0)
            if icomp != 0:
                biases.append(BiasOutput(role=name, channel=channel, level=0.0, comp=icomp))
        measure = self._measure(recipe, bound, mode)
        stair = [f for n, f in followers if n in stairs]
        sync = [f for n, f in followers if n in sync_names]
        try:
            setup = PulsedSetup(
                mode=mode, measure=tuple(m.channel for m in measure),
                operation={m.channel: (1 if m.quantity == "I" else 2) for m in measure},
                hold=timing.hold, period=timing.period, meas_time=timing.meas_time, pulses=tuple(pulse_sources),
                staircase=stair[0] if mode == 5 else None, sync=sync[0] if sync else None,
                wnx=tuple(stair) if mode == 28 else (), points=step_info.points if mode in (4, 5, 28) else 1,
                sweep=step_info.scale if mode in (4, 5, 28) else "linear",
                double=step_info.double if mode in (4, 5, 28) else False,
                average=timing.average if mode in (27, 28) else 1, auto_abort=True, post="start")
        except ValueError as exc:
            raise CompileError(f"invalid pulsed measurement: {exc}") from None
        if timing.average != 1 and mode not in (27, 28):
            raise CompileError(f"{primary_pulse}.average: averaging over pulses (MCPT) belongs to mode 27/28")
        host = hosts[0] if hosts else None
        host_values = list(pulses[host].values or []) if host else []
        triggers = max(1, len(host_values))
        trains: dict[int, list[PulseTrain]] = {}
        for name, source in zip([n for n in pulse_names if n in pulses], pulse_sources, strict=True):
            levels = pulses[name].levels()
            extreme = max(levels[1:], key=abs)
            trains[source.channel] = [PulseTrain(base_v=source.base, peak_v=extreme, width_s=timing.width,
                                                 period_s=timing.period, count=setup.pulses_per_trigger,
                                                 repeat=triggers)]
            envelope = _envelope(name, PULSE_FUNCTION, "V", levels, source.comp)
            channels[source.channel] = envelope.model_copy(
                update={"pulse": pulse_envelope(trains[source.channel], source_ohm=None)})
        envelope = CompiledEnvelope(channels=channels)
        enable = [bound[name] for name in recipe.roles if name in bound]
        measured = {f"{m.role}_{m.quantity}" for m in measure}
        trigger_s = timing.hold + setup.steps * timing.average * timing.period + TRIGGER_OVERHEAD_S
        program = PulsedProgram(
            data_format=(1, setup.format_mode), enable=enable, biases=biases, setup=setup,
            pulse_roles=[n for n in pulse_names if n in pulses], stair_roles=[n for n, _ in followers],
            measure=measure, host_role=host, host_values=host_values,
            source_columns={b.column: b.level for b in biases
                            if recipe.roles[b.role].function in BIAS_FUNCTIONS and b.column not in measured},
            ranges=self._ranges(recipe, params, binding, measure), trigger_estimate_s=round(trigger_s, 6),
            sources=SourcePlan(pulses=trains))
        estimate = Estimate(points=triggers * setup.steps, duration_s=round(SETUP_OVERHEAD_S + triggers * trigger_s, 6),
                            max_segment_s=round(trigger_s, 6))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self.preview(program),
                                program=program.dump())

    @staticmethod
    def _mode(multi: bool, sweeping_pulses: list[str], stairs: list[str], syncs: list[str]) -> int:
        if multi:
            return 28 if sweeping_pulses or stairs else 27
        if len(stairs) > 1:
            raise CompileError("a single-channel pulsed measurement has at most one staircase role (MM 5); more "
                               "need a multi-channel pulsed sweep (two pulse or measuring roles)")
        if sweeping_pulses and stairs:
            raise CompileError("a pulsed sweep (MM 4) has no staircase role; a staircase with pulsed bias (MM 5) "
                               "needs a pulse role with a peak")
        if sweeping_pulses:
            return 4
        return 5 if stairs else 3

    def _measure(self, recipe: Recipe, bound: dict[str, int], mode: int) -> list[MeasureColumn]:
        measure: list[MeasureColumn] = []
        for name, role in recipe.roles.items():
            if not role.measure or name not in bound:
                continue
            if len(role.measure) > 1:
                raise CompileError(f"role {name} measures {role.measure}; {self.kind_id} measures one quantity per "
                                   "channel")
            measure.append(MeasureColumn(channel=bound[name], role=name, quantity=role.measure[0]))
        if not measure:
            raise CompileError(f"recipe {recipe.id}: no bound role measures anything")
        if mode in (3, 4, 5) and len(measure) != 1:
            raise CompileError(f"mode {mode} measures exactly one channel (PG p93 (2-5)); {len(measure)} roles measure")
        return measure

    @staticmethod
    def _ranges(recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                measure: list[MeasureColumn]) -> list[RangeSetting]:
        measures_i = {m.role for m in measure if m.quantity == "I"}
        found: list[RangeSetting] = []
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue
            ranged = limited_range(name, role, params, bound)
            if ranged is None:
                continue
            if name not in measures_i:
                raise CompileError(f"role {name} sets a current measurement range but does not measure I")
            found.append(ranged)
        return found

    @staticmethod
    def preview(program: PulsedProgram) -> list[str]:
        """The writes ``acquire`` sends, in order (``ERRX?`` drains and queries are not listed)."""
        lines = [flex.fmt(*program.data_format), flex.cn(program.enable)]
        lines += [bias_command(b) for b in program.biases]
        lines += program.setup.commands()
        lines += [flex.ri(r.channel, r.code) for r in program.ranges]
        for index, value in enumerate(program.triggers):
            if index > 0:
                lines += program.setup_for(value).source_commands()
            lines.append(flex.XE)
        return lines

    @staticmethod
    def checkpoint_total(plan: PlanRecord) -> int:
        """Checkpoints ``acquire`` reports: one per trigger."""
        return len(PulsedProgram.load(plan.program).triggers) if plan.program else 0

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = PulsedProgram.load(plan.program)
        driver = tx.driver
        driver.set_format(*program.data_format)
        driver.enable(program.enable)
        drain_or_raise(tx, "enabling the outputs")
        tx.mark("outputs enabled")
        tx.lop_positive_control(program.enable)
        for bias in program.biases:
            force_bias(tx, bias)
        driver.pulsed_setup(program.setup)
        for ranged in program.ranges:
            driver.set_range(ranged.channel, "I", ranged.code)
        drain_or_raise(tx, "the pulsed setup")
        tx.mark("configured")
        timeout = 2.0 * program.trigger_estimate_s + READ_TIMEOUT_MARGIN_S
        expected = program.setup.steps * program.width
        blocks: list[RawBlock] = []
        triggers = program.triggers
        stop_reason = ""
        for index, value in enumerate(triggers):
            if index > 0:
                driver.pulsed_update(program.setup_for(value))
                drain_or_raise(tx, f"setting pulse level {index}")
            if value is not None:
                tx.mark(f"trigger {index}: {program.host_role} pulse {value:g} V")
            block = driver.execute_and_read(expected_points=expected, timeout_s=timeout)
            blocks.append(block)
            tx.checkpoint(index + 1, len(triggers), "pulse",
                          rows=lambda i=index, v=value, b=block: trigger_rows(program, i, v, b))
            flagged = sorted({str(p.status.value) for p in block.points if str(p.status.value) in STOP_STATUSES})
            if flagged and index < len(triggers) - 1:
                stop_reason = (f"trigger {index} reported status {','.join(flagged)}; the remaining "
                               f"{len(triggers) - 1 - index} trigger(s) were not run")
                tx.mark("stopped: " + stop_reason)
                break
        tx.mark("data read")
        result: dict[str, Any] = {"triggers_planned": len(triggers), "triggers_done": len(blocks),
                                  "stopped_early": bool(stop_reason), "stop_reason": stop_reason,
                                  "measurement_mode": program.setup.mode}
        return RawAcquisition(blocks=blocks, kind_result=result)

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """Tidy table over every trigger (module docstring).

        Raises:
            ValueError: If there is no block, more blocks than triggers, or a block does not hold the programmed
                elements.
        """
        program = PulsedProgram.load(plan.program)
        triggers = program.triggers
        if not raw.blocks or len(raw.blocks) > len(triggers):
            raise ValueError(f"{self.kind_id} expects 1..{len(triggers)} data blocks, got {len(raw.blocks)}")
        rows: list[dict[str, object]] = []
        for index, (block, value) in enumerate(zip(raw.blocks, triggers, strict=False)):
            rows += trigger_rows(program, index, value, block)
        return pd.DataFrame(rows)


def _step_values(program: PulsedProgram) -> dict[str, list[float]]:
    """Programmed per-step values of every sweeping source, by source column."""
    setup = program.setup
    out: dict[str, list[float]] = {}
    for role, pulse in zip(program.pulse_roles, setup.pulses, strict=True):
        if pulse.sweeping:
            assert pulse.start is not None and pulse.stop is not None
            out[f"{role}_{pulse.source}"] = source_values(pulse.start, pulse.stop, setup.points, setup.sweep,
                                                          setup.double)
    for role, follower in zip(program.stair_roles, setup.followers, strict=True):
        out[f"{role}_{follower.source}"] = source_values(follower.start, follower.stop, setup.points, setup.sweep,
                                                         setup.double)
    return out


def trigger_rows(program: PulsedProgram, index: int, value: float | None, block: RawBlock) -> list[dict[str, object]]:
    """Table rows of trigger ``index`` (host value ``value``), ``step`` continuing over the run (also the
    ``partial.csv`` rows).

    Raises:
        ValueError: If the block does not hold ``steps x width`` elements in the programmed order.
    """
    setup = program.setup_for(value)
    steps = setup.steps
    if len(block.points) != steps * program.width:
        raise ValueError(f"expected {steps * program.width} elements ({steps} steps x {program.width}), got "
                         f"{len(block.points)}")
    measured = {f"{m.role}_{m.quantity}" for m in program.measure}
    returned_channel = setup.returned_source
    roles_by_channel = {_norm(p.channel): (r, p.source) for r, p in zip(program.pulse_roles, setup.pulses,
                                                                         strict=True)}
    roles_by_channel |= {_norm(f.channel): (r, f.source) for r, f in zip(program.stair_roles, setup.followers,
                                                                         strict=True)}
    returned = None
    if returned_channel is not None and program.data_format[1] != 0:
        role, source = roles_by_channel[_norm(returned_channel)]
        returned = f"{role}_{source}"
    per_step = {c: v for c, v in _step_values(program).items() if c not in measured and c != returned}
    levels = {f"{r}_{p.source}": float(p.peak) for r, p in zip(program.pulse_roles, setup.pulses, strict=True)
              if not p.sweeping and p.peak is not None and f"{r}_{p.source}" not in measured}
    constants = {c: v for c, v in program.source_columns.items() if c not in measured}
    rows: list[dict[str, object]] = []
    for position, elements in enumerate(block.steps(program.width)):
        row: dict[str, object] = {"step": index * steps + position}
        if setup.double:
            row["segment"] = "fwd" if position < setup.points else "rev"
        if returned is not None:
            source = elements[-1]
            if not source.is_source:
                raise ValueError(f"step {position}: the last element is not the source value")
            if returned not in measured:
                row[returned] = source.value
        for column, values in per_step.items():
            row[column] = values[position]
        row.update(levels)
        for column, element in zip(program.measure, elements, strict=False):
            if element.is_source or element.channel_number is None \
                    or _norm(element.channel_number) != _norm(column.channel) \
                    or element.data_type != column.quantity:
                raise ValueError(f"step {position}: element {element.raw!r} is not {column.quantity} of channel "
                                 f"{column.channel}")
            name = f"{column.role}_{column.quantity}"
            row[name] = element.value
            row[f"{name}_status"] = str(element.status.value)
        row.update(constants)
        rows.append(row)
    return rows


__all__ = ["PulseRole", "PulsedProgram", "SmuPulsedKind", "Steps", "Timing", "trigger_rows"]
