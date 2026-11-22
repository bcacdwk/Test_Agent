"""Role resolution of kind ``smu_pulsed`` (``catalog/kinds/smu_pulsed.py``): what each recipe role of a pulsed recipe
asks for, the measurement mode the roles select and the timing they share (blueprint v2 2.7, WP7.3).

Pulse roles (function ``pulse_v``; ``$param`` references allowed in every setting):

- ``base`` (V, default 0): the level between pulses;
- one of ``peak`` (V: a pulsed bias), ``values`` (a ``float_list`` of peaks: a pulsed bias repeated over a host list,
  one trigger per value; at most one role per recipe) or ``start``/``stop``/``points`` (a pulsed sweep; ``points`` = 1
  is a pulsed bias at ``start``, as ``smu_stepped`` reads one point) with optional ``mode`` (``single``|``double``) and
  ``scale`` (``linear``|``log``; log only in MM 28: the PG allows only linear sweeps in MM 4/5, error 226);
- ``icomp`` (A, required: R-COMP-01), ``width`` and ``period`` (s, required on the first pulse role), ``hold`` (s,
  default 0), ``meas_time`` (s; the pulsed ADC's measurement time ``AIT 2,3``, ending with the pulse; default half the
  width, at most 20 ms, on the 2 us grid), ``average`` (MM 27/28 ``MCPT`` averaging, default 1). Further pulse roles
  share the first one's timing: they may repeat ``period``, ``hold``, ``meas_time``, ``average`` and ``width`` only
  with the same values (HR/MP/HPSMU pulse together with one width and no delay, PG Table 4-27, PDF 462).

Mode (PG Table 4-28, PDF 471): a recipe that declares two or more pulse roles or two or more measuring roles (bound or
not, so a recipe keeps its mode when an optional role is left out) is a multi-channel pulsed measurement: MM 28 when a
pulse role sweeps or a ``sweep_v``/``sweep_i`` role exists (staircase ``WNX`` sources), else MM 27. Otherwise: MM 4
when the pulse role sweeps (a ``sync_v``/``sync_i`` role follows it), MM 5 when a ``sweep_v``/``sweep_i`` role is the
staircase and the pulse role a pulsed bias (a synchronous role follows the staircase), else MM 3. The sweep steps
(``points``, ``mode``, ``scale``) belong to the primary sweep (MM 4: the pulse role; MM 5: the staircase role; MM 28:
the first sweeping role in recipe order); other sweeping roles may repeat them only with the same values.
"""

from __future__ import annotations

import math
from typing import Literal

from b1500_test_agent.catalog.schema import CompileError, setting_value
from b1500_test_agent.driver import flex
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.recipe import Recipe, RoleSpec

Source = Literal["V", "I"]

PULSE_FUNCTION = "pulse_v"
SWEEP_FUNCTIONS: dict[str, Source] = {"sweep_v": "V", "sweep_i": "I"}
SYNC_FUNCTIONS: dict[str, Source] = {"sync_v": "V", "sync_i": "I"}
BIAS_FUNCTIONS: dict[str, Source] = {"bias_v": "V", "bias_i": "I"}
PULSED_FUNCTIONS = frozenset({PULSE_FUNCTION, *SWEEP_FUNCTIONS, *SYNC_FUNCTIONS, *BIAS_FUNCTIONS, "ground",
                              "measure_only"})
"""Role functions kind ``smu_pulsed`` executes."""

TIMING_SETTINGS = ("period", "hold", "meas_time", "average", "width")
"""Pulse timing settings of the first pulse role; further pulse roles repeat them only with the same values."""

STEP_SETTINGS = ("points", "mode", "scale")
"""Sweep-step settings of the primary sweep; other sweeping roles repeat them only with the same values."""

MAX_HOST_VALUES = 1001
"""Most values of a host list of pulse levels (R-RUN-01 bounds the points and duration on top)."""

