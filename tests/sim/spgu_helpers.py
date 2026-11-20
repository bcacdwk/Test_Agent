"""Helpers for the HV-SPGU simulator tests (WP9.1): scenarios on the lab mainframe (SPGU in slot 1: channels 101 and
102, canonical 1 and 102) with devices wired to the SPGU outputs, and FLEX shortcuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport

LAB_SLOTS = [
    {"slot": 1, "model": "B1525A"}, {"slot": 2, "model": "B1530A"}, {"slot": 3, "model": "B1517A"},
    {"slot": 4, "model": "B1517A"}, {"slot": 5, "model": "B1511B"}, {"slot": 6, "model": "B1511B"},
    {"slot": 7, "model": "B1520A"},
]  # fmt: skip
"""The lab mainframe (blueprint v2 1.1): SPGU 1, WGFMU 2, HRSMU 3-4, MPSMU 5-6, MFCMU 7."""

FEFET_PARAMS: dict[str, Any] = {
    "polarity": "n", "vth0": 0.6, "k_v": 0.5, "vc_v": 2.8, "delta_v": 0.45, "p_init": -1.0, "slope_factor": 1.3,
    "beta": 1.0e-3, "theta": 0.5, "lambda": 0.05, "rs_ohm": 20.0, "gate_leak_s": 1.0e-12, "temperature_k": 300.0,
    "tau0_s": 1.0e-9, "va_v": 8.0, "alpha": 2.0, "beta_sw": 1.0,
}  # fmt: skip
"""A FeFET whose NLS switching takes microseconds at 4-5 V (``fefet_basic`` DC loop plus kinetics)."""


def spgu_scenario(models: dict[str, Any] | None = None, wiring: dict[str, Any] | None = None,
                  **extra: Any) -> SimScenario:
    """The lab mainframe with ``models`` wired by ``wiring`` (nothing wired: every SPGU output is an open load)."""
    data: dict[str, Any] = {
        "name": "spgu_test", "idn": "Keysight Technologies,B1500A,0,A.06.02.2023.0401", "slots": LAB_SLOTS,
        "wiring": wiring or {}, "models": models or {}, "noise": {"floor_a": {}, "rel": 0.0, "seed": 9},
    }
    data.update(extra)
    return SimScenario.model_validate(data)


def resistor_load(r_ohm: float, channel: int = 101) -> SimScenario:
    """A resistor from SPGU ``channel`` to the GNDU."""
    return spgu_scenario({"r": {"model": "resistor", "params": {"r_ohm": r_ohm}}},
                         {"r": {"a": channel, "b": "GNDU"}})


def fefet_on_spgu(**params: Any) -> SimScenario:
    """A FeFET with its gate on SPGU 101, drain on HRSMU 4, source and bulk on the GNDU."""
    return spgu_scenario({"dut": {"model": "fefet", "params": {**FEFET_PARAMS, **params}}},
                         {"dut": {"gate": 101, "drain": 4, "source": "GNDU", "bulk": "GNDU"}})


def open_sim(scenario: SimScenario | None = None, state_file: Path | None = None) -> SimTransport:
    sim = SimTransport(scenario or spgu_scenario(), state_file=state_file)
    sim.open()
    return sim


def send(sim: SimTransport, *commands: str) -> None:
    """Write each command; fail on any queued instrument error."""
    for command in commands:
        sim.write(command)
    assert sim.instrument.errors == [], f"errors after {commands}: {sim.instrument.errors}"


def errors_of(sim: SimTransport) -> list[int]:
    """Drain and return the queued error codes."""
    codes = []
    while True:
        code = int(sim.query("ERRX? 1"))
        if code == 0:
            return codes
        codes.append(code)


def two_level_setup(sim: SimTransport, *, ch: int = 101, peak: float = 3.0, base: float = 0.0, ser: float = 1e6,
                    period: float = 1e-5, width: float = 2e-6, run: str = "SPRM 1,3") -> None:
    """``CN``, PG mode, ``run``, period, one two-level channel, ``SPUPD`` (not started)."""
    send(sim, f"CN {ch}", "SIM 0", run, f"SPPER {period}", f"SER {ch},{ser}", f"SPM {ch},1",
         f"SPT {ch},1,0,{width},2E-8,2E-8", f"SPV {ch},1,{base},{peak}", f"SPUPD {ch}")
