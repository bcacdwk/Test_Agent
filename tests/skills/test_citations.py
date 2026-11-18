"""Manual citation lint (blueprint 5.2, WP5.8): every citation in the repository checks out, and bad ids, pages,
printed labels and keywords are caught in both the canonical (``PG p433 (4-115)``) and the v1 (``PG PDF 380,
printed 4-62``) forms."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from b1500_test_agent.devtools.skills import lint as lint_skills
from b1500_test_agent.devtools.skills.citations import (
    check_citations,
    citation_problems,
    find_citations,
    lint_files,
)
from b1500_test_agent.devtools.skills.common import Lint
from b1500_test_agent.manuals.catalog import ManualPaths, load_catalog
from b1500_test_agent.manuals.search import Corpus

pytestmark = pytest.mark.manuals

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "references" / "manuals" / "catalog.yaml")
CORPUS = Corpus.load(ManualPaths(references=ROOT / "references" / "manuals", manuals_dir=ROOT))


def problems_of(text: str, corpus: Corpus | None = CORPUS) -> list[tuple[str, list[str]]]:
    return [(c.text, citation_problems(c, CATALOG, corpus)) for c in find_citations(text, CATALOG)]


def test_repository_citations_all_check_out() -> None:
    lint = Lint(ROOT, ROOT / "recipes", ROOT / "config")
    count = check_citations(lint)
    assert lint.problems == [], [f"{p.file}:{p.line}: {p.message}" for p in lint.problems]
    assert count >= 150
    assert lint.notes == [f"citations: {count} checked (ids, pages, printed labels and keywords)"]


def test_scope_covers_skills_recipes_source_and_docs_but_not_references() -> None:
    files = {p.relative_to(ROOT).as_posix() for p in lint_files(ROOT, ROOT / "recipes")}
    assert ".agents/skills/b1500-test/knowledge/02-b1500-instrument.md" in files
    assert "src/b1500_test_agent/driver/flex/core.py" in files and "src/b1500_test_agent/driver/AGENTS.md" in files
    assert "docs/manuals.md" in files and "README.md" in files
    assert any(f.startswith("recipes/") for f in files)
    assert not any(f.startswith(("references/", ".claude/", "tests/")) for f in files)


def test_canonical_citations() -> None:
    assert problems_of('PG p433 (4-115) "ERSSP" and PG p507 and WG p125 (4-55) and AN-RTN p2 (2)') == [
        ('PG p433 (4-115) "ERSSP"', []), ("PG p507", []), ("WG p125 (4-55)", []), ("AN-RTN p2 (2)", [])]
    assert problems_of("PG p433-434 (4-115) and PG p433–p434") == [("PG p433-434 (4-115)", []),
                                                                  ("PG p433–p434", [])]
    found = dict(problems_of('PG p433 (4-116), PG p618, UG p0, AN-FOO p2, PG p433 "SPGU zzz", AC p1 (9-9)'))
    assert found["PG p433 (4-116)"] == ["printed label 4-116: PG p433 is printed 4-115"]
    assert found["PG p618"] == ["page 618 is outside PG (PDF pages 1..617)"]
    assert found["UG p0"] == ["page 0 is outside UG (PDF pages 1..160)"]
    assert found["AN-FOO p2"][0].startswith("unknown manual id AN-FOO")
    assert found['PG p433 "SPGU zzz"'] == ["keyword 'SPGU zzz' does not occur on PG p433"]
    assert found["AC p1 (9-9)"] == ["printed label 9-9: AC p1 is printed 1"]
    assert dict(problems_of("PG p1 (1-1)"))["PG p1 (1-1)"] == ["printed label 1-1: PG p1 has no printed label"]


def test_non_citations_are_ignored() -> None:
    assert problems_of("XY p3, the PG prefix, p433 alone, PGP p2, SMU p1, MM p2 and B1500A p5") == []


def test_legacy_v1_citations() -> None:
    text = ("PG PDF 380, printed 4-62; PG PDF 503-504, printed 4-185 to 4-186; PG PDF 470, 380, 568-569; "
            "UG PDF 58; WG Ed. 5 PDF 24; WG Ed. 8 PDF 16 (1-4); CC PDF 9 (printed 1-3)")
    assert all(problems == [] for _, problems in problems_of(text)), problems_of(text)
    assert [c.doc for c in find_citations(text, CATALOG)] == ["PG", "PG", "PG", "UG", "WG5", "WG", "CC"]
    found = dict(problems_of("PG PDF 380, printed 4-61. PG PDF 470, 380, 700. WG Ed. 3 PDF 5. UG PDF 9999"))
    assert found["PG PDF 380, printed 4-61"] == ["printed label 4-61: PG p380 is printed 4-62"]
    assert found["PG PDF 470, 380, 700"] == ["page 700 is outside PG (PDF pages 1..617)"]
    assert found["WG Ed. 3 PDF 5"] == ["no catalog document WG Edition 3"]
    assert found["UG PDF 9999"] == ["page 9999 is outside UG (PDF pages 1..160)"]


def test_without_a_corpus_only_ids_and_pages_are_checked() -> None:
    assert dict(problems_of("PG p433 (4-116) and PG p999", corpus=None)) == {
        "PG p433 (4-116)": [], "PG p999": ["page 999 is outside PG (PDF pages 1..617)"]}


def _tree(tmp_path: Path, *, corpus: bool = True) -> Path:
    root = tmp_path / "root"
    target = root / "references" / "manuals"
    target.mkdir(parents=True)
    for name in ("catalog.yaml", "synonyms.yaml"):
        shutil.copy(ROOT / "references" / "manuals" / name, target / name)
    if corpus:
        shutil.copytree(ROOT / "references" / "manuals" / "corpus", target / "corpus")
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text("Fine: PG p433 (4-115).\nBad: SEL p40 and PG p434 (4-115).\n",
                                            encoding="utf-8")
    return root


def test_check_citations_reports_file_and_line(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    lint = Lint(root, root / "recipes", root / "config")
    assert check_citations(lint) == 3
    assert [(p.code, p.file, p.line, p.message) for p in lint.problems] == [
        ("citation", "docs/notes.md", 2, "SEL p40: page 40 is outside SEL (PDF pages 1..32)"),
        ("citation", "docs/notes.md", 2, "PG p434 (4-115): printed label 4-115: PG p434 is printed 4-116")]


def test_check_citations_without_corpus_or_catalog(tmp_path: Path) -> None:
    root = _tree(tmp_path, corpus=False)
    lint = Lint(root, root / "recipes", root / "config")
    check_citations(lint)
    assert [p.line for p in lint.problems] == [2] and "no corpus" in lint.notes[-1]
    shutil.rmtree(root / "references")
    bare = Lint(root, root / "recipes", root / "config")
    assert check_citations(bare) == 0 and bare.problems == [] and "no manual catalog" in bare.notes[0]
    (root / "references" / "manuals").mkdir(parents=True)
    (root / "references" / "manuals" / "catalog.yaml").write_text("docs: []\n", encoding="utf-8")
    broken = Lint(root, root / "recipes", root / "config")
    check_citations(broken)
    assert [p.code for p in broken.problems] == ["citation"] and "invalid" in broken.problems[0].message


def test_lint_skills_runs_the_citation_check(tmp_path: Path) -> None:
    report = lint_skills.lint_skills(ROOT)
    assert report.ok and any(note.startswith("citations: ") for note in report.notes)
    root = tmp_path / "skills-root"
    shutil.copytree(ROOT / ".agents", root / ".agents")
    shutil.copytree(ROOT / "references" / "manuals", root / "references" / "manuals")
    knowledge = root / ".agents" / "skills" / "b1500-test" / "knowledge" / "02-b1500-instrument.md"
    knowledge.write_text(knowledge.read_text(encoding="utf-8") + "\nSee PG p9999.\n", encoding="utf-8")
    bad = lint_skills.lint_skills(root, recipes_dir=ROOT / "recipes", config_dir=ROOT / "config")
    assert [(p.code, p.file) for p in bad.problems if p.code == "citation"] == [
        ("citation", ".agents/skills/b1500-test/knowledge/02-b1500-instrument.md")]
