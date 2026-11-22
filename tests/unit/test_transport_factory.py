"""``make_bus`` (blueprint v2 2.4, replaces v1's ``make_transport``): sim by default, visa only when the settings say
so, the FLEX link always audited, ``Bus.wgfmu`` the audited simulated WGFMU library on the same simulated instrument
(WP10.1) or, on visa, the audited ctypes binding ``WgfmuDll`` of ``settings.wgfmu.library`` (WP10.2), nothing opened
and nothing loaded."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.config import load_config
from b1500_test_agent.models.sim import Oscillation, SimFaultProfile, WgfmuDllMissing
from b1500_test_agent.models.station import Settings
from b1500_test_agent.paths import Paths
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import Bus, TransportError, state_hooks
from b1500_test_agent.transport.factory import make_bus
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.visa import VisaTransport
from b1500_test_agent.transport.wgfmu import AuditingWgfmu, WgfmuApi
from b1500_test_agent.transport.wgfmu.dll import WgfmuDll, library_path


def test_committed_config_makes_an_audited_sim_bus(repo_paths: Paths, tmp_path: Path) -> None:
    bundle = load_config(repo_paths)
    sink = MemoryAuditSink()
    bus = make_bus(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
                   state_dir=tmp_path / "state")
    assert isinstance(bus, Bus) and isinstance(bus.wgfmu, AuditingWgfmu) and isinstance(bus.wgfmu, WgfmuApi)
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
    sink = MemoryAuditSink()
    bus = make_bus(Settings(backend="visa"), sink)
    transport = bus.flex
    assert isinstance(transport.inner, VisaTransport) and transport.backend == "visa"
    assert not transport.inner.is_open
    assert state_hooks(transport) is None  # never opened: no hardware is touched here
    # WP10.2: the WGFMU library binding of the default path, audited, constructed and never loaded here
    assert isinstance(bus.wgfmu, AuditingWgfmu) and bus.wgfmu.backend == "visa"
    library = bus.wgfmu.inner
    assert isinstance(library, WgfmuDll) and not library.loaded
    assert library.path == library_path(Settings()) and library.path.endswith("wgfmu.dll")
    assert sink.events == []


def test_visa_takes_an_injected_wgfmu_library_and_sim_refuses_one(repo_paths: Paths) -> None:
    made: list[str] = []

    def factory(path: str) -> WgfmuDll:
        made.append(path)
        return WgfmuDll(path, loader=lambda p: (_ for _ in ()).throw(AssertionError(p)))  # never loaded here

    settings = Settings.model_validate({"backend": "visa", "wgfmu": {"library": "D:/keysight/wgfmu.dll"}})
    bus = make_bus(settings, MemoryAuditSink(), wgfmu_factory=factory)
    assert made == ["D:/keysight/wgfmu.dll"] and isinstance(bus.wgfmu, AuditingWgfmu)
    bundle = load_config(repo_paths)
    with pytest.raises(TransportError, match="WGFMU library binding"):
        make_bus(bundle.settings, MemoryAuditSink(), scenario=bundle.sim_scenario, wgfmu_factory=factory)


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


def test_sim_bus_carries_the_audited_wgfmu_library_on_the_same_instrument(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    sink = MemoryAuditSink()
    bus = make_bus(bundle.settings, sink, scenario=bundle.sim_scenario)
    assert isinstance(bus.wgfmu, AuditingWgfmu) and bus.wgfmu.backend == "sim" and bus.wgfmu.sink is sink
    library = bus.wgfmu.inner
    assert isinstance(library, SimWgfmu) and library._inst is bus.flex.inner.instrument
    assert bus.flex.inner.instrument.wgfmu_unit is library
    bus.flex.open()
    bus.wgfmu.open_session(bus.flex.resource)  # the FLEX link is open but not locked
    assert bus.wgfmu.channel_ids() == [201, 202]  # lab layout: WGFMU in slot 2
    bus.wgfmu.close_session()
    bus.flex.close()
    assert [e.ev for e in sink.events] == ["bus_open", "wgfmu_call", "wgfmu_call", "wgfmu_call", "bus_close"]
    without = make_bus(bundle.settings, MemoryAuditSink(), scenario=bundle.sim_scenario, faults=[WgfmuDllMissing()])
    assert without.wgfmu is None
