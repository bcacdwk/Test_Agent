"""Persistent simulator state across ``SimTransport`` instances (blueprint 2.7, 3, 8.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from b1500_test_agent.transport.base import StatefulTransport, TransportError, state_hooks
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.state import COMMAND_LOG_LIMIT, SimPersistentState, load_state_file
from tests.sim.helpers import load_scenario, noiseless, run


def test_state_file_location(tmp_path: Path) -> None:
    assert sim_state_file(tmp_path, "nmos_basic") == tmp_path / "sim" / "nmos_basic.state.json"


def test_outputs_and_command_log_persist_across_two_transports(tmp_path: Path) -> None:
    """Process A (e.g. the MCP server) leaves an output on; process B (the CLI) sees it and its command log."""
    scenario = noiseless(load_scenario("nmos_basic"))
    path = sim_state_file(tmp_path, scenario.name)
    first = SimTransport(scenario, state_file=path)
    first.open()
    run(first, "CN 1,3", "DV 1,0,0.8,1E-3")
    first.save_state()
    first.close()

    second = SimTransport(scenario, state_file=path)
    second.open()  # loads the state
    outputs = second.instrument.outputs()
    assert outputs[1].output_on and outputs[1].voltage == 0.8 and outputs[1].icomp == pytest.approx(1e-3)
    assert second.query("LOP?").startswith("LOP01,00,01")
    assert [r.command for r in second.instrument.source_commands()] == ["DV 1,0,0.8,1E-3"]
    with pytest.raises(AssertionError):
        second.instrument.assert_safe()
    run(second, "DZ", "CL")
    second.instrument.assert_safe()
    second.save_state()

    first.load_state()  # under the lock, process A reloads before its next transaction
    first.instrument.assert_safe()
    seqs = [r.seq for r in first.instrument.command_log]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # one sequence across both processes


def test_measurement_counter_persists_so_noise_continues(tmp_path: Path) -> None:
    scenario = load_scenario("nmos_basic")
    path = sim_state_file(tmp_path, scenario.name)
    a = SimTransport(scenario, state_file=path)
    a.open()
    run(a, "CN 1,3", "DV 3,0,0.1,1E-2", "MM 1,3", "XE")
    first = a.read()
    a.save_state()
    b = SimTransport(scenario, state_file=path)
    b.open()
    run(b, "MM 1,3", "XE")
    assert b.read() != first  # the second measurement draws fresh noise
    assert b.instrument.state.measurement_count == 2


def test_save_is_atomic_json_and_without_a_file_is_a_no_op(tmp_path: Path) -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    path = sim_state_file(tmp_path, scenario.name)
    transport = SimTransport(scenario, state_file=path)
    transport.open()
    transport.save_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["scenario"] == "nmos_basic" and data["version"] == 1 and data["saved_at"].endswith("Z")
    assert list(path.parent.iterdir()) == [path]  # no temporary file left behind
    memory_only = SimTransport(scenario, state_file=None)
    memory_only.open()
    memory_only.save_state()
    memory_only.load_state()


def test_corrupt_or_foreign_state_is_a_transport_error(tmp_path: Path) -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    path = sim_state_file(tmp_path, scenario.name)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TransportError, match="Corrupt"):
        SimTransport(scenario, state_file=path).open()
    path.write_text(SimPersistentState(scenario="other").model_dump_json(), encoding="utf-8")
    with pytest.raises(TransportError, match="scenario"):
        SimTransport(scenario, state_file=path).open()
    assert load_state_file(tmp_path / "missing.json") is None


def test_command_log_is_trimmed_on_save(tmp_path: Path) -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    path = sim_state_file(tmp_path, scenario.name)
    transport = SimTransport(scenario, state_file=path)
    transport.open()
    for _ in range(COMMAND_LOG_LIMIT + 10):
        transport.instrument.handle("BC")
    transport.save_state()
    state = load_state_file(path)
    assert state is not None and len(state.command_log) == COMMAND_LOG_LIMIT and state.log_dropped == 10


def test_state_hooks_are_found_through_the_audit_wrapper() -> None:
    from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink

    inner = SimTransport(noiseless(load_scenario("nmos_basic")), state_file=None)
    wrapped = AuditingTransport(inner, MemoryAuditSink())
    assert state_hooks(wrapped) is inner and isinstance(inner, StatefulTransport)
    assert state_hooks(object()) is None
