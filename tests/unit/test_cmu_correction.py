"""Unit tests of the MFCMU correction work package (WP8.2): the set-up queries ``CORRL?``/``DCORR?`` (parser, driver,
simulator), the kind ``cmu_correction`` compile, the MFCMU side binding of correction roles (planner, R-PIN-01,
R-DUT-01), the probe-state prompt of R-ALWAYS-01, R-CORR-01's next step, the correction store's ``discard`` and the
executor wiring of ``catalog/corrections.py`` (reconciliation, records, device clear), and the ``station_status``
freshness text."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from b1500_test_agent.archive.corrections import CorrectionStore
from b1500_test_agent.catalog.corrections import lost_kinds, read_live_corrections, reconcile, record_run
from b1500_test_agent.catalog.kinds import CmuCorrectionKind
from b1500_test_agent.catalog.kinds.cmu_correction import MAX_CORRECTION_FREQS, live_after, same_frequencies
from b1500_test_agent.catalog.planner import Planner, bind_roles
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError, RawAcquisition
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver, CmuSignal
from b1500_test_agent.driver.cmu_data import parse_corrl_count, parse_corrl_frequency, parse_dcorr
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope, PlanRequest
from b1500_test_agent.models.recipe import RoleSpec, side_terminals
from b1500_test_agent.models.run import CleanupReport, CleanupStep
from b1500_test_agent.models.station import (
    CmuCorrectionLive,
    CmuStandards,
    CorrectionCheck,
    CorrectionFreshness,
    CorrectionRecord,
    Identity,
    LoadStandard,
)
from b1500_test_agent.rules.builtin.cmu import CORRECTION_NEXT_STEP, correction_next_steps
from b1500_test_agent.service.status import freshness_text
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import load_scenario, noiseless
from tests.unit import rules_factory_v2 as v2
from tests.unit.rules_factory import T0, bundle, dut, engine, example_station, pin_map_exact

pytestmark = pytest.mark.cmu

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
KIND = CmuCorrectionKind()
CMU = 7
CAP = pin_map_exact("capacitor-cmu", {"a": "7H", "b": "7L"})
MOSCAP = pin_map_exact("moscap-cmu", {"gate": "7H", "bulk": "7L"})
IDN = "Keysight Technologies,B1500A,SIM0000001,A.06.01.2024.0101"
SHA = "a" * 64


def plan(recipe_id: str, pin_map=CAP, dut_profile: str | None = None, duts=(), station=None, **params):
    cfg = bundle(pin_maps=[pin_map], duts=list(duts), station_profile=station)
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map.name, "dut_profile": dut_profile,
                                      "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


def sim_driver(envelope: CompiledEnvelope) -> tuple[B1500Driver, SimTransport]:
    transport = SimTransport(noiseless(load_scenario("capacitor_100p")), state_file=None)
    transport.open()
    driver = B1500Driver(transport, OutputGuard(envelope))
    driver.enable([CMU])
    return driver, transport


# -- CORRL? / DCORR?: parser, simulator, driver -----------------------------------------------------------------------


def test_corrl_and_dcorr_answers_parse() -> None:
    assert parse_corrl_count("23") == 23 and parse_corrl_count("+0") == 0
    assert parse_corrl_frequency("10000") == 1e4 and parse_corrl_frequency("+1.20000E+06") == 1.2e6
    assert parse_dcorr("400,0.00001,49.8765") == (400, 1e-5, 49.8765)  # PG p390 (4-72) example
    for bad in ("x", "-1", ""):
        with pytest.raises(FlexParseError):
            parse_corrl_count(bad)
    for bad in ("0", "-5", "nan", "abc"):
        with pytest.raises(FlexParseError):
            parse_corrl_frequency(bad)
    for bad in ("400,1", "300,0,0", "400,x,0", "400,0,inf"):
        with pytest.raises(FlexParseError):
            parse_dcorr(bad)


def test_builders_reject_a_zero_index() -> None:
    assert flex.corrl_q(7) == "CORRL? 7" and flex.corrl_q(7, 1) == "CORRL? 7,1" and flex.dcorr_q(7, "open") == \
        "DCORR? 7,1"
    with pytest.raises(ValueError, match="starts at 1"):
        flex.corrl_q(7, 0)


def test_the_driver_reads_the_list_back_and_may_then_measure_without_rewriting_it() -> None:
    envelope = CompiledEnvelope(channels={CMU: ChannelEnvelope(
        role="a", max_abs_v=0.0, max_abs_i=1e-3, function="cmu_high",
        ac=AcEnvelope(max_vrms=0.05, max_dc_v=0.0, f_min_hz=1e3, f_max_hz=5e6))})
    driver, transport = sim_driver(envelope)
    assert driver.correction_frequencies(CMU) == ()
    driver.set_correction_frequencies(CMU, [1e6, 1e5])
    driver.set_correction_standard(CMU, "short", 1e-9, 0.25)
    assert driver.correction_standard(CMU, "short") == (400, 1e-9, 0.25)
    assert driver.correction_standard(CMU, "open") == (100, 0.0, 0.0)  # never set: the ideal open (sim convention)

    fresh, _ = B1500Driver(transport, OutputGuard(envelope)), None  # a new transaction: nothing written by it
    fresh.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03))
    assert fresh.correction_frequencies(CMU) == (1e5, 1e6)
    before = len(transport.instrument.command_log)
    assert fresh.measure_correction(CMU, "open") == 0
    assert [r.command for r in transport.instrument.command_log[before:]] == ["CORR? 7,1"]  # no CLCORR/CORRL


def test_the_simulator_refuses_an_index_outside_the_list() -> None:
    transport = SimTransport(noiseless(load_scenario("capacitor_100p")), state_file=None)
    transport.open()
    transport.write("CLCORR 7,2")
    assert transport.query("CORRL? 7") == "23" and transport.query("CORRL? 7,23") == "5000000"
    transport.write("CORRL? 7,24")
    assert transport.query("ERRX?").startswith("120")


# -- kind compile ------------------------------------------------------------------------------------------------------


def test_phase_compensation_compiles_to_no_programmed_signal() -> None:
    record = plan("cmu.phase_compensation")
    assert record.tier == "needs_confirmation" and record.rules.confirm_reasons == ["physical_setup"]
    entry = record.envelope.channels[CMU]
    assert entry.role == "high" and entry.function == "cmu_high" and entry.max_abs_v == 0.0
    assert entry.ac == AcEnvelope(max_vrms=0.0, max_dc_v=0.0, f_min_hz=1e3, f_max_hz=5e6)
    assert record.flex_preview[:6] == ["CN 7", "CORRST 7,1,0", "CORRST 7,2,0", "CORRST 7,3,0", "ADJ 7,1", "ADJ? 7,1"]
    assert record.program["correction"] == "phase" and record.program["alias"] == "CMU1"
    assert record.program["timeout_s"] == 90.0 and "lift the probes" in record.program["setup"]  # type: ignore[operator]
    assert record.estimate.duration_s == 35.0 and record.mode == "sync"


def test_open_correction_compiles_its_frequency_list_and_ideal_standards() -> None:
    record = plan("cmu.correction_open")
    program = record.program
    assert program["default_list"] is True and len(program["freqs_hz"]) == 23  # type: ignore[arg-type]
    assert program["standards"] == {"open": [100.0, 0.0, 0.0], "short": [400.0, 0.0, 0.0]}
    assert record.envelope.channels[CMU].ac == AcEnvelope(max_vrms=0.03, max_dc_v=0.0, f_min_hz=1e3, f_max_hz=5e6)
    assert "CLCORR 7,2" in record.flex_preview and "CORRL 7,1000" not in record.flex_preview
    assert record.flex_preview.index("CORRL? 7") < record.flex_preview.index("CLCORR 7,2")
    custom = plan("cmu.correction_short", freqs_hz=[1e6, 1e5, 1e5])
    assert custom.program["freqs_hz"] == [1e5, 1e6] and custom.program["default_list"] is False
    assert ["CLCORR 7,1", "CORRL 7,100000", "CORRL 7,1000000"] == [
        c for c in custom.flex_preview if c.startswith(("CLCORR", "CORRL "))]
    assert custom.estimate.duration_s == pytest.approx(3.0) and custom.program["timeout_s"] == 14.0


def test_load_needs_the_station_standard_and_the_list_is_bounded() -> None:
    station = example_station().model_copy(update={"corrections": {"CMU1": CmuStandards(load=LoadStandard(
        ls_h=1e-9, rs_ohm=100.0))}})
    load = plan("cmu.correction_load", station=station)
    assert load.program["standards"]["load"] == [400.0, 1e-9, 100.0]  # type: ignore[index]
    assert "DCORR 7,3,400,1E-09,100" in load.flex_preview
    params = {"correction": Quantity(value="load"), "freqs_hz": Quantity(value=[1e5], unit="Hz"),
              "ac_vrms": Quantity(value=0.03, unit="V")}
    recipe = REGISTRY.get("cmu.correction_load")
    binding = bind_roles(recipe, CAP, example_station(), "capacitor-cmu")
    with pytest.raises(CompileError, match="corrections.CMU1.load"):
        KIND.compile(recipe, params, binding, example_station())
    many = {**params, "correction": Quantity(value="open"),
            "freqs_hz": Quantity(value=[1e3 + i for i in range(MAX_CORRECTION_FREQS + 1)], unit="Hz")}
    with pytest.raises(CompileError, match="at most 64"):
        KIND.compile(REGISTRY.get("cmu.correction_open"), many, binding, example_station())


def test_unbound_roles_compile_to_an_empty_envelope_and_r_pin_01_blocks() -> None:
    record = plan("cmu.correction_open", pin_map=pin_map_exact("smus", {"a": 3, "b": "GNDU"}))
    assert record.tier == "blocked" and record.envelope.channels == {} and record.program["channel"] is None
    assert any(f.rule_id == "R-PIN-01" and "no terminal to an MFCMU H side" in f.message for f in record.rules.findings)


def test_helpers_compare_lists_and_read_the_after_state() -> None:
    assert same_frequencies([1e5, 1e6], (1e6, 1e5)) and not same_frequencies([1e5], [1e5, 1e6])
    assert same_frequencies(list(flex.CLCORR_DEFAULT_FREQS_HZ), sorted(flex.CLCORR_DEFAULT_FREQS_HZ))
    assert live_after({"correction": "open"}) is None
    live = live_after({"after_phase": True, "after_open": True, "after_short": False, "after_load": None})
    assert live == CmuCorrectionLive(corr_state={"open": True, "short": False}, phase=True)


# -- side binding, R-PIN-01, R-DUT-01, R-ALWAYS-01, R-CORR-01 -------------------------------------------------------


def test_cmu_side_binding_is_only_for_mfcmu_roles() -> None:
    with pytest.raises(ValidationError, match="only MFCMU roles"):
        RoleSpec(function="bias_v", bind="cmu_side")
    terminals = {"gate": "7H", "bulk": "7L", "drain": "7L", "x": 3}
    assert side_terminals("cmu_high", terminals) == ["gate"]
    assert side_terminals("cmu_low", terminals) == ["bulk", "drain"]
    assert RoleSpec(function="cmu_low", bind="cmu_side").pin_terminal("low", terminals) == "bulk"
    assert RoleSpec(function="cmu_low").pin_terminal("low", terminals) is None


def test_correction_roles_bind_to_the_moscap_terminals_without_a_dut_profile() -> None:
    record = plan("cmu.correction_short", pin_map=MOSCAP)
    high, low = record.binding.roles["high"], record.binding.roles["low"]
    assert (high.terminal, high.channel, high.cmu_side) == ("gate", CMU, "H")
    assert (low.terminal, low.channel, low.cmu_side) == ("bulk", CMU, "L")
    assert record.tier == "needs_confirmation" and not [f for f in record.rules.findings if f.severity == "block"]


def test_a_dut_profile_given_anyway_is_checked() -> None:
    no_ac = dut("moscap-x", "moscap", gate=(3.0, 1e-6), bulk=(3.0, 1e-6))
    record = plan("cmu.correction_open", pin_map=MOSCAP, dut_profile="moscap-x", duts=[no_ac])
    assert record.tier == "blocked"
    assert any(f.rule_id == "R-CMU-01" and "declares no AC envelope" in f.message for f in record.rules.findings)


def test_r_always_01_carries_the_probe_state_prompt() -> None:
    finding = next(f for f in plan("cmu.correction_short").rules.findings if f.rule_id == "R-ALWAYS-01")
    assert finding.reason == "physical_setup" and "land the probes on a short" in finding.message


def test_r_corr_01_blocks_name_the_recipe_and_the_card() -> None:
    cfg, ctx = v2.cv(corrections={})
    findings = engine(cfg).evaluate(ctx, "plan").findings
    blocks = [f for f in findings if f.rule_id == "R-CORR-01" and f.severity == "block"]
    assert blocks and all("card cmu/cmu-correction" in f.message for f in blocks)
    assert correction_next_steps(blocks) == [CORRECTION_NEXT_STEP]
    assert correction_next_steps([]) == [] and correction_next_steps([], renew=True) == [CORRECTION_NEXT_STEP]


# -- store and executor wiring ----------------------------------------------------------------------------------------


def record(kind: str, ts: datetime = T0) -> CorrectionRecord:
    return CorrectionRecord(kind=kind, freqs_hz=[] if kind == "phase" else [1e5], run_id="S20261122T000000Z-0001",
                            ts=ts, idn=IDN, pin_map_sha=SHA, station_sha=SHA)


def test_store_discard_removes_only_the_named_kinds(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    for kind in ("phase", "open", "short"):
        store.add("CMU1", record(kind))
    assert store.discard("CMU1", ["load"]) == 0
    assert store.discard("CMU1", ["open", "short"]) == 2 and [r.kind for r in store.records("CMU1")] == ["phase"]
    assert store.discard("CMU1", ["phase"]) == 1 and not store.path("CMU1").exists()


def test_reconcile_discards_what_the_instrument_lost(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    for kind in ("phase", "open", "short"):
        store.add("CMU1", record(kind))
    live = CmuCorrectionLive(corr_state={"open": True, "short": False, "load": False}, phase=None)
    assert lost_kinds(live) == ["short", "load"]
    assert reconcile(store, "CMU1", live) == ["short"]  # no load record; phase unknown -> kept
    assert sorted(r.kind for r in store.records("CMU1")) == ["open", "phase"]


class _Driver:
    """``correction_state`` stand-in."""

    def __init__(self, live: CmuCorrectionLive) -> None:
        self.live = live
        self.calls: list[int] = []

    def correction_state(self, ch: int) -> CmuCorrectionLive:
        self.calls.append(ch)
        return self.live


def test_read_live_corrections_only_for_plans_with_an_mfcmu(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    store.add("CMU1", record("open"))
    cv_plan = v2.cv()[1].plan
    live = v2.live()
    driver = _Driver(CmuCorrectionLive(corr_state={"open": False}, phase=True))
    enriched, changes = read_live_corrections(driver, cv_plan, live, store)  # type: ignore[arg-type]
    assert driver.calls == [CMU] and enriched.cmu_corrections == {"CMU1": driver.live}
    assert changes.discarded == {"CMU1": ["open"]} and "run cmu.correction_open again" in changes.notes[0]
    smu_plan = plan("cmu.correction_open", pin_map=pin_map_exact("smus", {"a": 3}))
    unchanged, nothing = read_live_corrections(driver, smu_plan, live, store)  # type: ignore[arg-type]
    assert unchanged is live and not nothing.changed and driver.calls == [CMU]


def _raw(kind: str, **after: object) -> RawAcquisition:
    return RawAcquisition(kind_result={"correction": kind, "result_code": 0, "after_phase": True, "after_open": False,
                                       "after_short": False, "after_load": False, **after})  # type: ignore[arg-type]


def test_record_run_writes_the_record_and_discards_what_the_run_invalidated(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    store.add("CMU1", record("open"))
    store.add("CMU1", record("short"))
    phase_plan = plan("cmu.phase_compensation")
    snapshot = v2.live().model_copy(update={"identity": Identity(vendor="Keysight Technologies", model="B1500A",
                                                                 serial="SIM0000001", firmware="A", raw=IDN)})
    now = T0 + timedelta(minutes=5)
    changes = record_run(store, plan=phase_plan, raw=_raw("phase"), live=snapshot, cleanup=None, completed=True,
                         run_id="S20261122T000500Z-0002", now=now, station=example_station())
    assert changes.discarded == {"CMU1": ["open", "short"]} and "phase compensation invalidates" in changes.notes[0]
    assert changes.record is not None and changes.record.kind == "phase" and changes.record.ts == now
    assert [r.kind for r in store.records("CMU1")] == ["phase"] and changes.path == store.path("CMU1")
    failed = record_run(store, plan=phase_plan, raw=_raw("phase", after_phase=False), live=snapshot, cleanup=None,
                        completed=False, run_id="S20261122T000600Z-0003", now=now, station=example_station())
    assert failed.record is None and failed.discarded == {} and store.records("CMU1") == []  # phase lost: discarded


def test_a_device_clear_in_the_cleanup_clears_every_mfcmu(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    store.add("CMU1", record("phase"))
    cleanup = CleanupReport(steps=[CleanupStep(step="device_clear", ok=True, attempt=2)], verified="sim_state",
                            outputs_after={}, latched_fault=False)
    smu_plan = plan("cmu.correction_open", pin_map=pin_map_exact("smus", {"a": 3}))
    changes = record_run(store, plan=smu_plan, raw=None, live=None, cleanup=cleanup, completed=True,
                         run_id="S20261122T000500Z-0002", now=T0, station=example_station())
    assert changes.cleared == ["CMU1"] and "device clear" in changes.notes[0] and store.records("CMU1") == []


def test_station_status_freshness_text() -> None:
    checks = [CorrectionCheck(kind="phase", state="fresh", run_id="S20261122T000000Z-0001", age_h=0.25),
              CorrectionCheck(kind="open", state="stale", run_id="S20261122T000000Z-0001", age_h=9.04),
              CorrectionCheck(kind="short", state="missing")]
    stale = CorrectionFreshness(cmu="CMU1", checked_at=datetime.now(UTC), max_age_h=8, checks=checks, fresh=False)
    assert freshness_text(stale) == "not fresh: phase fresh 0.2 h; open stale 9.0 h; short missing"
    good = CorrectionFreshness(cmu="CMU1", checked_at=datetime.now(UTC), max_age_h=8, checks=checks[:1], fresh=True)
    assert freshness_text(good) == "fresh: phase 0.2 h"


def test_r_cmu_01_checks_the_correction_signal() -> None:
    """R-CMU-01 is live on the correction plans: above the 50 mVrms soft band needs ``soft_cmu``; a frequency outside
    the MFCMU's 1 kHz..5 MHz is outside the recipe range (R-PARAM-01 blocks; the kind does not compile it, so no
    envelope exists for any other rule to pass)."""
    loud = plan("cmu.correction_open", ac_vrms=0.1)
    assert loud.tier == "needs_confirmation" and "soft_cmu" in loud.rules.confirm_reasons
    assert any(f.rule_id == "R-CMU-01" and f.reason == "soft_cmu" for f in loud.rules.findings)
    high = plan("cmu.correction_short", freqs_hz=[1e5, 6e6])
    rules = {f.rule_id for f in high.rules.findings if f.severity == "block"}
    assert high.tier == "blocked" and "R-PARAM-01" in rules and high.envelope.channels == {}
