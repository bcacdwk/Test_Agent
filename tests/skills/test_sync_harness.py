"""``b1500 dev sync-harness [--check]`` and the doctor skills-mirror check (blueprint 6.6, 7, 8.1 ``skills/``).

The repository's ``.claude/skills/`` must be exactly the generated copy of ``.agents/skills/``; the other tests build
small source trees in temporary folders.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools import doctor, sync_harness
from b1500_test_agent.devtools.sync_harness import GENERATED_LINE, check, render_markdown, sync

ROOT = Path(__file__).resolve().parents[2]
SKILL = "---\nname: {name}\ndescription: Test skill {name}.\n---\n\n# {name}\n\nSee [card](cards/a.md).\n"


def _source(root: Path, rel: str, data: str | bytes) -> Path:
    path = root / ".agents/skills" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8", newline="")
    else:
        path.write_bytes(data)
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A root with both skills, a nested card, a non-Markdown file and a CRLF/BOM Markdown file."""
    _source(tmp_path, "b1500-test/SKILL.md", SKILL.format(name="b1500-test"))
    _source(tmp_path, "b1500-test/cards/a.md", "# Card A\r\n\r\nbody\r\n")
    _source(tmp_path, "b1500-test/knowledge/01-x.md", "\ufeff---\r\ndomain: x\r\n---\r\n## X\r\n")
    _source(tmp_path, "b1500-test/assets/table.csv", b"a,b\r\n1,2\r\n")
    _source(tmp_path, "b1500-debug/SKILL.md", SKILL.format(name="b1500-debug"))
    _source(tmp_path, "b1500-debug/.DS_Store", b"\x00junk")
    return tmp_path


def _mirror(root: Path, rel: str) -> Path:
    return root / ".claude/skills" / rel


def test_repository_mirror_is_in_sync() -> None:
    report = check(ROOT)
    assert report.ok, sync_harness.format_report(report)
    assert "b1500-test" in report.skills and report.files >= 1


