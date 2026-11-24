"""SMU module closure (WP7.7, blueprint v2 10 intro "Per-module closure AC", 3.1, 7.4): every recipe of the §3.1
catalogue is registered and ``sim_validated`` (its integration test against model truth passed in its WP), the
``smu`` family listing has no ``not_implemented`` entry left (``hspice.compare`` retired), every carded recipe sits on
the bring-up stage §3.1 names and that stage file runs it, and the SMU analysis methods are all implemented."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.analysis.registry import methods_for
from b1500_test_agent.bringup import load_stage
from b1500_test_agent.catalog.registry import RecipeRegistry
from tests.integration.helpers import REPO_ROOT, World

pytestmark = pytest.mark.smu

SECTION_3_1: dict[str, str] = {  # recipe -> bring-up stage (blueprint v2 3.1 "Stage" column)
    "basic.contact_resistor": "L2", "basic.diode_iv": "L3", "mosfet.idvg": "L4", "mosfet.idvd": "L4",
    "mosfet.gate_leakage": "L4", "fefet.dual_sweep_mw": "L7", "generic.smu_staircase": "", "system.self_test": "L1",
    "system.self_cal": "L1", "system.zero_check": "L1", "generic.smu_spot": "L2", "resistor.kelvin_4w": "L2",
    "basic.iv_force_i": "L3", "mosfet.idvg_family": "L4", "mosfet.idvg_sync": "L4", "mosfet.body_effect": "L4",
    "generic.smu_multi_sweep": "L2", "mosfet.idvg_pulsed": "L5", "mosfet.idvd_pulsed": "L5", "basic.pulsed_spot": "L5",
    "generic.smu_multi_pulsed": "L5", "generic.smu_sampling": "L5", "mosfet.id_t_sampling": "L5",
    "reliability.tddb_cvs": "L9", "mosfet.vth_search": "L5", "basic.breakdown_search": "L9", "dielectric.bdv": "L9",
    "reliability.bti_sms": "L9", "igzo.bias_stress": "L9", "reliability.hci": "L9", "reliability.silc": "L9",
}  # fmt: skip
"""The 31 SMU + GNDU recipes of blueprint v2 3.1 (the v1 nine included) and their stages (generic.smu_staircase:
no card by design, no stage)."""


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


def test_every_section_3_1_recipe_is_sim_validated(registry: RecipeRegistry) -> None:
    assert len(SECTION_3_1) == 31
    assert {r: registry.effective_status(r, "sim") for r in SECTION_3_1} == {r: "sim_validated" for r in SECTION_3_1}
    assert "hspice.compare" not in registry.ids()  # retired by WP7.7 (compact models are analysis methods)


def test_recipes_family_smu_lists_only_sim_validated_recipes(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in world.env().items():
        monkeypatch.setenv(name, value)
    result = CliRunner().invoke(app, ["recipes", "--family", "smu", "--json"])
    assert result.exit_code == 0, result.output
    listing = yaml.safe_load(result.stdout)
    statuses = {entry["id"]: entry["status"] for entry in listing["recipes"]}
    assert statuses and set(statuses.values()) == {"sim_validated"}, statuses
    assert set(statuses) <= set(SECTION_3_1) and "mosfet.idvg" in statuses


def test_cards_sit_on_their_section_3_1_stage_and_the_stage_runs_them(registry: RecipeRegistry) -> None:
    for recipe_id, stage in SECTION_3_1.items():
        recipe = registry.get(recipe_id)
        if not stage:
            assert recipe.card is None
            continue
        front = yaml.safe_load(Path(REPO_ROOT / (recipe.card or "")).read_text(encoding="utf-8").split("---")[1])
        assert front["bringup_stage"] == stage, recipe_id
        _path, stage_front, problem = load_stage(REPO_ROOT, stage)
        if stage in ("L5", "L9", "L1", "L2", "L3", "L4"):  # written stage files (L7: WP9.6)
            assert stage_front is not None, problem
            assert recipe_id in stage_front.recipes, (recipe_id, stage)


def test_smu_analysis_methods_are_implemented() -> None:
    names = {m.name for m in methods_for("smu")}
    assert {"compact_model_fit", "model_compare", "export_spice_netlist", "vth_search_value", "pulsed_vs_dc",
            "kelvin_resistance", "zero_floor", "dibl", "sampling_summary"} <= names
    assert all(m.status == "implemented" for m in methods_for("smu"))
