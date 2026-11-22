"""Recipe validation of the composite kind ``stress_measure`` on the simulator (WP7.6; blueprint v2 10.3 row 7.6,
per-recipe AC: tier, run, default analysis vs the 4.2 fidelity target). These tests set ``status: sim_validated`` of
``reliability.bti_sms``, ``igzo.bias_stress``, ``reliability.hci`` and ``reliability.silc``.

- BTI (scenario ``nmos_bti``): the power law dVth = A t^n of the model recovers n +-0.02 and A +-10 % (4.2), the
  recovered fraction follows the log-recovery law; the 30-minute card plan runs asynchronously (S14 shape).
- IGZO (scenario ``igzo_transient``): PBS and NBS give the stretched-exponential tau +-15 %, beta +-0.1 and dV_inf.
- HCI (``nmos_bti``): dId/Id0 = b t^m recovers m +-0.03 (4.2) and b within 10 %.
- SILC (``nmos_bti`` gate oxide): the SILC ratio and exponent of the dielectric's damage law, Ig0 and q_inj; a gate
  breakdown under the stress stops the run (compliance) with the reads before it analysed.
- Cancel at every checkpoint (AC): outcome ``cancelled``, outputs zero (cleanup verified), the partial rows up to that
  checkpoint and no trigger after it; a 4 h BTI runs asynchronously in < 2 s (``timing: instant``, blueprint v2 4.1).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.catalog.kinds.stress_measure import StressProgram
from tests.integration.async_helpers import (
    assert_async_invariant,
    manifest_of,
    partial_rows,
    progress_of,
    run_events,
)
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.test_async_cancel import abort_at
from tests.integration.test_recipes_sampling import by_quantity, run_request, truth_device

BASE = {"pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
BTI = {"recipe_id": "reliability.bti_sms", **BASE}
IGZO = {"recipe_id": "igzo.bias_stress", **BASE}
HCI = {"recipe_id": "reliability.hci", **BASE}
SILC = {"recipe_id": "reliability.silc", **BASE}
COLUMNS = ["step", "t_s", "cycle", "phase", "gate_V", "drain_V", "gate_I", "gate_I_status", "drain_I",
           "drain_I_status", "trust"]
SMALL = {"vg_stress": 2.0, "stress_time": 30.0, "reads_per_decade": 1, "recovery_time": 10.0}
"""A short BTI plan: reads at 0 (reference), 1, 10, 30 s of stress and 1, 10 s of recovery; one hold block per
segment, so 11 checkpoints (6 reads, 5 hold blocks)."""


def bti_faults(world: World, name: str, faults: list[dict[str, Any]]) -> str:
    """Select a copy of ``nmos_bti`` whose fault profile ``name`` holds ``faults``; returns the scenario name."""
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_bti.yaml").read_text(encoding="utf-8"))
    scenario["faults"] = name
    world.write_config(f"sim/faults/{name}.yaml", {"description": "test", "faults": faults})
    world.write_config(f"sim/scenarios/nmos_bti_{name}.yaml", scenario)
    world.use_scenario(f"nmos_bti_{name}")
    return f"nmos_bti_{name}"


def device(world: World, name: str = "dut") -> Any:
    from b1500_test_agent.config import load_config
    from b1500_test_agent.transport.sim.devices import Circuit

    return Circuit(load_config(world.paths).sim_scenario).devices[name]  # type: ignore[arg-type]


# -- reliability.bti_sms --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["reliability.bti_sms"])
def test_bti_sms_recovers_the_power_law(recipe_id: str, world: World) -> None:
    """The card example plan (2 V, 30 min, 3 reads per decade): async, long_run + destructive, n and A vs truth."""
    world.use_scenario("nmos_bti")
    service = world.service()
    validation, result = run_request(service, {**BTI, "recipe_id": recipe_id}, vg_stress=2.0, stress_time=1800.0)
    assert validation.tier == "needs_confirmation" and sorted(validation.confirm_reasons) == ["destructive",
                                                                                             "long_run"]
    assert validation.resolved is not None and validation.resolved.mode == "async"
    assert "gate=SMU4(HRSMU) sweep -0.2..1.5 V (max 2 V) stress 2 V Icomp 1 uA" in (validation.summary or "")
    assert "stress 30 min x11 reads" in (validation.summary or "")
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    found = by_quantity(result.analyses)
    dut = device(world)
    assert found["n"].value == pytest.approx(dut.params.bti_n, abs=0.02)
    assert found["a"].value == pytest.approx(dut.bti_truth(2.0, 1.0), rel=0.10)
    assert found["dvth"].value == pytest.approx(dut.bti_truth(2.0, 1800.0), rel=0.03)
    assert found["n"].derived and found["n"].method_record.name == "bti_power_law"
    data = load_run(result.run_id or "", data_root=world.data)
    assert list(data.table.columns) == COLUMNS
    reads = data.table[data.table["phase"] == "read"].groupby("cycle")["t_s"].first()
    assert list(reads.round(6)) == [0.0, 1.0, 2.15, 4.64, 10.0, 21.54, 46.42, 100.0, 215.44, 464.16, 1000.0, 1800.0]
    holds = data.table[data.table["phase"] == "stress"]
    assert len(holds) == data.manifest.kind_result["holds_done"] == 78 and (holds["gate_V"] == 2.0).all()
    assert data.manifest.kind_result == {
        "read_kind": "staircase", "reads_planned": 12, "reads_done": 12, "holds_planned": 78, "holds_done": 78,
        "stress_s_planned": 1800.0, "stress_s_done": 1800.0, "recovery_s_planned": 0.0, "recovery_s_done": 0.0,
        "stopped_early": False, "stop_reason": ""}
    progress = progress_of(world, result.run_id or "")
    assert progress is not None and (progress.done, progress.total, progress.state) == (90, 90, "completed")
    assert_async_invariant(world, result.run_id or "", scenario="nmos_bti")
    service.close()


@pytest.mark.parametrize("recipe_id", ["reliability.bti_sms"])
def test_bti_recovery_follows_the_log_recovery_law(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_bti")
    service = world.service()
    _, result = run_request(service, {**BTI, "recipe_id": recipe_id}, vg_stress=2.0, stress_time=1000.0,
                            recovery_time=1000.0)
    assert result.outcome == "completed", result.message
    found = by_quantity(result.analyses)
    dut = device(world)
    end = dut.bti_truth(2.0, 1000.0)
    assert found["dvth"].value == pytest.approx(end, rel=0.03)
    assert found["recovery"].value == pytest.approx(1.0 - dut.bti_recovery_truth(end, 1000.0) / end, abs=0.02)
    assert found["recovery_rate"].value == pytest.approx(dut.params.bti_recovery, rel=0.15)
    data = load_run(result.run_id or "", data_root=world.data)
    recovery = data.table[data.table["phase"] == "recovery"]
    assert (recovery["gate_V"] == 0.0).all() and recovery["t_s"].max() == pytest.approx(2000.0)
    assert data.manifest.kind_result["recovery_s_done"] == pytest.approx(1000.0)
    service.close()


@pytest.mark.parametrize("recipe_id", ["reliability.bti_sms"])
def test_bti_spot_reads_analyse_with_degradation_vs_time(recipe_id: str, world: World) -> None:
    """``read_kind: spot``: Id at vg_read per read; the Vth method has no sweep and fails with the hint, the drain
    current change is the spot reads' measure."""
    world.use_scenario("nmos_bti")
    service = world.service()
    _, result = run_request(service, {**BTI, "recipe_id": recipe_id}, vg_stress=2.0, stress_time=100.0,
                            read_kind="spot", samples=2)
    assert result.outcome == "completed_with_flags" and "degradation_vs_time" in result.message, result.message
    assert {r.outcome for r in result.analyses} == {"failed"}
    data = load_run(result.run_id or "", data_root=world.data)
    reads = data.table[data.table["phase"] == "read"]
    assert (reads["gate_V"] == 1.0).all() and len(reads) == 2 * 8
    from b1500_test_agent.analysis import degradation_vs_time

    found = by_quantity(degradation_vs_time(data, quantity="id", y="drain_I"))
    assert found["delta"].value is not None and found["delta"].value < 0  # Vth up: Id down
    service.close()


