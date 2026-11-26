"""Bring-up skill checks (blueprint v2 6.1, 7.4): ``b1500-bringup/SKILL.md`` budget, the stage template and every
stage file (fixed file name per stage id, frontmatter ``StageFrontmatter`` of ``models/validation.py``, the six
numbered sections, budget, registered recipes, every check id named in the "Expected values" section), and the
draft-record template ``records/_TEMPLATE.yaml`` (the only file in ``records/``: its keys are the fields of
``ValidationRecord``; drafts live in ``work/bringup/records/`` and reviewed records in ``validation/hw/``, never in the
skill).

WP6.3 wrote S0, L0-L4 and L10; the module closures L5-L9 (WP10.8 the last, L8). A card naming a stage whose file
is missing gets a lint note (``missing_stage_notes``), never a problem.

The step sequence ``steps.yaml`` (``check_steps``, problem code ``steps``; v2.1 plan §4.1): it validates as
``StepsFile``; every stage with a stage file has steps and vice versa; every numbered item of a stage file (physical
``P<n>``, agent ``A<n>``) has exactly one step and every step names an item (plus the review step ``<stage>.R``); a
step's recipes are registered and run by its stage or an earlier one (a reference run, e.g. the DC Id-Vg of L8);
``feeds`` are check ids of the stage and every check is fed by at least one step; ``on_fail`` names existing
debug runbooks; the ``b1500`` commands of the deployment and session steps exist.
"""


from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from b1500_test_agent.bringup_ledger import stage_items
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.skills.budgets import BRINGUP_MAX_LINES, STAGE_MAX_LINES, check_budget
from b1500_test_agent.devtools.skills.cards import check_sections, section_text
from b1500_test_agent.devtools.skills.commands import command_problems, named_commands
from b1500_test_agent.devtools.skills.common import (
    BRINGUP_SKILL,
    RECORD_KEYS,
    RECORD_TEMPLATE,
    RECORDS_DIR,
    STAGE_SECTIONS,
    STAGES,
    STAGES_DIR,
    TEMPLATE,
    Card,
    Lint,
    StageFrontmatter,
    model_front,
)
from b1500_test_agent.devtools.sync_harness import JUNK_DIRS, JUNK_FILES, SKILL_FILE, SOURCE_DIR
from b1500_test_agent.models.validation import StepsFile

STAGE_BY_STEM = {stem: stage for stage, (stem, _goal) in STAGES.items()}
STEPS_NAME = "steps.yaml"


def check_bringup(lint: Lint, skill_dir: Path, registry: RecipeRegistry) -> dict[str, StageFrontmatter]:
    """Lint the bring-up skill at ``skill_dir``; returns the valid stage files by stage id."""
    skill = lint.doc(skill_dir / SKILL_FILE)
    if skill is not None:
        check_budget(lint, skill, BRINGUP_MAX_LINES, "bring-up SKILL.md")
    stages_dir = skill_dir / STAGES_DIR
    template = stages_dir / TEMPLATE
    if not template.is_file():
        lint.add("stage", template, f"the stage template {STAGES_DIR}/{TEMPLATE} is missing (stage files are written "
                                    "from it)")
    else:
        doc = lint.doc(template)
        if doc is not None:
            check_budget(lint, doc, STAGE_MAX_LINES, "stage template")
            check_sections(lint, doc, STAGE_SECTIONS, "stage file", "stage")
    found: dict[str, StageFrontmatter] = {}
    for path in sorted(stages_dir.glob("*.md")) if stages_dir.is_dir() else []:
        if path.name == TEMPLATE or path.is_symlink():
            continue
        stage = check_stage_file(lint, path, registry)
        if stage is not None:
            found[stage.stage] = stage
    if stages_dir.is_dir():
        for path in sorted(p for p in stages_dir.iterdir()
                           if p.name not in JUNK_FILES | JUNK_DIRS and (p.suffix != ".md" or p.is_dir())):
            lint.add("stage", path, f"{STAGES_DIR}/ holds only {TEMPLATE} and stage files <stem>.md")
    check_records(lint, skill_dir / RECORDS_DIR)
    return found


