"""``plan_summary`` (blueprint 2.5, 8.1 ``unit/``): exact format, determinism, ASCII, at most 400 characters, every
swept/biased channel named with its max |V| and |Icomp|, built only from hashed plan content and plan-phase
confirm/block findings."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest

from b1500_test_agent.models.plan import (
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    PlanRecord,
    RuleFinding,
)
from b1500_test_agent.rules.tiers import SUMMARY_MAX_CHARS, _amps, _channels, _volts, plan_summary, with_rules
from tests.unit.rules_factory import (
    FORCE,
    IDVD,
    SYSTEM,
    T0,
    compile_plan,
    context,
    dut,
    engine,
    force,
    live_state,
    pin_map,
    pin_map_exact,
    recipe,
    station,
    wide_dut,
)

BASE = ("mosfet.idvg@1 | drain=SMU3(HRSMU) bias 0.05 V Icomp 1 mA; gate=SMU5(MPSMU) sweep -1..3 V Icomp 1 uA | "
        "DUT nmos-generic | pins mosfet-4t | sim")


def summarize(cfg_ctx: tuple[Any, Any], phase: str = "plan") -> tuple[str, list[RuleFinding]]:
    cfg, ctx = cfg_ctx
    report = engine(cfg).evaluate(ctx, phase)
    return plan_summary(ctx.plan, report.findings), report.findings


def finding(rule_id: str, severity: str, reason: str | None = None, message: str = "m") -> RuleFinding:
    return RuleFinding(rule_id=rule_id, severity=severity, message=message, source="s", reason=reason)


# -- Format ----------------------------------------------------------------------------------------------------------


def test_ok_plan_summary_is_exact() -> None:
    assert summarize(context())[0] == BASE


def test_blueprint_example_shape() -> None:
    """Blueprint 2.5 example (drain on SMU3 of the example station instead of SMU2)."""
    text, _ = summarize(context(rec=recipe(IDVD)))
    assert text == ("mosfet.idvd@1 | drain=SMU3(HRSMU) sweep 0..3 V Icomp 20 mA; gate=SMU5(MPSMU) step 0..2 V "
                    "Icomp 1 uA | DUT nmos-generic | pins mosfet-4t | sim | R-LIM-03 soft_limit, "
                    "R-DUT-01 dut_envelope")


def test_blocked_and_confirm_flags_follow_the_rule_table_order() -> None:
    text, _ = summarize(context(params={"vg_stop": 12.0}, pm=pin_map(certainty="unverified"), backend="visa"))
    assert text.endswith("| visa | R-REC-01 first_hw_run, R-PARAM-01 blocked, R-PIN-02 unverified_pin_map, "
                         "R-LIM-03 soft_limit, R-DUT-01 dut_envelope")


def test_flags_are_deduplicated_per_rule_and_reason() -> None:
    text, findings = summarize(force(15.0, 0.02))
    assert [f.rule_id for f in findings] == ["R-LIM-03", "R-LIM-03"]
    assert text == ("generic.smu_force@1 | force=SMU5(MPSMU) bias 15 V Icomp 20 mA | DUT wide | pins force-1 | sim "
                    "| R-LIM-03 soft_limit")


def test_dut_none_and_no_outputs() -> None:
    text, _ = summarize(context(rec=recipe(SYSTEM), du=None, dut_profile=None))
    assert text == ("system.self_test@1 | no outputs | DUT none | pins mosfet-4t | sim | "
                    "R-ALWAYS-01 system_self_test")


def test_levels_without_function_and_narrower_than_the_envelope() -> None:
    _, ctx = context()
    extra = {
        5: ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=1e-6),
        3: ChannelEnvelope(role="drain", max_abs_v=5.0, max_abs_i=1e-3, function="bias_v", v_start=0.05,
                           v_stop=0.05),
    }
    plan = PlanRecord.model_validate({**ctx.plan.model_dump(), "envelope": CompiledEnvelope(channels=extra)})
    assert plan_summary(plan, []).split(" | ")[1] == (
        "drain=SMU3(HRSMU) bias 0.05 V (max 5 V) Icomp 1 mA; gate=SMU5(MPSMU) max 3 V Icomp 1 uA")


def test_a_channel_without_compliance_says_so() -> None:
    """A ``pgu``/``wgfmu`` channel has no current limit: the summary never invents an Icomp for it."""
    _, ctx = context()
    pgu = {5: ChannelEnvelope(role="gate", max_abs_v=4.0, max_abs_i=None, function="pgu")}
    plan = PlanRecord.model_validate({**ctx.plan.model_dump(), "envelope": CompiledEnvelope(channels=pgu)})
    assert plan_summary(plan, []).split(" | ")[1] == "gate=SMU5(MPSMU) max 4 V no Icomp"
    assert _channels(plan, compact=True) == "gate=SMU5 <=4V noIcomp"


@pytest.mark.parametrize(
    ("amps", "text"),
    [(0.02, "20 mA"), (1e-6, "1 uA"), (1e-12, "1 pA"), (0.1, "100 mA"), (1.0, "1 A"), (2.5e-9, "2.5 nA"),
     (0.0, "0 A"), (1e-16, "0.1 fA"), (1.2345e-3, "1.234 mA")],
)
def test_current_formatting(amps: float, text: str) -> None:
    assert _amps(amps) == text


@pytest.mark.parametrize(("volts", "text"), [(-0.0, "0"), (0.05, "0.05"), (3.0, "3"), (-1.0, "-1"), (42.0, "42")])
def test_voltage_formatting(volts: float, text: str) -> None:
    assert _volts(volts) == text


# -- Canonical: only hashed content and plan-phase confirm/block findings --------------------------------------------


def test_deterministic_and_independent_of_finding_order() -> None:
    _, ctx = context(rec=recipe(IDVD), pm=pin_map(certainty="unverified"))
    findings = [finding("R-DUT-01", "confirm", "dut_envelope"), finding("R-LIM-03", "confirm", "soft_limit"),
                finding("R-PIN-02", "confirm", "unverified_pin_map"), finding("R-LIM-02", "block")]
    expected = plan_summary(ctx.plan, findings)
    rng = random.Random(7)
    for _ in range(10):
        shuffled = findings[:]
        rng.shuffle(shuffled)
        assert plan_summary(ctx.plan, shuffled) == expected
    assert expected.endswith("R-PIN-02 unverified_pin_map, R-LIM-02 blocked, R-LIM-03 soft_limit, "
                             "R-DUT-01 dut_envelope")


def test_ignores_info_warn_messages_label_and_timestamps() -> None:
    _, ctx = context(rec=recipe(IDVD))
    confirm = finding("R-LIM-03", "confirm", "soft_limit")
    base = plan_summary(ctx.plan, [confirm])
    noisy = [finding("R-ERRX-01", "warn"), confirm.model_copy(update={"message": "other text", "subject": "x"}),
             finding("R-CAL-01", "info")]
    _, relabeled = context(rec=recipe(IDVD), label="another die", created_at=T0 + timedelta(hours=3))
    assert plan_summary(ctx.plan, noisy) == base
    assert plan_summary(relabeled.plan, [confirm]) == base


def test_changes_when_the_plan_or_the_confirmations_change() -> None:
    base = summarize(context())[0]
    assert summarize(context(params={"vg_stop": 2.0}))[0] != base
    assert summarize(context(pm=pin_map(certainty="unverified")))[0] != base
    assert summarize(context(backend="visa", rec=recipe(status="hw_validated")))[0] != base


def test_live_state_never_changes_the_summary() -> None:
    plain = summarize(context())[0]
    assert summarize(context(live=live_state(errors=[(305, "x")])))[0] == plain


# -- Size, ASCII, channel coverage -----------------------------------------------------------------------------------


def _ten_channel_context() -> tuple[Any, Any]:
    slots = range(1, 11)
    profile = station(modules=[{"slot": s, "model": "B1511B", "type": "MPSMU", "channels": [s], "alias": f"SMU{s}"}
                               for s in slots], switches=[], corrections={})
    bias = {"function": "bias_v", "measure": ["I"], "settings": {"v": "$v", "icomp": "$icomp"}}
    roles: dict[str, Any] = {f"r{s}": bias for s in slots}
    roles["source"] = {"function": "ground", "allow_gndu": True}
    rec = recipe(FORCE, roles=roles)
    pm = pin_map_exact("ten", {**{f"r{s}": s for s in slots}, "source": "GNDU"}, certainty="unverified")
    return context(rec=rec, pm=pm, du=wide_dut(terminals=[f"r{s}" for s in slots]), station_profile=profile,
                   params={"v": 12.5, "icomp": 0.0125}, backend="visa")


def test_long_plans_use_the_compact_form_and_still_name_every_channel() -> None:
    text, findings = summarize(_ten_channel_context())
    assert len(text) <= SUMMARY_MAX_CHARS
    assert "Icomp" not in text  # compact channel form
    for s in range(1, 11):
        assert f"r{s}=SMU{s} 12.5V 12.5mA" in text
    assert text.endswith("| visa | R-REC-01 adhoc_recipe, R-REC-01 first_hw_run, R-PIN-02 unverified_pin_map, "
                         "R-LIM-03 soft_limit")
    assert all(f.reason in text for f in findings if f.reason)


def test_overlong_content_is_cut_to_400_characters() -> None:
    _, ctx = context()
    roles = {f"{'x' * 60}{c:02d}": c for c in range(1, 11)}
    envelope = CompiledEnvelope(channels={
        c: ChannelEnvelope(role=r, max_abs_v=1.0, max_abs_i=1e-3, function="bias_v", v_start=1.0, v_stop=1.0)
        for r, c in roles.items()})
    binding = ChannelBinding(pin_map="mosfet-4t", roles={
        r: BoundChannel(role=r, terminal=r, channel=c, slot=c, module_type="MPSMU", alias=f"SMU{c}")
        for r, c in roles.items()})
    plan = PlanRecord.model_validate({**ctx.plan.model_dump(), "envelope": envelope, "binding": binding})
    text = plan_summary(plan, [finding("R-LIM-03", "confirm", "soft_limit")])
    assert len(text) == SUMMARY_MAX_CHARS and text.endswith("...") and text.isascii()


def _contexts() -> list[tuple[Any, Any]]:
    return [
        context(), context(rec=recipe(IDVD)), force(45.0, 0.2), force(-3.3, 1e-9), _ten_channel_context(),
        context(pm=pin_map(gate=201)), context(du=dut(drain=(0.01, 1e-12))), context(pm=None),
    ]


@pytest.mark.parametrize("index", range(8))
def test_ascii_bounded_and_names_every_channel_with_max_v_and_icomp(index: int) -> None:
    cfg_ctx = _contexts()[index]
    text, _ = summarize(cfg_ctx)
    assert len(text) <= SUMMARY_MAX_CHARS
    assert text.isascii() and text.isprintable()
    plan = cfg_ctx[1].plan
    for channel, entry in plan.envelope.channels.items():
        bound = plan.binding.roles[entry.role]
        name = bound.alias or f"ch{channel}"
        assert f"{entry.role}={name}" in text
        assert _volts(entry.max_abs_v) in text
        assert _amps(entry.max_abs_i, space=" Icomp " in text) in text


def test_the_stored_plan_accepts_every_summary() -> None:
    for cfg, ctx in _contexts():
        report = engine(cfg).evaluate(ctx, "plan")
        stored = with_rules(ctx.plan, report)
        assert stored.summary == plan_summary(ctx.plan, report.findings)


def test_compile_plan_fixture_matches_the_envelope_contract() -> None:
    """Guard for the in-test planner: sweep levels are start..stop, bias levels equal, max |V| covers both."""
    plan = compile_plan(recipe(), pin_map(), station())
    gate, drain = plan.envelope.channels[5], plan.envelope.channels[3]
    assert (gate.function, gate.v_start, gate.v_stop, gate.max_abs_v, gate.max_abs_i) == ("sweep_v", -1.0, 3.0, 3.0,
                                                                                           1e-6)
    assert (drain.function, drain.v_start, drain.v_stop, drain.max_abs_i) == ("bias_v", 0.05, 0.05, 1e-3)