# -- igzo.bias_stress -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("vg_stress", "sign"), [(3.0, 1.0), (-3.0, -1.0)],
                         ids=["igzo.bias_stress-pbs_card_example", "igzo.bias_stress-nbs"])
def test_igzo_bias_stress_recovers_the_stretched_exponential(world: World, vg_stress: float, sign: float) -> None:
    world.use_scenario("igzo_transient")
    service = world.service()
    validation, result = run_request(service, IGZO, vg_stress=vg_stress)
    assert validation.tier == "needs_confirmation" and validation.confirm_reasons == ["destructive"]
    assert f"stress {vg_stress:g} V" in (validation.summary or "")
    assert result.outcome == "completed" and result.quality_verdict == "ok", result.message
    found = by_quantity(result.analyses)
    dut = device(world)
    assert found["tau"].value == pytest.approx(dut.params.igzo_tau_s, rel=0.15)
    assert found["beta"].value == pytest.approx(dut.params.igzo_beta, abs=0.1)
    truth = dut.igzo_truth(vg_stress, 300.0)
    assert found["delta"].value == pytest.approx(truth, rel=0.05) and found["delta"].value * sign > 0
    assert found["delta_inf"].value == pytest.approx(dut.params.igzo_dvth_per_v * vg_stress, rel=0.05)
    data = load_run(result.run_id or "", data_root=world.data)
    assert data.manifest.kind_result["reads_done"] == 16 and data.manifest.kind_result["stress_s_done"] == 300.0
    service.close()


