"""Recipe validation of the WP10.6 recipes on the simulator (blueprint v2 10.6 row 10.6, per-recipe AC: tier, run,
default analysis vs the 4.2 target). These tests set ``status: sim_validated`` of ``fecap.pund``,
``fefet.fast_program_read`` and ``fecap.endurance_pund``.

- ``fecap.pund`` (kind ``wgfmu_waveform``, builder ``pund``) on ``fecap_basic``: Pr, Ps and Ec within 5 % of the
  model's ``pund_truth`` (blueprint v2 4.2 ``ferro`` FeCap), reported as derived values with method and window (S13's
  contract), the event layout of the table, ``program.json`` and the raw readback.
- ``fefet.fast_program_read`` (builder ``program_read``) on ``fefet_lab``'s WGFMU landing: the memory window within
  10 % of ``memory_window_truth``, the reads microseconds after their pulses, cycle/phase rows.
- ``fecap.endurance_pund`` (kind ``pulse_read``, WGFMU path, PUND reads): the card example is an asynchronous long
  plan; 10^7 cycles run with checkpoints, Pr of every checkpoint within 5 % of the wake-up/fatigue truth, wake-up,
  fatigue and cycles to failure from the analysis; cancel at checkpoints: both buses clean (WGFMU disconnected and
  idle, RSUs at rest, SMUs off), partial rows kept.
- The WGFMU path with staircase reads (test-only ``generic.wgfmu_pulse_read`` on the FeFET landing): schedules
  ``cycles`` (memory window vs the model), ``grid`` (each point's state vs the NLS pulse truth) and ``retention``
  (log-decay slopes).
"""

from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.analysis import load_run, pulse_reads, vth_constant_current
from b1500_test_agent.archive.runfiles import read_program
from b1500_test_agent.config import load_config
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.async_helpers import assert_async_invariant, partial_rows, progress_of
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.test_async_cancel import abort_at

pytestmark = pytest.mark.wgfmu

FECAP = "fecap_basic"
FEFET = "fefet_lab"
PUND = {"recipe_id": "fecap.pund", "pin_map": "fecap-wgfmu", "dut_profile": "fecap-generic"}
ENDURANCE = {"recipe_id": "fecap.endurance_pund", "pin_map": "fecap-wgfmu", "dut_profile": "fecap-generic"}
FAST = {"recipe_id": "fefet.fast_program_read", "pin_map": "fefet-wgfmu", "dut_profile": "fefet-lab"}
WG_READ = {"recipe_id": "generic.wgfmu_pulse_read", "pin_map": "fefet-wgfmu", "dut_profile": "fefet-lab"}
REQUESTS = {r["recipe_id"]: r for r in (PUND, ENDURANCE, FAST)}
"""Plan requests by recipe id: each recipe's tests carry the id in their node id (``pytest -k <recipe>``)."""
UNVERIFIED = ["unverified_pin_map", "unverified_topology"]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recipes" / "generic" / "wgfmu_pulse_read.yaml"


def confirmed(world: World, request: dict[str, Any], *, reasons: list[str] | None = None, **params: Any) -> Any:
    service = world.service()
    validation = service.validate_plan(**request, params=params)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    if reasons is not None:
        assert sorted(validation.confirm_reasons) == sorted(reasons), validation.confirm_reasons
    result = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    if result.outcome == "running":
        result = service.follow_run(result.run_id or "")
    assert result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state"
    return result


def by_quantity(results: list[Any]) -> dict[str, Any]:
    return {r.quantity: r for r in results}


def device(world: World, name: str) -> Any:
    return Circuit(load_config(world.paths).sim_scenario).devices[name]  # type: ignore[arg-type]


def sim_state(world: World, scenario: str) -> Any:
    state = load_state_file(sim_state_file(world.state_dir, scenario))
    assert state is not None
    return state


def wgfmu_idle(world: World, scenario: str) -> bool:
    return all(not s.connected and not s.running for s in sim_state(world, scenario).wgfmu.values())


def run_folder(world: World, run_id: str) -> Path:
    return next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())


def with_fixture(world: World) -> World:
    target = world.root / "recipes"
    if not target.exists():
        shutil.copytree(REPO_ROOT / "recipes", target)
        shutil.copy(FIXTURE, target / "generic" / FIXTURE.name)
    world.recipes = target
    return world


