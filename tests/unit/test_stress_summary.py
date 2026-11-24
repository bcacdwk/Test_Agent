"""The stress-measure parts of the plan summary (WP7.6; blueprint v2 2.9, rules/tiers.py): the stress and recovery
level of every channel that holds one and the stress schedule, so that the human confirms the stress itself; the
compact form when the full line is too long; plans of other kinds unchanged (their goldens: test_plan_summary*.py)."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.sources import DcStress, SourcePlan, StressSchedule, source_plan
from b1500_test_agent.rules.tiers import SUMMARY_MAX_CHARS, plan_summary
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map

pytestmark = pytest.mark.smu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


def plan(recipe_id: str, **params: Any) -> PlanRecord:
    cfg = bundle(pin_maps=[pin_map(gate=4, drain=3)], duts=[dut()])
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic",
                                      "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


def test_bti_summary_names_the_stress_recovery_and_schedule() -> None:
    record = plan("reliability.bti_sms", vg_stress=2.0, stress_time=1800.0, recovery_time=600.0, vg_recovery=-0.5)
    assert record.summary == (
        "reliability.bti_sms@1 | drain=SMU3(HRSMU) bias 0.05 V Icomp 1 mA; gate=SMU4(HRSMU) sweep -0.2..1.5 V "
        "(max 2 V) stress 2 V rec -0.5 V Icomp 1 uA | DUT nmos-generic | pins mosfet-4t | sim | async ~42 min | "
        "stress 30 min x11 reads, recovery 10 min x10 reads | R-RUN-02 long_run, R-ALWAYS-01 destructive")
    assert len(record.summary) <= SUMMARY_MAX_CHARS


def test_short_stresses_are_given_in_seconds_and_zero_levels_are_omitted() -> None:
    record = plan("reliability.hci", vg_stress=1.2, vd_stress=2.5, stress_time=60.0, reads_per_decade=1)
    assert "drain=SMU3(HRSMU) bias 0.05 V (max 2.5 V) stress 2.5 V Icomp 1 mA" in record.summary
    assert "gate=SMU4(HRSMU) bias 1.5 V stress 1.2 V Icomp 1 uA" in record.summary
    assert "| stress 60 s x3 reads |" in record.summary and "rec" not in record.summary
    sources = source_plan(record.program)
    assert sources.schedule == StressSchedule(stress_s=60.0, reads=3)


def test_the_compact_form_keeps_the_stress() -> None:
    record = plan("reliability.bti_sms", vg_stress=2.0, stress_time=1800.0, recovery_time=600.0, vg_recovery=-0.5)
    long_flags = record.model_copy(update={"binding": record.binding.model_copy(update={"pin_map": "x" * 120})})
    text = plan_summary(long_flags, record.rules.findings)
    assert len(text) <= SUMMARY_MAX_CHARS and "st2V rec-0.5V 1uA" in text and "stress 30 min x11 reads" in text


def test_dc_stress_lookup_accepts_both_channel_spellings() -> None:
    sources = SourcePlan(stress={4: DcStress(level_v=2.0)})
    assert sources.dc_stress(401) == DcStress(level_v=2.0) and sources.dc_stress(3) is None


def test_other_kinds_carry_no_stress_part() -> None:
    record = plan("mosfet.idvg")
    assert " stress " not in record.summary and source_plan(record.program).schedule is None