# -- reliability.hci ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["reliability.hci"])
def test_hci_recovers_the_drain_degradation_power_law(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_bti")
    service = world.service()
    validation, result = run_request(service, {**HCI, "recipe_id": recipe_id}, vg_stress=1.2, vd_stress=2.5)
    assert sorted(validation.confirm_reasons) == ["destructive", "long_run"]
    summary = validation.summary or ""
    assert "drain=SMU3(HRSMU) bias 0.05 V (max 2.5 V) stress 2.5 V" in summary and "stress 1.2 V" in summary
    assert result.outcome == "completed" and result.quality_verdict == "ok", result.message
    found = by_quantity(result.analyses)
    dut = device(world)
    assert found["m"].value == pytest.approx(dut.params.hci_m, abs=0.03)
    assert -found["b"].value == pytest.approx(dut.hci_truth(2.5, 1.0), rel=0.10)
    assert -found["delta"].value == pytest.approx(dut.hci_truth(2.5, 1000.0), rel=0.10)
    data = load_run(result.run_id or "", data_root=world.data)
    holds = data.table[data.table["phase"] == "stress"]
    assert (holds["drain_V"] == 2.5).all() and (holds["gate_V"] == 1.2).all()
    assert holds["drain_I"].iloc[-1] < holds["drain_I"].iloc[0]  # the stress current degrades too
    reads = data.table[data.table["phase"] == "read"]
    assert (reads["gate_V"] == 1.5).all() and (reads["drain_V"] == 0.05).all() and len(reads) == 11 * 3
    service.close()


# -- reliability.silc -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["reliability.silc"])
def test_silc_recovers_the_oxide_damage_law(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_bti")
    service = world.service()
    validation, result = run_request(service, {**SILC, "recipe_id": recipe_id}, vg_stress=2.8)
    assert sorted(validation.confirm_reasons) == ["destructive", "long_run"]
    assert result.outcome == "completed" and result.quality_verdict == "ok", result.message
    found = by_quantity(result.analyses)
    gox = device(world, "gox")
    rate = 1.0 / gox.t_bd(2.8)  # damage per second at 2.8 V (constant: no breakdown)
    i0 = gox.conduction(1.5)
    assert found["ig0"].value == pytest.approx(i0, rel=0.02)
    assert found["silc_ratio"].value == pytest.approx(gox.conduction(1.5, damage=1000.0 * rate) / i0 - 1.0, rel=0.10)
    assert found["silc_exponent"].value == pytest.approx(1.0, abs=0.1)
    q_true = gox.conduction(2.8) * 1000.0 + gox.params.silc_s * 2.8 * rate * 1000.0**2 / 2.0
    assert found["q_inj"].value == pytest.approx(q_true, rel=0.05) and found["q_inj"].unit == "C"
    data = load_run(result.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "t_s", "cycle", "phase", "gate_V", "gate_I", "gate_I_status",
                                        "trust"]
    service.close()


@pytest.mark.parametrize("recipe_id", ["reliability.silc"])
def test_a_gate_breakdown_under_silc_stress_stops_the_run(recipe_id: str, world: World) -> None:
    scenario = bti_faults(world, "silc_breakdown", [{"kind": "breakdown_at", "t_s": 5.0}])
    service = world.service()
    _, result = run_request(service, {**SILC, "recipe_id": recipe_id}, vg_stress=2.8, stress_time=100.0)
    assert result.outcome == "completed_with_flags" and result.status_counts.get("C") == 1, result.message
    data = load_run(result.run_id or "", data_root=world.data)
    result_ = data.manifest.kind_result
    assert result_["stopped_early"] is True and "status C" in str(result_["stop_reason"])
    assert result_["reads_done"] < result_["reads_planned"]
    last = data.table.iloc[-1]
    assert last["phase"] == "stress" and last["gate_I_status"] == "C"
    assert_async_invariant(world, result.run_id or "", scenario=scenario)
    service.close()


# -- cancel at every checkpoint (AC) ---------------------------------------------------------------------------------


def _small_plan(world: World, recipe_id: str = "reliability.bti_sms") -> tuple[Any, StressProgram]:
    world.use_scenario("nmos_bti")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**{**BTI, "recipe_id": recipe_id}, params=SMALL)
    assert validation.ok and validation.plan_id is not None, validation.message
    plan = world.executor().load_plan(validation.plan_id)
    return validation, StressProgram.model_validate(plan.program)


def test_the_small_plan_has_eleven_checkpoints(world: World) -> None:
    _, program = _small_plan(world)
    ops = program.timeline()
    assert [(op.kind, op.cycle, op.phase, op.t_s) for op in ops] == [
        ("read", 0, "read", 0.0), ("hold", 1, "stress", 1.0), ("read", 1, "read", 1.0),
        ("hold", 2, "stress", 10.0), ("read", 2, "read", 10.0), ("hold", 3, "stress", 30.0), ("read", 3, "read", 30.0),
        ("hold", 4, "recovery", 31.0), ("read", 4, "read", 31.0), ("hold", 5, "recovery", 40.0),
        ("read", 5, "read", 40.0)]


@pytest.mark.parametrize("k", range(1, 12))
@pytest.mark.parametrize("recipe_id", ["reliability.bti_sms"])
def test_cancel_at_every_checkpoint_zeroes_the_outputs_and_keeps_the_partial_rows(
        recipe_id: str, world: World, monkeypatch: pytest.MonkeyPatch, k: int) -> None:
    """AC: an abort request seen at checkpoint k cancels there: outcome cancelled, verified cleanup, outputs zero,
    the rows of the first k checkpoints in partial.csv, no trigger after the cancelling checkpoint."""
    validation, program = _small_plan(world, recipe_id)
    rows_per_op = [program.read.staircase.steps if op.kind == "read" else 1  # type: ignore[union-attr]
                   for op in program.timeline()]
    service = world.services[-1]
    abort_at(monkeypatch, world, k)
    result = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    if result.outcome == "running":
        result = service.follow_run(result.run_id or "")  # type: ignore[assignment]
    assert result is not None and (result.outcome, result.error_code) == ("cancelled", "run_cancelled")
    assert result.cleanup_verified == "sim_state" and "data" not in result.artifacts
    run_id = result.run_id or ""
    assert partial_rows(world, run_id) == sum(rows_per_op[:k])
    manifest = assert_async_invariant(world, run_id, scenario="nmos_bti")
    assert manifest.outcome == "cancelled"
    events = run_events(world, run_id)
    xe = [e for e in events if e.ev == "write" and e.cmd == "XE"]
    assert len(xe) == k  # every checkpoint follows exactly one trigger; none after the cancelling one
    service.close()


@pytest.mark.parametrize("recipe_id", ["reliability.bti_sms"])
def test_an_async_bti_cancels_at_a_hold_block(recipe_id: str, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.use_scenario("nmos_bti")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**{**BTI, "recipe_id": recipe_id},
                                       params={"vg_stress": 2.0, "stress_time": 1800.0})
    abort_at(monkeypatch, world, 40)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "cancelled" and final.cleanup_verified == "sim_state"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.total, progress.state) == (40, 90, "cancelled")
    assert partial_rows(world, final.run_id or "") > 0
    manifest = assert_async_invariant(world, final.run_id or "", scenario="nmos_bti")
    assert manifest.plan.mode == "async"
    service.close()


