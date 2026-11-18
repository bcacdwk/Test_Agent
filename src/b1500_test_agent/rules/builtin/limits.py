"""Built-in rules: module, hard, soft and DUT limits, explicit compliance and the interlock (blueprint 2.8 / v1 4.2
table rows R-LIM-01, R-LIM-02, R-LIM-03, R-DUT-01, R-COMP-01, R-IL-01, in table order). ``interlock_errors`` is the
shared reading of the ``ERRX?`` interlock codes that measurement kinds call after ``CN``."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator

from b1500_test_agent.driver.modules import module_spec, violations
from b1500_test_agent.models.station import InstrumentError
from b1500_test_agent.rules.builtin.common import (
    CEILING_A_SYMBOL,
    CEILING_V_SYMBOL,
    COMPLIANCE_SETTING,
    INTERLOCK_ERRORS,
    SOURCING_FUNCTIONS,
    channel_envelope,
    envelope_items,
    is_real,
    scalar,
    setting_value,
    who,
)
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, rule, warn
from b1500_test_agent.rules.tiers import HARD_CEILING_A, HARD_CEILING_V

# -- R-LIM-01 --------------------------------------------------------------------------------------------------------


@rule("R-LIM-01", {"plan"})
def module_spec_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """|V|, |Icomp| and V*I of every envelope channel lie within its module's DC spec (``driver/modules.py``);
    the GNDU must sink the summed compliance of all channels when a role uses it. A channel without a current limit
    (``pgu``/``wgfmu`` role, no compliance) counts with 0 A here; R-PULSE-*/R-SPGU-01/R-GNDU-01 bound it."""
    total_i = 0.0
    for channel, entry in envelope_items(ctx):
        current = entry.max_abs_i if entry.max_abs_i is not None else 0.0
        total_i += current
        module = ctx.station.module_for_channel(channel)
        if module is None:
            yield block(f"{who(entry, channel)} has no module in the station profile", subject=entry.role,
                        source=env.station("modules"), observed=channel, limit=None)
            continue
        try:
            spec = module_spec(module.model)
        except KeyError:
            yield block(f"{who(entry, channel)}: {module.type} is not a DC source in v1 (no module spec)",
                        subject=entry.role, source=env.code("b1500_test_agent.driver.modules.MODULE_SPECS"),
                        observed=module.type, limit="an SMU")
            continue
        problems = violations(spec, entry.max_abs_v, current, source="V")
        if not problems:
            continue
        if entry.max_abs_v > spec.max_abs_v:
            observed, limit = entry.max_abs_v, spec.max_abs_v
        elif current > spec.max_abs_i:
            observed, limit = current, spec.max_abs_i
        else:
            observed = f"{entry.max_abs_v:g} V @ {current:g} A"
            limit = ", ".join(f"{v:g} V @ {i:g} A" for v, i in spec.v_source_envelope)
        yield block(f"{who(entry, channel)}: " + "; ".join(problems), subject=entry.role,
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
    """Every connected channel has a non-zero compliance in the envelope; sourcing roles set it explicitly
    (role setting ``icomp``)."""
    recipe, plan = ctx.recipe, ctx.plan
    for role_name, spec in sorted(recipe.roles.items()):
        bound = plan.binding.roles.get(role_name)
        if bound is None or bound.channel is None:
            continue
        channel = bound.channel
        entry = channel_envelope(ctx, channel)
        if entry is None:
            yield block(f"{role_name} (channel {channel}) is connected but has no compiled envelope, hence no "
                        "compliance", subject=role_name, source=env.plan("envelope.channels"), observed=None,
                        limit="non-zero compliance")
            continue
        if spec.function in SOURCING_FUNCTIONS:
            value = setting_value(spec, COMPLIANCE_SETTING, plan.resolved_params)
            if value is None or not is_real(value) or value == 0:
                yield block(f"{role_name} forces voltage without an explicit non-zero compliance "
                            f"(settings.{COMPLIANCE_SETTING} = {value!r})", subject=role_name,
                            source=env.recipe(recipe, f"roles.{role_name}.settings.{COMPLIANCE_SETTING}"),
                            observed=scalar(value), limit="non-zero compliance")
        if entry.max_abs_i is not None and entry.max_abs_i <= 0:
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


