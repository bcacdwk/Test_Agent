"""Recipe validation of the WP7.2 sweeps on the simulator (blueprint v2 10.3 row 7.2 AC; per-recipe AC of 10):
``basic.iv_force_i`` (WI), ``mosfet.idvg_family`` and ``mosfet.body_effect`` (smu_stepped), ``mosfet.idvg_sync``
(WSV) and ``generic.smu_multi_sweep`` (MM 16) run through the executor on their §3.1 scenarios with their card
requests, at tier ``ok``, and their default analyses recover the model truth; these tests set their
``status: sim_validated``. Also the current-source paths (DI, WI, WSI, WNX mode 2, ``step_i``) of the test-only
recipes against Ohm's law on a two-resistor scenario, and the MM 16 FLEX preview against the Programming Guide's
multi-channel sweep example (Table 3-13, PDF 226-228).

Tolerances: Vf at 1 mA within 5 mV of the diode model (AC), n ±2 %, Is ±15 %, Rs ±5 % (the v1 diode bounds); DIBL
within 5 mV/V of the model's ``dibl`` (AC; 0 on the long-channel ``nmos_basic``, 60 mV/V on a test copy); the
synchronous curve's Vth within 2 mV and SS within 2 % of the same extractors on the noiseless model curve, and SS
within 3 % of n·U_T·ln10 (the 0.2 V drain head start keeps the weak-inversion drain factor saturated); the body-effect
coefficient within 0.02 V/V of the EKV truth n - 1; R within 1 % of 100 kOhm; resistive readings within 0.1 %.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from b1500_test_agent.analysis import load_run, run_method, with_trust
from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.basic import DiodeDevice
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv
from tests.integration.helpers import REPO_ROOT, World, plan, run
from tests.integration.sweep_cases import (
    CASES,
    GENERIC_MULTI_NMOS,
    GENERIC_MULTI_PG,
    GENERIC_MULTI_RESISTOR,
    PG_EXAMPLE_PARAMS,
    PG_TABLE_3_13_DIFFERENCES,
    R_A,
    R_B,
    pg_table_3_13,
    use_two_resistors,
)

pytestmark = pytest.mark.smu


def for_recipe(recipe_id: str) -> Any:
    """Parametrize a test with the recipe it validates, so ``pytest -k <recipe id>`` selects it (per-recipe AC)."""
    return pytest.mark.parametrize("recipe_id", [recipe_id])


def case(recipe_id: str) -> dict[str, Any]:
    return next(c for c in CASES if c["recipe_id"] == recipe_id)


def run_case(world: World, recipe_id: str, scenario: str | None = None, **params: Any) -> RunSummary:
    entry = case(recipe_id)
    world.use_scenario(scenario or entry["scenario"])
    executor = world.executor()
    record = plan(executor, recipe_id=recipe_id, **{**entry["request"], "params": params})
    assert record.tier == "ok", record.rules.findings
    return run(executor, record.plan_id)


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def device(world: World) -> Any:
    return Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]


def nmos_variant(world: World, name: str, **params: float) -> str:
    """A copy of ``nmos_basic`` with device parameters replaced, written into the world's config folder."""
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_basic.yaml").read_text(encoding="utf-8"))
    scenario["models"]["dut"]["params"].update(params)
    world.write_config(f"sim/scenarios/{name}.yaml", scenario)
    return name


# -- basic.iv_force_i ------------------------------------------------------------------------------------------------


def diode_voltage(diode: DiodeDevice, current: float) -> float:
    """The model's anode voltage at ``current`` (bisection on the monotonic I(V))."""
    lo, hi = 0.0, 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if diode.current(mid) > current:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


