"""Recipe validation of the sampling kind on the simulator (WP7.4; blueprint v2 10.3 row 7.4, per-recipe AC: tier,
run, default analysis vs the 4.2 fidelity target). These tests set ``status: sim_validated`` of
``mosfet.id_t_sampling``, ``generic.smu_sampling`` and ``reliability.tddb_cvs``.

- IGZO transient (scenario ``igzo_transient``): the stretched-exponential tau and beta of Id(t) after the gate step
  recover the model's Vth drift within tau +-15 %, beta +-0.1 (linear region and the lab's 5 V drain).
- TDDB (scenario ``dielectric_tddb``): t_bd within one sampling interval of the model's Weibull life; the automatic
  abort ends the run; a 4 h stress runs asynchronously in less than 3 s of wall time (``timing: instant``) and is
  cancellable at a block boundary with a verified cleanup.
- generic sampling on a resistor; index gaps when the measurement is slower than the interval.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.async_helpers import (
    assert_async_invariant,
    manifest_of,
    partial_rows,
    progress_of,
)
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.test_async_cancel import abort_at

ID_T = {"recipe_id": "mosfet.id_t_sampling", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
TDDB = {"recipe_id": "reliability.tddb_cvs", "pin_map": "mosfet-4t", "dut_profile": "dielectric-generic"}
GENERIC_CONFIG: dict[str, Any] = {
    "pinmaps/generic-sampling-2t.yaml": {"certainty": "verified", "terminals": {"stress": 3, "ground": "GNDU"}},
    "duts/generic-sampling-2t.yaml": {"device_type": "resistor", "terminals": {
        "stress": {"max_abs_v": 2.0, "max_abs_i": 1e-3}, "ground": {"max_abs_v": 0.0, "max_abs_i": 1e-3}}},
}
"""Test-only pin map and DUT profile naming the generic recipe's terminals (no committed example has them)."""
GENERIC = {"recipe_id": "generic.smu_sampling", "pin_map": "generic-sampling-2t", "dut_profile": "generic-sampling-2t"}


def run_request(service: B1500Service, request: dict[str, Any], **params: Any) -> tuple[Any, RunSummary]:
    """Validate (confirming with the plan's own summary when asked, the test stands in for the human) and run to the
    end (following an asynchronous run)."""
    validation = service.validate_plan(**{**request, "params": params})
    assert validation.ok and validation.plan_id is not None, validation.message
    if validation.tier == "ok":
        result = service.run_plan(validation.plan_id)
    else:
        assert validation.tier == "needs_confirmation" and validation.summary is not None
        result = service.run_confirmed_plan(validation.plan_id, validation.summary)
    if result.outcome == "running":
        final = service.follow_run(result.run_id or "")
        assert final is not None
        result = final
    return validation, result


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def truth_device(world: World) -> Any:
    return Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]


# -- mosfet.id_t_sampling -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("params", "tier"), [({"vd": 0.1}, "ok"), ({}, "needs_confirmation")],
                         ids=["mosfet.id_t_sampling-card_example_linear_region",
                              "mosfet.id_t_sampling-lab_defaults_vd_5v"])
def test_id_t_sampling_recovers_the_igzo_drift(world: World, params: dict[str, Any], tier: str) -> None:
    world.use_scenario("igzo_transient")
    service = world.service()
    validation, result = run_request(service, ID_T, **params)
    assert validation.tier == tier and (tier == "ok" or validation.confirm_reasons == ["dut_envelope"])
    assert validation.resolved is not None and validation.resolved.mode == "sync"
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 10001}
    found = by_quantity(result.analyses)
    device = truth_device(world)
    assert found["tau"].value == pytest.approx(device.params.igzo_tau_s, rel=0.15)
    assert found["beta"].value == pytest.approx(device.params.igzo_beta, abs=0.1)
    assert found["drift"].value < 0  # positive gate stress: Vth up, Id down
    data = load_run(result.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "t_s", "drain_I", "drain_I_status", "gate_V", "drain_V", "trust"]
    assert data.table["t_s"].iloc[0] == pytest.approx(0.01) and data.table["t_s"].iloc[-1] == pytest.approx(40.01)
    assert data.manifest.kind_result == {
        "blocks_planned": 1, "blocks_done": 1, "samples_planned": 10001, "samples_measured": 10001,
        "samples_after_abort": 0, "index_gaps": 0, "aborted": False, "abort_reason": "", "abort_t_s": None,
        "stopped_early": False, "time_source": "timestamp"}
    service.close()


# -- reliability.tddb_cvs -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["reliability.tddb_cvs"])
def test_tddb_breakdown_time_is_within_one_interval_of_the_model(recipe_id: str, world: World) -> None:
    world.use_scenario("dielectric_tddb")
    service = world.service()
    t_true = truth_device(world).t_bd(5.5)
    validation, result = run_request(service, {**TDDB, "recipe_id": recipe_id}, v_stress=5.5, duration=600.0,
                                     interval=1.0)
    assert sorted(validation.confirm_reasons) == ["destructive", "long_run"]
    assert validation.resolved is not None and validation.resolved.mode == "async"
    assert result.outcome == "completed_with_flags" and result.quality_verdict == "limited", result.message
    assert result.status_counts["C"] == 1  # the breakdown sample itself
    (t_bd,) = result.analyses
    assert t_bd.quantity == "t_bd" and t_bd.classification == "breakdown"
    assert t_bd.value is not None and 0.0 <= t_bd.value - t_true < 1.0  # within one interval (blueprint 4.2)
    manifest = manifest_of(world, result.run_id or "")
    assert manifest is not None and manifest.kind_result["aborted"] is True
    assert manifest.kind_result["stopped_early"] is True and manifest.kind_result["blocks_done"] == 5
    assert manifest.kind_result["abort_t_s"] == t_bd.value
    assert_async_invariant(world, result.run_id or "", scenario="dielectric_tddb")
    # the broken site stays broken: a second stress breaks at the first sample (flagged)
    _, again = run_request(service, TDDB, v_stress=5.5, duration=600.0, interval=1.0)
    (second,) = again.analyses
    assert second.value == 0.0 and any("before the stress" in w for w in second.warnings)
    service.close()


