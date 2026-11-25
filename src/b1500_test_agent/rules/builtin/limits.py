"""Built-in rules: module, hard, soft and DUT limits, explicit compliance, the interlock and the GNDU budget
(blueprint 2.8 / v1 4.2 table rows R-LIM-01, R-LIM-02, R-LIM-03, R-DUT-01, R-COMP-01, R-IL-01, R-GNDU-01, in table
order). ``interlock_errors`` is the shared reading of the ``ERRX?`` interlock codes that measurement kinds call after
``CN``."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator

from b1500_test_agent.driver.modules import (
    CMU_SPEC,
    SPEC_SYMBOL,
    SPGU_SPEC,
    WGFMU_SPEC,
    ModuleSpec,
    module_spec,
    violations,
)
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.recipe import COMPLIANCE_FREE_FUNCTIONS, SMU_FUNCTIONS
from b1500_test_agent.models.station import InstrumentError, ModuleSlot, StationProfile
from b1500_test_agent.rules.builtin.common import (
    CEILING_A_SYMBOL,
    CEILING_V_SYMBOL,
    COMPLIANCE_SETTING,
    CURRENT_SOURCING_FUNCTIONS,
    INTERLOCK_ERRORS,
    SOURCING_FUNCTIONS,
    VOLTAGE_COMPLIANCE_SETTING,
    channel_envelope,
    envelope_items,
    is_real,
    role_function,
    scalar,
    setting_value,
    who,
)
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, rule, warn
from b1500_test_agent.rules.tiers import HARD_CEILING_A, HARD_CEILING_V

NON_DC_LIMITS: dict[str, tuple[str, float, str, frozenset[str]]] = {
    "HVSPGU": ("SPGU_SPEC.max_open_v", SPGU_SPEC.max_open_v, "UG p76 (2-36)", frozenset({"pgu"})),
    "WGFMU": ("WGFMU_SPEC.max_abs_v", WGFMU_SPEC.max_abs_v, "WG p16 (1-4)", frozenset({"wgfmu"})),
    "MFCMU": ("CMU_SPEC.max_dc_v", CMU_SPEC.max_dc_v, CMU_SPEC.source, frozenset({"cmu_high", "cmu_low"})),
}
"""Module types without a DC source spec: (spec field, largest |V|, citation, role functions they serve)."""

# -- R-LIM-01 --------------------------------------------------------------------------------------------------------


@rule("R-LIM-01", {"plan"})
def module_spec_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every envelope channel lies within its module's spec (``driver/modules.py``): an SMU's |V|, |I| and V-I
    corners (voltage forcing: |V| with |Icomp|; current forcing ``sweep_i``/``bias_i``/``step_i``/``sync_i``: |I|
    with |Vcomp|, the I-source corners); an HV-SPGU's open-load 40 V, a WGFMU's 10 V and an MFCMU's 25 V DC bias. A
    role function the module cannot serve is refused. The GNDU must sink the summed compliance of all channels when a
    role uses it (R-GNDU-01 adds the currents of sources without compliance)."""
    total_i = 0.0
    for channel, entry in envelope_items(ctx):
        current = entry.max_abs_i if entry.max_abs_i is not None else 0.0
        total_i += current
        module = ctx.station.module_for_channel(channel)
        if module is None:
            yield block(f"{who(entry, channel)} has no module in the station profile", subject=entry.role,
                        source=env.station("modules"), observed=channel, limit=None)
            continue
        function = role_function(ctx, entry.role, entry)
        if module.type in NON_DC_LIMITS:
            yield from _non_dc_limits(env, entry, channel, module, function)
            continue
        if function is not None and function not in SMU_FUNCTIONS:
            yield block(f"{who(entry, channel)}: a {module.type} cannot serve a {function} role",
                        subject=entry.role, source=env.code(f"{SPEC_SYMBOL}.MODULE_SPECS"), observed=function,
                        limit="an SMU role function")
            continue
        spec = module_spec(module.model)
        forcing_i = function in CURRENT_SOURCING_FUNCTIONS
        yield from _dc_limits(env, entry, channel, spec, current, forcing_i)
    if any(b.gndu for b in ctx.plan.binding.roles.values()):
        gndu = module_spec("GNDU")
        if total_i > gndu.max_abs_i:
            yield block(f"the GNDU would sink up to {total_i:g} A (sum of compliances), above its "
                        f"{gndu.max_abs_i:g} A", subject="GNDU",
                        source=env.code(f"b1500_test_agent.driver.modules.MODULE_SPECS[GNDU] "
                                        f"({gndu.envelope_source})"),
                        observed=total_i, limit=gndu.max_abs_i)