@for_recipe("basic.iv_force_i")
def test_iv_force_i_reads_vf_at_1_ma_and_the_diode_parameters(world: World, recipe_id: str) -> None:
    result = run_case(world, recipe_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 71} and result.cleanup_verified == "sim_state"
    diode = device(world)
    assert isinstance(diode, DiodeDevice)
    found = by_quantity(result.analyses)
    assert found["vf"].value == pytest.approx(diode_voltage(diode, 1e-3), abs=0.005)  # AC: Vf at 1 mA +-5 mV
    assert found["vf"].fit["i_a"] == 1e-3 and found["vf"].method_record.params["i_from"] == "plan.resolved_params.i_vf"
    truth = diode.params
    assert found["n"].value == pytest.approx(truth.n, rel=0.02)
    assert found["is"].value == pytest.approx(truth.is_a, rel=0.15)
    assert found["rs"].value == pytest.approx(truth.rs_ohm, rel=0.05)
    data = load_run(result.run_id, data_root=world.data)
    assert data.source_columns == ["anode_I"] and data.measured_columns == ["anode_V"]
    currents = data.table["anode_I"].to_numpy()
    assert currents[0] == pytest.approx(1e-9) and currents[-1] == pytest.approx(1e-2)
    assert np.allclose(np.diff(np.log10(currents)), 0.1, atol=1e-4)  # 10 per decade (WI log; 6-digit data)
    voltages = data.table["anode_V"].to_numpy()
    model = [diode_voltage(diode, i) for i in currents]
    assert np.allclose(voltages, model, atol=2e-5)  # the measured anode voltage is the model's V(I)


@for_recipe("basic.iv_force_i")
def test_iv_force_i_stops_at_the_voltage_compliance_on_an_open(world: World, recipe_id: str) -> None:
    """The current sweep lands on 100 kOhm (``resistor_100k``) with ``vcomp`` 0.5 V: 10 uA needs 1 V, so the anode
    reaches the voltage compliance, the sweep stops there (``C``, ``WM 2,1``) and the rows after it are dummies."""
    world.write_config("duts/diode-wide.yaml", {"device_type": "diode", "terminals": {
        "anode": {"max_abs_v": 5.0, "max_abs_i": 1e-2}, "cathode": {"max_abs_v": 5.0, "max_abs_i": 1e-2}}})
    world.write_config("pinmaps/diode-r.yaml", {"certainty": "verified", "terminals": {"anode": 3, "cathode": "GNDU"}})
    world.use_scenario("resistor_100k")
    executor = world.executor()
    record = plan(executor, recipe_id="basic.iv_force_i", pin_map="diode-r", dut_profile="diode-wide",
                  params={"vcomp": 0.5, "i_vf": 1e-6})
    assert record.tier == "ok", record.rules.findings
    result = run(executor, record.plan_id)
    assert result.outcome == "completed_with_flags" and result.status_counts["C"] == 1
    data = load_run(result.run_id, data_root=world.data)
    flagged = data.table[data.table["anode_V_status"] == "C"]
    assert flagged["anode_V"].iloc[0] == pytest.approx(0.5)  # clamped at Vcomp
    assert flagged["anode_I"].iloc[0] > 0.5 / 1e5  # the first current that needs more than 0.5 V
    vf = by_quantity(result.analyses)["vf"]
    assert vf.value == pytest.approx(1e-6 * 1e5, rel=1e-3)  # the resistor: V = I R at 1 uA


# -- mosfet.idvg_family (DIBL) ----------------------------------------------------------------------------------------


@for_recipe("mosfet.idvg_family")
def test_idvg_family_dibl_of_the_long_channel_device_is_zero(world: World, recipe_id: str) -> None:
    result = run_case(world, recipe_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 726}  # 3 curves x 121 points x (gate, drain)
    found = by_quantity(result.analyses)
    model = device(world)
    assert isinstance(model, MosfetEkv) and model.params.dibl == 0.0
    assert abs(found["dibl"].value) <= 5.0 and found["dibl"].unit == "mV/V"  # AC: DIBL +-5 mV/V
    assert set(found) == {"dibl", "vth_lin", "vth_sat"}
    data = load_run(result.run_id, data_root=world.data)
    assert data.table["drain_V"].unique().tolist() == [0.1, 0.55, 1.0]
    assert data.source_columns == ["gate_V", "drain_V"] and data.measured_columns == ["gate_I", "drain_I"]
    # every curve's Vth equals the same extractor on the noiseless model curve
    for vd in (0.1, 0.55, 1.0):
        assert found["dibl"].fit[f"drain_V={vd:g}"] == pytest.approx(model_vth(model, vd, data), abs=0.002), vd


def model_vth(model: MosfetEkv, vd: float, data: RunData, vb: float = 0.0, i_crit: float = 1e-7) -> float:
    """Constant-current Vth of the noiseless model curve at drain ``vd`` (bulk ``vb``) on the run's gate grid."""
    vg = np.sort(data.table["gate_V"].unique())
    table = pd.DataFrame({"step": np.arange(vg.size), "gate_V": vg,
                          "drain_I": [model.channel_current(v, vd, 0.0, vb) for v in vg], "drain_I_status": "N"})
    [vth] = run_method("vth_constant_current", RunData(manifest_for(data, "mosfet.idvg"), with_trust(table)),
                       {"i_crit_a": i_crit})
    assert vth.value is not None
    return vth.value


