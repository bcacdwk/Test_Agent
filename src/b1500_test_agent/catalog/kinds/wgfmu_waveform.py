"""``wgfmu_waveform``: one WGFMU ``WaveformProgram`` per run, optionally with FLEX SMU bias around it (blueprint v2
2.7, 2.7.1; WP10.4). Recipes ``wgfmu.pulsed_iv``, ``wgfmu.fast_iv``, ``wgfmu.pulse_train``, ``wgfmu.custom_waveform``
and ``wgfmu.dc_spot``; ``wgfmu.rtn`` and ``wgfmu.lfn`` (builder ``dc_sample``, WP10.5).

**Builder.** The recipe names its builder with the single-choice enum parameter ``builder`` (``WAVEFORM_BUILDERS``,
``catalog/waveforms.py``); the builder's inputs come from role settings (``$param`` references) and recipe
parameters read by name, never from a step language:

- ``pulsed_iv``: the WGFMU role with settings ``start``/``stop``/``points`` pulses from ``base`` (default 0) to each
  of ``points`` linear levels; parameters ``width``, ``period``, ``edge``, ``settle``;
- ``pulse_train``: the WGFMU role with setting ``peak`` pulses ``count`` times from ``base``; parameters ``width``,
  ``period``, ``edge``, ``settle``, ``count``, ``samples`` (points per pulse);
- ``fast_iv_ramp``: the WGFMU role with settings ``start``/``stop`` ramps; parameters ``ramp``, ``interval``,
  ``edge``, ``settle``, ``double`` (bool), ``cycles``;
- ``dc_spot``: each WGFMU role forces setting ``values`` (a list, at most one role) or ``v`` in DC mode; parameters
  ``samples`` (readings per step) and ``settle`` (s after each step);
- ``dc_sample``: each WGFMU role holds setting ``v``; parameters ``points``, ``interval``, ``average`` (default: the
  interval), ``edge`` and ``settle`` (s at the bias before the sampling starts; WP10.5);
- ``table``: each WGFMU role's setting ``wave`` references a ``file`` parameter (its waveform CSV); the ``file``
  parameter ``events`` holds the measurement rows (lab layout, ``catalog/waveforms.py``). The kind reads the bytes
  through the planner's ``ParamFiles`` (``read_param_file``: sha256 re-verified; ``reads_files``).
- ``fast_bti`` (WP10.7): the whole fast-BTI schedule of kind ``stress_measure``'s WGFMU path (settings ``stress``,
  ``recovery``, the swept role's ``start``/``stop``/``points``, ``v``; the schedule and sense-timing parameters;
  ``stress_wgfmu.build``) in ONE execution: a raw view (``event`` = ``sense``/``monitor``) without that kind's
  per-read checkpoints; recipe ``wgfmu.fast_bti`` runs it in ``stress_measure``.
- ``pund`` (WP10.6, ``fecap.pund``): the WGFMU role with setting ``amplitude`` (V) outputs the PUND sequence (preset,
  P, U, N, D: ``catalog/ferro_waveforms.py``), every other WGFMU role holds 0 V; parameters ``rise``, ``plateau``,
  ``delay``, ``interval``, ``preset`` (``pulse_wgfmu.pund_timing``); ``event`` = ``P``/``U``/``N``/``D``.
- ``program_read`` (WP10.6, ``fefet.fast_program_read``): the WGFMU role with setting ``program`` and/or ``erase``
  (``width``, ``erase_width``, ``base``, ``lead``, ``trail``) pulses and reads with its ``start``/``stop``/``points``
  staircase; every other WGFMU role reads at ``v`` and pulses at ``pulse_bias``; parameters ``sequence``, ``cycles``,
  ``count``, ``period``, ``initial_read``, ``read_edge``, ``read_width``, ``read_settle``
  (``pulse_wgfmu.build_waveform``): erase, read, program, read in ONE execution, the reads microseconds after the
  pulses; ``cycle`` = 0 for the reference read, else the cycle; ``phase`` = ``read``, ``erase`` or ``program``.

Every other WGFMU role of a pulse/ramp builder holds setting ``v`` (default 0 V). A WGFMU role measures what its
``measure`` lists (``[I]`` or ``[V]``, one quantity per channel; ``[]`` = measurement off); a current-measuring role
sets its range with setting ``range`` (``1ua`` .. ``10ma``, default ``1ma``); setting ``force_range`` (``3v``, ``5v``,
``-10v``, ``10v``, ``auto``) fixes a role's force range (default: the finest that holds its levels); setting
``mode`` (``fastiv``, ``pg``; WP11.2) its sequencer operation mode (default Fast IV; PG: the 50 Ohm pulse output,
voltage only, R-WG-02 checks the PG ranges; ``wgfmu.pulse_train`` exposes it as ``gate_mode``). SMU roles:
``bias_v`` (``DV`` at setting ``v`` with compliance ``icomp``) and ``ground`` (the GNDU, or an SMU at 0 V with setting
``icomp``); they are switched on and set before the WGFMU phase and held through it (WG Ex. 10); the transaction's
cleanup turns them off.

**Compile** (pure; the file bytes come from the planner): the program and, for pulse builders, the nominal pulse
trains (``SourcePlan``: ``waveform`` + ``pulses``, R-WG-02, R-PULSE-01..03); per WGFMU channel the envelope (the
largest |level|, no compliance, the pulse envelope of a pulsed role from ``models.sources.pulse_envelope``) and its
``WaveformLimits`` (most vectors of a pattern, values stored, output time); the RSU routes of every WGFMU role
(``RSU<ch>.OUT`` -> ``wgfmu``) in ``envelope.routes`` with phases ``waveform`` and ``rest``; SMU bias envelopes;
estimate (points = table rows; setup, output time, readback; ``max_segment_s`` from the checkpoint spacing) and the
FLEX preview of the SMU bias (``CN``, ``DV``; the library calls are no FLEX).

**Acquire.** ``program.json`` (``RunProgram``: the waveform program and the plan's file records) is written before
anything is sourced; SMU bias roles: ``CN``, ``ERRX?`` drain, on hardware the ``LOP?`` positive control, the
levels; then ``with tx.wgfmu_phase(flex_io=<SMU bias>) as wg:`` (FLEX lock released, library session opened and
initialized; its exit always runs the WGFMU safe state and relocks): ``wg.load(program)`` (every pattern and level
guard-checked before the first library call), then

- sequencer builders: ``wg.run(check_abort=tx.check_abort, on_poll=...)`` (update, RSU connect through
  ``check_route``, execute, status polls at most 1 s apart with abort checks, checkpoint ``waveform`` every
  ``CHECKPOINT_S`` of sequencer time, readback in 100,000-value chunks), each measuring channel's values archived as
  ``raw/wgfmu-<ch>-000.npz`` (``RunFolder.save_wgfmu_raw``) before the phase closes;
- ``dc_spot``: RSU connect of every channel, then per step the guarded DC levels, ``settle``, ``samples`` readings of
  every measuring channel (abort check after each), checkpoint ``dc`` with the step's rows.

A last checkpoint ``readback`` carries the rows (tables up to 200,000 rows; larger runs keep them in ``data.npz``).

**Table** (``analysis/dataset.py`` contract): one row per stored value (sequencer builders; the measuring channels
store values at the same times) or per DC reading: ``step``, ``t_s`` (library time stamp: the centre of the averaging
window, WG p126 (4-56)), ``cycle`` (``pulse_train``/``fast_iv_ramp``: the pattern repeat; ``pulsed_iv``: the pulse;
``program_read``: 0 for the reference read, else the cycle), ``phase`` (``program_read``: ``read``, ``erase``,
``program``), ``segment`` (``fast_iv_ramp`` double: ``fwd`` up, ``rev`` down), ``event`` (measure event; ``pund``:
``P``, ``U``, ``N``, ``D``), ``<role>_range`` (current
range of a current-measuring role at the point), per WGFMU role ``<role>_V`` (measured with a status letter when it
measures voltage, else the programmed level at the point's time, a source column) and ``<role>_I`` + status for a
current-measuring role, ``<role>_V`` of each SMU bias role (programmed). Status: ``V`` when the reading sits at the
full scale of its range (the WGFMU has no compliance: an over-range reading saturates, WG p16 (1-4)), else ``N``
(``rules.builtin.wgfmu_status_letter``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from pydantic import Field, ValidationError

from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.blocks import set_levels
from b1500_test_agent.catalog.files import ParamFiles
from b1500_test_agent.catalog.kinds.smu_staircase import BiasOutput, bias_command, drain_or_raise
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.driver.wgfmu import WgfmuDriver, WgfmuTrace, warning_facts
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, StrictModel
from b1500_test_agent.models.plan import (
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    WaveformLimits,
)
from b1500_test_agent.models.recipe import PARAM_REF, Recipe, RoleSpec
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.run import ProgramEntry, RunProgram
from b1500_test_agent.models.sources import (
    SOURCE_PLAN_KEY,
    SourcePlan,
    WaveformProgram,
    WgfmuCurrentRange,
    pulse_envelope,
)
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.rules.builtin import wgfmu_status_letter
from b1500_test_agent.transport.wgfmu.api import CURRENT_RANGE_A, VOLTAGE_RANGE_V

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

KIND_ID: Final = "wgfmu_waveform"
BUILDER_PARAM: Final = "builder"
WAVEFORM_BUILDERS: Final = wf.BUILDERS
"""Builders this kind compiles (``catalog/waveforms.py``)."""

SMU_ROLE_FUNCTIONS: Final = frozenset({"bias_v", "ground"})
"""SMU role functions held around the WGFMU phase (FLEX)."""

RANGE_SETTING: Final = "range"
DEFAULT_RANGE: Final[WgfmuCurrentRange] = "1ma"
FORCE_RANGE_SETTING: Final = "force_range"
MODE_SETTING: Final = "mode"
SEQUENCER_MODES: Final = ("fastiv", "pg")
"""Values of a WGFMU role's setting ``mode`` (WP11.2; the DC builders run in DC mode)."""

