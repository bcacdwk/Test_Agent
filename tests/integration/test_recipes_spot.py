"""Recipe validation on the simulator for the WP7.1 spot recipes (blueprint v2 10.3 row 7.1 AC, per-recipe AC): the
kind ``smu_spot`` recipes ``generic.smu_spot``, ``resistor.kelvin_4w`` and ``system.zero_check`` and the ASU option
``asu_1pa`` of ``mosfet.gate_leakage`` run through the executor on their scenarios (tier, run, default analysis vs
the model truth); these tests set their ``status: sim_validated``.

Tolerances: spot two-wire R ±1 % of the 100 kOhm truth (simulator noise 0.1 % relative, as the contact check);
four-wire R ±0.5 % of the 1 Ohm truth (row 7.1 AC); zero-check floor per SMU and range = the scenario floor ±20 %
(row 7.1 AC; the simulator floor is ``noise.floor_a`` of the module type times the ADC noise multiplier, the same on
every range).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.transport.sim.units.core import NOISE_MULTIPLIERS
from tests.integration.helpers import REPO_ROOT, World, plan, run

pytestmark = pytest.mark.smu

SPOT = {"recipe_id": "generic.smu_spot", "pin_map": "resistor-2t", "dut_profile": "resistor-generic"}
KELVIN = {"recipe_id": "resistor.kelvin_4w", "pin_map": "resistor-4w", "dut_profile": "resistor-1r"}
ZERO = {"recipe_id": "system.zero_check", "pin_map": "open-smus", "dut_profile": "open-circuit"}
LEAK = {"recipe_id": "mosfet.gate_leakage", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
REQUESTS = {r["recipe_id"]: r for r in (SPOT, KELVIN, ZERO, LEAK)}
HRSMU_RANGES = ["10pA", "1nA", "100nA", "10uA", "1mA"]
MPSMU_RANGES = ["1nA", "1nA", "100nA", "10uA", "1mA"]  # no 10 pA range without an ASU: the next one up


def recipe(recipe_id: str) -> pytest.MarkDecorator:
    """Parametrize a test with its recipe id, so ``pytest tests/integration -k <recipe id>`` selects it (per-recipe AC
    of blueprint v2 10)."""
    return pytest.mark.parametrize("recipe_id", [recipe_id])


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def scenario_copy(world: World, base: str, name: str, edit: Any) -> None:
    """A test-local copy of committed scenario ``base`` named ``name``, changed by ``edit(data)``, selected."""
    data = yaml.safe_load((REPO_ROOT / "config" / "sim" / "scenarios" / f"{base}.yaml").read_text(encoding="utf-8"))
    edit(data)
    world.write_config(f"sim/scenarios/{name}.yaml", data)
    world.use_scenario(name)


def run_on(world: World, request: dict[str, str], *, scenario: str | None = None, **params: object) -> RunSummary:
    if scenario is not None:
        world.use_scenario(scenario)
    executor = world.executor()
    record = plan(executor, **request, params=params)
    assert record.tier == "ok", record.rules.findings
    return run(executor, record.plan_id)


# -- generic.smu_spot ----------------------------------------------------------------------------------------------


@recipe("generic.smu_spot")
def test_generic_spot_recovers_the_100k_resistor(recipe_id: str, world: World) -> None:
    result = run_on(world, REQUESTS[recipe_id], scenario="resistor_100k")
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 5} and result.cleanup_verified == "sim_state"
    found = by_quantity(result.analyses)
    truth = load_config(world.paths).sim_scenario.models["dut"].params["r_ohm"]  # type: ignore[union-attr]
    assert found["resistance"].value == pytest.approx(truth, rel=0.01)
    assert found["resistance"].classification == "in_range"
    data = load_run(result.run_id, data_root=world.data)
    assert data.measured_columns == ["a_I"] and data.source_columns == ["a_V"]
    assert data.table["a_V"].tolist() == [-0.1, -0.05, 0.0, 0.05, 0.1]
    assert data.manifest.kind_result == {"points_planned": 5, "points_done": 5, "stopped_early": False,
                                         "stop_reason": ""}


@recipe("generic.smu_spot")
def test_generic_spot_samples_repeat_each_level(recipe_id: str, world: World) -> None:
    result = run_on(world, REQUESTS[recipe_id], scenario="resistor_100k", samples=3, a_levels=[0.05, 0.1])
    assert result.ok and result.status_counts == {"N": 6}, result.message
    table = load_run(result.run_id, data_root=world.data).table
    assert table["a_V"].tolist() == [0.05, 0.05, 0.05, 0.1, 0.1, 0.1] and table["step"].tolist() == list(range(6))


# -- resistor.kelvin_4w --------------------------------------------------------------------------------------------


@recipe("resistor.kelvin_4w")
def test_kelvin_recovers_the_1_ohm_truth_within_half_a_percent(recipe_id: str, world: World) -> None:
    result = run_on(world, REQUESTS[recipe_id], scenario="resistor_1r_kelvin")
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 16}
    found = by_quantity(result.analyses)
    params = load_config(world.paths).sim_scenario.models["dut"].params  # type: ignore[union-attr]
    assert params["lead_ohm"] > 0 and params["kelvin"] == "both"  # the leads exist but are sensed around
    resistance = found["resistance"]
    assert resistance.value == pytest.approx(params["r_ohm"], rel=0.005)
    assert resistance.classification == "in_range" and resistance.method == "kelvin_resistance"
    assert abs(found["offset_voltage"].value) < 1e-5 and found["linearity_r2"].value > 0.9999
    data = load_run(result.run_id, data_root=world.data)
    assert data.measured_columns == ["a_V"] and data.source_columns == ["a_I"]
    assert sorted(set(data.table["a_I"])) == [-0.01, -0.005, 0.005, 0.01]


@recipe("resistor.kelvin_4w")
def test_kelvin_without_sense_lines_reads_the_leads_too(recipe_id: str, world: World) -> None:
    """The same landing with Force only: the reading is r + 2 x lead (the two-wire error Kelvin removes)."""
    scenario_copy(world, "resistor_1r_kelvin", "resistor_1r_two_wire",
                  lambda d: d["models"]["dut"]["params"].update(kelvin="none"))
    result = run_on(world, REQUESTS[recipe_id])
    assert result.ok, result.message
    params = load_config(world.paths).sim_scenario.models["dut"].params  # type: ignore[union-attr]
    expected = params["r_ohm"] + 2 * params["lead_ohm"]
    assert by_quantity(result.analyses)["resistance"].value == pytest.approx(expected, rel=0.005)


@recipe("resistor.kelvin_4w")
def test_kelvin_on_an_open_landing_stops_at_the_voltage_compliance(recipe_id: str, world: World) -> None:
    """Pad b not landed: the forced current cannot flow, the SMU hits its 1 V compliance on the first point, the host
    loop stops there and the analysis classifies the landing open with a lower bound."""
    scenario_copy(world, "resistor_1r_kelvin", "resistor_1r_open", lambda d: d["wiring"]["dut"].pop("b"))
    result = run_on(world, REQUESTS[recipe_id])
    assert result.ok and result.outcome == "completed_with_flags", result.message
    assert result.status_counts == {"C": 1}
    data = load_run(result.run_id, data_root=world.data)
    assert data.manifest.kind_result["stopped_early"] is True
    assert data.table["a_V"].tolist() == [pytest.approx(-1.0, rel=1e-3)]  # -Vcomp (the current's polarity)
    resistance = by_quantity(result.analyses)["resistance"]
    assert resistance.classification == "open" and resistance.bound == "lower"
    assert resistance.value == pytest.approx(100.0, rel=1e-3)  # 1 V / 10 mA


@recipe("resistor.kelvin_4w")
def test_kelvin_currents_above_the_dut_envelope_need_confirmation(recipe_id: str, world: World) -> None:
    world.use_scenario("resistor_1r_kelvin")
    record = plan(world.executor(), **REQUESTS[recipe_id], params={"currents": [-0.03, 0.03]})
    assert record.tier == "needs_confirmation"
    assert sorted(record.rules.confirm_reasons) == ["dut_envelope", "soft_limit"]
    assert "a=SMU3(HRSMU) bias I<=30 mA Vcomp 1 V" in record.summary


# -- system.zero_check ---------------------------------------------------------------------------------------------


def _multiplier(plc: float) -> float:
    return next(mult for limit, mult in NOISE_MULTIPLIERS if plc < limit)


@pytest.mark.parametrize(("integration", "plc"), [("medium", 1.0), ("short", 1 / 128)])
@recipe("system.zero_check")
def test_zero_check_floor_per_range_is_the_scenario_floor(recipe_id: str, world: World, integration: str,
                                                         plc: float) -> None:
    result = run_on(world, REQUESTS[recipe_id], scenario="lab_station", integration=integration)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 2000}
    scenario = load_config(world.paths).sim_scenario
    assert scenario is not None
    data = load_run(result.run_id, data_root=world.data)
    assert data.measured_columns == ["smu3_I", "smu4_I", "smu5_I", "smu6_I"]
    found = by_quantity(result.analyses)
    for slot, module, ranges in ((3, "HRSMU", HRSMU_RANGES), (4, "HRSMU", HRSMU_RANGES), (5, "MPSMU", MPSMU_RANGES),
                                 (6, "MPSMU", MPSMU_RANGES)):
        role = f"smu{slot}"
        assert data.table[f"{role}_range"].tolist() == [r for r in ranges for _ in range(100)]
        truth = scenario.noise.floor_a[module] * _multiplier(plc)  # type: ignore[index]
        floor = found[f"{role}_floor"]
        assert floor.value == pytest.approx(truth, rel=0.2), role
        for label in dict.fromkeys(ranges):
            assert floor.fit[label] == pytest.approx(truth, rel=0.2), (role, label)
        assert abs(floor.fit["offset"]) < 4 * truth / 10  # the mean of pure noise: 100 or 200 readings
        assert floor.fit["max_abs_offset"] < 4 * truth / 10 and floor.points_used == 500


@recipe("system.zero_check")
def test_zero_check_plans_long_runs_asynchronously_and_confirms_very_long_ones(recipe_id: str, world: World) -> None:
    world.use_scenario("lab_station")
    executor = world.executor()
    longer = plan(executor, **REQUESTS[recipe_id], params={"integration": "long", "samples": 50})
    assert longer.tier == "ok" and longer.mode == "async" and longer.estimate.max_segment_s is not None
    assert longer.estimate.max_segment_s <= 30  # checkpoints at most every ~10 s (R-RUN-02 segment bound)
    longest = plan(executor, **REQUESTS[recipe_id], params={"integration": "long", "samples": 1000})
    assert longest.tier == "needs_confirmation" and "long_run" in longest.rules.confirm_reasons


@recipe("system.zero_check")
def test_zero_check_uses_the_asu_range_only_with_a_present_asu(recipe_id: str, world: World) -> None:
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    for switch in station["switches"]:
        if switch["id"] == "ASU3":
            switch["present"] = True
    world.write_config("station.yaml", station)
    world.use_scenario("lab_station")
    record = plan(world.executor(), **REQUESTS[recipe_id], params={"ranges": [1e-12, 1e-9]})
    assert record.tier == "ok", record.rules.findings
    group_codes = [line for line in record.flex_preview if line.startswith("RI ")]
    assert group_codes[:4] == ["RI 3,-8", "RI 4,-9", "RI 5,-11", "RI 6,-11"]  # 1 pA only behind ASU3


# -- mosfet.gate_leakage asu_1pa (R-ASU-01 live) ---------------------------------------------------------------------


@recipe("mosfet.gate_leakage")
def test_asu_option_is_blocked_without_a_declared_present_asu(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_basic")
    record = plan(world.executor(), **REQUESTS[recipe_id], params={"asu_1pa": True})
    assert record.tier == "blocked"
    blocks = [f for f in record.rules.findings if f.rule_id == "R-ASU-01" and f.severity == "block"]
    assert len(blocks) == 1 and "ASU4" in blocks[0].message and "unknown presence" in blocks[0].message
    plain = plan(world.executor(), **REQUESTS[recipe_id])
    assert plain.tier == "ok" and not any(line.startswith("RI ") for line in plain.flex_preview)


def _asu_station(world: World) -> None:
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    for switch in station["switches"]:
        if switch["id"] == "ASU4":
            switch["present"] = True
    world.write_config("station.yaml", station)


@recipe("mosfet.gate_leakage")
def test_asu_option_runs_on_a_gate_smu_with_its_asu(recipe_id: str, world: World) -> None:
    _asu_station(world)
    scenario_copy(world, "nmos_basic", "nmos_asu",
                  lambda d: [slot.update(asu=True) for slot in d["slots"] if slot["slot"] == 4])
    executor = world.executor()
    record = plan(executor, **REQUESTS[recipe_id], params={"asu_1pa": True})
    assert record.tier == "ok", record.rules.findings
    assert "RI 4,8" in record.flex_preview and record.flex_preview[-1] == "XE"
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed", result.message
    assert [r.command for r in world.sim_log("nmos_asu") if r.mnemonic == "RI"] == ["RI 4,8"]
    leakage = by_quantity(result.analyses)["leakage"]
    assert leakage.outcome == "ok" and leakage.classification == "pass"


@recipe("mosfet.gate_leakage")
def test_asu_option_aborts_before_the_trigger_when_the_instrument_has_no_asu(recipe_id: str, world: World) -> None:
    """The station claims ASU4 present but the mainframe has none: ``RI 4,8`` is an instrument error, the run fails
    before any ``XE`` and the cleanup verifies (the live side of R-ASU-01)."""
    _asu_station(world)
    world.use_scenario("nmos_basic")
    executor = world.executor()
    record = plan(executor, **REQUESTS[recipe_id], params={"asu_1pa": True})
    assert record.tier == "ok"
    result = run(executor, record.plan_id)
    assert not result.ok and result.error_code == "instrument_error" and "124" in result.message, result.message
    assert result.cleanup_verified == "sim_state"
    assert not any(r.mnemonic == "XE" for r in world.sim_log("nmos_basic"))