def manifest_for(data: RunData, recipe_id: str) -> Any:
    """``data``'s manifest relabelled as a run of ``recipe_id`` (kind ``smu_staircase``) for reference extractions."""
    plan_record = data.manifest.plan.model_copy(update={"kind": "smu_staircase"})
    return data.manifest.model_copy(update={"recipe_id": recipe_id, "plan": plan_record})


@for_recipe("mosfet.idvg_family")
def test_idvg_family_recovers_a_60_mv_per_v_dibl(world: World, recipe_id: str) -> None:
    scenario = nmos_variant(world, "nmos_dibl", dibl=0.06)
    result = run_case(world, recipe_id, scenario=scenario)
    assert result.ok and result.outcome == "completed", result.message
    found = by_quantity(result.analyses)
    assert found["dibl"].value == pytest.approx(60.0, abs=5.0)  # AC: DIBL +-5 mV/V of the model truth
    assert found["vth_lin"].value - found["vth_sat"].value == pytest.approx(0.06 * 0.9, abs=0.0045)
    assert found["dibl"].fit["slope_mv_per_v"] == pytest.approx(60.0, abs=5.0)


# -- mosfet.idvg_sync (WSV) -------------------------------------------------------------------------------------------


@for_recipe("mosfet.idvg_sync")
def test_idvg_sync_steps_the_drain_with_the_gate_and_matches_the_model(world: World, recipe_id: str) -> None:
    result = run_case(world, recipe_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 242}
    data = load_run(result.run_id, data_root=world.data)
    table = data.table
    assert data.source_columns == ["gate_V", "drain_V"]
    assert np.allclose(table["drain_V"], 0.2 + table["gate_V"] * (1.0 / 1.2))  # the WSV synchronous source
    model = device(world)
    assert isinstance(model, MosfetEkv)
    expected = np.array([model.channel_current(vg, vd) for vg, vd in zip(table["gate_V"], table["drain_V"],
                                                                         strict=True)])
    on = np.abs(expected) > 1e-9
    assert np.allclose(table["drain_I"][on], expected[on], rtol=0.01)
    noiseless = pd.DataFrame({"step": table["step"], "gate_V": table["gate_V"], "drain_V": table["drain_V"],
                              "drain_I": expected, "drain_I_status": "N"})
    reference = RunData(data.manifest, with_trust(noiseless))
    found = by_quantity(result.analyses)
    [vth] = run_method("vth_constant_current", reference)
    [ss] = run_method("subthreshold_swing", reference)
    assert found["vth"].value == pytest.approx(vth.value, abs=0.002)
    assert found["ss"].value == pytest.approx(ss.value, rel=0.02)
    ideal = model.subthreshold_swing * 1000.0
    assert found["ss"].value == pytest.approx(ideal, rel=0.03)


# -- mosfet.body_effect -----------------------------------------------------------------------------------------------


@for_recipe("mosfet.body_effect")
def test_body_effect_recovers_the_ekv_coefficient(world: World, recipe_id: str) -> None:
    result = run_case(world, recipe_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 5 * 121 * 3}  # five body biases x 121 points x (gate, drain, bulk)
    model = device(world)
    assert isinstance(model, MosfetEkv)
    found = by_quantity(result.analyses)
    assert found["body_effect"].value == pytest.approx(model.params.slope_factor - 1.0, abs=0.02)
    data = load_run(result.run_id, data_root=world.data)
    assert data.table["bulk_V"].unique().tolist() == [0.0, -0.25, -0.5, -0.75, -1.0]
    assert found["vth_vsb0"].value == pytest.approx(model_vth(model, 0.05, data), abs=0.002)
    assert np.abs(data.table["bulk_I"]).max() < 1e-10  # reverse-biased body: only the MPSMU noise floor
    plan_record = data.manifest.plan
    assert plan_record.binding.roles["bulk"].channel == 5 and plan_record.binding.roles["bulk"].module_type == "MPSMU"


@for_recipe("mosfet.body_effect")
def test_body_effect_needs_the_bulk_on_an_smu(world: World, recipe_id: str) -> None:
    """With ``mosfet-4t`` (bulk on the GNDU) the step role cannot be bound to a source: blocked (R-PIN-01)."""
    world.use_scenario("nmos_basic")
    record = plan(world.executor(), recipe_id="mosfet.body_effect", pin_map="mosfet-4t", dut_profile="nmos-generic")
    assert record.tier == "blocked" and any(f.rule_id == "R-PIN-01" for f in record.rules.findings)


