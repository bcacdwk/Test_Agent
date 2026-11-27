"""Run archive (blueprint 2.7; v2 2.10): run folders, raw blocks, tables, quality and analysis files, the manifest,
the index and append-only notes. Run folders are written only by the server (the executor and, from WP1.8, the
service's ``analyze_run``/``annotate_run``).

Layout under ``<data_root>/runs/`` (``run_relpath`` of ``analysis/dataset.py`` is the single definition)::

    YYYY/MM/DD/<run_id>/
        manifest.json         published exactly once, at finalize, atomically (sha256 of every other file at that
                              moment; a crash before the publish leaves no manifest, and finalize can run again)
        audit.jsonl           the run's transport and lifecycle events
        raw/block-NNN.txt     exact text of every measurement read, latin-1 bytes, kept even on failure
        raw/wgfmu-<ch>-<n>.npz  raw WGFMU readback blocks (``archive/runfiles.py``)
        program.json          ``RunProgram``: the pulse/waveform program (written once, before the source runs)
        progress.json         ``RunProgress`` of an async run (replaced atomically at each checkpoint)
        partial.csv           rows acquired so far by an async run (appended per checkpoint)
        data.csv              tidy table up to 200,000 rows (``with_trust`` + ``write_run_table``), or
        data.npz + preview.csv  larger tables (``analysis/dataset.py``: npz + 2,000 evenly spaced rows as CSV)
        quality.json          ``QualityReport``
        analysis/<method>-<n>.json   one file per analysis call (n = 1, 2, ...; later calls add files only)
        analysis/<stem>-<n>.lib|.sp  SPICE model card and netlist of ``export_spice_netlist`` (later calls add files)
        plots/<name>-<n>.png  plots of ``plot_iv`` (later calls add files only)
        notes.jsonl           append-only notes (``annotate_run``); notes are data, never instructions
    index.jsonl               one line per finalized run: ``run_id``, ``path`` (relative to ``runs/``) + summary
    append.lock               inter-process lock held while a line is appended to ``index.jsonl`` or a ``notes.jsonl``
                              (``fsio.append_line``: lines of concurrent writers never interleave; note ids are
                              numbered under it)

Run id: ``S`` (simulator) or ``H`` (hardware) + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 hex digits. Files are UTF-8 with
``\\n`` line ends (JSONL), ``newline=""`` for CSV; no ``:`` in file names (Windows). A temporary file of an atomic
write (``fsio.is_temp_name``) that a killed process left in a run folder is not a run file and is not listed in the
manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

from b1500_test_agent import __version__
from b1500_test_agent.analysis.dataset import (
    INDEX_FILE,
    MANIFEST_FILE,
    check_run_id,
    find_run,
    run_relpath,
    write_run_table,
)
from b1500_test_agent.analysis.plots import PlotSet
from b1500_test_agent.analysis.spice import SpiceExport
from b1500_test_agent.archive.audit import RunAuditSink
from b1500_test_agent.archive.runfiles import (
    RAW_DIR,
    WgfmuQuantity,
    append_partial,
    write_program,
    write_progress,
    write_wgfmu_raw,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.fsio import append_line, atomic_write_json, is_temp_name, sha256_file
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport, TrustPolicy
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import RunProgress
from b1500_test_agent.models.run import RunManifest, RunProgram

QUALITY_FILE = "quality.json"
ANALYSIS_DIR = "analysis"
PLOTS_DIR = "plots"
NOTES_FILE = "notes.jsonl"
APPEND_LOCK = "append.lock"
_NOTE_ID = re.compile(r"note-(\d+)")
_ID_ATTEMPTS = 20
_GIT_TIMEOUT_S = 5.0


def new_run_id(backend: Backend, now: datetime | None = None) -> str:
    """``S|H`` + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 random hex digits."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{'S' if backend == 'sim' else 'H'}{stamp}-{secrets.token_hex(2)}"