CHECKPOINT_S: Final = 10.0
"""Sequencer time between two ``waveform`` checkpoints (cancel latency is the 1 s poll; R-RUN-02 segment)."""

SETUP_OVERHEAD_S: Final = 0.5
"""Estimated time of the library session (open, initialize, load, update, connect) and the RSU switching."""

READBACK_S_PER_VALUE: Final = 2e-6
"""Estimated readback time per stored value (100,000-value chunks; TODO(verify)[L8.A6]: the record's
``wgfmu_readback_s_per_value``, blueprint v2 7.6)."""

DC_READ_S: Final = 1e-3
"""Estimated time of one DC reading (TODO(verify)[L8.A3]: the record's ``wgfmu_dc_read_s``)."""

OVERRANGE_FRACTION: Final = 1.0 - 1e-9
"""A reading at this fraction of its range's full scale or beyond is saturated (status ``V``)."""

PARTIAL_ROWS_MAX: Final = 200_000
"""Largest table also handed to the last checkpoint as rows (``partial.csv`` of a cancelled asynchronous run)."""


@runtime_checkable
class WaveformArchive(Protocol):
    """What the kind needs from the run handle besides raw blocks: the WGFMU raw files and ``program.json``
    (``archive.store.RunFolder``); a transaction without one (tests) archives nothing."""

    def save_wgfmu_raw(self, channel: int, time_s: np.ndarray, value: np.ndarray, *, offset: int = 0,
                       quantity: Literal["V", "I"] | None = None) -> str: ...

    def write_program(self, program: RunProgram) -> Path: ...


