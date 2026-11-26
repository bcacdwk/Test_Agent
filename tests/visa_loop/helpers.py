"""Hermetic worlds for the visa-loop suite (blueprint v2 7.1, 8.1 ``visa_loop/``).

A ``VisaWorld`` is a temporary repository root whose ``config/local/`` selects backend ``visa`` exactly as the lab
PC's would (settings, station and policy, and every committed example pin map and DUT profile copied as local files;
the real ``config/local/`` is never read or written), a temporary ``B1500_DATA_DIR`` and a bus directory for the
``LoopBus`` instruments. No ``B1500_CONFIG_DIR`` (backend visa refuses it, rule R-CFG-01). Services get the real
``make_bus`` with the visa-loop resource manager injected, so the whole stack down to ``VisaTransport`` is real.
The world's ``wgfmu.library`` names a synthetic x64 ``wgfmu.dll`` (``tests/wgfmu_abi/pe_builder.py``) and the bus
factory injects the loop's WGFMU library (``LoopBus.wgfmu_library``: the real ``WgfmuDll`` over the fake ABI), so the
library probe and session run as on the lab PC (WP10.2).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.catalog.executor import BusFactory
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.paths import ENV_DATA_DIR, ENV_HOME, Paths
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.audit import AuditSink
from b1500_test_agent.transport.base import Bus
from b1500_test_agent.transport.factory import make_bus
from tests.integration.sweep_cases import CASES as SWEEP_CASES
from tests.integration.test_plan_goldens import CASES, GENERIC_3T
from tests.sim.helpers import load_scenario
from tests.visa_loop.loop import DEFAULT_RESOURCE, LoopBus
from tests.wgfmu_abi.pe_builder import write_dll

REPO_ROOT = Path(__file__).resolve().parents[2]

SPOT_CASES: list[dict[str, Any]] = [
    {"recipe_id": "system.zero_check", "scenario": "lab_station", "source": "card zero-check", "chunk": 8,
     "request": {"params": {}, "pin_map": "open-smus", "dut_profile": "open-circuit"}},
    {"recipe_id": "generic.smu_spot", "scenario": "resistor_100k", "source": "card smu-spot-kelvin", "chunk": 8,
     "request": {"params": {}, "pin_map": "resistor-2t", "dut_profile": "resistor-generic"}},
    {"recipe_id": "resistor.kelvin_4w", "scenario": "resistor_1r_kelvin", "source": "card smu-spot-kelvin",
     "chunk": 8, "request": {"params": {}, "pin_map": "resistor-4w", "dut_profile": "resistor-1r"}},
]
"""The kind ``smu_spot`` recipes of WP7.1 with their card example requests and scenarios. A spot read is one
element per measured channel (16 to 64 bytes), so these cases read through 8-byte VISA chunks to keep the chunked
path exercised."""

CORRECTION_CASES: list[dict[str, Any]] = [
    {"recipe_id": recipe_id, "scenario": "capacitor_100p", "source": "card cmu-correction",
     "request": {"params": {}, "pin_map": "capacitor-cmu"}}
    for recipe_id in ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short", "cmu.correction_load")
]
"""The WP8.2 MFCMU correction recipes (kind ``cmu_correction``) with the card example request; no run table (like
``system.*``), so they are not in ``DATA_CASES``; ``cmu.correction_load`` needs the load standard in the station
profile (``tests/visa_loop/test_cmu_correction_visa.py`` writes it)."""

CORRECTION_RECIPES = frozenset(c["recipe_id"] for c in CORRECTION_CASES)

MEASUREMENT_CASES: list[dict[str, Any]] = [*CASES, *SWEEP_CASES, *SPOT_CASES, *CORRECTION_CASES]
"""The nine v1 runnable recipes with their card example requests (or recipe defaults) and v1 scenarios: the seven
measurement recipes (WP5.5) and ``system.self_test``/``system.self_cal`` (kind ``system`` on visa, WP6.2); plus the
five WP7.2 sweep recipes (``tests/integration/sweep_cases.CASES``: WI, WSV, MM 16, the two stepped families), the
three WP7.1 spot recipes (``SPOT_CASES``) and the four WP8.2 correction recipes (``CORRECTION_CASES``)."""

SYSTEM_RECIPES = frozenset({"system.self_test", "system.self_cal"})
"""The recipes of kind ``system`` (no output, no run table; ``system.zero_check`` is a measurement)."""

DATA_CASES: list[dict[str, Any]] = [c for c in MEASUREMENT_CASES
                                     if c["recipe_id"] not in SYSTEM_RECIPES | CORRECTION_RECIPES]
"""The cases that write a run table (every recipe but the kind ``system`` and ``cmu_correction`` ones)."""

SYSTEM_CASES: list[dict[str, Any]] = [c for c in MEASUREMENT_CASES if c["recipe_id"] in SYSTEM_RECIPES]

ROUTE_CASES: list[dict[str, Any]] = [
    {"recipe_id": "system.selector_check", "scenario": "lab_station", "source": "card spgu/selector-check",
     "request": {"params": {"dwell_s": 0.0}, "pin_map": "fefet-sel"}},
]
"""Route-only recipes of WP9.2 (kind ``spgu_pulse`` mode ``route_only``: no output, no run table) with their card
example requests (``dwell_s`` 0: the visa-loop sleeps for real between steps)."""


def bus_factory(bus: LoopBus) -> BusFactory:
    """The executor's bus factory: the real ``make_bus`` with the visa-loop resource manager and WGFMU library
    injected."""

    def build(bundle: ConfigBundle, sink: AuditSink) -> Bus:
        return make_bus(bundle.settings, sink, rm_factory=bus.manager, wgfmu_factory=bus.wgfmu_library)

    return build


@dataclass
class VisaWorld:
    root: Path
    data: Path
    bus_dir: Path
    services: list[B1500Service] = field(default_factory=list)

    @property
    def paths(self) -> Paths:
        return Paths.from_env({ENV_DATA_DIR: str(self.data)}, repo_root=self.root)

    @property
    def local(self) -> Path:
        return self.root / "config" / "local"

    @property
    def state_dir(self) -> Path:
        return self.data / "state"

    def write_local(self, rel: str, data: Any) -> Path:
        path = self.local / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def set_visa(self, **visa: Any) -> None:
        """Change ``visa:`` keys of ``config/local/settings.yaml``."""
        path = self.local / "settings.yaml"
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
        settings["visa"].update(visa)
        self.write_local("settings.yaml", settings)

    def bus(self, scenario: str, **kwargs: Any) -> LoopBus:
        """A ``LoopBus`` in this world's bus directory simulating committed scenario ``scenario``."""
        return LoopBus(self.bus_dir, load_scenario(scenario), **kwargs)

    def service(self, bus: LoopBus, **kwargs: Any) -> B1500Service:
        """A ``B1500Service`` on backend visa over ``bus`` (adapter ``cli`` unless given); closed by the fixture."""
        kwargs.setdefault("registry", RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT))
        kwargs.setdefault("lock_timeout_s", 2.0)
        service = B1500Service(paths=self.paths, bus_factory=bus_factory(bus), **kwargs)
        self.services.append(service)
        return service

    def env(self, bus: LoopBus) -> dict[str, str]:
        """Environment of a child process (CLI or MCP server) in this world over ``bus``; copies ``recipes/`` into the
        temporary root first (the CLI loads recipes from ``$B1500_HOME/recipes``)."""
        if not (self.root / "recipes").exists():
            shutil.copytree(REPO_ROOT / "recipes", self.root / "recipes")
        return {ENV_HOME: str(self.root), ENV_DATA_DIR: str(self.data), **bus.env()}

    def audit_events(self) -> list[AuditEvent]:
        """Every audit event under the data directory (daily files and run folders; the bring-up step ledgers under
        ``state/bringup/`` are no audit)."""
        events = []
        for path in sorted(self.data.rglob("*.jsonl")):
            if path.name in ("index.jsonl", "notes.jsonl") or path.parent.name == "bringup":
                continue
            events += [AuditEvent.from_json_line(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return events

    def daily_events(self) -> list[AuditEvent]:
        events = []
        for path in sorted((self.state_dir / "audit").glob("*.jsonl")):
            events += [AuditEvent.from_json_line(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return events

    def run_events(self, run_id: str) -> list[AuditEvent]:
        path = next(self.data.joinpath("runs").rglob(f"{run_id}/audit.jsonl"))
        return [AuditEvent.from_json_line(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def run_dir(self, run_id: str) -> Path:
        return next(p for p in self.data.joinpath("runs").rglob(run_id) if p.is_dir())

    def close(self) -> None:
        for service in self.services:
            service.close()


def make_visa_world(tmp_path: Path, **visa: Any) -> VisaWorld:
    """A world under ``tmp_path`` (module docstring); ``visa`` overrides ``visa:`` settings keys."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "config", root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    world = VisaWorld(root=root, data=tmp_path / "data", bus_dir=tmp_path / "bus")
    config = root / "config"
    settings = yaml.safe_load((config / "settings.example.yaml").read_text(encoding="utf-8"))
    settings["backend"] = "visa"
    settings["visa"].update({"resource": DEFAULT_RESOURCE, "lock_timeout_ms": 500, **visa})
    settings["wgfmu"] = {"library": write_dll(tmp_path / "lib" / "wgfmu.dll")}  # synthetic x64 DLL, never loaded
    world.write_local("settings.yaml", settings)
    for item in ("station", "policy"):
        shutil.copyfile(config / f"{item}.example.yaml", world.local / f"{item}.yaml")
    for folder in ("pinmaps", "duts"):
        (world.local / folder).mkdir(parents=True, exist_ok=True)
        for example in sorted((config / folder).glob("*.example.yaml")):
            shutil.copyfile(example, world.local / folder / example.name.replace(".example.yaml", ".yaml"))
    for rel, data in GENERIC_3T.items():  # test-only pin map/DUT of generic.smu_staircase (as in the goldens)
        world.write_local(rel, data)
    return world


def run_case(service: B1500Service, case: dict[str, Any]) -> RunSummary:
    """Validate a ``MEASUREMENT_CASES`` request and run it; when the tier asks for a confirmation, the test confirms
    with the plan's own summary (the test stands in for the human)."""
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert validation.ok and validation.plan_id is not None, validation.message
    if validation.tier == "ok":
        return service.run_plan(validation.plan_id)
    assert validation.tier == "needs_confirmation" and validation.summary is not None
    return service.run_confirmed_plan(validation.plan_id, summary=validation.summary)


SWITCH_MNEMONICS = frozenset({"ERMOD", "ERMOD?", "ERSSP", "ERSSP?"})
SWITCH_LEARN = frozenset({"*LRN? 81", "*LRN? 62"})
"""The declared-switch traffic every transaction on the lab station example sends since WP9.2 (blueprint v2 2.6):
the pre-execute snapshot's ``ERMOD?``/``ERMOD 1``/``ERSSP?`` and SCUU/ASU read-backs, cleanup step 5 (``ERMOD 1`` +
``ERSSP p,0`` per declared port, the SCUU/ASU read-backs) and step 8 (``ERSSP?`` per port, ``*LRN? 81``/``62``)."""


def ok_commands(log: list[Any]) -> list[str]:
    """Every executed command of a simulator command log, in order."""
    return [r.command for r in log if r.outcome == "ok"]


def without_switch_traffic(log: list[Any]) -> list[str]:
    """The mnemonics of the executed commands without the declared-switch traffic (``SWITCH_MNEMONICS``,
    ``SWITCH_LEARN``), i.e. the v1/v2 measurement and cleanup flow the older assertions describe."""
    return [r.mnemonic for r in log if r.outcome == "ok" and r.mnemonic not in SWITCH_MNEMONICS
            and r.command not in SWITCH_LEARN]


def assert_selectors_restored(log: list[Any], ports: tuple[int, ...] = (0, 1, 2, 3)) -> None:
    """Cleanup steps 5 and 8 on the lab station example (SEL1/SEL2 declared present, rest open): after the last
    ``DZ`` the control mode and ``ERSSP p,0`` for every declared port, then ``CL``; after ``CL`` the read-back
    ``ERSSP? p`` of every port. Nothing switched a selector to a non-rest state after the last ``DZ``."""
    sent = ok_commands(log)
    dz = len(sent) - 1 - sent[::-1].index("DZ")
    cl = sent.index("CL", dz)
    restore = [c for c in sent[dz:cl] if c.split(" ")[0] in ("ERMOD", "ERSSP")]
    assert restore == ["ERMOD 1", *[f"ERSSP {p},0" for p in ports[:2]], "ERMOD 1",
                       *[f"ERSSP {p},0" for p in ports[2:]]], restore
    assert [c for c in sent[cl:] if c.startswith("ERSSP?")] == [f"ERSSP? {p}" for p in ports]


def bus_events(events: list[AuditEvent]) -> list[str]:
    """The bus lifecycle and lock events, in order (``lock_acquired``/``lock_released`` mark the file lock)."""
    keep = {"bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_acquired", "lock_released"}
    return [e.ev for e in events if e.ev in keep]


def per_transaction_overhead_ms(events: list[AuditEvent]) -> Iterator[float]:
    """ATV-13: open + lock + unlock + close time of each transaction or snapshot (grouped by ``tx``)."""
    totals: dict[str, float] = {}
    for event in events:
        if event.ev in ("bus_open", "bus_lock", "bus_unlock", "bus_close") and event.tx and event.dur_ms is not None:
            totals[event.tx] = totals.get(event.tx, 0.0) + event.dur_ms
    yield from totals.values()
