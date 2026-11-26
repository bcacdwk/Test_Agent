"""The scripted bring-up rehearsal (v2.1 plan §4.4; WP21.7): a walker that takes each step ``b1500 bringup next``
names, does it as the agent and the scripted human would, and records it with ``b1500 bringup done``
(``bringup_steps``, in-process, as the CLI calls them).

- **The human** answers every human step with their own words (``HUMAN``), adopts configuration (``config.adopt``,
  the function behind the human-only CLI command) and reviews drafts into ``validation/hw/`` (visa-loop). A physical
  landing is the simulator scenario the next run needs (the simulator world's ``settings.sim.scenario``, the
  visa-loop's bus), set right before that run, or a test-local copy of it: the two-wire landing of L2.P5 (Sense
  lifted), the kill drill's fault profile.
- **The agent** runs each run step's recipes with the request of the recipe's visa-loop case
  (``tests/visa_loop/cases``: every recipe has one, with its scenario and the local files it needs), adjusted where
  the stage file asks for something else (``OVERRIDES``: the long zero check, the drills, the two-wire reading, the
  log sampling, the short timer chain, L1's open-terminal pin map); the MFCMU corrections a C-V plan needs
  (R-CORR-01) run first on the same landing; a plan of tier ``needs_confirmation`` runs with ``run_confirmed_plan``
  and its own summary (the scripted human consents); asynchronous runs are followed to the end; the cancel drill is
  the abort file another process's ``safe_shutdown`` writes (at a checkpoint, deterministic), the kill drill a run
  interrupted mid-way. Probes, proposals, doctor lines (injected, as in the integration tests), observations and the
  session's station checks complete the agent's part.
- **Backends**: ``SimRehearsal`` (the simulator ledger: records and captures are refused by design and the steps
  recorded as rehearsed after the walker saw the refusal) and ``tests/visa_loop/test_bringup_sequence_visa.py``
  (``H...`` runs, drafts, fixtures, adopted configuration and reviews in the test's temporary folders).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent import bringup, bringup_steps
from b1500_test_agent.bringup_ledger import effective_kind, load_steps
from b1500_test_agent.bringup_verify import StepArgs
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.models.validation import StepDone, StepSpec
from b1500_test_agent.service import B1500Admin, B1500Service
from b1500_test_agent.session import AbortFile, Transaction
from tests.integration.helpers import REPO_ROOT, World
from tests.visa_loop.cases import case_of

STEPS = load_steps(REPO_ROOT)
OWNER = "Owner"
HUMAN = {"human": "done (rehearsal)", "by": OWNER}
DOCTOR = [("python", "PASS", "CPython 3.12"), ("harness files", "PASS", "wired"),
          ("harness versions", "PASS", "= config/harness/validated.yaml")]
CORRECTIONS = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")
WGFMU_SESSION_PROBES = frozenset({"L0.A2", "L8.A1"})
"""Probe steps whose stage file asks for ``doctor --probe --wgfmu-session``."""
Variant = tuple[str, Callable[[dict[str, Any]], None]]


@dataclass(frozen=True)
class Override:
    """How a step runs a recipe differently from its visa-loop case: ``params`` merged into the case's, ``request``
    keys replaced (pin map, DUT profile), another ``scenario`` (a landing), a test-local scenario ``variant`` (name,
    edit of the scenario data), a cancel ``abort_at`` this checkpoint, ``repeat`` runs of the plan and ``extra``
    runs of the same recipe with further ``params`` changes."""

    params: dict[str, Any] = field(default_factory=dict)
    request: dict[str, Any] = field(default_factory=dict)
    scenario: str | None = None
    variant: Variant | None = None
    abort_at: int | None = None
    repeat: int = 1
    extra: tuple[dict[str, Any], ...] = ()


def _two_wire(data: dict[str, Any]) -> None:
    data["models"]["dut"]["params"]["kelvin"] = "none"  # L2.P5: both Sense probes lifted, Force landed


def _kill_drill(data: dict[str, Any]) -> None:
    data["faults"] = "rehearsal_kill"  # L9.P3: the process dies mid-run; the run ends aborted, cleanup verified


def _stuck_cleanup(data: dict[str, Any]) -> None:
    data["faults"] = "rehearsal_stuck"  # DZ and CL time out: cleanup unverified, fault latched


FAULT_PROFILES: dict[str, dict[str, Any]] = {
    "rehearsal_kill": {"description": "rehearsal kill drill (L9.P3): the run is interrupted mid-way",
                       "faults": [{"kind": "run_interrupt", "segment": 1}]},
    "rehearsal_stuck": {"description": "rehearsal failure routing: DZ and CL writes time out",
                        "faults": [{"kind": "cleanup_failure"}]},
}
LONG_ZERO = {"integration": "long", "samples": 50}
"""L1 agent step 5 (and L10's session end): the long zero check, asynchronous."""
BTI_10_MIN = {"stress_time": 600.0}
"""L9's BTI plan: 10 min of stress, asynchronous (``long_run``), so the drills act on a running run."""
OPEN_TERMINALS = {"pin_map": "open-smus", "dut_profile": "open-circuit"}
OVERRIDES: dict[tuple[str, str], Override] = {
    ("L1.A3", "system.self_test"): Override(request=OPEN_TERMINALS, scenario="lab_station"),
    ("L1.A3", "system.self_cal"): Override(request=OPEN_TERMINALS, scenario="lab_station"),
    ("L1.A5", "system.zero_check"): Override(params=LONG_ZERO),
    ("L1.A6", "system.zero_check"): Override(params=LONG_ZERO, abort_at=1),
    ("L1.A8", "system.zero_check"): Override(params={"ranges": [1e-11], "samples": 10}),
    ("L2.A8", "resistor.kelvin_4w"): Override(variant=("resistor_1r_two_wire", _two_wire)),
    ("L5.A7", "generic.smu_sampling"): Override(extra=({"sampling_mode": "log25", "points": 101,
                                                        "interval": 0.002},)),
    ("L7.A7", "fefet.dual_sweep_mw"): Override(repeat=2),
    ("L9.A2", "reliability.bti_sms"): Override(params=BTI_10_MIN),
    ("L9.A3", "reliability.bti_sms"): Override(params=BTI_10_MIN, abort_at=1),
    ("L9.A4", "reliability.bti_sms"): Override(params=BTI_10_MIN),
    ("L9.A5", "reliability.bti_sms"): Override(params=BTI_10_MIN, variant=("nmos_bti_kill", _kill_drill)),
    ("L9.A11", "generic.smu_sampling"): Override(params={"points": 101}),
    ("L10.A2", "system.zero_check"): Override(params=LONG_ZERO),
}
"""Where a step runs a recipe otherwise than its visa-loop case (the stage file's agent step says so)."""
CAPTURE_RUNS = frozenset({"L1.A8"})
"""Capture steps that run their recipe anew (L1's short zero check); the others capture runs of the stage."""
PROPOSALS: dict[str, tuple[str, ...]] = {
    "L1.A2": ("pinmaps/open-smus", "duts/open-circuit"),
    "L2.A2": ("pinmaps/resistor-2t", "duts/resistor-generic", "pinmaps/resistor-4w", "duts/resistor-1r"),
}
"""Pin map and DUT proposals the agent writes under ``work/bringup/`` (copies of the committed examples the stage
names), for the visa-loop walk (on the simulator these steps are the human's ``done``)."""
ADOPTED: dict[str, tuple[str, ...]] = {
    "L0.P3": ("pinmaps/open-smus", "duts/open-circuit"),
    "L1.P2": ("pinmaps/open-smus", "duts/open-circuit"),
    "L2.P2": ("pinmaps/resistor-2t", "duts/resistor-generic"),
    "L2.P4": ("pinmaps/resistor-4w", "duts/resistor-1r"),
}
"""The pin maps and DUT profiles the human adopts at each configuration step of the visa-loop walk."""


@contextmanager
def abort_at_checkpoint(state_dir: Path, k: int) -> Iterator[None]:
    """Write an abort request when a run reaches checkpoint ``k``, as ``b1500 shutdown`` in the human's second window
    would (the deterministic cancel of ``tests/integration/test_async_cancel.py``)."""
    original = Transaction.checkpoint
    written: list[bool] = []

    def checkpoint(self: Transaction, done: int, total: int, phase: str = "", rows: Any = None) -> None:
        if done >= k and not written:
            written.append(True)
            AbortFile(state_dir).request("rehearsal cancel drill", adapter="cli")
        original(self, done, total, phase, rows)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Transaction, "checkpoint", checkpoint)
        yield


