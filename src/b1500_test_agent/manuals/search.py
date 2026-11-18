"""Read-only manual queries (blueprint 5.2): ``search``, ``page``, ``toc`` and ``status`` over the committed corpus.

Search is pure-Python BM25 (k1 1.2, b 0.75), built in memory per call (no index file). Text and query are folded
(NFKC + casefold) and tokenised into ASCII words and mnemonics kept whole (``erssp``, ``b1500a``, ``4``), whole
``WGFMU_*`` names, and CJK bigrams (a lone CJK character stays a unigram); a few English stop words are dropped. A
page's own outline title counts ``TITLE_WEIGHT`` extra times; each document's ``priority`` multiplies its scores.
Matching: every term first (AND); zero hits → any term (OR); still zero → the query plus synonyms from
``synonyms.yaml`` (OR). Exact outline-title hits rank first (a query word equal to a command or function title such
as ``ERSSP`` or ``WGFMU_setMeasureEvent``, or the whole query equal to any title), the more authoritative document
first. Hits read ``PG p433 (4-115) · ERSSP · <snippet>`` with snippets of at most ``SNIPPET_CHARS`` characters.

``page`` shows at most ``MAX_PAGES`` consecutive pages (``max_chars`` in total); ``--printed`` finds a page by its
printed label. ``toc`` lists a PDF outline with printed labels. ``status`` reports the corpus (current, stale,
missing) and which PDFs are present.

Without a corpus every query answers from the structured extracts named in the catalog (``references/manuals/``:
indexes and ``structured/`` files, chunked into table rows, paragraphs and YAML items) and says how to build the
corpus. Nothing here writes a file.
"""

from __future__ import annotations

import gzip
import itertools
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from b1500_test_agent.manuals.catalog import (
    ManualError,
    ManualPaths,
    build_digest,
    load_catalog,
    load_synonyms,
    locate_pdfs,
)
from b1500_test_agent.models.manuals import (
    CorpusOutline,
    CorpusPage,
    CorpusState,
    DocStatus,
    ManualCatalog,
    ManualDoc,
    ManualHit,
    ManualPageResult,
    ManualSearchResult,
    ManualStatus,
    ManualTocResult,
    MatchMode,
    PageText,
    TocEntry,
)

K1 = 1.2
B = 0.75
TITLE_WEIGHT = 2
DEFAULT_K = 8
MAX_K = 50
SNIPPET_CHARS = 240
MAX_PAGES = 3
DEFAULT_MAX_CHARS = 6000
MIN_MAX_CHARS = 200

_CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿"
_TOKEN = re.compile(rf"wgfmu_[0-9a-z_]+|[{_CJK}]+|[^\W_{_CJK}]+")
_CJK_RUN = re.compile(rf"^[{_CJK}]+$")
_COMMAND_TITLE = re.compile(r"^\*?[A-Z][A-Z0-9]{1,15}\??$|^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+$")
"""An outline title that names a command or function (``ERSSP``, ``ERSSP?``, ``*RST``, ``WGFMU_setMeasureEvent``)."""
_DIGITS = re.compile(r"\d+")
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from", "has", "have", "if", "in", "into", "is",
    "it", "its", "may", "no", "not", "of", "on", "or", "so", "such", "than", "that", "the", "their", "then", "there",
    "these", "this", "to", "was", "were", "when", "which", "will", "with", "you", "your",
})


# -- text ------------------------------------------------------------------------------------------------------------


def fold(text: str) -> str:
    """NFKC + casefold: the comparison form of text, queries and titles (``µA`` = ``μa``, full width = ASCII)."""
    return unicodedata.normalize("NFKC", text).casefold()


def tokenize(text: str) -> list[str]:
    """Search tokens of ``text`` (see the module docstring)."""
    tokens: list[str] = []
    for match in _TOKEN.finditer(fold(text)):
        token = match.group(0)
        if _CJK_RUN.match(token):
            tokens.extend([token] if len(token) == 1 else [token[i:i + 2] for i in range(len(token) - 1)])
        elif token not in STOPWORDS:
            tokens.append(token)
    return tokens


def unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _label_key(label: str) -> str:
    compact = "".join(fold(label).split())
    return _DIGITS.sub(lambda m: str(int(m.group(0))), compact)


def _title_key(text: str) -> str:
    return " ".join(fold(text).split())


def cite(doc: str, p: int | None, printed: str = "") -> str:
    """The citation form: ``PG p433 (4-115)``; ``PG p433`` without a printed label."""
    if p is None:
        return doc
    return f"{doc} p{p} ({printed})" if printed else f"{doc} p{p}"


def snippet(text: str, terms: Sequence[str], limit: int = SNIPPET_CHARS) -> str:
    """At most ``limit`` characters of ``text`` (whitespace collapsed) around the first of ``terms`` found."""
    flat = " ".join(text.split())
    position = -1
    for term in terms:
        match = re.search(re.escape(term), flat, re.IGNORECASE)
        if match is None:
            folded = fold(flat)
            index = folded.find(term)
            position = min(index, len(flat) - 1) if index >= 0 else -1
        else:
            position = match.start()
        if position >= 0:
            break
    start = max(0, position - 60) if position >= 0 else 0
    body = flat[start:]
    prefix = "…" if start > 0 else ""
    if len(prefix) + len(body) <= limit:
        return prefix + body
    return prefix + body[: limit - len(prefix) - 1].rstrip() + "…"


# -- BM25 -------------------------------------------------------------------------------------------------------------


class Bm25:
    """BM25 over token bags; ``weights`` multiply each bag's score (document priority)."""

    def __init__(self, bags: Sequence[Counter[str]], weights: Sequence[float]) -> None:
        self.weights = list(weights)
        self.lengths = [sum(bag.values()) for bag in bags]
        self.average = (sum(self.lengths) / len(bags)) if bags else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for index, bag in enumerate(bags):
            for term, count in bag.items():
                self.postings.setdefault(term, []).append((index, count))
        self.size = len(bags)

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1.0 + (self.size - df + 0.5) / (df + 0.5))

    def score(self, terms: Sequence[str], *, require_all: bool) -> dict[int, float]:
        """Score of every bag that holds all (``require_all``) or any of ``terms``."""
        terms = unique(terms)
        if not terms or self.size == 0:
            return {}
        scores: dict[int, float] = {}
        seen: Counter[int] = Counter()
        for term in terms:
            idf = self.idf(term)
            for index, count in self.postings.get(term, ()):
                norm = K1 * (1 - B + B * self.lengths[index] / (self.average or 1.0))
                scores[index] = scores.get(index, 0.0) + idf * count * (K1 + 1) / (count + norm)
                seen[index] += 1
        if require_all:
            scores = {i: s for i, s in scores.items() if seen[i] == len(terms)}
        return {i: s * self.weights[i] for i, s in scores.items()}


def _query_words(query: str) -> list[str]:
    return [word for word in fold(query).split() if word]


def _expand(query: str, terms: list[str], synonyms: dict[str, list[str]]) -> list[str]:
    folded = {fold(key).strip(): values for key, values in synonyms.items()}
    extra: list[str] = []
    for key in [_title_key(query), *_query_words(query), *terms]:
        if key in folded:
            extra += tokenize(" ".join(folded[key]))
    return unique([*terms, *extra])


def _ranked(index: Bm25, terms: list[str], query: str, synonyms: dict[str, list[str]]
            ) -> tuple[MatchMode, dict[int, float], list[str]]:
    scores = index.score(terms, require_all=True)
    if scores:
        return "all", scores, terms
    scores = index.score(terms, require_all=False)
    if scores:
        return "any", scores, terms
    expanded = _expand(query, terms, synonyms)
    if expanded != terms:
        scores = index.score(expanded, require_all=False)
        if scores:
            return "synonyms", scores, expanded
    return "none", {}, terms


# -- corpus -----------------------------------------------------------------------------------------------------------


