"""``smu_staircase``: one SMU staircase sweep with synchronous or multi-channel sources and constant bias and ground
roles (blueprint v1 2.6; v2 2.7: WV/WI lin/log single/double, WSV/WSI, MM 16 with WNX).

Roles (recipe ``roles``, bound to channels through the pin map):

- one or more sweep roles, ``sweep_v`` (``WV``, voltage) or ``sweep_i`` (``WI``, current). The first one in recipe
  order is the primary sweep: settings ``start``, ``stop``, ``points`` and its compliance (``icomp`` in A for a
  voltage sweep, ``vcomp`` in V for a current sweep), all required, optional ``mode`` (``single``|``double``:
  start→stop or start→stop→start, 2·points steps), ``scale`` (``linear``|``log``; a log sweep needs non-zero start
  and stop of one polarity on every source), ``hold``/``delay`` (s, ``WT``);
- a recipe with two or more sweep roles is a multi-channel sweep (``MM 16``, PG p102 (2-14)): every further sweep
  role is a ``WNX`` source N = 2, 3, ... in recipe order (either output mode; settings ``start``, ``stop`` and its
  compliance; ``start`` = ``stop`` is a constant source) that follows the primary's steps and sweep mode, so it
  must not set ``points``, ``mode``, ``scale``, ``hold`` or ``delay`` to other values. An unbound optional sweep
  role is left out; the recipe stays an MM 16 recipe (an MM 16 sweep with the primary alone is legal, PG Table 3-13);
- at most one synchronous role (MM 2 only), ``sync_v`` (``WSV``, after a ``sweep_v`` primary) or ``sync_i``
  (``WSI``, after a ``sweep_i`` primary; PG p97 (2-9): the same output mode as the primary): ``start``, ``stop``
  and its compliance, following the primary's steps and sweep mode;
- ``bias_v`` roles: ``DV`` at setting ``v`` with compliance ``icomp``; ``bias_i`` roles: ``DI`` at setting ``i`` (A)
  with compliance ``vcomp`` (V);
- ``ground`` roles: the GNDU (nothing is sent) or an SMU forced to 0 V (``DV``) whose compliance is setting
  ``icomp`` or, when absent, the sum of what the sourcing roles can drive (their current compliances and forced
  currents: the ground terminal returns at most their currents);
- ``measure_only`` roles: an SMU at 0 V like a grounded SMU, measured;
- ``step_v``/``step_i`` roles need kind ``smu_stepped`` and are refused, as is every other role function (pulse,
  SPGU, WGFMU and MFCMU roles belong to their own kinds).

Each role's ``measure`` (``[I]`` or ``[V]``; both at once is not supported) puts its channel into the ``MM`` list
(primary sweep role first, then recipe order) with ``CMM`` 1 (current) or 2 (voltage). A current-measuring role may
set ``irange`` (full scale in A) or ``asu_1pa`` (bool): limited auto ranging that never goes below that range (``RI``
after ``WM``; ``catalog/kinds/ranging.py``, rule R-ASU-01 for the ASU's 1 pA range). The recipe parameter
``integration`` (``short``|``medium``|``long``, default ``medium``) selects the ADC preset for every measured
channel. The sweep always uses ``WM 2,1``: automatic abort on compliance (voltage or current), overflow or
oscillation (later steps then read ``199.999E+99`` with status ``V``) and a return of every sweep source to its
start value.

Acquisition (through the transaction's guarded driver, nothing else): ``FMT 1,1`` (each step also returns the
primary sweep source value), ``AAD``/``AIT``, ``CN``, ``ERRX?`` drain (an interlock error 202/203 or any other error
aborts: ATV-10 fallback), on hardware the ``LOP?`` positive control (v2 WP6.2), ``DV``/``DI`` per bias/ground SMU,
``MM``/``CMM``/``WV``|``WI``/``WSV``|``WSI``|``WNX``/``WT``/``WM``, ``RI`` per ranged role, ``ERRX?`` drain (any
error aborts: also a range the SMU lacks, e.g. 1 pA without an ASU), ``XE`` and one read of
``steps × (measured channels + 1)`` elements with a timeout of ``2 × estimate + 10 s`` (blueprint 7). The FLEX
preview lists exactly these writes in this order (queries are not listed).

Table columns (``analysis/dataset.py`` contract): ``step``, ``segment`` (double sweeps), the primary source
``<role>_V``|``<role>_I`` (the value the instrument returns with each step), the synchronous or ``WNX`` sources'
programmed values ``<role>_V``|``<role>_I`` (in source order), measured ``<role>_<I|V>`` + ``_status`` per measured
channel, constant bias source columns ``<role>_V`` (``bias_v``) or ``<role>_I`` (``bias_i``). A source column is left
out when its role measures the quantity it forces (the measured column holds it).

The same code path serves ``sim`` and ``visa``: the kind only talks to the driver. ``configure_staircase`` (setup
up to ``XE``) and ``staircase_rows`` (table rows of one block) are shared with ``smu_stepped``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, ClassVar, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.ranging import RangeSetting, limited_range
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import ADC_MODE_CODES, ADC_TYPE_CODES, RawBlock, StaircaseSetup, SweepSource
from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, ErrorCode, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration, SweepTiming
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleFunction, RoleSpec
from b1500_test_agent.models.station import InstrumentError, StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING, VOLTAGE_COMPLIANCE_SETTING, interlock_errors

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

Source = Literal["V", "I"]

SWEEP_FUNCTIONS: dict[str, Source] = {"sweep_v": "V", "sweep_i": "I"}
"""Sweep role functions and what they force (``WV``/``WI``; further sweep roles: ``WNX``)."""

SYNC_FUNCTIONS: dict[str, Source] = {"sync_v": "V", "sync_i": "I"}
"""Synchronous sweep role functions (``WSV``/``WSI``, MM 2)."""

BIAS_FUNCTIONS: dict[str, Source] = {"bias_v": "V", "bias_i": "I"}
"""Constant bias role functions (``DV``/``DI``)."""

STEP_FUNCTIONS = frozenset({"step_v", "step_i"})
"""Host-stepped role functions (kind ``smu_stepped``)."""

STAIRCASE_FUNCTIONS = frozenset({*SWEEP_FUNCTIONS, *SYNC_FUNCTIONS, *BIAS_FUNCTIONS, "ground", "measure_only"})
"""Role functions this kind executes."""

COMP_SETTINGS: dict[Source, str] = {"V": COMPLIANCE_SETTING, "I": VOLTAGE_COMPLIANCE_SETTING}
"""Compliance setting of a source role: ``icomp`` (A) for a voltage source, ``vcomp`` (V) for a current source."""

LEVEL_SETTINGS: dict[Source, str] = {"V": "v", "I": "i"}
"""Level setting of a bias role: ``v`` (V) for ``bias_v``, ``i`` (A) for ``bias_i``."""

PRIMARY_ONLY_SETTINGS = ("points", "mode", "scale", "hold", "delay")
"""Sweep settings that only the primary sweep role decides (``WNX`` sources follow it, PG p557 (4-239))."""

MAX_SWEEP_ROLES = 10
"""Sweep sources of one multi-channel sweep: the primary plus ``WNX`` N = 2 to 10 (PG p557 (4-239))."""

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


class PrimarySweep(StrictModel):
    """The resolved settings of the primary sweep role (compile-time only)."""

    channel: Channel
    source: Source
    start: float
    stop: float
    points: int
    comp: float
    scale: Literal["linear", "log"]
    double: bool
    timing: SweepTiming


class MeasureColumn(StrictModel):
    """One measured channel: its role and quantity (in ``MM`` order = data order of each step)."""

    channel: Channel
    role: str
    quantity: Literal["I", "V"]


class BiasOutput(StrictModel):
    """A constant DC output held during the sweep (bias, grounded SMU or measure-only SMU): ``source`` ``V``
    (``DV`` at ``level`` volts, compliance ``comp`` in A) or ``I`` (``DI`` at ``level`` amperes, compliance ``comp``
    in V)."""

    role: str
    channel: Channel
    source: Source = "V"
    level: float
    comp: float

    @property
    def column(self) -> str:
        """Its source column, ``<role>_V`` or ``<role>_I``."""
        return f"{self.role}_{self.source}"


class StaircaseProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    data_format: tuple[int, int] = DATA_FORMAT
    integration: Integration
    enable: list[Channel] = Field(min_length=1)
    biases: list[BiasOutput] = Field(default_factory=list)
    sweep_role: str
    sweep: StaircaseSetup
    follower_roles: list[str] = Field(default_factory=list)
    """Roles of the synchronous or ``WNX`` sources, in ``sweep.followers`` order."""
    measure: list[MeasureColumn] = Field(min_length=1)
    source_columns: dict[str, float] = Field(default_factory=dict)
    """Constant programmed levels of bias roles written as source columns (``drain_V``, ``base_I``), unless the role
    measures that quantity."""
    ranges: list[RangeSetting] = Field(default_factory=list)
    """``RI`` limited auto ranging of the roles with ``irange``/``asu_1pa`` (WP7.1); empty = auto ranging."""

    def dump(self) -> dict[str, object]:
        """The JSON program; without ranges there is no ``ranges`` key, so plans without ranging keep their hash."""
        return self.model_dump(mode="json", exclude={"ranges"} if not self.ranges else None)

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


def _source_envelope(role: str, function: RoleFunction, source: Source, levels: list[float],
                     comp: float) -> ChannelEnvelope:
    """The envelope of a sourcing role: a voltage source bounds |V| by its levels and |I| by its compliance (and shows
    its first/last level); a current source bounds |I| by its levels and |V| by its compliance."""
    peak = max(abs(v) for v in levels)
    if source == "V":
        return ChannelEnvelope(role=role, max_abs_v=peak, max_abs_i=abs(comp), function=function,
                               v_start=levels[0], v_stop=levels[-1])
    return ChannelEnvelope(role=role, max_abs_v=abs(comp), max_abs_i=peak, function=function)


def _drive(source: Source, levels: list[float], comp: float) -> float:
    """The most current a sourcing role can push into the DUT: its current compliance (voltage source) or its largest
    forced current (current source); a grounded SMU returns at most the sum."""
    return abs(comp) if source == "V" else max(abs(v) for v in levels)


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
    ``00``), ``DV``/``DI`` per bias/ground SMU, the sweep setup (``MM``/``CMM``/``WV``|``WI``/``WSV``|``WSI``|
    ``WNX``/``WT``/``WM``), ``RI`` per ranged role, ``ERRX?`` drain (any error aborts)."""
    driver = tx.driver
    driver.set_format(*program.data_format)
    driver.apply_integration(program.integration, [m.channel for m in program.measure])
    driver.enable(program.enable)
    drain_or_raise(tx, "enabling the outputs")
    tx.mark("outputs enabled")
    tx.lop_positive_control(program.enable)
    for bias in program.biases:
        force_bias(tx, bias)
    driver.staircase(program.sweep)
    for ranged in program.ranges:
        driver.set_range(ranged.channel, "I", ranged.code)
    drain_or_raise(tx, "the sweep setup")
    tx.mark("configured")


