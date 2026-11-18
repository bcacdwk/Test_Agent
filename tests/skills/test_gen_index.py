"""``b1500 dev gen-index [--check]`` (blueprint v2 6.1, 6.2): the generated card index ``cards/README.md``.

The repository's index is current; the text is a deterministic function of the card frontmatter and the registry
(one section per family in ``Recipe.family`` order, LF line endings, no timestamps); ``--check`` reports drift and
writes nothing; writing refuses while a card's frontmatter is invalid; the CLI exits 1 on drift or problems.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.skills import index
from b1500_test_agent.devtools.skills.common import FAMILIES

ROOT = Path(__file__).resolve().parents[2]
POSITIVE = ROOT / "tests" / "fixtures" / "skills" / "positive"
INDEX = Path(index.INDEX_REL)
CARD = ".agents/skills/b1500-test/cards/smu/mosfet-idvg.md"
runner = CliRunner()


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    return root


def test_repository_index_is_current() -> None:
    report = index.gen_index(ROOT, check=True)
    assert report.ok and not report.drift and report.cards >= 7, index.format_report(report)


def test_index_is_deterministic_lf_and_has_one_section_per_family() -> None:
    cards, problems = index.collect_cards(ROOT / ".agents" / "skills" / "b1500-test")
    assert problems == []
    registry = RecipeRegistry.load(ROOT / "recipes", repo_root=ROOT)
    first, second = index.render_index(cards, registry), index.render_index(list(reversed(cards)), registry)
    assert first == second and "\r" not in first and first.endswith("\n")
    headings = [line[3:] for line in first.splitlines() if line.startswith("## ")]
    assert headings == list(FAMILIES)
    assert first.splitlines()[0] == index.INDEX_MARKER
    assert (ROOT / INDEX).read_bytes() == first.encode("utf-8")


def test_check_reports_drift_and_write_repairs_it(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    target = root / INDEX
    target.write_text(target.read_text(encoding="utf-8").replace("| L4 |", "| L5 |"), encoding="utf-8")
    before = target.read_bytes()
    report = index.gen_index(root, check=True)
    assert not report.ok and report.drift and target.read_bytes() == before  # --check writes nothing
    written = index.gen_index(root)
    assert written.ok and written.written
    assert index.gen_index(root, check=True).ok
    assert not index.gen_index(root).written  # unchanged the second time


def test_missing_index_is_drift_and_gets_written(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / INDEX).unlink()
    assert index.gen_index(root, check=True).drift
    assert index.gen_index(root).written and (root / INDEX).is_file()


def test_invalid_card_frontmatter_refuses_to_write(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    card = root / CARD
    card.write_text(card.read_text(encoding="utf-8").replace("bringup_stage: L4", "bringup_stage: L99"),
                    encoding="utf-8")
    before = (root / INDEX).read_bytes()
    report = index.gen_index(root)
    assert not report.ok and not report.written and (root / INDEX).read_bytes() == before
    assert any("bringup_stage" in problem for problem in report.problems)
    assert "not written" in index.format_report(report)


def test_cli_gen_index(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    good = runner.invoke(app, ["dev", "gen-index", "--check", "--root", str(root)])
    assert good.exit_code == 0 and "up to date" in good.stdout
    (root / INDEX).write_text("stale\n", encoding="utf-8")
    bad = runner.invoke(app, ["dev", "gen-index", "--check", "--root", str(root), "--json"])
    assert bad.exit_code == 1 and json.loads(bad.stdout)["drift"] is True
    fixed = runner.invoke(app, ["dev", "gen-index", "--root", str(root)])
    assert fixed.exit_code == 0 and "written" in fixed.stdout
    assert runner.invoke(app, ["dev", "gen-index", "--check", "--root", str(root)]).exit_code == 0
    listed = runner.invoke(app, ["dev", "--help"])
    assert "gen-index" in listed.stdout