def _dc_limits(env: RuleEnv, entry: ChannelEnvelope, channel: int, spec: ModuleSpec, current: float,
               forcing_i: bool) -> Iterator[Finding]:
    problems = violations(spec, entry.max_abs_v, current, source="I" if forcing_i else "V")
    if not problems:
        return
    if entry.max_abs_v > spec.max_abs_v:
        observed, limit = entry.max_abs_v, spec.max_abs_v
    elif current > spec.max_abs_i:
        observed, limit = current, spec.max_abs_i
    elif forcing_i:
        observed = f"{current:g} A @ {entry.max_abs_v:g} V"
        limit = ", ".join(f"{i:g} A @ {v:g} V" for i, v in spec.i_source_envelope)
    else:
        observed = f"{entry.max_abs_v:g} V @ {current:g} A"
        limit = ", ".join(f"{v:g} V @ {i:g} A" for v, i in spec.v_source_envelope)
    yield block(f"{who(entry, channel)}: " + "; ".join(problems), subject=entry.role,
                source=env.code(f"{SPEC_SYMBOL}.MODULE_SPECS[{spec.module_type}] ({spec.envelope_source})"),
                observed=observed, limit=limit)


def _non_dc_limits(env: RuleEnv, entry: ChannelEnvelope, channel: int, module: ModuleSlot,
                   function: str | None) -> Iterator[Finding]:
    field, max_v, citation, functions = NON_DC_LIMITS[module.type]
    source = env.code(f"{SPEC_SYMBOL}.{field} ({citation})")
    if function is not None and function not in functions:
        yield block(f"{who(entry, channel)}: a {module.type} cannot serve a {function} role", subject=entry.role,
                    source=source, observed=function, limit=", ".join(sorted(functions)))
        return
    if not math.isfinite(entry.max_abs_v) or entry.max_abs_v > max_v:
        yield block(f"{who(entry, channel)}: |V| {entry.max_abs_v:g} V exceeds the {module.type}'s {max_v:g} V",
                    subject=entry.role, source=source, observed=scalar(entry.max_abs_v), limit=max_v)


# -- R-LIM-02 / R-LIM-03 ---------------------------------------------------------------------------------------------


@rule("R-LIM-02", {"plan"})
def hard_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every envelope channel stays within ``policy.hard_limits`` and never above the code ceiling (channels without
    a current limit, i.e. sources without compliance, are bounded by the pulse/waveform rules instead)."""
    hard = ctx.policy.hard_limits
    checks = (
        ("|V|", "V", "max_abs_v", hard.max_abs_voltage_v, HARD_CEILING_V, "max_abs_voltage_v", CEILING_V_SYMBOL),
        ("|Icomp|", "A", "max_abs_i", hard.max_abs_compliance_a, HARD_CEILING_A, "max_abs_compliance_a",
         CEILING_A_SYMBOL),
    )
    for label, unit, attr, policy_limit, ceiling, field, symbol in checks:
        limit = min(policy_limit, ceiling)
        source = env.policy(f"hard_limits.{field}") if policy_limit <= ceiling else env.code(symbol)
        for channel, entry in envelope_items(ctx):
            value = getattr(entry, attr)
            if value is None:
                continue
            if not math.isfinite(value):
                yield block(f"{who(entry, channel)}: {label} is not finite", subject=entry.role, source=source,
                            observed=repr(value), limit=limit)
            elif value > limit:
                yield block(f"{who(entry, channel)}: {label} {value:g} {unit} exceeds the hard limit {limit:g} "
                            f"{unit}", subject=entry.role, source=source, observed=value, limit=limit)


@rule("R-LIM-03", {"plan"})
def soft_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Above ``policy.soft_limits`` needs confirmation (``soft_limit``)."""
    soft = ctx.policy.soft_limits
    for label, unit, attr, limit, field in (
        ("|V|", "V", "max_abs_v", soft.voltage_v, "voltage_v"),
        ("|Icomp|", "A", "max_abs_i", soft.compliance_a, "compliance_a"),
    ):
        for channel, entry in envelope_items(ctx):
            value = getattr(entry, attr)
            if value is not None and value > limit:
                yield confirm("soft_limit", f"{who(entry, channel)}: {label} {value:g} {unit} is above the soft "
                              f"limit {limit:g} {unit}", subject=entry.role,
                              source=env.policy(f"soft_limits.{field}"), observed=value, limit=limit)


