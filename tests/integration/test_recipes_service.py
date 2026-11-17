"""The five WP2.2 recipes through ``B1500Service`` (the MCP/CLI path): validate → run → analyze on their scenarios,
run responses within the 2k-token budget of blueprint 5.1 (the default analyses travel in ``run_plan``), the
``analyze_run`` messages of the classifying methods, and ``plot_iv`` storing PNGs under the run folder's
``plots/`` through the archive."""

from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.devtools import budget
from b1500_test_agent.service import RESPONSE_TOKEN_BUDGET
from tests.integration.helpers import REPO_ROOT, World, plan, run

CASES = [
    ("resistor_100k", {"recipe_id": "basic.contact_resistor", "pin_map": "resistor-2t",
                       "dut_profile": "resistor-generic"}, "resistance"),
    ("diode_basic", {"recipe_id": "basic.diode_iv", "pin_map": "diode-2t", "dut_profile": "diode-generic"},
     "diode_fit"),
    ("nmos_basic", {"recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"},
     "output_metrics"),
    ("nmos_basic", {"recipe_id": "mosfet.gate_leakage", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"},
     "leakage_at"),
    ("fefet_basic", {"recipe_id": "fefet.dual_sweep_mw", "pin_map": "mosfet-4t", "dut_profile": "fefet-generic"},
     "memory_window"),
]


@pytest.fixture(scope="module")
def counter() -> budget.TokenCounter:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        found = budget.load_counter()
    if not found.method.startswith("tiktoken"):
        pytest.skip("o200k_base is not available offline; the chars/3.5 fallback overcounts JSON numbers")
    return found


def tokens(counter: budget.TokenCounter, result: object) -> int:
    payload = result.model_dump(mode="json")  # type: ignore[attr-defined]
    return counter.count(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


@pytest.mark.parametrize(("scenario", "request_", "method"), CASES, ids=[c[1]["recipe_id"] for c in CASES])
def test_recipe_runs_through_the_service_within_the_response_budget(
        world: World, counter: budget.TokenCounter, scenario: str, request_: dict[str, str], method: str) -> None:
    world.use_scenario(scenario)
    service = world.service(adapter="mcp")
    planned = service.validate_plan(**request_)
    assert planned.ok and planned.tier == "ok", planned.message
    result = service.run_plan(planned.plan_id)  # type: ignore[arg-type]
    assert result.ok and result.outcome == "completed", result.message
    assert result.analyses and {a.method for a in result.analyses} <= {method, "leakage_at"}
    assert tokens(counter, result) <= RESPONSE_TOKEN_BUDGET
    again = service.analyze_run(result.run_id, method)  # type: ignore[arg-type]
    assert again.ok and again.status == "ok" and "SIMULATED" in again.message, again.message
    assert tokens(counter, again) <= RESPONSE_TOKEN_BUDGET


def test_classifying_methods_state_bounds_and_verdicts(world: World) -> None:
    world.use_scenario("gd_short")
    service = world.service(adapter="mcp")
    planned = service.validate_plan(recipe_id="mosfet.gate_leakage", pin_map="mosfet-4t", dut_profile="nmos-generic")
    ran = service.run_plan(planned.plan_id)  # type: ignore[arg-type]
    assert ran.ok and ran.outcome == "completed_with_flags"
    leak = service.analyze_run(ran.run_id, "leakage_at", {"v": 2.0})  # type: ignore[arg-type]
    assert leak.ok and leak.message.startswith("leakage >= 1e-07 A (fail)"), leak.message


def test_plot_iv_stores_pngs_in_the_run_folder(world: World) -> None:
    world.use_scenario("nmos_basic")
    service = world.service(adapter="mcp")
    planned = service.validate_plan(recipe_id="mosfet.idvd", pin_map="mosfet-4t", dut_profile="nmos-generic")
    ran = service.run_plan(planned.plan_id)  # type: ignore[arg-type]
    folder = world.run_dirs()[0]
    manifest_before = (folder / "manifest.json").read_bytes()
    first = service.analyze_run(ran.run_id, "plot_iv")  # type: ignore[arg-type]
    assert first.ok and first.status == "ok" and len(first.plots) == 2, first.message
    assert sorted(p.name for p in (folder / "plots").iterdir()) == ["iv-linear-1.png", "iv-log-1.png"]
    assert all((folder / "plots" / name).read_bytes().startswith(b"\x89PNG") for name in ("iv-linear-1.png",
                                                                                          "iv-log-1.png"))
    record = json.loads((folder / "analysis" / "plot_iv-1.json").read_text(encoding="utf-8"))
    assert record["outcome"] == "ok" and record["plots"] == ["plots/iv-linear-1.png", "plots/iv-log-1.png"]
    assert record["x"] == "drain_V" and record["y"] == ["drain_I", "gate_I"]
    second = service.analyze_run(ran.run_id, "plot_iv", {"scale": "log"})  # type: ignore[arg-type]
    assert second.ok and [p.rsplit("/", 1)[-1] for p in second.plots] == ["iv-log-2.png"]  # never overwritten
    assert (folder / "manifest.json").read_bytes() == manifest_before
    refused = service.analyze_run(ran.run_id, "plot_iv", {"out_dir": "/tmp"})  # type: ignore[arg-type]
    assert not refused.ok and refused.error_code == "invalid_input"


def test_plot_iv_as_a_default_analysis_is_stored_before_the_manifest(world: World, tmp_path: Path) -> None:
    """A recipe may list plot_iv in analysis_defaults: the executor stores the PNGs through the archive before
    finalizing, so the manifest hashes them."""
    recipes = tmp_path / "recipes"
    shutil.copytree(REPO_ROOT / "recipes", recipes)
    path = recipes / "basic" / "contact_resistor.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["analysis_defaults"].append({"method": "plot_iv", "options": {"scale": "linear"}})
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    world.recipes = recipes
    world.use_scenario("resistor_100k")
    executor = world.executor()
    result = run(executor, plan(executor, recipe_id="basic.contact_resistor", pin_map="resistor-2t",
                                dut_profile="resistor-generic").plan_id)
    assert result.ok and result.outcome == "completed", result.message
    manifest = json.loads((world.run_dirs()[0] / "manifest.json").read_text(encoding="utf-8"))
    assert "plots/iv-linear-1.png" in manifest["files"] and "analysis/plot_iv-1.json" in manifest["files"]
