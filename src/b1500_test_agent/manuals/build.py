"""``b1500 manual build [--src DIR] [--check]``: extract the page corpus from the catalog's PDFs (blueprint 5.2).

Output (committed, OD-1): ``corpus/pages.jsonl.gz`` with one JSON line per PDF page, ``{"doc", "p", "printed",
"outline_path", "text"}``, documents in catalog order, and ``corpus/outline.json`` (``CorpusOutline``: the catalog's
build digest and per document the source sha256, page count, kept characters and PDF outline). Both are
deterministic: the same PDFs, catalog and ``pypdfium2`` version give the same bytes (gzip with mtime 0 and no file
name; JSON with fixed key order). ``--check`` rebuilds in memory and compares byte for byte: both files when every
PDF is present, per document otherwise; nothing is written.

Text extraction (``pypdfium2``, the PDFium text layer; no OCR) is normalised so that search and display work:
line ends to ``\\n``; PDFium's hyphenation marker (U+0002) is removed, joining the word; private-use glyphs of the
manuals' Symbol/Wingdings fonts become text via the catalog's symbol table (unlisted U+F020..U+F07E become the ASCII
character they encode; any other unlisted private-use glyph is dropped and reported); other control characters
become spaces; each line is stripped and runs of spaces collapse; table-of-contents leader dots become `` ... ``;
blank-line runs collapse.

Printed page labels come from the document's ``label_rule`` (first and last three non-empty lines of a page); an
unlabelled page directly before label ``X-N`` (N >= 2) whose predecessor is unlabelled or ``X-(N-2)`` gets ``X-(N-1)``
(chapter title pages). ``outline_path`` joins the titles of the outline entry in effect on a page and its ancestors.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import tempfile
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium

from b1500_test_agent.manuals.catalog import (
    CORPUS_BUDGET_BYTES,
    Located,
    ManualPaths,
    build_digest,
    load_catalog,
    locate_pdfs,
)
from b1500_test_agent.models.manuals import (
    CorpusOutline,
    CorpusPage,
    DocBuild,
    DocOutline,
    ManualBuildReport,
    ManualCatalog,
    ManualDoc,
    OutlineEntry,
)

LABEL_LINES = 3
"""Lines at the top and at the bottom of a page searched for the printed page label."""

HYPHEN_MARK = "\x02"
_PUA_ASCII = range(0xF020, 0xF07F)
_LEADER = re.compile(r"(?:\s?\.){4,}\s?")
_SPACES = re.compile(r"[   - 　]{2,}")
_DIGITS = re.compile(r"\d+")
_LABEL_TAIL = re.compile(r"^(.*?)(\d+)$")
_OUTLINE_DEPTH = 15


@dataclass
class Extracted:
    """One document read from its PDF: pages with labels and outline paths, the outline, kept characters and the
    number of dropped private-use glyphs."""

    doc: ManualDoc
    sha256: str
    pages: list[CorpusPage]
    outline: list[OutlineEntry]
    chars: int
    unmapped: Counter[str]

    def outline_record(self) -> DocOutline:
        return DocOutline(sha256=self.sha256, pages=len(self.pages), chars=self.chars, outline=self.outline)


# -- text ------------------------------------------------------------------------------------------------------------


def symbol_table(symbols: Mapping[str, str]) -> dict[int, str]:
    """``str.translate`` table for private-use glyphs: the catalog entries plus ASCII for unlisted U+F020..U+F07E."""
    table = {code: chr(code - 0xF000) for code in _PUA_ASCII}
    table.update({int(key, 16): value for key, value in symbols.items()})
    return table


def normalize_text(raw: str, table: Mapping[int, str], unmapped: Counter[str] | None = None) -> str:
    """Clean one page of PDFium text (see the module docstring); counts dropped private-use glyphs in ``unmapped``."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(HYPHEN_MARK + "\n", "").replace(HYPHEN_MARK, "")
    out: list[str] = []
    for char in text:
        code = ord(char)
        if 0xE000 <= code <= 0xF8FF:
            mapped = table.get(code)
            if mapped is None:
                if unmapped is not None:
                    unmapped[f"U+{code:04X}"] += 1
                continue
            out.append(mapped)
        elif char == "\n":
            out.append(char)
        elif unicodedata.category(char) == "Cc" or char in "﻿￾￿":
            out.append(" ")
        else:
            out.append(char)
    lines = []
    for line in "".join(out).split("\n"):
        line = _SPACES.sub(" ", _LEADER.sub(" ... ", line)).strip()
        lines.append(line)
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def normalize_title(raw: str, table: Mapping[int, str]) -> str:
    """An outline title on one line."""
    return " ".join(normalize_text(raw, table).split())


# -- labels and outline ----------------------------------------------------------------------------------------------


