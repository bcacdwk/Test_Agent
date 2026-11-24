"""Recipe validation of the ``pulse_read`` schedules of WP9.5 on the simulator (blueprint v2 10.5 row 9.5; per-recipe
AC: tier, run, default analysis vs the 4.2 fidelity target). These tests set ``status: sim_validated`` of
``fefet.switching_kinetics``, ``fefet.endurance`` and ``fefet.retention`` (scenario ``fefet_lab``: NLS kinetics,
retention loss and wake-up/fatigue of the lab FeFET).

- ``fefet.switching_kinetics``: the card example needs confirmation (unverified pin map and topology); the confirmed run
  wakes the film up (bipolar pre-cycles), resets and pulses the gate once per amplitude x width point through
  SEL1.OUT1 -> PGU and reads it through -> SMU; ``switching_kinetics_fit`` returns tau0 and beta within 20 % of the
  model truth (``tau0_s``, ``beta_sw``; 4.2 ``ferro``). ISPP reads follow the cumulative NLS model.
- ``fefet.endurance``: 10^6 program/erase cycles run asynchronously (bipolar three-level SPGU bursts between log-spaced
  checkpoints), the memory window of every checkpoint within 10 % of the model's wake-up/fatigue truth, and cancel at
  a checkpoint inside a burst or after a read leaves the SPGU stopped and the selector at rest.
- ``fefet.retention``: each state is written once and read at log times while the SMUs hold the gate at 0 V
  (instrument-timed holds); the retention slope of each state is within 10 % of the model truth ``k_v P_w
  retention_rate`` (and the window's slope likewise); cancel inside a hold.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.analysis import load_run, pulse_reads, vth_constant_current
from b1500_test_agent.catalog.kinds.pulse_read import stored_program
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.async_helpers import assert_async_invariant, manifest_of, partial_rows, progress_of
from tests.integration.helpers import World
from tests.integration.test_async_cancel import abort_at
from tests.sim.pulse_read_helpers import AT_REST, BASE, SCENARIO, fresh_fefet

pytestmark = pytest.mark.spgu

KINETICS = {"recipe_id": "fefet.switching_kinetics", **BASE}
ENDURANCE = {"recipe_id": "fefet.endurance", **BASE}
RETENTION = {"recipe_id": "fefet.retention", **BASE}
SER_GAIN = (1e6 + 50) / 1e6
"""Open-load gain of the 1 MOhm SER setting at the insulated gate (the level the FeFET sees)."""


def confirmed(world: World, request: dict[str, Any], **params: Any) -> tuple[Any, Any]:
    service = world.service()
    validation = service.validate_plan(**request, params=params)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    result = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    if result.outcome == "running":
        result = service.follow_run(result.run_id or "")
    return validation, result


def manifest(world: World, run_id: str) -> dict[str, Any]:
    folder = next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def sim_device_state(world: World) -> dict[str, float]:
    state = load_state_file(sim_state_file(world.state_dir, SCENARIO))
    assert state is not None
    return dict(state.devices["dut"])


def selector_ports(world: World) -> dict[int, int]:
    state = load_state_file(sim_state_file(world.state_dir, SCENARIO))
    assert state is not None
    return {port: state.selector_ports.get(port, 0) for port in range(4)}


def by_quantity(results: list[Any]) -> dict[str, Any]:
    return {r.quantity: r for r in results}


def route_log(entry: str) -> list[tuple[str, str, str]]:
    return [tuple(item.split(" ", 2)) for item in entry.split("; ")]  # type: ignore[misc]


def read_vths(world: World, run_id: str) -> dict[tuple[int, str], float]:
    """Constant-current Vth (100 nA) of every read of a run, by ``(cycle, phase)``."""
    data = load_run(run_id, data_root=world.data)
    out: dict[tuple[int, str], float] = {}
    for read in pulse_reads(data, "test"):
        found = vth_constant_current(data.subset(read.rows), x="gate_read_V", i_crit_a=1e-7)
        assert found.value is not None, found.error
        out[(read.cycle, "read" if read.state == "initial" else read.state)] = found.value
    return out


# -- fefet.switching_kinetics ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["fefet.switching_kinetics"])
def test_kinetics_card_example_needs_confirmation_with_its_routes(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**KINETICS)
    assert validation.tier == "needs_confirmation" and validation.resolved is not None
    assert sorted(validation.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    assert validation.resolved.mode == "sync" and validation.resolved.routes == {
        "cycling": ["SEL1.OUT1->pgu"], "erase": ["SEL1.OUT1->pgu"], "program": ["SEL1.OUT1->pgu"],
        "read": ["SEL1.OUT1->smu"], "rest": ["SEL1.OUT1->open"]}
    assert "pulse 0->-4..4.8 V 10 ns..100 us x1110" in str(validation.summary)
    assert not sim_state_file(world.state_dir, SCENARIO).exists()


@pytest.mark.parametrize("recipe_id", ["fefet.switching_kinetics"])
def test_switching_kinetics_fit_matches_the_nls_truth(recipe_id: str, world: World) -> None:
    """The WP9.5 AC: tau0 and beta of the NLS fit within 20 % of the model's tau0_s and beta_sw."""
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, KINETICS)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("sim", True, "sim_state")
    assert result.status_counts == {"N": 111 * 47 * 2}
    truth = fresh_fefet().params
    found = by_quantity(result.analyses)
    assert list(found) == ["tau0", "beta", "va", "vth_reset"]
    assert found["tau0"].value == pytest.approx(truth.tau0_s, rel=0.20) and found["tau0"].unit == "s"
    assert found["beta"].value == pytest.approx(truth.beta_sw, rel=0.20)
    assert found["va"].value == pytest.approx(truth.va_v, rel=0.05) and found["tau0"].fit["r2"] > 0.999
    assert found["tau0"].derived and found["vth_reset"].fit["std"] < 0.005  # every reset reaches the same state
    data = manifest(world, str(result.run_id))
    facts = data["kind_result"]
    assert (facts["schedule"], facts["grid_points_done"], facts["reads_done"], facts["pulse_ops_done"]) == (
        "grid", 55, 111, 110)
    assert (facts["bursts_done"], facts["burst_cycles_done"], facts["cycles_done"]) == (1, 1000, 1000)
    log = route_log(facts["routes"])
    assert log[:3] == [("start", "read", "SEL1.OUT1->smu"), ("c0", "cycling", "SEL1.OUT1->pgu"),
                       ("c0", "read", "SEL1.OUT1->smu")]
    assert [(w, p) for w, p, _ in log[3:7]] == [("c1", "erase"), ("c1", "read"), ("c1", "program"), ("c1", "read")]
    assert log[-1] == ("end", "rest", "SEL1.OUT1->open") and selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    assert {t: s for t, s in data["cleanup"]["switches_after"].items() if t.startswith("SEL")} == AT_REST
    assert any("grid point" in line for line in data["assumptions"])
    table = load_run(str(result.run_id), data_root=world.data).table
    assert "t_s" not in table.columns and table["cycle"].max() == 55
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    assert "SPM 101,3" in sent and sent.count("SRP") == 1 + 110  # the pre-cycle burst, then every reset and point


