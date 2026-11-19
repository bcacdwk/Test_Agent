"""Building blocks of lint-skills v2 (blueprint v2 6.2): schema constants stay in step with the models, module and
route derivation from recipe roles, family-folder placement, recipe-qualified parameter rows, the ``b1500``
command walk (alternatives, options, scope) and the repository's stage notes."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.skills import lint as lint_skills
from b1500_test_agent.devtools.skills.cards import card_folder_problem, recipe_modules, recipe_routes
from b1500_test_agent.devtools.skills.commands import alternatives, command_files, command_problems, named_commands_at
from b1500_test_agent.devtools.skills.common import (
    CARDLESS_RECIPES,
    FAMILIES,
    STAGES,
    CardModule,
    StageId,
)
from b1500_test_agent.devtools.skills.params import split_param_cell
from b1500_test_agent.models.recipe import RecipeFamily
from b1500_test_agent.models.station import ModuleType

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / ".agents" / "skills" / "b1500-test"


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(ROOT / "recipes", repo_root=ROOT)


def test_schema_constants_follow_the_models() -> None:
    assert set(get_args(CardModule)) == {*get_args(ModuleType), "GNDU"}
    assert FAMILIES == get_args(RecipeFamily)
    assert tuple(STAGES) == get_args(StageId)
    assert [stem for stem, _goal in STAGES.values()] == [  # blueprint v2 6.1 file names
        "s0-physical", "l0-probe-config", "l1-smu-zero", "l2-resistors", "l3-diode", "l4-mosfet", "l5-smu-advanced",
        "l6-cmu", "l7-spgu-selector", "l8-wgfmu", "l9-long-runs", "l10-harness-handoff"]


def test_cardless_recipes_are_runnable_and_cardless(registry: RecipeRegistry) -> None:
    for recipe_id in CARDLESS_RECIPES:
        recipe = registry.get(recipe_id)
        assert recipe.card is None and recipe.status != "not_implemented"


def test_recipe_modules_and_routes(registry: RecipeRegistry) -> None:
    diode = registry.get("basic.diode_iv")
    assert {"HRSMU", "GNDU"} <= recipe_modules(diode)  # anode HRSMU only; cathode SMU or GNDU
    assert "MFCMU" not in recipe_modules(diode) and "HVSPGU" not in recipe_modules(diode)
    assert recipe_modules(registry.get("system.self_test")) is None  # no roles: the whole instrument
    assert recipe_routes(registry.get("mosfet.idvg")) == {"selector_16440a:smu", "scuu:smu", "asu:smu", "rsu:smu"}
    assert recipe_routes(registry.get("system.self_cal")) == set()


def test_card_folder_problem() -> None:
    assert card_folder_problem(ENTRY, ENTRY / "cards" / "smu" / "x.md") is None
    assert "outside a family folder" in (card_folder_problem(ENTRY, ENTRY / "cards" / "x.md") or "")
    assert "not a family folder" in (card_folder_problem(ENTRY, ENTRY / "cards" / "misc" / "x.md") or "")
    assert "not a family folder" in (card_folder_problem(ENTRY, ENTRY / "cards" / "smu" / "a" / "x.md") or "")


@pytest.mark.parametrize(("cell", "name", "recipes"), [
    ("`vd`", "vd", ()),
    ("`operation` (`system.self_cal`)", "operation", ("system.self_cal",)),
    ("operation (system.self_test, system.self_cal)", "operation", ("system.self_test", "system.self_cal")),
    ("`vd` (typical)", "vd (typical)", ()),  # not a recipe id: the whole cell is the name (and gets reported)
])
def test_split_param_cell(cell: str, name: str, recipes: tuple[str, ...]) -> None:
    assert split_param_cell(cell) == (name, recipes)


def test_command_alternatives_and_problems() -> None:
    assert list(alternatives(["status|recipes", "--json"])) == [["status", "--json"], ["recipes", "--json"]]
    assert list(alternatives(["harness", "init", "--codex|--claude"])) == [["harness", "init", "--codex|--claude"]]
    assert command_problems(["status|recipes|plan|runs|show|analyze|note|shutdown", "--json"]) == []
    assert command_problems(["harness", "init", "--codex|--claude"]) == []
    assert command_problems(["manual", "search", "<terms>", "--doc", "PG"]) == []
    assert command_problems(["status|stauts"]) == ["no command `b1500 stauts`"]
    assert command_problems(["manual", "page", "--printed", "4-115", "--bogus"]) == [
        "`b1500 manual page` has no option --bogus"]


def test_command_extraction_has_line_numbers() -> None:
    text = "prose b1500 status\n\n`uv run b1500 doctor --probe` and `b1500 dev`\n```bash\nuv run b1500 runs\n```\n"
    assert named_commands_at(text) == [(3, ["doctor", "--probe"]), (3, ["dev"]), (5, ["runs"])]


def test_command_scope_skips_the_plan_and_session_reports() -> None:
    files = {p.relative_to(ROOT).as_posix() for p in command_files(ROOT)}
    assert ".agents/skills/b1500-bringup/SKILL.md" in files and "docs/hardware-bringup.md" in files
    assert "AGENTS.md" in files and "CLAUDE.md" in files and "src/b1500_test_agent/driver/AGENTS.md" in files
    assert "docs/acceptance/README.md" in files
    assert not any(f.startswith(("docs/design/", "docs/acceptance/20", ".claude/")) for f in files)


def test_repository_lint_notes_stages_without_files() -> None:
    report = lint_skills.lint_skills(ROOT)
    assert report.ok, lint_skills.format_report(report)
    stage_notes = [n for n in report.notes if n.startswith("bring-up stage ")]
    assert stage_notes and all("has no stage file yet" in n for n in stage_notes)
    assert any(n.startswith("bring-up stage L7 ") and "fefet-dual-sweep-mw" in n for n in stage_notes)
    assert not any(n.startswith(("bring-up stage S0 ", "bring-up stage L1 ", "bring-up stage L4 "))
                   for n in stage_notes)  # WP6.3 wrote S0, L0-L4 and L10
    assert report.stages == [f".agents/skills/b1500-bringup/stages/{stem}.md" for stem in sorted(
        ("s0-physical", "l0-probe-config", "l1-smu-zero", "l2-resistors", "l3-diode", "l4-mosfet",
         "l10-harness-handoff"))]
    assert "recipes without a card by design: generic.smu_staircase" in report.notes
    assert report.skills == ["b1500-bringup", "b1500-debug", "b1500-test"]
