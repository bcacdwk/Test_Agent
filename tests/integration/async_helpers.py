"""Helpers of the asynchronous-run tests (WP5.6, blueprint v2 2.6, 8.1): worlds with a timed simulator scenario,
the test-only long stepped recipe and the plans built from it, and small waiting/inspection helpers.

Plans (pin map ``mosfet-4t``, DUT ``nmos-generic``, scenario ``nmos_basic`` wiring):

- ``IDVD_LONG``: the v1 recipe ``mosfet.idvd`` as a long run (21 gate steps of 40 points at long integration,
  ~9 min, asynchronous, tier ok);
- ``stepped_long(steps, ...)``: ``generic.stepped_long`` (``tests/fixtures/recipes/generic/stepped_long.yaml``) with
  ``steps`` gate levels; with the defaults each sweep (one segment) takes ~27 s, so 46 steps are a ~20 min plan and
  504 steps of 2 points with ``delay=13.7`` (~29.9 s segments) a 4 h plan; above 600 s they need ``long_run``
  confirmation.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.analysis.dataset import MANIFEST_FILE
from b1500_test_agent.archive.runfiles import read_progress
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import RunProgress
from b1500_test_agent.models.run import RunManifest
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.helpers import REPO_ROOT, World

FIXTURE_RECIPE = REPO_ROOT / "tests" / "fixtures" / "recipes" / "generic" / "stepped_long.yaml"
SCENARIO = "nmos_timed"
BASE = {"pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
IDVD_LONG: dict[str, Any] = {
    "recipe_id": "mosfet.idvd", **BASE,
    "params": {"vd_points": 40, "vg_start": 0.5, "vg_stop": 1.5, "vg_points": 21, "integration": "long"},
}  # fmt: skip


def idvd_long(**params: Any) -> dict[str, Any]:
    """``IDVD_LONG`` with some parameters changed (e.g. ``vg_points=5`` for a synchronous run of the same shape)."""
    return {**IDVD_LONG, "params": {**IDVD_LONG["params"], **params}}


def stepped_long(steps: int, *, vd_points: int = 10, delay: float = 2.0, integration: str = "long",
                 **params: Any) -> dict[str, Any]:
    """A ``generic.stepped_long`` request with ``steps`` distinct gate levels between 0.5 and 1.5 V."""
    levels = [round(0.5 + i / max(steps - 1, 1), 6) for i in range(steps)] if steps > 1 else [0.5]
    return {"recipe_id": "generic.stepped_long", **BASE,
            "params": {"vd_points": vd_points, "delay": delay, "integration": integration, "vg_values": levels,
                       **params}}


def timed_world(world: World, *, timing: str = "instant", auto_calibration: bool = False,
                faults: list[dict[str, Any]] | None = None, fixture_recipe: bool = True) -> World:
    """``world`` on scenario ``nmos_timed`` (a copy of ``nmos_basic`` with ``timing``, the initial ``CM`` state and an
    optional fault profile) and, with ``fixture_recipe``, a temporary copy of ``recipes/`` plus the test-only
    ``generic.stepped_long`` (also copied into the CLI root, so CLI processes see the same recipes)."""
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_basic.yaml").read_text(encoding="utf-8"))
    scenario.update({"timing": timing, "auto_calibration": auto_calibration, "faults": None})
    if faults:
        world.write_config("sim/faults/timed_faults.yaml", {"description": "test", "faults": faults})
        scenario["faults"] = "timed_faults"
    world.write_config(f"sim/scenarios/{SCENARIO}.yaml", scenario)
    settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
    settings["sim"]["scenario"] = SCENARIO
    world.write_config("settings.yaml", settings)
    if fixture_recipe:
        recipes = world.root / "recipes"
        if not recipes.exists():
            shutil.copytree(REPO_ROOT / "recipes", recipes)
        shutil.copy(FIXTURE_RECIPE, recipes / "generic" / FIXTURE_RECIPE.name)
        world.recipes = recipes
    return world


def wait_for(predicate: Callable[[], Any], timeout_s: float = 30.0, interval_s: float = 0.05) -> Any:
    """Poll ``predicate`` until it returns a truthy value (returned) or ``timeout_s`` passes (``AssertionError``)."""
    deadline = time.monotonic() + timeout_s
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not met within {timeout_s} s")
        time.sleep(interval_s)


def run_dir(world: World, run_id: str) -> Path:
    """The folder of ``run_id`` (finished or not)."""
    return world.runs_dir / run_id[1:5] / run_id[5:7] / run_id[7:9] / run_id


def progress_of(world: World, run_id: str) -> RunProgress | None:
    return read_progress(run_dir(world, run_id))


def manifest_of(world: World, run_id: str) -> RunManifest | None:
    path = run_dir(world, run_id) / MANIFEST_FILE
    return RunManifest.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def run_events(world: World, run_id: str) -> list[AuditEvent]:
    """The run's own audit events (``<run>/audit.jsonl``)."""
    path = run_dir(world, run_id) / "audit.jsonl"
    return [AuditEvent.from_json_line(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sim_state_safe(world: World, scenario: str = SCENARIO) -> list[str]:
    """Why the persisted simulator state is not safe (empty when every output is off at 0 V)."""
    state = load_state_file(sim_state_file(world.state_dir, scenario))
    assert state is not None
    return [f"channel {ch}: {st.output_on} {st.voltage}" for ch, st in sorted(state.channels.items())
            if st.output_on or st.voltage != 0.0]


def assert_async_invariant(world: World, run_id: str, scenario: str = SCENARIO) -> RunManifest:
    """The global invariant after an asynchronous run ended (blueprint v2 2.6, 8.1): finalized with a cleanup that is
    verified (and the simulator safe) or the fault latch set with ``cleanup_unverified`` audited; DZ and CL after the
    last source command; no lock, no in-flight marker, no abort request left; a final progress record."""
    manifest = manifest_of(world, run_id)
    assert manifest is not None, "the run was not finalized"
    fault = world.state_dir / "fault.json"
    cleanup = manifest.cleanup
    assert cleanup is not None
    if cleanup.verified == "unverified":
        assert fault.is_file() and cleanup.latched_fault
        assert any(e.ev == "cleanup_unverified" for e in run_events(world, run_id))
    else:
        assert sim_state_safe(world, scenario) == []
        log = world.sim_log(scenario)
        sources = [r for r in log if r.source and r.outcome != "dropped"]
        if sources:
            after = {r.mnemonic for r in log if r.seq > sources[-1].seq and r.outcome == "ok"}
            assert {"DZ", "CL"} <= after, sorted(after)
    assert not (world.state_dir / "inflight.json").exists(), "inflight marker left behind"
    assert not (world.state_dir / "abort.json").exists(), "abort request left behind"
    holder = world.state_dir / "locks"
    if holder.is_dir():
        assert not any(p.suffix == ".json" for p in holder.iterdir()), "lock sidecar left behind"
    progress = read_progress(run_dir(world, run_id))
    if manifest.plan.mode == "async":
        assert progress is not None and progress.state != "running", progress
    return manifest


def partial_rows(world: World, run_id: str) -> int:
    """Data rows in the run's ``partial.csv`` (0 without one)."""
    path = run_dir(world, run_id) / "partial.csv"
    if not path.is_file():
        return 0
    return max(0, len(path.read_text(encoding="utf-8").splitlines()) - 1)


def json_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
