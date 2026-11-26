"""Bring-up stages, hardware validation records and the ``b1500 bringup status | capture | record`` results
(blueprint v2 6.1, 7.1, 7.2, 7.4).

**Stages.** ``S0`` (physical prerequisites), ``L0`` … ``L10`` in this order (``STAGES``: the stage file stem under
``.agents/skills/b1500-bringup/stages/`` and the goal). Hardware tests, records and test cards share the ids. A stage
file starts with ``StageFrontmatter``: the recipes the stage runs and its ``checks`` (``StageCheck``: quantity,
method, reference and tolerance). The checks are the machine-readable part of the file's "Expected values" table;
``b1500 bringup record`` copies them into the draft record, ``b1500 dev lint-skills`` keeps both in step.

**Validation records.** ``b1500 bringup record STAGE --run H…`` drafts a ``ValidationRecord`` into
``work/bringup/records/`` from hardware runs only (run ids ``H…``, backend ``visa``; simulator ``S…`` runs are
refused, rehearsal or not). A human reviewer checks it against the raw runs, fills ``reviewer`` and ``reviewed_on``
and moves it to ``validation/hw/<recipe_id>.yaml`` (a recipe record: promotion evidence of that recipe) or
``validation/hw/stage-<stage>.yaml`` (a stage record: S0 checklist, L0 probe, L1 zero check, L10 handoff), then
commits it. ``b1500 dev recipe-check`` enforces the promotion rule (7.2): status ``hw_validated`` ⇔ a reviewed,
passing recipe record with ``H…`` runs whose ``recipe_sha256`` equals ``recipe_definition_sha256`` of the current
recipe.

**Definition digest.** ``recipe_definition_sha256`` hashes what a recipe measures: the parsed recipe without
``status``, ``provenance`` and ``card`` (the fields a promotion edits) and without the file digest. Comments and
formatting do not count; any change to roles, parameters, quality, analyses, kind or version does, so a promotion
stays valid exactly as long as the validated measurement is unchanged. Each run of a record also keeps the raw file
digest of its manifest (``RecordRun.recipe_file_sha256``).

**Steps and the step ledger** (v2.1 plan §4.1). ``.agents/skills/b1500-bringup/steps.yaml`` (``StepsFile``) lists
every step in execution order: the deployment group ``D1``… (session 0), the session start ``R1``… and end ``E1``…
groups (every session) and per stage its numbered items (``L1.P1`` = physical step 1, ``L1.A4`` = agent step 4 of the
stage file) plus one review step ``<stage>.R``. ``StepSpec.verify`` names how ``b1500 bringup done`` verifies a step
on hardware; ``rehearsal`` how the simulator ledger takes it. The ledger ``<data>/state/bringup/ledger-<backend>.jsonl``
holds one ``LedgerEntry`` per ``done`` call, written only by the CLI and hash-chained (``prev_sha256`` = the previous
entry's ``sha256``, which covers the entry itself), so a hand edit shows in ``b1500 bringup check``. Records of
schema version 2 embed the stage's ledger entries (``ValidationRecord.steps``): the reviewer signs the step list and
it travels with the records.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Annotated, Final, Literal, get_args

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from b1500_test_agent.models.analysis import ExtractionResult, Identifier, QualityReport, RunId
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.common import Backend, ResultEnvelope, Sha256Hex, StrictModel
from b1500_test_agent.models.recipe import Recipe, RecipeId
from b1500_test_agent.models.run import RunManifest, RunOutcome

StageId = Literal["S0", "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10"]
"""Bring-up stage ids (blueprint v2 7.4); hardware tests, records and cards share them."""

STAGE_ORDER: Final[tuple[str, ...]] = get_args(StageId)

STAGES: Final[dict[str, tuple[str, str]]] = {
    "S0": ("s0-physical", "prerequisites: EasyEXPERT exited, GPIB 17, shield box, DUT set at hand"),
    "L0": ("l0-probe-config", "bus, identity, inventory, errors, WGFMU library; configuration adopted"),
    "L1": ("l1-smu-zero", "outputs safe at 0 V; cleanup verified; mid-run safe_shutdown once"),
    "L2": ("l2-resistors", "DC accuracy on known resistors; Kelvin"),
    "L3": ("l3-diode", "voltage and current forcing, compliance"),
    "L4": ("l4-mosfet", "MOSFET DC set against EasyEXPERT"),
    "L5": ("l5-smu-advanced", "pulsed, sampling, search, QSCV leakage"),
    "L6": ("l6-cmu", "phase compensation, open/short, known capacitor, MOS-C"),
    "L7": ("l7-spgu-selector", "selector map, pulses into 1 MOhm, FeFET program/read"),
    "L8": ("l8-wgfmu", "library session, self-test/cal, DC via RSU, fast vs DC, lwp waveform"),
    "L9": ("l9-long-runs", "async run, cancel, recovery; auto-calibration restored"),
    "L10": ("l10-harness-handoff", "acceptance prompts on hardware; records reviewed and transferred"),
}
"""Stage id -> (stage file stem under ``b1500-bringup/stages/``, goal); blueprint v2 6.1 and 7.4 (order of
``StageId``)."""

BRINGUP_SKILL: Final = "b1500-bringup"
STAGE_FILES_DIR: Final[tuple[str, ...]] = (".agents", "skills", BRINGUP_SKILL, "stages")
"""Repository-relative folder of the stage files (the canonical skill source, not the generated mirror)."""
VALIDATION_DIR: Final[tuple[str, ...]] = ("validation", "hw")
"""Repository-relative folder of the reviewed hardware records (committed by the human)."""
BRINGUP_WORK_DIR: Final = "bringup"
"""Folder under ``work/`` of the bring-up helpers: ``probe-<UTC>.json``, proposals, ``records/``, ``fixtures/``."""
DRAFTS_DIR: Final = "records"
FIXTURES_DIR: Final = "fixtures"
STAGE_RECORD_PREFIX: Final = "stage-"
"""Reviewed stage records are ``validation/hw/stage-<stage id in lower case>.yaml`` (a recipe id has a dot, so the
two name spaces never collide)."""
STEPS_FILE: Final[tuple[str, ...]] = (".agents", "skills", BRINGUP_SKILL, "steps.yaml")
"""Repository-relative path of the step sequence (``StepsFile``; the canonical skill source)."""
LEDGER_DIR: Final = "bringup"
"""Folder under ``<data>/state/`` of the step ledgers ``ledger-<backend>.jsonl`` (written only by the CLI)."""
RECORD_SCHEMA_VERSION: Final = 2
"""Schema version of the records ``b1500 bringup record`` drafts (2: with the stage's ledger steps; v2 records
without the key are version 1 and still load)."""
GENESIS_SHA256: Final = "0" * 64
"""``prev_sha256`` of the first ledger entry."""
DEFERRAL_ITEMS: Final = range(1, 15)
"""The numbered hardware deferrals of blueprint v2 7.6 (items 1-14) that ``StepSpec.items`` may name."""

DEFINITION_EXCLUDED: Final[frozenset[str]] = frozenset({"status", "provenance", "card", "sha256"})
"""Recipe fields left out of ``recipe_definition_sha256`` (the fields a promotion edits, and the file digest)."""

QuantityName = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]
"""A recorded quantity: an extraction quantity (``resistance``, ``vth``), ``noise_<column>`` (quality noise of a
measured column), a ``kind_result`` key (``result``), ``cleanup`` (every run verified with ``LOP?``) or a probe line
(``identity``, ``inventory`` …)."""

NonEmptyStr = Annotated[str, Field(min_length=1)]


def stage_file_name(stage: str) -> str:
    """``L4`` -> ``l4-mosfet.md``."""
    return f"{STAGES[stage][0]}.md"


def stage_index(stage: str) -> int:
    """Position of ``stage`` in ``STAGE_ORDER`` (``S0`` = 0)."""
    return STAGE_ORDER.index(stage)


# == Stage files ======================================================================================================


class Tolerance(StrictModel):
    """How a value passes, exactly one of: ``rel`` (|value − reference| ≤ rel·|reference|), ``absolute``
    (|value − reference| ≤ absolute, in the check's unit), ``factor`` (reference/factor ≤ value ≤ reference·factor,
    same sign) or ``max_abs`` (|value| ≤ max_abs; needs no reference)."""

    rel: float | None = Field(default=None, gt=0)
    absolute: float | None = Field(default=None, gt=0)
    factor: float | None = Field(default=None, gt=1)
    max_abs: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _exactly_one(self) -> Tolerance:
        if sum(v is not None for v in (self.rel, self.absolute, self.factor, self.max_abs)) != 1:
            raise ValueError("give exactly one of rel, absolute, factor and max_abs")
        return self

    @property
    def needs_reference(self) -> bool:
        return self.max_abs is None

    def check(self, value: float | None, reference: float | None) -> bool | None:
        """``True``/``False`` when it can be decided, ``None`` when the value or a needed reference is missing."""
        if value is None:
            return None
        if self.max_abs is not None:
            return abs(value) <= self.max_abs
        if reference is None:
            return None
        if self.rel is not None:
            return abs(value - reference) <= self.rel * abs(reference)
        if self.absolute is not None:
            return abs(value - reference) <= self.absolute
        assert self.factor is not None
        if reference == 0 or (value > 0) != (reference > 0):
            return False
        return abs(reference) / self.factor <= abs(value) <= abs(reference) * self.factor


class StageCheck(StrictModel):
    """One expected value of a stage (a row of its "Expected values" table). ``recipe`` names the recipe whose
    record holds the check (``None``: the stage record); ``method`` the ``analyze_run`` method that yields
    ``quantity`` (``None``: any, or a run fact); ``reference`` says what the value is compared with; ``tolerance``
    ``None`` = recorded only (the reviewer judges it); ``text`` is the criterion as shown in the stage file."""

    id: Identifier
    recipe: RecipeId | None = None
    quantity: QuantityName
    method: Identifier | None = None
    unit: str = ""
    reference: NonEmptyStr
    tolerance: Tolerance | None = None
    text: NonEmptyStr


class StageFrontmatter(StrictModel):
    """Bring-up stage-file frontmatter (``b1500-bringup/stages/<stem>.md``): the stage id (its file stem is fixed by
    ``STAGES``), a title, the recipes the stage runs (registered ids), its checks and a version."""

    stage: StageId
    title: NonEmptyStr
    recipes: list[RecipeId]
    checks: list[StageCheck] = Field(default_factory=list)
    version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _consistent(self) -> StageFrontmatter:
        if len(set(self.recipes)) != len(self.recipes):
            raise ValueError("recipes lists a recipe twice")
        ids = [c.id for c in self.checks]
        if len(set(ids)) != len(ids):
            raise ValueError("checks: every id must be unique within the stage")
        stray = sorted({c.recipe for c in self.checks if c.recipe is not None} - set(self.recipes))
        if stray:
            raise ValueError(f"checks name recipes the stage does not run: {stray}")
        return self

    def checks_for(self, recipe_id: str | None) -> list[StageCheck]:
        """The checks of one record: those of ``recipe_id`` (``None``: the stage-level checks)."""
        return [c for c in self.checks if c.recipe == recipe_id]

    def record_keys(self) -> list[str | None]:
        """The records that sign the stage off: one per recipe with checks (in ``recipes`` order), plus the stage
        record when the stage has stage-level checks or no checks at all."""
        keys: list[str | None] = [r for r in self.recipes if self.checks_for(r)]
        if self.checks_for(None) or not self.checks:
            keys.append(None)
        return keys


# == Bring-up steps and the step ledger (v2.1 plan §4.1) =============================================================

StepId = Annotated[str, Field(pattern=r"^(?:[DRE][1-9][0-9]?|(?:S0|L[0-9]|L10)\.(?:[PA][1-9][0-9]?|R))$")]
"""``D1`` (deployment), ``R1`` (session start), ``E1`` (session end), ``L1.P1`` / ``L1.A4`` (physical / agent item
of a stage file), ``L1.R`` (the stage's review step)."""
StepWho = Literal["agent", "human", "both"]
VerifyKind = Literal["run", "probe", "config", "proposal", "record", "capture", "observation", "hw_suite", "confirm",
                     "review", "station", "doctor", "ledger"]
"""How ``b1500 bringup done`` verifies a step (machine unless noted): ``run`` archived runs of the step's recipes on
the ledger's backend (outcome, cleanup verified, ``LOP?`` positive control on hardware, files unchanged, quality not
untrusted); ``probe`` the newest probe record without FAIL; ``config`` the adopted files (``config check`` valid,
local, equal to the proposal); ``proposal`` schema-valid files under ``work/bringup/``; ``record`` draft records of
the stage (not failing); ``capture`` fixture files; ``observation`` the required ``--observe`` keys; ``hw_suite`` the
JUnit file of ``pytest -m hardware`` (no failure, nothing skipped by the gate); ``confirm`` the human's own words and
name (human); ``review`` reviewed records of the stage in ``validation/hw/``; ``station`` ``station_status`` state
clean (no fault, lock holder or running run; no instrument I/O); ``doctor`` ``b1500 doctor`` without FAIL;
``ledger`` ``b1500 bringup check`` without a gap."""
RehearsalMode = Literal["run_sim", "refusal", "human_done", "skip"]
"""How the simulator ledger takes a step: ``run_sim`` verified like on hardware (simulator runs ``S…``); ``refusal``
the hardware evidence is refused on the simulator by design (records, fixtures): recorded as rehearsed;
``human_done`` the human's ``done`` (kind ``confirm``); ``skip`` not rehearsed (lab-only facts)."""
ConfigItemKind = Literal["settings", "station", "policy", "pinmap", "dut"]
StepVerdict = Literal["pass", "fail"]
LedgerActor = Literal["agent", "human_via_agent", "human"]
"""Who ran ``b1500 bringup done``: an agent session (``human_via_agent`` when it recorded the human's words) or the
human in their own terminal."""
EffectiveKind = Literal["run", "probe", "config", "proposal", "record", "capture", "observation", "hw_suite",
                        "confirm", "review", "station", "doctor", "ledger", "refusal"]
RunbookId = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
AtvId = Annotated[str, Field(pattern=r"^ATV-[1-9][0-9]?$")]
GROUPS: Final[dict[str, str]] = {"deployment": "D", "session_start": "R", "session_end": "E"}
"""``StepsFile`` group -> step id prefix."""


def step_group(step_id: str) -> str:
    """``D``, ``R``, ``E`` or the stage id of a step (``L1.A4`` -> ``L1``)."""
    return step_id.split(".", 1)[0] if "." in step_id else step_id[0]


class StepSpec(StrictModel):
    """One step of ``steps.yaml`` (module docstring). ``recipes``: the recipes whose runs the step takes (each needs
    a run unless listed in ``optional``); ``outcomes``: the run outcomes it accepts (default completed, with or
    without flags); ``keys``: ``--observe`` keys it needs; ``config``: the configuration items it adopts or proposes;
    ``must_pass``: doctor lines that must PASS; ``feeds``: stage check ids its evidence feeds; ``on_fail``: debug
    runbooks of a failure; ``reconfirm``: asked again after a break; ``after_record``: the step follows the drafting
    of the stage record (the human's go-on, the transfer), so the record cannot list it; ``items``/``atv``: the
    blueprint v2 7.6 items and ATVs it settles. ``text`` (deployment and session steps only; a stage step's text is its
    stage file item)."""

    id: StepId
    who: StepWho
    verify: VerifyKind
    rehearsal: RehearsalMode
    text: str | None = None
    recipes: list[RecipeId] = Field(default_factory=list)
    optional: list[RecipeId] = Field(default_factory=list)
    outcomes: list[RunOutcome] = Field(default_factory=list)
    keys: list[Identifier] = Field(default_factory=list)
    config: list[ConfigItemKind] = Field(default_factory=list)
    must_pass: list[NonEmptyStr] = Field(default_factory=list)
    feeds: list[Identifier] = Field(default_factory=list)
    on_fail: list[RunbookId] = Field(default_factory=list)
    reconfirm: bool = False
    after_record: bool = False
    items: list[int] = Field(default_factory=list)
    atv: list[AtvId] = Field(default_factory=list)

    @property
    def group(self) -> str:
        return step_group(self.id)

    @property
    def after_drafting(self) -> bool:
        """The step happens when or after the stage's records are drafted (verify ``record`` or ``review``, or
        ``after_record``): a stage record cannot list it; its reviewed records stand for it."""
        return self.verify in ("record", "review") or self.after_record

    @property
    def is_review(self) -> bool:
        return self.id.endswith(".R")

    @property
    def required_recipes(self) -> list[str]:
        return [r for r in self.recipes if r not in self.optional]

    @model_validator(mode="after")
    def _consistent(self) -> StepSpec:
        stage_step = "." in self.id
        problems = []
        if stage_step == (self.text is not None):
            problems.append("a deployment or session step gives text; a stage step takes its text from the stage file"
                            if stage_step else "a deployment or session step needs text")
        if not stage_step and (self.reconfirm or self.feeds or self.after_record):
            problems.append("reconfirm, feeds and after_record belong to stage steps")
        kind = self.id.split(".")[-1][:1] if stage_step else ""
        if kind == "P" and self.who != "human":
            problems.append("a physical item (P) is the human's")
        if kind == "A" and self.who == "human":
            problems.append("an agent item (A) is the agent's (who: agent or both)")
        if kind == "R" and (self.who != "human" or self.verify != "review"):
            problems.append("the review step <stage>.R is the human's, verify review")
        if self.verify == "run" and not self.recipes:
            problems.append("verify run needs recipes")
        if set(self.optional) - set(self.recipes) or len(set(self.recipes)) != len(self.recipes):
            problems.append("optional must be a subset of recipes; recipes are listed once")
        if self.outcomes and self.verify not in ("run", "capture"):
            problems.append("outcomes belong to verify run or capture")
        if self.verify == "observation" and not self.keys:
            problems.append("verify observation needs keys")
        if (self.verify in ("config", "proposal")) != bool(self.config):
            problems.append("config names the items of verify config or proposal (and only those)")
        if self.must_pass and self.verify != "doctor":
            problems.append("must_pass belongs to verify doctor")
        if any(item not in DEFERRAL_ITEMS for item in self.items):
            problems.append(f"items are blueprint v2 7.6 items {DEFERRAL_ITEMS.start}-{DEFERRAL_ITEMS.stop - 1}")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class StepsFile(StrictModel):
    """``steps.yaml``: the whole bring-up in execution order (module docstring). ``stages`` lists, per stage with a
    stage file and in stage order, every numbered item of the file once plus the review step ``<stage>.R``."""

    version: Annotated[int, Field(ge=1)]
    deployment: list[StepSpec]
    session_start: list[StepSpec]
    session_end: list[StepSpec]
    stages: dict[StageId, list[StepSpec]]

    @model_validator(mode="after")
    def _consistent(self) -> StepsFile:
        problems = []
        for group, prefix in GROUPS.items():
            stray = [s.id for s in getattr(self, group) if step_group(s.id) != prefix]
            if stray:
                problems.append(f"{group} holds {prefix}<n> steps only, not {stray}")
        for stage, steps in self.stages.items():
            stray = [s.id for s in steps if step_group(s.id) != stage]
            if stray:
                problems.append(f"stage {stage} holds {stage}.<item> steps only, not {stray}")
            if [s.id for s in steps].count(f"{stage}.R") != 1:
                problems.append(f"stage {stage} has exactly one review step {stage}.R")
        if list(self.stages) != [s for s in STAGE_ORDER if s in self.stages]:
            problems.append(f"stages are listed in stage order ({', '.join(STAGE_ORDER)})")
        ids = [s.id for s in self.all()]
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            problems.append(f"step ids listed twice: {twice}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def all(self) -> list[StepSpec]:
        """Every step: deployment, the stages in order, session start, session end."""
        return [*self.deployment, *(s for steps in self.stages.values() for s in steps), *self.session_start,
                *self.session_end]

    def get(self, step_id: str) -> StepSpec | None:
        return next((s for s in self.all() if s.id == step_id), None)


class EvidenceItem(StrictModel):
    """One piece of evidence: what it is (run id, repository-relative path, config item) and its sha256 then."""

    ref: NonEmptyStr
    sha256: Sha256Hex | None = None


class HumanWords(StrictModel):
    """The human's own words in chat, quoted, and their name (``--human "QUOTE" --by NAME``)."""

    quote: NonEmptyStr
    by: NonEmptyStr


class StepEvidence(StrictModel):
    """What one ``done`` call verified: runs (manifest digest), the probe record, files under ``work/`` (proposals,
    draft records, a JUnit report: ``drafts``), the fixture folder, adopted configuration files, observations,
    reference values of stage checks, the human's words and the machine facts read (doctor lines, station state)."""

    runs: list[EvidenceItem] = Field(default_factory=list)
    probe: EvidenceItem | None = None
    drafts: list[EvidenceItem] = Field(default_factory=list)
    fixtures: EvidenceItem | None = None
    config: list[EvidenceItem] = Field(default_factory=list)
    observe: dict[Identifier, NonEmptyStr] = Field(default_factory=dict)
    references: dict[Identifier, float] = Field(default_factory=dict)
    human: HumanWords | None = None
    facts: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        """One line for records and ``check`` output."""
        parts = [f"runs {', '.join(r.ref for r in self.runs)}" if self.runs else "",
                 f"probe {self.probe.ref}" if self.probe else "",
                 f"files {', '.join(d.ref for d in self.drafts)}" if self.drafts else "",
                 f"fixtures {self.fixtures.ref}" if self.fixtures else "",
                 f"config {', '.join(c.ref for c in self.config)}" if self.config else "",
                 ", ".join(f"{k}={v}" for k, v in self.observe.items()),
                 ", ".join(f"{k}={v:g}" for k, v in self.references.items()),
                 f'"{self.human.quote}" ({self.human.by})' if self.human else "", *self.facts]
        return "; ".join(p for p in parts if p)


class LedgerEntry(StrictModel):
    """One line of the step ledger (module docstring): the step, when, on which backend and station profile
    (``station`` = sha256 of the station file), who, how it was verified (``verify``: the effective kind, ``refusal``
    for a rehearsed record or capture), the evidence, the verdict with its reason and the hash chain."""

    seq: Annotated[int, Field(ge=1)]
    step: StepId
    ts: AwareDatetime
    backend: Backend
    station: Sha256Hex | None = None
    actor: LedgerActor
    verify: EffectiveKind
    evidence: StepEvidence = Field(default_factory=StepEvidence)
    verdict: StepVerdict
    reason: str = ""
    prev_sha256: Sha256Hex
    sha256: Sha256Hex


def ledger_entry_sha256(data: dict[str, JsonValue]) -> str:
    """The ``sha256`` of a ledger entry: canonical JSON of the entry (``model_dump(mode="json")``) without the
    ``sha256`` key itself."""
    body = {k: v for k, v in data.items() if k != "sha256"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RecordStep(StrictModel):
    """A ledger entry as a record embeds it (schema version 2): step, how it was verified, verdict, time, actor, the
    evidence in one line and the entry's ``sha256`` (it names the ledger line)."""

    step: StepId
    verify: EffectiveKind
    verdict: StepVerdict
    ts: AwareDatetime
    actor: LedgerActor
    evidence: str = ""
    entry_sha256: Sha256Hex


# == Validation records ===============================================================================================


class RecordStation(StrictModel):
    """The station the runs came from: ``config/local/station.yaml`` name and the ``*IDN?`` of the runs."""

    name: str = ""
    idn: str = ""
    firmware: str = ""


class RecordDut(StrictModel):
    """The DUT: profile name, instance (die, lot, standard label) and the reference used (meter, certificate,
    EasyEXPERT file)."""

    profile: str = ""
    instance: str = ""
    reference: str = ""


class RecordRun(StrictModel):
    """Facts of one hardware run copied from its manifest (``recipe_file_sha256`` = the manifest's raw recipe file
    digest at run time)."""

    run_id: RunId
    recipe_id: RecipeId
    recipe_file_sha256: Sha256Hex
    plan_hash: Sha256Hex
    pin_map: str
    dut_profile: str | None = None
    started_at: AwareDatetime
    outcome: str
    cleanup: str
    quality_verdict: str | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)


class RecordMeasurement(StrictModel):
    """One recorded quantity. ``check`` links it to a stage check (``None``: recorded for completeness); ``value``
    is copied from the run (never edited), ``observed`` holds non-numeric findings (probe lines, run facts,
    ``not measured``); ``reference`` and ``passed`` are filled when a reference was given (or the tolerance needs
    none)."""

    check: Identifier | None = None
    quantity: QuantityName
    value: float | None = None
    unit: str = ""
    observed: str = ""
    run_id: RunId | None = None
    method: str = ""
    reference: float | None = None
    reference_source: str = ""
    tolerance: str = ""
    passed: bool | None = None


class ValidationRecord(StrictModel):
    """A hardware validation record (see the module docstring). Drafts have ``reviewer: ""``; only a human fills
    ``reviewer``/``reviewed_on``. ``recipe_id`` ``None`` = a stage record. ``schema_version`` 2 (drafts since v2.1)
    adds ``steps``: the ledger entries of the record's stage when it was drafted; version 1 (v2 records, no key) has
    none."""

    schema_version: Literal[1, 2] = 1
    stage: StageId
    recipe_id: RecipeId | None = None
    recipe_version: Annotated[int, Field(ge=1)] | None = None
    recipe_sha256: Sha256Hex | None = None
    backend: Literal["visa"] = "visa"
    station: RecordStation = Field(default_factory=RecordStation)
    dut: RecordDut = Field(default_factory=RecordDut)
    runs: list[RunId] = Field(default_factory=list)
    evidence: list[RecordRun] = Field(default_factory=list)
    probe: str | None = None
    measurements: list[RecordMeasurement] = Field(default_factory=list)
    result: Literal["", "pass", "fail"] = ""
    operator: str = ""
    date: str = ""
    reviewer: str = ""
    reviewed_on: dt.date | None = None
    notes: list[str] = Field(default_factory=list)
    steps: list[RecordStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> ValidationRecord:
        if self.schema_version == 1 and self.steps:
            raise ValueError("steps belong to schema_version 2 records")
        foreign = sorted({s.step for s in self.steps if step_group(s.step) != self.stage})
        if foreign:
            raise ValueError(f"steps of a stage {self.stage} record are {self.stage}.<item> steps, not {foreign}")
        if len({s.step for s in self.steps}) != len(self.steps):
            raise ValueError("steps lists each step once (its latest ledger entry)")
        simulated = [r for r in self.runs if not r.startswith("H")]
        if simulated:
            raise ValueError(f"runs must be hardware runs (H...); simulator runs are never recorded: {simulated}")
        if (self.recipe_id is None) != (self.recipe_sha256 is None) or \
                (self.recipe_id is None) != (self.recipe_version is None):
            raise ValueError("a recipe record gives recipe_id, recipe_version and recipe_sha256; a stage record none")
        if self.evidence and sorted(e.run_id for e in self.evidence) != sorted(self.runs):
            raise ValueError("evidence must describe exactly the runs listed in runs")
        if self.recipe_id is not None and any(e.recipe_id != self.recipe_id for e in self.evidence):
            raise ValueError("every run of a recipe record must be a run of that recipe")
        if self.reviewer.strip() and self.reviewed_on is None:
            raise ValueError("a reviewed record gives reviewed_on (the date of the review)")
        return self

    @property
    def reviewed(self) -> bool:
        return bool(self.reviewer.strip())

    @property
    def key(self) -> str:
        """``<recipe_id>`` or ``stage-<stage>`` (the reviewed record's file stem)."""
        return self.recipe_id if self.recipe_id is not None else f"{STAGE_RECORD_PREFIX}{self.stage.lower()}"

    def file_name(self) -> str:
        """The file name of the reviewed record under ``validation/hw/``."""
        return f"{self.key}.yaml"


RECORD_KEYS: Final[tuple[str, ...]] = tuple(ValidationRecord.model_fields)
"""Top-level keys of a record (and of ``b1500-bringup/records/_TEMPLATE.yaml``), in order."""


def recipe_definition_sha256(recipe: Recipe) -> str:
    """sha256 of the recipe's measurement definition (module docstring): canonical JSON of the parsed recipe
    without ``DEFINITION_EXCLUDED``."""
    data = recipe.model_dump(mode="json", exclude=set(DEFINITION_EXCLUDED))
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reviewed_record_problems(record: ValidationRecord, file_name: str) -> list[str]:
    """Why ``record`` (a file ``file_name`` under ``validation/hw/``) is not a valid reviewed record: wrong name,
    not reviewed, not passing, or a recipe record without runs."""
    problems = []
    if file_name != record.file_name():
        problems.append(f"a {'recipe' if record.recipe_id else 'stage'} record of {record.key} is named "
                        f"{record.file_name()}, not {file_name}")
    if not record.reviewed:
        problems.append("reviewer is empty: validation/hw/ holds reviewed records only (drafts stay in "
                        "work/bringup/records/)")
    if record.result != "pass":
        problems.append(f"result is {record.result or 'empty'}: validation/hw/ holds passing records only")
    if record.recipe_id is not None and not record.runs:
        problems.append("a recipe record lists its hardware runs (H...)")
    return problems


# == Service evidence (input of capture and record) ===================================================================


FixtureKind = Literal["fmt1", "fmt5", "idn", "unt", "errx", "lop", "stb", "tst", "lrn", "ermod", "erssp", "spst",
                      "corrst", "adj"]
"""Kinds of the golden FLEX fixture format (``tests/fixtures/flex/``, documented in ``tests/unit/flex_fixtures.py``)."""


class CapturedExchange(StrictModel):
    """One instrument answer as the driver parsers read it: fixture ``kind``, the ``command`` that produced it, the
    ``response`` body (without its CR/LF terminator; with ``terminator: comma`` the trailing comma stays), the parsed
    ``expect`` (query kinds) or one ``points`` entry per data element (``<status> <channel> <type> <12 digits>``).
    ``problem`` is set (and ``expect``/``points`` empty) when the parser rejected the answer."""

    kind: FixtureKind
    command: str
    response: str
    terminator: Literal["crlf", "comma"] | None = None
    expect: JsonValue = None
    points: list[str] = Field(default_factory=list)
    problem: str | None = None


class RunFacts(StrictModel):
    """Everything a record or a capture reads from one archived run: the manifest, the run folder (display path),
    every analysis result, the quality report, the instrument answers of its audit and the files whose sha256 no
    longer matches the manifest."""

    manifest: RunManifest
    folder: str
    analyses: list[ExtractionResult] = Field(default_factory=list)
    quality: QualityReport | None = None
    exchanges: list[CapturedExchange] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)


class ProbeFacts(StrictModel):
    """A probe record (``work/bringup/probe-<UTC>.json``) with its answers parsed like a run's."""

    path: str
    report: ProbeReport
    exchanges: list[CapturedExchange] = Field(default_factory=list)


class RecipeFacts(StrictModel):
    """The current recipe file: version, raw file digest and definition digest."""

    recipe_id: RecipeId
    version: int
    file_sha256: Sha256Hex
    definition_sha256: Sha256Hex
    status: str


# == Results of b1500 bringup status | capture | record ===============================================================


RecordItemState = Literal["reviewed", "draft", "missing"]
StageStateName = Literal["signed", "rehearsed", "review", "in_progress", "open", "no_stage_file"]


class StageRecordItem(StrictModel):
    """One record a stage needs: ``recipe_id`` (``None`` = the stage record), its state and file."""

    recipe_id: RecipeId | None = None
    state: RecordItemState
    path: str | None = None


class StageProgress(StrictModel):
    """One stage of ``b1500 bringup status``: ``signed`` (every record reviewed and passing and every step of the
    stage passed: in the ledger of this station or in the step lists of its reviewed records), ``rehearsed`` (the
    simulator: every rehearsable step passed in the simulator ledger; a rehearsal never signs a stage), ``review``
    (every record drafted, some still unreviewed or steps missing), ``in_progress`` (some records or steps),
    ``open`` (none), ``no_stage_file`` (the stage file is missing or unreadable; every stage has a committed one since
    WP10.8). ``steps_done``/``steps_total``: passed steps of the stage (``None`` without a readable ``steps.yaml``)."""

    stage: StageId
    title: str
    file: str | None = None
    state: StageStateName
    records: list[StageRecordItem] = Field(default_factory=list)
    steps_done: int | None = None
    steps_total: int | None = None


class BringupStatus(ResultEnvelope):
    """Result of ``b1500 bringup status``: every stage in order, the next stage to work on (``None`` when all stages
    with a file are signed), reviewed records and drafts found, and notes (unreadable or misplaced files)."""

    stages: list[StageProgress] = Field(default_factory=list)
    next_stage: StageId | None = None
    next_step: StepId | None = None
    ledger: str | None = None
    reviewed: list[str] = Field(default_factory=list)
    drafts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CapturedFixture(StrictModel):
    """One fixture file written by ``b1500 bringup capture`` (``parsed`` false: the parser rejected the answer and
    the file went to ``unparsed/``)."""

    path: str
    kind: FixtureKind
    command: str
    source: str
    parsed: bool = True


class CaptureReport(ResultEnvelope):
    """Result of ``b1500 bringup capture``: the fixture files written under ``work/bringup/fixtures/`` and the
    answers left out (kind without a fixture format, duplicates)."""

    written: list[CapturedFixture] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    folder: str | None = None


class RecordDraft(ResultEnvelope):
    """Result of ``b1500 bringup record``: the draft record written to ``work/bringup/records/`` (``path``), the
    record itself and what the reviewer must still do."""

    stage: StageId | None = None
    path: str | None = None
    record: ValidationRecord | None = None
    notes: list[str] = Field(default_factory=list)


# == Results of b1500 bringup next | done | check ======================================================================


class StepView(StrictModel):
    """One step as ``b1500 bringup next`` shows it: id, group (``D``, ``R``, ``E`` or the stage), who, how it is
    verified on this backend (``verify``), its state (``open``; ``failed``: the last ``done`` recorded a failure;
    ``reconfirm``: asked again after a break), the text (stage file item or ``steps.yaml``), the expected values of the
    checks it feeds, the pass rule, the exact ``done`` line, the abort route and the runbooks of a failure."""

    id: StepId
    group: str
    who: StepWho
    verify: EffectiveKind
    state: Literal["open", "failed", "reconfirm"]
    text: str
    expected: list[str] = Field(default_factory=list)
    rule: str = ""
    done: str = ""
    abort: list[str] = Field(default_factory=list)
    on_fail: list[RunbookId] = Field(default_factory=list)
    last_reason: str | None = None


class NextStep(ResultEnvelope):
    """Result of ``b1500 bringup next`` (read-only): the ledger, the next step (``None`` when nothing is open), the
    steps to confirm again after a break, the review steps still open, the passed steps per group and notes."""

    ledger: str | None = None
    step: StepView | None = None
    reconfirm: list[StepId] = Field(default_factory=list)
    awaiting_review: list[StepId] = Field(default_factory=list)
    progress: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class StepDone(ResultEnvelope):
    """Result of ``b1500 bringup done``: the entry appended (``recorded``; ``ok`` = verdict pass) or why nothing was
    written (``status: refused``), and the next step."""

    ledger: str | None = None
    recorded: bool = False
    entry: LedgerEntry | None = None
    next: StepView | None = None
    notes: list[str] = Field(default_factory=list)


class LedgerGap(StrictModel):
    """A gap ``b1500 bringup check`` found: a step without a passing entry, an entry whose evidence no longer
    verifies, or a broken hash chain (``step`` ``-``)."""

    step: str
    reason: str


class LedgerCheck(ResultEnvelope):
    """Result of ``b1500 bringup check``: the scope (a stage, ``all`` or ``recorded``: everything up to the next
    step), how many entries were read and re-verified, the gaps (``ok`` iff none) and notes (evidence that moved or
    changed legitimately, steps recorded out of order)."""

    ledger: str | None = None
    scope: str = "recorded"
    entries: int = 0
    verified: int = 0
    gaps: list[LedgerGap] = Field(default_factory=list)
    progress: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