def force_bias(tx: Transaction, bias: BiasOutput) -> None:
    """``DV`` or ``DI`` of one constant output through the guarded driver."""
    if bias.source == "V":
        tx.driver.force_v(bias.channel, bias.level, icomp=bias.comp)
    else:
        tx.driver.force_i(bias.channel, bias.level, vcomp=bias.comp)


def bias_command(bias: BiasOutput) -> str:
    """The FLEX text ``force_bias`` writes (for the preview)."""
    build = flex.dv if bias.source == "V" else flex.di
    return build(bias.channel, 0, bias.level, bias.comp)


def follower_values(program: StaircaseProgram) -> dict[str, list[float]]:
    """Programmed values per step of the synchronous/``WNX`` sources, by source column (``<role>_V|I``), in the
    primary's sweep mode and steps (PG p97 (2-9), p102 (2-14))."""
    sweep = program.sweep
    out: dict[str, list[float]] = {}
    for role, src in zip(program.follower_roles, sweep.followers, strict=True):
        out[f"{role}_{src.source}"] = source_values(src.start, src.stop, sweep.points, sweep.sweep, sweep.double)
    return out


def source_values(start: float, stop: float, points: int, scale: str, double: bool) -> list[float]:
    """Staircase output values: linear steps, or log steps ``start·(stop/start)^(k/(n-1))``, single or double (there
    and back); a log source with ``start`` = ``stop`` stays constant."""
    if points == 1:
        forward = [start]
    elif scale == "linear":
        forward = [start + (stop - start) * i / (points - 1) for i in range(points)]
    else:
        forward = [start * (stop / start) ** (i / (points - 1)) for i in range(points)]
    return forward + forward[::-1] if double else forward


