"""``smu_staircase``: one SMU staircase voltage sweep with constant bias and ground roles (blueprint 2.6, M1).

Roles (recipe ``roles``, bound to channels through the pin map):

- exactly one ``sweep_v`` role on an SMU: settings ``start``, ``stop``, ``points``, ``icomp`` (all required), optional
  ``mode`` (``single``|``double``: start→stop or start→stop→start, 2·points steps), ``scale`` (``linear``|``log``),
  ``hold``/``delay`` (s, ``WT``);
- ``bias_v`` roles: ``DV`` at settings ``v`` with compliance ``icomp``;
- ``ground`` roles: the GNDU (nothing is sent) or an SMU forced to 0 V (``DV``) whose compliance is setting
  ``icomp`` or, when absent, the sum of the compliances of the sourcing roles (the ground terminal returns at most
  their currents);
- ``measure_only`` roles: an SMU at 0 V like a grounded SMU, measured;
- ``step_v`` roles need kind ``smu_stepped`` and are refused, as is every other role function (current forcing,
  synchronous, pulse, SPGU, WGFMU and MFCMU roles belong to their own kinds).

Each role's ``measure`` (``[I]`` or ``[V]``; both at once is not supported in v1) puts its channel into the ``MM 2``
list (sweep role first, then recipe order) with ``CMM`` 1 (current) or 2 (voltage). The recipe parameter
``integration`` (``short``|``medium``|``long``, default ``medium``) selects the ADC preset for every measured
channel. The sweep always uses ``WM 2,1``: automatic abort on compliance, overflow or oscillation (later steps then
read ``199.999E+99`` with status ``V``) and a return to the start value.

Acquisition (through the transaction's guarded driver, nothing else): ``FMT 1,1`` (each step also returns the
sweep source value), ``AAD``/``AIT``, ``CN``, ``ERRX?`` drain (an interlock error 202/203 or any other error aborts:
ATV-10 fallback), on hardware the ``LOP?`` positive control (v2 WP6.2), ``DV`` per bias/ground SMU,
``MM``/``CMM``/``WV``/``WT``/``WM``, ``ERRX?`` drain (any error aborts), ``XE`` and one read of
``steps × (measured channels + 1)`` elements with a timeout of ``2 × estimate + 10 s`` (blueprint 7). The FLEX
preview lists exactly these writes in this order (queries are not listed).

The same code path serves ``sim`` and ``visa``: the kind only talks to the driver. ``configure_staircase`` (setup
up to ``XE``) and ``staircase_rows`` (table rows of one block) are shared with ``smu_stepped``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, ClassVar, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, RawBlock, StaircaseSetup
from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, ErrorCode, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration, SweepTiming
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleSpec
from b1500_test_agent.models.station import InstrumentError, StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING, interlock_errors

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

STAIRCASE_FUNCTIONS = frozenset({"sweep_v", "bias_v", "ground", "measure_only"})
"""Role functions this kind executes."""

INTEGRATION_PARAM = "integration"
"""Recipe parameter that selects the ADC preset (enum ``short``/``medium``/``long``)."""

DEFAULT_PRESET = "medium"

INTEGRATION_PRESETS: dict[str, Integration] = {
    "short": Integration(adc="high_speed", mode="auto", n=1),
    "medium": Integration(adc="high_speed", mode="plc", n=1),
    "long": Integration(adc="high_speed", mode="plc", n=16),
}
"""ADC presets (``AAD``/``AIT``, PG PDF 351, 356-359): high-speed ADC, auto N=1 (fastest, noisiest); 1 power-line
cycle; 16 power-line cycles. The high-speed ADC exists on every SMU type, so presets never depend on the module."""

DATA_FORMAT = (1, 1)
"""``FMT 1,1``: ASCII with header, plus the sweep source value of each step (PG PDF 436-438)."""

ESTIMATE_LINE_HZ = 50.0
"""Line frequency assumed for estimates (50 Hz gives the longer PLC, so the estimate is conservative)."""

ESTIMATE_HS_SAMPLES_PER_PLC = 128
"""High-speed ADC samples per power-line cycle assumed for estimates (same convention as the simulator)."""

ESTIMATE_HR_AUTO_S = 2.5e-3
ESTIMATE_HR_MANUAL_S = 80e-6
SETUP_OVERHEAD_S = 1.0
"""Fixed allowance for setup commands and the data transfer in the duration estimate."""

READ_TIMEOUT_MARGIN_S = 10.0


class AcquisitionError(B1500Error):
    """The instrument reported an error during setup (``ERRX?`` not empty before ``XE``); nothing was triggered."""

    code: ClassVar[ErrorCode] = "instrument_error"

    def __init__(self, message: str, errors: list[InstrumentError]) -> None:
        self.errors = list(errors)
        super().__init__(message)


class MeasureColumn(StrictModel):
    """One measured channel: its role and quantity (in ``MM`` order = data order of each step)."""

    channel: Channel
    role: str
    quantity: Literal["I", "V"]


class BiasOutput(StrictModel):
    """A constant DC output held during the sweep (bias, grounded SMU or measure-only SMU)."""

    role: str
    channel: Channel
    v: float
    icomp: float


class StaircaseProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    data_format: tuple[int, int] = DATA_FORMAT
    integration: Integration
    enable: list[Channel] = Field(min_length=1)
    biases: list[BiasOutput] = Field(default_factory=list)
    sweep_role: str
    sweep: StaircaseSetup
    measure: list[MeasureColumn] = Field(min_length=1)
    source_columns: dict[str, float] = Field(default_factory=dict)
    """Constant programmed voltages of bias roles written as source columns (``drain_V``), unless measured."""

    @property
    def width(self) -> int:
        """Elements per step: one per measured channel plus the sweep source value (``FMT x,1``)."""
        return len(self.measure) + (1 if self.data_format[1] == 1 else 0)

    @property
    def steps(self) -> int:
        """Sweep steps (``2 x points`` for a double sweep)."""
        return self.sweep.points * (2 if self.sweep.double else 1)


# -- helpers ---------------------------------------------------------------------------------------------------------


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _choice(value: object, choices: tuple[str, ...], what: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise CompileError(f"{what} must be one of {list(choices)}, got {value!r}")
    return value


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel


def measurement_time_s(integration: Integration) -> float:
    """Estimated time of one measurement with ``integration`` (PG Table 4-21 conventions; estimate only)."""
    plc = 1.0 / ESTIMATE_LINE_HZ
    if integration.mode == "plc":
        return integration.n * plc
    if integration.adc == "high_resolution":
        return integration.n * (ESTIMATE_HR_AUTO_S if integration.mode == "auto" else ESTIMATE_HR_MANUAL_S)
    return integration.n * plc / ESTIMATE_HS_SAMPLES_PER_PLC


def read_timeout_s(estimate: Estimate) -> float:
    """Timeout of the measurement read: ``2 x estimate + 10 s`` (blueprint 7)."""
    return 2.0 * estimate.duration_s + READ_TIMEOUT_MARGIN_S


def drain_or_raise(tx: Transaction, stage: str) -> None:
    """Drain ``ERRX?``; an interlock error (202/203) or any other error aborts before anything is triggered."""
    errors = tx.driver.errors(drain=True)
    if not errors:
        return
    listed = ", ".join(f"{e.code} {e.message}".strip() for e in errors)
    if interlock_errors(errors):
        raise AcquisitionError(f"interlock refused the setup after {stage} ({listed}); aborted", errors)
    raise AcquisitionError(f"instrument reported errors after {stage} ({listed}); aborted before XE", errors)


def configure_staircase(tx: Transaction, program: StaircaseProgram) -> None:
    """Everything before ``XE`` through the guarded driver: ``FMT``, ``AAD``/``AIT``, ``CN``, ``ERRX?`` drain, on
    hardware the ``LOP?`` positive control (``Transaction.lop_positive_control``: the switched-on SMUs must not read
    ``00``), ``DV`` per bias/ground SMU, ``MM``/``CMM``/``WV``/``WT``/``WM``, ``ERRX?`` drain (any error aborts)."""
    driver = tx.driver
    driver.set_format(*program.data_format)
    driver.apply_integration(program.integration, [m.channel for m in program.measure])
    driver.enable(program.enable)
    drain_or_raise(tx, "enabling the outputs")
    tx.mark("outputs enabled")
    tx.lop_positive_control(program.enable)
    for bias in program.biases:
        driver.force_v(bias.channel, bias.v, icomp=bias.icomp)
    driver.staircase_v(program.sweep)
    drain_or_raise(tx, "the sweep setup")
    tx.mark("configured")


def staircase_rows(program: StaircaseProgram, block: RawBlock, *, first_step: int = 0) -> list[dict[str, object]]:
    """Table rows of one sweep block: ``step`` (from ``first_step``), ``segment`` (double sweeps: ``fwd`` for the
    first ``points`` steps, then ``rev``), the sweep source column ``<sweep role>_V`` (unless that role measures V),
    measured ``<role>_<I|V>`` + ``_status`` per measured channel, constant bias source columns.

    Raises:
        ValueError: If the block does not hold ``steps x width`` elements in the programmed order.
    """
    if len(block.points) != program.steps * program.width:
        raise ValueError(f"expected {program.steps * program.width} elements ({program.steps} steps x "
                         f"{program.width}), got {len(block.points)}")
    measured_v = {m.role for m in program.measure if m.quantity == "V"}
    sweep_source = None if program.sweep_role in measured_v else f"{program.sweep_role}_V"
    rows: list[dict[str, object]] = []
    for index, elements in enumerate(block.steps(program.width)):
        row: dict[str, object] = {"step": first_step + index}
        if program.sweep.double:
            row["segment"] = "fwd" if index < program.sweep.points else "rev"
        source = elements[-1] if program.data_format[1] == 1 else None
        if sweep_source is not None:
            if source is None or not source.is_source:
                raise ValueError(f"step {index}: the last element is not the sweep source value")
            row[sweep_source] = source.value
        for column, element in zip(program.measure, elements, strict=False):
            if element.is_source or element.channel_number is None \
                    or _norm(element.channel_number) != _norm(column.channel) \
                    or element.data_type != column.quantity:
                raise ValueError(f"step {index}: element {element.raw!r} is not {column.quantity} of channel "
                                 f"{column.channel}")
            name = f"{column.role}_{column.quantity}"
            row[name] = element.value
            row[f"{name}_status"] = str(element.status.value)
        for role, level in program.source_columns.items():
            row[f"{role}_V"] = level
        rows.append(row)
    return rows


# -- the kind --------------------------------------------------------------------------------------------------------


class SmuStaircaseKind:
    """Single or double staircase voltage sweep on one SMU with bias/ground roles (sim and visa code path)."""

    kind_id = "smu_staircase"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program; see the module docstring for the role semantics."""
        sweeps = [name for name, role in recipe.roles.items() if role.function == "sweep_v"]
        if len(sweeps) != 1:
            raise CompileError(f"{self.kind_id} needs exactly one sweep_v role; recipe {recipe.id} has {sweeps}")
        stepped = [name for name, role in recipe.roles.items() if role.function == "step_v"]
        if stepped:
            raise CompileError(f"step_v roles {stepped} need kind smu_stepped, not {self.kind_id}")
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in STAIRCASE_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(STAIRCASE_FUNCTIONS))}")
        integration = self._integration(params)
        channels: dict[int, ChannelEnvelope] = {}
        biases: list[BiasOutput] = []
        grounds: list[tuple[str, int, RoleSpec]] = []
        sweep_setup: dict[str, object] | None = None
        sourcing_icomp = 0.0
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue  # unbound or GNDU: R-PIN-01 decides whether that is allowed
            channel = bound.channel
            if role.function == "sweep_v":
                start = _number(setting_value(role, "start", params), f"{name}.start")
                stop = _number(setting_value(role, "stop", params), f"{name}.stop")
                points = setting_value(role, "points", params)
                if isinstance(points, bool) or not isinstance(points, int) or points < 1:
                    raise CompileError(f"{name}.points must be a positive integer, got {points!r}")
                icomp = _number(setting_value(role, COMPLIANCE_SETTING, params), f"{name}.{COMPLIANCE_SETTING}")
                mode = _choice(setting_value(role, "mode", params, "single"), ("single", "double"), f"{name}.mode")
                scale = _choice(setting_value(role, "scale", params, "linear"), ("linear", "log"), f"{name}.scale")
                hold = _number(setting_value(role, "hold", params, 0.0), f"{name}.hold")
                delay = _number(setting_value(role, "delay", params, 0.0), f"{name}.delay")
                sweep_setup = {"channel": channel, "start": start, "stop": stop, "points": points, "icomp": icomp,
                               "sweep": scale, "double": mode == "double",
                               "timing": SweepTiming(hold_s=hold, delay_s=delay)}
                channels[channel] = ChannelEnvelope(role=name, max_abs_v=max(abs(start), abs(stop)),
                                                    max_abs_i=abs(icomp), function="sweep_v", v_start=start,
                                                    v_stop=stop)
                sourcing_icomp += abs(icomp)
            elif role.function == "bias_v":
                v = _number(setting_value(role, "v", params), f"{name}.v")
                icomp = _number(setting_value(role, COMPLIANCE_SETTING, params), f"{name}.{COMPLIANCE_SETTING}")
                biases.append(BiasOutput(role=name, channel=channel, v=v, icomp=icomp))
                channels[channel] = ChannelEnvelope(role=name, max_abs_v=abs(v), max_abs_i=abs(icomp),
                                                    function="bias_v", v_start=v, v_stop=v)
                sourcing_icomp += abs(icomp)
            else:  # ground or measure_only on an SMU: 0 V
                grounds.append((name, channel, role))
        for name, channel, role in grounds:
            explicit = setting_value(role, COMPLIANCE_SETTING, params)
            icomp = (_number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else sourcing_icomp)
            channels[channel] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(icomp),
                                                function=role.function, v_start=0.0, v_stop=0.0)
            if icomp != 0:
                biases.append(BiasOutput(role=name, channel=channel, v=0.0, icomp=icomp))
        envelope = CompiledEnvelope(channels=channels)
        if sweep_setup is None:
            # The sweep role is not bound to a channel: the plan-phase rules block the plan (R-PIN-01).
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
        measure = self._measure(recipe, binding, sweeps[0])
        enable = [b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                  and b.channel is not None]
        try:
            setup = StaircaseSetup(
                **sweep_setup,  # type: ignore[arg-type]
                measure=tuple(m.channel for m in measure),
                operation={m.channel: (1 if m.quantity == "I" else 2) for m in measure},
                auto_abort=True,
                post="start",
            )
        except ValueError as exc:
            raise CompileError(f"invalid sweep: {exc}") from None
        measured_v = {m.role for m in measure if m.quantity == "V"}
        program = StaircaseProgram(
            integration=integration,
            enable=enable,
            biases=biases,
            sweep_role=sweeps[0],
            sweep=setup,
            measure=measure,
            source_columns={b.role: b.v for b in biases
                            if recipe.roles[b.role].function == "bias_v" and b.role not in measured_v},
        )
        estimate = Estimate(points=program.steps, duration_s=self._duration(program))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self.preview(program),
                                program=program.model_dump(mode="json"))

    @staticmethod
    def _integration(params: dict[str, Quantity]) -> Integration:
        preset = params.get(INTEGRATION_PARAM)
        name = DEFAULT_PRESET if preset is None else preset.value
        if not isinstance(name, str) or name not in INTEGRATION_PRESETS:
            raise CompileError(f"{INTEGRATION_PARAM} must be one of {sorted(INTEGRATION_PRESETS)}, got {name!r}")
        return INTEGRATION_PRESETS[name]

    def _measure(self, recipe: Recipe, binding: ChannelBinding, sweep_role: str) -> list[MeasureColumn]:
        order = [sweep_role, *(name for name in recipe.roles if name != sweep_role)]
        measure: list[MeasureColumn] = []
        for name in order:
            role = recipe.roles[name]
            bound = binding.roles.get(name)
            if not role.measure or bound is None or bound.channel is None:
                continue
            if len(role.measure) > 1:
                raise CompileError(f"role {name} measures {role.measure}; {self.kind_id} measures one quantity per "
                                   "channel in v1")
            measure.append(MeasureColumn(channel=bound.channel, role=name, quantity=role.measure[0]))
        if not measure:
            raise CompileError(f"recipe {recipe.id}: no bound role measures anything")
        return measure

    @staticmethod
    def _duration(program: StaircaseProgram) -> float:
        per_measurement = measurement_time_s(program.integration)
        timing = program.sweep.timing
        per_step = timing.delay_s + max(len(program.measure) * per_measurement, timing.step_delay_s)
        return round(SETUP_OVERHEAD_S + timing.hold_s + program.steps * per_step, 6)

    @staticmethod
    def preview(program: StaircaseProgram) -> list[str]:
        """The setup and trigger commands ``acquire`` writes, in order (``ERRX?`` drains are not listed)."""
        integration = program.integration
        adc = ADC_TYPE_CODES[integration.adc]
        sweep = program.sweep
        timing = sweep.timing
        lines = [flex.fmt(*program.data_format)]
        lines += [flex.aad(m.channel, adc) for m in program.measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n))
        lines.append(flex.cn(program.enable))
        lines += [flex.dv(b.channel, 0, b.v, b.icomp) for b in program.biases]
        lines.append(flex.mm(2, sweep.measure))
        lines += [flex.cmm(ch, op) for ch, op in sweep.operation.items()]
        lines.append(flex.wv(sweep.channel, sweep.wv_mode, sweep.vrange, sweep.start, sweep.stop, sweep.points,
                                 sweep.icomp))
        lines.append(flex.wt(timing.hold_s, timing.delay_s, timing.step_delay_s, timing.trigger_delay_s,
                                 timing.measure_delay_s))
        lines.append(flex.wm(2 if sweep.auto_abort else 1, 1 if sweep.post == "start" else 2))
        lines.append(flex.XE)
        return lines

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (see the module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = StaircaseProgram.model_validate(plan.program)
        configure_staircase(tx, program)
        block = tx.driver.execute_and_read(expected_points=program.steps * program.width,
                                        timeout_s=read_timeout_s(plan.estimate))
        tx.mark("data read")
        return RawAcquisition(blocks=[block])

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """Tidy table of the single block (``staircase_rows``): ``step``, ``segment`` (double sweeps), the sweep
        source column ``<sweep role>_V``, measured ``<role>_<I|V>`` + ``_status`` per measured channel, constant bias
        source columns.

        Raises:
            ValueError: If there is not exactly one block or it does not hold ``steps x width`` elements in the
                programmed order.
        """
        program = StaircaseProgram.model_validate(plan.program)
        if len(raw.blocks) != 1:
            raise ValueError(f"{self.kind_id} expects one data block, got {len(raw.blocks)}")
        return pd.DataFrame(staircase_rows(program, raw.blocks[0]))
