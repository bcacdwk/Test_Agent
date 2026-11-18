"""Run-table contract v2 (blueprint v2 2.10, WP5.7): optional columns, MFCMU quantities, ``data.csv`` up to 200,000
rows else ``data.npz`` + ``preview.csv``, ``load_run`` on both formats, excerpts, and the 1 M-row round trip."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import (
    CSV_MAX_ROWS,
    NPZ_FILE,
    PREVIEW_FILE,
    RunFormatError,
    load_run,
    read_table,
    read_table_excerpt,
    run_table_path,
    validate_table,
    value_column,
    with_trust,
    write_run_table,
    write_table,
)
from b1500_test_agent.analysis.dataset import (
    PREVIEW_MAX_ROWS,
    column_unit,
    parse_value_column,
    range_column,
    read_npz_table,
    sample_indices,
    write_npz_table,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.run import RunManifest
from tests.unit.analysis_helpers import RUN_ID, manifest

ROUND_TRIP_LIMIT_S = 5.0


def full_table(n: int = 12) -> pd.DataFrame:
    """A table with every optional column: WGFMU-like values, MFCMU values and all context columns."""
    steps = np.arange(n)
    table = pd.DataFrame({
        "trust": "ok",  # replaced by with_trust; put first to check the canonical order
        "gate_Cp": np.linspace(1e-12, 2e-12, n), "gate_Cp_status": "N",
        "gate_G": np.linspace(1e-9, 2e-9, n), "gate_G_status": ["N"] * (n - 1) + ["C"],
        "drain_V": np.linspace(0.0, 1.0, n),
        "drain_I": np.linspace(1e-6, 2e-6, n), "drain_I_status": "N",
        "drain_range": ["10mA"] * (n // 2) + ["1uA"] * (n - n // 2),
        "dc_v": np.linspace(-2.0, 2.0, n), "ac_vrms": 0.03, "freq_hz": 1e5,
        "range": "5V", "event": ["meas_1"] * n, "phase": ["stress", "read"] * (n // 2),
        "segment": ["fwd"] * (n // 2) + ["rev"] * (n - n // 2), "cycle": steps // 4,
        "t_s": steps * 1e-7, "step": steps,
    })
    return with_trust(table)


CANONICAL = ["step", "t_s", "cycle", "segment", "phase", "event", "freq_hz", "ac_vrms", "dc_v", "range",
             "drain_range", "gate_Cp", "gate_Cp_status", "gate_G", "gate_G_status", "drain_V", "drain_I",
             "drain_I_status", "trust"]


def big_table(n: int, *, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    status = np.where(rng.random(n) < 1e-3, "V", "N")
    return with_trust(pd.DataFrame({
        "step": np.arange(n), "t_s": np.arange(n) * 1e-7,
        "event": np.where(np.arange(n) < n // 2, "meas_1", "meas_2"), "range": "1mA",
        "drain_V": rng.normal(size=n), "drain_I": rng.normal(size=n) * 1e-6, "drain_I_status": status,
    }))


def finalize(run_dir: Path, data_file: Path, run_manifest: RunManifest | None = None) -> None:
    """Write ``manifest.json`` with the table file's digest, as the archive does."""
    final = (run_manifest or manifest()).model_copy(
        update={"files": {data_file.name: hashlib.sha256(data_file.read_bytes()).hexdigest()}})
    (run_dir / "manifest.json").write_text(final.model_dump_json(indent=1), encoding="utf-8", newline="\n")


def run_dir_of(root: Path) -> Path:
    path = root / "runs" / "2026" / "11" / "17" / RUN_ID
    path.mkdir(parents=True)
    return path


# -- Columns ---------------------------------------------------------------------------------------------------------


