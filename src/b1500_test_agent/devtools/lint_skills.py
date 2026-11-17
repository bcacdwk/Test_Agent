"""``b1500 dev lint-skills``: schema, budgets and link graph of the canonical skills (blueprint 6.1-6.5, 8.1).

Works on any root that has the repository layout (the repository itself or a fixture tree): skills in
``<root>/.agents/skills/``, recipes in ``<root>/recipes/`` and config in ``<root>/config/`` (both overridable). Every
problem is one ``LintProblem`` (code, file, line, message); the command exits 0 iff there is none.

Checks (problem ``code`` in brackets)
-------------------------------------
- Layout [``skill_layout``]: ``.agents/skills/`` exists, holds the entry skill ``b1500-test``, every folder in it has
  a ``SKILL.md``, no symlinks inside a skill (Windows checkouts turn them into text files). Source files never carry
  the generated-copy marker [``generated_marker``] (edit sources, never paste the mirror back).
- ``SKILL.md`` frontmatter [``frontmatter``]: keys ``name`` (= folder name, lowercase-kebab, ≤64 chars) and
  ``description`` (1-300 chars), optional ``license``/``metadata``; nothing else (``allowed-tools`` would pre-approve
  tools and bypass the harness confirmation; ``hooks`` would add hooks).
- Budgets [``budget``]: entry ``SKILL.md`` ≤150 lines and ≤9,000 bytes; ``b1500-debug/SKILL.md`` ≤100 lines;
  ``cards/*.md`` ≤150 lines; ``knowledge/**/*.md`` ≤300 lines; always-loaded text (``AGENTS.md`` + ``CLAUDE.md`` +
  every skill's frontmatter ``description``) ≤2,500 tokens, counted like ``devtools/budget.py`` (tiktoken
  ``o200k_base``; with the chars/3.5 fallback an excess is only a note, because the fallback overestimates).
- Links [``link``, ``anchor``]: every relative Markdown link or image (inline or reference definition, outside code)
  in a skill file resolves, with exact case, to a file or folder inside **that** skill folder; absolute paths are
  refused; ``#anchors`` on Markdown targets (and same-file ``#anchors``) must be heading ids of the target. Heading
  ids follow GitHub: lowercase, characters other than letters, digits, ``-``, ``_`` and spaces dropped, spaces
  become ``-``, repeats get ``-1``, ``-2``; ``<a id="x">`` anchors count too.
- Knowledge files (``b1500-test/knowledge/**/*.md`` except ``README.md``) [``frontmatter``]: ``domain``,
  ``maturity`` (``seed|draft|reviewed``), ``sources`` (≥1), ``last_reviewed`` (date or null; set when reviewed).
- Test cards (``b1500-test/cards/*.md``; ``_*.md`` such as ``_TEMPLATE.md`` and ``README.md`` are not cards):
  frontmatter [``frontmatter``] = ``CardFrontmatter`` (``id`` = file stem, ``title``, ``recipes``, ``device_types``,
  ``modules``, ``status``, ``confirmation``, ``knowledge``, ``debug``, ``sources``, ``version``); the body has exactly
  the ten numbered H2 sections of ``CARD_SECTIONS`` in order (``## 1. Purpose and applicable devices`` ...
  ``## 10. Validation record``; ``->`` may stand for ``→``; H3 inside a section is free) [``card_sections``]; see the
  section-4 contract below. ``cards/_TEMPLATE.md`` has the same ten sections and the card line budget.
- Link graph: card ``recipes`` exist and each recipe's ``card`` points back to the card [``card_recipe``]; every
  recipe ``card`` is an existing card under ``.agents/skills/b1500-test/cards/`` that lists the recipe
  [``recipe_card``]; card ``device_types`` appear in the recipes' ``device_types`` [``card_recipe``]; card
  ``knowledge`` entries ``knowledge/<file>.md#<heading-id>`` exist [``card_knowledge``]; card ``debug`` ids are
  ``b1500-debug/runbooks/<id>.md`` files [``card_debug``]; every recipe ``analysis_defaults`` method exists in
  ``ANALYSIS_METHODS`` [``analysis_method``]; card ``status`` equals each recipe's effective status on the simulator
  [``card_status``].

Card section 4 contract ("Recipe and parameters"; for ``cards/_TEMPLATE.md`` and the cards)
--------------------------------------------------------------------------------------------
1. **Parameter table** [``param_table`` for structure, ``param_range`` for values]: a Markdown table whose first four
   header cells are ``param | default | recommended | recipe range`` (case-insensitive; further columns such as
   ``why | effect`` are free text). One row per parameter; ``param`` is the recipe parameter name (backticks
   allowed) and must belong to one of the card's recipes. Values: a number with an optional SI prefix and the
   parameter's unit (``-1 V``, ``50 mV``, ``1e-6``, ``1 uA``, ``100 kOhm``); intervals as ``low..high`` (also
   ``low … high``, ``low to high``, ``[low, high]``), a unitless low end takes the high end's unit (``20..100 mV``);
   ``-``, ``—``, empty or ``n/a`` mean "none" (``required`` too, for ``default``); enum values are choice names,
   lists separated by ``,``; booleans ``true``/``false``. Rules: ``default`` equals the recipe default (none when the
   recipe parameter is required) and lies inside the recipe range; ``recommended`` lies inside the recipe range
   (enum: each item is a choice); ``recipe range`` equals the recipe ``range`` (enum: the full choice list or none).
2. **Example plan** [``example_plan``]: exactly one fenced ```` ```yaml ```` block in section 4, a mapping with
   ``recipe_id`` (one of the card's ``recipes``), ``params`` (mapping, may be empty), ``pin_map``, ``dut_profile``
   (optional), ``sim_scenario`` (a ``config/sim/scenarios/`` name) and optional ``label``; nothing else. The lint
   validates it with ``B1500Service.validate_plan`` against a temporary copy of the config (``config/local/`` is
   never read) with ``B1500_CONFIG_DIR`` selecting ``sim_scenario`` and a temporary ``B1500_DATA_DIR``: the call must
   succeed with a tier other than ``blocked``; ``confirmation: never`` requires tier ``ok`` and
   ``confirmation: always`` tier ``needs_confirmation`` [``card_confirmation``].
"""

