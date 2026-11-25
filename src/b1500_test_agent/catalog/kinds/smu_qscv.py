"""``smu_qscv``: SMU quasi-static C-V, ``MM 13`` with leakage compensation and the ``QSZ`` capacitance offset (blueprint
v2 2.7, WP8.5): one SMU sweeps the gate in small steps and integrates the charge each ``cvoltage`` transition moves;
the instrument returns ``C = (I - Leak) cinteg / (V - V0)`` per step (PG p115-117 (2-27 to 2-29)). The low-frequency
(quasi-static) curve: interface traps and the inversion layer follow, so with a high-frequency C-V of the same device
it gives Dit (``dit_high_low``).

Roles (recipe ``roles``, bound through the pin map):

- exactly one ``sweep_v`` role, the ``QSV`` source, which also measures (``measure: [I]``; ``MM 13,ch``). Settings:
  ``start``, ``stop`` (V), ``step`` (V, a magnitude; ``|stop - start|`` a whole number of steps, 2-1002 of them),
  ``cvoltage`` (V, default the step, at most the step), ``icomp`` (A), ``sweep`` (``single``|``double``), ``hold``,
  ``delay1``, ``delay2``, ``cinteg``, ``linteg`` (s; integration times rounded to whole line periods at 50 Hz),
  ``irange`` (A: the ``QSR`` range 10 pA .. 1 uA; it must hold the charge current ``C cvoltage / cinteg`` plus the
  leakage, and the module must have it: an MPSMU from 1 nA), ``leakage`` (``compensate`` = ``QSL 1,1``, ``data`` =
  ``QSL 1,0``, ``off`` = ``QSL 0,0``), ``operation`` (``normal``|``compatible``, ``QSC``), ``auto_abort`` (bool,
  ``QSM``), ``post`` (``start``|``stop``) and ``offset``: ``off`` (``QSZ 0``), ``cancel`` (``QSZ 1``: subtract the
  offset the last offset measurement stored in the instrument) or ``measure`` (the run is the offset measurement:
  the setup, then ``QSZ 2`` with the terminals open at the device end; the program's ``setup`` prompt makes R-ALWAYS-01
  ask for ``physical_setup``);
- ``ground`` and ``measure_only`` roles: SMUs at 0 V (``DV``; compliance ``icomp`` or the source's) or the GNDU;
  they do not measure.

SCUU (one landing for I-V and C-V, PG p520 (4-202)): a role whose pin-map terminal is an SCUU output reaches it through
the SCUU's SMU input. The plan then routes that SCUU's outputs (used ones to ``smu``, the others ``open``; one ``SSP``
path 1, 2 or 3) in phase ``measure`` and back to the switch's ``rest`` state in phase ``rest`` when that differs;
the ``SSP`` switches those SMUs on (they are never in the ``CN`` list: error 323) and the transaction cleanup restores
and verifies the rest state on every exit (WP9.2).

Compile (pure): envelope (the source |V| up to its larger end with Icomp and ``v_start``/``v_stop``; 0 V grounds with
their compliance), the SCUU routes, the estimate (1 s setup; hold + per step delay1, leakage integrations, cinteg,
delay2; ``max_segment_s`` = the whole sweep: one ``XE`` that only ``AB`` interrupts, so a sweep longer than
``segment_max_s`` cannot run async), the exact FLEX preview and the program.

Acquire (one transaction, guarded driver only): ``FMT 1,1``, ``TSC 0``, the SCUU ``measure`` routes, ``CN`` of the
other channels, ``ERRX?`` drain, on hardware the ``LOP?`` positive control, ``DV`` per ground SMU, the QSCV setup
(``qscv_setup``: ``MM 13``, ``QSC``, ``QSO 0``, ``QSL``, ``QSM``, ``QSR``, ``QST``, ``QSV``, ``QSZ``), ``ERRX?``
drain, then ``XE`` and one read (or ``QSZ 2`` and its one datum), an ``ERRX?`` drain (error 242: the automatic abort
stopped the sweep, recorded; any other error fails the run) and the ``rest`` routes. Cleanup is the transaction's.

Table (``data.csv`` contract): one row per measured step, ``step``, ``segment`` (``fwd``/``rev`` of a double sweep),
``dc_v`` (the step voltage the source reports), ``<role>_Cp`` (the quasi-static capacitance, F; leakage-compensated
with ``leakage: compensate``) with its status and, unless ``leakage: off``, ``<role>_I`` (the leakage current, A) with
its status. An offset measurement: one row, ``<role>_Cp`` = the offset. ``kind_result``: ``measurement_mode`` 13,
``points``, ``offset`` mode, ``offset_f`` (offset run), ``leakage_max_a`` (the largest |leakage| of the sweep, unless
``leakage: off``; WP8.6), ``aborted`` (error 242) and the column names.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_staircase import (
    READ_TIMEOUT_MARGIN_S,
    SETUP_OVERHEAD_S,
    AcquisitionError,
    BiasOutput,
    bias_command,
    drain_or_raise,
    force_bias,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import QscvSetup, QscvSource, RawBlock
from b1500_test_agent.driver.modules import module_spec
from b1500_test_agent.driver.qscv import parse_qscv, parse_qscv_offset
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import ChannelBinding, ChannelEnvelope, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route, SwitchSpec
from b1500_test_agent.models.station import StationProfile, scuu_side
from b1500_test_agent.rules.builtin import COMPLIANCE_SETTING

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

MEASURE_PHASE = "measure"
REST_PHASE = "rest"

QSCV_FUNCTIONS = frozenset({"sweep_v", "ground", "measure_only"})
"""Role functions this kind executes."""

LINE_HZ = 50.0
"""Line frequency the integration times are rounded to (ATV-31; the instrument rounds to ``n / f_line``)."""

LEAKAGE_MODES: dict[str, tuple[bool, bool]] = {"compensate": (True, True), "data": (True, False),
                                               "off": (False, False)}
"""``leakage`` setting -> ``QSL data,compen``."""

OFFSET_SETUP_PROMPT = ("open the measurement terminals at the device end (lift the probes from the pads) for the "
                       "QSCV offset measurement, then land them again before the next QSCV run")
"""The probe state an offset measurement needs (R-ALWAYS-01 shows it with ``physical_setup``)."""

ABORT_ERROR = 242
"""``QSCV measurement was aborted`` (PG p580 (5-8)): the automatic abort stopped the sweep."""


class QscvProgram(StrictModel):
    """The compiled program stored in ``PlanRecord.program`` (hashed) and executed by ``acquire``. ``setup`` is the
    probe-state prompt of an offset measurement (the key R-ALWAYS-01 reads, as for the correction kinds)."""

    qscv: QscvSetup
    source_role: str
    enable: list[Channel] = Field(default_factory=list)
    """Channels switched on with ``CN`` (not the SCUU's SMUs: ``SSP`` switches those)."""
    switched: list[Channel] = Field(default_factory=list)
    """Every SMU channel the run switches on (``CN`` and ``SSP``), for the ``LOP?`` positive control."""
    biases: list[BiasOutput] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    rest_routes: list[Route] = Field(default_factory=list)
    ssp: list[tuple[int, int]] = Field(default_factory=list)
    """``(MFCMU channel, SSP path)`` of the ``measure`` routes, per SCUU (preview)."""
    ssp_rest: list[tuple[int, int]] = Field(default_factory=list)
    """``(MFCMU channel, SSP path)`` of the ``rest`` routes (empty when they equal the ``measure`` routes)."""
    read_timeout_s: float = Field(gt=0)
    setup: str | None = None

    @property
    def offset_run(self) -> bool:
        """True when the run is the ``QSZ 2`` offset measurement."""
        return self.qscv.offset == "measure"

    @property
    def capacitance_column(self) -> str:
        return f"{self.source_role}_Cp"

    @property
    def leakage_column(self) -> str | None:
        return f"{self.source_role}_I" if self.qscv.leakage_data and not self.offset_run else None


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


def _line_rounded(seconds: float, what: str, limits: tuple[int, int]) -> float:
    n = math.floor(seconds * LINE_HZ + 0.5)
    if not limits[0] <= n <= limits[1]:
        raise CompileError(f"{what} must be {limits[0] / LINE_HZ:g} to {limits[1] / LINE_HZ:g} s (whole line periods "
                           f"at {LINE_HZ:g} Hz, PG p496-497 (4-178 to 4-179)), got {seconds:g} s")
    return n / LINE_HZ


def _scuu_routes(switch: SwitchSpec, used: set[str]) -> tuple[list[Route], list[Route], tuple[int, int, int]]:
    """The ``measure`` routes (used outputs -> ``smu``, the other declared outputs -> ``open``), the ``rest`` routes
    and ``(MFCMU channel, measure SSP path, rest SSP path)`` of one SCUU (PG p520 (4-202) Table 4-30)."""
    measure = sorted((Route(switch=switch.id, output=o, state="smu" if o in used else "open") for o in switch.ports),
                     key=Route.sort_key)
    rest = sorted((Route(switch=switch.id, output=o, state=switch.rest) for o in switch.ports), key=Route.sort_key)
    cmus = {port.inputs.get("cmu") for port in switch.ports.values()}
    cmu = next(iter(cmus)) if len(cmus) == 1 else None
    if cmu is None:
        raise CompileError(f"smu_qscv: {switch.id} has no single MFCMU input recorded (station profile)")
    side = {output: scuu_side(int(cmu), port.index) for output, port in switch.ports.items()}

    def path(routes: list[Route]) -> int:
        states = {side[r.output]: r.state for r in routes}
        pair = (states.get("H", "open"), states.get("L", "open"))
        found = next((p for p, given in flex.SSP_PATHS.items() if given == pair), None)
        if found is None:
            raise CompileError(f"smu_qscv: {switch.id} cannot connect {pair} (output 1, output 2) with one SSP path")
        return found

    return measure, rest, (int(cmu), path(measure), path(rest))


def smu_scuu_path(recipe: Recipe, binding: ChannelBinding, station: StationProfile, *,
                  kind_id: str) -> tuple[list[Route], list[Route], frozenset[int], list[tuple[int, int, int]]]:
    """The SCUU routes of the SMU roles bound through SCUU outputs (module docstring): ``(measure, rest, modules,
    paths)``; ``modules`` are the SMU channels the SCUUs feed (switched by ``SSP``, never ``CN``), ``paths`` the
    ``(MFCMU channel, measure SSP path, rest SSP path)`` per SCUU. Roles through any other switch kind raise
    ``CompileError`` (selectors and ASUs are not routed by this kind); an undeclared switch is left to R-PIN-01."""
    used: dict[str, set[str]] = {}
    for name in recipe.roles:
        bound = binding.roles.get(name)
        if bound is None or bound.via is None:
            continue
        switch = station.switch(bound.via.switch)
        if switch is None:
            continue
        if switch.kind != "scuu":
            raise CompileError(f"{kind_id}: role {name} reaches its terminal through {switch.id} ({switch.kind}); this "
                               "kind routes SMU roles only through an SCUU")
        used.setdefault(switch.id, set()).add(bound.via.output)
    measure: list[Route] = []
    rest: list[Route] = []
    modules: set[int] = set()
    paths: list[tuple[int, int, int]] = []
    for switch_id, outputs in sorted(used.items()):
        switch = station.switch(switch_id)
        assert switch is not None
        routes, back, ssp = _scuu_routes(switch, outputs)
        measure += routes
        rest += back
        paths.append(ssp)
        modules |= {int(port.inputs["smu"]) for port in switch.ports.values()  # type: ignore[arg-type]
                    if port.inputs.get("smu") is not None}
    return measure, rest, frozenset(modules), paths


def _norm(channel: int) -> int:
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


class SmuQscvKind:
    """Quasi-static C-V on an SMU (MM 13; sim and visa code path)."""

    kind_id = "smu_qscv"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # compile -----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """Envelope, routes, estimate, FLEX preview and program (module docstring)."""
        source_name = self._check_roles(recipe)
        role = recipe.roles[source_name]
        bound = {name: b.channel for name in recipe.roles if (b := binding.roles.get(name)) is not None
                 and b.channel is not None}
        start = _number(setting_value(role, "start", params), f"{source_name}.start")
        stop = _number(setting_value(role, "stop", params), f"{source_name}.stop")
        icomp = _number(setting_value(role, COMPLIANCE_SETTING, params), f"{source_name}.{COMPLIANCE_SETTING}")
        channels: dict[int, ChannelEnvelope] = {}
        if source_name in bound:
            channels[bound[source_name]] = ChannelEnvelope(role=source_name, max_abs_v=max(abs(start), abs(stop)),
                                                           max_abs_i=abs(icomp), function="sweep_v", v_start=start,
                                                           v_stop=stop)
        routes, rest, scuu_modules, ssp = smu_scuu_path(recipe, binding, station, kind_id=self.kind_id)
        biases: list[BiasOutput] = []
        for name, spec in recipe.roles.items():
            if name == source_name or name not in bound:
                continue
            explicit = setting_value(spec, COMPLIANCE_SETTING, params)
            comp = _number(explicit, f"{name}.{COMPLIANCE_SETTING}") if explicit is not None else abs(icomp)
            channels[bound[name]] = ChannelEnvelope(role=name, max_abs_v=0.0, max_abs_i=abs(comp),
                                                    function=spec.function, v_start=0.0, v_stop=0.0)
            biases.append(BiasOutput(role=name, channel=bound[name], level=0.0, comp=comp))
        envelope = CompiledEnvelope(channels=channels, routes=frozenset(routes))
        phases = {MEASURE_PHASE: routes, **({REST_PHASE: rest} if rest != routes else {})} if routes else {}
        if source_name not in bound:  # the source is unbound: R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=0, duration_s=0.0),
                                    routes_by_phase=phases)
        setup = self._setup(recipe, params, source_name, bound[source_name], (start, stop, icomp), station)
        scuu = {_norm(ch) for ch in scuu_modules}
        enable = [bound[n] for n in recipe.roles if n in bound and _norm(bound[n]) not in scuu]
        switched = [bound[n] for n in recipe.roles if n in bound]
        duration = round(SETUP_OVERHEAD_S + (setup.offset_duration_s() if setup.offset == "measure"
                                             else setup.duration_s()), 6)
        differs = rest != routes
        program = QscvProgram(qscv=setup, source_role=source_name, enable=enable, switched=switched, biases=biases,
                              routes=routes, rest_routes=rest if differs else [],
                              ssp=[(cmu, path) for cmu, path, _ in ssp],
                              ssp_rest=[(cmu, path) for cmu, _, path in ssp] if differs else [],
                              read_timeout_s=round(2.0 * duration + READ_TIMEOUT_MARGIN_S, 6),
                              setup=OFFSET_SETUP_PROMPT if setup.offset == "measure" else None)
        points = 1 if program.offset_run else setup.points
        estimate = Estimate(points=points, duration_s=duration, max_segment_s=duration)
        try:
            preview = self.preview(program)
        except ValueError as exc:
            raise CompileError(f"invalid QSCV setup: {exc}") from None
        return CompiledKindPlan(envelope=envelope, estimate=estimate, flex_preview=preview,
                                program=program.model_dump(mode="json"), routes_by_phase=phases)

    def _check_roles(self, recipe: Recipe) -> str:
        """The source role's name after the role checks (``CompileError``)."""
        other = sorted(f"{name} ({role.function})" for name, role in recipe.roles.items()
                       if role.function not in QSCV_FUNCTIONS)
        if other:
            raise CompileError(f"{self.kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                               f"{', '.join(sorted(QSCV_FUNCTIONS))}")
        sweeps = [name for name, role in recipe.roles.items() if role.function == "sweep_v"]
        if len(sweeps) != 1:
            raise CompileError(f"{self.kind_id} needs exactly one sweep_v role (the QSV source), got {sweeps}")
        if "I" not in recipe.roles[sweeps[0]].measure:
            raise CompileError(f"{sweeps[0]}: the QSV source measures the charge current (MM 13,ch) and must list I in "
                               "measure")
        extra = sorted(name for name, role in recipe.roles.items() if role.measure and name != sweeps[0])
        if extra:
            raise CompileError(f"a QSCV measures only on its source ({sweeps[0]}); roles {extra} also measure")
        return sweeps[0]

    @staticmethod
    def _setup(recipe: Recipe, params: dict[str, Quantity], name: str, channel: int,
               levels: tuple[float, float, float], station: StationProfile) -> QscvSetup:
        role = recipe.roles[name]
        start, stop, icomp = levels

        def value(key: str, default: object = None) -> object:
            return setting_value(role, key, params, default)

        step = abs(_number(value("step"), f"{name}.step"))
        cvoltage = value("cvoltage")
        sweep = _choice(value("sweep", "single"), ("single", "double"), f"{name}.sweep")
        leakage = _choice(value("leakage", "compensate"), tuple(LEAKAGE_MODES), f"{name}.leakage")
        data, compensation = LEAKAGE_MODES[leakage]
        offset = _choice(value("offset", "off"), ("off", "cancel", "measure"), f"{name}.offset")
        irange = _number(value("irange", 1e-9), f"{name}.irange")
        code = next((c for c, full in flex.QSCV_RANGE_CODES.items() if math.isclose(full, irange, rel_tol=1e-9)),
                    None)
        if code is None:
            raise CompileError(f"{name}.irange must be one of {sorted(flex.QSCV_RANGE_CODES.values())} A (QSR), got "
                               f"{irange:g}")
        module = station.module_for_channel(channel)
        if module is not None:
            ranges = [r for r in module_spec(module.model).i_ranges if not r.requires_asu and not r.pulse_only]
            if not any(math.isclose(r.full_scale, irange, rel_tol=1e-9) for r in ranges):
                low = min((r.full_scale for r in ranges), default=math.inf)
                raise CompileError(f"{name}.irange {irange:g} A: a {module.type} has no such current range (QSR); its "
                                   f"smallest is {low:g} A")
        try:
            source = QscvSource(channel=channel, start=start, stop=stop, step=step,
                                cvoltage=None if cvoltage is None else _number(cvoltage, f"{name}.cvoltage"),
                                icomp=icomp, double=sweep == "double")
            return QscvSetup(
                source=source, cinteg=_line_rounded(_number(value("cinteg", 0.1), f"{name}.cinteg"),
                                                    f"{name}.cinteg", (1, 20000)),
                linteg=_line_rounded(_number(value("linteg", 0.1), f"{name}.linteg"), f"{name}.linteg", (1, 100)),
                hold=_number(value("hold", 0.0), f"{name}.hold"),
                delay1=_number(value("delay1", 0.0), f"{name}.delay1"),
                delay2=_number(value("delay2", 0.0), f"{name}.delay2"),
                leakage_data=data, compensation=compensation,
                operation=_choice(value("operation", "normal"), ("normal", "compatible"),  # type: ignore[arg-type]
                                  f"{name}.operation"),
                range_code=code, auto_abort=_flag(value("auto_abort", True), f"{name}.auto_abort"),
                post=_choice(value("post", "start"), ("start", "stop"), f"{name}.post"),  # type: ignore[arg-type]
                offset=offset)  # type: ignore[arg-type]
        except ValueError as exc:
            raise CompileError(f"invalid QSCV sweep on {name}: {exc}") from None

    @staticmethod
    def preview(program: QscvProgram) -> list[str]:
        """The writes ``acquire`` sends, in order (``ERRX?`` drains, route read-backs and queries are not listed; the
        ``SSP`` lines are the SCUU phases)."""
        lines = [flex.fmt(1, 1), flex.tsc(False)]
        lines += [flex.ssp(cmu, path) for cmu, path in program.ssp]
        if program.enable:
            lines.append(flex.cn(program.enable))
        lines += [bias_command(b) for b in program.biases]
        lines += program.qscv.commands()
        lines.append(flex.qsz(flex.QSZ_MEASURE) if program.offset_run else flex.XE)
        lines += [flex.ssp(cmu, path) for cmu, path in program.ssp_rest]
        return lines

    # acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        """Execute the stored program (module docstring); every source command passes the guard."""
        if not plan.program:
            raise CompileError(f"plan {plan.plan_id} has no compiled {self.kind_id} program")
        program = QscvProgram.model_validate(plan.program)
        driver = tx.driver
        setup = program.qscv
        driver.set_format(1, 1)
        driver.set_time_stamp(False)
        if program.routes:
            tx.apply_routes(program.routes, phase=MEASURE_PHASE)
        if program.enable:
            driver.enable(program.enable)
        drain_or_raise(tx, "switching the outputs on")
        tx.mark("outputs enabled")
        tx.lop_positive_control(program.switched)
        for bias in program.biases:
            force_bias(tx, bias)
        driver.qscv_setup(setup)
        drain_or_raise(tx, "the QSCV setup")
        tx.mark("configured")
        if program.offset_run:
            block = driver.measure_qscv_offset(timeout_s=program.read_timeout_s)
        else:
            block = driver.execute_and_read(expected_points=setup.points * setup.elements_per_step,
                                            timeout_s=program.read_timeout_s)
        tx.mark("data read")
        errors = driver.errors(drain=True)
        unexpected = [e for e in errors if e.code != ABORT_ERROR]
        if unexpected:
            listed = ", ".join(f"{e.code} {e.message}".strip() for e in unexpected)
            raise AcquisitionError(f"instrument reported errors during the QSCV measurement ({listed})", unexpected)
        if program.rest_routes:
            tx.apply_routes(program.rest_routes, phase=REST_PHASE)
        result = qscv_result(program, block)
        result["aborted"] = any(e.code == ABORT_ERROR for e in errors)
        return RawAcquisition(blocks=[block], kind_result=result)

    # table -------------------------------------------------------------------------------------------------------

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame:
        """The table (module docstring).

        Raises:
            ValueError: If there is not exactly one block or it does not hold the programmed elements.
        """
        program = QscvProgram.model_validate(plan.program)
        if len(raw.blocks) != 1:
            raise ValueError(f"{self.kind_id} expects one data block, got {len(raw.blocks)}")
        return pd.DataFrame(qscv_rows(program, raw.blocks[0]))


def qscv_result(program: QscvProgram, block: RawBlock) -> dict[str, Any]:
    """``kind_result`` of one QSCV read (module docstring)."""
    setup = program.qscv
    result: dict[str, Any] = {"measurement_mode": flex.QSCV_MODE, "offset": setup.offset,
                              "capacitance_column": program.capacitance_column,
                              "leakage_column": program.leakage_column, "source_role": program.source_role,
                              "start": setup.source.start, "stop": setup.source.stop,
                              "cvoltage": setup.source.measuring_voltage}
    if program.offset_run:
        point = parse_qscv_offset(block.points, channel=setup.measured_channel)
        result |= {"points": 1, "offset_f": point.value, "offset_status": str(point.status.value)}
    else:
        steps = parse_qscv(block.points, channel=setup.measured_channel, source_channel=setup.source.channel,
                           leakage=setup.leakage_data, steps=setup.points)
        result["points"] = len(steps)
        leaks = [abs(s.leakage.value) for s in steps if s.leakage is not None and not s.leakage.invalid]
        if leaks:  # the largest leakage of the sweep (bring-up L6 QSCV leakage check; WP8.6)
            result["leakage_max_a"] = max(leaks)
    return result


def qscv_rows(program: QscvProgram, block: RawBlock) -> list[dict[str, object]]:
    """The table rows of one QSCV read (module docstring).

    Raises:
        ValueError: If the block does not hold the programmed elements (``FlexParseError`` is a ``ValueError``).
    """
    setup = program.qscv
    if program.offset_run:
        point = parse_qscv_offset(block.points, channel=setup.measured_channel)
        return [{"step": 0, program.capacitance_column: point.value,
                 f"{program.capacitance_column}_status": str(point.status.value)}]
    steps = parse_qscv(block.points, channel=setup.measured_channel, source_channel=setup.source.channel,
                       leakage=setup.leakage_data, steps=setup.points)
    forward = setup.source.steps
    rows: list[dict[str, object]] = []
    for index, item in enumerate(steps):
        row: dict[str, object] = {"step": index}
        if setup.source.double:
            row["segment"] = "fwd" if index < forward else "rev"
        row["dc_v"] = item.source.value
        row[program.capacitance_column] = item.capacitance.value
        row[f"{program.capacitance_column}_status"] = item.status
        if item.leakage is not None and program.leakage_column is not None:
            row[program.leakage_column] = item.leakage.value
            row[f"{program.leakage_column}_status"] = str(item.leakage.status.value)
        rows.append(row)
    return rows


__all__ = ["OFFSET_SETUP_PROMPT", "QscvProgram", "SmuQscvKind", "qscv_result", "qscv_rows", "smu_scuu_path"]
