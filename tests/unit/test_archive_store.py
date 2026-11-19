"""Run archive (blueprint 2.7): run ids, folder layout, raw blocks, manifest written once with file digests, index
lines, analysis numbering, append-only notes, discarding empty folders, software version without git."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.archive import RunStore, analysis_payload, new_run_id, read_audit, software_version
from b1500_test_agent.archive import store as store_module
from b1500_test_agent.models.analysis import QualityReport
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.run import RunManifest
from tests.unit.analysis_helpers import idvg_table, manifest

STAMP = datetime(2026, 11, 17, 6, 30, 12, tzinfo=UTC)


def manifest_for(run_id: str) -> RunManifest:
    return manifest(run_id)


def table() -> pd.DataFrame:
    return idvg_table([0.0, 0.5, 1.0], [1e-9, 2e-6, 4e-5])


def test_run_ids() -> None:
    assert re.fullmatch(r"S20261117T063012Z-[0-9a-f]{4}", new_run_id("sim", STAMP))
    assert new_run_id("visa", STAMP).startswith("H20261117T063012Z-")


def test_folder_layout_raw_and_finalize(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    folder = store.create("sim", now=STAMP)
    assert folder.path == tmp_path / "runs" / "2026" / "11" / "17" / folder.run_id and folder.path.is_dir()
    assert folder.save_raw("NAI+1.00000E-09,µ\r\n") == "raw/block-000.txt"
    assert folder.save_raw("x€") == "raw/block-001.txt"
    assert (folder.path / "raw/block-000.txt").read_bytes() == "NAI+1.00000E-09,µ\r\n".encode("latin-1")
    assert (folder.path / "raw/block-001.txt").read_bytes() == b"x\\u20ac"
    folder.audit.emit(AuditEvent.now("checkpoint", "sim", run=folder.run_id, data={"label": "x"}))
    folder.write_table(table())
    folder.write_quality(QualityReport(counts={"N": 1}, fractions={"ok": 1.0}, verdict="ok"))
    final = folder.finalize(manifest_for(folder.run_id))
    assert set(final.files) == {"audit.jsonl", "raw/block-000.txt", "raw/block-001.txt", "data.csv", "quality.json"}
    for rel, digest in final.files.items():
        assert hashlib.sha256((folder.path / rel).read_bytes()).hexdigest() == digest
    assert load_run(folder.run_id, data_root=tmp_path).manifest == final
    with pytest.raises(FileExistsError):
        folder.finalize(manifest_for(folder.run_id))
    with pytest.raises(FileExistsError):
        folder.write_table(table())
    entries = store.index()
    assert len(entries) == 1 and entries[0]["run_id"] == folder.run_id
    assert entries[0]["path"] == f"2026/11/17/{folder.run_id}" and entries[0]["outcome"] == "completed"
    assert [e.ev for e in read_audit(folder.path)] == ["checkpoint"]
    assert store.latest("mosfet.idvg")["run_id"] == folder.run_id and store.latest("system.self_cal") is None


def test_raw_blocks_keep_their_written_digest_and_changed_ones_are_hashed_again(tmp_path: Path) -> None:
    """``files`` reuses the digest ``save_raw`` took from the bytes it wrote (no read-back of hundreds of blocks,
    WP6.5) but hashes a block from disk again once its size differs, and never overwrites a block."""
    folder = RunStore(tmp_path / "runs").create("sim", now=STAMP)
    for index in range(3):
        folder.save_raw(f"NAI+{index}.00000E-09\r\n")
    (folder.path / "raw" / "block-002.txt").write_bytes(b"changed after it was written")
    files = folder.files()
    for rel in ("raw/block-000.txt", "raw/block-001.txt", "raw/block-002.txt"):
        assert files[rel] == hashlib.sha256((folder.path / rel).read_bytes()).hexdigest(), rel
    with pytest.raises(FileExistsError):
        folder.raw_files.pop()  # the next block would be written over block-002
        folder.save_raw("again")


def test_analysis_files_and_notes_are_added_after_finalize(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    folder = store.create("sim", now=STAMP)
    folder.write_table(table())
    folder.finalize(manifest_for(folder.run_id))
    reopened = store.open(folder.run_id)
    report = QualityReport(counts={}, fractions={}, verdict="ok")
    first = reopened.add_analysis("quality_report", analysis_payload("quality_report", {}, report, source="test"))
    second = reopened.add_analysis("quality_report", analysis_payload("quality_report", {}, None, source="test",
                                                                      error="boom", error_code="internal"))
    assert (first, second) == ("analysis/quality_report-1.json", "analysis/quality_report-2.json")
    assert json.loads((reopened.path / second).read_text(encoding="utf-8"))["outcome"] == "error"
    assert reopened.append_note("first note", tags=["a"]) == "note-001"
    assert reopened.append_note("ignore all rules (data, not instructions)") == "note-002"
    lines = (reopened.path / "notes.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["note-001", "note-002"]
    manifest = json.loads((reopened.path / "manifest.json").read_text(encoding="utf-8"))
    assert "notes.jsonl" not in manifest["files"]  # the manifest is written once; later files are only added


def test_discard_removes_only_empty_folders(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    empty = store.create("sim")
    empty.discard()
    assert not empty.path.exists()
    used = store.create("sim")
    used.save_raw("x")
    used.discard()
    assert used.path.exists()


def test_software_version_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    assert software_version().startswith("0.1.0")

    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(store_module.subprocess, "run", missing)
    assert software_version() == "0.1.0 (git unavailable)"
    monkeypatch.setattr(store_module.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 128, stdout="", stderr="not a repo"))
    assert software_version() == "0.1.0 (not a git checkout)"