@pytest.mark.parametrize("recipe_id", ["fefet.switching_kinetics"])
def test_ispp_steps_follow_the_cumulative_switching_model(recipe_id: str, world: World) -> None:
    """ISPP (one reset and reset read per width, amplitudes cumulatively): each step's Vth change from the previous
    read equals the model's cumulative NLS step (same device, same pulses, the reads' disturb at their sweep ends)
    within 5 mV; the first step of a row within 15 mV (the reset read measures the saturated state at its Vth crossing
    and then nudges it at the 1.8 V end of its sweep: about 10 mV of read disturb); ``v50`` lies inside the amplitude
    range."""
    world.use_scenario(SCENARIO)
    amps, widths = [3.0, 3.3, 3.6, 3.9, 4.2], [1e-7, 1e-6]
    _, result = confirmed(world, KINETICS, grid_mode="ispp", amplitudes=amps, widths=widths, precycles=0,
                          initial_read=False)
    assert result.ok and result.outcome == "completed", result.message
    found = by_quantity(result.analyses)
    assert list(found) == ["v50", "ispp_slope", "vth_reset"] and 3.0 <= found["v50"].value <= 4.2
    assert found["v50"].fit["rows"] == 2 and found["ispp_slope"].value > 0
    vth = read_vths(world, str(result.run_id))
    device = fresh_fefet()
    k_v, p = device.params.k_v, device.p

    def read(p_now: float) -> float:  # a read sweeps -0.5 -> 1.8 V: the polarization is clamped into both bands
        return device.polarization_after(1.8, device.polarization_after(-0.5, p_now))

    for row, width in enumerate(widths):
        first = row * len(amps) + 1
        p = read(device.pulse_truth(-4.0 * SER_GAIN, 1e-6, p))
        previous, before = p, vth[(first, "erase")]
        for step, amp in enumerate(amps):
            p = read(device.pulse_truth(amp * SER_GAIN, width, p))
            measured = vth[(first + step, "program")]
            tolerance = 0.015 if step == 0 else 0.005
            assert measured - before == pytest.approx(-k_v * (p - previous), abs=tolerance), (row, amp)
            previous, before = p, measured


