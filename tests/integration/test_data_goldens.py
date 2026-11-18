"""Golden ``data.csv`` of every v1 measurement recipe (WP5.7, blueprint v2 10.1 row 5.7: "v1 ``data.csv``
byte-identical").

The v2 data contract (``analysis/dataset.py``: optional columns, ``data.npz`` + ``preview.csv`` above 200k rows,
``partial.csv``) must not change one byte of what the v1 recipes archive. Each
``tests/fixtures/tables/v1_<recipe_id>.csv`` is the ``data.csv`` that the v1 writer (base ``0c191cd``, before any
WP5.7 change) archived for the request of the matching FLEX golden (``test_plan_goldens.CASES``) on its simulator
scenario in a fresh hermetic world. The test runs the same request through the executor again and compares the
archived file byte for byte; it also round-trips each golden through the v2 reader and writer.

The simulator is deterministic (seeded noise per measurement, six significant digits in the ASCII data), so the
bytes depend only on the code. ``system.*`` recipes archive no table and are not part of this check. Regenerate only
for an intended data change and say why in ``docs/design/progress.md``:
``uv run python -m tests.integration.test_data_goldens --write``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE, read_table, write_table
from b1500_test_agent.models.plan import PlanRequest
from tests.integration.helpers import REPO_ROOT, World, make_world, run
from tests.integration.test_plan_goldens import CASES as PLAN_CASES

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "tables"
CASES: list[dict[str, Any]] = [c for c in PLAN_CASES if not c["recipe_id"].startswith("system.")]
"""The seven v1 measurement recipes, with the request and scenario of their FLEX golden."""


def fixture_path(recipe_id: str) -> Path:
    return FIXTURES / f"v1_{recipe_id}.csv"


def archived_table(case: dict[str, Any], world: World) -> bytes:
    """Plan and run ``case`` in ``world`` (confirming when the tier asks) and return the archived ``data.csv``."""
    world.use_scenario(case["scenario"])
    for rel, data in case.get("config", {}).items():
        world.write_config(rel, data)
    executor = world.executor()
    try:
        record = executor.plan(PlanRequest.model_validate({"recipe_id": case["recipe_id"], **case["request"]}))
        assert record.tier != "blocked", record.findings
        summary = record.summary if record.tier == "needs_confirmation" else None
        result = run(executor, record.plan_id, summary)
    finally:
        executor.close()
    assert result.ok, result.message
    assert result.run_id is not None
    (run_dir,) = world.run_dirs()
    return (run_dir / DATA_FILE).read_bytes()


@pytest.mark.parametrize("case", CASES, ids=[c["recipe_id"] for c in CASES])
def test_v1_data_csv_is_byte_identical_to_the_golden(case: dict[str, Any], tmp_path: Path) -> None:
    golden = fixture_path(case["recipe_id"]).read_bytes()
    assert archived_table(case, make_world(tmp_path)) == golden


@pytest.mark.parametrize("case", CASES, ids=[c["recipe_id"] for c in CASES])
def test_v1_golden_round_trips_through_the_v2_reader_and_writer(case: dict[str, Any], tmp_path: Path) -> None:
    source = fixture_path(case["recipe_id"])
    target = write_table(read_table(source), tmp_path / DATA_FILE)
    assert target.name == DATA_FILE
    assert target.read_bytes() == source.read_bytes()


def test_goldens_cover_exactly_the_seven_v1_measurement_recipes() -> None:
    expected = {fixture_path(c["recipe_id"]).name for c in CASES}
    assert len(expected) == 7
    assert {p.name for p in FIXTURES.glob("v1_*.csv")} == expected


def test_goldens_are_non_trivial() -> None:
    for case in CASES:
        lines = fixture_path(case["recipe_id"]).read_text(encoding="utf-8").splitlines()
        header = lines[0].split(",")
        assert header[0] == "step" and header[-1] == "trust", case["recipe_id"]
        assert len(lines) > 10, case["recipe_id"]


def write_goldens() -> None:
    """Regenerate every golden file from the current code (intended data changes only)."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="b1500-data-golden-", ignore_cleanup_errors=True) as tmp:
            fixture_path(case["recipe_id"]).write_bytes(archived_table(case, make_world(Path(tmp))))
            print(f"wrote {fixture_path(case['recipe_id']).relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python -m tests.integration.test_data_goldens --write")
    write_goldens()
