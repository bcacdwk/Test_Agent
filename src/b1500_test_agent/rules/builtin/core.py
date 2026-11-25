"""Built-in rules: configuration, fault latch, recipe status, parameters, pin map and inventory (blueprint 2.8 / v1
4.2 table rows R-CFG-01, R-FAULT-01, R-REC-01, R-PARAM-01, R-PIN-01, R-PIN-02, R-INV-01, in table order)."""

from __future__ import annotations

from collections.abc import Iterator

from b1500_test_agent.config import CORE_ITEMS
from b1500_test_agent.models.plan import BoundChannel
from b1500_test_agent.models.recipe import CMU_SIDES, FUNCTION_INPUT, FUNCTION_MODULE_TYPES, RoleSpec, target_cmu_side
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.station import cmu_side, switch_target
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
    if ctx.station != cfg.planning_station():
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
    """Recipe status for the backend: a recipe whose kind has no code path on the backend blocks; on visa
    ``draft``/``sim_validated``/``generic.*`` need confirmation; on sim ``draft`` warns."""
    recipe, status = ctx.recipe, ctx.recipe.status
    if not ctx.runnable:
        yield block(f"recipe {recipe.id}: kind {recipe.kind} has no code path on backend {ctx.backend} (recipe "
                    f"status {status}); it cannot run here", source=env.recipe(recipe, "kind"), observed=recipe.kind,
                    limit=f"a kind implemented on {ctx.backend}")
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
    """Requested and resolved parameters match the recipe's ``ParamSpec`` type, choices and range; every ``file``
    parameter was read by the planner (exists, inside its folder, at most ``FILE_PARAM_MAX_BYTES``)."""
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
        if spec.type == "file" and problem is None:
            record = ctx.plan.files.get(name)
            if record is None or record.path != quantity.value:
                yield block(f"file parameter {name} = {quantity.value!r} was not read by the planner", subject=name,
                            source=env.plan(f"files.{name}"), observed=scalar(quantity.value), limit="a read file")
            elif record.problem is not None:
                yield block(f"file parameter {name}: {record.problem}", subject=name,
                            source=env.plan(f"files.{name}"), observed=record.path,
                            limit="an existing CSV of at most 1 MiB in its folder")
    for name in sorted(set(ctx.plan.files) - set(specs)):
        yield block(f"the plan records file {name!r}, which is not a recipe parameter", subject=name,
                    source=env.plan(f"files.{name}"), observed=name, limit=declared)


# -- R-PIN-01 --------------------------------------------------------------------------------------------------------