DEFAULT_MEAS_FRACTION = 0.5
MAX_MEAS_TIME_S = 0.02
"""Default measurement time: half the pulse width, at most 20 ms (``AIT 2,3`` range 2 us to 20 ms, PDF 359)."""


class PulseRole(StrictModel):
    """A resolved pulse role: base, the peak(s) or sweep, compliance."""

    name: str
    base: float
    peak: float | None = None
    values: list[float] | None = None
    start: float | None = None
    stop: float | None = None
    icomp: float

    @property
    def sweeping(self) -> bool:
        return self.start is not None

    def levels(self) -> list[float]:
        """Every level the role outputs (base first)."""
        tops = self.values if self.values is not None else (
            [self.peak] if self.peak is not None else [self.start, self.stop])
        return [self.base, *(float(v) for v in tops if v is not None)]


class Timing(StrictModel):
    """The shared pulse timing (first pulse role)."""

    width: float
    period: float
    hold: float = 0.0
    meas_time: float
    average: int = 1


class Steps(StrictModel):
    """Sweep steps of the primary sweep."""

    points: int = 1
    double: bool = False
    scale: Literal["linear", "log"] = "linear"


def number(value: object, what: str) -> float:
    """A finite number or ``CompileError``."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def integer(value: object, what: str) -> int:
    """A positive integer (a literal setting may be a float) or ``CompileError``."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CompileError(f"{what} must be a positive integer, got {value!r}")
    return value


def choice(value: object, choices: tuple[str, ...], what: str) -> str:
    """One of ``choices`` or ``CompileError``."""
    if not isinstance(value, str) or value not in choices:
        raise CompileError(f"{what} must be one of {list(choices)}, got {value!r}")
    return value


def check_roles(kind_id: str, recipe: Recipe) -> tuple[list[str], list[str], list[str]]:
    """Pulse, sweep and synchronous role names (recipe order) after the role-function checks."""
    pulses = [n for n, r in recipe.roles.items() if r.function == PULSE_FUNCTION]
    sweeps = [n for n, r in recipe.roles.items() if r.function in SWEEP_FUNCTIONS]
    syncs = [n for n, r in recipe.roles.items() if r.function in SYNC_FUNCTIONS]
    if not pulses:
        raise CompileError(f"{kind_id} needs a pulse_v role; recipe {recipe.id} has none")
    other = sorted(f"{n} ({r.function})" for n, r in recipe.roles.items() if r.function not in PULSED_FUNCTIONS)
    if other:
        raise CompileError(f"{kind_id} cannot execute role(s) {', '.join(other)}; it supports "
                           f"{', '.join(sorted(PULSED_FUNCTIONS))} (DC host steps: smu_stepped)")
    if len(pulses) + len(sweeps) > flex.MCP_MAX_SOURCE:
        raise CompileError(f"{kind_id}: {len(pulses) + len(sweeps)} pulse and sweep roles exceed the "
                           f"{flex.MCP_MAX_SOURCE} sources of a multi-channel pulsed sweep (PG p465 (4-147))")
    if len(syncs) > 1:
        raise CompileError(f"{kind_id}: at most one synchronous role, recipe {recipe.id} has {syncs}")
    for name in pulses:
        role = recipe.roles[name]
        if role.measure and len(role.measure) > 1:
            raise CompileError(f"role {name} measures {role.measure}; one quantity per channel")
    return pulses, sweeps, syncs


def is_multi(recipe: Recipe, pulses: list[str]) -> bool:
    """Multi-channel pulsed (MM 27/28): two or more pulse roles or two or more measuring roles are declared."""
    measuring = [n for n, r in recipe.roles.items() if r.measure]
    return len(pulses) >= 2 or len(measuring) >= 2


