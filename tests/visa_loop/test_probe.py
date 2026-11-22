"""The read-only bring-up probe and the station proposal on backend visa (blueprint v2 7.1, 7.4 L0; WP6.1 AC).

The real ``VisaTransport`` runs over the visa-loop resource manager against the ``lab_station`` simulator: the
probe loads the VISA library, lists the resources, opens and locks the bus, sends queries only, unlocks and closes,
and records every raw answer in ``work/bringup/probe-<UTC>.json``. The AC "visa-loop probe: audit contains only
queries" is ``test_probe_passes_and_the_audit_contains_only_queries``; "proposed station validates and equals the
lab_station inventory" is ``test_proposed_station_validates_and_equals_the_lab_station_inventory``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from b1500_test_agent import bringup
from b1500_test_agent.config import adopt
from b1500_test_agent.models.audit import BUS_EVENTS, TRANSPORT_EVENTS
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.service import B1500Admin
from b1500_test_agent.transport.readonly import is_query
from tests.sim.helpers import load_scenario
from tests.visa_loop.helpers import VisaWorld, bus_factory
from tests.visa_loop.loop import DEFAULT_RESOURCE, LoopBus

RECORD_NAME = re.compile(r"^probe-\d{8}T\d{9}Z(-\d+)?\.json$")
FLEX_PART = ["visa library", "visa resources", "bus", "identity", "inventory", "error queue", "status byte",
             "outputs", "settings", "selectors", "spgu", "cmu CMU1", "release", "wgfmu library", "fault latch"]
"""The probe's lines without ``--wgfmu-session``: the FLEX part, then the WGFMU library probe (a file read, WP10.2)."""


def probe(world: VisaWorld, bus: LoopBus, **kwargs: object) -> ProbeReport:
    return B1500Admin(world.service(bus, **kwargs)).probe()


def statuses(report: ProbeReport) -> dict[str, str]:
    return {c.name: c.status for c in report.checks}


def io_events(world: VisaWorld) -> list:
    return [e for e in world.daily_events() if e.ev in TRANSPORT_EVENTS]


def test_probe_passes_and_the_audit_contains_only_queries(world: VisaWorld) -> None:
    bus = world.bus("lab_station")
    report = probe(world, bus)
    assert report.ok and report.status == "ok" and report.backend == "visa" and not report.simulated, report.checks
    assert [c.name for c in report.checks] == FLEX_PART
    assert all(c.status in ("PASS", "INFO") for c in report.checks), report.checks
    found = statuses(report)
    assert found["visa resources"] == "PASS" and found["identity"] == "PASS" and found["inventory"] == "PASS"
    assert report.identity is not None and report.identity.firmware == "A.06.02.2023.0401"
    assert report.visa_resources == [DEFAULT_RESOURCE] and bus.stats.library == "@ivi"
    library = report.wgfmu_library  # WP10.2: probed as a file (the world's synthetic x64 DLL), never loaded
    assert library is not None and library.loadable and library.machine == "x64" and bus.stats.wgfmu_loads == 0
    assert found["wgfmu library"] == "PASS" and report.wgfmu_channels is None
    # the AC: every instrument I/O of the probe is a single query; nothing else reached the instrument
    events = io_events(world)
    assert events and all(e.ev == "query" and e.cmd is not None and is_query(e.cmd) for e in events), events
    assert {e.cmd for e in events} >= {"*IDN?", "UNT?", "ERRX?", "*STB?", "LOP?", "*LRN? 31", "ERMOD?", "SPST?",
                                       "CORRST? 7,1", "CORRST? 7,2", "CORRST? 7,3", "ADJ? 7,0"}
    assert all(r.command.split()[0].endswith("?") for r in bus.instrument.command_log)
    assert not bus.instrument.source_commands()
    # bus lifecycle: open -> lock -> queries -> unlock -> close, nothing held afterwards
    lifecycle = [e.ev for e in world.daily_events() if e.ev in BUS_EVENTS and e.intent == "probe"]
    assert lifecycle == ["bus_open", "bus_lock", "bus_unlock", "bus_close"]
    assert bus.lock_is_free() and all(s.closed for s in bus.sessions)
    assert (bus.stats.locks, bus.stats.unlocks, bus.stats.clears) == (1, 1, 0)
    # ERRX? answered +0, (the lab firmware form) and counted as empty
    assert bus.stats.signed_errx >= 1 and found["error queue"] == "PASS"
    # raw record: Windows-safe name, the whole report including every exchange
    assert report.record is not None
    path = world.root / report.record
    assert RECORD_NAME.match(path.name) and ":" not in path.name and path.parent == world.root / "work" / "bringup"
    stored = ProbeReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert stored.record == report.record and [e.cmd for e in stored.transcript] == [e.cmd for e in events]
    assert all(e.resp is not None for e in stored.transcript)
    probe_events = [e for e in world.daily_events() if e.ev == "probe"]
    assert len(probe_events) == 1 and probe_events[0].data is not None
    assert probe_events[0].data["record"] == report.record and probe_events[0].data["n_fail"] == 0