# -- R-DUT-01 --------------------------------------------------------------------------------------------------------


@rule("R-DUT-01", {"plan"})
def dut_envelope(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """A recipe with DUT roles needs an existing DUT profile that describes every driven terminal; levels outside
    the profile's envelope need confirmation (``dut_envelope``). A recipe whose roles all bind by ``cmu_side`` (the
    MFCMU correction recipes: open terminals, a short or a standard, never the DUT) needs none; a DUT profile given
    anyway is checked as usual."""
    recipe = ctx.recipe
    if not recipe.roles:
        return
    name = ctx.plan.request.dut_profile
    if name is None and all(r.bind == "cmu_side" for r in recipe.roles.values()):
        return  # only MFCMU-path roles (correction recipes): the probes are lifted, shorted or on a standard
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
    for channel, entry in envelope_items(ctx):
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
            if value is not None and value > limit:
                yield confirm("dut_envelope", f"{terminal} (channel {channel}): {label} {value:g} {unit} is outside "
                              f"DUT {dut.name}'s envelope {limit:g} {unit}", subject=terminal,
                              source=env.dut(dut.name, f"terminals.{terminal}.{field}"), observed=value, limit=limit)


# -- R-COMP-01 -------------------------------------------------------------------------------------------------------


@rule("R-COMP-01", {"plan"})
def explicit_compliance(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every connected channel has a non-zero compliance in the envelope; voltage-forcing roles (``sweep_v``,
    ``bias_v``, ``step_v``, ``sync_v``, ``pulse_v``) set ``icomp`` explicitly, current-forcing roles (``sweep_i``,
    ``bias_i``, ``step_i``, ``sync_i``) set ``vcomp``. The envelope's compliance is ``max_abs_i`` for a
    voltage-forcing channel and ``max_abs_v`` for a current-forcing one (whose ``max_abs_i`` is the forced current,
    which may be 0 A: a voltmeter). Sources without compliance (``pgu``, ``wgfmu``) are exempt: R-PULSE-*, R-SPGU-01
    and R-WG-* bound them."""
    recipe, plan = ctx.recipe, ctx.plan
    for role_name, spec in sorted(recipe.roles.items()):
        bound = plan.binding.roles.get(role_name)
        if bound is None or bound.channel is None or spec.function in COMPLIANCE_FREE_FUNCTIONS:
            continue
        channel = bound.channel
        entry = channel_envelope(ctx, channel)
        if entry is None:
            yield block(f"{role_name} (channel {channel}) is connected but has no compiled envelope, hence no "
                        "compliance", subject=role_name, source=env.plan("envelope.channels"), observed=None,
                        limit="non-zero compliance")
            continue
        for functions, key, what in ((SOURCING_FUNCTIONS, COMPLIANCE_SETTING, "voltage"),
                                     (CURRENT_SOURCING_FUNCTIONS, VOLTAGE_COMPLIANCE_SETTING, "current")):
            if spec.function not in functions:
                continue
            value = setting_value(spec, key, plan.resolved_params)
            if value is None or not is_real(value) or value == 0:
                yield block(f"{role_name} forces {what} without an explicit non-zero compliance "
                            f"(settings.{key} = {value!r})", subject=role_name,
                            source=env.recipe(recipe, f"roles.{role_name}.settings.{key}"),
                            observed=scalar(value), limit="non-zero compliance")
        forces_current = spec.function in CURRENT_SOURCING_FUNCTIONS
        compliance = entry.max_abs_v if forces_current else entry.max_abs_i
        if compliance is not None and compliance <= 0:
            field = "max_abs_v" if forces_current else "max_abs_i"
            yield block(f"{role_name} (channel {channel}): compliance is zero", subject=role_name,
                        source=env.plan(f"envelope.channels.{channel}.{field}"), observed=compliance, limit="> 0")


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
        yield block(f"{need}; status byte bit 3 (interlock open: a request above the limit was refused) is set",
                    source=env.live("status_byte.bit3"),
                    observed=live.status_byte.value, limit="bit 3 clear")
    for error in interlock_errors(live.errors):
        yield block(f"{need}; instrument error {error.code} ({INTERLOCK_ERRORS[error.code]}) reports an interlock "
                    "refusal", source=env.live("errors"), observed=error.code, limit="no error 202/203")


# -- R-GNDU-01 -------------------------------------------------------------------------------------------------------


@rule("R-GNDU-01", {"plan"})
def gndu_budget(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """When a role uses the GNDU, or the pin map lands any DUT terminal on it (a pad on the GNDU carries return current
    whether a recipe role names it or not; WP8.5), every current that can return through it stays within its 4.2 A
    (UG p58 (2-18) "4.2 A"): the compliances of the SMU channels plus the expected currents of the sources without
    compliance (a pulse channel's short-circuit bound ``pulse.max_short_circuit_a``; without a pulse envelope an
    HV-SPGU's open-load maximum into its 50 Ohm, a WGFMU's ``WGFMU_SPEC.max_output_a``). The simulator accounts the
    current that really returns (``Circuit.ground_peak_a``); tests keep it within this bound."""
    roles = any(b.gndu for b in ctx.plan.binding.roles.values())
    pads = ctx.pin_map is not None and any(target == "GNDU" for target in ctx.pin_map.terminals.values())
    if not (roles or pads):
        return
    dc, pulsed = gndu_return_a(ctx.plan.envelope, ctx.station)
    gndu = module_spec("GNDU")
    total = dc + pulsed
    if total > gndu.max_abs_i:
        yield block(f"up to {total:g} A could return through the GNDU ({dc:g} A of compliances + {pulsed:g} A from "
                    f"sources without compliance), above its {gndu.max_abs_i:g} A", subject="GNDU",
                    source=env.code(f"{SPEC_SYMBOL}.MODULE_SPECS[GNDU] ({gndu.envelope_source})"),
                    observed=round(total, 9), limit=gndu.max_abs_i)


def gndu_return_a(envelope: CompiledEnvelope, station: StationProfile) -> tuple[float, float]:
    """The R-GNDU-01 bound of a compiled envelope: ``(dc, pulsed)`` (A), the compliances of the channels with one and
    the expected currents of the sources without compliance (rule docstring). Pure; the GNDU table tests compare it
    with the simulator's accounting."""
    dc = pulsed = 0.0
    for channel, entry in sorted(envelope.channels.items()):
        if entry.max_abs_i is not None:
            dc += entry.max_abs_i
        elif entry.pulse is not None:
            pulsed += entry.pulse.max_short_circuit_a
        else:
            module = station.module_for_channel(channel)
            if module is not None and module.type == "WGFMU":
                pulsed += WGFMU_SPEC.max_output_a
            else:
                pulsed += SPGU_SPEC.max_open_v / SPGU_SPEC.output_ohm
    return dc, pulsed


def interlock_errors(errors: Iterable[InstrumentError]) -> list[InstrumentError]:
    """The interlock errors (202, 203) among drained ``ERRX?`` entries, first occurrence of each code.

    Measurement kinds call this after ``CN`` (ATV-10 fallback) and abort on any hit."""
    found: dict[int, InstrumentError] = {}
    for error in errors:
        if error.code in INTERLOCK_ERRORS:
            found.setdefault(error.code, error)
    return [found[code] for code in sorted(found)]


