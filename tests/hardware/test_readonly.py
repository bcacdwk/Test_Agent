"""The hardware suite is read-only (blueprint v2 7.1 ``tests/hardware/`` "never sources", 8.1 ``visa_loop/`` "probe
sends only queries (audit spy)", decision 24, guardrail 10.0.1; WP6.4). An ordinary CI test, not a hardware test.

A child pytest runs the hardware tests exactly as the owner runs them on the lab PC (``B1500_HW=1``, backend visa
from ``config/local/`` of a temporary repository, the real ``VisaTransport``), over the visa-loop
(``loop_plugin.py`` injects only the VISA resource manager). Afterwards four spies look at what happened:

1. audit: every instrument I/O event the suite caused (``AuditingTransport`` -> ``data/state/audit/``) is a single
   query, and every bus session was opened, locked, unlocked and closed;
2. wire: every command the simulated instrument received (its command log, shared with the child through the
   bus state file) is a single query; no device clear, nothing that sets an output level;
3. lab: none of the setting commands the lab's own scripts send (``tests/fixtures/lab/lwp_*.txt``, the anonymized
   lwp transcripts of WP6.2) reached the instrument, and the probe saw the lab's firmware (``idvg_real.csv``);
4. files: nothing under ``config/``, ``recipes/``, ``validation/`` or ``data/runs/`` changed or appeared; the suite
   left only its probe records in ``work/bringup/`` and audit/state files in ``data/state/``.

Two stations: the lab station at rest (the probe tests pass, the record tests find no record and skip) and one with
an SMU output left on and an earlier client's error in the queue (the suite reports the output, drains the error,
re-probes, and still only reads: the output is still on afterwards).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.models.audit import BUS_EVENTS, TRANSPORT_EVENTS
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.transport.readonly import is_query
from tests.hardware.rehearsal import changes, run_on_loop, snapshot
from tests.unit.lab_fixtures import READ, SEQUENCES, load_sequence, real_idvg_header
from tests.visa_loop.helpers import VisaWorld, make_visa_world
from tests.visa_loop.loop import LoopBus

PROBE_TESTS = 15
RECORD_TESTS = 13


def lab_setting_mnemonics() -> set[str]:
    """Mnemonics of the setting commands the lab scripts write (``*RST``, ``CN``, ``DV``, ``ERSSP`` ...)."""
    found = set()
    for name in SEQUENCES:
        for step in load_sequence(name).steps:
            if step.command != READ and not step.is_query:
                found.add(step.mnemonic)
    return found


def lab_firmware() -> str:
    """The lab instrument's firmware from the anonymized lab curve header (``InstrumentID: B1500A,<firmware>``)."""
    line = next(h for h in real_idvg_header() if h.startswith("InstrumentID:"))
    return line.split(",")[-1].strip()


@pytest.fixture
def world(tmp_path: Path):
    w = make_visa_world(tmp_path / "w")
    yield w
    w.close()


