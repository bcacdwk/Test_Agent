"""Debug cases of skill ``b1500-debug`` (v2.1 plan §3): the case schema (template v2), the expectation grammar of a
case's simulator ``reproduction`` and the case lint that ``b1500 dev lint-skills`` and ``b1500 dev cases check`` run.

A case ``b1500-debug/cases/<YYYY-MM-DD>-<slug>.md`` (``origin: observed``) records one problem seen in the lab, dated
by the observation; ``b1500-debug/cases/example-<slug>.md`` (``origin: illustrative``, title ``Example: ...``) is an
example of a kind of problem written from a list (v2.1 KD-5: the owner's planning deck is illustrative, never a lab
record), with ``backend: none``, ``station: none`` and no runs. Its frontmatter keeps the facts of the observation
(``origin``, ``backend``, ``station``, ``device``, ``runs``, ``sources``) apart from the simulator reproduction (v2.1
plan D-6): ``runs`` lists only runs of the case's own backend (``H...`` for ``visa``, ``S...`` for ``sim``, at least
one; ``none`` = no run of this agent: an illustrative case, or a lab record from outside the agent, whose
``sources`` name it), the reproduction's runs appear only in the section "Simulator reproduction (SIMULATED)"; an
observed case never cites the deck as a source. ``status: draft`` is what an agent writes (``reviewed_by: null``); only
a human sets ``status: reviewed`` with their name, after answering every open question (``open_questions: 0``; the
guard hook blocks an agent write that sets it, v2.1 D-7).

``reproduction`` (or ``null`` when the simulator has no model of the cause; the section then says so):

- ``scenario``: the default simulator scenario of the steps; ``scenarios``: local aliases ``name: {base: <committed
  scenario>, faults: [<SimFault>...]}`` (each alias is a device of its own: its own simulator state, so an alias
  without faults is "another device of the same kind" or "the same device after a long rest");
- ``steps``: plans run in order on one temporary data directory, each ``{id, scenario?, recipe, pin_map,
  dut_profile?, params?, corrections?, analyze?}``; ``corrections: true`` first runs the policy-required MFCMU
  corrections with the step's pin map (each confirmed: the runner stands in for the human); a plan of tier
  ``needs_confirmation`` is run with its summary, a ``blocked`` one is not run;
- ``expect`` (the symptom signature) and ``discriminator`` (``check``: the runbook check that separates the causes, in
  words; ``expect``: its expected result): expressions over the steps.

Expression grammar (Python syntax, nothing else is accepted): constants (numbers, strings, ``True``/``False``/
``None``), lists and tuples, comparisons (chains allowed, ``in``/``not in``), ``and``/``or``/``not``, ``+ - * /``,
``abs()``/``min()``/``max()``, step attributes ``<step>.tier|outcome|error_code|quality|run_id|blocked_by|
confirm_reasons`` and step methods with constant arguments: ``status(column, row)`` (status letter of a data row;
``0`` is the first, ``-1`` the last), ``value(column, row)`` (measured value), ``value_at(column, x_column, x)`` (the
value in the row whose ``x_column`` is nearest to ``x``, e.g. ``value_at('gate_Cp', 'dc_v', -0.65)``),
``snr(column)`` (quality report), ``count(letter)`` (status count),
``result([method,] quantity)`` (the one derived value of that quantity among the run's default and ``analyze``
analyses, e.g. ``result('vth')``; name the method when several give the quantity), ``classification([method,]
quantity)``, ``kind(key)`` (the run's ``kind_result``). ``devtools/cases.py`` evaluates them.

Lint [``case``]: the template (``status: draft``, ``reviewed_by: null``, ``origin: observed``, no deck in its
``sources``) and every case have the frontmatter keys of ``CASE_KEYS`` in order and the ten H2 sections of
``CASE_SECTIONS``; a case's name is ``<YYYY-MM-DD>-<slug>.md`` (observed) or ``example-<slug>.md`` (illustrative) with
``id`` = the name, its frontmatter validates (``CaseFrontmatter``), its ``runbook`` is a runbook (or ``new``) whose
``sources`` name the case, every scenario, fault, recipe, parameter, pin map, DUT profile and analysis method of the
reproduction exists, ``open_questions`` equals the numbered items of "Open questions for the owner", no
``TODO(owner)`` stands outside that section, and the reproduction section names ``uv run b1500 dev cases reproduce
<id>`` (or, without a reproduction, says why).
"""


