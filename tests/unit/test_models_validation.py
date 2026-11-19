"""Bring-up stage and validation-record models (``models/validation.py``, WP6.3): tolerances, stage frontmatter,
record invariants (hardware runs only, reviewed records dated), the definition digest and the template keys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from b1500_test_agent.catalog.schema import parse_recipe
from b1500_test_agent.models.validation import (
    RECORD_KEYS,
    STAGE_ORDER,
    STAGES,
    StageCheck,
    StageFrontmatter,
    Tolerance,
    ValidationRecord,
    recipe_definition_sha256,
    reviewed_record_problems,
    stage_file_name,
    stage_index,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".agents" / "skills" / "b1500-bringup" / "records" / "_TEMPLATE.yaml"
H = "H20261201T093012Z-1a2b"
DIGEST = "a" * 64


@pytest.mark.parametrize("tolerance, value, reference, expected", [
    ({"rel": 0.01}, 100.9, 100.0, True), ({"rel": 0.01}, 101.1, 100.0, False), ({"rel": 0.01}, 100.0, None, None),
    ({"absolute": 0.010}, 0.459, 0.450, True), ({"absolute": 0.010}, 0.461, 0.450, False),
    ({"factor": 2}, 3e-12, 2e-12, True), ({"factor": 2}, 5e-12, 2e-12, False), ({"factor": 2}, -3e-12, 2e-12, False),
    ({"max_abs": 0.5}, 0, None, True), ({"max_abs": 0.5}, 4, None, False), ({"max_abs": 0.5}, None, None, None),
])  # fmt: skip
def test_tolerance(tolerance: dict[str, float], value: float | None, reference: float | None,
                   expected: bool | None) -> None:
    assert Tolerance(**tolerance).check(value, reference) is expected


@pytest.mark.parametrize("data", [{}, {"rel": 0.01, "absolute": 0.1}, {"rel": -1}, {"factor": 1.0}])
def test_tolerance_needs_exactly_one_positive_bound(data: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Tolerance(**data)


def _check(**changes: Any) -> dict[str, Any]:
    return {"id": "vth", "recipe": "mosfet.idvg", "quantity": "vth", "reference": "EasyEXPERT", "text": "+-10 mV",
            **changes}


def test_stage_frontmatter_rules() -> None:
    front = StageFrontmatter(stage="L4", title="t", recipes=["mosfet.idvg"], checks=[_check()], version=1)
    assert front.record_keys() == ["mosfet.idvg"]
    with pytest.raises(ValidationError, match="checks name recipes the stage does not run"):
        StageFrontmatter(stage="L4", title="t", recipes=[], checks=[_check()], version=1)
    with pytest.raises(ValidationError, match="unique"):
        StageFrontmatter(stage="L4", title="t", recipes=["mosfet.idvg"], checks=[_check(), _check()], version=1)
    stage_level = StageFrontmatter(stage="L1", title="t", recipes=[], checks=[_check(recipe=None)], version=1)
    assert stage_level.record_keys() == [None] and stage_level.checks_for(None)[0].id == "vth"
    assert StageFrontmatter(stage="S0", title="t", recipes=[], version=1).record_keys() == [None]
    with pytest.raises(ValidationError):
        StageCheck(**_check(quantity="no spaces"))


def test_stage_table() -> None:
    assert STAGE_ORDER == tuple(STAGES) and STAGE_ORDER[0] == "S0" and STAGE_ORDER[-1] == "L10"
    assert stage_file_name("L4") == "l4-mosfet.md" and stage_index("L10") == 11


def _record(**changes: Any) -> dict[str, Any]:
    return {"stage": "L2", "recipe_id": "basic.contact_resistor", "recipe_version": 1, "recipe_sha256": DIGEST,
            "runs": [H], **changes}


def test_records_hold_hardware_runs_only() -> None:
    assert ValidationRecord(**_record()).backend == "visa"
    with pytest.raises(ValidationError, match="simulator runs are never recorded"):
        ValidationRecord(**_record(runs=["S20261201T093012Z-1a2b"]))
    with pytest.raises(ValidationError):
        ValidationRecord(**_record(backend="sim"))


def test_record_invariants() -> None:
    with pytest.raises(ValidationError, match="a recipe record gives recipe_id, recipe_version and recipe_sha256"):
        ValidationRecord(**_record(recipe_sha256=None))
    with pytest.raises(ValidationError, match="reviewed_on"):
        ValidationRecord(**_record(reviewer="someone"))
    stage = ValidationRecord(stage="L0", runs=[])
    assert stage.key == "stage-l0" and stage.file_name() == "stage-l0.yaml"
    reviewed = ValidationRecord(**_record(reviewer="r", reviewed_on="2026-12-02", result="pass"))
    assert reviewed.reviewed and reviewed_record_problems(reviewed, "basic.contact_resistor.yaml") == []
    draft = ValidationRecord(**_record())
    problems = reviewed_record_problems(draft, "x.yaml")
    assert len(problems) == 3 and "named basic.contact_resistor.yaml" in problems[0]


def test_definition_digest_ignores_status_provenance_card_and_comments() -> None:
    raw = (ROOT / "recipes" / "mosfet" / "idvg.yaml").read_text(encoding="utf-8")
    base = recipe_definition_sha256(parse_recipe(raw.encode(), source="x"))
    promoted = ("# promoted\n" + raw).replace("status: sim_validated", "status: hw_validated").replace(
        "validation_runs: []", f"validation_runs: [{H}]").replace(
        "card: .agents/skills/b1500-test/cards/smu/mosfet-idvg.md", "card: null")
    assert recipe_definition_sha256(parse_recipe(promoted.encode(), source="x")) == base
    changed = raw.replace("default: 0.05", "default: 0.1", 1)
    assert changed != raw and recipe_definition_sha256(parse_recipe(changed.encode(), source="x")) != base


def test_template_keys_are_the_record_fields() -> None:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert tuple(data) == RECORD_KEYS
    assert data["reviewer"] == "" and data["runs"] == [] and data["backend"] == "visa"