@pytest.mark.parametrize("k", [1, 4, 9])
@pytest.mark.parametrize("recipe_id", ["fefet.switching_kinetics"])
def test_kinetics_cancel_returns_the_selector_to_rest(recipe_id: str, k: int, world: World,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Checkpoints: the pre-cycle burst (1), the reference read (2), then reset/read/pulse/read per point."""
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**KINETICS)
    abort_at(monkeypatch, world, k)
    result = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    if result.outcome == "running":
        result = service.follow_run(result.run_id or "")  # type: ignore[assignment]
    assert result is not None and (result.outcome, result.error_code) == ("cancelled", "run_cancelled")
    assert result.cleanup_verified == "sim_state" and selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    assert partial_rows(world, result.run_id or "") == 47 * {1: 0, 4: 2, 9: 4}[k]
    data = assert_async_invariant(world, result.run_id or "", scenario=SCENARIO)
    assert data.cleanup is not None and data.cleanup.verified == "sim_state"
    service.close()


# -- fefet.endurance -------------------------------------------------------------------------------------------------


def window_truth(device: FefetDevice, cycles: float) -> float:
    """``memory_window_truth`` of the card's pulses after ``cycles`` bipolar cycles (wake-up/fatigue scale)."""
    device.cycles = float(cycles)
    return device.memory_window_truth(4.0 * SER_GAIN, -4.0 * SER_GAIN, 1e-6)


@pytest.mark.parametrize("recipe_id", ["fefet.endurance"])
def test_endurance_card_example_is_a_long_async_plan(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**ENDURANCE)
    assert validation.tier == "needs_confirmation" and validation.resolved is not None
    assert sorted(validation.confirm_reasons) == ["dut_envelope", "long_run", "soft_pulse", "unverified_pin_map",
                                                  "unverified_topology"]
    assert validation.resolved.mode == "async" and "async ~18 min" in str(validation.summary)
    assert list(validation.resolved.routes) == ["cycling", "erase", "program", "read", "rest"]


@pytest.mark.parametrize("recipe_id", ["fefet.endurance"])
def test_a_million_cycles_run_async_and_follow_wake_up_and_fatigue(recipe_id: str, world: World) -> None:
    """The WP9.5 AC: 10^6-cycle endurance async with checkpoints; MW of every checkpoint within 10 % of the model."""
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**ENDURANCE)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running" and started.eta_s is not None and started.eta_s > 600
    result = service.follow_run(started.run_id or "")
    assert result is not None and result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state"
    data = assert_async_invariant(world, result.run_id or "", scenario=SCENARIO)
    progress = progress_of(world, result.run_id or "")
    assert progress is not None and progress.done == progress.total and progress.state == "completed"
    assert progress.total > 39 + 2 * 19  # reads, operations and the burst checkpoints (every 10 s of output)
    facts = data.kind_result
    assert (facts["cycles_done"], facts["burst_cycles_done"], facts["checkpoints_planned"]) == (10**6, 10**6 - 19, 19)
    assert facts["reads_done"] == 39 and not facts["stopped_early"] and facts["spp_fallbacks"] == 0
    assert sim_device_state(world)["cycles"] == pytest.approx(10**6, abs=1.0)
    vth = read_vths(world, result.run_id or "")
    device = fresh_fefet()
    checkpoints = sorted({c for c, p in vth if c > 0})
    assert len(checkpoints) == 19 and checkpoints[-1] == 10**6
    for n in checkpoints:
        window = vth[(n, "erase")] - vth[(n, "program")]
        assert window == pytest.approx(window_truth(device, n), rel=0.10), n
    found = by_quantity(result.analyses)
    assert found["memory_window_final"].value == pytest.approx(window_truth(device, 10**6), rel=0.10)
    scales = [device.endurance_truth(n) for n in checkpoints]
    assert found["wake_up"].value == pytest.approx(max(scales) / scales[0] - 1, abs=0.02)
    assert found["fatigue"].value == pytest.approx(1 - scales[-1] / max(scales), abs=0.02)
    half = next(n for n in np.geomspace(10, 1e6, 2000) if device.endurance_truth(n) < 0.5 * max(scales))
    assert found["cycles_to_failure"].value == pytest.approx(half, rel=0.25)
    log = route_log(facts["routes"])
    assert sum(1 for _, phase, _ in log if phase == "cycling") == facts["bursts_done"] == facts["bursts_planned"]
    assert log[-1] == ("end", "rest", "SEL1.OUT1->open") and selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    service.close()


@pytest.mark.parametrize("k", [3, 12, 40])
@pytest.mark.parametrize("recipe_id", ["fefet.endurance"])
def test_endurance_cancel_inside_a_burst_stops_the_spgu(recipe_id: str, k: int, world: World,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """An abort seen at checkpoint k (a read, or the 10 s chunks of a long burst) cancels there: SPGU stopped, outputs
    off, selector at rest, cleanup verified, the reads up to k kept as partial rows."""
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**ENDURANCE)
    assert validation.resolved is not None and validation.resolved.mode == "async"
    abort_at(monkeypatch, world, k)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and (final.outcome, final.error_code) == ("cancelled", "run_cancelled")
    assert final.cleanup_verified == "sim_state"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and progress.done == k and progress.state == "cancelled"
    data = assert_async_invariant(world, final.run_id or "", scenario=SCENARIO)
    assert data.cleanup is not None and "spgu_stop" in [s.step for s in data.cleanup.steps]
    assert selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    assert partial_rows(world, final.run_id or "") % 47 == 0
    service.close()