def test_value_columns_cover_the_mfcmu_quantities() -> None:
    units = {"V": "V", "I": "A", "Cp": "F", "G": "S", "Cs": "F", "Rs": "Ohm", "D": "1", "Z": "Ohm", "theta": "rad"}
    for qty, unit in units.items():
        name = value_column("gate", qty)
        assert parse_value_column(name) == ("gate", qty) and column_unit(name) == unit
    assert parse_value_column("x_theta_V") == ("x_theta", "V")
    for not_a_value in ("dc_v", "t_s", "freq_hz", "ac_vrms", "drain_range", "phase", "gate_C", "gate_cp"):
        assert parse_value_column(not_a_value) is None
    assert range_column("drain") == "drain_range"
    with pytest.raises(InvalidInputError):
        range_column("Drain")


def test_every_optional_column_is_validated_and_ordered() -> None:
    tidy = validate_table(full_table())
    assert list(tidy.columns) == CANONICAL
    assert tidy["step"].dtype == np.int64 and tidy["cycle"].dtype == np.int64
    for column in ("t_s", "freq_hz", "ac_vrms", "dc_v", "gate_Cp", "drain_V"):
        assert tidy[column].dtype == np.float64, column
    for column in ("segment", "phase", "event", "range", "drain_range", "gate_G_status", "trust"):
        assert tidy[column].map(type).eq(str).all(), column
    assert tidy["trust"].tolist()[-1] == "limited"  # gate_G compliance on the last row