class WaveformKindProgram(StrictModel):
    """The kind's part of ``PlanRecord.program`` (next to ``sources``): builder, WGFMU roles, SMU bias outputs and
    how the table is laid out."""

    builder: str
    roles: list[wf.WgRole] = Field(min_length=1)
    """WGFMU roles in recipe order."""
    biases: list[BiasOutput] = Field(default_factory=list)
    """SMU outputs (bias and grounded SMUs) held around the WGFMU phase."""
    cycle_by: wf.CycleBy = "none"
    segments: dict[str, Literal["fwd", "rev"]] = Field(default_factory=dict)
    phases: dict[str, str] = Field(default_factory=dict)
    """Table ``phase`` of each measure event (``program_read``)."""
    samples: int = Field(default=1, ge=1)
    """``dc_spot``: readings per DC step."""
    settle_s: float = Field(default=0.0, ge=0)
    """``dc_spot``: wait after each DC step."""
    chunks: int = Field(default=1, ge=1)
    """Checkpoints while the sequencer runs (one per ``CHECKPOINT_S``)."""
    rows: int = Field(ge=0)
    """Table rows planned."""

    @property
    def measuring(self) -> list[wf.WgRole]:
        return [r for r in self.roles if r.measure is not None]


@dataclass
class WaveformAcquisition(RawAcquisition):
    """``RawAcquisition`` plus the WGFMU readings: the traces of the measuring channels (sequencer builders) or the
    DC rows (``dc_spot``)."""

    traces: dict[int, WgfmuTrace] = field(default_factory=dict)
    dc_rows: list[dict[str, object]] = field(default_factory=list)


def stored(plan: PlanRecord) -> tuple[WaveformKindProgram, WaveformProgram, SourcePlan]:
    """The kind program, the waveform program and the source plan of ``plan``.

    Raises:
        CompileError: If the plan holds no valid ``wgfmu_waveform`` program.
    """
    data = {k: v for k, v in plan.program.items() if k != SOURCE_PLAN_KEY}
    try:
        program = WaveformKindProgram.model_validate(data)
        sources = SourcePlan.model_validate(plan.program.get(SOURCE_PLAN_KEY) or {})
    except ValidationError as exc:
        raise CompileError(f"plan {plan.plan_id} has no valid {KIND_ID} program: {exc}") from None
    if sources.waveform is None:
        raise CompileError(f"plan {plan.plan_id} has no waveform program")
    return program, sources.waveform, sources


# -- compile helpers -------------------------------------------------------------------------------------------------


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


