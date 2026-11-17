"""MOSFET extraction (WP1.5 AC): analytic Vth error < 5 mV with/without the Vd/2 correction, C/T exclusion,
untrusted refusal unless forced, window at max gm."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from b1500_test_agent.analysis import RunData, gm, local_derivative, vth_linear_extrapolation
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, Quantity
from b1500_test_agent.models.recipe import QualityCriteria
from tests.unit.analysis_helpers import BETA, VD, VTH, ekv_like_id, idvg_table, linear_region_id, manifest
from tests.unit.helpers import assert_roundtrip

TOL = 5e-3  # V, the WP1.5 acceptance bound
VG = np.linspace(-1.0, 3.0, 101)
INVALID = 199.999e99


def mosfet_run(
    vg: np.ndarray = VG, drain_i: np.ndarray | None = None, *, vd: float = VD, **table_kwargs: object
) -> RunData:
    current = linear_region_id(vg, vd=vd) if drain_i is None else drain_i
    run_manifest = manifest(params={"vd": Quantity(value=vd, unit="V"), "vg_points": Quantity(value=len(vg))})
    return RunData(run_manifest, idvg_table(vg, current, **table_kwargs))  # type: ignore[arg-type]


# -- Analytic accuracy (AC) ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("vth", [0.42, -0.3, 1.1])
@pytest.mark.parametrize("vd", [0.02, 0.05, 0.1])
@pytest.mark.parametrize("points", [41, 101, 401])
def test_vth_error_is_below_5_mv_on_the_analytic_curve(vth: float, vd: float, points: int) -> None:
    vg = np.linspace(-1.0, 3.0, points)
    run_manifest = manifest(params={"vd": Quantity(value=vd, unit="V")})
    data = RunData(run_manifest, idvg_table(vg, linear_region_id(vg, vth=vth, vd=vd)))
    corrected = vth_linear_extrapolation(data)
    assert corrected.outcome == "ok" and abs(corrected.value - vth) < TOL
    assert corrected.fit["vd"] == vd and corrected.method_record.params["vd_source"] == "plan.resolved_params.vd"
    uncorrected = vth_linear_extrapolation(data, subtract_half_vd=False)
    assert abs(uncorrected.value - (vth + vd / 2)) < TOL  # the raw intercept is Vth + Vd/2
    assert uncorrected.fit.get("vd") is None and uncorrected.method_record.params["vd"] is None


def test_without_the_vd_correction_the_error_exceeds_the_bound() -> None:
    data = mosfet_run(vd=0.1)
    assert abs(vth_linear_extrapolation(data).value - VTH) < TOL
    assert abs(vth_linear_extrapolation(data, subtract_half_vd=False).value - VTH) > 0.04


def test_pmos_transfer_curve() -> None:
    vg = np.linspace(1.0, -3.0, 101)
    vd = -0.05
    drain_i = -linear_region_id(-vg, vth=0.42, vd=0.05)  # mirror image of an nmos with Vth 0.42 V
    result = vth_linear_extrapolation(mosfet_run(vg, drain_i, vd=vd))
    assert abs(result.value - (-0.42)) < TOL and result.fit["x_intercept"] == pytest.approx(-0.445)


def test_result_shape() -> None:
    result = vth_linear_extrapolation(mosfet_run())
    assert result.method == "vth_linear_extrapolation" and result.quantity == "vth" and result.unit == "V"
    assert result.derived is True and result.forced_on_untrusted is False and result.error is None
    assert result.window is not None and result.window.unit == "V" and result.points_used == 5
    assert result.points_used + sum(result.points_excluded.values()) == len(VG)
    assert set(result.fit) >= {"slope", "intercept", "r2", "x_intercept", "gm_max", "x_at_gm_max", "vd"}
    assert result.method_record.params["window"] == "max_gm"
    assert result.method_record.params["derivative"] == {"name": "savitzky_golay", "window_points": 5,
                                                         "polyorder": 2}
    assert_roundtrip(result)


@pytest.mark.parametrize(
    "change",
    [
        {"value": None},  # ok without a value
        {"outcome": "refused", "error": "Refused: x"},  # refused with a value
        {"value": None, "outcome": "failed"},  # failure without an error message
        {"error": "stray"},  # an error on an ok result
    ],
)
def test_extraction_result_value_matches_outcome(change: dict[str, object]) -> None:
    data = vth_linear_extrapolation(mosfet_run()).model_dump()
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({**data, **change})


# -- Drain bias ------------------------------------------------------------------------------------------------------


def test_drain_bias_comes_from_the_manifest_unless_overridden() -> None:
    curve = linear_region_id(VG, vd=0.05)
    data = RunData(manifest(params={"vd": Quantity(value=0.1, unit="V")}), idvg_table(VG, curve))
    assert vth_linear_extrapolation(data).value == pytest.approx(VTH + 0.025 - 0.05, abs=1e-9)
    override = vth_linear_extrapolation(data, vd=0.05)
    assert abs(override.value - VTH) < TOL and override.method_record.params["vd_source"] == "argument"
    renamed = RunData(manifest(params={"v_drain": Quantity(value=0.05, unit="V")}), idvg_table(VG, curve))
    assert abs(vth_linear_extrapolation(renamed, vd_param="v_drain").value - VTH) < TOL


def test_missing_or_non_voltage_drain_bias_is_an_input_error() -> None:
    curve = linear_region_id(VG)
    no_vd = RunData(manifest(params={}), idvg_table(VG, curve))
    with pytest.raises(InvalidInputError, match="pass vd="):
        vth_linear_extrapolation(no_vd)
    assert abs(vth_linear_extrapolation(no_vd, subtract_half_vd=False).value - (VTH + VD / 2)) < TOL
    amps = RunData(manifest(params={"vd": Quantity(value=1e-3, unit="A")}), idvg_table(VG, curve))
    with pytest.raises(InvalidInputError, match="not a voltage"):
        vth_linear_extrapolation(amps)


# -- Trust: C/T excluded, untrusted refused unless forced ------------------------------------------------------------


def test_compliance_points_are_excluded_from_the_fit() -> None:
    drain_i = linear_region_id(VG)
    status = ["N"] * len(VG)
    clamped = [60, 61, 62]  # Vg = 1.4 .. 1.48 V inside the window below; a clamped current would bend the line
    for i in clamped:
        drain_i[i] = 5e-5
        status[i] = "C"
    gate_status = ["T" if i == 70 else "N" for i in range(len(VG))]
    data = mosfet_run(drain_i=drain_i, drain_status=status, gate_status=gate_status)
    result = vth_linear_extrapolation(data, window=(1.0, 2.0))
    assert result.outcome == "ok" and abs(result.value - VTH) < TOL
    assert result.points_excluded["C"] == 3 and result.points_excluded["T"] == 1
    assert result.points_used == 26 - 4
    assert result.points_used + sum(result.points_excluded.values()) == len(VG)
    assert any("max_limited_fraction_in_fit" in w for w in result.warnings)  # 4 of 26 > 5 %
    relaxed = QualityCriteria(max_limited_fraction_in_fit=0.2)
    tolerant = vth_linear_extrapolation(data, window=(1.0, 2.0), criteria=relaxed)
    assert not any("max_limited_fraction_in_fit" in w for w in tolerant.warnings)
    at_max_gm = vth_linear_extrapolation(data)
    assert at_max_gm.outcome == "ok" and abs(at_max_gm.value - VTH) < TOL and at_max_gm.points_excluded["C"] == 3


@pytest.mark.parametrize("letter", ["V", "X", "F", "D", "G", "S", "U", "W"])
def test_untrusted_points_refuse_the_extraction_unless_forced(letter: str) -> None:
    drain_i = linear_region_id(VG)
    status = ["N"] * len(VG)
    for i in (10, 90):
        status[i] = letter
        drain_i[i] = INVALID if letter == "V" else drain_i[i] * 3
    data = mosfet_run(drain_i=drain_i, drain_status=status)
    refused = vth_linear_extrapolation(data)
    assert refused.outcome == "refused" and refused.value is None and refused.window is None
    assert refused.points_used == 0 and refused.points_excluded == {letter: 2}
    assert "untrusted" in refused.error and "force=True" in refused.error and not refused.forced_on_untrusted
    assert_roundtrip(refused)

    forced = vth_linear_extrapolation(data, force=True)
    assert forced.outcome == "ok" and abs(forced.value - VTH) < TOL
    assert forced.forced_on_untrusted is True and forced.warnings[0].startswith("Forced on untrusted data")
    assert forced.points_excluded[letter] == 2 and forced.method_record.params["force"] is True


def test_untrusted_gate_values_also_refuse() -> None:
    gate_status = ["X" if i == 30 else "N" for i in range(len(VG))]
    assert vth_linear_extrapolation(mosfet_run(gate_status=gate_status)).outcome == "refused"


def test_force_without_untrusted_data_is_not_flagged() -> None:
    result = vth_linear_extrapolation(mosfet_run(), force=True)
    assert result.outcome == "ok" and result.forced_on_untrusted is False and result.warnings == []


def test_recipe_policy_can_classify_a_letter_as_limited() -> None:
    status = ["X" if i == 10 else "N" for i in range(len(VG))]
    x_limited = QualityCriteria(limited=["C", "T", "X"], untrusted=["V", "F", "D", "G", "S", "U"])
    result = vth_linear_extrapolation(mosfet_run(drain_status=status), criteria=x_limited)
    assert result.outcome == "ok" and result.points_excluded["X"] == 1 and not result.forced_on_untrusted


def test_noise_dominated_response_is_refused_unless_forced() -> None:
    rng = np.random.default_rng(11)
    data = mosfet_run(drain_i=1e-11 * rng.standard_normal(len(VG)))
    refused = vth_linear_extrapolation(data)
    assert refused.outcome == "refused" and "noise-dominated" in refused.error
    forced = vth_linear_extrapolation(data, force=True)
    assert forced.outcome == "ok" and forced.forced_on_untrusted is True


def test_realistic_noise_is_accepted_and_barely_moves_vth() -> None:
    """Smooth curve with a gm peak (like the simulator), 0.1 % relative noise plus a 1 pA floor."""
    rng = np.random.default_rng(5)
    clean = ekv_like_id(VG)
    noisy = clean * (1 + 1e-3 * rng.standard_normal(len(VG))) + 1e-12 * rng.standard_normal(len(VG))
    reference = vth_linear_extrapolation(mosfet_run(drain_i=clean))
    result = vth_linear_extrapolation(mosfet_run(drain_i=noisy))
    assert result.outcome == "ok" and not result.forced_on_untrusted and result.warnings == []
    assert abs(result.value - reference.value) < TOL
    assert abs(reference.value - VTH) < 0.03  # method bias from mobility degradation and n*Vd/2 stays small
    assert reference.window.low < 0.8  # the tangent sits at the gm peak just above threshold


# -- Windows and segments --------------------------------------------------------------------------------------------


def test_window_is_centred_on_the_gm_maximum() -> None:
    """y' = Gaussian(x_p, s), so |gm| peaks at x_p and the tangent there meets y = 0 at x_p - s*sqrt(pi/2)."""
    x_p, s, g0 = 1.2, 0.25, 1e-4
    x = np.linspace(-1.0, 3.0, 401)
    y = g0 * s * math.sqrt(math.pi / 2) * (1 + np.array([math.erf((v - x_p) / (s * math.sqrt(2))) for v in x]))
    result = vth_linear_extrapolation(mosfet_run(x, y), subtract_half_vd=False)
    assert abs(result.fit["x_at_gm_max"] - x_p) <= 0.01 + 1e-12
    assert result.window.contains(x_p) and result.window.high - result.window.low == pytest.approx(0.04)
    assert abs(result.value - (x_p - s * math.sqrt(math.pi / 2))) < 2e-3
    assert result.fit["gm_max"] == pytest.approx(g0, rel=1e-3)


