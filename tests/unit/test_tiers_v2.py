"""Tiers with the v2 confirm reasons (blueprint v2 2.1, 2.8): ``soft_pulse``, ``soft_cmu``, ``long_run``,
``physical_setup`` and ``unverified_topology`` each make a plan ``needs_confirmation`` with that reason (and a flag in
the summary); blocks win over them; a plan evaluated again at run time gets the same tier and summary."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.models.plan import AcEnvelope
from b1500_test_agent.models.sources import PulseTrain
from b1500_test_agent.rules.tiers import plan_summary, with_rules
from tests.unit import rules_factory_v2 as v2
from tests.unit.rules_factory import context, engine, recipe

Ctx = tuple[Any, Any]


def train(**changes: Any) -> PulseTrain:
    return v2.TRAIN.model_copy(update=changes)


def correction_recipe() -> Ctx:
    """A correction recipe (kind ``cmu_correction``) on the C-V wiring: exempt from R-CORR-01, always
    ``physical_setup`` (the human places the open/short standard)."""
    return v2.cv(rec=recipe(v2.CV_REC, id="cmu.correction_open", kind="cmu_correction",
                            always_confirm=["physical_setup"]), corrections={})


CONFIRM_CASES: list[tuple[str, Any, list[str], str]] = [
    ("soft-pulse", lambda: v2.spgu([train(count=20000)]), ["soft_pulse"], "R-PULSE-03 soft_pulse"),
    ("soft-cmu", lambda: v2.cv(AcEnvelope(max_vrms=0.08, max_dc_v=2.0, f_min_hz=1e6, f_max_hz=1e6)), ["soft_cmu"],
     "R-CMU-01 soft_cmu"),
    ("long-run", lambda: context(duration_s=700.0, mode="async", max_segment_s=10.0), ["long_run"],
     "R-RUN-02 long_run"),
    ("physical-setup", correction_recipe, ["physical_setup"], "R-ALWAYS-01 physical_setup"),
    ("unverified-topology", lambda: v2.spgu(station_profile=v2.lab_station(sel1={"certainty": "unverified"})),
     ["unverified_topology"], "R-ROUTE-02 unverified_topology"),
]


@pytest.mark.parametrize(("build", "reasons", "flag"), [c[1:] for c in CONFIRM_CASES],
                         ids=[c[0] for c in CONFIRM_CASES])
def test_each_new_reason_needs_confirmation(build: Any, reasons: list[str], flag: str) -> None:
    cfg, ctx = build()
    report = engine(cfg).evaluate(ctx, "plan")
    assert report.tier == "needs_confirmation", [f.message for f in report.findings if f.severity == "block"]
    assert report.confirm_reasons == reasons
    stored = with_rules(ctx.plan, report)
    assert stored.tier == "needs_confirmation" and stored.summary.endswith(flag)


def test_the_lab_wiring_needs_both_wiring_confirmations() -> None:
    cfg, ctx = v2.spgu(pm_certainty="unverified", station_profile=v2.lab_station(sel1={"certainty": "unverified"}))
    report = engine(cfg).evaluate(ctx, "plan")
    assert report.confirm_reasons == ["unverified_pin_map", "unverified_topology"]


@pytest.mark.parametrize(
    ("build", "blocked_by"),
    [
        (lambda: v2.spgu([train(peak_v=2.0, load_ohm=50.0)]), {"R-SPGU-01"}),                 # x2 on a high_z gate
        (lambda: v2.spgu([train(count=20000, width_s=5e-9)]), {"R-PULSE-01"}),               # confirm + block
        (lambda: context(duration_s=400.0), {"R-RUN-02"}),                                    # sync but too long
        (lambda: v2.cv(AcEnvelope(max_vrms=0.3, max_dc_v=2.0, f_min_hz=1e6, f_max_hz=1e6)), {"R-CMU-01"}),
        (lambda: v2.cv(corrections={}), {"R-CORR-01"}),
        (lambda: v2.wgfmu(top_target=201), {"R-WG-01"}),
    ],
)
def test_blocks_win_over_confirmations(build: Any, blocked_by: set[str]) -> None:
    cfg, ctx = build()
    report = engine(cfg).evaluate(ctx, "plan")
    assert report.tier == "blocked"
    assert {f.rule_id for f in report.findings if f.severity == "block"} == blocked_by


@pytest.mark.parametrize("build", [v2.spgu, v2.smu_pulse, v2.wgfmu, v2.cv], ids=["spgu", "smu", "wgfmu", "cv"])
def test_run_time_reevaluation_reproduces_tier_and_summary(build: Any) -> None:
    """The executor re-runs the plan-phase rules on the stored plan without I/O: same tier, same summary."""
    cfg, ctx = build()
    first = engine(cfg).evaluate(ctx, "plan")
    stored = with_rules(ctx.plan, first)
    again = engine(cfg).evaluate(ctx.model_copy(update={"plan": stored}), "plan")
    assert again.tier == stored.tier == "ok"
    assert plan_summary(stored, again.findings) == stored.summary


def test_pre_execute_rules_only_block_or_inform() -> None:
    cfg, ctx = v2.spgu(live=v2.live(switch_states=v2.at_rest(v2.lab_station(), SEL1_OUT1="pgu")))
    report = engine(cfg).evaluate(ctx, "pre_execute")
    assert report.tier == "blocked" and report.confirm_reasons == []
