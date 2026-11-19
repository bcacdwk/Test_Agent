"""Shared pieces of the skill lint: layout names, the schema of skill/card/knowledge frontmatter and example plans,
the report models, the per-run ``Lint`` context (problems, notes, parsed-document cache) and frontmatter helpers. The
bring-up stage list, the stage-file frontmatter and the record keys live in ``models/validation.py`` (shared with
``b1500 bringup``) and are re-exported here."""


from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Final, Literal, get_args

from pydantic import Field, JsonValue, ValidationError, model_validator

from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, parse_markdown
from b1500_test_agent.models.analysis import Identifier
from b1500_test_agent.models.common import ConfigName, StrictModel
from b1500_test_agent.models.recipe import RecipeFamily, RecipeId
from b1500_test_agent.models.validation import (  # noqa: F401 - re-exported: the stage schema lives in models
    RECORD_KEYS,
    STAGES,
    StageFrontmatter,
    StageId,
)

ENTRY_SKILL = "b1500-test"
DEBUG_SKILL = "b1500-debug"
BRINGUP_SKILL = "b1500-bringup"
CARDS_DIR = "cards"
KNOWLEDGE_DIR = "knowledge"
RUNBOOKS_DIR = "runbooks"
STAGES_DIR = "stages"
RECORDS_DIR = "records"
README = "README.md"
TEMPLATE = "_TEMPLATE.md"
RECORD_TEMPLATE = "_TEMPLATE.yaml"
RESERVED_DIR = "reserved"
"""``cards/reserved/README.md``: the v1 reserved-slot list (no card), kept until WP11.2 deletes it."""

MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 300

FAMILIES: Final[tuple[str, ...]] = get_args(RecipeFamily)
"""Card family folders under ``cards/`` (= ``Recipe.family``), in index order (blueprint v2 6.3)."""

CARDLESS_RECIPES: Final[dict[str, str]] = {
    "generic.smu_staircase": "ad-hoc fallback of the entry skill: used only when no card fits and the human asked "
                             "for it (blueprint v2 6.3 gives it no card)",
}
"""Runnable recipes that deliberately have no card, with the reason (shown in the generated index and as a lint
note). Every other runnable recipe needs a card; reserved (``not_implemented``) recipes are exempt until WP11.2."""

GNDU = "GNDU"
CardModule = Literal["HPSMU", "MPSMU", "HRSMU", "MCSMU", "HCSMU", "HVSMU", "MFCMU", "HVSPGU", "WGFMU", "GNDU"]
"""A module type a card needs (``ModuleType`` or the ground unit ``GNDU``; a test keeps it equal to
``ModuleType`` + ``GNDU``)."""

RouteToken = Annotated[str, Field(pattern=r"^(selector_16440a|scuu|asu|rsu):(smu|pgu|pgu_open|cmu|wgfmu)$")]
"""A route a card's measurement needs: ``<switch kind>:<state>``, e.g. ``selector_16440a:pgu`` (``open`` is every
switch's rest state, never a need)."""

STAGE_SECTIONS: tuple[str, ...] = (
    "Preconditions",
    "Physical steps (human)",
    "Agent steps",
    "Expected values",
    "Abort criteria",
    "Record",
)
"""The six H2 sections of a bring-up stage file, numbered ``## 1. ...`` to ``## 6. ...`` (blueprint v2 6.1)."""

CARD_SECTIONS: tuple[str, ...] = (
    "Purpose and applicable devices",
    "Wiring, pin map, modules",
    "Pre-run checklist",
    "Recipe and parameters",
    "Limits and confirmation",
    "Quality criteria",
    "Analysis method",
    "Expected result shape",
    "Common failures → debug",
    "Validation record",
)
"""The ten H2 sections of a test card, numbered ``## 1. ...`` to ``## 10. ...`` (blueprint 6.3)."""

ProblemCode = Literal[
    "skill_layout", "generated_marker", "frontmatter", "budget", "link", "anchor", "card_sections", "card_recipe",
    "recipe_card", "card_knowledge", "card_debug", "analysis_method", "card_status", "param_table", "param_range",
    "example_plan", "card_confirmation", "citation", "card_layout", "card_modules", "card_routes", "card_stage",
    "card_index", "stage", "command",
]

_KEBAB = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
NonEmptyStr = Annotated[str, Field(min_length=1)]
KebabId = Annotated[str, Field(pattern=_KEBAB, max_length=MAX_NAME_CHARS)]
KnowledgeRef = Annotated[str, Field(pattern=r"^knowledge/[^#\s]+\.md#[^#\s]+$")]
"""A card ``knowledge`` entry: skill-relative Markdown file + ``#`` + heading id."""


# == Schemas ==========================================================================================================


class SkillFrontmatter(StrictModel):
    """``SKILL.md`` frontmatter (Codex needs ``name`` and ``description``; both harnesses list the description)."""

    name: KebabId
    description: Annotated[str, Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)]
    license: str | None = None
    metadata: dict[str, str] | None = None