from __future__ import annotations

import math
import os
import posixpath
import re
import shutil
import tempfile
import warnings
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote

import yaml
from pydantic import Field, JsonValue, ValidationError, model_validator

from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.budget import TokenCounter, load_counter
from b1500_test_agent.devtools.sync_harness import (
    GENERATED_LINE,
    SKILL_FILE,
    SOURCE_DIR,
    frontmatter_end,
    normalize_text,
    scan_tree,
    source_skills,
)
from b1500_test_agent.models.analysis import Identifier
from b1500_test_agent.models.common import ConfigName, StrictModel
from b1500_test_agent.models.recipe import ParamSpec, Recipe, RecipeId
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, Paths, find_repo_root
from b1500_test_agent.service import B1500Service

ENTRY_SKILL = "b1500-test"
DEBUG_SKILL = "b1500-debug"
CARDS_DIR = "cards"
KNOWLEDGE_DIR = "knowledge"
RUNBOOKS_DIR = "runbooks"
README = "README.md"
TEMPLATE = "_TEMPLATE.md"

MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 300
ENTRY_MAX_LINES = 150
ENTRY_MAX_BYTES = 9_000
DEBUG_MAX_LINES = 100
CARD_MAX_LINES = 150
KNOWLEDGE_MAX_LINES = 300
ALWAYS_LOADED_LIMIT = 2_500
ALWAYS_LOADED_FILES = ("AGENTS.md", "CLAUDE.md")

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

PARAM_TABLE_COLUMNS = ("param", "default", "recommended", "recipe range")
EXAMPLE_PLAN_INFO = frozenset({"yaml", "yml"})
NONE_MARKERS = frozenset({"", "-", "—", "–", "n/a", "none"})
REQUIRED_MARKERS = frozenset({"required", "(required)"})
SI_PREFIXES = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6,
               "G": 1e9}

ProblemCode = Literal[
    "skill_layout", "generated_marker", "frontmatter", "budget", "link", "anchor", "card_sections", "card_recipe",
    "recipe_card", "card_knowledge", "card_debug", "analysis_method", "card_status", "param_table", "param_range",
    "example_plan", "card_confirmation",
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
    """Test-card frontmatter (blueprint 6.3)."""

    id: KebabId
    title: NonEmptyStr
    recipes: Annotated[list[RecipeId], Field(min_length=1)]
    device_types: Annotated[list[Identifier], Field(min_length=1)]
    modules: Annotated[list[NonEmptyStr], Field(min_length=1)]
    status: Literal["draft", "sim_validated", "hw_validated"]
    confirmation: Literal["never", "conditional", "always"]
    knowledge: list[KnowledgeRef]
    debug: list[KebabId]
    sources: Annotated[list[NonEmptyStr], Field(min_length=1)]
    version: Annotated[int, Field(ge=1)]


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
    example_plans: list[ExamplePlanCheck] = Field(default_factory=list)
    always_loaded: AlwaysLoadedBudget | None = None
    notes: list[str] = Field(default_factory=list)
    problems: list[LintProblem] = Field(default_factory=list)


# == Markdown =========================================================================================================

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_INLINE_LINK = re.compile(
    r"!?\[(?:[^\[\]\\]|\\.|\[[^\[\]]*\])*\]"
    r"\(\s*(<[^<>\n]*>|[^\s()<>]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
_REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*(<[^<>\n]*>|\S+)")
_HTML_ANCHOR = re.compile(r"<a\s[^>]*\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_HEADING_MARKUP = re.compile(r"!?\[([^\]]*)\]\([^)]*\)|<[^>]+>")


def slugify(text: str) -> str:
    """GitHub-style heading id: link text kept, markup dropped, lowercase, spaces → ``-``."""
    plain = _HEADING_MARKUP.sub(lambda m: m.group(1) or "", text).replace("`", "")
    lowered = plain.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in " -_").replace(" ", "-")


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int
    slug: str