def check_stage_file(lint: Lint, path: Path, registry: RecipeRegistry) -> StageFrontmatter | None:
    doc = lint.doc(path)
    if doc is None:
        return None
    if path.stem not in STAGE_BY_STEM:
        known = ", ".join(f"{stem}.md" for stem, _goal in STAGES.values())
        lint.add("stage", path, f"{path.name} is not a stage file name (blueprint 7.4 stages: {known})")
        return None
    check_budget(lint, doc, STAGE_MAX_LINES, "stage file")
    check_sections(lint, doc, STAGE_SECTIONS, "stage file", "stage")
    front: StageFrontmatter | None = model_front(lint, doc, StageFrontmatter, "stage file")
    if front is None:
        return None
    expected = STAGE_BY_STEM[path.stem]
    if front.stage != expected:
        lint.add("stage", path, f"stage {front.stage} does not match the file name ({path.stem}.md is stage "
                                f"{expected})", 1)
        return None
    known = set(registry.ids())
    for recipe_id in front.recipes:
        if recipe_id not in known:
            lint.add("stage", path, f"recipes lists {recipe_id}, which is not a registered recipe", 1)
    expected = section_text(doc, STAGE_SECTIONS.index("Expected values") + 1, STAGE_SECTIONS)
    for check in front.checks if expected is not None else []:  # a missing section is reported by check_sections
        if f"`{check.id}`" not in expected:
            lint.add("stage", path, f"check {check.id} is not named in the Expected values section (write `"
                                    f"{check.id}` in its row)", 1)
    return front


def check_records(lint: Lint, records_dir: Path) -> None:
    """``records/`` holds exactly ``_TEMPLATE.yaml``: a YAML mapping with the ``RECORD_KEYS`` and an empty
    ``reviewer`` (only a human reviewer fills it, after the run ids were checked to be hardware ``H…`` runs)."""
    template = records_dir / RECORD_TEMPLATE
    if not template.is_file():
        lint.add("stage", template, f"the draft-record template {RECORDS_DIR}/{RECORD_TEMPLATE} is missing")
    else:
        try:
            data = load_yaml(template.read_bytes())
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            lint.add("stage", template, "not valid YAML: " + " ".join(str(exc).split()))
            data = None
        if data is not None and not isinstance(data, dict):
            lint.add("stage", template, "the record template must be a YAML mapping")
        elif isinstance(data, dict):
            missing = [key for key in RECORD_KEYS if key not in data]
            if missing:
                lint.add("stage", template, f"record template lacks the keys {missing}")
            extra = [key for key in data if key not in RECORD_KEYS]
            if extra:
                lint.add("stage", template, f"record template has keys a record does not have: {extra}")
            if data.get("reviewer", "") != "":
                lint.add("stage", template, "reviewer must stay empty in the template (a human reviewer fills it)")
            runs = data.get("runs")
            if not isinstance(runs, list) or any(not str(run).startswith("H") for run in runs):
                lint.add("stage", template, "runs must be a list of hardware run ids (H...); simulator S... runs are "
                                            "never recorded")
    if records_dir.is_dir():
        for path in sorted(records_dir.rglob("*")):
            if path != template and path.is_file() and path.name not in JUNK_FILES:
                lint.add("stage", path, f"{RECORDS_DIR}/ holds only {RECORD_TEMPLATE}; draft records belong in "
                                        "work/bringup/records/, reviewed ones in validation/hw/")


def missing_stage_notes(cards: list[Card], stages: dict[str, StageFrontmatter]) -> list[str]:
    """One note per bring-up stage that cards name but that has no stage file."""
    waiting: dict[str, list[str]] = {}
    for card in cards:
        for stage in card.front.stages:
            if stage not in stages:
                waiting.setdefault(stage, []).append(card.front.id)
    order = list(STAGES)
    return [f"bring-up stage {stage} has no stage file ({SOURCE_DIR}/{BRINGUP_SKILL}/{STAGES_DIR}/"
            f"{STAGES[stage][0]}.md); cards waiting: {', '.join(sorted(ids))}"
            for stage, ids in sorted(waiting.items(), key=lambda item: order.index(item[0]))]


# == steps.yaml ========================================================================================================


def _step_lines(text: str) -> dict[str, int]:
    """Step id -> the line of its ``id:`` in ``steps.yaml`` (for problem lines)."""
    found: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), 1):
        match = re.search(r"\bid:\s*([A-Z][A-Z0-9]*(?:\.[A-Z0-9]+)?)\b", line)
        if match:
            found.setdefault(match[1], number)
    return found


def _error_line(data: Any, loc: tuple[Any, ...], lines: dict[str, int]) -> int | None:
    """The line of the step a validation error points into (``None`` when it is not inside one step)."""
    node = data
    step_line = None
    for part in loc:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            step_line = lines.get(node["id"])
    return step_line


