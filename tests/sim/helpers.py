"""Helpers for the simulator tests: committed scenarios, noiseless variants, scenarios built in code, and small
FLEX conveniences. Nothing here touches ``config/local/`` or a real instrument."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO_ROOT / "config" / "sim" / "scenarios"
FAULT_DIR = REPO_ROOT / "config" / "sim" / "faults"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"

NMOS_SLOTS = [
    {"slot": 1, "model": "B1511B"}, {"slot": 2, "model": "B1511B"}, {"slot": 3, "model": "B1517A"},
    {"slot": 4, "model": "B1517A"}, {"slot": 5, "model": "B1530A"}, {"slot": 6, "model": "B1525A"},
    {"slot": 7, "model": "B1520A"},
]  # fmt: skip
"""The fixed test mainframe of the FLEX-level simulator tests: MPSMU in slots 1-2, HRSMU 3-4, WGFMU 5, HV-SPGU 6,
MFCMU 7 (the v1 example layout). These tests check command semantics on "an MPSMU in slot 1"; keeping their
mainframe fixed keeps their channel numbers independent of the station example, whose lab layout (WP5.3: SPGU 1,
WGFMU 2, HRSMU 3-4, MPSMU 5-6, MFCMU 7) the committed scenarios use (``test_scenarios.py``, integration tests)."""


def load_scenario(name: str) -> SimScenario:
    """A committed scenario file (name = file stem, as the config loader does)."""
    data = yaml.safe_load((SCENARIO_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return SimScenario.model_validate({**data, "name": name})


def noiseless(scenario: SimScenario) -> SimScenario:
    """``scenario`` without measurement noise."""
    return scenario.model_copy(update={"noise": scenario.noise.model_copy(update={"rel": 0.0, "floor_a": {}})})


def on_test_mainframe(scenario: SimScenario) -> SimScenario:
    """``scenario`` (devices, wiring, noise) on the fixed FLEX test mainframe ``NMOS_SLOTS``; its wiring must only use
    slots both layouts share (3, 4, 7, GNDU), which every committed v1 scenario does."""
    return SimScenario.model_validate({**scenario.model_dump(mode="json"), "slots": NMOS_SLOTS})


def scenario_with(models: dict[str, Any], wiring: dict[str, Any], **extra: Any) -> SimScenario:
    """A scenario on the example mainframe with the given devices (noiseless unless ``noise`` is given)."""
    data: dict[str, Any] = {
        "name": "test_scenario",
        "idn": "Keysight Technologies,B1500A,0,A.06.01.2024.0101",
        "slots": NMOS_SLOTS,
        "wiring": wiring,
        "models": models,
        "noise": {"floor_a": {}, "rel": 0.0, "seed": 7},
    }
    data.update(extra)
    return SimScenario.model_validate(data)


def resistor_scenario(r_ohm: float = 1000.0, **extra: Any) -> SimScenario:
    """A resistor between SMU1 (``a``) and SMU3 (``b``)."""
    return scenario_with({"r": {"model": "resistor", "params": {"r_ohm": r_ohm}}}, {"r": {"a": 1, "b": 3}}, **extra)


def run(transport: SimTransport, *commands: str) -> None:
    """Write each command and fail the test on any queued instrument error."""
    for command in commands:
        transport.write(command)
    errors = transport.instrument.errors
    assert errors == [], f"instrument errors after {commands}: {errors}"


def elements(text: str) -> list[str]:
    """FMT 1 data split into elements (the CR/LF terminator is already stripped by the transport)."""
    return text.split(",") if text else []


def values(text: str) -> list[float]:
    """Numeric parts (characters 4-15) of FMT 1/5 elements."""
    return [float(e[3:]) for e in elements(text) if e]


def errx_all(transport: SimTransport) -> list[int]:
    """Drain the error queue through ``ERRX?`` (codes, oldest first)."""
    codes = []
    while True:
        code = int(transport.query("ERRX? 1"))
        if code == 0:
            return codes
        codes.append(code)
