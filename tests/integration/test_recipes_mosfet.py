"""Recipe validation on the simulator (WP2.2, blueprint 9.3 AC): ``mosfet.idvd`` and ``mosfet.gate_leakage`` run
through the executor on ``nmos_basic`` (pin map ``mosfet-4t``: gate SMU4 and drain SMU3, both HRSMU) and recover the
model truth; these tests set their ``status: sim_validated``. Also the damaged scenarios of blueprint 8.2: no Vth
method reports a valid value on ``open_drain_noisy`` (S7) or ``gd_short``, and the gate-leakage check flags the
gate-drain short through the compliance.

Tolerances. Id-Vd: per curve, Ron/gds/Vd_sat within 1 %/15 %/one Vd step of the same extractor on the noiseless
model curve (gds is a slope of a nearly flat line under 0.1 % current noise), and at Vg >= 1 V Ron within 2 %,
gds within 15 % and Vd_sat within 0.03 V of the analytic model (dId/dVd at Vd -> 0, at the window centre, and where
dId/dVd falls to 10 %). Gate leakage: |Ig(v_op)| within 10 % of gate_leak_s x v_op (the model with D/S at 0 V)."""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run, run_method, with_trust
from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv
from tests.integration.helpers import IDVG, World, plan, run

IDVD = {"recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
LEAK = {"recipe_id": "mosfet.gate_leakage", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
VTH_METHODS = ("vth_linear_extrapolation", "vth_constant_current", "vth_max_gm")


def run_on(world: World, scenario: str, request: dict[str, str], **params: object) -> RunSummary:
    world.use_scenario(scenario)
    executor = world.executor()
    record = plan(executor, **request, params=params)
    assert record.tier == "ok", record.rules.findings
    return run(executor, record.plan_id)


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def model(world: World) -> MosfetEkv:
    device = Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]
    assert isinstance(device, MosfetEkv)
    return device


# -- mosfet.idvd -----------------------------------------------------------------------------------------------------


def test_idvd_output_metrics_match_the_model(world: World) -> None:
    result = run_on(world, "nmos_basic", IDVD)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 1010}  # 5 curves x 101 points x (drain, gate)
    data = load_run(result.run_id, data_root=world.data)
    levels = data.table["gate_V"].unique().tolist()
    assert levels == [0.5, 0.75, 1.0, 1.25, 1.5]
    found = by_quantity(result.analyses)
    assert set(found) == {"ron", "gds", "vd_sat"} and found["ron"].fit["step_v"] == 1.5  # the strongest drive

    device = model(world)
    vd = data.table["drain_V"].unique()
    noiseless = pd.DataFrame({
        "step": np.arange(vd.size * len(levels)),
        "drain_V": np.tile(vd, len(levels)),
        "gate_V": np.repeat(levels, vd.size),
        "drain_I": [device.channel_current(vg, v) for vg in levels for v in vd],
        "drain_I_status": "N",
    })
    reference = by_quantity(run_method("output_metrics", RunData(data.manifest, with_trust(noiseless))))
    step = float(vd[1] - vd[0])
    h = 1e-4
    for vg in levels:
        key = f"gate_V={vg:g}"
        ron, gds, vd_sat = (found[q].fit[key] for q in ("ron", "gds", "vd_sat"))
        assert ron == pytest.approx(reference["ron"].fit[key], rel=0.01), vg
        assert gds == pytest.approx(reference["gds"].fit[key], rel=0.15), vg
        assert vd_sat == pytest.approx(reference["vd_sat"].fit[key], abs=step), vg
        if vg >= 1.0:  # strong inversion: the extractors agree with the analytic model quantities
            g0 = (device.channel_current(vg, h) - device.channel_current(vg, -h)) / (2 * h)
            centre = 3.0 - 0.1 * 3.0
            g_sat = (device.channel_current(vg, centre + h) - device.channel_current(vg, centre - h)) / (2 * h)
            dense = np.linspace(0.0, 3.0, 3001)
            gd = np.gradient([device.channel_current(vg, v) for v in dense], dense)
            onset = float(dense[int(np.argmax(gd <= 0.1 * gd[0]))])
            assert ron == pytest.approx(1 / g0, rel=0.02), vg
            assert gds == pytest.approx(g_sat, rel=0.15), vg
            assert vd_sat == pytest.approx(onset, abs=0.03), vg
    family = [found["ron"].fit[f"gate_V={v:g}"] for v in levels]
    assert all(b < a for a, b in itertools.pairwise(family))  # more gate drive, lower on-resistance


