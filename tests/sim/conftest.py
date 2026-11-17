"""Fixtures for the simulator tests (helpers live in ``tests/sim/helpers.py``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from b1500_test_agent.models.sim import SimFault
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import load_scenario, noiseless


@pytest.fixture
def nmos() -> SimScenario:
    """The committed ``nmos_basic`` scenario (with noise)."""
    return load_scenario("nmos_basic")


@pytest.fixture
def make_sim() -> Callable[..., SimTransport]:
    """Factory: an opened ``SimTransport`` for a scenario (default: noiseless ``nmos_basic``)."""

    def _make(scenario: SimScenario | None = None, *, faults: Iterable[SimFault] = (),
              state_file: Path | None = None, timeout_s: float = 10.0) -> SimTransport:
        transport = SimTransport(scenario or noiseless(load_scenario("nmos_basic")), state_file=state_file,
                                 faults=faults, timeout_s=timeout_s)
        transport.open()
        return transport

    return _make
