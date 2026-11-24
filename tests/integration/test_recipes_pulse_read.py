"""Recipe validation of the composite kind ``pulse_read`` on the simulator (WP9.4; blueprint v2 10.5 row 9.4, per-recipe
AC: tier, run, default analysis vs the 4.2 fidelity target). These tests set ``status: sim_validated`` of
``fefet.pulse_write_read`` and ``spgu.program_smu_read``.

- ``fefet.pulse_write_read`` (scenario ``fefet_lab``): the card example needs confirmation (unverified pin map and
  topology) and its ``validate_plan`` ``resolved`` block lists the routes per phase; the confirmed run erases and
  programs the FeFET with HV-SPGU pulses through SEL1.OUT1 -> PGU and reads it through SEL1.OUT1 -> SMU after every
  operation; the memory window from the pulses is within 10 % of the model truth ``memory_window_truth(v_program,
  v_erase, width)`` (4.2 ``ferro``; the S12 grader's truth); the manifest records PGU -> SMU per operation of every
  cycle and rest at the end, the selector ends at rest (verified); spot reads give the read currents of the model.
- ``spgu.program_smu_read``: always confirmed (``adhoc_recipe``); its spot read currents after program and erase are
  within 5 % of the model's currents.
- The SMU pulse source (test-only ``generic.smu_pulse_read``): one SMU pulses and reads the gate, MW within 10 %.
- The WGFMU source and read are refused at plan time (WP10.6) with zero instrument I/O.
- Async runs and cancel: a long plan runs asynchronously; an abort seen at any checkpoint cancels there with the
  selector back at rest and the cleanup verified; a read in compliance stops the run (rest still applied).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.async_helpers import assert_async_invariant, partial_rows, progress_of
from tests.integration.helpers import World
from tests.integration.test_async_cancel import abort_at
from tests.sim.pulse_read_helpers import (
    AT_REST,
    PROGRAM_READ,
    SCENARIO,
    SMU_PULSE_READ,
    WRITE_READ,
    drain_current,
    fresh_fefet,
    mw_truth,
    recipes_with_fixture,
)

pytestmark = pytest.mark.spgu

EXAMPLE_SUMMARY = ("fefet.pulse_write_read@1 | drain=SMU4(HRSMU) bias 0.05 V Icomp 1 mA; gate=SPGU1:101 via SEL1.OUT1 "
                   "pulse 0->-4..4 V 1 us x2 @100 kHz SER 1 MOhm Isc<=0.08 A residual; gate_read=SMU3(HRSMU) via "
                   "SEL1.OUT1 sweep -0.5..1.8 V Icomp 1 uA | DUT fefet-lab | pins fefet-sel | sim | R-PIN-02 "
                   "unverified_pin_map, R-ROUTE-02 unverified_topology")


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


def selector_ports(world: World) -> dict[int, int]:
    state = load_state_file(sim_state_file(world.state_dir, SCENARIO))
    assert state is not None
    return {port: state.selector_ports.get(port, 0) for port in range(4)}


def fefet_p(world: World) -> float:
    state = load_state_file(sim_state_file(world.state_dir, SCENARIO))
    assert state is not None
    return float(state.devices["dut"]["p"])


def by_quantity(results: list[Any]) -> dict[str, Any]:
    return {r.quantity: r for r in results}


def route_log(entry: str) -> list[tuple[str, str, str]]:
    """``(when, phase, route)`` of ``kind_result.routes``."""
    return [tuple(item.split(" ", 2)) for item in entry.split("; ")]  # type: ignore[misc]


def fixture_world(world: World) -> World:
    world.recipes = recipes_with_fixture(world.root)
    return world


# -- fefet.pulse_write_read ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_card_example_needs_confirmation_and_lists_routes_per_phase(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**WRITE_READ)
    assert validation.tier == "needs_confirmation" and validation.summary == EXAMPLE_SUMMARY
    assert sorted(validation.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    assert validation.resolved is not None and validation.resolved.routes == {
        "erase": ["SEL1.OUT1->pgu"], "program": ["SEL1.OUT1->pgu"], "read": ["SEL1.OUT1->smu"],
        "rest": ["SEL1.OUT1->open"]}
    assert validation.resolved.channels["gate"] == "SPGU1(HVSPGU)"
    assert validation.resolved.channels["gate_read"] == "SMU3(HRSMU)"
    assert not sim_state_file(world.state_dir, SCENARIO).exists()  # validation never touched the instrument


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_memory_window_from_pulses_matches_the_model_truth(recipe_id: str, world: World) -> None:
    """The WP9.4 AC: MW +-10 % of memory_window_truth; manifest routes PGU -> SMU per operation, rest at the end;
    selector at rest (verified)."""
    world.use_scenario(SCENARIO)
    validation, result = confirmed(world, WRITE_READ)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("sim", True, "sim_state")
    assert result.status_counts == {"N": 3 * 47 * 2}
    truth = mw_truth(4.0, -4.0, 1e-6)
    found = by_quantity(result.analyses)
    assert list(found) == ["memory_window", "vth_program", "vth_erase", "vth_initial"]
    assert found["memory_window"].value == pytest.approx(truth, rel=0.10) and found["memory_window"].unit == "V"
    assert found["memory_window"].value == pytest.approx(truth, abs=0.01)  # a rigid shift: the method offset cancels
    assert found["vth_initial"].value == pytest.approx(found["vth_erase"].value, abs=0.01)  # it starts erased
    data = manifest(world, str(result.run_id))
    facts = data["kind_result"]
    assert (facts["source"], facts["reads_done"], facts["pulse_ops_done"], facts["pulses_applied"]) == ("spgu", 3, 2, 2)
    assert (facts["spp_fallbacks"], facts["stopped_early"], facts["route_phases"]) == (0, False, 6)
    assert route_log(facts["routes"]) == [
        ("start", "read", "SEL1.OUT1->smu"), ("c1", "erase", "SEL1.OUT1->pgu"), ("c1", "read", "SEL1.OUT1->smu"),
        ("c1", "program", "SEL1.OUT1->pgu"), ("c1", "read", "SEL1.OUT1->smu"), ("end", "rest", "SEL1.OUT1->open")]
    assert {t: s for t, s in data["cleanup"]["switches_after"].items() if t.startswith("SEL")} == AT_REST
    assert selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0} and not data["cleanup"]["latched_fault"]
    assert data["confirmed_summary"] == validation.summary
    assert any("program/read" in line for line in data["assumptions"])
    audit = [(e.data["phase"], e.data["readback"]) for e in world.audit_events()
             if e.ev == "checkpoint" and e.data and e.data.get("label") == "routes" and "readback" in e.data]
    assert [phase for phase, _ in audit] == ["read", "erase", "read", "program", "read", "rest"]
    assert all("SEL1.OUT1 " + ("pgu" if p in ("erase", "program") else "open" if p == "rest" else "smu") in rb
               for p, rb in audit)
    assert fefet_p(world) > 0.9  # programmed last
    table = load_run(str(result.run_id), data_root=world.data).table
    assert list(table.columns) == ["step", "cycle", "phase", "gate_read_V", "gate_read_I", "gate_read_I_status",
                                   "drain_I", "drain_I_status", "drain_V", "trust"]
    assert table.groupby(["cycle", "phase"], sort=False).size().to_dict() == {
        (0, "read"): 47, (1, "erase"): 47, (1, "program"): 47}
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    first_pgu = sent.index("ERSSP 0,2")
    assert sent.index("ERSSP 0,1") < sent.index("CN 3,4,101") < first_pgu < sent.index("SRP")
    window = sent[sent.index("XE"):first_pgu]  # after the reference read, before the gate's relay moves to the PGU
    assert "DV 4,0,0,0.001" in window and "DV 3,0,0,1E-06" in window  # every read SMU at 0 V first


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_every_cycle_routes_pgu_then_smu_and_reproduces_the_window(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, WRITE_READ, cycles=3, sequence="program_erase", initial_read=False)
    assert result.ok and result.outcome == "completed", result.message
    mw = by_quantity(result.analyses)["memory_window"]
    assert mw.value == pytest.approx(mw_truth(), rel=0.10) and mw.fit["cycles"] == 3 and mw.fit["mw_std"] < 0.01
    log = route_log(manifest(world, str(result.run_id))["kind_result"]["routes"])
    for cycle in (1, 2, 3):
        assert [(p, r) for w, p, r in log if w == f"c{cycle}"] == [
            ("program", "SEL1.OUT1->pgu"), ("read", "SEL1.OUT1->smu"), ("erase", "SEL1.OUT1->pgu"),
            ("read", "SEL1.OUT1->smu")]
    assert log[-1] == ("end", "rest", "SEL1.OUT1->open") and fefet_p(world) < -0.9  # erased last


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_spot_reads_give_the_model_read_currents(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, WRITE_READ, read_kind="spot", samples=3)
    assert result.ok, result.message
    found = by_quantity(result.analyses)
    device = fresh_fefet()
    p_prog = device.pulse_truth(4.0 * (1e6 + 50) / 1e6, 1e-6, -1.0)
    p_erase = device.pulse_truth(-4.0 * (1e6 + 50) / 1e6, 1e-6, p_prog)
    assert found["i_program"].value == pytest.approx(drain_current(p_prog, 0.6), rel=0.05)
    assert found["i_erase"].value == pytest.approx(drain_current(p_erase, 0.6), rel=0.05)
    assert found["current_ratio"].value > 100


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_a_read_in_compliance_stops_the_run_and_still_rests(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, WRITE_READ, icomp_drain=1e-7)
    assert result.ok and result.outcome in ("completed", "completed_with_flags"), result.message
    facts = manifest(world, str(result.run_id))["kind_result"]
    assert facts["stopped_early"] and facts["reads_done"] == 1 and "reported status C" in facts["stop_reason"]
    assert facts["pulse_ops_done"] == 0 and route_log(facts["routes"])[-1] == ("end", "rest", "SEL1.OUT1->open")
    assert selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}


# -- spgu.program_smu_read -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["spgu.program_smu_read"])
def test_program_smu_read_is_ad_hoc_and_reads_the_model_currents(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation, result = confirmed(world, PROGRAM_READ)
    assert sorted(validation.confirm_reasons) == ["adhoc_recipe", "unverified_pin_map", "unverified_topology"]
    assert validation.resolved is not None and list(validation.resolved.routes) == ["program", "erase", "read", "rest"]
    assert result.ok and result.outcome == "completed", result.message
    found = by_quantity(result.analyses)
    assert list(found) == ["current_ratio", "i_program", "i_erase", "i_initial"]
    device = fresh_fefet()
    level = 4.0 * (1e6 + 50) / 1e6
    p_prog = device.pulse_truth(level, 1e-6, -1.0)
    p_erase = device.pulse_truth(-level, 1e-6, p_prog)
    assert found["i_program"].value == pytest.approx(drain_current(p_prog, 0.9), rel=0.05)
    assert found["i_erase"].value == pytest.approx(drain_current(p_erase, 0.9), rel=0.05)
    assert found["current_ratio"].value == pytest.approx(
        drain_current(p_prog, 0.9) / drain_current(p_erase, 0.9), rel=0.10)
    facts = manifest(world, str(result.run_id))["kind_result"]
    assert (facts["cycles_done"], facts["reads_done"], facts["pulse_ops_done"]) == (3, 7, 6)
    assert [p for _, p, _ in route_log(facts["routes"])].count("read") == 7


@pytest.mark.parametrize("recipe_id", ["spgu.program_smu_read"])
def test_program_only_staircase_reads_follow_the_cumulative_program(recipe_id: str, world: World) -> None:
    """A program-only sequence with Id-Vg reads: no window, the programmed state's Vth per cycle (the pulses here
    saturate the film in the first cycle, so every read sits at the programmed Vth); the drain holds vd_pulse while
    the pulses run."""
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, PROGRAM_READ, sequence="program", read_kind="staircase", cycles=2, vd_pulse=0.02)
    assert result.ok and result.outcome == "completed", result.message
    found = by_quantity(result.analyses)
    assert "memory_window" not in found and list(found) == ["vth_program", "vth_initial"]
    program = found["vth_program"]
    assert program.fit["reads"] == 2 and abs(program.fit["last"] - program.fit["first"]) < 0.005
    assert found["vth_initial"].value - program.value == pytest.approx(mw_truth(), rel=0.10)  # erased -> programmed
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    first_pgu = sent.index("ERSSP 0,2")
    assert "DV 4,0,0.02,0.001" in sent[sent.index("XE"):first_pgu]  # the drain at vd_pulse before the pulses


# -- SMU pulse source ------------------------------------------------------------------------------------------------


def test_the_smu_pulse_source_programs_and_reads_with_one_smu(world: World) -> None:
    fixture_world(world).use_scenario(SCENARIO)
    validation, result = confirmed(world, SMU_PULSE_READ)
    assert "gate=SMU3(HRSMU) via SEL1.OUT1 pulse 0->-4..4 V 1 ms x2 @200 Hz" in str(validation.summary)
    assert result.ok and result.outcome == "completed", result.message
    mw = by_quantity(result.analyses)["memory_window"]
    assert mw.value == pytest.approx(mw_truth(4.0, -4.0, 1e-3), rel=0.10)
    facts = manifest(world, str(result.run_id))["kind_result"]
    assert (facts["source"], facts["pulse_readings"], facts["pulse_statuses"]) == ("smu", 2, "N")
    assert facts["pulse_i_max_a"] < 1e-9 and "spp_fallbacks" not in facts
    assert route_log(facts["routes"]) == [("start", "read", "SEL1.OUT1->smu"), ("end", "rest", "SEL1.OUT1->open")]
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    assert "MM 3,3" in sent and "PV 3,0,0,4,1E-06" in sent and "PV 3,0,0,-4,1E-06" in sent
    assert not any(c.startswith(("SPV", "SRP", "ERSSP 0,2")) for c in sent)
    assert selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}


# -- WGFMU source: refused at plan time ------------------------------------------------------------------------------


def test_the_wgfmu_read_and_source_are_refused_at_plan_time_without_io(world: World, tmp_path: Path) -> None:
    fixture_world(world).use_scenario(SCENARIO)
    service = world.service()
    read = service.validate_plan(**SMU_PULSE_READ, params={"read_kind": "wgfmu"})
    assert not read.ok and read.error_code == "invalid_input" and "arrives in WP10.6" in read.message
    recipe = world.recipes / "generic" / "smu_pulse_read.yaml"
    text = recipe.read_text(encoding="utf-8").replace("function: pulse_v\n    measure: [I]\n    module_types: [MPSMU, "
                                                      "HRSMU, HPSMU]", "function: wgfmu\n    module_types: [WGFMU]")
    recipe.write_text(text.replace("  bulk:", "  probe: {function: measure_only, measure: [I]}\n  bulk:"),
                      encoding="utf-8")
    source = world.service().validate_plan(**SMU_PULSE_READ)
    assert not source.ok and source.error_code == "invalid_input"
    assert "WGFMU source arrives in WP10.6" in source.message
    assert not sim_state_file(world.state_dir, SCENARIO).exists() and world.run_dirs() == []


# -- async, checkpoints, cancel --------------------------------------------------------------------------------------


@pytest.mark.parametrize("k", range(1, 6))
@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_cancel_at_every_checkpoint_returns_the_selector_to_rest(recipe_id: str, k: int, world: World,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Five checkpoints (reference read, erase, read, program, read): an abort seen at checkpoint k cancels there."""
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**WRITE_READ)
    abort_at(monkeypatch, world, k)
    result = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    if result.outcome == "running":
        result = service.follow_run(result.run_id or "")  # type: ignore[assignment]
    assert result is not None and (result.outcome, result.error_code) == ("cancelled", "run_cancelled")
    assert result.cleanup_verified == "sim_state" and "data" not in result.artifacts
    assert partial_rows(world, result.run_id or "") == 47 * ((k + 1) // 2)  # rows of the reads up to checkpoint k
    data = assert_async_invariant(world, result.run_id or "", scenario=SCENARIO)
    assert data.outcome == "cancelled" and data.cleanup is not None
    assert {t: s for t, s in data.cleanup.switches_after.items() if t.startswith("SEL")} == AT_REST
    assert selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    service.close()


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_a_long_plan_runs_asynchronously_with_checkpoints_and_cancels(recipe_id: str, world: World,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**WRITE_READ, params={"cycles": 3, "settle": 60.0})
    assert validation.resolved is not None and validation.resolved.mode == "async"
    assert "async ~" in str(validation.summary)
    abort_at(monkeypatch, world, 8)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "cancelled" and final.cleanup_verified == "sim_state"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.total, progress.state) == (8, 7 + 6 * 7, "cancelled")
    data = assert_async_invariant(world, final.run_id or "", scenario=SCENARIO)
    assert data.plan.mode == "async" and selector_ports(world) == {0: 0, 1: 0, 2: 0, 3: 0}
    service.close()


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_a_long_plan_completes_asynchronously(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    _, result = confirmed(world, WRITE_READ, cycles=3, settle=60.0)
    assert result.ok and result.outcome == "completed", result.message
    assert manifest(world, str(result.run_id))["plan"]["mode"] == "async"
    assert by_quantity(result.analyses)["memory_window"].value == pytest.approx(mw_truth(), rel=0.10)
