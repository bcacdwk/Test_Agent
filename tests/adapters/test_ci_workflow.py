"""The CI workflow (blueprint 7, 8.1): parses as YAML and runs the simulator-only gate on macOS and Windows."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_ci_workflow_runs_the_simulator_gate_on_macos_and_windows() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    (job,) = workflow["jobs"].values()
    assert {"macos-latest", "windows-latest"} <= set(job["strategy"]["matrix"]["os"])
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert any(u.startswith("astral-sh/setup-uv@") for u in uses)
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert runs == ["uv sync --frozen", "uv run ruff check", 'uv run pytest -q -m "not hardware and not acceptance"']