@dataclass
class Corpus:
    """The loaded corpus: pages in file order, the outline file, and an index by (doc, page)."""

    pages: list[CorpusPage]
    outline: CorpusOutline
    by_key: dict[tuple[str, int], CorpusPage] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_key = {(page.doc, page.p): page for page in self.pages}

    @classmethod
    def load(cls, paths: ManualPaths) -> Corpus | None:
        """The corpus under ``paths.corpus_dir``; ``None`` when either file is missing; ``ManualError`` when one is
        unreadable."""
        if not (paths.pages.is_file() and paths.outline.is_file()):
            return None
        try:
            outline = CorpusOutline.model_validate_json(paths.outline.read_bytes())
            with gzip.open(paths.pages, "rt", encoding="utf-8") as handle:
                pages = [CorpusPage.model_validate_json(line) for line in handle if line.strip()]
        except (OSError, EOFError, ValueError, ValidationError) as exc:
            raise ManualError(f"the manual corpus at {paths.display(paths.corpus_dir)} is unreadable ({exc}); "
                              "rebuild it with uv run b1500 manual build or restore it with git") from None
        return cls(pages, outline)

    def doc_pages(self, doc: str) -> list[CorpusPage]:
        return [page for page in self.pages if page.doc == doc]

    def printed(self, doc: str, p: int) -> str:
        page = self.by_key.get((doc, p))
        return page.printed if page else ""


@dataclass
class Context:
    """What every query needs: paths, catalog, synonyms and the corpus (``None`` = answer from the extracts)."""

    paths: ManualPaths
    catalog: ManualCatalog
    corpus: Corpus | None
    synonyms: dict[str, list[str]]

    @classmethod
    def load(cls, paths: ManualPaths) -> Context:
        catalog = load_catalog(paths.catalog)
        return cls(paths, catalog, Corpus.load(paths), load_synonyms(paths.synonyms).synonyms)

    def doc(self, doc_id: str) -> ManualDoc:
        doc = self.catalog.get(doc_id.upper()) or self.catalog.get(doc_id)
        if doc is None:
            raise ManualError(f"unknown manual {doc_id!r}; ids: {', '.join(self.catalog.ids)}", usage=True)
        return doc

    def select(self, docs: Sequence[str] | None) -> list[ManualDoc]:
        return list(self.catalog.docs) if not docs else [self.doc(d) for d in docs]

    @property
    def stale_note(self) -> str:
        if self.corpus is not None and self.corpus.outline.catalog != build_digest(self.catalog):
            return " (corpus is stale: the catalog changed since it was built; run uv run b1500 manual build)"
        return ""

    def no_corpus_note(self) -> str:
        return (f"No manual corpus at {self.paths.display(self.paths.pages)}: answered from the structured extracts "
                f"(references/manuals/). Build it with `uv run b1500 manual build` (needs the PDFs in "
                f"{self.paths.display(self.paths.manuals_dir)}; set B1500_MANUALS_DIR or settings.manuals_dir).")


