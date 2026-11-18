"""Golden FLEX previews of the nine v1 runnable recipes (WP5.2, blueprint 10.1 row 5.2).

Each ``tests/fixtures/plans/v1_<recipe_id>.json`` pins the exact FLEX preview (``PlanRecord.flex_preview``: every
setup and trigger write ``acquire`` sends, in order) that the v1 code compiled for one request on its v1 simulator
scenario: the card example plan for the six carded recipes, the recipe defaults for ``generic.smu_staircase`` (on a
test-written ``generic-3t`` pin map, as in ``test_executor_recipes.py``) and for ``system.self_test``/``self_cal``.
The test plans each request again in a hermetic world (temporary config and data, simulator only) and asserts that
the rendered JSON is byte-identical to the committed file, so package splits and later refactors cannot change
what reaches the instrument unnoticed.

The fixtures were written from the v1 code (base ``e71245e``) before the WP5.2 split. Regenerate them only for an
intended FLEX change, and say why in ``docs/design/progress.md``:
``uv run python -m tests.integration.test_plan_goldens --write``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.models.plan import PlanRequest
from tests.integration.helpers import REPO_ROOT, World, make_world

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "plans"

GENERIC_3T: dict[str, Any] = {
    "pinmaps/generic-3t.yaml": {"certainty": "verified", "terminals": {"sweep": 3, "bias": 4, "ground": "GNDU"}},
    "duts/generic-3t.yaml": {"device_type": "nmos", "terminals": {
        "sweep": {"max_abs_v": 2.0, "max_abs_i": 1e-3}, "bias": {"max_abs_v": 2.0, "max_abs_i": 1e-3},
        "ground": {"max_abs_v": 0.0, "max_abs_i": 1e-2}}},
}
"""Test-only pin map and DUT profile naming the generic recipe's terminals (no committed example has them)."""

CASES: list[dict[str, Any]] = [
    {"recipe_id": "basic.contact_resistor", "scenario": "resistor_100k", "source": "card contact-resistor-check",
     "request": {"params": {}, "pin_map": "resistor-2t", "dut_profile": "resistor-generic"}},
    {"recipe_id": "basic.diode_iv", "scenario": "diode_basic", "source": "card diode-iv",
     "request": {"params": {}, "pin_map": "diode-2t", "dut_profile": "diode-generic"}},
    {"recipe_id": "mosfet.idvg", "scenario": "nmos_basic", "source": "card mosfet-idvg",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "mosfet.idvd", "scenario": "nmos_basic", "source": "card mosfet-idvd",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "mosfet.gate_leakage", "scenario": "nmos_basic", "source": "card gate-leakage",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "fefet.dual_sweep_mw", "scenario": "fefet_basic", "source": "card fefet-dual-sweep-mw",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "fefet-generic"}},
    {"recipe_id": "generic.smu_staircase", "scenario": "nmos_basic", "source": "recipe defaults",
     "request": {"params": {}, "pin_map": "generic-3t", "dut_profile": "generic-3t"}, "config": GENERIC_3T},
    {"recipe_id": "system.self_test", "scenario": "nmos_basic", "source": "recipe defaults",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": None}},
    {"recipe_id": "system.self_cal", "scenario": "nmos_basic", "source": "recipe defaults",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": None}},
]


def fixture_path(recipe_id: str) -> Path:
    return FIXTURES / f"v1_{recipe_id}.json"


def compute(case: dict[str, Any], world: World) -> dict[str, Any]:
    """Plan ``case`` in ``world`` (no instrument I/O) and return the golden document."""
    world.use_scenario(case["scenario"])
    for rel, data in case.get("config", {}).items():
        world.write_config(rel, data)
    executor = world.executor()
    try:
        record = executor.plan(PlanRequest.model_validate({"recipe_id": case["recipe_id"], **case["request"]}))
    finally:
        executor.close()
    return {
        "recipe_id": case["recipe_id"],
        "source": case["source"],
        "scenario": case["scenario"],
        "request": case["request"],
        "config": case.get("config", {}),
        "kind": record.kind,
        "flex_preview": list(record.flex_preview),
    }


def render(document: dict[str, Any]) -> bytes:
    """Canonical bytes of a golden document: 2-space JSON, ASCII, LF line ends, one trailing newline."""
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


@pytest.mark.parametrize("case", CASES, ids=[c["recipe_id"] for c in CASES])
def test_flex_preview_is_byte_identical_to_the_v1_golden(case: dict[str, Any], tmp_path: Path) -> None:
    golden = fixture_path(case["recipe_id"]).read_bytes()
    assert render(compute(case, make_world(tmp_path))) == golden


def test_goldens_cover_exactly_the_nine_v1_runnable_recipes() -> None:
    expected = {fixture_path(c["recipe_id"]).name for c in CASES}
    assert len(expected) == 9
    assert {p.name for p in FIXTURES.glob("v1_*.json")} == expected


def test_goldens_are_non_trivial() -> None:
    previews = {c["recipe_id"]: json.loads(fixture_path(c["recipe_id"]).read_text(encoding="utf-8"))["flex_preview"]
                for c in CASES}
    assert previews["system.self_test"] == ["*TST?"] and previews["system.self_cal"] == ["*CAL?"]
    for recipe_id, preview in previews.items():
        if not recipe_id.startswith("system."):
            assert preview[0].startswith("FMT ") and preview[-1] == "XE" and any(p.startswith("WV ") for p in preview)


def write_goldens() -> None:
    """Regenerate every golden file from the current code (intended FLEX changes only)."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="b1500-golden-", ignore_cleanup_errors=True) as tmp:
            fixture_path(case["recipe_id"]).write_bytes(render(compute(case, make_world(Path(tmp)))))
            print(f"wrote {fixture_path(case['recipe_id']).relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python -m tests.integration.test_plan_goldens --write")
    write_goldens()