def normalize_label(label: str) -> str:
    """Canonical printed label: no whitespace, no leading zeros in numbers (``4- 07`` → ``4-7``, ``05`` → ``5``)."""
    compact = "".join(label.split())
    return _DIGITS.sub(lambda m: str(int(m.group(0))), compact)


def page_label(text: str, rule: re.Pattern[str]) -> str:
    """The printed label of a page: the first non-empty group of ``rule`` on the first, then the last, three
    non-empty lines; ``""`` when none matches."""
    lines = [line for line in text.split("\n") if line.strip()]
    for line in lines[:LABEL_LINES] + lines[-LABEL_LINES:]:
        match = rule.search(line)
        if match:
            group = next((g for g in match.groups() if g), None)
            if group:
                return normalize_label(group)
    return ""


def infer_labels(labels: list[str]) -> list[str]:
    """Fill unlabelled pages that the numbering implies: the page before ``X-N`` (N >= 2) becomes ``X-(N-1)`` unless
    its own predecessor already claims that number (``X-(N-1)`` or a later one of the same prefix). Works
    backwards, so a run of chapter-start pages resolves in one pass; front matter before ``X-1`` stays unlabelled."""
    out = list(labels)
    for index in range(len(out) - 2, -1, -1):
        if out[index]:
            continue
        match = _LABEL_TAIL.match(out[index + 1])
        if not match or int(match.group(2)) < 2:
            continue
        prefix, number = match.group(1), int(match.group(2))
        before = _LABEL_TAIL.match(out[index - 1]) if index > 0 else None
        if before and before.group(1) == prefix and int(before.group(2)) >= number - 1:
            continue
        out[index] = f"{prefix}{number - 1}"
    return out


def outline_paths(outline: list[OutlineEntry], pages: int) -> list[str]:
    """For each page 1..``pages`` the `` > ``-joined titles of the outline entry shown for it and its ancestors.

    A page where entries start shows the first of them, descending into children that start on the same page
    (``4 Command Reference > ... > ERSSP``); any other page shows the entry in effect (the last one, in document
    order, that started before it); ``""`` before the first entry."""
    stack: list[str] = []
    paths: list[str] = []
    for entry in outline:
        del stack[entry.level:]
        stack.extend([""] * (entry.level - len(stack)))
        stack.append(entry.title)
        paths.append(" > ".join(t for t in stack if t))
    shown: dict[int, str] = {}
    for index, entry in enumerate(outline):
        if entry.p in shown:
            continue
        deepest = index
        while (deepest + 1 < len(outline) and outline[deepest + 1].p == entry.p
               and outline[deepest + 1].level > outline[deepest].level):
            deepest += 1
        shown[entry.p] = paths[deepest]
    starts = sorted((entry.p, order) for order, entry in enumerate(outline))
    result: list[str] = []
    current, cursor = "", 0
    for page in range(1, pages + 1):
        while cursor < len(starts) and starts[cursor][0] < page:
            current = paths[starts[cursor][1]]
            cursor += 1
        result.append(shown.get(page, current))
    return result


# -- extraction ------------------------------------------------------------------------------------------------------


def extract_pdf(doc: ManualDoc, raw: bytes, sha256: str, table: Mapping[int, str]) -> Extracted:
    """Read one PDF (its bytes) into pages, labels, outline paths and outline."""
    rule = re.compile(doc.label_rule)
    unmapped: Counter[str] = Counter()
    pdf = pdfium.PdfDocument(raw)
    try:
        count = len(pdf)
        outline: list[OutlineEntry] = []
        for item in pdf.get_toc(max_depth=_OUTLINE_DEPTH):
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            if index is None or not 0 <= index < count:
                continue
            outline.append(OutlineEntry(level=item.level, title=normalize_title(item.get_title(), table),
                                        p=index + 1))
        texts: list[str] = []
        for index in range(count):
            page = pdf[index]
            textpage = page.get_textpage()
            try:
                texts.append(normalize_text(textpage.get_text_bounded(), table, unmapped))
            finally:
                textpage.close()
                page.close()
    finally:
        pdf.close()
    labels = infer_labels([page_label(text, rule) for text in texts])
    paths = outline_paths(outline, count)
    pages = [CorpusPage(doc=doc.id, p=i + 1, printed=labels[i], outline_path=paths[i], text=texts[i])
             for i in range(count)]
    return Extracted(doc, sha256, pages, outline, sum(len(t) for t in texts), unmapped)


# -- serialisation ---------------------------------------------------------------------------------------------------


def page_line(page: CorpusPage) -> str:
    """One corpus line (no newline): compact JSON, keys in model order, UTF-8 text unescaped."""
    return json.dumps(page.model_dump(), ensure_ascii=False, separators=(",", ":"))


