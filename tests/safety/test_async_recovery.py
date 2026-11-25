"""Recovery of a crashed asynchronous run restores the auto-calibration state (blueprint v2 2.6 R-CAL-02, 7.4 stage
L9 "auto-cal restore" and "kill-and-recover drill"; WP11.1).

An asynchronous run sends ``CM 0`` and its own cleanup restores the state read before the run. When the process dies
mid-run (a harness that kills the MCP server at turn end, WP7.7; Task Manager; a power cut of the host) that cleanup
never runs. The in-flight marker therefore records the state first, and the next transaction's recovery cleanup (or a
``safe_shutdown``) restores it after the outputs are verified off; an unverified recovery leaves auto-calibration off
(the fault latch is set). A crash during the recovery itself keeps the state to restore in the recovering
transaction's marker. The crashing transactions run in ``spawn`` children that die with ``os._exit`` (no cleanup).
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.models.sim import IgnoreDz
from b1500_test_agent.session import CleanupUnverified, read_inflight
from b1500_test_agent.session.transaction import Transaction, state_hooks
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.safety.helpers import DRAIN, GATE, acquire, make_harness

SPAWN = multiprocessing.get_context("spawn")
SCENARIO = "nmos_basic"


def crash_inside_an_async_run(state_dir: str, ready: Any, before: bool) -> None:
    """Child target: an asynchronous run's transaction with auto-calibration ``before`` (``CM 1``/``CM 0``), suspended
    as the executor does (``CM 0``), outputs on, simulator state saved; then death without any cleanup."""
    h = make_harness(Path(state_dir))
    tx = h.transaction(run=False, intent="crashing async run")
    tx.__enter__()
    tx.driver.set_auto_calibration(before)
    tx.suspend_auto_calibration(tx.driver.auto_calibration())
    tx.driver.enable([GATE, DRAIN])
    tx.driver.force_v(DRAIN, 0.1, icomp=1e-3)
    tx.driver.force_v(GATE, 1.2, icomp=1e-5)
    hooks = state_hooks(h.session.transport)
    assert hooks is not None
    hooks.save_state()
    ready.set()
    os._exit(4)


def crash_inside_the_recovery(state_dir: str, ready: Any) -> None:
    """Child target: the next transaction recovers (outputs zeroed and verified) but dies before it restores the
    crashed run's auto-calibration state."""
    def die(self: Transaction, previous: Any, report: Any) -> Any:
        hooks = state_hooks(self._session.transport)
        assert hooks is not None
        hooks.save_state()
        ready.set()
        os._exit(5)

    Transaction._restore_previous_auto_calibration = die  # type: ignore[method-assign]
    h = make_harness(Path(state_dir))
    with h.transaction(run=False, intent="recovering"):
        pass


def _run_child(target: Any, *args: Any, code: int) -> None:
    ready = SPAWN.Event()
    child = SPAWN.Process(target=target, args=(*args, ready))
    child.start()
    child.join(60)
    assert ready.is_set() and child.exitcode == code


def _crash(state_dir: Path, before: bool) -> None:
    ready = SPAWN.Event()
    child = SPAWN.Process(target=crash_inside_an_async_run, args=(str(state_dir), ready, before))
    child.start()
    child.join(60)
    assert ready.is_set() and child.exitcode == 4


def _auto_calibration(state_dir: Path) -> bool:
    state = load_state_file(sim_state_file(state_dir, SCENARIO))
    assert state is not None
    return state.auto_calibration


@pytest.mark.parametrize("before", [True, False])
def test_the_next_transaction_recovers_a_crashed_async_run_and_restores_auto_calibration(tmp_path: Path,
                                                                                         before: bool) -> None:
    _crash(tmp_path, before)
    marker = read_inflight(tmp_path / "inflight.json")
    assert marker is not None and marker.auto_calibration_before == ("on" if before else "off")
    assert _auto_calibration(tmp_path) is False  # CM 0 was sent before the crash
    h = make_harness(tmp_path)
    with h.transaction(run=False, intent="after the crash") as tx:
        assert tx.recovery is not None and tx.recovery.verified == "sim_state"
        restore = [s for s in tx.recovery.steps if s.step == "restore"]
        assert len(restore) == 1 and restore[0].ok and "recovery of the crashed run" in restore[0].detail
        assert h.sim.instrument.state.auto_calibration is before
        assert read_inflight(tmp_path / "inflight.json").auto_calibration_before is None  # type: ignore[union-attr]
        h.sim.instrument.assert_safe()
        acquire(tx, h.hook)
    assert _auto_calibration(tmp_path) is before
    assert [c for c in h.log if c.mnemonic == "CM"][-1].args == (["1"] if before else ["0"])
    steps = [e.data["step"] for e in h.events(run=False) if e.ev == "cleanup_step" and e.data]
    assert steps.index("restore") == steps.index("verify") + 1  # after the verified recovery, before the body


def test_safe_shutdown_is_the_recovery_and_restores_auto_calibration(tmp_path: Path) -> None:
    _crash(tmp_path, True)
    h = make_harness(tmp_path)
    report = h.session.safe_shutdown(reason="after a kill")
    assert report.verified == "sim_state" and report.steps[-1].step == "restore" and report.steps[-1].ok
    assert "restored to on" in report.steps[-1].detail
    assert _auto_calibration(tmp_path) is True
    assert any(e.ev == "recovery_cleanup" for e in h.events(run=False))
    assert not (tmp_path / "inflight.json").exists()


def test_a_crash_during_the_recovery_keeps_the_state_to_restore(tmp_path: Path) -> None:
    _crash(tmp_path, True)
    _run_child(crash_inside_the_recovery, str(tmp_path), code=5)
    marker = read_inflight(tmp_path / "inflight.json")
    assert marker is not None and marker.intent == "recovering" and marker.auto_calibration_before == "on"
    h = make_harness(tmp_path)
    with h.transaction(run=False, intent="second recovery") as tx:
        assert tx.recovery is not None and tx.recovery.steps[-1].step == "restore" and tx.recovery.steps[-1].ok
    assert _auto_calibration(tmp_path) is True


def test_an_unverified_recovery_leaves_auto_calibration_off(tmp_path: Path) -> None:
    _crash(tmp_path, True)
    h = make_harness(tmp_path)
    h.sim.inject(IgnoreDz(channels=[GATE]))
    with pytest.raises(CleanupUnverified), h.transaction(run=False):
        pass
    assert h.session.fault_latch.get() is not None
    restore = [e.data for e in h.events(run=False) if e.ev == "cleanup_step" and e.data and
               e.data["step"] == "restore"]
    assert len(restore) == 1 and restore[0]["ok"] is False and "stays off" in str(restore[0]["detail"])
    assert _auto_calibration(tmp_path) is False


def test_a_crashed_synchronous_transaction_has_nothing_to_restore(tmp_path: Path) -> None:
    from tests.safety.helpers import crash_inside_transaction

    _run_child(crash_inside_transaction, str(tmp_path), code=4)
    assert read_inflight(tmp_path / "inflight.json").auto_calibration_before is None  # type: ignore[union-attr]
    h = make_harness(tmp_path)
    with h.transaction(run=False) as tx:
        assert tx.recovery is not None and not any(s.step == "restore" for s in tx.recovery.steps)
