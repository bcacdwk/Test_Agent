"""The transaction's WGFMU phase and cleanup step 3 on the simulator (blueprint v2 0 #7, 2.6; WP10.3): FLEX unlock ->
library session -> initialize -> guarded driver -> exit always runs step 3 and relocks; the ATV-14 fallback setting
(``flex_during_phase: close``) and ``flex_io``; RSU states from the library; step 3 in ``safe_shutdown`` (only with a
WGFMU and an available library) and in the in-flight recovery after a crash inside a phase; ATV-17 (``initialize``
leaves an SMU bias alone). The visa path is ``tests/visa_loop/test_wgfmu_phase_visa.py``, the fault matrix
``tests/safety/test_wgfmu_matrix.py``."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from b1500_test_agent.driver.wgfmu import WgfmuSafeStateFailed
from b1500_test_agent.models.sim import WgfmuDisconnectFails, WgfmuDllMissing, WgfmuErrorFault
from b1500_test_agent.session import CleanupUnverified, read_inflight
from b1500_test_agent.transport.base import TransportClosed
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.safety.helpers import assert_cleanup_order
from tests.safety.wgfmu_helpers import (
    BOTTOM,
    LAB_SLOTS,
    R_WG_OHM,
    SMU,
    TOP,
    assert_lock_windows,
    assert_wgfmu_invariant,
    body,
    crash_inside_wgfmu_phase,
    make_wg_harness,
    program,
    wg_scenario,
)

pytestmark = pytest.mark.wgfmu
SPAWN = multiprocessing.get_context("spawn")

PHASE_EXIT = ["abort", "initialize", "disconnect", "disconnect", "close_session"]


def library(h, *, run: bool = True) -> list[str]:
    return [e.cmd or "" for e in h.events(run=run) if e.ev == "wgfmu_call"]


def labels(h, *, run: bool = True) -> list[str]:
    return [str((e.data or {}).get("label")) for e in h.events(run=run) if e.ev == "checkpoint"]


def test_a_phase_releases_the_lock_runs_the_program_and_relocks(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    with h.transaction() as tx:
        block = body(tx, h)
        assert h.sim.locked and h.library.session is None  # relocked, library session closed again
        assert not tx.wgfmu_link.pending and tx.wgfmu_link.phases == ["unlocked (flex_io)"]
    assert block is not None and block.status == "completed"
    top, bottom = block.traces[TOP], block.traces[BOTTOM]
    assert top.quantity == "V" and len(top) == 4000 and max(top.value) == pytest.approx(3.0)
    assert bottom.quantity == "I" and min(bottom.value) == pytest.approx(-3.0 / R_WG_OHM, rel=0.02)
    names = h.spy.names()
    assert names[:2] == ["open_session", "initialize"] and names[-len(PHASE_EXIT):] == PHASE_EXIT
    assert names.index("clear") < names.index("add_vectors") < names.index("update") < names.index("execute")
    events = h.events()
    assert_lock_windows(events)
    order = [e.ev if e.ev != "checkpoint" else (e.data or {}).get("label") for e in events
             if e.ev in ("bus_lock", "bus_unlock") or (e.ev == "checkpoint" and
                                                     (e.data or {}).get("label", "").startswith("wgfmu"))]
    assert order[:5] == ["bus_lock", "wgfmu_phase", "bus_unlock", "bus_lock", "wgfmu_phase_end"]
    calls = [e for e in events if e.ev == "wgfmu_call"]
    assert {e.tx for e in calls} == {tx.tx_id} and {e.run for e in calls} == {h.run.run_id}
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    assert "wgfmu" not in [s.step for s in tx.cleanup.steps]  # the phase confirmed its safe state itself
    assert tx.cleanup.switches_after["RSU201.OUT"] == "open" and tx.cleanup.switches_after["RSU202.OUT"] == "open"
    assert_wgfmu_invariant(h, tx)


def test_flex_commands_inside_the_phase_go_out_without_the_lock_and_initialize_keeps_the_smu_bias(
        tmp_path: Path) -> None:
    """WG Ex. 10 combines an SMU bias with the WGFMU (FLEX stays usable in the phase); ATV-17: ``initialize`` (entry
    and step 3) resets the WGFMU only, the SMU keeps its bias until the cleanup's DZ."""
    h = make_wg_harness(tmp_path)
    with h.transaction() as tx:
        tx.driver.enable([SMU])
        tx.driver.force_v(SMU, 0.5, icomp=1e-3)
        with tx.wgfmu_phase() as wg:
            assert h.sim.instrument.state.channels[SMU].voltage == 0.5  # after the entry's initialize
            tx.driver.force_v(SMU, 0.4, icomp=1e-3)  # inside the phase: allowed, lock released
            wg.load(program())
            wg.run()
        state = h.sim.instrument.state.channels[SMU]
        assert state.output_on and state.voltage == 0.4  # after the exit's abort + initialize
    dv = [(cmd, locked) for cmd, locked in h.hook.writes if cmd.startswith("DV 3")]
    assert [locked for _, locked in dv] == [True, False]  # before the phase locked, inside it unlocked
    assert_wgfmu_invariant(h, tx)


