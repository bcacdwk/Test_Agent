"""``b1500 dev recipe-check``: load ``recipes/`` against the measurement kinds and list every problem (blueprint 5.3).

Clean (exit 0) iff ``RecipeRegistry.problems()`` is empty; the report also lists each recipe with its own status and
its effective status on both backends.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.common import StrictModel, ValidationStatus
from b1500_test_agent.paths import Paths


class RecipeRow(StrictModel):
    id: str
    kind: str
    status: ValidationStatus
    effective: dict[str, ValidationStatus]
    source: str
    card: str | None


class RecipeCheckReport(StrictModel):
    ok: bool
    root: str
    recipes: list[RecipeRow] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


def check_recipes(root: Path | None = None, *, repo_root: Path | None = None) -> RecipeCheckReport:
    """Load the recipe tree (default: ``recipes/`` of the located repository) and report its problems."""
    if root is None:
        paths = Paths.from_env()
        root, repo_root = paths.recipes_dir, paths.repo_root
    registry = RecipeRegistry.load(root, repo_root=repo_root)
    rows = []
    for recipe_id in registry.ids():
        recipe = registry.get(recipe_id)
        rows.append(RecipeRow(id=recipe.id, kind=recipe.kind, status=recipe.status, source=registry.source(recipe_id),
                              card=recipe.card, effective={backend: registry.effective_status(recipe_id, backend)
                                                           for backend in ("sim", "visa")}))
    problems = registry.problems()
    return RecipeCheckReport(ok=not problems, root=Path(root).as_posix(), recipes=rows, problems=problems)


def format_report(report: RecipeCheckReport) -> str:
    """Human-readable report: verdict, one line per recipe, problems."""
    lines = [f"recipes: {'clean' if report.ok else 'PROBLEMS'} ({len(report.recipes)} loaded from {report.root})"]
    if report.recipes:
        width = max(len(r.id) for r in report.recipes)
        kind_width = max(len(r.kind) for r in report.recipes)
        for row in report.recipes:
            lines.append(f"  {row.id:<{width}}  {row.kind:<{kind_width}}  {row.status:<15}  "
                         f"sim:{row.effective['sim']}  visa:{row.effective['visa']}")
    if report.problems:
        lines.append("problems:")
        lines += [f"  - {problem}" for problem in report.problems]
    return "\n".join(lines)
