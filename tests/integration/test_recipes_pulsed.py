"""Recipe validation of the pulsed kind on the simulator (WP7.3; blueprint v2 10.3 row 7.3, per-recipe AC: tier, run,
default analysis vs the 4.2 fidelity target). These tests set ``status: sim_validated`` of ``mosfet.idvg_pulsed``,
``mosfet.idvd_pulsed``, ``basic.pulsed_spot`` and ``generic.smu_multi_pulsed``.

- Self-heating (scenario ``nmos_selfheat``): pulsed minus DC drain current (``pulsed_vs_dc`` against a DC run of the
  same bias) equals the model's within +-10 % (blueprint 4.2 ``mosfet`` +selfheat); the model truth replays the pulse
  train on the device model (``Mosfet.advance``: cold start, one pulse per step, the reading the mean of the current at
  the start and the end of the measurement window) against its steady self-heated DC current.
- A pulse narrower than the HR/MP/HPSMU 500 us is blocked by R-PULSE-01 (PG p486 (4-168)).
- Pulsed spot and multi-channel pulsed sweep on a 100 kOhm resistor: R within 1 % of the truth (MM 3, 27, 28).
"""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.helpers import World

pytestmark = pytest.mark.smu

IDVG_P = {"recipe_id": "mosfet.idvg_pulsed", "pin_map": "mosfet-4t", "dut_profile": "nmos-pulsed"}
IDVG_DC = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "dut_profile": "nmos-pulsed"}
IDVD_P = {"recipe_id": "mosfet.idvd_pulsed", "pin_map": "mosfet-4t", "dut_profile": "nmos-pulsed"}
IDVD_DC = {"recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-pulsed"}
SPOT = {"recipe_id": "basic.pulsed_spot", "pin_map": "resistor-2t", "dut_profile": "resistor-pulsed"}
MULTI = {"recipe_id": "generic.smu_multi_pulsed", "pin_map": "resistor-2t", "dut_profile": "resistor-pulsed"}
R_TRUE = 1.0e5


def run_ok(service: B1500Service, request: dict[str, Any], **params: Any) -> Any:
    validation = service.validate_plan(**{**request, "params": params})
    assert validation.ok and validation.tier == "ok" and validation.plan_id is not None, validation.message
    result = service.run_plan(validation.plan_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    return validation, result


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def truth_device(world: World) -> Any:
    return Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]


def pulsed_truth(device: Any, levels: list[tuple[float, float]], width: float, period: float,
                 meas: float) -> list[float]:
    """Model drain current of a pulse train: ``levels`` = (gate, drain) per pulse, gate base 0 V between pulses; the
    reading is the mean of the current at the start and the end of the measurement window (the pulse's last
    ``meas`` seconds)."""
    device.reset()
    readings = []
    for vg, vd in levels:
        on = {"gate": vg, "drain": vd, "source": 0.0, "bulk": 0.0}
        device.advance(width - meas, on)
        start = device.advance(0.0, on)["drain"]
        end = device.advance(meas, on)["drain"]
        readings.append(0.5 * (start + end))
        device.advance(period - width, {"gate": 0.0, "drain": vd, "source": 0.0, "bulk": 0.0})
    return readings