def _param(params: Mapping[str, Quantity], name: str, default: Any = None) -> float:
    value = _value(params, name, default)
    if value is None:
        raise CompileError(f"the recipe gives no parameter {name}")
    return _real(value, name)


def _setting(name: str, spec: RoleSpec, params: Mapping[str, Quantity], key: str, default: Any = None) -> Any:
    return setting_value(spec, key, params, default)


def _wg_role(name: str, spec: RoleSpec, params: Mapping[str, Quantity], channel: int) -> wf.WgRole:
    if len(spec.measure) > 1:
        raise CompileError(f"role {name}: a WGFMU channel measures one quantity (I or V), not {spec.measure}")
    measure = spec.measure[0] if spec.measure else None
    rng = _setting(name, spec, params, RANGE_SETTING, DEFAULT_RANGE)
    if rng not in CURRENT_RANGE_A:
        raise CompileError(f"role {name}: {RANGE_SETTING} must be one of {sorted(CURRENT_RANGE_A)}, got {rng!r}")
    force = _setting(name, spec, params, FORCE_RANGE_SETTING)
    if force is not None and force not in WGFMU_SPEC.force_ranges:
        raise CompileError(f"role {name}: {FORCE_RANGE_SETTING} must be one of {sorted(WGFMU_SPEC.force_ranges)}, "
                           f"got {force!r}")
    mode = _setting(name, spec, params, MODE_SETTING)
    if mode is not None and mode not in SEQUENCER_MODES:
        raise CompileError(f"role {name}: {MODE_SETTING} must be one of {list(SEQUENCER_MODES)}, got {mode!r}")
    return wf.WgRole(role=name, channel=channel, measure=measure, current_range=rng, force_range=force, mode=mode)


def _one(roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], key: str, builder: str) -> str:
    """The one WGFMU role that has setting ``key`` (the pulsed/ramped role of a builder)."""
    found = [name for name, (_, spec) in roles.items() if key in spec.settings]
    if len(found) != 1:
        raise CompileError(f"{builder}: exactly one WGFMU role gives setting {key!r}, found {found or 'none'}")
    return found[0]


def _biases(roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], params: Mapping[str, Quantity],
            skip: str) -> list[tuple[wf.WgRole, float]]:
    return [(role, _real(_setting(name, spec, params, "v", 0.0), f"{name}.v"))
            for name, (role, spec) in roles.items() if name != skip]


def _levels(start: float, stop: float, points: int) -> list[float]:
    if points < 1:
        raise CompileError(f"points must be >= 1, got {points}")
    if points == 1:
        return [start]
    return [round(start + (stop - start) * i / (points - 1), 12) for i in range(points)]


def _file_name(name: str, spec: RoleSpec) -> str:
    raw = spec.settings.get("wave")
    match = PARAM_REF.match(raw) if isinstance(raw, str) else None
    if match is None:
        raise CompileError(f"table: role {name} needs setting wave: $<file parameter>")
    return match.group(1)


