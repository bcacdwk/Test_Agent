"""The test cards of skill ``b1500-test`` (blueprint v1 6.3-6.4, 8.2; v2 6.1, 6.3) and the reserved slots.

``b1500 dev lint-skills`` (``test_lint_skills.py``) checks frontmatter, family folders, sections, budgets, links,
the card-recipe graph, modules/routes/stage, parameter tables, the generated index and that each example plan
validates on its simulator scenario. These tests pin what the acceptance scenarios and the bring-up rely on beyond
that: the cards' family paths and v2 frontmatter (family, stage, manual citations), the example plans of S1 (Vth on
``nmos_basic``) and S10 (memory window on ``fefet_basic``), the generated index rows, debug ids from the eight
runbooks, a simulator validation record per card plus the hardware record path and stage, no simulator scenario
named in the expected-result section, and one reserved-slot entry per ``not_implemented`` recipe.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.skills.citations import CANONICAL
from b1500_test_agent.devtools.skills.common import CARD_SECTIONS, CARDLESS_RECIPES, STAGES
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, parse_markdown

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "b1500-test"
CARDS = {  # card path under cards/ -> recipes (v1 blueprint 6.4 + the v2 system card, blueprint 6.3)
    "smu/contact-resistor-check": ["basic.contact_resistor"],
    "smu/diode-iv": ["basic.diode_iv", "basic.iv_force_i"],
    "smu/mosfet-idvg": ["mosfet.idvg", "mosfet.idvg_family", "mosfet.idvg_sync", "mosfet.body_effect"],
    "smu/mosfet-idvd": ["mosfet.idvd"],
    "smu/gate-leakage": ["mosfet.gate_leakage"],
    "nvm/fefet-dual-sweep-mw": ["fefet.dual_sweep_mw"],
    "system/self-test-cal": ["system.self_test", "system.self_cal", "system.wgfmu_self_test",
                             "system.wgfmu_self_cal"],  # WP10.7: the WGFMU library self-test/cal
    "smu/smu-sampling": ["mosfet.id_t_sampling", "generic.smu_sampling"],  # WP7.4
    "reliability/tddb-bdv": ["reliability.tddb_cvs", "dielectric.bdv", "basic.breakdown_search"],  # WP7.4, WP7.5
    "smu/smu-spot-kelvin": ["generic.smu_spot", "resistor.kelvin_4w", "generic.smu_multi_sweep"],  # WP7.1, WP7.2
    "system/zero-check": ["system.zero_check"],  # WP7.1
    "reliability/bti-stress-measure": ["reliability.bti_sms", "wgfmu.fast_bti"],  # WP7.6, WP10.7
    "reliability/igzo-bias-stress": ["igzo.bias_stress"],  # WP7.6
    "reliability/hci-silc": ["reliability.hci", "reliability.silc"],  # WP7.6
    "cmu/cmu-correction": ["cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short",
                           "cmu.correction_load"],  # WP8.2
    "cmu/cmu-spot": ["cmu.spot"], "cmu/moscap-cv": ["moscap.cv"],  # WP8.3
    "cmu/mosfet-split-cv": ["mosfet.cgc_cv", "mosfet.cgd_cv"],  # WP8.3
    "spgu/selector-check": ["system.selector_check"],  # WP9.2
    "smu/smu-pulsed-iv": ["mosfet.idvg_pulsed", "mosfet.idvd_pulsed", "basic.pulsed_spot",
                          "generic.smu_multi_pulsed"],  # WP7.3
    "spgu/spgu-pulse-train": ["spgu.pulse_train", "spgu.alwg_sequence"],  # WP9.3
    "spgu/charge-pumping": ["mosfet.charge_pumping"],  # WP9.3
    "smu/smu-search": ["mosfet.vth_search"],  # WP7.5
    "nvm/fefet-pulse-write-read": ["fefet.pulse_write_read", "spgu.program_smu_read",
                                   "fefet.fast_program_read"],  # WP9.4; WP10.6: the WGFMU section
    "cmu/moscap-cf-ct": ["moscap.cf", "moscap.ct"], "nvm/fecap-cv-butterfly": ["fecap.cv_butterfly"],  # WP8.4
    "nvm/fecap-pund": ["fecap.pund", "fecap.endurance_pund"],  # WP10.6 (the butterfly split into its own card)
    "smu/compact-model-spice": [],  # WP7.7: analysis only (compact_model_fit, model_compare, export_spice_netlist)
    "wgfmu/wgfmu-pulsed-iv": ["wgfmu.pulsed_iv", "wgfmu.fast_iv", "wgfmu.pulse_train"],  # WP10.4
    "wgfmu/wgfmu-custom-waveform": ["wgfmu.custom_waveform", "wgfmu.dc_spot"],  # WP10.4
    "nvm/fefet-switching-kinetics": ["fefet.switching_kinetics"],  # WP9.5
    "nvm/fefet-endurance-retention": ["fefet.endurance", "fefet.retention"],  # WP9.5
    "cmu/moscap-dit": ["moscap.qscv", "moscap.cv_multi_freq"],  # WP8.5
    "wgfmu/wgfmu-rtn-noise": ["wgfmu.rtn", "wgfmu.lfn"],  # WP10.5
}
CARDS["cmu/moscap-cv"] = ["moscap.cv", "moscap.cv_ac_level", "moscap.pulsed_cv"]  # WP8.4 adds the AC-level/pulsed C-V
ROUTES = {"spgu/selector-check": ["selector_16440a:smu", "selector_16440a:pgu", "selector_16440a:pgu_open"],
          "spgu/spgu-pulse-train": ["selector_16440a:pgu"], "spgu/charge-pumping": ["selector_16440a:pgu"],
          "cmu/cmu-correction": ["scuu:cmu"], "cmu/moscap-cv": ["scuu:cmu"], "cmu/mosfet-split-cv": ["scuu:cmu"],
          "nvm/fefet-pulse-write-read": ["selector_16440a:pgu", "selector_16440a:smu", "rsu:wgfmu"],  # +WP10.6
          "cmu/moscap-cf-ct": ["scuu:cmu"],  # WP8.4
          "nvm/fecap-pund": ["rsu:wgfmu"],  # WP10.6
          "wgfmu/wgfmu-pulsed-iv": ["rsu:wgfmu"], "wgfmu/wgfmu-custom-waveform": ["rsu:wgfmu"],
          "nvm/fefet-switching-kinetics": ["selector_16440a:pgu", "selector_16440a:smu"],  # WP9.5
          "nvm/fefet-endurance-retention": ["selector_16440a:pgu", "selector_16440a:smu"],
          "cmu/moscap-dit": ["scuu:smu", "scuu:cmu"],  # WP8.5
          "wgfmu/wgfmu-rtn-noise": ["rsu:wgfmu"],  # WP10.5
          "reliability/bti-stress-measure": ["rsu:wgfmu"]}  # WP10.7: the fast BTI's RSU path
"""Cards whose recipes set switch routes (WP9.2, WP9.3; WP8.3: the MFCMU recipes through an SCUU when the pin map says
so; WP9.4: program/read through the selector; WP10.4: the RSU path of the WGFMU; WP8.5: QSCV through the SCUU's SMU
path); every other card's recipes route nothing ("Routes: none")."""
STAGE_OF = {"smu/contact-resistor-check": "L2", "smu/diode-iv": "L3", "smu/mosfet-idvg": "L4", "smu/mosfet-idvd": "L4",
            "smu/gate-leakage": "L4", "nvm/fefet-dual-sweep-mw": "L7", "system/self-test-cal": "L1",
            "smu/smu-sampling": "L5", "reliability/tddb-bdv": "L9", "smu/smu-spot-kelvin": "L2",
            "system/zero-check": "L1", "reliability/bti-stress-measure": "L9", "reliability/igzo-bias-stress": "L9",
            "reliability/hci-silc": "L9", "cmu/cmu-correction": "L6", "spgu/selector-check": "L7",
            "smu/smu-pulsed-iv": "L5", "spgu/spgu-pulse-train": "L7", "spgu/charge-pumping": "L7",
            "smu/smu-search": "L5",  # WP7.5
            "cmu/cmu-spot": "L6", "cmu/moscap-cv": "L6", "cmu/mosfet-split-cv": "L6",  # WP8.3
            "nvm/fefet-pulse-write-read": "L7",  # WP9.4
            "cmu/moscap-cf-ct": "L6", "nvm/fecap-cv-butterfly": "L6",  # WP8.4
            "nvm/fecap-pund": "L8",  # WP10.6 (fefet-pulse-write-read: fefet.fast_program_read at L8, recipe_stages)
            "smu/compact-model-spice": "L4",  # WP7.7
            "wgfmu/wgfmu-pulsed-iv": "L8", "wgfmu/wgfmu-custom-waveform": "L8",  # WP10.4
            "nvm/fefet-switching-kinetics": "L7", "nvm/fefet-endurance-retention": "L9",  # WP9.5
            "cmu/moscap-dit": "L6",  # WP8.5
            "wgfmu/wgfmu-rtn-noise": "L8"}  # WP10.5
