"""HV-SPGU + 16440A closure (WP9.6, blueprint v2 10 intro "Per-module closure AC", 3.3, 7.4, 8.2): every recipe of the
§3.3 catalogue is registered and ``sim_validated`` (its integration test against model truth passed in its WP), the
``spgu`` family listing and the nvm pulse rows have no ``not_implemented`` entry left, every recipe's card sits on the
bring-up stage §3.3 names and that stage file runs it, the module's analysis methods are implemented, its coverage
ledger rows are closed and its acceptance scenarios (S12, the rewritten S3) are runnable while v1's S3 is gone."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.bringup import load_stage
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.acceptance.scenario import find_scenario, load_scenario, missing_requirements
from tests.integration.helpers import REPO_ROOT, World

pytestmark = pytest.mark.spgu

SECTION_3_3: dict[str, tuple[str, str, str]] = {  # recipe -> (kind, card, bring-up stage) of blueprint v2 3.3
    "system.selector_check": ("spgu_pulse", "spgu/selector-check", "L7"),
    "spgu.pulse_train": ("spgu_pulse", "spgu/spgu-pulse-train", "L7"),
    "spgu.alwg_sequence": ("spgu_pulse", "spgu/spgu-pulse-train", "L7"),
    "mosfet.charge_pumping": ("spgu_pulse", "spgu/charge-pumping", "L7"),
    "fefet.pulse_write_read": ("pulse_read", "nvm/fefet-pulse-write-read", "L7"),
    "spgu.program_smu_read": ("pulse_read", "nvm/fefet-pulse-write-read", "L7"),
    "fefet.switching_kinetics": ("pulse_read", "nvm/fefet-switching-kinetics", "L7"),
    "fefet.endurance": ("pulse_read", "nvm/fefet-endurance-retention", "L9"),
    "fefet.retention": ("pulse_read", "nvm/fefet-endurance-retention", "L9"),
}
"""The nine HV-SPGU + 16440A recipes of blueprint v2 3.3 (four of family ``spgu``, five ``nvm`` pulse_read rows)."""

SPGU_METHODS = ("charge_pumping", "memory_window_pulse", "switching_kinetics_fit", "endurance_summary",
                "retention_fit")
"""Analysis methods of the module's recipes (WP9.3-9.5)."""

WGFMU_PULSE_READ = {"fecap.endurance_pund"}
"""``nvm`` recipes of kind ``pulse_read`` whose source is the WGFMU (WP10.6, blueprint v2 3.4)."""


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


def test_every_section_3_3_recipe_is_sim_validated_with_its_kind_and_card(registry: RecipeRegistry) -> None:
    assert len(SECTION_3_3) == 9
    assert {r: registry.effective_status(r, "sim") for r in SECTION_3_3} == {r: "sim_validated" for r in SECTION_3_3}
    for recipe_id, (kind, card, _stage) in SECTION_3_3.items():
        recipe = registry.get(recipe_id)
        assert recipe.kind == kind, recipe_id
        assert recipe.card == f".agents/skills/b1500-test/cards/{card}.md", recipe_id


def _listing(world: World, monkeypatch: pytest.MonkeyPatch, family: str) -> dict[str, dict]:
    for name, value in world.env().items():
        monkeypatch.setenv(name, value)
    result = CliRunner().invoke(app, ["recipes", "--family", family, "--json"])
    assert result.exit_code == 0, result.output
    return {entry["id"]: entry for entry in yaml.safe_load(result.stdout)["recipes"]}


def test_recipes_family_spgu_lists_only_sim_validated_section_3_3_recipes(world: World,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _listing(world, monkeypatch, "spgu")
    assert set(listing) == {"system.selector_check", "spgu.pulse_train", "spgu.alwg_sequence",
                            "mosfet.charge_pumping"}
    assert {entry["status"] for entry in listing.values()} == {"sim_validated"}


def test_the_nvm_pulse_rows_of_section_3_3_are_sim_validated(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _listing(world, monkeypatch, "nvm")
    pulse_rows = {r for r, (kind, _card, _stage) in SECTION_3_3.items() if kind == "pulse_read"}
    assert pulse_rows <= set(listing)
    assert {r: listing[r]["status"] for r in pulse_rows} == {r: "sim_validated" for r in pulse_rows}
    # WP10.6: fecap.endurance_pund is the WGFMU path of pulse_read (blueprint v2 3.4, not an HV-SPGU row)
    assert {r for r, entry in listing.items() if entry["kind"] == "pulse_read"} == pulse_rows | WGFMU_PULSE_READ


def test_cards_sit_on_their_section_3_3_stage_and_the_stage_runs_them(registry: RecipeRegistry) -> None:
    for recipe_id, (_kind, card, stage) in SECTION_3_3.items():
        text = Path(REPO_ROOT / ".agents/skills/b1500-test/cards" / f"{card}.md").read_text(encoding="utf-8")
        assert yaml.safe_load(text.split("---")[1])["bringup_stage"] == stage, recipe_id
        _path, front, problem = load_stage(REPO_ROOT, stage)
        assert front is not None, problem
        assert recipe_id in front.recipes, (recipe_id, stage)
        assert front.checks_for(recipe_id), (recipe_id, stage)  # each recipe has its checks in the stage file


def test_stage_l7_runs_every_recipe_of_the_cards_that_name_it() -> None:
    """Every recipe a card puts on L7 (the SPGU cards plus the DC FeFET loop, the reference of the pulse memory window);
    a card's ``recipe_stages`` moves single recipes to another stage (WP10.6: ``fefet.fast_program_read`` on L8)."""
    _path, front, problem = load_stage(REPO_ROOT, "L7")
    assert front is not None, problem
    named: set[str] = set()
    for path in (REPO_ROOT / ".agents/skills/b1500-test/cards").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            card = yaml.safe_load(text.split("---")[1]) or {}
            stages = card.get("recipe_stages") or {}
            named |= {r for r in card.get("recipes") or [] if stages.get(r, card.get("bringup_stage")) == "L7"}
    assert named == set(front.recipes)
    assert "fefet.dual_sweep_mw" in named and "fefet.fast_program_read" not in named


def test_spgu_analysis_methods_are_implemented() -> None:
    for name in SPGU_METHODS:
        assert ANALYSIS_METHODS[name].status == "implemented", name


def test_s12_and_the_rewritten_s3_are_runnable_and_v1_s3_is_retired() -> None:
    """Blueprint v2 8.2: WP9.6 replaces v1's S3 by the rewritten S3; S12 and S3 carry the ``spgu`` tag."""
    for scenario_id in ("S3", "S12"):
        path = find_scenario(REPO_ROOT, scenario_id)
        scenario = load_scenario(path)
        assert scenario.safety and "spgu" in scenario.tags and not missing_requirements(scenario, REPO_ROOT)
    assert find_scenario(REPO_ROOT, "S3").name == "S03-spgu-overdrive.yaml"
    assert not (REPO_ROOT / "tests/acceptance/scenarios/S03-wgfmu-pund.yaml").exists()
