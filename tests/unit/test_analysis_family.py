"""``dibl``, ``body_effect`` (``analysis/mosfet_family.py``) and ``forward_voltage`` (``analysis/diode.py``) on analytic
curves with known truth (WP7.2; knowledge file 06 "DIBL and body effect", "Forward voltage"): the constant-current
Vth of an exponential subthreshold curve is exact (log-linear interpolation), so DIBL and dVth/dVsb come back to
rounding; refusals, failures, p-type signs, step and column detection."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import body_effect, dibl, forward_voltage, run_method
from b1500_test_agent.analysis.dataset import with_trust
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from tests.unit.analysis_helpers import run_of, subthreshold_id

pytestmark = pytest.mark.smu

VG = np.round(np.linspace(-0.2, 1.2, 141), 9)
I_CRIT = 1e-7


def family(step: str, levels: list[float], vth_of, *, sign: float = 1.0, drain_status: dict[int, str] | None = None,
           extra: dict[str, float] | None = None) -> pd.DataFrame:
    """A transfer family: per step level a subthreshold curve whose 100 nA crossing (``v0`` with ``i0`` = I_crit)
    sits at ``vth_of(level)``; ``sign`` -1 mirrors it into a p-type family (negative Vg and currents)."""
    rows = []
    for level in levels:
        ids = subthreshold_id(VG, v0=vth_of(level), i0=I_CRIT, ss_mv=80.0, i_on=1e-3)
        for vg, i in zip(VG, ids, strict=True):
            rows.append({"gate_V": sign * vg, step: level, "drain_I": sign * i, "drain_I_status": "N", **(extra or {})})
    table = pd.DataFrame(rows)
    for index, letter in (drain_status or {}).items():
        table.loc[index, "drain_I_status"] = letter
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def vth_cc(vth_target: float) -> float:
    """Where the harmonic sum ``subthreshold_id`` reaches I_crit: a hair above ``v0`` (the i_on term)."""
    i = I_CRIT
    return vth_target + 0.08 * np.log10(1.0 / (1.0 - i / 1e-3))


# -- dibl ------------------------------------------------------------------------------------------------------------


def test_dibl_of_a_known_shift() -> None:
    table = family("drain_V", [0.1, 0.55, 1.0], lambda vd: 0.40 - 0.05 * vd)  # 50 mV/V
    results = {r.quantity: r for r in dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"))}
    assert results["dibl"].value == pytest.approx(50.0, abs=0.2) and results["dibl"].unit == "mV/V"
    assert results["dibl"].fit["slope_mv_per_v"] == pytest.approx(50.0, abs=0.2)
    assert results["vth_lin"].value == pytest.approx(vth_cc(0.395), abs=1e-3)
    assert results["vth_sat"].value == pytest.approx(vth_cc(0.35), abs=1e-3)
    assert results["dibl"].fit["drain_V=0.55"] == pytest.approx(vth_cc(0.3725), abs=1e-3)
    assert results["dibl"].method_record.params["step"] == "drain_V"
    assert results["dibl"].window is not None and results["dibl"].window.low == 0.1


def test_dibl_of_a_p_type_family_is_positive() -> None:
    table = family("drain_V", [-0.1, -1.0], lambda vd: 0.40 - 0.03 * abs(vd), sign=-1.0)
    [value, *_] = dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"))
    assert value.value == pytest.approx(30.0, abs=0.3)


def test_dibl_through_the_registry_and_its_refusals() -> None:
    table = family("drain_V", [0.1, 1.0], lambda vd: 0.4, drain_status={5: "X"})  # an untrusted row, first curve
    data = run_of(table, "mosfet.idvg_family", kind="smu_stepped")
    results = run_method("dibl", data)
    assert [r.outcome for r in results] == ["refused"] * 3 and "end curve drain_V = 0.1" in results[0].error
    assert run_method("dibl", data, {"force": True})[0].forced_on_untrusted
    with pytest.raises(InvalidInputError, match="does not apply"):
        run_method("dibl", run_of(table, "mosfet.idvg"))  # a staircase run is no family


def test_dibl_needs_two_drain_biases() -> None:
    table = family("drain_V", [0.1], lambda vd: 0.4)
    [value, *_] = dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"))
    assert value.outcome == "failed" and "two different" in value.error


def test_a_curve_without_a_crossing_fails_dibl_at_the_end_but_warns_in_the_middle() -> None:
    table = family("drain_V", [0.1, 0.5, 1.0], lambda vd: 0.4 if vd != 0.5 else 5.0)  # the middle never crosses
    [value, *_] = dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"))
    assert value.outcome == "ok" and any("drain_V = 0.5" in w for w in value.warnings)
    table = family("drain_V", [0.1, 1.0], lambda vd: 0.4 if vd < 1 else 5.0)
    [value, *_] = dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"))
    assert value.outcome == "failed" and "drain_V = 1" in value.error


def test_dibl_step_column_must_be_unambiguous() -> None:
    table = family("drain_V", [0.1, 1.0], lambda vd: 0.4)
    table["bulk_V"] = np.where(table["drain_V"] > 0.5, -1.0, 0.0)
    with pytest.raises(InvalidInputError, match="pass step="):
        dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"))
    [value, *_] = dibl(run_of(table, "mosfet.idvg_family", kind="smu_stepped"), step="drain_V")
    assert value.outcome == "ok"


# -- body_effect -----------------------------------------------------------------------------------------------------


def test_body_effect_of_a_linear_coefficient() -> None:
    table = family("bulk_V", [0.0, -0.5, -1.0], lambda vb: 0.40 + 0.25 * (0.0 - vb))  # 0.25 V/V
    results = {r.quantity: r for r in body_effect(run_of(table, "mosfet.body_effect", kind="smu_stepped"))}
    assert results["body_effect"].value == pytest.approx(0.25, abs=1e-3) and results["body_effect"].unit == "1"
    assert results["vth_vsb0"].value == pytest.approx(vth_cc(0.40), abs=1e-3)
    assert results["body_effect"].fit["vsb_max"] == 1.0 and results["body_effect"].fit["r2"] > 0.9999


def test_body_effect_reads_a_source_column_and_warns_on_a_square_root_law() -> None:
    gamma, two_phi = 0.5, 0.7
    table = family("bulk_V", [0.0, -1.0, -2.0, -3.0],
                   lambda vb: 0.4 + gamma * (np.sqrt(two_phi + 0.2 - vb) - np.sqrt(two_phi)), extra={"source_V": 0.2})
    results = {r.quantity: r for r in body_effect(run_of(table, "mosfet.body_effect", kind="smu_stepped"))}
    assert results["body_effect"].method_record.params["source_v"] == 0.2  # Vsb = 0.2 - V_bulk
    assert results["body_effect"].fit["vsb_min"] == pytest.approx(0.2)
    assert any("square-root law" in w for w in results["body_effect"].warnings)
    slope = results["body_effect"].value
    assert gamma / (2 * np.sqrt(two_phi + 3.2)) < slope < gamma / (2 * np.sqrt(two_phi + 0.2))  # the mean slope


def test_body_effect_needs_two_valid_curves() -> None:
    table = family("bulk_V", [0.0, -1.0], lambda vb: 0.4 if vb == 0 else 5.0)
    [value, *_] = body_effect(run_of(table, "mosfet.body_effect", kind="smu_stepped"))
    assert value.outcome == "failed" and "two body biases" in value.error


# -- forward_voltage -------------------------------------------------------------------------------------------------

UT = 0.025852
IS, N, RS = 1e-14, 1.05, 10.0


def diode_v(i: np.ndarray) -> np.ndarray:
    return N * UT * np.log(i / IS + 1.0) + RS * i


def test_forward_voltage_of_a_current_sweep() -> None:
    currents = np.logspace(-9, -2, 71)
    table = with_trust(pd.DataFrame({"step": np.arange(71), "anode_I": currents, "anode_V": diode_v(currents),
                                     "anode_V_status": "N"}))
    params = {"i_vf": Quantity(value=1e-3, unit="A")}
    data = run_of(table, "basic.iv_force_i", params=params)
    vf = forward_voltage(data, i_param="i_vf")
    assert vf.value == pytest.approx(float(diode_v(np.array([1e-3]))[0]), abs=1e-4)
    assert vf.method_record.params["x"] == "anode_V" and vf.method_record.params["y"] == "anode_I"
    low = forward_voltage(data, i_a=3.3e-7)  # between grid points: log interpolation
    assert low.value == pytest.approx(float(diode_v(np.array([3.3e-7]))[0]), abs=2e-4)
    fit = {r.quantity: r for r in run_method("diode_fit", data)}  # the forced current is y, the measured V is x
    assert fit["n"].value == pytest.approx(N, rel=0.01) and fit["rs"].value == pytest.approx(RS, rel=0.05)


def test_forward_voltage_of_a_voltage_sweep_and_its_failures() -> None:
    vs = np.linspace(-1.0, 0.9, 191)
    table = with_trust(pd.DataFrame({"step": np.arange(191), "anode_V": vs,
                                     "anode_I": IS * (np.exp(vs / (N * UT)) - 1.0), "anode_I_status": "N"}))
    data = run_of(table, "basic.diode_iv")
    vf = forward_voltage(data)  # default 1 mA
    assert vf.value == pytest.approx(N * UT * np.log(1e-3 / IS + 1), abs=1e-3)
    high = forward_voltage(data, i_a=50.0)  # above the 2.5 A the curve reaches at 0.9 V
    assert high.outcome == "failed" and "does not bracket" in high.error
    with pytest.raises(InvalidInputError, match="not a current"):
        forward_voltage(data, i_param="nothing")


def test_forward_voltage_reads_through_a_compliance_stop() -> None:
    """A current sweep that reached its voltage compliance: the dummy rows after it are ``aborted``, not untrusted."""
    currents = np.logspace(-6, -2, 9)
    voltages = np.minimum(currents * 1e3, 2.0)
    status = ["N"] * 7 + ["C", "V"]
    voltages[-1] = 199.999e99
    table = with_trust(pd.DataFrame({"step": np.arange(9), "anode_I": currents, "anode_V": voltages,
                                     "anode_V_status": status}))
    vf = forward_voltage(run_of(table, "basic.iv_force_i"), i_a=1e-4)
    assert vf.outcome == "ok" and vf.value == pytest.approx(0.1, rel=1e-3)
    assert vf.points_excluded.get("aborted") == 1
