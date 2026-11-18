"""``make_bus`` (blueprint v2 2.4, replaces v1's ``make_transport``): sim by default, visa only when the settings say
so, the FLEX link always audited, ``Bus.wgfmu`` empty until WP10.1, nothing opened."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.config import load_config
from b1500_test_agent.models.sim import Oscillation, SimFaultProfile
from b1500_test_agent.models.station import Settings
from b1500_test_agent.paths import Paths
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import Bus, TransportError, state_hooks
from b1500_test_agent.transport.factory import make_bus
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.visa import VisaTransport


def test_committed_config_makes_an_audited_sim_bus(repo_paths: Paths, tmp_path: Path) -> None:
    bundle = load_config(repo_paths)
    sink = MemoryAuditSink()
    bus = make_bus(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
                   state_dir=tmp_path / "state")
    assert isinstance(bus, Bus) and bus.wgfmu is None
    transport = bus.flex
    assert isinstance(transport, AuditingTransport) and isinstance(transport.inner, SimTransport)
    assert transport.backend == "sim" and transport.resource == "SIM::nmos_basic"
    assert transport.inner.state_file == tmp_path / "state" / "sim" / "nmos_basic.state.json"
    assert sink.events == []  # nothing is opened by the factory
    transport.open()
    transport.lock()
    assert transport.query("*IDN?").startswith("Keysight Technologies,B1500A")
    transport.unlock()
    transport.close()
    assert [e.ev for e in sink.events] == ["bus_open", "bus_lock", "query", "bus_unlock", "bus_close"]
    hooks = state_hooks(transport)
    assert hooks is transport.inner
    hooks.save_state()
    assert transport.inner.state_file.is_file()


def test_default_settings_never_select_visa(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    bus = make_bus(Settings(), MemoryAuditSink(), scenario=bundle.sim_scenario)
    assert isinstance(bus.flex.inner, SimTransport)
    with pytest.raises(TransportError, match="needs the scenario"):
        make_bus(Settings(), MemoryAuditSink())


def test_visa_only_when_the_settings_say_so() -> None:
    bus = make_bus(Settings(backend="visa"), MemoryAuditSink())
    transport = bus.flex
    assert isinstance(transport.inner, VisaTransport) and transport.backend == "visa"
    assert not transport.inner.is_open and bus.wgfmu is None
    assert state_hooks(transport) is None  # never opened: no hardware is touched here


def test_visa_takes_an_injected_resource_manager_and_refuses_sim_arguments(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)

    def factory(library: str) -> object:  # never called: nothing is opened here
        raise AssertionError(library)

    bus = make_bus(Settings(backend="visa"), MemoryAuditSink(), rm_factory=factory)
    assert bus.flex.inner._rm_factory is factory
    with pytest.raises(TransportError):
        make_bus(Settings(backend="visa"), MemoryAuditSink(), scenario=bundle.sim_scenario)
    with pytest.raises(TransportError, match="resource manager"):
        make_bus(bundle.settings, MemoryAuditSink(), scenario=bundle.sim_scenario, rm_factory=factory)


def test_scenario_must_match_the_settings(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    other = bundle.sim_scenario.model_copy(update={"name": "other"})
    with pytest.raises(TransportError, match="not the configured"):
        make_bus(bundle.settings, MemoryAuditSink(), scenario=other)


def test_fault_profile_or_list_activates_faults(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    profile = SimFaultProfile(name="osc", faults=[Oscillation()])
    for faults in (profile, [Oscillation()]):
        bus = make_bus(bundle.settings, MemoryAuditSink(), scenario=bundle.sim_scenario, faults=faults)
        assert [f.kind for f in bus.flex.inner.instrument.faults.faults] == ["oscillation"]