@dataclass(frozen=True)
class Fence:
    info: str
    line: int
    body: str


@dataclass
class MarkdownDoc:
    """A parsed Markdown file (1-based line numbers count the frontmatter lines)."""

    path: Path
    rel: str
    lines: list[str]
    has_front: bool = False
    front: Any = None
    front_error: str | None = None
    headings: list[Heading] = field(default_factory=list)
    links: list[tuple[str, int]] = field(default_factory=list)
    fences: list[Fence] = field(default_factory=list)
    fenced: set[int] = field(default_factory=set)
    anchors: set[str] = field(default_factory=set)

    def section(self, title: str, level: int = 2) -> tuple[int, int] | None:
        """1-based line range ``(heading line, end line exclusive)`` of the heading ``title`` at ``level``."""
        wanted = _norm_title(title)
        for index, heading in enumerate(self.headings):
            if heading.level == level and _norm_title(heading.text) == wanted:
                end = next((h.line for h in self.headings[index + 1:] if h.level <= level), len(self.lines) + 1)
                return heading.line, end
        return None


def _norm_title(text: str) -> str:
    return " ".join(text.replace("->", "→").split()).casefold()


def parse_markdown(path: Path, rel: str) -> MarkdownDoc:
    """Parse ``path``; raises ``UnicodeDecodeError`` for non-UTF-8 bytes and ``OSError`` when unreadable."""
    lines = normalize_text(path.read_bytes()).split("\n")
    doc = MarkdownDoc(path=path, rel=rel, lines=lines)
    end = frontmatter_end(lines)
    start = 0
    if end is not None:
        doc.has_front, start = True, end + 1
        try:
            doc.front = load_yaml("\n".join(lines[1:end]).encode("utf-8"))
        except yaml.YAMLError as exc:
            doc.front_error = "invalid YAML: " + " ".join(str(exc).split())
    elif lines and lines[0].rstrip() == "---":
        doc.has_front, start = True, 1
        doc.front_error = "frontmatter is not closed by a '---' line"
    slugs: dict[str, int] = {}
    fence: tuple[str, int, str, int, list[str]] | None = None  # char, length, info, line, body
    for index in range(start, len(lines)):
        line, number = lines[index], index + 1
        if fence is not None:
            doc.fenced.add(number)
            close = _FENCE_CLOSE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                doc.fences.append(Fence(info=fence[2], line=fence[3], body="\n".join(fence[4])))
                fence = None
            else:
                fence[4].append(line)
            continue
        opening = _FENCE_OPEN.match(line)
        if opening:
            doc.fenced.add(number)
            fence = (opening.group(1)[0], len(opening.group(1)), opening.group(2).lower(), number, [])
            continue
        heading = _HEADING.match(line)
        if heading:
            text = _CLOSING_HASHES.sub("", heading.group(2) or "").strip()
            slug = slugify(text)
            count = slugs.get(slug, 0)
            slugs[slug] = count + 1
            unique = slug if count == 0 else f"{slug}-{count}"
            doc.headings.append(Heading(level=len(heading.group(1)), text=text, line=number, slug=unique))
            doc.anchors.add(unique)
        doc.anchors.update(_HTML_ANCHOR.findall(line))
        plain = _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
        doc.links.extend((target, number) for target in _INLINE_LINK.findall(plain))
        reference = _REF_DEF.match(plain)
        if reference:
            doc.links.append((reference.group(1), number))
    if fence is not None:
        doc.fences.append(Fence(info=fence[2], line=fence[3], body="\n".join(fence[4])))
    return doc


# == Values of the card parameter table ===============================================================================

_NUMBER = re.compile(r"^\s*([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?)\s*(.*?)\s*$")
MINUS_SIGN = "\u2212"  # typographic minus (U+2212), as written in the deck
_RANGE_SEP = re.compile(r"\s*(?:\.\.|…|\bto\b)\s*")
_BRACKETS = re.compile(r"^\[(.*)\]\s*(\S*)\s*$")


