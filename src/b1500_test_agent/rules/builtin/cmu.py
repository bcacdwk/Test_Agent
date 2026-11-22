"""Built-in rules of the MFCMU family (blueprint v2 2.8 rows R-CMU-01 and R-CORR-01, in table order).

R-CMU-01 checks the AC envelope of every MFCMU source role (``cmu_high``) against the module (``CMU_SPEC``), the DUT
terminals' ``ac`` envelopes, the hard |V| limit and the ``policy.cmu`` soft bands. R-CORR-01 checks the correction
records of the server-written store (``RuleContext.corrections``, filled through ``rules.correction_records`` from a
``CorrectionRecordSource`` such as ``archive/corrections.py: records_for``) at validation and the live correction
state (``LiveState.cmu_corrections``: ``CORRST?`` per function, phase compensation) before execution.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from b1500_test_agent.driver.modules import CMU_SPEC, SPEC_SYMBOL
from b1500_test_agent.models.plan import RuleFinding
from b1500_test_agent.models.station import CorrectionRecord
from b1500_test_agent.rules.builtin.common import (
    CMU_SOURCE_FUNCTION,
    channel_envelope,
    dut_terminal,
    hard_limit_v,
    is_real,
    who,
)
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, info, rule

CORRECTION_KINDS_EXEMPT = frozenset({"cmu_correction"})
"""Kinds that measure the corrections themselves and therefore need none."""

CORRECTION_CARD = "cmu/cmu-correction"
"""The card (skill ``b1500-test``) every R-CORR-01 block points at (blueprint v2 0 #11: block, next step = card)."""

CORRECTION_RECIPES: dict[str, str] = {
    "phase": "cmu.phase_compensation", "open": "cmu.correction_open", "short": "cmu.correction_short",
    "load": "cmu.correction_load",
}  # fmt: skip
"""The recipe that renews each correction kind."""

CORRECTION_NEXT_STEP = (f"load card {CORRECTION_CARD} (skill b1500-test): run the missing corrections with the same "
                        "pin map, in the order phase compensation, open, short (load), each after the human's own "
                        "physical set-up and confirmation, then validate the capacitance plan again")
"""Next step of a result blocked by R-CORR-01 (``validate_plan`` and refused runs)."""


def correction_next_steps(findings: Iterable[RuleFinding], *, renew: bool = False) -> list[str]:
    """``[CORRECTION_NEXT_STEP]`` when ``findings`` hold an R-CORR-01 block or ``renew`` (a run discarded correction
    records), else ``[]``."""
    blocked = any(f.rule_id == "R-CORR-01" and f.severity == "block" for f in findings)
    return [CORRECTION_NEXT_STEP] if blocked or renew else []


def _next(kind: str) -> str:
    return f"next: {CORRECTION_RECIPES.get(kind, 'the correction recipes')} (card {CORRECTION_CARD})"

# -- R-CMU-01 --------------------------------------------------------------------------------------------------------


@rule("R-CMU-01", {"plan"})
def cmu_ac_envelope(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every MFCMU source role (``cmu_high``) has an AC envelope inside the module (1 kHz <= f <= 5 MHz, AC 10 to
    250 mVrms, |DC bias| <= 25 V; UG p73 (2-33)), the hard |V| limit and the AC envelope of each DUT terminal on the
    MFCMU (a terminal without one blocks); above ``policy.cmu`` (DC bias, AC level) needs confirmation
    (``soft_cmu``)."""
    cmu_roles = sorted(r for r, s in ctx.recipe.roles.items() if s.function in ("cmu_high", "cmu_low"))
    spec_src = env.code(f"{SPEC_SYMBOL}.CMU_SPEC ({CMU_SPEC.source})")
    hard_v, hard_source = hard_limit_v(ctx, env)
    soft = ctx.policy.cmu
    for role, spec in sorted(ctx.recipe.roles.items()):
        bound = ctx.plan.binding.roles.get(role)
        if spec.function != CMU_SOURCE_FUNCTION or bound is None or bound.channel is None:
            continue
        entry = channel_envelope(ctx, bound.channel)
        if entry is None:
            continue  # R-COMP-01 blocks a connected channel without an envelope
        name = who(entry, bound.channel)
        ac = entry.ac
        if ac is None:
            yield block(f"{name}: an MFCMU role without an AC envelope (the guard would refuse every setting)",
                        subject=role, source=env.plan(f"envelope.channels.{bound.channel}.ac"), observed=None,
                        limit="an AC envelope")
            continue
        f_low, f_high = CMU_SPEC.f_hz
        if ac.f_min_hz < f_low or ac.f_max_hz > f_high:
            observed = ac.f_min_hz if ac.f_min_hz < f_low else ac.f_max_hz
            yield block(f"{name}: frequency {observed:g} Hz is outside the MFCMU's {f_low:g}..{f_high:g} Hz",
                        subject=role, source=spec_src, observed=observed, limit=f"{f_low:g}..{f_high:g}")
        v_low, v_high = CMU_SPEC.ac_vrms
        if ac.max_vrms > v_high or 0 < ac.max_vrms < v_low:
            yield block(f"{name}: AC level {ac.max_vrms * 1e3:g} mVrms is outside the MFCMU's {v_low * 1e3:g}.."
                        f"{v_high * 1e3:g} mVrms", subject=role, source=spec_src, observed=ac.max_vrms,
                        limit=f"{v_low:g}..{v_high:g}")
        for limit, source, what in ((CMU_SPEC.max_dc_v, spec_src, "the MFCMU's internal DC bias"),
                                    (hard_v, hard_source, "the hard |V| limit")):
            if ac.max_dc_v > limit:
                yield block(f"{name}: DC bias {ac.max_dc_v:g} V exceeds {what} {limit:g} V", subject=role,
                            source=source, observed=ac.max_dc_v, limit=limit)
        yield from _dut_ac(ctx, env, cmu_roles, name, ac.max_vrms)
        for value, limit, field, label, unit in (
            (ac.max_dc_v, soft.soft_dc_bias_v, "soft_dc_bias_v", "DC bias", "V"),
            (ac.max_vrms, soft.soft_ac_vrms, "soft_ac_vrms", "AC level", "Vrms"),
        ):
            if value > limit:
                yield confirm("soft_cmu", f"{name}: {label} {value:g} {unit} is above the soft band {limit:g} {unit}",
                              subject=role, source=env.policy(f"cmu.{field}"), observed=value, limit=limit)


def _dut_ac(ctx: RuleContext, env: RuleEnv, roles: list[str], name: str, vrms: float) -> Iterator[Finding]:
    dut = ctx.dut
    if dut is None:
        return  # R-DUT-01 blocks
    for role in roles:
        terminal, limits = dut_terminal(ctx, role)
        if limits is None:
            continue  # R-DUT-01 blocks an undescribed driven terminal
        if limits.ac is None:
            yield block(f"{name}: terminal {terminal} of DUT {dut.name} declares no AC envelope; a human adds one "
                        "(never invent it)", subject=terminal, source=env.dut(dut.name, f"terminals.{terminal}.ac"),
                        observed=None, limit="an ac envelope")
        elif vrms > limits.ac.max_vrms:
            yield block(f"{name}: AC level {vrms:g} Vrms exceeds terminal {terminal}'s {limits.ac.max_vrms:g} Vrms",
                        subject=terminal, source=env.dut(dut.name, f"terminals.{terminal}.ac.max_vrms"),
                        observed=vrms, limit=limits.ac.max_vrms)


# -- R-CORR-01 -------------------------------------------------------------------------------------------------------


def _uses_cmu(ctx: RuleContext) -> bool:
    recipe = ctx.recipe
    return (recipe.kind.startswith("cmu")
            or any(b.module_type == "MFCMU" for b in ctx.plan.binding.roles.values())
            or any("MFCMU" in r.module_types or r.resource == "cmu" for r in recipe.roles.values()))


def _aliases(ctx: RuleContext) -> list[str]:
    bound = sorted({b.alias or f"CH{b.channel}" for b in ctx.plan.binding.roles.values() if b.module_type == "MFCMU"})
    return bound or sorted(m.alias or f"CH{m.channels[0]}" for m in ctx.station.modules if m.type == "MFCMU")


def _frequencies(ctx: RuleContext) -> list[float]:
    freqs: list[float] = []
    for quantity in ctx.plan.resolved_params.values():
        if quantity.unit == "Hz":
            values = quantity.value if isinstance(quantity.value, list) else [quantity.value]
            freqs.extend(float(v) for v in values if is_real(v))
    return freqs


@rule("R-CORR-01", {"plan", "pre_execute"})
def cmu_correction(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Capacitance (MFCMU) plans need, for every MFCMU they use, a correction record of each kind in
    ``policy.corrections.require`` that covers every plan frequency, is at most ``max_age_h`` old at validation and
    was measured with this station profile and pin map (records: ``RuleContext.corrections``, i.e. the correction
    store); the age of the oldest record in use is recorded (info, shown in the summary as ``corr <age>``). Before
    execution (and at validation when a snapshot carries them) the live state must still hold them: ``CORRST?`` on
    for every required open/short/load correction, phase compensation in effect, the same ``*IDN?`` as the records
    (a ``*RST``, a device clear or a power cycle loses corrections). Correction recipes themselves are exempt. Every
    block names the recipe that renews the correction and the card ``cmu/cmu-correction`` (the next step; WP8.2)."""
    if not _uses_cmu(ctx) or ctx.recipe.kind in CORRECTION_KINDS_EXEMPT:
        return
    aliases = _aliases(ctx)
    if not aliases:
        yield block("capacitance measurement but the station profile has no MFCMU", source=env.station("modules"),
                    observed=None, limit="an MFCMU")
        return
    in_use: dict[str, list[CorrectionRecord]] = {}
    for alias in aliases:
        findings, records = _records_in_use(ctx, env, alias)
        if env.phase == "plan":
            yield from findings
        if records is not None:
            in_use[alias] = records
    live = ctx.live
    if env.phase == "pre_execute" or (live is not None and live.cmu_corrections is not None):
        yield from _live_corrections(ctx, env, aliases, in_use)


def _records_in_use(ctx: RuleContext, env: RuleEnv,
                    alias: str) -> tuple[list[Finding], list[CorrectionRecord] | None]:
    """Plan-phase findings for one MFCMU and the records in use (``None`` when a required kind is not usable)."""
    plan, policy = ctx.plan, ctx.policy.corrections
    freqs = _frequencies(ctx)
    station_sha, pin_map_sha = plan.hashes.get("station"), plan.hashes.get("pin_map")
    records = ctx.corrections.get(alias, [])
    found: list[Finding] = []
    chosen: list[CorrectionRecord] = []
    usable_kinds = 0
    for kind in policy.require:
        matching = [r for r in records if r.kind == kind]
        if not matching:
            found.append(block(f"MFCMU {alias}: no {kind} correction record; {_next(kind)}", subject=f"{alias}.{kind}",
                               source=env.policy("corrections.require"), observed=None, limit=kind))
            continue
        usable = [r for r in matching if r.station_sha == station_sha and r.pin_map_sha == pin_map_sha]
        if not usable:
            found.append(block(f"MFCMU {alias}: the {kind} correction was measured with another station profile or "
                               f"pin map; {_next(kind)} with this pin map", subject=f"{alias}.{kind}",
                               source=env.state(f"corrections/{alias}.json"), observed=matching[-1].run_id,
                               limit="this station profile and pin map"))
            continue
        fresh = [r for r in usable if r.age_h(plan.created_at) <= policy.max_age_h]
        if not fresh:
            age = max(usable, key=lambda r: r.ts).age_h(plan.created_at)
            found.append(block(f"MFCMU {alias}: the {kind} correction is {age:.1f} h old, older than "
                               f"{policy.max_age_h:g} h; {_next(kind)}", subject=f"{alias}.{kind}",
                               source=env.policy("corrections.max_age_h"), observed=round(age, 3),
                               limit=policy.max_age_h))
            continue
        missing = sorted({f for f in freqs if not any(r.covers([f]) for r in fresh)})
        if missing:
            corrected = sorted({f for r in fresh for f in r.freqs_hz})
            found.append(block(f"MFCMU {alias}: the {kind} correction does not cover {missing[0]:g} Hz; "
                               f"{_next(kind)} with freqs_hz including it", subject=f"{alias}.{kind}",
                               source=env.state(f"corrections/{alias}.json"), observed=missing[0],
                               limit=", ".join(f"{f:g}" for f in corrected) or None))
            continue
        usable_kinds += 1
        chosen.extend(_covering_records(fresh, freqs))
    if usable_kinds != len(policy.require):
        return found, None
    age = max(r.age_h(plan.created_at) for r in chosen)
    found.append(info(f"MFCMU {alias}: corrections {', '.join(r.kind for r in chosen)} in use, the oldest "
                      f"{age:.1f} h old", subject=alias, source=env.state(f"corrections/{alias}.json"),
                      observed=round(age, 3), limit=policy.max_age_h))
    return found, chosen


def _covering_records(fresh: list[CorrectionRecord], freqs: list[float]) -> list[CorrectionRecord]:
    """The records a plan uses: per frequency the newest fresh record covering it (several records may share the
    frequencies), or the newest fresh record when the plan names no frequency. Every frequency is covered."""
    if not freqs:
        return [max(fresh, key=lambda r: r.ts)]
    used: list[CorrectionRecord] = []
    for freq in sorted(set(freqs)):
        record = max((r for r in fresh if r.covers([freq])), key=lambda r: r.ts)
        if not any(record is r for r in used):
            used.append(record)
    return used


def _live_corrections(ctx: RuleContext, env: RuleEnv, aliases: list[str],
                      in_use: dict[str, list[CorrectionRecord]]) -> Iterator[Finding]:
    live = ctx.live
    if live is None:
        yield block("no live snapshot: the MFCMU correction state cannot be checked", source=env.live("snapshot"),
                    observed=None, limit="a live snapshot")
        return
    states = live.cmu_corrections
    if states is None:
        yield block("the MFCMU correction state was not read (CORRST?)", source=env.live("cmu_corrections"),
                    observed=None, limit="corrections on")
        return
    required = ctx.policy.corrections.require
    for alias in aliases:
        state = states.get(alias)
        where = env.live(f"cmu_corrections.{alias}")
        if state is None:
            yield block(f"MFCMU {alias}: the correction state was not read", source=where, observed=None,
                        limit="corrections on")
            continue
        for kind in required:
            if kind == "phase":
                if state.phase is False:
                    yield block(f"MFCMU {alias}: phase compensation data are no longer in effect (a *RST, device "
                                f"clear or power cycle clears them); {_next('phase')}", subject=f"{alias}.phase",
                                source=f"{where}.phase", observed=False, limit=True)
            elif state.corr_state.get(kind) is not True:
                reading = "off" if kind in state.corr_state else "unknown"
                yield block(f"MFCMU {alias}: CORRST? reports the {kind} correction {reading} (a *RST, device clear "
                            f"or power cycle clears it); {_next(kind)}", subject=f"{alias}.{kind}",
                            source=f"{where}.corr_state.{kind}", observed=state.corr_state.get(kind), limit=True)
        identity = live.identity
        for record in in_use.get(alias, []):
            if identity is not None and record.idn.strip() != identity.raw.strip():
                yield block(f"MFCMU {alias}: the {record.kind} correction was measured on another mainframe "
                            f"({record.idn}); {_next(record.kind)}", subject=f"{alias}.{record.kind}",
                            source=env.live("identity"), observed=identity.raw, limit=record.idn)
