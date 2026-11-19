"""The ``LOP?`` positive control of a hardware transaction (blueprint v2 10.2 row 6.2; v1 ATV-1, ATV-23).

Unit level: ``run_cleanup`` with a passed or failed control (a spy transport posing as hardware), and
``Transaction.lop_positive_control`` on the simulator (no I/O: the simulator verifies its own state). The end-to-end
hardware path (visa-loop: ``CN`` -> ``LOP?`` on -> ... -> ``CL`` -> ``LOP?`` off, and an instrument whose ``LOP?``
never shows an output on) is in ``tests/visa_loop/test_recipes.py`` and ``tests/visa_loop/test_positive_control.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.models.run import CleanupReport, PositiveControl
from b1500_test_agent.session import PositiveControlFailed, run_cleanup
from tests.safety.helpers import make_harness
from tests.unit.test_session import LOP_OFF, NO_ERROR, HwSpy, Recorder

PASSED = PositiveControl(channels=[3, 4, 5], codes={3: "01", 4: "01", 5: "01"}, ok=True,
                         detail="slot 3 01, slot 4 01, slot 5 01 with the output switches of channels 3, 4, 5 on")
FAILED = PositiveControl(channels=[3, 4], codes={3: "01", 4: "00"}, ok=False,
                         detail="slot(s) 4 read 00 although the run had switched on the output switches of channels "
                                "3, 4 (slot 3 01, slot 4 00)")


def test_a_passed_control_is_the_evidence_next_to_the_all_off_reading() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    events = Recorder()
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=events, positive=PASSED).report
    assert report.verified == "lop" and report.positive_control == PASSED
    verify = [d for ev, d, _ in events.events if ev == "cleanup_step" and d and d["step"] == "verify"]
    assert verify[-1]["ok"] is True
    assert verify[-1]["detail"] == f"all slots report 00; positive control with the outputs on: {PASSED.detail}"
    assert CleanupReport.model_validate_json(report.model_dump_json()) == report  # manifest round trip


def test_a_failed_control_makes_the_all_off_reading_worthless() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder(), positive=FAILED).report
    assert report.verified == "unverified" and report.positive_control == FAILED
    assert report.outputs_after == {slot: "00" for slot in range(1, 11)}  # LOP? said off; that proves nothing here
    verify = [s for s in report.steps if s.step == "verify"]
    assert [s.ok for s in verify] == [False, False]  # first attempt and the retry after the device clear
    assert "positive control failed" in verify[-1].detail and "does not prove the outputs off" in verify[-1].detail


def test_without_a_control_the_cleanup_is_unchanged() -> None:
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder()).report
    assert report.verified == "lop" and report.positive_control is None
    assert [s.detail for s in report.steps if s.step == "verify"] == ["all slots report 00"]


def test_the_failure_names_the_slots_and_the_atv() -> None:
    error = PositiveControlFailed(FAILED)
    assert error.code == "cleanup_unverified" and error.control is FAILED
    assert "slot(s) 4 read 00" in str(error) and "ATV-1" in str(error) and "fault latched" in str(error)


def test_the_simulator_needs_no_control_and_sends_nothing(tmp_path: Path) -> None:
    """On sim the cleanup reads the simulated state (``verified: sim_state``): no ``LOP?``, no record."""
    harness = make_harness(tmp_path)
    with harness.session.transaction(intent="unit", envelope=None, run=None) as tx:
        before = len(harness.sim.instrument.command_log)
        assert tx.lop_positive_control([3, 4]) is None
        assert tx.positive_control is None
        assert len(harness.sim.instrument.command_log) == before
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state" and tx.cleanup.positive_control is None


@pytest.mark.parametrize("channels", [[], ()])
def test_no_channel_means_no_control(tmp_path: Path, channels: list[int]) -> None:
    harness = make_harness(tmp_path)
    with harness.session.transaction(intent="unit", envelope=None, run=None) as tx:
        assert tx.lop_positive_control(channels) is None