def _clean(cell: str) -> str:
    """A table cell without emphasis, backticks and surrounding blanks."""
    return cell.replace("`", "").replace("**", "").strip()


def _unit_factor(suffix: str, unit: str | None) -> float | None:
    """Scale of ``suffix`` (SI prefix + unit) for a parameter in ``unit``; ``None`` when it does not fit."""
    text = suffix.replace("Ω", "Ohm").replace("ohm", "Ohm")
    if text == "":
        return 1.0
    if unit is None or unit == "1":
        return None
    if text == unit:
        return 1.0
    prefix = text[: -len(unit)] if text.endswith(unit) else None
    return SI_PREFIXES.get(prefix) if prefix else None


def parse_value(text: str, unit: str | None) -> tuple[float, str]:
    """``(value in base units, suffix as written)`` of ``-1 V``, ``50 mV``, ``1e-6``; raises ``ValueError``."""
    match = _NUMBER.match(text.replace(MINUS_SIGN, "-"))
    if not match:
        raise ValueError(f"{text.strip()!r} is not a number")
    factor = _unit_factor(match.group(2), unit)
    if factor is None:
        raise ValueError(f"{text.strip()!r}: unit {match.group(2)!r} does not fit the parameter unit {unit or 'none'}")
    return float(match.group(1)) * factor, match.group(2)


def _split_items(text: str) -> list[str]:
    """Items of ``a, b`` or ``[a, b] unit`` (a unit after the bracket applies to unitless items)."""
    bracket = _BRACKETS.match(text.strip())
    if not bracket:
        return [part.strip() for part in text.split(",")]
    suffix = bracket.group(2)
    items = [part.strip() for part in bracket.group(1).split(",")]
    return [f"{item} {suffix}" if suffix and not _has_suffix(item) else item for item in items]


def _has_suffix(item: str) -> bool:
    match = _NUMBER.match(item.replace(MINUS_SIGN, "-"))
    return bool(match and match.group(2))


def parse_interval(text: str, unit: str | None) -> tuple[float, float]:
    """``(low, high)`` of ``a..b``, ``a … b``, ``a to b`` or ``[a, b]`` (a unitless low end takes the high end's
    unit); raises ``ValueError``."""
    stripped = text.strip()
    parts = _split_items(stripped) if stripped.startswith("[") else _RANGE_SEP.split(stripped)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"{stripped!r} is not an interval low..high")
    high, high_suffix = parse_value(parts[1], unit)
    low, low_suffix = parse_value(parts[0], unit)
    if not low_suffix and high_suffix:
        low *= _unit_factor(high_suffix, unit) or 1.0
    if low > high:
        raise ValueError(f"{stripped!r}: low end above high end")
    return low, high


def parse_list(text: str, unit: str | None) -> list[float]:
    """Values of ``[a, b, c] V`` or ``a, b, c``; raises ``ValueError``."""
    return [parse_value(item, unit)[0] for item in _split_items(text)]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)


def _fmt(value: float, unit: str | None) -> str:
    return f"{value:g} {unit}" if unit and unit != "1" else f"{value:g}"


def _fmt_interval(window: tuple[float, float], unit: str | None) -> str:
    return f"{window[0]:g}..{_fmt(window[1], unit)}"


def _is_none(cell: str, *, required_ok: bool = False) -> bool:
    text = _clean(cell).lower()
    return text in NONE_MARKERS or (required_ok and text in REQUIRED_MARKERS)


def _split_row(line: str) -> list[str]:
    text = line.strip().removeprefix("|")
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", text)]


_DELIMITER_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


@dataclass(frozen=True)
class ParamRow:
    name: str
    default: str
    recommended: str
    range: str
    line: int


def param_rows(doc: MarkdownDoc, start: int, end: int) -> tuple[list[ParamRow], list[tuple[int, str]]]:
    """Rows of every parameter table between 1-based lines ``start`` and ``end`` (exclusive), plus row problems."""
    rows: list[ParamRow] = []
    problems: list[tuple[int, str]] = []
    number = start
    while number < end:
        line = doc.lines[number - 1]
        cells = [_clean(c).lower() for c in _split_row(line)] if line.lstrip().startswith("|") else []
        if number in doc.fenced or tuple(cells[:4]) != PARAM_TABLE_COLUMNS:
            number += 1
            continue
        if number + 1 >= end or not _DELIMITER_ROW.match(doc.lines[number]):
            problems.append((number, "parameter table header is not followed by a |---| delimiter row"))
            number += 1
            continue
        number += 2
        while number < end and doc.lines[number - 1].lstrip().startswith("|") and number not in doc.fenced:
            row = _split_row(doc.lines[number - 1])
            if len(row) < 4:
                problems.append((number, f"parameter table row has {len(row)} cells; expected at least 4"))
            else:
                rows.append(ParamRow(name=_clean(row[0]), default=row[1], recommended=row[2], range=row[3],
                                     line=number))
            number += 1
    return rows, problems


