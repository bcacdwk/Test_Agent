"""Asynchronous runs on backend visa through the real ``VisaTransport`` (blueprint v2 2.6, 8.1 ``visa_loop/``; WP5.6):
the v1 stepped plan as a long run completes with the ``LOP?`` cleanup verification, sends ``CM 0`` and restores the
auto-calibration switch over VISA, writes the same ``data.csv`` as the simulator backend, and stops at a checkpoint
when an abort request arrives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.session import AbortFile, Transaction
from tests.integration.async_helpers import IDVD_LONG, timed_world
from tests.integration.helpers import make_world
from tests.sim.helpers import load_scenario
from tests.visa_loop.helpers import VisaWorld
from tests.visa_loop.loop import LoopBus


def confirmed_run(world: VisaWorld, bus: LoopBus) -> tuple[Any, str]:
    service = world.service(bus)
    plan = service.validate_plan(**IDVD_LONG)
    assert plan.backend == "visa" and plan.resolved is not None and plan.resolved.mode == "async"
    assert plan.tier == "needs_confirmation" and "first_hw_run" in plan.confirm_reasons
    started = service.run_confirmed_plan(plan.plan_id or "", plan.summary or "")
    assert started.outcome == "running" and not started.simulated, started.message
    return service, started.run_id or ""


def test_async_run_completes_on_visa_with_lop_cleanup_and_cm_restore(world: VisaWorld, tmp_path: Path) -> None:
    scenario = load_scenario("nmos_basic").model_copy(update={"auto_calibration": True})
    bus = LoopBus(world.bus_dir, scenario)
    service, run_id = confirmed_run(world, bus)
    final = service.follow_run(run_id)
    assert final is not None and final.outcome == "completed" and final.cleanup_verified == "lop", final.message
    sent = [r.command for r in bus.instrument.command_log if r.outcome == "ok"]
    assert sent.index("*LRN? 31") < sent.index("CM 0") < sent.index("XE") and sent[-1] == "CM 1"
    assert bus.instrument.state.auto_calibration is True
    assert sum(r.mnemonic == "XE" for r in bus.instrument.command_log) == 21
    sim = make_world(tmp_path / "sim")
    timed_world(sim, fixture_recipe=False)
    sim_service = sim.service()
    try:
        sim_plan = sim_service.validate_plan(**IDVD_LONG)
        sim_final = sim_service.follow_run(sim_service.run_plan(sim_plan.plan_id or "").run_id or "")
    finally:
        sim_service.close()
    assert sim_final is not None and sim_final.outcome == "completed"
    visa_csv = (world.run_dir(run_id) / DATA_FILE).read_bytes()
    sim_csv = next(sim.runs_dir.rglob(f"{sim_final.run_id}/{DATA_FILE}")).read_bytes()
    assert visa_csv == sim_csv


def test_async_run_on_visa_stops_at_a_checkpoint(world: VisaWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    bus = world.bus("nmos_basic")
    original = Transaction.checkpoint

    def checkpoint(self: Transaction, done: int, total: int, phase: str = "", rows: Any = None) -> None:
        if done == 3:
            AbortFile(world.state_dir).request("visa test", adapter="cli")
        original(self, done, total, phase, rows)

    monkeypatch.setattr(Transaction, "checkpoint", checkpoint)
    service, run_id = confirmed_run(world, bus)
    final = service.follow_run(run_id)
    assert final is not None and (final.outcome, final.cleanup_verified) == ("cancelled", "lop")
    assert sum(r.mnemonic == "XE" for r in bus.instrument.command_log) == 3
    assert not (world.state_dir / "abort.json").exists() and not (world.state_dir / "inflight.json").exists()
    bus.instrument.assert_safe()
    assert bus.lock_is_free()
