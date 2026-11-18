"""Test cards: the ten sections, the frontmatter link graph (recipes, knowledge, runbooks, status), the section-4
parameter table and example plan (validated on the simulator with ``B1500Service.validate_plan``), and the recipe
side of the card graph."""


from __future__ import annotations

import os
import posixpath
import shutil
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.skills.budgets import CARD_MAX_LINES, check_budget
from b1500_test_agent.devtools.skills.common import (
    CARD_SECTIONS,
    CARDS_DIR,
    DEBUG_SKILL,
    KNOWLEDGE_DIR,
    README,
    RUNBOOKS_DIR,
    Card,
    CardFrontmatter,
    ExamplePlan,
    ExamplePlanCheck,
    Lint,
    model_front,
    validation_messages,
)
from b1500_test_agent.devtools.skills.links import exists_exact
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, norm_title
from b1500_test_agent.devtools.skills.params import check_param_row, param_rows
from b1500_test_agent.devtools.sync_harness import SOURCE_DIR
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, Paths
from b1500_test_agent.service import B1500Service

EXAMPLE_PLAN_INFO = frozenset({"yaml", "yml"})


def check_sections(lint: Lint, doc: MarkdownDoc) -> None:
    found = [h for h in doc.headings if h.level == 2]
    expected = [f"{i}. {title}" for i, title in enumerate(CARD_SECTIONS, 1)]
    for index in range(max(len(found), len(expected))):
        have = found[index] if index < len(found) else None
        want = expected[index] if index < len(expected) else None
        if have is not None and want is not None and norm_title(have.text) == norm_title(want):
            continue
        if have is None:
            message = f"missing H2 section '## {want}' (a card has the ten numbered sections of the template)"
        elif want is None:
            message = f"unexpected H2 section '## {have.text}' after section 10 (use H3 inside a section)"
        else:
            message = f"H2 section {index + 1} is '## {have.text}'; expected '## {want}' (template order)"
        lint.add("card_sections", doc.path, message, have.line if have else None)
        return


def parse_example_plan(lint: Lint, doc: MarkdownDoc, span: tuple[int, int]) -> tuple[ExamplePlan | None, int | None]:
    blocks = [f for f in doc.fences if f.info in EXAMPLE_PLAN_INFO and span[0] < f.line < span[1]]
    if not blocks:
        lint.add("example_plan", doc.path, "section 4 has no example plan (one fenced yaml block with recipe_id, "
                                           "params, pin_map, dut_profile, sim_scenario)", span[0])
        return None, None
    if len(blocks) > 1:
        lint.add("example_plan", doc.path, f"section 4 has {len(blocks)} fenced yaml blocks; exactly one (the "
                                           "example plan) is allowed", blocks[1].line)
        return None, None
    block = blocks[0]
    try:
        data = load_yaml(block.body.encode("utf-8"))
    except yaml.YAMLError as exc:
        lint.add("example_plan", doc.path, "example plan is not valid YAML: " + " ".join(str(exc).split()), block.line)
        return None, block.line
    try:
        return ExamplePlan.model_validate(data), block.line
    except ValidationError as exc:
        for message in validation_messages(exc, prefix="example plan "):
            lint.add("example_plan", doc.path, message, block.line)
        return None, block.line


