"""``RecipeRegistry``: the recipes under ``recipes/`` checked against the measurement kinds (blueprint 2.6).

Layout: ``recipes/<group>/<name>.yaml`` holds recipe ``<group>.<name>`` (``mosfet/idvg.yaml`` = ``mosfet.idvg``);
``recipes/waveforms/`` is the waveform library of ``file`` parameters. The v1 reserved slots (``recipes/reserved/``)
are gone since WP11.2: every slot was implemented or retired (blueprint v2 3, 9).

``problems()`` lists everything wrong with the tree, one line each (``b1500 dev recipe-check`` exits 0 iff it is
empty): schema errors (including ``$param`` references that do not resolve), file name ≠ recipe id, duplicate ids,
unknown kinds, dangling card paths, unknown analysis methods (or methods/options that do not apply to the recipe),
a validated status on a kind that has no simulator code path, and ``file`` parameter defaults that do not name a
readable CSV of at most ``FILE_PARAM_MAX_BYTES`` in the waveform library (``recipes/waveforms/``). Recipes with
schema errors are left out of the registry; the others load even when the tree has other problems.

``runnable(recipe_id, backend)``: the recipe's kind is registered and has a code path for ``backend``. The status
(``draft · sim_validated · hw_validated``, blueprint v2 7.2) is always the recipe's own; R-REC-01 blocks a plan whose
recipe is not runnable on the backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.catalog.kinds import MeasurementKind, default_kinds, implemented_on
from b1500_test_agent.catalog.schema import RECIPE_SUFFIX, RecipeFileError, parse_recipe, recipe_sha256
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.recipe import FILE_PARAM_MAX_BYTES, Recipe, RecipeSummary

WAVEFORMS_DIR = "waveforms"
"""The committed waveform library ``recipes/waveforms/`` (``file`` parameters ``recipes/waveforms/<name>.csv``)."""


class UnknownRecipeError(InvalidInputError):
    """No recipe with this id is registered (or its file does not validate)."""


@dataclass(frozen=True)
class RecipeEntry:
    """A loaded recipe and its file (``source`` is repository-relative, POSIX separators)."""

    recipe: Recipe
    path: Path
    source: str


def _display(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _fingerprint(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): recipe_sha256(p.read_bytes())
            for p in sorted(root.rglob(f"*{RECIPE_SUFFIX}")) if p.is_file()}


class RecipeRegistry:
    """Recipes by id plus the problems found while loading (see the module docstring)."""

    def __init__(self, root: Path, kinds: Mapping[str, MeasurementKind], repo_root: Path,
                 entries: dict[str, RecipeEntry], problems: list[str], fingerprint: dict[str, str]) -> None:
        self.root = root
        self.kinds = dict(kinds)
        self.repo_root = repo_root
        self._entries = entries
        self._problems = problems
        self._fingerprint = fingerprint

    @classmethod
    def load(cls, root: Path, kinds: Mapping[str, MeasurementKind] | None = None, *,
             repo_root: Path | None = None) -> RecipeRegistry:
        """Load every ``*.yaml`` under ``root`` (default kinds: ``default_kinds()``; card paths resolve against
        ``repo_root``, default ``root.parent``). Never raises for bad recipe files: see ``problems()``."""
        root = Path(root)
        kinds = default_kinds() if kinds is None else kinds
        repo_root = Path(repo_root) if repo_root is not None else root.parent
        entries: dict[str, RecipeEntry] = {}
        problems: list[str] = []
        if not root.is_dir():
            problems.append(f"{_display(root, repo_root)}: recipe directory not found")
        files = sorted(root.rglob(f"*{RECIPE_SUFFIX}")) if root.is_dir() else []
        for path in files:
            source = _display(path, repo_root)
            try:
                recipe = parse_recipe(path.read_bytes(), source=source)
            except OSError as exc:
                problems.append(f"{source}: cannot read: {exc}")
                continue
            except RecipeFileError as exc:
                problems.extend(f"{source}: {problem}" for problem in exc.problems)
                continue
            problems.extend(f"{source}: {p}" for p in _check(recipe, path, root, repo_root, kinds))
            if recipe.id in entries:
                problems.append(f"{source}: duplicate recipe id {recipe.id} (also {entries[recipe.id].source})")
                continue
            entries[recipe.id] = RecipeEntry(recipe=recipe, path=path, source=source)
        return cls(root, kinds, repo_root, entries, problems, _fingerprint(root))

    def reload_if_changed(self) -> RecipeRegistry:
        """This registry, or a freshly loaded one when any recipe file was added, removed or edited."""
        if _fingerprint(self.root) == self._fingerprint:
            return self
        return RecipeRegistry.load(self.root, self.kinds, repo_root=self.repo_root)

    # -- queries ---------------------------------------------------------------------------------------------------

    def problems(self) -> list[str]:
        """Every problem of the recipe tree (empty = clean)."""
        return list(self._problems)

    def ids(self) -> list[str]:
        return sorted(self._entries)

    def get(self, recipe_id: str) -> Recipe:
        """The recipe ``recipe_id``; raises ``UnknownRecipeError`` (code ``invalid_input``)."""
        return self.entry(recipe_id).recipe

    def entry(self, recipe_id: str) -> RecipeEntry:
        entry = self._entries.get(recipe_id)
        if entry is None:
            raise UnknownRecipeError(f"unknown recipe {recipe_id!r}; known: {', '.join(self.ids()) or 'none'}")
        return entry

    def source(self, recipe_id: str) -> str:
        """Repository-relative path of the recipe file (used in rule finding sources)."""
        return self.entry(recipe_id).source

    def kind(self, recipe_id: str) -> MeasurementKind | None:
        """The measurement kind of the recipe (``None`` when the kind id is unknown)."""
        return self.kinds.get(self.get(recipe_id).kind)

    def runnable(self, recipe_id: str, backend: Backend) -> bool:
        """True when the recipe's kind is registered and has a code path for ``backend`` (R-REC-01 blocks the plans
        of a recipe that is not)."""
        return implemented_on(self.kinds.get(self.get(recipe_id).kind), backend)

    def list(self, *, device_type: str | None = None) -> list[RecipeSummary]:
        """Index entries sorted by id; ``device_type`` filters recipes that name it (recipes without device types,
        e.g. ``generic.*`` and ``system.*``, always match)."""
        out = []
        for recipe_id in self.ids():
            recipe = self.get(recipe_id)
            if device_type is not None and recipe.device_types and device_type not in recipe.device_types:
                continue
            out.append(RecipeSummary(id=recipe.id, title=recipe.title, family=recipe.family, kind=recipe.kind,
                                     status=recipe.status, card=recipe.card,
                                     device_types=list(recipe.device_types)))
        return out


def _check(recipe: Recipe, path: Path, root: Path, repo_root: Path,
           kinds: Mapping[str, MeasurementKind]) -> list[str]:
    """Problems of one schema-valid recipe (see the module docstring)."""
    problems: list[str] = []
    rel = path.relative_to(root)
    expected = ".".join([*rel.parent.parts, path.stem])
    if recipe.id != expected:
        problems.append(f"recipe id {recipe.id} does not match its file name (expected {expected})")
    kind = kinds.get(recipe.kind)
    if kind is None:
        problems.append(f"unknown kind {recipe.kind!r}; known: {', '.join(sorted(kinds))}")
    elif recipe.status in ("sim_validated", "hw_validated") and not implemented_on(kind, "sim"):
        problems.append(f"status {recipe.status} but kind {recipe.kind} has no simulator code path")
    if recipe.card is not None:
        card = Path(recipe.card)
        if card.is_absolute() or ".." in card.parts:
            problems.append(f"card {recipe.card!r} must be a repository-relative path")
        elif not (repo_root / card).is_file():
            problems.append(f"card {recipe.card} does not exist (dangling card path)")
    for name, param in recipe.params.items():
        if param.type == "file" and isinstance(param.default, str):
            library = root / WAVEFORMS_DIR / param.default.removeprefix(f"recipes/{WAVEFORMS_DIR}/")
            if not library.is_file():
                problems.append(f"params.{name}: default {param.default} does not exist in the waveform library")
            elif library.stat().st_size > FILE_PARAM_MAX_BYTES:
                problems.append(f"params.{name}: default {param.default} exceeds {FILE_PARAM_MAX_BYTES} bytes")
    for index, spec in enumerate(recipe.analysis_defaults):
        method = ANALYSIS_METHODS.get(spec.method)
        where = f"analysis_defaults[{index}]"
        if method is None:
            problems.append(f"{where}: unknown analysis method {spec.method!r}")
            continue
        if not method.applies_to(recipe.id, recipe.kind):
            problems.append(f"{where}: {spec.method} does not apply to recipe {recipe.id} (kind {recipe.kind})")
        unknown = sorted(set(spec.options) - set(method.options))
        if unknown:
            problems.append(f"{where}: {spec.method} has no option(s) {unknown}")
    return problems
