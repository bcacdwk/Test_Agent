"""Recipe validation of kind ``wgfmu_waveform`` on the simulator (WP10.4; blueprint v2 10.6 row 10.4, per-recipe AC:
tier, run, default analysis vs the 4.2 target). These tests set ``status: sim_validated`` of ``wgfmu.pulsed_iv``,
``wgfmu.fast_iv``, ``wgfmu.pulse_train``, ``wgfmu.custom_waveform`` and ``wgfmu.dc_spot``.

- Pulsed Id at low duty = DC Id +-2 % (the WP AC): ``wgfmu.pulsed_iv`` (1 % duty) against a DC ``mosfet.idvg`` on pin
  map ``mosfet-4t``, which reaches the same simulated transistor through the RSUs' SMU inputs (scenario
  ``nmos_wgfmu``); ``pulsed_vs_dc``; and each plateau against the model's quasi-static current.
- A lab-shaped table of 1,825 rows with one 504,000-point event (the lab's LFN layout, synthetic levels) from
  ``work/waveforms/`` runs, needs ``adhoc_recipe``, and is archived as ``data.npz`` + ``preview.csv`` with the raw
  readback ``raw/wgfmu-<ch>-000.npz`` and ``program.json`` (the WP ACs); a CSV changed after validation makes the
  run ``plan_stale``.
- WGFMU engine targets (4.2): event timing exact on the 10 ns grid, point counts exact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.analysis.dataset import NPZ_FILE, PREVIEW_FILE
from b1500_test_agent.archive.runfiles import read_program, read_wgfmu_raw
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.helpers import World

pytestmark = pytest.mark.wgfmu

MOSFET = {"pin_map": "mosfet-wgfmu", "dut_profile": "nmos-wgfmu"}
BODY = {"pin_map": "mosfet-wgfmu-body", "dut_profile": "nmos-wgfmu"}
DC_IDVG = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "dut_profile": "nmos-wgfmu"}
RESISTOR = {"recipe_id": "wgfmu.dc_spot", "pin_map": "resistor-wgfmu", "dut_profile": "resistor-generic"}
R_TRUE = 1.0e5


def validate(service: B1500Service, recipe_id: str, request: dict[str, Any], **params: Any) -> Any:
    validation = service.validate_plan(recipe_id=recipe_id, **request, params=params)
    assert validation.ok and validation.plan_id is not None, validation.message
    return validation


def run_confirmed(service: B1500Service, recipe_id: str, request: dict[str, Any], *,
                  reasons: set[str] = frozenset({"unverified_topology"}), **params: Any) -> tuple[Any, Any]:
    """Validate (the example RSUs are unverified: ``needs_confirmation``), confirm with the plan's own summary as
    the human would, run; the run completes with a verified cleanup."""
    validation = validate(service, recipe_id, request, **params)
    assert validation.tier == "needs_confirmation" and set(validation.confirm_reasons) == set(reasons), validation
    result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state" and result.quality_verdict == "ok"
    return validation, result


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def device(world: World) -> Any:
    return Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]


def model_id(dut: Any, vg: float, vd: float) -> float:
    return dut.terminal_currents({"gate": vg, "drain": vd, "source": 0.0, "bulk": 0.0})["drain"]


def run_dir(world: World, run_id: str | None) -> Path:
    return next(p for p in world.runs_dir.rglob(str(run_id)) if p.is_dir())


# -- wgfmu.pulsed_iv -------------------------------------------------------------------------------------------------


def test_pulsed_iv_at_low_duty_equals_the_dc_id(world: World) -> None:
    """The WP AC: pulsed Id (10 us at 1 % duty) = DC Id +-2 % at every gate level above 1 % of the largest current."""
    world.use_scenario("nmos_wgfmu")
    service = world.service()
    dc_plan = validate(service, "mosfet.idvg", {k: v for k, v in DC_IDVG.items() if k != "recipe_id"}, vd=1.0,
                       vg_start=0.0, vg_stop=2.0, vg_points=21, icomp_drain=1e-3)
    dc = service.run_plan(dc_plan.plan_id)
    assert dc.ok and dc.outcome == "completed", dc.message
    validation, pulsed = run_confirmed(service, "wgfmu.pulsed_iv", MOSFET)
    assert validation.resolved is not None and validation.resolved.mode == "sync" and validation.resolved.points == 21
    assert "pulse 0->0..2 V 10 us x21 @1 kHz" in (validation.summary or "")
    assert pulsed.status_counts == {"N": 21}
    defaults = by_quantity(pulsed.analyses)
    dut = device(world)
    assert defaults["plateau_current"].value == pytest.approx(model_id(dut, 2.0, 1.0), rel=0.01)
    assert defaults["plateau_current"].fit["level_v"] == 2.0 and defaults["gm_max"].outcome == "ok"
    compared = service.analyze_run(pulsed.run_id or "", "pulsed_vs_dc", {"reference_run": dc.run_id})
    assert compared.ok, compared.message
    found = by_quantity(compared.results)
    assert found["max_rel_difference"].value <= 0.02  # blueprint 10.6 row 10.4: +-2 %
    assert found["pulsed_over_dc"].value == pytest.approx(1.0, abs=0.02)
    data = load_run(pulsed.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "t_s", "cycle", "event", "drain_range", "gate_V", "drain_V", "drain_I",
                                        "drain_I_status", "trust"]
    expected = [model_id(dut, vg, 1.0) for vg in data.table["gate_V"]]
    assert data.table["drain_I"].to_numpy() == pytest.approx(expected, rel=0.02, abs=2e-8)
    starts = data.table["t_s"].to_numpy() - 4e-6  # plateau window centre - half its 8 us average
    assert np.allclose(np.diff(starts), 1e-3, rtol=0, atol=1e-12)  # one point per period, exact on the grid
    service.close()


def test_pulsed_iv_with_an_smu_body_bias(world: World) -> None:
    """The kind's optional FLEX SMU bias: the bulk on SMU5 is switched on and biased before the WGFMU phase, held
    through it and switched off by the cleanup; a negative body bias raises Vth (less Id)."""
    world.use_scenario("nmos_wgfmu")
    service = world.service()
    _, flat = run_confirmed(service, "wgfmu.pulsed_iv", MOSFET, vg_points=5)
    validation, biased = run_confirmed(service, "wgfmu.pulsed_iv", BODY, vg_points=5, vb=-0.5)
    assert "bulk=SMU5(MPSMU) bias -0.5 V Icomp 100 uA" in (validation.summary or "")
    top = by_quantity(biased.analyses)["plateau_current"].value
    assert top is not None and top < by_quantity(flat.analyses)["plateau_current"].value * 0.95
    log = [r.command for r in world.sim_log("nmos_wgfmu") if r.outcome == "ok"]
    assert "CN 5" in log and "DV 5,0,-0.5,0.0001" in log
    assert log.index("DV 5,0,-0.5,0.0001") < len(log) - 1 - log[::-1].index("DZ")  # bias before the cleanup
    service.close()


def test_pulsed_iv_needs_its_rsu_and_a_pulse_envelope(world: World) -> None:
    world.use_scenario("nmos_wgfmu")
    world.write_config("pinmaps/direct.yaml", {"description": "WGFMU channels named directly", "certainty": "verified",
                                               "terminals": {"gate": 201, "drain": 202, "source": "GNDU"}})
    service = world.service()
    direct = service.validate_plan(recipe_id="wgfmu.pulsed_iv", pin_map="direct", dut_profile="nmos-wgfmu")
    assert direct.tier == "blocked" and "R-WG-01" in {f.rule_id for f in direct.findings if f.severity == "block"}
    no_pulse = service.validate_plan(recipe_id="wgfmu.pulsed_iv", pin_map="mosfet-wgfmu", dut_profile="nmos-generic")
    assert no_pulse.tier == "blocked"
    assert "R-PULSE-02" in {f.rule_id for f in no_pulse.findings if f.severity == "block"}
    service.close()


# -- wgfmu.fast_iv and wgfmu.pulse_train -----------------------------------------------------------------------------


def test_fast_iv_up_and_down_ramps_follow_the_quasi_static_curve(world: World) -> None:
    world.use_scenario("nmos_wgfmu")
    service = world.service()
    _, result = run_confirmed(service, "wgfmu.fast_iv", MOSFET)
    assert result.status_counts == {"N": 200}
    data = load_run(result.run_id or "", data_root=world.data)
    table = data.table
    assert list(table["segment"].unique()) == ["fwd", "rev"] and (table["segment"] == "fwd").sum() == 100
    dut = device(world)
    # each point averages one 100 ns interval of the ramp: its current lies between those at the interval's ends
    slope = 2.0 / 1e-5 * np.where(table["segment"] == "fwd", 1.0, -1.0)
    ends = [np.asarray([model_id(dut, vg, 1.0) for vg in table["gate_V"] + k * slope * 5e-8]) for k in (-1, 1)]
    low, high = np.minimum(*ends), np.maximum(*ends)
    measured = table["drain_I"].to_numpy()
    noise = 5 * 2e-6 * (1e-3 / 1e-2) / np.sqrt(20) + 2e-3 * np.abs(high)  # 5 sigma: floor (1 mA, 20 samples) + rel
    assert np.all(measured >= low - noise) and np.all(measured <= high + noise)
    gm = by_quantity(result.analyses)["gm_max"]
    vg = np.linspace(0.0, 2.0, 2001)
    model_gm = np.max(np.gradient([model_id(dut, v, 1.0) for v in vg], vg))
    assert gm.value == pytest.approx(model_gm, rel=0.02)
    assert np.allclose(np.diff(table["t_s"].to_numpy()[:100]), 1e-7, rtol=0, atol=1e-12)
    service.close()


def test_pulse_train_reads_every_pulse_plateau(world: World) -> None:
    world.use_scenario("nmos_wgfmu")
    service = world.service()
    validation, result = run_confirmed(service, "wgfmu.pulse_train", MOSFET, count=50, samples=5)
    assert "pulse 0->2 V 10 us x50 @10 kHz" in (validation.summary or "")
    assert result.status_counts == {"N": 250}
    table = load_run(result.run_id or "", data_root=world.data).table
    assert sorted(table["cycle"].unique()) == list(range(50)) and set(table["event"]) == {"pulse"}
    expected = model_id(device(world), 2.0, 1.0)
    plateau = by_quantity(result.analyses)["plateau_current"]
    assert plateau.value == pytest.approx(expected, rel=0.01) and plateau.fit["pulses"] == 50
    first = service.analyze_run(result.run_id or "", "pulse_plateau", {"x": "gate_V", "y": "drain_I", "pulse": 0})
    assert first.ok and first.results[0].value == pytest.approx(expected, rel=0.01)
    periods = np.diff(table["t_s"].to_numpy().reshape(50, 5)[:, 0])
    assert np.allclose(periods, 1e-4, rtol=0, atol=1e-12)  # one pattern per period, no gap inside the sequence
    service.close()


def test_pulse_train_in_pg_mode_reads_the_same_plateaus(world: World) -> None:
    """``gate_mode: pg`` (WP11.2, blueprint v2 1.2 WGFMU "PG mode"): the gate channel runs in PG mode (50 Ohm output,
    no measurement, a 5 V range at most); on the insulated gate the open-load level reaches the DUT, so every plateau
    current is the model's Id at the peak as in Fast IV mode."""
    world.use_scenario("nmos_wgfmu")
    service = world.service()
    validation, result = run_confirmed(service, "wgfmu.pulse_train", MOSFET, count=20, samples=5, gate_mode="pg")
    assert result.ok and result.status_counts == {"N": 100} and "pulse 0->2 V" in (validation.summary or "")
    program = read_program(run_dir(world, result.run_id))
    assert program is not None
    channels = program.programs["waveform"].spec["channels"]
    assert isinstance(channels, dict)
    assert {ch: setup["mode"] for ch, setup in channels.items()} == {"201": "pg", "202": "fastiv"}  # type: ignore[index]
    assert channels["201"]["force_range"] == "3v" and not channels["201"]["measure_enabled"]  # type: ignore[index]
    plateau = by_quantity(result.analyses)["plateau_current"]
    assert plateau.value == pytest.approx(model_id(device(world), 2.0, 1.0), rel=0.01)
    service.close()


