"""Building blocks of lint-skills v2 (blueprint v2 6.2): schema constants stay in step with the models, module and
route derivation from recipe roles, family-folder placement, recipe-qualified parameter rows, the ``b1500``
command walk (alternatives, options, scope) and the repository's stage notes."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.skills import lint as lint_skills
from b1500_test_agent.devtools.skills.cards import (
    analysis_example_problem,
    card_folder_problem,
    check_analysis,
    recipe_modules,
    recipe_routes,
)
from b1500_test_agent.devtools.skills.commands import alternatives, command_files, command_problems, named_commands_at
from b1500_test_agent.devtools.skills.common import (
    CARDLESS_RECIPES,
    FAMILIES,
    STAGES,
    CardFrontmatter,
    CardModule,
    Lint,
    StageId,
)
from b1500_test_agent.devtools.skills.markdown import parse_markdown
from b1500_test_agent.devtools.skills.params import ParamRow, check_param_row, split_param_cell
from b1500_test_agent.models.recipe import ParamSpec, RecipeFamily
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


def test_file_parameter_rows_name_the_library_default_and_no_window() -> None:
    """WP10.4: a ``file`` parameter row states the recipe's default path; recommended and recipe range are ``-``."""
    spec = ParamSpec(type="file", default="recipes/waveforms/lwp_sample.csv")

    def row(default: str, recommended: str = "-", range_: str = "-") -> ParamRow:
        return ParamRow(name="gate_wave", default=default, recommended=recommended, range=range_, line=1)

    assert check_param_row(row("`recipes/waveforms/lwp_sample.csv`"), "wgfmu.custom_waveform", spec) == []
    assert [c for c, _ in check_param_row(row("recipes/waveforms/other.csv"), "r.x", spec)] == ["param_range"]
    assert [c for c, _ in check_param_row(row("recipes/waveforms/lwp_sample.csv", "1..2"), "r.x", spec)] == [
        "param_table"]
    assert [c for c, _ in check_param_row(row("-"), "r.x", spec)] == ["param_range"]
    assert check_param_row(row("required"), "r.x", ParamSpec(type="file")) == []


def test_command_alternatives_and_problems() -> None:
    assert list(alternatives(["status|recipes", "--json"])) == [["status", "--json"], ["recipes", "--json"]]
    assert list(alternatives(["harness", "init", "--codex|--claude"])) == [["harness", "init", "--codex|--claude"]]
    assert command_problems(["status|recipes|plan|runs|show|analyze|note|shutdown", "--json"]) == []
    assert command_problems(["harness", "init", "--codex|--claude"]) == []
    assert command_problems(["manual", "search", "<terms>", "--doc", "PG"]) == []
    assert command_problems(["status|stauts"]) == ["no command `b1500 stauts`"]
    assert command_problems(["manual", "page", "--printed", "4-115", "--bogus"]) == [
        "`b1500 manual page` has no option --bogus"]


def test_command_check_does_not_depend_on_how_help_is_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typer colours and re-wraps its Rich help when ``GITHUB_ACTIONS``/``FORCE_COLOR`` is set or the terminal is
    narrow (every CI command check failed that way, WP6.5); the verdicts come from the command tree, so they stay."""
    from typer import rich_utils
    from typer.testing import CliRunner

    from b1500_test_agent.adapters.cli import app
    from b1500_test_agent.devtools.skills import commands

    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", True)
    monkeypatch.setattr(rich_utils, "MAX_WIDTH", 40)
    commands._help_exit_code.cache_clear()
    try:
        assert "\x1b[" in CliRunner().invoke(app, ["run", "--help"]).output  # the condition is real
        assert command_problems(["status|recipes|plan|runs|show|analyze|note|shutdown", "--json"]) == []
        assert command_problems(["run", "--confirm", "PLAN_ID"]) == []
        assert command_problems(["manual", "page", "--printed", "4-115"]) == []
        assert command_problems(["dev", "sync-harness|gen-index|lint-skills"]) == []
        assert command_problems(["manual", "page", "--bogus"]) == ["`b1500 manual page` has no option --bogus"]
    finally:
        commands._help_exit_code.cache_clear()


def test_hidden_commands_and_options_count_as_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    import typer

    from b1500_test_agent.devtools.skills import commands

    demo = typer.Typer()

    @demo.command()
    def shown(flag: bool = typer.Option(False, "--flag"), secret: bool = typer.Option(False, "--secret", hidden=True)) \
            -> None:
        """A listed command with a hidden option."""

    @demo.command(hidden=True)
    def ghost() -> None:
        """A hidden command."""

    monkeypatch.setattr(commands, "_root_command", lambda: typer.main.get_command(demo))
    monkeypatch.setattr(commands, "_help_exit_code", lambda path: 0)
    assert commands.help_problem(["shown"], ["--flag", "--help"]) is None
    assert commands.help_problem(["shown"], ["--secret"]) == "`b1500 shown --help` does not list --secret"
    assert commands.help_problem(["ghost"], []) == "`b1500 ghost` is not listed by `b1500 --help`"
    assert commands.help_problem(["nowhere"], []) == "`b1500 nowhere` is not listed by `b1500 --help`"


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
    assert not any(n.startswith(("bring-up stage L5 ", "bring-up stage L9 ")) for n in stage_notes)  # WP7.7
    assert report.stages == [f".agents/skills/b1500-bringup/stages/{stem}.md" for stem in sorted(
        ("s0-physical", "l0-probe-config", "l1-smu-zero", "l2-resistors", "l3-diode", "l4-mosfet",
         "l5-smu-advanced", "l9-long-runs", "l10-harness-handoff"))]
    assert "recipes without a card by design: generic.smu_staircase" in report.notes
    assert report.skills == ["b1500-bringup", "b1500-debug", "b1500-test"]


# -- analysis-only cards (WP7.7: smu/compact-model-spice) ------------------------------------------------------------


def _front(**changes: object) -> dict[str, object]:
    doc = parse_markdown(ENTRY / "cards" / "smu" / "compact-model-spice.md", "card")
    assert isinstance(doc.front, dict)
    return {**doc.front, **changes}


def test_analysis_only_card_frontmatter() -> None:
    card = CardFrontmatter.model_validate(_front())
    assert card.recipes == [] and card.analysis == ["compact_model_fit", "model_compare", "export_spice_netlist"]
    with pytest.raises(ValidationError, match="recipes is empty"):
        CardFrontmatter.model_validate(_front(analysis=[]))
    with pytest.raises(ValidationError, match="twice"):
        CardFrontmatter.model_validate(_front(analysis=["model_compare", "model_compare"]))


def test_analysis_methods_and_example_of_an_analysis_only_card(registry: RecipeRegistry, tmp_path: Path) -> None:
    lint = Lint(tmp_path, ROOT / "recipes", ROOT / "config")
    front = CardFrontmatter.model_validate(_front(analysis=["compact_model_fit", "no_such_method", "charge_pumping"]))
    check_analysis(lint, tmp_path / "card.md", front, registry)
    messages = [p.message for p in lint.problems]
    assert any("no_such_method" in m and "not in ANALYSIS_METHODS" in m for m in messages)
    assert any("charge_pumping serves ['spgu']" in m for m in messages) and len(messages) == 2
    good = CardFrontmatter.model_validate(_front())
    assert analysis_example_problem("mosfet.idvg", good, registry) is None
    assert "do not apply" in (analysis_example_problem("basic.diode_iv", good, registry) or "")
    assert "not a registered recipe" in (analysis_example_problem("mosfet.nothing", good, registry) or "")