@pytest.mark.wall_clock
@pytest.mark.parametrize("recipe_id", ["reliability.tddb_cvs"])
def test_a_four_hour_tddb_runs_asynchronously_in_seconds(recipe_id: str, world: World) -> None:
    """AC: a 4 h TDDB stress (4.5 V, 2 s interval: 601 blocks) runs async in < 3 s of wall time (timing instant)."""
    world.use_scenario("dielectric_tddb")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**{**TDDB, "recipe_id": recipe_id},
                                       params={"v_stress": 4.5, "duration": 14400.0, "interval": 2.0})
    assert validation.resolved is not None and validation.resolved.mode == "async"
    assert validation.resolved.est_s >= 4 * 3600 and validation.summary is not None
    t0 = time.monotonic()
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary)
    assert started.outcome == "running" and time.monotonic() - t0 < 1.0
    final = service.follow_run(started.run_id or "")
    wall = time.monotonic() - t0
    assert final is not None and final.outcome == "completed", final.message
    timings = manifest_of(world, final.run_id or "").timings  # type: ignore[union-attr]
    assert wall < 3.0, f"4 h TDDB took {wall:.2f} s of wall time (manifest timings {timings})"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.total, progress.state) == (601, 601, "completed")
    data = load_run(final.run_id or "", data_root=world.data)
    assert len(data.table) == 7201 and data.table["t_s"].iloc[-1] >= 4 * 3600
    (t_bd,) = final.analyses
    assert t_bd.classification == "no_breakdown" and t_bd.bound == "lower"  # t_bd(4.5 V) is about 100 h
    manifest = assert_async_invariant(world, final.run_id or "", scenario="dielectric_tddb")
    assert manifest.kind_result["blocks_done"] == 601 and manifest.kind_result["time_source"] == "timestamp"
    service.close()


@pytest.mark.parametrize("recipe_id", ["reliability.tddb_cvs"])
def test_a_long_tddb_cancels_at_a_block_boundary(recipe_id: str, world: World,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    world.use_scenario("dielectric_tddb")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**{**TDDB, "recipe_id": recipe_id},
                                       params={"v_stress": 4.5, "duration": 3600.0, "interval": 1.0})
    abort_at(monkeypatch, world, 7)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "cancelled" and final.error_code == "run_cancelled"
    assert final.cleanup_verified == "sim_state"
    assert partial_rows(world, final.run_id or "") == 7 * 25  # seven blocks of 25 samples at 1 s
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.state) == (7, "cancelled")
    assert_async_invariant(world, final.run_id or "", scenario="dielectric_tddb")
    service.close()


# -- generic.smu_sampling -------------------------------------------------------------------------------------------


def generic_world(world: World, faults: list[dict[str, Any]] | None = None) -> None:
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/resistor_100k.yaml").read_text(encoding="utf-8"))
    if faults:
        world.write_config("sim/faults/sampling_faults.yaml", {"description": "test", "faults": faults})
        scenario["faults"] = "sampling_faults"
    world.write_config("sim/scenarios/resistor_sampling.yaml", scenario)
    world.use_scenario("resistor_sampling")
    for rel, data in GENERIC_CONFIG.items():
        world.write_config(rel, data)


@pytest.mark.parametrize("recipe_id", ["generic.smu_sampling"])
def test_generic_sampling_measures_the_resistor_current(recipe_id: str, world: World) -> None:
    generic_world(world)
    service = world.service()
    validation, result = run_request(service, {**GENERIC, "recipe_id": recipe_id}, base=0.0, bias=1.0,
                                     interval=0.01, points=501)
    assert validation.tier == "ok" and result.outcome == "completed", result.message
    found = by_quantity(result.analyses)
    r_ohm = truth_device(world).params.r_ohm
    assert found["mean"].value == pytest.approx(1.0 / r_ohm, rel=0.005)
    assert abs(found["drift"].value) < 0.01
    data = load_run(result.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "t_s", "stress_I", "stress_I_status", "stress_V", "trust"]
    service.close()


@pytest.mark.parametrize("recipe_id", ["generic.smu_sampling"])
def test_a_measurement_slower_than_the_interval_shows_index_gaps(recipe_id: str, world: World) -> None:
    generic_world(world, faults=[{"kind": "slow", "factor": 3.5}])
    service = world.service()
    _, result = run_request(service, {**GENERIC, "recipe_id": recipe_id}, bias=1.0, interval=0.01, points=50,
                            integration="long")
    assert result.outcome == "completed", result.message
    data = load_run(result.run_id or "", data_root=world.data)
    steps = data.table["t_s"].diff().dropna().round(6).unique().tolist()
    assert steps == [0.04]  # every fourth grid point: 3.5 x the 10 ms the instrument allows per sample
    assert data.manifest.kind_result["index_gaps"] == 49 * 3
    service.close()
