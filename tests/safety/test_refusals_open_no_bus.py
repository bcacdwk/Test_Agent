"""Blocked and unconfirmed plans open neither bus, for every recipe of the registry (WP11.3; blueprint v2 8.1
``safety/``, 2.6).

Each recipe runs the request of its visa-loop case (``tests/visa_loop/cases``) on backend visa, where every plan
needs a human confirmation (``first_hw_run``), with spies on both buses: the visa-loop resource manager counts every
VISA session opened and locked (FLEX), the fake ``wgfmu.dll`` records every C call and every library load (WGFMU).
After the per-family preparation the suite's own run test does (recorded selector wiring, SCUU, load standard; the
MFCMU corrections a C-V plan needs, which do use the bus), the refusals must not touch either bus again:

- the unconfirmed plan: ``run_plan`` without a summary answers ``needs_confirmation`` and ``run_confirmed_plan``
  with a summary that is not the plan's own is refused (``summary_mismatch``);
- with the fault latch set: validation answers ``blocked`` (R-FAULT-01); that plan is refused with or without its
  summary, and so is the earlier plan even with its exact summary (the human's consent does not outrank the latch).

Zero VISA opens and locks, zero library loads and C calls, no run folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.session.fault import FaultLatch
from b1500_test_agent.transport.audit import NullAuditSink
from tests.visa_loop.cases import case_of, correct, prepare, registry
from tests.visa_loop.helpers import make_visa_world
from tests.visa_loop.loop import LoopBus, LoopWgfmuLibrary

REGISTRY = registry()
RECIPES = sorted(rid for rid in REGISTRY.ids() if REGISTRY.runnable(rid, "visa"))


def io_marker(bus: LoopBus, calls: list[str], data: Path) -> tuple[int, ...]:
    """(VISA opens, locks, lock refusals, library loads, C calls, run folders): unchanged = no bus touched."""
    runs = data / "runs"
    folders = len([p for p in runs.glob("*/*/*/*") if p.is_dir()]) if runs.exists() else 0
    stats = bus.stats
    return stats.opens, stats.locks, stats.lock_refusals, stats.wgfmu_loads, len(calls), folders


def refused(result: RunSummary, status: str, code: str, outcome: str = "refused") -> None:
    assert not result.ok and result.run_id is None, result.message
    assert (result.status, result.error_code, result.outcome) == (status, code, outcome), result.message


@pytest.mark.parametrize("recipe_id", RECIPES)
def test_blocked_and_unconfirmed_plans_open_neither_bus(recipe_id: str, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = LoopWgfmuLibrary.dispatch

    def dispatch(self: LoopWgfmuLibrary, name: str, args: tuple[Any, ...]) -> int:
        calls.append(name)
        return original(self, name, args)

    monkeypatch.setattr(LoopWgfmuLibrary, "dispatch", dispatch)
    recipe = REGISTRY.get(recipe_id)
    case = case_of(recipe_id).case
    world = make_visa_world(tmp_path)
    try:
        prepare(world, recipe, case)
        bus = world.bus(case["scenario"])
        service = world.service(bus)
        correct(service, recipe, case)
        before = io_marker(bus, calls, world.data)

        validation = service.validate_plan(recipe_id=recipe_id, **case["request"])
        assert validation.ok and validation.plan_id is not None and validation.summary is not None
        assert validation.tier == "needs_confirmation" and "first_hw_run" in validation.confirm_reasons, \
            validation.message
        refused(service.run_plan(validation.plan_id), "needs_confirmation", "confirmation_required",
                "confirmation_required")
        refused(service.run_confirmed_plan(validation.plan_id, summary="go ahead"), "refused", "summary_mismatch")
        assert io_marker(bus, calls, world.data) == before, "an unconfirmed plan touched a bus"

        FaultLatch(world.state_dir, audit=NullAuditSink(), backend="visa").set("safety matrix latch", None)
        blocked = service.validate_plan(recipe_id=recipe_id, **case["request"])
        assert blocked.tier == "blocked" and blocked.plan_id is not None, blocked.message
        assert "R-FAULT-01" in blocked.message, blocked.message
        refused(service.run_plan(blocked.plan_id), "blocked", "blocked_by_rules")
        refused(service.run_confirmed_plan(blocked.plan_id, summary=blocked.summary or ""), "blocked",
                "blocked_by_rules")
        refused(service.run_confirmed_plan(validation.plan_id, summary=validation.summary), "blocked",
                "blocked_by_rules")
        assert io_marker(bus, calls, world.data) == before, "a blocked plan touched a bus"
    finally:
        world.close()
