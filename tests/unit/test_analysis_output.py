"""``output_metrics`` on an analytic square-law Id-Vd family (WP2.2): Ron, gds and Vd_sat per curve, the reported
curve, family values in ``fit``, per-curve refusal and the trust rules."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis.mosfet import output_metrics
from b1500_test_agent.analysis.registry import run_method
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import iv_table, output_family, run_of

pytestmark = pytest.mark.smu

VD = np.linspace(0.0, 3.0, 301)
LEVELS = [1.0, 1.5, 2.0]
VTH, BETA, LAM = 0.4, 1e-3, 0.05


def family(table=None):
    return run_of(output_family(VD, LEVELS, vth=VTH, beta=BETA, lam=LAM) if table is None else table,
                  "mosfet.idvd", kind="smu_stepped")


def truth(vg: float) -> dict[str, float]:
    vov = vg - VTH
    return {"ron": 1 / (BETA * vov), "gds": LAM * BETA * vov**2 / 2, "vd_sat": 0.9 * vov}


def test_the_strongest_curve_is_reported_with_the_family_in_fit() -> None:
    ron, gds, vd_sat = output_metrics(family())
    expected = truth(2.0)
    assert [r.quantity for r in (ron, gds, vd_sat)] == ["ron", "gds", "vd_sat"]
    assert [r.unit for r in (ron, gds, vd_sat)] == ["Ohm", "S", "V"]
    assert ron.fit["step_v"] == 2.0 and ron.method_record.params["curve"] == 2.0
    assert ron.value == pytest.approx(expected["ron"], rel=1e-6)
    assert gds.value == pytest.approx(expected["gds"], rel=1e-6)
    assert vd_sat.value == pytest.approx(expected["vd_sat"], abs=0.01)  # one Vd step
    for level in LEVELS:
        assert ron.fit[f"gate_V={level:g}"] == pytest.approx(truth(level)["ron"], rel=1e-6)
        assert gds.fit[f"gate_V={level:g}"] == pytest.approx(truth(level)["gds"], rel=1e-6)
        assert vd_sat.fit[f"gate_V={level:g}"] == pytest.approx(truth(level)["vd_sat"], abs=0.01)


def test_a_chosen_curve_and_a_single_curve() -> None:
    ron, _, _ = output_metrics(family(), curve=1.0)
    assert ron.fit["step_v"] == 1.0 and ron.value == pytest.approx(truth(1.0)["ron"], rel=1e-6)
    with pytest.raises(InvalidInputError, match="no curve"):
        output_metrics(family(), curve=1.2)
    single = output_family(VD, [1.5]).drop(columns=["gate_V"])
    ron, _gds, _ = output_metrics(run_of(single, "mosfet.idvd", kind="smu_stepped"))
    assert ron.value == pytest.approx(truth(1.5)["ron"], rel=1e-6) and "step_v" not in ron.fit


def test_a_curve_that_does_not_saturate_fails_for_vd_sat_only() -> None:
    short_sweep = np.linspace(0.0, 0.4, 41)
    ron, gds, vd_sat = output_metrics(run_of(output_family(short_sweep, [2.0]), "mosfet.idvd", kind="smu_stepped"))
    assert ron.outcome == "ok" and gds.outcome == "ok"
    assert vd_sat.outcome == "failed" and "not saturated" in vd_sat.error


def test_untrusted_data_refuse_their_curve_only() -> None:
    table = output_family(VD, LEVELS, vth=VTH, beta=BETA, lam=LAM)
    status = ["N"] * len(table)
    status[len(VD) + 10] = "X"  # inside the 1.5 V curve
    table["drain_I_status"] = status
    data = family(iv_table({"drain_V": table["drain_V"], "gate_V": table["gate_V"]}, {"drain_I": table["drain_I"]},
                           status={"drain_I": status}))
    ron, _gds, _vd_sat = output_metrics(data)
    assert ron.outcome == "ok" and ron.fit["step_v"] == 2.0 and "gate_V=1.5" not in ron.fit
    assert any("gate_V = 1.5 V: Refused" in w for w in ron.warnings)
    picked = output_metrics(data, curve=1.5)
    assert all(r.outcome == "refused" and r.fit["step_v"] == 1.5 for r in picked)
    forced = output_metrics(data, curve=1.5, force=True)
    assert all(r.outcome == "ok" and r.forced_on_untrusted for r in forced)


def test_compliance_points_are_excluded_from_the_derivatives() -> None:
    table = output_family(VD, [2.0], vth=VTH, beta=BETA, lam=LAM)
    status = ["N"] * len(table)
    status[150] = "C"
    data = family(iv_table({"drain_V": table["drain_V"], "gate_V": table["gate_V"]}, {"drain_I": table["drain_I"]},
                           status={"drain_I": status}))
    ron, gds, _ = output_metrics(data)
    assert ron.points_excluded["C"] == 1 and gds.value == pytest.approx(truth(2.0)["gds"], rel=1e-6)


def test_registry_runs_output_metrics_on_stepped_runs() -> None:
    results = run_method("output_metrics", family(), {"sat_window": 0.3})
    assert len(results) == 3 and results[1].method_record.params["sat_window"] == 0.3
