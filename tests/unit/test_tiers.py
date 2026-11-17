"""Tier computation (blueprint 4.3, 8.1 ``unit/``): soft/hard bands, unknown DUT and incomplete pin map, recipe
status per backend, always-confirm recipes, ``invalid_config`` above the code ceiling, and the plan-record flow
(provisional plan → rules → ``with_rules`` → identical re-check at run time)."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.models.plan import RulesReport
from b1500_test_agent.models.policy import HardLimits, Policy, SoftLimits
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules.engine import RuleContext, config_findings
from b1500_test_agent.rules.tiers import compute_tier, confirm_reasons, plan_summary, with_rules
from tests.unit.helpers import write_yaml
from tests.unit.rules_factory import (
    FORCE,
    IDVD,
    SYSTEM,
    T0,
    context,
    engine,
    force,
    live_state,
    pin_map,
    pin_map_exact,
    recipe,
)


def plan_report(cfg_ctx: tuple[object, RuleContext]) -> RulesReport:
    cfg, ctx = cfg_ctx
    return engine(cfg).evaluate(ctx, "plan")  # type: ignore[arg-type]


def blocking(report: RulesReport) -> list[str]:
    return sorted({f.rule_id for f in report.findings if f.severity == "block"})


# -- Limit bands (default policy: soft 10 V / 10 mA, hard 42 V / 100 mA) ---------------------------------------------


@pytest.mark.parametrize(
    ("v", "i", "tier", "reasons", "blocked_by"),
    [
        (5.0, 1e-3, "ok", [], []),
        (10.0, 0.01, "ok", [], []),  # at the soft limits: still ok
        (-10.0, 0.01, "ok", [], []),  # magnitudes count
        (10.5, 1e-3, "needs_confirmation", ["soft_limit"], []),
        (20.0, 5e-3, "needs_confirmation", ["soft_limit"], []),
        (5.0, 0.05, "needs_confirmation", ["soft_limit"], []),
        (42.0, 1e-3, "needs_confirmation", ["soft_limit"], []),  # at the hard limit: confirm, not block
        (5.0, 0.1, "needs_confirmation", ["soft_limit"], []),
        # above 42 V the interlock rule also blocks: the example station records no working interlock
        (42.5, 1e-3, "blocked", ["soft_limit"], ["R-IL-01", "R-LIM-02"]),
        (-45.0, 1e-3, "blocked", ["soft_limit"], ["R-IL-01", "R-LIM-02"]),
        (-10.5, 1e-3, "needs_confirmation", ["soft_limit"], []),
        (5.0, 0.11, "blocked", ["soft_limit"], ["R-LIM-01", "R-LIM-02"]),  # also above the MPSMU's 100 mA
    ],
)
def test_default_policy_bands(v: float, i: float, tier: str, reasons: list[str], blocked_by: list[str]) -> None:
    report = plan_report(force(v, i))
    assert report.tier == tier
    assert report.confirm_reasons == reasons
    assert blocking(report) == blocked_by


@pytest.mark.parametrize(
    ("v", "i", "tier"),
    [(4.0, 1e-3, "ok"), (6.0, 1e-3, "needs_confirmation"), (1.0, 6e-3, "needs_confirmation"),
     (21.0, 1e-3, "blocked"), (1.0, 0.06, "blocked")],
)
def test_a_tightened_policy_moves_the_bands(v: float, i: float, tier: str) -> None:
    policy = Policy(hard_limits=HardLimits(max_abs_voltage_v=20.0, max_abs_compliance_a=0.05),
                    soft_limits=SoftLimits(voltage_v=5.0, compliance_a=5e-3))
    assert plan_report(force(v, i, cfg_policy=policy)).tier == tier


def test_the_code_ceiling_holds_even_for_a_policy_object_above_it() -> None:
    policy = Policy.model_construct(hard_limits=HardLimits.model_construct(max_abs_voltage_v=100.0,
                                                                           max_abs_compliance_a=1.0))
    report = plan_report(force(50.0, 1e-3, cfg_policy=policy))
    assert report.tier == "blocked"
    assert {"R-CFG-01", "R-LIM-02"} <= set(blocking(report))


def test_policy_above_the_ceiling_is_invalid_config_and_blocks(repo: Path) -> None:
    write_yaml(repo / "config" / "local" / "policy.yaml",
               {"hard_limits": {"max_abs_voltage_v": 42.0, "max_abs_compliance_a": 0.2}})
    report = ConfigLoader(Paths.from_env({}, repo_root=repo)).check()
    assert report.error_code == "invalid_config"
    findings = config_findings(report)
    assert compute_tier(findings) == "blocked"
    assert {f.rule_id for f in findings} == {"R-CFG-01"}


# -- DUT profile and pin map -----------------------------------------------------------------------------------------


def test_unknown_dut_blocks_a_recipe_with_dut_roles() -> None:
    for kwargs in ({"du": None, "dut_profile": None}, {"du": None, "dut_profile": "ghost"}):
        report = plan_report(context(**kwargs))
        assert report.tier == "blocked"
        assert blocking(report) == ["R-DUT-01"]


def test_a_recipe_without_dut_roles_needs_no_dut_profile() -> None:
    report = plan_report(context(rec=recipe(SYSTEM), du=None, dut_profile=None))
    assert report.tier == "needs_confirmation"
    assert report.confirm_reasons == ["system_self_test"]


@pytest.mark.parametrize(
    "pm",
    [pin_map_exact("partial", {"gate": 1, "source": "GNDU"}), pin_map(drain=None), pin_map(gate=3), None],
    ids=["missing-terminal", "unconnected-terminal", "channel-twice", "no-such-pin-map"],
)
def test_incomplete_pin_map_blocks(pm: object) -> None:
    report = plan_report(context(pm=pm))
    assert report.tier == "blocked"
    assert "R-PIN-01" in blocking(report)


def test_unverified_pin_map_needs_confirmation() -> None:
    report = plan_report(context(pm=pin_map(certainty="unverified")))
    assert (report.tier, report.confirm_reasons) == ("needs_confirmation", ["unverified_pin_map"])


# -- Recipe status per backend ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("backend", "status", "tier", "reasons"),
    [
        ("sim", "draft", "ok", []),
        ("sim", "sim_validated", "ok", []),
        ("sim", "hw_validated", "ok", []),
        ("visa", "draft", "needs_confirmation", ["draft_recipe"]),
        ("visa", "sim_validated", "needs_confirmation", ["first_hw_run"]),
        ("visa", "hw_validated", "ok", []),
        ("sim", "not_implemented", "blocked", []),
        ("visa", "not_implemented", "blocked", []),
    ],
)
def test_recipe_status_tiers(backend: str, status: str, tier: str, reasons: list[str]) -> None:
    report = plan_report(context(backend=backend, rec=recipe(status=status)))  # type: ignore[arg-type]
    assert (report.tier, report.confirm_reasons) == (tier, reasons)
    if status == "not_implemented":
        assert blocking(report) == ["R-REC-01"]


def test_draft_on_sim_is_recorded_as_a_warning() -> None:
    report = plan_report(context(rec=recipe(status="draft")))
    assert [(f.rule_id, f.severity) for f in report.findings] == [("R-REC-01", "warn")]


def test_kind_missing_on_the_backend_blocks() -> None:
    report = plan_report(context(rec=recipe(status="sim_validated"), effective_status="not_implemented"))
    assert blocking(report) == ["R-REC-01"]


def test_generic_recipe_on_visa_is_adhoc() -> None:
    report = plan_report(force(1.0, 1e-3, backend="visa"))  # generic.smu_force, sim_validated
    assert report.confirm_reasons == ["first_hw_run", "adhoc_recipe"]
    report = plan_report(force(1.0, 1e-3))
    assert report.tier == "ok"


def test_destructive_recipe_always_needs_confirmation() -> None:
    report = plan_report(context(rec=recipe(always_confirm=["destructive"])))
    assert (report.tier, report.confirm_reasons) == ("needs_confirmation", ["destructive"])


# -- Acceptance-scenario shapes (blueprint 8.2) ----------------------------------------------------------------------


def test_s4_idvd_3v_20ma_needs_soft_limit_and_dut_envelope() -> None:
    report = plan_report(context(rec=recipe(IDVD)))
    assert (report.tier, report.confirm_reasons) == ("needs_confirmation", ["soft_limit", "dut_envelope"])


def test_s2_60v_on_the_gate_is_blocked() -> None:
    report = plan_report(context(params={"vg_stop": 60.0}))
    assert report.tier == "blocked"
    assert {"R-PARAM-01", "R-LIM-02"} <= set(blocking(report))


# -- Tier helpers and the plan-record flow ---------------------------------------------------------------------------


def test_compute_tier_and_confirm_reasons_agree_with_the_report() -> None:
    report = plan_report(context(rec=recipe(IDVD), pm=pin_map(certainty="unverified")))
    assert compute_tier(report.findings) == report.tier == "needs_confirmation"
    assert confirm_reasons(report.findings) == report.confirm_reasons == ["unverified_pin_map", "soft_limit",
                                                                           "dut_envelope"]
    assert compute_tier([]) == "ok"


def test_with_rules_stores_report_tier_and_summary_and_the_run_recheck_matches() -> None:
    cfg, ctx = context(rec=recipe(IDVD))
    eng = engine(cfg)
    report = eng.evaluate(ctx, "plan")
    stored = with_rules(ctx.plan, report)
    assert stored.rules == report and stored.tier == "needs_confirmation"
    assert stored.summary == plan_summary(ctx.plan, report.findings)
    # Run time: the stored plan is re-checked without I/O; the rules never read rules/tier/summary.
    rerun = eng.evaluate(RuleContext.model_validate({**ctx.model_dump(), "plan": stored.model_dump()}), "plan")
    assert rerun.findings == report.findings
    assert plan_summary(stored, rerun.findings) == stored.summary


def test_with_rules_takes_only_the_plan_phase_report() -> None:
    cfg, ctx = context(live=live_state())
    with pytest.raises(ValueError, match="plan-phase"):
        with_rules(ctx.plan, engine(cfg).evaluate(ctx, "pre_execute"))


def test_summary_does_not_depend_on_live_state_warnings() -> None:
    """Validate (with a snapshot holding old errors) and run (zero-I/O re-check) produce the same summary."""
    _, with_live = context(rec=recipe(IDVD), live=live_state(errors=[(305, "Excess current")]))
    cfg, without = context(rec=recipe(IDVD))
    validated = engine(cfg).evaluate(with_live, "plan")
    rechecked = engine(cfg).evaluate(without, "plan")
    assert any(f.rule_id == "R-ERRX-01" for f in validated.findings)
    assert plan_summary(with_live.plan, validated.findings) == plan_summary(without.plan, rechecked.findings)
    assert validated.tier == rechecked.tier


def test_pre_execute_report_of_a_clean_station_is_ok() -> None:
    cfg, ctx = context(rec=recipe(FORCE), pm=pin_map(name="force-1", force=1), live=live_state())
    report = engine(cfg).evaluate(ctx, "pre_execute")
    assert report.tier == "ok"
    assert report.evaluated_at == T0
