"""Fixtures of the visa-loop suite: a hermetic backend-visa world per test (``helpers.make_visa_world``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from b1500_test_agent.service import ENV_SESSION_TAG
from tests.visa_loop.helpers import VisaWorld, make_visa_world


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits B1500_* overrides from the developer's shell."""
    for name in (ENV_HOME, ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_SESSION_TAG):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[VisaWorld]:
    w = make_visa_world(tmp_path)
    yield w
    w.close()