from __future__ import annotations

import ast
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, JsonValue, model_validator

from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.skills.common import (
    TEMPLATE,
    KebabId,
    Lint,
    NonEmptyStr,
    model_front,
)
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc, norm_title
from b1500_test_agent.models.analysis import Identifier, RunId
from b1500_test_agent.models.common import ConfigName, StrictModel
from b1500_test_agent.models.recipe import RecipeId
from b1500_test_agent.models.sim import SimFault

CASES_DIR: Final = "cases"
NEW_RUNBOOK: Final = "new"
"""``runbook`` value of a case no runbook covered (yet)."""
OWNER_MARKER: Final = "TODO(owner)"
EXAMPLE_PREFIX: Final = "example-"
"""Id and file-name prefix of an illustrative case (v2.1 KD-5); an observed case starts with the observation date."""
EXAMPLE_TITLE: Final = "Example: "
"""Title prefix of an illustrative case."""
NO_BACKEND: Final = "none"
"""``backend`` and ``station`` of a case no run of this agent belongs to."""
REPRODUCE_COMMAND: Final = "uv run b1500 dev cases reproduce"

CASE_KEYS: Final[tuple[str, ...]] = (
    "id", "title", "status", "reviewed_by", "runbook", "origin", "backend", "station", "device", "runs", "sources",
    "reproduction", "open_questions",
)  # fmt: skip
"""Frontmatter keys of a case, in order (template v3: the v1 ten + ``reproduction`` + ``open_questions`` (v2.1 §3)
+ ``origin`` (v2.1 KD-5))."""

REPRODUCTION_SECTION: Final = "Simulator reproduction (SIMULATED)"
QUESTIONS_SECTION: Final = "Open questions for the owner"
CASE_SECTIONS: Final[tuple[str, ...]] = (
    "Symptom", "Observed data and status codes", "Physical checks", "Instrument checks", "DUT hypotheses",
    "Resolution", "Reproducible", "Proposed follow-up", REPRODUCTION_SECTION, QUESTIONS_SECTION,
)  # fmt: skip
"""The H2 sections of a case, in order (template v2)."""

CASE_NAME: Final = re.compile(r"(?:\d{4}-\d{2}-\d{2}|example)-[a-z0-9]+(?:-[a-z0-9]+)*")
"""``<YYYY-MM-DD>-<slug>`` (observed) or ``example-<slug>`` (illustrative)."""
CaseId = Annotated[str, Field(pattern=rf"^{CASE_NAME.pattern}$")]

STEP_ATTRIBUTES: Final[frozenset[str]] = frozenset({
    "tier", "outcome", "error_code", "quality", "run_id", "blocked_by", "confirm_reasons"})
"""Step attributes an expectation may read (``devtools/cases.py`` ``StepView``)."""
STEP_METHODS: Final[dict[str, tuple[int, ...]]] = {
    "status": (2,), "value": (2,), "value_at": (3,), "snr": (1,), "count": (1,), "result": (1, 2),
    "classification": (1, 2), "kind": (1,)}
"""Step methods an expectation may call -> the numbers of (constant) arguments they take."""
FUNCTIONS: Final[dict[str, Callable[..., Any]]] = {"abs": abs, "min": min, "max": max}
"""Plain functions an expectation may call."""

_COMPARE_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}
_NUMBERED = re.compile(r"^\d+\.\s+\S")


# == Expectation grammar ==============================================================================================


class ExpectationError(Exception):
    """An expectation could not be evaluated (a step without a run, a missing column, a refused analysis ...)."""


def parse_expectation(text: str, steps: Collection[str]) -> ast.Expression:
    """Parse ``text`` with the grammar of the module docstring; ``steps`` are the step ids it may name. Raises
    ``ValueError`` with the reason."""
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"{text!r}: not an expression ({exc.msg})") from None
    _check_node(tree.body, set(steps), text)
    return tree