"""Blueprint v2 7.4 / 3.1: the stage that validates each card's recipes on hardware."""
RECIPE_STAGES = {"nvm/fefet-pulse-write-read": {"fefet.fast_program_read": "L8"}}
"""Recipes another stage validates than their card's (frontmatter ``recipe_stages``; WP10.6)."""
RUNBOOKS = {"current-too-high", "noisy-data", "compliance-hit", "vth-drift-igzo", "errx-codes", "visa-no-connection",
            "interlock-open", "cleanup-failed-fault", "cmu-correction-stale",  # WP8.2: the first v2 runbook
            "spgu-selector-state", "spgu-pulse-no-effect", "spgu-load-mismatch",  # WP9.3
            "smu-sampling-skips", "stress-degradation-unexpected",  # WP7.7
            "wgfmu-library-error", "wgfmu-range-overflow", "wgfmu-memory-budget",  # WP10.4
            "cmu-cv-distortion", "cmu-series-resistance"}  # WP8.6
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


def test_cards_are_exactly_the_planned_ones() -> None:
    found = sorted(p.relative_to(SKILL_DIR / "cards").with_suffix("").as_posix()
                   for p in (SKILL_DIR / "cards").glob("*/*.md") if p.parent.name != "reserved")
    assert found == sorted(CARDS)
    assert sorted(p.name for p in (SKILL_DIR / "cards").glob("*.md")) == ["README.md", "_TEMPLATE.md"]