# -- mosfet.gate_leakage ---------------------------------------------------------------------------------------------


def test_gate_leakage_matches_the_model_and_passes(world: World) -> None:
    result = run_on(world, "nmos_basic", LEAK)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 62}
    [leakage] = result.analyses
    g = model(world).params.gate_leak_s
    assert leakage.quantity == "leakage" and leakage.fit["v"] == 1.5 and leakage.bound == "exact"
    assert leakage.value == pytest.approx(g * 1.5, rel=0.10)  # D and S at 0 V: Ig = g/2 Vg + g/2 Vg
    assert leakage.classification == "pass" and leakage.fit["limit_a"] == 1e-9
    data = load_run(result.run_id, data_root=world.data)
    assert data.measured_columns == ["gate_I", "drain_I"] and data.source_columns == ["gate_V"]
    plan_record = data.manifest.plan
    assert plan_record.binding.roles["gate"].module_type == "HRSMU"  # R-PIN-01 low_current
    assert plan_record.binding.roles["drain"].channel == 3 and plan_record.binding.roles["gate"].channel == 4


def test_gate_leakage_flags_the_gate_drain_short_by_compliance(world: World) -> None:
    result = run_on(world, "gd_short", LEAK)
    assert result.ok and result.outcome == "completed_with_flags" and result.quality_verdict == "untrusted"
    assert result.status_counts["C"] == 1
    [leakage] = result.analyses
    assert (leakage.outcome, leakage.bound, leakage.classification) == ("ok", "lower", "fail")
    assert leakage.value == pytest.approx(1e-7, rel=0.01) and leakage.fit["v_compliance"] == pytest.approx(0.1)
    assert leakage.points_excluded.get("aborted", 0) > 0


def test_gate_leakage_on_an_mpsmu_gate_is_blocked(world: World) -> None:
    """R-PIN-01 low_current: a pin map that puts the gate on an MPSMU cannot run the gate-leakage recipe."""
    world.write_config("pinmaps/mosfet-mp.yaml", {"certainty": "verified", "terminals": {
        "gate": 1, "drain": 3, "source": "GNDU", "bulk": "GNDU"}})
    executor = world.executor()
    record = plan(executor, **{**LEAK, "pin_map": "mosfet-mp"})
    assert record.tier == "blocked"
    assert any(f.rule_id == "R-PIN-01" and "low_current" in f.message for f in record.rules.findings)


# -- damaged devices: never a valid Vth ------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["open_drain_noisy", "gd_short"])
def test_no_vth_method_reports_a_value_on_a_damaged_device(world: World, scenario: str) -> None:
    result = run_on(world, scenario, IDVG)
    assert result.outcome == "completed_with_flags"
    assert [a.outcome for a in result.analyses] == ["refused"]
    data = load_run(result.run_id, data_root=world.data)
    criteria = world.executor().registry().get("mosfet.idvg").quality
    for method in (*VTH_METHODS, "subthreshold_swing", "gm_max"):
        [extracted] = run_method(method, data, criteria=criteria)
        assert extracted.outcome == "refused" and extracted.value is None, method
        expected = "noise-dominated" if scenario == "open_drain_noisy" else "untrusted"
        assert expected in extracted.error, method