def _build(builder: str, recipe: Recipe, params: Mapping[str, Quantity],
           roles: Mapping[str, tuple[wf.WgRole, RoleSpec]], files: ParamFiles | None) -> wf.BuiltWaveform:
    """The builder's program from the recipe's settings and parameters (module docstring)."""
    if builder == "pulsed_iv":
        name = _one(roles, "start", builder)
        role, spec = roles[name]
        points = _int(_setting(name, spec, params, "points"), f"{name}.points")
        levels = _levels(_real(_setting(name, spec, params, "start"), f"{name}.start"),
                         _real(_setting(name, spec, params, "stop"), f"{name}.stop"), points)
        return wf.pulsed_iv(role, _biases(roles, params, name),
                            base=_real(_setting(name, spec, params, "base", 0.0), f"{name}.base"), levels=levels,
                            width=_param(params, "width"), period=_param(params, "period"),
                            edge=_param(params, "edge"), settle=_param(params, "settle", 0.0))
    if builder == "pulse_train":
        name = _one(roles, "peak", builder)
        role, spec = roles[name]
        return wf.pulse_train(role, _biases(roles, params, name),
                              base=_real(_setting(name, spec, params, "base", 0.0), f"{name}.base"),
                              peak=_real(_setting(name, spec, params, "peak"), f"{name}.peak"),
                              width=_param(params, "width"), period=_param(params, "period"),
                              edge=_param(params, "edge"), settle=_param(params, "settle", 0.0),
                              count=_int(_value(params, "count"), "count"),
                              samples=_int(_value(params, "samples", 1), "samples"))
    if builder == "fast_iv_ramp":
        name = _one(roles, "stop", builder)
        role, spec = roles[name]
        double = _value(params, "double", True)
        if not isinstance(double, bool):
            raise CompileError(f"double must be a bool, got {double!r}")
        return wf.fast_iv_ramp(role, _biases(roles, params, name),
                               start=_real(_setting(name, spec, params, "start"), f"{name}.start"),
                               stop=_real(_setting(name, spec, params, "stop"), f"{name}.stop"),
                               ramp=_param(params, "ramp"), interval=_param(params, "interval"),
                               edge=_param(params, "edge"), settle=_param(params, "settle", 0.0), double=double,
                               cycles=_int(_value(params, "cycles", 1), "cycles"))
    if builder == "dc_spot":
        listed: list[tuple[wf.WgRole, list[float]]] = []
        for name, (role, spec) in roles.items():
            values = _setting(name, spec, params, "values")
            if values is None:
                listed.append((role, [_real(_setting(name, spec, params, "v", 0.0), f"{name}.v")]))
            elif isinstance(values, list) and values:
                listed.append((role, [_real(v, f"{name}.values[{i}]") for i, v in enumerate(values)]))
            else:
                raise CompileError(f"role {name}: values must be a non-empty list of volts, got {values!r}")
        if sum(len(levels) > 1 for _, levels in listed) > 1:
            raise CompileError("dc_spot: at most one role steps through a list of levels")
        return wf.dc_spot(listed)
    if builder == "dc_sample":
        interval = _param(params, "interval")
        return wf.dc_sample([(role, _real(_setting(name, spec, params, "v", 0.0), f"{name}.v"))
                             for name, (role, spec) in roles.items()],
                            points=_int(_value(params, "points"), "points"), interval=interval,
                            average=_param(params, "average", interval), edge=_param(params, "edge"),
                            settle=_param(params, "settle", 0.0))
    if builder == "table":
        if files is None:
            raise CompileError("table: the waveform files are read through the planner (file parameters)")
        waves = [(role, wf.parse_wave_csv(files.read(_file_name(name, spec)), name=_file_name(name, spec)))
                 for name, (role, spec) in roles.items()]
        events = wf.parse_events_csv(files.read("events"), name="events", channels=len(waves))
        return wf.table(waves, events)
    if builder == "fast_bti":
        from b1500_test_agent.catalog.kinds import stress_wgfmu

        return stress_wgfmu.build(roles, params)[0]
    if builder in ("pund", "program_read"):
        from b1500_test_agent.catalog.kinds import pulse_wgfmu

        return pulse_wgfmu.build_waveform(builder, roles, params)
    raise CompileError(f"{KIND_ID}: {BUILDER_PARAM} must be one of {list(WAVEFORM_BUILDERS)}, got {builder!r}")


def _rows(built: wf.BuiltWaveform, measuring: Sequence[wf.WgRole], samples: int) -> int:
    program = built.program
    if program.dc:
        return program.dc_steps * samples
    counts = {program.points(r.channel) for r in measuring}
    if len(counts) != 1:
        raise CompileError(f"the measuring channels store different numbers of values {sorted(counts)}; their "
                           "rows cannot be aligned")
    return counts.pop()


def _rest_routes(routes: Sequence[Route], station: StationProfile) -> list[Route]:
    rest = []
    for route in routes:
        switch = station.switch(route.switch)
        if switch is not None:
            rest.append(Route(switch=route.switch, output=route.output, state=switch.rest))
    return rest


# -- the kind --------------------------------------------------------------------------------------------------------


