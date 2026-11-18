"""Manual corpus models (blueprint 5.2): the committed catalog of Keysight PDFs, the page corpus built from them and
the results of the read-only ``b1500 manual`` commands.

The catalog (``references/manuals/catalog.yaml``) names every indexed PDF by a short id (``PG``, ``WG``,
``AN-RTN`` ...) and pins its file, edition, sha256 and page count; it holds no manual text. The corpus
(``references/manuals/corpus/``) holds one ``CorpusPage`` per PDF page and the PDF outlines (``CorpusOutline``).
Citations in skills, recipes, driver docstrings and docs read ``PG p433 (4-115)``: doc id, physical 1-based PDF page,
optional printed page label (``ManualHit.cite``).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from b1500_test_agent.models.common import Sha256Hex, StrictModel

DocId = Annotated[str, Field(pattern=r"^(?:[A-Z]{2,3}[0-9]?|AN-[A-Z]{2,6})$")]
"""Short manual id: two or three capitals with an optional edition digit (``PG``, ``WG5``) or ``AN-<TOPIC>`` for an
application note."""

DocKind = Literal[
    "programming_guide", "user_guide", "software_guide", "configuration_guide", "accessories_guide", "data_sheet",
    "app_note", "tutorial",
]  # fmt: skip
"""What a manual is (used for display and to tell reference manuals from application material)."""

Language = Literal["en", "zh"]
"""Main language of a manual's text (``zh`` = Simplified Chinese)."""

SourceKind = Literal["corpus", "extracts"]
"""Where a manual answer came from: the page corpus or, without one, the structured extracts."""

CorpusState = Literal["current", "stale", "missing", "invalid"]
"""Corpus state: built from this catalog, built from another catalog (rebuild), absent, or unreadable."""

MatchMode = Literal["all", "any", "synonyms", "none"]
"""How a search matched: every term (AND), any term (OR-relaxed), with synonym expansion, or not at all."""

_SYMBOL_KEY = re.compile(r"^[0-9A-F]{4}$")
_PRIVATE_USE = range(0xE000, 0xF900)


class ManualDoc(StrictModel):
    """One indexed PDF of the catalog.

    ``file`` is a POSIX path relative to the manuals folder (``Settings.manuals_dir``, default the clone's parent;
    ``B1500_MANUALS_DIR`` overrides). ``label_rule`` is a regular expression with at least one capture group, matched
    against each of the first and last three non-empty lines of a page; the first non-empty group is the printed page
    label (e.g. ``4-189``). ``size`` (bytes) and ``sha256`` let the build find a renamed or moved copy. ``priority``
    multiplies search scores (reference manuals > application material).
    ``extracts`` are files under ``references/manuals/`` (curated extracts and indexes of this manual) that answer
    queries when no corpus is built.
    """

    id: DocId
    file: str = Field(min_length=5, pattern=r"(?i)^[^\\:]+\.pdf$")
    title: str = Field(min_length=1)
    edition: str = Field(min_length=1)
    part_number: str = ""
    sha256: Sha256Hex
    size: int = Field(gt=0)
    pages: int = Field(ge=1, le=10_000)
    language: Language
    kind: DocKind
    priority: float = Field(default=1.0, ge=0.1, le=3.0)
    label_rule: str = Field(min_length=1)
    extracts: list[str] = Field(default_factory=list)
    note: str = ""

    @field_validator("label_rule")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            pattern = re.compile(value)
        except re.error as exc:
            raise ValueError(f"label_rule is not a valid regular expression: {exc}") from None
        if pattern.groups < 1:
            raise ValueError("label_rule needs at least one capture group (the printed page label)")
        return value

    @field_validator("file", "extracts")
    @classmethod
    def _relative_posix(cls, value: str | list[str]) -> str | list[str]:
        for item in [value] if isinstance(value, str) else value:
            parts = item.split("/")
            if item.startswith("/") or ".." in parts or "\\" in item or ":" in item:
                raise ValueError(f"{item!r} must be a relative POSIX path without '..', '\\' or ':'")
        return value


