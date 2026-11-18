"""``b1500 manual`` (blueprint 5.2, WP5.8) through ``CliRunner``: search/page/toc/status on the committed corpus,
build and ``--check`` on the fixture tree, the extract fallback, exit codes, the ``doctor`` manual checks, the
``docs/manuals.md`` command names, and the CLI-only exception of the parity rule (no MCP tool)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner, Result

from b1500_test_agent.adapters.cli import TOOL_COMMANDS, app
from b1500_test_agent.devtools.doctor import check_manuals
from b1500_test_agent.manuals.catalog import ENV_MANUALS_DIR
from b1500_test_agent.models.manuals import ManualBuildReport, ManualPageResult, ManualSearchResult, ManualStatus
from b1500_test_agent.paths import ENV_HOME
from b1500_test_agent.service import TOOL_NAMES
from tests.adapters.test_docs_commands import help_problem, named_commands, resolve
from tests.fixtures.manuals.make_fixture import PDF_NAME, fixture_pdf, fixture_tree
from tests.integration.helpers import World

pytestmark = pytest.mark.manuals

REPO = Path(__file__).resolve().parents[2]
runner = CliRunner()


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args))


@pytest.fixture(autouse=True)
def _no_pdfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Queries run against the committed corpus with an empty manuals folder (PDFs are optional)."""
    folder = tmp_path / "no-pdfs"
    folder.mkdir()
    monkeypatch.setenv(ENV_MANUALS_DIR, str(folder))
    return folder


def fixture_home(root: Path, monkeypatch: pytest.MonkeyPatch, *, with_corpus: bool = True) -> Path:
    """A clone-shaped folder whose references/manuals is the fixture tree; B1500_HOME points at it."""
    tree = fixture_tree(root / "references" / "manuals", with_corpus=with_corpus)
    monkeypatch.setenv(ENV_HOME, str(root))
    return tree


def test_help_lists_the_manual_commands() -> None:
    assert "manual" in invoke("--help").stdout
    group = invoke("manual", "--help")
    for command in ("search", "page", "toc", "status", "build"):
        assert command in group.stdout


def test_search_prints_citation_lines() -> None:
    result = invoke("manual", "search", "ERSSP status")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert "for 'ERSSP status' (all terms)" in lines[0]
    assert lines[1].startswith("PG p433 (4-115) · ERSSP · ")
    assert all(len(line.split(" · ", 2)[-1]) <= 240 for line in lines[1:])


def test_search_json_and_filters() -> None:
    result = invoke("manual", "search", "WGFMU_setMeasureEvent", "--doc", "WG,wg5", "-k", "2", "--json")
    assert result.exit_code == 0, result.output
    parsed = ManualSearchResult.model_validate_json(result.stdout)
    assert parsed.docs == ["WG", "WG5"] and len(parsed.hits) == 2 and parsed.hits[0].doc == "WG"
    words = invoke("manual", "search", "随机电报噪声", "--json")
    assert "AN-RTN" in {hit["doc"] for hit in json.loads(words.stdout)["hits"]}


def test_search_exit_codes() -> None:
    assert invoke("manual", "search", "qqqqzzzz").exit_code == 1
    unknown = invoke("manual", "search", "status", "--doc", "XX")
    assert unknown.exit_code == 2 and "unknown manual 'XX'" in unknown.stderr
    assert invoke("manual", "search", "status", "-k", "0").exit_code == 2


def test_page_by_printed_label_and_range() -> None:
    result = invoke("manual", "page", "PG", "--printed", "4-189")
    assert result.exit_code == 0, result.output
    assert "=== PG p507 (4-189) · " in result.stdout and "load impedance" in result.stdout
    many = ManualPageResult.model_validate_json(invoke("manual", "page", "PG", "433", "--to", "440",
                                                       "--json").stdout)
    assert [p.p for p in many.pages] == [433, 434, 435] and "at most 3 pages" in many.message
    short = invoke("manual", "page", "PG", "433", "--max-chars", "300", "--json")
    assert sum(len(p["text"]) for p in json.loads(short.stdout)["pages"]) <= 302
    assert invoke("manual", "page", "PG", "9999").exit_code == 2
    assert invoke("manual", "page", "PG").exit_code == 2


def test_toc_with_grep() -> None:
    result = invoke("manual", "toc", "PG", "--grep", "^FMT$")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[1].strip() == "FMT  p436 (4-118)"
    assert invoke("manual", "toc", "NOPE").exit_code == 2


def test_status_reports_the_committed_corpus_and_absent_pdfs(_no_pdfs: Path) -> None:
    result = invoke("manual", "status")
    assert result.exit_code == 0, result.output
    assert "corpus current: 16 docs, 2315 pages" in result.stdout and "PDFs 0/16" in result.stdout
    status = ManualStatus.model_validate_json(invoke("manual", "status", "--json").stdout)
    assert status.ok and status.manuals_dir_source == ENV_MANUALS_DIR
    assert status.manuals_dir == _no_pdfs.resolve().as_posix()


