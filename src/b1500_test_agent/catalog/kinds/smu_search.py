"""``smu_search``: SMU search measurements, ``MM 14`` linear search, ``MM 15`` binary search and ``MM 9`` quasi-pulsed
spot (blueprint v2 2.7, WP7.5): the instrument steps or bisects one source until a monitored current or voltage
reaches a target (threshold voltage at a critical current, breakdown voltage at a current criterion) or ramps a
quasi-pulse until the device breaks down; one ``XE``, one result.

Roles (recipe ``roles``, bound through the pin map):

- exactly one search role, ``sweep_v`` (voltage source) or ``sweep_i`` (current source), with setting ``search``:
  ``linear`` (``LSV``/``LSI``: ``start``, ``stop``, ``step``), ``binary`` (``BSV``/``BSI``: ``start``, ``stop``;
  ``control`` ``normal``|``cautious``, default ``cautious``: cautious never forces the stop value first) or
  ``quasi_pulsed`` (``BDV``, ``sweep_v`` only: ``start`` default 0, ``stop``, ``|stop - start| >= 10 V``;
  ``interval`` ``short``|``long``). Its compliance is ``icomp`` (A) for a voltage source, ``vcomp`` (V) for a current
  source; optional ``hold``/``delay`` (s; ``LSTM``/``BST``/``BDT``), ``post`` (``start``|``stop``|``last``, the
  output after a normal end; default ``start``) and ``auto_abort`` (bool, default true: compliance, overflow or
  oscillation stops the search and the sources return to start);
- linear/binary: exactly one monitor role, the role with setting ``target`` (may be the search role itself). It
  measures its compliance side (PG error 279): current on a voltage-forcing role (``sweep_v``, ``sync_v``,
  ``bias_v``, ``ground``, ``measure_only``), voltage on a current-forcing one, and must list that quantity in
  ``measure``. ``target`` is a magnitude (> 0, A or V), times ``target_scale`` (default 1; e.g. W/L); its polarity is
  the one the monitored quantity of a passive device takes: on the search role the ramp direction (stop - start), on
  a bias role its level's sign, on the synchronous role its larger end's sign, on a ground/measure-only role the
  opposite of the ramp (the return current). Linear: ``judge`` ``above`` (the first step with a reading ``>=
  target``) or ``below`` (``<=``), default from the signed target (``|reading| >= |target|``); ``step`` is a
  magnitude, its sign follows start -> stop. Binary: one of ``limit`` (stop at ``target +/- limit``), ``limit_rel``
  (``limit = limit_rel x |target|``) and ``repeats`` (1-16 output changes). The target must not exceed the monitor's
  compliance (error 275);
- at most one synchronous role, ``sync_v``/``sync_i`` (``LSSV``/``LSSI``, ``BSSV``/``BSSI``; same output mode as the
  search role): ``polarity`` (+1/-1, default +1), ``offset`` (default 0) and its compliance; it forces
  ``polarity x search + offset`` (linear/binary only);
- ``bias_v``/``bias_i``, ``ground`` and ``measure_only`` roles as in ``smu_staircase`` (``DV``/``DI`` held during the
  search; a ground SMU's compliance is ``icomp`` or the sum of what the sources can drive);
- quasi-pulsed: exactly one measuring role (the search role or another SMU role) measures ``V`` when its ``measure``
  lists ``V`` (``BDM`` mode 0: the detection voltage, i.e. the breakdown voltage), else ``I`` (mode 1). A role may
  list ``[V, I]`` so one recipe serves both a quasi-pulsed and a linear search (``dielectric.bdv``: ``method``).

Recipe parameter ``integration`` (``short``/``medium``/``long``, default ``medium``) selects the ADC preset of the
measuring channel (``AAD``/``AIT``, as ``smu_staircase``).

Compile (pure): per-channel envelope (the search source |V| or |I| up to its larger end, compliance, ``v_start``/
``v_stop``; the synchronous source at ``polarity x start/stop + offset``; bias/ground roles as ``smu_staircase``), the
estimate (1 s setup; hold + points x (delay + measurement time): linear the step count, binary ``repeats + 2`` or 19
points; quasi-pulsed hold + the ramp at 6 V/ms + delay + measurement time; ``max_segment_s`` = the whole search,
one ``XE`` that only ``AB`` interrupts) and the exact FLEX preview.

Acquire (one transaction, guarded driver only): ``FMT 1,0``, ``AAD``/``AIT``, ``CN``, ``ERRX?`` drain, on hardware the
``LOP?`` positive control, ``DV``/``DI`` per bias/ground SMU, the search setup (``search_setup``: ``MM 14``/``MM 15``,
``LSM``/``BSM``, ``LSVM 1``/``BSVM 1``, ``LSTM``/``BST``, monitor, source, synchronous source; or
``quasi_pulse_setup``: ``MM 9,ch``, ``BDT``, ``BDM``, ``BDV``), ``ERRX?`` drain (any error aborts before ``XE``),
``XE`` and one read (``Data_search,Data_sense`` or the one quasi-pulsed datum; timeout ``2 x estimate + 10 s``).
Cleanup is the transaction's.

Table (``data.csv`` contract): one row, ``step`` 0. Linear/binary: the search role's ``<role>_V|I`` = ``Data_search``
(the value it forced at the result point) with ``_status`` (``N`` found, ``G`` not found in the range, ``S`` stopped
by the automatic abort), the monitor's ``<role>_I|V`` = ``Data_sense`` with its ``_status``, the synchronous role's
programmed value at the result, constant bias columns. Quasi-pulsed: the measuring role's ``<role>_V|I`` with its
``_status`` (``C`` the source reached its compliance: the breakdown; ``N`` it reached stop; ``S`` compliance before a
10 V change from start; ``G`` detection timeout) and constant bias columns. ``kind_result``: ``measurement_mode``,
``search``, ``search_status``, ``found``, ``target`` (linear/binary), ``source_column``, ``result_column``,
``monitor_column`` and the programmed ``start``/``stop``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_staircase import (
    BIAS_FUNCTIONS,
    COMP_SETTINGS,
    DEFAULT_PRESET,
    INTEGRATION_PARAM,
    INTEGRATION_PRESETS,
    LEVEL_SETTINGS,
    READ_TIMEOUT_MARGIN_S,
    SETUP_OVERHEAD_S,
    BiasOutput,
    bias_command,
    drain_or_raise,
    force_bias,
    measurement_time_s,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import (
    ADC_MODE_CODES,
    ADC_TYPE_CODES,
    QuasiPulseSetup,
    RawBlock,
    SearchMonitor,
    SearchSetup,
    SearchSource,
    SyncSource,
)
from b1500_test_agent.driver.search import parse_quasi_pulsed, parse_search
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel, Integration
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe, RoleFunction, RoleSpec
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

Source = Literal["V", "I"]
Method = Literal["linear", "binary", "quasi_pulsed"]

SEARCH_SETTING = "search"
"""Role setting that makes a ``sweep_v``/``sweep_i`` role the search source and names the method."""

TARGET_SETTING = "target"
"""Role setting that makes a role the search monitor (linear/binary): the target's magnitude (A or V, > 0)."""

