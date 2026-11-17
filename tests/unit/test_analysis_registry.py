"""Analysis method registry, uniform runner and headless plot helpers (blueprint 2.8, 5.1 ``analyze_run``)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from b1500_test_agent.analysis import (
    ANALYSIS_METHODS,
    MethodNotImplementedError,
    RunData,
    run_method,
)
from b1500_test_agent.analysis.plots import new_figure, save_figure
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport
from b1500_test_agent.models.recipe import AnalysisSpec, QualityCriteria
from tests.unit.analysis_helpers import VTH, idvg_table, linear_region_id, manifest

VG = np.linspace(-1.0, 3.0, 101)
IMPLEMENTED = {"quality_report", "vth_linear_extrapolation"}
DECLARED = {"vth_constant_current", "vth_max_gm", "subthreshold_swing", "gm_max", "ion_ioff", "output_metrics",
            "resistance", "diode_fit", "leakage_at", "memory_window", "plot_iv"}


def idvg_run(recipe_id: str = "mosfet.idvg", drain_status: list[str] | None = None) -> RunData:
    table = idvg_table(VG, linear_region_id(VG), drain_status=drain_status)
    return RunData(manifest(recipe_id=recipe_id), table)


def test_registry_lists_the_m1_and_declared_methods() -> None:
    assert set(ANALYSIS_METHODS) == IMPLEMENTED | DECLARED
    for name, method in ANALYSIS_METHODS.items():
        assert method.name == name and callable(method.fn) and method.summary
        assert method.status == ("implemented" if name in IMPLEMENTED else "declared")
        assert method.milestone == ("M1" if name in IMPLEMENTED else "M2")
    assert ANALYSIS_METHODS["vth_linear_extrapolation"].options == (
        "window", "subtract_half_vd", "segment", "force", "x", "y", "vd", "vd_param", "smooth", "fit_points")
    assert ANALYSIS_METHODS["quality_report"].options == ()
    with pytest.raises(TypeError):
        ANALYSIS_METHODS["x"] = ANALYSIS_METHODS["gm_max"]  # type: ignore[index]


@pytest.mark.parametrize("name", sorted(DECLARED))
def test_declared_methods_report_not_implemented(name: str) -> None:
    data = idvg_run("generic.smu_staircase")
    with pytest.raises(MethodNotImplementedError, match="declared but not implemented") as info:
        run_method(name, data)
    assert info.value.code == "not_implemented" and "M2" in str(info.value)
    with pytest.raises(MethodNotImplementedError):
        ANALYSIS_METHODS[name].fn(data)
    assert ANALYSIS_METHODS[name].options == ()


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


def test_plots_module_never_imports_pyplot() -> None:
    code = "import sys, b1500_test_agent.analysis.plots; print('matplotlib.pyplot' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120)
    assert out.stdout.strip() == "False"
