"""Helpers for the ``spgu_pulse`` pulse-mode tests (WP9.3): plans of the real recipes compiled against the committed
config (examples, a temporary ``B1500_CONFIG_DIR`` selecting the scenario and, optionally, a station override) and a
transaction harness on the same scenario with the recorded selectors (``selector_helpers.SELECTORS``), so a test can
run the real kind and look at the simulator's SPGU spy (``SimInstrument.spgu_runs``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import ConfigBundle, load_config
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, Paths
from b1500_test_agent.rules import RulesEngine
from tests.safety.helpers import Harness, HookTransport, make_harness
from tests.sim.helpers import REPO_ROOT, load_scenario, noiseless
from tests.sim.selector_helpers import SELECTORS
from tests.unit.rules_factory import T0

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)

PULSE_TRAIN = {"recipe_id": "spgu.pulse_train", "pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
ALWG = {"recipe_id": "spgu.alwg_sequence", "pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
CHARGE_PUMPING = {"recipe_id": "mosfet.charge_pumping", "pin_map": "mosfet-cp", "dut_profile": "nmos-cv"}
"""The card example requests (the scenarios: ``fefet_lab`` for the first two, ``nmos_cv`` for charge pumping)."""


def repo_bundle(tmp: Path, scenario: str, *, station: dict[str, Any] | None = None) -> ConfigBundle:
    """The committed config with the simulator on ``scenario`` (and ``station`` as the station profile when given)."""
    cfg = tmp / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
    settings["sim"]["scenario"] = scenario
    (cfg / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    if station is not None:
        (cfg / "station.yaml").write_text(yaml.safe_dump(station, sort_keys=False), encoding="utf-8")
    env = {ENV_CONFIG_DIR: str(cfg), ENV_DATA_DIR: str(tmp / "data")}
    return load_config(Paths.from_env(env, repo_root=REPO_ROOT))


def compile_plan(tmp: Path, scenario: str, request: dict[str, Any], **params: Any) -> PlanRecord:
    """A rule-checked plan of ``request`` (+ ``params``) on ``scenario`` (not stored)."""
    bundle = repo_bundle(tmp, scenario)
    req = PlanRequest.model_validate({**request, "params": {**request.get("params", {}), **params}})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, bundle, RulesEngine(bundle, clock=lambda: T0))


def pulse_harness(tmp: Path, scenario: str, *, hook_type: type[HookTransport] = HookTransport,
                  **changes: Any) -> Harness:
    """A transaction harness on the noiseless committed ``scenario`` (``changes`` update the scenario, e.g.
    ``faults``) with SEL1/SEL2 declared as recorded."""
    sim_scenario = noiseless(load_scenario(scenario))
    if changes:
        sim_scenario = sim_scenario.model_copy(update=changes)
    return make_harness(tmp, sim_scenario, hook_type=hook_type, switches=SELECTORS)