def scenario_data(scenario: str, variant: Variant | None) -> tuple[str, dict[str, Any]]:
    """The committed scenario's data, edited by ``variant`` (name, edit), and its name."""
    data = yaml.safe_load((REPO_ROOT / "config" / "sim" / "scenarios" / f"{scenario}.yaml").read_text(encoding="utf-8"))
    if variant is None:
        return scenario, data
    name, edit = variant
    edit(data)
    return name, data


class Rehearsal(ABC):
    """The walker (module docstring); subclasses bind it to a backend (``service``, ``land``, ``write_config``)."""

    backend: Backend = "sim"

    def __init__(self, root: Path, state_dir: Path) -> None:
        self.root = root
        self.state_dir = state_dir
        self.runs: dict[str, list[str]] = {}
        """Run ids by step (the evidence of each run or capture step)."""
        self.facts: dict[str, tuple[str, str]] = {}
        """Run id -> (recipe, outcome)."""
        self.recorded: list[StepDone] = []
        self.landed: str | None = None

    # -- backend hooks -----------------------------------------------------------------------------------------------

    @property
    @abstractmethod
    def service(self) -> B1500Service:
        """The service the agent's tools and the CLI run through (the landing's, on the visa-loop)."""

    @abstractmethod
    def land(self, scenario: str, variant: Variant | None = None) -> None:
        """The human lands the device of ``scenario`` (or of its test-local ``variant``)."""

    @abstractmethod
    def write_config(self, rel: str, data: Any) -> None:
        """A local configuration file the run's case needs (a pin map, a DUT profile)."""

    # -- recording ---------------------------------------------------------------------------------------------------

    def kind(self, spec: StepSpec) -> str:
        kind = effective_kind(spec, self.backend)
        assert kind is not None, f"{spec.id} is not rehearsed on {self.backend}"
        return kind

    def args(self, spec: StepSpec, **extra: Any) -> StepArgs:
        """The evidence options of ``spec``: the human's words for a human or confirm step, observation values for
        the keys of a step verified its own way, plus ``extra``."""
        kind = self.kind(spec)
        values: dict[str, Any] = {}
        if spec.who == "human" or kind == "confirm":
            values.update(HUMAN)
        if kind == spec.verify:
            values["observe"] = tuple(f"{key}=rehearsed: {key.replace('_', ' ')}" for key in spec.keys)
        values.update(extra)
        return StepArgs(**values)

    def done(self, step_id: str, **extra: Any) -> StepDone:
        spec = STEPS.get(step_id)
        assert spec is not None
        result = bringup_steps.done(self.service, step_id, self.args(spec, **extra), doctor=lambda: DOCTOR)
        assert result.recorded and result.entry is not None, f"{step_id} not recorded: {result.message}"
        assert result.entry.verdict == "pass", f"{step_id} failed: {result.entry.reason}"
        self.recorded.append(result)
        return result

    # -- the walk ----------------------------------------------------------------------------------------------------

    def walk(self, *, until: str | None = None, limit: int = 400) -> list[str]:
        """Do and record every step ``next`` names (up to, not including, ``until``), the review steps it lists as
        awaiting first (the human reviews a finished stage before going on); the step ids in order."""
        walked: list[str] = []
        for _ in range(limit):
            shown = bringup_steps.next_step(self.service)
            assert shown.ok, shown.message
            for review in shown.awaiting_review:
                self.step(review)
                walked.append(review)
            view = shown.step
            if view is None or view.id == until:
                return walked
            self.step(view.id)
            walked.append(view.id)
        raise AssertionError(f"the walk did not end within {limit} steps: {walked[-5:]}")

    def step(self, step_id: str) -> StepDone:
        """Do step ``step_id`` its kind's way and record it."""
        spec = STEPS.get(step_id)
        assert spec is not None
        handler = getattr(self, f"do_{self.kind(spec)}", None)
        assert handler is not None, f"no rehearsal handler for verify {self.kind(spec)} ({step_id})"
        return handler(spec)

    def do_confirm(self, spec: StepSpec) -> StepDone:
        return self.done(spec.id)

    do_observation = do_doctor = do_ledger = do_confirm

    def do_station(self, spec: StepSpec) -> StepDone:
        if spec.id == "E1":
            assert self.service.safe_shutdown("end of session").ok
        return self.done(spec.id)

    def do_probe(self, spec: StepSpec) -> StepDone:
        self.land("lab_station")  # the probe reads the station as wired: the lab inventory
        report = B1500Admin(self.service).probe(wgfmu_session=spec.id in WGFMU_SESSION_PROBES)
        assert report.ok, f"{spec.id}: {report.message}"
        return self.done(spec.id, probe="latest")

    def do_proposal(self, spec: StepSpec) -> StepDone:
        drafts: list[str] = []
        if "station" in spec.config:
            self.land("lab_station")
            proposal = bringup.propose_station(self.service)
            assert proposal.ok and proposal.path is not None, proposal.message
            drafts.append(proposal.path)
        for item in PROPOSALS.get(spec.id, ()):
            folder, name = item.split("/")
            target = self.root / "work" / "bringup" / f"{name}.yaml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((self.root / "config" / folder / f"{name}.example.yaml").read_text(encoding="utf-8"),
                              encoding="utf-8")
            drafts.append(target.relative_to(self.root).as_posix())
        return self.done(spec.id, drafts=tuple(drafts))

    def do_run(self, spec: StepSpec) -> StepDone:
        runs = self.run_step(spec)
        self.runs[spec.id] = runs
        return self.done(spec.id, runs=tuple(runs))

    # -- runs --------------------------------------------------------------------------------------------------------

    def stage_runs(self, stage: str, recipe_id: str | None = None) -> list[str]:
        """Runs of ``stage`` (of ``recipe_id``) that completed, in order."""
        return [r for step, ids in self.runs.items() if step.startswith(f"{stage}.") for r in ids
                if self.facts[r][1] in ("completed", "completed_with_flags")
                and (recipe_id is None or self.facts[r][0] == recipe_id)]

    def run_step(self, spec: StepSpec) -> list[str]:
        """Run the required recipes of a run step (module docstring); returns the run ids it records."""
        ids: list[str] = []
        for recipe_id in spec.required_recipes:
            override = OVERRIDES.get((spec.id, recipe_id), Override())
            case = case_of(recipe_id).case
            for change in ({}, *override.extra):
                for _ in range(override.repeat):
                    ids += self.run_recipe(spec, case, override, change)
        return ids

    def run_recipe(self, spec: StepSpec, case: dict[str, Any], override: Override,
                   change: dict[str, Any]) -> list[str]:
        """One plan of ``case`` (with the override): land, local files, corrections when R-CORR-01 asks for them,
        validate, run (consented when needed), follow; the run ids it adds to the step."""
        request = {**case["request"], **override.request}
        request["params"] = {**request.get("params", {}), **override.params, **change}
        self.land(override.scenario or case["scenario"], override.variant)
        for rel, data in case.get("config", {}).items():
            self.write_config(rel, data)
        ids: list[str] = []
        validation = self.service.validate_plan(recipe_id=case["recipe_id"], **request)
        if validation.tier == "blocked" and "R-CORR-01" in validation.message:
            ids += self.correct(spec, request["pin_map"], case.get("corrections"))
            validation = self.service.validate_plan(recipe_id=case["recipe_id"], **request)
        assert validation.plan_id is not None and validation.tier in ("ok", "needs_confirmation"), \
            f"{spec.id} {case['recipe_id']}: {validation.tier} {validation.message}"
        if override.abort_at is not None:
            with abort_at_checkpoint(self.state_dir, override.abort_at):
                result = self.execute(validation)
        else:
            result = self.execute(validation)
        outcomes = spec.outcomes or ["completed", "completed_with_flags"]
        assert result.run_id is not None and result.outcome in outcomes, \
            f"{spec.id} {case['recipe_id']}: {result.outcome} {result.message}"
        self.facts[result.run_id] = (case["recipe_id"], str(result.outcome))
        return [*ids, result.run_id]

    def execute(self, validation: Any) -> RunSummary:
        service = self.service
        result = (service.run_plan(validation.plan_id) if validation.tier == "ok"
                  else service.run_confirmed_plan(validation.plan_id, summary=validation.summary))
        if result.outcome == "running":
            final = service.follow_run(result.run_id or "", poll_s=0.02)
            assert final is not None, result.message
            result = final
        return result

    def correct(self, spec: StepSpec, pin_map: str, params: dict[str, Any] | None) -> list[str]:
        """The phase compensation, open and short corrections on the landing (the human lifts the probes, then lands
        on a short: L6.P2); their ids count for a step that lists the correction recipes."""
        ids = []
        for recipe_id in CORRECTIONS:
            extra = {} if recipe_id == "cmu.phase_compensation" else (params or {})
            validation = self.service.validate_plan(recipe_id=recipe_id, params=extra, pin_map=pin_map)
            assert validation.plan_id is not None and validation.tier in ("ok", "needs_confirmation"), \
                validation.message
            result = self.execute(validation)
            assert result.ok and result.run_id is not None, result.message
            self.facts[result.run_id] = (recipe_id, str(result.outcome))
            if recipe_id in spec.recipes:
                ids.append(result.run_id)
        return ids

    def capture_sources(self, spec: StepSpec, *, fresh: bool = True) -> list[str]:
        """What a capture step captures: one run per required recipe of the stage (with ``fresh``, a new one where the
        stage file asks for it), or the newest probe record."""
        if not spec.recipes:
            return ["probe"]
        if fresh and spec.id in CAPTURE_RUNS:
            runs = self.run_step(spec)
            self.runs[spec.id] = runs
            return runs
        return [self.stage_runs(spec.group, recipe_id)[0] for recipe_id in spec.required_recipes]


