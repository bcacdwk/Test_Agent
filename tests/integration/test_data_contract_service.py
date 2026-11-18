"""The v2 data contract through the executor and the service (blueprint v2 2.9, 2.10, 8.1 ``integration/`` "npz";
WP5.7): a run above the CSV limit is archived as ``data.npz`` + ``preview.csv`` with the same values, ``get_run``
returns at most 200 rows of an npz run whatever ``max_points`` asks, and ``analyze_run`` reads npz runs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent import service as service_module
from b1500_test_agent.analysis import dataset, load_run, read_table, validate_table, with_trust
from b1500_test_agent.analysis.dataset import load_manifest
from b1500_test_agent.archive import RunStore
from b1500_test_agent.service import NPZ_MAX_POINTS
from tests.integration.helpers import IDVG, World
from tests.integration.test_data_goldens import fixture_path

IDVD = {"recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}


def run_recipe(world: World, request: dict[str, str]) -> str:
    service = world.service()
    plan = service.validate_plan(**request)
    assert plan.ok and plan.tier == "ok", plan.message
    run = service.run_plan(plan.plan_id)  # type: ignore[arg-type]
    assert run.ok and run.run_id is not None, run.message
    return run.run_id


def test_a_run_above_the_csv_limit_is_archived_as_npz(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset, "CSV_MAX_ROWS", 50)
    service = world.service()
    plan = service.validate_plan(**IDVG)
    run = service.run_plan(plan.plan_id)  # type: ignore[arg-type]
    assert run.ok and run.run_id is not None and run.outcome == "completed", run.message
    assert run.artifacts["data"].endswith("data.npz") and run.artifacts["preview"].endswith("preview.csv")
    data = load_run(run.run_id, data_root=world.data)
    assert data.path is not None and not (data.path / "data.csv").exists()
    manifest = load_manifest(data.path)
    assert {"data.npz", "preview.csv", "quality.json"} <= set(manifest.files)
    # same values as the v1 CSV archive of the same request (golden), and the preview holds every row
    golden = read_table(fixture_path("mosfet.idvg"))
    pd.testing.assert_frame_equal(data.table, golden)
    pd.testing.assert_frame_equal(read_table(data.path / "preview.csv"), golden)
    vth = service.analyze_run(run.run_id, "vth_linear_extrapolation")
    assert vth.ok and vth.results[0].value == pytest.approx(0.42, abs=0.03), vth.message


def test_get_run_caps_npz_runs_at_200_rows(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "approx_tokens", lambda text: 0)  # no budget trimming: see the row cap
    csv_run = run_recipe(world, IDVD)
    monkeypatch.setattr(dataset, "CSV_MAX_ROWS", 100)
    npz_run = run_recipe(world, IDVD)
    service = world.service()
    as_csv = service.get_run(csv_run, include=["data"], max_points=5000)
    as_npz = service.get_run(npz_run, include=["data"], max_points=5000)
    assert as_csv.data is not None and as_npz.data is not None
    assert as_csv.data.rows_total == as_npz.data.rows_total == 505
    assert as_csv.data.rows_returned == 505 and as_csv.data.note == "full table: data.csv"
    assert as_npz.data.rows_returned == NPZ_MAX_POINTS == 200
    assert as_npz.data.note.startswith("full table: data.npz (every ~2.5th row shown")
    assert as_npz.data.columns == as_csv.data.columns
    assert as_npz.paths["data"].endswith("data.npz") and as_npz.paths["preview"].endswith("preview.csv")
    assert as_npz.data.rows[0][0] == 0 and as_npz.data.rows[-1][0] == 504  # first and last row kept
    small = service.get_run(npz_run, include=["data"], max_points=20)
    assert small.data is not None and small.data.rows_returned == 20


def test_get_run_and_analyze_run_on_a_large_npz_run(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    source = run_recipe(world, IDVG)
    service = world.service()
    real = load_run(source, data_root=world.data)
    assert real.path is not None
    n = 300_000
    rng = np.random.default_rng(3)
    table = with_trust(pd.DataFrame({
        "step": np.arange(n), "t_s": np.arange(n) * 1e-7, "event": "meas_1", "range": "10uA",
        "drain_V": np.full(n, 0.1), "drain_I": 1e-6 + rng.normal(size=n) * 1e-9, "drain_I_status": "N",
    }))
    folder = RunStore(world.runs_dir).create("sim")
    assert folder.write_table(table).name == "data.npz"
    final = folder.finalize(load_manifest(real.path).model_copy(update={"run_id": folder.run_id, "files": {}}))
    assert {"data.npz", "preview.csv"} <= set(final.files)

    detail = service.get_run(folder.run_id, include=["summary", "data"], max_points=10_000)
    assert detail.ok and detail.data is not None and detail.data.rows_total == n
    assert 2 <= detail.data.rows_returned <= NPZ_MAX_POINTS
    assert detail.data.rows[0][0] == 0 and detail.data.rows[-1][0] == n - 1  # first and last row kept
    monkeypatch.setattr(service_module, "approx_tokens", lambda text: 0)
    uncapped = service.get_run(folder.run_id, include=["data"], max_points=10_000)
    assert uncapped.data is not None and uncapped.data.rows_returned == NPZ_MAX_POINTS
    steps = [row[0] for row in uncapped.data.rows]
    assert steps == sorted(steps) and steps[-1] == n - 1

    plots = service.analyze_run(folder.run_id, "plot_timeseries", {"scale": "linear"})
    assert plots.ok and len(plots.plots) == 1 and plots.plots[0].endswith(".png"), plots.message
    quality = service.analyze_run(folder.run_id, "quality_report")
    assert quality.ok and quality.quality is not None and quality.quality.points == n
    pd.testing.assert_frame_equal(load_run(folder.run_id, data_root=world.data).table, validate_table(table))