def _check_node(node: ast.AST, steps: set[str], text: str) -> None:
    def fail(why: str) -> None:
        raise ValueError(f"{text!r}: {why}")

    if isinstance(node, ast.Constant):
        if not isinstance(node.value, int | float | str | bool | type(None)):
            fail(f"constant {node.value!r} is not a number, string, boolean or None")
    elif isinstance(node, ast.List | ast.Tuple):
        for item in node.elts:
            _check_node(item, steps, text)
    elif isinstance(node, ast.Compare):
        for part in (node.left, *node.comparators):
            _check_node(part, steps, text)
        if any(type(op) not in _COMPARE_OPS for op in node.ops):
            fail("only == != < <= > >= in, not in compare")
    elif isinstance(node, ast.BoolOp):
        for part in node.values:
            _check_node(part, steps, text)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not | ast.USub | ast.UAdd):
            fail("only not, - and + are unary operators")
        _check_node(node.operand, steps, text)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            fail("only + - * / are operators")
        _check_node(node.left, steps, text)
        _check_node(node.right, steps, text)
    elif isinstance(node, ast.Attribute):
        _step_name(node.value, steps, fail)
        if node.attr not in STEP_ATTRIBUTES:
            fail(f"step attribute {node.attr!r} unknown (known: {', '.join(sorted(STEP_ATTRIBUTES))})")
    elif isinstance(node, ast.Call):
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            fail("calls take positional arguments only")
        if isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            if not node.args:
                fail(f"{node.func.id}() needs arguments")
            for arg in node.args:
                _check_node(arg, steps, text)
        elif isinstance(node.func, ast.Attribute):
            _step_name(node.func.value, steps, fail)
            counts = STEP_METHODS.get(node.func.attr)
            if counts is None:
                fail(f"step method {node.func.attr!r} unknown (known: {', '.join(sorted(STEP_METHODS))})")
            elif len(node.args) not in counts or not all(_is_constant(a) for a in node.args):
                fail(f"{node.func.attr}() takes {' or '.join(map(str, counts))} constant argument(s)")
        else:
            fail(f"only {', '.join(sorted(FUNCTIONS))}() and step methods can be called")
    elif isinstance(node, ast.Name):
        fail(f"{node.id!r} alone means nothing: use <step>.<attribute> or <step>.<method>(...)"
             if node.id in steps else f"unknown name {node.id!r} (steps: {', '.join(sorted(steps)) or 'none'})")
    else:
        fail(f"{type(node).__name__} is not allowed")


