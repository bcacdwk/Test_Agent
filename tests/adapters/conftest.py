"""Fixtures of the adapter tests: a hermetic world (temporary repository root with the committed config, temporary
``B1500_CONFIG_DIR`` and ``B1500_DATA_DIR``) and the CLI environment over it (helpers: ``helpers.py``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from b1500_test_agent.service import ENV_SESSION_TAG
from tests.integration.helpers import World, make_world


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits B1500_* overrides from the developer's shell."""
    for name in (ENV_HOME, ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_SESSION_TAG):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path)
    yield w
    for service in w.services:
        service.close()
    for executor in w.executors:
        executor.close()


@pytest.fixture
def cli_world(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """``world`` with ``B1500_HOME``/``B1500_CONFIG_DIR``/``B1500_DATA_DIR`` set, as a CLI process would see it."""
    for key, value in world.env().items():
        monkeypatch.setenv(key, value)
    return world