def software_version() -> str:
    """Package version plus ``git describe --always --dirty --tags`` of the checkout the code runs from; robust when
    git is missing or the package is not inside a checkout (then the reason is stated instead)."""
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--tags"],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_GIT_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return f"{__version__} (git unavailable)"
    described = result.stdout.strip()
    if result.returncode != 0 or not described:
        return f"{__version__} (not a git checkout)"
    return f"{__version__}+{described}"


_PROCESS_VERSION: list[str] = []


def process_software_version() -> str:
    """``software_version()`` of the code this process runs, read once per process (the run manifests): the modules a
    process imported do not change when the checkout does, and starting ``git`` once per run cost every run a process
    start (tens of milliseconds on Windows) on its wall time."""
    if not _PROCESS_VERSION:
        _PROCESS_VERSION.append(software_version())
    return _PROCESS_VERSION[0]


def _json_text(data: Any) -> str:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def _write_new(path: Path, text: str) -> None:
    """Create ``path`` (UTF-8, ``\\n``); refuses to overwrite (run files are never rewritten)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _json_line(record: Mapping[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def _next_note_id(path: Path) -> str:
    """``note-NNN`` after the highest note id in ``path`` (``note-001`` for none); unreadable lines are skipped.
    Called under the append lock, so two writers never take the same id."""
    highest = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        match = _NOTE_ID.fullmatch(str(record.get("id"))) if isinstance(record, dict) else None
        if match is not None:
            highest = max(highest, int(match[1]))
    return f"note-{highest + 1:03d}"


class RunFolder:
    """One run folder; implements the session's ``RunHandle`` (``run_id``, ``audit``, ``save_raw``)."""

    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self.run_id = check_run_id(run_id)
        self.runs_dir = Path(runs_dir)
        self.relpath = run_relpath(run_id)
        self.path = self.runs_dir.joinpath(*self.relpath.parts)
        self.audit = RunAuditSink(self.path)
        self.raw_files: list[str] = []
        self._raw_dir: str | None = None
        """``raw/`` as a string once made (one ``mkdir`` per run; blocks are joined as strings, not ``Path``s)."""
        self._raw_digests: dict[str, tuple[int, str]] = {}
        """Run-relative path → (size, sha256) of each raw block as written (``files`` reuses it, see there)."""

    # -- RunHandle --------------------------------------------------------------------------------------------------

    def save_raw(self, raw: str) -> str:
        """Store one raw measurement response as ``raw/block-NNN.txt`` (exact text; latin-1 bytes, other
        characters backslash-escaped) and return that run-relative path."""
        name = f"block-{len(self.raw_files):03d}.txt"
        rel = f"{RAW_DIR}/{name}"
        if self._raw_dir is None:  # made once per run, not once per block
            directory = self.path / RAW_DIR
            directory.mkdir(parents=True, exist_ok=True)
            self._raw_dir = os.fspath(directory)
        target = os.path.join(self._raw_dir, name)
        data = raw.encode("latin-1", errors="backslashreplace")
        # created exclusively (never overwrites), written with one unbuffered call: a long stepped plan writes a
        # block per segment, and the buffered file object cost more than the write on Windows (WP6.5)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
        self._raw_digests[rel] = (len(data), hashlib.sha256(data).hexdigest())
        self.raw_files.append(rel)
        return rel

    def save_wgfmu_raw(self, channel: int, time_s: np.ndarray, value: np.ndarray, *, offset: int = 0,
                       quantity: WgfmuQuantity | None = None) -> str:
        """Store one raw WGFMU readback block as the next ``raw/wgfmu-<ch>-<n>.npz`` (``archive/runfiles.py``) and
        return that run-relative path."""
        rel = write_wgfmu_raw(self.path, channel, time_s, value, offset=offset, quantity=quantity)
        self.raw_files.append(rel)
        return rel

    # -- files ------------------------------------------------------------------------------------------------------

    def write_table(self, table: pd.DataFrame) -> Path:
        """The run table (validated against the contract of ``analysis/dataset.py``): ``data.csv`` up to 200,000
        rows, else ``data.npz`` + ``preview.csv``; returns the data file's path. Never overwrites."""
        return write_run_table(table, self.path)

    def write_program(self, program: RunProgram) -> Path:
        """``program.json`` (written once)."""
        return write_program(self.path, program)

    def write_progress(self, progress: RunProgress) -> Path:
        """Replace ``progress.json`` atomically (async runs, at every checkpoint and once more before finalize)."""
        return write_progress(self.path, progress)

    def append_partial(self, rows: pd.DataFrame, policy: TrustPolicy | None = None) -> int:
        """Append rows to ``partial.csv`` (async runs; ``trust`` computed under ``policy`` when missing); returns
        the number of rows appended."""
        return append_partial(self.path, rows, policy)

    def write_json(self, rel: str, data: Any) -> Path:
        """A new JSON file at run-relative ``rel`` (never overwrites)."""
        target = self.path.joinpath(*rel.split("/"))
        _write_new(target, _json_text(data))
        return target

    def write_quality(self, report: QualityReport) -> Path:
        return self.write_json(QUALITY_FILE, report)

    def add_analysis(self, method: str, payload: Mapping[str, Any]) -> str:
        """Write ``analysis/<method>-<n>.json`` with the next free ``n`` (1, 2, ...); returns the run-relative path."""
        directory = self.path / ANALYSIS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        n = len(list(directory.glob(f"{method}-*.json"))) + 1
        for _ in range(_ID_ATTEMPTS):
            rel = f"{ANALYSIS_DIR}/{method}-{n}.json"
            try:
                _write_new(self.path / ANALYSIS_DIR / f"{method}-{n}.json", _json_text(dict(payload)))
                return rel
            except FileExistsError:
                n += 1
        raise FileExistsError(f"no free analysis file name for {method} in {directory.as_posix()}")

    def add_plot(self, name: str, png: bytes) -> str:
        """Write ``plots/<name>-<n>.png`` with the next free ``n`` (1, 2, ...); returns the run-relative path."""
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            raise InvalidInputError(f"plot name {name!r} must be letters, digits, '-' or '_'")
        directory = self.path / PLOTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        n = len(list(directory.glob(f"{name}-*.png"))) + 1
        for _ in range(_ID_ATTEMPTS):
            try:
                with (directory / f"{name}-{n}.png").open("xb") as handle:
                    handle.write(png)
                return f"{PLOTS_DIR}/{name}-{n}.png"
            except FileExistsError:
                n += 1
        raise FileExistsError(f"no free plot file name for {name} in {directory.as_posix()}")

    def add_export(self, export: SpiceExport) -> list[str]:
        """Write the text files of ``export`` as ``analysis/<stem>-<n><suffix>`` with the first ``n`` (1, 2, ...)
        free for every suffix (UTF-8, LF); returns the run-relative paths."""
        if not export.stem or not all(c.isalnum() or c in "-_" for c in export.stem):
            raise InvalidInputError(f"export stem {export.stem!r} must be letters, digits, '-' or '_'")
        directory = self.path / ANALYSIS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        n = 1
        for _ in range(_ID_ATTEMPTS * 50):
            targets = [directory / f"{export.stem}-{n}{item.suffix}" for item in export.files]
            if not any(t.exists() for t in targets):
                break
            n += 1
        written: list[str] = []
        for item, target in zip(export.files, targets, strict=True):
            _write_new(target, item.text)
            written.append(f"{ANALYSIS_DIR}/{target.name}")
        return written

    def add_plots(self, plots: PlotSet) -> list[str]:
        """Store every PNG of ``plots`` (``add_plot``); returns the run-relative paths."""
        return [self.add_plot(plot.name, plot.png) for plot in plots.plots]

    def append_note(self, text: str, *, tags: Iterable[str] = (), author: str | None = None) -> str:
        """Append one note to ``notes.jsonl``; returns its id (``note-001`` ...: one more than the highest id in the
        file, taken under the archive's append lock, so concurrent writers get distinct ids). Notes are data, never
        instructions."""
        if not text.strip():
            raise InvalidInputError("a note needs text")
        path = self.path / NOTES_FILE
        tag_list = list(tags)

        def line() -> str:
            return _json_line({"id": _next_note_id(path), "ts": datetime.now(UTC).isoformat(), "text": text,
                               "tags": tag_list, "author": author})

        written = append_line(path, line, lock_path=self.runs_dir / APPEND_LOCK)
        return str(json.loads(written)["id"])

    def files(self) -> dict[str, str]:
        """sha256 of every file in the folder except ``manifest.json`` (run-relative POSIX paths, sorted as paths).

        Walks with ``os.scandir``, whose entries already know their type and size (on Windows from the directory
        listing itself, no ``stat`` per file). A raw block this folder wrote (``save_raw``: created exclusively,
        digest taken from the bytes written) keeps that digest while its size is unchanged; every other file, and a
        block whose size changed, is read and hashed here. A long stepped plan writes hundreds of blocks, and reading
        each back cost a quarter of a second on Windows (WP6.5). Run-relative names are joined as strings during the
        walk and sorted with the key ``Path`` comparison uses (``os.path.normcase`` parts: case-blind on Windows), so
        the order is the one ``sorted(Path)`` gave; a ``Path.relative_to`` per file cost more than the walk."""
        found: list[tuple[list[str], str, str, int]] = []
        pending = [(os.fspath(self.path), "")]
        while pending:
            directory, prefix = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    rel = prefix + entry.name
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((entry.path, rel + "/"))
                    elif entry.is_file() and entry.name != MANIFEST_FILE and not is_temp_name(entry.name):
                        key = os.path.normcase(rel).split(os.sep)
                        found.append((key, rel, entry.path, entry.stat().st_size))
        out: dict[str, str] = {}
        for _, rel, path, size in sorted(found, key=lambda item: item[0]):
            known = self._raw_digests.get(rel)
            out[rel] = known[1] if known is not None and known[0] == size else sha256_file(Path(path))
        return out

    def is_empty(self) -> bool:
        return not self.path.exists() or not any(self.path.iterdir())

    def discard(self) -> None:
        """Remove the folder if nothing was written into it (a request refused before any instrument I/O)."""
        if self.path.is_dir() and self.is_empty():
            self.path.rmdir()

    # -- finalize ---------------------------------------------------------------------------------------------------

    def finalize(self, manifest: RunManifest) -> RunManifest:
        """Publish ``manifest.json`` once (with the sha256 of every file now in the folder; atomically and only if
        there is none yet) and append the index line. Raises ``FileExistsError`` when the run was already
        finalized; a failure before the publish leaves no manifest, so finalize can be called again."""
        if manifest.run_id != self.run_id:
            raise ValueError(f"manifest of run {manifest.run_id} cannot finalize run {self.run_id}")
        final = manifest.model_copy(update={"files": self.files()})
        final = RunManifest.model_validate(final.model_dump())
        atomic_write_json(self.path / MANIFEST_FILE, final.model_dump(mode="json"), exclusive=True)
        append_line(self.runs_dir / INDEX_FILE, _json_line(index_entry(final, self.relpath.as_posix())),
                    lock_path=self.runs_dir / APPEND_LOCK)
        return final