TARGET_SCALE_SETTING = "target_scale"
"""Monitor setting multiplying the target (default 1), e.g. W/L for a critical current per square."""

SEARCH_FUNCTIONS: dict[str, Source] = {"sweep_v": "V", "sweep_i": "I"}
SYNC_FUNCTIONS: dict[str, Source] = {"sync_v": "V", "sync_i": "I"}
VOLTAGE_FORCING = frozenset({"sweep_v", "sync_v", "bias_v", "ground", "measure_only"})
"""Role functions that force a voltage, so a monitor on them measures current (its compliance side)."""

SEARCH_KIND_FUNCTIONS = frozenset({*SEARCH_FUNCTIONS, *SYNC_FUNCTIONS, *BIAS_FUNCTIONS, "ground", "measure_only"})
"""Role functions this kind executes."""

METHOD_MODES: dict[str, int] = {"linear": flex.LINEAR_SEARCH_MODE, "binary": flex.BINARY_SEARCH_MODE,
                                "quasi_pulsed": flex.QUASI_PULSED_SPOT_MODE}

DATA_FORMAT = (1, 0)
"""``FMT 1,0``: ASCII with header, measurement data only (a search returns its own source value)."""

QUASI_RAMP_V_PER_S = 6.0e3
"""Quasi-pulse ramp rate assumed by the estimate (the long detection interval's, the slower one: conservative)."""


class SearchProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``."""

    data_format: tuple[int, int] = DATA_FORMAT
    integration: Integration
    enable: list[Channel] = Field(min_length=1)
    biases: list[BiasOutput] = Field(default_factory=list)
    method: Method
    search: SearchSetup | None = None
    quasi: QuasiPulseSetup | None = None
    source_role: str
    sync_role: str | None = None
    monitor_role: str
    """Linear/binary: the monitor role; quasi-pulsed: the measuring role."""
    monitor_quantity: Source
    source_columns: dict[str, float] = Field(default_factory=dict)
    read_timeout_s: float = Field(gt=0)

    @property
    def mode(self) -> int:
        """The ``MM`` mode."""
        return METHOD_MODES[self.method]

    @property
    def source_quantity(self) -> Source:
        """What the search source forces."""
        if self.search is not None:
            return self.search.source.source
        return "V"

    @property
    def monitor_channel(self) -> int:
        """The measuring channel."""
        if self.search is not None:
            return self.search.monitor.channel
        assert self.quasi is not None
        return self.quasi.measured_channel

    @property
    def expected_points(self) -> int:
        """Elements of the read: ``Data_search,Data_sense`` or the one quasi-pulsed datum."""
        return 2 if self.search is not None else 1

    @property
    def result_column(self) -> str:
        """The column that holds the result value (``Data_search`` or the quasi-pulsed datum)."""
        if self.search is not None:
            return f"{self.source_role}_{self.source_quantity}"
        return f"{self.monitor_role}_{self.monitor_quantity}"

    @property
    def monitor_column(self) -> str:
        """The monitor's column (``Data_sense``; the quasi-pulsed datum)."""
        return f"{self.monitor_role}_{self.monitor_quantity}"


