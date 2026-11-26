"""Built-in rules of the switch accessories (blueprint v2 2.8 rows R-ROUTE-01, R-ROUTE-02, R-ASU-01, plus R-RSU-01 of
the v2.1 plan section 12 (WP21.13), in table order).

The plan's routes are ``envelope.routes`` (what the ``OutputGuard`` admits besides each switch's ``rest`` state),
``routes_by_phase`` (what the kind applies, phase by phase, in order) and each role's ``via`` (the route its terminal
needs). R-PIN-01 already checks a role's own switch target against the pin map (declared, not absent, the state its
resource needs, wiring recorded, route in the envelope); these rules check every route of the plan as a whole, the
live switch states before execution, the certainty of the topology, the ASU current ranges and the RSU's "From SMU"
input limit.

Facts (``models/routing.py``): ``ERSSP`` 0 = open, 1 = SMU, 2 = PGU, 3 = PGU open; the PGU-open state exists only on
CH 1 of each 16440A (ports 0 and 2); a selector's SMU path carries Force only (Sense open) (PG p154 (2-66)); after
``*RST`` or power-on every port is open and ``ERMOD 1`` must precede ``ERSSP`` (PG p433 (4-115) "ERSSP"). The RSU's
"From SMU" input takes at most +-25 V ("Or the RSU will be damaged", WG p20 (1-8)) and its SMU path 100 mA (WG p16
(1-4) "SMU mode").
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from b1500_test_agent.driver.modules import SPEC_SYMBOL, WGFMU_SPEC, module_spec
from b1500_test_agent.models.plan import ChannelEnvelope
from b1500_test_agent.models.routing import RSU_KIND, Route, RsuSmuInput, SwitchSpec, rsu_smu_inputs
from b1500_test_agent.models.station import SMU_TYPES
from b1500_test_agent.rules.builtin.common import (
    ASU_1PA_SETTING,
    MEASURE_RANGE_SETTING,
    PlanRoute,
    envelope_items,
    is_real,
    measure_range_a,
    norm_channel,
    plan_routes,
    scalar,
    who,
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
    ``ERMOD 1``; the transaction's snapshot reads them, WP9.2) was read and is a rest state (``SwitchSpec.at_rest``:
    the ``rest`` state, or both outputs of an SCUU open, its power-on state)."""
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
            elif not switch.at_rest(output, state):
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
    """A role's current measurement range (setting ``irange``, full scale in A, or setting ``asu_1pa`` true = the
    1 pA range; ``common.measure_range_a``) exists on its SMU; a range that needs an ASU (1 pA on an HRSMU, 1-100 pA
    on a B1511B MPSMU) is allowed only on an SMU with a declared ASU recorded ``present: true`` (PG p505 (4-187)
    "SAP"). On the instrument the ASU's presence shows again before the trigger: without it ``RI ch,8`` is an
    instrument error, which the kinds' ``ERRX?`` drain turns into an abort before ``XE``."""
    for role, spec in sorted(ctx.recipe.roles.items()):
        value = measure_range_a(spec, ctx.plan.resolved_params)
        bound = ctx.plan.binding.roles.get(role)
        if value is None or bound is None or bound.channel is None:
            continue
        key = MEASURE_RANGE_SETTING if MEASURE_RANGE_SETTING in spec.settings else ASU_1PA_SETTING
        source = env.recipe(ctx.recipe, f"roles.{role}.settings.{key}")
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


# -- R-RSU-01 --------------------------------------------------------------------------------------------------------

RSU_V_SOURCE = f"{SPEC_SYMBOL}.WGFMU_SPEC.smu_mode_max_v (WG p20 (1-8))"
RSU_A_SOURCE = f"{SPEC_SYMBOL}.WGFMU_SPEC.smu_mode_max_a (WG p16 (1-4))"
RSU_RECORD = ("a human records which SMU feeds each RSU's From SMU input, or deletes the smu side when none is "
              "cabled (bring-up L8)")


