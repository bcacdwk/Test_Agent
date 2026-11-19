"""Record checks of the hardware suite (blueprint v2 7.1 rows ``bringup record``, ``validation/hw/``,
``tests/hardware/``; 7.2 recipe promotion; 7.4 stages).

Hardware validation records are YAML files, one record each, in two places:

- ``validation/hw/*.yaml``: reviewed records. The human reviewer filled ``reviewer``, moved the draft there and
  commits it (OD-7); ``b1500 dev recipe-check`` promotes recipes to ``hw_validated`` only on such records (7.2).
  "Committed" below means a file in this folder.
- ``<work_dir>/bringup/records/*.yaml``: drafts of ``b1500 bringup record STAGE --run H...`` (``reviewer: ""``).

Files whose name starts with ``_`` are templates, not records. Besides ``README.md``, ``validation/hw/`` holds only
``*.yaml`` records (``stray_files``).

Checks of one record (``record_problems``), all read-only:

1. it parses (YAML, unique keys) and validates against the WP6.3 record schema (``RecordSchema``);
2. every run is a hardware run: id ``H...``, a valid manifest of that id in ``<data_root>/runs``, backend ``visa``
   (not simulated), a run of the record's recipe (recipe records); the files the manifest lists still have their
   sha256 (the archive is the evidence); the recipe file digest a record copied per run (``evidence``) equals the
   manifest's;
3. a recipe record's ``recipe_sha256`` equals the definition digest of the current recipe (the schema's digest
   function), so the record still describes the recipe as it is;
4. a record that claims ``pass``: every run's cleanup was verified with ``LOP?`` and latched no fault, and every
   ``LOP?`` positive control taken (manifest ``cleanup.positive_control``, WP6.2) passed. Stage L1's stage record
   (the zero check) also needs a run with a passing positive control, and each of its runs that measured values
   carries one;
5. a record that names a probe record (stage L0): a draft's probe file must exist; an existing probe file must be a
   passing probe on backend ``visa``;
6. a reviewed record (``validation/hw/``): ``reviewer`` is filled and the schema's review rules hold (passing result,
   file named after the record).

Schema binding (the small interface to WP6.3, which defines the record schema): ``RecordSchema`` wraps
``b1500_test_agent.models.validation`` (``ValidationRecord``, ``recipe_definition_sha256``,
``reviewed_record_problems``) and turns a validated record into a ``RecordView``, the schema-independent facts the
checks read. ``load_schema`` is ``None`` while that module is not installed; the hardware record tests then fail as
soon as they meet a record.
"""

from __future__ import annotations

import hashlib
import importlib
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from b1500_test_agent.analysis.dataset import find_run, load_manifest
from b1500_test_agent.config import load_yaml
from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.run import RunManifest

SCHEMA_MODULE = "b1500_test_agent.models.validation"
"""WP6.3's record schema module."""
SCHEMA_NAMES = ("ValidationRecord", "recipe_definition_sha256", "reviewed_record_problems")
"""What the checks use from it."""

VALIDATION_DIR = ("validation", "hw")
"""Reviewed records, relative to the repository root."""
DRAFTS_DIR = ("bringup", "records")
"""Draft records, relative to the work directory."""
VALIDATION_README = "README.md"

ZERO_CHECK_STAGE = "L1"
PROBE_STAGE = "L0"
VERIFIED_BY_LOP = "lop"

Location = Literal["validation", "draft"]


class RecordInvalid(ValueError):
    """A record that does not parse or does not validate against the schema."""


# -- files -------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordFile:
    """One record file: where it is (``validation`` = reviewed and committed, ``draft``) and its display path."""

    path: Path
    location: Location
    shown: str

    @property
    def committed(self) -> bool:
        return self.location == "validation"