def staircase_rows(program: StaircaseProgram, block: RawBlock, *, first_step: int = 0) -> list[dict[str, object]]:
    """Table rows of one sweep block: ``step`` (from ``first_step``), ``segment`` (double sweeps: ``fwd`` for the
    first ``points`` steps, then ``rev``), the primary source column ``<sweep role>_V|I`` (the returned source value),
    the follower source columns (programmed values), measured ``<role>_<I|V>`` + ``_status`` per measured channel,
    constant bias source columns; a role that measures the quantity it forces gets no source column.

    Raises:
        ValueError: If the block does not hold ``steps x width`` elements in the programmed order.
    """
    if len(block.points) != program.steps * program.width:
        raise ValueError(f"expected {program.steps * program.width} elements ({program.steps} steps x "
                         f"{program.width}), got {len(block.points)}")
    measured = {f"{m.role}_{m.quantity}" for m in program.measure}
    primary = f"{program.sweep_role}_{program.sweep.source}"
    sweep_source = None if primary in measured else primary
    followers = {column: values for column, values in follower_values(program).items() if column not in measured}
    constants = {column: level for column, level in program.source_columns.items() if column not in measured}
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
        for column, values in followers.items():
            row[column] = values[index]
        for column, element in zip(program.measure, elements, strict=False):
            if element.is_source or element.channel_number is None \
                    or _norm(element.channel_number) != _norm(column.channel) \
                    or element.data_type != column.quantity:
                raise ValueError(f"step {index}: element {element.raw!r} is not {column.quantity} of channel "
                                 f"{column.channel}")
            name = f"{column.role}_{column.quantity}"
            row[name] = element.value
            row[f"{name}_status"] = str(element.status.value)
        for column, level in constants.items():
            row[column] = level
        rows.append(row)
    return rows


