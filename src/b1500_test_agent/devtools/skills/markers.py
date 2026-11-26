"""Blank markers (v2.1 KD-1, KD-8): the ``TODO(owner)`` / ``TODO(verify)[<step ids>]`` / ``TODO(cite)`` lint of
``b1500 dev lint-skills`` and the owner questions that ``b1500 dev gen-index`` collects into
``docs/open-questions.md`` (``devtools/skills/questions.py``).

A value nobody has a source for is left blank with one marker (knowledge ``README.md`` "Conventions"):

- ``TODO(owner): <question>?`` — only the owner knows it (device, film, process, station, lab practice). A colon
  follows the marker (after its closing backtick in Markdown), then one question that ends with ``?`` within
  ``MAX_QUESTION_CHARS`` characters; a ``?`` inside a backtick code span (``ERSSP?``) does not end it. The question
  may run over the following lines of the same paragraph or comment block.
- ``TODO(verify)[<step ids>]`` — a hardware measurement at bring-up gives it: the brackets name steps of
  ``.agents/skills/b1500-bringup/steps.yaml`` (``L6.A2``; several separated by commas), each of which must exist.
  The stage files' summary line ``- TODO(verify) (blueprint v2 7.6 items <n>, ...)`` keeps its form: the steps that
  settle those items carry them in ``steps.yaml`` (``items:``).
- ``TODO(cite)`` — a literature or data-sheet value that needs a checked source.

Accepted mentions (text about the markers, not a blank): the combined form ``TODO(owner|verify|cite)`` (any two or
three kinds), placeholders (``TODO(verify)[<step ids>]``, ``TODO(owner): <question ending with ?>``) and the files of
``CONVENTION_FILES`` (the convention text itself, the templates and the lint's own code). Everything else is a
problem: ``todo_verify`` (no step ids, an unknown step), ``todo_owner`` (no question), ``todo_marker`` (an unknown
kind such as ``TODO(later)`` or a bare ``TODO``).

Scope (``marker_files``): the skills (``.agents/skills/**``, ``*.md``/``*.yaml``), ``src/b1500_test_agent/**``
(``*.py``, ``*.md``), ``docs/**/*.md`` without ``docs/design/`` (plan history) and ``docs/acceptance/`` (dated
reports), ``README.md``, ``AGENTS.md``, ``CLAUDE.md``, ``recipes/**/*.yaml`` and ``config/**/*.yaml`` without
``config/local/`` (the human's files, never read); a recipe or config folder outside the root (a fixture tree linted
with the repository's config) is not scanned. Generated files (``GENERATED_FILES``) are skipped; tests are not
in scope (fixtures and assertions quote markers on purpose). Debug cases keep their owner questions as the numbered
items of "Open questions for the owner" (the case lint, ``cases.py``), so their ``TODO(owner)`` markers are left to
that lint.
"""


from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Final, Literal

from b1500_test_agent.devtools.skills.common import STAGES, Lint, ProblemCode

KINDS: Final = ("owner", "verify", "cite")
MAX_QUESTION_CHARS: Final = 700
"""Longest owner question (characters, whitespace collapsed); a longer run without ``?`` is a missing question."""
STEP_ID: Final = re.compile(r"^(?:[DRE]\d+|(?:S0|L\d+)\.(?:[PA]\d+|R))$")
"""Shape of a ``steps.yaml`` id (``D3``, ``R1``, ``E2``, ``L6.A2``, ``S0.P5``, ``L4.R``)."""

CONVENTION_FILES: Final[tuple[str, ...]] = (
    ".agents/skills/b1500-test/knowledge/README.md",  # defines the markers (section "Conventions")
    ".agents/skills/*/cards/_TEMPLATE.md",  # templates: placeholders and the rules for the files made from them
    ".agents/skills/*/stages/_TEMPLATE.md",
    ".agents/skills/*/cases/_TEMPLATE.md",
    ".agents/skills/*/records/_TEMPLATE.yaml",
    "src/b1500_test_agent/devtools/*",  # the lint, the generator and the case lint name the markers
)
"""Files whose markers are mentions (definitions, templates, the lint's own code): neither checked nor collected."""
GENERATED_FILES: Final[tuple[str, ...]] = (
    "docs/open-questions.md", "docs/coverage.md", ".agents/skills/b1500-test/cards/README.md")
CASES_GLOB: Final = ".agents/skills/b1500-debug/cases/*.md"

_MARKER = re.compile(r"TODO\((?P<body>[^)\n]{0,40})\)")
_BARE = re.compile(r"\bTODO\b(?!\()")
_COMBINED = re.compile(r"^(?:owner|verify|cite)(?:\|(?:owner|verify|cite))+$")
_SUMMARY = re.compile(r"^ \(blueprint v2 7\.6 items? ")
_LEADER = re.compile(r"^\s*(?:#+(?=\s|$)|//)?\s*")
_STOP_MD = re.compile(r"^\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s|\||```|~~~)")

