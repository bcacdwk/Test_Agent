"""``RecipeRegistry`` (blueprint 2.6): the committed tree is clean; every problem class is reported; effective
status and listing."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.catalog.kinds import UNIMPLEMENTED_KINDS, default_kinds
from b1500_test_agent.catalog.registry import RecipeRegistry, UnknownRecipeError
from tests.unit.helpers import REPO_ROOT

RECIPES = REPO_ROOT / "recipes"
RESERVED_SLOTS = {"wgfmu.pulsed_iv", "wgfmu.fast_bti", "spgu.program_smu_read", "fefet.pulse_write_read",
                  "fecap.pund", "reliability.bti_sms", "reliability.hci", "reliability.tddb_cvs", "cmu.correction",
                  "moscap.cv", "moscap.qscv", "hspice.compare", "mosfet.cgd_cv"}


def minimal(recipe_id: str = "basic.thing", **changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": recipe_id, "version": 1, "title": "t", "kind": "smu_staircase", "status": "draft", "card": None,
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
    reserved = {r for r in registry.ids() if registry.entry(r).source.startswith("recipes/reserved/")}
    assert reserved == RESERVED_SLOTS
    for recipe_id in reserved:
        recipe = registry.get(recipe_id)
        assert recipe.status == "not_implemented" and recipe.preconditions
        assert registry.kinds[recipe.kind].implemented_on == frozenset()


def test_committed_statuses() -> None:
    registry = RecipeRegistry.load(RECIPES, repo_root=REPO_ROOT)
    status = {r: (registry.effective_status(r, "sim"), registry.effective_status(r, "visa")) for r in registry.ids()}
    assert status["mosfet.idvg"] == ("sim_validated", "sim_validated")
    assert status["generic.smu_staircase"] == ("sim_validated", "sim_validated")
    assert status["system.self_test"] == status["system.self_cal"] == ("sim_validated", "not_implemented")
    assert status["mosfet.idvd"] == ("draft", "draft")  # smu_stepped has sim and visa code paths (WP2.1)
    assert registry.get("mosfet.idvd").kind == "smu_stepped" and registry.get("mosfet.idvd").status == "draft"
    assert registry.get("mosfet.idvg").card is None
    assert registry.get("system.self_test").always_confirm == ["system_self_test"]
    assert registry.get("system.self_cal").always_confirm == ["system_self_cal"]


def test_kinds() -> None:
    kinds = default_kinds()
    assert kinds["smu_staircase"].implemented_on == {"sim", "visa"}
    assert kinds["smu_stepped"].implemented_on == {"sim", "visa"} and "smu_stepped" not in UNIMPLEMENTED_KINDS
    assert kinds["system"].implemented_on == {"sim"}
    for kind_id in ("smu_spot", "smu_sampling", "smu_pulsed", "wgfmu_pulsed_iv", "spgu_program_read", "cmu_cv"):
        assert kind_id in UNIMPLEMENTED_KINDS and kinds[kind_id].implemented_on == frozenset()


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
    ({"reserved/x.y.yaml": minimal("x.y", kind="cmu_cv")}, "must be not_implemented"),
    ({"reserved/x.y.yaml": minimal("x.y", kind="cmu_cv", status="not_implemented")}, "preconditions"),
    ({"reserved/x.z.yaml": minimal("x.y", kind="cmu_cv", status="not_implemented", preconditions=["a"])},
     "reserved/x.y.yaml"),
    ({"basic/thing.yaml": minimal(kind="cmu_cv", status="sim_validated")}, "no simulator code path"),
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


def test_existing_card_and_listing(tmp_path: Path) -> None:
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.md").write_text("card", encoding="utf-8")
    registry = tree(tmp_path, {
        "basic/thing.yaml": minimal(card="cards/c.md", device_types=["nmos"]),
        "basic/other.yaml": minimal("basic.other", device_types=["diode"]),
        "generic/any.yaml": minimal("generic.any"),
        "basic/later.yaml": minimal("basic.later", kind="smu_spot"),
    })
    assert registry.problems() == []
    # recipes without device types (basic.later, generic.any) match every device type
    assert [s.id for s in registry.list(device_type="nmos")] == ["basic.later", "basic.thing", "generic.any"]
    listing = {s.id: s for s in registry.list(backend="visa")}
    assert listing["basic.thing"].card == "cards/c.md" and listing["basic.later"].status == "not_implemented"
    assert registry.source("basic.thing") == "recipes/basic/thing.yaml"


def test_reload_if_changed(tmp_path: Path) -> None:
    root = tmp_path / "recipes"
    shutil.copytree(RECIPES, root)
    registry = RecipeRegistry.load(root, repo_root=REPO_ROOT)
    assert registry.reload_if_changed() is registry
    path = root / "mosfet" / "idvg.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# edit\n", encoding="utf-8")
    fresh = registry.reload_if_changed()
    assert fresh is not registry and fresh.get("mosfet.idvg").sha256 != registry.get("mosfet.idvg").sha256
