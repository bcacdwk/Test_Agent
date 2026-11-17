"""Agent instruction files (blueprint §5.2, §6.6–6.7): size limits, import shape, the driver-map isolation rule,
the skill frontmatter and the always-loaded budget (AGENTS.md + CLAUDE.md + every skill's frontmatter description
≤ 2,500 tokens, counted by ``lint_skills.always_loaded_budget`` with the ``devtools/budget.py`` counter).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.devtools.budget import load_counter
from b1500_test_agent.devtools.lint_skills import ALWAYS_LOADED_LIMIT, always_loaded_budget

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "b1500_test_agent"

MAX_AGENTS_LINES = 80
MAX_AGENTS_TOKENS = 1200
MAX_DEVELOPER_LINES = 25
MAX_CLAUDE_SPECIFIC_LINES = 10
MAX_NESTED_AGENTS_LINES = 30
MAX_SKILL_NAME_CHARS = 64
MAX_SKILL_DESCRIPTION_CHARS = 300
MAX_ALWAYS_LOADED_TOKENS = 2500


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_root_agents_md_line_budget() -> None:
    assert len(_read(ROOT / "AGENTS.md").splitlines()) <= MAX_AGENTS_LINES


def test_root_agents_md_token_budget() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        counter = load_counter()
    if counter.warning:
        # The chars/3.5 fallback overestimates prose; only the real encoding can decide a hard limit.
        pytest.skip(counter.warning)
    tokens = counter.count(_read(ROOT / "AGENTS.md"))
    assert tokens <= MAX_AGENTS_TOKENS, f"AGENTS.md has {tokens} tokens ({counter.method})"


def test_root_agents_md_developer_section_budget() -> None:
    lines = _read(ROOT / "AGENTS.md").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Developer"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    assert end - start - 1 <= MAX_DEVELOPER_LINES


def test_root_claude_md_imports_agents_md() -> None:
    lines = [line for line in _read(ROOT / "CLAUDE.md").splitlines() if line.strip()]
    assert lines[0] == "@AGENTS.md"
    assert len(lines) - 1 <= MAX_CLAUDE_SPECIFIC_LINES


@pytest.mark.parametrize("layer", ["driver", "analysis"])
def test_nested_instructions(layer: str) -> None:
    folder = PACKAGE / layer
    assert len(_read(folder / "AGENTS.md").splitlines()) <= MAX_NESTED_AGENTS_LINES
    assert _read(folder / "CLAUDE.md").strip() == "@AGENTS.md"


def test_driver_map_is_never_auto_loaded() -> None:
    """Always-loaded instructions and skills must not point at `references/driver-map/` (developer-only)."""
    candidates = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md"]
    for skills_root in (ROOT / ".agents", ROOT / ".claude" / "skills"):
        if skills_root.is_dir():
            candidates.extend(p for p in skills_root.rglob("*") if p.is_file())
    offenders = [p.relative_to(ROOT).as_posix() for p in candidates if b"driver-map" in p.read_bytes()]
    assert offenders == []


def test_skill_frontmatter() -> None:
    """Every canonical skill has frontmatter with ``name`` = its folder (≤64 chars) and a ≤300-char description."""
    skills = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    assert [p.parent.name for p in skills][:1] == ["b1500-test"]
    for path in skills:
        text = _read(path)
        assert text.startswith("---\n"), path
        front = yaml.safe_load(text.split("---\n", 2)[1])
        assert front["name"] == path.parent.name and len(front["name"]) <= MAX_SKILL_NAME_CHARS
        assert 0 < len(front["description"]) <= MAX_SKILL_DESCRIPTION_CHARS


def test_always_loaded_token_budget() -> None:
    """AGENTS.md + CLAUDE.md + both skills' descriptions stay within 2,500 tokens (tiktoken o200k_base)."""
    assert ALWAYS_LOADED_LIMIT == MAX_ALWAYS_LOADED_TOKENS
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        counter = load_counter()
    budget = always_loaded_budget(ROOT, counter)
    assert {"AGENTS.md", "CLAUDE.md", ".agents/skills/b1500-test/SKILL.md#description"} <= set(budget.parts)
    if counter.warning and budget.total > MAX_ALWAYS_LOADED_TOKENS:
        pytest.skip(f"only the chars/3.5 estimate is available ({budget.total} tokens): {counter.warning}")
    assert budget.total <= MAX_ALWAYS_LOADED_TOKENS, f"always-loaded text has {budget.total} tokens: {budget.parts}"
