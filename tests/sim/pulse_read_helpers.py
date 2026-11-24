"""Helpers for the ``pulse_read`` tests (WP9.4): the card example requests, the test-only SMU-pulse recipe
(``tests/fixtures/recipes/generic/smu_pulse_read.yaml``), plans compiled against the committed config, a transaction
harness on ``fefet_lab`` with the recorded selectors (``selector_helpers.SELECTORS``) and the FeFET model truth."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.rules import RulesEngine
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from tests.safety.helpers import Harness, HookTransport
from tests.sim.helpers import REPO_ROOT, load_scenario
from tests.sim.spgu_pulse_helpers import pulse_harness, repo_bundle
from tests.unit.rules_factory import T0

SCENARIO = "fefet_lab"
FIXTURE_RECIPE = REPO_ROOT / "tests" / "fixtures" / "recipes" / "generic" / "smu_pulse_read.yaml"
BASE = {"pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
WRITE_READ = {"recipe_id": "fefet.pulse_write_read", **BASE}
PROGRAM_READ = {"recipe_id": "spgu.program_smu_read", **BASE}
SMU_PULSE_READ = {"recipe_id": "generic.smu_pulse_read", **BASE}
"""The card example requests (``fefet_lab``) and the SMU-pulse source request."""

AT_REST = {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open"}


def recipes_with_fixture(tmp: Path) -> Path:
    """A copy of ``recipes/`` plus the test-only ``generic.smu_pulse_read``."""
    target = tmp / "recipes"
    if not target.exists():
        shutil.copytree(REPO_ROOT / "recipes", target)
        shutil.copy(FIXTURE_RECIPE, target / "generic" / FIXTURE_RECIPE.name)
    return target


def registry(tmp: Path) -> RecipeRegistry:
    return RecipeRegistry.load(recipes_with_fixture(tmp), repo_root=REPO_ROOT)


def pr_plan(tmp: Path, request: dict[str, Any], *, station: dict[str, Any] | None = None, **params: Any) \
        -> PlanRecord:
    """A rule-checked plan of ``request`` (+ ``params``) on ``fefet_lab`` (not stored)."""
    bundle = repo_bundle(tmp / "cfg-root", SCENARIO, station=station)
    req = PlanRequest.model_validate({**request, "params": {**request.get("params", {}), **params}})
    return Planner(registry(tmp), clock=lambda: T0).plan(req, bundle, RulesEngine(bundle, clock=lambda: T0))


def pr_harness(tmp: Path, *, hook_type: type[HookTransport] = HookTransport, **changes: Any) -> Harness:
    """A transaction harness on the noiseless ``fefet_lab`` with SEL1/SEL2 recorded."""
    return pulse_harness(tmp, SCENARIO, hook_type=hook_type, **changes)


def fresh_fefet() -> FefetDevice:
    """The ``fefet_lab`` FeFET as the simulator builds it (erased, P = p_init)."""
    from b1500_test_agent.transport.sim.devices import Circuit

    device = Circuit(load_scenario(SCENARIO)).devices["dut"]
    assert isinstance(device, FefetDevice)
    return device


def mw_truth(v_program: float = 4.0, v_erase: float = -4.0, width: float = 1e-6) -> float:
    """``memory_window_truth`` of a fresh ``fefet_lab`` device (the S12 grader's truth)."""
    return fresh_fefet().memory_window_truth(v_program, v_erase, width)


def drain_current(p: float, vg: float, vd: float = 0.05) -> float:
    """Noiseless drain current of the ``fefet_lab`` FeFET at polarization ``p`` (no switching)."""
    device = fresh_fefet()
    device.p = p
    return device.instant_currents({"gate": vg, "drain": vd, "source": 0.0, "bulk": 0.0})["drain"]
