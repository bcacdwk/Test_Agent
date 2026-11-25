"""CMU module closure (WP8.6, blueprint v2 10 intro "Per-module closure AC", 3.2, 6.1, 7.4): every recipe of the §3.2
catalogue (MFCMU + SCUU + QSCV) is registered and ``sim_validated`` (its integration test against model truth passed
in its WP), the ``cmu`` family listing has no other status, every carded recipe sits on bring-up stage L6 and the L6
stage file runs it with at least one check (so the stage drafts one record per recipe), the CMU runbooks of §6.1
exist and the cards point to them, and the CMU analysis methods are all implemented."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.analysis.registry import methods_for
from b1500_test_agent.bringup import load_stage
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.rules.builtin.cmu import CORRECTION_NEXT_STEP
from b1500_test_agent.service import B1500Service
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.test_recipes_cv import MOSCAP, moscap_truth, value

pytestmark = pytest.mark.cmu

SECTION_3_2: tuple[str, ...] = (
    "cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short", "cmu.correction_load", "cmu.spot",
    "moscap.cv", "moscap.cv_ac_level", "moscap.pulsed_cv", "moscap.cf", "moscap.ct", "moscap.cv_multi_freq",
    "moscap.qscv", "mosfet.cgc_cv", "mosfet.cgd_cv", "fecap.cv_butterfly",
)  # fmt: skip
"""The 15 MFCMU (+SCUU, QSCV) recipes of blueprint v2 3.2; every one on stage L6 ("Stage" column)."""

RUNBOOKS = ("cmu-correction-stale", "cmu-cv-distortion", "cmu-series-resistance")
"""The CMU runbooks of blueprint v2 6.1 (``cmu-correction-stale`` since WP8.2, the other two WP8.6)."""

DEBUG_DIR = REPO_ROOT / ".agents" / "skills" / "b1500-debug" / "runbooks"


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


@pytest.fixture
def svc(world: World) -> B1500Service:
    world.use_scenario("moscap_basic")
    return world.service()


def _front(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---")[1])


def test_every_section_3_2_recipe_is_sim_validated(registry: RecipeRegistry) -> None:
    assert len(SECTION_3_2) == 15 and len(set(SECTION_3_2)) == 15
    assert {r: registry.get(r).status for r in SECTION_3_2} == {r: "sim_validated" for r in SECTION_3_2}
    assert all(registry.runnable(r, backend) for r in SECTION_3_2 for backend in ("sim", "visa"))
    assert "cmu.correction" not in registry.ids()  # the v1 reserved id, retired by WP8.2


def test_recipes_family_cmu_lists_only_sim_validated_recipes(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, setting in world.env().items():
        monkeypatch.setenv(name, setting)
    result = CliRunner().invoke(app, ["recipes", "--family", "cmu", "--json"])
    assert result.exit_code == 0, result.output
    listing = yaml.safe_load(result.stdout)
    statuses = {entry["id"]: entry["status"] for entry in listing["recipes"]}
    assert statuses and set(statuses.values()) == {"sim_validated"}, statuses
    assert set(statuses) == set(SECTION_3_2) - {"fecap.cv_butterfly"}  # family nvm (card nvm/fecap-cv-butterfly)


def test_every_card_sits_on_l6_and_the_stage_runs_and_checks_its_recipes(registry: RecipeRegistry) -> None:
    _path, stage, problem = load_stage(REPO_ROOT, "L6")
    assert stage is not None, problem
    assert set(stage.recipes) == set(SECTION_3_2)
    for recipe_id in SECTION_3_2:
        recipe = registry.get(recipe_id)
        assert recipe.card is not None, recipe_id
        assert _front(REPO_ROOT / recipe.card)["bringup_stage"] == "L6", recipe_id
        checks = stage.checks_for(recipe_id)
        assert any(c.quantity == "cleanup" for c in checks), recipe_id  # one record per recipe, cleanup judged
    assert set(stage.record_keys()) == {*SECTION_3_2, None}  # + the stage record (corrections, store, SCUU rest)
    judged = {c.id: c.tolerance for c in stage.checks if c.tolerance is not None}
    assert judged["known_c"].rel == 0.01  # blueprint v2 7.4 L6: C standard +-1 %
    assert judged["qscv_cox"].rel == 0.02 and judged["mosc_cox"].rel == 0.02  # QSCV vs HF (SCUU same landing)
    assert {c.id for c in stage.checks_for(None)} == {"corrst_on", "store_written", "scuu_rest"}


def test_the_cmu_runbooks_exist_and_the_cards_name_them() -> None:
    for runbook in RUNBOOKS:
        front = _front(DEBUG_DIR / f"{runbook}.md")
        assert front["id"] == runbook and front["maturity"] == "seed"
    named = set()
    for card in (REPO_ROOT / ".agents" / "skills" / "b1500-test" / "cards" / "cmu").glob("*.md"):
        named |= set(_front(card)["debug"])
    assert set(RUNBOOKS) <= named


def test_cmu_analysis_methods_are_implemented() -> None:
    names = {m.name for m in methods_for("cmu")}
    assert {"cv_cox", "cv_flatband", "cv_doping_profile", "cv_vth", "cv_hysteresis", "impedance_convert", "plot_cv",
            "cf_dispersion", "ct_recovery", "cv_ac_dependence", "cv_pulsed_vs_dc", "dit_high_low",
            "dit_conductance"} <= names
    assert all(callable(m.fn) for m in methods_for("cmu"))  # every registered method is implemented (WP11.2)


def test_the_s11_flow_runs_on_the_real_recipes(svc: B1500Service) -> None:
    """Acceptance scenario S11 (blueprint v2 8.2) on the service: the C-V is blocked by R-CORR-01 with the correction
    card as next step; phase compensation and open need `physical_setup` and run with their summaries (the probes
    lifted), then the short; the C-V then needs confirmation for the unverified pin map and `dut_envelope` (the MFCMU's
    nominal AC current against `moscap-generic`'s 1 uA; the rule stays, owner default of the WP8.3 question) and meets
    the scenario's thresholds against the simulator truth: Cox +-2 %, Vfb +-30 mV of `truth()`."""
    blocked = svc.validate_plan(**MOSCAP)
    assert blocked.tier == "blocked" and CORRECTION_NEXT_STEP in blocked.next_steps
    assert {f.rule_id for f in blocked.findings if f.severity == "block"} == {"R-CORR-01"}
    for recipe_id in ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short"):
        plan = svc.validate_plan(recipe_id=recipe_id, pin_map="moscap-cmu")
        assert plan.tier == "needs_confirmation" and "physical_setup" in plan.confirm_reasons, plan.message
        result = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]
        assert result.ok and result.outcome == "completed", result.message
    plan = svc.validate_plan(**MOSCAP)
    assert plan.tier == "needs_confirmation" and set(plan.confirm_reasons) == {"unverified_pin_map", "dut_envelope"}
    assert plan.summary is not None and "R-DUT-01" in plan.summary
    result = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]
    assert result.ok and result.simulated and result.outcome == "completed", result.message
    truth = moscap_truth().truth()
    assert value(result, "cv_cox", "cox") == pytest.approx(truth["cox_f"], rel=0.02)
    assert value(result, "cv_flatband", "vfb") == pytest.approx(truth["vfb_v"], abs=0.03)  # +29 mV: border traps
