"""The MFCMU correction recipes on the simulator (blueprint v2 10.4 row 8.2 AC, per-recipe AC; WP8.2).

``cmu.phase_compensation``, ``cmu.correction_open``, ``cmu.correction_short`` and ``cmu.correction_load`` (kind
``cmu_correction``) run through ``B1500Service`` on the scenario ``capacitor_100p`` (100 pF behind the fixture: open
0.3 pF || 1 GOhm, short 0.5 Ohm + 50 nH, 1 deg/MHz phase error until phase compensation; blueprint v2 4.2): every one
is ``needs_confirmation (physical_setup)`` with the probe-state prompt, runs when confirmed with its summary, and
writes its record to the correction store. Fidelity (4.2): uncorrected the 100 pF reads about +0.3 pF; after phase +
open + short it reads 100 pF within 0.1 %. The correction gate R-CORR-01 is exercised end to end with the capacitance
recipe ``cmu.spot`` (kind ``cmu_measure``, WP8.3; it replaced the WP8.2 test stub): missing, stale, uncovered and
other-pin-map corrections block at validation with the card as next step, and a ``cmu_correction_lost`` fault blocks
before execution with zero source commands. These tests set the recipes' ``status: sim_validated``. Each data
correction reads its data back (``CORRDT?``, WP8.6): the fixture's open and short parasitics, the load standard.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.archive.corrections import CorrectionStore
from b1500_test_agent.driver.b1500 import B1500Driver, CmuSignal
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.rules.builtin.cmu import CORRECTION_NEXT_STEP
from b1500_test_agent.service import B1500Service
from tests.integration.helpers import REPO_ROOT, World

pytestmark = pytest.mark.cmu

CMU, ALIAS = 7, "CMU1"
TRUTH_F = 100e-12
PINS = "capacitor-cmu"
PROMPTS = {
    "cmu.phase_compensation": "lift the probes", "cmu.correction_open": "lift the probes",
    "cmu.correction_short": "land the probes on a short", "cmu.correction_load": "connect the load standard",
}
LOAD = {"ls_h": 0.0, "rs_ohm": 100.0}
SPOT_REQUEST = {"recipe_id": "cmu.spot", "pin_map": PINS, "dut_profile": "capacitor-100p"}


def recipe(recipe_id: str) -> pytest.MarkDecorator:
    """Parametrize with the recipe id, so ``pytest tests/integration -k <recipe id>`` selects the test."""
    return pytest.mark.parametrize("recipe_id", [recipe_id])


@pytest.fixture
def svc(world: World) -> B1500Service:
    world.use_scenario("capacitor_100p")
    return world.service()


def with_load_standard(world: World) -> None:
    """A station profile (temporary config dir) that declares the 100 Ohm load standard of CMU1."""
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    station["corrections"] = {ALIAS: {"load": LOAD}}
    world.write_config("station.yaml", station)


def validate(svc: B1500Service, recipe_id: str, pin_map: str = PINS, dut: str | None = None,
             **params: Any) -> PlanValidation:
    return svc.validate_plan(recipe_id=recipe_id, params=params or None, pin_map=pin_map, dut_profile=dut)


def confirm(svc: B1500Service, recipe_id: str, pin_map: str = PINS, **params: Any) -> RunSummary:
    """Validate and run with the plan's own summary (the test stands in for the human's consent)."""
    plan = validate(svc, recipe_id, pin_map, **params)
    assert plan.tier == "needs_confirmation" and plan.summary is not None, plan.message
    return svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]


def correct(svc: B1500Service, *recipes: str, **params: Any) -> list[RunSummary]:
    results = [confirm(svc, r, **params) for r in recipes]
    for result in results:
        assert result.ok and result.outcome == "completed", result.message
    return results


def run_spot(svc: B1500Service, **params: Any) -> tuple[PlanValidation, RunSummary | None]:
    """Validate ``cmu.spot`` on the 100 pF standard and run it unless blocked (with the summary when confirmation
    is needed: the test stands in for the human)."""
    plan = svc.validate_plan(**SPOT_REQUEST, params=params or None)
    if plan.tier == "blocked":
        return plan, None
    run = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary) if plan.tier == "needs_confirmation" \
        else svc.run_plan(plan.plan_id)  # type: ignore[arg-type]
    return plan, run


def kind_result(world: World, run_id: str) -> dict[str, Any]:
    folder = next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())
    return yaml.safe_load((folder / "manifest.json").read_text(encoding="utf-8"))["kind_result"]


def cp_by_frequency(world: World, run_id: str) -> dict[int, float]:
    """Mean ``a_Cp`` per frequency (Hz, rounded) of a ``cmu.spot`` run."""
    table = load_run(run_id, data_root=world.data).table
    return {round(f): float(group["a_Cp"].mean()) for f, group in table.groupby("freq_hz")}


def cp_at(driver: B1500Driver, ch: int, freq_hz: float, ac_vrms: float, dc_v: float = 0.0) -> float:
    """One guarded spot ``Cp`` (F) of MFCMU ``ch`` (the channel must be on and the format set)."""
    driver.apply_cmu_signal(ch, CmuSignal(freq_hz=freq_hz, ac_vrms=ac_vrms, dc_v=dc_v))
    driver.spot_c(ch)
    block = driver.measure_cmu(driver.cmu_layout(17), steps=1, timeout_s=10.0)
    return block.readings[0].table_values()["Cp"][0]


def spot_cp(svc: B1500Service, freq_hz: float, ac_vrms: float = 0.03) -> float:
    """Cp outside any plan (no R-CORR-01): a test transaction with its own MFCMU envelope."""
    envelope = CompiledEnvelope(channels={CMU: ChannelEnvelope(
        role="a", max_abs_v=0.0, max_abs_i=1e-3, function="cmu_high",
        ac=AcEnvelope(max_vrms=ac_vrms, max_dc_v=0.0, f_min_hz=1e3, f_max_hz=5e6))})
    session = svc.executor.session(svc.config.get())
    with session.transaction(intent="test spot Cp", envelope=envelope, run=None) as tx:
        tx.driver.set_format(1, 1)
        tx.driver.enable([CMU])
        tx.driver.set_impedance_model(100)
        return cp_at(tx.driver, CMU, freq_hz, ac_vrms)


def store(world: World) -> CorrectionStore:
    return CorrectionStore(world.state_dir)


# -- per recipe: tier, prompt, run, record ---------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", sorted(PROMPTS))
def test_correction_recipe_needs_the_physical_setup_and_writes_its_record(recipe_id: str, world: World,
                                                                          svc: B1500Service) -> None:
    if recipe_id == "cmu.correction_load":
        with_load_standard(world)
    plan = validate(svc, recipe_id)
    assert plan.ok and plan.tier == "needs_confirmation", plan.message
    assert "physical_setup" in plan.confirm_reasons and "unverified_pin_map" in plan.confirm_reasons
    setup = next(f for f in plan.findings if f.rule_id == "R-ALWAYS-01")
    assert PROMPTS[recipe_id] in setup.message  # the probe state the human sets up and confirms
    assert plan.summary is not None and "high=CMU1:H" in plan.summary and "low=CMU1:L low" in plan.summary
    assert plan.resolved is not None and plan.resolved.channels == {"high": "CMU1(MFCMU)", "low": "CMU1(MFCMU)"}
    refused = svc.run_plan(plan.plan_id)  # type: ignore[arg-type]
    assert refused.error_code == "confirmation_required" and not store(world).records(ALIAS)

    result = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]
    assert result.ok and result.outcome == "completed" and result.simulated, result.message
    assert result.cleanup_verified == "sim_state" and result.artifacts["corrections"].endswith("corrections/CMU1.json")
    kind = recipe_id.split("_")[-1] if recipe_id != "cmu.phase_compensation" else "phase"
    facts = kind_result(world, result.run_id)  # type: ignore[arg-type]
    assert facts["result_code"] == 0 and facts["correction"] == kind
    records = store(world).records(ALIAS)
    assert [r.kind for r in records] == [kind] and records[0].run_id == result.run_id
    record = records[0]
    assert record.idn.startswith("Keysight Technologies,B1500A") and len(record.pin_map_sha) == 64
    if kind == "phase":
        assert record.freqs_hz == [] and facts["after_phase"] is True
    else:
        assert len(record.freqs_hz) == 23 and record.corr_state[kind] is True and facts["setup"] == "rewritten"
        # CORRDT? read-back (WP8.6): the fixture's open 0.3 pF, short 0.5 Ohm + 50 nH, the 100 Ohm load (medians over
        # the 23 frequencies, uncompensated phase: a few % on the short)
        expected = {"open": {"open_cp_f": (0.3e-12, 0.02)}, "load": {"load_rs_ohm": (100.0, 0.01)},
                    "short": {"short_rs_ohm": (0.5, 0.05), "short_ls_h": (50e-9, 0.05)}}[kind]
        assert facts["data_freqs"] == 23
        assert {k: facts[k] for k in expected} == {k: pytest.approx(v, rel=r) for k, (v, r) in expected.items()}


def test_corrections_need_no_dut_profile_and_bind_to_the_pin_maps_mfcmu_terminals(svc: B1500Service) -> None:
    """The roles ``high``/``low`` bind by MFCMU side: ``gate``/``bulk`` of moscap-cmu, ``a``/``b`` of capacitor-cmu."""
    for pin_map, high in (("moscap-cmu", "gate"), (PINS, "a")):
        plan = validate(svc, "cmu.correction_open", pin_map)
        assert plan.tier == "needs_confirmation", plan.message
        record = svc.executor.load_plan(plan.plan_id)  # type: ignore[arg-type]
        assert record.binding.roles["high"].terminal == high and record.binding.roles["high"].cmu_side == "H"
        assert record.request.dut_profile is None
    resistor = validate(svc, "cmu.phase_compensation", "resistor-2t")
    assert resistor.tier == "blocked" and any("no terminal to an MFCMU H side" in f.message for f in resistor.findings)


def test_load_correction_needs_the_load_standard_of_the_station(svc: B1500Service) -> None:
    plan = validate(svc, "cmu.correction_load")
    assert not plan.ok and plan.error_code == "invalid_input" and "corrections.CMU1.load" in plan.message


# -- fidelity: uncorrected +0.3 pF, corrected within 0.1 % ------------------------------------------------------------


@recipe("cmu.correction_short")
def test_100pf_reads_within_0_1_percent_after_phase_open_and_short(recipe_id: str, world: World,
                                                                   svc: B1500Service) -> None:
    for freq in (1e5, 1e6):
        uncorrected = spot_cp(svc, freq)
        assert uncorrected - TRUTH_F == pytest.approx(0.3e-12, rel=0.05)  # the fixture's open capacitance
    blocked, _ = run_spot(svc)
    assert blocked.tier == "blocked" and CORRECTION_NEXT_STEP in blocked.next_steps

    correct(svc, "cmu.phase_compensation", "cmu.correction_open", recipe_id)
    plan, run = run_spot(svc)
    assert plan.tier == "needs_confirmation", plan.message  # unverified pin map only
    corr = next(f for f in plan.findings if f.rule_id == "R-CORR-01")
    assert corr.severity == "info" and plan.summary is not None and "corr <1h" in plan.summary
    assert run is not None and run.ok, run.message if run else None
    measured = cp_by_frequency(world, run.run_id)  # type: ignore[arg-type]
    for freq in (100000, 1000000):
        assert measured[freq] == pytest.approx(TRUTH_F, rel=1e-3)
        assert spot_cp(svc, float(freq)) == pytest.approx(TRUTH_F, rel=1e-3)
    assert spot_cp(svc, 3e5) - TRUTH_F == pytest.approx(0.3e-12, rel=0.1)  # not a listed frequency: uncorrected


@recipe("cmu.correction_load")
def test_load_correction_after_open_and_short_also_reads_within_0_1_percent(recipe_id: str, world: World,
                                                                            svc: B1500Service) -> None:
    with_load_standard(world)
    correct(svc, "cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short", recipe_id)
    assert [r.kind for r in store(world).records(ALIAS)] == ["phase", "open", "short", "load"]
    for freq in (1e5, 1e6, 5e6):
        assert spot_cp(svc, freq) == pytest.approx(TRUTH_F, rel=1e-3)


# -- R-CORR-01 through the plan and pre-execute phases ---------------------------------------------------------------


@recipe("cmu.phase_compensation")
def test_missing_corrections_block_the_cv_plan_with_the_card_as_next_step(recipe_id: str,
                                                                          svc: B1500Service) -> None:
    plan, _ = run_spot(svc)
    blocks = [f for f in plan.findings if f.rule_id == "R-CORR-01" and f.severity == "block"]
    assert {f.subject for f in blocks} == {"CMU1.phase", "CMU1.open", "CMU1.short"}
    assert all("card cmu/cmu-correction" in f.message for f in blocks)
    assert "cmu.phase_compensation" in blocks[0].message and CORRECTION_NEXT_STEP in plan.next_steps
    correct(svc, recipe_id)
    plan, _ = run_spot(svc)
    assert {f.subject for f in plan.findings if f.rule_id == "R-CORR-01" and f.severity == "block"} == {
        "CMU1.open", "CMU1.short"}


@recipe("cmu.correction_open")
def test_stale_corrections_block_the_cv_plan(recipe_id: str, world: World, svc: B1500Service) -> None:
    correct(svc, "cmu.phase_compensation", recipe_id, "cmu.correction_short")
    fresh, run = run_spot(svc)
    assert fresh.tier == "needs_confirmation" and run is not None and run.ok
    world.clock.offset += timedelta(hours=8.5)  # policy corrections.max_age_h = 8
    stale, _ = run_spot(svc)
    assert stale.tier == "blocked" and CORRECTION_NEXT_STEP in stale.next_steps
    blocks = [f for f in stale.findings if f.rule_id == "R-CORR-01" and f.severity == "block"]
    assert {f.subject for f in blocks} == {"CMU1.phase", "CMU1.open", "CMU1.short"}
    assert all("older than 8 h" in f.message and f.limit == 8.0 for f in blocks)
    assert "not fresh: phase stale" in svc.station_status(refresh=False).corrections[ALIAS]


@recipe("cmu.correction_open")
def test_a_plan_frequency_outside_the_correction_list_blocks(recipe_id: str, svc: B1500Service) -> None:
    correct(svc, "cmu.phase_compensation")
    correct(svc, recipe_id, "cmu.correction_short", freqs_hz=[1e5, 1e6])
    assert run_spot(svc, freqs_hz=[1e5, 1e6])[0].tier == "needs_confirmation"
    plan, _ = run_spot(svc, freqs_hz=[1e5, 3e5])
    blocks = [f for f in plan.findings if f.rule_id == "R-CORR-01" and f.severity == "block"]
    assert {f.subject for f in blocks} == {"CMU1.open", "CMU1.short"}
    assert all(f.observed == 3e5 and "does not cover 300000 Hz" in f.message for f in blocks)


@recipe("cmu.correction_short")
def test_corrections_of_another_pin_map_do_not_count(recipe_id: str, svc: B1500Service) -> None:
    for name in ("cmu.phase_compensation", "cmu.correction_open", recipe_id):
        result = confirm(svc, name, "moscap-cmu")
        assert result.ok, result.message
    plan, _ = run_spot(svc)  # capacitor-cmu: same MFCMU, another landing
    blocks = [f for f in plan.findings if f.rule_id == "R-CORR-01" and f.severity == "block"]
    assert len(blocks) == 3 and all("another station profile or pin map" in f.message for f in blocks)


@recipe("cmu.correction_short")
def test_correction_lost_before_the_run_blocks_before_execution(recipe_id: str, world: World,
                                                                svc: B1500Service) -> None:
    """``cmu_correction_lost`` (a module power glitch) right after the pre-execute snapshot's ``*IDN?``: the live
    ``CORRST?``/``ADJ?`` read refuses the C-V before any source command, discards the lost records and the next
    validation already blocks."""
    correct(svc, "cmu.phase_compensation", "cmu.correction_open", recipe_id)
    plan = svc.validate_plan(**SPOT_REQUEST)
    assert plan.tier == "needs_confirmation", plan.message
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/capacitor_100p.yaml").read_text(encoding="utf-8"))
    scenario["faults"] = "lost"
    world.write_config("sim/faults/lost.yaml", {"description": "test", "faults": [
        {"kind": "cmu_correction_lost", "after_cmd": "*IDN?"}]})
    world.write_config("sim/scenarios/capacitor_lost.yaml", scenario)
    world.use_scenario("capacitor_lost")
    before = len(world.sim_log("capacitor_lost"))
    run = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]
    assert not run.ok and run.outcome == "refused" and run.error_code == "blocked_by_rules", run.message
    assert "CORRST? reports the open correction off" in run.message and CORRECTION_NEXT_STEP in run.next_steps
    sent = [r.mnemonic for r in world.sim_log("capacitor_lost")[before:] if r.outcome == "ok"]
    assert "CORRST?" in sent and not {"FC", "ACV", "DCV", "XE", "CN"} & set(sent)  # zero source commands
    assert store(world).records(ALIAS) == []  # lost on the instrument -> discarded from the store
    again = svc.validate_plan(**SPOT_REQUEST)
    assert again.tier == "blocked" and any("no phase correction record" in f.message for f in again.findings)


# -- keeping the other corrections ------------------------------------------------------------------------------------


@recipe("cmu.correction_short")
def test_the_short_run_keeps_the_open_correction(recipe_id: str, world: World, svc: B1500Service) -> None:
    _, open_run, short_run = correct(svc, "cmu.phase_compensation", "cmu.correction_open", recipe_id)
    assert kind_result(world, open_run.run_id)["setup"] == "rewritten"  # type: ignore[arg-type]
    facts = kind_result(world, short_run.run_id)  # type: ignore[arg-type]
    assert facts["setup"] == "kept" and facts["after_open"] is True and facts["after_short"] is True
    sent = [r.mnemonic for r in world.sim_log("capacitor_100p")]
    tail = sent[len(sent) - sent[::-1].index("CORRL?") - 1:]
    assert not {"CLCORR", "CORRL", "DCORR"} & set(tail)  # nothing that clears the open data after the read-back


@recipe("cmu.correction_short")
def test_another_frequency_list_clears_and_discards_the_open_correction(recipe_id: str, world: World,
                                                                        svc: B1500Service) -> None:
    correct(svc, "cmu.phase_compensation", "cmu.correction_open")
    result = confirm(svc, recipe_id, freqs_hz=[1e5, 1e6])
    assert result.ok and result.outcome == "completed_with_flags", result.message
    assert "open correction record(s) were discarded" in result.message and CORRECTION_NEXT_STEP in result.next_steps
    assert [r.kind for r in store(world).records(ALIAS)] == ["phase", "short"]


@recipe("cmu.phase_compensation")
def test_a_new_phase_compensation_discards_the_data_corrections(recipe_id: str, world: World,
                                                                svc: B1500Service) -> None:
    correct(svc, recipe_id, "cmu.correction_open", "cmu.correction_short")
    again = confirm(svc, recipe_id)
    assert again.outcome == "completed_with_flags" and "open, short correction record(s)" in again.message
    facts = kind_result(world, again.run_id)  # type: ignore[arg-type]
    assert facts["after_open"] is False and facts["after_short"] is False and facts["after_phase"] is True
    assert [r.kind for r in store(world).records(ALIAS)] == ["phase", "phase"]


@recipe("cmu.correction_open")
def test_a_device_clear_in_the_cleanup_clears_the_correction_store(recipe_id: str, world: World,
                                                                   svc: B1500Service) -> None:
    """The first cleanup attempt fails, the retry follows a device clear, which switches the corrections off like
    ``*RST`` (PG p175 (2-87)): the store is cleared and the run is flagged."""
    correct(svc, "cmu.phase_compensation")
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/capacitor_100p.yaml").read_text(encoding="utf-8"))
    scenario["faults"] = "flaky"
    world.write_config("sim/faults/flaky.yaml", {"description": "test", "faults": [
        {"kind": "cleanup_failure", "count": 1}]})
    world.write_config("sim/scenarios/capacitor_flaky.yaml", scenario)
    world.use_scenario("capacitor_flaky")
    result = confirm(svc, recipe_id)
    assert result.ok and result.outcome == "completed_with_flags", result.message
    assert "device clear" in result.message and store(world).records(ALIAS) == []
    assert result.cleanup_verified == "sim_state"


def test_station_status_reports_the_correction_freshness(world: World, svc: B1500Service) -> None:
    assert svc.station_status(refresh=False).corrections == {ALIAS: "not fresh: phase missing; open missing; short "
                                                                    "missing"}
    correct(svc, "cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")
    status = svc.station_status(refresh=True)
    assert status.corrections[ALIAS].startswith("fresh: phase 0.0 h, open 0.0 h, short 0.0 h")
    assert "corrections not fresh" not in status.message
