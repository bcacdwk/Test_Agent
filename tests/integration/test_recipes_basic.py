"""Recipe validation on the simulator (WP2.2, blueprint 9.3 AC): ``basic.contact_resistor`` and ``basic.diode_iv``
run through the executor on their scenarios and recover the model truth; these tests are what sets their
``status: sim_validated``. Also the S7 gate-keeper reading: the contact check reads ``open`` on ``open_drain_noisy``.

Tolerances: resistor R ±1 % (simulator noise 0.1 % relative); diode n ±2 %, Is ±15 %, Rs ±5 % (the WP2.1 model-truth
bounds), reverse leakage at -5 V ±10 % of the model current."""

from __future__ import annotations

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.basic import DiodeDevice
from tests.integration.helpers import World, plan, run

CONTACT = {"recipe_id": "basic.contact_resistor", "pin_map": "resistor-2t", "dut_profile": "resistor-generic"}
DIODE = {"recipe_id": "basic.diode_iv", "pin_map": "diode-2t", "dut_profile": "diode-generic"}


def run_on(world: World, scenario: str, request: dict[str, str], **params: object) -> RunSummary:
    world.use_scenario(scenario)
    executor = world.executor()
    record = plan(executor, **request, params=params)
    assert record.tier == "ok", record.rules.findings  # defaults are inside every limit on the simulator
    return run(executor, record.plan_id)


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def test_contact_check_recovers_the_100k_resistor(world: World) -> None:
    result = run_on(world, "resistor_100k", CONTACT)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 21}
    found = by_quantity(result.analyses)
    resistance = found["resistance"]
    truth = load_config(world.paths).sim_scenario.models["dut"].params["r_ohm"]  # type: ignore[union-attr]
    assert resistance.value == pytest.approx(truth, rel=0.01) and resistance.unit == "Ohm"
    assert resistance.classification == "in_range" and resistance.bound == "exact"
    assert found["linearity_r2"].value > 0.999 and abs(found["offset_current"].value) < 1e-9
    data = load_run(result.run_id, data_root=world.data)
    assert data.measured_columns == ["a_I"] and data.source_columns == ["a_V"]
    assert data.table["a_V"].min() == pytest.approx(-0.1) and data.table["a_V"].max() == pytest.approx(0.1)


def test_contact_check_reads_open_on_an_unlanded_probe(world: World) -> None:
    """S7: the drain probe of ``open_drain_noisy`` (SMU3, the ``a`` terminal of resistor-2t) is not landed."""
    result = run_on(world, "open_drain_noisy", CONTACT)
    assert result.ok and result.outcome == "completed", result.message
    resistance = by_quantity(result.analyses)["resistance"]
    assert resistance.classification == "open" and resistance.bound == "lower" and resistance.value > 1e9
    assert "noise floor" in resistance.warnings[0]


def test_contact_check_cannot_see_a_gate_drain_short_behind_a_floating_gate(world: World) -> None:
    """On ``gd_short`` the contact check drives only the drain; the shorted gate floats, so no current flows and the
    check reads open. The short is the gate-leakage recipe's finding (test_recipes_mosfet.py)."""
    resistance = by_quantity(run_on(world, "gd_short", CONTACT).analyses)["resistance"]
    assert resistance.classification == "open"


def test_diode_iv_recovers_is_n_rs_and_leakage(world: World) -> None:
    result = run_on(world, "diode_basic", DIODE)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 291} and result.cleanup_verified == "sim_state"
    found = by_quantity(result.analyses)
    device = Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]
    assert isinstance(device, DiodeDevice)
    truth = device.params
    assert found["n"].value == pytest.approx(truth.n, rel=0.02)
    assert found["is"].value == pytest.approx(truth.is_a, rel=0.15)
    assert found["rs"].value == pytest.approx(truth.rs_ohm, rel=0.05)
    assert found["n"].window is not None and found["n"].window.low > 0.0  # forward branch only
    leakage = found["leakage"]
    assert leakage.fit["v"] == -5.0 and leakage.bound == "exact" and leakage.classification == "pass"
    assert leakage.value == pytest.approx(abs(device.current(-5.0)), rel=0.10)
    data = load_run(result.run_id, data_root=world.data)
    assert data.table["anode_V"].iloc[0] == pytest.approx(-5.0) and data.table["anode_V"].iloc[-1] == pytest.approx(0.8)


def test_diode_breakdown_is_stopped_by_the_compliance(world: World) -> None:
    """Outside the default envelope (14 V: above the soft limit and the DUT profile, so the plan needs confirmation):
    a reverse sweep into the 12 V soft breakdown with a 1 uA compliance aborts at the compliance; the leakage check
    fails with a lower bound and diode_fit refuses (no forward data)."""
    world.use_scenario("diode_basic")
    executor = world.executor()
    record = plan(executor, **DIODE, params={"v_rev": -14.0, "icomp": 1e-6})
    assert record.tier == "needs_confirmation" and set(record.rules.confirm_reasons) == {"soft_limit", "dut_envelope"}
    result = run(executor, record.plan_id, record.summary)
    assert result.outcome == "completed_with_flags" and result.status_counts["C"] == 1
    found = by_quantity(result.analyses)
    assert found["n"].outcome == "refused"
    leakage = found["leakage"]
    assert leakage.bound == "lower" and leakage.classification == "fail"
    assert leakage.value == pytest.approx(1e-6, rel=0.01)  # the compliance current (with measurement noise)
    assert leakage.fit["v_compliance"] < -12.0