# -- helpers ---------------------------------------------------------------------------------------------------------


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _choice(value: object, choices: tuple[str, ...], what: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise CompileError(f"{what} must be one of {list(choices)}, got {value!r}")
    return value


def _flag(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise CompileError(f"{what} must be true or false, got {value!r}")
    return value


def _source_envelope(role: str, function: RoleFunction, source: Source, levels: list[float],
                     comp: float) -> ChannelEnvelope:
    peak = max(abs(v) for v in levels)
    if source == "V":
        return ChannelEnvelope(role=role, max_abs_v=peak, max_abs_i=abs(comp), function=function,
                               v_start=levels[0], v_stop=levels[-1])
    return ChannelEnvelope(role=role, max_abs_v=abs(comp), max_abs_i=peak, function=function)


def _drive(source: Source, levels: list[float], comp: float) -> float:
    return abs(comp) if source == "V" else max(abs(v) for v in levels)


def _pick(roles: dict[str, RoleSpec], params: dict[str, Quantity], key: str) -> list[str]:
    return [name for name, role in roles.items() if setting_value(role, key, params) is not None]


class SmuSearchKind:
    """Linear/binary search (MM 14/15) and quasi-pulsed spot (MM 9) on SMUs (sim and visa code path)."""

    kind_id = "smu_search"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, estimate, FLEX preview and program (module docstring)."""
        source_name = self._check_roles(recipe, params)
        role = recipe.roles[source_name]
        method = _choice(setting_value(role, SEARCH_SETTING, params), tuple(METHOD_MODES),
                         f"{source_name}.{SEARCH_SETTING}")
        source: Source = SEARCH_FUNCTIONS[role.function]
        if method == "quasi_pulsed" and source != "V":
            raise CompileError(f"{source_name}: a quasi-pulsed source (BDV) forces voltage; use sweep_v")
        bound = {name: b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                 and b.channel is not None}
        integration = self._integration(params)
        comp_name = COMP_SETTINGS[source]
        start = _number(setting_value(role, "start", params, 0.0 if method == "quasi_pulsed" else None),
                        f"{source_name}.start")
        stop = _number(setting_value(role, "stop", params), f"{source_name}.stop")
        comp = _number(setting_value(role, comp_name, params), f"{source_name}.{comp_name}")
        channels: dict[int, ChannelEnvelope] = {}
        sourcing = 0.0
        if source_name in bound:
            channels[bound[source_name]] = _source_envelope(source_name, role.function, source, [start, stop], comp)
            sourcing += _drive(source, [start, stop], comp)
        sync_name = next((n for n, r in recipe.roles.items() if r.function in SYNC_FUNCTIONS), None)
        sync: SyncSource | None = None
        if sync_name is not None and sync_name in bound:
            if method == "quasi_pulsed":
                raise CompileError(f"{sync_name}: a quasi-pulsed measurement has no synchronous source")
            sync_role = recipe.roles[sync_name]
            if SYNC_FUNCTIONS[sync_role.function] != source:
                raise CompileError(f"{sync_name} must force what {source_name} forces (PG p132 (2-44))")
            polarity = _number(setting_value(sync_role, "polarity", params, 1), f"{sync_name}.polarity")
            if polarity not in (1.0, -1.0):
                raise CompileError(f"{sync_name}.polarity must be +1 or -1, got {polarity:g}")
            try:
                sync = SyncSource(channel=bound[sync_name], polarity=1 if polarity > 0 else -1,
                                  offset=_number(setting_value(sync_role, "offset", params, 0.0),
                                                 f"{sync_name}.offset"),
                                  comp=_number(setting_value(sync_role, comp_name, params),
                                               f"{sync_name}.{comp_name}"))
            except ValueError as exc:
                raise CompileError(f"{sync_name}: {exc}") from None
            levels = [sync.value(start), sync.value(stop)]
            channels[sync.channel] = _source_envelope(sync_name, sync_role.function, source, levels, sync.comp)
            sourcing += _drive(source, levels, sync.comp)
        biases, grounds = self._biases(recipe, params, bound, source_name, sync_name, channels)
        sourcing += sum(_drive(b.source, [b.level], b.comp) for b in biases)
        for name, channel in grounds:
            explicit = setting_value(recipe.roles[name], COMPLIANCE_SETTING, params)
            icomp = _number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else sourcing
            channels[channel] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(icomp),
                                                function=recipe.roles[name].function, v_start=0.0, v_stop=0.0)
            if icomp != 0:
                biases.append(BiasOutput(role=name, channel=channel, level=0.0, comp=icomp))
        envelope = CompiledEnvelope(channels=channels)
        if source_name not in bound:  # the search role is unbound: R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0))
        hold = _number(setting_value(role, "hold", params, 0.0), f"{source_name}.hold")
        delay = _number(setting_value(role, "delay", params, 0.0), f"{source_name}.delay")
        monitor_name, quantity = self._monitor(recipe, params, method, source_name, bound)
        search: SearchSetup | None = None
        quasi: QuasiPulseSetup | None = None
        try:
            if method == "quasi_pulsed":
                interval = _choice(setting_value(role, "interval", params, "short"), ("short", "long"),
                                   f"{source_name}.interval")
                quasi = QuasiPulseSetup(channel=bound[source_name], start=start, stop=stop, icomp=comp, hold=hold,
                                        delay=delay, interval=interval, measure=quantity,  # type: ignore[arg-type]
                                        measure_channel=None if monitor_name == source_name else bound[monitor_name])
            else:
                search = self._search_setup(recipe, method, source_name, params, bound, (start, stop, comp),
                                            monitor_name, quantity, sync, (hold, delay))
        except ValueError as exc:
            raise CompileError(f"invalid {method} search: {exc}") from None
        enable = [bound[name] for name in recipe.roles if name in bound]
        measured = {f"{monitor_name}_{quantity}"}
        if search is not None:
            measured.add(f"{source_name}_{source}")
        program = SearchProgram(
            integration=integration, enable=enable, biases=biases, method=method,  # type: ignore[arg-type]
            search=search, quasi=quasi, source_role=source_name, sync_role=sync_name if sync is not None else None,
            monitor_role=monitor_name, monitor_quantity=quantity,
            source_columns={b.column: b.level for b in biases
                            if recipe.roles[b.role].function in BIAS_FUNCTIONS and b.column not in measured},
            read_timeout_s=1.0)
        duration = self._duration(program)
        program = program.model_copy(update={"read_timeout_s": round(2.0 * duration + READ_TIMEOUT_MARGIN_S, 6)})
        points = search.points if search is not None else 1
        estimate = Estimate(points=points, duration_s=duration, max_segment_s=duration)
        try:
            preview = self.preview(program)  # every builder's syntax checks
        except ValueError as exc:
            raise CompileError(f"invalid {method} search: {exc}") from None
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=preview,
                                program=program.model_dump(mode="json"))

    def _check_roles(self, recipe: Recipe, params: dict[str, Quantity]) -> str:
        """The search role's name after the role-function checks (``CompileError``)."""
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in SEARCH_KIND_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(SEARCH_KIND_FUNCTIONS))}")
        sweeps = [n for n, r in recipe.roles.items() if r.function in SEARCH_FUNCTIONS]
        searching = _pick(recipe.roles, params, SEARCH_SETTING)
        if len(sweeps) != 1 or searching != sweeps:
            raise CompileError(f"{self.kind_id} needs exactly one sweep_v/sweep_i role with setting "
                               f"'{SEARCH_SETTING}' (the search source); recipe {recipe.id} has sweep roles {sweeps} "
                               f"and search settings on {searching}")
        syncs = [n for n, r in recipe.roles.items() if r.function in SYNC_FUNCTIONS]
        if len(syncs) > 1:
            raise CompileError(f"{self.kind_id}: at most one synchronous role, got {syncs}")
        return sweeps[0]

    @staticmethod
    def _biases(recipe: Recipe, params: dict[str, Quantity], bound: dict[str, int], source_name: str,
                sync_name: str | None, channels: dict[int, ChannelEnvelope]
                ) -> tuple[list[BiasOutput], list[tuple[str, int]]]:
        biases: list[BiasOutput] = []
        grounds: list[tuple[str, int]] = []
        for name, role in recipe.roles.items():
            if name not in bound or name in (source_name, sync_name):
                continue
            if role.function in BIAS_FUNCTIONS:
                source = BIAS_FUNCTIONS[role.function]
                level = _number(setting_value(role, LEVEL_SETTINGS[source], params),
                                f"{name}.{LEVEL_SETTINGS[source]}")
                comp = _number(setting_value(role, COMP_SETTINGS[source], params), f"{name}.{COMP_SETTINGS[source]}")
                biases.append(BiasOutput(role=name, channel=bound[name], source=source, level=level, comp=comp))
                channels[bound[name]] = _source_envelope(name, role.function, source, [level], comp)
            else:
                grounds.append((name, bound[name]))
        return biases, grounds

    def _monitor(self, recipe: Recipe, params: dict[str, Quantity], method: str, source_name: str,
                 bound: dict[str, int]) -> tuple[str, Source]:
        """``(role, quantity)`` of the monitor (linear/binary) or the measuring role (quasi-pulsed)."""
        if method == "quasi_pulsed":
            measuring = [n for n, r in recipe.roles.items() if r.measure and n in bound]
            if len(measuring) != 1:
                raise CompileError(f"{self.kind_id}: a quasi-pulsed measurement measures on exactly one channel; "
                                   f"bound roles that measure: {measuring}")
            name = measuring[0]
            return name, "V" if "V" in recipe.roles[name].measure else "I"
        targets = _pick(recipe.roles, params, TARGET_SETTING)
        if len(targets) != 1:
            raise CompileError(f"{self.kind_id}: a {method} search needs exactly one monitor role with setting "
                               f"'{TARGET_SETTING}', got {targets}")
        name = targets[0]
        role = recipe.roles[name]
        if name not in bound:
            raise CompileError(f"the search monitor {name} must be bound to an SMU")
        quantity: Source = "I" if role.function in VOLTAGE_FORCING else "V"
        if quantity not in role.measure:
            raise CompileError(f"{name} monitors the search on its compliance side ({quantity}, PG error 279) and "
                               f"must list {quantity} in measure")
        extra = sorted(n for n, r in recipe.roles.items() if r.measure and n != name and n in bound)
        if extra:
            raise CompileError(f"a search measures only its monitor ({name}); roles {extra} also measure")
        return name, quantity

    @staticmethod
    def _search_setup(recipe: Recipe, method: str, name: str, params: dict[str, Quantity], bound: dict[str, int],
                      levels: tuple[float, float, float], monitor_name: str, quantity: Source,
                      sync: SyncSource | None, timing: tuple[float, float]) -> SearchSetup:
        """The ``SearchSetup`` of a linear/binary search: the search role's settings (``step``, ``control``,
        ``post``, ``auto_abort``) and the monitor role's (``target``, ``judge``, ``limit``/``repeats``)."""
        role, monitor = recipe.roles[name], recipe.roles[monitor_name]
        start, stop, comp = levels
        source: Source = SEARCH_FUNCTIONS[role.function]
        post = _choice(setting_value(role, "post", params, "start"), ("start", "stop", "last"), f"{name}.post")
        abort = _flag(setting_value(role, "auto_abort", params, True), f"{name}.auto_abort")
        magnitude = _number(setting_value(monitor, TARGET_SETTING, params), f"{monitor_name}.{TARGET_SETTING}")
        scale = _number(setting_value(monitor, TARGET_SCALE_SETTING, params, 1.0),
                        f"{monitor_name}.{TARGET_SCALE_SETTING}")
        if magnitude <= 0 or scale <= 0:
            raise CompileError(f"{monitor_name}: the search target is a magnitude (> 0, times "
                               f"{TARGET_SCALE_SETTING} > 0); its polarity follows the drive")
        target = _target_sign(recipe, params, name, monitor_name, start, stop, sync) * magnitude * scale
        common: dict[str, Any] = {
            "source": SearchSource(channel=bound[name], source=source, start=start, stop=stop, comp=comp),
            "monitor": SearchMonitor(channel=bound[monitor_name], quantity=quantity, target=target),
            "sync": sync, "hold": timing[0], "delay": timing[1], "auto_abort": abort, "post": post}
        if method == "linear":
            step = abs(_number(setting_value(role, "step", params), f"{name}.step"))
            judge = setting_value(monitor, "judge", params)
            if judge is not None:
                _choice(judge, ("above", "below"), f"{monitor_name}.judge")
            return SearchSetup(mode=flex.LINEAR_SEARCH_MODE, step=math.copysign(step, stop - start), judge=judge,
                               **common)
        control = _choice(setting_value(role, "control", params, "cautious"), ("normal", "cautious"),
                          f"{name}.control")
        limit = setting_value(monitor, "limit", params)
        limit_rel = setting_value(monitor, "limit_rel", params)
        repeats = setting_value(monitor, "repeats", params)
        if sum(v is not None for v in (limit, limit_rel, repeats)) != 1:
            raise CompileError(f"{monitor_name}: a binary search needs exactly one of 'limit' (stop within target "
                               "+/- limit), 'limit_rel' (a fraction of |target|) and 'repeats' (1-16 output "
                               "changes)")
        if repeats is not None:
            count = _number(repeats, f"{monitor_name}.repeats")
            if not count.is_integer():
                raise CompileError(f"{monitor_name}.repeats must be an integer, got {count:g}")
            repeats = int(count)
        elif limit_rel is not None:
            limit = _number(limit_rel, f"{monitor_name}.limit_rel") * abs(target)
        else:
            limit = _number(limit, f"{monitor_name}.limit")
        return SearchSetup(mode=flex.BINARY_SEARCH_MODE, control=control, limit=limit, repeats=repeats, **common)

    @staticmethod
    def _integration(params: dict[str, Quantity]) -> Integration:
        preset = params.get(INTEGRATION_PARAM)
        name = DEFAULT_PRESET if preset is None else preset.value
        if not isinstance(name, str) or name not in INTEGRATION_PRESETS:
            raise CompileError(f"{INTEGRATION_PARAM} must be one of {sorted(INTEGRATION_PRESETS)}, got {name!r}")
        return INTEGRATION_PRESETS[name]

    @staticmethod
    def _duration(program: SearchProgram) -> float:
        per_measurement = measurement_time_s(program.integration)
        if program.search is not None:
            setup = program.search
            total = setup.hold + setup.points * (setup.delay + per_measurement)
        else:
            assert program.quasi is not None
            quasi = program.quasi
            total = quasi.hold + abs(quasi.stop - quasi.start) / QUASI_RAMP_V_PER_S + quasi.delay + per_measurement
        return round(SETUP_OVERHEAD_S + total, 6)

    @staticmethod
    def preview(program: SearchProgram) -> list[str]:
        """The writes ``acquire`` sends, in order (``ERRX?`` drains and queries are not listed)."""
        integration = program.integration
        adc = ADC_TYPE_CODES[integration.adc]
        lines = [flex.fmt(*program.data_format), flex.aad(program.monitor_channel, adc),
                 flex.ait(adc, ADC_MODE_CODES[integration.mode], integration.n), flex.cn(program.enable)]
        lines += [bias_command(b) for b in program.biases]
        lines += program.search.commands() if program.search is not None else program.quasi.commands()  # type: ignore[union-attr]
        lines.append(flex.XE)
        return lines

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = SearchProgram.model_validate(plan.program)
        driver = tx.driver
        driver.set_format(*program.data_format)
        driver.apply_integration(program.integration, [program.monitor_channel])
        driver.enable(program.enable)
        drain_or_raise(tx, "enabling the outputs")
        tx.mark("outputs enabled")
        tx.lop_positive_control(program.enable)
        for bias in program.biases:
            force_bias(tx, bias)
        if program.search is not None:
            driver.search_setup(program.search)
        else:
            assert program.quasi is not None
            driver.quasi_pulse_setup(program.quasi)
        drain_or_raise(tx, f"the {program.method} search setup")
        tx.mark("configured")
        block = driver.execute_and_read(expected_points=program.expected_points, timeout_s=program.read_timeout_s)
        tx.mark("data read")
        return RawAcquisition(blocks=[block], kind_result=search_result(program, block))

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """The one-row table (module docstring).

        Raises:
            ValueError: If there is not exactly one block or it does not hold the programmed elements.
        """
        program = SearchProgram.model_validate(plan.program)
        if len(raw.blocks) != 1:
            raise ValueError(f"{self.kind_id} expects one data block, got {len(raw.blocks)}")
        return pd.DataFrame(search_rows(program, raw.blocks[0]))


