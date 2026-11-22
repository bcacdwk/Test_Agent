"""`b1500 dev recipe-check [--json]` (blueprint 5.3, WP1.7 AC): exit 0 iff the recipe tree has no problems."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from tests.unit.helpers import REPO_ROOT

runner = CliRunner()


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary clone with a copy of recipes/ and the test cards they point at, selected through B1500_HOME."""
    for name in (ENV_CONFIG_DIR, ENV_DATA_DIR):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "clone"
    shutil.copytree(REPO_ROOT / "recipes", root / "recipes")
    cards = Path(".agents", "skills", "b1500-test", "cards")
    shutil.copytree(REPO_ROOT / cards, root / cards)  # recipe `card:` paths must resolve (WP2.5)
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(root))
    return root


def test_committed_recipes_are_clean(clone: Path) -> None:
    result = runner.invoke(app, ["dev", "recipe-check"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("recipes: clean (42 loaded")  # 24 (WP7.4) + five WP7.2 sweeps + three WP7.1
# + WP7.6: bti_sms and hci leave recipes/reserved, igzo.bias_stress and reliability.silc are new
# + WP8.2: the four cmu.* correction recipes, the reserved cmu.correction retired
# + WP9.2: system.selector_check
# + WP7.3: the four SMU pulsed recipes
    assert "mosfet.idvg" in result.output and "sim:sim_validated" in result.output


def test_problems_exit_non_zero_with_json(clone: Path) -> None:
    path = clone / "recipes" / "mosfet" / "idvg.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("kind: smu_staircase", "kind: warp_drive"),
                    encoding="utf-8")
    result = runner.invoke(app, ["dev", "recipe-check", "--json"])
    assert result.exit_code == 1
    report = json.loads(result.output)
    assert report["ok"] is False
    assert report["problems"] and all(p.startswith("recipes/mosfet/idvg.yaml: ") for p in report["problems"])
    assert any("unknown kind 'warp_drive'" in p for p in report["problems"])
    assert {r["id"] for r in report["recipes"]} >= {"mosfet.idvg", "system.self_test"}
