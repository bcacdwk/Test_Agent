"""Helpers for the executor-level integration tests (blueprint 8.1 ``integration/``; WP1.8 adds the service and CLI
layers on top).

Every test gets a hermetic world: a temporary repository root holding a copy of the committed ``config/`` (never
``config/local/``), a temporary ``B1500_CONFIG_DIR`` for test-specific config files and a temporary
``B1500_DATA_DIR`` for plans, runs and simulator state. Recipes come from the repository's ``recipes/`` (or a
temporary copy when a test edits one). Nothing touches hardware.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.catalog.executor import Executor
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.models.audit import TRANSPORT_EVENTS, AuditEvent
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.run import ClientInfo, RunSummary
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME, Paths
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.state import CommandRecord, load_state_file, sim_state_file

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = ClientInfo(adapter="cli")
MCP = ClientInfo(adapter="mcp", session_tag="test-session")
IDVG = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}


@dataclass
class Clock:
    """A controllable UTC clock (real time plus ``offset``)."""

    offset: timedelta = field(default_factory=timedelta)

    def __call__(self) -> datetime:
        return datetime.now(UTC) + self.offset


@dataclass
class World:
    root: Path
    cfg: Path
    data: Path
    recipes: Path
    clock: Clock
    executors: list[Executor] = field(default_factory=list)
    services: list[B1500Service] = field(default_factory=list)

    @property
    def paths(self) -> Paths:
        env = {ENV_CONFIG_DIR: str(self.cfg), ENV_DATA_DIR: str(self.data)}
        return Paths.from_env(env, repo_root=self.root)

    @property
    def state_dir(self) -> Path:
        return self.data / "state"

    @property
    def runs_dir(self) -> Path:
        return self.data / "runs"

    def executor(self, **kwargs: Any) -> Executor:
        registry = RecipeRegistry.load(self.recipes, repo_root=REPO_ROOT)
        kwargs.setdefault("clock", self.clock)
        executor = Executor(ConfigLoader(self.paths), registry=registry, **kwargs)
        self.executors.append(executor)
        return executor

    def service(self, **kwargs: Any) -> B1500Service:
        """A ``B1500Service`` over this world (adapter ``cli`` unless given); closed by the fixture."""
        kwargs.setdefault("registry", RecipeRegistry.load(self.recipes, repo_root=REPO_ROOT))
        kwargs.setdefault("clock", self.clock)
        service = B1500Service(paths=self.paths, **kwargs)
        self.services.append(service)
        return service

    def env(self) -> dict[str, str]:
        """``B1500_HOME``/``B1500_CONFIG_DIR``/``B1500_DATA_DIR`` for a CLI process in this world; copies
        ``recipes/`` into the temporary root first (the CLI loads recipes from ``$B1500_HOME/recipes``)."""
        if not (self.root / "recipes").exists():
            shutil.copytree(REPO_ROOT / "recipes", self.root / "recipes")
        return {ENV_HOME: str(self.root), ENV_CONFIG_DIR: str(self.cfg), ENV_DATA_DIR: str(self.data)}

    def write_config(self, rel: str, data: Any) -> Path:
        """A YAML file in the temporary ``B1500_CONFIG_DIR`` (e.g. ``duts/nmos-generic.yaml``)."""
        path = self.cfg / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def use_scenario(self, scenario: str) -> None:
        """Select committed simulator scenario ``scenario`` through a temporary ``settings.yaml``."""
        settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
        settings["sim"]["scenario"] = scenario
        self.write_config("settings.yaml", settings)

    def use_faults(self, name: str, faults: list[dict[str, Any]]) -> None:
        """Select a copy of ``nmos_basic`` whose fault profile ``name`` holds ``faults``."""
        scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_basic.yaml").read_text(encoding="utf-8"))
        scenario["faults"] = name
        self.write_config(f"sim/faults/{name}.yaml", {"description": "test", "faults": faults})
        self.write_config(f"sim/scenarios/nmos_{name}.yaml", scenario)
        settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
        settings["sim"]["scenario"] = f"nmos_{name}"
        self.write_config("settings.yaml", settings)

    def sim_log(self, scenario: str = "nmos_basic") -> list[CommandRecord]:
        state = load_state_file(sim_state_file(self.state_dir, scenario))
        return [] if state is None else list(state.command_log)

    def audit_events(self) -> list[AuditEvent]:
        """Every audit event written anywhere under the data directory (daily files and run folders; the bring-up
        step ledgers under ``state/bringup/`` are no audit)."""
        events = []
        for path in sorted(self.data.rglob("*.jsonl")):
            if path.name in ("index.jsonl", "notes.jsonl") or path.parent.name == "bringup":
                continue
            events += [AuditEvent.from_json_line(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return events

    def run_dirs(self) -> list[Path]:
        return sorted(p.parent for p in self.runs_dir.rglob("manifest.json")) if self.runs_dir.exists() else []

    def io_marker(self) -> tuple[int, int, int, bool]:
        """(sim commands, transport audit events, run folders, sim state saved) - unchanged means zero I/O."""
        transport = sum(e.ev in TRANSPORT_EVENTS for e in self.audit_events())
        folders = len(list(self.runs_dir.glob("*/*/*/*"))) if self.runs_dir.exists() else 0
        return len(self.sim_log()), transport, folders, sim_state_file(self.state_dir, "nmos_basic").exists()


def plan(executor: Executor, **changes: Any) -> PlanRecord:
    data = {**IDVG, **changes}
    return executor.plan(PlanRequest.model_validate(data))


def run(executor: Executor, plan_id: str, summary: str | None = None, *, dut: str | None = None,
        client: ClientInfo = CLI) -> RunSummary:
    return executor.run(plan_id, confirmed_summary=summary, dut_instance=dut, client=client)



def make_world(tmp_path: Path) -> World:
    """A hermetic world under ``tmp_path`` (see the module docstring)."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "config", root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return World(root=root, cfg=cfg, data=tmp_path / "data", recipes=REPO_ROOT / "recipes", clock=Clock())


UNRUNNABLE_DEMO = "demo.unregistered_kind"
"""A test-only recipe whose kind is not registered (WP11.2: the reserved slots and their status are gone; what R-REC-01
still blocks is a recipe whose kind has no code path on the backend, e.g. a broken tree)."""


def with_unrunnable_recipe(world: World, tmp_path: Path) -> str:
    """Copy ``recipes/`` to ``tmp_path`` with one extra recipe ``UNRUNNABLE_DEMO`` (the BTI recipe under a kind no
    registry knows) and point the world at it; returns its id."""
    recipes = tmp_path / "recipes"
    if not recipes.exists():
        shutil.copytree(REPO_ROOT / "recipes", recipes)
    data = yaml.safe_load((recipes / "reliability" / "bti_sms.yaml").read_text(encoding="utf-8"))
    data.update(id=UNRUNNABLE_DEMO, kind="demo_unregistered_kind", card=None, analysis_defaults=[])
    (recipes / "demo").mkdir(exist_ok=True)
    (recipes / "demo" / "unregistered_kind.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    world.recipes = recipes
    return UNRUNNABLE_DEMO
