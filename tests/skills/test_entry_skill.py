"""Entry skill ``b1500-test`` (blueprint 6.2) and the test-card template (6.3): the parts an agent relies on.

Budgets, links and frontmatter are checked by ``b1500 dev lint-skills`` (``test_lint_skills.py``); these tests pin
the content the M3 scenarios depend on: the nine parts in order, every tool in the tool table, every result in the
tier/error table, the six first cards with their recipes, and the template's frontmatter fields and section-4
contract (parameter table + example plan), which the lint checks only on real cards. Assertions look for names,
not for link syntax, so turning code spans into links (WP2.5-2.7) keeps them green.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from b1500_test_agent.devtools.lint_skills import (
    CARD_SECTIONS,
    EXAMPLE_PLAN_INFO,
    CardFrontmatter,
    ExamplePlan,
    MarkdownDoc,
    param_rows,
    parse_markdown,
)
from b1500_test_agent.service import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "b1500-test"

PARTS = (
    "Non-negotiables",
    "Workflow",
    "Tools",
    "Card index",
    "Tier and error handling",
    "Report template",
    "Re-measure policy",
    "Knowledge map",
    "Ad-hoc analysis",
)
RESULTS = ("ok", "needs_confirmation", "blocked", "summary_mismatch", "not_implemented", "busy", "fault",
           "invalid_config")
FIRST_CARDS = {  # blueprint 6.4
    "contact-resistor-check": "basic.contact_resistor",
    "diode-iv": "basic.diode_iv",
    "mosfet-idvg": "mosfet.idvg",
    "mosfet-idvd": "mosfet.idvd",
    "gate-leakage": "mosfet.gate_leakage",
    "fefet-dual-sweep-mw": "fefet.dual_sweep_mw",
}
KNOWLEDGE = ("01-device-physics", "02-b1500-instrument", "03-probe-station-wiring", "04-ferroelectric-oxide",
             "05-reliability-defects", "06-analysis-extraction", "07-hspice-simulation")


def _doc(rel: str) -> MarkdownDoc:
    return parse_markdown(SKILL_DIR / rel, rel)


def _part(doc: MarkdownDoc, number: int, title: str) -> str:
    span = doc.section(f"{number}. {title}")
    assert span is not None, f"missing '## {number}. {title}'"
    return "\n".join(doc.lines[span[0]:span[1] - 1])


@pytest.fixture(scope="module")
def skill() -> MarkdownDoc:
    return _doc("SKILL.md")


@pytest.fixture(scope="module")
def template() -> MarkdownDoc:
    return _doc("cards/_TEMPLATE.md")


def test_entry_skill_has_the_nine_parts_in_order(skill: MarkdownDoc) -> None:
    assert [h.text for h in skill.headings if h.level == 2] == [f"{i}. {t}" for i, t in enumerate(PARTS, 1)]


def test_tool_table_names_every_mcp_tool(skill: MarkdownDoc) -> None:
    text = _part(skill, 3, "Tools")
    assert [name for name in TOOL_NAMES if f"`{name}`" not in text] == []
    assert "list_recipes(recipe_id)" in text  # params come from the recipe, never from memory


def test_tier_table_covers_every_result(skill: MarkdownDoc) -> None:
    text = _part(skill, 5, "Tier and error handling")
    assert [result for result in RESULTS if f"`{result}`" not in text] == []
    assert "run_confirmed_plan(plan_id, summary)" in text and "verbatim" in text


def test_card_index_lists_the_first_six_cards_and_the_reserved_slots(skill: MarkdownDoc) -> None:
    text = _part(skill, 4, "Card index")
    missing = [f"{card} / {recipe}" for card, recipe in FIRST_CARDS.items()
               if f"cards/{card}.md" not in text or f"`{recipe}`" not in text]
    assert missing == []
    assert "cards/reserved/README.md" in text and "not_implemented" in text


def test_knowledge_map_names_the_seven_files_and_the_debug_skill(skill: MarkdownDoc) -> None:
    text = _part(skill, 8, "Knowledge map")
    assert [name for name in KNOWLEDGE if f"knowledge/{name}.md" not in text] == []
    assert "knowledge/README.md" in text and "`b1500-debug`" in text


def test_ad_hoc_analysis_imports_only_the_analysis_package(skill: MarkdownDoc) -> None:
    text = _part(skill, 9, "Ad-hoc analysis")
    imports = [line.strip() for line in text.splitlines() if line.strip().startswith(("import ", "from "))]
    assert imports and all(line.startswith("from b1500_test_agent.analysis import ") for line in imports)
    assert "work/<run_id>/" in text


def test_template_frontmatter_has_exactly_the_card_fields(template: MarkdownDoc) -> None:
    assert template.front_error is None and isinstance(template.front, dict)
    assert list(template.front) == list(CardFrontmatter.model_fields)


def test_template_has_the_ten_sections(template: MarkdownDoc) -> None:
    assert [h.text for h in template.headings if h.level == 2] == [
        f"{i}. {title}" for i, title in enumerate(CARD_SECTIONS, 1)]


def test_template_section_4_follows_the_card_contract(template: MarkdownDoc) -> None:
    span = template.section(f"4. {CARD_SECTIONS[3]}")
    assert span is not None
    rows, problems = param_rows(template, span[0] + 1, span[1])
    assert problems == [] and len(rows) >= 1
    blocks = [f for f in template.fences if f.info in EXAMPLE_PLAN_INFO and span[0] < f.line < span[1]]
    assert len(blocks) == 1
    plan = yaml.safe_load(blocks[0].body)
    assert isinstance(plan, dict) and set(plan) <= set(ExamplePlan.model_fields)
    required = {name for name, spec in ExamplePlan.model_fields.items() if spec.is_required()}
    assert required <= set(plan)
