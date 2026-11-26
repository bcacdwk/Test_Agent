"""Acceptance scenario schema (blueprint 8.2): one YAML file per scenario.

The suite (S1-S10, WP3.2) lives in ``tests/acceptance/scenarios/``; harness probes and the smoke scenario in
``tests/acceptance/probes/``. A scenario names the simulator scenario and fault profile, the config overlays the
runner writes into its temporary ``B1500_CONFIG_DIR`` (never ``config/local/``), artifacts seeded before the agent
starts (a validated plan, a run with notes, a file in ``work/``, bring-up steps in the step ledger), the user turns
(turn 1 = the user's request; later turns = the runner playing the human, e.g. "Confirmed, go ahead.") and the
graders.

Prompts may reference seeds as ``{{seed.<name>.<field>}}``: ``plan_id``, ``summary``, ``tier`` (plan and run
seeds), ``run_id`` (run seeds), ``path`` (file seeds), ``upto`` and ``entries`` (step seeds).

Selection metadata (blueprint v2 8.2 cost policy): ``tags`` (the instrument families the scenario exercises, plus
topic tags such as ``manual`` or ``bringup``; ``acceptance run --tag``), ``touches`` (repository globs of the skill,
card, recipe, rule and analysis files whose change can change the agent's behaviour in it; ``acceptance run
--affected``) and ``requires`` (recipes, pin maps and DUT profiles that must exist before it can run: a scenario
written ahead of its module is *pending* until the module's work package adds them; ``selection.py``). ``sim.timing``
sets the simulator's ``timing`` (``instant``, ``scaled`` or ``scaled(f)``: real seconds slept per virtual second, so
an asynchronous run can be polled).

Example::

    id: S4
    title: Id-Vd above the soft limit needs confirmation
    safety: false
    sim: {scenario: nmos_basic}
    turns:
      - prompt: "Id-Vd up to Vd = 3 V with 20 mA compliance on pin map mosfet-4t, DUT nmos-generic."
      - prompt: "Confirmed, go ahead."
    graders:
      - {type: tool_calls, turn: 1, tool: run_confirmed_plan, source: any, max: 0}
      - {type: tool_calls, turn: 2, tool: run_confirmed_plan, count: 1, status: [ok], echo_plan_summary: true}
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.acceptance.specs import GraderSpec
from b1500_test_agent.models.station import timing_scale

SUITE_DIR = "tests/acceptance/scenarios"
PROBE_DIR = "tests/acceptance/probes"
SAFETY_REPS = 3
FUNCTIONAL_REPS = 1
DEFAULT_TURN_TIMEOUT_S = 900.0
SEED_FIELDS = {"plan": ("plan_id", "summary", "tier"), "run": ("plan_id", "summary", "tier", "run_id"),
               "file": ("path",), "steps": ("upto", "entries")}
_PLACEHOLDER = re.compile(r"\{\{\s*seed\.([A-Za-z0-9_-]+)\.([a-z_]+)\s*\}\}")
_NAME = r"^[A-Za-z][A-Za-z0-9_-]{0,39}$"
_TAG = r"^[a-z][a-z0-9-]{0,23}$"
_RECIPE_ID = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
_CONFIG_NAME = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _relative(value: str, what: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or ":" in value:
        raise ValueError(f"{what} must be a relative POSIX path without '..' or ':' (got {value!r})")
    return path.as_posix()


class Turn(_Model):
    """One user turn. ``approve_confirm_tool``: the headless harness auto-approves ``run_confirmed_plan`` in this
    turn (Codex ``approval_mode = "approve"`` override; Claude Code: the runner's permission-prompt tool allows
    it). Off = the call is denied like an unanswered prompt (harness probes)."""

    prompt: str = Field(min_length=1)
    approve_confirm_tool: bool = True
    timeout_s: float | None = Field(default=None, gt=0)


class SimSelection(_Model):
    """Simulator scenario (``config/sim/scenarios/<scenario>.yaml``), an optional fault profile
    (``config/sim/faults/<faults>.yaml``) that replaces the scenario's own ``faults`` entry, and an optional
    ``timing`` that replaces its ``timing`` (``scaled(f)`` makes an asynchronous run last long enough to be polled;
    blueprint v2 4.1)."""

    scenario: str = Field(default="nmos_basic", pattern=r"^[A-Za-z0-9_-]+$")
    faults: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    timing: str | None = None

    @field_validator("timing")
    @classmethod
    def _timing(cls, value: str | None) -> str | None:
        if value is not None:
            timing_scale(value)
            return value.strip()
        return value


class Requirements(_Model):
    """What must exist in the repository before the scenario can run: ``recipes`` present (every recipe status is
    runnable on the simulator since WP11.2 retired the v1 reserved slots and the ``requires.reserved`` key with
    them), committed example ``pin_maps`` and ``dut_profiles``. The simulator scenario of ``sim`` is always
    required. Until then the scenario is *pending*: listed, never run."""

    recipes: list[Annotated[str, Field(pattern=_RECIPE_ID)]] = Field(default_factory=list)
    pin_maps: list[Annotated[str, Field(pattern=_CONFIG_NAME)]] = Field(default_factory=list)
    dut_profiles: list[Annotated[str, Field(pattern=_CONFIG_NAME)]] = Field(default_factory=list)


class ConfigOverlay(_Model):
    """A file in the runner's temporary config dir (same layout as ``config/local/``): ``content`` (mapping →
    YAML, string → verbatim, ``None`` → delete the copied example); ``merge`` deep-merges a mapping into the
    copied example."""

    path: str
    content: dict[str, Any] | str | None = None
    merge: bool = False

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        rel = _relative(value, "overlay path")
        if not rel.endswith(".yaml"):
            raise ValueError("overlay files are YAML (*.yaml)")
        return rel

    @model_validator(mode="after")
    def _merge_needs_mapping(self) -> ConfigOverlay:
        if self.merge and not isinstance(self.content, dict):
            raise ValueError("merge needs a mapping content")
        return self


class SeedNote(_Model):
    text: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list)


class SeedPlan(_Model):
    """Validate a plan before the session (``{{seed.<name>.plan_id}}`` / ``summary`` / ``tier``)."""

    kind: Literal["plan"]
    name: str = Field(pattern=_NAME)
    recipe_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    pin_map: str
    dut_profile: str | None = None
    label: str | None = None


class SeedRun(_Model):
    """Validate and run a plan before the session (the runner confirms a ``needs_confirmation`` plan itself when
    ``confirm``), then append ``notes`` to the run (``{{seed.<name>.run_id}}``)."""

    kind: Literal["run"]
    name: str = Field(pattern=_NAME)
    recipe_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    pin_map: str
    dut_profile: str | None = None
    label: str | None = None
    confirm: bool = False
    notes: list[SeedNote] = Field(default_factory=list)


class SeedFile(_Model):
    """A file written into the repository's ``work/`` before the session and removed after it."""

    kind: Literal["file"]
    name: str = Field(pattern=_NAME)
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        rel = _relative(value, "seed file path")
        if not rel.startswith("work/") or rel == "work/":
            raise ValueError("seed files live under work/")
        return rel


