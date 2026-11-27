"""Cleanup step 2 on the hardware path (blueprint v2 2.6: ``SPP`` if an SPGU is installed and ``SPST?`` != 0; verify
``SPST?`` = 0; WP9.1): order, the inventory decision, the retry with a second ``SPP``, the latch when the output
never stops, and what the transaction knows about the inventory."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.discovery import parse_unt
from b1500_test_agent.models.station import Settings
from b1500_test_agent.session import Session
from b1500_test_agent.session.cleanup import run_cleanup, spgu_installed
from b1500_test_agent.transport.audit import MemoryAuditSink
from tests.unit.test_session import LOP_OFF, NO_ERROR, UNT_NO_SPGU, HwSpy, Recorder

pytestmark = pytest.mark.spgu

UNT_LAB = ";".join(["B1525A,0", "B1530A,0", "B1517A,0", "B1517A,0", "B1511B,0", "B1511B,0", "B1520A,0"]
                   + ["0,0"] * 3)
"""``UNT?`` of the lab mainframe: HV-SPGU in slot 1 (blueprint v2 1.1)."""


def lab_spy(spst: list[str] | str, **kwargs: object) -> HwSpy:
    return HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF, "UNT?": UNT_LAB, "SPST?": spst, "*STB?": "0",
                          "*IDN?": "Agilent Technologies,B1500A,0,A.06.02.2023.0401"}, **kwargs)


def steps(report) -> list[tuple[int, str, bool]]:
    return [(s.attempt, s.step, s.ok) for s in report.steps]


def test_an_active_output_is_stopped_before_dz_and_verified_after() -> None:
    spy = lab_spy(["1", "0"])
    report = run_cleanup(B1500Driver(spy), always_abort=True, emit=Recorder()).report
    assert spy.sent == ["AB", "UNT?", "SPST?", "SPP", "DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    assert report.verified == "lop" and "SPST? 0" in report.steps[-1].detail
    assert steps(report)[:3] == [(1, "abort", True), (1, "spgu_stop", True), (1, "zero", True)]
    assert report.steps[1].detail == "SPST? 1: SPP sent"


def test_an_inactive_output_gets_no_spp() -> None:
    spy = lab_spy("0")
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder(), spgu=True).report
    assert spy.sent == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"] and report.verified == "lop"


def test_without_an_spgu_nothing_is_asked() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF, "UNT?": UNT_NO_SPGU})
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder()).report
    assert spy.sent == ["UNT?", "DZ", "CL", "ERRX?", "LOP?"] and "spgu_stop" not in [s.step for s in report.steps]
    known = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    run_cleanup(B1500Driver(known), always_abort=False, emit=Recorder(), spgu=False)
    assert known.sent == ["DZ", "CL", "ERRX?", "LOP?"]


def test_an_output_that_stops_only_on_the_second_spp_is_verified_by_the_retry() -> None:
    spy = lab_spy(["1", "1", "1", "0"])  # step 1, verify 1, step 2 (retry), verify 2
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder(), spgu=True).report
    assert report.verified == "lop"
    assert steps(report) == [
        (1, "spgu_stop", True), (1, "zero", True), (1, "disconnect", True), (1, "drain_errors", True),
        (1, "verify", False), (2, "device_clear", True), (2, "spgu_stop", True), (2, "zero", True),
        (2, "disconnect", True), (2, "drain_errors", True), (2, "verify", True)]
    assert spy.sent.count("SPP") == 2 and "still active" in report.steps[4].detail


def test_an_output_that_never_stops_is_unverified() -> None:
    spy = lab_spy("1")
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder(), spgu=True).report
    assert report.verified == "unverified" and spy.sent.count("SPP") == 2
    assert [s.step for s in report.steps if not s.ok] == ["verify", "verify"]


def test_unreadable_state_and_inventory_still_send_spp() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF, "UNT?": "garbage", "SPST?": ["x", "0", "0", "0"]})
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder()).report
    assert spy.sent[:3] == ["UNT?", "SPST?", "SPP"]  # unreadable inventory counts as an SPGU; SPP sent anyway
    assert (1, "spgu_stop", False) in steps(report) and report.verified == "lop"  # the retry verified


def test_spgu_installed_reads_the_inventory() -> None:
    assert spgu_installed(parse_unt(UNT_LAB)) is True
    assert spgu_installed(parse_unt(UNT_NO_SPGU)) is False
    assert spgu_installed(None) is None


def test_a_transaction_uses_the_inventory_it_already_read(tmp_path: Path) -> None:
    spy = lab_spy("0")
    session = Session(Settings(), lambda: spy, MemoryAuditSink(), state_dir=tmp_path)
    with session.transaction(intent="x", envelope=None, run=None) as tx:
        tx.snapshot()  # reads UNT? (the executor's pre-execute snapshot)
    after = spy.sent[spy.sent.index("LOP?") + 1:]
    assert "UNT?" not in after and after[:2] == ["SPST?", "DZ"] and after[-1] == "SPST?"
    spy.sent.clear()
    with session.transaction(intent="y", envelope=None, run=None):
        pass  # the session's last snapshot names the SPGU: no UNT? either
    assert "UNT?" not in spy.sent and spy.sent[1] == "SPST?"
