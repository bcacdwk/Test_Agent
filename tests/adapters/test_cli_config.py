"""`b1500 config check [--json]` (blueprint 5.3, 7): exit codes, structured errors, file and backend report."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from tests.unit.helpers import CONFIG_DIR, read_yaml, write_yaml

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary clone with the committed config tree, selected through B1500_HOME."""
    for name in (ENV_CONFIG_DIR, ENV_DATA_DIR):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "clone"
    shutil.copytree(CONFIG_DIR, root / "config", ignore=shutil.ignore_patterns("local"))
    monkeypatch.setenv(ENV_HOME, str(root))
    return root


def test_config_check_valid_examples(home: Path) -> None:
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("config: valid")
    assert "backend: sim: config/settings.example.yaml is the committed example" in result.output
    assert "policy" in result.output and "config/policy.example.yaml" in result.output
    assert "state_dir: data/state" in result.output


def test_config_check_json(home: Path) -> None:
    result = runner.invoke(app, ["config", "check", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["ok"] is True and report["backend"] == "sim" and report["error_code"] is None
    assert {f["key"]: f["source"] for f in report["files"]}["settings"] == "example"
    assert report["paths"]["runs_dir"] == "data/runs"


def test_config_check_invalid_is_structured(home: Path) -> None:
    settings = read_yaml(home / "config" / "settings.example.yaml")
    settings["backend"] = "visa"
    write_yaml(home / "config" / "settings.example.yaml", settings)
    result = runner.invoke(app, ["config", "check", "--json"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)  # no traceback
    report = json.loads(result.output)
    assert report["ok"] is False and report["error_code"] == "invalid_config"
    assert report["problems"][0]["file"] == "config/settings.example.yaml"

    human = runner.invoke(app, ["config", "check"])
    assert human.exit_code == 1
    assert "config: INVALID (invalid_config)" in human.output
    assert "example file can never select backend visa" in human.output
