"""Built-in rules: configuration, fault latch, recipe status, parameters, pin map and inventory (blueprint 2.8 / v1
4.2 table rows R-CFG-01, R-FAULT-01, R-REC-01, R-PARAM-01, R-PIN-01, R-PIN-02, R-INV-01, in table order)."""

from __future__ import annotations

from collections.abc import Iterator

from b1500_test_agent.config import CORE_ITEMS
from b1500_test_agent.models.plan import BoundChannel
from b1500_test_agent.models.recipe import RoleSpec
from b1500_test_agent.models.station import SMU_TYPES
from b1500_test_agent.rules.builtin.common import (
    CEILING_A_SYMBOL,
    CEILING_V_SYMBOL,
    envelope_items,
    module_index,
    norm_channel,
    param_problem,
    scalar,
)
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, rule, warn
from b1500_test_agent.rules.tiers import HARD_CEILING_A, HARD_CEILING_V

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
        ("max_abs_voltage_v", hard.max_abs_voltage_v, HARD_CEILING_V, CEILING_V_SYMBOL, "V"),
        ("max_abs_compliance_a", hard.max_abs_compliance_a, HARD_CEILING_A, CEILING_A_SYMBOL, "A"),
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
        problem = param_problem(spec, quantity.value)
        if problem is not None:
            text, field, observed, limit = problem
            yield block(f"parameter {name} = {quantity.value!r} {text}", subject=name,
                        source=env.recipe(recipe, f"params.{name}.{field}"), observed=scalar(observed),
                        limit=scalar(limit))
        if quantity.unit != spec.unit:
            yield block(f"parameter {name} has unit {quantity.unit} but the recipe declares {spec.unit}",
                        subject=name, source=env.recipe(recipe, f"params.{name}.unit"), observed=quantity.unit,
                        limit=spec.unit)
        if name in requested and requested[name] != quantity.value:
            yield block(f"parameter {name}: resolved value {quantity.value!r} differs from the requested "
                        f"{requested[name]!r}", subject=name, source=env.plan(f"resolved_params.{name}"),
                        observed=scalar(quantity.value), limit=scalar(requested[name]))


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
        norm_channel(b.channel): role for role, b in binding.items() if b.channel is not None and role in recipe.roles
    }
    for channel, entry in envelope_items(ctx):
        owner = bound_channels.get(norm_channel(channel))
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
    if bound.channel is None or norm_channel(bound.channel) != norm_channel(channel):
        yield block(f"role {role_name}: the plan binding (channel {bound.channel}) differs from the pin map "
                    f"(channel {channel})", subject=role_name, source=terminal_src, observed=bound.channel,
                    limit=channel)
    previous = seen.get(norm_channel(channel))
    if previous is not None:
        yield block(f"channel {channel} is mapped to both {previous} and {role_name}", subject=role_name,
                    source=terminal_src, observed=channel, limit="one role per channel")
    seen[norm_channel(channel)] = role_name
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
                    source=env.station(f"modules[{module_index(ctx, module)}]"), observed=bound.module_model,
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
                        source=env.station(f"modules[{module_index(ctx, module)}].model"), observed=installed,
                        limit=module.model)


