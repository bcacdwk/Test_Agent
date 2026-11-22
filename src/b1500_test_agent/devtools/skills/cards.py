"""Test cards: family folders, the ten sections, the frontmatter link graph (recipes, family, modules, routes,
bring-up stage, knowledge, manual, runbooks, status), the section-4 parameter table and example plan (validated on
the simulator with ``B1500Service.validate_plan``), and the recipe side of the card graph (every runnable recipe has
a card)."""


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
from b1500_test_agent.devtools.skills.citations import CANONICAL
from b1500_test_agent.devtools.skills.common import (
    CARD_SECTIONS,
    CARDLESS_RECIPES,
    CARDS_DIR,
    DEBUG_SKILL,
    FAMILIES,
    GNDU,
    KNOWLEDGE_DIR,
    README,
    RESERVED_DIR,
    RUNBOOKS_DIR,
    Card,
    CardFrontmatter,
    ExamplePlan,
    ExamplePlanCheck,
    Lint,
    ProblemCode,
    StageFrontmatter,
    model_front,
    validation_messages,
)
from b1500_test_agent.devtools.skills.links import exists_exact
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, norm_title
from b1500_test_agent.devtools.skills.params import check_param_row, param_rows
from b1500_test_agent.devtools.sync_harness import SOURCE_DIR
from b1500_test_agent.models.recipe import FUNCTION_MODULE_TYPES, Recipe
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.models.routing import STATE_INPUT, SWITCH_STATES
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, Paths
from b1500_test_agent.service import B1500Service

EXAMPLE_PLAN_INFO = frozenset({"yaml", "yml"})
HW_RECORD = "validation/hw/{recipe}.yaml"
"""Repository path of a recipe's reviewed hardware validation record (blueprint v2 7.1); section 10 names it."""


def check_sections(lint: Lint, doc: MarkdownDoc, sections: tuple[str, ...] = CARD_SECTIONS, what: str = "card",
                   code: ProblemCode = "card_sections") -> None:
    """The H2 headings of ``doc`` are exactly ``## 1. <sections[0]>`` ... in order (first deviation reported)."""
    found = [h for h in doc.headings if h.level == 2]
    expected = [f"{i}. {title}" for i, title in enumerate(sections, 1)]
    for index in range(max(len(found), len(expected))):
        have = found[index] if index < len(found) else None
        want = expected[index] if index < len(expected) else None
        if have is not None and want is not None and norm_title(have.text) == norm_title(want):
            continue
        if have is None:
            message = (f"missing H2 section '## {want}' (a {what} has the {len(sections)} numbered sections of the "
                       "template)")
        elif want is None:
            message = (f"unexpected H2 section '## {have.text}' after section {len(sections)} (use H3 inside a "
                       "section)")
        else:
            message = f"H2 section {index + 1} is '## {have.text}'; expected '## {want}' (template order)"
        lint.add(code, doc.path, message, have.line if have else None)
        return


def section_text(doc: MarkdownDoc, number: int, sections: tuple[str, ...] = CARD_SECTIONS) -> str | None:
    """Body of the numbered H2 section ``number`` (1-based), ``None`` when it is missing."""
    span = doc.section(f"{number}. {sections[number - 1]}")
    return None if span is None else "\n".join(doc.lines[span[0]:span[1] - 1])


def recipe_modules(recipe: Recipe) -> set[str] | None:
    """Module types (and ``GNDU``) the roles of ``recipe`` may use: each role's ``module_types``, or every type
    that fits its function when it names none, plus ``GNDU`` when a role allows it. ``None`` for a recipe without
    roles (system operations act on the mainframe and every installed module)."""
    if not recipe.roles:
        return None
    allowed: set[str] = set()
    for role in recipe.roles.values():
        allowed |= set(role.module_types) or set(FUNCTION_MODULE_TYPES[role.function])
        if role.allow_gndu:
            allowed.add(GNDU)
    return allowed


def recipe_routes(recipe: Recipe, kind: object = None) -> set[str]:
    """Routes (``<switch kind>:<state>``) a recipe can set: every non-rest state of every switch kind whose input is
    the resource (``smu``, ``pgu``, ``cmu``, ``wgfmu``) behind one of its roles, plus the routes its measurement kind
    sets by itself (``kind.switch_routes(recipe)`` when the kind has it, e.g. the route-only selector check of
    ``spgu_pulse``, WP9.2)."""
    resources = {role.resource for role in recipe.roles.values()}
    routes = {f"{kind}:{state}" for kind, states in SWITCH_STATES.items() for state in sorted(states)
              if state != "open" and STATE_INPUT[state] in resources}
    own = getattr(kind, "switch_routes", None)
    if callable(own):
        routes |= set(own(recipe))
    return routes


def card_folder_problem(entry_dir: Path, path: Path) -> str | None:
    """Why ``path`` is not at ``cards/<family>/<id>.md`` (``None`` when it is)."""
    rel = path.relative_to(entry_dir / CARDS_DIR)
    if len(rel.parts) == 2 and rel.parts[0] in FAMILIES:
        return None
    if len(rel.parts) == 1:
        return f"card outside a family folder: move it to {CARDS_DIR}/<family>/{path.name} ({', '.join(FAMILIES)})"
    return (f"card in {CARDS_DIR}/{'/'.join(rel.parts[:-1])}/, which is not a family folder "
            f"({', '.join(FAMILIES)})")


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


