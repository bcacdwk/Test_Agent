"""The CI workflow (blueprint v2 7.1 "Windows CI", 8.1, 10 Definition of done; WP6.5): parses as YAML and runs the
whole gate on macOS and Windows, every gate step even after an earlier one failed."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = [  # blueprint v2 10 "Definition of done", in the workflow's order
    'uv run pytest -q -m "not hardware and not acceptance and not wall_clock" -n auto',
    'uv run pytest -q -m "wall_clock and not hardware and not acceptance"',  # alone: nothing shares their CPU
    "uv run ruff check",
    "uv run b1500 dev recipe-check",
    "uv run b1500 dev lint-skills",
    "uv run b1500 dev gen-index --check",
    "uv run b1500 dev sync-harness --check",
    "uv run b1500 dev tool-budget",
    "uv run b1500 manual status",  # manual build --check needs the PDFs, which CI does not have
]


def test_ci_workflow_runs_the_gate_on_macos_and_windows() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    (job,) = workflow["jobs"].values()
    assert {"macos-latest", "windows-latest"} <= set(job["strategy"]["matrix"]["os"])
    assert job["strategy"]["fail-fast"] is False and job["env"]["PYTHONUTF8"] == "1"
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert any(u.startswith("astral-sh/setup-uv@") for u in uses)
    steps = [step for step in job["steps"] if "run" in step]
    assert [step["run"] for step in steps] == ["uv sync --frozen", *GATE]
    assert all(step.get("if") == "${{ !cancelled() }}" for step in steps[1:])  # one run reports every red gate


def test_the_two_pytest_steps_run_every_gate_test_once() -> None:
    """The parallel step and the wall-clock step split the gate's selection ``not hardware and not acceptance``
    without a gap or an overlap (the wall-clock tests run alone, never skipped)."""
    parallel, alone = GATE[0], GATE[1]
    assert '"not hardware and not acceptance and not wall_clock"' in parallel and "-n auto" in parallel
    assert '"wall_clock and not hardware and not acceptance"' in alone and "-n" not in alone.split()
    markers = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"wall_clock: asserts a wall-clock bound of the plan' in markers
    marked = [path for path in (ROOT / "tests").rglob("test_*.py")
              if "@pytest.mark.wall_clock" in path.read_text(encoding="utf-8")]
    assert ROOT / "tests" / "integration" / "test_async_runs.py" in marked  # the 4 h instant run (blueprint v2 4.1)


def test_xdist_is_in_the_dev_group() -> None:
    """``-n auto`` needs pytest-xdist in the locked dev group (blueprint v2 9 "Dependencies")."""
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest-xdist" in pyproject["dependency-groups"]["dev"]
    assert 'name = "pytest-xdist"' in (ROOT / "uv.lock").read_text(encoding="utf-8")
