"""Run archive writes under concurrency and crashes: two processes annotate one run and finalize runs at the same
time (every ``notes.jsonl`` and ``index.jsonl`` line well formed, note ids unique: they come from the highest id
under the append lock, not from a line count); the manifest is published atomically and exclusively (an interrupt
before the publish leaves no manifest and finalize can run again, on both platform branches; of two finalizers of
one run exactly one wins); temporary files a killed writer left behind are not run files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from b1500_test_agent import fsio
from b1500_test_agent.analysis.errors import RunNotFoundError
from b1500_test_agent.archive.store import APPEND_LOCK, NOTES_FILE, RunFolder, RunStore
from b1500_test_agent.models.run import RunManifest
from tests.unit.analysis_helpers import idvg_table, manifest

NOTES_PER_PROCESS = 500
RUNS_PER_PROCESS = 25
START_TIMEOUT_S = 60.0
CHILD_TIMEOUT_S = 180.0

CHILD = r"""
import sys
import time
from pathlib import Path

from b1500_test_agent.archive.store import RunStore
from b1500_test_agent.models.run import RunManifest

runs, run_id, tag, notes, finals, ready, go = sys.argv[1:8]
store = RunStore(Path(runs))
folder = store.open(run_id)
template = RunManifest.model_validate_json((folder.path / "manifest.json").read_text(encoding="utf-8"))
Path(ready).touch()
deadline = time.monotonic() + 60
while not Path(go).exists():
    if time.monotonic() > deadline:
        sys.exit("no start signal")
    time.sleep(0.002)
every = int(notes) // int(finals)
for i in range(int(notes)):
    folder.append_note(f"{tag} {i}", tags=[tag], author=tag)
    if i % every == every - 1:
        new = store.create("sim")
        new.finalize(template.model_copy(update={"run_id": new.run_id}))