def check_param_row(row: ParamRow, recipe_id: str, spec: ParamSpec) -> list[tuple[ProblemCode, str]]:
    """Problems of one table row against one recipe parameter (see the section-4 contract)."""
    out: list[tuple[ProblemCode, str]] = []

    def flag(code: ProblemCode, message: str) -> None:
        out.append((code, message))

    where = f"param {row.name} (recipe {recipe_id})"
    if spec.type == "enum":
        choices = list(spec.choices or [])
        if _is_none(row.default, required_ok=True):
            if spec.default is not None:
                flag("param_range", f"{where}: default is empty but the recipe default is {spec.default}")
        else:
            value = _clean(row.default)
            if value not in choices:
                flag("param_range", f"{where}: default {value!r} is not one of the recipe choices {choices}")
            elif value != spec.default:
                flag("param_range", f"{where}: default {value!r} differs from the recipe default "
                     f"{spec.default!r}")
        for column, cell in (("recommended", row.recommended), ("recipe range", row.range)):
            if _is_none(cell):
                continue
            items = [_clean(item) for item in re.split(r"[,|/]", _clean(cell).strip("[]{}")) if _clean(item)]
            unknown = [item for item in items if item not in choices]
            if unknown:
                flag("param_range", f"{where}: {column} {unknown} outside the recipe choices {choices}")
            elif column == "recipe range" and sorted(set(items)) != sorted(choices):
                flag("param_range", f"{where}: recipe range {items} differs from the recipe choices "
                     f"{choices}")
        return out
    if spec.type == "bool":
        if not _is_none(row.default, required_ok=True):
            value = _clean(row.default).lower()
            if value not in ("true", "false"):
                flag("param_table", f"{where}: default {row.default!r} is not true/false")
            elif (value == "true") != spec.default:
                flag("param_range", f"{where}: default {value} differs from the recipe default "
                     f"{str(spec.default).lower()}")
        for column, cell in (("recommended", row.recommended), ("recipe range", row.range)):
            if not _is_none(cell):
                flag("param_table", f"{where}: a bool parameter has no {column} (use -)")
        return out
    unit = spec.unit
    rng = spec.range
    # default
    if _is_none(row.default, required_ok=True):
        if spec.default is not None:
            flag("param_range", f"{where}: default is empty but the recipe default is "
                 f"{_fmt_default(spec.default, unit)}")
    else:
        try:
            values = parse_list(_clean(row.default), unit) if spec.type == "float_list" else \
                [parse_value(_clean(row.default), unit)[0]]
        except ValueError as exc:
            flag("param_table", f"{where}: cannot read default: {exc}")
            values = None
        if values is not None:
            expected = spec.default if isinstance(spec.default, list) else [spec.default]
            if rng is not None and any(not rng[0] <= v <= rng[1] for v in values):
                flag("param_range", f"{where}: default {_clean(row.default)} lies outside the recipe range "
                     f"{_fmt_interval(rng, unit)}")
            elif spec.default is None:
                flag("param_range", f"{where}: default {_clean(row.default)} given, but the recipe "
                     "parameter is required (no default)")
            elif len(values) != len(expected) or not all(_close(a, float(b)) for a, b in zip(values, expected,
                                                                                             strict=False)):
                flag("param_range", f"{where}: default {_clean(row.default)} differs from the recipe default "
                     f"{_fmt_default(spec.default, unit)}")
    # recommended
    if not _is_none(row.recommended):
        try:
            window = parse_interval(_clean(row.recommended), unit)
        except ValueError as exc:
            flag("param_table", f"{where}: cannot read recommended: {exc}")
        else:
            if rng is not None and not (rng[0] <= window[0] and window[1] <= rng[1]):
                flag("param_range", f"{where}: recommended {_fmt_interval(window, unit)} lies outside the "
                     f"recipe range {_fmt_interval(rng, unit)}")
    # recipe range
    if _is_none(row.range):
        if rng is not None:
            flag("param_range", f"{where}: recipe range is empty but the recipe range is "
                 f"{_fmt_interval(rng, unit)}")
    else:
        try:
            stated = parse_interval(_clean(row.range), unit)
        except ValueError as exc:
            flag("param_table", f"{where}: cannot read recipe range: {exc}")
        else:
            if rng is None:
                flag("param_range", f"{where}: recipe range {_fmt_interval(stated, unit)} stated, but the "
                     "recipe parameter has no range")
            elif not (_close(stated[0], rng[0]) and _close(stated[1], rng[1])):
                flag("param_range", f"{where}: recipe range {_fmt_interval(stated, unit)} differs from the "
                     f"recipe's range {_fmt_interval(rng, unit)}")
    return out