def pages_bytes(lines: list[str]) -> bytes:
    """Deterministic gzip of the JSON lines (mtime 0, no file name, level 9)."""
    payload = "".join(f"{line}\n" for line in lines).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as handle:
        handle.write(payload)
    return buffer.getvalue()


def outline_bytes(outline: CorpusOutline) -> bytes:
    """``outline.json``: one outline entry per line, so diffs stay readable; LF line ends."""
    lines = ["{", f' "format": {outline.format},', f' "catalog": "{outline.catalog}",', ' "docs": {']
    names = list(outline.docs)
    for position, name in enumerate(names):
        record = outline.docs[name]
        head = (f'  {json.dumps(name)}: {{"sha256": "{record.sha256}", "pages": {record.pages}, '
                f'"chars": {record.chars}, "outline": [')
        entries = [json.dumps(e.model_dump(), ensure_ascii=False, separators=(",", ":")) for e in record.outline]
        tail = "]}" + ("," if position < len(names) - 1 else "")
        if entries:
            lines.append(head)
            lines.extend(f"   {entry}{',' if i < len(entries) - 1 else ''}" for i, entry in enumerate(entries))
            lines.append(f"  {tail}")
        else:
            lines.append(f"{head}{tail}")
    lines += [" }", "}"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_pages(data: bytes) -> list[str]:
    """The JSON lines of a ``pages.jsonl.gz`` payload."""
    return gzip.decompress(data).decode("utf-8").splitlines()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


# -- build / check ---------------------------------------------------------------------------------------------------


@dataclass
class _Run:
    """State shared by a build and a check: where things are and what was extracted."""

    paths: ManualPaths
    results: dict[str, DocBuild]
    extracted: dict[str, Extracted]
    missing: list[str]
    warnings: list[str]
    problems: list[str]

    @property
    def manuals_dir(self) -> str:
        return f"{self.paths.display(self.paths.manuals_dir)} ({self.paths.manuals_dir_source})"

    @property
    def page_count(self) -> int:
        return sum(len(item.pages) for item in self.extracted.values())

    def report(self, mode: Literal["build", "check"], message: str, *, size: int,
               identical: bool | None = None) -> ManualBuildReport:
        return ManualBuildReport(
            ok=not self.problems, mode=mode, manuals_dir=self.manuals_dir,
            corpus_dir=self.paths.display(self.paths.corpus_dir), docs=list(self.results.values()),
            pages=self.page_count, corpus_bytes=size, seconds=0.0, identical=identical, warnings=self.warnings,
            problems=self.problems, message=message)


def _lines_by_doc(lines: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for line in lines:
        grouped.setdefault(json.loads(line)["doc"], []).append(line)
    return grouped


def _kb(size: int) -> str:
    return f"{size / 1000:.0f} kB"


def _mismatch(where: Located) -> str:
    doc = where.doc
    return (f"{doc.id}: edition mismatch at {where.path.as_posix() if where.path else '-'}: sha256 "
            f"{(where.sha256 or '')[:12]}..., the catalog pins {doc.sha256[:12]}... ({doc.edition}, {doc.pages} pages);"
            " built from the file found - update catalog.yaml (sha256, size, pages, edition) and re-check citations")


def _extract_all(paths: ManualPaths, catalog: ManualCatalog) -> _Run:
    table = symbol_table(catalog.symbols)
    located = locate_pdfs(catalog, paths.manuals_dir, skip=paths.repo_root)
    run = _Run(paths, {}, {}, [], [], [])
    for doc_id, where in located.items():
        run.results[doc_id] = DocBuild(id=doc_id, pdf=where.state,
                                       path=paths.display_pdf(where.path) if where.path else "")
        if where.path is None:
            run.missing.append(doc_id)
            continue
        if where.state == "mismatch":
            run.warnings.append(_mismatch(where))
        try:
            item = extract_pdf(where.doc, where.path.read_bytes(), where.sha256 or "", table)
        except (OSError, pdfium.PdfiumError) as exc:
            run.problems.append(f"{doc_id}: cannot read {paths.display(where.path)}: {exc}")
            continue
        run.extracted[doc_id] = item
        if len(item.pages) != where.doc.pages:
            run.warnings.append(f"{doc_id}: {len(item.pages)} pages, the catalog says {where.doc.pages}")
        if item.unmapped:
            listed = ", ".join(f"{k} x{v}" for k, v in sorted(item.unmapped.items()))
            run.warnings.append(f"{doc_id}: dropped unmapped private-use glyphs {listed} (add them to catalog "
                                "symbols)")
        run.results[doc_id] = run.results[doc_id].model_copy(update={
            "pages": len(item.pages), "labelled": sum(bool(p.printed) for p in item.pages),
            "outline": len(item.outline), "chars": item.chars})
    return run


def build_corpus(paths: ManualPaths, *, check: bool = False, catalog: ManualCatalog | None = None,
                 clock: Callable[[], float] = time.perf_counter) -> ManualBuildReport:
    """Build (or with ``check`` verify) the corpus under ``paths.corpus_dir`` from the PDFs in ``paths.manuals_dir``.

    A build needs every catalog PDF (a missing one is a problem and nothing is written); an edition mismatch is a
    warning and the found file is used. A check compares whatever PDFs are present (see the module docstring).
    Raises ``ManualError`` when the catalog is missing or invalid."""
    started = clock()
    catalog = catalog or load_catalog(paths.catalog)
    run = _extract_all(paths, catalog)
    lines = [page_line(page) for item in run.extracted.values() for page in item.pages]
    outline = CorpusOutline(catalog=build_digest(catalog),
                            docs={doc_id: item.outline_record() for doc_id, item in run.extracted.items()})
    new_pages, new_outline = pages_bytes(lines), outline_bytes(outline)
    if check:
        report = _check(run, lines, new_pages, new_outline)
    elif run.missing:
        run.problems.append(f"missing PDFs: {', '.join(run.missing)} (looked in {run.manuals_dir}; set "
                            "B1500_MANUALS_DIR or pass --src); nothing written")
        report = run.report("build", "build failed: " + "; ".join(run.problems), size=0)
    elif run.problems:
        report = run.report("build", "build failed: " + "; ".join(run.problems), size=0)
    else:
        _write_atomic(paths.pages, new_pages)
        _write_atomic(paths.outline, new_outline)
        size = len(new_pages) + len(new_outline)
        if size > CORPUS_BUDGET_BYTES:
            run.warnings.append(f"corpus is {_kb(size)}, above the {_kb(CORPUS_BUDGET_BYTES)} budget (OD-1)")
        report = run.report("build", f"built {len(run.extracted)} docs, {run.page_count} pages -> "
                                     f"{paths.display(paths.corpus_dir)}/ ({_kb(len(new_pages))} pages + "
                                     f"{_kb(len(new_outline))} outline)", size=size)
    elapsed = round(clock() - started, 2)
    return report.model_copy(update={"seconds": elapsed, "message": f"{report.message} in {elapsed:.1f} s"})


def _check(run: _Run, lines: list[str], new_pages: bytes, new_outline: bytes) -> ManualBuildReport:
    """Compare a rebuild with the committed corpus (see ``build_corpus``)."""
    paths = run.paths
    try:
        old_pages, old_outline = paths.pages.read_bytes(), paths.outline.read_bytes()
        old_lines = read_pages(old_pages)
        old_docs = json.loads(old_outline.decode("utf-8")).get("docs", {})
    except (OSError, ValueError, EOFError) as exc:
        run.problems.append(f"no readable committed corpus at {paths.display(paths.corpus_dir)}: {exc}")
        return run.report("check", "check failed: " + "; ".join(run.problems), size=0, identical=False)
    size = len(old_pages) + len(old_outline)
    if not run.extracted:
        return run.report("check", f"not verified: no catalog PDF found in {run.manuals_dir} (the committed "
                                   "corpus is used as is)", size=size)
    old_by_doc, new_by_doc = _lines_by_doc(old_lines), _lines_by_doc(lines)
    new_docs = json.loads(new_outline.decode("utf-8"))["docs"]
    differs = []
    for doc_id in run.extracted:
        same = old_by_doc.get(doc_id) == new_by_doc.get(doc_id) and old_docs.get(doc_id) == new_docs.get(doc_id)
        run.results[doc_id] = run.results[doc_id].model_copy(update={"check": "identical" if same else "differs"})
        if not same:
            differs.append(doc_id)
    identical: bool | None = None
    if run.missing:
        verdict = (f"partial check: {len(run.extracted) - len(differs)}/{len(run.extracted)} present docs "
                   f"identical; not checked (PDF missing): {', '.join(run.missing)}")
    elif old_pages == new_pages and old_outline == new_outline:
        identical, verdict = True, "corpus reproduced byte for byte (pages.jsonl.gz and outline.json)"
    elif old_lines == lines and old_outline == new_outline:
        identical, verdict = True, ("corpus content reproduced (identical JSON lines and outline.json); the gzip "
                                    "bytes differ only by the zlib build")
    else:
        identical, verdict = False, "corpus differs from a rebuild"
    if differs:
        run.problems.append(f"differs from a rebuild: {', '.join(differs)} (run uv run b1500 manual build; "
                            f"pypdfium2 here is {pdfium.PYPDFIUM_INFO})")
    elif identical is False:
        run.problems.append("outline.json (catalog digest) differs from a rebuild: run uv run b1500 manual build")
    message = verdict if not run.problems else f"{verdict}: " + "; ".join(run.problems)
    return run.report("check", message, size=size, identical=identical)
