"""Simulator side of the read-only probe's family state queries (blueprint v2 4.1, 7.1; WP6.1): ``ERMOD?``,
``ERSSP?`` (switch unit), ``SPST?`` (SPGU unit), ``CORRST?`` and ``ADJ? ch,0`` (CMU unit) answer the persistent
state, keep it across processes (state file) and reset it like power-on on ``*RST``/device clear."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.state import load_state_file
from tests.sim.helpers import load_scenario, noiseless


def lab(state_file: Path | None = None) -> SimTransport:
    transport = SimTransport(noiseless(load_scenario("lab_station")), state_file=state_file)
    transport.open()
    return transport


def test_power_on_state_is_open_inactive_and_off() -> None:
    sim = lab()
    assert sim.query("ERMOD?") == "0"
    assert [sim.query(f"ERSSP? {port}") for port in range(4)] == ["0", "0", "0", "0"]
    assert sim.query("SPST?") == "0"
    assert [sim.query(f"CORRST? 7,{corr}") for corr in (1, 2, 3)] == ["0", "0", "0"]
    assert sim.query("ADJ? 7,0") == "3"  # no phase compensation measurement since power-on (PG PDF 356)
    assert sim.instrument.errors == []
    assert all(r.outcome == "ok" for r in sim.instrument.command_log)


def test_queries_read_the_seeded_state() -> None:
    sim = lab()
    state = sim.instrument.state
    state.selector_mode = 1
    state.selector_ports.update({0: 2, 3: 1})
    state.spgu_output_active = True
    state.cmu_corrections[7] = {1: True, 2: False}
    state.cmu_phase_results[7] = 0
    assert sim.query("ERMOD?") == "1"
    assert [sim.query(f"ERSSP? {port}") for port in range(4)] == ["2", "0", "0", "1"]
    assert sim.query("SPST?") == "1"
    assert [sim.query(f"CORRST? 7,{corr}") for corr in (1, 2, 3)] == ["1", "0", "0"]
    assert sim.query("ADJ? 7,0") == "0"


def test_rst_resets_like_power_on_but_keeps_the_phase_compensation_data() -> None:
    sim = lab()
    state = sim.instrument.state
    state.selector_mode, state.spgu_output_active = 1, True
    state.selector_ports[2] = 3
    state.cmu_corrections[7] = {3: True}
    state.cmu_phase_results[7] = 0
    sim.write("*RST")
    assert (sim.query("ERMOD?"), sim.query("ERSSP? 2"), sim.query("SPST?"), sim.query("CORRST? 7,3")) == (
        "0", "0", "0", "0")
    assert sim.query("ADJ? 7,0") == "0"  # only a power cycle clears the compensation data (PG PDF 355)
    state.spgu_output_active = True
    sim.device_clear()
    assert sim.query("SPST?") == "0"


def test_state_persists_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "lab.state.json"
    first = lab(path)
    first.load_state()
    state = first.instrument.state
    state.selector_mode, state.selector_ports[1] = 1, 1
    state.cmu_corrections[7] = {2: True}
    state.cmu_phase_results[7] = 1
    first.save_state()
    stored = load_state_file(path)
    assert stored is not None and stored.selector_ports == {1: 1} and stored.cmu_corrections == {7: {2: True}}
    second = lab(path)
    second.load_state()
    assert (second.query("ERMOD?"), second.query("ERSSP? 1"), second.query("CORRST? 7,2"),
            second.query("ADJ? 7,0")) == ("1", "1", "1", "1")


@pytest.mark.parametrize(
    ("command", "error"),
    [
        ("ERSSP? 4", 120),  # ports 0-3 (PG PDF 433)
        ("ERSSP?", 103),  # the port is required (wrong parameter count, as for every command)
        ("CORRST? 7,4", 120),  # modes 1-3 (PG PDF 388)
        ("CORRST? 3,1", 322),  # slot 3 is an SMU: "not available for SMU" (PG PDF 583)
        ("CORRST? 9,1", 153),  # slot 9 is empty
        ("ADJ? 7,2", 120),  # modes 0 and 1 (PG PDF 356)
        ("ADJ? 4,0", 322),
        ("ADJ? 1,0", 151),  # slot 1 is the HV-SPGU
        ("ERMOD? 1", 103),
    ],
)
def test_malformed_probe_queries_queue_an_error_and_answer_nothing(command: str, error: int) -> None:
    sim = lab()
    sim.write(command)
    assert sim.instrument.errors == [error]
    assert sim.query("ERRX?").startswith(f"{error},")


@pytest.mark.parametrize("command", ["ADJ? 7,1", "ADJ? 7"])
def test_phase_compensation_measurement_needs_the_manual_mode(command: str) -> None:
    """``ADJ?`` mode 1 (the manual's default) measures for about 30 s, only in the manual mode (error 680, PG PDF
    587); the read-only probe therefore always writes mode 0 (WP8.1 simulates the measurement)."""
    sim = lab()
    sim.write(command)
    assert sim.instrument.errors == [680]
    sim.query("ERRX?")
    sim.write("ADJ 7,1")
    start = sim.instrument.clock
    assert sim.query(command, timeout_s=60.0) == "0"
    assert sim.instrument.clock - start == pytest.approx(30.0)
    assert sim.query("ADJ? 7,0") == "0"
