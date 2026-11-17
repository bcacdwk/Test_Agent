"""Built-in rules of blueprint 4.2, registered in table order (which is also the finding order).

Thresholds come only from ``policy.yaml``, the station profile, pin maps, DUT profiles, recipe ``ParamSpec.range``
and the code tables (module specs in ``driver/modules.py``, the hard-limit ceiling in ``rules/tiers.py``).
Limits compare magnitudes and are exclusive: a value equal to a limit passes (10 V with a 10 V soft limit is ``ok``).

Every voltage/current check runs over the plan's ``CompiledEnvelope`` (the per-channel |V| and |I| the
``OutputGuard`` will enforce), never over the raw request, so a rule and the guard can never disagree about what
may be applied. Live-state rules (R-INV-01, R-IL-01, R-ERRX-01) also run in the ``plan`` phase when a snapshot is
supplied and skip otherwise; they only block or warn, so the plan summary depends on config alone.

R-QUAL-* is the post-run classification of per-point status letters (``quality_findings``); it is not a phase of
``RulesEngine.evaluate`` and is reached through ``RulesEngine.quality``. It does not import ``analysis``, which
owns the detailed quality report and the extraction gate.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping

from b1500_test_agent.config import CORE_ITEMS
from b1500_test_agent.driver.modules import module_spec, violations
from b1500_test_agent.models.analysis import Quantity, TrustPolicy
from b1500_test_agent.models.plan import BoundChannel, ChannelEnvelope, RuleFinding
from b1500_test_agent.models.recipe import ParamSpec, RoleSpec
from b1500_test_agent.models.station import SMU_TYPES, InstrumentError, ModuleSlot
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, info, rule, warn
from b1500_test_agent.rules.tiers import HARD_CEILING_A, HARD_CEILING_V

SOURCING_FUNCTIONS = frozenset({"sweep_v", "bias_v", "step_v"})
"""Role functions that force a programmed voltage and therefore need an explicit compliance (R-COMP-01)."""

COMPLIANCE_SETTING = "icomp"
"""Role-settings key that holds a sourcing role's current compliance (blueprint 2.6 recipe example)."""

INTERLOCK_ERRORS: dict[int, str] = {
    202: "Interlock circuit must be closed.",
    203: "Cannot enable channel.",
}
"""``ERRX?`` codes that report the interlock refusing a high-voltage state (Programming Guide Ed. 15, PDF 577,
printed 5-5). R-IL-01 checks them in addition to status-byte bit 3, because bit 3 latches an event and is cleared by
a serial poll rather than tracking the interlock level (ATV-10 fallback)."""

CMU_CORRECTIONS = ("phase_compensation", "open", "short")
"""MFCMU corrections a capacitance measurement needs (R-CORR-01); open and short must also cover its frequencies."""

_CEILING_V_SYMBOL = "b1500_test_agent.rules.tiers.HARD_CEILING_V"
_CEILING_A_SYMBOL = "b1500_test_agent.rules.tiers.HARD_CEILING_A"


# -- Helpers ---------------------------------------------------------------------------------------------------------