# -- the kind --------------------------------------------------------------------------------------------------------


class SmuStaircaseKind:
    """Staircase sweep (MM 2, or MM 16 with several sweep roles) with synchronous, bias and ground roles (sim and
    visa code path)."""

    kind_id = "smu_staircase"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program; see the module docstring for the role semantics."""
        sweeps, syncs = self._check_roles(recipe)
        integration = self._integration(params)
        primary = sweeps[0]
        primary_source = SWEEP_FUNCTIONS[recipe.roles[primary].function]
        channels: dict[int, ChannelEnvelope] = {}
        biases: list[BiasOutput] = []
        grounds: list[tuple[str, int, RoleSpec]] = []
        sweep_setup: PrimarySweep | None = None
        followers: list[tuple[str, SweepSource]] = []
        sourcing = 0.0
        for name, role in recipe.roles.items():
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue  # unbound or GNDU: R-PIN-01 decides whether that is allowed
            channel = bound.channel
            function = role.function
            if name == primary:
                sweep_setup = self._primary(name, role, params, channel)
                levels = [sweep_setup.start, sweep_setup.stop]
                channels[channel] = _source_envelope(name, function, sweep_setup.source, levels, sweep_setup.comp)
                sourcing += _drive(sweep_setup.source, levels, sweep_setup.comp)
            elif function in SWEEP_FUNCTIONS or function in SYNC_FUNCTIONS:
                source = SWEEP_FUNCTIONS.get(function) or SYNC_FUNCTIONS[function]
                follower = self._follower(name, role, params, channel, source, recipe.roles[primary], primary)
                followers.append((name, follower))
                channels[channel] = _source_envelope(name, function, source, [follower.start, follower.stop],
                                                     follower.comp)
                sourcing += _drive(source, [follower.start, follower.stop], follower.comp)
            elif function in BIAS_FUNCTIONS:
                source = BIAS_FUNCTIONS[function]
                level = _number(setting_value(role, LEVEL_SETTINGS[source], params),
                                f"{name}.{LEVEL_SETTINGS[source]}")
                comp = _number(setting_value(role, COMP_SETTINGS[source], params), f"{name}.{COMP_SETTINGS[source]}")
                biases.append(BiasOutput(role=name, channel=channel, source=source, level=level, comp=comp))
                channels[channel] = _source_envelope(name, function, source, [level], comp)
                sourcing += _drive(source, [level], comp)
            else:  # ground or measure_only on an SMU: 0 V
                grounds.append((name, channel, role))
        for name, channel, role in grounds:
            explicit = setting_value(role, COMPLIANCE_SETTING, params)
            icomp = (_number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else sourcing)
            channels[channel] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(icomp),
                                                function=role.function, v_start=0.0, v_stop=0.0)
            if icomp != 0:
                biases.append(BiasOutput(role=name, channel=channel, level=0.0, comp=icomp))
        envelope = CompiledEnvelope(channels=channels)
        if sweep_setup is None:
            # The primary sweep role is not bound to a channel: the plan-phase rules block the plan (R-PIN-01).
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
        measure = self._measure(recipe, binding, primary)
        enable = [b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                  and b.channel is not None]
        multi = len(sweeps) > 1
        try:
            setup = StaircaseSetup(
                channel=sweep_setup.channel, start=sweep_setup.start, stop=sweep_setup.stop,
                points=sweep_setup.points, source=primary_source, sweep=sweep_setup.scale,
                double=sweep_setup.double, timing=sweep_setup.timing,
                icomp=sweep_setup.comp if primary_source == "V" else None,
                vcomp=sweep_setup.comp if primary_source == "I" else None,
                sync=followers[0][1] if syncs and followers else None,
                multi_channel=multi, sources=tuple(f for _, f in followers) if multi else (),
                measure=tuple(m.channel for m in measure),
                operation={m.channel: (1 if m.quantity == "I" else 2) for m in measure},
                auto_abort=True, post="start",
            )
        except ValueError as exc:
            raise CompileError(f"invalid sweep: {exc}") from None
        measured = {f"{m.role}_{m.quantity}" for m in measure}
        program = StaircaseProgram(
            integration=integration,
            enable=enable,
            biases=biases,
            sweep_role=primary,
            sweep=setup,
            follower_roles=[name for name, _ in followers],
            measure=measure,
            source_columns={b.column: b.level for b in biases
                            if recipe.roles[b.role].function in BIAS_FUNCTIONS and b.column not in measured},
            ranges=self._ranges(recipe, params, binding, measure),
        )
        estimate = Estimate(points=program.steps, duration_s=self._duration(program))
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=self.preview(program),
                                program=program.dump())

    @staticmethod
    def _ranges(recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                measure: list[MeasureColumn]) -> list[RangeSetting]:
        """``RI`` limited auto ranging of the current-measuring roles with ``irange``/``asu_1pa`` (``ranging.py``)."""
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

    def _check_roles(self, recipe: Recipe) -> tuple[list[str], list[str]]:
        """Sweep and synchronous role names (recipe order) after the role-function checks (CompileError)."""
        sweeps = [name for name, role in recipe.roles.items() if role.function in SWEEP_FUNCTIONS]
        syncs = [name for name, role in recipe.roles.items() if role.function in SYNC_FUNCTIONS]
        if not sweeps:
            raise CompileError(f"{self.kind_id} needs a sweep_v or sweep_i role; recipe {recipe.id} has none")
        if len(sweeps) > MAX_SWEEP_ROLES:
            raise CompileError(f"{self.kind_id}: {len(sweeps)} sweep roles exceed the {MAX_SWEEP_ROLES} sweep sources "
                               "of a multi-channel sweep (PG p557 (4-239))")
        stepped = [name for name, role in recipe.roles.items() if role.function in STEP_FUNCTIONS]
        if stepped:
            raise CompileError(f"step roles {stepped} need kind smu_stepped, not {self.kind_id}")
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in STAIRCASE_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(STAIRCASE_FUNCTIONS))}")
        if len(syncs) > 1:
            raise CompileError(f"{self.kind_id}: at most one synchronous role (WSV/WSI); recipe {recipe.id} has "
                               f"{syncs}")
        if syncs and len(sweeps) > 1:
            raise CompileError(f"{self.kind_id}: a synchronous role ({syncs[0]}) belongs to a single-sweep "
                               "staircase; with several sweep roles every further one is a multi-channel sweep source")
        if syncs:
            primary_source = SWEEP_FUNCTIONS[recipe.roles[sweeps[0]].function]
            if SYNC_FUNCTIONS[recipe.roles[syncs[0]].function] != primary_source:
                raise CompileError(f"{self.kind_id}: {syncs[0]} must force what the primary {sweeps[0]} forces "
                                   f"({'sync_v' if primary_source == 'V' else 'sync_i'}; PG p97 (2-9))")
        return sweeps, syncs

    @staticmethod
    def _primary(name: str, role: RoleSpec, params: dict[str, Quantity], channel: int) -> PrimarySweep:
        """The primary sweep's resolved settings."""
        source = SWEEP_FUNCTIONS[role.function]
        comp_name = COMP_SETTINGS[source]
        start = _number(setting_value(role, "start", params), f"{name}.start")
        stop = _number(setting_value(role, "stop", params), f"{name}.stop")
        points = setting_value(role, "points", params)
        if isinstance(points, float) and points.is_integer():
            points = int(points)  # a literal role setting is stored as a float
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise CompileError(f"{name}.points must be a positive integer, got {points!r}")
        comp = _number(setting_value(role, comp_name, params), f"{name}.{comp_name}")
        mode = _choice(setting_value(role, "mode", params, "single"), ("single", "double"), f"{name}.mode")
        scale = _choice(setting_value(role, "scale", params, "linear"), ("linear", "log"), f"{name}.scale")
        hold = _number(setting_value(role, "hold", params, 0.0), f"{name}.hold")
        delay = _number(setting_value(role, "delay", params, 0.0), f"{name}.delay")
        try:
            timing = SweepTiming(hold_s=hold, delay_s=delay)
        except ValueError as exc:
            raise CompileError(f"{name}: invalid sweep timing: {exc}") from None
        return PrimarySweep(channel=channel, source=source, start=start, stop=stop, points=points, comp=comp,
                            scale=scale, double=mode == "double", timing=timing)

    @staticmethod
    def _follower(name: str, role: RoleSpec, params: dict[str, Quantity], channel: int, source: Source,
                  primary: RoleSpec, primary_name: str) -> SweepSource:
        """A synchronous or ``WNX`` source: ``start``, ``stop`` and its compliance; the primary-only settings may only
        repeat the primary's values."""
        for key in PRIMARY_ONLY_SETTINGS:
            own = setting_value(role, key, params)
            if own is not None and own != setting_value(primary, key, params):
                raise CompileError(f"{name}.{key}: a following sweep source uses the primary's {key} "
                                   f"({primary_name}); remove the setting")
        comp_name = COMP_SETTINGS[source]
        start = _number(setting_value(role, "start", params), f"{name}.start")
        stop = _number(setting_value(role, "stop", params), f"{name}.stop")
        comp = _number(setting_value(role, comp_name, params), f"{name}.{comp_name}")
        try:
            return SweepSource(channel=channel, source=source, start=start, stop=stop, comp=comp)
        except ValueError as exc:
            raise CompileError(f"{name}: {exc}") from None

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
        lines = [flex.fmt(*program.data_format)]
        lines += [flex.aad(m.channel, adc) for m in program.measure]
        lines.append(flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n))
        lines.append(flex.cn(program.enable))
        lines += [bias_command(b) for b in program.biases]
        lines += program.sweep.commands()
        lines += [flex.ri(r.channel, r.code) for r in program.ranges]
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
