"""Budgets of the skill lint: line/byte limits per file kind and the always-loaded token budget (``AGENTS.md`` +
``CLAUDE.md`` + every skill's frontmatter ``description``), counted like ``devtools/budget.py``."""


from __future__ import annotations

import warnings
from pathlib import Path

from b1500_test_agent.devtools.budget import TokenCounter, load_counter
from b1500_test_agent.devtools.skills.common import AlwaysLoadedBudget, Lint
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, parse_markdown
from b1500_test_agent.devtools.sync_harness import SKILL_FILE, SOURCE_DIR, normalize_text, source_skills

ENTRY_MAX_LINES = 150
ENTRY_MAX_BYTES = 9_000
DEBUG_MAX_LINES = 100
CARD_MAX_LINES = 150
KNOWLEDGE_MAX_LINES = 300
ALWAYS_LOADED_LIMIT = 2_500
ALWAYS_LOADED_FILES = ("AGENTS.md", "CLAUDE.md")


def check_budget(lint: Lint, doc: MarkdownDoc, max_lines: int, what: str, max_bytes: int | None = None) -> None:
    count = len(doc.lines) - (1 if doc.lines and doc.lines[-1] == "" else 0)
    if count > max_lines:
        lint.add("budget", doc.path, f"{what} has {count} lines (limit {max_lines})")
    if max_bytes is not None:
        size = doc.path.stat().st_size
        if size > max_bytes:
            lint.add("budget", doc.path, f"{what} has {size:,} bytes (limit {max_bytes:,})")


def always_loaded_budget(root: Path, counter: TokenCounter | None = None) -> AlwaysLoadedBudget:
    """Tokens of ``AGENTS.md`` + ``CLAUDE.md`` + every skill's frontmatter ``description`` under ``root``."""
    if counter is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            counter = load_counter()
    root = Path(root)
    parts: dict[str, int] = {}
    for name in ALWAYS_LOADED_FILES:
        path = root / name
        if path.is_file():
            parts[name] = counter.count(normalize_text(path.read_bytes()))
    for skill in source_skills(root):
        rel = f"{SOURCE_DIR}/{skill}/{SKILL_FILE}"
        try:
            doc = parse_markdown(root / rel, rel)
        except (OSError, UnicodeDecodeError):
            continue
        description = doc.front.get("description") if isinstance(doc.front, dict) else None
        if isinstance(description, str):
            parts[f"{rel}#description"] = counter.count(description)
    return AlwaysLoadedBudget(method=counter.method, warning=counter.warning, limit=ALWAYS_LOADED_LIMIT,
                              total=sum(parts.values()), parts=parts)


