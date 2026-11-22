"""``spgu.pulse_train`` and ``spgu.alwg_sequence`` through ``B1500Service`` and the real kind on the simulator
(blueprint v2 3.3, 2.7 ``spgu_pulse`` pg/alwg, 2.8 R-PULSE-01..03 + R-SPGU-01 live, 4.2 SPGU output target; WP9.3
per-recipe AC): tier as the card says, the 4 V x 1 us x 1000 train on ``fefet_lab`` through SEL1.OUT1 runs, programs
the FeFET and leaves every selector at rest (verified), the level at the gate and the pulse count follow the
SER-divider model exactly, SER 50 Ohm on the high_z gate is blocked, three-level and duration-bounded trains, the ALWG
waveform, and the ATV-19 fallback (``SPST?`` stuck: ``SPP``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SpguPulseKind
from b1500_test_agent.models.spgu import spgu_programs
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.helpers import REPO_ROOT, World
from tests.sim.selector_helpers import recorded_station, selector_states
from tests.sim.spgu_pulse_helpers import ALWG, PULSE_TRAIN, compile_plan, pulse_harness

pytestmark = pytest.mark.spgu

SCENARIO = "fefet_lab"
EXAMPLE_SUMMARY = ("spgu.pulse_train@1 | gate=SPGU1:101 via SEL1.OUT1 pulse 0->4 V 1 us x1000 @10 kHz SER 1 MOhm "
                   "Isc<=0.08 A residual | DUT fefet-lab | pins fefet-sel | sim | R-PIN-02 unverified_pin_map, "
                   "R-ROUTE-02 unverified_topology")
AT_REST = {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open"}


def confirmed(world: World, request: dict[str, Any], **params: Any) -> tuple[Any, Any]:
    service = world.service()
    validation = service.validate_plan(**request, params=params)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    return validation, service.run_confirmed_plan(validation.plan_id, summary=validation.summary)


def manifest(world: World, run_id: str) -> dict[str, Any]:
    folder = next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def fefet_p(world: World) -> float:
    state = load_state_file(sim_state_file(world.state_dir, SCENARIO))
    return float(state.devices["dut"]["p"])


# -- spgu.pulse_train ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_card_example_is_the_blueprint_summary_and_needs_confirmation(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**PULSE_TRAIN)
    assert validation.tier == "needs_confirmation"
    assert sorted(validation.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    assert validation.summary == EXAMPLE_SUMMARY  # blueprint v2 2.9 pulse form, residual of the high_z gate


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_four_volt_train_runs_through_the_selector_and_ends_at_rest(recipe_id: str, world: World) -> None:
    """The WP9.3 AC: 4 V x 1 us x 1000 on fefet_lab runs, selector at rest (verified)."""
    world.use_scenario(SCENARIO)  # the FeFET starts erased (p_init -1)
    validation, result = confirmed(world, PULSE_TRAIN)
    assert result.ok and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state" and result.backend == "sim" and result.simulated
    data = manifest(world, str(result.run_id))
    facts = data["kind_result"]
    assert (facts["mode"], facts["outputs"], facts["pulses_planned"], facts["spp_fallbacks"]) == ("pg", 1, 1000, 0)
    assert facts["output_s_planned"] == pytest.approx(0.1) and 0.1 <= facts["waited_s"] <= 0.2 + 1e-9
    assert {t: s for t, s in data["cleanup"]["switches_after"].items() if t.startswith("SEL")} == AT_REST
    assert data["confirmed_summary"] == validation.summary and not data["cleanup"]["latched_fault"]
    assert fefet_p(world) > 0.9  # the 4 V pulses reached the gate through the PGU path and programmed the FeFET
    routes = [e.data for e in world.audit_events()
              if e.ev == "checkpoint" and e.data and e.data.get("label") == "routes"]
    assert [(r["phase"], r["routes"]) for r in routes] == [("pulse", "SEL1.OUT1->pgu"), ("rest", "SEL1.OUT1->open")]
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    assert sent.index("ERSSP 0,2") < sent.index("CN 101") < sent.index("SPUPD 101") < sent.index("SRP")
    assert sent.index("SRP") < sent.index("ERSSP 0,0") and "SPRM 1,1000" in sent and "SER 101,1000000" in sent
    assert "SPP" not in sent[:sent.index("ERSSP 0,0")]  # the count ended the train (SPST? 0), no fallback


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_level_count_and_timing_follow_the_ser_model_exactly(recipe_id: str, tmp_path: Path) -> None:
    """Blueprint v2 4.2 SPGU target on the real kind: the open gate sees V_set (SER + 50) / SER, the output lasts
    count x period exactly, the FeFET switches, the selector port is back at rest."""
    plan = compile_plan(tmp_path / "plan", SCENARIO, PULSE_TRAIN)
    h = pulse_harness(tmp_path / "state", SCENARIO)
    with h.transaction(envelope=plan.envelope, intent="spgu.pulse_train") as tx:
        raw = SpguPulseKind().acquire(tx, plan)
    assert raw.ok and raw.kind_result["pulses_planned"] == 1000
    run = h.sim.instrument.spgu_runs[-1]
    record = run.channels[1]  # canonical channel of 101
    assert record.ser == 1e6 and record.max_set_v == 4.0
    assert record.delivered_v == pytest.approx(4.0 * (1e6 + 50) / 1e6, rel=1e-12)  # open-load level, exact
    assert run.end_s - run.start_s == pytest.approx(1000 * 1e-4, rel=1e-12)  # count x period, exact
    assert h.sim.instrument.circuit.devices["dut"].p > 0.9  # type: ignore[attr-defined]
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state" and selector_states(h.sim) == {
        0: 0, 1: 0, 2: 0, 3: 0}


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_ser_50_ohm_on_the_high_z_gate_is_blocked(recipe_id: str, world: World) -> None:
    """The WP9.3 AC: SER 50 Ohm on a high_z gate doubles the level at the open gate -> blocked (R-SPGU-01)."""
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**PULSE_TRAIN, params={"load_ohm": 50.0})
    assert validation.tier == "blocked"
    blocks = [f for f in validation.findings if f.severity == "block"]
    assert {f.rule_id for f in blocks} == {"R-SPGU-01"}
    assert any("high_z but SER is 50 Ohm" in f.message for f in blocks)
    assert any("open-load 8 V exceeds terminal gate's pulse limit 5 V" in f.message for f in blocks)
    assert "SER 50 Ohm Isc<=0.16 A residual" in str(validation.summary)
    assert not sim_state_file(world.state_dir, SCENARIO).exists()  # validation never touched the instrument


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_recorded_wiring_and_a_verified_pin_map_give_tier_ok(recipe_id: str, world: World) -> None:
    import yaml

    world.use_scenario(SCENARIO)
    world.write_config("station.yaml", recorded_station())
    pin_map = yaml.safe_load((REPO_ROOT / "config/pinmaps/fefet-sel.example.yaml").read_text(encoding="utf-8"))
    world.write_config("pinmaps/fefet-sel.yaml", {**pin_map, "certainty": "verified"})
    validation = world.service().validate_plan(**PULSE_TRAIN)
    assert validation.tier == "ok", validation.message
    soft = world.service().validate_plan(**PULSE_TRAIN, params={"count": 20000})
    assert soft.tier == "needs_confirmation" and soft.confirm_reasons == ["soft_pulse"]  # R-PULSE-03 count band


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_three_level_and_duration_bound(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation, result = confirmed(world, PULSE_TRAIN, three_level=True, bound="duration", duration=0.05)
    assert "pulse 0->-4..4 V 2 us x500 @10 kHz SER 1 MOhm" in str(validation.summary)  # both levels; 2 windows
    assert result.ok and result.outcome == "completed", result.message
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    assert {"SPM 101,3", "SPRM 2,0.05", "SPT 101,2,2E-06,1E-06,2E-08,2E-08", "SPV 101,2,0,-4"} <= set(sent)
    assert fefet_p(world) < -0.9  # source 2 (-4 V) follows source 1 in every period: erased at the end


# -- spgu.alwg_sequence ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["spgu.alwg_sequence"])
def test_alwg_card_example_runs_and_ends_at_rest(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation, result = confirmed(world, ALWG)
    assert sorted(validation.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    assert "pulse 0->-4..4 V 2.4 us x100 @44.64 kHz SER 1 MOhm Isc<=0.08 A residual" in str(validation.summary)
    assert result.ok and result.outcome == "completed", result.message
    data = manifest(world, str(result.run_id))
    assert data["kind_result"]["mode"] == "alwg" and data["kind_result"]["spp_fallbacks"] == 0
    assert {t: s for t, s in data["cleanup"]["switches_after"].items() if t.startswith("SEL")} == AT_REST
    sent = [r.command for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    assert "SIM 1" in sent and sent.index("ALS 26") < sent.index("SPUPD 101") < sent.index("SRP")
    assert fefet_p(world) < -0.9  # +4 V then -4 V each sequence: erased last


@pytest.mark.parametrize("recipe_id", ["spgu.alwg_sequence"])
def test_alwg_sequences_and_levels_are_exact(recipe_id: str, tmp_path: Path) -> None:
    plan = compile_plan(tmp_path / "plan", SCENARIO, ALWG)
    program = spgu_programs(plan.program)[0]
    h = pulse_harness(tmp_path / "state", SCENARIO)
    with h.transaction(envelope=plan.envelope, intent="spgu.alwg_sequence") as tx:
        SpguPulseKind().acquire(tx, plan)
    run = h.sim.instrument.spgu_runs[-1]
    assert run.mode == "alwg" and run.channels[1].max_set_v == 4.0
    assert run.end_s - run.start_s == pytest.approx(program.output_time_s(), rel=1e-12)  # 100 sequences exactly
    assert program.output_time_s() == pytest.approx(100 * 22.4e-6, rel=1e-12)


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_atv19_fallback_sends_spp_and_the_cleanup_verifies(recipe_id: str, tmp_path: Path) -> None:
    """``SPST?`` stays 1 after the count (fault ``spgu_no_stop`` ignoring the first ``SPP``): the burst block polls the
    planned time plus the margin, sends ``SPP`` (ignored), the run fails because the output is still active, and the
    cleanup's ``SPP`` stops it (``SPST?`` 0 verified). The completed fallback path is ``tests/unit``."""
    from b1500_test_agent.driver.errors import DriverError
    from b1500_test_agent.models.sim import SpguNoStop

    plan = compile_plan(tmp_path / "plan", SCENARIO, PULSE_TRAIN, count=100)
    h = pulse_harness(tmp_path / "state", SCENARIO)
    h.sim.inject(SpguNoStop(spp_ignored=1))
    with pytest.raises(DriverError, match="did not stop"), h.transaction(envelope=plan.envelope, intent="t") as tx:
        SpguPulseKind().acquire(tx, plan)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state" and not h.sim.instrument.spgu_output_active()
    marks = [e.data["label"] for e in h.events() if e.ev == "checkpoint" and e.data and "ATV-19" in str(e.data)]
    assert marks and "SPP" in marks[0]
    assert [r.mnemonic for r in h.log if r.outcome == "ok"].count("SPP") == 2  # the fallback, then the cleanup's


