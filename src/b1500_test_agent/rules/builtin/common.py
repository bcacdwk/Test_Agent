"""Shared constants and helpers of the built-in rules (blueprint 2.8): role-function classes, envelope access,
channel, module, DUT-terminal and source-plan lookup, hard limits, parameter-range checks and the code-ceiling symbols
used as finding sources."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import BoundChannel, ChannelEnvelope
from b1500_test_agent.models.policy import HARD_CEILING_A, HARD_CEILING_V, DutTerminal
from b1500_test_agent.models.recipe import ParamSpec, RoleSpec, file_param_origin
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import SourcePlan, source_plan
from b1500_test_agent.models.station import ModuleSlot
from b1500_test_agent.rules.engine import RuleContext, RuleEnv

SOURCING_FUNCTIONS = frozenset({"sweep_v", "bias_v", "step_v", "sync_v", "pulse_v"})
"""Role functions that force a programmed voltage and therefore need an explicit current compliance (R-COMP-01)."""

CURRENT_SOURCING_FUNCTIONS = frozenset({"sweep_i", "bias_i", "step_i", "sync_i"})
"""Role functions that force a programmed current and therefore need an explicit voltage compliance (R-COMP-01);
their envelope's ``max_abs_i`` is the forced current and ``max_abs_v`` the compliance (R-LIM-01: I-source corners)."""

COMPLIANCE_SETTING = "icomp"
"""Role-settings key that holds a sourcing role's current compliance (blueprint 2.6 recipe example)."""

VOLTAGE_COMPLIANCE_SETTING = "vcomp"
"""Role-settings key that holds a current-forcing role's voltage compliance."""

MEASURE_RANGE_SETTING = "irange"
"""Role-settings key with the full scale (A) of a role's fixed or limited-auto current measurement range; a range that
needs an ASU (1 pA) is allowed only on an SMU with a declared, present ASU (R-ASU-01)."""

PULSE_FUNCTIONS = frozenset({"pulse_v", "pgu"})
"""Role functions that apply pulse trains (SMU pulse source, HV-SPGU output); WGFMU channels are pulse channels when
their envelope carries a pulse envelope (R-PULSE-*)."""

CMU_SOURCE_FUNCTION = "cmu_high"
"""The MFCMU role that applies the AC signal and DC bias (the High side); ``cmu_low`` is its virtual-ground side."""

INTERLOCK_ERRORS: dict[int, str] = {
    202: "Interlock circuit must be closed.",
    203: "Cannot enable channel.",
}
"""``ERRX?`` codes that report the interlock refusing a high-voltage state (Programming Guide Ed. 15, PDF 577,
printed 5-5). R-IL-01 checks them in addition to status-byte bit 3, because bit 3 latches an event and is cleared by
a serial poll rather than tracking the interlock level (ATV-10 fallback)."""

CEILING_V_SYMBOL = "b1500_test_agent.rules.tiers.HARD_CEILING_V"
CEILING_A_SYMBOL = "b1500_test_agent.rules.tiers.HARD_CEILING_A"


# -- Helpers ---------------------------------------------------------------------------------------------------------


