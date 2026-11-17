"""Shared fixtures for config and model tests: a hermetic copy of the committed config tree in ``tmp_path``.

Tests never read or write the repository's ``config/local/``; they copy the committed examples into a temporary
repository root and point ``Paths`` (or ``B1500_HOME``) at it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME, Paths
from tests.unit.helpers import CONFIG_DIR


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits B1500_* overrides from the developer's shell."""
    for name in (ENV_HOME, ENV_CONFIG_DIR, ENV_DATA_DIR):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A temporary repository root holding a copy of the committed config tree (without ``config/local/``)."""
    root = tmp_path / "repo"
    shutil.copytree(CONFIG_DIR, root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    return root


@pytest.fixture
def repo_paths(repo: Path) -> Paths:
    return Paths.from_env({}, repo_root=repo)