def _fmt_default(value: Any, unit: str | None) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(f"{v:g}" for v in value) + "]" + (f" {unit}" if unit and unit != "1" else "")
    return _fmt(float(value), unit) if isinstance(value, int | float) and not isinstance(value, bool) else str(value)


# == Lint =============================================================================================================


@dataclass
class _Card:
    doc: MarkdownDoc
    front: CardFrontmatter
    example: ExamplePlan | None = None
    example_line: int | None = None


class _Lint:
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


def _validation_messages(exc: ValidationError, prefix: str = "") -> list[str]:
    messages = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "frontmatter"
        message = error["msg"]
        if error["type"] == "string_too_long" and isinstance(error.get("input"), str):
            message += f" (has {len(error['input'])})"
        messages.append(f"{prefix}{loc}: {message}")
    return messages


def _exists_exact(base: Path, target: Path) -> bool:
    """``target`` (inside ``base``) exists with exactly this spelling of every path component."""
    current = base
    for part in target.relative_to(base).parts:
        try:
            names = os.listdir(current)
        except OSError:
            return False
        if part not in names:
            return False
        current = current / part
    return True


def _check_links(lint: _Lint, doc: MarkdownDoc, skill_dir: Path) -> None:
    for raw_target, line in doc.links:
        target = raw_target[1:-1].strip() if raw_target.startswith("<") else raw_target
        if not target:
            lint.add("link", doc.path, "empty link target", line)
            continue
        if _WINDOWS_ABSOLUTE.match(target) or target.startswith(("/", "\\")):
            lint.add("link", doc.path, f"absolute link {target!r}; link relative to the skill folder", line)
            continue
        if _URL_SCHEME.match(target):
            continue  # external URL (https:, mailto: ...)
        path_part, _, anchor = target.partition("#")
        path_part = unquote(path_part.split("?", 1)[0])
        if not path_part:
            if anchor and anchor not in doc.anchors:
                lint.add("anchor", doc.path, f"link #{anchor}: no heading with this id in this file", line)
            continue
        resolved = Path(os.path.normpath(doc.path.parent / path_part))
        if not resolved.is_relative_to(skill_dir):
            lint.add("link", doc.path, f"link {target!r} leaves the skill folder {lint.rel(skill_dir)}", line)
            continue
        if not _exists_exact(skill_dir, resolved):
            lint.add("link", doc.path, f"broken link {target!r}: {lint.rel(resolved)} does not exist", line)
            continue
        if anchor and resolved.is_file() and resolved.suffix.lower() == ".md":
            target_doc = lint.doc(resolved)
            if target_doc is not None and anchor not in target_doc.anchors:
                lint.add("anchor", doc.path, f"link {target!r}: {lint.rel(resolved)} has no heading id {anchor!r}",
                         line)


def _check_skill_front(lint: _Lint, doc: MarkdownDoc, skill: str) -> SkillFrontmatter | None:
    if not doc.has_front:
        lint.add("frontmatter", doc.path, "SKILL.md must start with YAML frontmatter (name, description)", 1)
        return None
    if doc.front_error:
        lint.add("frontmatter", doc.path, doc.front_error, 1)
        return None
    if not isinstance(doc.front, dict):
        lint.add("frontmatter", doc.path, "frontmatter must be a mapping", 1)
        return None
    try:
        front = SkillFrontmatter.model_validate(doc.front)
    except ValidationError as exc:
        for message in _validation_messages(exc):
            lint.add("frontmatter", doc.path, message, 1)
        return None
    if front.name != skill:
        lint.add("frontmatter", doc.path, f"name {front.name!r} must equal the folder name {skill!r}", 1)
    return front


def _check_budget(lint: _Lint, doc: MarkdownDoc, max_lines: int, what: str, max_bytes: int | None = None) -> None:
    count = len(doc.lines) - (1 if doc.lines and doc.lines[-1] == "" else 0)
    if count > max_lines:
        lint.add("budget", doc.path, f"{what} has {count} lines (limit {max_lines})")
    if max_bytes is not None:
        size = doc.path.stat().st_size
        if size > max_bytes:
            lint.add("budget", doc.path, f"{what} has {size:,} bytes (limit {max_bytes:,})")


def _model_front(lint: _Lint, doc: MarkdownDoc, model: type[StrictModel], what: str) -> Any:
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
        for message in _validation_messages(exc):
            lint.add("frontmatter", doc.path, message, 1)
        return None