"""


def table() -> pd.DataFrame:
    return idvg_table([0.0, 0.5, 1.0], [1e-9, 2e-6, 4e-5])


def finalized_run(store: RunStore) -> RunFolder:
    folder = store.create("sim")
    folder.write_table(table())
    folder.finalize(manifest(folder.run_id))
    return folder


def index_lines(store: RunStore) -> list[str]:
    path = store.runs_dir / "index.jsonl"
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def test_two_processes_annotate_and_finalize_at_once(tmp_path: Path) -> None:
    """500 notes from each of two processes on one run, 25 finalized runs each meanwhile: 1,000 well-formed note
    lines with the ids ``note-001`` ... ``note-1000`` (each once), every process's notes in its own order, and one
    well-formed index line per finalized run."""
    store = RunStore(tmp_path / "runs")
    shared = finalized_run(store)
    go = tmp_path / "go"
    children = []
    for tag in ("alpha", "beta"):
        ready = tmp_path / f"ready-{tag}"
        argv = [sys.executable, "-c", CHILD, str(store.runs_dir), shared.run_id, tag, str(NOTES_PER_PROCESS),
                str(RUNS_PER_PROCESS), str(ready), str(go)]
        children.append((ready, subprocess.Popen(argv, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                 text=True, encoding="utf-8", errors="replace")))
    deadline = time.monotonic() + START_TIMEOUT_S
    while not all(ready.exists() for ready, _ in children):
        assert all(child.poll() is None for _, child in children), [c.communicate() for _, c in children]
        assert time.monotonic() < deadline, "the writers did not start"
        time.sleep(0.01)
    go.touch()
    for _, child in children:
        out, err = child.communicate(timeout=CHILD_TIMEOUT_S)
        assert child.returncode == 0, (out, err)

    lines = (shared.path / NOTES_FILE).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    total = 2 * NOTES_PER_PROCESS
    assert len(records) == total and all(isinstance(r, dict) for r in records)
    assert sorted(r["id"] for r in records) == sorted(f"note-{n:03d}" for n in range(1, total + 1))
    for tag in ("alpha", "beta"):
        mine = sorted((r for r in records if r["author"] == tag), key=lambda r: int(r["id"].split("-")[1]))
        assert [r["text"] for r in mine] == [f"{tag} {i}" for i in range(NOTES_PER_PROCESS)]
        assert all(r["tags"] == [tag] for r in mine)

    entries = [json.loads(line) for line in index_lines(store)]
    assert len(entries) == 1 + 2 * RUNS_PER_PROCESS
    assert len({e["run_id"] for e in entries}) == len(entries)
    for entry in entries:
        assert store.open(entry["run_id"]).path == store.runs_dir.joinpath(*entry["path"].split("/"))
    assert (store.runs_dir / APPEND_LOCK).is_file() or os.name == "nt"  # Windows removes a released lock file


def windows_rename(src: Any, dst: Any) -> None:
    """``os.rename`` with Windows semantics on any platform: an existing target is never replaced."""
    if os.path.lexists(dst):
        raise FileExistsError(str(dst))
    os.replace(src, dst)


@pytest.mark.parametrize("platform", ["posix", "windows"])
def test_an_interrupt_before_the_manifest_publish_leaves_no_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                     platform: str) -> None:
    """The process is interrupted after the manifest's temporary file is written, before it is published
    (``os.link`` on POSIX, ``os.rename`` on Windows; the platform is injected): no manifest, no temporary file, no
    index line, the run is still unfinished; a later finalize publishes it once."""
    monkeypatch.setattr(fsio, "_WINDOWS", platform == "windows")
    name = "rename" if platform == "windows" else "link"
    real = windows_rename if platform == "windows" else os.link
    crash = [True]

    def publish(src: Any, dst: Any) -> None:
        if crash:
            crash.clear()
            raise KeyboardInterrupt
        real(src, dst)

    monkeypatch.setattr(os, name, publish)
    store = RunStore(tmp_path / "runs")
    folder = store.create("sim")
    folder.write_table(table())
    before = sorted(p.name for p in folder.path.iterdir())
    with pytest.raises(KeyboardInterrupt):
        folder.finalize(manifest(folder.run_id))
    assert sorted(p.name for p in folder.path.iterdir()) == before
    assert index_lines(store) == []
    with pytest.raises(RunNotFoundError):
        store.open(folder.run_id)
    assert store.open(folder.run_id, unfinished=True).path == folder.path

    final = folder.finalize(manifest(folder.run_id))
    assert set(final.files) == set(before)
    published = RunManifest.model_validate_json((folder.path / "manifest.json").read_text(encoding="utf-8"))
    assert published == final
    with pytest.raises(FileExistsError):
        folder.finalize(manifest(folder.run_id))
    assert [json.loads(line)["run_id"] for line in index_lines(store)] == [folder.run_id]
    assert sorted(p.name for p in folder.path.iterdir()) == sorted([*before, "manifest.json"])


def finalize_after(folder: RunFolder, barrier: threading.Barrier, outcomes: list[str]) -> None:
    barrier.wait()
    try:
        folder.finalize(manifest(folder.run_id))
        outcomes.append("published")
    except FileExistsError:
        outcomes.append("refused")


def test_of_two_finalizers_of_one_run_exactly_one_wins(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    for _ in range(20):
        first = store.create("sim")
        first.write_table(table())
        second = RunFolder(store.runs_dir, first.run_id)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        threads = [threading.Thread(target=finalize_after, args=(f, barrier, outcomes)) for f in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["published", "refused"]
        RunManifest.model_validate_json((first.path / "manifest.json").read_text(encoding="utf-8"))
    runs = [json.loads(line)["run_id"] for line in index_lines(store)]
    assert len(runs) == len(set(runs)) == 20


def test_temporary_files_of_a_killed_writer_are_not_run_files(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    folder = store.create("sim")
    folder.write_table(table())
    (folder.path / ".progress.json.k2j3h4ab.tmp").write_text('{"half', encoding="utf-8")
    (folder.path / ".manifest.json.q9w8e7rt.tmp").write_text("{", encoding="utf-8")
    final = folder.finalize(manifest(folder.run_id))
    assert set(final.files) == {"data.csv"}


def test_note_ids_follow_the_highest_id_not_the_line_count(tmp_path: Path) -> None:
    """A malformed line, a torn line and a line without an id do not shift the numbering; the new note is a line of
    its own."""
    store = RunStore(tmp_path / "runs")
    folder = finalized_run(store)
    notes = folder.path / NOTES_FILE
    notes.write_text('{"id":"note-001","text":"a"}\nnot json\n{"text":"no id"}\n{"id":"note-007","text":"b"}\n'
                     '{"id":"note-0', encoding="utf-8")
    assert folder.append_note("next") == "note-008"
    assert folder.append_note("and next", tags=["t"]) == "note-009"
    lines = notes.read_text(encoding="utf-8").splitlines()
    assert lines[4] == '{"id":"note-0'
    assert [json.loads(line)["id"] for line in lines[5:]] == ["note-008", "note-009"]
    assert json.loads(lines[6])["tags"] == ["t"]
    other = finalized_run(store)
    assert other.append_note("first") == "note-001"
