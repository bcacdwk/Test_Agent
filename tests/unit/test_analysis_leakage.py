"""``leakage_at`` on analytic leakage curves (WP2.2): value at the bias, pass/fail against the limit, plan
parameters as defaults, the compliance lower bound, the noise-floor upper bound and the trust rules."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis.leakage import leakage_at
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from tests.unit.analysis_helpers import iv_table, run_of

pytestmark = pytest.mark.smu

VG = np.linspace(0.0, 3.0, 31)
G = 1e-12
INVALID = 199.999e99
PARAMS = {"v_op": Quantity(value=1.5, unit="V"), "leak_limit_a": Quantity(value=1e-9, unit="A")}


def gate_run(current: np.ndarray, status: list[str] | None = None, params: dict[str, Quantity] | None = None,
             vg: np.ndarray = VG):
    statuses = None
    if status:  # the drain sees the other channel's compliance (T) and the same abort (V)
        statuses = {"gate_I": status, "drain_I": ["T" if s == "C" else s for s in status]}
    table = iv_table({"gate_V": vg}, {"gate_I": current, "drain_I": -current / 2}, status=statuses)
    return run_of(table, "mosfet.gate_leakage", params=PARAMS if params is None else params)


def test_leakage_at_the_planned_bias_passes() -> None:
    result = leakage_at(gate_run(G * VG))
    assert (result.quantity, result.unit, result.bound, result.classification) == ("leakage", "A", "exact", "pass")
    assert result.value == pytest.approx(1.5e-12) and result.fit["v"] == 1.5 and result.fit["limit_a"] == 1e-9
    assert result.method_record.params["v_source"] == "plan.resolved_params.v_op"
    assert result.points_used == 1 and result.points_excluded == {"outside_window": 30}


def test_arguments_override_the_plan_and_interpolate() -> None:
    result = leakage_at(gate_run(G * VG), v=1.55, limit_a=1e-12)
    assert result.value == pytest.approx(1.55e-12) and result.classification == "fail"
    no_limit = leakage_at(gate_run(G * VG, params={"v_op": Quantity(value=1.5, unit="V")}))
    assert no_limit.classification is None and no_limit.outcome == "ok"
    renamed = leakage_at(gate_run(G * VG, params={"vr": Quantity(value=-2.0, unit="V")}, vg=-VG), v_param="vr")
    assert renamed.value == pytest.approx(2e-12)
    with pytest.raises(InvalidInputError, match="needs the bias"):
        leakage_at(gate_run(G * VG, params={}))
    with pytest.raises(InvalidInputError, match="not a scalar in V"):
        leakage_at(gate_run(G * VG, params={"v_op": Quantity(value=1.0, unit="A")}))


def test_outside_the_sweep_fails() -> None:
    result = leakage_at(gate_run(G * VG), v=4.0)
    assert result.outcome == "failed" and "outside the trusted sweep range" in result.error


def test_compliance_before_the_bias_is_a_fail_with_a_lower_bound() -> None:
    current = np.full(VG.size, INVALID)
    status = ["V"] * VG.size
    current[0], status[0] = 0.0, "N"
    current[1], status[1] = 1e-7, "C"  # the short reaches the 100 nA compliance at 0.1 V
    result = leakage_at(gate_run(current, status))
    assert (result.outcome, result.bound, result.classification) == ("ok", "lower", "fail")
    assert result.value == pytest.approx(1e-7) and result.fit["v_compliance"] == pytest.approx(0.1)
    assert result.points_excluded["aborted"] == 29 and "compliance" in result.warnings[0]
    undecidable = leakage_at(gate_run(current, status), limit_a=1e-6)
    assert undecidable.outcome == "failed" and "cannot be decided" in undecidable.error


def test_compliance_beyond_the_bias_keeps_the_value_exact() -> None:
    current = G * VG
    status = ["N"] * VG.size
    current[25], status[25] = 1e-7, "C"
    for i in range(26, VG.size):
        current[i], status[i] = INVALID, "V"
    result = leakage_at(gate_run(current, status))
    assert result.outcome == "ok" and result.bound == "exact" and result.value == pytest.approx(1.5e-12)
    assert any("beyond the leakage bias" in w for w in result.warnings)


def test_noise_floor_is_an_upper_bound_not_a_refusal() -> None:
    rng = np.random.default_rng(6)
    result = leakage_at(gate_run(3e-14 * rng.standard_normal(VG.size)))
    assert result.outcome == "ok" and result.bound == "upper" and result.classification == "pass"
    assert 3e-14 < result.value < 3e-13 and "detection limit" in result.warnings[0]


def test_other_untrusted_letters_refuse_unless_forced() -> None:
    status = ["N"] * VG.size
    status[3] = "X"
    refused = leakage_at(gate_run(G * VG, status))
    assert refused.outcome == "refused" and refused.value is None
    forced = leakage_at(gate_run(G * VG, status), force=True)
    assert forced.outcome == "ok" and forced.forced_on_untrusted
