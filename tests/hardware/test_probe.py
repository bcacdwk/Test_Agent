"""Stage L0 on the real B1500A: the read-only probe (blueprint v2 7.1 ``doctor --probe``, 7.4 L0; WP6.4).

The checks reuse WP6.1's probe (``B1500Admin.probe``, the machinery of ``b1500 doctor --probe``): it opens the bus,
takes the exclusive VISA lock, sends single queries through ``ReadOnlyTransport`` (which refuses anything else),
unlocks and closes, and writes ``work/bringup/probe-<UTC>.json``. Nothing here sets, sources or resets anything;
``test_readonly.py`` runs this module against the visa-loop and proves that only queries reach the instrument.

Pass criteria (7.4 L0): identity names a B1500A, ``UNT?`` equals ``config/local/station.yaml`` (R-INV-01), the error
queue drains to empty, ``LOP?`` reports every output off, declared selector outputs are at rest, ``SPST?`` = 0,
the MFCMU correction state is readable, no fault is latched and no probe line fails.

Run on the lab PC (owner present): ``$env:B1500_HW = "1"; uv run pytest -m "hardware and hw_l0" -rs``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import parse_spst
from b1500_test_agent.driver.errors import parse_errx
from b1500_test_agent.models.audit import BUS_EVENTS, TRANSPORT_EVENTS
from b1500_test_agent.models.bringup import ProbeCheck, ProbeReport
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL
from b1500_test_agent.service import B1500Admin, B1500Service
from b1500_test_agent.transport.readonly import is_query
from tests.hardware.support import audit_events_since

pytestmark = [pytest.mark.hardware, pytest.mark.hw_l0]

SELECTOR_KIND = "selector_16440a"
BASE_QUERIES = (flex.IDN_Q, flex.UNT_Q, flex.ERRX_Q, flex.STB_Q, flex.LOP_Q)
"""Queries every probe of a B1500A sends."""


def line(report: ProbeReport, name: str) -> ProbeCheck:
    found = [c for c in report.checks if c.name == name]
    assert found, f"the probe has no '{name}' line; lines: {[c.name for c in report.checks]} ({report.message})"
    return found[0]


def answers(report: ProbeReport, cmd: str) -> list[str | None]:
    return [e.resp for e in report.transcript if e.cmd == cmd]


def installed_slots(report: ProbeReport, module_type: str) -> list[int]:
    assert report.inventory is not None, "the probe read no inventory"
    return [m.slot for m in report.inventory.modules if MODULE_TYPE_BY_MODEL.get(m.model) == module_type]


# -- configuration and bus ---------------------------------------------------------------------------------------------


def test_configuration_is_local_and_valid_on_visa(hw_config: ConfigBundle) -> None:
    assert hw_config.backend == "visa"
    for item in ("settings", "station", "policy"):
        used = hw_config.files[item]
        assert used.source == "local" and used.path == f"config/local/{item}.yaml", used


def test_visa_library_loads_and_the_resource_is_reachable(probe_report: ProbeReport) -> None:
    assert line(probe_report, "visa library").status == "PASS"
    listed = line(probe_report, "visa resources")
    assert listed.status in ("PASS", "WARN"), listed
    if listed.status == "WARN":  # some VISA stacks list a GPIB device only after a scan: the open must then work
        assert line(probe_report, "bus").status == "PASS", f"{listed.detail}; and the bus did not open"
    else:
        assert probe_report.visa_resources and probe_report.resource in probe_report.visa_resources


def test_bus_opens_with_the_exclusive_lock_and_is_released(probe_report: ProbeReport) -> None:
    for name in ("bus", "release"):
        check = line(probe_report, name)
        assert check.status == "PASS", check
    assert probe_report.backend == "visa" and not probe_report.simulated


# -- instrument state --------------------------------------------------------------------------------------------------


def test_identity_names_a_b1500a(probe_report: ProbeReport) -> None:
    assert line(probe_report, "identity").status == "PASS"
    identity = probe_report.identity
    assert identity is not None and "B1500A" in identity.model, identity
    assert identity.firmware, f"no firmware revision in {identity.raw!r}"  # recorded in the probe record


def test_installed_modules_equal_the_local_station_profile(probe_report: ProbeReport, hw_config: ConfigBundle) -> None:
    check = line(probe_report, "inventory")
    assert check.status == "PASS", check  # WARN: modules installed that config/local/station.yaml does not list
    assert probe_report.inventory is not None
    installed = {m.slot: m.model for m in probe_report.inventory.modules}
    assert installed == {m.slot: m.model for m in hw_config.station.modules}


def test_error_queue_is_drained(probe_report: ProbeReport, hw_service: B1500Service) -> None:
    check = line(probe_report, "error queue")
    assert check.status in ("PASS", "WARN"), check
    final = answers(probe_report, flex.ERRX_Q)[-1]
    assert final is not None and parse_errx(final) is None, f"the last ERRX? answer is not empty: {final!r}"
    if check.status == "WARN":  # errors left by an earlier client were drained; a second drain must find none
        again = B1500Admin(hw_service).probe()
        repeat = line(again, "error queue")
        assert repeat.status == "PASS", f"errors appear again after a drain: {repeat.detail} (first: {check.detail})"


def test_status_byte_has_no_error_bit(probe_report: ProbeReport) -> None:
    check = line(probe_report, "status byte")
    assert check.status == "PASS", check


def test_every_output_switch_is_off(probe_report: ProbeReport) -> None:
    check = line(probe_report, "outputs")
    assert check.status == "PASS", check
    lop = answers(probe_report, flex.LOP_Q)
    assert lop and lop[-1] is not None


def test_selector_outputs_are_at_rest(probe_report: ProbeReport, hw_config: ConfigBundle) -> None:
    check = line(probe_report, "selectors")
    assert check.status in ("PASS", "INFO"), check  # WARN: an output is not in its rest state
    if probe_report.switch_states is None:
        return  # no selector declared, or selector control mode off (power-on state; outputs not readable)
    rest = {f"{s.id}.{output}": s.rest for s in hw_config.station.switches if s.kind == SELECTOR_KIND
            for output in s.ports}
    assert probe_report.switch_states and set(probe_report.switch_states) <= set(rest)
    assert all(state == rest[target] for target, state in probe_report.switch_states.items()), \
        probe_report.switch_states


def test_spgu_output_is_idle(probe_report: ProbeReport) -> None:
    check = line(probe_report, "spgu")
    if not installed_slots(probe_report, "HVSPGU"):
        assert check.status == "INFO", check
        pytest.skip("no SPGU installed")
    assert check.status == "PASS", check
    spst = answers(probe_report, flex.SPST_Q)
    assert spst and spst[-1] is not None and parse_spst(spst[-1]) is False, f"SPST? answered {spst!r}, not 0"


def test_cmu_correction_state_is_readable(probe_report: ProbeReport) -> None:
    slots = installed_slots(probe_report, "MFCMU")
    if not slots:
        pytest.skip("no MFCMU installed")
    lines = [c for c in probe_report.checks if c.name.startswith("cmu ")]
    assert len(lines) == len(slots), lines
    assert all(c.status in ("INFO", "WARN") for c in lines), lines  # WARN: last phase compensation failed/aborted
    assert probe_report.cmu_corrections is not None and len(probe_report.cmu_corrections) == len(slots)
    for alias, live in probe_report.cmu_corrections.items():
        assert set(live.corr_state) == set(flex.CORRECTION_CODES), (alias, live)
    for slot in slots:
        for query in [flex.corrst_q(slot, name) for name in flex.CORRECTION_CODES] + [
                flex.adj_q(slot, flex.ADJ_READ_LAST)]:
            read = answers(probe_report, query)
            assert read and all(a is not None for a in read), f"{query} not answered"


def test_no_fault_is_latched(probe_report: ProbeReport) -> None:
    check = line(probe_report, "fault latch")
    assert check.status == "PASS", check


def test_no_probe_line_fails(probe_report: ProbeReport) -> None:
    failed = [c for c in probe_report.checks if c.status == "FAIL"]
    assert probe_report.ok and not failed, failed


# -- read-only evidence ------------------------------------------------------------------------------------------------


def test_the_probe_sent_single_queries_only(probe_report: ProbeReport, hw_config: ConfigBundle) -> None:
    transcript = probe_report.transcript
    assert transcript, "the probe recorded no exchange"
    assert all(is_query(e.cmd) for e in transcript), [e.cmd for e in transcript if not is_query(e.cmd)]
    assert all(e.resp is not None and e.error is None for e in transcript), [e for e in transcript if e.error]
    assert set(BASE_QUERIES) <= {e.cmd for e in transcript}
    assert probe_report.taken_at is not None
    events = audit_events_since(hw_config.paths.state_dir, probe_report.taken_at, intent="probe")
    io = [e for e in events if e.ev in TRANSPORT_EVENTS]
    assert io and all(e.ev == "query" and e.cmd is not None and is_query(e.cmd) for e in io), \
        [(e.ev, e.cmd) for e in io if e.ev != "query"]
    lifecycle = [e.ev for e in events if e.ev in BUS_EVENTS]
    if hw_config.settings.visa.exclusive_lock:
        assert "bus_lock" in lifecycle and "bus_unlock" in lifecycle[lifecycle.index("bus_lock"):], lifecycle


def test_the_probe_record_holds_the_whole_report(probe_report: ProbeReport, hw_config: ConfigBundle) -> None:
    assert probe_report.record is not None, "the probe record was not written (work directory not writable?)"
    path = hw_config.paths.repo_root / Path(probe_report.record)
    stored = ProbeReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert stored.record == probe_report.record and stored.backend == "visa" and not stored.simulated
    assert [e.cmd for e in stored.transcript] == [e.cmd for e in probe_report.transcript]
