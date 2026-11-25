"""Entry skill ``b1500-test`` v2 (blueprint v2 6.1, 6.2, 5.2 "Agents") and the test-card template (6.3): the parts an
agent relies on.

Budgets, links and frontmatter are checked by ``b1500 dev lint-skills`` (``test_lint_skills.py``); these tests pin
the content the acceptance scenarios and later work packages depend on: the ten parts in order, every tool in the
tools part, every result in the tier table plus the v2 confirm reasons, the family router (≤ 8 rows, one per
family, each linking ``cards/README.md#<family>``), the async workflow (WP5.6 behaviour, blueprint 2.6/2.9), the
four-line manual lookup with the citation form and the doc-id table of the knowledge index, and the template's
frontmatter fields and section-4 contract (parameter table + example plan), which the lint checks only on real
cards. Assertions look for names, not for link syntax.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.devtools.skills.cards import EXAMPLE_PLAN_INFO
from b1500_test_agent.devtools.skills.common import CARD_SECTIONS, FAMILIES, CardFrontmatter, ExamplePlan
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, parse_markdown
from b1500_test_agent.devtools.skills.params import param_rows
from b1500_test_agent.manuals.catalog import load_catalog
from b1500_test_agent.service import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "b1500-test"

PARTS = (
    "Non-negotiables",
    "Workflow",
    "Tools",
    "Family router",
    "Tiers and errors",
    "Long runs",
    "Manual lookup",
    "Report template",
    "Re-measure policy",
    "Knowledge and ad-hoc analysis",
)
RESULTS = ("ok", "needs_confirmation", "blocked", "summary_mismatch", "busy", "fault", "invalid_config",
           "invalid_input", "error", "plan_stale")
"""The results part 5 names (WP11.2: no retired reserved status, ``models.common.ResultStatus``)."""
NEW_CONFIRM_REASONS = ("soft_pulse", "soft_cmu", "long_run", "physical_setup", "unverified_topology")
MAX_ROUTER_ROWS = 8
MANUAL_LOOKUP_LINES = 4


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


def test_entry_skill_has_the_ten_parts_in_order(skill: MarkdownDoc) -> None:
    assert [h.text for h in skill.headings if h.level == 2] == [f"{i}. {t}" for i, t in enumerate(PARTS, 1)]


def test_tools_part_names_every_mcp_tool(skill: MarkdownDoc) -> None:
    text = _part(skill, 3, "Tools")
    assert [name for name in TOOL_NAMES if f"`{name}`" not in text] == []
    assert "`recipe_id`" in text and "progress" in text  # params from the recipe; get_run progress (async)


def test_tier_table_covers_every_result_and_the_new_confirm_reasons(skill: MarkdownDoc) -> None:
    text = _part(skill, 5, "Tiers and errors")
    assert [result for result in RESULTS if f"`{result}`" not in text] == []
    assert "run_confirmed_plan(plan_id, summary)" in text and "verbatim" in text
    assert [reason for reason in NEW_CONFIRM_REASONS if f"`{reason}`" not in text] == []
    assert "`running`" in text and "`cancelled`" in text


def test_family_router_links_every_family_index(skill: MarkdownDoc) -> None:
    text = _part(skill, 4, "Family router")
    rows = [line for line in text.splitlines() if line.startswith("| [")]
    assert 1 <= len(rows) <= MAX_ROUTER_ROWS
    linked = [m.group(1) for row in rows for m in re.finditer(r"\(cards/README\.md#([a-z]+)\)", row)]
    assert linked == list(FAMILIES)
    assert "not runnable" in text and "never emulate" in text and "`generic.smu_staircase`" in text
    assert "not_" + "implemented" not in text and "Reserved" not in text  # WP11.2
    assert "cards/smu/" not in text  # cards are reached through the generated index, one hop from here


def test_long_runs_describe_the_async_workflow(skill: MarkdownDoc) -> None:
    """Blueprint 2.6/2.9 (built by WP5.6): run -> outcome running -> poll get_run include=progress -> report;
    cancel = safe_shutdown from any process; partial data labelled."""
    text = _part(skill, 6, "Long runs")
    for needle in ("`outcome: running`", "`run_id`", "`eta_s`", "get_run(run_id, include=[progress])", "`busy`",
                   "`long_run`", "safe_shutdown(reason)", "`cancelled`", "partial", "`mode`", "`est_s`"):
        assert needle in text, needle
    assert "uv run b1500 shutdown" in text


def test_manual_lookup_is_four_lines_with_commands_and_citation_form(skill: MarkdownDoc) -> None:
    text = _part(skill, 7, "Manual lookup")
    body = [line for line in text.splitlines() if line.strip()]
    assert len(body) == MANUAL_LOOKUP_LINES
    joined = " ".join(body)
    for needle in ("knowledge first", "uv run b1500 manual search", "uv run b1500 manual page",
                   "knowledge/README.md#manual-documents", "`PG p433 (4-115)`", "never paste long passages"):
        assert needle in joined, needle


def test_knowledge_index_lists_every_manual_doc_id_once() -> None:
    catalog = load_catalog(ROOT / "references" / "manuals" / "catalog.yaml")
    doc = _doc("knowledge/README.md")
    text = "\n".join(doc.lines)
    span = doc.section("Manual documents")
    assert span is not None
    table = "\n".join(doc.lines[span[0]:span[1] - 1])
    ids = [row.split("|")[1].strip() for row in table.splitlines() if row.startswith("| ") and not
           row.startswith("| id ")]
    assert ids == list(catalog.ids)
    assert "manual search|page|toc" in table and "PG p433 (4-115)" in text


def test_report_template_and_knowledge_part(skill: MarkdownDoc) -> None:
    report = _part(skill, 8, "Report template")
    assert "SIMULATED" in report and "one line each, not a table" in report and "partial" in report
    knowledge = _part(skill, 10, "Knowledge and ad-hoc analysis")
    assert "knowledge/README.md" in knowledge and "`b1500-debug`" in knowledge and "`b1500-bringup`" in knowledge


def test_ad_hoc_analysis_imports_only_the_analysis_package(skill: MarkdownDoc) -> None:
    text = _part(skill, 10, "Knowledge and ad-hoc analysis")
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