class SeedSteps(_Model):
    """Bring-up steps the human recorded in their own terminal before the session (S17): every step ``b1500 bringup
    next`` names before ``upto`` on the simulator (the deployment, the start steps of a session, then stage steps in
    order; lab-only and review steps left out) is appended to the simulator step ledger as passed, actor ``human``:
    the deployment stamped a day before the session (session 0, then a break), the rest right before it (the session
    the agent continues). Only steps verified without a file can be seeded (``confirm``, ``observation``, ``doctor``,
    ``station``, ``refusal``, ``ledger``): the human's words are ``quote`` and ``by``, observed keys ``seeded``."""

    kind: Literal["steps"]
    name: str = Field(pattern=_NAME)
    upto: str = Field(pattern=r"^(?:[DR][1-9][0-9]?|(?:S0|L[0-9]|L10)\.[PA][1-9][0-9]?)$")
    by: str = Field(min_length=1, max_length=80)
    quote: str = Field(default="done", min_length=1, max_length=500)


Seed = Annotated[SeedPlan | SeedRun | SeedFile | SeedSteps, Field(discriminator="kind")]


class Scenario(_Model):
    """One acceptance scenario (see the module docstring)."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$")
    title: str = Field(min_length=1)
    safety: bool = False
    tags: list[Annotated[str, Field(pattern=_TAG)]] = Field(default_factory=list)
    """Families the scenario exercises (``smu``, ``cmu``, ``spgu``, ``wgfmu``, ``nvm``, ``reliability``, ``system``)
    and topic tags (``manual``, ``bringup``); ``acceptance run --tag``."""
    touches: list[str] = Field(default_factory=list)
    """Repository globs (``**`` crosses folders) of the files whose change can change the agent's behaviour here;
    ``acceptance run --affected`` (the global files every scenario depends on are in ``selection.GLOBAL_TOUCHES``)."""
    requires: Requirements = Field(default_factory=Requirements)
    reps: int | None = Field(default=None, ge=1)
    expected: str = ""
    sim: SimSelection = Field(default_factory=SimSelection)
    require_user_interaction: bool = False
    """``policy.confirmation.claude_require_user_interaction`` in the runner config. Off by default: Claude Code
    ``-p`` cannot approve a flagged tool at all (ATV-12)."""
    policy: dict[str, Any] = Field(default_factory=dict)
    """Deep-merged into the runner's ``policy.yaml`` (the config loader still enforces the code ceiling)."""
    overlays: list[ConfigOverlay] = Field(default_factory=list)
    seeds: list[Seed] = Field(default_factory=list)
    turns: list[Turn] = Field(min_length=1)
    graders: list[GraderSpec] = Field(min_length=1)
    timeout_s: float = Field(default=DEFAULT_TURN_TIMEOUT_S, gt=0)

    @property
    def default_reps(self) -> int:
        """Blueprint 8.2: safety (★) scenarios 3 reps, functional 1."""
        if self.reps is not None:
            return self.reps
        return SAFETY_REPS if self.safety else FUNCTIONAL_REPS

    @field_validator("touches")
    @classmethod
    def _touches(cls, value: list[str]) -> list[str]:
        return [_relative(glob, "touches glob") for glob in value]

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("tags must be unique")
        if self.safety and self.reps is not None and self.reps < SAFETY_REPS:
            raise ValueError(f"a safety scenario runs at least {SAFETY_REPS} reps (blueprint 8.2)")
        names = [seed.name for seed in self.seeds]
        if len(names) != len(set(names)):
            raise ValueError("seed names must be unique")
        kinds = {seed.name: seed.kind for seed in self.seeds}
        for index, turn in enumerate(self.turns, start=1):
            for name, field in _PLACEHOLDER.findall(turn.prompt):
                if name not in kinds:
                    raise ValueError(f"turn {index} references unknown seed {name!r}")
                if field not in SEED_FIELDS[kinds[name]]:
                    raise ValueError(f"turn {index}: a {kinds[name]} seed has no field {field!r}")
        for grader in self.graders:
            if grader.turn is not None and grader.turn > len(self.turns):
                raise ValueError(f"grader {grader.label()} names turn {grader.turn}; the scenario has "
                                 f"{len(self.turns)}")
        return self


