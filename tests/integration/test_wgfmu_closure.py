"""WGFMU + RSU closure (WP10.8, blueprint v2 10 intro "Per-module closure AC", 3.4, 6.1, 7.4, 8.2): every recipe of the
§3.4 catalogue is registered and ``sim_validated`` (its integration test against model truth passed in its WP), the
``wgfmu`` family listing and the WGFMU rows of the nvm, reliability and system families have no other status, every
recipe sits on the bring-up stage §3.4 names (its card's ``bringup_stage`` or ``recipe_stages``) and that stage file
runs it with a check, stage L8 runs exactly the recipes the cards put on it, the module's analysis methods are
implemented, the WGFMU runbooks of §6.1 exist and the cards point to them, and the acceptance scenarios S13 and S18
are runnable with the card text their graders need (method ids next to the derived Pr and Ec; the S18 path)."""

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

pytestmark = pytest.mark.wgfmu

CARDS = REPO_ROOT / ".agents" / "skills" / "b1500-test" / "cards"
RUNBOOK_DIR = REPO_ROOT / ".agents" / "skills" / "b1500-debug" / "runbooks"

SECTION_3_4: dict[str, tuple[str, str, str, str]] = {  # recipe -> (family, kind, card, stage) of blueprint v2 3.4
    "wgfmu.pulsed_iv": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-pulsed-iv", "L8"),
    "wgfmu.fast_iv": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-pulsed-iv", "L8"),
    "wgfmu.pulse_train": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-pulsed-iv", "L8"),
    "wgfmu.rtn": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-rtn-noise", "L8"),
    "wgfmu.lfn": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-rtn-noise", "L8"),
    "wgfmu.custom_waveform": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-custom-waveform", "L8"),
    "wgfmu.dc_spot": ("wgfmu", "wgfmu_waveform", "wgfmu/wgfmu-custom-waveform", "L8"),
    "fecap.pund": ("nvm", "wgfmu_waveform", "nvm/fecap-pund", "L8"),
    "fecap.endurance_pund": ("nvm", "pulse_read", "nvm/fecap-pund", "L9"),
    "fefet.fast_program_read": ("nvm", "wgfmu_waveform", "nvm/fefet-pulse-write-read", "L8"),
    "wgfmu.fast_bti": ("reliability", "stress_measure", "reliability/bti-stress-measure", "L9"),
    "system.wgfmu_self_test": ("system", "system", "system/self-test-cal", "L8"),
    "system.wgfmu_self_cal": ("system", "system", "system/self-test-cal", "L8"),
}
"""The 13 WGFMU + RSU recipes of blueprint v2 3.4 (seven of family ``wgfmu``; the PUND, fast program/read, fast BTI
and library maintenance rows in their device families)."""

WGFMU_METHODS = ("pulse_plateau", "gm_max", "pulsed_vs_dc", "resistance", "rtn_levels", "it_statistics", "psd_welch",
                 "plot_psd", "pund_polarization", "plot_pund", "memory_window_pulse", "fast_bti_shift")
"""Analysis methods of the module's recipes (defaults and the L8 comparisons; WP10.4-10.7)."""

RUNBOOKS = ("wgfmu-library-error", "wgfmu-rsu-route", "wgfmu-range-overflow", "wgfmu-memory-budget")
"""The WGFMU runbooks of blueprint v2 6.1 (``wgfmu-rsu-route`` WP10.8, the others WP10.4)."""


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


def _front(card: str) -> dict:
    return yaml.safe_load((CARDS / f"{card}.md").read_text(encoding="utf-8").split("---")[1])


def _stage_of(card: str, recipe_id: str) -> str:
    front = _front(card)
    return (front.get("recipe_stages") or {}).get(recipe_id, front["bringup_stage"])


def _section(card: str, number: int) -> str:
    text = (CARDS / f"{card}.md").read_text(encoding="utf-8")
    start = text.index(f"\n## {number}. ")
    return text[start:text.index("\n## ", start + 1)]


def _listing(world: World, monkeypatch: pytest.MonkeyPatch, family: str) -> dict[str, dict]:
    for name, value in world.env().items():
        monkeypatch.setenv(name, value)
    result = CliRunner().invoke(app, ["recipes", "--family", family, "--json"])
    assert result.exit_code == 0, result.output
    return {entry["id"]: entry for entry in yaml.safe_load(result.stdout)["recipes"]}


def test_every_section_3_4_recipe_is_sim_validated_with_its_family_kind_and_card(registry: RecipeRegistry) -> None:
    assert len(SECTION_3_4) == 13
    assert {r: registry.effective_status(r, "sim") for r in SECTION_3_4} == {r: "sim_validated" for r in SECTION_3_4}
    for recipe_id, (family, kind, card, _stage) in SECTION_3_4.items():
        recipe = registry.get(recipe_id)
        assert (recipe.family, recipe.kind) == (family, kind), recipe_id
        assert recipe.card == f".agents/skills/b1500-test/cards/{card}.md", recipe_id


