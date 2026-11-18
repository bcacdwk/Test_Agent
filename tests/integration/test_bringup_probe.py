"""The read-only probe and the station proposal through ``B1500Service`` on the simulator (blueprint v2 7.1, WP6.1):
the read-only session refuses every setting command, the probe stops at a non-B1500A, the proposal fits the base
profile to the live inventory (aliases, unknown models, switches, cables) and never writes ``config/``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from b1500_test_agent import bringup
from b1500_test_agent.models.station import InstalledModule, ModuleInventory, StationProfile
from b1500_test_agent.service import B1500Admin
from b1500_test_agent.transport.readonly import ReadOnlyViolation
from tests.integration.helpers import REPO_ROOT, World

EXAMPLE = StationProfile.model_validate(
    yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8")))


def test_the_read_only_session_refuses_setting_commands_and_still_releases_the_bus(world: World) -> None:
    service = world.service()
    session = service.executor.session(service.config.get())
    with pytest.raises(ReadOnlyViolation), session.read_only("test") as driver:
        assert driver.identify().model == "B1500A"
        driver.set_format(1, 1)  # FMT 1,1: refused before anything is written
    assert not session.bus_open and not session.lock.is_held()
    assert [r.command for r in world.sim_log()] == ["*IDN?"]
    for refused in (lambda d: d.zero(), lambda d: d.disconnect(), lambda d: d.reset(), lambda d: d.device_clear(),
                    lambda d: d.set_auto_calibration(True), lambda d: d.status_byte(poll=True)):
        with pytest.raises(ReadOnlyViolation), session.read_only("test") as driver:
            refused(driver)
    assert [r.command for r in world.sim_log()] == ["*IDN?"]
    assert service.station_status().ok  # the status snapshot reads through the same read-only link


def test_the_probe_sends_nothing_after_a_foreign_identity(world: World) -> None:
    world.use_faults("idn", [{"kind": "idn_override", "idn": "Keysight Technologies,E4980A,0,A.02.00"}])
    report = B1500Admin(world.service()).probe()
    identity = next(c for c in report.checks if c.name == "identity")
    assert identity.status == "FAIL" and "not a B1500A" in identity.detail and not report.ok
    assert [e.cmd for e in report.transcript] == ["*IDN?"]
    assert not any(c.name == "inventory" for c in report.checks)


def test_the_probe_on_an_invalid_configuration_answers_invalid_config(world: World) -> None:
    world.write_config("policy.yaml", {"hard_limits": {"max_abs_voltage_v": 100}})
    report = B1500Admin(world.service()).probe()
    assert not report.ok and report.error_code == "invalid_config" and report.checks == []
    assert world.sim_log() == []


def test_proposal_on_the_simulator_is_based_on_the_example_and_writes_only_work(world: World) -> None:
    world.use_scenario("lab_station")
    before = sorted(p.relative_to(world.root).as_posix() for p in (world.root / "config").rglob("*"))
    proposal = bringup.propose_station(world.service())
    assert proposal.ok and proposal.simulated and proposal.base == "config/station.example.yaml"
    assert proposal.diff is None and proposal.local is None and proposal.matches_local is None
    assert proposal.station is not None and proposal.station.name == "lab-b1500a"
    assert proposal.station.notes[-1].startswith(bringup.PROVENANCE) and "SIMULATED" in proposal.station.notes[-1]
    assert sorted(p.relative_to(world.root).as_posix() for p in (world.root / "config").rglob("*")) == before
    assert list(world.cfg.rglob("*.yaml")) == [world.cfg / "settings.yaml"]
    assert (world.root / "work" / "bringup" / "station.proposed.yaml").is_file()
    again = bringup.propose_station(world.service())
    provenance = [n for n in again.station.notes if n.startswith(bringup.PROVENANCE)] if again.station else []
    assert len(provenance) == 1  # a new proposal replaces the old provenance note


def test_proposal_keeps_recorded_wiring_when_the_inventory_is_unchanged(world: World) -> None:
    world.use_scenario("lab_station")
    station = EXAMPLE.model_dump(mode="json")
    station["name"] = "lab"
    sel1 = next(s for s in station["switches"] if s["id"] == "SEL1")
    sel1["ports"]["OUT1"]["inputs"] = {"smu": 3, "pgu": 101}
    sel1["ports"]["OUT2"]["inputs"] = {"smu": 4, "pgu": 102}
    sel1["certainty"] = "verified"
    world.write_config("station.yaml", station)
    proposal = bringup.propose_station(world.service())
    assert proposal.ok and proposal.matches_local is True and proposal.station is not None
    kept = proposal.station.switch("SEL1")
    assert kept is not None and kept.certainty == "verified" and kept.ports["OUT1"].inputs["pgu"] == 101


def test_modules_fit_the_inventory_with_aliases_and_notes() -> None:
    inventory = ModuleInventory(modules=[
        InstalledModule(slot=1, model="B1525A", revision="0"),
        InstalledModule(slot=3, model="B1517A", revision="0"),
        InstalledModule(slot=5, model="B1511A", revision="0"),
        InstalledModule(slot=8, model="B1517A", revision="0"),
        InstalledModule(slot=9, model="B9999X", revision="0"),
    ])
    notes: list[str] = []
    modules = bringup._modules(inventory, EXAMPLE, notes)
    assert [(m.slot, m.model, m.type, m.alias, m.channels) for m in modules] == [
        (1, "B1525A", "HVSPGU", "SPGU1", [101, 102]),
        (3, "B1517A", "HRSMU", "SMU3", [3]),
        (5, "B1511A", "MPSMU", "SMU5", [5]),
        (8, "B1517A", "HRSMU", "SMU8", [8]),
    ]
    assert "slot 9: model B9999X is not a module type this kernel knows; left out (a reviewed code change adds it)" \
        in notes
    assert "slot 5: B1511B in the base profile, B1511A installed" in notes
    assert "slot 8: B1517A added (not in the base profile)" in notes
    assert any(n.startswith("slot 2: B1530A in the base profile, nothing installed") for n in notes)


def test_switches_lose_unresolvable_inputs_and_index_bound_switches_drop_out() -> None:
    inventory = ModuleInventory(modules=[InstalledModule(slot=s, model=m, revision="0")
                                         for s, m in ((1, "B1525A"), (3, "B1517A"), (4, "B1517A"), (5, "B1511B"),
                                                      (7, "B1520A"))])
    notes: list[str] = []
    modules = bringup._modules(inventory, EXAMPLE, notes)
    fitted = {s.id: bringup._fit_switch(s, modules, force_unverified=False, notes=notes) for s in EXAMPLE.switches}
    assert fitted["RSU201"] is None and fitted["RSU202"] is None  # no WGFMU
    assert fitted["SCUU1"] is None  # its OUT1 belongs to SMU6, which is gone
    assert fitted["ASU3"] is not None and fitted["SEL1"] is not None
    assert any("RSU201: its channel 201 is not installed" in n for n in notes)
    station = StationProfile.model_validate({**EXAMPLE.model_dump(mode="json"),
                                             "modules": [m.model_dump(mode="json") for m in modules],
                                             "switches": [s for s in fitted.values() if s is not None],
                                             "topology": {**EXAMPLE.topology.model_dump(mode="json"),
                                                          "cables": {"SMU3": {}, "SMU4": {}, "SMU5": {}}}})
    assert {s.id for s in station.switches} == {"SEL1", "SEL2", "ASU3", "ASU4"}


def test_a_wired_input_whose_module_is_gone_becomes_null_and_unverified(tmp_path: Path) -> None:
    data = EXAMPLE.model_dump(mode="json")
    sel1 = next(s for s in data["switches"] if s["id"] == "SEL1")
    sel1["ports"]["OUT1"]["inputs"] = {"smu": 5, "pgu": 101}
    sel1["certainty"] = "verified"
    sel1["ports"]["OUT2"]["inputs"] = {"smu": 6, "pgu": 102}
    base = StationProfile.model_validate(data)
    inventory = ModuleInventory(modules=[InstalledModule(slot=s, model=m, revision="0")
                                         for s, m in ((3, "B1517A"), (4, "B1517A"), (5, "B1511B"), (6, "B1511B"))])
    notes: list[str] = []
    modules = bringup._modules(inventory, base, notes)
    fitted = bringup._fit_switch(base.switch("SEL1"), modules, force_unverified=False, notes=notes)  # type: ignore[arg-type]
    assert fitted is not None and fitted["certainty"] == "unverified"
    assert fitted["ports"]["OUT1"]["inputs"] == {"smu": 5, "pgu": None}
    assert "switch SEL1.OUT1: input pgu -> channel 101 is not installed; set to null (unknown)" in notes
