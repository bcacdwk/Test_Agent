"""Built-in rules of the switch accessories (blueprint v2 2.8 rows R-ROUTE-01, R-ROUTE-02, R-ASU-01, in table order).

The plan's routes are ``envelope.routes`` (what the ``OutputGuard`` admits besides each switch's ``rest`` state),
``routes_by_phase`` (what the kind applies, phase by phase, in order) and each role's ``via`` (the route its terminal
needs). R-PIN-01 already checks a role's own switch target against the pin map (declared, not absent, the state its
resource needs, wiring recorded, route in the envelope); these rules check every route of the plan as a whole, the
live switch states before execution, the certainty of the topology and the ASU current ranges.

Facts (``models/routing.py``): ``ERSSP`` 0 = open, 1 = SMU, 2 = PGU, 3 = PGU open; the PGU-open state exists only on
CH 1 of each 16440A (ports 0 and 2); a selector's SMU path carries Force only (Sense open) (PG p154 (2-66)); after
``*RST`` or power-on every port is open and ``ERMOD 1`` must precede ``ERSSP`` (PG p433 (4-115) "ERSSP").
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from b1500_test_agent.driver.modules import SPEC_SYMBOL, module_spec
from b1500_test_agent.models.routing import Route, SwitchSpec
from b1500_test_agent.rules.builtin.common import (
    MEASURE_RANGE_SETTING,
    PlanRoute,
    is_real,
    plan_routes,
    scalar,
    setting_value,
)
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, rule


def _switch_index(ctx: RuleContext, switch_id: str) -> int:
    return next(i for i, s in enumerate(ctx.station.switches) if s.id == switch_id)


def _involved(ctx: RuleContext, routes: list[PlanRoute]) -> list[SwitchSpec]:
    ids = {r.route.switch for r in routes}
    return [s for s in ctx.station.switches if s.id in ids]


# -- R-ROUTE-01 ------------------------------------------------------------------------------------------------------


@rule("R-ROUTE-01", {"plan", "pre_execute"})
def routes_valid(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every route of the plan resolves: a declared switch and output that can take the state (``pgu_open`` only on
    selector CH 1, ports 0 and 2), on visa a switch recorded ``present: true``; phases apply only routes of
    ``envelope.routes`` (or a switch's ``rest``) and name every allowed route; no switch output is driven by two
    sources (two non-rest states) in one phase; Kelvin roles never go through a selector (Force only). Pre-execute:
    the live state of every output of the involved switches and of every declared selector port (``ERSSP?`` after
    ``ERMOD 1``) was read and is its ``rest`` state."""
    routes = plan_routes(ctx)
    if not routes:
        return
    if env.phase == "plan":
        yield from _resolve(ctx, env, routes)
        yield from _phases(ctx, env)
        yield from _kelvin(ctx, env)
    if env.phase == "pre_execute":
        yield from _live_rest(ctx, env, routes)


def _resolve(ctx: RuleContext, env: RuleEnv, routes: list[PlanRoute]) -> Iterator[Finding]:
    seen: set[Route] = set()
    for item in routes:
        route = item.route
        if route in seen:
            continue
        seen.add(route)
        switch = ctx.station.switch(route.switch)
        if switch is None:
            declared = ", ".join(s.id for s in ctx.station.switches) or "none"
            yield block(f"route {route}: switch {route.switch} is not declared", source=env.station("switches"),
                        observed=str(route), limit=declared)
            continue
        where = env.station(f"switches[{_switch_index(ctx, switch.id)}]")
        if route.output not in switch.ports:
            yield block(f"route {route}: {switch.id} has no output {route.output}", source=f"{where}.ports",
                        observed=route.output, limit=", ".join(switch.ports))
            continue
        if not switch.allows(route.output, route.state):
            port = switch.ports[route.output].index
            why = (f"the PGU-open state exists only on selector CH 1 (ports 0, 2), not port {port}"
                   if route.state == "pgu_open" and route.state in switch.states() else
                   f"a {switch.kind} cannot take state {route.state}")
            yield block(f"route {route}: {why}", source=f"{where}.ports.{route.output}", observed=route.state,
                        limit=", ".join(sorted(switch.states())))
        if ctx.backend == "visa" and switch.present is not True:
            state = "unknown" if switch.present is None else "declared absent"
            yield block(f"route {route}: switch {switch.id} is {state}; on hardware a human records present: true "
                        "(bring-up stage L7)", source=f"{where}.present", observed=switch.present, limit=True)


