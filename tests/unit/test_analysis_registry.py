"""Analysis method registry, uniform runner and headless plot helpers (blueprint 2.8, 5.1 ``analyze_run``). Since
WP2.2 every registered method is implemented; the ``declared`` path is checked with a synthetic method."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import get_args

import numpy as np
import pytest

from b1500_test_agent.analysis import (
    ANALYSIS_METHODS,
    MethodNotImplementedError,
    RunData,
    run_method,
)
from b1500_test_agent.analysis.plots import PlotSet, new_figure, plot_iv, save_figure
from b1500_test_agent.analysis.registry import AnalysisMethod, _declared, methods_for
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport
from b1500_test_agent.models.recipe import AnalysisSpec, QualityCriteria, RecipeFamily
from tests.unit.analysis_helpers import VTH, idvg_table, linear_region_id, manifest
from tests.unit.helpers import REPO_ROOT

VG = np.linspace(-1.0, 3.0, 101)
M1 = {"quality_report", "vth_linear_extrapolation"}
M2 = {"vth_constant_current", "vth_max_gm", "subthreshold_swing", "gm_max", "ion_ioff", "output_metrics",
      "resistance", "diode_fit", "leakage_at", "memory_window", "plot_iv"}
M5 = {"plot_timeseries"}
M8 = {"cv_cox", "cv_flatband", "cv_doping_profile", "cv_vth", "cv_hysteresis", "impedance_convert", "plot_cv"}  # WP8.3
M7 = {"sampling_summary", "time_to_breakdown", "dibl", "body_effect", "forward_voltage",  # WP7.4, WP7.2
      "kelvin_resistance", "zero_floor",  # WP7.1
      "bti_power_law", "degradation_vs_time", "silc",  # WP7.6
      "pulsed_vs_dc", "pulse_plateau",  # WP7.3
      "vth_search_value", "breakdown_voltage"}  # WP7.5
M9 = {"charge_pumping"}  # WP9.3


def idvg_run(recipe_id: str = "mosfet.idvg", drain_status: list[str] | None = None) -> RunData:
    table = idvg_table(VG, linear_region_id(VG), drain_status=drain_status)
    return RunData(manifest(recipe_id=recipe_id), table)


def test_registry_lists_every_method_as_implemented() -> None:
    assert set(ANALYSIS_METHODS) == M1 | M2 | M5 | M7 | M8 | M9
    for name, method in ANALYSIS_METHODS.items():
        assert method.name == name and callable(method.fn) and method.summary
        assert method.status == "implemented"
        assert method.milestone == ("M1" if name in M1 else "M2" if name in M2 else "M5" if name in M5 else
                                    "M8" if name in M8 else "M9" if name in M9 else "M7")
        assert "criteria" not in method.options and "d" not in method.options and "out_dir" not in method.options
        assert (name == "quality_report") == (not method.options)
    assert ANALYSIS_METHODS["vth_linear_extrapolation"].options == (
        "window", "subtract_half_vd", "segment", "force", "x", "y", "vd", "vd_param", "smooth", "fit_points")
    assert ANALYSIS_METHODS["quality_report"].options == ()
    with pytest.raises(TypeError):
        ANALYSIS_METHODS["x"] = ANALYSIS_METHODS["gm_max"]  # type: ignore[index]


def test_a_declared_method_reports_not_implemented() -> None:
    data = idvg_run("generic.smu_staircase")
    declared = AnalysisMethod(name="cv_fit", status="declared", output="extraction", summary="later",
                              fn=_declared("cv_fit", "M2"), families=("cmu",), milestone="M2")
    with pytest.raises(MethodNotImplementedError, match="declared but not implemented") as info:
        declared.run(data)
    assert info.value.code == "not_implemented" and "M2" in str(info.value)
    with pytest.raises(MethodNotImplementedError):
        declared.fn(data)
    assert declared.options == ()


@pytest.mark.parametrize(("name", "quantities"), [
    ("vth_constant_current", ["vth"]), ("vth_max_gm", ["vth"]), ("subthreshold_swing", ["ss"]),
    ("gm_max", ["gm_max"]), ("ion_ioff", ["ion", "ioff", "on_off_ratio"]),
])
def test_transfer_methods_run_through_the_registry(name: str, quantities: list[str]) -> None:
    from tests.unit.analysis_helpers import ekv_like_id, idvg_table

    data = RunData(manifest(), idvg_table(VG, ekv_like_id(VG)))
    results = run_method(name, data)
    assert [r.quantity for r in results] == quantities and all(r.outcome == "ok" for r in results)


def test_quality_report_runner() -> None:
    report = run_method("quality_report", idvg_run())
    assert isinstance(report, QualityReport) and report.verdict == "ok"


def test_vth_runner_takes_json_options() -> None:
    results = run_method("vth_linear_extrapolation", idvg_run(), {"window": [1.0, 2.0], "subtract_half_vd": True})
    assert isinstance(results, list) and len(results) == 1 and isinstance(results[0], ExtractionResult)
    assert abs(results[0].value - VTH) < 5e-3 and results[0].points_used == 26


def test_recipe_analysis_defaults_run_as_written() -> None:
    """The blueprint 2.6 ``mosfet.idvg`` default analysis runs through the runner unchanged."""
    spec = AnalysisSpec(method="vth_linear_extrapolation", options={"window": "max_gm", "subtract_half_vd": True})
    (result,) = run_method(spec.method, idvg_run(), spec.options)
    assert result.outcome == "ok" and abs(result.value - VTH) < 5e-3


@pytest.mark.parametrize(
    "options",
    [
        {"windo": "max_gm"},  # unknown option
        {"criteria": {"limited": ["C", "T", "V"], "untrusted": []}},  # the trust policy is not an option
        {"window": "foo"},
        {"window": [2.0, 1.0]},
        {"smooth": 4},
        {"x": "nope"},
    ],
)
def test_bad_options_are_input_errors(options: dict[str, object]) -> None:
    with pytest.raises(InvalidInputError):
        run_method("vth_linear_extrapolation", idvg_run(), options)


def test_unknown_method_is_an_input_error() -> None:
    with pytest.raises(InvalidInputError, match="known"):
        run_method("vth_magic", idvg_run())


def test_refusal_is_a_result_and_criteria_come_from_the_caller() -> None:
    status = ["X" if i == 10 else "N" for i in range(len(VG))]
    data = idvg_run(drain_status=status)
    (refused,) = run_method("vth_linear_extrapolation", data)
    assert refused.outcome == "refused" and refused.value is None
    (forced,) = run_method("vth_linear_extrapolation", data, {"force": True})
    assert forced.forced_on_untrusted
    x_limited = QualityCriteria(limited=["C", "T", "X"], untrusted=["V", "F", "D", "G", "S", "U"])
    (recipe_policy,) = run_method("vth_linear_extrapolation", data, criteria=x_limited)
    assert recipe_policy.outcome == "ok" and not recipe_policy.forced_on_untrusted


def test_methods_check_the_run_recipe() -> None:
    assert ANALYSIS_METHODS["vth_linear_extrapolation"].applies_to("mosfet.idvg", "smu_staircase")
    assert ANALYSIS_METHODS["vth_linear_extrapolation"].applies_to("generic.smu_staircase", "smu_staircase")
    assert not ANALYSIS_METHODS["vth_linear_extrapolation"].applies_to("mosfet.idvg", "smu_sampling")
    assert ANALYSIS_METHODS["quality_report"].applies_to("basic.diode_iv", "smu_staircase")
    with pytest.raises(InvalidInputError, match="does not apply"):
        run_method("vth_linear_extrapolation", idvg_run("basic.diode_iv"))
    assert run_method("quality_report", idvg_run("basic.diode_iv")).verdict == "ok"
    (generic,) = run_method("vth_linear_extrapolation", idvg_run("generic.smu_staircase"))
    assert generic.outcome == "ok"


# -- Plots -----------------------------------------------------------------------------------------------------------


def test_plots_render_headless_png(tmp_path: Path) -> None:
    figure = new_figure()
    axes = figure.add_subplot()
    axes.semilogy(VG, linear_region_id(VG) + 1e-12)
    path = save_figure(figure, tmp_path / "plots" / "idvg.png")
    assert path.read_bytes().startswith(b"\x89PNG")


def test_plot_iv_renders_a_plot_set_and_writes_files(tmp_path: Path) -> None:
    out = run_method("plot_iv", idvg_run(), {"scale": "log"})
    assert isinstance(out, PlotSet) and [p.name for p in out.plots] == ["iv-log"]
    assert out.x == "gate_V" and out.y == ("gate_I", "drain_I") and out.plots[0].png.startswith(b"\x89PNG")
    both = run_method("plot_iv", idvg_run())
    assert [p.name for p in both.plots] == ["iv-linear", "iv-log"]
    paths = plot_iv(idvg_run(), out_dir=tmp_path / "work")
    assert [p.name for p in paths] == ["iv-linear.png", "iv-log.png"] and all(p.read_bytes()[:4] == b"\x89PNG"
                                                                              for p in paths)
    with pytest.raises(InvalidInputError):
        run_method("plot_iv", idvg_run(), {"out_dir": str(tmp_path)})  # the server decides where plots go
    with pytest.raises(InvalidInputError):
        run_method("plot_iv", idvg_run(), {"scale": "cubic"})


def test_plots_module_never_imports_pyplot() -> None:
    code = "import sys, b1500_test_agent.analysis.plots; print('matplotlib.pyplot' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", check=True,
                         timeout=120)
    assert out.stdout.strip() == "False"


# -- Family tags (blueprint v2 2.10, WP5.7) --------------------------------------------------------------------------


def test_every_method_carries_valid_family_tags() -> None:
    families = set(get_args(RecipeFamily))
    for name, method in ANALYSIS_METHODS.items():
        assert method.families and set(method.families) <= families, name
        assert len(set(method.families)) == len(method.families), name
    # system.zero_check (WP7.1) archives a table: the table methods serve family system too
    assert {m.name for m in ANALYSIS_METHODS.values() if "system" in m.families} == {
        "quality_report", "plot_iv", "plot_timeseries", "zero_floor"}
    with pytest.raises(ValueError, match="families"):
        AnalysisMethod(name="x", status="declared", output="extraction", summary="x", fn=_declared("x", "M7"),
                       families=())
    with pytest.raises(ValueError, match="families"):
        AnalysisMethod(name="x", status="declared", output="extraction", summary="x", fn=_declared("x", "M7"),
                       families=("smu", "optics"))  # type: ignore[arg-type]


def test_methods_for_a_family() -> None:
    smu = {m.name for m in methods_for("smu")}
    assert {"quality_report", "vth_linear_extrapolation", "resistance", "plot_iv", "plot_timeseries"} <= smu
    assert {m.name for m in methods_for("nvm")} >= {"memory_window", "quality_report", "plot_timeseries"}
    assert "resistance" not in {m.name for m in methods_for("nvm")}
    assert {m.name for m in methods_for("cmu")} == {"quality_report", "plot_timeseries", *M8}
    assert {m.name for m in methods_for("system")} == {"quality_report", "plot_iv", "plot_timeseries", "zero_floor"}
    assert {"kelvin_resistance", "zero_floor"} <= {m.name for m in methods_for("smu")}
    with pytest.raises(InvalidInputError, match="family"):
        methods_for("optics")  # type: ignore[arg-type]


def test_applicable_methods_list_the_family_of_every_runnable_recipe() -> None:
    registry = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    checked = 0
    for recipe_id in registry.ids():
        recipe = registry.get(recipe_id)
        if recipe.kind in ("system", "cmu_correction") or registry.effective_status(recipe_id, "sim") == \
                "not_implemented":
            continue  # kinds without a run table (no data to analyse)
        for method in ANALYSIS_METHODS.values():
            if method.applies_to(recipe_id, recipe.kind):
                assert recipe.family in method.families, (method.name, recipe_id, recipe.family)
                checked += 1
        for spec in recipe.analysis_defaults:
            assert recipe.family in ANALYSIS_METHODS[spec.method].families, (spec.method, recipe_id)
    assert checked > 20