def _is_constant(node: ast.AST) -> bool:
    """A literal: a constant, or a signed numeric constant (``-0.65``)."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        node = node.operand
        return isinstance(node, ast.Constant) and isinstance(node.value, int | float) \
            and not isinstance(node.value, bool)
    return isinstance(node, ast.Constant)


def _step_name(node: ast.AST, steps: set[str], fail: Callable[[str], None]) -> str:
    if not isinstance(node, ast.Name) or node.id not in steps:
        fail(f"{ast.unparse(node)!r} is not a step id (steps: {', '.join(sorted(steps))})")
    assert isinstance(node, ast.Name)
    return node.id


class StepAccess(Protocol):
    """What an evaluated expression sees of one step (``devtools/cases.py`` ``StepView``)."""

    def attribute(self, name: str) -> Any: ...

    def call(self, method: str, args: tuple[Any, ...]) -> Any: ...


def evaluate_expectation(tree: ast.Expression, steps: dict[str, StepAccess], terms: list[str]) -> Any:
    """Evaluate a parsed expectation over ``steps``; every step attribute and method value read is appended to
    ``terms`` as ``"<step>.<name>(...) = <value>"``. Raises ``ExpectationError`` (from the step views)."""

    def show(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.4g}"
        return repr(value)

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List | ast.Tuple):
            return [ev(item) for item in node.elts]
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, right_node in zip(node.ops, node.comparators, strict=True):
                right = ev(right_node)
                if not _compare(op, left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(ev(v)) for v in node.values)
            return any(bool(ev(v)) for v in node.values)
        if isinstance(node, ast.UnaryOp):
            operand = ev(node.operand)
            if isinstance(node.op, ast.Not):
                return not operand
            return -_number(operand) if isinstance(node.op, ast.USub) else _number(operand)
        if isinstance(node, ast.BinOp):
            left, right = _number(ev(node.left)), _number(ev(node.right))
            if isinstance(node.op, ast.Div) and right == 0:
                raise ExpectationError(f"division by zero in {ast.unparse(node)}")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.Attribute):
            name = node.value.id  # type: ignore[attr-defined]
            value = steps[name].attribute(node.attr)
            term = f"{name}.{node.attr} = {show(value)}"
            if term not in terms:
                terms.append(term)
            return value
        if isinstance(node, ast.Call):
            args = [ev(a) for a in node.args]
            if isinstance(node.func, ast.Name):
                return FUNCTIONS[node.func.id](*args)
            name, method = node.func.value.id, node.func.attr  # type: ignore[attr-defined]
            value = steps[name].call(method, tuple(args))
            term = f"{name}.{method}({', '.join(repr(a) for a in args)}) = {show(value)}"
            if term not in terms:
                terms.append(term)
            return value
        raise ExpectationError(f"cannot evaluate {type(node).__name__}")  # parse_expectation refuses it first

    return ev(tree.body)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExpectationError(f"{value!r} is not a number")
    return float(value)


def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
    try:
        return bool(_COMPARE_OPS[type(op)](left, right))
    except TypeError as exc:
        raise ExpectationError(f"cannot compare {left!r} with {right!r}") from exc


# == Schema ===========================================================================================================


class ScenarioAlias(StrictModel):
    """A local simulator scenario of a reproduction: committed scenario ``base`` with ``faults`` active from the start
    (``SimFault`` mappings). Each alias has a simulator state of its own (its own device)."""

    base: ConfigName
    faults: list[SimFault] = Field(default_factory=list)


class AnalysisRequest(StrictModel):
    """One extra ``analyze_run`` call of a step."""

    method: Identifier
    options: dict[str, JsonValue] = Field(default_factory=dict)


class ReproStep(StrictModel):
    """One plan of a reproduction (module docstring)."""

    id: Identifier
    scenario: ConfigName | None = None
    recipe: RecipeId
    pin_map: ConfigName
    dut_profile: ConfigName | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)
    corrections: bool = False
    analyze: list[AnalysisRequest] = Field(default_factory=list)


class Discriminator(StrictModel):
    """The runbook check that separates the causes (``check``, in words) and its expected result."""

    check: NonEmptyStr
    expect: Annotated[list[NonEmptyStr], Field(min_length=1)]


class Reproduction(StrictModel):
    """The simulator reproduction of a case (module docstring)."""

    scenario: ConfigName
    scenarios: dict[ConfigName, ScenarioAlias] = Field(default_factory=dict)
    steps: Annotated[list[ReproStep], Field(min_length=1)]
    expect: Annotated[list[NonEmptyStr], Field(min_length=1)]
    discriminator: Discriminator

    @model_validator(mode="after")
    def _consistent(self) -> Reproduction:
        ids = [step.id for step in self.steps]
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            raise ValueError(f"step ids used twice: {twice}")
        for text in (*self.expect, *self.discriminator.expect):
            parse_expectation(text, ids)
        return self

    def scenario_of(self, step: ReproStep) -> str:
        """The scenario (alias or committed name) ``step`` runs on."""
        return step.scenario or self.scenario

    def parsed(self) -> tuple[list[tuple[str, ast.Expression]], list[tuple[str, ast.Expression]]]:
        """``(expect, discriminator.expect)`` as ``(text, tree)`` pairs."""
        ids = [step.id for step in self.steps]
        return ([(t, parse_expectation(t, ids)) for t in self.expect],
                [(t, parse_expectation(t, ids)) for t in self.discriminator.expect])


class CaseFrontmatter(StrictModel):
    """Frontmatter of a debug case (template v2, module docstring)."""

    id: CaseId
    title: NonEmptyStr
    status: Literal["draft", "reviewed"]
    reviewed_by: NonEmptyStr | None
    runbook: KebabId
    origin: Literal["observed", "illustrative"]
    backend: Literal["sim", "visa", "none"]
    station: NonEmptyStr
    device: NonEmptyStr
    runs: list[RunId]
    sources: Annotated[list[NonEmptyStr], Field(min_length=1)]
    reproduction: Reproduction | None
    open_questions: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _review_rules(self) -> CaseFrontmatter:
        if self.status == "draft" and self.reviewed_by is not None:
            raise ValueError("status draft needs reviewed_by: null (only a human sets reviewed, with their name)")
        if self.status == "reviewed" and self.reviewed_by is None:
            raise ValueError("status reviewed needs reviewed_by: the name of the human who reviewed the case")
        if self.status == "reviewed" and self.open_questions:
            raise ValueError(f"status reviewed needs open_questions: 0 (has {self.open_questions}): answer them first")
        self._origin_rules()
        if self.backend == NO_BACKEND:
            if self.runs:
                raise ValueError(f"backend none has no runs (has {self.runs}): runs of this agent give the backend")
            return self
        prefix = "H" if self.backend == "visa" else "S"
        if not self.runs:
            raise ValueError(f"backend {self.backend} needs the observation's runs ({prefix}...) in runs; a lab record "
                             "without runs of this agent has backend: none")
        foreign = [r for r in self.runs if not r.startswith(prefix)]
        if foreign:
            raise ValueError(f"runs of backend {self.backend} start with {prefix} (simulator reproduction runs belong "
                             f"in the section {REPRODUCTION_SECTION!r}): {foreign}")
        return self

    def _origin_rules(self) -> None:
        """v2.1 KD-5: an illustrative case shows itself as an example and claims no observation; an observed case is
        dated and never rests on the illustrative deck."""
        if self.origin == "illustrative":
            wrong = [what for what, bad in (
                (f"id {EXAMPLE_PREFIX}<slug>", not self.id.startswith(EXAMPLE_PREFIX)),
                (f"a title starting {EXAMPLE_TITLE!r}", not self.title.startswith(EXAMPLE_TITLE)),
                ("backend: none", self.backend != NO_BACKEND), ("station: none", self.station != NO_BACKEND),
                ("runs: []", bool(self.runs))) if bad]
            if wrong:
                raise ValueError("an illustrative case (an example: nothing was observed) needs " + ", ".join(wrong))
            return
        if self.id.startswith(EXAMPLE_PREFIX):
            raise ValueError(f"an observed case is named <YYYY-MM-DD>-<slug> (date of the observation); "
                             f"{EXAMPLE_PREFIX}<slug> is for origin: illustrative")
        deck = [s for s in self.sources if "deck" in s.lower()]
        if deck:
            raise ValueError(f"an observed case's sources are records of the observation (run notes, lab notebook); "
                             f"the owner's deck is illustrative, never one: {deck}")


# == Lint =============================================================================================================


@dataclass
class Case:
    """A case file whose frontmatter validated."""

    doc: MarkdownDoc
    front: CaseFrontmatter

    @property
    def id(self) -> str:
        return self.front.id


def case_paths(cases_dir: Path) -> list[Path]:
    """Case files of ``cases_dir`` (every ``*.md`` but ``_TEMPLATE.md``), sorted."""
    if not cases_dir.is_dir():
        return []
    return sorted(p for p in cases_dir.glob("*.md") if p.name != TEMPLATE and not p.is_symlink())


def check_cases(lint: Lint, debug_dir: Path, registry: RecipeRegistry, runbooks: Collection[str]) -> list[Case]:
    """Lint the template and the cases under ``debug_dir/cases``; returns the cases whose frontmatter validated."""
    cases_dir = debug_dir / CASES_DIR
    template = cases_dir / TEMPLATE
    if not template.is_file():
        lint.add("case", template, f"the case template {CASES_DIR}/{TEMPLATE} is missing (cases are written from it)")
    else:
        doc = lint.doc(template)
        if doc is not None:
            check_template(lint, doc)
    found: list[Case] = []
    for path in case_paths(cases_dir):
        case = check_case(lint, path, registry, runbooks, debug_dir)
        if case is not None:
            found.append(case)
    return found


def check_template(lint: Lint, doc: MarkdownDoc) -> None:
    """The template has the keys (in order) and sections of a case, ``status: draft``, ``reviewed_by: null`` and
    ``origin: observed`` (an agent drafts what it saw; v2.1 KD-5), and its ``sources`` do not offer the deck."""
    _check_keys(lint, doc)
    _check_case_sections(lint, doc)
    if not isinstance(doc.front, dict):
        return
    if doc.front.get("status") != "draft" or doc.front.get("reviewed_by") is not None:
        lint.add("case", doc.path, "the template starts every case as status: draft with reviewed_by: null", 1)
    if doc.front.get("origin") != "observed":
        lint.add("case", doc.path, "the template starts every case as origin: observed (illustrative is the exception)",
                 1)
    if "deck" in str(doc.front.get("sources", "")).lower():
        lint.add("case", doc.path, "the template's sources are records of the observation; the owner's deck is "
                                   "illustrative, never a source of a case", 1)


def check_case(lint: Lint, path: Path, registry: RecipeRegistry, runbooks: Collection[str],
               debug_dir: Path) -> Case | None:
    doc = lint.doc(path)
    if doc is None:
        return None
    if not CASE_NAME.fullmatch(path.stem):
        lint.add("case", path, f"{path.name}: a case is named <YYYY-MM-DD>-<slug>.md (date of the observation) or "
                               f"{EXAMPLE_PREFIX}<slug>.md (illustrative)")
    _check_keys(lint, doc)
    _check_case_sections(lint, doc)
    _check_owner_markers(lint, doc)
    front: CaseFrontmatter | None = model_front(lint, doc, CaseFrontmatter, "debug case")
    if front is None:
        return None
    if front.id != path.stem:
        lint.add("case", path, f"id {front.id!r} differs from the file name {path.stem!r}", 1)
    _check_runbook(lint, doc, front, runbooks, debug_dir)
    questions = numbered_items(doc, QUESTIONS_SECTION)
    if questions != front.open_questions:
        lint.add("case", path, f"open_questions is {front.open_questions} but the section {QUESTIONS_SECTION!r} has "
                               f"{questions} numbered question(s)", 1)
    section = section_text(doc, REPRODUCTION_SECTION).strip()
    if front.reproduction is None and not section:
        lint.add("case", path, f"reproduction is null: the section {REPRODUCTION_SECTION!r} says why (no simulator "
                               "model of the cause)")
    if front.reproduction is not None:
        if f"{REPRODUCE_COMMAND} {front.id}" not in section:
            lint.add("case", path, f"the section {REPRODUCTION_SECTION!r} names the command to regenerate it: "
                                   f"`{REPRODUCE_COMMAND} {front.id}`")
        check_reproduction(lint, path, front.reproduction, registry)
    return Case(doc=doc, front=front)


def _check_keys(lint: Lint, doc: MarkdownDoc) -> None:
    if isinstance(doc.front, dict) and tuple(doc.front) != CASE_KEYS:
        lint.add("case", doc.path, f"frontmatter keys are {', '.join(CASE_KEYS)} in this order (has "
                                   f"{', '.join(map(str, doc.front))})", 1)


def _check_case_sections(lint: Lint, doc: MarkdownDoc) -> None:
    found = [h.text for h in doc.headings if h.level == 2]
    if [norm_title(t) for t in found] != [norm_title(t) for t in CASE_SECTIONS]:
        lint.add("case", doc.path, "sections are " + " · ".join(f"## {t}" for t in CASE_SECTIONS) + " in this order "
                                   f"(has {' · '.join(found) or 'none'})")


def _check_owner_markers(lint: Lint, doc: MarkdownDoc) -> None:
    span = doc.section(QUESTIONS_SECTION)
    for number, line in enumerate(doc.lines, 1):
        if OWNER_MARKER in line and not (span and span[0] < number < span[1]):
            lint.add("case", doc.path, f"{OWNER_MARKER} outside the section {QUESTIONS_SECTION!r}: make it a "
                                       "numbered question there", number)


def _check_runbook(lint: Lint, doc: MarkdownDoc, front: CaseFrontmatter, runbooks: Collection[str],
                   debug_dir: Path) -> None:
    if front.runbook == NEW_RUNBOOK:
        return
    if front.runbook not in runbooks:
        lint.add("case", doc.path, f"runbook {front.runbook!r} is not a runbooks/<id>.md file (or 'new')", 1)
        return
    runbook = lint.doc(debug_dir / "runbooks" / f"{front.runbook}.md")
    sources = runbook.front.get("sources") if runbook is not None and isinstance(runbook.front, dict) else None
    if not isinstance(sources, list) or not any(front.id in str(s) for s in sources):
        lint.add("case", doc.path, f"runbook {front.runbook}'s sources do not name this case ({front.id})", 1)


def section_text(doc: MarkdownDoc, title: str) -> str:
    """The body of the H2 section ``title`` (empty when missing)."""
    span = doc.section(title)
    return "" if span is None else "\n".join(doc.lines[span[0]:span[1] - 1])


def numbered_items(doc: MarkdownDoc, title: str) -> int:
    """Numbered list items (``1. ...`` at the line start) of the H2 section ``title``."""
    return sum(1 for line in section_text(doc, title).splitlines() if _NUMBERED.match(line))


def check_reproduction(lint: Lint, path: Path, repro: Reproduction, registry: RecipeRegistry) -> None:
    """Every scenario, alias base, recipe, parameter, pin map, DUT profile and analysis method exists."""
    config = lint.config_dir
    known = scenario_names(config)
    for alias, spec in sorted(repro.scenarios.items()):
        if alias in known:
            lint.add("case", path, f"reproduction alias {alias!r} shadows the committed scenario of that name", 1)
        if spec.base not in known:
            lint.add("case", path, f"reproduction alias {alias!r}: scenario {spec.base!r} is not in "
                                   "config/sim/scenarios/", 1)
    for step in repro.steps:
        where = f"reproduction step {step.id!r}"
        scenario = repro.scenario_of(step)
        if scenario not in known and scenario not in repro.scenarios:
            lint.add("case", path, f"{where}: scenario {scenario!r} is neither in config/sim/scenarios/ nor an "
                                   "alias of reproduction.scenarios", 1)
        if step.recipe not in registry.ids():
            lint.add("case", path, f"{where}: recipe {step.recipe!r} is not registered", 1)
        else:
            unknown = sorted(set(step.params) - set(registry.get(step.recipe).params))
            if unknown:
                lint.add("case", path, f"{where}: {step.recipe} has no parameter(s) {unknown}", 1)
        if not config_exists(config, "pinmaps", step.pin_map):
            lint.add("case", path, f"{where}: pin map {step.pin_map!r} is not in config/pinmaps/", 1)
        if step.dut_profile is not None and not config_exists(config, "duts", step.dut_profile):
            lint.add("case", path, f"{where}: DUT profile {step.dut_profile!r} is not in config/duts/", 1)
        methods = [request.method for request in step.analyze]
        for method in sorted(set(methods)):
            if method not in ANALYSIS_METHODS:
                lint.add("case", path, f"{where}: analysis method {method!r} is not registered", 1)
            if methods.count(method) > 1:
                lint.add("case", path, f"{where}: analysis method {method!r} requested twice (results must be "
                                       "unique per method and quantity)", 1)
            if step.recipe in registry.ids() and any(a.method == method
                                                     for a in registry.get(step.recipe).analysis_defaults):
                lint.add("case", path, f"{where}: {method} is a default analysis of {step.recipe} already", 1)
    if repro.scenario not in known and repro.scenario not in repro.scenarios:
        lint.add("case", path, f"reproduction scenario {repro.scenario!r} is neither in config/sim/scenarios/ nor an "
                               "alias", 1)


def scenario_names(config_dir: Path) -> set[str]:
    """Committed simulator scenario names (``config/sim/scenarios/<name>.yaml``)."""
    folder = config_dir / "sim" / "scenarios"
    return {p.stem for p in folder.glob("*.yaml")} if folder.is_dir() else set()


def config_exists(config_dir: Path, folder: str, name: str) -> bool:
    """``config/<folder>/<name>.example.yaml`` or ``<name>.yaml`` exists (committed examples; ``config/local`` is the
    human's and never read here)."""
    return any((config_dir / folder / f"{name}{suffix}").is_file() for suffix in (".example.yaml", ".yaml"))