def test_explicit_window_uses_every_trusted_point_inside() -> None:
    result = vth_linear_extrapolation(mosfet_run(), window=(1.0, 2.0))
    assert abs(result.value - VTH) < TOL and result.points_used == 26
    assert result.window.low == pytest.approx(1.0) and result.window.high == pytest.approx(2.0)
    assert result.points_excluded == {"outside_window": len(VG) - 26}
    assert result.method_record.params["window"] == [1.0, 2.0] and "gm_max" not in result.fit


def test_edge_maximum_warns() -> None:
    vg = np.linspace(-1.0, 3.0, 101)
    result = vth_linear_extrapolation(mosfet_run(vg, 1e-5 * np.exp(vg)), subtract_half_vd=False)
    assert result.outcome == "ok" and any("end of the sweep" in w for w in result.warnings)


def test_double_sweep_segments_are_analysed_separately() -> None:
    vg = np.concatenate([VG, VG[::-1]])
    shift = 0.1  # reverse branch shifted, like a hysteretic FeFET
    drain_i = np.concatenate([linear_region_id(VG), linear_region_id(VG[::-1], vth=VTH + shift)])
    drain_status = ["N"] * len(VG) + ["V" if i == 5 else "N" for i in range(len(VG))]
    data = mosfet_run(vg, drain_i, drain_status=drain_status, segment=["fwd"] * len(VG) + ["rev"] * len(VG))
    fwd = vth_linear_extrapolation(data)  # the invalid point lies in the reverse branch only
    assert fwd.outcome == "ok" and abs(fwd.value - VTH) < TOL
    assert fwd.points_used + sum(fwd.points_excluded.values()) == len(VG)
    rev = vth_linear_extrapolation(data, segment="rev", force=True)
    assert abs(rev.value - (VTH + shift)) < TOL and rev.forced_on_untrusted
    assert vth_linear_extrapolation(data, segment="rev").outcome == "refused"


