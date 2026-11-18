"""Built-in rules of the MFCMU family: R-CORR-01 correction records (blueprint v2 2.8; the CMU kinds of M8 make it
live, the correction store of ``archive/corrections.py`` supplies the records)."""

from __future__ import annotations

from collections.abc import Iterator

from b1500_test_agent.rules.builtin.common import is_real
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, rule

CORRECTION_KINDS_EXEMPT = frozenset({"cmu_correction"})
"""Kinds that measure the corrections themselves and therefore need none."""

# -- R-CORR-01 -------------------------------------------------------------------------------------------------------


@rule("R-CORR-01", {"plan"})
def cmu_correction(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Capacitance (MFCMU) plans need, for every MFCMU they use, a correction record of each kind in
    ``policy.corrections.require`` that covers every plan frequency, is at most ``max_age_h`` old at validation and
    was measured with this station profile and pin map (records: ``RuleContext.corrections``, i.e. the correction
    store). Correction recipes themselves are exempt. The pre-execute part (``CORRST?``/``ADJ?`` still on, same
    ``*IDN?``) needs live state."""
    recipe, plan, policy = ctx.recipe, ctx.plan, ctx.policy.corrections
    roles_cmu = [b for b in plan.binding.roles.values() if b.module_type == "MFCMU"]
    uses_cmu = (
        recipe.kind.startswith("cmu")
        or bool(roles_cmu)
        or any("MFCMU" in r.module_types or r.resource == "cmu" for r in recipe.roles.values())
    )
    if not uses_cmu or recipe.kind in CORRECTION_KINDS_EXEMPT:
        return
    aliases = sorted({b.alias or f"CH{b.channel}" for b in roles_cmu}) or sorted(
        m.alias or f"CH{m.channels[0]}" for m in ctx.station.modules if m.type == "MFCMU")
    if not aliases:
        yield block("capacitance measurement but the station profile has no MFCMU", source=env.station("modules"),
                    observed=None, limit="an MFCMU")
        return
    freqs: list[float] = []
    for quantity in plan.resolved_params.values():
        if quantity.unit == "Hz":
            values = quantity.value if isinstance(quantity.value, list) else [quantity.value]
            freqs.extend(float(v) for v in values if is_real(v))
    station_sha, pin_map_sha = plan.hashes.get("station"), plan.hashes.get("pin_map")
    for alias in aliases:
        records = ctx.corrections.get(alias, ())
        for kind in policy.require:
            matching = [r for r in records if r.kind == kind]
            if not matching:
                yield block(f"MFCMU {alias}: no {kind} correction record (run the {kind} correction recipe first)",
                            subject=f"{alias}.{kind}", source=env.policy("corrections.require"), observed=None,
                            limit=kind)
                continue
            usable = [r for r in matching if r.station_sha == station_sha and r.pin_map_sha == pin_map_sha]
            if not usable:
                yield block(f"MFCMU {alias}: the {kind} correction was measured with another station profile or pin "
                            "map", subject=f"{alias}.{kind}", source=env.state(f"corrections/{alias}.json"),
                            observed=matching[-1].run_id, limit="this station profile and pin map")
                continue
            fresh = [r for r in usable if r.age_h(plan.created_at) <= policy.max_age_h]
            if not fresh:
                age = max(usable, key=lambda r: r.ts).age_h(plan.created_at)
                yield block(f"MFCMU {alias}: the {kind} correction is {age:.1f} h old, older than "
                            f"{policy.max_age_h:g} h", subject=f"{alias}.{kind}",
                            source=env.policy("corrections.max_age_h"), observed=round(age, 3),
                            limit=policy.max_age_h)
                continue
            if not any(r.covers(freqs) for r in fresh):
                missing = sorted({f for f in freqs if not any(r.covers([f]) for r in fresh)})
                yield block(f"MFCMU {alias}: the {kind} correction does not cover {missing[0]:g} Hz",
                            subject=f"{alias}.{kind}", source=env.state(f"corrections/{alias}.json"),
                            observed=missing[0], limit=", ".join(f"{f:g}" for f in fresh[-1].freqs_hz) or None)