# -- fecap.pund ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["fecap.pund"])
def test_pund_card_example_needs_confirmation(recipe_id: str, world: World) -> None:
    world.use_scenario(FECAP)
    validation = world.service().validate_plan(**REQUESTS[recipe_id])
    assert validation.tier == "needs_confirmation" and sorted(validation.confirm_reasons) == UNVERIFIED
    assert validation.resolved is not None and validation.resolved.mode == "sync"
    assert validation.resolved.routes == {"waveform": ["RSU201.OUT->wgfmu", "RSU202.OUT->wgfmu"],
                                          "rest": ["RSU201.OUT->open", "RSU202.OUT->open"]}


@pytest.mark.parametrize("recipe_id", ["fecap.pund"])
def test_pund_gives_pr_ps_ec_within_5_percent_of_the_model(recipe_id: str, world: World) -> None:
    """The WP AC: Pr, Ps, Ec +-5 % (blueprint v2 4.2 ferro FeCap); derived, with method and window (S13)."""
    world.use_scenario(FECAP)
    result = confirmed(world, REQUESTS[recipe_id], reasons=UNVERIFIED)
    found = by_quantity(result.analyses)
    dev = device(world, "dut")
    dev.cycles = 1.0  # the PUND switches the pristine film about one cycle (preset, P, N): its wake-up scale then
    truth = dev.pund_truth(3.0)
    assert found["pr"].value == pytest.approx(truth["pr_uc_cm2"], rel=0.05) and found["pr"].unit == "uC/cm^2"
    assert found["ps"].value == pytest.approx(truth["ps_uc_cm2"], rel=0.05)
    assert found["ec"].value == pytest.approx(truth["ec_mv_cm"], rel=0.05) and found["ec"].unit == "MV/cm"
    for name in ("pr", "ps", "ec"):
        assert found[name].derived and found[name].method == "pund_polarization" and found[name].window is not None
    assert found["c_lin"].value == pytest.approx(dev.c_lin, rel=0.02)
    assert abs(found["v_imprint"].value) < 0.02
    data = load_run(result.run_id, data_root=world.data)
    table = data.table
    assert list(table["event"].unique()) == ["P", "U", "N", "D"] and len(table) == 800
    assert {"top_V", "bottom_V", "bottom_I", "bottom_I_status"} <= set(table.columns)
    assert set(table["bottom_I_status"]) == {"N"} and table["top_V"].abs().max() == pytest.approx(3.0, abs=0.02)
    folder = run_folder(world, result.run_id)
    program = read_program(folder)
    assert program is not None and program.programs["waveform"].spec["builder"] == "pund"
    assert (folder / "raw" / "wgfmu-202-000.npz").is_file()
    assert wgfmu_idle(world, FECAP)


@pytest.mark.parametrize("recipe_id", ["fecap.pund"])
def test_pund_switches_the_film(recipe_id: str, world: World) -> None:
    """Each PUND ends in the negative remanent state and counts about 1.5 cycles."""
    world.use_scenario(FECAP)
    confirmed(world, REQUESTS[recipe_id])
    state = sim_state(world, FECAP).devices["dut"]
    dev = device(world, "dut")
    assert state["cycles"] == pytest.approx(1.5) and state["p"] == pytest.approx(-dev.params.pr_uc_cm2
                                                                                 / dev.params.ps_uc_cm2
                                                                                 * dev.endurance_truth(1.5), rel=0.01)


# -- fefet.fast_program_read -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["fefet.fast_program_read"])
def test_fast_program_read_memory_window_within_10_percent(recipe_id: str, world: World) -> None:
    world.use_scenario(FEFET)
    result = confirmed(world, REQUESTS[recipe_id], reasons=UNVERIFIED, cycles=3)
    found = by_quantity(result.analyses)
    truth = device(world, "wg").memory_window_truth(4.0, -4.0, 1e-6)
    assert found["memory_window"].value == pytest.approx(truth, rel=0.10)
    assert found["memory_window"].fit["cycles"] == 3 and found["vth_initial"].value == pytest.approx(
        found["vth_erase"].value, abs=0.02)  # the pristine film is erased (p_init -1)
    data = load_run(result.run_id, data_root=world.data)
    table = data.table
    assert sorted(table.groupby(["cycle", "phase"]).size().to_dict().items()) == sorted(
        [((0, "read"), 47)] + [((c, p), 47) for c in (1, 2, 3) for p in ("erase", "program")])
    program_rows = table[(table["cycle"] == 1) & (table["phase"] == "program")]
    erase_rows = table[(table["cycle"] == 1) & (table["phase"] == "erase")]
    gap = float(program_rows["t_s"].iloc[0] - erase_rows["t_s"].iloc[-1])
    assert gap < 20e-6  # the program pulse and its read follow the erase read within microseconds
    assert set(table["drain_I_status"]) == {"N"} and wgfmu_idle(world, FEFET)