MarkerKind = Literal["owner", "verify", "cite"]
MarkerForm = Literal["live", "placeholder", "summary"]


@dataclass(frozen=True)
class Marker:
    """One marker as written: kind, form, file (repository-relative, POSIX), line, and for ``verify`` the step ids,
    for ``owner`` the question (whitespace collapsed, ending with ``?``)."""

    kind: MarkerKind
    form: MarkerForm
    file: str
    line: int
    ids: tuple[str, ...] = ()
    question: str = ""


@dataclass(frozen=True)
class MarkerProblem:
    code: ProblemCode
    file: str
    line: int
    message: str


def _matches(rel: str, patterns: Collection[str]) -> bool:
    return any(fnmatch(rel, pattern) for pattern in patterns)


def marker_files(root: Path, recipes_dir: Path | None = None, config_dir: Path | None = None) -> list[Path]:
    """The files in scope under ``root`` (module docstring), sorted; convention and generated files excluded."""
    recipes_dir = recipes_dir or root / "recipes"
    config_dir = config_dir or root / "config"
    found: set[Path] = set()
    skills = root / ".agents" / "skills"
    if skills.is_dir():
        found.update(p for pattern in ("*.md", "*.yaml") for p in skills.rglob(pattern))
    source = root / "src" / "b1500_test_agent"
    if source.is_dir():
        found.update(p for pattern in ("*.py", "*.md") for p in source.rglob(pattern))
    docs = root / "docs"
    if docs.is_dir():
        found.update(p for p in docs.rglob("*.md")
                     if not {"design", "acceptance"} & set(p.relative_to(docs).parts[:1]))
    found.update(p for p in (root / "README.md", root / "AGENTS.md", root / "CLAUDE.md") if p.is_file())
    if recipes_dir.is_dir() and recipes_dir.resolve().is_relative_to(root.resolve()):
        found.update(recipes_dir.rglob("*.yaml"))
    if config_dir.is_dir() and config_dir.resolve().is_relative_to(root.resolve()):
        found.update(p for p in config_dir.rglob("*.yaml") if "local" not in p.relative_to(config_dir).parts[:1])
    out = []
    for path in sorted(found):
        rel = relpath(root, path)
        if path.is_file() and not path.is_symlink() and not _matches(rel, CONVENTION_FILES + GENERATED_FILES):
            out.append(path)
    return out


