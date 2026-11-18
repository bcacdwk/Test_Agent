"""``plot_timeseries`` (blueprint v2 2.10 ``reliability.py``; WP5.7): x choice (t_s, cycle, step), one curve per
phase, log axes, trust markers, min/max decimation of long records, options through the registry, file output."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import RunData, plot_timeseries, run_method, with_trust
from b1500_test_agent.analysis.plots import PlotSet
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.analysis.reliability import envelope_indices, render_timeseries
from b1500_test_agent.archive import RunFolder, analysis_payload
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import RUN_ID, manifest

PNG = b"\x89PNG\r\n\x1a\n"


def bti_run(n: int = 60) -> RunData:
    """Stress/read cycles: drain current drifting down by a power law, gate held at 2 V, a compliance in a read."""
    t = np.linspace(0.0, 100.0, n)
    phase = np.where(np.arange(n) % 3 == 0, "read", "stress")
    status = ["N"] * n
    status[n // 2] = "C"
    table = with_trust(pd.DataFrame({
        "step": np.arange(n), "t_s": t, "cycle": np.arange(n) // 3, "phase": phase,
        "gate_V": np.full(n, 2.0), "drain_I": 1e-5 * (1 - 0.01 * t**0.3), "drain_I_status": status,
    }))
    return RunData(manifest(recipe_id="reliability.bti_sms", kind="stress_measure", params={}), table)


def test_time_series_plots_by_phase() -> None:
    plots = render_timeseries(bti_run(), scale="both")
    assert isinstance(plots, PlotSet) and plots.x == "t_s" and plots.y == ("drain_I",) and plots.scale == "both"
    assert [p.name for p in plots.plots] == ["timeseries-linear", "timeseries-log"]
    assert all(p.png.startswith(PNG) for p in plots.plots)
    assert plots.warnings == ()


def test_x_falls_back_to_cycle_then_step() -> None:
    run = bti_run()
    no_time = RunData(run.manifest, run.table.drop(columns=["t_s"]))
    assert render_timeseries(no_time).x == "cycle"
    bare = RunData(run.manifest, run.table.drop(columns=["t_s", "cycle", "phase"]))
    plots = render_timeseries(bare)
    assert plots.x == "step" and "no t_s or cycle column" in plots.warnings[0]
    assert render_timeseries(run, x="step").warnings == ()  # asked for explicitly: no warning
    with pytest.raises(InvalidInputError, match="no 't_s' column"):
        render_timeseries(bare, x="t_s")


def test_y_defaults_to_measured_columns_and_accepts_any_value_column() -> None:
    run = bti_run()
    assert render_timeseries(run, y=["gate_V", "drain_I"]).y == ("gate_V", "drain_I")
    with pytest.raises(InvalidInputError):
        render_timeseries(run, y=["bulk_I"])
    with pytest.raises(InvalidInputError):
        render_timeseries(run, y=["phase"])
    no_measured = RunData(run.manifest, run.table.drop(columns=["drain_I", "drain_I_status"]))
    with pytest.raises(InvalidInputError, match="no measured value column"):
        render_timeseries(no_measured)


def test_log_axes_leave_out_non_positive_points() -> None:
    run = bti_run()
    plots = render_timeseries(run, scale="log", log_time=True)
    assert len(plots.plots) == 1 and plots.plots[0].name == "timeseries-log"
    assert "1 point(s) not drawn" in plots.warnings[0]  # t_s = 0 on the log time axis


def test_invalid_data_are_not_drawn() -> None:
    run = bti_run()
    table = run.table.copy()
    table.loc[5, "drain_I"] = 199.999e99
    table.loc[5, "drain_I_status"] = "V"
    plots = render_timeseries(RunData(run.manifest, with_trust(table)))
    assert "1 point(s) not drawn" in plots.warnings[0]


def test_envelope_keeps_spikes() -> None:
    values = np.zeros(1_000_000)
    values[123_457] = 5.0
    values[876_543] = -3.0
    values[10:20] = np.nan
    kept = envelope_indices(values, 1000)
    assert len(kept) <= 1000 and 123_457 in kept and 876_543 in kept
    assert np.all(np.diff(kept) > 0)
    assert envelope_indices(values[:50], 1000).tolist() == list(range(50))
    assert envelope_indices(np.full(10, np.nan), 4).tolist() == []


def test_long_records_are_decimated_and_noted() -> None:
    n = 400_000
    t = np.arange(n) * 1e-7
    current = 1e-6 + 1e-9 * np.sin(t * 1e5)
    current[200_000] = 5e-6  # a random-telegraph-like spike must survive
    table = with_trust(pd.DataFrame({"step": np.arange(n), "t_s": t, "event": "meas_1", "drain_I": current,
                                     "drain_I_status": "N"}))
    plots = render_timeseries(RunData(manifest(recipe_id="wgfmu.dc_sample", kind="wgfmu_waveform"), table),
                              max_points=2000)
    assert any("thinned to the min/max envelope (max_points=2000)" in w for w in plots.warnings)


def test_mfcmu_quantities_plot_with_their_units() -> None:
    n = 30
    table = with_trust(pd.DataFrame({"step": np.arange(n), "t_s": np.arange(n) * 1.0, "freq_hz": 1e5,
                                     "gate_Cp": np.full(n, 1e-12), "gate_Cp_status": "N",
                                     "gate_D": np.full(n, 0.01), "gate_D_status": "N"}))
    plots = render_timeseries(RunData(manifest(recipe_id="moscap.ct", kind="cmu_measure"), table))
    assert plots.y == ("gate_Cp", "gate_D") and plots.plots[0].png.startswith(PNG)


def test_registry_runs_plot_timeseries_with_json_options(tmp_path: Path) -> None:
    method = ANALYSIS_METHODS["plot_timeseries"]
    assert method.output == "plots" and method.options == ("y", "x", "scale", "log_time", "max_points")
    out = run_method("plot_timeseries", bti_run(), {"scale": "log", "x": "cycle", "max_points": 500})
    assert isinstance(out, PlotSet) and out.x == "cycle" and out.scale == "log"
    for bad in ({"scale": "loglog"}, {"x": "gate_V"}, {"max_points": 10}, {"window": [0, 1]}):
        with pytest.raises(InvalidInputError):
            run_method("plot_timeseries", bti_run(), bad)
    folder = RunFolder(tmp_path / "runs", RUN_ID)
    stored = folder.add_plots(out)
    assert stored == ["plots/timeseries-log-1.png"]
    payload = analysis_payload("plot_timeseries", {"scale": "log"}, out, source="analyze_run", plots=stored)
    assert payload["outcome"] == "ok" and payload["x"] == "cycle" and payload["y"] == ["drain_I"]


def test_agent_scripts_write_into_their_out_dir(tmp_path: Path) -> None:
    paths = plot_timeseries(bti_run(), scale="both", out_dir=tmp_path / "plots")
    assert [p.name for p in paths] == ["timeseries-linear.png", "timeseries-log.png"]
    assert all(p.read_bytes().startswith(PNG) for p in paths)
