"""``b1500 dev lint-skills`` (blueprint v1 6.1-6.5, v2 6.2, 8.1 ``skills/``): the repository, a positive fixture
tree and one negative case per defect class.

Fixtures live in ``tests/fixtures/skills/``: ``positive/`` is a complete v2 root (``.agents/skills/`` with the three
skills: a card in ``cards/smu/``, its generated ``cards/README.md``, a knowledge file, runbooks, the bring-up stage
template, one stage file and the record template; ``recipes/`` whose ``mosfet.idvg`` copy points at the card; a copy
of the manual-corpus fixture catalog and corpus under ``references/manuals/`` so citations are checked; config
comes from the repository's committed ``config/``). Each ``negative/<case>/`` holds ``case.yaml`` (``edits``: exact
text substitutions in positive files, each ``old`` occurring exactly once; ``move``: positive files to rename,
``{from, to}``; ``delete``: positive files to remove; ``expect``: the problems as ``code``/``file``/message
substring) and optionally ``tree/``, copied over the positive tree. A case passes when the lint fails with exactly
the expected problems and nothing else.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools import skills as lint_skills
from b1500_test_agent.devtools.budget import fallback_counter
from b1500_test_agent.devtools.skills.common import LintReport
from b1500_test_agent.devtools.skills.markdown import slugify
from b1500_test_agent.devtools.skills.params import parse_interval, parse_value

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "skills"
POSITIVE = FIXTURES / "positive"
NEGATIVE = FIXTURES / "negative"
CONFIG = ROOT / "config"
CARD = ".agents/skills/b1500-test/cards/smu/mosfet-idvg.md"
STAGE = ".agents/skills/b1500-bringup/stages/l4-mosfet.md"
CASES = sorted(p.name for p in NEGATIVE.iterdir() if (p / "case.yaml").is_file())


def _materialize(case: str, target: Path) -> dict[str, Any]:
    """Copy the positive tree to ``target`` and apply negative case ``case``; returns the case spec."""
    spec = yaml.safe_load((NEGATIVE / case / "case.yaml").read_text(encoding="utf-8"))
    shutil.copytree(POSITIVE, target)
    for edit in spec.get("edits", []):
        path = target / edit["file"]
        text = path.read_text(encoding="utf-8")
        assert text.count(edit["old"]) == 1, f"{case}: edit target not unique in {edit['file']}: {edit['old']!r}"
        path.write_text(text.replace(edit["old"], edit["new"]), encoding="utf-8")
    for move in spec.get("move", []):
        source, destination = target / move["from"], target / move["to"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    for rel in spec.get("delete", []):
        (target / rel).unlink()
    overlay = NEGATIVE / case / "tree"
    if overlay.is_dir():
        shutil.copytree(overlay, target, dirs_exist_ok=True)
    return spec


def _lint(root: Path) -> LintReport:
    return lint_skills.lint_skills(root, config_dir=CONFIG)


def test_negative_cases_exist() -> None:
    assert {"broken-link", "param-out-of-range", "dangling-card-path", "card-lists-missing-recipe", "over-budget",
            "bad-frontmatter"} <= set(CASES)
    # WP5.10 (blueprint 10.1 AC): missing index row, bad citation page, card outside a family folder, and the other
    # v2 checks
    assert {"missing-index-row", "bad-citation-page", "card-outside-family-folder", "card-modules-routes",
            "card-family-mismatch", "card-stage-not-run", "card-manual-form", "stage-files",
            "unknown-command", "recipe-without-card"} <= set(CASES)


def test_repository_skills_are_clean() -> None:
    report = lint_skills.lint_skills(ROOT)
    assert report.ok, lint_skills.format_report(report)
    assert "b1500-test" in report.skills


def test_positive_fixture_passes() -> None:
    report = _lint(POSITIVE)
    assert report.ok, lint_skills.format_report(report)
    assert report.skills == ["b1500-bringup", "b1500-debug", "b1500-test"]
    assert report.cards == [CARD]  # _TEMPLATE.md and the index README.md are not cards
    assert report.stages == [STAGE]
    assert "citations: 2 checked (ids, pages, printed labels and keywords)" in report.notes
    assert any(note.startswith("b1500 commands: ") for note in report.notes)
    assert report.knowledge == [".agents/skills/b1500-test/knowledge/06-analysis-extraction.md"]
    assert report.runbooks == ["compliance-hit", "noisy-data"]
    [example] = report.example_plans
    assert (example.card, example.recipe_id, example.sim_scenario) == ("mosfet-idvg", "mosfet.idvg", "nmos_basic")
    assert example.status == "ok" and example.tier == "ok" and example.plan_id


def test_example_plans_never_touch_the_repository_data(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    assert _lint(root).ok
    assert not (root / "data").exists() and not (root / "config").exists()


@pytest.mark.parametrize("case", CASES)
def test_negative_case_fails_with_exactly_the_expected_problems(case: str, tmp_path: Path) -> None:
    spec = _materialize(case, tmp_path / "root")
    report = _lint(tmp_path / "root")
    assert not report.ok
    found = [(p.code, p.file, p.message) for p in report.problems]
    expected = spec["expect"]
    for item in expected:
        assert any(code == item["code"] and file == item["file"] and item["contains"] in message
                   for code, file, message in found), f"{case}: missing {item}; got {found}"
    for code, file, message in found:
        assert any(code == item["code"] and file == item["file"] and item["contains"] in message
                   for item in expected), f"{case}: unexpected problem [{code}] {file}: {message}"


def test_problem_lines_point_at_the_defect(tmp_path: Path) -> None:
    _materialize("param-out-of-range", tmp_path / "root")
    report = _lint(tmp_path / "root")
    lines = (tmp_path / "root" / CARD).read_text(encoding="utf-8").splitlines()
    for problem in report.problems:
        assert problem.line is not None
        name = problem.message.split()[1]
        assert f"`{name}`" in lines[problem.line - 1]


def test_entry_skill_byte_budget(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    skill = root / ".agents/skills/b1500-test/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n" + "x" * 9_000 + "\n", encoding="utf-8")
    report = _lint(root)
    assert [(p.code, p.file) for p in report.problems] == [("budget", ".agents/skills/b1500-test/SKILL.md")]
    assert "bytes (limit 9,000)" in report.problems[0].message


def test_knowledge_and_card_line_budgets(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    for rel, count in ((".agents/skills/b1500-test/knowledge/06-analysis-extraction.md", 300), (CARD, 150)):
        path = root / rel
        text = path.read_text(encoding="utf-8")
        filler = count - len(text.splitlines()) + 1
        path.write_text(text + "\n".join(f"filler {i}" for i in range(filler)) + "\n", encoding="utf-8")
    messages = sorted(p.message for p in _lint(root).problems)
    assert messages == ["card has 151 lines (limit 150)", "knowledge file has 301 lines (limit 300)"]


def test_missing_entry_skill_and_skill_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    shutil.rmtree(root / ".agents/skills/b1500-test")
    report = _lint(root)
    assert ("skill_layout", ".agents/skills/b1500-test") in {(p.code, p.file) for p in report.problems}
    assert "recipe_card" in {p.code for p in report.problems}  # the recipe still points at the removed card
    shutil.rmtree(root / ".agents")
    assert any(p.code == "skill_layout" and "not found" in p.message for p in _lint(root).problems)


def test_always_loaded_budget_over_limit(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    (root / "AGENTS.md").write_text("word " * 3_000, encoding="utf-8")
    report = lint_skills.lint_skills(root, config_dir=CONFIG)
    assert report.always_loaded is not None and report.always_loaded.total > 2_500
    if report.always_loaded.warning is None:
        assert [p.code for p in report.problems] == ["budget"]
    # The chars/3.5 fallback overestimates: an excess is only a note, never a problem.
    estimate = lint_skills.lint_skills(root, config_dir=CONFIG, counter=fallback_counter(warning="offline"))
    assert estimate.ok and estimate.notes and "estimate only" in estimate.notes[0]


def test_example_plan_needs_a_config(tmp_path: Path) -> None:
    report = lint_skills.lint_skills(POSITIVE, config_dir=tmp_path / "nowhere")
    assert [(p.code, p.file) for p in report.problems] == [("example_plan", CARD)]
    assert "config folder" in report.problems[0].message


def test_cli_lint_skills(tmp_path: Path) -> None:
    runner = CliRunner()
    good = runner.invoke(app, ["dev", "lint-skills", "--root", str(POSITIVE), "--config-dir", str(CONFIG)])
    assert good.exit_code == 0, good.output
    assert good.stdout.startswith("skills: clean") and "example plan mosfet-idvg" in good.stdout
    _materialize("broken-link", tmp_path / "root")
    bad = runner.invoke(app, ["dev", "lint-skills", "--root", str(tmp_path / "root"), "--config-dir", str(CONFIG),
                              "--json"])
    assert bad.exit_code == 1
    payload = json.loads(bad.stdout)
    assert payload["ok"] is False and {p["code"] for p in payload["problems"]} == {"link", "anchor"}
    human = runner.invoke(app, ["dev", "lint-skills", "--root", str(tmp_path / "root"), "--config-dir", str(CONFIG)])
    assert human.exit_code == 1 and ".agents/skills/b1500-test/SKILL.md:" in human.stdout and "[link]" in human.stdout


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        ("4. Recipe and parameters", "4-recipe-and-parameters"),
        ("9. Common failures → debug", "9-common-failures--debug"),
        ("Subthreshold swing (SS)", "subthreshold-swing-ss"),
        ("`vth_max_gm` and [gm](x.md)", "vth_max_gm-and-gm"),
        ("Gate leakage: Ig(Vg)", "gate-leakage-igvg"),
    ],
)
def test_slugify_matches_github(heading: str, slug: str) -> None:
    assert slugify(heading) == slug


@pytest.mark.parametrize(
    ("text", "unit", "value"),
    [("-1 V", "V", -1.0), ("\u22121 V", "V", -1.0), ("50 mV", "V", 0.05), ("1e-6", "A", 1e-6), ("1 uA", "A", 1e-6),
     ("1 µA", "A", 1e-6), ("10 kOhm", "Ohm", 1e4), ("2 kΩ", "Ohm", 2e3), ("101", None, 101.0), ("0.5 s", "s", 0.5)],
)
def test_parse_value(text: str, unit: str | None, value: float) -> None:
    assert parse_value(text, unit)[0] == pytest.approx(value, rel=1e-12)


@pytest.mark.parametrize(("text", "unit"), [("50 mA", "V"), ("abc", "V"), ("3 V", None), ("1 xV", "V")])
def test_parse_value_rejects(text: str, unit: str | None) -> None:
    with pytest.raises(ValueError):
        parse_value(text, unit)


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [("-10..10 V", -10, 10), ("20..100 mV", 0.02, 0.1), ("1 pA..1 mA", 1e-12, 1e-3), ("[-5, 5] V", -5, 5),
     ("0 to 3 V", 0, 3), ("-2 … 0 V", -2, 0)],
)
def test_parse_interval(text: str, low: float, high: float) -> None:
    assert parse_interval(text, "V" if "V" in text else "A") == (pytest.approx(low), pytest.approx(high))


@pytest.mark.parametrize("text", ["5..1 V", "1 V", "1..2..3 V"])
def test_parse_interval_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_interval(text, "V")


def test_symlinks_in_skills_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    try:
        (root / ".agents/skills/b1500-test/knowledge/alias.md").symlink_to(
            root / ".agents/skills/b1500-test/knowledge/README.md")
        (root / ".agents/skills/linked-skill").symlink_to(root / ".agents/skills/b1500-debug",
                                                          target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # Windows without Developer Mode
        pytest.skip(f"symlinks unavailable: {exc}")
    found = {(p.code, p.file) for p in _lint(root).problems}
    assert found == {("skill_layout", ".agents/skills/b1500-test/knowledge/alias.md"),
                     ("skill_layout", ".agents/skills/linked-skill")}