def test_settings_manuals_dir_is_used_without_the_environment(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in world.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(ENV_MANUALS_DIR)
    shutil.copytree(REPO / "references" / "manuals", world.root / "references" / "manuals")
    settings = yaml.safe_load((REPO / "config" / "settings.example.yaml").read_text(encoding="utf-8"))
    settings["manuals_dir"] = "my-pdfs"
    world.write_config("settings.yaml", settings)
    status = ManualStatus.model_validate_json(invoke("manual", "status", "--json").stdout)
    assert status.manuals_dir_source == "settings.manuals_dir"
    assert status.manuals_dir == "my-pdfs"  # shown relative to the clone


def test_build_and_check_on_the_fixture_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = fixture_home(tmp_path / "clone", monkeypatch, with_corpus=False)
    src = tree / "pdfs"
    built = invoke("manual", "build", "--src", str(src))
    assert built.exit_code == 0, built.output
    assert built.stdout.startswith("built 1 docs, 2 pages -> references/manuals/corpus/")
    check = invoke("manual", "build", "--src", str(src), "--check", "--json")
    report = ManualBuildReport.model_validate_json(check.stdout)
    assert check.exit_code == 0 and report.identical is True and report.mode == "check"
    (src / PDF_NAME).unlink()
    missing = invoke("manual", "build", "--src", str(src))
    assert missing.exit_code == 1 and "missing PDFs: FX" in missing.stdout
    (src / PDF_NAME).write_bytes(fixture_pdf())
    monkeypatch.setenv(ENV_MANUALS_DIR, str(src))
    assert invoke("manual", "build", "--check").exit_code == 0  # B1500_MANUALS_DIR without --src


def test_queries_without_a_corpus_answer_from_the_extracts(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_home(tmp_path / "clone", monkeypatch, with_corpus=False)
    result = invoke("manual", "search", "FIXCMD")
    assert result.exit_code == 0, result.output
    assert "No manual corpus" in result.stdout and "uv run b1500 manual build" in result.stdout
    assert "[extracts/" in result.stdout
    status = invoke("manual", "status")
    assert status.exit_code == 1 and "no corpus" in status.stdout


# -- doctor ------------------------------------------------------------------------------------------------------------


def test_doctor_manual_checks(tmp_path: Path) -> None:
    corpus, pdfs = check_manuals(REPO, "..", {ENV_MANUALS_DIR: str(tmp_path)})
    assert (corpus.name, corpus.status) == ("manual corpus", "PASS") and "16 docs, 2315 pages" in corpus.detail
    assert (pdfs.name, pdfs.status) == ("manual PDFs", "INFO") and "0/16" in pdfs.detail
    assert [c.status for c in check_manuals(tmp_path / "empty", "..", {})] == ["WARN", "INFO"]

    clone = tmp_path / "clone"
    tree = fixture_tree(clone / "references" / "manuals", with_corpus=False)
    env = {ENV_MANUALS_DIR: str(tree / "pdfs")}
    missing, present = check_manuals(clone, "..", env)
    assert missing.status == "WARN" and "missing" in missing.detail and present.status == "PASS"
    (tree / "pdfs" / PDF_NAME).write_bytes(fixture_pdf() + b"\n")
    assert check_manuals(clone, "..", env)[1].status == "WARN"  # edition mismatch
    (tree / "catalog.yaml").write_text("docs: [", encoding="utf-8")
    assert check_manuals(clone, "..", env)[0].status == "FAIL"


# -- docs and parity ---------------------------------------------------------------------------------------------------


def test_manuals_doc_names_only_existing_commands() -> None:
    text = (REPO / "docs" / "manuals.md").read_text(encoding="utf-8")
    commands = named_commands(text)
    assert len(commands) >= 8
    problems = []
    for tokens in commands:
        path, _, options, problem = resolve(tokens)
        problem = problem or help_problem(path, options)
        if problem:
            problems.append(f"{problem} (from b1500 {' '.join(tokens)})")
    assert not problems, problems
    named = {" ".join(tokens[:2]) for tokens in commands}
    assert {"manual search", "manual page", "manual toc", "manual status", "manual build"} <= named


def test_manual_group_is_a_documented_cli_only_exception() -> None:
    assert all(command[0] != "manual" for command in TOOL_COMMANDS.values())
    assert len(TOOL_NAMES) == 10 and not any("manual" in name for name in TOOL_NAMES)
    import b1500_test_agent.adapters.cli as cli_package

    assert "manuals (CLI only, no MCP tool)" in (cli_package.__doc__ or "")