def _norm(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if channel <= 10 else channel


def _envelope(ctx: RuleContext) -> list[tuple[int, ChannelEnvelope]]:
    return sorted(ctx.plan.envelope.channels.items())


def _channel_envelope(ctx: RuleContext, channel: int) -> ChannelEnvelope | None:
    return next((e for ch, e in ctx.plan.envelope.channels.items() if _norm(ch) == _norm(channel)), None)


def _who(env_entry: ChannelEnvelope, channel: int) -> str:
    return f"{env_entry.role} (channel {channel})"


def _module_index(ctx: RuleContext, module: ModuleSlot) -> int:
    return ctx.station.modules.index(module)


def _is_real(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _range_text(spec: ParamSpec) -> str:
    assert spec.range is not None
    return f"{spec.range[0]:g}..{spec.range[1]:g}"


def _param_problem(spec: ParamSpec, value: object) -> tuple[str, str, object, object] | None:
    """``(problem, spec field, observed, limit)`` when ``value`` does not match ``spec``, else ``None``."""
    if spec.type == "bool":
        return None if isinstance(value, bool) else ("is not a bool", "type", repr(value), "bool")
    if spec.type == "enum":
        choices = spec.choices or []
        if isinstance(value, str) and value in choices:
            return None
        return "is not one of the choices", "choices", repr(value), ", ".join(choices)
    if spec.type == "int":
        if not (isinstance(value, int) and not isinstance(value, bool)):
            return "is not an integer", "type", repr(value), "int"
        values: list[float] = [value]
    elif spec.type == "float":
        if not _is_real(value):
            return "is not a finite number", "type", repr(value), "float"
        values = [value]  # type: ignore[list-item]
    else:
        if not (isinstance(value, list) and value and all(_is_real(v) for v in value)):
            return "is not a non-empty list of finite numbers", "type", repr(value), "float_list"
        values = list(value)
    if spec.range is not None:
        low, high = spec.range
        outside = [v for v in values if not low <= v <= high]
        if outside:
            return "lies outside the recipe range", "range", outside[0], _range_text(spec)
    return None


def _setting_value(role: RoleSpec, key: str, params: Mapping[str, Quantity]) -> object:
    """A role setting with ``$param`` references resolved (``None`` when absent or unresolvable)."""
    raw = role.settings.get(key)
    if isinstance(raw, str) and raw.startswith("$"):
        quantity = params.get(raw[1:])
        return None if quantity is None else quantity.value
    return raw


# -- R-CFG-01 --------------------------------------------------------------------------------------------------------


@rule("R-CFG-01", {"plan", "pre_execute"})
def config_valid(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """The loaded config is valid for this backend and is the config the context was built from.

    The loader already rejects invalid files with ``invalid_config`` (``config_findings`` turns that report into
    R-CFG-01 findings); this re-checks the invariants that must hold for any bundle that reaches the engine.
    """
    cfg = env.config
    hard = cfg.policy.hard_limits
    for field, value, ceiling, symbol, unit in (
        ("max_abs_voltage_v", hard.max_abs_voltage_v, HARD_CEILING_V, _CEILING_V_SYMBOL, "V"),
        ("max_abs_compliance_a", hard.max_abs_compliance_a, HARD_CEILING_A, _CEILING_A_SYMBOL, "A"),
    ):
        if value > ceiling:
            yield block(
                f"policy hard_limits.{field} {value:g} {unit} exceeds the code ceiling {ceiling:g} {unit} "
                f"({env.code(symbol)}); hard limits may only tighten it",
                source=env.policy(f"hard_limits.{field}"),
                observed=value,
                limit=ceiling,
            )
    if cfg.backend == "visa":
        for item in CORE_ITEMS:
            file = cfg.files.get(item)
            if file is None or file.source != "local":
                yield block(
                    f"backend visa requires config/local/{item}.yaml (resolved: "
                    f"{file.source if file else 'missing'})",
                    source=env.config_source(item),
                    observed=file.source if file else None,
                    limit="local",
                )
        if cfg.paths.override_config_dir is not None:
            yield block(
                "backend visa with B1500_CONFIG_DIR set (tests and the M3 runner only)",
                source=env.settings("backend"),
                observed=cfg.paths.override_config_dir.as_posix(),
                limit=None,
            )
    for what, backend in (("plan", ctx.plan.backend), ("rule context", ctx.backend)):
        if backend != cfg.backend:
            yield block(
                f"{what} backend {backend} differs from the configured backend {cfg.backend}; validate a new plan",
                source=env.settings("backend"),
                observed=backend,
                limit=cfg.backend,
            )
    mismatched = []
    if ctx.policy != cfg.policy:
        mismatched.append(("policy", env.config_source("policy")))
    if ctx.station != cfg.station:
        mismatched.append(("station profile", env.config_source("station")))
    if ctx.pin_map is not None and cfg.pin_maps.get(ctx.pin_map.name) != ctx.pin_map:
        mismatched.append((f"pin map {ctx.pin_map.name}", env.pin_map(ctx.pin_map.name)))
    if ctx.dut is not None and cfg.dut_profiles.get(ctx.dut.name) != ctx.dut:
        mismatched.append((f"DUT profile {ctx.dut.name}", env.dut(ctx.dut.name)))
    for what, source in mismatched:
        yield block(f"the {what} in the rule context differs from the loaded config", source=source)


# -- R-FAULT-01 ------------------------------------------------------------------------------------------------------


@rule("R-FAULT-01", {"plan", "pre_execute"})
def no_fault(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """No latched fault and no unrecovered in-flight marker."""
    if ctx.fault is not None:
        yield block(
            f"fault latched ({ctx.fault.reason}); every sourcing path refuses until a human clears it after a "
            "verified safe shutdown",
            source=env.state("fault.json"),
            observed=ctx.fault.reason,
            limit="no latched fault",
        )
    if ctx.inflight_unrecovered:
        yield block(
            "an interrupted transaction left an in-flight marker that has not been recovered; call safe_shutdown",
            source=env.state("inflight.json"),
            observed=True,
            limit=False,
        )


# -- R-REC-01 --------------------------------------------------------------------------------------------------------


@rule("R-REC-01", {"plan"})
def recipe_status(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Effective recipe status: ``not_implemented`` blocks; on visa ``draft``/``sim_validated``/``generic.*``
    need confirmation; on sim ``draft`` warns."""
    recipe, status = ctx.recipe, ctx.effective_status
    if status == "not_implemented":
        if recipe.status != "not_implemented":
            message = (f"recipe {recipe.id}: kind {recipe.kind} is not implemented on backend {ctx.backend} "
                       f"(recipe status {recipe.status})")
            source = env.recipe(recipe, "kind")
        else:
            message = f"recipe {recipe.id} is not_implemented"
            source = env.recipe(recipe, "status")
        yield block(message, source=source, observed=status, limit="draft or better")
        return
    status_source = env.recipe(recipe, "status")
    if ctx.backend == "visa":
        if status == "draft":
            yield confirm("draft_recipe", f"recipe {recipe.id} is a draft (not validated on the simulator)",
                          source=status_source, observed=status, limit="hw_validated")
        elif status == "sim_validated":
            yield confirm("first_hw_run", f"recipe {recipe.id} has not been validated on hardware yet",
                          source=status_source, observed=status, limit="hw_validated")
        if recipe.id.startswith("generic."):
            yield confirm("adhoc_recipe", f"recipe {recipe.id} is a generic ad-hoc recipe",
                          source=env.recipe(recipe, "id"), observed=recipe.id, limit="device-specific recipe")
    elif status == "draft":
        yield warn(f"recipe {recipe.id} is a draft: runs on the simulator, needs confirmation on hardware",
                   source=status_source, observed=status, limit="sim_validated")


# -- R-PARAM-01 ------------------------------------------------------------------------------------------------------


@rule("R-PARAM-01", {"plan"})
def params_match_spec(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Requested and resolved parameters match the recipe's ``ParamSpec`` type, choices and range."""
    recipe = ctx.recipe
    specs, resolved, requested = recipe.params, ctx.plan.resolved_params, ctx.plan.request.params
    declared = ", ".join(sorted(specs)) or "none"
    for name in sorted(set(requested) - set(specs)):
        yield block(f"unknown parameter {name!r} (recipe parameters: {declared})", subject=name,
                    source=env.recipe(recipe, "params"), observed=name, limit=declared)
    for name in sorted(set(resolved) - set(specs) - set(requested)):
        yield block(f"resolved parameter {name!r} is not declared by the recipe", subject=name,
                    source=env.recipe(recipe, "params"), observed=name, limit=declared)
    for name, spec in sorted(specs.items()):
        quantity = resolved.get(name)
        if quantity is None:
            yield block(f"parameter {name!r} has no value" + (" (required)" if spec.default is None else ""),
                        subject=name, source=env.recipe(recipe, f"params.{name}"), observed=None,
                        limit="a value")
            continue
        problem = _param_problem(spec, quantity.value)
        if problem is not None:
            text, field, observed, limit = problem
            yield block(f"parameter {name} = {quantity.value!r} {text}", subject=name,
                        source=env.recipe(recipe, f"params.{name}.{field}"), observed=_scalar(observed),
                        limit=_scalar(limit))
        if quantity.unit != spec.unit:
            yield block(f"parameter {name} has unit {quantity.unit} but the recipe declares {spec.unit}",
                        subject=name, source=env.recipe(recipe, f"params.{name}.unit"), observed=quantity.unit,
                        limit=spec.unit)
        if name in requested and requested[name] != quantity.value:
            yield block(f"parameter {name}: resolved value {quantity.value!r} differs from the requested "
                        f"{requested[name]!r}", subject=name, source=env.plan(f"resolved_params.{name}"),
                        observed=_scalar(quantity.value), limit=_scalar(requested[name]))


def _scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, str | bool | int | float):
        return value  # type: ignore[return-value]
    return repr(value)


# -- R-PIN-01 --------------------------------------------------------------------------------------------------------


@rule("R-PIN-01", {"plan"})
def pin_map_complete(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """The pin map exists, maps every non-optional role, uses existing channels once each with an allowed module
    type (``low_current`` needs an HRSMU), and the plan binding and envelope agree with it."""
    recipe, plan = ctx.recipe, ctx.plan
    name = plan.binding.pin_map
    pin_map = ctx.pin_map
    if pin_map is None:
        yield block(f"pin map {name!r} not found; ask the human for the wiring (never invent a pin map)",
                    source=env.pin_map(name), observed=name, limit="an existing pin map")
        return
    binding = plan.binding.roles
    for role_name in sorted(set(binding) - set(recipe.roles)):
        yield block(f"the plan binds role {role_name!r}, which recipe {recipe.id} does not define",
                    subject=role_name, source=env.plan(f"binding.roles.{role_name}"), observed=role_name)
    seen: dict[int, str] = {}
    for role_name, spec in sorted(recipe.roles.items()):
        yield from _check_role(ctx, env, role_name, spec, binding.get(role_name), seen)
    bound_channels = {
        _norm(b.channel): role for role, b in binding.items() if b.channel is not None and role in recipe.roles
    }
    for channel, entry in _envelope(ctx):
        owner = bound_channels.get(_norm(channel))
        if owner is None or owner != entry.role:
            yield block(f"envelope channel {channel} (role {entry.role}) is not the channel bound to that role",
                        subject=entry.role, source=env.plan(f"envelope.channels.{channel}"), observed=channel,
                        limit=None if owner is None else f"role {owner}")


def _check_role(ctx: RuleContext, env: RuleEnv, role_name: str, spec: RoleSpec, bound: BoundChannel | None,
                seen: dict[int, str]) -> Iterator[Finding]:
    assert ctx.pin_map is not None
    pin_map, station, recipe = ctx.pin_map, ctx.station, ctx.recipe
    terminal_src = env.pin_map(pin_map.name, f"terminals.{role_name}")
    target = pin_map.terminals.get(role_name)
    if target is None:
        if spec.optional:
            if bound is not None:
                yield block(f"optional role {role_name} is bound although the pin map leaves it unconnected",
                            subject=role_name, source=terminal_src, observed=None, limit=None)
            return
        why = "has no terminal" if role_name not in pin_map.terminals else "leaves the terminal unconnected"
        yield block(f"role {role_name} is not mapped: pin map {pin_map.name} {why} {role_name!r}",
                    subject=role_name, source=terminal_src, observed=None, limit="a channel or GNDU")
        return
    if bound is None:
        yield block(f"role {role_name} is mapped in pin map {pin_map.name} but missing from the plan binding",
                    subject=role_name, source=env.plan(f"binding.roles.{role_name}"), observed=None,
                    limit=str(target))
        return
    if bound.terminal != role_name:
        yield block(f"role {role_name} is bound to terminal {bound.terminal!r}", subject=role_name,
                    source=env.plan(f"binding.roles.{role_name}.terminal"), observed=bound.terminal,
                    limit=role_name)
    if target == "GNDU":
        if not bound.gndu:
            yield block(f"role {role_name}: the plan binding differs from the pin map (GNDU)", subject=role_name,
                        source=terminal_src, observed=bound.channel, limit="GNDU")
        if not spec.allow_gndu:
            yield block(f"role {role_name} may not use the GNDU", subject=role_name,
                        source=env.recipe(recipe, f"roles.{role_name}.allow_gndu"), observed="GNDU",
                        limit="an SMU channel")
        elif spec.function != "ground" or spec.low_current or spec.measure:
            yield block(f"role {role_name} ({spec.function}) needs an SMU; the GNDU only provides 0 V",
                        subject=role_name, source=env.recipe(recipe, f"roles.{role_name}.function"),
                        observed="GNDU", limit="an SMU channel")
        if not station.mainframe.gndu:
            yield block("the station profile has no GNDU", subject=role_name,
                        source=env.station("mainframe.gndu"), observed=False, limit=True)
        return
    channel = target
    if bound.channel is None or _norm(bound.channel) != _norm(channel):
        yield block(f"role {role_name}: the plan binding (channel {bound.channel}) differs from the pin map "
                    f"(channel {channel})", subject=role_name, source=terminal_src, observed=bound.channel,
                    limit=channel)
    previous = seen.get(_norm(channel))
    if previous is not None:
        yield block(f"channel {channel} is mapped to both {previous} and {role_name}", subject=role_name,
                    source=terminal_src, observed=channel, limit="one role per channel")
    seen[_norm(channel)] = role_name
    module = station.module_for_channel(channel)
    if module is None:
        installed = ", ".join(str(c) for m in station.modules for c in m.channels)
        yield block(f"role {role_name}: channel {channel} has no module in the station profile",
                    subject=role_name, source=env.station("modules"), observed=channel, limit=installed)
        return
    if (bound.slot, bound.module_type, bound.module_model) != (module.slot, module.type, module.model):
        yield block(f"role {role_name}: the plan binding ({bound.module_model} {bound.module_type} in slot "
                    f"{bound.slot}) differs from the station profile ({module.model} {module.type} in slot "
                    f"{module.slot})", subject=role_name,
                    source=env.station(f"modules[{_module_index(ctx, module)}]"), observed=bound.module_model,
                    limit=module.model)
    allowed = list(spec.module_types) or sorted(SMU_TYPES)
    if module.type not in allowed:
        yield block(f"role {role_name} needs one of {', '.join(allowed)}; channel {channel} is a {module.type}",
                    subject=role_name, source=env.recipe(recipe, f"roles.{role_name}.module_types"),
                    observed=module.type, limit=", ".join(allowed))
    if spec.low_current and module.type != "HRSMU":
        yield block(f"role {role_name} is low_current and needs an HRSMU; channel {channel} is a {module.type}",
                    subject=role_name, source=env.recipe(recipe, f"roles.{role_name}.low_current"),
                    observed=module.type, limit="HRSMU")


# -- R-PIN-02 --------------------------------------------------------------------------------------------------------


@rule("R-PIN-02", {"plan"})
def pin_map_verified(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """An ``unverified`` pin map needs confirmation."""
    if ctx.pin_map is not None and ctx.pin_map.certainty == "unverified":
        yield confirm("unverified_pin_map",
                      f"pin map {ctx.pin_map.name} is unverified: a human must confirm the wiring",
                      source=env.pin_map(ctx.pin_map.name, "certainty"), observed="unverified", limit="verified")


# -- R-INV-01 --------------------------------------------------------------------------------------------------------


@rule("R-INV-01", {"plan", "pre_execute"})
def inventory_matches(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Live identity and ``UNT?`` inventory match the station profile for every bound channel."""
    live = ctx.live
    if live is None:
        if env.phase == "pre_execute":
            yield block("no live instrument snapshot: identity and module inventory cannot be checked",
                        source=env.live("snapshot"), observed=None, limit="a live snapshot")
        return
    if live.backend != ctx.backend:
        yield block(f"live snapshot comes from backend {live.backend}, the plan targets {ctx.backend}",
                    source=env.live("backend"), observed=live.backend, limit=ctx.backend)
    expected_model = ctx.station.mainframe.model
    if live.identity is None:
        yield block("instrument identity was not read", source=env.live("identity"), observed=None,
                    limit=expected_model)
    elif live.identity.model.strip() != expected_model:
        yield block(f"instrument identifies as {live.identity.model}, the station profile says {expected_model}",
                    source=env.station("mainframe.model"), observed=live.identity.model, limit=expected_model)
    if live.inventory is None:
        yield block("module inventory was not read", source=env.live("inventory"), observed=None,
                    limit="inventory")
        return
    checked: set[int] = set()
    for role_name, bound in sorted(ctx.plan.binding.roles.items()):
        if bound.channel is None:
            continue
        module = ctx.station.module_for_channel(bound.channel)
        if module is None or module.slot in checked:
            continue  # unknown channel: R-PIN-01 blocks
        checked.add(module.slot)
        installed = live.inventory.model_in_slot(module.slot)
        if installed != module.model:
            yield block(f"slot {module.slot} ({role_name}): the instrument reports {installed or 'an empty slot'}, "
                        f"the station profile says {module.model}", subject=role_name,
                        source=env.station(f"modules[{_module_index(ctx, module)}].model"), observed=installed,
                        limit=module.model)


# -- R-LIM-01 --------------------------------------------------------------------------------------------------------


@rule("R-LIM-01", {"plan"})
def module_spec_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """|V|, |Icomp| and V*I of every envelope channel lie within its module's DC spec (``driver/modules.py``);
    the GNDU must sink the summed compliance of all channels when a role uses it."""
    total_i = 0.0
    for channel, entry in _envelope(ctx):
        total_i += entry.max_abs_i
        module = ctx.station.module_for_channel(channel)
        if module is None:
            yield block(f"{_who(entry, channel)} has no module in the station profile", subject=entry.role,
                        source=env.station("modules"), observed=channel, limit=None)
            continue
        try:
            spec = module_spec(module.model)
        except KeyError:
            yield block(f"{_who(entry, channel)}: {module.type} is not a DC source in v1 (no module spec)",
                        subject=entry.role, source=env.code("b1500_test_agent.driver.modules.MODULE_SPECS"),
                        observed=module.type, limit="an SMU")
            continue
        problems = violations(spec, entry.max_abs_v, entry.max_abs_i, source="V")
        if not problems:
            continue
        if entry.max_abs_v > spec.max_abs_v:
            observed, limit = entry.max_abs_v, spec.max_abs_v
        elif entry.max_abs_i > spec.max_abs_i:
            observed, limit = entry.max_abs_i, spec.max_abs_i
        else:
            observed = f"{entry.max_abs_v:g} V @ {entry.max_abs_i:g} A"
            limit = ", ".join(f"{v:g} V @ {i:g} A" for v, i in spec.v_source_envelope)
        yield block(f"{_who(entry, channel)}: " + "; ".join(problems), subject=entry.role,
                    source=env.code(f"b1500_test_agent.driver.modules.MODULE_SPECS[{spec.module_type}] "
                                    f"({spec.envelope_source})"),
                    observed=observed, limit=limit)
    if any(b.gndu for b in ctx.plan.binding.roles.values()):
        gndu = module_spec("GNDU")
        if total_i > gndu.max_abs_i:
            yield block(f"the GNDU would sink up to {total_i:g} A (sum of compliances), above its "
                        f"{gndu.max_abs_i:g} A", subject="GNDU",
                        source=env.code(f"b1500_test_agent.driver.modules.MODULE_SPECS[GNDU] "
                                        f"({gndu.envelope_source})"),
                        observed=total_i, limit=gndu.max_abs_i)


# -- R-LIM-02 / R-LIM-03 ---------------------------------------------------------------------------------------------


@rule("R-LIM-02", {"plan"})
def hard_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every envelope channel stays within ``policy.hard_limits`` and never above the code ceiling."""
    hard = ctx.policy.hard_limits
    checks = (
        ("|V|", "V", "max_abs_v", hard.max_abs_voltage_v, HARD_CEILING_V, "max_abs_voltage_v", _CEILING_V_SYMBOL),
        ("|Icomp|", "A", "max_abs_i", hard.max_abs_compliance_a, HARD_CEILING_A, "max_abs_compliance_a",
         _CEILING_A_SYMBOL),
    )
    for label, unit, attr, policy_limit, ceiling, field, symbol in checks:
        limit = min(policy_limit, ceiling)
        source = env.policy(f"hard_limits.{field}") if policy_limit <= ceiling else env.code(symbol)
        for channel, entry in _envelope(ctx):
            value = getattr(entry, attr)
            if not math.isfinite(value):
                yield block(f"{_who(entry, channel)}: {label} is not finite", subject=entry.role, source=source,
                            observed=repr(value), limit=limit)
            elif value > limit:
                yield block(f"{_who(entry, channel)}: {label} {value:g} {unit} exceeds the hard limit {limit:g} "
                            f"{unit}", subject=entry.role, source=source, observed=value, limit=limit)


@rule("R-LIM-03", {"plan"})
def soft_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Above ``policy.soft_limits`` needs confirmation (``soft_limit``)."""
    soft = ctx.policy.soft_limits
    for label, unit, attr, limit, field in (
        ("|V|", "V", "max_abs_v", soft.voltage_v, "voltage_v"),
        ("|Icomp|", "A", "max_abs_i", soft.compliance_a, "compliance_a"),
    ):
        for channel, entry in _envelope(ctx):
            value = getattr(entry, attr)
            if value > limit:
                yield confirm("soft_limit", f"{_who(entry, channel)}: {label} {value:g} {unit} is above the soft "
                              f"limit {limit:g} {unit}", subject=entry.role,
                              source=env.policy(f"soft_limits.{field}"), observed=value, limit=limit)


# -- R-DUT-01 --------------------------------------------------------------------------------------------------------


@rule("R-DUT-01", {"plan"})
def dut_envelope(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """A recipe with DUT roles needs an existing DUT profile that describes every driven terminal; levels outside
    the profile's envelope need confirmation (``dut_envelope``)."""
    recipe = ctx.recipe
    if not recipe.roles:
        return
    name = ctx.plan.request.dut_profile
    if name is None:
        yield block(f"recipe {recipe.id} drives DUT terminals but no DUT profile was given; ask the human "
                    "(never invent a DUT profile)", source=env.plan("request.dut_profile"), observed=None,
                    limit="a DUT profile")
        return
    dut = ctx.dut
    if dut is None:
        yield block(f"DUT profile {name!r} not found", source=env.dut(name), observed=name,
                    limit="an existing DUT profile")
        return
    if recipe.device_types and dut.device_type not in recipe.device_types:
        yield warn(f"DUT {dut.name} is a {dut.device_type}; recipe {recipe.id} is meant for "
                   f"{', '.join(recipe.device_types)}", source=env.dut(dut.name, "device_type"),
                   observed=dut.device_type, limit=", ".join(recipe.device_types))
    binding = ctx.plan.binding.roles
    for channel, entry in _envelope(ctx):
        bound = binding.get(entry.role)
        terminal = bound.terminal if bound is not None else entry.role
        limits = dut.terminals.get(terminal)
        if limits is None:
            yield block(f"DUT profile {dut.name} has no envelope for driven terminal {terminal!r}",
                        subject=terminal, source=env.dut(dut.name, "terminals"), observed=terminal,
                        limit=", ".join(sorted(dut.terminals)))
            continue
        for label, unit, value, limit, field in (
            ("|V|", "V", entry.max_abs_v, limits.max_abs_v, "max_abs_v"),
            ("|Icomp|", "A", entry.max_abs_i, limits.max_abs_i, "max_abs_i"),
        ):
            if value > limit:
                yield confirm("dut_envelope", f"{terminal} (channel {channel}): {label} {value:g} {unit} is outside "
                              f"DUT {dut.name}'s envelope {limit:g} {unit}", subject=terminal,
                              source=env.dut(dut.name, f"terminals.{terminal}.{field}"), observed=value, limit=limit)


# -- R-COMP-01 -------------------------------------------------------------------------------------------------------


@rule("R-COMP-01", {"plan"})
def explicit_compliance(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every connected channel has a non-zero compliance in the envelope; sourcing roles set it explicitly
    (role setting ``icomp``)."""
    recipe, plan = ctx.recipe, ctx.plan
    for role_name, spec in sorted(recipe.roles.items()):
        bound = plan.binding.roles.get(role_name)
        if bound is None or bound.channel is None:
            continue
        channel = bound.channel
        entry = _channel_envelope(ctx, channel)
        if entry is None:
            yield block(f"{role_name} (channel {channel}) is connected but has no compiled envelope, hence no "
                        "compliance", subject=role_name, source=env.plan("envelope.channels"), observed=None,
                        limit="non-zero compliance")
            continue
        if spec.function in SOURCING_FUNCTIONS:
            value = _setting_value(spec, COMPLIANCE_SETTING, plan.resolved_params)
            if value is None or not _is_real(value) or value == 0:
                yield block(f"{role_name} forces voltage without an explicit non-zero compliance "
                            f"(settings.{COMPLIANCE_SETTING} = {value!r})", subject=role_name,
                            source=env.recipe(recipe, f"roles.{role_name}.settings.{COMPLIANCE_SETTING}"),
                            observed=_scalar(value), limit="non-zero compliance")
        if entry.max_abs_i <= 0:
            yield block(f"{role_name} (channel {channel}): compliance is zero", subject=role_name,
                        source=env.plan(f"envelope.channels.{channel}.max_abs_i"), observed=entry.max_abs_i,
                        limit="> 0")


# -- R-IL-01 ---------------------------------------------------------------------------------------------------------


@rule("R-IL-01", {"plan", "pre_execute"})
def interlock_closed(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """|V| above ``interlock.required_above_v`` needs a working, closed interlock: the station profile records one,
    status-byte bit 3 is clear and no ``ERRX?`` 202/203 is pending (ATV-10 fallback). Unreachable with the default
    policy because R-LIM-02 caps |V| at 42 V."""
    threshold = ctx.policy.interlock.required_above_v
    v_max = ctx.plan.envelope.max_abs_v
    if v_max <= threshold:
        return
    need = f"|V| {v_max:g} V above {threshold:g} V needs a closed interlock"
    available = ctx.station.interlock.available
    if available is not True:
        yield block(f"{need}, but the station profile does not record a working interlock",
                    source=env.station("interlock.available"), observed=available, limit=True)
    live = ctx.live
    if live is None:
        if env.phase == "pre_execute":
            yield block(f"{need}, but no live status was read", source=env.live("status_byte"), observed=None,
                        limit="bit 3 clear")
        return
    if live.status_byte is None:
        yield block(f"{need}, but the status byte was not read", source=env.live("status_byte"), observed=None,
                    limit="bit 3 clear")
    elif live.status_byte.interlock_open:
        yield block(f"{need}; status byte bit 3 (interlock open) is set", source=env.live("status_byte.bit3"),
                    observed=live.status_byte.value, limit="bit 3 clear")
    for error in interlock_errors(live.errors):
        yield block(f"{need}; instrument error {error.code} ({INTERLOCK_ERRORS[error.code]}) reports an interlock "
                    "refusal", source=env.live("errors"), observed=error.code, limit="no error 202/203")


def interlock_errors(errors: Iterable[InstrumentError]) -> list[InstrumentError]:
    """The interlock errors (202, 203) among drained ``ERRX?`` entries, first occurrence of each code.

    Measurement kinds call this after ``CN`` (ATV-10 fallback) and abort on any hit."""
    found: dict[int, InstrumentError] = {}
    for error in errors:
        if error.code in INTERLOCK_ERRORS:
            found.setdefault(error.code, error)
    return [found[code] for code in sorted(found)]


# -- R-RUN-01 --------------------------------------------------------------------------------------------------------


@rule("R-RUN-01", {"plan"})
def run_size(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Points and estimated duration within ``policy.run_limits``."""
    limits, estimate = ctx.policy.run_limits, ctx.plan.estimate
    if estimate.points > limits.max_points:
        yield block(f"{estimate.points} points exceed the run limit {limits.max_points}",
                    source=env.policy("run_limits.max_points"), observed=estimate.points, limit=limits.max_points)
    if estimate.duration_s > limits.max_sync_run_s:
        yield block(f"estimated {estimate.duration_s:g} s exceeds the synchronous run limit "
                    f"{limits.max_sync_run_s:g} s", source=env.policy("run_limits.max_sync_run_s"),
                    observed=estimate.duration_s, limit=limits.max_sync_run_s)


# -- R-ALWAYS-01 -----------------------------------------------------------------------------------------------------


@rule("R-ALWAYS-01", {"plan"})
def always_confirm(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Recipe ``always_confirm`` reasons (destructive, system self-test/self-calibration)."""
    recipe = ctx.recipe
    for reason in recipe.always_confirm:
        yield confirm(reason, f"recipe {recipe.id} always needs confirmation ({reason})",
                      source=env.recipe(recipe, "always_confirm"), observed=reason, limit=None)


# -- R-ERRX-01 -------------------------------------------------------------------------------------------------------


@rule("R-ERRX-01", {"plan", "pre_execute"})
def preexisting_errors(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Pre-existing ``ERRX?`` entries drained by the snapshot are recorded as warnings."""
    if ctx.live is None:
        return
    for error in ctx.live.errors:
        yield warn(f"pre-existing instrument error {error.code}: {error.message or '(no message)'} "
                   "(drained and recorded)", source=env.live("errors"), observed=error.code, limit=0)


# -- R-CAL-01 --------------------------------------------------------------------------------------------------------


@rule("R-CAL-01", {"pre_execute"})
def calibration_recorded(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Auto-calibration state and the last self-calibration are recorded; unknown → warn."""
    cal = ctx.calibration
    auto = None if cal is None else cal.auto_calibration
    if auto is None:
        yield warn("auto-calibration state was not read", source=env.live("auto_calibration"), observed=None,
                   limit="recorded")
    else:
        yield info(f"auto-calibration is {'on' if auto else 'off'}", source=env.live("auto_calibration"),
                   observed=auto)
    last = None if cal is None else cal.last_self_calibration
    if last is None:
        yield warn("no completed self-calibration is recorded (recipe system.self_cal)", source=env.runs_index(),
                   observed=None, limit="recorded")
    else:
        run = cal.last_self_calibration_run if cal is not None else None
        yield info(f"last self-calibration {last.isoformat()}" + (f" (run {run})" if run else ""),
                   source=env.runs_index(), observed=last.isoformat())


# -- R-CORR-01 -------------------------------------------------------------------------------------------------------


@rule("R-CORR-01", {"plan"})
def cmu_correction(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Capacitance (MFCMU) plans need performed phase compensation, open and short corrections whose frequency
    ranges cover every frequency parameter. Declared for completeness: CMU kinds are ``not_implemented`` in v1."""
    recipe, plan = ctx.recipe, ctx.plan
    uses_cmu = (
        recipe.kind.startswith("cmu")
        or any(b.module_type == "MFCMU" for b in plan.binding.roles.values())
        or any("MFCMU" in r.module_types for r in recipe.roles.values())
    )
    if not uses_cmu:
        return
    corrections = ctx.station.corrections.cmu
    if corrections is None:
        yield block("capacitance measurement without an MFCMU correction record",
                    source=env.station("corrections.cmu"), observed=None, limit="performed corrections")
        return
    freqs: list[float] = []
    for quantity in plan.resolved_params.values():
        if quantity.unit == "Hz":
            values = quantity.value if isinstance(quantity.value, list) else [quantity.value]
            freqs.extend(float(v) for v in values if _is_real(v))
    for name in CMU_CORRECTIONS:
        record = getattr(corrections, name)
        if record.status != "performed":
            yield block(f"MFCMU {name} correction is {record.status}", subject=name,
                        source=env.station(f"corrections.cmu.{name}.status"), observed=record.status,
                        limit="performed")
            continue
        if name == "phase_compensation" or not freqs:
            continue
        span = record.frequency_range_hz
        outside = [f for f in sorted(set(freqs)) if span is None or not span[0] <= f <= span[1]]
        if outside:
            yield block(f"MFCMU {name} correction does not cover {outside[0]:g} Hz", subject=name,
                        source=env.station(f"corrections.cmu.{name}.frequency_range_hz"), observed=outside[0],
                        limit=None if span is None else f"{span[0]:g}..{span[1]:g}")


# -- R-QUAL-* (post-run) ---------------------------------------------------------------------------------------------


def quality_findings(counts: Mapping[str, int], trust: TrustPolicy, *, source: str) -> list[RuleFinding]:
    """R-QUAL-* classification of per-point status counts (letter → number of points) after a run.

    R-QUAL-01 (info) records the per-class counts; R-QUAL-02 (warn) flags ``limited`` points, which fits exclude;
    R-QUAL-03 (warn) flags ``untrusted`` points, from which extraction is refused unless forced (then flagged).
    Unknown letters classify as untrusted (``TrustPolicy.classify``). Report only; never changes a tier.
    """
    by_class: dict[str, dict[str, int]] = {"ok": {}, "limited": {}, "untrusted": {}}
    for letter, count in sorted(counts.items()):
        if count:
            by_class[trust.classify(letter)][letter] = count
    totals = {level: sum(letters.values()) for level, letters in by_class.items()}
    total = sum(totals.values())

    def detail(level: str) -> str:
        return ", ".join(f"{letter} {n}" for letter, n in by_class[level].items())

    findings = [
        RuleFinding(rule_id="R-QUAL-01", severity="info",
                    message=f"{total} points: {totals['ok']} ok, {totals['limited']} limited, "
                            f"{totals['untrusted']} untrusted", observed=total, source=source)
    ]
    if totals["limited"]:
        findings.append(RuleFinding(rule_id="R-QUAL-02", severity="warn",
                                    message=f"{totals['limited']} limited points ({detail('limited')}) are excluded "
                                            "from fits", observed=totals["limited"], limit=0, source=source))
    if totals["untrusted"]:
        findings.append(RuleFinding(rule_id="R-QUAL-03", severity="warn",
                                    message=f"{totals['untrusted']} untrusted points ({detail('untrusted')}): "
                                            "extraction is refused unless forced, and then flagged",
                                    observed=totals["untrusted"], limit=0, source=source))
    return findings