def pulse_role(name: str, role: RoleSpec, params: dict[str, Quantity]) -> PulseRole:
    """The levels of pulse role ``name`` (module docstring)."""
    base = number(setting_value(role, "base", params, 0.0), f"{name}.base")
    icomp = number(setting_value(role, "icomp", params), f"{name}.icomp")
    forms = [key for key in ("peak", "values", "start") if key in role.settings]
    if len(forms) != 1 or ("start" in role.settings) != ("stop" in role.settings):
        raise CompileError(f"{name}: give exactly one of peak, values or start/stop/points")
    if "peak" in role.settings:
        return PulseRole(name=name, base=base, peak=number(setting_value(role, "peak", params), f"{name}.peak"),
                         icomp=icomp)
    if "values" in role.settings:
        listed = setting_value(role, "values", params)
        if not isinstance(listed, list) or not listed:
            raise CompileError(f"{name}.values must be a non-empty list of pulse levels, got {listed!r}")
        if len(listed) > MAX_HOST_VALUES:
            raise CompileError(f"{name}: {len(listed)} pulse levels exceed {MAX_HOST_VALUES}")
        return PulseRole(name=name, base=base, values=[number(v, f"{name}.values[{i}]") for i, v in enumerate(listed)],
                         icomp=icomp)
    start = number(setting_value(role, "start", params), f"{name}.start")
    stop = number(setting_value(role, "stop", params), f"{name}.stop")
    points = integer(setting_value(role, "points", params, 1), f"{name}.points")
    if points == 1:
        return PulseRole(name=name, base=base, peak=start, icomp=icomp)
    return PulseRole(name=name, base=base, start=start, stop=stop, icomp=icomp)


def timing(primary: str, roles: dict[str, RoleSpec], pulse_names: list[str], params: dict[str, Quantity]) -> Timing:
    """The first pulse role's timing; the others may repeat it only with the same values."""
    role = roles[primary]
    width = number(setting_value(role, "width", params), f"{primary}.width")
    period = number(setting_value(role, "period", params), f"{primary}.period")
    hold = number(setting_value(role, "hold", params, 0.0), f"{primary}.hold")
    default_meas = min(width * DEFAULT_MEAS_FRACTION, MAX_MEAS_TIME_S)
    default_meas = max(flex.PULSE_WIDTH_GRID_S, round(default_meas / flex.PULSE_WIDTH_GRID_S) * flex.PULSE_WIDTH_GRID_S)
    meas = number(setting_value(role, "meas_time", params, default_meas), f"{primary}.meas_time")
    average = integer(setting_value(role, "average", params, 1), f"{primary}.average")
    if meas > width:
        raise CompileError(f"{primary}.meas_time {meas:g} s must fit inside the pulse width {width:g} s (the "
                           "measurement ends with the pulse)")
    own = {"width": width, "period": period, "hold": hold, "meas_time": meas, "average": average}
    for name in pulse_names:
        if name == primary:
            continue
        for key in TIMING_SETTINGS:
            value = setting_value(roles[name], key, params)
            if value is not None and value != own[key]:
                raise CompileError(f"{name}.{key}: every pulse role shares the timing of {primary} (HR/MP/HPSMU pulse "
                                   "together, one width, PG p462 (4-144)); remove the setting or use the same value")
    return Timing(width=width, period=period, hold=hold, meas_time=meas, average=average)


def steps(primary: str, roles: dict[str, RoleSpec], sweeping: list[str], params: dict[str, Quantity]) -> Steps:
    """The primary sweep's steps; other sweeping roles may repeat them only with the same values."""
    role = roles[primary]
    points = integer(setting_value(role, "points", params), f"{primary}.points")
    mode = choice(setting_value(role, "mode", params, "single"), ("single", "double"), f"{primary}.mode")
    scale = choice(setting_value(role, "scale", params, "linear"), ("linear", "log"), f"{primary}.scale")
    for name in sweeping:
        if name == primary:
            continue
        for key in STEP_SETTINGS:
            value = setting_value(roles[name], key, params)
            if value is not None and value != setting_value(role, key, params):
                raise CompileError(f"{name}.{key}: every sweep source follows the steps of {primary}; remove the "
                                   "setting")
    return Steps(points=points, double=mode == "double", scale=scale)  # type: ignore[arg-type]