# -- long trains: asynchronous, checkpointed, cancellable ------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_a_long_train_runs_async_with_a_checkpoint_every_ten_seconds(recipe_id: str, world: World) -> None:
    from tests.integration.async_helpers import progress_of

    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    params = {"bound": "duration", "duration": 400.0, "v_peak": 3.0, "period": 1e-3}
    validation = service.validate_plan(**PULSE_TRAIN, params=params)
    assert validation.resolved is not None and validation.resolved.mode == "async"
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "completed" and final.cleanup_verified == "sim_state", final
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.total, progress.state) == (40, 40, "completed")
    service.close()


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_a_long_train_cancels_at_a_checkpoint_and_the_cleanup_stops_it(recipe_id: str, world: World,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.async_helpers import progress_of
    from tests.integration.test_async_cancel import abort_at

    world.use_scenario(SCENARIO)
    service = world.service(adapter="mcp")
    params = {"bound": "duration", "duration": 400.0, "v_peak": 3.0, "period": 1e-3}
    validation = service.validate_plan(**PULSE_TRAIN, params=params)
    abort_at(monkeypatch, world, 5)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "cancelled" and final.cleanup_verified == "sim_state"
    progress = progress_of(world, final.run_id or "")
    assert progress is not None and (progress.done, progress.total) == (5, 40)
    sent = [r.mnemonic for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    assert sent[sent.index("SRP"):].count("SPP") == 1  # the cleanup stopped the running output (step 2)
    assert manifest(world, str(final.run_id))["cleanup"]["switches_after"]["SEL1.OUT1"] == "open"
    service.close()


@pytest.mark.parametrize("recipe_id", ["spgu.pulse_train"])
def test_a_gate_wired_directly_to_the_spgu_needs_no_route(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    world.write_config("pinmaps/gate-101.yaml", {"description": "gate on SPGU 101 directly", "certainty": "verified",
                                                 "terminals": {"gate": 101}})
    validation = world.service().validate_plan(recipe_id=recipe_id, pin_map="gate-101", dut_profile="fefet-lab")
    assert validation.tier == "ok", validation.message  # verified pin map, no switch, inside every band
    assert validation.summary is not None and "gate=SPGU1:101 pulse 0->4 V" in validation.summary
    assert " via " not in validation.summary and "routes" not in validation.summary
