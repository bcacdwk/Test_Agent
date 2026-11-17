"""Fixtures of the executor-level integration tests: a hermetic ``world`` per test (``helpers.make_world``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from tests.integration.helpers import World, make_world


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits B1500_* overrides from the developer's shell."""
    for name in (ENV_HOME, ENV_CONFIG_DIR, ENV_DATA_DIR):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path)
    yield w
    for executor in w.executors:
        executor.close()
    for service in w.services:
        service.close()