# -- fecap.endurance_pund --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["fecap.endurance_pund"])
def test_endurance_card_example_is_a_long_async_plan(recipe_id: str, world: World) -> None:
    world.use_scenario(FECAP)
    validation = world.service().validate_plan(**REQUESTS[recipe_id])
    assert validation.tier == "needs_confirmation" and validation.resolved is not None
    assert sorted(validation.confirm_reasons) == ["dut_envelope", "long_run", "soft_pulse", "unverified_pin_map",
                                                  "unverified_topology"]
    assert validation.resolved.mode == "async" and "async ~17 min" in str(validation.summary)
    assert list(validation.resolved.routes) == ["waveform", "rest"]


def pr_truth(dev: Any, cycles: float) -> float:
    """Pr of the model after ``cycles`` bipolar cycles (``pund_truth`` at the wake-up/fatigue scale s(N))."""
    return dev.params.pr_uc_cm2 * dev.endurance_truth(cycles)


@pytest.mark.parametrize("recipe_id", ["fecap.endurance_pund"])
def test_ten_million_cycles_run_async_with_pr_at_every_checkpoint(recipe_id: str, world: World) -> None:
    """The WP AC: endurance PUND async with checkpoints; Pr of every checkpoint within 5 % of the model."""
    world.use_scenario(FECAP)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**REQUESTS[recipe_id])
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running" and started.eta_s is not None and started.eta_s > 600
    result = service.follow_run(started.run_id or "")
    assert result is not None and result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state"
    manifest = assert_async_invariant(world, result.run_id or "", scenario=FECAP)
    progress = progress_of(world, result.run_id or "")
    facts = manifest.kind_result
    assert progress is not None and progress.state == "completed"
    assert progress.done == progress.total == 22 + facts["bursts_planned"]  # one unit per read and per burst
    assert facts["bursts_done"] == facts["bursts_planned"] > 21  # gaps above 10^6 cycles are several bursts
    assert (facts["cycles_done"], facts["burst_cycles_done"], facts["reads_done"]) == (10**7, 10**7 - 22, 22)
    assert facts["source"] == "wgfmu" and facts["wgfmu_read"] == "pund" and not facts["stopped_early"]
    assert sim_state(world, FECAP).devices["dut"]["cycles"] == pytest.approx(10**7, abs=1.0)
    data = load_run(result.run_id or "", data_root=world.data)
    from b1500_test_agent.analysis.pund import pund_polarization

    reads = sorted(data.table["cycle"].unique())
    assert len(reads) == 22 and reads[0] == 1 and reads[-1] == 10**7
    dev = device(world, "dut")
    truths = {n: pr_truth(dev, n - 0.5) for n in reads}  # the read's P pulse: n - 1 cycles plus the preset half
    for n in reads:
        one = data.subset(data.table[data.table["cycle"] == n])
        found = by_quantity(pund_polarization(one))
        assert found["pr"].value == pytest.approx(truths[n], rel=0.05), n
    found = by_quantity(result.analyses)
    top = max(truths.values())
    assert found["wake_up"].value == pytest.approx(top / truths[1] - 1, abs=0.02)
    assert found["fatigue"].value == pytest.approx(1 - truths[10**7] / top, abs=0.02)
    half = next(n for n in np.geomspace(10, 1e7, 4000) if pr_truth(dev, n) < 0.5 * top)
    assert found["cycles_to_failure"].value == pytest.approx(half, rel=0.25)
    assert found["ec"].value == pytest.approx(1.0, rel=0.05)
    assert wgfmu_idle(world, FECAP)
    service.close()


@pytest.mark.parametrize("recipe_id", ["fecap.endurance_pund"])
@pytest.mark.parametrize("k", [1, 6, 20])
def test_endurance_cancel_at_a_checkpoint_leaves_both_buses_clean(k: int, recipe_id: str, world: World,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """An abort seen at checkpoint k cancels there: WGFMU aborted, initialized, disconnected and the session closed,
    the RSUs at rest, the FLEX link relocked, cleanup verified; the reads up to k kept as partial rows."""
    world.use_scenario(FECAP)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**REQUESTS[recipe_id])
    assert validation.resolved is not None and validation.resolved.mode == "async"
    abort_at(monkeypatch, world, k)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and (final.outcome, final.error_code) == ("cancelled", "run_cancelled")
    assert final.cleanup_verified == "sim_state"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and progress.done == k and progress.state == "cancelled"
    manifest = assert_async_invariant(world, final.run_id or "", scenario=FECAP)
    assert manifest.cleanup is not None and manifest.cleanup.verified == "sim_state"
    assert wgfmu_idle(world, FECAP) and partial_rows(world, final.run_id or "") % 800 == 0
    assert partial_rows(world, final.run_id or "") > 0
    switches = manifest.cleanup.switches_after
    assert switches.get("RSU201.OUT") == "open" and switches.get("RSU202.OUT") == "open"
    service.close()