def search(paths: ManualPaths, query: str, *, docs: Sequence[str] | None = None, k: int = DEFAULT_K
           ) -> ManualSearchResult:
    """Search the corpus (or, without one, the extracts); see the module docstring."""
    if not 1 <= k <= MAX_K:
        raise ManualError(f"-k must be 1..{MAX_K}", usage=True)
    ctx = Context.load(paths)
    selected = ctx.select(docs)
    terms = unique(tokenize(query))
    if not terms:
        raise ManualError("the query has no searchable words", usage=True)
    if ctx.corpus is None:
        return _extract_search(ctx, query, terms, selected, k)
    corpus = ctx.corpus
    priority = {doc.id: doc.priority for doc in selected}
    pages = [page for page in corpus.pages if page.doc in priority]
    bags = []
    for page in pages:
        bag = Counter(tokenize(page.text))
        title = page.outline_path.rsplit(" > ", 1)[-1]
        for token in tokenize(title):
            bag[token] += TITLE_WEIGHT
        bags.append(bag)
    index = Bm25(bags, [priority[page.doc] for page in pages])
    match, scores, used = _ranked(index, terms, query, ctx.synonyms)
    position = {(page.doc, page.p): i for i, page in enumerate(pages)}
    titled = _title_hits(corpus, query, selected, position)
    order = {doc.id: n for n, doc in enumerate(selected)}
    first = sorted(titled, key=lambda i: (-priority[pages[i].doc], -scores.get(i, 0.0), order[pages[i].doc],
                                          pages[i].p))
    rest = sorted((i for i in scores if i not in titled), key=lambda i: (-scores[i], order[pages[i].doc], pages[i].p))
    ranked = [*first, *rest][:k]
    focus = sorted(used, key=lambda t: -index.idf(t))
    rules = {doc.id: re.compile(doc.label_rule) for doc in selected}
    hits = [ManualHit(doc=pages[i].doc, p=pages[i].p, printed=pages[i].printed,
                      title=titled.get(i) or pages[i].outline_path.rsplit(" > ", 1)[-1],
                      outline_path=pages[i].outline_path, score=round(scores.get(i, 0.0), 3), title_hit=i in titled,
                      cite=cite(pages[i].doc, pages[i].p, pages[i].printed),
                      snippet=snippet(body(pages[i].text, rules[pages[i].doc]), focus)) for i in ranked]
    if match == "none" and hits:
        match = "any"
    total = len(set(scores) | set(titled))
    how = {"all": "all terms", "any": "any term (no page has all terms)",
           "synonyms": "with synonyms (no page has any term)", "none": "no match"}[match]
    message = (f"{total} page(s) for {query!r} ({how}); showing {len(hits)}" if hits else
               f"no page matches {query!r} (tried all terms, any term and synonyms)") + ctx.stale_note
    return ManualSearchResult(ok=bool(hits), source="corpus", query=query, docs=[d.id for d in selected],
                              match=match, terms=used, hits=hits, message=message)


def _title_hits(corpus: Corpus, query: str, selected: list[ManualDoc], position: dict[tuple[str, int], int]
                ) -> dict[int, str]:
    """Pages whose outline entry title is a command or function name equal to a query word (any case), or any title
    equal to the whole query; page index -> the matched title (first match)."""
    whole = _title_key(query)
    words = set(_query_words(query))
    found: dict[int, str] = {}
    for doc in selected:
        record = corpus.outline.docs.get(doc.id)
        for entry in record.outline if record else []:
            key = _title_key(entry.title)
            hit = key == whole or (key in words and _COMMAND_TITLE.match(entry.title.strip()) is not None)
            if hit and (doc.id, entry.p) in position:
                found.setdefault(position[(doc.id, entry.p)], entry.title)
    return found


def body(text: str, rule: re.Pattern[str] | None) -> str:
    """Page text without its running header/footer lines (those matching the document's label rule)."""
    if rule is None:
        return text
    lines = text.split("\n")
    edge = set(range(3)) | set(range(max(0, len(lines) - 3), len(lines)))
    return "\n".join(line for i, line in enumerate(lines) if i not in edge or not rule.search(line))


