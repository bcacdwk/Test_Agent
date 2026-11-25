"""``RecipeRegistry`` (blueprint 2.6): the committed tree is clean; every problem class is reported; status, the
backends a recipe runs on (``runnable``) and listing."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.catalog.registry import RecipeRegistry, UnknownRecipeError
from tests.unit.helpers import REPO_ROOT

RECIPES = REPO_ROOT / "recipes"
CORRECTION_RECIPES = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short", "cmu.correction_load")
RETIRED_IDS = ("cmu.correction", "hspice.compare")
"""The two v1 reserved ids blueprint v2 3 retires (WP8.2: the four cmu.* correction recipes; WP7.7: compact models are
the analysis methods compact_model_fit, model_compare and export_spice_netlist). Every other v1 reserved id is a
recipe now (WP7.6 bti_sms, hci; WP8.3 moscap.cv, mosfet.cgd_cv; WP9.4 fefet.pulse_write_read, spgu.program_smu_read;
WP10.4 wgfmu.pulsed_iv; WP8.5 moscap.qscv; WP10.7 wgfmu.fast_bti; WP10.6 fecap.pund), and WP11.2 deleted the reserved
folder, the status and the declared-only kind."""
V1_RESERVED_IDS = ("reliability.bti_sms", "reliability.hci", "reliability.tddb_cvs", "moscap.cv", "mosfet.cgd_cv",
                   "fefet.pulse_write_read", "spgu.program_smu_read", "wgfmu.pulsed_iv", "moscap.qscv",
                   "wgfmu.fast_bti", "fecap.pund")
"""The v1 reserved ids blueprint v2 3 marks ``*`` (implemented under that id)."""
WGFMU_RECIPES = ("wgfmu.pulsed_iv", "wgfmu.fast_iv", "wgfmu.pulse_train", "wgfmu.custom_waveform", "wgfmu.dc_spot",
                 "wgfmu.rtn", "wgfmu.lfn")
"""Kind wgfmu_waveform (WP10.4; tests/integration/test_recipes_wgfmu.py; WP10.5 rtn, lfn:
tests/integration/test_recipes_noise.py)."""


def minimal(recipe_id: str = "basic.thing", **changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": recipe_id, "version": 1, "title": "t", "family": "smu", "kind": "smu_staircase", "status": "draft",
        "card": None,
        "device_types": [], "roles": {"sweep": {"function": "sweep_v", "measure": ["I"],
                                                "settings": {"start": "$a", "stop": 1.0, "points": 11,
                                                             "icomp": 1e-3}}},
        "params": {"a": {"unit": "V", "default": 0.0, "range": [-1, 1]}}, "quality": {},
        "provenance": {"sources": ["test"]},
    }
    data.update(changes)
    return data


def tree(tmp_path: Path, files: dict[str, Any]) -> RecipeRegistry:
    root = tmp_path / "recipes"
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return RecipeRegistry.load(root, repo_root=tmp_path)


def test_committed_tree_is_clean() -> None:
    registry = RecipeRegistry.load(RECIPES, repo_root=REPO_ROOT)
    assert registry.problems() == []
    assert {"mosfet.idvg", "mosfet.idvd", "generic.smu_staircase", "system.self_test", "system.self_cal"} \
        <= set(registry.ids())
    assert not (RECIPES / "reserved").exists() and not set(RETIRED_IDS) & set(registry.ids())
    assert set(V1_RESERVED_IDS) <= set(registry.ids())
    assert {registry.get(r).status for r in V1_RESERVED_IDS} == {"sim_validated"}


def test_committed_statuses() -> None:
    registry = RecipeRegistry.load(RECIPES, repo_root=REPO_ROOT)
    status = {r: tuple(registry.get(r).status if registry.runnable(r, b) else "not runnable" for b in ("sim", "visa"))
              for r in registry.ids()}
    assert status["mosfet.idvg"] == ("sim_validated", "sim_validated")
    assert status["generic.smu_staircase"] == ("sim_validated", "sim_validated")
    assert status["system.self_test"] == status["system.self_cal"] == ("sim_validated", "sim_validated")  # WP6.2
    # validated on the simulator by WP2.2 (tests/integration/test_recipes_*.py); smu_stepped has both code paths
    for recipe_id in ("mosfet.idvd", "mosfet.gate_leakage", "basic.contact_resistor", "basic.diode_iv",
                      "fefet.dual_sweep_mw"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
    # WP7.4: sampling recipes validated on the simulator (tests/integration/test_recipes_sampling.py)
    for recipe_id in ("generic.smu_sampling", "mosfet.id_t_sampling", "reliability.tddb_cvs"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
    assert registry.get("reliability.tddb_cvs").always_confirm == ["destructive"]
    # WP7.1: kind smu_spot (tests/integration/test_recipes_spot.py)
    for recipe_id in ("system.zero_check", "generic.smu_spot", "resistor.kelvin_4w"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "smu_spot"
    assert registry.get("mosfet.idvd").kind == "smu_stepped"
    # WP8.2: kind cmu_correction (tests/integration/test_recipes_cmu_correction.py); always physical_setup
    for recipe_id in CORRECTION_RECIPES:
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "cmu_correction"
        assert registry.get(recipe_id).always_confirm == ["physical_setup"]
    # WP8.3: kind cmu_measure (tests/integration/test_recipes_cv.py)
    for recipe_id in ("cmu.spot", "moscap.cv", "mosfet.cgc_cv", "mosfet.cgd_cv"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "cmu_measure" and registry.get(recipe_id).family == "cmu"
    # WP8.4: the C-V variants of kind cmu_measure (tests/integration/test_recipes_cv_variants.py)
    for recipe_id in ("moscap.cv_ac_level", "moscap.pulsed_cv", "moscap.cf", "moscap.ct", "fecap.cv_butterfly"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "cmu_measure"
    assert registry.get("fecap.cv_butterfly").family == "nvm"
    # WP8.5: QSCV (kind smu_qscv) and the multi-frequency C-V (tests/integration/test_recipes_qscv.py)
    assert status["moscap.qscv"] == status["moscap.cv_multi_freq"] == ("sim_validated", "sim_validated")
    assert (registry.get("moscap.qscv").kind, registry.get("moscap.cv_multi_freq").kind) == ("smu_qscv", "cmu_measure")
    # WP9.2: kind spgu_pulse, mode route_only (tests/integration/test_recipes_selector.py)
    assert status["system.selector_check"] == ("sim_validated", "sim_validated")
    assert registry.get("system.selector_check").kind == "spgu_pulse"
    # WP9.3: kind spgu_pulse, modes pg/alwg (tests/integration/test_recipes_spgu_pulse.py, ..._charge_pumping.py)
    for recipe_id in ("spgu.pulse_train", "spgu.alwg_sequence", "mosfet.charge_pumping"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "spgu_pulse" and registry.get(recipe_id).family == "spgu"
    # WP9.4: kind pulse_read (tests/integration/test_recipes_pulse_read.py); the generic one is always confirmed
    for recipe_id in ("fefet.pulse_write_read", "spgu.program_smu_read"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "pulse_read" and registry.get(recipe_id).family == "nvm"
    assert registry.get("spgu.program_smu_read").always_confirm == ["adhoc_recipe"]
    # WP9.5: the pulse_read schedules grid, cycles with checkpoints, retention (tests/integration/
    # test_recipes_nvm_schedules.py)
    for recipe_id in ("fefet.switching_kinetics", "fefet.endurance", "fefet.retention"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "pulse_read" and registry.get(recipe_id).family == "nvm"
    # WP7.6: kind stress_measure (tests/integration/test_recipes_stress.py); destructive, always confirmed
    for recipe_id in ("reliability.bti_sms", "igzo.bias_stress", "reliability.hci", "reliability.silc"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "stress_measure"
        assert registry.get(recipe_id).always_confirm == ["destructive"]
    # WP7.3: kind smu_pulsed (tests/integration/test_recipes_pulsed.py)
    for recipe_id in ("mosfet.idvg_pulsed", "mosfet.idvd_pulsed", "basic.pulsed_spot", "generic.smu_multi_pulsed"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "smu_pulsed"
    # WP7.5: kind smu_search (tests/integration/test_recipes_search.py); the breakdown recipes are destructive
    for recipe_id in ("mosfet.vth_search", "basic.breakdown_search", "dielectric.bdv"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "smu_search"
    assert registry.get("basic.breakdown_search").always_confirm == registry.get("dielectric.bdv").always_confirm \
        == ["destructive"]
    # WP10.7: wgfmu.fast_bti = kind stress_measure (WGFMU path); the WGFMU library self-test/cal = kind system
    # (tests/integration/test_recipes_fast_bti.py, test_recipes_wgfmu_system.py)
    assert status["wgfmu.fast_bti"] == ("sim_validated", "sim_validated")
    assert registry.get("wgfmu.fast_bti").kind == "stress_measure" and registry.get("wgfmu.fast_bti").family == \
        "reliability"
    assert registry.get("wgfmu.fast_bti").always_confirm == ["destructive"]
    for recipe_id, reason in (("system.wgfmu_self_test", "system_self_test"), ("system.wgfmu_self_cal",
                                                                             "system_self_cal")):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "system" and registry.get(recipe_id).always_confirm == [reason]
    # WP10.6: tests/integration/test_recipes_pund.py
    for recipe_id, kind in (("fecap.pund", "wgfmu_waveform"), ("fefet.fast_program_read", "wgfmu_waveform"),
                            ("fecap.endurance_pund", "pulse_read")):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == kind and registry.get(recipe_id).family == "nvm"
    # WP10.4: kind wgfmu_waveform (tests/integration/test_recipes_wgfmu.py)
    for recipe_id in WGFMU_RECIPES:
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
        assert registry.get(recipe_id).kind == "wgfmu_waveform" and registry.get(recipe_id).family == "wgfmu"
    cards = {"mosfet.idvg": "smu/mosfet-idvg", "mosfet.idvd": "smu/mosfet-idvd",
             "mosfet.gate_leakage": "smu/gate-leakage", "basic.contact_resistor": "smu/contact-resistor-check",
             "basic.diode_iv": "smu/diode-iv", "fefet.dual_sweep_mw": "nvm/fefet-dual-sweep-mw",
             "system.self_test": "system/self-test-cal", "system.self_cal": "system/self-test-cal",
             "generic.smu_sampling": "smu/smu-sampling", "mosfet.id_t_sampling": "smu/smu-sampling",
             "reliability.tddb_cvs": "reliability/tddb-bdv",  # WP7.4
             "basic.iv_force_i": "smu/diode-iv", "mosfet.idvg_family": "smu/mosfet-idvg",
             "mosfet.idvg_sync": "smu/mosfet-idvg", "mosfet.body_effect": "smu/mosfet-idvg",
             "generic.smu_multi_sweep": "smu/smu-spot-kelvin",  # WP7.2
             "system.zero_check": "system/zero-check", "generic.smu_spot": "smu/smu-spot-kelvin",
             "resistor.kelvin_4w": "smu/smu-spot-kelvin",  # WP7.1
             "reliability.bti_sms": "reliability/bti-stress-measure",
             "igzo.bias_stress": "reliability/igzo-bias-stress",
             "reliability.hci": "reliability/hci-silc", "reliability.silc": "reliability/hci-silc",  # WP7.6
             **{r: "cmu/cmu-correction" for r in CORRECTION_RECIPES},  # WP8.2
         "system.selector_check": "spgu/selector-check",  # WP9.2
         "mosfet.idvg_pulsed": "smu/smu-pulsed-iv", "mosfet.idvd_pulsed": "smu/smu-pulsed-iv",
         "basic.pulsed_spot": "smu/smu-pulsed-iv", "generic.smu_multi_pulsed": "smu/smu-pulsed-iv",  # WP7.3
         "spgu.pulse_train": "spgu/spgu-pulse-train", "spgu.alwg_sequence": "spgu/spgu-pulse-train",
         "mosfet.charge_pumping": "spgu/charge-pumping",  # WP9.3
         "mosfet.vth_search": "smu/smu-search", "basic.breakdown_search": "reliability/tddb-bdv",
         "dielectric.bdv": "reliability/tddb-bdv",  # WP7.5
         "cmu.spot": "cmu/cmu-spot", "moscap.cv": "cmu/moscap-cv", "mosfet.cgc_cv": "cmu/mosfet-split-cv",
         "mosfet.cgd_cv": "cmu/mosfet-split-cv",  # WP8.3
         "fefet.pulse_write_read": "nvm/fefet-pulse-write-read",
         "spgu.program_smu_read": "nvm/fefet-pulse-write-read",  # WP9.4
         "moscap.cv_ac_level": "cmu/moscap-cv", "moscap.pulsed_cv": "cmu/moscap-cv", "moscap.cf": "cmu/moscap-cf-ct",
         "moscap.ct": "cmu/moscap-cf-ct", "fecap.cv_butterfly": "nvm/fecap-cv-butterfly",  # WP8.4 (WP10.6 split)
         **{r: "wgfmu/wgfmu-pulsed-iv" for r in ("wgfmu.pulsed_iv", "wgfmu.fast_iv", "wgfmu.pulse_train")},
         "wgfmu.custom_waveform": "wgfmu/wgfmu-custom-waveform",
         "wgfmu.dc_spot": "wgfmu/wgfmu-custom-waveform",  # WP10.4
         "fefet.switching_kinetics": "nvm/fefet-switching-kinetics",
         "fefet.endurance": "nvm/fefet-endurance-retention",
         "fefet.retention": "nvm/fefet-endurance-retention",  # WP9.5
         "moscap.qscv": "cmu/moscap-dit", "moscap.cv_multi_freq": "cmu/moscap-dit",  # WP8.5
         "wgfmu.rtn": "wgfmu/wgfmu-rtn-noise", "wgfmu.lfn": "wgfmu/wgfmu-rtn-noise",  # WP10.5
         "wgfmu.fast_bti": "reliability/bti-stress-measure", "system.wgfmu_self_test": "system/self-test-cal",
         "system.wgfmu_self_cal": "system/self-test-cal",  # WP10.7
         "fecap.pund": "nvm/fecap-pund", "fecap.endurance_pund": "nvm/fecap-pund",
         "fefet.fast_program_read": "nvm/fefet-pulse-write-read"}  # WP10.6
    # WP2.5: the six first test cards; WP5.10: family folders + the system card; WP7.2: the sweep recipes
    for recipe_id in ("basic.iv_force_i", "mosfet.idvg_family", "mosfet.idvg_sync", "mosfet.body_effect",
                      "generic.smu_multi_sweep"):
        assert status[recipe_id] == ("sim_validated", "sim_validated"), recipe_id
    for recipe_id in registry.ids():
        expected = f".agents/skills/b1500-test/cards/{cards[recipe_id]}.md" if recipe_id in cards else None
        assert registry.get(recipe_id).card == expected, recipe_id
    assert registry.get("system.self_test").always_confirm == ["system_self_test"]
    assert registry.get("system.self_cal").always_confirm == ["system_self_cal"]


def test_kinds() -> None:
    kinds = default_kinds()
    assert kinds["smu_staircase"].implemented_on == {"sim", "visa"}
    assert kinds["smu_stepped"].implemented_on == {"sim", "visa"}
    assert kinds["system"].implemented_on == {"sim", "visa"}  # WP6.2: self-test/cal on hardware
    assert kinds["smu_sampling"].implemented_on == {"sim", "visa"}
    assert kinds["smu_spot"].implemented_on == {"sim", "visa"}  # WP7.1
    assert kinds["cmu_correction"].implemented_on == {"sim", "visa"}
    assert kinds["stress_measure"].implemented_on == {"sim", "visa"} and "smu_stress_measure" not in kinds  # WP7.6
    assert kinds["smu_pulsed"].implemented_on == {"sim", "visa"}  # WP7.3
    assert kinds["cmu_measure"].implemented_on == {"sim", "visa"} and "cmu_cv" not in kinds  # WP8.3 replaced cmu_cv
    assert kinds["pulse_read"].implemented_on == {"sim", "visa"} and "spgu_program_read" not in kinds  # WP9.4
    assert kinds["smu_qscv"].implemented_on == {"sim", "visa"}  # WP8.5
    assert kinds["wgfmu_waveform"].implemented_on == {"sim", "visa"} and "wgfmu_pulsed_iv" not in kinds  # WP10.4
    assert "wgfmu_fast_bti" not in kinds  # WP10.7: wgfmu.fast_bti runs in stress_measure (WGFMU path)
    # WP11.2: the 14 kinds of blueprint v2 2.7, each with both code paths; the declared-only wgfmu_pulse_sequence is
    # retired (no blueprint v2 3 recipe names it: PUND runs in wgfmu_waveform, WGFMU program/read in pulse_read)
    assert len(kinds) == 14 and "wgfmu_pulse_sequence" not in kinds
    assert all(kind.implemented_on == {"sim", "visa"} for kind in kinds.values())


@pytest.mark.parametrize(("files", "expected"), [
    ({"basic/thing.yaml": "id: [unclosed"}, "not valid UTF-8 YAML"),
    ({"basic/thing.yaml": "- a list"}, "top level must be a mapping"),
    ({"basic/thing.yaml": minimal(sha256="0" * 64)}, "sha256 is computed at load"),
    ({"basic/thing.yaml": minimal(version=0)}, "version"),
    ({"basic/thing.yaml": minimal(kind="warp_drive")}, "unknown kind 'warp_drive'"),
    ({"basic/thing.yaml": minimal(card="cards/missing.md")}, "dangling card path"),
    ({"basic/thing.yaml": minimal(card="../outside.md")}, "repository-relative"),
    ({"basic/thing.yaml": minimal(analysis_defaults=[{"method": "magic"}])}, "unknown analysis method 'magic'"),
    ({"basic/thing.yaml": minimal(analysis_defaults=[{"method": "memory_window"}])}, "does not apply"),
    ({"basic/thing.yaml": minimal("generic.x", analysis_defaults=[
        {"method": "vth_linear_extrapolation", "options": {"bogus": 1}}])}, "no option(s) ['bogus']"),
    ({"basic/thing.yaml": minimal(params={})}, "reference undeclared parameters ['a']"),
    ({"basic/thing.yaml": minimal("basic.other")}, "does not match its file name (expected basic.thing)"),
    ({"basic/thing.yaml": minimal(), "basic/thing2.yaml": minimal()}, "duplicate recipe id basic.thing"),
    ({"reserved/x.y.yaml": minimal("x.y")}, "does not match its file name (expected reserved.x.y)"),
    ({"basic/thing.yaml": minimal(status="not" + "_implemented")}, "status"),  # the retired status (WP11.2)
    ({"basic/thing.yaml": minimal(preconditions=["a"])}, "preconditions"),  # the reserved slots' field is gone
])
def test_problems_are_reported(tmp_path: Path, files: dict[str, Any], expected: str) -> None:
    problems = tree(tmp_path, files).problems()
    assert any(expected in p for p in problems), problems
    assert all(p.startswith("recipes/") for p in problems)


def test_a_bad_file_does_not_hide_the_good_ones(tmp_path: Path) -> None:
    registry = tree(tmp_path, {"basic/thing.yaml": minimal(), "basic/broken.yaml": minimal("basic.broken", kind=1)})
    assert registry.ids() == ["basic.thing"] and len(registry.problems()) == 1
    with pytest.raises(UnknownRecipeError, match="known: basic.thing"):
        registry.get("basic.broken")


class SimOnlyKind:
    """A registered kind with a simulator code path only (a kind under development; R-REC-01 blocks it on visa)."""

    kind_id = "sim_only"
    implemented_on = frozenset({"sim"})

    def compile(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - never compiled here
        raise AssertionError("not compiled in these tests")

    def acquire(self, *args: Any) -> Any:  # pragma: no cover
        raise AssertionError("not run in these tests")

    def to_table(self, *args: Any) -> None:  # pragma: no cover
        return None


def test_existing_card_and_listing(tmp_path: Path) -> None:
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.md").write_text("card", encoding="utf-8")
    files = {
        "basic/thing.yaml": minimal(card="cards/c.md", device_types=["nmos"]),
        "basic/other.yaml": minimal("basic.other", device_types=["diode"]),
        "generic/any.yaml": minimal("generic.any"),
        "basic/later.yaml": minimal("basic.later", kind="sim_only"),
    }
    tree(tmp_path, files)
    registry = RecipeRegistry.load(tmp_path / "recipes", {**default_kinds(), "sim_only": SimOnlyKind()},
                                   repo_root=tmp_path)
    assert registry.problems() == []
    # recipes without device types (basic.later, generic.any) match every device type
    assert [s.id for s in registry.list(device_type="nmos")] == ["basic.later", "basic.thing", "generic.any"]
    listing = {s.id: s for s in registry.list()}
    assert listing["basic.thing"].card == "cards/c.md" and listing["basic.later"].status == "draft"
    assert registry.runnable("basic.later", "sim") and not registry.runnable("basic.later", "visa")
    assert registry.runnable("basic.thing", "visa")
    assert registry.source("basic.thing") == "recipes/basic/thing.yaml"
    unknown = tree(tmp_path / "other", {"basic/thing.yaml": minimal(kind="warp_drive")})
    assert not unknown.runnable("basic.thing", "sim") and unknown.problems()  # an unknown kind runs nowhere


def test_reload_if_changed(tmp_path: Path) -> None:
    root = tmp_path / "recipes"
    shutil.copytree(RECIPES, root)
    registry = RecipeRegistry.load(root, repo_root=REPO_ROOT)
    assert registry.reload_if_changed() is registry
    path = root / "mosfet" / "idvg.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# edit\n", encoding="utf-8")
    fresh = registry.reload_if_changed()
    assert fresh is not registry and fresh.get("mosfet.idvg").sha256 != registry.get("mosfet.idvg").sha256