def test_the_close_fallback_closes_the_flex_link_unless_the_kind_needs_it(tmp_path: Path) -> None:
    """ATV-14 fallback (``settings.wgfmu.flex_during_phase: close``): the FLEX link is closed for a WGFMU-only phase
    and reopened and locked at its exit; a kind that sends FLEX commands keeps it open without the lock."""
    h = make_wg_harness(tmp_path, settings={"wgfmu": {"flex_during_phase": "close"}})
    with h.transaction() as tx:
        with tx.wgfmu_phase() as wg:
            assert not h.session.bus_open
            with pytest.raises(TransportClosed):
                tx.driver.force_v(SMU, 0.1, icomp=1e-3)
            wg.load(program())
            assert wg.run().status == "completed"
        assert h.session.bus_open and h.sim.locked
        with tx.wgfmu_phase(flex_io=True) as wg:
            assert h.session.bus_open and not h.sim.locked
            wg.load(program())
            wg.run()
    assert tx.wgfmu_link.phases == ["closed", "unlocked (flex_io)"] == tx.wgfmu_phases  # the manifest lists them
    lifecycle = [e.ev for e in h.events() if e.ev.startswith("bus_")]
    assert lifecycle[:6] == ["bus_open", "bus_lock", "bus_close", "bus_open", "bus_lock", "bus_unlock"]
    assert [e.data["flex"] for e in h.events() if e.ev == "checkpoint" and e.data
            and e.data.get("label") == "wgfmu_phase"] == ["closed", "unlocked (flex_io)"]
    assert_wgfmu_invariant(h, tx)


def test_without_a_library_the_phase_refuses_before_releasing_anything(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path, wgfmu=False)
    with pytest.raises(WgfmuError) as caught, h.transaction() as tx:
        tx.wgfmu_phase().__enter__()
    assert caught.value.rc == api.LIBRARY_ERROR and "no WGFMU instrument library" in str(caught.value)
    assert [e.ev for e in h.events() if e.ev.startswith("bus_")] == ["bus_open", "bus_lock", "bus_unlock",
                                                                     "bus_close"]
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"


