"""Skill ``b1500-bringup`` skeleton (blueprint v2 6.1, 6.2, 7.4): the trigger description, the four rules
(the human does every physical step and adopts every configuration; stop on any abort criterion; no records from
simulator ``S...`` runs), the stage order with the blueprint file names, the stage template sections and the
draft-record template. Stage files arrive with WP6.3 and the module closure WPs; ``lint-skills`` checks them."""

from __future__ import annotations

from pathlib import Path

import yaml

from b1500_test_agent.devtools.skills.common import RECORD_KEYS, STAGE_SECTIONS, STAGES
from b1500_test_agent.devtools.skills.markdown import parse_markdown

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "b1500-bringup"
MAX_DESCRIPTION_CHARS = 300
CLAUDE_DESCRIPTION_CAP = 1536  # Claude Code's per-skill listing cap (ATV-29)


def _skill_text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_description_has_trigger_words_first_and_fits_both_listings() -> None:
    front = parse_markdown(SKILL_DIR / "SKILL.md", "SKILL.md").front
    description = front["description"]
    assert front["name"] == "b1500-bringup"
    assert description.startswith("B1500A hardware bring-up")
    assert len(description) <= MAX_DESCRIPTION_CHARS <= CLAUDE_DESCRIPTION_CAP
    for word in ("lab PC", "visa", "rehearsal", "rewiring", "validation records", "Not for routine measurements"):
        assert word in description, word


def test_rules_hand_physical_steps_and_config_to_the_human() -> None:
    doc = parse_markdown(SKILL_DIR / "SKILL.md", "SKILL.md")
    span = doc.section("1. Rules")
    assert span is not None
    rules = " ".join(" ".join(doc.lines[span[0]:span[1] - 1]).split())
    for needle in ("The human does every physical step", "The human adopts configuration", "`config/local/**`",
                   "Stop on any abort criterion", "`safe_shutdown(reason)`", "Never relax",
                   "Records only from hardware runs", "`S...`", "never become validation records",
                   "Never write `validation/hw/`", "never set `hw_validated`", "`first_hw_run`",
                   "The harness approval prompt is not consent"):
        assert needle in rules, needle
    assert "skill `b1500-test`" in _skill_text()


def test_stage_table_lists_every_stage_in_order_with_its_file() -> None:
    doc = parse_markdown(SKILL_DIR / "SKILL.md", "SKILL.md")
    span = doc.section("2. Stages")
    assert span is not None
    rows = [line for line in doc.lines[span[0]:span[1] - 1] if line.startswith("| ") and not line.startswith("| Stage")]
    assert [row.split("|")[1].strip() for row in rows] == list(STAGES)
    for row, (stem, _goal) in zip(rows, STAGES.values(), strict=True):
        assert row.rstrip().endswith(f"`stages/{stem}.md` |")


def test_stage_template_has_the_six_sections() -> None:
    doc = parse_markdown(SKILL_DIR / "stages" / "_TEMPLATE.md", "stages/_TEMPLATE.md")
    assert [h.text for h in doc.headings if h.level == 2] == [f"{i}. {t}" for i, t in enumerate(STAGE_SECTIONS, 1)]
    assert set(doc.front) == {"stage", "title", "recipes", "version"}


def test_record_template_is_a_draft_without_reviewer_or_runs() -> None:
    data = yaml.safe_load((SKILL_DIR / "records" / "_TEMPLATE.yaml").read_text(encoding="utf-8"))
    assert list(data) == list(RECORD_KEYS)
    assert data["reviewer"] == "" and data["reviewed_on"] is None and data["runs"] == []
    assert data["backend"] == "visa"
    assert sorted(p.name for p in (SKILL_DIR / "records").iterdir()) == ["_TEMPLATE.yaml"]


def test_skill_stays_within_its_budget() -> None:
    assert len(_skill_text().splitlines()) <= 120
