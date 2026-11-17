"""Fault latch: refusal while set, ``safe_shutdown`` never gated, ``FaultLatch.clear`` refusals (blueprint 2.4,
4.3 point 5, 8.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from b1500_test_agent.models.run import CleanupReport, CleanupStep
from b1500_test_agent.models.sim import Disconnect, ErrxFault, IgnoreDz
from b1500_test_agent.models.station import InstrumentError
from b1500_test_agent.session import CleanupUnverified, FaultClearRefused, FaultLatched, clear_refusals
from tests.safety.helpers import DRAIN, GATE, RUN_ID, Harness, acquire, assert_global_invariant, make_harness

STEPS_OK = [CleanupStep(step=name, ok=True) for name in ("zero", "disconnect", "drain_errors", "verify")]


def latched_by_stuck_output(tmp_path: Path) -> Harness:
    """A run whose gate output sticks: cleanup cannot verify, the latch is set."""
    h = make_harness(tmp_path)
    h.sim.inject(IgnoreDz(channels=[GATE]))
    with pytest.raises(CleanupUnverified), h.transaction() as tx:
        acquire(tx, h.hook)
    assert_global_invariant(h)
    return h


def report(**changes: object) -> CleanupReport:
    base = CleanupReport(steps=STEPS_OK, verified="sim_state", outputs_after={1: "off", 3: "off"},
                         latched_fault=False)
    return base.model_copy(update=changes)


def test_latched_fault_refuses_sourcing_with_zero_io(tmp_path: Path) -> None:
    h = latched_by_stuck_output(tmp_path)
    record = h.session.fault_latch.get()
    assert record is not None and record.run_id == RUN_ID and "cleanup unverified" in record.reason
    log_before, run_events_before = len(h.log), len(h.run.audit.events)
    daily_before = len(h.daily.events)
    with pytest.raises(FaultLatched) as caught, h.transaction():
        pytest.fail("a sourcing transaction must not start while the fault is latched")
    assert caught.value.code == "fault_latched" and caught.value.record == record
    assert len(h.log) == log_before and len(h.run.audit.events) == run_events_before
    assert len(h.daily.events) == daily_before
    assert h.session.lock.holder() is None


def test_non_sourcing_work_still_runs_while_latched(tmp_path: Path) -> None:
    h = latched_by_stuck_output(tmp_path)
    live = h.session.snapshot()
    assert live.outputs[GATE].output_on  # the stuck output is visible to the human
    seen = None
    # A non-sourcing transaction starts; its cleanup still cannot verify the stuck output, so it reports that.
    with pytest.raises(CleanupUnverified), h.transaction(envelope=None, run=False, intent="read-only") as tx:
        seen = tx.snapshot()
    assert seen is not None and seen.identity is not None and seen.outputs[GATE].output_on
    assert h.session.fault_latch.get() is not None  # still latched: only clear() removes it


def test_safe_shutdown_is_never_gated_and_clear_needs_a_verified_shutdown(tmp_path: Path) -> None:
    h = latched_by_stuck_output(tmp_path)
    stuck = h.session.safe_shutdown(reason="operator")
    assert stuck.verified == "unverified" and stuck.latched_fault
    with pytest.raises(FaultClearRefused) as refused:
        h.session.fault_latch.clear(by="owner", shutdown=stuck)
    assert any("could not verify" in r for r in refused.value.reasons)
    assert any("not all off" in r for r in refused.value.reasons)
    assert h.session.fault_latch.get() is not None

    h.sim.clear_faults()  # the stuck relay was repaired
    good = h.session.safe_shutdown(reason="operator")
    assert good.verified == "sim_state" and not good.latched_fault and not good.errors
    assert [s.step for s in good.steps] == ["abort", "zero", "disconnect", "drain_errors", "verify"]
    h.session.fault_latch.clear(by="owner", shutdown=good)
    assert h.session.fault_latch.get() is None
    cleared = next(e for e in h.daily.events if e.ev == "fault_cleared")
    assert cleared.data is not None and cleared.data["by"] == "owner" and cleared.run == RUN_ID
    with h.transaction() as tx:  # sourcing works again
        acquire(tx, h.hook)
    h.sim.instrument.assert_safe()


def test_clear_refuses_while_errx_is_not_empty_then_succeeds(tmp_path: Path) -> None:
    h = latched_by_stuck_output(tmp_path)
    h.sim.clear_faults()
    h.sim.inject(ErrxFault(after_cmd="CL", code=305))
    first = h.session.safe_shutdown(reason="operator")
    assert first.verified == "sim_state" and [e.code for e in first.errors] == [305]
    with pytest.raises(FaultClearRefused) as refused:
        h.session.fault_latch.clear(by="owner", shutdown=first)
    assert refused.value.reasons == [refused.value.reasons[0]] and "ERRX? was not empty" in refused.value.reasons[0]
    second = h.session.safe_shutdown(reason="operator")
    assert not second.errors
    h.session.fault_latch.clear(by="owner", shutdown=second)
    assert h.session.fault_latch.get() is None


def test_safe_shutdown_without_a_link_latches(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    with h.transaction() as tx:
        tx.driver.enable([GATE, DRAIN])
    h.sim.inject(Disconnect(after_writes=0))
    result = h.session.safe_shutdown(reason="link test")
    assert result.verified == "unverified" and result.latched_fault
    assert h.session.fault_latch.get() is not None
    assert h.session.lock.holder() is None and not (tmp_path / "inflight.json").exists()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"verified": "unverified"}, "could not verify"),
        ({"latched_fault": True}, "itself latched"),
        ({"outputs_after": {1: "off", 3: "on 0.1 V"}}, "not all off"),
        ({"outputs_after": {}}, "no output state"),
        ({"outputs_after": {1: "00", 2: "01"}}, "not all off"),
        ({"steps": [s for s in STEPS_OK if s.step != "drain_errors"]}, "could not be read"),
        ({"steps": [*STEPS_OK[:2], CleanupStep(step="drain_errors", ok=False), STEPS_OK[3]]}, "could not be read"),
        ({"errors": [InstrumentError(code=305, message="Excess current")]}, "not empty"),
    ],
)
def test_clear_refusal_reasons(tmp_path: Path, changes: dict[str, object], expected: str) -> None:
    h = make_harness(tmp_path)
    h.session.fault_latch.set("test fault", None)
    bad = report(**changes)
    reasons = clear_refusals(bad)
    assert len(reasons) == 1 and expected in reasons[0]
    with pytest.raises(FaultClearRefused):
        h.session.fault_latch.clear(by="owner", shutdown=bad)
    assert h.session.fault_latch.get() is not None
    assert not clear_refusals(report()) and not clear_refusals(report(outputs_after={1: "00", 2: "00"}))
    h.session.fault_latch.clear(by="owner", shutdown=report())
    assert h.session.fault_latch.get() is None


def test_latch_keeps_the_first_cause_and_corrupt_file_counts_as_latched(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    latch = h.session.fault_latch
    assert latch.get() is None
    latch.clear(by="owner", shutdown=report(verified="unverified"))  # nothing latched: no-op
    latch.set("first", RUN_ID)
    latch.set("second", None)
    record = latch.get()
    assert record is not None and record.reason == "first" and record.run_id == RUN_ID
    assert record.set_at <= datetime.now(UTC)
    assert [e.data["already_latched"] for e in h.daily.events if e.ev == "fault" and e.data] == [False, True]
    latch.path.write_text("{oops", encoding="utf-8")
    corrupt = latch.get()
    assert corrupt is not None and "corrupt" in corrupt.reason
    with pytest.raises(FaultLatched), h.transaction():
        pass
