"""Real-harness runs (marker ``acceptance``; excluded from the normal gate, run explicitly, cost tokens).

``uv run pytest -m acceptance tests/acceptance/test_live_harness.py`` runs the read-only smoke probe once per
installed harness through ``b1500 dev acceptance run``. The S1-S10 suite itself is run with
``uv run b1500 dev acceptance run --harness codex|claude --all`` (docs/acceptance/README.md).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from tests.acceptance.helpers import REPO_ROOT

pytestmark = pytest.mark.acceptance


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_smoke_probe_on_a_real_harness(harness: str, tmp_path: Path) -> None:
    if shutil.which(harness) is None:
        pytest.skip(f"{harness} is not installed")
    result = CliRunner().invoke(app, ["dev", "acceptance", "run", "--harness", harness, "--scenario", "smoke",
                                      "--repo", str(REPO_ROOT), "--out", str(tmp_path), "--no-rerun"])
    assert result.exit_code == 0, result.stdout
    assert "smoke: PASS" in result.stdout