class Spies:
    """Snapshots before the child run and the spies after it."""

    def __init__(self, world: VisaWorld, bus: LoopBus) -> None:
        self.world, self.bus = world, bus
        world.env(bus)  # copies recipes/ into the world before the snapshot
        bus.sync_in()
        self.first_seq = max((r.seq for r in bus.instrument.command_log), default=-1)
        self.repo_before = snapshot(world.root)
        self.data_before = snapshot(world.data)

    def wire(self) -> list:
        self.bus.sync_in()  # the child saved the instrument state (and its command log) when it unlocked
        return [r for r in self.bus.instrument.command_log if r.seq > self.first_seq]

    def check(self) -> list:
        """The four spies of the module docstring; returns the suite's instrument commands."""
        world = self.world
        # 1. audit
        events = world.daily_events()
        io = [e for e in events if e.ev in TRANSPORT_EVENTS]
        assert io and all(e.ev == "query" and e.cmd is not None and is_query(e.cmd) for e in io), \
            [(e.ev, e.cmd) for e in io if not (e.ev == "query" and e.cmd and is_query(e.cmd))]
        lifecycle = [e.ev for e in events if e.ev in BUS_EVENTS]
        sessions = lifecycle.count("bus_open")
        assert sessions >= 1 and lifecycle == ["bus_open", "bus_lock", "bus_unlock", "bus_close"] * sessions, lifecycle
        assert not any(e.run for e in events), "the suite ran a recipe"
        # 2. wire
        wire = self.wire()
        assert wire and all(is_query(r.command) for r in wire), [r.command for r in wire if not is_query(r.command)]
        assert not [r for r in wire if r.mnemonic.startswith("<")], "an interface event (device clear) reached it"
        assert not [r for r in wire if r.source], "a command that sets an output level reached the instrument"
        assert [r.command for r in wire] == [e.cmd for e in io]
        # 3. lab
        assert not {r.mnemonic for r in wire} & lab_setting_mnemonics()
        # 4. files
        created, changed, removed = changes(self.repo_before, snapshot(world.root))
        assert not changed and not removed, (changed, removed)
        assert created and all(p.startswith("work/bringup/probe-") and p.endswith(".json") for p in created), created
        created, changed, removed = changes(self.data_before, snapshot(world.data))
        assert all(p.startswith("state/") for p in created + changed + removed), (created, changed, removed)
        return wire

    def probe_records(self) -> list[ProbeReport]:
        folder = self.world.root / "work" / "bringup"
        return [ProbeReport.model_validate_json(p.read_text(encoding="utf-8"))
                for p in sorted(folder.glob("probe-*.json"))]


def test_the_suite_passes_on_a_station_at_rest_and_only_reads(world: VisaWorld, tmp_path: Path) -> None:
    bus = world.bus("lab_station")
    spies = Spies(world, bus)
    run = run_on_loop(world, bus, tmp_path)
    assert run.returncode == 0, run.output[-4000:]
    passed = run.with_status("passed")
    assert len(passed) == PROBE_TESTS and all(n.startswith("test_probe.py::") for n in passed), run.outcomes
    skipped = run.with_status("skipped")
    assert len(skipped) == RECORD_TESTS and all(n.startswith("test_records.py::") for n in skipped)
    assert all("no record" in run.outcomes[n].message for n in skipped), {n: run.outcomes[n].message for n in skipped}
    assert "VISA-LOOP REHEARSAL" in run.output and "hardware suite: 28 hardware test(s) selected" in run.output
    spies.check()
    (record,) = spies.probe_records()  # one probe: the error queue was empty, no second drain
    assert record.ok and record.backend == "visa" and not record.simulated
    assert record.identity is not None and record.identity.firmware == lab_firmware()
    bus.instrument.assert_safe()


def test_the_suite_reports_a_station_not_at_rest_and_still_only_reads(world: VisaWorld, tmp_path: Path) -> None:
    bus = world.bus("lab_station")
    state = bus.instrument.state
    state.channels[3] = state.channels[3].model_copy(update={"output_on": True})  # an SMU left on by another client
    state.selector_mode = 1  # 16440A control mode on, SEL1.OUT1 left on the SPGU path
    state.selector_ports[0] = 2
    bus.touch()
    bus.sync_out()
    spies = Spies(world, bus)
    run = run_on_loop(world, bus, tmp_path, "tests/hardware/test_probe.py")
    assert run.returncode == 1, run.output[-4000:]
    failed = ["test_probe.py::test_every_output_switch_is_off", "test_probe.py::test_no_probe_line_fails",
              "test_probe.py::test_selector_outputs_are_at_rest"]
    assert run.with_status("failed") == failed, run.outcomes
    assert "slot 3 code 01" in run.outcomes[failed[0]].message
    assert "SEL1.OUT1 pgu (rest open)" in run.outcomes[failed[2]].message
    assert len(run.with_status("passed")) == PROBE_TESTS - len(failed)
    wire = spies.check()
    assert [r.command for r in wire if r.mnemonic == "ERSSP?"] == [f"ERSSP? {port}" for port in range(4)]
    (record,) = spies.probe_records()
    assert not record.ok and record.switch_states is not None and record.switch_states["SEL1.OUT1"] == "pgu"
    bus.sync_in()  # the suite reported the station as it found it and changed nothing
    assert bus.instrument.state.channels[3].output_on and bus.instrument.state.selector_ports[0] == 2