@pytest.mark.parametrize("card", sorted(CARDS))
def test_card_and_recipe_point_at_each_other(card: str, registry: RecipeRegistry) -> None:
    doc = _card(card)
    assert doc.front["recipes"] == CARDS[card]
    for recipe in CARDS[card]:
        assert registry.get(recipe).card == f".agents/skills/b1500-test/cards/{card}.md"
        assert registry.get(recipe).family == doc.front["family"] == card.split("/")[0]
    assert set(doc.front["debug"]) <= RUNBOOKS


@pytest.mark.parametrize("card", sorted(CARDS))
def test_card_frontmatter_v2(card: str) -> None:
    front = _card(card).front
    assert front["bringup_stage"] == STAGE_OF[card] and front["bringup_stage"] in STAGES
    assert front["manual"] and all(CANONICAL.fullmatch(entry) for entry in front["manual"])
    assert front["routes"] == ROUTES.get(card, [])  # the SPGU cards (WP9.2, WP9.3) and the SCUU path (WP8.3) route
    assert front["intent"]


@pytest.mark.parametrize("card", sorted(CARDS))
def test_card_has_sim_and_hw_validation_records_and_no_scenario_in_expected_shape(card: str) -> None:
    doc = _card(card)
    record = _section(doc, 10)
    sim_rows = [line for line in record.splitlines() if line.startswith("| sim |")]
    assert sim_rows and all(RUN_ID.search(line) for line in sim_rows)
    assert _example(doc)["sim_scenario"] in sim_rows[0]
    assert f"| hw | pending (bring-up stage {STAGE_OF[card]}) |" in record
    for recipe in CARDS[card]:
        assert f"`validation/hw/{recipe}.yaml`" in record
    assert ("Routes per phase:" if card in ROUTES else "Routes: none") in _section(doc, 2)
    expected = _section(doc, 8)
    assert [s for s in SCENARIOS if s in expected] == []  # typical ranges, never simulator truth


def test_m3_scenarios_find_their_example_plans(registry: RecipeRegistry) -> None:
    s1 = _example(_card("smu/mosfet-idvg"))
    assert (s1["pin_map"], s1["dut_profile"], s1["sim_scenario"]) == ("mosfet-4t", "nmos-generic", "nmos_basic")
    assert registry.get("mosfet.idvg").analysis_defaults[0].method == "vth_linear_extrapolation"
    s10 = _example(_card("nvm/fefet-dual-sweep-mw"))
    assert s10["sim_scenario"] == "fefet_basic"
    assert registry.get("fefet.dual_sweep_mw").analysis_defaults[0].method == "memory_window"
    assert "vth_fwd" in _section(_card("nvm/fefet-dual-sweep-mw"), 7)
    contact = _example(_card("smu/contact-resistor-check"))  # S7: contact check on any landing
    assert (contact["pin_map"], contact["dut_profile"]) == ("resistor-2t", "resistor-generic")


def test_generated_index_has_a_row_per_card_and_recipe(registry: RecipeRegistry) -> None:
    text = (SKILL_DIR / "cards" / "README.md").read_text(encoding="utf-8")
    for card, recipes in CARDS.items():
        row = next(line for line in text.splitlines() if f"]({card}.md)" in line)
        family = card.split("/")[0]
        assert row.startswith(f"| {family} |") and all(f"`{r}`" in row for r in recipes)
        stage = STAGE_OF[card] + "".join(f" (`{r}`: {s})" for r, s in RECIPE_STAGES.get(card, {}).items())
        assert f"| {_card(card).front['status']} |" in row and row.endswith(f"| {stage} |")
    for recipe in CARDLESS_RECIPES:
        assert f"| `{recipe}` |" in text and "no card by design" in text
    for recipe in registry.ids():
        if registry.get(recipe).status == "not_implemented":
            assert f"| `{recipe}` | not_implemented |" in text, recipe


def test_reserved_readme_lists_every_reserved_recipe_with_preconditions(registry: RecipeRegistry) -> None:
    text = (SKILL_DIR / "cards" / "reserved" / "README.md").read_text(encoding="utf-8")
    reserved = sorted(p.stem for p in (ROOT / "recipes" / "reserved").glob("*.yaml"))
    assert all(registry.get(r).status == "not_implemented" for r in reserved)
    if not reserved:  # WP10.6 implemented the last slot (fecap.pund): the README says so until WP11.2 deletes it
        assert "No reserved slot is left" in text and "`fecap.pund` (WP10.6" in text
    for recipe in reserved:
        assert f"| `{recipe}` |" in text, recipe
        assert f"- `{recipe}`:" in text, recipe  # its preconditions bullet
