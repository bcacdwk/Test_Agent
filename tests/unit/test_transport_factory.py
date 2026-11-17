"""``make_transport`` (blueprint 2.2): sim by default, visa only when the settings say so, always audited."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.config import load_config
from b1500_test_agent.models.sim import Oscillation, SimFaultProfile
from b1500_test_agent.models.station import Settings
from b1500_test_agent.paths import Paths
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import TransportError, state_hooks
from b1500_test_agent.transport.factory import make_transport
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.visa import VisaTransport


def test_committed_config_makes_an_audited_sim_transport(repo_paths: Paths, tmp_path: Path) -> None:
    bundle = load_config(repo_paths)
    sink = MemoryAuditSink()
    transport = make_transport(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
                               state_dir=tmp_path / "state")
    assert isinstance(transport, AuditingTransport) and isinstance(transport.inner, SimTransport)
    assert transport.backend == "sim" and transport.resource == "SIM::nmos_basic"
    assert transport.inner.state_file == tmp_path / "state" / "sim" / "nmos_basic.state.json"
    transport.open()
    assert transport.query("*IDN?").startswith("Keysight Technologies,B1500A")
    assert sink.events[-1].ev == "query"
    hooks = state_hooks(transport)
    assert hooks is transport.inner
    hooks.save_state()
    assert transport.inner.state_file.is_file()


def test_default_settings_never_select_visa(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    transport = make_transport(Settings(), MemoryAuditSink(), scenario=bundle.sim_scenario)
    assert isinstance(transport.inner, SimTransport)
    with pytest.raises(TransportError, match="needs the scenario"):
        make_transport(Settings(), MemoryAuditSink())


def test_visa_only_when_the_settings_say_so() -> None:
    transport = make_transport(Settings(backend="visa"), MemoryAuditSink())
    assert isinstance(transport.inner, VisaTransport) and transport.backend == "visa"
    assert state_hooks(transport) is None  # never opened: no hardware is touched here


def test_visa_refuses_sim_arguments(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    with pytest.raises(TransportError):
        make_transport(Settings(backend="visa"), MemoryAuditSink(), scenario=bundle.sim_scenario)


def test_scenario_must_match_the_settings(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    other = bundle.sim_scenario.model_copy(update={"name": "other"})
    with pytest.raises(TransportError, match="not the configured"):
        make_transport(bundle.settings, MemoryAuditSink(), scenario=other)


def test_fault_profile_or_list_activates_faults(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    profile = SimFaultProfile(name="osc", faults=[Oscillation()])
    for faults in (profile, [Oscillation()]):
        transport = make_transport(bundle.settings, MemoryAuditSink(), scenario=bundle.sim_scenario, faults=faults)
        assert [f.kind for f in transport.inner.instrument.faults.faults] == ["oscillation"]
