"""Helpers for the 16440A selector tests (WP9.2): the station switches matching the simulated selector cabling of
``fefet_lab``/``lab_station`` (port 0: SMU3 + SPGU 101, port 1: SPGU 102, port 2: SMU5, port 3: SMU6), a recorded
lab station profile for config-level tests, and the sim's selector state."""

from __future__ import annotations

from typing import Any

import yaml

from b1500_test_agent.models.routing import SwitchSpec
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import REPO_ROOT

GATE_SMU, DRAIN_SMU, PGU = 3, 4, 101

SEL1 = SwitchSpec.model_validate({
    "id": "SEL1", "kind": "selector_16440a", "present": True, "certainty": "verified", "rest": "open",
    "ports": {"OUT1": {"index": 0, "inputs": {"smu": 3, "pgu": 101}}, "OUT2": {"index": 1, "inputs": {"pgu": 102}}},
})
SEL2 = SwitchSpec.model_validate({
    "id": "SEL2", "kind": "selector_16440a", "present": True, "certainty": "verified", "rest": "open",
    "ports": {"OUT1": {"index": 2, "inputs": {"smu": 5}}, "OUT2": {"index": 3, "inputs": {"smu": 6}}},
})
SELECTORS: tuple[SwitchSpec, ...] = (SEL1, SEL2)
"""The two selectors as a human records them after bring-up L7 on the simulated lab cabling."""


def recorded_station(**changes: Any) -> dict[str, Any]:
    """``config/station.example.yaml`` with SEL1/SEL2 replaced by ``SELECTORS`` (wiring recorded, verified);
    ``changes`` update top-level keys."""
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    recorded = {s.id: s.model_dump(mode="json") for s in SELECTORS}
    station["switches"] = [recorded.get(s["id"], s) for s in station["switches"]]
    station.update(changes)
    return station


def selector_states(sim: SimTransport) -> dict[int, int]:
    """``ERSSP`` status per port (0-3) as the simulated instrument reports it (``ERSSP?``)."""
    return {port: sim.instrument._selector_status(port) for port in range(4)}  # type: ignore[attr-defined]


def at_rest(sim: SimTransport) -> bool:
    """Every selector port open (status 0)."""
    return all(status == 0 for status in selector_states(sim).values())