def norm_channel(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if channel <= 10 else channel


def envelope_items(ctx: RuleContext) -> list[tuple[int, ChannelEnvelope]]:
    return sorted(ctx.plan.envelope.channels.items())


def channel_envelope(ctx: RuleContext, channel: int) -> ChannelEnvelope | None:
    return next((e for ch, e in ctx.plan.envelope.channels.items() if norm_channel(ch) == norm_channel(channel)), None)


def who(env_entry: ChannelEnvelope, channel: int) -> str:
    return f"{env_entry.role} (channel {channel})"


def module_index(ctx: RuleContext, module: ModuleSlot) -> int:
    return ctx.station.modules.index(module)


def binding_of(ctx: RuleContext, channel: int) -> tuple[str, BoundChannel] | None:
    """``(role, binding)`` of the role whose envelope entry is on ``channel`` (``None`` when unbound)."""
    entry = channel_envelope(ctx, channel)
    if entry is None:
        return None
    bound = ctx.plan.binding.roles.get(entry.role)
    return None if bound is None else (entry.role, bound)


def role_function(ctx: RuleContext, role: str, entry: ChannelEnvelope | None = None) -> str | None:
    """The role's function from the recipe (else the envelope entry's)."""
    spec = ctx.recipe.roles.get(role)
    if spec is not None:
        return spec.function
    return entry.function if entry is not None else None


def dut_terminal(ctx: RuleContext, role: str) -> tuple[str, DutTerminal | None]:
    """The DUT terminal a role drives and its envelope in the DUT profile (``None`` when not described)."""
    bound = ctx.plan.binding.roles.get(role)
    terminal = bound.terminal if bound is not None else role
    if ctx.dut is None:
        return terminal, None
    return terminal, ctx.dut.terminals.get(terminal)


def hard_limit_v(ctx: RuleContext, env: RuleEnv) -> tuple[float, str]:
    """``(limit, source)`` of the |V| hard limit: the policy value, never above the code ceiling."""
    value = ctx.policy.hard_limits.max_abs_voltage_v
    if value <= HARD_CEILING_V:
        return value, env.policy("hard_limits.max_abs_voltage_v")
    return HARD_CEILING_V, env.code(CEILING_V_SYMBOL)


def hard_limit_a(ctx: RuleContext, env: RuleEnv) -> tuple[float, str]:
    """``(limit, source)`` of the |I| hard limit: the policy value, never above the code ceiling."""
    value = ctx.policy.hard_limits.max_abs_compliance_a
    if value <= HARD_CEILING_A:
        return value, env.policy("hard_limits.max_abs_compliance_a")
    return HARD_CEILING_A, env.code(CEILING_A_SYMBOL)


def source_plan_of(ctx: RuleContext) -> tuple[SourcePlan, str | None]:
    """The plan's ``SourcePlan`` (``plan.program["sources"]``) and why it does not validate (``None`` = it does;
    an invalid one comes back empty)."""
    try:
        return source_plan(ctx.plan.program), None
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {"msg": str(exc), "loc": ()}
        where = ".".join(str(p) for p in first.get("loc", ()))
        return SourcePlan(), f"{where}: {first['msg']}" if where else str(first["msg"])


@dataclass(frozen=True)
class PlanRoute:
    """One switch route of the plan and where the plan names it (``envelope.routes``, a phase or a role binding)."""

    route: Route
    where: str


def plan_routes(ctx: RuleContext) -> list[PlanRoute]:
    """Every switch route the plan names: the allowed routes, the routes of every phase, the roles' ``via``."""
    found = [PlanRoute(r, "envelope.routes") for r in sorted(ctx.plan.envelope.routes, key=Route.sort_key)]
    for phase, routes in sorted(ctx.plan.routes_by_phase.items()):
        found.extend(PlanRoute(r, f"routes_by_phase.{phase}[{i}]") for i, r in enumerate(routes))
    for role, bound in sorted(ctx.plan.binding.roles.items()):
        if bound.via is not None:
            found.append(PlanRoute(bound.via, f"binding.roles.{role}.via"))
    return found


def is_real(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def range_text(spec: ParamSpec) -> str:
    assert spec.range is not None
    return f"{spec.range[0]:g}..{spec.range[1]:g}"


def param_problem(spec: ParamSpec, value: object) -> tuple[str, str, object, object] | None:
    """``(problem, spec field, observed, limit)`` when ``value`` does not match ``spec``, else ``None``."""
    if spec.type == "bool":
        return None if isinstance(value, bool) else ("is not a bool", "type", repr(value), "bool")
    if spec.type == "enum":
        choices = spec.choices or []
        if isinstance(value, str) and value in choices:
            return None
        return "is not one of the choices", "choices", repr(value), ", ".join(choices)
    if spec.type == "file":
        if file_param_origin(value) is not None:
            return None
        if isinstance(value, str) and "\\" in value:  # a Windows spelling: the plan names files with / only
            return ("uses \\ separators; name the CSV with / (as on every OS)", "type", repr(value),
                    "recipes/waveforms/<name>.csv or work/waveforms/<name>.csv")
        return ("is not a CSV path under recipes/waveforms/ or work/waveforms/", "type", repr(value),
                "recipes/waveforms/<name>.csv or work/waveforms/<name>.csv")
    if spec.type == "int":
        if not (isinstance(value, int) and not isinstance(value, bool)):
            return "is not an integer", "type", repr(value), "int"
        values: list[float] = [value]
    elif spec.type == "float":
        if not is_real(value):
            return "is not a finite number", "type", repr(value), "float"
        values = [value]  # type: ignore[list-item]
    else:
        if not (isinstance(value, list) and value and all(is_real(v) for v in value)):
            return "is not a non-empty list of finite numbers", "type", repr(value), "float_list"
        values = list(value)
    if spec.range is not None:
        low, high = spec.range
        outside = [v for v in values if not low <= v <= high]
        if outside:
            return "lies outside the recipe range", "range", outside[0], range_text(spec)
    return None


def setting_value(role: RoleSpec, key: str, params: Mapping[str, Quantity]) -> object:
    """A role setting with ``$param`` references resolved (``None`` when absent or unresolvable)."""
    raw = role.settings.get(key)
    if isinstance(raw, str) and raw.startswith("$"):
        quantity = params.get(raw[1:])
        return None if quantity is None else quantity.value
    return raw


def scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, str | bool | int | float):
        return value  # type: ignore[return-value]
    return repr(value)


