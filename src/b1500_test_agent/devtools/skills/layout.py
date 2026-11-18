"""Skill layout checks: ``SKILL.md`` frontmatter (name, description; nothing that pre-approves tools or adds hooks),
the Markdown files of a skill, symlinks and the generated-copy marker."""


from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from b1500_test_agent.devtools.skills.common import Lint, SkillFrontmatter, validation_messages
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc
from b1500_test_agent.devtools.sync_harness import GENERATED_LINE, scan_tree


def check_skill_front(lint: Lint, doc: MarkdownDoc, skill: str) -> SkillFrontmatter | None:
    if not doc.has_front:
        lint.add("frontmatter", doc.path, "SKILL.md must start with YAML frontmatter (name, description)", 1)
        return None
    if doc.front_error:
        lint.add("frontmatter", doc.path, doc.front_error, 1)
        return None
    if not isinstance(doc.front, dict):
        lint.add("frontmatter", doc.path, "frontmatter must be a mapping", 1)
        return None
    try:
        front = SkillFrontmatter.model_validate(doc.front)
    except ValidationError as exc:
        for message in validation_messages(exc):
            lint.add("frontmatter", doc.path, message, 1)
        return None
    if front.name != skill:
        lint.add("frontmatter", doc.path, f"name {front.name!r} must equal the folder name {skill!r}", 1)
    return front


def skill_files(lint: Lint, skill_dir: Path) -> list[Path]:
    """Markdown files of one skill (sorted); symlinks and the generated marker are problems."""
    tree = scan_tree(skill_dir)
    for link in tree.links:
        lint.add("skill_layout", skill_dir / link, "symlink inside a skill (Windows checkouts break them); use a "
                                                   "real file")
    markdown = []
    for rel, path in sorted(tree.files.items()):
        if not rel.lower().endswith(".md"):
            continue
        markdown.append(path)
        doc = lint.doc(path)
        if doc is not None and any(line.strip() == GENERATED_LINE for line in doc.lines):
            lint.add("generated_marker", path, "source file carries the generated-copy marker; edit the source and "
                                               "regenerate .claude/skills with b1500 dev sync-harness")
    return markdown