def _check_sections(lint: _Lint, doc: MarkdownDoc) -> None:
    found = [h for h in doc.headings if h.level == 2]
    expected = [f"{i}. {title}" for i, title in enumerate(CARD_SECTIONS, 1)]
    for index in range(max(len(found), len(expected))):
        have = found[index] if index < len(found) else None
        want = expected[index] if index < len(expected) else None
        if have is not None and want is not None and _norm_title(have.text) == _norm_title(want):
            continue
        if have is None:
            message = f"missing H2 section '## {want}' (a card has the ten numbered sections of the template)"
        elif want is None:
            message = f"unexpected H2 section '## {have.text}' after section 10 (use H3 inside a section)"
        else:
            message = f"H2 section {index + 1} is '## {have.text}'; expected '## {want}' (template order)"
        lint.add("card_sections", doc.path, message, have.line if have else None)
        return


def _example_plan(lint: _Lint, doc: MarkdownDoc, span: tuple[int, int]) -> tuple[ExamplePlan | None, int | None]:
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
        for message in _validation_messages(exc, prefix="example plan "):
            lint.add("example_plan", doc.path, message, block.line)
        return None, block.line


def _check_card(lint: _Lint, path: Path, registry: RecipeRegistry, entry_dir: Path,
                runbooks: set[str]) -> _Card | None:
    doc = lint.doc(path)
    if doc is None:
        return None
    _check_budget(lint, doc, CARD_MAX_LINES, "card")
    _check_sections(lint, doc)
    front: CardFrontmatter | None = _model_front(lint, doc, CardFrontmatter, "test card")
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
        if not target.is_relative_to(entry_dir / KNOWLEDGE_DIR) or not _exists_exact(entry_dir, target) \
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
    card = _Card(doc=doc, front=front)
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
    card.example, card.example_line = _example_plan(lint, doc, span)
    if card.example is not None and card.example.recipe_id not in front.recipes:
        lint.add("example_plan", path, f"example plan recipe_id {card.example.recipe_id} is not one of the card's "
                                       f"recipes {front.recipes}", card.example_line)
        card.example = None
    return card


def _validate_examples(lint: _Lint, cards: list[_Card], registry: RecipeRegistry) -> list[ExamplePlanCheck]:
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
                    _judge_example(lint, card, result)
            finally:
                service.close()
    return checks


def _judge_example(lint: _Lint, card: _Card, result: PlanValidation) -> None:
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


def always_loaded_budget(root: Path, counter: TokenCounter | None = None) -> AlwaysLoadedBudget:
    """Tokens of ``AGENTS.md`` + ``CLAUDE.md`` + every skill's frontmatter ``description`` under ``root``."""
    if counter is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            counter = load_counter()
    root = Path(root)
    parts: dict[str, int] = {}
    for name in ALWAYS_LOADED_FILES:
        path = root / name
        if path.is_file():
            parts[name] = counter.count(normalize_text(path.read_bytes()))
    for skill in source_skills(root):
        rel = f"{SOURCE_DIR}/{skill}/{SKILL_FILE}"
        try:
            doc = parse_markdown(root / rel, rel)
        except (OSError, UnicodeDecodeError):
            continue
        description = doc.front.get("description") if isinstance(doc.front, dict) else None
        if isinstance(description, str):
            parts[f"{rel}#description"] = counter.count(description)
    return AlwaysLoadedBudget(method=counter.method, warning=counter.warning, limit=ALWAYS_LOADED_LIMIT,
                              total=sum(parts.values()), parts=parts)


def _skill_files(lint: _Lint, skill_dir: Path) -> list[Path]:
    """Markdown files of one skill (sorted); symlinks and the generated marker are problems."""
    tree = scan_tree(skill_dir)
    for link in tree.links:
        lint.add("skill_layout", skill_dir / link, "symlink inside a skill (Windows checkouts break them); use a "
                                                   "real file")
    markdown = []
    for rel, path in sorted(tree.files.items()):
        if not rel.lower().endswith(".md"):
            continue
        markdown.append(path)
        doc = lint.doc(path)
        if doc is not None and any(line.strip() == GENERATED_LINE for line in doc.lines):
            lint.add("generated_marker", path, "source file carries the generated-copy marker; edit the source and "
                                               "regenerate .claude/skills with b1500 dev sync-harness")
    return markdown