def test_single_sweep_has_no_reverse_segment() -> None:
    with pytest.raises(InvalidInputError, match="single sweep"):
        vth_linear_extrapolation(mosfet_run(), segment="rev")


def test_too_few_trusted_points_fail_without_a_value() -> None:
    vg = np.linspace(0.0, 2.0, 6)
    status = ["N", "N", "C", "C", "C", "N"]
    result = vth_linear_extrapolation(mosfet_run(vg, drain_status=status))
    assert result.outcome == "failed" and result.value is None and "trusted point" in result.error
    empty_window = vth_linear_extrapolation(mosfet_run(), window=(5.0, 6.0))
    assert empty_window.outcome == "failed" and "window" in empty_window.error


def test_flat_response_fails() -> None:
    result = vth_linear_extrapolation(mosfet_run(drain_i=np.full(len(VG), 1e-6)), window=(1.0, 2.0))
    assert result.outcome == "failed" and "flat" in result.error


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"window": (2.0, 1.0)}, ValidationError),
        ({"window": "min_gm"}, ValidationError),
        ({"smooth": 4}, ValidationError),
        ({"fit_points": 1}, ValidationError),
        ({"segment": "up"}, ValidationError),
        ({"x": "drain_I"}, InvalidInputError),
        ({"y": "gate_V"}, InvalidInputError),
        ({"x": "bulk_V"}, InvalidInputError),
    ],
)
def test_bad_arguments_raise(kwargs: dict[str, object], error: type[Exception]) -> None:
    with pytest.raises(error):
        vth_linear_extrapolation(mosfet_run(), **kwargs)  # type: ignore[arg-type]


