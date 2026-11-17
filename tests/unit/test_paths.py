"""Repository-relative default paths and the test-only environment overrides (blueprint 2.7, 4.1, decision D1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.models.station import PathSettings
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME, Paths, find_repo_root
from tests.unit.helpers import REPO_ROOT


def test_default_paths_are_repo_relative() -> None:
    paths = Paths.from_env()
    root = REPO_ROOT.resolve()
    assert paths.repo_root == root
    assert paths.config_dir == root / "config"
    assert paths.local_config_dir == root / "config" / "local"
    assert paths.override_config_dir is None
    assert paths.data_root == root / "data"
    assert paths.runs_dir == root / "data" / "runs"
    assert paths.state_dir == root / "data" / "state"
    assert paths.work_dir == root / "work"
    assert paths.recipes_dir == root / "recipes"
    report = paths.report()
    assert (report["local_config_dir"], report["runs_dir"], report["state_dir"], report["work_dir"]) == (
        "config/local",
        "data/runs",
        "data/state",
        "work",
    )


def test_default_settings_keep_the_defaults() -> None:
    paths = Paths.from_env()
    assert paths.with_settings(PathSettings()) == paths


def test_b1500_home_is_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    paths = Paths.from_env()
    root = tmp_path.resolve()
    assert paths.repo_root == root
    assert paths.local_config_dir == root / "config" / "local"
    assert paths.state_dir == root / "data" / "state"


def test_relative_b1500_home_resolves_against_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "clone").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_HOME, "clone")
    assert find_repo_root() == (tmp_path / "clone").resolve()


def test_config_and_data_overrides_are_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_CONFIG_DIR, str(tmp_path / "cfg"))
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "dat"))
    paths = Paths.from_env()
    assert paths.repo_root == REPO_ROOT.resolve()
    assert paths.override_config_dir == (tmp_path / "cfg").resolve()
    assert paths.data_root == (tmp_path / "dat").resolve()
    assert paths.runs_dir == (tmp_path / "dat" / "runs").resolve()
    assert paths.state_dir == (tmp_path / "dat" / "state").resolve()
    assert paths.local_config_dir == REPO_ROOT.resolve() / "config" / "local"  # unchanged
    assert "tests/M3 only" in paths.report()["data_root"]


def test_relative_overrides_resolve_against_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    paths = Paths.from_env({ENV_CONFIG_DIR: "cfg", ENV_DATA_DIR: "dat"})
    assert paths.override_config_dir == (tmp_path / "cfg").resolve()
    assert paths.data_root == (tmp_path / "dat").resolve()


def test_empty_overrides_are_ignored() -> None:
    paths = Paths.from_env({ENV_CONFIG_DIR: "", ENV_DATA_DIR: ""})
    assert paths.override_config_dir is None
    assert paths.data_root == REPO_ROOT.resolve() / "data"


def test_settings_paths_apply_but_env_data_dir_wins(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    custom = PathSettings(data_root="archive", work_dir=str(tmp_path / "scratch"))
    paths = Paths.from_env({}, repo_root=root).with_settings(custom)
    assert paths.data_root == root / "archive"
    assert paths.state_dir == root / "archive" / "state"
    assert paths.work_dir == root / "scratch"
    pinned = Paths.from_env({ENV_DATA_DIR: str(tmp_path / "env")}, repo_root=root).with_settings(custom)
    assert pinned.data_root == root / "env"


def test_display_is_repo_relative_posix(tmp_path: Path) -> None:
    paths = Paths.from_env({}, repo_root=tmp_path)
    assert paths.display(tmp_path / "config" / "local" / "policy.yaml") == "config/local/policy.yaml"
    outside = tmp_path.parent / "elsewhere.yaml"
    assert paths.display(outside) == outside.resolve().as_posix()


def test_missing_b1500_home_is_invalid_config(tmp_path: Path) -> None:
    with pytest.raises(InvalidConfigError) as info:
        find_repo_root({ENV_HOME: str(tmp_path / "missing")})
    assert info.value.code == "invalid_config"
    assert ENV_HOME in info.value.problems[0].message