def test_a_refused_session_relocks_and_leaves_nothing_pending(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    h.sim.inject(WgfmuErrorFault(fn="open_session", code=api.COMMUNICATION_ERROR))
    with pytest.raises(WgfmuError), h.transaction() as tx:
        body(tx, h)
    assert library(h) == ["WGFMU_openSession"] and not tx.wgfmu_link.pending
    assert tx.cleanup is not None and "wgfmu" not in [s.step for s in tx.cleanup.steps]
    assert_wgfmu_invariant(h, tx)


def test_a_failed_initialize_still_runs_step_3_at_the_exit(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    h.sim.inject(WgfmuErrorFault(fn="initialize", code=3002))
    with pytest.raises(WgfmuError) as caught, h.transaction() as tx:
        body(tx, h)
    assert caught.value.wgfmu_code == 3002
    assert h.spy.names() == ["open_session", "initialize", "abort", "initialize", "close_session"]
    assert_wgfmu_invariant(h, tx)


def test_one_phase_at_a_time(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    with h.transaction() as tx, tx.wgfmu_phase(), pytest.raises(RuntimeError, match="already open"):
        tx.wgfmu_phase().__enter__()
    assert_wgfmu_invariant(h, tx)


def test_a_stuck_relay_fails_the_phase_and_latches_the_fault(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    h.sim.inject(WgfmuDisconnectFails(channels=[TOP]))
    with pytest.raises(WgfmuSafeStateFailed, match="disconnect 201 FAILED"), h.transaction() as tx:
        body(tx, h)
    assert tx.cleanup is not None and tx.cleanup.latched_fault and tx.wgfmu_link.pending
    steps = [(s.attempt, s.step, s.ok) for s in tx.cleanup.steps if s.step == "wgfmu"]
    assert steps == [(1, "wgfmu", False), (2, "wgfmu", False)]
    assert "RSU201.OUT" not in tx.cleanup.switches_after and tx.cleanup.switches_after["RSU202.OUT"] == "open"
    assert_wgfmu_invariant(h, tx)


def test_a_relay_that_opens_on_the_retry_is_verified_by_the_cleanup(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    h.sim.inject(WgfmuDisconnectFails(channels=[TOP], count=1))
    with pytest.raises(WgfmuSafeStateFailed), h.transaction() as tx:
        body(tx, h)
    assert tx.cleanup is not None and not tx.cleanup.latched_fault and tx.cleanup.verified == "sim_state"
    step = next(s for s in tx.cleanup.steps if s.step == "wgfmu")
    assert step.ok and "channel_ids" in step.detail and "disconnect 201" in step.detail
    assert not tx.wgfmu_link.pending
    assert_wgfmu_invariant(h, tx)


def test_the_pre_execute_snapshot_reads_the_rsus_from_the_library(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    with h.transaction(envelope=None, run=False) as tx:
        live = tx.snapshot(wgfmu=True)
    assert live.wgfmu_channels == [TOP, BOTTOM] and live.switch_states is not None
    assert live.switch_states["RSU201.OUT"] == "open" and live.switch_states["RSU202.OUT"] == "open"
    assert live.switch_states["SEL1.OUT1"] == "open"  # the FLEX-read selectors are still there
    assert h.spy.names() == ["open_session", "channel_ids", "disconnect", "disconnect", "close_session"]


def test_a_stuck_rsu_stays_unread_in_the_snapshot(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    h.sim.inject(WgfmuDisconnectFails(channels=[TOP]))
    with h.transaction(envelope=None, run=False) as tx:
        live = tx.snapshot(wgfmu=True)
    assert live.switch_states is not None and "RSU201.OUT" not in live.switch_states
    assert live.switch_states["RSU202.OUT"] == "open" and "rsu_unread" in labels(h, run=False)


# -- safe_shutdown and recovery ----------------------------------------------------------------------------------------


def test_safe_shutdown_opens_a_library_session_only_to_abort_and_disconnect(tmp_path: Path) -> None:
    h = make_wg_harness(tmp_path)
    report = h.session.safe_shutdown(reason="operator stop")
    assert report.verified == "sim_state" and not report.latched_fault
    step = next(s for s in report.steps if s.step == "wgfmu")
    assert step.ok and step.detail.endswith("close_session, flex relocked")
    assert h.spy.names() == ["open_session", "channel_ids", "abort", "initialize", "disconnect", "disconnect",
                             "close_session"]
    assert not any(name in h.spy.names() for name in ("connect", "add_vectors", "execute", "dc_force_voltage"))
    assert_lock_windows(h.events(run=False))
    assert report.switches_after["RSU201.OUT"] == "open"


def test_safe_shutdown_skips_the_wgfmu_without_a_module_or_a_library(tmp_path: Path) -> None:
    no_module = wg_scenario(slots=[s for s in LAB_SLOTS if s["slot"] != 2],
                            wiring={"r_smu": {"a": SMU, "b": "GNDU"}}, models={
                                "r_smu": {"model": "resistor", "params": {"r_ohm": 1e5}}})
    h = make_wg_harness(tmp_path / "a", no_module)
    h.session.snapshot()  # the inventory shows no WGFMU
    assert "wgfmu" not in [s.step for s in h.session.safe_shutdown(reason="x").steps] and h.spy.calls == []
    h = make_wg_harness(tmp_path / "b", wgfmu=False)
    assert "wgfmu" not in [s.step for s in h.session.safe_shutdown(reason="x").steps]


def test_a_library_lost_after_start_does_not_hide_a_safe_wgfmu(tmp_path: Path) -> None:
    """``wgfmu_dll_missing`` injected later: the shutdown's session cannot open; the simulated state proves the WGFMU
    safe, so the cleanup verifies (on hardware the step's failure leaves it unverified: visa-loop test)."""
    h = make_wg_harness(tmp_path)
    h.sim.inject(WgfmuDllMissing())
    report = h.session.safe_shutdown(reason="x")
    steps = [s for s in report.steps if s.step == "wgfmu"]
    assert [s.ok for s in steps] == [False, False] and "open_session FAILED" in steps[0].detail
    assert report.verified == "sim_state" and not report.latched_fault and h.sim.locked is False


def test_a_crash_inside_a_phase_is_recovered_by_the_next_transaction(tmp_path: Path) -> None:
    ready = SPAWN.Event()
    child = SPAWN.Process(target=crash_inside_wgfmu_phase, args=(str(tmp_path), ready))
    child.start()
    child.join(60)
    assert ready.is_set() and child.exitcode == 5
    assert read_inflight(tmp_path / "inflight.json") is not None
    h = make_wg_harness(tmp_path)
    with h.transaction(run=False, intent="after the crash") as tx:
        assert tx.recovery is not None and tx.recovery.verified == "sim_state"
        assert "wgfmu" in [s.step for s in tx.recovery.steps]
        wgfmu = h.sim.instrument.state.wgfmu
        assert all(not s.connected and not s.running for s in wgfmu.values())
    assert h.spy.names()[:2] == ["open_session", "channel_ids"]
    events = h.events(run=False)
    recovery = next(i for i, e in enumerate(events) if e.ev == "recovery_cleanup")
    assert_cleanup_order(events[:recovery])
    assert_cleanup_order(events[recovery + 1:])
    assert_lock_windows(events)
    assert h.library.session is None
    h.sim.instrument.assert_safe()
    assert h.session.fault_latch.get() is None and not (tmp_path / "inflight.json").exists()


def test_without_recovery_the_crashed_phase_would_not_verify(tmp_path: Path) -> None:
    """The control: the state the crash leaves is unsafe (connected RSUs), so only step 3 makes the recovery pass."""
    ready = SPAWN.Event()
    child = SPAWN.Process(target=crash_inside_wgfmu_phase, args=(str(tmp_path), ready))
    child.start()
    child.join(60)
    h = make_wg_harness(tmp_path, wgfmu=False)  # no library: step 3 cannot run
    with pytest.raises(CleanupUnverified), h.transaction(run=False):
        pass
    assert h.session.fault_latch.get() is not None
