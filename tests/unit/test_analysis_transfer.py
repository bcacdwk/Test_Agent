"""M2 transfer-curve methods on analytic curves (WP2.2): vth_constant_current, vth_max_gm, subthreshold_swing,
gm_max and ion_ioff recover the known truth; C/T are excluded, untrusted data and noise-dominated responses are
refused unless forced, exactly like vth_linear_extrapolation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.analysis import RunData
from b1500_test_agent.analysis.mosfet import (
    gm_max,
    ion_ioff,
    subthreshold_swing,
    vth_constant_current,
    vth_linear_extrapolation,
    vth_max_gm,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from tests.unit.analysis_helpers import (
    BETA,
    VD,
    VTH,
    ekv_like_id,
    idvg_table,
    linear_region_id,
    manifest,
    subthreshold_id,
)
from tests.unit.helpers import assert_roundtrip

VG = np.linspace(-1.0, 3.0, 401)
INVALID = 199.999e99
TRANSFER = [vth_constant_current, vth_max_gm, subthreshold_swing, gm_max, ion_ioff]


def run_of(drain_i: np.ndarray, vg: np.ndarray = VG, *, vd: float = VD, **table_kwargs: object) -> RunData:
    return RunData(manifest(params={"vd": Quantity(value=vd, unit="V")}),
                   idvg_table(vg, drain_i, **table_kwargs))  # type: ignore[arg-type]


def first(result: object) -> object:
    return result[0] if isinstance(result, list) else result


# -- vth_constant_current --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("i_crit", [1e-9, 1e-8, 1e-7])
def test_constant_current_vth_is_exact_on_an_exponential(i_crit: float) -> None:
    data = run_of(subthreshold_id(VG, v0=0.3, i0=1e-7, ss_mv=80.0))
    result = vth_constant_current(data, i_crit_a=i_crit)
    expected = 0.3 + 0.080 * math.log10(i_crit / 1e-7)  # log-linear interpolation is exact here (to the knee)
    assert result.outcome == "ok" and result.quantity == "vth" and result.unit == "V"
    assert result.value == pytest.approx(expected, abs=2e-3)
    assert result.points_used == 2 and result.window is not None and result.window.contains(result.value)
    assert result.points_used + sum(result.points_excluded.values()) == len(VG)
    assert_roundtrip(result)


def test_constant_current_scales_with_w_over_l_and_handles_pmos() -> None:
    data = run_of(subthreshold_id(VG, v0=0.3, i0=1e-7, ss_mv=80.0))
    scaled = vth_constant_current(data, i_crit_a=1e-8, w_over_l=10.0)  # 1e-7 A in total
    assert scaled.value == pytest.approx(0.3, abs=2e-3) and scaled.fit["i_crit"] == pytest.approx(1e-7)
    vg = -VG
    pmos = run_of(-subthreshold_id(VG, v0=0.3), vg, vd=-VD)  # mirror image: |Id| grows towards negative Vg
    assert vth_constant_current(pmos).value == pytest.approx(-0.3, abs=2e-3)


def test_constant_current_fails_without_a_crossing() -> None:
    result = vth_constant_current(run_of(subthreshold_id(VG)), i_crit_a=1e-2)
    assert result.outcome == "failed" and result.value is None and "never rises through" in result.error


# -- vth_max_gm ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("vth", [0.42, -0.3, 1.1])
def test_max_gm_change_vth_on_the_square_law(vth: float) -> None:
    result = vth_max_gm(run_of(linear_region_id(VG, vth=vth)))
    assert result.outcome == "ok" and result.value == pytest.approx(vth, abs=5e-3)
    assert result.fit["x_peak"] == pytest.approx(vth + VD / 2, abs=5e-3)  # gm turns on between Vth and Vth + Vd
    uncorrected = vth_max_gm(run_of(linear_region_id(VG, vth=vth)), subtract_half_vd=False)
    assert uncorrected.value == pytest.approx(vth + VD / 2, abs=5e-3)


def test_max_gm_change_vth_on_a_smooth_curve_is_near_threshold() -> None:
    result = vth_max_gm(run_of(ekv_like_id(VG)))
    assert result.outcome == "ok" and result.value == pytest.approx(VTH, abs=0.03)
    assert result.fit["x_at_gm_max"] > result.fit["x_peak"]  # gm peaks above threshold (mobility degradation)


# -- subthreshold_swing ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ss_mv", [65.0, 80.0, 120.0])
def test_subthreshold_swing_is_recovered(ss_mv: float) -> None:
    result = subthreshold_swing(run_of(subthreshold_id(VG, ss_mv=ss_mv)))
    assert result.outcome == "ok" and result.unit == "mV/dec" and result.value == pytest.approx(ss_mv, rel=0.01)
    assert result.fit["r2"] >= 0.99 and result.points_used == 5
    by_decades = subthreshold_swing(run_of(subthreshold_id(VG, ss_mv=ss_mv)), decades=2.0)
    assert by_decades.value == pytest.approx(ss_mv, rel=0.01) and by_decades.fit["decades"] >= 2.0


def test_subthreshold_swing_of_the_ekv_curve_and_a_noise_floor() -> None:
    truth = 1.3 * 0.02585 * math.log(10) * 1000  # n U_T ln10 of ekv_like_id
    rng = np.random.default_rng(3)
    noisy = ekv_like_id(VG) * (1 + 1e-3 * rng.standard_normal(VG.size)) + 1e-13 * rng.standard_normal(VG.size)
    result = subthreshold_swing(run_of(noisy))
    assert result.outcome == "ok" and result.value == pytest.approx(truth, rel=0.03)
    assert result.fit["i_low"] > 1e-12  # the floor (scattered log10|I|) never forms a window


def test_subthreshold_swing_fails_without_a_subthreshold_region() -> None:
    flat = run_of(np.full(VG.size, 1e-6))  # no current rise anywhere
    result = subthreshold_swing(flat)
    assert result.outcome == "failed" and "No subthreshold window" in result.error


# -- gm_max ----------------------------------------------------------------------------------------------------------


def test_gm_max_on_the_square_law() -> None:
    result = gm_max(run_of(linear_region_id(VG)))
    assert result.outcome == "ok" and result.unit == "S" and result.value == pytest.approx(BETA * VD, rel=1e-6)
    peak = gm_max(run_of(ekv_like_id(VG)))
    assert peak.fit["x_at_gm_max"] == pytest.approx(vth_linear_extrapolation(run_of(ekv_like_id(VG))).fit[
        "x_at_gm_max"], abs=0.02)


# -- ion_ioff --------------------------------------------------------------------------------------------------------


def test_ion_ioff_at_given_and_default_biases() -> None:
    curve = subthreshold_id(VG)
    ion, ioff, ratio = ion_ioff(run_of(curve), v_on=2.0, v_off=0.0)
    on_value, off_value = np.interp(2.0, VG, curve), np.interp(0.0, VG, curve)
    assert (ion.quantity, ion.value) == ("ion", pytest.approx(on_value, rel=1e-6))
    assert (ioff.quantity, ioff.value) == ("ioff", pytest.approx(off_value, rel=1e-6))
    assert ratio.value == pytest.approx(on_value / off_value, rel=1e-6) and ratio.unit == "1"
    assert ion.bound == ioff.bound == ratio.bound == "exact"
    default = ion_ioff(run_of(curve))
    assert default[0].fit["v"] == 3.0 and default[1].fit["v"] == -1.0
    between = ion_ioff(run_of(curve), v_on=2.005, v_off=0.0)[0]  # interpolated between grid points
    assert between.value == pytest.approx(np.interp(2.005, VG, curve), rel=1e-6)


def test_ion_ioff_reports_a_floor_limited_ioff_as_an_upper_bound() -> None:
    rng = np.random.default_rng(8)
    curve = subthreshold_id(VG) + 1e-13 * rng.standard_normal(VG.size)
    _, ioff, ratio = ion_ioff(run_of(curve), v_off=-1.0)
    assert ioff.bound == "upper" and 1e-13 < ioff.value < 1e-12 and "noise floor" in ioff.warnings[0]
    assert ratio.bound == "lower"


def test_ion_ioff_outside_the_sweep_fails() -> None:
    [result] = ion_ioff(run_of(subthreshold_id(VG)), v_on=5.0)
    assert result.outcome == "failed" and "outside the trusted sweep range" in result.error


# -- shared trust rules ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", TRANSFER)
@pytest.mark.parametrize("letter", ["V", "X", "F"])
def test_untrusted_points_refuse_every_transfer_method_unless_forced(method, letter: str) -> None:
    curve = subthreshold_id(VG)
    status = ["N"] * VG.size
    for i in (20, 380):
        status[i] = letter
        curve[i] = INVALID if letter == "V" else curve[i] * 3
    data = run_of(curve, drain_status=status)
    refused = first(method(data))
    assert refused.outcome == "refused" and refused.value is None and "untrusted" in refused.error
    assert refused.points_excluded == {letter: 2} and not refused.forced_on_untrusted
    forced = first(method(data, force=True))
    assert forced.outcome == "ok" and forced.forced_on_untrusted
    assert forced.warnings[0].startswith("Forced on untrusted data")


@pytest.mark.parametrize("method", TRANSFER)
def test_noise_dominated_response_refuses_every_transfer_method(method) -> None:
    rng = np.random.default_rng(11)
    data = run_of(1e-11 * rng.standard_normal(VG.size))
    refused = first(method(data))
    assert refused.outcome == "refused" and "noise-dominated" in refused.error


def test_compliance_points_are_excluded_and_counted() -> None:
    curve = subthreshold_id(VG)
    status = ["N"] * VG.size
    for i in (300, 301):  # deep in the on state: clamped values must not enter any derivative
        status[i] = "C"
        curve[i] = 5e-5
    data = run_of(curve, drain_status=status)
    for method in (vth_constant_current, subthreshold_swing, gm_max):
        result = method(data)
        assert result.outcome == "ok" and result.points_excluded["C"] == 2
    assert subthreshold_swing(data).value == pytest.approx(80.0, rel=0.01)


def test_a_double_sweep_needs_its_segment() -> None:
    vg = np.concatenate([VG, VG[::-1]])
    data = run_of(np.concatenate([subthreshold_id(VG), subthreshold_id(VG, v0=0.5)[::-1]]), vg,
                  segment=["fwd"] * VG.size + ["rev"] * VG.size)
    assert vth_constant_current(data, segment="rev").value == pytest.approx(0.5, abs=2e-3)
    assert vth_constant_current(data).value == pytest.approx(0.3, abs=2e-3)
    with pytest.raises(InvalidInputError, match="not strictly monotonic"):
        vth_constant_current(run_of(np.concatenate([subthreshold_id(VG)] * 2), np.concatenate([VG, VG[::-1]])))