@pytest.mark.wall_clock
@pytest.mark.parametrize("recipe_id", ["fefet.endurance"])
def test_a_million_cycle_endurance_runs_in_seconds(recipe_id: str, world: World) -> None:
    """Virtual time: the ~18 min plan (10^6 cycles at 1 kHz plus 39 reads) runs in seconds of wall time."""
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**ENDURANCE)
    t0 = time.monotonic()
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running" and time.monotonic() - t0 < 1.0
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed", final.message
    assert time.monotonic() - t0 < 15.0
    service.close()


# -- fefet.retention -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["fefet.retention"])
def test_retention_card_example_is_a_long_async_plan(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**RETENTION)
    assert validation.tier == "needs_confirmation" and validation.resolved is not None
    assert sorted(validation.confirm_reasons) == ["long_run", "unverified_pin_map", "unverified_topology"]
    assert validation.resolved.mode == "async" and "async ~5.7 h" in str(validation.summary)


@pytest.mark.parametrize("recipe_id", ["fefet.retention"])
def test_retention_slopes_match_the_log_decay_truth(recipe_id: str, world: World) -> None:
    """The WP9.5 AC: the retention slope of each state within 10 % of k_v P_w retention_rate (V/decade)."""
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, RETENTION)
    assert result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state" and set(result.status_counts) == {"N"}
    device = fresh_fefet()
    rate, k_v = device.params.retention_rate, device.params.k_v
    p_program = device.pulse_truth(4.0 * SER_GAIN, 1e-6, device.polarization_after(1.8))
    device.cycles = 0.5
    p_erase = device.pulse_truth(-4.0 * SER_GAIN, 1e-6, device.retention_truth(p_program, 1e4))
    found = by_quantity(result.analyses)
    assert list(found) == ["retention_slope_program", "retention_slope_erase", "memory_window_slope",
                           "memory_window_at_target", "retention_time"]
    assert found["retention_slope_program"].value == pytest.approx(device.retention_slope(p_program), rel=0.10)
    assert found["retention_slope_erase"].value == pytest.approx(device.retention_slope(p_erase), rel=0.10)
    assert found["retention_slope_program"].value == pytest.approx(k_v * p_program * rate, rel=0.10)
    assert found["memory_window_slope"].value == pytest.approx(-k_v * rate * (p_program - p_erase), rel=0.10)
    assert found["memory_window_slope"].unit == "V/dec" and found["memory_window_at_target"].warnings
    data = manifest(world, str(result.run_id))
    facts = data["kind_result"]
    assert (facts["schedule"], facts["reads_done"], facts["retention_s_planned"]) == ("retention", 27, 10000.0)
    planned = manifest_of(world, str(result.run_id))
    assert planned is not None
    holds = [s for s in stored_program(planned.plan)[0].steps() if s.action == "hold"]
    assert facts["held_s"] == pytest.approx(2e4) and facts["hold_blocks"] == sum(s.chunks for s in holds) == 816
    assert data["plan"]["mode"] == "async" and any("retention" in line for line in data["assumptions"])
    table = load_run(str(result.run_id), data_root=world.data).table
    assert list(table.columns[:4]) == ["step", "t_s", "cycle", "phase"]
    assert math.isnan(table["t_s"].iloc[0]) and table.loc[table["phase"] == "erase", "t_s"].max() == 1e4
    assert selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}


@pytest.mark.parametrize("recipe_id", ["fefet.retention"])
def test_retention_cancel_inside_a_hold_rests(recipe_id: str, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**RETENTION, params={"retention_time": 1000.0})
    abort_at(monkeypatch, world, 30)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    final = service.follow_run(started.run_id or "") if started.outcome == "running" else started
    assert final is not None and (final.outcome, final.error_code) == ("cancelled", "run_cancelled")
    assert final.cleanup_verified == "sim_state" and selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    manifest_data = manifest_of(world, final.run_id or "")
    assert manifest_data is not None and manifest_data.outcome == "cancelled"
    service.close()


def test_the_three_recipes_are_sim_validated(world: World) -> None:
    listing = world.service().list_recipes(family="nvm")
    status = {r.id: r.status for r in listing.recipes}
    assert {status[r] for r in ("fefet.switching_kinetics", "fefet.endurance", "fefet.retention")} == {
        "sim_validated"}

