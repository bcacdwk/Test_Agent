"""Catalog, paths and PDF location of the manual corpus (blueprint 5.2).

Files (``references/manuals/`` of the clone, or any folder with the same layout for tests):

- ``catalog.yaml`` (committed): every indexed PDF with id, file, edition, sha256, size, pages, label rule, priority
  and the private-use glyph table (``ManualCatalog``); no manual text.
- ``synonyms.yaml`` (committed, small): extra query terms used when a search finds nothing (``Synonyms``).
- ``corpus/pages.jsonl.gz`` and ``corpus/outline.json`` (committed, OD-1): the page text and PDF outlines written by
  ``b1500 manual build`` (``manuals.build``).

The PDFs themselves are never committed. They live in the manuals folder: ``$B1500_MANUALS_DIR`` when set, else
``Settings.manuals_dir`` (default ``..``, the clone's parent) resolved against the repository root. A PDF is found at
its catalog path; a copy that was renamed or moved is found by size and sha256 in a bounded walk of that folder; a
file at the catalog path with another sha256 is reported as an edition ``mismatch`` (a warning, never fatal). Extra
files are ignored.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from b1500_test_agent.models.manuals import ManualCatalog, ManualDoc, Synonyms

ENV_MANUALS_DIR = "B1500_MANUALS_DIR"
REFERENCES_REL = "references/manuals"
CATALOG_FILE = "catalog.yaml"
SYNONYMS_FILE = "synonyms.yaml"
CORPUS_DIR = "corpus"
PAGES_FILE = "pages.jsonl.gz"
OUTLINE_FILE = "outline.json"
CORPUS_BUDGET_BYTES = 1_000_000
"""OD-1: the committed corpus (both files) stays at or below 1 MB."""

SCAN_DEPTH = 4
"""How deep the manuals folder is walked to find a renamed or moved PDF."""

_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", "site-packages"})

PdfState = Literal["ok", "mismatch", "missing"]


class ManualError(Exception):
    """A manual command cannot answer: invalid catalog or corpus, unknown document, page out of range. The message
    says what to do; adapters print it (exit code 2 for a usage problem, 1 otherwise)."""

    def __init__(self, message: str, *, usage: bool = False) -> None:
        super().__init__(message)
        self.usage = usage


def resolve_manuals_dir(setting: str, repo_root: Path, environ: Mapping[str, str] | None = None) -> tuple[Path, str]:
    """The manuals folder and where it came from: ``$B1500_MANUALS_DIR`` (relative values resolve against the current
    directory) or ``settings.manuals_dir`` (relative values resolve against the repository root)."""
    env = os.environ if environ is None else environ
    override = env.get(ENV_MANUALS_DIR)
    if override:
        path = Path(override).expanduser()
        return (path if path.is_absolute() else Path.cwd() / path).resolve(), ENV_MANUALS_DIR
    path = Path(setting).expanduser()
    return (path if path.is_absolute() else repo_root / path).resolve(), "settings.manuals_dir"


@dataclass(frozen=True)
class ManualPaths:
    """Where the catalog, synonyms, extracts and corpus are (``references``) and where the PDFs are
    (``manuals_dir``). ``repo_root`` only shortens paths for display."""

    references: Path
    manuals_dir: Path
    manuals_dir_source: str = "settings.manuals_dir"
    repo_root: Path | None = None

    @classmethod
    def for_repo(cls, repo_root: Path, setting: str = "..", environ: Mapping[str, str] | None = None) -> ManualPaths:
        """The clone's ``references/manuals/`` and the resolved manuals folder (see ``resolve_manuals_dir``)."""
        manuals_dir, source = resolve_manuals_dir(setting, repo_root, environ)
        return cls(references=repo_root / REFERENCES_REL, manuals_dir=manuals_dir, manuals_dir_source=source,
                   repo_root=repo_root)

    def with_manuals_dir(self, manuals_dir: Path, source: str) -> ManualPaths:
        """These paths with another PDF folder (``b1500 manual build --src DIR``)."""
        return ManualPaths(self.references, manuals_dir.resolve(), source, self.repo_root)

    @property
    def catalog(self) -> Path:
        return self.references / CATALOG_FILE

    @property
    def synonyms(self) -> Path:
        return self.references / SYNONYMS_FILE

    @property
    def corpus_dir(self) -> Path:
        return self.references / CORPUS_DIR

    @property
    def pages(self) -> Path:
        return self.corpus_dir / PAGES_FILE

    @property
    def outline(self) -> Path:
        return self.corpus_dir / OUTLINE_FILE

    def display_pdf(self, path: Path) -> str:
        """A PDF path relative to the manuals folder (POSIX) when inside it, else as ``display`` shows it."""
        try:
            return path.resolve().relative_to(self.manuals_dir.resolve()).as_posix()
        except ValueError:
            return self.display(path)

    def display(self, path: Path) -> str:
        """``path`` relative to the repository root (POSIX) when inside it, else absolute (POSIX)."""
        if self.repo_root is not None:
            try:
                return path.resolve().relative_to(self.repo_root.resolve()).as_posix()
            except ValueError:
                pass
        return path.resolve().as_posix()