def relpath(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _continuation(text: str, start: int, markdown: bool) -> str:
    """The text from ``start`` to the end of its paragraph or comment block, comment leaders removed, whitespace
    collapsed (at most a few lines; the question must end before)."""
    first, *rest = text[start:start + 4 * MAX_QUESTION_CHARS].split("\n")
    parts = [first]
    for raw in rest[:12]:
        if markdown and _STOP_MD.match(raw):
            break
        line = _LEADER.sub("", raw, count=1).strip()
        if not line or line in ('"""', "'''"):
            break
        parts.append(line)
    return " ".join(" ".join(parts).split())


def _question(after: str) -> str | None:
    """The question at the start of ``after``: up to the first ``?`` outside a backtick code span, within
    ``MAX_QUESTION_CHARS``; ``None`` when there is none."""
    ticks = 0
    for index, char in enumerate(after[:MAX_QUESTION_CHARS]):
        if char == "`":
            ticks ^= 1
        elif char == "?" and not ticks:
            return after[:index + 1].strip()
    return None


def scan_text(text: str, rel: str) -> tuple[list[Marker], list[MarkerProblem]]:
    """Every marker of one file's text and the problems of its form (step ids are checked by ``check_markers``)."""
    markers: list[Marker] = []
    problems: list[MarkerProblem] = []
    markdown = rel.endswith(".md")
    case_file = _matches(rel, (CASES_GLOB,))
    for match in _BARE.finditer(text):
        problems.append(MarkerProblem("todo_marker", rel, _line_of(text, match.start()),
                                      "a bare TODO: use TODO(owner): <question>?, TODO(verify)[<step ids>] or "
                                      "TODO(cite) (knowledge README, Conventions)"))
    for match in _MARKER.finditer(text):
        body, line = match.group("body"), _line_of(text, match.start())
        if _COMBINED.match(body):
            continue  # a mention of several kinds
        if body not in KINDS:
            problems.append(MarkerProblem("todo_marker", rel, line, f"unknown marker TODO({body}): use "
                                          "TODO(owner), TODO(verify)[<step ids>] or TODO(cite)"))
            continue
        after = text[match.end():].removeprefix("`")
        if body == "cite":
            markers.append(Marker("cite", "live", rel, line))
        elif body == "verify":
            marker = _verify(after, rel, line, problems)
            if marker is not None:
                markers.append(marker)
        elif not case_file:
            marker = _owner(text, len(text) - len(after), rel, line, markdown, problems)
            if marker is not None:
                markers.append(marker)
    return markers, problems


def _verify(after: str, rel: str, line: int, problems: list[MarkerProblem]) -> Marker | None:
    if after.startswith("["):
        end = after.find("]", 0, 200)
        content = after[1:end] if end > 0 else ""
        if end < 0 or not content.strip():
            problems.append(MarkerProblem("todo_verify", rel, line, "TODO(verify)[...] needs a closing ']' after "
                                          "the step ids"))
            return None
        if content.strip().startswith("<"):
            return Marker("verify", "placeholder", rel, line)
        ids = tuple(part.strip() for part in content.split(","))
        bad = [i for i in ids if not STEP_ID.match(i)]
        if bad:
            problems.append(MarkerProblem("todo_verify", rel, line, f"TODO(verify)[{content}]: {', '.join(bad)} "
                                          "is not a step id (L6.A2, S0.P5, D3; several separated by commas)"))
            return None
        return Marker("verify", "live", rel, line, ids=ids)
    if _SUMMARY.match(after):
        return Marker("verify", "summary", rel, line)
    problems.append(MarkerProblem("todo_verify", rel, line, "TODO(verify) without step ids: name the bring-up steps "
                                  "that record the fact, TODO(verify)[<step ids>] (steps.yaml); a fact no step can "
                                  "record is reworded or, for a data-sheet or literature value, TODO(cite)"))
    return None


def _owner(text: str, start: int, rel: str, line: int, markdown: bool,
           problems: list[MarkerProblem]) -> Marker | None:
    rest = _continuation(text, start, markdown)
    if rest.startswith(":"):
        body = rest[1:].strip()
        if body.startswith("<"):
            return Marker("owner", "placeholder", rel, line)
        question = _question(body)
        if question:
            return Marker("owner", "live", rel, line, question=question)
    problems.append(MarkerProblem("todo_owner", rel, line, "TODO(owner) needs its question: `TODO(owner)`: <the "
                                  f"exact question>? (ending with '?' within {MAX_QUESTION_CHARS} characters)"))
    return None


def scan_files(root: Path, recipes_dir: Path | None = None,
               config_dir: Path | None = None) -> tuple[list[Marker], list[MarkerProblem]]:
    """Markers and form problems of every file in scope (unreadable files are skipped: the layout checks report
    them)."""
    markers: list[Marker] = []
    problems: list[MarkerProblem] = []
    for path in marker_files(root, recipes_dir, config_dir):
        try:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            continue
        found, wrong = scan_text(text, relpath(root, path))
        markers += found
        problems += wrong
    return markers, problems


def unknown_steps(markers: list[Marker], step_ids: Collection[str]) -> Iterator[MarkerProblem]:
    """``todo_verify`` problems for step ids that ``steps.yaml`` does not have. A stage step whose stage has no steps
    in this tree (a partial fixture tree; the repository has steps for every stage) is not checked, unless the
    stage itself is no bring-up stage at all."""
    known = set(step_ids)
    stages = {i.split(".", 1)[0] for i in known if "." in i}
    for marker in markers:
        missing = [i for i in marker.ids if i not in known
                   and ("." not in i or i.split(".", 1)[0] in stages or i.split(".", 1)[0] not in STAGES)]
        if missing:
            yield MarkerProblem("todo_verify", marker.file, marker.line,
                                f"TODO(verify)[{', '.join(marker.ids)}]: no step {', '.join(missing)} in "
                                ".agents/skills/b1500-bringup/steps.yaml")


def check_markers(lint: Lint, step_ids: Collection[str] | None) -> list[Marker]:
    """Lint every marker under ``lint.root`` (problems to ``lint``, one note with the counts); returns the markers.
    ``step_ids`` ``None`` (no valid ``steps.yaml``): the step ids are not checked (a note says so)."""
    markers, problems = scan_files(lint.root, lint.recipes_dir, lint.config_dir)
    if step_ids is not None:
        problems += list(unknown_steps(markers, step_ids))
    for problem in problems:
        lint.add(problem.code, problem.file, problem.message, problem.line)
    count = {kind: sum(1 for m in markers if m.kind == kind and m.form == "live") for kind in KINDS}
    ids = {i for m in markers for i in m.ids}
    summaries = sum(1 for m in markers if m.form == "summary")
    checked = "" if step_ids is not None else " (step ids not checked: no valid steps.yaml)"
    lint.notes.append(f"markers: TODO(owner) {count['owner']} (questions for docs/open-questions.md), "
                      f"TODO(verify)[...] {count['verify']} naming {len(ids)} steps{checked}, stage summary lines "
                      f"{summaries}, TODO(cite) {count['cite']}")
    return markers