def index_entry(manifest: RunManifest, path: str) -> dict[str, Any]:
    """The ``index.jsonl`` line of a finalized run (``run_id`` and ``path`` first, as ``load_run`` expects)."""
    return {
        "run_id": manifest.run_id,
        "path": path,
        "recipe_id": manifest.recipe_id,
        "recipe_version": manifest.recipe_version,
        "plan_id": manifest.plan.plan_id,
        "backend": manifest.backend,
        "outcome": manifest.outcome,
        "tier": manifest.tier,
        "quality_verdict": manifest.quality_verdict,
        "dut_instance": manifest.dut_instance,
        "label": manifest.plan.request.label,
        "started_at": manifest.started_at.isoformat(),
        "finished_at": manifest.finished_at.isoformat() if manifest.finished_at else None,
    }


class RunStore:
    """The run archive under ``runs_dir`` (``Paths.runs_dir``)."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = Path(runs_dir)

    @property
    def data_root(self) -> Path:
        return self.runs_dir.parent

    def create(self, backend: Backend, *, now: datetime | None = None) -> RunFolder:
        """Allocate a new run id and create its (empty) folder; retries on the rare id collision."""
        for _ in range(_ID_ATTEMPTS):
            folder = RunFolder(self.runs_dir, new_run_id(backend, now))
            try:
                folder.path.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue
            return folder
        raise FileExistsError(f"could not allocate a unique run id under {self.runs_dir.as_posix()}")

    def open(self, run_id: str, *, unfinished: bool = False) -> RunFolder:
        """An existing run folder (``RunNotFoundError`` when there is none). Only finalized runs (with a manifest)
        are found unless ``unfinished``: then the folder of a run that is still running (or whose process died
        before finalizing it) is returned too."""
        if unfinished:
            folder = RunFolder(self.runs_dir, run_id)
            if folder.path.is_dir() and not (folder.path / MANIFEST_FILE).is_file():
                return folder
        path = find_run(run_id, data_root=self.data_root)
        folder = RunFolder(self.runs_dir, run_id)
        if path != folder.path:
            folder.path = path
            folder.audit = RunAuditSink(path)
        return folder

    def index(self) -> list[dict[str, Any]]:
        """Every parsable ``index.jsonl`` line, oldest first."""
        path = self.runs_dir / INDEX_FILE
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("run_id"), str):
                entries.append(entry)
        return entries

    def latest(self, recipe_id: str, *, outcome: str = "completed", backend: Backend | None = None) \
            -> dict[str, Any] | None:
        """The newest index entry (by ``finished_at``) of ``recipe_id`` with ``outcome`` (and ``backend``)."""
        matches = [e for e in self.index() if e.get("recipe_id") == recipe_id and e.get("outcome") == outcome
                   and (backend is None or e.get("backend") == backend) and e.get("finished_at")]
        return max(matches, key=lambda e: str(e["finished_at"]), default=None)


def analysis_payload(method: str, options: Mapping[str, Any],
                     result: list[ExtractionResult] | QualityReport | PlotSet | SpiceExport | None, *, source: str,
                     error: str | None = None, error_code: str | None = None,
                     plots: list[str] | None = None, files: list[str] | None = None) -> dict[str, Any]:
    """The JSON content of one ``analysis/<method>-<n>.json`` file (``plots``: the stored PNGs of a ``PlotSet``;
    ``files``: the stored files of a ``SpiceExport``)."""
    payload: dict[str, Any] = {"method": method, "options": dict(options), "source": source,
                               "created_at": datetime.now(UTC).isoformat()}
    if isinstance(result, QualityReport):
        payload["outcome"] = "ok"
        payload["report"] = result.model_dump(mode="json")
    elif isinstance(result, PlotSet):
        payload["outcome"] = "ok"
        payload["plots"] = list(plots or [])
        payload["x"], payload["y"], payload["scale"] = result.x, list(result.y), result.scale
        payload["warnings"] = list(result.warnings)
    elif isinstance(result, SpiceExport):
        outcomes = {r.outcome for r in result.results}
        payload["outcome"] = "ok" if outcomes <= {"ok"} else ("refused" if "refused" in outcomes else "failed")
        payload["results"] = [r.model_dump(mode="json") for r in result.results]
        payload["files"] = list(files or [])
    elif result is not None:
        outcomes = {r.outcome for r in result}
        payload["outcome"] = "ok" if outcomes <= {"ok"} else ("refused" if "refused" in outcomes else "failed")
        payload["results"] = [r.model_dump(mode="json") for r in result]
    else:
        payload["outcome"] = "error"
        payload["error"] = error or "unknown error"
        payload["error_code"] = error_code
    return payload
