"""The six first test cards of skill ``b1500-test`` and the reserved slots (blueprint 6.3-6.4, 8.2).

``b1500 dev lint-skills`` (``test_lint_skills.py``) checks frontmatter, sections, budgets, links, the card-recipe
graph, parameter tables and that each example plan validates on its simulator scenario. These tests pin what the M3
scenarios rely on beyond that: the example plans of S1 (Vth on ``nmos_basic``) and S10 (memory window on
``fefet_basic``), the card index status in ``SKILL.md``, debug ids from the eight runbooks, a simulator validation
record per card, no simulator scenario named in the expected-result section, and one reserved-slot entry per
``not_implemented`` recipe.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.lint_skills import CARD_SECTIONS, MarkdownDoc, parse_markdown

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "b1500-test"
CARDS = {  # blueprint 6.4
    "contact-resistor-check": "basic.contact_resistor",
    "diode-iv": "basic.diode_iv",
    "mosfet-idvg": "mosfet.idvg",
    "mosfet-idvd": "mosfet.idvd",
    "gate-leakage": "mosfet.gate_leakage",
    "fefet-dual-sweep-mw": "fefet.dual_sweep_mw",
}
RUNBOOKS = {"current-too-high", "noisy-data", "compliance-hit", "vth-drift-igzo", "errx-codes", "visa-no-connection",
            "interlock-open", "cleanup-failed-fault"}
RUN_ID = re.compile(r"\bS\d{8}T\d{6}Z-[0-9a-f]{4}\b")
SCENARIOS = sorted(p.stem for p in (ROOT / "config" / "sim" / "scenarios").glob("*.yaml"))


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(ROOT / "recipes", repo_root=ROOT)


def _card(card: str) -> MarkdownDoc:
    return parse_markdown(SKILL_DIR / "cards" / f"{card}.md", f"cards/{card}.md")


def _section(doc: MarkdownDoc, number: int) -> str:
    span = doc.section(f"{number}. {CARD_SECTIONS[number - 1]}")
    assert span is not None
    return "\n".join(doc.lines[span[0]:span[1] - 1])


def _example(doc: MarkdownDoc) -> dict:
    block = re.search(r"```yaml\n(.*?)```", _section(doc, 4), flags=re.DOTALL)
    assert block is not None
    return yaml.safe_load(block.group(1))


@pytest.mark.parametrize("card", sorted(CARDS))
def test_card_and_recipe_point_at_each_other(card: str, registry: RecipeRegistry) -> None:
    doc = _card(card)
    assert doc.front["recipes"] == [CARDS[card]]
    assert registry.get(CARDS[card]).card == f".agents/skills/b1500-test/cards/{card}.md"
    assert set(doc.front["debug"]) <= RUNBOOKS


@pytest.mark.parametrize("card", sorted(CARDS))
def test_card_has_sim_validation_record_and_no_scenario_in_expected_shape(card: str) -> None:
    doc = _card(card)
    record = _section(doc, 10)
    sim_rows = [line for line in record.splitlines() if line.startswith("| sim |")]
    assert sim_rows and all(RUN_ID.search(line) for line in sim_rows)
    assert _example(doc)["sim_scenario"] in sim_rows[0]
    assert "| hw (M4) | pending M4 |" in record
    expected = _section(doc, 8)
    assert [s for s in SCENARIOS if s in expected] == []  # typical ranges, never simulator truth


def test_m3_scenarios_find_their_example_plans(registry: RecipeRegistry) -> None:
    s1 = _example(_card("mosfet-idvg"))
    assert (s1["pin_map"], s1["dut_profile"], s1["sim_scenario"]) == ("mosfet-4t", "nmos-generic", "nmos_basic")
    assert registry.get("mosfet.idvg").analysis_defaults[0].method == "vth_linear_extrapolation"
    s10 = _example(_card("fefet-dual-sweep-mw"))
    assert s10["sim_scenario"] == "fefet_basic"
    assert registry.get("fefet.dual_sweep_mw").analysis_defaults[0].method == "memory_window"
    assert "vth_fwd" in _section(_card("fefet-dual-sweep-mw"), 7)
    contact = _example(_card("contact-resistor-check"))  # S7: contact check on any landing
    assert (contact["pin_map"], contact["dut_profile"]) == ("resistor-2t", "resistor-generic")


def test_card_index_status_matches_the_cards() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for card, recipe in CARDS.items():
        row = next(line for line in text.splitlines() if f"(cards/{card}.md)" in line)
        assert f"`{recipe}`" in row and row.rstrip(" |").endswith(_card(card).front["status"])


def test_reserved_readme_lists_every_reserved_recipe_with_preconditions(registry: RecipeRegistry) -> None:
    text = (SKILL_DIR / "cards" / "reserved" / "README.md").read_text(encoding="utf-8")
    reserved = sorted(p.stem for p in (ROOT / "recipes" / "reserved").glob("*.yaml"))
    assert reserved and all(registry.get(r).status == "not_implemented" for r in reserved)
    for recipe in reserved:
        assert f"| `{recipe}` |" in text, recipe
        assert f"- `{recipe}`:" in text, recipe  # its preconditions bullet