def test_pulse_train_long_confirms_soft_pulse(world: World) -> None:
    world.use_scenario("nmos_wgfmu")
    service = world.service()
    validation = validate(service, "wgfmu.pulse_train", MOSFET, count=20000, samples=1)
    assert validation.tier == "needs_confirmation"
    assert set(validation.confirm_reasons) == {"soft_pulse", "unverified_topology"}
    service.close()


# -- wgfmu.dc_spot ---------------------------------------------------------------------------------------------------


def test_dc_spot_reads_the_known_resistor_through_the_rsu(world: World) -> None:
    """Bring-up L8 target on the simulator: I(R) +-3 %, the resistance line of the DC steps; several readings per
    level are rows of their own."""
    world.use_scenario("resistor_100k")
    service = world.service()
    request = {k: v for k, v in RESISTOR.items() if k != "recipe_id"}
    _, result = run_confirmed(service, "wgfmu.dc_spot", request)
    found = by_quantity(result.analyses)
    assert found["resistance"].value == pytest.approx(R_TRUE, rel=0.03)
    assert found["resistance"].classification == "in_range"
    _, result = run_confirmed(service, "wgfmu.dc_spot", request, samples=2)
    table = load_run(result.run_id or "", data_root=world.data).table
    assert list(table.columns) == ["step", "a_V", "a_I", "a_I_status", "trust"] and len(table) == 10
    assert table["a_I"].to_numpy() == pytest.approx(table["a_V"].to_numpy() / R_TRUE, rel=0.01, abs=5e-9)
    manifest = json.loads((run_dir(world, result.run_id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind_result"]["dc_steps"] == 5 and manifest["kind_result"]["readings"] == 10
    service.close()


# -- wgfmu.custom_waveform -------------------------------------------------------------------------------------------


def test_custom_waveform_library_sample_runs_with_exact_event_timing(world: World) -> None:
    world.use_scenario("nmos_rtn")
    service = world.service()
    validation, result = run_confirmed(service, "wgfmu.custom_waveform", MOSFET)
    assert validation.resolved is not None and validation.resolved.points == 55200
    assert result.status_counts == {"N": 110400}
    folder = run_dir(world, result.run_id)
    table = load_run(result.run_id or "", data_root=world.data).table
    assert len(table) == 55200 and set(table["event"]) == {"E1"} and set(table["drain_range"]) == {"100ua"}
    assert np.allclose(table["t_s"].to_numpy(), (np.arange(55200) + 0.5) * 1e-7, rtol=0, atol=1e-15)  # the grid
    program = read_program(folder)
    assert program is not None and program.kind == "wgfmu_waveform"
    entry = program.programs["waveform"]
    assert entry.channels == [201, 202] and entry.spec["builder"] == "table"
    assert {name: f.path for name, f in program.files.items()} == {
        "gate_wave": "recipes/waveforms/lwp_sample.csv", "drain_wave": "recipes/waveforms/lwp_sample_drain.csv",
        "events": "recipes/waveforms/lwp_sample_events.csv"}
    gate_raw = read_wgfmu_raw(folder / "raw" / "wgfmu-201-000.npz")
    assert gate_raw.quantity == "V" and len(gate_raw.time_s) == 55200
    assert table["gate_V"].to_numpy() == pytest.approx(gate_raw.value)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert {"program.json", "raw/wgfmu-201-000.npz", "raw/wgfmu-202-000.npz"} <= set(manifest["files"])
    assert any("WGFMU waveform" in a for a in manifest["assumptions"])
    assert any("WGFMU phase 1" in a for a in manifest["assumptions"])
    assert result.artifacts["program"].endswith("program.json")
    service.close()


def lab_shaped(work: Path) -> dict[str, str]:
    """A table of the lab's shape (lwp/1530 ch1_wave_pt.csv: 1,825 rows, 30 us steps with 10 ns edges, 50.4 ms;
    synthetic levels), a constant drain bias and one 504,000-point event at 100 ns (meas_pt.csv shape)."""
    folder = work / "waveforms"
    folder.mkdir(parents=True, exist_ok=True)
    rows, tick, level = ["0,0"], 0, 0.0
    levels = (1.5, 2.0, 2.5, 3.0, 0.0)
    for index in range(1, 1824):
        if index % 2:  # a 10 ns edge to the next level
            tick += 1
            level = levels[(index // 2) % len(levels)]
        else:  # hold it
            tick += 5_520
        rows.append(f"{tick * 1e-8:.8g},{level:g}")
    rows.append(f"{5_040_000 * 1e-8:.8g},{level:g}")  # hold the last level to 50.4 ms
    assert len(rows) == 1825 and tick < 5_040_000
    (folder / "lab_gate.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (folder / "lab_drain.csv").write_text("0,0\n1e-05,0.1\n0.05039,0.1\n0.0504,0\n", encoding="utf-8")
    (folder / "lab_events.csv").write_text("0,504000,1e-07,1e-07,0,3\n", encoding="utf-8")
    return {"gate_wave": "work/waveforms/lab_gate.csv", "drain_wave": "work/waveforms/lab_drain.csv",
            "events": "work/waveforms/lab_events.csv"}


def test_custom_waveform_lab_shaped_504000_point_run_is_archived_as_npz(world: World) -> None:
    """The WP ACs: a lab-shaped 1,825-row table with a 504,000-point event runs and archives as npz; a
    work/waveforms/ file needs adhoc_recipe."""
    world.use_scenario("nmos_rtn")
    params = lab_shaped(world.paths.work_dir)
    service = world.service()
    validation, result = run_confirmed(service, "wgfmu.custom_waveform", MOSFET,
                                       reasons={"adhoc_recipe", "unverified_topology"}, **params)
    assert "504000 pts @100 ns" in (validation.summary or "") and validation.resolved is not None
    assert validation.resolved.points == 504000
    assert result.status_counts == {"N": 1_008_000}
    folder = run_dir(world, result.run_id)
    assert (folder / NPZ_FILE).is_file() and (folder / PREVIEW_FILE).is_file() and not (folder / "data.csv").exists()
    data = load_run(result.run_id or "", data_root=world.data)
    assert len(data.table) == 504000 and data.table["t_s"].iloc[-1] == pytest.approx(0.0504 - 5e-8)
    program = read_program(folder)
    assert program is not None and len(program.programs["waveform"].spec["patterns"]["gate"]["vectors"]) == 1824
    assert {f.origin for f in program.files.values()} == {"work"}
    detail = service.get_run(result.run_id or "", include=["data"])
    assert detail.ok and detail.data is not None and len(detail.data.rows) <= 200
    service.close()


def test_custom_waveform_file_changed_after_validation_makes_the_run_stale(world: World) -> None:
    world.use_scenario("nmos_rtn")
    params = lab_shaped(world.paths.work_dir)
    service = world.service()
    validation = validate(service, "wgfmu.custom_waveform", MOSFET, **params)
    events = world.paths.work_dir / "waveforms" / "lab_events.csv"
    events.write_text("0,1000,1e-07,1e-07,0,3\n", encoding="utf-8")
    result = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    assert not result.ok and result.error_code == "plan_stale" and "events" in result.message
    assert world.run_dirs() == []
    service.close()


def test_custom_waveform_beyond_the_pattern_limit_is_blocked(world: World) -> None:
    world.use_scenario("nmos_rtn")
    folder = world.paths.work_dir / "waveforms"
    folder.mkdir(parents=True)
    (folder / "long.csv").write_text("\n".join(f"{k * 1e-6:.8g},{k % 2:g}" for k in range(2050)) + "\n",
                                     encoding="utf-8")
    (folder / "events.csv").write_text("0,10,1e-6,0,0,0\n", encoding="utf-8")
    service = world.service()
    blocked = service.validate_plan(recipe_id="wgfmu.custom_waveform", **MOSFET, params={
        "gate_wave": "work/waveforms/long.csv", "drain_wave": "work/waveforms/long.csv",
        "events": "work/waveforms/events.csv"})
    assert blocked.tier == "blocked"
    assert any(f.rule_id == "R-WG-02" and "2049 vectors" in f.message for f in blocked.findings)
    service.close()


# -- asynchronous runs -----------------------------------------------------------------------------------------------

LONG_TRAIN = {"count": 400, "period": 1.0, "samples": 1}
"""400 pulses at 1 Hz: 400 s of sequencer time, above ``max_sync_run_s`` (asynchronous), checkpoints every 10 s."""


def test_pulse_train_long_runs_asynchronously_with_checkpoints(world: World) -> None:
    world.use_scenario("nmos_wgfmu")
    service = world.service(adapter="mcp")
    validation = validate(service, "wgfmu.pulse_train", MOSFET, **LONG_TRAIN)
    assert validation.resolved is not None and validation.resolved.mode == "async"
    assert set(validation.confirm_reasons) == {"unverified_topology"}
    started = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    assert started.ok and started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed" and final.cleanup_verified == "sim_state"
    assert final.status_counts == {"N": 400}
    progress = service.get_run(final.run_id or "", include=["progress"]).progress
    assert progress is not None and progress.state == "completed" and progress.done == progress.total == 42
    # one checkpoint per 10 s of the 400 s sequencer time (41 chunks) plus the readback
    service.close()


def test_pulse_train_cancelled_aborts_the_sequencer_with_a_verified_cleanup(world: World,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from b1500_test_agent.session import AbortFile, Transaction

    world.use_scenario("nmos_wgfmu")
    original = Transaction.checkpoint

    def checkpoint(self: Transaction, done: int, total: int, phase: str = "", rows: Any = None) -> None:
        if done == 3:
            AbortFile(world.state_dir).request("test abort", adapter="cli")
        original(self, done, total, phase, rows)

    monkeypatch.setattr(Transaction, "checkpoint", checkpoint)
    service = world.service(adapter="mcp")
    validation = validate(service, "wgfmu.pulse_train", MOSFET, **LONG_TRAIN)
    started = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and (final.outcome, final.error_code) == ("cancelled", "run_cancelled")
    assert final.cleanup_verified == "sim_state"
    events = [json.loads(line) for line in (run_dir(world, final.run_id) / "audit.jsonl").read_text(
        encoding="utf-8").splitlines()]
    calls = [str(e.get("cmd")).split("_", 1)[-1] for e in events if e["ev"] == "wgfmu_call"]  # C names, no prefix
    assert "getMeasureValues" not in calls  # cancelled while the sequencer ran: no readback
    assert calls.index("abort") > calls.index("execute") and calls[-1] == "closeSession"
    phase_end = next(e for e in events if e["ev"] == "checkpoint" and e["data"].get("label") == "wgfmu_phase_end")
    assert phase_end["data"]["ok"] is True
    progress = service.get_run(final.run_id or "", include=["progress"]).progress
    assert progress is not None and (progress.state, progress.done) == ("cancelled", 3)
    service.close()
