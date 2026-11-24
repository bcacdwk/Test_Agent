"""Recipe validation of ``wgfmu.rtn`` and ``wgfmu.lfn`` (kind ``wgfmu_waveform``, builder ``dc_sample``) on the
simulator (WP10.5; blueprint v2 10.6 row 10.5, per-recipe AC: tier, run, default analysis vs the 4.2 ``noise``
target). These tests set ``status: sim_validated`` of both recipes.

- ``wgfmu.rtn`` on ``nmos_rtn``: ``rtn_levels`` gives tau_c and tau_e within +-20 % of the trap's truth with at least
  200 transitions and dI/I within +-10 %; the 400,000-row record is archived as ``data.npz`` + ``preview.csv``; the
  frequency-domain view of the same record (``psd_welch``) finds the trap's Lorentzian corner.
- ``wgfmu.lfn`` on ``nmos_rtn``: the lab's channel layout (lwp/1530 ``LFN_noise_meas.cpp``: Fast IV and the 5 V range
  on both channels, channel 1 measures its voltage, channel 2 its current on 100 uA, one event of 504,000 points at
  100 ns averaged over 100 ns on both, readback in 100,000-value chunks) is reproduced call by call; ``psd_welch``
  gives gamma within +-0.1 of the 1/f truth (the trap's Lorentzian is fitted alongside, model ``auto``).
- Plot, short records (warning below 200 transitions), plan limits and an asynchronous record with checkpoints.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.analysis.dataset import NPZ_FILE, PREVIEW_FILE
from b1500_test_agent.archive.runfiles import read_program, read_wgfmu_raw
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.helpers import World
from tests.unit.helpers import REPO_ROOT

pytestmark = pytest.mark.wgfmu

MOSFET = {"pin_map": "mosfet-wgfmu", "dut_profile": "nmos-wgfmu"}
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
VG, VD = 1.0, 0.1


def run_confirmed(service: B1500Service, recipe_id: str, **params: Any) -> tuple[Any, Any]:
    """Validate (the example RSUs are unverified: ``needs_confirmation``), confirm with the plan's own summary as the
    human would, run; the run completes with a verified cleanup."""
    validation = service.validate_plan(recipe_id=recipe_id, **MOSFET, params=params)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    assert validation.confirm_reasons == ["unverified_topology"]
    result = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    assert result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state" and result.quality_verdict == "ok"
    return validation, result


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def truth(world: World) -> dict[str, float]:
    circuit = Circuit(load_config(world.paths).sim_scenario)  # type: ignore[arg-type]
    return circuit.devices["rtn"].truth()  # type: ignore[attr-defined]


def model_id(world: World) -> float:
    dut = Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]
    return float(dut.terminal_currents({"gate": VG, "drain": VD, "source": 0.0, "bulk": 0.0})["drain"])


def run_dir(world: World, run_id: str | None) -> Path:
    return next(p for p in world.runs_dir.rglob(str(run_id)) if p.is_dir())


def wgfmu_calls(folder: Path) -> list[dict[str, Any]]:
    events = [json.loads(line) for line in (folder / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    return [e["data"] for e in events if e["ev"] == "wgfmu_call"]


# -- wgfmu.rtn -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["wgfmu.rtn"])  # the recipe id in the node id: -k wgfmu.rtn
def test_rtn_extracts_the_trap_time_constants_and_step_within_the_targets(recipe_id: str, world: World) -> None:
    """The WP ACs: tau_c, tau_e +-20 % with >= 200 transitions; dI/I +-10 %; the long record archives as npz."""
    world.use_scenario("nmos_rtn")
    service = world.service()
    validation, result = run_confirmed(service, recipe_id)
    assert "drain=WGFMU1:202 via RSU202.OUT dc_sample 0..0.1 V 400000 pts @10 us" in (validation.summary or "")
    assert validation.resolved is not None and validation.resolved.mode == "sync"
    assert result.status_counts == {"N": 400000}
    true = truth(world)
    found = by_quantity(result.analyses)
    tau_c, tau_e = found["tau_c"], found["tau_e"]
    assert tau_c.outcome == tau_e.outcome == "ok" and tau_c.unit == "s" and tau_c.derived
    assert tau_c.value == pytest.approx(true["tau_c_s"], rel=0.2)  # blueprint v2 4.2: +-20 %
    assert tau_e.value == pytest.approx(true["tau_e_s"], rel=0.2)
    assert tau_c.fit["transitions"] >= 200 and tau_c.fit["n"] >= 100 and tau_e.fit["n"] >= 100
    assert found["delta_i_rel"].value == pytest.approx(true["delta_rel"], rel=0.1)  # +-10 %
    assert found["delta_i"].value == pytest.approx(true["delta_rel"] * model_id(world), rel=0.1)
    occupancy = true["tau_e_s"] / (true["tau_c_s"] + true["tau_e_s"])
    assert tau_c.fit["occupancy"] == pytest.approx(occupancy, abs=0.05)
    assert 0.8 <= tau_c.fit["cv"] <= 1.2 and tau_c.fit["separation"] >= 5 and not tau_c.warnings
    stats = by_quantity([r for r in result.analyses if r.method == "it_statistics"])
    assert stats["mean"].value == pytest.approx(model_id(world) * (1 - true["delta_rel"] * occupancy), rel=0.02)
    assert stats["sample_interval"].value == pytest.approx(1e-5) and stats["std"].fit["bimodality"] > 5 / 9
    folder = run_dir(world, result.run_id)
    assert (folder / NPZ_FILE).is_file() and (folder / PREVIEW_FILE).is_file() and not (folder / "data.csv").exists()
    table = load_run(result.run_id or "", data_root=world.data).table
    assert list(table.columns) == ["step", "t_s", "event", "drain_range", "gate_V", "drain_V", "drain_I",
                                   "drain_I_status", "trust"]
    assert set(table["event"]) == {"sample"} and set(table["drain_range"]) == {"100ua"}
    assert set(table["gate_V"]) == {VG} and set(table["drain_V"]) == {VD}  # programmed levels (sources)
    start = 1e-6 + 1e-2  # edge + settle: the event starts on the 10 ns grid, stamps at the window centres
    assert np.allclose(table["t_s"].to_numpy(), start + (np.arange(400000) + 0.5) * 1e-5, rtol=0, atol=1e-12)
    raw = read_wgfmu_raw(folder / "raw" / "wgfmu-202-000.npz")
    assert raw.quantity == "I" and np.array_equal(raw.value, table["drain_I"].to_numpy())
    program = read_program(folder)
    assert program is not None and program.programs["waveform"].spec["builder"] == "dc_sample"
    detail = service.get_run(result.run_id or "", include=["data"])
    assert detail.ok and detail.data is not None and len(detail.data.rows) <= 200
    service.close()


@pytest.mark.parametrize("recipe_id", ["wgfmu.rtn"])  # the recipe id in the node id: -k wgfmu.rtn
def test_the_rtn_record_in_the_frequency_domain_shows_the_trap_corner(recipe_id: str, world: World) -> None:
    """``psd_welch`` on the same record: the Lorentzian corner = (1/tau_c + 1/tau_e) / 2 pi (+-20 %); ``plot_psd``
    stores its PNG under the run's plots/."""
    world.use_scenario("nmos_rtn")
    service = world.service()
    _, result = run_confirmed(service, recipe_id)
    spectrum = service.analyze_run(result.run_id or "", "psd_welch", {})
    assert spectrum.ok, spectrum.message
    found = by_quantity(spectrum.results)
    true = truth(world)
    corner = (1 / true["tau_c_s"] + 1 / true["tau_e_s"]) / (2 * math.pi)
    assert found["gamma"].classification == "power_lorentzian"
    assert found["corner_frequency"].value == pytest.approx(corner, rel=0.2)
    rtn = by_quantity(result.analyses)
    rate = 1 / rtn["tau_c"].value + 1 / rtn["tau_e"].value  # type: ignore[operator]
    assert found["corner_frequency"].fit["tau_rtn_s"] == pytest.approx(1 / rate, rel=0.25)
    plot = service.analyze_run(result.run_id or "", "plot_psd", {})
    assert plot.ok, plot.message
    assert (run_dir(world, result.run_id) / "plots" / "psd-1.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    service.close()


@pytest.mark.parametrize("recipe_id", ["wgfmu.rtn"])  # the recipe id in the node id: -k wgfmu.rtn
def test_a_short_rtn_record_warns_about_its_transitions(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_rtn")
    service = world.service()
    _, result = run_confirmed(service, recipe_id, points=10000)
    tau_c = by_quantity(result.analyses)["tau_c"]
    assert tau_c.outcome == "ok" and tau_c.fit["transitions"] < 200
    assert any("transitions" in w for w in tau_c.warnings)
    folder = run_dir(world, result.run_id)
    assert (folder / "data.csv").is_file() and not (folder / NPZ_FILE).exists()  # <= 200,000 rows stay CSV
    service.close()


# -- wgfmu.lfn -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["wgfmu.lfn"])  # the recipe id in the node id: -k wgfmu.lfn
def test_lfn_reproduces_the_lab_channel_layout(recipe_id: str, world: World) -> None:
    """The WP AC "lwp LFN channel layout (ch1 V, ch2 I) reproduced": the library calls of the run are the lab
    code's ``configure_hw`` + ``build_and_setup`` (with a constant-bias waveform) + chunked export."""
    world.use_scenario("nmos_rtn")
    service = world.service()
    validation, result = run_confirmed(service, recipe_id)
    assert "gate=WGFMU1:201 via RSU201.OUT dc_sample 0..1 V 504000 pts @100 ns" in (validation.summary or "")
    assert result.status_counts == {"N": 1_008_000}
    calls = wgfmu_calls(run_dir(world, result.run_id))
    setup = {(c["fn"], c["ch"]): c.get("mode", c.get("rng")) for c in calls if c["fn"].startswith("set_") and "ch" in c
             and c["fn"] != "set_measure_enabled"}
    assert setup == {("set_operation_mode", 201): "fastiv", ("set_operation_mode", 202): "fastiv",
                     ("set_force_voltage_range", 201): "5v", ("set_force_voltage_range", 202): "5v",
                     ("set_measure_mode", 201): "voltage", ("set_measure_mode", 202): "current",
                     ("set_measure_voltage_range", 201): "5v", ("set_measure_current_range", 202): "100ua"}
    events = [c for c in calls if c["fn"] == "set_measure_event"]
    assert [e["pattern"] for e in events] == ["gate", "drain"]
    assert all((e["points"], e["interval"], e["average"], e["raw"]) == (504000, 1e-7, 1e-7, False) for e in events)
    for ch in (201, 202):
        sizes = [c["size"] for c in calls if c["fn"] == "measure_values" and c["ch"] == ch]
        assert sizes == [100_000] * 5 + [4_000]  # the lab's 100,000-value chunks
    table = load_run(result.run_id or "", data_root=world.data).table
    assert list(table.columns) == ["step", "t_s", "event", "drain_range", "gate_V", "gate_V_status", "drain_V",
                                   "drain_I", "drain_I_status", "trust"]  # ch1 voltage measured, ch2 current
    assert table["gate_V"].to_numpy() == pytest.approx(VG) and set(table["gate_V_status"]) == {"N"}
    assert table["drain_I"].mean() == pytest.approx(model_id(world), rel=0.05)
    folder = run_dir(world, result.run_id)
    assert {p.name for p in (folder / "raw").iterdir()} == {"wgfmu-201-000.npz", "wgfmu-202-000.npz"}
    assert (folder / NPZ_FILE).is_file()
    service.close()


@pytest.mark.parametrize("recipe_id", ["wgfmu.lfn"])  # the recipe id in the node id: -k wgfmu.lfn
def test_lfn_gamma_within_the_target(recipe_id: str, world: World) -> None:
    """The WP AC gamma +-0.1: the default analysis of the lab-shaped record (20 Hz .. 5 MHz; fit 270 Hz .. 1 MHz)
    separates the trap's Lorentzian from the 1/f part."""
    world.use_scenario("nmos_rtn")
    service = world.service()
    _, result = run_confirmed(service, recipe_id)
    found = by_quantity(result.analyses)
    true = truth(world)
    gamma = found["gamma"]
    assert gamma.outcome == "ok" and gamma.derived and gamma.method == "psd_welch"
    assert gamma.value == pytest.approx(true["gamma"], abs=0.1)  # blueprint v2 4.2
    assert gamma.classification == "power_lorentzian" and gamma.window is not None and gamma.window.unit == "Hz"
    assert gamma.window.low < 500 and gamma.window.high > 5e5
    mean = found["gamma"].fit["mean"]
    assert found["flicker_norm_1hz"].value == pytest.approx(true["flicker_k"] * (model_id(world) / mean) ** 2,
                                                            rel=0.5)
    corner = (1 / true["tau_c_s"] + 1 / true["tau_e_s"]) / (2 * math.pi)
    assert found["corner_frequency"].value == pytest.approx(corner, rel=0.35)
    assert found["psd_at_f_ref"].unit == "A^2/Hz" and found["psd_at_f_ref"].fit["f_ref_hz"] == 1000.0
    assert found["norm_psd_at_f_ref"].value == pytest.approx(found["psd_at_f_ref"].value / mean**2, rel=1e-5)
    referred = service.analyze_run(result.run_id or "", "psd_welch", {"gm_s": 5e-5})
    assert referred.ok
    input_noise = by_quantity(referred.results)["input_noise_at_f_ref"]
    assert input_noise.unit == "V^2/Hz"
    assert input_noise.value == pytest.approx(found["psd_at_f_ref"].value / 5e-5**2, rel=1e-5)
    service.close()


# -- plan limits and long records ------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["wgfmu.rtn", "wgfmu.lfn"])
def test_noise_plans_outside_the_module_limits_are_blocked(recipe_id: str, world: World) -> None:
    world.use_scenario("nmos_rtn")
    service = world.service()
    too_many = service.validate_plan(recipe_id=recipe_id, **MOSFET, params={"points": 4_000_001})
    assert too_many.tier == "blocked"
    assert any(f.rule_id == "R-WG-02" and "4000001 stored values" in f.message for f in too_many.findings)
    interval = float(REGISTRY.get(recipe_id).params["interval"].default)  # type: ignore[arg-type]
    averaging = service.validate_plan(recipe_id=recipe_id, **MOSFET, params={"average": 2 * interval})
    assert averaging.tier == "blocked"
    assert any(f.rule_id == "R-WG-02" and "error 3316" in f.message for f in averaging.findings)
    out_of_range = service.validate_plan(recipe_id=recipe_id, **MOSFET, params={"vrange": "3v", "vg": 4.0})
    assert not out_of_range.ok and "do not fit its force range 3v" in out_of_range.message
    assert world.run_dirs() == []
    service.close()


@pytest.mark.parametrize("recipe_id", ["wgfmu.rtn"])  # the recipe id in the node id: -k wgfmu.rtn
def test_a_long_rtn_record_runs_asynchronously_with_checkpoints(recipe_id: str, world: World) -> None:
    """40,000 points at 10 ms = 400 s of sequencer time: above ``max_sync_run_s`` (asynchronous), checkpoints every
    10 s of sequencer time and one for the readback. (Sparse on purpose: the simulator steps the dynamic ``mosfet``
    model point by point when a record is evaluated in poll-sized chunks; 10 ms sampling cannot resolve this trap,
    so ``rtn_levels`` is not asserted here.)"""
    world.use_scenario("nmos_rtn")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(recipe_id=recipe_id, **MOSFET, params={"interval": 1e-2, "points": 40000})
    assert validation.resolved is not None and validation.resolved.mode == "async"
    assert validation.confirm_reasons == ["unverified_topology"]
    started = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    assert started.ok and started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed" and final.cleanup_verified == "sim_state"
    assert final.status_counts == {"N": 40000}
    progress = service.get_run(final.run_id or "", include=["progress"]).progress
    assert progress is not None and progress.state == "completed" and progress.done == progress.total == 42
    service.close()