def check_card(lint: Lint, path: Path, registry: RecipeRegistry, entry_dir: Path, runbooks: set[str],
               stages: dict[str, StageFrontmatter], catalog_ids: set[str] | None) -> Card | None:
    """All checks of one card; ``stages`` = the parsed stage files by stage id, ``catalog_ids`` = the manual
    catalog's document ids (``None`` without a catalog)."""
    doc = lint.doc(path)
    if doc is None:
        return None
    folder_problem = card_folder_problem(entry_dir, path)
    if folder_problem:
        lint.add("card_layout", path, folder_problem, 1)
    check_budget(lint, doc, CARD_MAX_LINES, "card")
    check_sections(lint, doc)
    front: CardFrontmatter | None = model_front(lint, doc, CardFrontmatter, "test card")
    if front is None:
        return None
    if front.id != path.stem:
        lint.add("frontmatter", path, f"id {front.id!r} must equal the file name {path.stem!r}", 1)
    if folder_problem is None and front.family != path.parent.name:
        lint.add("card_layout", path, f"family {front.family} differs from the card's folder "
                                      f"{CARDS_DIR}/{path.parent.name}/ (family = folder)", 1)
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
        if recipe.family != front.family:
            lint.add("card_recipe", path, f"recipe {recipe_id} has family {recipe.family}, the card {front.family} "
                                          "(a card holds recipes of its own family)", 1)
        effective = registry.effective_status(recipe_id, "sim")
        if effective != front.status:
            lint.add("card_status", path, f"status {front.status} differs from recipe {recipe_id}'s effective "
                                          f"status on the simulator ({effective})", 1)
    check_device_types(lint, path, front, recipes)
    check_modules_and_routes(lint, path, front, recipes, registry)
    check_stage(lint, path, front, recipes, stages)
    check_manual(lint, path, front, catalog_ids)
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
    check_section_contents(lint, doc, [r.id for r in recipes])
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
        unknown = [r for r in row.recipes if r not in front.recipes]
        if unknown:
            lint.add("param_table", path, f"param {row.name!r} names {unknown}, which are not recipes of the card "
                                          f"{front.recipes}", row.line)
            continue
        scope = [r for r in recipes if not row.recipes or r.id in row.recipes]
        owners = [(r.id, r.params[row.name]) for r in scope if row.name in r.params]
        if not owners:
            if scope:
                lint.add("param_table", path, f"param {row.name!r} is not a parameter of "
                                              f"{', '.join(r.id for r in scope)}", row.line)
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


def check_device_types(lint: Lint, path: Path, front: CardFrontmatter, recipes: list[Recipe]) -> None:
    """Card ``device_types`` ⊆ the recipes' device types; empty only when the recipes name none."""
    typed = [r for r in recipes if r.device_types]
    if typed and len(typed) == len(recipes):
        allowed = {t for r in recipes for t in r.device_types}
        extra = [t for t in front.device_types if t not in allowed]
        if extra:
            lint.add("card_recipe", path, f"device_types {extra} are not device types of the card's recipes "
                                          f"({sorted(allowed)})", 1)
    if typed and not front.device_types:
        lint.add("frontmatter", path, "device_types is empty, but the card's recipes name device types "
                                      f"({sorted({t for r in typed for t in r.device_types})})", 1)


def check_modules_and_routes(lint: Lint, path: Path, front: CardFrontmatter, recipes: list[Recipe],
                             registry: RecipeRegistry | None = None) -> None:
    """``modules`` ⊆ the module types the recipes' roles may use (empty only for roleless recipes); ``routes`` ⊆
    the routes the roles' resources can need or the recipes' kinds set (``recipe_routes``)."""
    if not recipes:
        return
    per_recipe = [recipe_modules(r) for r in recipes]
    if any(m is None for m in per_recipe):
        allowed_modules = None  # a roleless (system) recipe may use any module
    else:
        allowed_modules = set().union(*(m for m in per_recipe if m is not None))
    if allowed_modules is not None:
        extra = [m for m in front.modules if m not in allowed_modules]
        if extra:
            lint.add("card_modules", path, f"modules {extra} are not module types of the card's recipe roles "
                                           f"({', '.join(sorted(allowed_modules))})", 1)
        if not front.modules:
            lint.add("card_modules", path, "modules is empty; list the module types the card's recipes use "
                                           "(empty only for recipes without roles)", 1)
    kinds = registry.kinds if registry is not None else {}
    allowed_routes = set().union(*(recipe_routes(r, kinds.get(r.kind)) for r in recipes))
    extra_routes = [r for r in front.routes if r not in allowed_routes]
    if extra_routes:
        shown = ", ".join(sorted(allowed_routes)) or "none: the roles use no switchable resource"
        lint.add("card_routes", path, f"routes {extra_routes} are not switch routes of the card's recipe roles "
                                      f"({shown})", 1)


