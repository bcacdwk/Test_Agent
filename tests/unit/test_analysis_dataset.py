"""Run-table contract, run lookup (derived folder and index fallback) and ``RunData`` (blueprint 2.7, 2.8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import (
    RunData,
    RunFormatError,
    RunNotFoundError,
    column_unit,
    load_run,
    read_table,
    run_relpath,
    status_column,
    validate_table,
    value_column,
    with_trust,
    work_dir_for,
    write_table,
)
from b1500_test_agent.analysis.dataset import parse_value_column, row_reasons, trust_levels
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity, TrustPolicy
from b1500_test_agent.paths import ENV_DATA_DIR
from tests.unit.analysis_helpers import RUN_ID, VD, append_index, idvg_table, linear_region_id, manifest, write_run

VG = np.linspace(-1.0, 3.0, 11)


def small_table() -> pd.DataFrame:
    return idvg_table(VG, linear_region_id(VG))


def mixed_status_table() -> pd.DataFrame:
    """Rows: ok; drain compliance; gate compliance (drain T); invalid drain; unknown letter on the gate."""
    return idvg_table(
        [0.0, 0.5, 1.0, 1.5, 2.0], [0.0, 1e-5, 2e-5, 199.999e99, 4e-5],
        gate_status=["N", "N", "C", "N", "W"], drain_status=["N", "C", "T", "V", "N"],
    )


# -- Column names and trust ------------------------------------------------------------------------------------------


def test_column_names_follow_the_contract() -> None:
    assert value_column("drain", "I") == "drain_I"
    assert status_column("drain_I") == "drain_I_status"
    assert parse_value_column("gate_top_V") == ("gate_top", "V")
    assert parse_value_column("gate_I_status") is None and parse_value_column("step") is None
    assert column_unit("gate_V") == "V" and column_unit("drain_I") == "A"
    for role, qty in (("Gate", "V"), ("gate", "C"), ("1gate", "I")):
        with pytest.raises(InvalidInputError):
            value_column(role, qty)


def test_trust_is_the_worst_level_of_the_measured_values() -> None:
    table = mixed_status_table()
    assert list(table["trust"]) == ["ok", "limited", "limited", "untrusted", "untrusted"]
    assert list(row_reasons(table)) == ["N", "C", "C", "V", "W"]
    assert list(trust_levels(table, columns=["drain_I"])) == ["ok", "limited", "limited", "untrusted", "ok"]
    oscillating = idvg_table([0.0, 1.0], [0.0, 1e-5], drain_status=["N", "X"])
    assert list(trust_levels(oscillating)) == ["ok", "untrusted"]
    x_limited = TrustPolicy(limited=["C", "T", "X"], untrusted=["V", "F", "D", "G", "S", "U"])
    assert list(trust_levels(oscillating, x_limited)) == ["ok", "limited"]
    with pytest.raises(InvalidInputError):
        trust_levels(table, columns=["gate_V"])  # a source column has no status


# -- data.csv --------------------------------------------------------------------------------------------------------


def test_write_table_is_canonical_utf8_with_lf(tmp_path: Path) -> None:
    table = small_table()
    # value columns keep their order; step, status columns and trust move to their canonical places
    shuffled = table[["trust", "drain_I_status", "gate_V", "gate_I", "step", "drain_I", "gate_I_status"]]
    path = write_table(shuffled, tmp_path / "data.csv")
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")
    header = raw.decode("utf-8").splitlines()[0]
    assert header == "step,gate_V,gate_I,gate_I_status,drain_I,drain_I_status,trust"
    back = read_table(path)
    pd.testing.assert_frame_equal(back, validate_table(table))
    assert back["drain_I"].tolist() == table["drain_I"].tolist()  # floats survive exactly


def test_double_sweep_keeps_its_segment_column(tmp_path: Path) -> None:
    vg = np.concatenate([VG, VG[::-1]])
    table = idvg_table(vg, linear_region_id(vg), segment=["fwd"] * 11 + ["rev"] * 11)
    back = read_table(write_table(table, tmp_path / "data.csv"))
    assert list(back.columns[:2]) == ["step", "segment"] and set(back["segment"]) == {"fwd", "rev"}


def test_missing_values_load_as_nan(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("step,gate_V,drain_I,drain_I_status,trust\n0,0.0,,N,ok\n1,0.1,1e-6,N,ok\n", encoding="utf-8")
    table = read_table(path)
    assert np.isnan(table["drain_I"][0]) and table["drain_I"][1] == 1e-6


@pytest.mark.parametrize(
    "change",
    [
        lambda t: t.assign(note="x"),  # column outside the contract
        lambda t: t.drop(columns=["trust"]),
        lambda t: t.drop(columns=["step"]),
        lambda t: t.drop(columns=["gate_V", "gate_I", "gate_I_status", "drain_I", "drain_I_status"]),
        lambda t: t.assign(bulk_I_status="N"),  # status column without its value column
        lambda t: t.assign(drain_I_status=["NC"] + ["N"] * 10),
        lambda t: t.assign(drain_I_status=["n"] * 11),
        lambda t: t.assign(drain_I_status=[""] * 11),
        lambda t: t.assign(trust=["good"] * 11),
        lambda t: t.assign(segment=["up"] * 11),
        lambda t: t.assign(step=[0, 2, 1, *range(3, 11)]),
        lambda t: t.assign(step=[0.5 + i for i in range(11)]),
        lambda t: t.assign(drain_I=["abc"] * 11),
    ],
)
def test_validate_table_rejects_contract_violations(change: Any) -> None:
    with pytest.raises(RunFormatError):
        validate_table(change(small_table()))


def test_run_data_validates_and_never_modifies_its_input() -> None:
    table = small_table()
    before = table.copy()
    data = RunData(manifest(), table)
    assert data.measured_columns == ["gate_I", "drain_I"] and data.source_columns == ["gate_V"]
    assert data.unit("drain_I") == "A" and data.param("vd") == Quantity(value=VD, unit="V")
    assert data.param("absent") is None and not data.has_segments and data.segments() == [None]
    pd.testing.assert_frame_equal(table, before)
    with pytest.raises(InvalidInputError):
        data.unit("source_I")
    with pytest.raises(InvalidInputError):
        data.rows("rev")
    with pytest.raises(RunFormatError):
        RunData(manifest(), table.assign(trust="maybe"))


def test_a_subset_is_the_validated_table_of_its_rows() -> None:
    """``RunData.subset`` (per-read analyses of a stress run) skips the second validation: rows of a validated table
    give exactly the table ``validate_table`` would return for them."""
    data = RunData(manifest(), mixed_status_table())
    for rows in (data.table.iloc[[1, 3, 4]], data.table[data.table["drain_I_status"] == "N"], data.table.iloc[:0]):
        sub = data.subset(rows)
        assert sub.manifest is data.manifest and sub.path == data.path
        pd.testing.assert_frame_equal(sub.table, validate_table(rows), check_exact=True)
    with pytest.raises(ValueError):
        data.subset(data.table.drop(columns=["gate_I"]))


def test_trusted_drops_limited_and_untrusted_rows() -> None:
    data = RunData(manifest(), mixed_status_table())
    assert data.trusted()["step"].tolist() == [0]
    assert data.trusted(columns=["drain_I"])["step"].tolist() == [0, 4]


# -- Run lookup ------------------------------------------------------------------------------------------------------


def test_run_folder_derives_from_the_run_id() -> None:
    assert run_relpath(RUN_ID).as_posix() == "2026/11/17/S20261117T063012Z-7f3a"
    assert run_relpath("H20270102T030405Z-00ff").as_posix() == "2027/01/02/H20270102T030405Z-00ff"


@pytest.mark.parametrize("bad", ["../x", "S2026-11-17-7f3a", "X20261117T063012Z-7f3a", "S20261117T063012Z-7F3A", ""])
def test_malformed_run_ids_are_rejected(bad: str, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        run_relpath(bad)
    with pytest.raises(InvalidInputError):
        load_run(bad, data_root=tmp_path)


def test_load_run_reads_the_derived_folder(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, small_table())
    assert run_dir == tmp_path / "runs" / "2026" / "11" / "17" / RUN_ID
    data = load_run(RUN_ID, data_root=tmp_path)
    assert data.run_id == RUN_ID and data.path == run_dir and len(data.table) == 11
    pd.testing.assert_frame_equal(data.table, validate_table(small_table()))
    assert load_run(RUN_ID, data_root=str(tmp_path)).run_id == RUN_ID


def test_load_run_falls_back_to_the_index(tmp_path: Path) -> None:
    write_run(tmp_path, small_table(), folder=tmp_path / "runs" / "moved" / "run-a")
    index = tmp_path / "runs" / "index.jsonl"
    index.write_text(
        "not json\n"
        + '{"run_id": "S20261117T063012Z-7f3a", "path": "../outside"}\n'
        + '{"run_id": "S20261117T063012Z-7f3a", "path": "/abs/path"}\n',
        encoding="utf-8",
    )
    with pytest.raises(RunNotFoundError):
        load_run(RUN_ID, data_root=tmp_path)
    append_index(tmp_path, RUN_ID, "moved/run-a")
    data = load_run(RUN_ID, data_root=tmp_path)
    assert data.path == tmp_path / "runs" / "moved" / "run-a"


def test_unknown_run_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(RunNotFoundError, match="index.jsonl") as info:
        load_run(RUN_ID, data_root=tmp_path)
    assert info.value.code == "invalid_input"


def test_load_run_checks_the_data_digest(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, small_table())
    data_csv = run_dir / "data.csv"
    tampered = data_csv.read_text(encoding="utf-8").replace(",N,ok", ",C,ok", 1)
    data_csv.write_text(tampered, encoding="utf-8", newline="")
    with pytest.raises(RunFormatError, match="sha256"):
        load_run(RUN_ID, data_root=tmp_path)


def test_load_run_rejects_broken_run_folders(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, small_table(), with_digest=False)
    (run_dir / "manifest.json").write_text(manifest("S20261117T063012Z-0000").model_dump_json(), encoding="utf-8")
    with pytest.raises(RunFormatError, match="belongs to run"):
        load_run(RUN_ID, data_root=tmp_path)
    (run_dir / "manifest.json").write_text('{"run_id": "S20261117T063012Z-7f3a"}', encoding="utf-8")
    with pytest.raises(RunFormatError, match="does not validate"):
        load_run(RUN_ID, data_root=tmp_path)
    (run_dir / "manifest.json").write_text(manifest().model_dump_json(), encoding="utf-8")
    (run_dir / "data.csv").unlink()
    with pytest.raises(RunFormatError, match="no data.csv"):
        load_run(RUN_ID, data_root=tmp_path)


def test_default_data_root_honors_b1500_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_run(tmp_path, small_table())
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    assert load_run(RUN_ID).path == tmp_path / "runs" / "2026" / "11" / "17" / RUN_ID


def test_work_dir_is_outside_the_run_folder(tmp_path: Path) -> None:
    target = work_dir_for(RUN_ID, work_root=tmp_path / "work")
    assert target == tmp_path / "work" / RUN_ID and target.is_dir()
    default = work_dir_for(RUN_ID, create=False)
    assert default.parts[-2:] == ("work", RUN_ID)
    with pytest.raises(InvalidInputError):
        work_dir_for("../../etc", work_root=tmp_path)


def test_with_trust_uses_the_given_policy() -> None:
    table = mixed_status_table().drop(columns=["trust"])
    strict = with_trust(table)
    assert list(strict["trust"]) == ["ok", "limited", "limited", "untrusted", "untrusted"]
    assert "trust" not in table.columns  # input untouched
