"""Manual citation lint (blueprint 5.2), part of ``b1500 dev lint-skills`` and pytest; problem code ``citation``.

Scope: the skills (``.agents/skills/**/*.md``), recipes (``recipes/**/*.yaml``), source docstrings and comments
(``src/b1500_test_agent/**/*.py`` and its nested ``*.md``, which include the driver) and the docs (``docs/**/*.md``,
``README.md``, ``AGENTS.md``). ``references/`` is not linted (read-only extracts with their own page conventions), nor
is the generated ``.claude/skills/`` copy.

Forms checked against ``references/manuals/catalog.yaml`` and, when it exists, the page corpus:

- Canonical: ``<ID> p<N>[-<M>] [(<printed>)] ["<keyword>"]``, e.g. ``PG p433 (4-115)`` or ``PG p433 (4-115)
  "ERSSP"``. ``ID`` is a catalog id or any ``AN-<TOPIC>`` (an unknown one is a problem); ``1 <= N <= M <= pages``;
  the printed label must be the corpus label of page ``N``; the keyword (any case, whitespace-insensitive) must occur
  on pages ``N..M``.
- Legacy (v1 docs and docstrings): ``<ID> [Ed. <E>] PDF <N>[-<M>][, <K>...] [, printed <X>[ to <Y>]]`` with the
  same page-range check for every listed page and label checks for ``X`` (page ``N``) and ``Y`` (page ``M``).
  ``Ed. <E>`` selects the catalog edition (``WG Ed. 5`` = ``WG5``).

Without a corpus only ids and page ranges are checked (a note says so); without a catalog nothing is checked (note).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from b1500_test_agent.devtools.skills.common import Lint
from b1500_test_agent.manuals.catalog import ManualError, ManualPaths, load_catalog
from b1500_test_agent.manuals.search import Corpus, fold
from b1500_test_agent.models.manuals import ManualCatalog, ManualDoc

_ID = r"(?P<doc>AN-[A-Z0-9]{2,8}|[A-Z]{2,3}[0-9]?)"
_LABEL = r"[0-9A-Z]{1,3}-\s?\d{1,4}|\d{1,4}"
CANONICAL = re.compile(
    rf"(?<![\w-]){_ID} p(?P<p>\d{{1,5}})(?:\s?[–-]\s?p?(?P<p2>\d{{1,5}}))?(?![\w-])"
    rf"(?: \((?P<printed>{_LABEL})\))?"
    r"(?: [\"“](?P<kw>[^\"”\n]{1,80})[\"”])?"
)
LEGACY = re.compile(
    rf"(?<![\w-]){_ID}(?: Ed\. ?(?P<ed>\d{{1,2}}))? PDF (?P<list>\d{{1,5}}(?:\s?[–-]\s?\d{{1,5}})?"
    r"(?:, \d{1,5}(?:\s?[–-]\s?\d{1,5})?)*)(?![\w-])"
    rf"(?:(?:,|;| \(|) ?printed (?P<printed>{_LABEL})(?: to (?P<printed2>{_LABEL}))?)?"
)
_RANGE = re.compile(r"(\d{1,5})(?:\s?[–-]\s?(\d{1,5}))?")
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class Citation:
    """One citation found in a file: the text as written, its line, the resolved document id (or the problem with
    it), the cited page ranges and the printed labels / keyword it claims."""

    text: str
    line: int
    doc: str
    ranges: tuple[tuple[int, int], ...]
    printed: str = ""
    printed_end: str = ""
    keyword: str = ""
    problem: str = ""


def lint_files(root: Path, recipes_dir: Path) -> list[Path]:
    """The files in scope (see the module docstring), sorted."""
    files: set[Path] = set()
    skills = root / ".agents" / "skills"
    if skills.is_dir():
        files.update(skills.rglob("*.md"))
    if recipes_dir.is_dir():
        files.update(recipes_dir.rglob("*.yaml"))
    source = root / "src" / "b1500_test_agent"
    if source.is_dir():
        files.update(source.rglob("*.py"))
        files.update(source.rglob("*.md"))
    docs = root / "docs"
    if docs.is_dir():
        files.update(docs.rglob("*.md"))
    files.update(p for p in (root / "README.md", root / "AGENTS.md") if p.is_file())
    return sorted(p for p in files if p.is_file() and not p.is_symlink())


def _label_key(label: str) -> str:
    compact = "".join(label.split())
    return _DIGITS.sub(lambda m: str(int(m.group(0))), compact)


def _resolve(catalog: ManualCatalog, doc_id: str, edition: str | None) -> tuple[ManualDoc | None, str]:
    if edition is not None:
        for candidate in (f"{doc_id}{edition}", doc_id):
            doc = catalog.get(candidate)
            if doc is not None and re.match(rf"(?i)edition {edition}\b", doc.edition):
                return doc, ""
        return None, f"no catalog document {doc_id} Edition {edition}"
    doc = catalog.get(doc_id)
    return (doc, "") if doc else (None, f"unknown manual id {doc_id} (catalog: {', '.join(catalog.ids)})")


def find_citations(text: str, catalog: ManualCatalog) -> Iterator[Citation]:
    """Every citation in ``text``: canonical ones for catalog ids and ``AN-*``, legacy ones for catalog ids."""
    known = set(catalog.ids)
    for number, line in enumerate(text.splitlines(), 1):
        for match in CANONICAL.finditer(line):
            doc_id = match.group("doc")
            if doc_id not in known and not doc_id.startswith("AN-"):
                continue
            doc, problem = _resolve(catalog, doc_id, None)
            first = int(match.group("p"))
            last = int(match.group("p2") or first)
            yield Citation(match.group(0), number, doc.id if doc else doc_id, ((first, last),),
                           match.group("printed") or "", "", (match.group("kw") or "").strip(), problem)
        for match in LEGACY.finditer(line):
            doc_id = match.group("doc")
            if doc_id not in known and not doc_id.startswith("AN-"):
                continue
            doc, problem = _resolve(catalog, doc_id, match.group("ed"))
            ranges = tuple((int(a), int(b or a)) for a, b in _RANGE.findall(match.group("list")))
            yield Citation(match.group(0), number, doc.id if doc else doc_id, ranges, match.group("printed") or "",
                           match.group("printed2") or "", "", problem)


def citation_problems(citation: Citation, catalog: ManualCatalog, corpus: Corpus | None) -> list[str]:
    """What is wrong with one citation (empty when it checks out)."""
    if citation.problem:
        return [citation.problem]
    doc = catalog.get(citation.doc)
    assert doc is not None
    problems = []
    for first, last in citation.ranges:
        if not 1 <= first <= last <= doc.pages:
            problems.append(f"page {first}" + (f"-{last}" if last != first else "") +
                            f" is outside {doc.id} (PDF pages 1..{doc.pages})")
    if problems or corpus is None:
        return problems
    first, last = citation.ranges[0][0], citation.ranges[-1][1]
    for label, page in ((citation.printed, first), (citation.printed_end, last)):
        if not label:
            continue
        actual = corpus.printed(doc.id, page)
        if _label_key(label) != _label_key(actual):
            shown = f"is printed {actual}" if actual else "has no printed label"
            problems.append(f"printed label {label}: {doc.id} p{page} {shown}")
    if citation.keyword:
        wanted = " ".join(fold(citation.keyword).split())
        texts = [corpus.by_key[(doc.id, p)].text for p in range(first, last + 1) if (doc.id, p) in corpus.by_key]
        if not any(wanted in " ".join(fold(text).split()) for text in texts):
            problems.append(f"keyword {citation.keyword!r} does not occur on {doc.id} p{first}"
                            + (f"-{last}" if last != first else ""))
    return problems


def check_citations(lint: Lint) -> int:
    """Lint every citation under ``lint.root``; returns how many were checked (problems go to ``lint``)."""
    paths = ManualPaths(references=lint.root / "references" / "manuals", manuals_dir=lint.root,
                        repo_root=lint.root)
    if not paths.catalog.is_file():
        lint.notes.append(f"citations not checked: no manual catalog at {lint.rel(paths.catalog)}")
        return 0
    try:
        catalog = load_catalog(paths.catalog)
        corpus = Corpus.load(paths)
    except ManualError as exc:
        lint.add("citation", paths.catalog, str(exc))
        return 0
    count = 0
    for path in lint_files(lint.root, lint.recipes_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable skill files are reported by the layout checks
        for citation in find_citations(text, catalog):
            count += 1
            for problem in citation_problems(citation, catalog, corpus):
                lint.add("citation", path, f"{citation.text}: {problem}", citation.line)
    scope = "ids, pages, printed labels and keywords" if corpus else "ids and pages (no corpus: labels and " \
                                                                     "keywords not checked)"
    lint.notes.append(f"citations: {count} checked ({scope})")
    return count