def _yaml(path: Path, what: str) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ManualError(f"no manual {what} at {path.as_posix()} (git pull restores it)") from None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ManualError(f"manual {what} {path.as_posix()} is not readable UTF-8 YAML: {exc}") from None


def _problems(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'top level'}: {e['msg']}" for e in exc.errors()[:5])


def load_catalog(path: Path) -> ManualCatalog:
    """Parse and validate ``catalog.yaml``; raises ``ManualError`` naming the first problems."""
    try:
        return ManualCatalog.model_validate(_yaml(path, "catalog"))
    except ValidationError as exc:
        raise ManualError(f"manual catalog {path.as_posix()} is invalid: {_problems(exc)}") from None


def load_synonyms(path: Path) -> Synonyms:
    """Parse ``synonyms.yaml`` (a missing file means no synonyms); raises ``ManualError`` when it is invalid."""
    if not path.is_file():
        return Synonyms()
    try:
        return Synonyms.model_validate(_yaml(path, "synonyms file") or {})
    except ValidationError as exc:
        raise ManualError(f"manual synonyms {path.as_posix()} are invalid: {_problems(exc)}") from None


def build_digest(catalog: ManualCatalog) -> str:
    """sha256 over everything in the catalog that changes the built corpus (ids and order, source sha256, pages,
    label rules, the symbol table). Recorded in ``outline.json``; a different value marks the corpus stale."""
    relevant = {
        "symbols": dict(sorted(catalog.symbols.items())),
        "docs": [[doc.id, doc.sha256, doc.pages, doc.label_rule] for doc in catalog.docs],
    }
    return hashlib.sha256(json.dumps(relevant, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Streaming sha256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Located:
    """Where a catalog document's PDF was found: ``ok`` (sha256 matches), ``mismatch`` (a different file at the
    catalog path), ``missing``. ``path`` is the file to read (``None`` when missing); ``how`` says how it was found."""

    doc: ManualDoc
    state: PdfState
    path: Path | None
    sha256: str | None
    how: str


def _variants(base: Path, rel: str) -> Iterator[Path]:
    """The catalog path, then its NFC/NFD spellings (a copy made on another OS may store either)."""
    seen: set[str] = set()
    for form in (rel, unicodedata.normalize("NFC", rel), unicodedata.normalize("NFD", rel)):
        if form not in seen:
            seen.add(form)
            yield base.joinpath(*form.split("/"))


def _walk_pdfs(root: Path, skip: Path | None) -> Iterator[Path]:
    """PDF files under ``root`` up to ``SCAN_DEPTH`` folders deep, skipping hidden and tool folders and ``skip``
    (the clone itself). Sorted, so the first match is deterministic."""
    stack = [(root, 0)]
    skip_resolved = skip.resolve() if skip is not None else None
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        subdirs = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < SCAN_DEPTH and not entry.name.startswith(".") and entry.name not in _SKIP_DIRS:
                        path = Path(entry.path)
                        if skip_resolved is None or path.resolve() != skip_resolved:
                            subdirs.append((path, depth + 1))
                elif entry.is_file() and entry.name.lower().endswith(".pdf"):
                    yield Path(entry.path)
            except OSError:
                continue
        stack.extend(reversed(subdirs))


def locate_pdfs(catalog: ManualCatalog, manuals_dir: Path, *, skip: Path | None = None) -> dict[str, Located]:
    """Find every catalog PDF in ``manuals_dir`` (see the module docstring); keyed by document id, catalog order.

    Never fails on extra files; a folder that does not exist simply finds nothing."""
    found: dict[str, Located] = {}
    for doc in catalog.docs:
        for candidate in _variants(manuals_dir, doc.file):
            if candidate.is_file():
                digest = sha256_file(candidate)
                state: PdfState = "ok" if digest == doc.sha256 else "mismatch"
                found[doc.id] = Located(doc, state, candidate, digest, "catalog path")
                break
    pending = {doc.id: doc for doc in catalog.docs if doc.id not in found or found[doc.id].state != "ok"}
    if pending and manuals_dir.is_dir():
        by_size: dict[int, list[ManualDoc]] = {}
        for doc in pending.values():
            by_size.setdefault(doc.size, []).append(doc)
        for path in _walk_pdfs(manuals_dir, skip):
            if not pending:
                break
            try:
                size = path.stat().st_size
            except OSError:
                continue
            candidates = [doc for doc in by_size.get(size, []) if doc.id in pending]
            if not candidates:
                continue
            digest = sha256_file(path)
            for doc in candidates:
                if digest == doc.sha256:
                    found[doc.id] = Located(doc, "ok", path, digest, "found by size and sha256")
                    del pending[doc.id]
    result: dict[str, Located] = {}
    for doc in catalog.docs:
        result[doc.id] = found.get(doc.id) or Located(doc, "missing", None, None, "not found")
    return result
