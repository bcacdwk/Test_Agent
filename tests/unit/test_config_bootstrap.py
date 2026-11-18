"""``config.init_local`` / ``config.adopt`` (the human-only configuration bootstrap, blueprint v2 7.1, WP6.1) on
temporary clones; with ``$B1500_CONFIG_DIR`` set they write there, never into the clone's ``config/local/``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.config import ADOPT_TARGETS, adopt, bootstrap_dir, init_local
from b1500_test_agent.paths import ENV_CONFIG_DIR, Paths
from tests.unit.helpers import CONFIG_DIR


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    root = tmp_path / "clone"
    shutil.copytree(CONFIG_DIR, root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    return root


def test_bootstrap_dir_is_the_override_directory_when_set(clone: Path, tmp_path: Path) -> None:
    assert bootstrap_dir(Paths.from_env({}, repo_root=clone)) == clone / "config" / "local"
    override = tmp_path / "cfg"
    assert bootstrap_dir(Paths.from_env({ENV_CONFIG_DIR: str(override)}, repo_root=clone)) == override.resolve()


def test_init_into_the_override_never_touches_config_local(clone: Path, tmp_path: Path) -> None:
    override = tmp_path / "cfg"
    paths = Paths.from_env({ENV_CONFIG_DIR: str(override)}, repo_root=clone)
    report = init_local(paths, visa=True)
    assert report.ok and len(report.copied) == 3 and not (clone / "config" / "local").exists()
    assert any("B1500_CONFIG_DIR" in note for note in report.notes)
    assert report.check is not None and not report.check.ok  # backend visa refuses B1500_CONFIG_DIR (R-CFG-01)
    assert yaml.safe_load((override / "settings.yaml").read_text(encoding="utf-8"))["backend"] == "visa"


def test_init_reports_an_example_without_a_backend_line(clone: Path) -> None:
    example = clone / "config" / "settings.example.yaml"
    example.write_text(example.read_text(encoding="utf-8").replace("backend: sim", "# backend chosen elsewhere"),
                       encoding="utf-8")
    report = init_local(Paths.from_env({}, repo_root=clone), visa=True)
    assert not report.ok and "no `backend: sim` line" in report.problems[0]
    assert not (clone / "config" / "local" / "settings.yaml").exists()
    assert sorted(report.copied) == ["config/local/policy.yaml", "config/local/station.yaml"]


def test_adopt_uses_the_name_key_of_a_pin_map(clone: Path, tmp_path: Path) -> None:
    paths = Paths.from_env({}, repo_root=clone)
    source = tmp_path / "anything.yaml"
    data = yaml.safe_load((clone / "config" / "pinmaps" / "diode-2t.example.yaml").read_text(encoding="utf-8"))
    source.write_text(yaml.safe_dump({**data, "name": "diode-probe-a"}), encoding="utf-8")
    report = adopt(source, "pinmap", paths)
    assert report.adopted and report.target == "config/local/pinmaps/diode-probe-a.yaml" and report.ok
    again = adopt(clone / "config" / "local" / "pinmaps" / "diode-probe-a.yaml", "pinmap", paths)
    assert not again.ok and "already is the local file" in again.problems[0]


def test_adopt_refuses_a_name_that_is_no_config_name(clone: Path, tmp_path: Path) -> None:
    source = tmp_path / "x.yaml"
    data = yaml.safe_load((clone / "config" / "duts" / "nmos-generic.example.yaml").read_text(encoding="utf-8"))
    source.write_text(yaml.safe_dump({**data, "name": "../escape"}), encoding="utf-8")
    report = adopt(source, "dut", Paths.from_env({}, repo_root=clone))
    assert not report.ok and not report.adopted and report.target is None
    assert any(p.startswith("name:") for p in report.problems)
    assert not (clone / "config" / "local").exists() and not (clone / "config" / "escape.yaml").exists()


def test_every_kind_has_a_target_and_a_schema() -> None:
    assert set(ADOPT_TARGETS) == {"settings", "station", "policy", "pinmap", "dut"}
    assert [ADOPT_TARGETS[k][0] for k in ("settings", "station", "policy", "pinmap", "dut")] == [
        "settings.yaml", "station.yaml", "policy.yaml", "pinmaps", "duts"]
