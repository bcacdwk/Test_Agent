"""``b1500 manual`` (blueprint 5.2): read the Keysight manuals from the committed page corpus; CLI only (no MCP tool,
a documented exception of the CLI parity rule).

- ``search "<terms>" [--doc PG,WG] [-k 8]`` → ``PG p433 (4-115) · ERSSP · <snippet>`` lines
- ``page PG 433 [--to 435] [--printed 4-115] [--max-chars 6000]`` → at most three pages of text
- ``toc PG [--grep FMT]`` → the PDF outline with printed labels
- ``status`` → corpus current/stale/missing and which PDFs are in the manuals folder
- ``build [--src DIR] [--check]`` (developers) → rebuild ``references/manuals/corpus/`` from the PDFs, or verify it

Every query command is read-only and takes ``--json`` (the ``models.manuals`` result model). Exit codes: 0 answered
(``build``/``status``: ok), 1 nothing found or not ok, 2 usage error (unknown document, page out of range). The
manuals folder is ``$B1500_MANUALS_DIR`` or ``settings.manuals_dir`` (default: the clone's parent).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from pydantic import BaseModel

from b1500_test_agent.adapters.cli.core import JsonOption
from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.manuals import build, search
from b1500_test_agent.manuals.catalog import ManualError, ManualPaths
from b1500_test_agent.models.manuals import (
    ManualBuildReport,
    ManualPageResult,
    ManualSearchResult,
    ManualStatus,
    ManualTocResult,
)
from b1500_test_agent.models.station import Settings
from b1500_test_agent.paths import find_repo_root

manual_app = typer.Typer(
    help="Keysight manuals: search and read the committed page corpus (read-only; build is for developers).",
    no_args_is_help=True,
)

ResultT = TypeVar("ResultT", bound=BaseModel)


def manual_paths(src: Path | None = None) -> ManualPaths:
    """Paths of this clone: ``references/manuals/`` and the manuals folder (``--src`` > ``$B1500_MANUALS_DIR`` >
    ``settings.manuals_dir``; an invalid config falls back to the default setting)."""
    repo_root = find_repo_root()
    try:
        setting = ConfigLoader().get().settings.manuals_dir
    except InvalidConfigError:
        setting = Settings().manuals_dir
    paths = ManualPaths.for_repo(repo_root, setting)
    return paths if src is None else paths.with_manuals_dir(src, "--src")


def _run(call: Callable[[], ResultT]) -> ResultT:
    """Run a manual query; ``ManualError`` / config problems become a message and exit code 2 (usage) or 1."""
    try:
        return call()
    except ManualError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2 if exc.usage else 1) from exc
    except InvalidConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _emit(result: BaseModel, as_json: bool, lines: list[str], ok: bool) -> None:
    typer.echo(result.model_dump_json(indent=2) if as_json else "\n".join(lines))
    if not ok:
        raise typer.Exit(code=1)


def search_lines(result: ManualSearchResult) -> list[str]:
    lines = [result.message]
    for hit in result.hits:
        title = f" · {hit.title}" if hit.title else ""
        where = f" [{hit.ref}]" if hit.source == "extracts" else ""
        lines.append(f"{hit.cite}{title}{where} · {hit.snippet}")
    return lines


def page_lines(result: ManualPageResult) -> list[str]:
    lines = [result.message]
    for item in result.pages:
        where = f" [{item.ref}]" if item.ref else ""
        lines += ["", f"=== {item.cite}{where} · {item.outline_path} ===" if item.outline_path
                  else f"=== {item.cite}{where} ===", item.text]
    return lines


def toc_lines(result: ManualTocResult) -> list[str]:
    lines = [result.message]
    for entry in result.entries:
        page = "" if entry.p is None else f"p{entry.p}" + (f" ({entry.printed})" if entry.printed else "")
        lines.append(f"{'  ' * entry.level}{entry.title}  {page}".rstrip())
    return lines


def status_lines(result: ManualStatus) -> list[str]:
    lines = [result.message]
    for doc in result.docs:
        pdf = doc.pdf if not doc.path else f"{doc.pdf} {doc.path}"
        lines.append(f"  {doc.id:<8} {doc.pages:>4} p  corpus {doc.corpus_pages:>4}  PDF {pdf}  ({doc.edition})"
                     + (f"  {doc.note}" if doc.note else ""))
    return lines


def build_lines(report: ManualBuildReport) -> list[str]:
    lines = [report.message, f"  manuals folder: {report.manuals_dir}"]
    for doc in report.docs:
        check = "" if doc.check == "not_checked" else f"  {doc.check}"
        lines.append(f"  {doc.id:<8} PDF {doc.pdf:<8} {doc.pages:>4} p  {doc.labelled:>4} labelled  "
                     f"{doc.outline:>4} outline  {doc.chars:>8} chars{check}")
    lines += [f"  warning: {w}" for w in report.warnings]
    lines += [f"  problem: {p}" for p in report.problems]
    return lines


@manual_app.command("search")
def search_command(
    terms: Annotated[list[str], typer.Argument(help="Search terms (quote a phrase or pass several words).")],
    doc: Annotated[str | None, typer.Option("--doc", help="Only these documents, comma-separated (PG,WG).")] = None,
    k: Annotated[int, typer.Option("-k", "--top", min=1, max=search.MAX_K, help="Number of hits.")] =
    search.DEFAULT_K,
    as_json: JsonOption = False,
) -> None:
    """Rank manual pages for the terms (BM25; exact command/function titles first). Read-only."""
    docs = [d.strip() for d in doc.split(",") if d.strip()] if doc else None
    result = _run(lambda: search.search(manual_paths(), " ".join(terms), docs=docs, k=k))
    _emit(result, as_json, search_lines(result), result.ok)


@manual_app.command("page")
def page_command(
    doc: Annotated[str, typer.Argument(help="Document id (PG, WG, AN-RTN ...; see manual status).")],
    page: Annotated[int | None, typer.Argument(help="Physical 1-based PDF page.")] = None,
    to: Annotated[int | None, typer.Option("--to", help="Last PDF page (at most 3 pages in total).")] = None,
    printed: Annotated[str | None, typer.Option("--printed", help="Find the page by its printed label "
                                                                  "(e.g. 4-189).")] = None,
    max_chars: Annotated[int, typer.Option("--max-chars", help="Characters of text in total.")] =
    search.DEFAULT_MAX_CHARS,
    as_json: JsonOption = False,
) -> None:
    """Show the text of up to three manual pages. Read-only."""
    result = _run(lambda: search.page(manual_paths(), doc, page, to=to, printed=printed, max_chars=max_chars))
    _emit(result, as_json, page_lines(result), result.ok)


@manual_app.command("toc")
def toc_command(
    doc: Annotated[str, typer.Argument(help="Document id (PG, WG ...).")],
    grep: Annotated[str | None, typer.Option("--grep", help="Only titles matching this regex/text "
                                                            "(any case).")] = None,
    as_json: JsonOption = False,
) -> None:
    """List a manual's PDF outline (PG: one entry per command; WG: one per function). Read-only."""
    result = _run(lambda: search.toc(manual_paths(), doc, grep=grep))
    _emit(result, as_json, toc_lines(result), result.ok)


@manual_app.command("status")
def status_command(as_json: JsonOption = False) -> None:
    """Is the corpus built and current; which PDFs are in the manuals folder (optional). Read-only."""
    result = _run(lambda: search.status(manual_paths()))
    _emit(result, as_json, status_lines(result), result.ok)


@manual_app.command("build")
def build_command(
    src: Annotated[Path | None, typer.Option("--src", help="Folder with the PDFs (default: $B1500_MANUALS_DIR "
                                                           "or settings.manuals_dir).")] = None,
    check: Annotated[bool, typer.Option("--check", help="Rebuild in memory and compare with the committed corpus "
                                                        "byte for byte; write nothing.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Extract references/manuals/corpus/ from the catalog's PDFs (developers; PDFs are never committed)."""
    report = _run(lambda: build.build_corpus(manual_paths(src), check=check))
    _emit(report, as_json, build_lines(report), report.ok)