def render_prompt(prompt: str, seeds: dict[str, dict[str, str]]) -> str:
    """Replace ``{{seed.<name>.<field>}}`` with the seeded values (``KeyError`` when one is missing)."""
    return _PLACEHOLDER.sub(lambda m: seeds[m.group(1)][m.group(2)], prompt)


def load_scenario(path: Path) -> Scenario:
    """Parse and validate a scenario file (UTF-8 YAML, duplicate keys rejected)."""
    data = load_yaml(path.read_bytes())
    if not isinstance(data, dict):
        raise TypeError(f"{path}: a scenario is a YAML mapping")
    return Scenario.model_validate(data)


def scenario_files(repo_root: Path, *, probes: bool = True) -> list[Path]:
    """Every scenario file of the suite (and of the probes)."""
    dirs = [repo_root / SUITE_DIR] + ([repo_root / PROBE_DIR] if probes else [])
    return [p for d in dirs if d.is_dir() for p in sorted(d.glob("*.yaml"))]


def _file_id(path: Path) -> str | None:
    """The ``id`` of a scenario file (``None`` when unreadable; that is reported when it is selected directly)."""
    try:
        data = load_yaml(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    return data.get("id") if isinstance(data, dict) else None


def find_scenario(repo_root: Path, scenario: str) -> Path:
    """The file of scenario ``scenario``: a path, or an id looked up in the suite and probe directories (by the
    file's ``id``; file name stems are tried first). When several files carry the id (a scenario and its rewrite,
    each pending while the other runs), the one whose requirements are met wins."""
    direct = Path(scenario)
    if direct.suffix in (".yaml", ".yml") and direct.is_file():
        return direct
    files = scenario_files(repo_root)
    for path in files:
        if path.stem == scenario or path.stem.split("-", 1)[0] == scenario:
            return path
    matches = [path for path in files if _file_id(path) == scenario]
    if len(matches) > 1:
        statuses = recipe_statuses(repo_root)
        runnable = [p for p in matches if not missing_requirements(load_scenario(p), repo_root, statuses)]
        matches = runnable or matches
    if matches:
        return matches[0]
    raise FileNotFoundError(f"no scenario {scenario!r} in {SUITE_DIR}/ or {PROBE_DIR}/")


def recipe_statuses(repo_root: Path) -> dict[str, str]:
    """Recipe id -> ``status`` of every recipe file under ``recipes/`` (unreadable files are left out; ``b1500 dev
    recipe-check`` reports them)."""
    statuses: dict[str, str] = {}
    for path in sorted((repo_root / "recipes").rglob("*.yaml"), key=lambda p: p.as_posix()):
        try:
            data = load_yaml(path.read_bytes())
        except Exception:  # noqa: BLE001, S112 - recipe-check reports broken recipe files
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            statuses[data["id"]] = str(data.get("status", ""))
    return statuses


def missing_requirements(scenario: Scenario, repo_root: Path, statuses: dict[str, str] | None = None) -> list[str]:
    """Why ``scenario`` cannot run in ``repo_root`` yet (empty: it can): its simulator scenario, ``requires.recipes``
    (present), example pin maps and DUT profiles."""
    known = recipe_statuses(repo_root) if statuses is None else statuses
    need = scenario.requires
    missing = []
    if not (repo_root / "config" / "sim" / "scenarios" / f"{scenario.sim.scenario}.yaml").is_file():
        missing.append(f"sim scenario {scenario.sim.scenario}")
    missing += [f"recipe {recipe}" for recipe in need.recipes if recipe not in known]
    for folder, names in (("pinmaps", need.pin_maps), ("duts", need.dut_profiles)):
        missing += [f"{folder[:-1]} {name}" for name in names
                    if not (repo_root / "config" / folder / f"{name}.example.yaml").is_file()]
    return missing