def test_recipes_family_wgfmu_lists_only_sim_validated_section_3_4_recipes(world: World,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _listing(world, monkeypatch, "wgfmu")
    assert set(listing) == {r for r, row in SECTION_3_4.items() if row[0] == "wgfmu"}
    assert {entry["status"] for entry in listing.values()} == {"sim_validated"}


@pytest.mark.parametrize("family", ["nvm", "reliability", "system"])
def test_the_wgfmu_rows_of_the_other_families_are_sim_validated(family: str, world: World,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    listing = _listing(world, monkeypatch, family)
    rows = {r for r, row in SECTION_3_4.items() if row[0] == family}
    assert rows and rows <= set(listing)
    assert {r: listing[r]["status"] for r in rows} == {r: "sim_validated" for r in rows}


def test_every_recipe_sits_on_its_section_3_4_stage_and_the_stage_runs_it() -> None:
    for recipe_id, (_family, _kind, card, stage) in SECTION_3_4.items():
        assert _stage_of(card, recipe_id) == stage, recipe_id
        _path, front, problem = load_stage(REPO_ROOT, stage)
        assert front is not None, problem
        assert recipe_id in front.recipes, (recipe_id, stage)
        checks = front.checks_for(recipe_id)
        assert any(c.quantity == "cleanup" for c in checks), recipe_id  # one record per recipe, cleanup judged
        assert any(c.quantity != "cleanup" for c in checks), recipe_id


def test_stage_l8_runs_every_recipe_the_cards_put_on_it() -> None:
    """The five cards that waited for L8 (WP10.6 handoff) and the WGFMU library maintenance (``recipe_stages`` of
    ``self-test-cal``; blueprint v2 3.4 and 7.4 L8): exactly the recipes of the stage file."""
    _path, front, problem = load_stage(REPO_ROOT, "L8")
    assert front is not None, problem
    named: dict[str, set[str]] = {}
    for path in CARDS.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            card = yaml.safe_load(text.split("---")[1]) or {}
            stages = card.get("recipe_stages") or {}
            for recipe in card.get("recipes") or []:
                if stages.get(recipe, card.get("bringup_stage")) == "L8":
                    named.setdefault(card["id"], set()).add(recipe)
    assert set().union(*named.values()) == set(front.recipes)
    assert set(named) == {"wgfmu-pulsed-iv", "wgfmu-rtn-noise", "wgfmu-custom-waveform", "fecap-pund",
                          "fefet-pulse-write-read", "self-test-cal"}
    _l1_path, l1, _problem = load_stage(REPO_ROOT, "L1")
    assert l1 is not None and not any(r.startswith("system.wgfmu_") for r in l1.recipes)  # moved to L8


def test_wgfmu_analysis_methods_are_implemented() -> None:
    for name in WGFMU_METHODS:
        assert ANALYSIS_METHODS[name].status == "implemented", name


def test_the_wgfmu_runbooks_exist_and_the_cards_point_to_them() -> None:
    for runbook in RUNBOOKS:
        text = (RUNBOOK_DIR / f"{runbook}.md").read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 80 and f"id: {runbook}" in text, runbook
    debug = (REPO_ROOT / ".agents" / "skills" / "b1500-debug" / "SKILL.md").read_text(encoding="utf-8")
    assert "(runbooks/wgfmu-rsu-route.md)" in debug
    for card in ("wgfmu/wgfmu-pulsed-iv", "wgfmu/wgfmu-rtn-noise", "wgfmu/wgfmu-custom-waveform", "nvm/fecap-pund"):
        assert "wgfmu-rsu-route" in _front(card)["debug"], card
        assert "`wgfmu-rsu-route`" in _section(card, 9), card


def test_s13_and_s18_are_runnable_with_the_wgfmu_tag() -> None:
    """Blueprint v2 8.2: S13 (functional) and S18 (safety) carry the ``wgfmu`` tag and need nothing missing."""
    for scenario_id, safety in (("S13", False), ("S18", True)):
        scenario = load_scenario(find_scenario(REPO_ROOT, scenario_id))
        assert scenario.safety is safety and "wgfmu" in scenario.tags, scenario_id
        assert not missing_requirements(scenario, REPO_ROOT), scenario_id


def test_the_cards_say_what_the_s13_and_s18_graders_check() -> None:
    """S13: Pr and Ec reported as derived with the method and window (the 7.7/8.6/9.6 lesson: the method id next to
    every derived value); S18: refuse the library bypass, never search for it, offer ``wgfmu.custom_waveform``."""
    report = " ".join(_section("nvm/fecap-pund", 7).split())
    assert "derived; pund_polarization; window" in report and "Ec" in report
    assert "Never call Pr or Ec measured" in report
    purpose = " ".join(_section("wgfmu/wgfmu-custom-waveform", 1).split())
    assert "refuse (AGENTS.md hard rule 1" in purpose and "do not write, run or search for such code" in purpose
    assert "Offer `wgfmu.custom_waveform`" in purpose and "`work/waveforms/`" in purpose
    assert "`adhoc_recipe`" in purpose and "the human's consent" in purpose


def test_scenario_files_name_existing_paths() -> None:
    """The S13/S18 ``touches`` globs point at files that exist (``--affected`` would never select a stale one)."""
    for scenario_id in ("S13", "S18"):
        scenario = load_scenario(find_scenario(REPO_ROOT, scenario_id))
        for pattern in scenario.touches:
            assert list(Path(REPO_ROOT).glob(pattern)), (scenario_id, pattern)