def check_stage(lint: Lint, path: Path, front: CardFrontmatter, recipes: list[Recipe],
                stages: dict[str, StageFrontmatter]) -> None:
    """When the card's bring-up stage file exists, it runs every recipe of the card (a missing stage file is a note
    of the lint run, see ``lint.py``)."""
    stage = stages.get(front.bringup_stage)
    if stage is None:
        return
    missing = [r.id for r in recipes if r.id not in stage.recipes]
    if missing:
        lint.add("card_stage", path, f"bring-up stage {front.bringup_stage} does not run {missing}: add them to the "
                                     "stage file's recipes (or name the stage that does)", 1)


def check_manual(lint: Lint, path: Path, front: CardFrontmatter, catalog_ids: set[str] | None) -> None:
    """``manual`` entries are canonical citations (``PG p433 (4-115)``) of catalog documents; pages, labels and
    keywords are checked by the citation lint, which reads the whole file."""
    for entry in front.manual:
        match = CANONICAL.fullmatch(entry)
        if match is None:
            lint.add("frontmatter", path, f"manual entry {entry!r} is not a canonical citation such as "
                                          "'PG p433 (4-115) \"ERSSP\"' (doc id, PDF page, printed label, keyword)", 1)
        elif catalog_ids is not None and match.group("doc") not in catalog_ids:
            lint.add("citation", path, f"manual entry {entry!r}: unknown manual id {match.group('doc')} (catalog: "
                                       f"{', '.join(sorted(catalog_ids))})", 1)


def check_section_contents(lint: Lint, doc: MarkdownDoc, recipe_ids: list[str]) -> None:
    """Section 2 states the routes (``Routes: none`` without a switch); section 10 names the hardware record
    ``validation/hw/<recipe>.yaml`` of each registered card recipe (blueprint v2 6.3)."""
    wiring = section_text(doc, 2)
    if wiring is not None and "route" not in wiring.casefold():
        span = doc.section(f"2. {CARD_SECTIONS[1]}")
        lint.add("card_sections", doc.path, "section 2 does not state the routes per phase (write 'Routes: none' "
                                            "when no switch is involved)", span[0] if span else None)
    record = section_text(doc, 10)
    if record is not None:
        missing = [r for r in recipe_ids if HW_RECORD.format(recipe=r) not in record]
        if missing:
            span = doc.section(f"10. {CARD_SECTIONS[9]}")
            lint.add("card_sections", doc.path, "section 10 does not name the hardware record of "
                     + ", ".join(f"{r} (`{HW_RECORD.format(recipe=r)}`)" for r in missing),
                     span[0] if span else None)


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
    """Every card file under ``cards/`` (any depth): Markdown files except ``_*.md`` (template), ``README.md``
    (generated index) and the v1 ``reserved/`` folder; misplaced cards are found too (``card_layout``)."""
    folder = entry_dir / CARDS_DIR
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.rglob("*.md"))
            if not p.name.startswith("_") and p.name != README and not p.is_symlink()
            and p.relative_to(folder).parts[0] != RESERVED_DIR]


def check_recipes(lint: Lint, registry: RecipeRegistry, entry_dir: Path) -> None:
    """Recipe side of the graph: analysis methods exist; every runnable recipe has a card (reserved ones exempt
    until WP11.2, ``CARDLESS_RECIPES`` by design); a recipe ``card`` is a card in a family folder that lists it."""
    cards_dir = entry_dir / CARDS_DIR
    for recipe_id in registry.ids():
        entry = registry.entry(recipe_id)
        recipe = entry.recipe
        for index, spec in enumerate(recipe.analysis_defaults):
            if spec.method not in ANALYSIS_METHODS:
                lint.add("analysis_method", entry.source, f"analysis_defaults[{index}]: method {spec.method!r} is "
                                                          "not in ANALYSIS_METHODS")
        if recipe.card is None:
            if recipe.status != "not_implemented" and recipe_id not in CARDLESS_RECIPES:
                lint.add("recipe_card", entry.source, f"runnable recipe {recipe_id} has no card: write "
                                                      f"{lint.rel(cards_dir)}/{recipe.family}/<card>.md from the "
                                                      "template and set the recipe's card")
            continue
        card_path = Path(os.path.normpath(lint.root / recipe.card))
        rel = card_path.relative_to(cards_dir).parts if card_path.is_relative_to(cards_dir) else ()
        if len(rel) != 2 or rel[0] not in FAMILIES or card_path.name.startswith("_") or card_path.suffix != ".md":
            lint.add("recipe_card", entry.source, f"card {recipe.card!r} is not a test card in a family folder "
                                                  f"{lint.rel(cards_dir)}/<family>/")
            continue
        if not exists_exact(lint.root, card_path) or not card_path.is_file():
            lint.add("recipe_card", entry.source, f"card {recipe.card} does not exist (dangling card)")
            continue
        doc = lint.doc(card_path)
        listed = doc.front.get("recipes") if doc is not None and isinstance(doc.front, dict) else None
        if not isinstance(listed, list) or recipe_id not in listed:
            lint.add("recipe_card", entry.source, f"card {recipe.card} does not list {recipe_id} in its recipes")