def test_inventory_that_differs_from_the_station_profile_fails(world: VisaWorld) -> None:
    station = yaml.safe_load((world.local / "station.yaml").read_text(encoding="utf-8"))
    station["modules"][4]["model"] = "B1511A"  # slot 5: the example's B1511B guess was wrong
    world.write_local("station.yaml", station)
    report = probe(world, world.bus("lab_station"))
    assert not report.ok and report.error_code == "instrument_error"
    inventory = next(c for c in report.checks if c.name == "inventory")
    assert inventory.status == "FAIL" and "slot 5: profile B1511A, installed B1511B" in inventory.detail
    assert any("propose-station" in step for step in report.next_steps)
    assert all(e.ev == "query" for e in io_events(world))


def test_a_foreign_lock_makes_the_probe_busy_with_nothing_sent(world: VisaWorld) -> None:
    world.set_visa(lock_timeout_ms=50)
    bus = world.bus("lab_station")
    with bus.foreign_lock():
        report = probe(world, bus)
    assert not report.ok and report.status == "busy" and report.error_code == "instrument_busy"
    assert statuses(report)["bus"] == "FAIL" and "EasyEXPERT" in " ".join(report.next_steps)
    assert io_events(world) == [] and bus.instrument.command_log == []
    assert statuses(report)["visa library"] == "PASS"


def test_unlisted_resource_warns_and_the_open_fails(world: VisaWorld) -> None:
    world.set_visa(resource="GPIB0::18::INSTR")
    report = probe(world, world.bus("lab_station"))
    found = statuses(report)
    assert found["visa resources"] == "WARN" and found["bus"] == "FAIL" and not report.ok
    assert report.error_code == "transport_error" and report.transcript == []


def test_a_visa_library_that_does_not_load_fails_before_any_open(world: VisaWorld) -> None:
    bus = world.bus("lab_station")

    def broken(library: str) -> object:
        raise OSError("no VISA installed")

    from b1500_test_agent.service import B1500Service
    from b1500_test_agent.transport.factory import make_bus

    service = B1500Service(paths=world.paths, lock_timeout_s=2.0,
                           bus_factory=lambda bundle, sink: make_bus(bundle.settings, sink, rm_factory=broken))
    world.services.append(service)
    report = B1500Admin(service).probe()
    assert [c.name for c in report.checks] == ["visa library", "wgfmu library", "fault latch"]
    assert statuses(report)["visa library"] == "FAIL" and report.error_code == "transport_error"
    assert bus.stats.opens == 0
    # the default WgfmuDll of this factory probes the world's synthetic x64 DLL, but not on Windows: WARN on the Mac
    library = next(c for c in report.checks if c.name == "wgfmu library")
    if sys.platform != "win32":
        assert library.status == "WARN" and "only on Windows" in library.detail, library
    assert report.wgfmu_library is not None and report.wgfmu_library.machine == "x64"


@pytest.mark.parametrize(
    ("seed", "check", "status", "fragment"),
    [
        (lambda s: s.channels.__setitem__(3, s.channels[3].model_copy(update={"output_on": True})), "outputs",
         "FAIL", "slot 3 code 01"),
        (lambda s: setattr(s, "spgu_output_active", True), "spgu", "FAIL", "output is active"),
        (lambda s: (setattr(s, "selector_mode", 1), s.selector_ports.update({0: 2})), "selectors", "WARN",
         "SEL1.OUT1 pgu (rest open)"),
        (lambda s: s.cmu_phase_results.update({7: 1}), "cmu CMU1", "WARN", "failed"),
    ],
)
def test_live_state_findings(world: VisaWorld, seed, check: str, status: str, fragment: str) -> None:
    bus = world.bus("lab_station")
    seed(bus.instrument.state)
    report = probe(world, bus)
    line = next(c for c in report.checks if c.name == check)
    assert line.status == status and fragment in line.detail, line
    assert report.ok is (status != "FAIL")
    assert all(e.ev == "query" for e in io_events(world))