def lint_skills(root: Path | None = None, *, recipes_dir: Path | None = None, config_dir: Path | None = None,
                counter: TokenCounter | None = None) -> LintReport:
    """Lint the skills under ``root`` (default: the located repository); see the module docstring."""
    root = Path(root).resolve() if root is not None else find_repo_root()
    lint = _Lint(root, Path(recipes_dir).resolve() if recipes_dir else root / "recipes",
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
        files = _skill_files(lint, skill_dir)
        skill_doc = lint.doc(skill_dir / SKILL_FILE)
        if skill_doc is not None:
            _check_skill_front(lint, skill_doc, skill)
            if skill == ENTRY_SKILL:
                _check_budget(lint, skill_doc, ENTRY_MAX_LINES, "entry SKILL.md", ENTRY_MAX_BYTES)
            elif skill == DEBUG_SKILL:
                _check_budget(lint, skill_doc, DEBUG_MAX_LINES, "debug SKILL.md")
        for path in files:
            doc = lint.doc(path)
            if doc is not None:
                _check_links(lint, doc, skill_dir)
    knowledge: list[str] = []
    if ENTRY_SKILL in skills and (entry_dir / KNOWLEDGE_DIR).is_dir():
        for path in sorted((entry_dir / KNOWLEDGE_DIR).rglob("*.md")):
            doc = lint.doc(path)
            if doc is None or path.is_symlink():
                continue
            _check_budget(lint, doc, KNOWLEDGE_MAX_LINES, "knowledge file")
            if path.name != README:
                knowledge.append(lint.rel(path))
                _model_front(lint, doc, KnowledgeFrontmatter, "knowledge file")
    runbooks = sorted(p.stem for p in (debug_dir / RUNBOOKS_DIR).glob("*.md")) \
        if DEBUG_SKILL in skills and (debug_dir / RUNBOOKS_DIR).is_dir() else []
    if not lint.recipes_dir.is_dir():
        lint.add("skill_layout", lint.recipes_dir, "recipe folder not found (card and recipe links cannot be checked)")
    registry = RecipeRegistry.load(lint.recipes_dir, repo_root=root)
    _check_recipes(lint, registry, entry_dir)
    cards: list[_Card] = []
    card_paths = _card_paths(entry_dir) if ENTRY_SKILL in skills else []
    for path in card_paths:
        card = _check_card(lint, path, registry, entry_dir, set(runbooks))
        if card is not None:
            cards.append(card)
    other = sorted(set((entry_dir / CARDS_DIR).glob("*.md")) - set(card_paths)) if ENTRY_SKILL in skills else []
    for path in other:  # _TEMPLATE.md (and any README.md): card budget; the template also has the card sections
        doc = lint.doc(path)
        if doc is not None:
            _check_budget(lint, doc, CARD_MAX_LINES, path.name)
            if path.name == TEMPLATE:
                _check_sections(lint, doc)
    examples = _validate_examples(lint, cards, registry)
    budget = always_loaded_budget(root, counter)
    if budget.total > budget.limit:
        message = f"always-loaded text has {budget.total} tokens (limit {budget.limit}; {budget.method})"
        if budget.warning is None:
            lint.add("budget", "AGENTS.md", message + "; parts: " + ", ".join(f"{k} {v}"
                                                                               for k, v in budget.parts.items()))
        else:
            lint.notes.append(message + " - estimate only, re-check with the tiktoken encoding")
    problems = sorted(lint.problems, key=lambda p: (p.file, p.line or 0, p.code, p.message))
    return LintReport(ok=not problems, root=root.as_posix(), skills=skills,
                      cards=[lint.rel(p) for p in card_paths], knowledge=knowledge,
                      runbooks=runbooks, example_plans=examples, always_loaded=budget, notes=lint.notes,
                      problems=_dedupe(problems))


def _card_paths(entry_dir: Path) -> list[Path]:
    folder = entry_dir / CARDS_DIR
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob("*.md")) if not p.name.startswith("_") and p.name != README]


def _check_recipes(lint: _Lint, registry: RecipeRegistry, entry_dir: Path) -> None:
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
        if not _exists_exact(lint.root, card_path) or not card_path.is_file():
            lint.add("recipe_card", entry.source, f"card {recipe.card} does not exist (dangling card)")
            continue
        doc = lint.doc(card_path)
        listed = doc.front.get("recipes") if doc is not None and isinstance(doc.front, dict) else None
        if not isinstance(listed, list) or recipe_id not in listed:
            lint.add("recipe_card", entry.source, f"card {recipe.card} does not list {recipe_id} in its recipes")


def _dedupe(problems: Iterable[LintProblem]) -> list[LintProblem]:
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
              f"{len(report.knowledge)} knowledge files, {len(report.runbooks)} runbooks; root {report.root})")]
    for check in report.example_plans:
        lines.append(f"  example plan {check.card}: {check.recipe_id} on {check.sim_scenario} -> {check.status}, "
                     f"tier {check.tier or '-'}")
    if report.always_loaded is not None:
        budget = report.always_loaded
        lines.append(f"  always-loaded text: {budget.total} / {budget.limit} tokens ({budget.method})")
    lines += [f"  note: {note}" for note in report.notes]
    lines += [f"  {format_problem(problem)}" for problem in report.problems]
    return "\n".join(lines)

