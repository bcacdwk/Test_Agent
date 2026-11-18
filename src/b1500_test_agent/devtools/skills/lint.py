"""``b1500 dev lint-skills`` entry point: runs every check of this package over a root and formats the report (the
checks are listed in the package docstring)."""


from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.budget import TokenCounter
from b1500_test_agent.devtools.skills.budgets import (
    CARD_MAX_LINES,
    DEBUG_MAX_LINES,
    ENTRY_MAX_BYTES,
    ENTRY_MAX_LINES,
    KNOWLEDGE_MAX_LINES,
    always_loaded_budget,
    check_budget,
)
from b1500_test_agent.devtools.skills.cards import (
    check_card,
    check_recipes,
    check_sections,
    find_card_paths,
    validate_examples,
)
from b1500_test_agent.devtools.skills.citations import check_citations
from b1500_test_agent.devtools.skills.commands import check_commands
from b1500_test_agent.devtools.skills.common import (
    BRINGUP_SKILL,
    CARDLESS_RECIPES,
    CARDS_DIR,
    DEBUG_SKILL,
    ENTRY_SKILL,
    KNOWLEDGE_DIR,
    README,
    RUNBOOKS_DIR,
    STAGES_DIR,
    TEMPLATE,
    Card,
    KnowledgeFrontmatter,
    Lint,
    LintProblem,
    LintReport,
    StageFrontmatter,
    model_front,
)
from b1500_test_agent.devtools.skills.index import check_index
from b1500_test_agent.devtools.skills.layout import check_skill_front, skill_files
from b1500_test_agent.devtools.skills.links import check_links
from b1500_test_agent.devtools.skills.stages import check_bringup, missing_stage_notes
from b1500_test_agent.devtools.sync_harness import SKILL_FILE, SOURCE_DIR
from b1500_test_agent.manuals.catalog import ManualError, load_catalog
from b1500_test_agent.paths import find_repo_root