def _phases(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    allowed = ctx.plan.envelope.routes
    phases = ctx.plan.routes_by_phase
    if allowed and not phases:
        yield block("the plan allows switch routes but names no phase that applies them",
                    source=env.plan("routes_by_phase"), observed=None, limit="routes per phase")
    used: set[Route] = set()
    for phase, routes in sorted(phases.items()):
        states: dict[tuple[str, str], set[str]] = {}
        for index, route in enumerate(routes):
            used.add(route)
            switch = ctx.station.switch(route.switch)
            rest = switch.rest if switch is not None else None
            if route not in allowed and route.state != rest:
                yield block(f"phase {phase} applies {route}, which is neither an allowed route of the plan nor the "
                            "switch's rest state", source=env.plan(f"routes_by_phase.{phase}[{index}]"),
                            observed=str(route), limit="envelope.routes")
            if route.state not in ("open", rest):
                states.setdefault((route.switch, route.output), set()).add(route.state)
        for (switch_id, output), driven in sorted(states.items()):
            if len(driven) > 1:
                yield block(f"phase {phase}: {switch_id}.{output} is driven by {len(driven)} sources "
                            f"({', '.join(sorted(driven))}); one terminal takes one source per phase",
                            source=env.plan(f"routes_by_phase.{phase}"), observed=", ".join(sorted(driven)),
                            limit="one source")
    if phases:
        for route in sorted(allowed - used, key=Route.sort_key):
            yield block(f"allowed route {route} is applied in no phase", source=env.plan("envelope.routes"),
                        observed=str(route), limit="a phase that applies it")


def _kelvin(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    for role, spec in sorted(ctx.recipe.roles.items()):
        bound = ctx.plan.binding.roles.get(role)
        if not spec.kelvin or bound is None or bound.via is None:
            continue
        switch = ctx.station.switch(bound.via.switch)
        if switch is not None and switch.kind == "selector_16440a":
            yield block(f"role {role} is a Kelvin role but reaches its terminal through selector {switch.id}, whose "
                        "SMU path carries Force only (Sense open)", subject=role,
                        source=env.recipe(ctx.recipe, f"roles.{role}.kelvin"), observed=str(bound.via),
                        limit="a direct SMU connection")


def _live_rest(ctx: RuleContext, env: RuleEnv, routes: list[PlanRoute]) -> Iterator[Finding]:
    live = ctx.live
    if live is None:
        yield block("no live snapshot: the switch states cannot be checked", source=env.live("snapshot"),
                    observed=None, limit="a live snapshot")
        return
    states = live.switch_states
    if states is None:
        yield block("the switch states were not read (selector, SCUU, ASU and RSU states)",
                    source=env.live("switch_states"), observed=None, limit="every declared output at rest")
        return
    involved = {s.id for s in _involved(ctx, routes)}
    for switch in ctx.station.switches:
        if switch.id not in involved and not (switch.kind == "selector_16440a" and switch.present is True):
            continue
        for output in switch.ports:
            target = f"{switch.id}.{output}"
            state = states.get(target)
            if state is None:
                yield block(f"{target}: the live state was not readable", source=env.live(f"switch_states.{target}"),
                            observed=None, limit=switch.rest)
            elif state != switch.rest:
                yield block(f"{target} is {state}, not its rest state {switch.rest} (a previous run or a human left "
                            "it switched; run safe_shutdown)", source=env.live(f"switch_states.{target}"),
                            observed=state, limit=switch.rest)


# -- R-ROUTE-02 ------------------------------------------------------------------------------------------------------


@rule("R-ROUTE-02", {"plan"})
def topology_verified(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """A plan that routes through a switch recorded ``certainty: unverified``, or through a switch output whose DUT
    side comes from an ``unverified`` pin map, needs confirmation (``unverified_topology``)."""
    routes = plan_routes(ctx)
    if not routes:
        return
    for switch in _involved(ctx, routes):
        if switch.certainty == "unverified":
            yield confirm("unverified_topology", f"switch {switch.id} ({switch.kind}) wiring is unverified: a human "
                          "confirms which channel feeds each input and which pad each output reaches",
                          subject=switch.id,
                          source=env.station(f"switches[{_switch_index(ctx, switch.id)}].certainty"),
                          observed="unverified", limit="verified")
    pin_map = ctx.pin_map
    if pin_map is not None and pin_map.certainty == "unverified" and pin_map.switch_targets():
        targets = ", ".join(f"{t}={s}.{o}" for t, (s, o) in sorted(pin_map.switch_targets().items()))
        yield confirm("unverified_topology", f"pin map {pin_map.name} maps switch outputs to DUT terminals "
                      f"({targets}) and is unverified", subject=pin_map.name,
                      source=env.pin_map(pin_map.name, "certainty"), observed="unverified", limit="verified")


# -- R-ASU-01 --------------------------------------------------------------------------------------------------------


@rule("R-ASU-01", {"plan"})
def asu_ranges(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """A role's current measurement range (setting ``irange``, full scale in A) exists on its SMU; a range that needs
    an ASU (1 pA on an HRSMU, 1-100 pA on an MPSMU) is allowed only on an SMU with a declared ASU recorded
    ``present: true`` (PG p505 (4-187) "SAP")."""
    for role, spec in sorted(ctx.recipe.roles.items()):
        value = setting_value(spec, MEASURE_RANGE_SETTING, ctx.plan.resolved_params)
        bound = ctx.plan.binding.roles.get(role)
        if value is None or bound is None or bound.channel is None:
            continue
        source = env.recipe(ctx.recipe, f"roles.{role}.settings.{MEASURE_RANGE_SETTING}")
        module = ctx.station.module_for_channel(bound.channel)
        if module is None:
            continue  # R-PIN-01 blocks
        try:
            dc = module_spec(module.model)
        except KeyError:
            yield block(f"role {role}: a {module.type} has no SMU current ranges", subject=role, source=source,
                        observed=module.type, limit="an SMU")
            continue
        if not is_real(value) or float(value) <= 0:  # type: ignore[arg-type]
            yield block(f"role {role}: current range {value!r} is not a positive full scale in A", subject=role,
                        source=source, observed=scalar(value), limit="a range full scale")
            continue
        full_scale = abs(float(value))  # type: ignore[arg-type]
        found = next((r for r in dc.i_ranges if math.isclose(r.full_scale, full_scale, rel_tol=1e-9)), None)
        if found is None:
            yield block(f"role {role}: {module.type} has no {full_scale:g} A range", subject=role,
                        source=env.code(f"{SPEC_SYMBOL}.MODULE_SPECS[{dc.module_type}]"), observed=full_scale,
                        limit=", ".join(f"{r.full_scale:g}" for r in dc.i_ranges))
            continue
        if not found.requires_asu:
            continue
        asu = next((s for s in ctx.station.switches if s.kind == "asu"
                    and any(p.index == bound.channel for p in s.ports.values())), None)
        if asu is None:
            yield block(f"role {role}: the {full_scale:g} A range needs an ASU on {module.alias or module.type}, and "
                        "none is declared", subject=role, source=env.station("switches"), observed=None,
                        limit=f"an asu switch on channel {bound.channel}")
        elif asu.present is not True:
            yield block(f"role {role}: the {full_scale:g} A range needs ASU {asu.id}, which is "
                        f"{'of unknown presence' if asu.present is None else 'declared absent'}", subject=role,
                        source=env.station(f"switches[{_switch_index(ctx, asu.id)}].present"), observed=asu.present,
                        limit=True)