def check_card(lint: Lint, path: Path, registry: RecipeRegistry, entry_dir: Path,
                runbooks: set[str]) -> Card | None:
    doc = lint.doc(path)
    if doc is None:
        return None
    check_budget(lint, doc, CARD_MAX_LINES, "card")
    check_sections(lint, doc)
    front: CardFrontmatter | None = model_front(lint, doc, CardFrontmatter, "test card")
    if front is None:
        return None
    if front.id != path.stem:
        lint.add("frontmatter", path, f"id {front.id!r} must equal the file name {path.stem!r}", 1)
    rel = lint.rel(path)
    recipes: list[Recipe] = []
    known = set(registry.ids())
    for recipe_id in front.recipes:
        if recipe_id not in known:
            lint.add("card_recipe", path, f"recipes lists {recipe_id}, which is not a registered recipe (dangling; "
                                          "see b1500 dev recipe-check)", 1)
            continue
        recipe = registry.get(recipe_id)
        recipes.append(recipe)
        if recipe.card is None or posixpath.normpath(recipe.card) != rel:
            lint.add("card_recipe", path, f"recipe {recipe_id} has card {recipe.card!r}, not {rel!r} (the recipe's "
                                          "card must point back)", 1)
        effective = registry.effective_status(recipe_id, "sim")
        if effective != front.status:
            lint.add("card_status", path, f"status {front.status} differs from recipe {recipe_id}'s effective "
                                          f"status on the simulator ({effective})", 1)
    typed = [r for r in recipes if r.device_types]
    if typed and len(typed) == len(recipes):
        allowed = {t for r in recipes for t in r.device_types}
        extra = [t for t in front.device_types if t not in allowed]
        if extra:
            lint.add("card_recipe", path, f"device_types {extra} are not device types of the card's recipes "
                                          f"({sorted(allowed)})", 1)
    for ref in front.knowledge:
        file_part, _, anchor = ref.partition("#")
        target = Path(os.path.normpath(entry_dir / file_part))
        if not target.is_relative_to(entry_dir / KNOWLEDGE_DIR) or not exists_exact(entry_dir, target) \
                or not target.is_file():
            lint.add("card_knowledge", path, f"knowledge entry {ref}: {file_part} does not exist", 1)
            continue
        target_doc = lint.doc(target)
        if target_doc is not None and anchor not in target_doc.anchors:
            lint.add("card_knowledge", path, f"knowledge entry {ref}: {file_part} has no heading id {anchor!r}", 1)
    for runbook in front.debug:
        if runbook not in runbooks:
            lint.add("card_debug", path, f"debug id {runbook!r} is not a runbook "
                                         f"({SOURCE_DIR}/{DEBUG_SKILL}/{RUNBOOKS_DIR}/{runbook}.md)", 1)
    card = Card(doc=doc, front=front)
    span = doc.section(f"4. {CARD_SECTIONS[3]}")
    if span is None:
        return card  # the section problem is already reported
    rows, row_problems = param_rows(doc, span[0] + 1, span[1])
    for line, message in row_problems:
        lint.add("param_table", path, message, line)
    if not rows and not row_problems:
        lint.add("param_table", path, "section 4 has no parameter table (param | default | recommended | recipe "
                                      "range | why | effect)", span[0])
    for row in rows:
        owners = [(r.id, r.params[row.name]) for r in recipes if row.name in r.params]
        if not owners:
            if recipes:
                lint.add("param_table", path, f"param {row.name!r} is not a parameter of "
                                              f"{', '.join(r.id for r in recipes)}", row.line)
            continue
        for recipe_id, spec in owners:
            for code, message in check_param_row(row, recipe_id, spec):
                lint.add(code, path, message, row.line)
    card.example, card.example_line = parse_example_plan(lint, doc, span)
    if card.example is not None and card.example.recipe_id not in front.recipes:
        lint.add("example_plan", path, f"example plan recipe_id {card.example.recipe_id} is not one of the card's "
                                       f"recipes {front.recipes}", card.example_line)
        card.example = None
    return card


