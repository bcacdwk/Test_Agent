"""Bring-up skill checks (blueprint v2 6.1, 7.4): ``b1500-bringup/SKILL.md`` budget, the stage template and every
stage file (fixed file name per stage id, frontmatter ``StageFrontmatter`` of ``models/validation.py``, the six
numbered sections, budget, registered recipes, every check id named in the "Expected values" section), and the
draft-record template ``records/_TEMPLATE.yaml`` (the only file in ``records/``: its keys are the fields of
``ValidationRecord``; drafts live in ``work/bringup/records/`` and reviewed records in ``validation/hw/``, never in the
skill).

WP6.3 wrote S0, L0-L4 and L10; L5-L9 arrive with their module work packages. Until a stage's file exists, cards
naming that stage get a lint note (``missing_stage_notes``), never a problem.
"""


from __future__ import annotations

from pathlib import Path

import yaml

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.skills.budgets import BRINGUP_MAX_LINES, STAGE_MAX_LINES, check_budget
from b1500_test_agent.devtools.skills.cards import check_sections, section_text
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

STAGE_BY_STEM = {stem: stage for stage, (stem, _goal) in STAGES.items()}


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
        elif registry.get(recipe_id).status == "not_implemented":
            lint.add("stage", path, f"recipes lists {recipe_id}, which is reserved (not_implemented)", 1)
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
    """One note per bring-up stage that cards name but that has no stage file yet."""
    waiting: dict[str, list[str]] = {}
    for card in cards:
        for stage in card.front.stages:
            if stage not in stages:
                waiting.setdefault(stage, []).append(card.front.id)
    order = list(STAGES)
    return [f"bring-up stage {stage} has no stage file yet ({SOURCE_DIR}/{BRINGUP_SKILL}/{STAGES_DIR}/"
            f"{STAGES[stage][0]}.md); cards waiting: {', '.join(sorted(ids))}"
            for stage, ids in sorted(waiting.items(), key=lambda item: order.index(item[0]))]