# -- generic.smu_multi_sweep (MM 16) ---------------------------------------------------------------------------------


@for_recipe("generic.smu_multi_sweep")
def test_multi_sweep_measures_the_100k_resistor(world: World, recipe_id: str) -> None:
    result = run_case(world, recipe_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    data = load_run(result.run_id, data_root=world.data)
    assert data.manifest.plan.flex_preview[4:6] == ["MM 16,3", "CMM 3,1"]
    [r, *_] = run_method("resistance", data, {"x": "a_V", "y": "a_I"})
    assert r.value == pytest.approx(1e5, rel=0.01) and r.classification == "in_range"


@for_recipe("generic.smu_multi_sweep")
def test_multi_sweep_second_source_follows_the_primary(world: World, recipe_id: str) -> None:
    """Terminal c on SMU4 (wired to nothing in ``resistor_100k``) sweeps with a: ``WNX 2``; it reads the floor."""
    for rel, content in GENERIC_MULTI_RESISTOR.items():
        world.write_config(rel, content)
    world.use_scenario("resistor_100k")
    executor = world.executor()
    record = plan(executor, recipe_id="generic.smu_multi_sweep", pin_map="multi-r", dut_profile="multi-r",
                  params={"start_c": 0.0, "stop_c": -0.5})
    assert record.tier == "ok", record.rules.findings
    assert "WNX 2,4,1,0,0,-0.5,0.0001" in record.flex_preview and "MM 16,3,4" in record.flex_preview
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed", result.message
    data = load_run(result.run_id, data_root=world.data)
    assert data.source_columns == ["a_V", "c_V"]
    assert np.allclose(data.table["c_V"], -0.5 * data.table["a_V"])
    assert np.abs(data.table["c_I"]).max() < 1e-11  # nothing connected: the HRSMU floor
    assert np.allclose(data.table["a_I"], data.table["a_V"] / 1e5, rtol=0.01, atol=1e-11)


@for_recipe("generic.smu_multi_sweep")
def test_multi_sweep_of_gate_and_drain_equals_the_synchronous_sweep(world: World, recipe_id: str) -> None:
    """MM 16 with the drain as the WNX source reproduces ``mosfet.idvg_sync``'s curve (same model, same points)."""
    for rel, content in GENERIC_MULTI_NMOS.items():
        world.write_config(rel, content)
    world.use_scenario("nmos_basic")
    executor = world.executor()
    params = {"start": 0.0, "stop": 1.2, "points": 121, "icomp": 1e-6, "start_c": 0.2, "stop_c": 1.2,
              "icomp_c": 1e-3}
    record = plan(executor, recipe_id="generic.smu_multi_sweep", pin_map="multi-nmos", dut_profile="multi-nmos",
                  params=params)
    assert record.tier == "ok", record.rules.findings
    multi = run(executor, record.plan_id)
    sync = run_case(world, "mosfet.idvg_sync")
    a = load_run(multi.run_id, data_root=world.data).table
    b = load_run(sync.run_id, data_root=world.data).table
    assert np.allclose(a["c_V"], b["drain_V"]) and np.allclose(a["a_V"], b["gate_V"])
    on = np.abs(b["drain_I"]) > 1e-9
    assert np.allclose(a["c_I"][on], b["drain_I"][on], rtol=0.01)


@for_recipe("generic.smu_multi_sweep")
def test_multi_sweep_preview_matches_the_programming_guide_example(world: World, recipe_id: str) -> None:
    """MM 16 preview vs Table 3-13 (PG PDF 226-228, printed 3-46 to 3-48; ``sweep_cases.pg_table_3_13``): every
    command the example sends is in the preview, identical, except the documented differences."""
    for rel, content in GENERIC_MULTI_PG.items():
        world.write_config(rel, content)
    world.use_scenario("nmos_basic")
    record = plan(world.executor(), recipe_id="generic.smu_multi_sweep", pin_map="pg-3-13", dut_profile="pg-3-13",
                  params=PG_EXAMPLE_PARAMS)
    assert record.tier == "needs_confirmation" and record.rules.confirm_reasons == ["soft_limit"]  # 50 mA > 10 mA
    ours = list(record.flex_preview)
    example = pg_table_3_13()
    dropped = [c for c in example if c.split()[0] in ("TSC", "TSR", "FL", "AV", "RI")]
    assert {c.split()[0] for c in dropped} == {"TSC", "TSR", "FL", "AV", "RI"} <= {
        k.split()[0] for k in PG_TABLE_3_13_DIFFERENCES}
    rewritten = {"WT 0,0,0": "WT 0,0", "WV 3,1,0,0.1,0.9,11,0.1,0.1": "WV 3,1,0,0.1,0.9,11,0.05",
                 "DV 4,0,3,0.1": "DV 4,0,3,0.05"}  # WT form, Pcomp dropped, 50 mA compliances
    expected = [rewritten.get(c, c) for c in example if c not in dropped]
    assert sorted(c for c in ours if not c.startswith(("AAD", "AIT", "CN"))) == sorted(expected)
    assert ours[0] == "FMT 1,1" and ours[-1] == "XE"
    assert ours.index("MM 16,3,4") < ours.index("CMM 3,1") < ours.index("WV 3,1,0,0.1,0.9,11,0.05")
    assert "DV 5,0,0,0.1" in ours  # the emitter: an SMU at 0 V with the summed 100 mA compliance, as the example


# -- current sources against Ohm's law (test-only recipes) -----------------------------------------------------------


def run_two_resistors(world: World, recipe_id: str, **params: Any) -> tuple[PlanRecord, pd.DataFrame, RunSummary]:
    use_two_resistors(world)
    executor = world.executor()
    record = executor.plan(PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": "two-r",
                                                       "dut_profile": "two-r", "params": params}))
    assert record.tier == "ok", record.rules.findings
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed", result.message
    return record, load_run(result.run_id, data_root=world.data).table, result