def lint_skills(root: Path | None = None, *, recipes_dir: Path | None = None, config_dir: Path | None = None,
                counter: TokenCounter | None = None) -> LintReport:
    """Lint the skills under ``root`` (default: the located repository); see the module docstring."""
    root = Path(root).resolve() if root is not None else find_repo_root()
    lint = Lint(root, Path(recipes_dir).resolve() if recipes_dir else root / "recipes",
                 Path(config_dir).resolve() if config_dir else root / "config")
    base = root / SOURCE_DIR
    skills: list[str] = []
    if not base.is_dir():
        lint.add("skill_layout", SOURCE_DIR, "skill folder .agents/skills/ not found")
    else:
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            if folder.is_symlink():
                lint.add("skill_layout", folder, "a skill folder must be a real folder, not a symlink")
            elif (folder / SKILL_FILE).is_file():
                skills.append(folder.name)
            else:
                lint.add("skill_layout", folder, f"{folder.name} has no {SKILL_FILE} (every folder under "
                                                 f"{SOURCE_DIR} is a skill)")
        if ENTRY_SKILL not in skills:
            lint.add("skill_layout", f"{SOURCE_DIR}/{ENTRY_SKILL}", f"entry skill {ENTRY_SKILL} not found")
    entry_dir, debug_dir = base / ENTRY_SKILL, base / DEBUG_SKILL
    for skill in skills:
        skill_dir = base / skill
        files = skill_files(lint, skill_dir)
        skill_doc = lint.doc(skill_dir / SKILL_FILE)
        if skill_doc is not None:
            check_skill_front(lint, skill_doc, skill)
            if skill == ENTRY_SKILL:
                check_budget(lint, skill_doc, ENTRY_MAX_LINES, "entry SKILL.md", ENTRY_MAX_BYTES)
            elif skill == DEBUG_SKILL:
                check_budget(lint, skill_doc, DEBUG_MAX_LINES, "debug SKILL.md")
        for path in files:
            doc = lint.doc(path)
            if doc is not None:
                check_links(lint, doc, skill_dir)
    knowledge: list[str] = []
    if ENTRY_SKILL in skills and (entry_dir / KNOWLEDGE_DIR).is_dir():
        for path in sorted((entry_dir / KNOWLEDGE_DIR).rglob("*.md")):
            doc = lint.doc(path)
            if doc is None or path.is_symlink():
                continue
            check_budget(lint, doc, KNOWLEDGE_MAX_LINES, "knowledge file")
            if path.name != README:
                knowledge.append(lint.rel(path))
                model_front(lint, doc, KnowledgeFrontmatter, "knowledge file")
    runbooks = sorted(p.stem for p in (debug_dir / RUNBOOKS_DIR).glob("*.md")) \
        if DEBUG_SKILL in skills and (debug_dir / RUNBOOKS_DIR).is_dir() else []
    if not lint.recipes_dir.is_dir():
        lint.add("skill_layout", lint.recipes_dir, "recipe folder not found (card and recipe links cannot be checked)")
    registry = RecipeRegistry.load(lint.recipes_dir, repo_root=root)
    check_recipes(lint, registry, entry_dir)
    stages: dict[str, StageFrontmatter] = {}
    if BRINGUP_SKILL in skills:
        stages = check_bringup(lint, base / BRINGUP_SKILL, registry)
    catalog_ids = manual_ids(root)
    cards: list[Card] = []
    card_paths = find_card_paths(entry_dir) if ENTRY_SKILL in skills else []
    for path in card_paths:
        card = check_card(lint, path, registry, entry_dir, set(runbooks), stages, catalog_ids)
        if card is not None:
            cards.append(card)
    other = sorted(set((entry_dir / CARDS_DIR).glob("*.md")) - set(card_paths)) if ENTRY_SKILL in skills else []
    for path in other:  # _TEMPLATE.md (and the index README.md): card budget; the template has the card sections
        doc = lint.doc(path)
        if doc is not None:
            check_budget(lint, doc, CARD_MAX_LINES, path.name)
            if path.name == TEMPLATE:
                check_sections(lint, doc)
    if ENTRY_SKILL in skills and (entry_dir / CARDS_DIR).is_dir():
        if len(cards) == len(card_paths):
            check_index(lint, entry_dir, [(c.doc.path.relative_to(entry_dir / CARDS_DIR).as_posix(), c.front)
                                          for c in cards], registry)
        else:
            lint.notes.append(f"{CARDS_DIR}/{README} not compared with the generated index: fix the card "
                              "frontmatter first")
    lint.notes.extend(missing_stage_notes(cards, stages))
    cardless = [r for r in CARDLESS_RECIPES if r in registry.ids()]
    if cardless:
        lint.notes.append("recipes without a card by design: " + ", ".join(cardless))
    examples = validate_examples(lint, cards, registry)
    budget = always_loaded_budget(root, counter)
    if budget.total > budget.limit:
        message = f"always-loaded text has {budget.total} tokens (limit {budget.limit}; {budget.method})"
        if budget.warning is None:
            lint.add("budget", "AGENTS.md", message + "; parts: " + ", ".join(f"{k} {v}"
                                                                               for k, v in budget.parts.items()))
        else:
            lint.notes.append(message + " - estimate only, re-check with the tiktoken encoding")
    check_citations(lint)
    check_commands(lint)
    problems = sorted(lint.problems, key=lambda p: (p.file, p.line or 0, p.code, p.message))
    stage_files = sorted(lint.rel(base / BRINGUP_SKILL / STAGES_DIR / p.name)
                         for p in (base / BRINGUP_SKILL / STAGES_DIR).glob("*.md") if not p.name.startswith("_")) \
        if BRINGUP_SKILL in skills and (base / BRINGUP_SKILL / STAGES_DIR).is_dir() else []
    return LintReport(ok=not problems, root=root.as_posix(), skills=skills,
                      cards=[lint.rel(p) for p in card_paths], knowledge=knowledge,
                      runbooks=runbooks, stages=stage_files, example_plans=examples, always_loaded=budget,
                      notes=lint.notes, problems=dedupe(problems))


def manual_ids(root: Path) -> set[str] | None:
    """Document ids of ``references/manuals/catalog.yaml`` under ``root`` (``None`` without a readable catalog; the
    citation lint reports a broken one)."""
    path = root / "references" / "manuals" / "catalog.yaml"
    if not path.is_file():
        return None
    try:
        return set(load_catalog(path).ids)
    except ManualError:
        return None


def dedupe(problems: Iterable[LintProblem]) -> list[LintProblem]:
    seen: set[tuple[str, str, int | None, str]] = set()
    out = []
    for problem in problems:
        key = (problem.code, problem.file, problem.line, problem.message)
        if key not in seen:
            seen.add(key)
            out.append(problem)
    return out


def format_problem(problem: LintProblem) -> str:
    where = f"{problem.file}:{problem.line}" if problem.line else problem.file
    return f"{where}: [{problem.code}] {problem.message}"


def format_report(report: LintReport) -> str:
    """Human-readable report: verdict and counts, the always-loaded budget, notes and problems."""
    verdict = "clean" if report.ok else f"{len(report.problems)} PROBLEM(S)"
    lines = [(f"skills: {verdict} ({len(report.skills)} skills, {len(report.cards)} cards, "
              f"{len(report.knowledge)} knowledge files, {len(report.runbooks)} runbooks, {len(report.stages)} "
              f"stage files; root {report.root})")]
    for check in report.example_plans:
        lines.append(f"  example plan {check.card}: {check.recipe_id} on {check.sim_scenario} -> {check.status}, "
                     f"tier {check.tier or '-'}")
    if report.always_loaded is not None:
        budget = report.always_loaded
        lines.append(f"  always-loaded text: {budget.total} / {budget.limit} tokens ({budget.method})")
    lines += [f"  note: {note}" for note in report.notes]
    lines += [f"  {format_problem(problem)}" for problem in report.problems]
    return "\n".join(lines)