def check_steps(lint: Lint, skill_dir: Path, registry: RecipeRegistry, stages: dict[str, StageFrontmatter],
                runbooks: list[str]) -> StepsFile | None:
    """Lint ``steps.yaml`` of the bring-up skill at ``skill_dir`` against its stage files (module docstring)."""
    path = skill_dir / STEPS_NAME
    stage_paths = {stage: skill_dir / STAGES_DIR / f"{stem}.md" for stage, (stem, _goal) in STAGES.items()
                   if (skill_dir / STAGES_DIR / f"{stem}.md").is_file()}
    if not path.is_file():
        if stage_paths:
            lint.add("steps", path, f"{STEPS_NAME} is missing: the stage files need their step sequence (b1500 "
                                    "bringup next|done|check)")
        return None
    try:
        text = path.read_text(encoding="utf-8")
        data = load_yaml(text.encode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        lint.add("steps", path, "not valid YAML: " + " ".join(str(exc).split()))
        return None
    lines = _step_lines(text)
    try:
        steps = StepsFile.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors():
            where = ".".join(str(part) for part in error["loc"]) or "file"
            lint.add("steps", path, f"{where}: {error['msg']}", _error_line(data, error["loc"], lines))
        return None
    for stage, stage_path in stage_paths.items():
        if stage not in steps.stages:
            lint.add("steps", path, f"stage {stage} has a stage file ({stage_path.name}) but no steps")
    known = set(registry.ids())
    runbook_ids = set(runbooks)
    run_so_far: set[str] = set()
    for stage, specs in steps.stages.items():
        stage_path = stage_paths.get(stage)
        if stage_path is None:
            lint.add("steps", path, f"stage {stage} has steps but no stage file", lines.get(specs[0].id))
            continue
        doc = lint.doc(stage_path)
        items = set(stage_items("\n".join(doc.lines))) if doc is not None else set()
        named = {spec.id.split(".", 1)[1]: spec for spec in specs if not spec.is_review}
        for item in sorted(items - set(named), key=lambda i: (i[0], int(i[1:]))):
            lint.add("steps", path, f"item {item} of {stage_path.name} ({'physical' if item[0] == 'P' else 'agent'} "
                                    f"step {item[1:]}) has no step {stage}.{item}")
        for item in sorted(set(named) - items):
            lint.add("steps", path, f"step {stage}.{item} names no numbered item of {stage_path.name}",
                     lines.get(f"{stage}.{item}"))
        front = stages.get(stage)
        run_so_far |= set(front.recipes) if front is not None else set()
        checks = {check.id for check in front.checks} if front is not None else set()
        fed: set[str] = set()
        for spec in specs:
            line = lines.get(spec.id)
            for recipe_id in spec.recipes:
                if recipe_id not in known:
                    lint.add("steps", path, f"{spec.id}: recipe {recipe_id} is not registered", line)
                elif front is not None and recipe_id not in run_so_far:  # an invalid stage file is reported there
                    lint.add("steps", path, f"{spec.id}: recipe {recipe_id} is run by neither stage {stage} nor an "
                                            "earlier stage", line)
            for check_id in spec.feeds:
                if front is not None and check_id not in checks:
                    lint.add("steps", path, f"{spec.id}: feeds {check_id}, which is not a check of stage {stage}",
                             line)
            fed |= set(spec.feeds)
            for runbook in spec.on_fail:
                if runbook not in runbook_ids:
                    lint.add("steps", path, f"{spec.id}: on_fail names runbook {runbook}, which does not exist",
                             line)
        for check_id in sorted(checks - fed):
            lint.add("steps", path, f"check {check_id} of stage {stage} is fed by no step (feeds)")
    for spec in [*steps.deployment, *steps.session_start, *steps.session_end]:
        for tokens in named_commands(spec.text or ""):
            for problem in command_problems(tokens):
                lint.add("steps", path, f"{spec.id}: {problem}", lines.get(spec.id))
    return steps


def steps_note(steps: StepsFile) -> str:
    return (f"bring-up steps: {len(steps.all())} (deployment {len(steps.deployment)}, "
            f"{sum(len(v) for v in steps.stages.values())} in {len(steps.stages)} stages, session start "
            f"{len(steps.session_start)}, end {len(steps.session_end)})")