def test_cli_check_on_the_repository() -> None:
    result = CliRunner().invoke(app, ["dev", "sync-harness", "--check"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("skills mirror: in sync")


def test_render_inserts_the_generated_line_after_the_frontmatter() -> None:
    rendered = render_markdown(SKILL.format(name="s").encode()).decode()
    lines = rendered.split("\n")
    assert lines[:5] == ["---", "name: s", "description: Test skill s.", "---", GENERATED_LINE]
    assert rendered.replace(GENERATED_LINE + "\n", "") == SKILL.format(name="s")


def test_render_without_frontmatter_and_normalisation() -> None:
    assert render_markdown(b"# Title\r\nbody\r") == f"{GENERATED_LINE}\n# Title\nbody\n".encode()
    assert render_markdown("\ufeff---\r\na: 1\r\n---".encode()) == f"---\na: 1\n---\n{GENERATED_LINE}\n".encode()
    # An unclosed frontmatter is not a frontmatter: the line goes first.
    assert render_markdown(b"---\na: 1\n").startswith(GENERATED_LINE.encode())


def test_sync_writes_a_full_byte_stable_copy(tree: Path) -> None:
    assert check(tree).ok is False
    report = sync(tree)
    assert report.ok and report.mode == "sync" and report.skills == ["b1500-debug", "b1500-test"]
    assert report.files == 5 and len(report.written) == 5 and report.removed == []
    skill = _mirror(tree, "b1500-test/SKILL.md").read_bytes()
    assert skill == render_markdown(SKILL.format(name="b1500-test").encode())
    assert _mirror(tree, "b1500-test/cards/a.md").read_bytes() == f"{GENERATED_LINE}\n# Card A\n\nbody\n".encode()
    assert _mirror(tree, "b1500-test/knowledge/01-x.md").read_bytes() == \
        f"---\ndomain: x\n---\n{GENERATED_LINE}\n## X\n".encode()
    assert _mirror(tree, "b1500-test/assets/table.csv").read_bytes() == b"a,b\r\n1,2\r\n"  # non-Markdown: verbatim
    assert not _mirror(tree, "b1500-debug/.DS_Store").exists()
    assert not any(p.is_symlink() for p in (tree / ".claude/skills").rglob("*"))
    before = {p: p.read_bytes() for p in (tree / ".claude/skills").rglob("*") if p.is_file()}
    again = sync(tree)
    assert again.ok and again.written == [] and again.removed == []
    assert {p: p.read_bytes() for p in (tree / ".claude/skills").rglob("*") if p.is_file()} == before


def test_check_lists_missing_extra_and_changed(tree: Path) -> None:
    sync(tree)
    _mirror(tree, "b1500-test/cards/a.md").write_text("edited by hand\n", encoding="utf-8")
    _mirror(tree, "b1500-test/assets/table.csv").unlink()
    _mirror(tree, "b1500-test/cards/old/stale.md").parent.mkdir(parents=True)
    _mirror(tree, "b1500-test/cards/old/stale.md").write_text("stale\n", encoding="utf-8")
    report = check(tree)
    assert not report.ok
    assert [(d.kind, d.path) for d in report.drift] == [
        ("missing", ".claude/skills/b1500-test/assets/table.csv"),
        ("changed", ".claude/skills/b1500-test/cards/a.md"),
        ("extra", ".claude/skills/b1500-test/cards/old/stale.md"),
    ]
    result = CliRunner().invoke(app, ["dev", "sync-harness", "--check", "--root", str(tree)])
    assert result.exit_code == 1
    assert "DRIFT (3 paths" in result.stdout and "extra   .claude/skills/b1500-test/cards/old/stale.md" in result.stdout
    fixed = sync(tree)
    assert fixed.ok and fixed.removed == [".claude/skills/b1500-test/cards/old/stale.md"]
    assert sorted(fixed.written) == [".claude/skills/b1500-test/assets/table.csv",
                                     ".claude/skills/b1500-test/cards/a.md"]
    assert not _mirror(tree, "b1500-test/cards/old").exists()  # emptied folders are pruned


def test_a_new_source_file_is_missing_until_synced(tree: Path) -> None:
    sync(tree)
    _source(tree, "b1500-debug/runbooks/noisy-data.md", "# Noisy\n")
    assert [(d.kind, d.path) for d in check(tree).drift] == [
        ("missing", ".claude/skills/b1500-debug/runbooks/noisy-data.md")]


def test_removed_skill_is_deleted_but_foreign_folders_stay(tree: Path) -> None:
    sync(tree)
    foreign = _mirror(tree, "my-own-skill/SKILL.md")
    foreign.parent.mkdir(parents=True)
    foreign.write_text("---\nname: my-own-skill\ndescription: hand-written\n---\n", encoding="utf-8")
    shutil.rmtree(tree / ".agents/skills/b1500-debug")
    report = check(tree)
    assert [(d.kind, d.path) for d in report.drift] == [("extra", ".claude/skills/b1500-debug/SKILL.md")]
    assert sync(tree).ok
    assert not _mirror(tree, "b1500-debug").exists() and foreign.is_file()


def test_sync_never_touches_other_claude_files(tree: Path) -> None:
    settings = tree / ".claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n", encoding="utf-8")
    sync(tree)
    assert settings.read_text(encoding="utf-8") == "{}\n"


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:  # Windows without Developer Mode
        pytest.skip(f"symlinks unavailable: {exc}")


def test_symlinks_in_the_mirror_are_replaced_by_copies(tree: Path, tmp_path: Path) -> None:
    sync(tree)
    card = _mirror(tree, "b1500-test/cards/a.md")
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    card.unlink()
    _symlink(card, outside)
    assert [(d.kind, d.path) for d in check(tree).drift] == [("changed", ".claude/skills/b1500-test/cards/a.md")]
    assert sync(tree).ok
    assert not card.is_symlink() and outside.read_text(encoding="utf-8") == "outside\n"


def test_symlinked_source_folder_is_refused(tree: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _symlink(tree / ".agents/skills/b1500-test/linked", elsewhere, directory=True)
    report = sync(tree)
    assert not report.ok and "symlinked directories are not mirrored" in report.problems[0]
    assert not (tree / ".claude/skills").exists()


def test_non_utf8_markdown_is_refused(tree: Path) -> None:
    _source(tree, "b1500-test/cards/bad.md", b"\xff\xfe broken")
    report = check(tree)
    assert not report.ok and "cards/bad.md: not UTF-8" in report.problems[0]


def test_doctor_skills_mirror_check(tree: Path, tmp_path: Path) -> None:
    assert doctor.check_skills_mirror(ROOT).status == "PASS"
    drift = doctor.check_skills_mirror(tree)
    assert drift.status == "FAIL" and "missing .claude/skills/b1500-debug/SKILL.md" in drift.detail
    assert "dev sync-harness" in drift.detail
    sync(tree)
    passed = doctor.check_skills_mirror(tree)
    assert passed.status == "PASS" and "b1500-debug, b1500-test" in passed.detail
    empty = tmp_path / "empty"
    empty.mkdir()
    assert doctor.check_skills_mirror(empty).status == "WARN"