# -- mosfet.idvg_pulsed ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["mosfet.idvg_pulsed"])
def test_idvg_pulsed_minus_dc_matches_the_self_heating_model(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_selfheat")
    service = world.service()
    _, dc = run_ok(service, IDVG_DC, vd=3.0, vg_start=0.0, vg_stop=3.0, vg_points=61)
    validation, pulsed = run_ok(service, {**IDVG_P, "recipe_id": recipe_id}, vd=3.0)
    assert validation.resolved is not None and validation.resolved.mode == "sync"
    assert pulsed.status_counts == {"N": 61}
    defaults = by_quantity(pulsed.analyses)
    assert defaults["vth"].outcome == "ok" and defaults["gm_max"].outcome == "ok"
    analysis = service.analyze_run(pulsed.run_id or "", "pulsed_vs_dc", {"reference_run": dc.run_id})
    assert analysis.ok, analysis.message
    found = by_quantity(analysis.results)
    delta = found["pulsed_minus_dc"]
    assert delta.fit["v"] == pytest.approx(3.0)
    device = truth_device(world)
    v_on = {"gate": 3.0, "drain": 3.0, "source": 0.0, "bulk": 0.0}
    gates = [3.0 * i / 60 for i in range(61)]
    model_pulsed = pulsed_truth(device, [(vg, 3.0) for vg in gates], width=1e-3, period=0.02, meas=2e-4)[-1]
    model_dc = device.selfheat_truth(v_on)["id_dc"]
    model_delta = model_pulsed - model_dc
    assert model_delta > 0.1 * model_dc  # the scenario's self-heating is a large effect (16 %)
    assert delta.value == pytest.approx(model_delta, rel=0.10)  # blueprint 4.2: pulsed - DC = model +-10 %
    assert found["pulsed_over_dc"].value == pytest.approx(model_pulsed / model_dc, rel=0.02)
    assert found["max_rel_difference"].fit["v_at_max"] == pytest.approx(3.0)
    data = load_run(pulsed.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "gate_V", "drain_I", "drain_I_status", "drain_V", "trust"]
    service.close()


def test_pulsed_vs_dc_refuses_other_bias_conditions(world: World) -> None:
    world.use_scenario("nmos_selfheat")
    service = world.service()
    _, dc = run_ok(service, IDVG_DC, vd=0.05, vg_start=0.0, vg_stop=3.0, vg_points=61)
    _, pulsed = run_ok(service, IDVG_P, vd=3.0)
    analysis = service.analyze_run(pulsed.run_id or "", "pulsed_vs_dc", {"reference_run": dc.run_id})
    assert not analysis.ok and analysis.status == "error"
    assert all(r.outcome == "failed" and "drain_V 3 vs 0.05" in (r.error or "") for r in analysis.results)
    missing = service.analyze_run(pulsed.run_id or "", "pulsed_vs_dc", {})
    assert missing.status == "refused" and missing.error_code == "invalid_input"
    assert "reference_run" in missing.message
    service.close()


def test_a_pulse_below_500_us_is_blocked_by_r_pulse_01(world: World) -> None:
    """AC: width < 500 us -> blocked (HR/MP/HPSMU PT table, PG p486 (4-168))."""
    world.use_scenario("nmos_selfheat")
    service = world.service()
    validation = service.validate_plan(**IDVG_P, params={"width": 4e-4})
    assert validation.tier == "blocked" and validation.status == "blocked", validation.message
    blocking = [f for f in validation.findings if f.severity == "block"]
    assert {f.rule_id for f in blocking} == {"R-PULSE-01"}
    assert any("500" in f.message or "0.0005" in f.message for f in blocking)
    ok = service.validate_plan(**IDVG_P, params={"width": 5e-4})
    assert ok.tier == "ok", ok.message
    service.close()


# -- mosfet.idvd_pulsed ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["mosfet.idvd_pulsed"])
def test_idvd_pulsed_family_and_pulsed_minus_dc(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_selfheat")
    service = world.service()
    validation, pulsed = run_ok(service, {**IDVD_P, "recipe_id": recipe_id})
    assert validation.resolved is not None and validation.resolved.points == 5 * 31
    assert pulsed.status_counts == {"N": 155}
    metrics = by_quantity(pulsed.analyses)
    assert {"ron", "gds", "vd_sat"} <= set(metrics) and all(r.outcome == "ok" for r in pulsed.analyses)
    assert metrics["ron"].fit and "gate_V=3" in metrics["ron"].fit
    data = load_run(pulsed.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "drain_V", "gate_V", "drain_I", "drain_I_status", "trust"]
    assert sorted(data.table["gate_V"].unique()) == [1.0, 1.5, 2.0, 2.5, 3.0]
    device = truth_device(world)
    drains = [3.0 * i / 30 for i in range(31)]
    truth = pulsed_truth(device, [(3.0, vd) for vd in drains], width=1e-3, period=0.02, meas=2e-4)
    top = data.table[data.table["gate_V"] == 3.0]["drain_I"].to_numpy()
    assert top[-1] == pytest.approx(truth[-1], rel=0.02)
    _, dc = run_ok(service, IDVD_DC, vg_start=1.0, vg_stop=3.0, vg_points=5, icomp_drain=1e-3)
    analysis = service.analyze_run(pulsed.run_id or "", "pulsed_vs_dc", {"reference_run": dc.run_id})
    assert analysis.ok, analysis.message
    delta = by_quantity(analysis.results)["pulsed_minus_dc"]
    assert delta.fit["curve"] == 3.0 and delta.fit["v"] == pytest.approx(3.0)
    model_dc = device.selfheat_truth({"gate": 3.0, "drain": 3.0, "source": 0.0, "bulk": 0.0})["id_dc"]
    assert delta.value == pytest.approx(truth[-1] - model_dc, rel=0.10)
    service.close()


# -- basic.pulsed_spot and generic.smu_multi_pulsed ------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["basic.pulsed_spot"])
def test_pulsed_spot_resistance_on_100_kohm(recipe_id: str, world: World) -> None:
    world.use_scenario("resistor_100k")
    service = world.service()
    _, result = run_ok(service, {**SPOT, "recipe_id": recipe_id})
    data = load_run(result.run_id or "", data_root=world.data)
    preview = data.manifest.plan.flex_preview
    assert "MM 3,3" in preview and preview.count("XE") == 4 and preview.count("PV 3,0,0,0.1,0.0001") == 1
    assert result.status_counts == {"N": 4}
    (r,) = [a for a in result.analyses if a.quantity == "resistance"]
    assert r.value == pytest.approx(R_TRUE, rel=0.01) and r.classification == "in_range"
    assert list(data.table.columns) == ["step", "a_V", "a_I", "a_I_status", "trust"]
    assert list(data.table["a_V"]) == [-0.1, -0.05, 0.05, 0.1]
    service.close()


@pytest.mark.parametrize(("params", "mode", "points"),
                         [({}, "MM 28,3", 11), ({"points": 1, "start": 0.1}, "MM 27,3", 1)],
                         ids=["generic.smu_multi_pulsed-sweep_mm28", "generic.smu_multi_pulsed-spot_mm27"])
def test_multi_pulsed_on_100_kohm(world: World, params: dict[str, Any], mode: str, points: int) -> None:
    world.use_scenario("resistor_100k")
    service = world.service()
    _, result = run_ok(service, MULTI, **params)
    data = load_run(result.run_id or "", data_root=world.data)
    assert mode in data.manifest.plan.flex_preview
    assert result.status_counts == {"N": points}
    current = data.table["a_I"].to_numpy()
    volts = data.table["a_V"].to_numpy()
    assert current[-1] == pytest.approx(volts[-1] / R_TRUE, rel=0.01)
    if points > 1:
        analysis = service.analyze_run(result.run_id or "", "resistance", {})
        (r,) = [a for a in analysis.results if a.quantity == "resistance"]
        assert r.value == pytest.approx(R_TRUE, rel=0.01)
    service.close()