class SimRehearsal(Rehearsal):
    """The walk on the simulator: the world's ``settings.sim.scenario`` is the landing; records and captures are
    refused by design (``rehearsal: refusal``), the walker asserts that before it records the step."""

    backend: Backend = "sim"

    def __init__(self, world: World) -> None:
        super().__init__(world.root, world.state_dir)
        self.world = world
        self._service = world.service()
        self.refusals: list[str] = []

    @property
    def service(self) -> B1500Service:
        return self._service

    def new_process(self) -> None:
        """A new process (the agent restarted): a new service on the same world."""
        self._service = self.world.service()

    def write_config(self, rel: str, data: Any) -> None:
        self.world.write_config(rel, data)

    def land(self, scenario: str, variant: Variant | None = None) -> None:
        name, data = scenario_data(scenario, variant)
        if variant is not None:
            if data.get("faults") in FAULT_PROFILES:
                self.world.write_config(f"sim/faults/{data['faults']}.yaml", FAULT_PROFILES[data["faults"]])
            self.world.write_config(f"sim/scenarios/{name}.yaml", data)
        if name != self.landed:
            self.world.use_scenario(name)
            self.landed = name

    def do_refusal(self, spec: StepSpec) -> StepDone:
        """A record or capture step: on hardware it drafts records or captures fixtures; the simulator refuses both
        for the stage's ``S...`` runs, so the step is recorded as rehearsed (never written by hand)."""
        if spec.verify == "record":
            refused = bringup.record(self.service, spec.group, self.stage_runs(spec.group), operator=OWNER)
            named: list[str] = []
        else:
            named = [s for s in self.capture_sources(spec, fresh=False) if s != "probe"]
            refused = bringup.capture(self.service, named or ["probe"])
        assert refused.status == "refused" and not refused.ok, f"{spec.id}: {refused.message}"
        self.refusals.append(f"{spec.id}: {refused.message}")
        return self.done(spec.id, runs=tuple(named))