def page(paths: ManualPaths, doc_id: str, p: int | None = None, *, to: int | None = None,
         printed: str | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> ManualPageResult:
    """Text of PDF page ``p`` (or the page printed ``printed``) up to ``to`` (at most ``MAX_PAGES`` pages)."""
    if max_chars < MIN_MAX_CHARS:
        raise ManualError(f"--max-chars must be at least {MIN_MAX_CHARS}", usage=True)
    ctx = Context.load(paths)
    doc = ctx.doc(doc_id)
    if (p is None) == (printed is None):
        raise ManualError("give a PDF page number or --printed LABEL (one of them)", usage=True)
    if ctx.corpus is None:
        return _extract_page(ctx, doc, p, printed, max_chars)
    pages = ctx.corpus.doc_pages(doc.id)
    if not pages:
        raise ManualError(f"{doc.id} is not in the corpus{ctx.stale_note or '; rebuild it'}")
    note = ""
    if printed is not None:
        key = _label_key(printed)
        matches = [pg.p for pg in pages if pg.printed and _label_key(pg.printed) == key]
        if not matches:
            labelled = [pg.printed for pg in pages if pg.printed]
            span = f"{labelled[0]} .. {labelled[-1]}" if labelled else "none"
            raise ManualError(f"no page of {doc.id} is printed {printed!r} (labels {span})", usage=True)
        p = matches[0]
        if len(matches) > 1:
            note = f"; label {printed!r} also on PDF page(s) {', '.join(map(str, matches[1:]))}"
    assert p is not None
    last = len(pages)
    if not 1 <= p <= last:
        raise ManualError(f"{doc.id} has PDF pages 1..{last}", usage=True)
    end = p if to is None else to
    if end < p:
        raise ManualError("--to must not be before the first page", usage=True)
    if end > last:
        end = last
        note += f"; {doc.id} ends at PDF page {last}"
    if end - p + 1 > MAX_PAGES:
        end = p + MAX_PAGES - 1
        note += f"; showing at most {MAX_PAGES} pages"
    budget, shown = max_chars, []
    for number in range(p, end + 1):
        record = ctx.corpus.by_key[(doc.id, number)]
        text, cut = record.text, False
        if len(text) > budget:
            text, cut = text[:budget].rstrip() + " …", True
        budget -= len(text)
        shown.append(PageText(doc=doc.id, p=number, printed=record.printed, outline_path=record.outline_path,
                              cite=cite(doc.id, number, record.printed), text=text, truncated=cut))
        if budget <= 0 and number < end:
            note += f"; stopped after {max_chars} characters (--max-chars)"
            break
    if any(item.truncated for item in shown) and "--max-chars" not in note:
        note += f"; truncated at {max_chars} characters (--max-chars)"
    span = shown[0].cite if len(shown) == 1 else f"{shown[0].cite} .. {shown[-1].cite}"
    return ManualPageResult(ok=True, source="corpus", doc=doc.id, pages=shown,
                            message=f"{doc.title}, {doc.edition}: {span}{note}{ctx.stale_note}")


def toc(paths: ManualPaths, doc_id: str, *, grep: str | None = None) -> ManualTocResult:
    """The PDF outline of one document with printed labels, optionally filtered (regex or text, any case)."""
    ctx = Context.load(paths)
    doc = ctx.doc(doc_id)
    pattern = _grep_pattern(grep)
    if ctx.corpus is None:
        return _extract_toc(ctx, doc, pattern)
    record = ctx.corpus.outline.docs.get(doc.id)
    if record is None:
        raise ManualError(f"{doc.id} is not in the corpus{ctx.stale_note or '; rebuild it'}")
    entries = [TocEntry(level=e.level, title=e.title, p=e.p, printed=ctx.corpus.printed(doc.id, e.p))
               for e in record.outline if pattern is None or pattern.search(e.title)]
    if not record.outline:
        message = (f"{doc.id} ({doc.title}) has no PDF outline; read it with `uv run b1500 manual page {doc.id} 1 "
                   f"--to {min(MAX_PAGES, doc.pages)}` ({record.pages} pages)")
    else:
        message = f"{doc.id} outline: {len(entries)} of {len(record.outline)} entries" + (
            f" matching {grep!r}" if grep else "")
    return ManualTocResult(ok=bool(entries) or not record.outline, source="corpus", doc=doc.id, entries=entries,
                           message=message + ctx.stale_note)


def _grep_pattern(grep: str | None) -> re.Pattern[str] | None:
    if not grep:
        return None
    try:
        return re.compile(grep, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(grep), re.IGNORECASE)


def status(paths: ManualPaths) -> ManualStatus:
    """Corpus state (current / stale / missing / invalid) and the PDFs found in the manuals folder."""
    catalog = load_catalog(paths.catalog)
    corpus: Corpus | None = None
    state: CorpusState = "missing"
    problem = ""
    try:
        corpus = Corpus.load(paths)
    except ManualError as exc:
        state, problem = "invalid", str(exc)
    counts: Counter[str] = Counter(page.doc for page in corpus.pages) if corpus else Counter()
    if corpus is not None:
        same_docs = list(corpus.outline.docs) == catalog.ids and all(
            counts[doc.id] == doc.pages for doc in catalog.docs)
        state = "current" if corpus.outline.catalog == build_digest(catalog) and same_docs else "stale"
    located = locate_pdfs(catalog, paths.manuals_dir, skip=paths.repo_root)
    docs = []
    for doc in catalog.docs:
        where = located[doc.id]
        note = "" if where.state != "mismatch" else (
            f"sha256 {(where.sha256 or '')[:12]}... differs from the catalog (another edition?)")
        docs.append(DocStatus(id=doc.id, title=doc.title, edition=doc.edition, pages=doc.pages,
                              corpus_pages=counts[doc.id], pdf=where.state,
                              path=paths.display_pdf(where.path) if where.path else "", note=note))
    found = sum(d.pdf != "missing" for d in docs)
    size = sum(f.stat().st_size for f in (paths.pages, paths.outline) if f.is_file())
    where_dir = f"{paths.display(paths.manuals_dir)} ({paths.manuals_dir_source})"
    corpus_text = {
        "current": f"corpus current: {len(counts)} docs, {sum(counts.values())} pages ({size / 1000:.0f} kB)",
        "stale": f"corpus STALE ({len(counts)} docs, {sum(counts.values())} pages; built from another catalog): run "
                 "uv run b1500 manual build",
        "missing": f"no corpus at {paths.display(paths.corpus_dir)}: queries answer from the structured extracts; "
                   "build it with uv run b1500 manual build",
        "invalid": problem,
    }[state]
    pdf_text = (f"PDFs {found}/{len(docs)} in {where_dir}" + (
        "" if found == len(docs) else " (optional: needed only for figures and manual build)"))
    mismatched = [d.id for d in docs if d.pdf == "mismatch"]
    if mismatched:
        pdf_text += f"; edition mismatch: {', '.join(mismatched)}"
    return ManualStatus(ok=state == "current", corpus=state,
                        corpus_dir=paths.display(paths.corpus_dir), corpus_bytes=size,
                        docs_in_corpus=len(counts), pages_in_corpus=sum(counts.values()),
                        catalog_docs=len(catalog.docs), catalog_pages=catalog.total_pages,
                        manuals_dir=paths.display(paths.manuals_dir), manuals_dir_source=paths.manuals_dir_source,
                        pdfs_found=found, docs=docs, message=f"{corpus_text}; {pdf_text}")


# -- structured extracts (no corpus) ----------------------------------------------------------------------------------

_PDF_REF = re.compile(r"\bPDF\s+(\d{1,4})(?:\s*[–-]\s*(\d{1,4}))?")
_PDF_PAGES = re.compile(r"pdf_pages:\s*\[([0-9,\s]*)\]")
_RANGE = re.compile(r"(\d{1,4})(?:\s*[–-]\s*(\d{1,4}))?")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_YAML_ITEM = re.compile(r"^(\s*)(?:- |[A-Za-z_][\w-]*:)")
_CHUNK_LINES = 40


@dataclass(frozen=True)
class Chunk:
    """A piece of a structured extract: its document, file (relative to references/manuals), first line, heading
    or first line as title, text, PDF pages it names and printed labels from an index table."""

    doc: str
    file: str
    line: int
    title: str
    text: str
    pages: tuple[int, ...]
    printed: tuple[str, ...] = ()
    level: int = 0
    kind: Literal["heading", "row", "text", "item"] = "text"

    @property
    def ref(self) -> str:
        return f"{self.file}:L{self.line}"


def _pages_in(text: str) -> list[int]:
    pages: list[int] = []
    for match in _PDF_REF.finditer(text):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        pages.extend(range(first, min(last, first + 50) + 1) if last >= first else [first])
    for match in _PDF_PAGES.finditer(text):
        pages.extend(int(n) for n in re.findall(r"\d+", match.group(1)))
    return pages


def _cell_pages(cell: str) -> list[int]:
    pages: list[int] = []
    for match in _RANGE.finditer(cell):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        pages.extend(range(first, min(last, first + 50) + 1) if last >= first else [first])
    return pages


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_chunks(doc: str, rel: str, text: str) -> list[Chunk]:
    """Headings, each table row (with the PDF/printed page columns of index tables) and each paragraph."""
    chunks: list[Chunk] = []
    heading, level = "", 0
    header: list[str] = []
    para: list[str] = []
    para_start = 0

    def flush() -> None:
        if para:
            body = "\n".join(para)
            chunks.append(Chunk(doc, rel, para_start, heading, body, tuple(unique_ints(_pages_in(body))),
                                level=level + 1))
            para.clear()

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        found = _HEADING.match(stripped)
        if found:
            flush()
            level, heading = len(found.group(1)), found.group(2).strip()
            header = []
            chunks.append(Chunk(doc, rel, number, heading, heading, tuple(unique_ints(_pages_in(heading))),
                                level=level - 1, kind="heading"))
        elif stripped.startswith("|"):
            flush()
            cells = _cells(stripped)
            if set("".join(cells)) <= set("-: "):
                continue
            if not header:
                header = cells
                continue
            pages = _pages_in(stripped)
            printed: list[str] = []
            for name, cell in zip(header, cells, strict=False):
                lowered = name.lower()
                if lowered.startswith("pdf page"):
                    pages = _cell_pages(cell) + pages
                elif lowered.startswith("printed"):
                    printed += [c for c in re.findall(r"[0-9A-Z]{1,2}-\d{1,3}|\d{1,3}", cell)]
            row = " | ".join(f"{h}: {c}" for h, c in zip(header, cells, strict=False) if c and c not in "—-")
            chunks.append(Chunk(doc, rel, number, cells[0] or heading, row, tuple(unique_ints(pages)),
                                tuple(printed), level=level, kind="row"))
        elif not stripped:
            flush()
            header = []
        else:
            if not para:
                para_start = number
            para.append(stripped)
            if len(para) >= _CHUNK_LINES:
                flush()
    flush()
    return chunks


def yaml_chunks(doc: str, rel: str, text: str) -> list[Chunk]:
    """Items of a YAML extract: a new chunk at each top-level key and at each list item of the outermost list
    indentation, at most ``_CHUNK_LINES`` lines each."""
    lines = text.splitlines()
    items = [len(m.group(1)) for line in lines if (m := _YAML_ITEM.match(line)) and line.lstrip().startswith("- ")]
    outer = min(items, default=0)
    starts = [i for i, line in enumerate(lines) if (m := _YAML_ITEM.match(line)) and (
        not m.group(1) or (line.lstrip().startswith("- ") and len(m.group(1)) <= outer))]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    chunks: list[Chunk] = []
    bounds = [*starts, len(lines)]
    for first, end in itertools.pairwise(bounds):
        for begin in range(first, end, _CHUNK_LINES):
            block = lines[begin:min(end, begin + _CHUNK_LINES)]
            body = "\n".join(line.rstrip() for line in block).strip()
            if body:
                chunks.append(Chunk(doc, rel, begin + 1, block[0].strip()[:120], body,
                                    tuple(unique_ints(_pages_in(body))), kind="item"))
    return chunks


def unique_ints(items: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(items))


def extract_chunks(ctx: Context, docs: Sequence[ManualDoc]) -> list[Chunk]:
    """Chunks of the extracts the catalog lists for ``docs`` (missing files are skipped)."""
    chunks: list[Chunk] = []
    for doc in docs:
        for rel in doc.extracts:
            path = ctx.paths.references.joinpath(*rel.split("/"))
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            reader = yaml_chunks if path.suffix.lower() in (".yaml", ".yml") else markdown_chunks
            chunks += reader(doc.id, rel, text)
    return chunks


def _no_extracts(ctx: Context, docs: Sequence[ManualDoc]) -> str:
    return (f"{ctx.no_corpus_note()} No structured extract covers {', '.join(d.id for d in docs)}"
            + ("; WG5 (Edition 5) has extracts" if any(d.id == "WG" for d in docs) else "") + ".")


def _extract_search(ctx: Context, query: str, terms: list[str], selected: list[ManualDoc], k: int
                    ) -> ManualSearchResult:
    chunks = [c for c in extract_chunks(ctx, selected) if c.kind != "heading"]
    ids = [d.id for d in selected]
    if not chunks:
        return ManualSearchResult(ok=False, source="extracts", query=query, docs=ids, match="none", terms=terms,
                                  hits=[], message=_no_extracts(ctx, selected))
    priority = {doc.id: doc.priority for doc in selected}
    bags = []
    for chunk in chunks:
        bag = Counter(tokenize(chunk.text))
        for token in tokenize(chunk.title):
            bag[token] += TITLE_WEIGHT
        bags.append(bag)
    index = Bm25(bags, [priority[c.doc] for c in chunks])
    match, scores, used = _ranked(index, terms, query, ctx.synonyms)
    ranked = sorted(scores, key=lambda i: (-scores[i], ids.index(chunks[i].doc), chunks[i].file, chunks[i].line))[:k]
    focus = sorted(used, key=lambda t: -index.idf(t))
    hits = []
    for i in ranked:
        chunk = chunks[i]
        p = chunk.pages[0] if chunk.pages else None
        printed = chunk.printed[0] if chunk.printed and p is not None else ""
        hits.append(ManualHit(doc=chunk.doc, p=p, printed=printed, title=chunk.title[:120], score=round(scores[i], 3),
                              cite=cite(chunk.doc, p, printed) if p is not None else f"references/manuals/{chunk.ref}",
                              snippet=snippet(chunk.text, focus), source="extracts", ref=chunk.ref))
    message = (f"{len(scores)} extract item(s) for {query!r}; showing {len(hits)}. " if hits else
               f"no extract item matches {query!r}. ") + ctx.no_corpus_note()
    return ManualSearchResult(ok=bool(hits), source="extracts", query=query, docs=ids, match=match, terms=used,
                              hits=hits, message=message)


def _extract_page(ctx: Context, doc: ManualDoc, p: int | None, printed: str | None, max_chars: int
                  ) -> ManualPageResult:
    chunks = [c for c in extract_chunks(ctx, [doc]) if c.kind != "heading"]
    if printed is not None:
        key = _label_key(printed)
        with_label = [c for c in chunks if c.pages and any(_label_key(x) == key for x in c.printed)]
        if not with_label:
            raise ManualError(f"no corpus, and no extract of {doc.id} maps printed page {printed!r} to a PDF page. "
                              f"{ctx.no_corpus_note()}")
        p = with_label[0].pages[0]
    assert p is not None
    if not 1 <= p <= doc.pages:
        raise ManualError(f"{doc.id} has PDF pages 1..{doc.pages}", usage=True)
    about = [c for c in chunks if p in c.pages]
    budget, shown = max_chars, []
    for chunk in about:
        if budget <= 0:
            break
        text = chunk.text if len(chunk.text) <= budget else chunk.text[:budget].rstrip() + " …"
        budget -= len(text)
        shown.append(PageText(doc=doc.id, p=p, printed=chunk.printed[0] if chunk.printed else "",
                              outline_path=chunk.title, cite=cite(doc.id, p), text=text,
                              truncated=len(text) < len(chunk.text), ref=chunk.ref))
    head = (f"{len(about)} extract item(s) about {doc.id} p{p} (not the page text). " if about else
            f"no extract mentions {doc.id} p{p}. ")
    if not doc.extracts:
        head = f"no extract mentions {doc.id} p{p}; {_no_extracts(ctx, [doc])} "
    return ManualPageResult(ok=bool(shown), source="extracts", doc=doc.id, pages=shown,
                            message=head + ctx.no_corpus_note())


def _extract_toc(ctx: Context, doc: ManualDoc, pattern: re.Pattern[str] | None) -> ManualTocResult:
    entries = []
    for chunk in extract_chunks(ctx, [doc]):
        if chunk.kind == "heading" or (chunk.kind == "row" and chunk.pages):
            title = chunk.title.strip("`* ")
            if pattern is None or pattern.search(title):
                entries.append(TocEntry(level=chunk.level, title=title, p=chunk.pages[0] if chunk.pages else None,
                                        printed=chunk.printed[0] if chunk.printed else ""))
    message = (f"{doc.id}: {len(entries)} entries from the structured extracts (headings and index rows). "
               if doc.extracts else _no_extracts(ctx, [doc]) + " ")
    return ManualTocResult(ok=bool(entries), source="extracts", doc=doc.id, entries=entries,
                           message=message + ctx.no_corpus_note())
