"""Every runnable recipe of the registry runs on backend visa in this suite, and every recipe that drives the WGFMU
runs through the fake ABI (WP11.3; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

The recipes come from the registry, the cases from the suite's own run tests (``cases.collect_cases``: the
parametrizations of every ``..._on_backend_visa...`` test), so a new recipe without a visa-loop run, or a run test
that stops naming its recipe, fails here.

The WGFMU recipes (a ``wgfmu`` role, or kind ``system``'s library self-test/cal) run once more with a spy on the
fake ``wgfmu.dll`` (``LoopWgfmuLibrary.dispatch``, the C functions the real ``WgfmuDll`` calls through ctypes
marshalling): the library was loaded through the binding from the synthetic x64 DLL, each session it opened was
closed, every C call ran with the FLEX exclusive VISA lock released, the recipe's own work (sequencer, DC force,
self-test/cal) went through it, every RSU channel it connected was disconnected again, and the run completed with its
cleanup verified on the hardware path (``LOP?``) and both buses safe.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.visa_loop.cases import FIXTURE_RECIPES, case_of, collect_cases, prepare, recipe_families, registry
from tests.visa_loop.helpers import VisaWorld
from tests.visa_loop.loop import LoopWgfmuLibrary
from tests.visa_loop.test_sampling_visa import run_to_end

REGISTRY = registry()
RUNNABLE = sorted(rid for rid in REGISTRY.ids() if REGISTRY.runnable(rid, "visa"))
WGFMU_RECIPES = sorted(rid for rid in RUNNABLE if "wgfmu" in recipe_families(REGISTRY.get(rid)))
WORK = frozenset({"WGFMU_execute", "WGFMU_dcforceVoltage", "WGFMU_doSelfTest", "WGFMU_doSelfCalibration"})
"""C functions that do a recipe's work (sequencer run, DC force, self-test, self-calibration)."""


def test_every_runnable_recipe_has_a_visa_loop_case() -> None:
    assert RUNNABLE == sorted(REGISTRY.ids()), "a registered recipe is not runnable on backend visa"
    covered = {found.recipe_id for found in collect_cases()}
    assert not set(RUNNABLE) - covered, f"no visa-loop run test for {sorted(set(RUNNABLE) - covered)}"
    assert covered - set(RUNNABLE) <= FIXTURE_RECIPES, "a visa-loop case names an unknown recipe"
    for found in collect_cases():
        assert {"recipe_id", "scenario", "request"} <= set(found.case), found.test


def test_the_wgfmu_recipes_are_every_recipe_with_a_wgfmu_path() -> None:
    assert len(WGFMU_RECIPES) == 13
    roles = {rid for rid in RUNNABLE if any(r.function == "wgfmu" for r in REGISTRY.get(rid).roles.values())}
    assert roles | {"system.wgfmu_self_test", "system.wgfmu_self_cal"} == set(WGFMU_RECIPES)


def _value(arg: Any) -> Any:
    return getattr(arg, "value", arg)


@pytest.mark.wgfmu
@pytest.mark.parametrize("recipe_id", WGFMU_RECIPES)
def test_every_wgfmu_recipe_runs_through_the_fake_abi(recipe_id: str, world: VisaWorld,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[Any, ...], bool]] = []
    original = LoopWgfmuLibrary.dispatch

    def dispatch(self: LoopWgfmuLibrary, name: str, args: tuple[Any, ...]) -> int:
        calls.append((name, tuple(_value(a) for a in args), self.bus.lock_is_free()))
        return original(self, name, args)

    monkeypatch.setattr(LoopWgfmuLibrary, "dispatch", dispatch)
    recipe = REGISTRY.get(recipe_id)
    case = case_of(recipe_id).case
    prepare(world, recipe, case)
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("visa", False, "lop")

    assert bus.stats.wgfmu_loads >= 1, "the WGFMU binding never loaded the (fake) wgfmu.dll"
    names = [name for name, _, _ in calls]
    assert names and all(free for _, _, free in calls), "a library call while a VISA session held the lock"
    assert names.count("WGFMU_openSession") == names.count("WGFMU_closeSession") >= 1
    assert names[-1] == "WGFMU_closeSession"
    assert WORK & set(names), f"the recipe's work did not go through the library: {sorted(set(names))}"
    for index, (name, args, _) in enumerate(calls):
        if name == "WGFMU_connect":
            later = [a for n, a, _ in calls[index + 1:] if n == "WGFMU_disconnect"]
            assert any(a[:1] == args[:1] for a in later), f"channel {args[0]} connected and never disconnected"
    bus.sync_in()
    bus.instrument.assert_safe()  # SMU/MFCMU off, SPGU stopped, every WGFMU channel idle, library session closed
    assert all(not s.connected and not s.running for s in bus.instrument.state.wgfmu.values())
    assert bus.lock_is_free() and all(session.closed for session in bus.sessions)