@rule("R-PIN-01", {"plan"})
def pin_map_complete(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """The pin map exists, maps every non-optional role, uses existing channels once each with an allowed module
    type (``low_current`` needs an HRSMU), and the plan binding and envelope agree with it. MFCMU roles use an MFCMU
    side target (``7H`` for ``cmu_high``, ``7L`` for ``cmu_low``) and only they may; a role with ``bind: cmu_side``
    (correction recipes) uses the pin map's terminal on its MFCMU side, whatever its name; a role with ``terminal``
    (a second role on one pad, kind ``pulse_read``) uses the terminal it names. A terminal wired through a
    switch (``SEL1.OUT1``) needs a declared, not absent switch that can connect the role's resource to that output, a
    known channel on that input, and a plan that applies the route (``envelope.routes``); kinds that route no switch
    therefore cannot use such a terminal. Presence on hardware, Kelvin paths and rest states are R-ROUTE-01."""
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
    seen: dict[tuple[int, str], str] = {}
    for role_name, spec in sorted(recipe.roles.items()):
        yield from _check_role(ctx, env, role_name, spec, binding.get(role_name), seen)
    bound_channels: dict[int, list[str]] = {}
    for role, b in sorted(binding.items()):
        if b.channel is not None and role in recipe.roles:
            bound_channels.setdefault(norm_channel(b.channel), []).append(role)
    for channel, entry in envelope_items(ctx):
        owners = bound_channels.get(norm_channel(channel), [])
        if entry.role not in owners:  # both MFCMU sides share one channel; its envelope belongs to either role
            yield block(f"envelope channel {channel} (role {entry.role}) is not the channel bound to that role",
                        subject=entry.role, source=env.plan(f"envelope.channels.{channel}"), observed=channel,
                        limit=None if not owners else "role " + ", ".join(owners))


def _check_role(ctx: RuleContext, env: RuleEnv, role_name: str, spec: RoleSpec, bound: BoundChannel | None,
                seen: dict[tuple[int, str], str]) -> Iterator[Finding]:
    assert ctx.pin_map is not None
    pin_map, station, recipe = ctx.pin_map, ctx.station, ctx.recipe
    terminal = spec.terminal or role_name  # a second role on one pad names its terminal (RoleSpec.terminal, WP9.4)
    if spec.bind == "cmu_side":  # the terminal on the role's MFCMU side, whatever its name (WP8.2)
        side = CMU_SIDES[spec.function]
        terminal = spec.pin_terminal(role_name, pin_map.terminals, station) or ""
        if not terminal:
            if not spec.optional:
                yield block(f"role {role_name} ({spec.function}) binds to the pin map's MFCMU {side} side, but pin "
                            f"map {pin_map.name} wires no terminal to an MFCMU {side} side", subject=role_name,
                            source=env.pin_map(pin_map.name, "terminals"), observed=None,
                            limit=f"a <ch>{side} target")
            elif bound is not None:
                yield block(f"optional role {role_name} is bound although the pin map has no MFCMU {side} side",
                            subject=role_name, source=env.pin_map(pin_map.name, "terminals"), observed=None,
                            limit=None)
            return
    terminal_src = env.pin_map(pin_map.name, f"terminals.{terminal}")
    target = pin_map.terminals.get(terminal)
    if target is None:
        if spec.optional:
            if bound is not None:
                yield block(f"optional role {role_name} is bound although the pin map leaves it unconnected",
                            subject=role_name, source=terminal_src, observed=None, limit=None)
            return
        why = "has no terminal" if terminal not in pin_map.terminals else "leaves the terminal unconnected"
        yield block(f"role {role_name} is not mapped: pin map {pin_map.name} {why} {terminal!r}",
                    subject=role_name, source=terminal_src, observed=None, limit="a channel, GNDU or switch output")
        return
    if bound is None:
        yield block(f"role {role_name} is mapped in pin map {pin_map.name} but missing from the plan binding",
                    subject=role_name, source=env.plan(f"binding.roles.{role_name}"), observed=None,
                    limit=str(target))
        return
    if bound.terminal != terminal:
        yield block(f"role {role_name} is bound to terminal {bound.terminal!r}", subject=role_name,
                    source=env.plan(f"binding.roles.{role_name}.terminal"), observed=bound.terminal,
                    limit=terminal)
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
    side = ""
    if switch_target(target) is not None:
        findings, resolved = _check_switch_role(ctx, env, role_name, spec, bound, str(target), terminal_src)
        yield from findings
        if resolved is None:
            return
        channel = resolved
        expected = CMU_SIDES.get(spec.function)
        if expected is not None:  # an MFCMU role through an SCUU output (WP8.3): CMUH = output 1, CMUL = output 2
            side = target_cmu_side(target, station) or ""
            if side != expected:
                yield block(f"role {role_name} ({spec.function}) needs the MFCMU {expected} side, but {target} is "
                            f"{'the ' + side + ' side' if side else 'no MFCMU side'}", subject=role_name,
                            source=terminal_src, observed=str(target), limit=f"an SCUU output on the {expected} side")
    elif (cmu := cmu_side(target)) is not None:
        channel, side = cmu
        expected = CMU_SIDES.get(spec.function)
        if expected is None:
            yield block(f"role {role_name} ({spec.function}) cannot use the MFCMU side {target}", subject=role_name,
                        source=terminal_src, observed=str(target), limit="a channel, GNDU or switch output")
        elif expected != side:
            yield block(f"role {role_name} ({spec.function}) needs the MFCMU {expected} side, the pin map gives "
                        f"{target}", subject=role_name, source=terminal_src, observed=str(target),
                        limit=f"{channel}{expected}")
        if (bound.channel, bound.cmu_side) != (channel, side):
            yield block(f"role {role_name}: the plan binding differs from the pin map ({target})", subject=role_name,
                        source=terminal_src, observed=bound.channel, limit=str(target))
    else:
        channel = int(target)  # type: ignore[arg-type]
        if spec.function in CMU_SIDES:
            yield block(f"role {role_name} ({spec.function}) needs an MFCMU side target "
                        f"({channel}{CMU_SIDES[spec.function]})", subject=role_name, source=terminal_src,
                        observed=channel, limit=f"{channel}{CMU_SIDES[spec.function]}")
        if bound.channel is None or norm_channel(bound.channel) != norm_channel(channel) or bound.via is not None:
            yield block(f"role {role_name}: the plan binding (channel {bound.channel}) differs from the pin map "
                        f"(channel {channel})", subject=role_name, source=terminal_src, observed=bound.channel,
                        limit=channel)
    previous = seen.get((norm_channel(channel), side))
    if previous is not None:
        yield block(f"channel {channel}{side} is mapped to both {previous} and {role_name}", subject=role_name,
                    source=terminal_src, observed=channel, limit="one role per channel")
    seen[(norm_channel(channel), side)] = role_name
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
    allowed = list(spec.module_types) or sorted(FUNCTION_MODULE_TYPES[spec.function])
    if module.type not in allowed:
        yield block(f"role {role_name} needs one of {', '.join(allowed)}; channel {channel} is a {module.type}",
                    subject=role_name, source=env.recipe(recipe, f"roles.{role_name}.module_types"),
                    observed=module.type, limit=", ".join(allowed))
    if spec.low_current and module.type != "HRSMU":
        yield block(f"role {role_name} is low_current and needs an HRSMU; channel {channel} is a {module.type}",
                    subject=role_name, source=env.recipe(recipe, f"roles.{role_name}.low_current"),
                    observed=module.type, limit="HRSMU")


def _check_switch_role(ctx: RuleContext, env: RuleEnv, role_name: str, spec: RoleSpec, bound: BoundChannel,
                       target: str, terminal_src: str) -> tuple[list[Finding], int | None]:
    """Findings for a role whose terminal is a switch output, and the channel wired to the role's input of that
    output (``None`` when the route does not resolve to one)."""
    ref = switch_target(target)
    assert ref is not None
    switch_id, output = ref
    route = Route(switch=switch_id, output=output, state=FUNCTION_INPUT[spec.function])
    switch = ctx.station.switch(switch_id)
    if switch is None or output not in switch.ports:
        problem = ctx.station.target_problem(target) or f"{target} does not resolve"
        return [block(f"role {role_name}: {problem}", subject=role_name, source=env.station("switches"),
                      observed=target, limit="a declared switch output")], None
    index = next(i for i, s in enumerate(ctx.station.switches) if s.id == switch_id)
    switch_src = env.station(f"switches[{index}]")
    found: list[Finding] = []
    if bound.via != route:
        found.append(block(f"role {role_name}: the plan binding ({bound.via}) differs from the pin map ({route})",
                           subject=role_name, source=terminal_src, observed=str(bound.via), limit=str(route)))
    if switch.present is False:
        found.append(block(f"role {role_name}: switch {switch_id} is declared absent", subject=role_name,
                           source=f"{switch_src}.present", observed=False, limit=True))
    if not switch.allows(output, route.state):
        found.append(block(f"role {role_name} ({spec.function}) needs {target} -> {route.state}, which a "
                           f"{switch.kind} cannot connect", subject=role_name, source=f"{switch_src}.kind",
                           observed=switch.kind, limit=", ".join(sorted(switch.states()))))
        return found, None
    channel = switch.input_channel(output, route.state)
    if channel is None:
        state = "unknown (null)" if route.state in switch.ports[output].inputs else "not connected"
        found.append(block(f"role {role_name}: the {route.state} input of {target} is {state} in the station "
                           "profile; a human records the wiring", subject=role_name,
                           source=f"{switch_src}.ports.{output}.inputs.{route.state}", observed=None,
                           limit="a channel"))
        return found, None
    if bound.channel is None or norm_channel(bound.channel) != norm_channel(channel):
        found.append(block(f"role {role_name}: the plan binding (channel {bound.channel}) differs from the "
                           f"{route.state} input of {target} (channel {channel})", subject=role_name,
                           source=terminal_src, observed=bound.channel, limit=channel))
    if route not in ctx.plan.envelope.routes:
        found.append(block(f"role {role_name} reaches its terminal only through {route}, but the plan sets no such "
                           f"route (kind {ctx.recipe.kind} does not route switches)", subject=role_name,
                           source=env.plan("envelope.routes"), observed=None, limit=str(route)))
    return found, channel


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


