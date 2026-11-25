"""Rules engine (blueprint 2.5, 4.1-4.3): registry and decorator, phases, ordering, fail-closed evaluation, report
fields, finding sources from the resolved config files, the rule context, and R-CFG-01 on an invalid config."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from b1500_test_agent.config import ConfigLoader, load_config
from b1500_test_agent.models.policy import Policy
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules import builtin
from b1500_test_agent.rules.engine import (
    Finding,
    RuleContext,
    RuleEnv,
    RuleRegistry,
    RulesEngine,
    block,
    config_findings,
    confirm,
    registered_rules,
    rule,
    rule_rank,
    warn,
)
from tests.unit.helpers import write_yaml
from tests.unit.rules_factory import T0, context, engine, live_state, pin_map, recipe

TABLE: dict[str, set[str]] = {
    "R-CFG-01": {"plan", "pre_execute"},
    "R-FAULT-01": {"plan", "pre_execute"},
    "R-REC-01": {"plan"},
    "R-PARAM-01": {"plan"},
    "R-PIN-01": {"plan"},
    "R-PIN-02": {"plan"},
    "R-INV-01": {"plan", "pre_execute"},
    "R-LIM-01": {"plan"},
    "R-LIM-02": {"plan"},
    "R-LIM-03": {"plan"},
    "R-DUT-01": {"plan"},
    "R-COMP-01": {"plan"},
    "R-IL-01": {"plan", "pre_execute"},
    "R-GNDU-01": {"plan"},
    "R-RUN-01": {"plan"},
    "R-RUN-02": {"plan"},
    "R-ALWAYS-01": {"plan"},
    "R-ERRX-01": {"plan", "pre_execute"},
    "R-CAL-01": {"pre_execute"},
    "R-CAL-02": {"pre_execute"},
    "R-PULSE-01": {"plan"},
    "R-PULSE-02": {"plan"},
    "R-PULSE-03": {"plan"},
    "R-SPGU-01": {"plan"},
    "R-WG-01": {"plan", "pre_execute"},
    "R-WG-02": {"plan"},
    "R-ROUTE-01": {"plan", "pre_execute"},
    "R-ROUTE-02": {"plan"},
    "R-ASU-01": {"plan"},
    "R-CMU-01": {"plan"},
    "R-CORR-01": {"plan", "pre_execute"},
}
"""Blueprint v1 4.2 + v2 2.8 in registration order (family modules core, limits, run, pulse, route, cmu). ``pre``
rules that read live state also run at ``plan`` when a snapshot exists."""


# -- Registry --------------------------------------------------------------------------------------------------------


def test_builtin_rules_follow_the_blueprint_table() -> None:
    specs = registered_rules()
    assert [s.rule_id for s in specs] == list(TABLE)
    assert {s.rule_id: set(s.phases) for s in specs} == TABLE
    assert all(s.fn.__doc__ for s in specs)
    families = [builtin.core.__name__, builtin.limits.__name__, builtin.run.__name__, builtin.pulse.__name__,
                builtin.route.__name__, builtin.cmu.__name__]
    modules = [s.fn.__module__ for s in specs]
    assert set(modules) == set(families)
    assert modules == sorted(modules, key=families.index)  # one block per family module, in table order


def test_rule_rank_is_table_order() -> None:
    assert rule_rank("R-LIM-03") < rule_rank("R-DUT-01") < rule_rank("R-CORR-01")
    assert rule_rank("R-QUAL-01") == len(TABLE)


@pytest.mark.parametrize(
    ("rule_id", "phases"),
    [("LIM-03", {"plan"}), ("R-lim-03", {"plan"}), ("R-LIM-3", {"plan"}), ("R-X-01", set()),
     ("R-X-01", {"post"}), ("R-X-01", {"plan", "run"})],
)
def test_decorator_rejects_bad_ids_and_phases(rule_id: str, phases: set[str]) -> None:
    with pytest.raises(ValueError):
        RuleRegistry().rule(rule_id, phases)


def test_decorator_rejects_duplicates_and_builtin_ids() -> None:
    registry = RuleRegistry()
    registry.rule("R-X-01", {"plan"})(lambda ctx, env: [])
    with pytest.raises(ValueError, match="already registered"):
        registry.rule("R-X-01", {"plan"})
    registered_rules()
    with pytest.raises(ValueError, match="already registered"):
        rule("R-LIM-03", {"plan"})


# -- Evaluation ------------------------------------------------------------------------------------------------------


def _rules(*pairs: tuple[str, set[str], object]) -> list:
    registry = RuleRegistry()
    for rule_id, phases, fn in pairs:
        registry.rule(rule_id, phases)(fn)  # type: ignore[arg-type]
    return list(registry.rules())


def _const(*findings: Finding):
    def fn(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
        yield from findings

    return fn


def test_tier_aggregation_and_report_fields() -> None:
    cfg, ctx = context()
    w = warn("w", source="s")
    c = confirm("soft_limit", "c", source="s")
    b = block("b", source="s")
    cases = [((w,), "ok"), ((w, c), "needs_confirmation"), ((c, b, w), "blocked"), ((), "ok")]
    for drafts, tier in cases:
        eng = RulesEngine(cfg, rules=_rules(("R-T-01", {"plan"}, _const(*drafts))), clock=lambda: T0)
        report = eng.evaluate(ctx, "plan")
        assert report.tier == tier
        assert report.phase == "plan"
        assert report.evaluated_at == T0
        assert report.policy_digest == cfg.sha256("policy")
        assert report.confirm_reasons == (["soft_limit"] if c in drafts else [])
        assert [f.rule_id for f in report.findings] == ["R-T-01"] * len(drafts)


def test_rules_run_only_in_their_phases_and_keep_registration_order() -> None:
    cfg, ctx = context()
    rules = _rules(
        ("R-B-01", {"plan"}, _const(warn("b1", source="s"), warn("b2", source="s"))),
        ("R-A-01", {"pre_execute"}, _const(warn("a", source="s"))),
        ("R-C-01", {"plan", "pre_execute"}, _const(warn("c", source="s"))),
    )
    eng = RulesEngine(cfg, rules=rules, clock=lambda: T0)
    assert [f.message for f in eng.evaluate(ctx, "plan").findings] == ["b1", "b2", "c"]
    assert [f.message for f in eng.evaluate(ctx, "pre_execute").findings] == ["a", "c"]
    with pytest.raises(ValueError, match="unknown phase"):
        eng.evaluate(ctx, "post")  # type: ignore[arg-type]


def _raises(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    raise KeyError("boom")


def _wrong_type(ctx: RuleContext, env: RuleEnv) -> list[object]:
    return ["not a finding"]


def _confirm_live(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    yield confirm("soft_limit", "a live rule must not ask for confirmation", source="s")


@pytest.mark.parametrize("fn", [_raises, _wrong_type, _confirm_live])
def test_a_broken_rule_fails_closed(fn: object) -> None:
    cfg, ctx = context()
    eng = RulesEngine(cfg, rules=_rules(("R-T-01", {"plan", "pre_execute"}, fn)), clock=lambda: T0)
    report = eng.evaluate(ctx, "pre_execute")
    assert report.tier == "blocked"
    [finding] = report.findings
    assert finding.rule_id == "R-T-01" and finding.severity == "block"
    assert finding.source.startswith("code:tests.unit.test_rules_engine.")
    assert "fail closed" in finding.message


def test_live_rules_never_confirm() -> None:
    """Pre-execute reports carry only block/warn/info, so validate and run show the same summary."""
    cfg, ctx = context(live=live_state(stb=8, errors=[(202, "x"), (305, "y")], slots={3: None}))
    report = engine(cfg).evaluate(ctx, "pre_execute")
    assert report.tier == "blocked"
    assert {f.severity for f in report.findings} <= {"block", "warn", "info"}


def test_evaluation_is_deterministic() -> None:
    cfg, ctx = context(rec=recipe(status="draft"), pm=pin_map(certainty="unverified"), params={"vg_stop": 12.0},
                       live=live_state(errors=[(305, "x")]))
    eng = engine(cfg)
    first = eng.evaluate(ctx, "plan")
    assert first == eng.evaluate(ctx, "plan")
    ranks = [rule_rank(f.rule_id) for f in first.findings]
    assert ranks == sorted(ranks)
    assert first.tier == "blocked"  # 12 V lies outside the recipe range


def test_default_engine_uses_the_builtin_rules() -> None:
    cfg, _ = context()
    assert RulesEngine(cfg).rules == registered_rules()


# -- Sources from the resolved config files --------------------------------------------------------------------------


def _loaded_context(repo: Path, **kw: object) -> tuple[object, RuleContext]:
    """A context whose station, policy, pin map and DUT come from the real loader over the hermetic repo copy."""
    cfg = load_config(Paths.from_env({}, repo_root=repo))
    _, ctx = context(pm=cfg.pin_maps["mosfet-4t"], **kw)  # the plan binds the committed pin map's channels
    ctx = ctx.model_copy(update={"policy": cfg.policy, "station": cfg.station,
                                 "pin_map": cfg.pin_maps["mosfet-4t"], "dut": cfg.dut_profiles["nmos-generic"]})
    return cfg, RuleContext.model_validate(ctx.model_dump())


def test_sources_name_the_committed_example_files(repo: Path) -> None:
    cfg, ctx = _loaded_context(repo, params={"vg_stop": 3.5, "icomp_drain": 5e-3}, points=20000)
    report = RulesEngine(cfg).evaluate(ctx, "plan")  # type: ignore[arg-type]
    assert [(f.rule_id, f.source) for f in report.findings] == [  # per rule, in channel order (drain 3, gate 4)
        ("R-DUT-01", "config/duts/nmos-generic.example.yaml#terminals.drain.max_abs_i"),
        ("R-DUT-01", "config/duts/nmos-generic.example.yaml#terminals.gate.max_abs_v"),
        ("R-RUN-01", "config/policy.example.yaml#run_limits.max_points.smu"),
    ]


def test_sources_name_the_local_files_when_present(repo: Path) -> None:
    write_yaml(repo / "config" / "local" / "policy.yaml", {"soft_limits": {"voltage_v": 2.0, "compliance_a": 0.01}})
    cfg, ctx = _loaded_context(repo)
    report = RulesEngine(cfg).evaluate(ctx, "plan")  # type: ignore[arg-type]
    assert report.tier == "needs_confirmation"
    [finding] = report.findings
    assert (finding.rule_id, finding.source, finding.observed, finding.limit) == (
        "R-LIM-03", "config/local/policy.yaml#soft_limits.voltage_v", 3.0, 2.0)
    assert report.policy_digest == cfg.sha256("policy")  # type: ignore[attr-defined]


# -- R-CFG-01 on an invalid configuration ----------------------------------------------------------------------------


def test_hard_limits_above_the_ceiling_are_invalid_config_via_r_cfg_01(repo: Path) -> None:
    write_yaml(repo / "config" / "local" / "policy.yaml", {"hard_limits": {"max_abs_voltage_v": 60.0}})
    loader = ConfigLoader(Paths.from_env({}, repo_root=repo))
    report = loader.check()
    assert not report.ok and report.error_code == "invalid_config"
    findings = config_findings(report)
    assert findings and all(f.rule_id == "R-CFG-01" and f.severity == "block" for f in findings)
    [finding] = [f for f in findings if f.source.startswith("config/local/policy.yaml")]
    assert finding.source == "config/local/policy.yaml#hard_limits"
    assert "code ceiling 42.0 V" in finding.message


def test_config_findings_of_a_valid_report_are_empty(repo: Path) -> None:
    assert config_findings(ConfigLoader(Paths.from_env({}, repo_root=repo)).check()) == []


# -- Rule context ----------------------------------------------------------------------------------------------------


def test_context_rejects_a_recipe_that_is_not_the_plans() -> None:
    _, ctx = context()
    other = recipe(version=2)
    with pytest.raises(ValidationError, match="differs from the plan"):
        RuleContext.model_validate({**ctx.model_dump(), "recipe": other.model_dump()})


def test_context_needs_to_know_whether_the_recipe_runs_on_the_backend() -> None:
    _, ctx = context(rec=recipe(status="draft"))
    data = ctx.model_dump()
    del data["runnable"]
    with pytest.raises(ValidationError, match="runnable"):
        RuleContext.model_validate(data)


def test_context_rejects_foreign_pin_map_and_dut() -> None:
    _, ctx = context()
    data = ctx.model_dump()
    with pytest.raises(ValidationError, match="pin_map"):
        RuleContext.model_validate({**data, "pin_map": pin_map(name="other").model_dump()})
    with pytest.raises(ValidationError, match="dut"):
        RuleContext.model_validate({**data, "dut": {**data["dut"], "name": "other"}})


def test_context_policy_bypassing_validation_still_hits_the_ceiling_check() -> None:
    from b1500_test_agent.models.policy import HardLimits

    policy = Policy.model_construct(hard_limits=HardLimits.model_construct(max_abs_voltage_v=50.0,
                                                                           max_abs_compliance_a=0.5))
    cfg, ctx = context(cfg_policy=policy)
    report = engine(cfg).evaluate(ctx, "pre_execute")
    assert report.tier == "blocked"
    assert [(f.rule_id, f.observed, f.limit) for f in report.findings if f.rule_id == "R-CFG-01"] == [
        ("R-CFG-01", 50.0, 42.0), ("R-CFG-01", 0.5, 0.1)]