def _target_sign(recipe: Recipe, params: dict[str, Quantity], source_name: str, monitor_name: str, start: float,
                 stop: float, sync: SyncSource | None) -> float:
    """Polarity of the search target (module docstring): what the monitored quantity of a passive device follows."""
    ramp = 1.0 if stop >= start else -1.0
    if monitor_name == source_name:
        return ramp
    role = recipe.roles[monitor_name]
    if role.function in SYNC_FUNCTIONS and sync is not None:
        return 1.0 if max(sync.value(start), sync.value(stop), key=abs) >= 0 else -1.0
    if role.function in BIAS_FUNCTIONS:
        level = setting_value(role, LEVEL_SETTINGS[BIAS_FUNCTIONS[role.function]], params, 0.0)
        return -1.0 if isinstance(level, int | float) and level < 0 else 1.0
    return -ramp  # ground or measure_only: the return current


def search_result(program: SearchProgram, block: RawBlock) -> dict[str, Any]:
    """``kind_result`` of one search read (module docstring)."""
    result: dict[str, Any] = {"measurement_mode": program.mode, "search": program.method,
                              "source_column": f"{program.source_role}_{program.source_quantity}",
                              "result_column": program.result_column, "monitor_column": program.monitor_column}
    if program.search is not None:
        data = parse_search(block.points, source_channel=program.search.source.channel,
                            source_quantity=program.source_quantity, monitor_channel=program.monitor_channel,
                            monitor_quantity=program.monitor_quantity)
        result |= {"search_status": data.status, "found": data.found, "target": program.search.monitor.target,
                   "start": program.search.source.start, "stop": program.search.source.stop}
        if program.search.mode == flex.LINEAR_SEARCH_MODE and program.search.step is not None:
            result["step"] = program.search.step
    else:
        assert program.quasi is not None
        point = parse_quasi_pulsed(block.points, channel=program.monitor_channel, quantity=program.monitor_quantity)
        status = str(point.status.value)
        result |= {"search_status": status, "found": status == "C", "start": program.quasi.start,
                   "stop": program.quasi.stop, "icomp": program.quasi.icomp}
    return result