@rule("R-RSU-01", {"plan"})
def rsu_from_smu_limit(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """An SMU cabled to an RSU's "From SMU" input stays within +-25 V and 100 mA whatever the RSU's state: the input
    takes at most +-25 V ("Or the RSU will be damaged", WG p20 (1-8)) and the SMU path 100 mA (WG p16 (1-4) "SMU
    mode"); the kernel's 42 V ceiling does not protect it. The cabling is the station's ``switches[].ports.<out>.
    inputs.smu`` of every RSU not recorded absent (``routing.rsu_smu_inputs``). Blocked: (1) an envelope channel
    recorded on such an input whose |V| (the forced voltage or the voltage compliance) or |I| (the compliance or the
    forced current) exceeds ``WGFMU_SPEC.smu_mode_max_v``/``smu_mode_max_a``, which covers a role bound through the
    RSU's SMU path (``RSU201.OUT`` -> ``smu``) and a role on the SMU's own channel (``mosfet-4t`` on an RSU landing);
    (2) a plan route that puts an RSU output on its SMU path (other than its ``rest``) while the SMU on that input is
    unknown (``null``); (3) on hardware, while any RSU's input is unknown, every SMU channel of the plan above those
    limits (it may be the one cabled there) until a human records the wiring (bring-up L8). On the simulator the
    scenario's ``rsu_smu`` cabling stands in for a ``null`` input (``ConfigBundle.planning_station``). The
    ``OutputGuard`` refuses the same levels per command (``rsu_input_exceeded``)."""
    inputs = rsu_smu_inputs(ctx.station.switches)
    if not inputs:
        return
    cabled: dict[int, list[RsuSmuInput]] = {}
    for item in inputs:
        if item.channel is not None:
            cabled.setdefault(norm_channel(item.channel), []).append(item)
    for channel, entry in envelope_items(ctx):
        found = cabled.get(norm_channel(channel))
        if found:
            targets = ", ".join(item.target for item in found)
            for label, unit, value, limit, source in _rsu_over(entry):
                what = (f"the +-{limit:g} V the From SMU input of {targets} takes; this SMU is cabled there (station "
                        "switches), and above it the RSU is damaged (WG p20 (1-8))" if unit == "V" else
                        f"the {limit:g} A of the SMU path of {targets}, which this SMU is cabled to (WG p16 (1-4) "
                        "\"SMU mode\")")
                yield block(f"{who(entry, channel)}: {label} {value:g} {unit} exceeds {what}; keep it within "
                            f"{limit:g} {unit} or use an SMU that no RSU is cabled to", subject=entry.role,
                            source=env.code(source), observed=scalar(value), limit=limit)
    yield from _rsu_unknown_routes(ctx, env)
    unknown = [item for item in inputs if item.channel is None]
    if unknown and ctx.backend == "visa":
        yield from _rsu_unknown_inputs(ctx, env, unknown, cabled)


def _rsu_over(entry: ChannelEnvelope) -> list[tuple[str, str, float, float, str]]:
    """``(label, unit, value, limit, code source)`` of each envelope value above the RSU input's limits (a non-finite
    value counts as above)."""
    over = []
    for label, unit, value, limit, source in (
        ("|V|", "V", entry.max_abs_v, WGFMU_SPEC.smu_mode_max_v, RSU_V_SOURCE),
        ("|I|", "A", entry.max_abs_i, WGFMU_SPEC.smu_mode_max_a, RSU_A_SOURCE),
    ):
        if value is not None and (not math.isfinite(value) or value > limit):
            over.append((label, unit, value, limit, source))
    return over


def _rsu_unknown_routes(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Plan routes (allowed routes and phases; a role's ``via`` is R-PIN-01's) that switch an RSU output to its SMU
    path while the SMU on that input is unknown."""
    seen: set[Route] = set()
    routes = [*sorted(ctx.plan.envelope.routes, key=Route.sort_key),
              *(r for _, rs in sorted(ctx.plan.routes_by_phase.items()) for r in rs)]
    for route in routes:
        switch = ctx.station.switch(route.switch)
        if (route in seen or switch is None or switch.kind != RSU_KIND or switch.present is False
                or route.state != "smu" or route.state == switch.rest or route.output not in switch.ports):
            continue
        seen.add(route)
        inputs = switch.ports[route.output].inputs
        if "smu" in inputs and inputs["smu"] is None:
            yield block(f"route {route} puts the SMU on the From SMU input of {route.target} on the DUT, but the "
                        f"station does not record which SMU that is (inputs.smu: null), so its level cannot be held "
                        f"to +-{WGFMU_SPEC.smu_mode_max_v:g} V; {RSU_RECORD}",
                        source=env.station(f"switches[{_switch_index(ctx, switch.id)}].ports.{route.output}"
                                           ".inputs.smu"),
                        observed=None, limit="the SMU channel on the From SMU input")


def _rsu_unknown_inputs(ctx: RuleContext, env: RuleEnv, unknown: list[RsuSmuInput],
                        cabled: dict[int, list[RsuSmuInput]]) -> Iterator[Finding]:
    """Hardware only: while an RSU's From SMU input is unknown, any SMU channel of the plan (not already bounded by
    its own recorded RSU) above the input's limits may be the one cabled there."""
    targets = ", ".join(item.target for item in unknown)
    first = unknown[0]
    source = env.station(f"switches[{_switch_index(ctx, first.switch)}].ports.{first.output}.inputs.smu")
    for channel, entry in envelope_items(ctx):
        if norm_channel(channel) in cabled:
            continue  # bounded above by the RSU it is recorded on
        module = ctx.station.module_for_channel(channel)
        if module is None or module.type not in SMU_TYPES:
            continue
        for label, unit, value, limit, _source in _rsu_over(entry):
            yield block(f"{who(entry, channel)}: {label} {value:g} {unit} is above the {limit:g} {unit} an RSU From "
                        f"SMU input takes (WG p20 (1-8), WG p16 (1-4)), and the station does not record which SMU "
                        f"feeds {targets} (inputs.smu: null): if it is this one, the RSU is damaged; {RSU_RECORD}",
                        subject=entry.role, source=source, observed=scalar(value), limit=limit)
