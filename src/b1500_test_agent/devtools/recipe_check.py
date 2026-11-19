"""``b1500 dev recipe-check``: load ``recipes/`` against the measurement kinds and list every problem (blueprint 5.3),
and enforce the promotion rule of blueprint v2 7.2 against ``validation/hw/``.

Clean (exit 0) iff ``RecipeRegistry.problems()`` and the promotion problems are empty; the report also lists each
recipe with its own status and its effective status on both backends, and every record found.

**Promotion rule.** ``hw_validated`` ⇔ a reviewed hardware record: a recipe with ``status: hw_validated`` needs
``validation/hw/<recipe_id>.yaml`` that validates as ``ValidationRecord``, is reviewed (``reviewer`` and
``reviewed_on``), passed (``result: pass``), lists hardware runs only (``H…``) and pins the current recipe
(``recipe_sha256`` = ``recipe_definition_sha256`` of the loaded recipe, ``models/validation.py``). Every file in
``validation/hw/`` must be such a reviewed record (recipe record ``<recipe_id>.yaml`` of a registered recipe, or stage
record ``stage-<stage>.yaml``) or the folder's ``README.md``. A reviewed record of a recipe that is not
``hw_validated`` yet is a note (promotion pending), as is a stale one (the recipe changed since); for an
``hw_validated`` recipe a stale record is a problem.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_yaml
from b1500_test_agent.models.common import StrictModel, ValidationStatus
from b1500_test_agent.models.validation import (
    VALIDATION_DIR,
    ValidationRecord,
    recipe_definition_sha256,
    reviewed_record_problems,
)
from b1500_test_agent.paths import Paths

README = "README.md"


class RecipeRow(StrictModel):
    id: str
    kind: str
    status: ValidationStatus
    effective: dict[str, ValidationStatus]
    source: str
    card: str | None
    record: str | None = None


class RecordRow(StrictModel):
    """One file in ``validation/hw/`` and its verdict (``problems`` empty = a valid reviewed record)."""

    path: str
    key: str | None = None
    stage: str | None = None
    problems: list[str] = Field(default_factory=list)


class RecipeCheckReport(StrictModel):
    ok: bool
    root: str
    validation_dir: str = ""
    recipes: list[RecipeRow] = Field(default_factory=list)
    records: list[RecordRow] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _display(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_records(folder: Path, repo_root: Path) -> tuple[dict[str, ValidationRecord], list[RecordRow]]:
    """Every file of ``validation/hw/``: the valid reviewed records by key (recipe id or ``stage-<stage>``) and one
    row per file with its problems (``README.md`` is skipped)."""
    records: dict[str, ValidationRecord] = {}
    rows: list[RecordRow] = []
    if not folder.is_dir():
        return records, rows
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        shown = _display(path, repo_root)
        if path.parent == folder and path.name == README:
            continue
        if path.parent != folder or path.suffix != ".yaml":
            rows.append(RecordRow(path=shown, problems=[("validation/hw/ holds <recipe_id>.yaml, stage-<stage>.yaml "
                                                        "and README.md only")]))
            continue
        try:
            record = ValidationRecord.model_validate(load_yaml(path.read_bytes()))
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else type(exc).__name__
            rows.append(RecordRow(path=shown, problems=[f"not a validation record: {reason}"]))
            continue
        problems = reviewed_record_problems(record, path.name)
        rows.append(RecordRow(path=shown, key=record.key, stage=record.stage, problems=problems))
        if not problems:
            records[record.key] = record
    return records, rows


def promotion_problems(registry: RecipeRegistry, records: dict[str, ValidationRecord], rows: list[RecordRow]) \
        -> tuple[list[str], list[str]]:
    """``(problems, notes)`` of the promotion rule (module docstring)."""
    problems = [f"{row.path}: {problem}" for row in rows for problem in row.problems]
    notes: list[str] = []
    known = set(registry.ids())
    for row in rows:
        if row.key is not None and "." in row.key and row.key not in known:
            problems.append(f"{row.path}: no registered recipe {row.key}")
    for recipe_id in registry.ids():
        recipe = registry.get(recipe_id)
        record = records.get(recipe_id)
        digest = recipe_definition_sha256(recipe)
        if recipe.status == "hw_validated":
            if record is None:
                problems.append(f"{registry.source(recipe_id)}: status hw_validated without a reviewed record "
                                f"validation/hw/{recipe_id}.yaml (blueprint v2 7.2; promotions follow the "
                                "hardware review)")
            elif record.recipe_sha256 != digest:
                problems.append(f"{registry.source(recipe_id)}: status hw_validated, but validation/hw/{recipe_id}"
                                ".yaml pins another recipe definition (the recipe changed after its validation: "
                                "re-validate on hardware or set it back to sim_validated)")
        elif record is not None:
            stale = "" if record.recipe_sha256 == digest else " (stale: the recipe changed since)"
            notes.append(f"validation/hw/{recipe_id}.yaml is a reviewed record of a {recipe.status} recipe: "
                         f"promotion pending{stale}")
    return problems, notes


def check_recipes(root: Path | None = None, *, repo_root: Path | None = None,
                  validation_dir: Path | None = None) -> RecipeCheckReport:
    """Load the recipe tree (default: ``recipes/`` of the located repository) and the reviewed records (default:
    ``validation/hw/`` of the repository) and report their problems."""
    if root is None:
        paths = Paths.from_env()
        root, repo_root = paths.recipes_dir, paths.repo_root
    repo = Path(repo_root) if repo_root is not None else Path(root).parent
    folder = Path(validation_dir) if validation_dir is not None else repo.joinpath(*VALIDATION_DIR)
    registry = RecipeRegistry.load(root, repo_root=repo_root)
    records, record_rows = load_records(folder, repo)
    rows = []
    for recipe_id in registry.ids():
        recipe = registry.get(recipe_id)
        rows.append(RecipeRow(id=recipe.id, kind=recipe.kind, status=recipe.status, source=registry.source(recipe_id),
                              card=recipe.card, record=f"validation/hw/{recipe_id}.yaml" if recipe_id in records
                              else None,
                              effective={backend: registry.effective_status(recipe_id, backend)
                                         for backend in ("sim", "visa")}))
    promotion, notes = promotion_problems(registry, records, record_rows)
    problems = registry.problems() + promotion
    return RecipeCheckReport(ok=not problems, root=Path(root).as_posix(), validation_dir=_display(folder, repo),
                             recipes=rows, records=record_rows, problems=problems, notes=notes)


def format_report(report: RecipeCheckReport) -> str:
    """Human-readable report: verdict, one line per recipe, the records, notes and problems."""
    lines = [(f"recipes: {'clean' if report.ok else 'PROBLEMS'} ({len(report.recipes)} loaded from {report.root}; "
             f"{len(report.records)} hardware record(s) in {report.validation_dir})")]
    if report.recipes:
        width = max(len(r.id) for r in report.recipes)
        kind_width = max(len(r.kind) for r in report.recipes)
        for row in report.recipes:
            lines.append(f"  {row.id:<{width}}  {row.kind:<{kind_width}}  {row.status:<15}  "
                         f"sim:{row.effective['sim']}  visa:{row.effective['visa']}"
                         + (f"  record:{row.record}" if row.record else ""))
    lines += [f"  note: {note}" for note in report.notes]
    if report.problems:
        lines.append("problems:")
        lines += [f"  - {problem}" for problem in report.problems]
    return "\n".join(lines)