def search_rows(program: SearchProgram, block: RawBlock) -> list[dict[str, object]]:
    """The table row of one search read (module docstring).

    Raises:
        ValueError: If the block does not hold the programmed elements (``FlexParseError`` is a ``ValueError``).
    """
    row: dict[str, object] = {"step": 0}
    if program.search is not None:
        data = parse_search(block.points, source_channel=program.search.source.channel,
                            source_quantity=program.source_quantity, monitor_channel=program.monitor_channel,
                            monitor_quantity=program.monitor_quantity)
        result = program.result_column
        row[result] = data.search.value
        row[f"{result}_status"] = data.status
        assert data.sense is not None
        row[program.monitor_column] = data.sense.value
        row[f"{program.monitor_column}_status"] = str(data.sense.status.value)
        if program.sync_role is not None and program.search.sync is not None:
            row[f"{program.sync_role}_{program.source_quantity}"] = program.search.sync.value(data.search.value)
    else:
        assert program.quasi is not None
        point = parse_quasi_pulsed(block.points, channel=program.monitor_channel, quantity=program.monitor_quantity)
        row[program.monitor_column] = point.value
        row[f"{program.monitor_column}_status"] = str(point.status.value)
    row.update(program.source_columns)
    return [row]


__all__ = ["SearchProgram", "SmuSearchKind", "search_result", "search_rows"]