class WgfmuWaveformKind:
    """WGFMU waveform kind (module docstring)."""

    kind_id = KIND_ID
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})
    reads_files = True
    """The planner hands ``compile`` the plan's ``file`` parameters (builder ``table``)."""

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile, files: ParamFiles | None = None) -> CompiledKindPlan:
        builder = _value(params, BUILDER_PARAM)
        if builder not in WAVEFORM_BUILDERS:
            raise CompileError(f"{KIND_ID}: {BUILDER_PARAM} must be one of {list(WAVEFORM_BUILDERS)}, got "
                               f"{builder!r}")
        other = sorted(f"{n} ({r.function})" for n, r in recipe.roles.items()
                       if r.function != "wgfmu" and r.function not in SMU_ROLE_FUNCTIONS)
        if other:
            raise CompileError(f"{KIND_ID}: cannot execute role(s) {', '.join(other)}; it supports wgfmu, bias_v "
                               "and ground")
        roles: dict[str, tuple[wf.WgRole, RoleSpec]] = {}
        routes: list[Route] = []
        wanted: list[str] = []
        for name, spec in recipe.roles.items():
            if spec.function != "wgfmu":
                continue
            bound = binding.roles.get(name)
            if bound is None and spec.optional:
                continue  # an optional role the pin map does not land: not part of this plan
            wanted.append(name)
            if bound is not None and bound.via is not None:
                routes.append(bound.via)
            if bound is None or bound.channel is None:
                continue
            roles[name] = (_wg_role(name, spec, params, bound.channel), spec)
        if not any(s.function == "wgfmu" for s in recipe.roles.values()):
            raise CompileError(f"{KIND_ID}: recipe {recipe.id} has no wgfmu role")
        if not wanted or len(roles) != len(wanted):  # unbound or wiring unknown: R-PIN-01 blocks the plan
            return CompiledKindPlan(envelope=CompiledEnvelope(channels={}, routes=frozenset(routes)),
                                    estimate=Estimate(points=0, duration_s=0.0))
        biases, smu_envelopes = self._smu_roles(recipe, params, binding)
        built = _build(str(builder), recipe, params, roles, files)
        program = built.program
        samples = _int(_value(params, "samples", 1), "samples") if program.dc else 1
        settle = _param(params, "settle", 0.0) if program.dc else 0.0
        if samples < 1 or settle < 0:
            raise CompileError("samples must be >= 1 and settle >= 0")
        measuring = [r for r, _ in roles.values() if r.measure is not None]
        rows = _rows(built, measuring, samples)
        channels: dict[int, ChannelEnvelope] = dict(smu_envelopes)
        limits: dict[int, WaveformLimits] = {}
        for role, _ in roles.values():
            ch = role.channel
            levels = program.levels(ch) or [0.0]
            trains = built.pulses.get(ch, [])
            pulse = (pulse_envelope(trains, source_ohm=None, short_circuit_a=WGFMU_SPEC.max_output_a)
                     if trains else None)
            channels[ch] = ChannelEnvelope(role=role.role, max_abs_v=max(abs(v) for v in levels), max_abs_i=None,
                                           function="wgfmu", pulse=pulse)
            limits[ch] = WaveformLimits(max_vectors=max(1, wf.max_vectors(program, ch)), max_points=program.points(ch),
                                        total_time_s=program.sequence_time_s(ch))
        total = program.total_time_s()
        chunks = max(1, math.ceil(total / CHECKPOINT_S))
        stored_program = WaveformKindProgram(builder=str(builder), roles=[r for r, _ in roles.values()],
                                             biases=biases, cycle_by=built.cycle_by, segments=built.segments,
                                             phases=built.phases, samples=samples, settle_s=settle, chunks=chunks,
                                             rows=rows)
        data: dict[str, Any] = stored_program.model_dump(mode="json")
        data[SOURCE_PLAN_KEY] = SourcePlan(pulses=built.pulses, waveform=program).model_dump(mode="json")
        ordered = sorted(set(routes), key=Route.sort_key)
        phases = {"waveform": ordered, "rest": _rest_routes(ordered, station)} if ordered else {}
        return CompiledKindPlan(
            envelope=CompiledEnvelope(channels=channels, routes=frozenset(ordered), waveform=limits),
            estimate=self._estimate(stored_program, program), flex_preview=self._preview(biases),
            program=data, routes_by_phase=phases)

    @staticmethod
    def _smu_roles(recipe: Recipe, params: Mapping[str, Quantity],
                   binding: ChannelBinding) -> tuple[list[BiasOutput], dict[int, ChannelEnvelope]]:
        biases: list[BiasOutput] = []
        envelopes: dict[int, ChannelEnvelope] = {}
        for name, spec in recipe.roles.items():
            if spec.function not in SMU_ROLE_FUNCTIONS:
                continue
            bound = binding.roles.get(name)
            if bound is None or bound.channel is None:
                continue  # GNDU (nothing sent) or unbound: R-PIN-01 decides
            icomp = _setting(name, spec, params, "icomp")
            if icomp is None:
                raise CompileError(f"role {name}: an SMU {spec.function} role needs setting icomp")
            comp = _real(icomp, f"{name}.icomp")
            level = _real(_setting(name, spec, params, "v", 0.0), f"{name}.v") if spec.function == "bias_v" else 0.0
            biases.append(BiasOutput(role=name, channel=bound.channel, level=level, comp=comp))
            envelopes[bound.channel] = ChannelEnvelope(role=name, max_abs_v=abs(level), max_abs_i=abs(comp),
                                                       function=spec.function, v_start=level, v_stop=level)
        return biases, envelopes

    @staticmethod
    def _estimate(program: WaveformKindProgram, waveform: WaveformProgram) -> Estimate:
        if waveform.dc:
            step = program.settle_s + program.samples * len(program.measuring) * DC_READ_S
            return Estimate(points=program.rows, duration_s=round(SETUP_OVERHEAD_S + waveform.dc_steps * step, 6),
                            max_segment_s=round(step + SETUP_OVERHEAD_S, 6))
        total = waveform.total_time_s()
        readback = sum(waveform.points(r.channel) for r in program.measuring) * READBACK_S_PER_VALUE
        polls = min(total, 1.0)
        segment = max(min(total, CHECKPOINT_S), readback) + SETUP_OVERHEAD_S
        return Estimate(points=program.rows, duration_s=round(SETUP_OVERHEAD_S + total + polls + readback, 6),
                        max_segment_s=round(segment, 6))

    @staticmethod
    def _preview(biases: Sequence[BiasOutput]) -> list[str]:
        """The FLEX writes of the SMU bias (``CN``, ``DV``); the WGFMU library calls are no FLEX."""
        if not biases:
            return []
        return [flex.cn([b.channel for b in biases]), *(bias_command(b) for b in biases)]

    def checkpoint_total(self, plan: PlanRecord) -> int:
        """One checkpoint per DC step (``dc_spot``); else one per ``CHECKPOINT_S`` of sequencer time plus the
        readback."""
        program, waveform, _ = stored(plan)
        return waveform.dc_steps if waveform.dc else program.chunks + 1

    # -- acquire -----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        program, waveform, _ = stored(plan)
        archive = tx.run if isinstance(tx.run, WaveformArchive) else None
        channels = sorted(r.channel for r in program.roles)
        if archive is not None:
            archive.write_program(RunProgram(kind=KIND_ID, programs={"waveform": ProgramEntry(
                source="wgfmu", channels=channels, spec=waveform.model_dump(mode="json"),
                preview=waveform.preview())}, files=dict(plan.files)))
        if program.biases:
            smu = [b.channel for b in program.biases]
            tx.driver.enable(smu)
            drain_or_raise(tx, "enabling the SMU bias")
            tx.mark("SMU bias outputs enabled")
            tx.lop_positive_control(smu)
            set_levels(tx, program.biases)
            drain_or_raise(tx, "the SMU bias levels")
        total_checkpoints = self.checkpoint_total(plan)
        traces: dict[int, WgfmuTrace] = {}
        dc_rows: list[dict[str, object]] = []
        facts: dict[str, Any] = {"builder": program.builder, "channels": ",".join(str(c) for c in channels)}
        with tx.wgfmu_phase(flex_io=bool(program.biases)) as wg:
            wg.load(waveform)
            if waveform.dc:
                dc_rows = self._run_dc(tx, wg, program, waveform)
                facts.update(dc_steps=waveform.dc_steps, readings=len(dc_rows), **warning_facts(wg.warnings()))
            else:
                done = 0

                def on_poll(elapsed: float, total: float) -> None:
                    nonlocal done
                    reached = min(int(elapsed // CHECKPOINT_S), program.chunks)
                    while done < reached:
                        done += 1
                        tx.checkpoint(done, total_checkpoints, "waveform")

                block = wg.run(check_abort=tx.check_abort, on_poll=on_poll)
                traces = block.traces
                raw = [archive.save_wgfmu_raw(ch, t.time_s, t.value, quantity=t.quantity)
                       for ch, t in sorted(traces.items())] if archive is not None else []
                facts.update(status=block.status, output_s=round(block.total_s, 9), polls=block.polls,
                             values=sum(len(t) for t in traces.values()), raw_files=len(raw),
                             **warning_facts(block.warnings))
        acquisition = WaveformAcquisition(traces=traces, dc_rows=dc_rows, kind_result=facts,
                                          message=f"{program.builder}: {program.rows} rows from WGFMU channels "
                                                  f"{', '.join(str(c) for c in channels)}")
        if not waveform.dc:
            rows: Callable[[], pd.DataFrame] | None = None
            if program.rows <= PARTIAL_ROWS_MAX:
                rows = (lambda: waveform_table(program, waveform, traces))
            tx.checkpoint(total_checkpoints, total_checkpoints, "readback", rows=rows)
        return acquisition

    @staticmethod
    def _run_dc(tx: Transaction, wg: WgfmuDriver, program: WaveformKindProgram,
                waveform: WaveformProgram) -> list[dict[str, object]]:
        """``dc_spot``: RSU connect, then per step the DC levels, ``settle``, ``samples`` readings (module
        docstring); returns the rows."""
        for role in program.roles:
            wg.connect(role.channel)
        rows: list[dict[str, object]] = []
        steps = waveform.dc_steps
        for step in range(steps):
            for role in program.roles:
                wg.force_dc(role.channel, waveform.dc[role.channel][step])
            if program.settle_s > 0:
                tx.wgfmu_link.host_wait(program.settle_s)
            first = len(rows)
            for _ in range(program.samples):
                row: dict[str, object] = {"step": len(rows)}
                for role in program.roles:
                    level = waveform.dc[role.channel][step]
                    if role.measure is None:
                        row[f"{role.role}_V"] = level
                        continue
                    value = wg.measure_dc(role.channel)
                    setup = waveform.channels[role.channel]
                    full = (CURRENT_RANGE_A[setup.current_range or DEFAULT_RANGE] if role.measure == "I"
                            else VOLTAGE_RANGE_V[setup.voltage_range or "10v"])
                    if role.measure == "I":
                        row[f"{role.role}_V"] = level
                    row[f"{role.role}_{role.measure}"] = value
                    row[f"{role.role}_{role.measure}_status"] = wgfmu_status_letter(
                        range_overflow=abs(value) >= full * OVERRANGE_FRACTION, error=False)
                row.update({f"{bias.role}_V": bias.level for bias in program.biases})
                rows.append(row)
                tx.check_abort()
            tx.checkpoint(step + 1, steps, "dc", rows=rows[first:])
        return rows

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame | None:
        """The run table (module docstring).

        Raises:
            ValueError: If the readings do not match the program (missing values, misaligned channels).
        """
        program, waveform, _ = stored(plan)
        if waveform.dc:
            rows = raw.dc_rows if isinstance(raw, WaveformAcquisition) else []
            if len(rows) != program.rows:
                raise ValueError(f"{KIND_ID}: {len(rows)} DC readings, {program.rows} planned")
            return pd.DataFrame(rows)
        traces = raw.traces if isinstance(raw, WaveformAcquisition) else {}
        return waveform_table(program, waveform, traces)


def waveform_table(program: WaveformKindProgram, waveform: WaveformProgram,
                   traces: Mapping[int, WgfmuTrace]) -> pd.DataFrame:
    """The table of a sequencer run (module docstring).

    Raises:
        ValueError: If a measuring channel's trace is missing, has another length than its program stores, or its
            time stamps lie outside the program's averaging windows, or the channels' times differ.
    """
    measuring = program.measuring
    layout: wf.PointLayout | None = None
    times: np.ndarray | None = None
    for role in measuring:
        trace = traces.get(role.channel)
        if trace is None:
            raise ValueError(f"{KIND_ID}: no readback of channel {role.channel} ({role.role})")
        own = wf.point_layout(waveform, role.channel)
        if len(trace) != len(own):
            raise ValueError(f"{KIND_ID}: channel {role.channel} returned {len(trace)} values, the program stores "
                             f"{len(own)}")
        low = own.start_s - 1e-12
        high = own.start_s + own.average_s + wf.TICK_S + 1e-12
        if np.any((trace.time_s < low) | (trace.time_s > high)):
            raise ValueError(f"{KIND_ID}: channel {role.channel} time stamps lie outside the program's measurement "
                             "windows")
        if times is None:
            layout, times = own, np.asarray(trace.time_s, dtype=float)
        elif len(trace) != len(times) or not np.allclose(trace.time_s, times, rtol=0.0, atol=wf.TICK_S):
            raise ValueError(f"{KIND_ID}: the measuring channels were sampled at different times")
    assert layout is not None and times is not None
    n = len(times)
    columns: dict[str, Any] = {"step": np.arange(n, dtype=np.int64), "t_s": times}
    if program.cycle_by == "repeat":
        columns["cycle"] = layout.repeat.astype(np.int64)
    elif program.cycle_by == "point":
        columns["cycle"] = layout.point.astype(np.int64)
    if program.phases:
        phase = np.asarray([program.phases.get(str(e), str(e)) for e in layout.event], dtype=object)
        if program.cycle_by == "op":
            columns["cycle"] = np.where(phase == "read", 0, layout.repeat + 1).astype(np.int64)
        columns["phase"] = phase
    if program.segments:
        columns["segment"] = np.asarray([program.segments.get(str(e), "fwd") for e in layout.event], dtype=object)
    columns["event"] = layout.event
    values: dict[str, Any] = {}
    for role in program.roles:
        ch = role.channel
        setup = waveform.channels[ch]
        if role.measure is None:
            values[f"{role.role}_V"] = wf.program_levels(waveform, ch, times)
            continue
        trace = traces[ch]
        value = np.asarray(trace.value, dtype=float)
        if role.measure == "I":
            own = wf.point_layout(waveform, ch)
            assert own.range is not None
            full = np.asarray([CURRENT_RANGE_A[r] for r in own.range], dtype=float)
            columns[f"{role.role}_range"] = own.range
            values[f"{role.role}_V"] = wf.program_levels(waveform, ch, times)
        else:
            full = np.full(n, VOLTAGE_RANGE_V[setup.voltage_range or "10v"])
        over = np.abs(value) >= full * OVERRANGE_FRACTION
        letters = np.where(over, wgfmu_status_letter(range_overflow=True, error=False),
                           wgfmu_status_letter(range_overflow=False, error=False))
        values[f"{role.role}_{role.measure}"] = value
        values[f"{role.role}_{role.measure}_status"] = letters.astype(object)
    for bias in program.biases:
        values[f"{bias.role}_V"] = np.full(n, bias.level)
    columns.update(values)
    return pd.DataFrame(columns)