@pytest.mark.wall_clock
@pytest.mark.parametrize("recipe_id", ["reliability.bti_sms"])
def test_a_four_hour_bti_runs_asynchronously_in_seconds(recipe_id: str, world: World) -> None:
    """Blueprint v2 4.1: a 4 h BTI (2 V, 3 reads per decade, 576 hold blocks) runs in < 2 s of wall time (timing
    instant)."""
    world.use_scenario("nmos_bti")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**{**BTI, "recipe_id": recipe_id},
                                       params={"vg_stress": 2.0, "stress_time": 14400.0})
    assert validation.resolved is not None and validation.resolved.mode == "async"
    t0 = time.monotonic()
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running" and time.monotonic() - t0 < 1.0
    final = service.follow_run(started.run_id or "")
    wall = time.monotonic() - t0
    assert final is not None and final.outcome == "completed", final.message
    timings = manifest_of(world, final.run_id or "").timings  # type: ignore[union-attr]
    assert wall < 2.0, f"4 h BTI took {wall:.2f} s of wall time (manifest timings {timings})"
    found = by_quantity(final.analyses)
    assert found["n"].value == pytest.approx(device(world).params.bti_n, abs=0.02)
    service.close()


def test_device_truth_helper_matches_the_sampling_helper(world: World) -> None:
    world.use_scenario("nmos_bti")
    assert truth_device(world).truth()["bti_n"] == device(world).params.bti_n == 0.2