def test_selector_outputs_are_read_only_with_the_selector_control_mode_on(world: VisaWorld) -> None:
    bus = world.bus("lab_station")
    off = probe(world, bus)
    assert off.switch_states is None and "ERSSP" not in " ".join(e.cmd for e in off.transcript)
    bus.instrument.state.selector_mode = 1
    on = probe(world, bus)
    assert on.switch_states == {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open"}
    assert [e.cmd for e in on.transcript if e.cmd.startswith("ERSSP")] == [f"ERSSP? {p}" for p in range(4)]
    assert statuses(on)["selectors"] == "PASS"


def test_earlier_errors_are_drained_and_reported(world: VisaWorld) -> None:
    bus = world.bus("lab_station")
    bus.instrument.handle("BOGUS")  # an earlier client left error 100 in the queue
    report = probe(world, bus)
    line = next(c for c in report.checks if c.name == "error queue")
    assert line.status == "WARN" and "100" in line.detail and report.ok
    assert [e.resp for e in report.transcript if e.cmd == "ERRX?"][-1].startswith("+0,")


def test_a_latched_fault_fails_the_probe(world: VisaWorld) -> None:
    world.state_dir.mkdir(parents=True, exist_ok=True)
    (world.state_dir / "fault.json").write_text('{"reason": "test", "set_at": "2026-11-17T00:00:00Z"}',
                                                encoding="utf-8")
    report = probe(world, world.bus("lab_station"))
    assert statuses(report)["fault latch"] == "FAIL" and not report.ok
    assert statuses(report)["identity"] == "PASS"  # read-only: the probe still reads the instrument


def test_proposed_station_validates_and_equals_the_lab_station_inventory(world: VisaWorld) -> None:
    bus = world.bus("lab_station")
    service = world.service(bus)
    proposal = bringup.propose_station(service)
    assert proposal.ok and proposal.backend == "visa" and not proposal.simulated, proposal.message
    path = world.root / "work" / "bringup" / "station.proposed.yaml"
    assert proposal.path == "work/bringup/station.proposed.yaml" and path.is_file()
    station = StationProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    scenario = load_scenario("lab_station")
    assert {(m.slot, m.model) for m in station.modules} == {(s.slot, s.model) for s in scenario.slots}
    assert [m.alias for m in station.modules] == ["SPGU1", "WGFMU1", "SMU3", "SMU4", "SMU5", "SMU6", "CMU1"]
    assert all(s.certainty == "unverified" for s in station.switches)
    selectors = [s for s in station.switches if s.kind == "selector_16440a"]
    assert selectors and all(v is None for s in selectors for p in s.ports.values() for v in p.inputs.values())
    # the local station is the example's copy (config init), which already names the lab inventory
    assert proposal.local == "config/local/station.yaml" and proposal.matches_local is True and proposal.diff == []
    assert all(e.ev == "query" for e in io_events(world))
    assert {e.cmd for e in io_events(world)} == {"*IDN?", "UNT?"}
    # the human adopts it; the configuration stays valid and the next proposal matches the local file
    adopted = adopt(path, "station", world.paths)
    assert adopted.ok and adopted.adopted and adopted.backup == "config/local/station.yaml.bak"
    assert adopted.check is not None and adopted.check.ok and adopted.check.backend == "visa"
    again = bringup.propose_station(world.service(bus))
    assert again.ok and again.matches_local is True and again.diff == []


def test_proposal_follows_a_different_installed_module(world: VisaWorld, tmp_path: Path) -> None:
    scenario = load_scenario("lab_station")
    data = scenario.model_dump(mode="json")
    data["slots"][4]["model"] = "B1511A"  # the real slot 5 is a B1511A
    data["slots"] = [s for s in data["slots"] if s["slot"] != 2]  # and no WGFMU
    bus = LoopBus(world.bus_dir, type(scenario).model_validate(data))
    proposal = bringup.propose_station(world.service(bus))
    assert proposal.ok and proposal.station is not None
    assert {m.slot: m.model for m in proposal.station.modules}[5] == "B1511A"
    assert 2 not in {m.slot for m in proposal.station.modules}
    assert {s.id for s in proposal.station.switches} >= {"SEL1", "SEL2"}
    assert not {"RSU201", "RSU202"} & {s.id for s in proposal.station.switches}  # their WGFMU is gone
    assert any("RSU201" in note for note in proposal.notes)
    assert proposal.diff and any(line.startswith("+") and "B1511A" in line for line in proposal.diff)


def test_bus_factory_helper_is_the_real_make_bus(world: VisaWorld) -> None:
    """Guard for the tests above: the probe runs through the real VisaTransport (no simulator shortcut)."""
    bus = world.bus("lab_station")
    service = world.service(bus)
    session = service.executor.session(service.config.get())
    from b1500_test_agent.transport.base import unwrap
    from b1500_test_agent.transport.visa import VisaTransport

    assert isinstance(unwrap(session.transport), VisaTransport)
    assert bus_factory(bus) is not None