class ManualCatalog(StrictModel):
    """``references/manuals/catalog.yaml``: the symbol table for private-use glyphs and the indexed documents.

    ``symbols`` maps a private-use code point (four hex digits, U+E000..U+F8FF; the manuals' Symbol and Wingdings
    fonts land at U+F0xx) to its text; an unlisted code in U+F020..U+F07E becomes the ASCII character it encodes.
    """

    version: Literal[1] = 1
    symbols: dict[str, str] = Field(default_factory=dict)
    docs: list[ManualDoc] = Field(min_length=1)

    @field_validator("symbols")
    @classmethod
    def _private_use(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if not _SYMBOL_KEY.match(key) or int(key, 16) not in _PRIVATE_USE:
                raise ValueError(f"symbol key {key!r} is not a private-use code point written as four hex digits")
        return value

    @model_validator(mode="after")
    def _unique(self) -> ManualCatalog:
        ids = [doc.id for doc in self.docs]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate document ids: {sorted({i for i in ids if ids.count(i) > 1})}")
        files = [doc.file for doc in self.docs]
        if len(set(files)) != len(files):
            raise ValueError("two documents name the same file")
        return self

    def get(self, doc_id: str) -> ManualDoc | None:
        """The document with id ``doc_id`` (exact, case-sensitive) or ``None``."""
        return next((doc for doc in self.docs if doc.id == doc_id), None)

    @property
    def ids(self) -> list[str]:
        return [doc.id for doc in self.docs]

    @property
    def total_pages(self) -> int:
        return sum(doc.pages for doc in self.docs)


class Synonyms(StrictModel):
    """``references/manuals/synonyms.yaml``: a query word (any case) → extra search terms, used only when a search
    finds nothing with its own terms (blueprint 5.2: "zero hits → OR-relax, then synonyms")."""

    synonyms: dict[str, list[str]] = Field(default_factory=dict)


# -- corpus ------------------------------------------------------------------------------------------------------------


class CorpusPage(StrictModel):
    """One line of ``corpus/pages.jsonl.gz``: a PDF page's text with its printed label and outline path.

    ``printed`` is ``""`` when the page carries no label (cover, front matter); chapter title pages get the label
    their numbering implies (``2-1`` before ``2-2``). ``outline_path`` joins the PDF outline titles in effect on the
    page with `` > ``.
    """

    doc: str
    p: int = Field(ge=1)
    printed: str
    outline_path: str
    text: str


class OutlineEntry(StrictModel):
    """One PDF outline (bookmark) entry: depth (0 = top), title and the 1-based PDF page it points to."""

    level: int = Field(ge=0)
    title: str
    p: int = Field(ge=1)


class DocOutline(StrictModel):
    """Per-document record of ``corpus/outline.json``: the source PDF's sha256 and page count, the characters of
    page text kept, and the outline."""

    sha256: Sha256Hex
    pages: int = Field(ge=1)
    chars: int = Field(ge=0)
    outline: list[OutlineEntry]


class CorpusOutline(StrictModel):
    """``corpus/outline.json``: format version, the build digest of the catalog it was built from (a different
    digest means the corpus is stale) and one ``DocOutline`` per document in catalog order."""

    format: Literal[1] = 1
    catalog: Sha256Hex
    docs: dict[str, DocOutline]


# -- command results ---------------------------------------------------------------------------------------------------


class ManualHit(StrictModel):
    """One search hit. ``cite`` is the citation to use (``PG p433 (4-115)``); an answer from the structured extracts
    has ``source`` ``extracts``, ``ref`` = ``<file>:L<line>`` and ``p`` only when the extract names a PDF page."""

    doc: str
    p: int | None
    printed: str = ""
    title: str = ""
    outline_path: str = ""
    score: float
    title_hit: bool = False
    cite: str
    snippet: str
    source: SourceKind = "corpus"
    ref: str = ""


class ManualSearchResult(StrictModel):
    """``b1500 manual search``: the hits, how they matched and where they came from."""

    ok: bool
    source: SourceKind
    query: str
    docs: list[str]
    match: MatchMode
    terms: list[str]
    hits: list[ManualHit]
    message: str


class PageText(StrictModel):
    """One page (or, without a corpus, one extract excerpt) shown by ``b1500 manual page``."""

    doc: str
    p: int | None
    printed: str = ""
    outline_path: str = ""
    cite: str
    text: str
    truncated: bool = False
    ref: str = ""


class ManualPageResult(StrictModel):
    """``b1500 manual page``: up to three pages of text (``max_chars`` in total)."""

    ok: bool
    source: SourceKind
    doc: str
    pages: list[PageText]
    message: str


class TocEntry(StrictModel):
    """One line of ``b1500 manual toc``: outline depth, title, PDF page and its printed label."""

    level: int
    title: str
    p: int | None
    printed: str = ""


class ManualTocResult(StrictModel):
    """``b1500 manual toc``: the PDF outline of one document (filtered by ``--grep``)."""

    ok: bool
    source: SourceKind
    doc: str
    entries: list[TocEntry]
    message: str


class DocStatus(StrictModel):
    """Per-document line of ``b1500 manual status``: corpus pages and the PDF's state in the manuals folder.

    ``pdf`` is ``ok`` (sha256 matches the catalog), ``mismatch`` (another edition or a modified file at the
    catalog path or matched by name), or ``missing``."""

    id: str
    title: str
    edition: str
    pages: int
    corpus_pages: int
    pdf: Literal["ok", "mismatch", "missing"]
    path: str = ""
    note: str = ""


class ManualStatus(StrictModel):
    """``b1500 manual status``: is the corpus built and current, which PDFs are present (they are optional)."""

    ok: bool
    corpus: CorpusState
    corpus_dir: str
    corpus_bytes: int
    docs_in_corpus: int
    pages_in_corpus: int
    catalog_docs: int
    catalog_pages: int
    manuals_dir: str
    manuals_dir_source: str
    pdfs_found: int
    docs: list[DocStatus]
    message: str


class DocBuild(StrictModel):
    """Per-document outcome of ``b1500 manual build``."""

    id: str
    path: str = ""
    pdf: Literal["ok", "mismatch", "missing"]
    pages: int = 0
    labelled: int = 0
    outline: int = 0
    chars: int = 0
    check: Literal["identical", "differs", "not_checked"] = "not_checked"


class ManualBuildReport(StrictModel):
    """``b1500 manual build [--check]``: what was extracted, written or compared, and every warning and problem."""

    ok: bool
    mode: Literal["build", "check"]
    manuals_dir: str
    corpus_dir: str
    docs: list[DocBuild]
    pages: int
    corpus_bytes: int
    seconds: float
    identical: bool | None = None
    warnings: list[str]
    problems: list[str]
    message: str