def test_csv_round_trip_keeps_every_column(tmp_path: Path) -> None:
    table = full_table()
    back = read_table(write_table(table, tmp_path / "data.csv"))
    pd.testing.assert_frame_equal(back, validate_table(table))
    header = (tmp_path / "data.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(CANONICAL)


def test_context_columns_may_be_empty_where_allowed(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("step,t_s,event,range,freq_hz,dc_v,drain_I,drain_I_status,trust\n"
                    "0,,,,,,1e-6,N,ok\n1,0.5,m1,1mA,1000,0.1,2e-6,N,ok\n", encoding="utf-8")
    table = read_table(path)
    assert np.isnan(table["t_s"][0]) and table["t_s"][1] == 0.5 and table["event"].tolist() == ["", "m1"]
    assert np.isnan(table["freq_hz"][0]) and table["range"].tolist() == ["", "1mA"]


@pytest.mark.parametrize("change", [
    lambda t: t.assign(phase=["stress", "bake"] * 6),
    lambda t: t.assign(phase=[""] * 12),
    lambda t: t.assign(cycle=[-1] + [0] * 11),
    lambda t: t.assign(cycle=[0.5] * 12),
    lambda t: t.assign(cycle=[np.nan] + [0.0] * 11),
    lambda t: t.assign(t_s=[-1e-9] + [0.0] * 11),
    lambda t: t.assign(t_s=[np.inf] + [0.0] * 11),
    lambda t: t.assign(freq_hz=0.0),
    lambda t: t.assign(ac_vrms=-0.01),
    lambda t: t.assign(dc_v=[np.inf] + [0.0] * 11),
    lambda t: t.assign(event=["a b"] * 12),
    lambda t: t.assign(range=["x" * 33] * 12),
    lambda t: t.assign(drain_range=["1,2"] * 12),
    lambda t: t.assign(segment=[""] * 12),
    lambda t: t.drop(columns=["gate_Cp_status"]),  # an MFCMU value is always measured
    lambda t: t.assign(gate_Cp_status=["n"] * 12),
    lambda t: t.assign(notes="x"),
    lambda t: t.assign(gate_C=1.0),
    lambda t: t.assign(drain_V_status="N", drain_V_range="1V"),
])
def test_contract_violations_are_rejected(change: Any) -> None:
    with pytest.raises(RunFormatError):
        validate_table(change(full_table()))


def test_a_table_needs_a_value_column() -> None:
    with pytest.raises(RunFormatError, match="no value column"):
        validate_table(pd.DataFrame({"step": [0], "t_s": [0.0], "trust": ["ok"]}))


# -- npz -------------------------------------------------------------------------------------------------------------


def test_npz_round_trip_keeps_values_types_and_order(tmp_path: Path) -> None:
    table = full_table()
    path = write_npz_table(table, tmp_path / NPZ_FILE)
    back = read_npz_table(path)
    pd.testing.assert_frame_equal(back, validate_table(table))
    with np.load(path, allow_pickle=False) as archive:
        schema = json.loads(str(archive["schema"]))
        assert schema == {"format": "b1500-run-table", "version": 1, "rows": 12, "columns": CANONICAL}
        assert archive["col.step"].dtype == np.int64 and archive["col.t_s"].dtype == np.float64
        assert archive["col.trust"].dtype == np.uint8 and list(archive["lev.trust"]) == ["limited", "ok"]
        assert list(archive["lev.phase"]) == ["read", "stress"]


def test_empty_and_one_row_tables_round_trip(tmp_path: Path) -> None:
    for n in (0, 1):
        table = full_table(2).iloc[:n]
        back = read_npz_table(write_npz_table(table, tmp_path / f"t{n}.npz"))
        assert len(back) == n and list(back.columns) == CANONICAL


def _rewrite(path: Path, change: Any) -> None:
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    change(arrays)
    with path.open("wb") as handle:
        np.savez(handle, **arrays)


@pytest.mark.parametrize("change", [
    lambda a: a.update(schema=np.asarray(json.dumps({"format": "other", "version": 1, "rows": 12, "columns": []}))),
    lambda a: a.update(schema=np.asarray("not json")),
    lambda a: a.pop("col.drain_I"),
    lambda a: a.update({"col.drain_I": np.zeros(3)}),
    lambda a: a.update({"col.phase": np.full(12, 9, dtype=np.uint8)}),
    lambda a: a.update({"col.phase": np.full(12, -1, dtype=np.int8)}),
    lambda a: a.update({"col.phase": np.zeros(12, dtype=np.float64)}),
    lambda a: a.update({"col.step": np.zeros(12, dtype=np.int64)}),
])
def test_broken_npz_files_are_rejected(tmp_path: Path, change: Any) -> None:
    path = write_npz_table(full_table(), tmp_path / NPZ_FILE)
    _rewrite(path, change)
    with pytest.raises(RunFormatError):
        read_npz_table(path)


@pytest.mark.parametrize("keep", [0, 30, 400, -10])
def test_truncated_npz_files_are_rejected(tmp_path: Path, keep: int) -> None:
    path = write_npz_table(full_table(), tmp_path / NPZ_FILE)
    data = path.read_bytes()
    path.write_bytes(data[:keep])  # negative: cut the end
    with pytest.raises(RunFormatError):
        read_npz_table(path)


def test_npz_never_needs_pickle(tmp_path: Path) -> None:
    path = write_npz_table(full_table(), tmp_path / NPZ_FILE)
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            array = np.lib.format.read_array(io.BytesIO(archive.read(name)), allow_pickle=False)
            assert array.dtype != object, name


# -- Archive format choice -------------------------------------------------------------------------------------------


def test_up_to_200k_rows_stay_csv(tmp_path: Path) -> None:
    path = write_run_table(big_table(CSV_MAX_ROWS), tmp_path)
    assert path.name == "data.csv" and sorted(p.name for p in tmp_path.iterdir()) == ["data.csv"]


def test_larger_tables_go_to_npz_with_a_preview(tmp_path: Path) -> None:
    table = big_table(CSV_MAX_ROWS + 1)
    path = write_run_table(table, tmp_path)
    assert path.name == NPZ_FILE and sorted(p.name for p in tmp_path.iterdir()) == [NPZ_FILE, PREVIEW_FILE]
    preview = read_table(tmp_path / PREVIEW_FILE)
    assert len(preview) == PREVIEW_MAX_ROWS and list(preview.columns) == list(validate_table(table).columns)
    assert preview["step"].iloc[0] == 0 and preview["step"].iloc[-1] == CSV_MAX_ROWS
    assert np.all(np.diff(preview["step"].to_numpy()) > 0)
    full = validate_table(table)
    pd.testing.assert_frame_equal(preview, full.iloc[preview["step"].to_numpy()].reset_index(drop=True))
    with pytest.raises(FileExistsError):
        write_run_table(table, tmp_path)


def test_one_million_rows_round_trip_quickly(tmp_path: Path) -> None:
    table = big_table(1_000_000)
    t0 = time.perf_counter()
    path = write_run_table(table, tmp_path)
    back = read_table(path)
    elapsed = time.perf_counter() - t0
    assert path.name == NPZ_FILE
    pd.testing.assert_frame_equal(back, validate_table(table))
    assert elapsed < ROUND_TRIP_LIMIT_S, f"1 M-row npz round trip took {elapsed:.2f} s"


def test_csv_round_trip_at_the_limit_is_exact(tmp_path: Path) -> None:
    table = big_table(CSV_MAX_ROWS)
    t0 = time.perf_counter()
    back = read_table(write_run_table(table, tmp_path))
    elapsed = time.perf_counter() - t0
    pd.testing.assert_frame_equal(back, validate_table(table))
    assert elapsed < ROUND_TRIP_LIMIT_S, f"200k-row CSV round trip took {elapsed:.2f} s"


# -- Loading and excerpts --------------------------------------------------------------------------------------------


def test_load_run_reads_npz_runs_and_checks_their_digest(tmp_path: Path) -> None:
    run_dir = run_dir_of(tmp_path)
    table = big_table(CSV_MAX_ROWS + 10)
    data_file = write_run_table(table, run_dir)
    finalize(run_dir, data_file)
    data = load_run(RUN_ID, data_root=tmp_path)
    assert len(data.table) == CSV_MAX_ROWS + 10 and data.measured_columns == ["drain_I"]
    pd.testing.assert_frame_equal(data.table, validate_table(table))
    with data_file.open("r+b") as handle:  # flip one byte of the last value
        handle.seek(-1, 2)
        last = handle.read(1)
        handle.seek(-1, 2)
        handle.write(bytes([last[0] ^ 1]))
    with pytest.raises(RunFormatError, match="sha256"):
        load_run(RUN_ID, data_root=tmp_path)


def test_a_run_holds_exactly_one_table_file(tmp_path: Path) -> None:
    run_dir = run_dir_of(tmp_path)
    assert run_table_path(run_dir) is None
    write_table(full_table(), run_dir / "data.csv")
    assert run_table_path(run_dir) == run_dir / "data.csv"
    write_npz_table(full_table(), run_dir / NPZ_FILE)
    with pytest.raises(RunFormatError, match="exactly one"):
        run_table_path(run_dir)
    finalize(run_dir, run_dir / "data.csv")
    with pytest.raises(RunFormatError, match="exactly one"):
        load_run(RUN_ID, data_root=tmp_path)
    (run_dir / "data.csv").unlink()
    (run_dir / NPZ_FILE).unlink()
    with pytest.raises(RunFormatError, match="no data.csv or data.npz"):
        load_run(RUN_ID, data_root=tmp_path)


def test_sample_indices_keep_first_and_last() -> None:
    assert sample_indices(5, 10).tolist() == [0, 1, 2, 3, 4]
    assert sample_indices(0, 10).tolist() == [] and sample_indices(7, 1).tolist() == [0]
    picked = sample_indices(1_000_001, 200)
    assert len(picked) == 200 and picked[0] == 0 and picked[-1] == 1_000_000
    assert np.all(np.diff(picked) > 0)


@pytest.mark.parametrize("rows", [50, CSV_MAX_ROWS + 1])
def test_excerpts_of_both_formats(tmp_path: Path, rows: int) -> None:
    table = validate_table(big_table(rows))
    path = write_run_table(table, tmp_path)
    excerpt, total = read_table_excerpt(path, 200)
    assert total == rows and len(excerpt) == min(rows, 200)
    assert excerpt["step"].iloc[0] == 0 and excerpt["step"].iloc[-1] == rows - 1
    pd.testing.assert_frame_equal(excerpt, table.iloc[excerpt["step"].to_numpy()].reset_index(drop=True))
    whole, total = read_table_excerpt(path)
    assert total == rows and len(whole) == rows
