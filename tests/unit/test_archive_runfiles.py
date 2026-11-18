"""Run-folder files of v2 (blueprint v2 2.6, 2.10; WP5.7): ``progress.json``, ``partial.csv``, ``program.json``,
``raw/wgfmu-<ch>-<n>.npz``, the npz run table through ``RunFolder``, and a manifest whose sha256 list covers them
all."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import CSV_MAX_ROWS, NPZ_FILE, PREVIEW_FILE, RunFormatError, load_run, validate_table
from b1500_test_agent.archive import (
    PARTIAL_FILE,
    PROGRAM_FILE,
    PROGRESS_FILE,
    RunStore,
    read_partial,
    read_program,
    read_progress,
    read_wgfmu_raw,
    wgfmu_raw_files,
)
from b1500_test_agent.archive.runfiles import (
    append_partial,
    check_wgfmu_channel,
    wgfmu_raw_name,
    write_program,
    write_progress,
    write_wgfmu_raw,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.plan import ParamFile, RunProgress
from b1500_test_agent.models.run import ProgramEntry, RunProgram
from tests.unit.analysis_helpers import manifest
from tests.unit.test_data_contract import big_table

STAMP = datetime(2026, 11, 17, 6, 30, 12, tzinfo=UTC)


def progress(done: int, state: str = "running") -> RunProgress:
    return RunProgress(state=state, done=done, total=10, phase="stress", elapsed_s=done * 1.5, eta_s=(10 - done) * 1.5,
                       last_values={"drain_I": 1e-6 * done}, updated_at=STAMP + timedelta(seconds=done))


def rows(start: int, n: int, *, trust: bool = False) -> pd.DataFrame:
    table = pd.DataFrame({"step": np.arange(start, start + n), "t_s": np.arange(start, start + n) * 0.5,
                          "phase": "read", "drain_I": np.full(n, 1e-6),
                          "drain_I_status": ["N"] * max(n - 1, 0) + ["C"] * min(n, 1)})
    if trust:
        table["trust"] = "ok"
    return table


def program() -> RunProgram:
    return RunProgram(kind="pulse_read", programs={
        "program": ProgramEntry(source="spgu", channels=[101], spec={"base_v": 0.0, "peak_v": 4.0, "width_s": 1e-6},
                                preview=["101: 0 -> 4 V, 1 us x1000"]),
        "read": ProgramEntry(source="wgfmu", channels=[201, 202], spec={"patterns": {"read": [[1e-6, 0.5]]}}),
    }, files={"table": ParamFile(path="recipes/waveforms/a.csv", origin="library", sha256="c" * 64, size_bytes=88)})


# -- progress.json ---------------------------------------------------------------------------------------------------


def test_progress_is_replaced_atomically(tmp_path: Path) -> None:
    assert read_progress(tmp_path) is None
    write_progress(tmp_path, progress(1))
    path = write_progress(tmp_path, progress(4))
    assert path.name == PROGRESS_FILE and read_progress(tmp_path) == progress(4)
    assert sorted(p.name for p in tmp_path.iterdir()) == [PROGRESS_FILE]  # no temporary file left behind
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RunFormatError, match=PROGRESS_FILE):
        read_progress(tmp_path)


# -- partial.csv -----------------------------------------------------------------------------------------------------


def test_partial_rows_append_in_the_data_csv_format(tmp_path: Path) -> None:
    assert read_partial(tmp_path) is None
    assert append_partial(tmp_path, rows(0, 3)) == 3
    assert append_partial(tmp_path, rows(3, 2)) == 2
    text = (tmp_path / PARTIAL_FILE).read_text(encoding="utf-8")
    assert text.count("step,") == 1 and text.endswith("\n") and "\r" not in text
    table = read_partial(tmp_path)
    assert table is not None and table["step"].tolist() == [0, 1, 2, 3, 4]
    assert table["trust"].tolist() == ["ok", "ok", "limited", "ok", "limited"]  # computed from the status letters
    assert list(table.columns) == ["step", "t_s", "phase", "drain_I", "drain_I_status", "trust"]


def test_partial_rows_must_keep_columns_and_continue_the_steps(tmp_path: Path) -> None:
    append_partial(tmp_path, rows(0, 3))
    with pytest.raises(RunFormatError, match="columns"):
        append_partial(tmp_path, rows(3, 2).drop(columns=["t_s"]))
    with pytest.raises(RunFormatError, match="continue after 2"):
        append_partial(tmp_path, rows(2, 2))
    with pytest.raises(RunFormatError):
        append_partial(tmp_path, rows(5, 2).assign(phase="bake"))
    assert append_partial(tmp_path, rows(5, 0)) == 0
    assert append_partial(tmp_path, rows(5, 1, trust=True)) == 1
    table = read_partial(tmp_path)
    assert table is not None and table["step"].tolist() == [0, 1, 2, 5]


def test_a_torn_last_line_is_ignored_then_cut(tmp_path: Path) -> None:
    append_partial(tmp_path, rows(0, 2))
    path = tmp_path / PARTIAL_FILE
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("2,1.0,re")  # a writer killed mid-line
    table = read_partial(tmp_path)
    assert table is not None and table["step"].tolist() == [0, 1]
    append_partial(tmp_path, rows(2, 1))
    table = read_partial(tmp_path)
    assert table is not None and table["step"].tolist() == [0, 1, 2]
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 and all(not line.endswith(",re") for line in lines)


def test_a_torn_header_starts_the_file_again(tmp_path: Path) -> None:
    (tmp_path / PARTIAL_FILE).write_text("step,t_", encoding="utf-8")
    assert read_partial(tmp_path) is None
    append_partial(tmp_path, rows(0, 1))
    table = read_partial(tmp_path)
    assert table is not None and table["step"].tolist() == [0]


def test_partial_of_a_long_run_reads_its_last_step(tmp_path: Path) -> None:
    for start in range(0, 20_000, 5_000):
        append_partial(tmp_path, rows(start, 5_000))
    with pytest.raises(RunFormatError, match="continue after 19999"):
        append_partial(tmp_path, rows(19_999, 1))
    table = read_partial(tmp_path)
    assert table is not None and len(table) == 20_000


# -- program.json ----------------------------------------------------------------------------------------------------


def test_program_is_written_once(tmp_path: Path) -> None:
    assert read_program(tmp_path) is None
    path = write_program(tmp_path, program())
    assert path.name == PROGRAM_FILE and read_program(tmp_path) == program()
    with pytest.raises(FileExistsError):
        write_program(tmp_path, program())
    path.write_text('{"kind": "x", "programs": {}}', encoding="utf-8")
    with pytest.raises(RunFormatError):
        read_program(tmp_path)


def test_a_program_names_a_source_and_channels() -> None:
    with pytest.raises(ValueError):
        ProgramEntry(source="cmu", channels=[7], spec={})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ProgramEntry(source="spgu", channels=[], spec={})
    with pytest.raises(ValueError):
        RunProgram(kind="spgu_pulse", programs={})


# -- raw WGFMU blocks ------------------------------------------------------------------------------------------------


def test_raw_wgfmu_blocks_are_numbered_per_channel(tmp_path: Path) -> None:
    t = np.arange(5) * 1e-7
    assert write_wgfmu_raw(tmp_path, 201, t, np.ones(5), quantity="V") == "raw/wgfmu-201-000.npz"
    assert write_wgfmu_raw(tmp_path, 202, t, np.zeros(5), quantity="I") == "raw/wgfmu-202-000.npz"
    assert write_wgfmu_raw(tmp_path, 201, t + 5e-7, np.full(5, 2.0), offset=5) == "raw/wgfmu-201-001.npz"
    assert [p.name for p in wgfmu_raw_files(tmp_path)] == ["wgfmu-201-000.npz", "wgfmu-201-001.npz",
                                                           "wgfmu-202-000.npz"]
    assert [p.name for p in wgfmu_raw_files(tmp_path, 202)] == ["wgfmu-202-000.npz"]
    block = read_wgfmu_raw(tmp_path / "raw" / "wgfmu-201-001.npz")
    assert (block.channel, block.index, block.offset, block.quantity, len(block)) == (201, 1, 5, None, 5)
    assert block.time_s.dtype == np.float64 and block.value.tolist() == [2.0] * 5
    assert read_wgfmu_raw(tmp_path / "raw" / "wgfmu-201-000.npz").quantity == "V"


def test_raw_wgfmu_blocks_keep_four_million_points(tmp_path: Path) -> None:
    n = 4_000_000
    rel = write_wgfmu_raw(tmp_path, 1002, np.arange(n) * 1e-8, np.linspace(-1.0, 1.0, n), quantity="I")
    block = read_wgfmu_raw(tmp_path / rel)
    assert rel == "raw/wgfmu-1002-000.npz" and len(block) == n and block.value[-1] == 1.0


@pytest.mark.parametrize("channel", [0, 1, 103, 1101, 7, True, "201"])
def test_wgfmu_channel_numbers_are_checked(channel: object) -> None:
    with pytest.raises(InvalidInputError):
        check_wgfmu_channel(channel)  # type: ignore[arg-type]


def test_raw_wgfmu_arguments_are_checked(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        write_wgfmu_raw(tmp_path, 201, np.zeros(3), np.zeros(4))
    with pytest.raises(InvalidInputError):
        write_wgfmu_raw(tmp_path, 201, np.zeros((2, 2)), np.zeros((2, 2)))
    with pytest.raises(InvalidInputError):
        write_wgfmu_raw(tmp_path, 201, np.zeros(2), np.zeros(2), offset=-1)
    with pytest.raises(InvalidInputError):
        write_wgfmu_raw(tmp_path, 201, np.zeros(2), np.zeros(2), quantity="Q")  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        wgfmu_raw_name(201, -1)
    (tmp_path / "raw").mkdir(exist_ok=True)
    np.savez(tmp_path / "raw" / "wgfmu-201-009.npz", format=np.asarray("other"))
    with pytest.raises(RunFormatError):
        read_wgfmu_raw(tmp_path / "raw" / "wgfmu-201-009.npz")
    rel = write_wgfmu_raw(tmp_path, 202, np.zeros(10), np.zeros(10))
    data = (tmp_path / rel).read_bytes()
    (tmp_path / rel).write_bytes(data[: len(data) // 2])
    with pytest.raises(RunFormatError):
        read_wgfmu_raw(tmp_path / rel)


# -- RunFolder and the manifest --------------------------------------------------------------------------------------


def test_manifest_sha256_covers_every_v2_file(tmp_path: Path) -> None:
    folder = RunStore(tmp_path / "runs").create("sim", now=STAMP)
    folder.write_program(program())
    folder.write_progress(progress(2))
    folder.append_partial(rows(0, 3))
    rel = folder.save_wgfmu_raw(201, np.arange(4) * 1e-7, np.ones(4), quantity="I")
    folder.write_progress(progress(10, "completed"))
    table = big_table(CSV_MAX_ROWS + 1)
    assert folder.write_table(table).name == NPZ_FILE
    with pytest.raises(FileExistsError):
        folder.write_table(table)
    final = folder.finalize(manifest(folder.run_id))
    assert rel == "raw/wgfmu-201-000.npz" and folder.raw_files == [rel]
    expected = {PROGRAM_FILE, PROGRESS_FILE, PARTIAL_FILE, rel, NPZ_FILE, PREVIEW_FILE}
    assert expected <= set(final.files), sorted(final.files)
    for name, digest in final.files.items():
        assert hashlib.sha256((folder.path / name).read_bytes()).hexdigest() == digest, name
    assert read_progress(folder.path) == progress(10, "completed")
    data = load_run(folder.run_id, data_root=tmp_path)
    pd.testing.assert_frame_equal(data.table, validate_table(table))
