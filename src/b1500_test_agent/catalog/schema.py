"""Recipe files and the data passed between planner, measurement kinds and executor (blueprint 2.6).

The recipe schema itself is ``models.recipe.Recipe`` (shared with the rules and the service); this module turns a
YAML file under ``recipes/`` into a ``Recipe`` (``sha256`` = digest of the raw file bytes, computed here and never
written in the file) and defines the kind interface's value types:

- ``CompiledKindPlan``: what ``MeasurementKind.compile`` returns (pure): the per-channel envelope, the size
  estimate, the exact FLEX preview and the kind's JSON program that ``acquire`` executes.
- ``RawAcquisition``: what ``MeasurementKind.acquire`` returns: the raw measurement blocks (each one was already
  handed to the run folder before parsing) and kind-specific result facts.

Recipe ``$param`` references are only resolved here and in the kinds (``setting_value``); there is no other
expression language (decision 14).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import JsonValue, ValidationError

from b1500_test_agent.config import load_yaml
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import JsonScalar
from b1500_test_agent.models.plan import CompiledEnvelope, Estimate
from b1500_test_agent.models.recipe import (
    PARAM_REF,
    AnalysisSpec,
    ParamSpec,
    QualityCriteria,
    Recipe,
    RecipeSummary,
    RoleSpec,
)

__all__ = [
    "AnalysisSpec",
    "CompileError",
    "CompiledKindPlan",
    "ParamSpec",
    "QualityCriteria",
    "RawAcquisition",
    "Recipe",
    "RecipeFileError",
    "RecipeSummary",
    "RoleSpec",
    "parse_recipe",
    "recipe_sha256",
    "setting_value",
]

RECIPE_SUFFIX = ".yaml"


class CompileError(InvalidInputError):
    """A measurement kind cannot compile the request (e.g. a role function the kind does not support)."""


class RecipeFileError(ValueError):
    """A recipe file does not parse or validate; ``problems`` lists every reason (one line each)."""

    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = list(problems)
        super().__init__(f"{source}: " + "; ".join(self.problems))


@dataclass(frozen=True)
class CompiledKindPlan:
    """Result of ``MeasurementKind.compile``: envelope, estimate, FLEX preview and program (JSON, hashed)."""

    envelope: CompiledEnvelope
    estimate: Estimate
    flex_preview: list[str] = field(default_factory=list)
    program: dict[str, JsonValue] = field(default_factory=dict)


@dataclass
class RawAcquisition:
    """Result of ``MeasurementKind.acquire``: raw measurement blocks in read order (each already saved to the run
    folder as ``raw/block-NNN.txt`` by the transaction before parsing) and kind-specific result facts."""

    blocks: list[RawBlock] = field(default_factory=list)
    kind_result: dict[str, JsonScalar] = field(default_factory=dict)
    ok: bool = True
    """False when the kind's own result says the operation failed (e.g. a self-test failure code)."""
    message: str = ""


def recipe_sha256(raw: bytes) -> str:
    """Recipe digest: sha256 of the raw file bytes (any edit, comments included, gives a new digest)."""
    return hashlib.sha256(raw).hexdigest()


def parse_recipe(raw: bytes, *, source: str) -> Recipe:
    """Parse one recipe file (UTF-8 YAML) into a ``Recipe`` with ``sha256`` computed from ``raw``.

    Raises:
        RecipeFileError: On YAML errors, a non-mapping top level, a ``sha256`` key in the file, or schema errors
            (one problem per field, including ``$param`` references that do not resolve).
    """
    try:
        data = load_yaml(raw)
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise RecipeFileError(source, [f"not valid UTF-8 YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise RecipeFileError(source, ["the top level must be a mapping"])
    if "sha256" in data:
        raise RecipeFileError(source, ["sha256 is computed at load and must not be written in the file"])
    try:
        return Recipe.model_validate({**data, "sha256": recipe_sha256(raw)})
    except ValidationError as exc:
        problems = []
        for err in exc.errors(include_url=False, include_input=False):
            where = ".".join(str(part) for part in err["loc"]) or "recipe"
            problems.append(f"{where}: {err['msg']}")
        raise RecipeFileError(source, problems) from None


def setting_value(role: RoleSpec, key: str, params: dict[str, Quantity], default: Any = None) -> Any:
    """Role setting ``key`` with a ``$param`` reference resolved to the parameter's value (``default`` when the
    setting is absent or the parameter has no value)."""
    raw = role.settings.get(key)
    if raw is None:
        return default
    if isinstance(raw, str):
        match = PARAM_REF.match(raw)
        if match:
            quantity = params.get(match.group(1))
            return default if quantity is None else quantity.value
    return raw