def _shown(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def record_files(repo_root: Path, work_dir: Path) -> list[RecordFile]:
    """Every record file: ``validation/hw/*.yaml`` first, then the drafts; templates (``_*``) left out."""
    found: list[RecordFile] = []
    places: tuple[tuple[Location, Path], ...] = (("validation", repo_root.joinpath(*VALIDATION_DIR)),
                                                 ("draft", work_dir.joinpath(*DRAFTS_DIR)))
    for location, folder in places:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.yaml")):
            if path.is_file() and not path.name.startswith("_"):
                found.append(RecordFile(path, location, _shown(path, repo_root)))
    return found


def stray_files(repo_root: Path) -> list[str]:
    """Files in ``validation/hw/`` that are neither ``README.md`` nor a ``*.yaml`` record (``recipe-check`` and these
    checks would never read them)."""
    folder = repo_root.joinpath(*VALIDATION_DIR)
    if not folder.is_dir():
        return []
    return [_shown(p, repo_root) for p in sorted(folder.iterdir())
            if p.name != VALIDATION_README and not (p.is_file() and p.suffix == ".yaml")]


def read_record(path: Path) -> Any:
    """The parsed YAML of a record file; raises ``RecordInvalid``."""
    try:
        data = load_yaml(path.read_bytes())
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RecordInvalid(f"cannot read it as YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RecordInvalid(f"a record is a YAML mapping, not {type(data).__name__}")
    return data


def stage_of(path: Path) -> str | None:
    """The ``stage`` a record file names, read without the schema (``None`` when it names none)."""
    try:
        stage = read_record(path).get("stage")
    except RecordInvalid:
        return None
    return stage if isinstance(stage, str) and stage else None


# -- the schema interface ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordView:
    """What the checks read from one validated record (independent of the schema's class layout).

    ``evidence``: run id -> recipe file sha256 the record copied from that run's manifest. ``review_problems``: the
    schema's verdict for a reviewed record (empty for a draft)."""

    stage: str
    recipe_id: str | None
    recipe_sha256: str | None
    runs: tuple[str, ...]
    result: str
    reviewer: str
    evidence: Mapping[str, str] = field(default_factory=dict)
    probe: str | None = None
    review_problems: tuple[str, ...] = ()

    @property
    def claims_pass(self) -> bool:
        return self.result == "pass"


class RecordSchema:
    """The WP6.3 record schema as the checks use it (see the module docstring)."""

    def __init__(self, module: ModuleType) -> None:
        missing = [name for name in SCHEMA_NAMES if not hasattr(module, name)]
        if missing:
            raise ImportError(f"{module.__name__} lacks {', '.join(missing)}: the record checks need "
                              f"{', '.join(SCHEMA_NAMES)}")
        self.module = module

    def view(self, data: Any, file: RecordFile) -> RecordView:
        """Validate ``data`` (the parsed record of ``file``) and return its view; raises ``RecordInvalid``."""
        try:
            record = self.module.ValidationRecord.model_validate(data)
        except ValidationError as exc:
            lines = [f"{'.'.join(str(p) for p in e['loc']) or 'record'}: {e['msg']}" for e in exc.errors()]
            raise RecordInvalid("does not validate against the record schema: " + "; ".join(lines)) from exc
        review: tuple[str, ...] = ()
        if file.committed:
            review = tuple(self.module.reviewed_record_problems(record, file.path.name))
        evidence = {item.run_id: item.recipe_file_sha256 for item in getattr(record, "evidence", None) or []}
        return RecordView(stage=record.stage, recipe_id=record.recipe_id, recipe_sha256=record.recipe_sha256,
                          runs=tuple(record.runs), result=record.result, reviewer=record.reviewer,
                          evidence=evidence, probe=getattr(record, "probe", None), review_problems=review)

    def recipe_sha256(self, recipe: Recipe) -> str:
        """The digest a recipe record's ``recipe_sha256`` must equal (WP6.3: the recipe's definition digest)."""
        return str(self.module.recipe_definition_sha256(recipe))


def load_schema() -> RecordSchema | None:
    """The WP6.3 schema, or ``None`` while ``SCHEMA_MODULE`` is not installed."""
    try:
        module = importlib.import_module(SCHEMA_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == SCHEMA_MODULE:
            return None
        raise
    return RecordSchema(module)


# -- the run archive ---------------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArchivedRun:
    """A run of the archive: its manifest and folder, or why it could not be read (``problem``)."""

    run_id: str
    manifest: RunManifest | None = None
    folder: Path | None = None
    problem: str | None = None


@dataclass
class RunArchive:
    """The runs under ``<data_root>/runs`` as the checks read them (each run read once)."""

    data_root: Path
    _runs: dict[str, ArchivedRun] = field(default_factory=dict)

    def get(self, run_id: str) -> ArchivedRun:
        if run_id not in self._runs:
            self._runs[run_id] = self._read(run_id)
        return self._runs[run_id]

    def _read(self, run_id: str) -> ArchivedRun:
        try:
            folder = find_run(run_id, data_root=self.data_root)
            manifest = load_manifest(folder)
        except B1500Error as exc:
            return ArchivedRun(run_id, problem=f"not in {(self.data_root / 'runs').as_posix()}: {exc}")
        if manifest.run_id != run_id:
            return ArchivedRun(run_id, problem=f"{folder.as_posix()}/manifest.json belongs to run {manifest.run_id}")
        return ArchivedRun(run_id, manifest, folder)

    def changed_files(self, run: ArchivedRun) -> list[str]:
        """Files the manifest lists whose sha256 differs now (or that are gone)."""
        if run.manifest is None or run.folder is None:
            return []
        changed = []
        for rel, digest in sorted(run.manifest.files.items()):
            path = run.folder.joinpath(*rel.split("/"))
            if not path.is_file() or _sha256(path) != digest:
                changed.append(rel)
        return changed


# -- the checks --------------------------------------------------------------------------------------------------------


def _run_problems(run_id: str, view: RecordView, archive: RunArchive) -> list[str]:
    if not run_id.startswith("H"):
        return [f"run {run_id}: not a hardware run (simulator runs S... are never recorded)"]
    run = archive.get(run_id)
    if run.manifest is None:
        return [f"run {run_id}: {run.problem}"]
    manifest = run.manifest
    problems = []
    if manifest.backend != "visa" or manifest.simulated:
        problems.append(f"run {run_id}: backend {manifest.backend} (simulated {manifest.simulated}), not visa")
    if view.recipe_id is not None and manifest.recipe_id != view.recipe_id:
        problems.append(f"run {run_id}: a run of {manifest.recipe_id}, not of the record's recipe {view.recipe_id}")
    recorded = view.evidence.get(run_id)
    if recorded is not None and recorded != manifest.recipe_sha:
        problems.append(f"run {run_id}: the record copied recipe file sha256 {recorded[:12]}..., the manifest says "
                        f"{manifest.recipe_sha[:12]}...")
    changed = archive.changed_files(run)
    if changed:
        problems.append(f"run {run_id}: files differ from the sha256 in its manifest: {', '.join(changed)}")
    if view.claims_pass:
        problems += _cleanup_problems(run_id, manifest)
    return problems


def _cleanup_problems(run_id: str, manifest: RunManifest) -> list[str]:
    cleanup = manifest.cleanup
    if cleanup is None:
        return [f"run {run_id}: no cleanup report in its manifest"]
    problems = []
    if cleanup.verified != VERIFIED_BY_LOP or cleanup.latched_fault:
        problems.append(f"run {run_id}: cleanup verified {cleanup.verified!r}, fault latched {cleanup.latched_fault} "
                        "(a passing record needs every cleanup verified with LOP? and no fault)")
    control = cleanup.positive_control
    if control is not None and not control.ok:
        problems.append(f"run {run_id}: the LOP? positive control failed ({control.detail or control.codes})")
    return problems


def _zero_check_problems(view: RecordView, archive: RunArchive) -> list[str]:
    """Stage L1's stage record: the positive control is the evidence that ``LOP?`` sees the outputs (v1 ATV-1)."""
    manifests = [m for m in (archive.get(r).manifest for r in view.runs) if m is not None]
    problems = []
    controlled = [m for m in manifests if m.cleanup is not None and m.cleanup.positive_control is not None
                  and m.cleanup.positive_control.ok]
    if not controlled:
        problems.append("stage L1 record: no run with a passing LOP? positive control (manifest "
                        "cleanup.positive_control), so no LOP? reading is evidence that the outputs were off")
    for manifest in manifests:
        if manifest.status_counts and (manifest.cleanup is None or manifest.cleanup.positive_control is None):
            problems.append(f"run {manifest.run_id}: measured values but took no LOP? positive control")
    return problems


def _probe_problems(view: RecordView, file: RecordFile, repo_root: Path) -> list[str]:
    assert view.probe is not None
    path = Path(view.probe)
    path = path if path.is_absolute() else repo_root / path
    if not path.is_file():
        if file.committed:
            warnings.warn(f"{file.shown}: probe record {view.probe} is no longer in the work directory; it was "
                          "checked while the record was a draft", stacklevel=2)
            return []
        return [f"probe record {view.probe} not found"]
    try:
        report = ProbeReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        return [f"probe record {view.probe} is not a probe report: {exc}"]
    problems = []
    if report.backend != "visa" or report.simulated:
        problems.append(f"probe record {view.probe}: backend {report.backend}, not visa (a simulator probe is "
                        "never evidence)")
    if not report.ok and view.claims_pass:
        failed = ", ".join(c.name for c in report.checks if c.status == "FAIL")
        problems.append(f"probe record {view.probe}: failing lines ({failed}) in a record that claims pass")
    return problems


def record_problems(view: RecordView, file: RecordFile, *, archive: RunArchive, recipes: Mapping[str, Recipe],
                    digest: Callable[[Recipe], str], repo_root: Path) -> list[str]:
    """Checks 2-6 of the module docstring for one validated record; empty when it holds."""
    problems: list[str] = []
    if view.recipe_id is not None:
        if not view.runs:
            problems.append("a recipe record lists the hardware runs (H...) it rests on; it lists none")
        recipe = recipes.get(view.recipe_id)
        if recipe is None:
            problems.append(f"recipe {view.recipe_id} is not in recipes/")
        elif view.recipe_sha256 != (current := digest(recipe)):
            problems.append(f"recipe {view.recipe_id} changed since the record: recipe_sha256 "
                            f"{(view.recipe_sha256 or '')[:12]}..., current {current[:12]}... (re-run the stage "
                            "and record it again)")
    for run_id in view.runs:
        problems += _run_problems(run_id, view, archive)
    if view.stage == ZERO_CHECK_STAGE and view.recipe_id is None and view.claims_pass:
        problems += _zero_check_problems(view, archive)
    if view.probe is not None:
        problems += _probe_problems(view, file, repo_root)
    if file.committed:
        unreviewed = not view.reviewer.strip()
        if unreviewed:
            problems.append("reviewer is empty: a record in validation/hw/ is a reviewed record (drafts stay in "
                            "work/bringup/records/)")
        problems += [p for p in view.review_problems if not (unreviewed and "reviewer" in p)]
    return problems


def check_file(file: RecordFile, schema: RecordSchema | None, *, archive: RunArchive, recipes: Mapping[str, Recipe],
               repo_root: Path) -> list[str]:
    """All checks of one record file, each problem prefixed with the file."""
    try:
        data = read_record(file.path)
        if schema is None:
            raise RecordInvalid(f"the record schema ({SCHEMA_MODULE}, WP6.3) is not installed: update the clone")
        view = schema.view(data, file)
    except RecordInvalid as exc:
        return [f"{file.shown}: {exc}"]
    found = record_problems(view, file, archive=archive, recipes=recipes, digest=schema.recipe_sha256,
                            repo_root=repo_root)
    return [f"{file.shown}: {problem}" for problem in found]