def test_bias_i_forces_a_dc_current(world: World) -> None:
    record, table, _ = run_two_resistors(world, "generic.bias_current", i_b=5e-6)
    assert "DI 5,0,5E-06,2" in record.flex_preview
    assert np.allclose(table["b_V"], 5e-6 * R_B, rtol=1e-3)
    assert np.allclose(table["a_I"], table["a_V"] / R_A, rtol=1e-3)
    assert list(table.columns) == ["step", "a_V", "a_I", "a_I_status", "b_V", "b_V_status", "b_I", "trust"]
    assert set(table["b_I"]) == {5e-6}  # the bias source column


def test_step_i_family_forces_each_current(world: World) -> None:
    record, table, result = run_two_resistors(world, "generic.current_family")
    assert [line for line in record.flex_preview if line.startswith("DI")] == [
        "DI 5,0,1E-06,2", "DI 5,0,2E-06,2", "DI 5,0,3E-06,2", "DI 5,0,4E-06,2"]
    assert table["b_I"].unique().tolist() == [1e-6, 2e-6, 3e-6, 4e-6]  # the step column
    assert np.allclose(table["b_V"], table["b_I"] * R_B, rtol=1e-3)
    assert result.status_counts == {"N": 4 * 11 * 2}


def test_sync_current_source_follows_a_log_current_sweep(world: World) -> None:
    record, table, _ = run_two_resistors(world, "generic.sync_current")
    assert "WI 3,2,0,1E-06,0.0001,11,2" in record.flex_preview and "WSI 5,0,1E-07,1E-05,2" in record.flex_preview
    assert np.allclose(np.log10(table["b_I"]), np.log10(table["a_I"]) - 1.0)  # same log steps, a decade lower
    assert np.allclose(table["a_V"], table["a_I"] * R_A, rtol=1e-3)
    assert np.allclose(table["b_V"], table["b_I"] * R_B, rtol=1e-3)


def test_multi_channel_sweep_mixes_voltage_and_current_sources(world: World) -> None:
    record, table, _ = run_two_resistors(world, "generic.multi_mixed")
    assert "WNX 2,5,2,0,0,1E-05,2" in record.flex_preview and "MM 16,3,5" in record.flex_preview
    assert np.allclose(table["b_I"], table["a_V"] * 1e-5)  # the WNX current follows a's steps
    assert np.allclose(table["b_V"], table["b_I"] * R_B, atol=1e-9)
    assert np.allclose(table["a_I"], table["a_V"] / R_A, rtol=1e-3)


def test_the_five_recipes_are_sim_validated(world: World) -> None:
    registry = world.executor().registry()
    assert [registry.get(c["recipe_id"]).status for c in CASES] == ["sim_validated"] * 5