def validate_examples(lint: Lint, cards: list[Card], registry: RecipeRegistry) -> list[ExamplePlanCheck]:
    """Run ``validate_plan`` for every example plan, one temporary config/data set per simulator scenario."""
    pending = [c for c in cards if c.example is not None]
    if not pending:
        return []
    if not lint.config_dir.is_dir():
        for card in pending:
            lint.add("example_plan", card.doc.path, f"cannot validate the example plan: config folder "
                                                    f"{lint.rel(lint.config_dir)} not found", card.example_line)
        return []
    checks: list[ExamplePlanCheck] = []
    scenarios = sorted({c.example.sim_scenario for c in pending if c.example is not None})
    with tempfile.TemporaryDirectory(prefix="b1500-lint-", ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        repo = base / "repo"
        source = lint.config_dir
        shutil.copytree(source, repo / "config",
                        ignore=lambda folder, names: ["local"] if Path(folder) == source else [])
        for number, scenario in enumerate(scenarios):
            override, data = base / f"override-{number}", base / f"data-{number}"
            override.mkdir()
            (override / "settings.yaml").write_text(
                yaml.safe_dump({"backend": "sim", "sim": {"scenario": scenario}}, sort_keys=False), encoding="utf-8")
            env = {ENV_CONFIG_DIR: str(override), ENV_DATA_DIR: str(data)}
            service = B1500Service(paths=Paths.from_env(env, repo_root=repo), environ=env, registry=registry)
            try:
                for card in pending:
                    plan = card.example
                    if plan is None or plan.sim_scenario != scenario:
                        continue
                    result = service.validate_plan(recipe_id=plan.recipe_id, params=dict(plan.params),
                                                   pin_map=plan.pin_map, dut_profile=plan.dut_profile,
                                                   label=plan.label)
                    checks.append(ExamplePlanCheck(card=card.front.id, recipe_id=plan.recipe_id,
                                                   sim_scenario=scenario, status=result.status, tier=result.tier,
                                                   plan_id=result.plan_id))
                    judge_example(lint, card, result)
            finally:
                service.close()
    return checks


def judge_example(lint: Lint, card: Card, result: PlanValidation) -> None:
    path, line = card.doc.path, card.example_line
    if result.tier is None:
        lint.add("example_plan", path, f"example plan does not validate on the simulator: {result.status} "
                                       f"({result.error_code}): {result.message}", line)
        return
    if result.tier == "blocked":
        blocks = "; ".join(f"{f.rule_id} {f.message}" for f in result.findings if f.severity == "block")
        lint.add("example_plan", path, f"example plan is blocked on the simulator ({result.status}): "
                                       f"{blocks or result.message}", line)
        return
    confirmation = card.front.confirmation
    if confirmation == "never" and result.tier != "ok":
        lint.add("card_confirmation", path, f"confirmation is never, but the example plan needs confirmation "
                                            f"({', '.join(result.confirm_reasons)})", line)
    elif confirmation == "always" and result.tier != "needs_confirmation":
        lint.add("card_confirmation", path, "confirmation is always, but the example plan has tier ok", line)


def find_card_paths(entry_dir: Path) -> list[Path]:
    folder = entry_dir / CARDS_DIR
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob("*.md")) if not p.name.startswith("_") and p.name != README]


def check_recipes(lint: Lint, registry: RecipeRegistry, entry_dir: Path) -> None:
    """Recipe side of the graph: analysis methods exist; a recipe ``card`` is a card that lists the recipe."""
    cards_dir = entry_dir / CARDS_DIR
    for recipe_id in registry.ids():
        entry = registry.entry(recipe_id)
        recipe = entry.recipe
        for index, spec in enumerate(recipe.analysis_defaults):
            if spec.method not in ANALYSIS_METHODS:
                lint.add("analysis_method", entry.source, f"analysis_defaults[{index}]: method {spec.method!r} is "
                                                          "not in ANALYSIS_METHODS")
        if recipe.card is None:
            continue
        card_path = Path(os.path.normpath(lint.root / recipe.card))
        if not card_path.is_relative_to(cards_dir) or card_path.parent != cards_dir \
                or card_path.name.startswith("_") or card_path.suffix != ".md":
            lint.add("recipe_card", entry.source, f"card {recipe.card!r} is not a test card under "
                                                  f"{lint.rel(cards_dir)}/")
            continue
        if not exists_exact(lint.root, card_path) or not card_path.is_file():
            lint.add("recipe_card", entry.source, f"card {recipe.card} does not exist (dangling card)")
            continue
        doc = lint.doc(card_path)
        listed = doc.front.get("recipes") if doc is not None and isinstance(doc.front, dict) else None
        if not isinstance(listed, list) or recipe_id not in listed:
            lint.add("recipe_card", entry.source, f"card {recipe.card} does not list {recipe_id} in its recipes")