@pytest.mark.wall_clock
@pytest.mark.parametrize("recipe_id", ["fecap.endurance_pund"])
def test_ten_million_cycle_endurance_runs_in_seconds(recipe_id: str, world: World) -> None:
    """Virtual time and bulk cycling: the ~17 min plan (10^7 cycles at 10 kHz plus 22 PUND reads) runs in seconds."""
    world.use_scenario(FECAP)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**REQUESTS[recipe_id])
    t0 = time.monotonic()
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running" and time.monotonic() - t0 < 1.0
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed", final.message
    assert time.monotonic() - t0 < 15.0
    service.close()


# -- the WGFMU path with staircase reads -----------------------------------------------------------------------------


def vths(world: World, run_id: str) -> dict[tuple[int, str], float]:
    data = load_run(run_id, data_root=world.data)
    out: dict[tuple[int, str], float] = {}
    for read in pulse_reads(data, "test"):
        found = vth_constant_current(data.subset(read.rows), x="gate_V", i_crit_a=1e-7)
        assert found.value is not None, found.error
        out[(read.cycle, "read" if read.state == "initial" else read.state)] = found.value
    return out


def test_wgfmu_source_with_staircase_reads_gives_the_memory_window(world: World) -> None:
    with_fixture(world).use_scenario(FEFET)
    result = confirmed(world, WG_READ, reasons=UNVERIFIED, cycles=2)
    found = by_quantity(result.analyses)
    truth = device(world, "wg").memory_window_truth(4.0, -4.0, 1e-6)
    assert found["memory_window"].value == pytest.approx(truth, rel=0.10)
    folder = run_folder(world, result.run_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    facts = manifest["kind_result"]
    assert (facts["executions"], facts["reads_done"], facts["pulse_ops_done"], facts["cycles_done"]) == (9, 5, 4, 2)
    assert manifest["plan"]["program"]["path"] == "wgfmu" and wgfmu_idle(world, FEFET)


def test_wgfmu_grid_points_follow_the_nls_pulse_truth(world: World) -> None:
    with_fixture(world).use_scenario(FEFET)
    result = confirmed(world, WG_READ, schedule="grid", cycles=1, period=1e-4)
    dev = device(world, "wg")
    program = load_run(result.run_id, data_root=world.data).manifest.plan.program
    measured = vths(world, result.run_id)
    for point in program["grid"]:
        dev.cycles = float(point["cycle"])  # about one program/erase cycle per point so far (wake-up scale s(N))
        reset = -dev.scale
        p = dev.pulse_truth(point["level"], point["width"] + 1e-7, p=reset)  # the simulator holds each vertex
        expected = measured[(point["cycle"], "erase")] - dev.params.k_v * (p - reset)  # step at its end level
        assert measured[(point["cycle"], "program")] == pytest.approx(expected, abs=0.02), point


def test_wgfmu_retention_reads_follow_the_log_decay(world: World) -> None:
    with_fixture(world).use_scenario(FEFET)
    result = confirmed(world, WG_READ, schedule="retention", cycles=1, retention_time=100.0, first_read=0.1)
    found = by_quantity(result.analyses)  # memory_window_pulse over the reads
    assert found["memory_window"].value > 0.5
    data = load_run(result.run_id, data_root=world.data)
    program_reads = data.table[data.table["phase"] == "program"]
    times = sorted(set(program_reads["t_s"]))
    assert times[0] == pytest.approx(0.1) and times[-1] == pytest.approx(100.0)
    measured = vths(world, result.run_id)
    dev = device(world, "wg")
    t0 = dev.params.retention_t0_s
    drift = measured[(len(times), "program")] - measured[(1, "program")]
    p_written = dev.pulse_truth(4.0, 1e-6, p=-1.0)
    decades = math.log10(1 + times[-1] / t0) - math.log10(1 + times[0] / t0)
    assert drift == pytest.approx(dev.retention_slope(p_written) * decades, rel=0.10)  # Vth = vth0 - k_v P_w (1 - r lg)
    assert wgfmu_idle(world, FEFET)


@pytest.mark.parametrize("recipe_id", sorted(REQUESTS))
def test_the_recipe_is_sim_validated(recipe_id: str, world: World) -> None:
    listing = {r.id: r for r in world.service().list_recipes(family="nvm").recipes}  # type: ignore[union-attr]
    assert listing[recipe_id].status == "sim_validated", recipe_id