def test_non_monotonic_sweep_without_segments_is_rejected() -> None:
    vg = np.concatenate([VG, VG[::-1]])
    with pytest.raises(InvalidInputError, match="monotonic"):
        vth_linear_extrapolation(mosfet_run(vg, linear_region_id(vg)))


# -- gm --------------------------------------------------------------------------------------------------------------


def test_local_derivative_is_exact_for_quadratics_on_any_grid() -> None:
    x = np.sort(np.random.default_rng(2).uniform(-1.0, 2.0, 40))
    y = 3 * x**2 + 2 * x + 1
    for smooth in (3, 5, 9):
        assert np.allclose(local_derivative(x, y, smooth), 6 * x + 2, rtol=1e-9, atol=1e-9)
    assert np.allclose(local_derivative(x, 2 * x, 1), 2.0)


def test_gm_on_the_analytic_curve() -> None:
    status = ["C" if i == 80 else "N" for i in range(len(VG))]
    data = mosfet_run(drain_status=status)
    before = data.table.copy()
    series = gm(data)
    assert series.attrs["unit"] == "S" and series.name == "gm" and len(series) == len(VG)
    linear = (VG > VTH + VD + 0.1) & (np.arange(len(VG)) != 80)
    assert np.allclose(series[linear], BETA * VD, rtol=1e-9)
    assert np.isnan(series[80]) and np.allclose(series[VG < VTH - 0.1], 0.0)
    pd.testing.assert_frame_equal(data.table, before)  # measured columns untouched


def test_gm_per_segment() -> None:
    vg = np.concatenate([VG, VG[::-1]])
    data = mosfet_run(vg, linear_region_id(vg), segment=["fwd"] * len(VG) + ["rev"] * len(VG))
    both = gm(data)
    assert np.allclose(both[np.concatenate([VG, VG[::-1]]) > 1.0], BETA * VD)
    only_rev = gm(data, segment="rev")
    assert only_rev[: len(VG)].isna().all() and only_rev[len(VG):].notna().all()