class CardFrontmatter(StrictModel):
    """Test-card frontmatter v2 (blueprint v2 6.1, 6.3): v1 fields plus ``family`` (= the card's folder),
    ``intent`` (keywords of the generated index), ``modules`` (module types, checked against the recipes' roles),
    ``routes`` (switch routes, checked against the roles' resources), ``bringup_stage`` (7.4 stage id) and
    ``manual`` (canonical manual citations, checked by the citation lint). ``device_types`` and ``modules`` may be
    empty only for recipes without device types / roles (system recipes)."""

    id: KebabId
    title: NonEmptyStr
    family: RecipeFamily
    intent: Annotated[list[NonEmptyStr], Field(min_length=1, max_length=12)]
    recipes: Annotated[list[RecipeId], Field(min_length=1)]
    device_types: list[Identifier]
    modules: list[CardModule]
    routes: list[RouteToken]
    bringup_stage: StageId
    status: Literal["draft", "sim_validated", "hw_validated"]
    confirmation: Literal["never", "conditional", "always"]
    knowledge: list[KnowledgeRef]
    manual: list[NonEmptyStr]
    debug: list[KebabId]
    sources: Annotated[list[NonEmptyStr], Field(min_length=1)]
    version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _unique(self) -> CardFrontmatter:
        for name in ("intent", "recipes", "device_types", "modules", "routes", "manual"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} lists an entry twice")
        return self


class KnowledgeFrontmatter(StrictModel):
    """Knowledge-file frontmatter (blueprint 6.5); ``reviewed`` only by a human, with a review date."""

    domain: NonEmptyStr
    maturity: Literal["seed", "draft", "reviewed"]
    sources: Annotated[list[NonEmptyStr], Field(min_length=1)]
    last_reviewed: date | None

    @model_validator(mode="after")
    def _reviewed_has_date(self) -> KnowledgeFrontmatter:
        if self.maturity == "reviewed" and self.last_reviewed is None:
            raise ValueError("maturity reviewed needs last_reviewed (the date a human reviewed the file)")
        return self


class ExamplePlan(StrictModel):
    """The example plan of a card (fenced YAML block in section 4); see the module docstring."""

    recipe_id: RecipeId
    params: dict[str, JsonValue] = Field(default_factory=dict)
    pin_map: ConfigName
    dut_profile: ConfigName | None = None
    sim_scenario: ConfigName
    label: str | None = None


# == Report ===========================================================================================================


class LintProblem(StrictModel):
    """One problem: ``file`` is root-relative (POSIX), ``line`` 1-based when known."""

    code: ProblemCode
    file: str
    line: int | None = None
    message: str


class ExamplePlanCheck(StrictModel):
    """Outcome of one card's example plan on the simulator."""

    card: str
    recipe_id: str
    sim_scenario: str
    status: str
    tier: str | None = None
    plan_id: str | None = None


class AlwaysLoadedBudget(StrictModel):
    """Tokens of the always-loaded text (blueprint 5.2 second budget)."""

    method: str
    warning: str | None = None
    limit: int
    total: int
    parts: dict[str, int]


class LintReport(StrictModel):
    """All findings of one lint run; ``ok`` iff ``problems`` is empty."""

    ok: bool
    root: str
    skills: list[str] = Field(default_factory=list)
    cards: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    runbooks: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    example_plans: list[ExamplePlanCheck] = Field(default_factory=list)
    always_loaded: AlwaysLoadedBudget | None = None
    notes: list[str] = Field(default_factory=list)
    problems: list[LintProblem] = Field(default_factory=list)

# == Lint =============================================================================================================


@dataclass
class Card:
    doc: MarkdownDoc
    front: CardFrontmatter
    example: ExamplePlan | None = None
    example_line: int | None = None


class Lint:
    """State of one lint run."""

    def __init__(self, root: Path, recipes_dir: Path, config_dir: Path) -> None:
        self.root = root
        self.recipes_dir = recipes_dir
        self.config_dir = config_dir
        self.problems: list[LintProblem] = []
        self.notes: list[str] = []
        self.docs: dict[Path, MarkdownDoc] = {}

    def add(self, code: ProblemCode, file: str | Path, message: str, line: int | None = None) -> None:
        rel = file if isinstance(file, str) else self.rel(file)
        self.problems.append(LintProblem(code=code, file=rel, line=line, message=message))

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def doc(self, path: Path) -> MarkdownDoc | None:
        """The parsed Markdown file at ``path`` (cached); ``None`` (with a problem) when unreadable."""
        if path not in self.docs:
            try:
                self.docs[path] = parse_markdown(path, self.rel(path))
            except UnicodeDecodeError as exc:
                self.add("skill_layout", path, f"not UTF-8 ({exc.reason} at byte {exc.start})")
                return None
            except OSError as exc:
                self.add("skill_layout", path, f"cannot read: {exc}")
                return None
        return self.docs[path]


def validation_messages(exc: ValidationError, prefix: str = "") -> list[str]:
    messages = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "frontmatter"
        message = error["msg"]
        if error["type"] == "string_too_long" and isinstance(error.get("input"), str):
            message += f" (has {len(error['input'])})"
        messages.append(f"{prefix}{loc}: {message}")
    return messages


def model_front(lint: Lint, doc: MarkdownDoc, model: type[StrictModel], what: str) -> Any:
    if not doc.has_front:
        lint.add("frontmatter", doc.path, f"a {what} starts with YAML frontmatter", 1)
        return None
    if doc.front_error:
        lint.add("frontmatter", doc.path, doc.front_error, 1)
        return None
    if not isinstance(doc.front, dict):
        lint.add("frontmatter", doc.path, "frontmatter must be a mapping", 1)
        return None
    try:
        return model.model_validate(doc.front)
    except ValidationError as exc:
        for message in validation_messages(exc):
            lint.add("frontmatter", doc.path, message, 1)
        return None


