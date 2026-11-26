"""Blank markers and the owner's question list (v2.1 KD-1, KD-2, KD-8): the marker lint of ``b1500 dev lint-skills``
(``devtools/skills/markers.py``) and ``docs/open-questions.md`` written by ``b1500 dev gen-index``
(``devtools/skills/questions.py``).

The repository has no marker problem and its question list is current; each marker form is accepted or refused as
the knowledge README's conventions say (step ids exist, owner questions end with ``?``, mentions and placeholders
pass); questions are collected from Markdown, YAML comments and debug cases, grouped by topic with links."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.skills import index, markers, questions
from b1500_test_agent.devtools.skills.common import Lint
from b1500_test_agent.devtools.skills.stages import STEPS_NAME
from b1500_test_agent.models.validation import StepsFile

ROOT = Path(__file__).resolve().parents[2]
POSITIVE = ROOT / "tests" / "fixtures" / "skills" / "positive"
KNOWLEDGE = ".agents/skills/b1500-test/knowledge/06-analysis-extraction.md"
runner = CliRunner()
_T = "TODO"  # built here so a source scan never meets a marker of this test file


def _scan(text: str, rel: str = "x.md") -> tuple[list[markers.Marker], list[markers.MarkerProblem]]:
    return markers.scan_text(text, rel)


def test_repository_markers_are_clean_and_counted() -> None:
    lint = Lint(ROOT, ROOT / "recipes", ROOT / "config")
    steps = StepsFile.model_validate(load_yaml((ROOT / ".agents/skills/b1500-bringup" / STEPS_NAME).read_bytes()))
    found = markers.check_markers(lint, {spec.id for spec in steps.all()})
    assert lint.problems == []
    assert any(m.kind == "verify" and m.form == "live" for m in found)
    stage_lines = [m for m in found if m.form == "summary" and "/b1500-bringup/stages/" in m.file]
    assert len(stage_lines) == 12  # one per stage file (S0, L0-L10)
    assert any(m.kind == "owner" and m.question.endswith("?") for m in found)
    assert lint.notes and lint.notes[0].startswith("markers: ")


@pytest.mark.parametrize(("text", "ids"), [
    (f"x {_T}(verify)[L6.A2] y", ("L6.A2",)),
    (f"x `{_T}(verify)[L6.A7, L8.A8]` y", ("L6.A7", "L8.A8")),
    (f"x {_T}(verify)[S0.P5,D3] y", ("S0.P5", "D3")),
])
def test_verify_markers_carry_their_step_ids(text: str, ids: tuple[str, ...]) -> None:
    found, problems = _scan(text)
    assert problems == [] and [(m.kind, m.form, m.ids) for m in found] == [("verify", "live", ids)]


def test_verify_forms_that_need_no_ids_and_the_refused_ones() -> None:
    found, problems = _scan(f"- {_T}(verify) (blueprint v2 7.6 items 3, 8): the blocks\n"
                            f"see `{_T}(verify)[<step ids>]`\n")
    assert problems == [] and [m.form for m in found] == ["summary", "placeholder"]
    _found, problems = _scan(f"a {_T}(verify) at bring-up L7\n")
    assert [p.code for p in problems] == ["todo_verify"] and "without step ids" in problems[0].message
    _found, problems = _scan(f"a {_T}(verify)[L7] and {_T}(verify)[at L8]\n")
    assert [p.code for p in problems] == ["todo_verify", "todo_verify"]
    assert "not a step id" in problems[0].message
    found, _problems = _scan(f"a {_T}(verify)[L4.A9]\n")
    assert [p.message for p in markers.unknown_steps(found, {"L4.A1"})] == [
        f"{_T}(verify)[L4.A9]: no step L4.A9 in .agents/skills/b1500-bringup/steps.yaml"]
    # a partial tree (fixture) without steps for stage L6 leaves L6 ids unchecked; L66 is no stage at all
    found, _problems = _scan(f"a {_T}(verify)[L6.A2] b {_T}(verify)[L66.A1] c {_T}(verify)[D9]\n")
    assert [p.message.split(":")[0] for p in markers.unknown_steps(found, {"L4.A1", "D1"})] == [
        f"{_T}(verify)[L66.A1]", f"{_T}(verify)[D9]"]


def test_owner_questions_run_over_lines_and_skip_code_spans() -> None:
    text = (f"- Basis: none. `{_T}(owner)`: which `ERSSP?` answer and which\n"
            "  tolerance does the lab accept\n  at L7? More text?\n")
    found, problems = _scan(text)
    assert problems == []
    assert [m.question for m in found] == [
        "which `ERSSP?` answer and which tolerance does the lab accept at L7?"]
    yaml_text = f"key: 1   # vc: {_T}(owner): which coercive\n# voltage does the film have?\nother: 2\n"
    found, problems = _scan(yaml_text, "config/duts/x.example.yaml")
    assert problems == [] and found[0].question == "which coercive voltage does the film have?"


def test_owner_markers_without_a_question_and_the_accepted_mentions() -> None:
    _found, problems = _scan(f"A value marked `{_T}(owner)` is blank.\n\nNext paragraph?\n")
    assert [p.code for p in problems] == ["todo_owner"]
    _found, problems = _scan(f"{_T}(owner): a statement without an end\n\nlater?\n")
    assert [p.code for p in problems] == ["todo_owner"]
    found, problems = _scan(f"`{_T}(owner|verify|cite)` or unknown; `{_T}(owner)`: <question ending with ?>\n")
    assert problems == [] and [m.form for m in found] == ["placeholder"]
    found, problems = _scan(f"literature value `{_T}(cite)`\n")
    assert problems == [] and [(m.kind, m.form) for m in found] == [("cite", "live")]


def test_unknown_kinds_and_bare_markers_are_problems() -> None:
    _found, problems = _scan(f"{_T}(later) and {_T}: fix\n")
    assert sorted(p.message.split(":")[0] for p in problems) == ["a bare TODO", f"unknown marker {_T}(later)"]
    assert {p.code for p in problems} == {"todo_marker"}


def test_case_files_leave_owner_questions_to_the_case_lint() -> None:
    found, problems = _scan(f"Noise. {_T}(owner): which current level.\n",
                            ".agents/skills/b1500-debug/cases/2026-11-05-x.md")
    assert found == [] and problems == []


def test_scope_skips_conventions_generated_files_tests_and_local_config(tmp_path: Path) -> None:
    files = {
        ".agents/skills/b1500-test/knowledge/README.md": "convention",
        ".agents/skills/b1500-test/cards/_TEMPLATE.md": "template",
        "docs/open-questions.md": "generated",
        "docs/design/progress.md": "history",
        "docs/acceptance/2026-11-26-x.md": "report",
        "config/local/duts/x.yaml": "local",
        "tests/test_x.py": "test",
        "src/b1500_test_agent/devtools/skills/markers.py": "lint",
        "src/b1500_test_agent/driver/x.py": "in",
        "docs/safety-model.md": "in",
        "config/duts/x.example.yaml": "in",
        "recipes/a/b.yaml": "in",
        "README.md": "in",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    found = {markers.relpath(tmp_path, p) for p in markers.marker_files(tmp_path)}
    assert found == {rel for rel, text in files.items() if text == "in"}


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    knowledge = root / KNOWLEDGE
    knowledge.write_text(knowledge.read_text(encoding="utf-8") + (
        f"\n## Owner facts\n\nFilm: `{_T}(owner)`: which films does the lab measure?\n"
        f"Again: `{_T}(owner)`: Which films does the lab   measure?\n"), encoding="utf-8")
    duts = root / "config" / "duts"
    duts.mkdir(parents=True)
    (duts / "x.example.yaml").write_text(f"device_type: x  # {_T}(owner): which Vc does\n# the film have?\n",
                                         encoding="utf-8")
    case = root / ".agents/skills/b1500-debug/cases/example-x.md"
    case.write_text("---\ntitle: 'Example: X'\n---\n# X\n\n## Open questions for the owner\n\n"
                    "1. Has the lab seen this problem? If yes, record it.\n2. Which rest time does the lab\n"
                    "   use between sweeps?\n", encoding="utf-8")
    return root


def test_questions_are_grouped_by_topic_with_links_and_merged(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    found, titles = questions.collect_questions(root)
    assert [(q.topic, q.question, len(q.places)) for q in found] == [
        ("Devices, films, processes and lab practice", "which films does the lab measure?", 2),
        ("DUT profiles", "which Vc does the film have?", 1),
        ("Debug cases: what the lab has seen", "Has the lab seen this problem? If yes, record it.", 1),
        ("Debug cases: what the lab has seen", "Which rest time does the lab use between sweeps?", 1),
    ]
    assert found[0].places[0].anchor == "owner-facts" and titles[".agents/skills/b1500-debug/cases/example-x.md"] \
        == "Example: X"
    text = questions.render_questions(found, titles)
    assert text.startswith(questions.QUESTIONS_MARKER + "\n# Open questions for the owner\n")
    assert "4 questions in 3 files." in text and "\r" not in text and text.endswith("\n")
    assert f"- Which films does the lab measure? ([Owner facts](../{KNOWLEDGE}#owner-facts); " in text
    assert "- Which Vc does the film have? ([x.example.yaml](../config/duts/x.example.yaml))" in text
    assert text.index("## Devices, films") < text.index("## DUT profiles") < text.index("## Debug cases")
    assert questions.render_questions(*questions.collect_questions(root)) == text  # deterministic


def test_gen_index_writes_and_checks_the_question_list(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = (root / questions.QUESTIONS_REL).read_bytes()  # the fixture's list: no question
    report = index.gen_index(root, check=True)
    assert not report.ok and report.questions_drift and (root / questions.QUESTIONS_REL).read_bytes() == before
    written = index.gen_index(root)
    assert written.ok and written.questions_written and written.questions == 4
    assert index.gen_index(root, check=True).ok
    assert "owner questions: up to date (docs/open-questions.md, 4 questions)" in index.format_report(
        index.gen_index(root, check=True))
    (root / KNOWLEDGE).write_text((root / KNOWLEDGE).read_text(encoding="utf-8").replace("films", "stacks"),
                                  encoding="utf-8")
    assert index.gen_index(root, check=True).questions_drift
    result = runner.invoke(app, ["dev", "gen-index", "--check", "--root", str(root)])
    assert result.exit_code == 1 and "owner questions: DRIFT" in result.output


def test_repository_question_list_is_current_and_lists_the_stage_and_case_questions() -> None:
    state = questions.gen_questions(ROOT, check=True)
    assert not state.drift, "docs/open-questions.md is stale: run `uv run b1500 dev gen-index`"
    text = (ROOT / questions.QUESTIONS_REL).read_text(encoding="utf-8")
    assert "## Bring-up: provisional acceptance criteria" in text and "## Debug cases: what the lab has seen" in text
    assert "l6-cmu.md#4-expected-values" in text and "example-noisy-data.md#open-questions-for-the-owner" in text
