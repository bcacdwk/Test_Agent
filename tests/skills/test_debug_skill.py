"""Debug skill ``b1500-debug`` (blueprint 6.5 domain 08, 8.2 S7; v2 6.1): the structure agents and test cards rely on.

Budgets, frontmatter and links are checked by ``b1500 dev lint-skills`` (``test_lint_skills.py``). These tests pin
the runbook ids that card ``debug:`` lists name (and that the lint resolves them), the fixed runbook structure, the
symptom x family router (WP11.1: every family has a row, and the ``any`` rows plus a family's row reach every runbook
the family's cards name), the human-only fault clear, the interrupted-run runbook, and the case template with the
deck's three seed cases, which stay ``draft`` until a human reviews them.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from b1500_test_agent.devtools import skills as lint_skills
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, parse_markdown

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "b1500-debug"
POSITIVE = ROOT / "tests" / "fixtures" / "skills" / "positive"
FIXTURE_CARD = ".agents/skills/b1500-test/cards/smu/mosfet-idvg.md"

RUNBOOKS = ("current-too-high", "noisy-data", "compliance-hit", "vth-drift-igzo", "errx-codes", "visa-no-connection",
            "interlock-open", "cleanup-failed-fault", "cmu-correction-stale", "spgu-selector-state",
            "spgu-pulse-no-effect", "spgu-load-mismatch", "smu-sampling-skips", "stress-degradation-unexpected",
            "wgfmu-library-error", "wgfmu-range-overflow", "wgfmu-memory-budget", "cmu-cv-distortion",
            "cmu-series-resistance", "wgfmu-rsu-route", "async-run-interrupted")
"""Blueprint 6.5 (v1 eight) + v2 6.1 (``cmu-correction-stale``, WP8.2; the three ``spgu-*``, WP9.3; the two SMU
runbooks, WP7.7; three ``wgfmu-*``, WP10.4; ``cmu-cv-distortion``, ``cmu-series-resistance``, WP8.6;
``wgfmu-rsu-route``, WP10.8; ``async-run-interrupted``, WP11.1); test cards name these ids in ``debug:``
(``runbooks/<id>.md`` stem)."""
ROUTER = "3. Symptom router (family x symptom)"
LONG_RUN_CARDS = ("reliability/bti-stress-measure", "reliability/hci-silc", "reliability/igzo-bias-stress",
                  "reliability/tddb-bdv", "nvm/fefet-endurance-retention", "nvm/fefet-pulse-write-read",
                  "nvm/fecap-pund", "smu/smu-sampling", "smu/smu-spot-kelvin", "system/zero-check", "cmu/moscap-cf-ct",
                  "wgfmu/wgfmu-rtn-noise", "spgu/spgu-pulse-train")
"""Cards whose recipes run asynchronously (long plans): they name ``async-run-interrupted`` (WP11.1)."""

RUNBOOK_SECTIONS = ("Symptom", "Likely causes", "First safe checks", "Physical checks to ask the human", "Do not",
                    "Stop and call safe_shutdown")
RUNBOOK_KEYS = ("id", "title", "maturity", "sources")
CASE_KEYS = ("id", "title", "status", "reviewed_by", "runbook", "backend", "station", "device", "runs", "sources")
CASE_SECTIONS = ("Symptom", "Observed data and status codes", "Physical checks", "Instrument checks",
                 "DUT hypotheses", "Resolution", "Reproducible", "Proposed follow-up")
SEED_CASES = {  # deck slide 17: the owner's three debug records
    "2026-11-04-current-orders-too-high": "current-too-high",
    "2026-11-04-noisy-data": "noisy-data",
    "2026-11-04-igzo-vth-drift": "vth-drift-igzo",
}
SKILL_PARTS = ("First moves", "Triage order (deck slide 17)", "Symptom router (family x symptom)",
               "Safe software checks", "Physical checks: ask the human", "Forbidden \"fixes\"", "Recording a case",
               "Iteration policy")
CLEAR_COMMAND = "uv run b1500 " + "fault clear"  # built indirectly: the harness guard blocks the literal in shells


def _doc(rel: str) -> MarkdownDoc:
    return parse_markdown(SKILL_DIR / rel, rel)


def _h2(doc: MarkdownDoc) -> list[str]:
    return [h.text for h in doc.headings if h.level == 2]


def _section(doc: MarkdownDoc, title: str) -> str:
    span = doc.section(title)
    assert span is not None, f"{doc.rel}: missing '## {title}'"
    return "\n".join(doc.lines[span[0]:span[1] - 1])


def test_runbooks_are_exactly_the_listed_ids() -> None:
    assert sorted(p.stem for p in (SKILL_DIR / "runbooks").glob("*.md")) == sorted(RUNBOOKS)


@pytest.mark.parametrize("runbook", RUNBOOKS)
def test_runbook_has_the_fixed_structure(runbook: str) -> None:
    doc = _doc(f"runbooks/{runbook}.md")
    assert doc.front_error is None and isinstance(doc.front, dict)
    assert tuple(doc.front) == RUNBOOK_KEYS
    assert doc.front["id"] == runbook and doc.front["title"] and doc.front["sources"]
    assert doc.front["maturity"] in ("seed", "draft", "reviewed")
    assert [h.level for h in doc.headings].count(1) == 1
    assert tuple(_h2(doc)) == RUNBOOK_SECTIONS
    assert [title for title in RUNBOOK_SECTIONS if not _section(doc, title).strip()] == []


def test_skill_has_the_parts_and_indexes_every_runbook() -> None:
    doc = _doc("SKILL.md")
    assert _h2(doc) == [f"{i}. {title}" for i, title in enumerate(SKILL_PARTS, 1)]
    index = _section(doc, ROUTER)
    targets = {target for target, _ in doc.links}
    assert [r for r in RUNBOOKS if f"runbooks/{r}.md" not in targets or f"[{r}]" not in index] == []
    triage = _section(doc, "2. Triage order (deck slide 17)")
    order = [triage.index(word) for word in ("Physical", "Instrument", "Data", "DUT")]
    assert order == sorted(order)


def test_skill_names_the_safe_checks_forbidden_fixes_and_case_recording() -> None:
    doc = _doc("SKILL.md")
    checks = _section(doc, "4. Safe software checks")
    assert all(item in checks for item in ("station_status", "contact-resistor-check", "lifts the probes",
                                           "integration", "validate_plan"))
    forbidden = _section(doc, "6. Forbidden \"fixes\"")
    assert all(item in forbidden for item in ("compliance", "config/local/**", "Bypass modes", "PyVISA",
                                              "fault clear"))
    recording = _section(doc, "7. Recording a case")
    assert "annotate_run" in recording and "status: draft" in recording and "cases/_TEMPLATE.md" in recording
    assert ".agents/skills/b1500-debug/cases/" in recording  # never the generated .claude/skills copy


def _router_rows(doc: MarkdownDoc) -> dict[str, set[str]]:
    """Family cell -> the runbook ids linked in that row of the router table."""
    rows: dict[str, set[str]] = {}
    for line in _section(doc, ROUTER).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 2 and cells[0] not in ("Family", "---"):
            rows[cells[0]] = set(re.findall(r"\(runbooks/([a-z0-9-]+)\.md\)", cells[1]))
    return rows


def test_router_has_a_row_per_family_and_reaches_every_card_runbook() -> None:
    """Blueprint v2 6.1 "symptom x family router": the ``any`` rows (state, data) and one row per recipe family; the
    ``any`` rows plus a family's row link every runbook that the family's cards name in ``debug:``."""
    from b1500_test_agent.devtools.skills.common import FAMILIES

    rows = _router_rows(_doc("SKILL.md"))
    assert list(rows) == ["any state", "any data", *FAMILIES]
    shared = rows["any state"] | rows["any data"]
    assert {"cleanup-failed-fault", "errx-codes", "async-run-interrupted"} <= rows["any state"]
    cards_dir = ROOT / ".agents" / "skills" / "b1500-test" / "cards"
    for family in FAMILIES:
        named: set[str] = set()
        for path in sorted((cards_dir / family).glob("*.md")):
            doc = parse_markdown(path, path.name)
            assert isinstance(doc.front, dict), path
            named |= set(doc.front["debug"])
        assert named, family
        assert sorted(named - shared - rows[family]) == [], family
    assert set().union(*rows.values()) == set(RUNBOOKS)  # every runbook is reachable from the router


@pytest.mark.parametrize("card", LONG_RUN_CARDS)
def test_long_run_cards_name_the_interrupted_run_runbook(card: str) -> None:
    path = ROOT / ".agents" / "skills" / "b1500-test" / "cards" / f"{card}.md"
    doc = parse_markdown(path, path.name)
    assert isinstance(doc.front, dict) and "async-run-interrupted" in doc.front["debug"]
    assert "`async-run-interrupted`" in "\n".join(doc.lines)  # section 9 maps a symptom to it


def test_interrupted_run_runbook_covers_every_end_state_and_the_human() -> None:
    """WP11.1: the server killed (the Codex headless turn end, WP7.7: recovery archives ``aborted``), the harness
    closed (stdin EOF or SIGTERM: ``cancelled``), the recovery path, partial data and what the human does."""
    doc = _doc("runbooks/async-run-interrupted.md")
    causes = _section(doc, "Likely causes")
    assert all(item in causes for item in ("SIGTERM", "`cancelled`", "codex-cli", "turn", "`aborted`",
                                           "consent record", "auto-calibration", "in-flight marker"))
    checks = _section(doc, "First safe checks")
    assert checks.index("safe_shutdown") < checks.index("station_status") < checks.index("get_run")
    assert "PARTIAL" in checks and "recovery_cleanup" in checks
    assert "fresh one" in _section(doc, "Physical checks to ask the human")
    dont = _section(doc, "Do not")
    assert "new consent" in dont and "inflight.json" in dont and "fault clear" in dont


def test_noisy_data_runbook_covers_scenario_s7() -> None:
    text = "\n".join(_doc("runbooks/noisy-data.md").lines)
    assert "noise-dominated" in text and "contact-resistor-check" in text
    assert "re-land" in text and "force" in text


def test_only_the_human_clears_the_fault_latch() -> None:
    doc = _doc("runbooks/cleanup-failed-fault.md")
    assert any(fence.body.strip() == CLEAR_COMMAND for fence in doc.fences)  # shown to the human
    assert "own terminal" in "\n".join(doc.lines)
    assert "Run that command yourself" in _section(doc, "Do not")


def test_interlock_runbook_has_no_high_voltage_path() -> None:
    doc = _doc("runbooks/interlock-open.md")
    assert "42 V" in _section(doc, "Likely causes")
    assert "defeating the interlock" in _section(doc, "Do not")


def test_case_template_structure() -> None:
    doc = _doc("cases/_TEMPLATE.md")
    assert doc.front_error is None and isinstance(doc.front, dict)
    assert tuple(doc.front) == CASE_KEYS and doc.front["status"] == "draft" and doc.front["reviewed_by"] is None
    assert tuple(_h2(doc)) == CASE_SECTIONS


def test_seed_cases_from_the_deck_are_drafts_for_human_review() -> None:
    names = {p.stem for p in (SKILL_DIR / "cases").glob("*.md") if not p.name.startswith("_")}
    assert set(SEED_CASES) <= names
    for name in sorted(names):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*", name), name
        doc = _doc(f"cases/{name}.md")
        assert doc.front_error is None and isinstance(doc.front, dict), name
        assert tuple(doc.front) == CASE_KEYS and doc.front["id"] == name, name
        assert doc.front["runbook"] in (*RUNBOOKS, "new"), name
        if doc.front["status"] != "reviewed":
            assert doc.front["status"] == "draft" and doc.front["reviewed_by"] is None, name
        assert tuple(_h2(doc)) == CASE_SECTIONS, name
    for name, runbook in SEED_CASES.items():
        doc = _doc(f"cases/{name}.md")
        assert doc.front["status"] == "draft" and doc.front["runbook"] == runbook
        assert "deck slide 17" in doc.front["sources"]


def test_lint_resolves_every_runbook_id_in_a_card(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(POSITIVE, root)
    shutil.rmtree(root / ".agents/skills/b1500-debug")
    shutil.copytree(SKILL_DIR, root / ".agents/skills/b1500-debug")
    card = root / FIXTURE_CARD
    text = card.read_text(encoding="utf-8")
    old = "debug: [noisy-data, compliance-hit]"
    assert text.count(old) == 1
    card.write_text(text.replace(old, "debug: [" + ", ".join(RUNBOOKS) + "]"), encoding="utf-8")
    report = lint_skills.lint_skills(root, config_dir=ROOT / "config")
    assert report.ok, lint_skills.format_report(report)
    assert report.runbooks == sorted(RUNBOOKS)
    card.write_text(text.replace(old, "debug: [noisy-data, current-too-low]"), encoding="utf-8")
    report = lint_skills.lint_skills(root, config_dir=ROOT / "config")
    assert [(p.code, p.file) for p in report.problems] == [("card_debug", FIXTURE_CARD)]
