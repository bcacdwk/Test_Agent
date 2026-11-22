"""Selector routes in the driver and the transaction (blueprint v2 2.5, 2.6 steps 5 and 8; WP9.2): the guarded
``ERSSP``/``SSP``/``SAP`` routes, the rest-only cleanup guard, the read-back, ``Transaction.apply_routes``, the
cleanup's ``routes`` step and switch verification, the snapshot's ``switch_states`` and the station status."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.errors import RouteNotVerified
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops.switch import rest_guard
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.routing import Route, SwitchSpec
from b1500_test_agent.models.sim import SelectorStuck
from b1500_test_agent.models.station import LiveState, StationProfile
from b1500_test_agent.service.status import switch_status
from b1500_test_agent.session.routes import cleanup_scope, verify_routes
from b1500_test_agent.transport.sim import SimTransport
from tests.safety.helpers import CLEANUP_ORDER, Harness, make_harness
from tests.sim.helpers import load_scenario, noiseless
from tests.sim.selector_helpers import SEL1, SEL2, SELECTORS, at_rest, recorded_station, selector_states

SWITCHES = {s.id: s for s in SELECTORS}
TO_SMU = Route(switch="SEL1", output="OUT1", state="smu")
TO_PGU = Route(switch="SEL1", output="OUT1", state="pgu")
PGU_OPEN = Route(switch="SEL1", output="OUT1", state="pgu_open")
ENVELOPE = CompiledEnvelope(channels={}, routes=frozenset({TO_SMU, TO_PGU, PGU_OPEN}))

SCUU = SwitchSpec.model_validate({"id": "SCUU1", "kind": "scuu", "present": None, "rest": "smu", "ports": {
    "OUT1": {"index": 6, "inputs": {"smu": 6, "cmu": 7}}, "OUT2": {"index": 5, "inputs": {"smu": 5, "cmu": 7}}}})
ASU3 = SwitchSpec.model_validate({"id": "ASU3", "kind": "asu", "present": None, "rest": "smu",
                                  "ports": {"OUT": {"index": 3, "inputs": {"smu": 3}}}})


def lab_sim() -> SimTransport:
    sim = SimTransport(noiseless(load_scenario("fefet_lab")), state_file=None)
    sim.open()
    return sim


def driver(sim: SimTransport, envelope: CompiledEnvelope | None = ENVELOPE,
           switches: tuple[SwitchSpec, ...] = SELECTORS) -> B1500Driver:
    return B1500Driver(sim, None if envelope is None else OutputGuard(envelope, switches=switches))


def writes(sim: SimTransport) -> list[str]:
    return [r.command for r in sim.instrument.command_log if r.outcome == "ok" and not r.mnemonic.endswith("?")]


# -- driver -----------------------------------------------------------------------------------------------------------


def test_apply_routes_sends_the_control_mode_then_one_erssp_per_output() -> None:
    sim = lab_sim()
    d = driver(sim)
    assert d.apply_routes([TO_PGU, Route(switch="SEL2", output="OUT1", state="open")], SWITCHES) == [
        "SEL1.OUT1", "SEL2.OUT1"]
    assert writes(sim) == ["ERMOD 1", "ERSSP 0,2", "ERSSP 2,0"]  # SEL2.OUT1 -> open: its rest state, allowed
    assert d.switch_states(SELECTORS) == {"SEL1.OUT1": "pgu", "SEL1.OUT2": "open", "SEL2.OUT1": "open",
                                          "SEL2.OUT2": "open"}


@pytest.mark.parametrize("bad", [
    Route(switch="SEL1", output="OUT2", state="pgu"),  # not a route of the plan
    Route(switch="SEL1", output="OUT2", state="pgu_open"),  # CH 2: no PGU open (port 1)
    Route(switch="SEL2", output="OUT2", state="pgu_open"),  # CH 2 of the second selector (port 3)
])
def test_a_refused_route_sends_nothing_of_its_phase(bad: Route) -> None:
    sim = lab_sim()
    with pytest.raises(EnvelopeViolation) as raised:
        driver(sim).apply_routes([TO_SMU, bad], SWITCHES)
    assert raised.value.reason == "route_not_allowed"
    assert writes(sim) == []  # TO_SMU (allowed) is not sent either: the whole phase is checked first


def test_routes_need_a_guard_declared_outputs_and_flex_switches() -> None:
    sim = lab_sim()
    with pytest.raises(EnvelopeViolation, match="no OutputGuard"):
        driver(sim, envelope=None).apply_routes([TO_SMU], SWITCHES)
    rsu = SwitchSpec.model_validate({"id": "RSU201", "kind": "rsu", "present": True, "rest": "open",
                                     "ports": {"OUT": {"index": 201, "inputs": {"wgfmu": 201}}}})
    with pytest.raises(ValueError, match="WGFMU library"):
        driver(sim).apply_routes([Route(switch="RSU201", output="OUT", state="wgfmu")], {**SWITCHES, "RSU201": rsu})
    with pytest.raises(ValueError, match="not a declared switch output"):
        driver(sim).apply_routes([Route(switch="SEL9", output="OUT1", state="smu")], SWITCHES)
    with pytest.raises(ValueError, match="named twice"):
        driver(sim).apply_routes([TO_SMU, TO_PGU], SWITCHES)
    assert writes(sim) == []


def test_the_rest_guard_admits_rest_states_only() -> None:
    guard = rest_guard(SELECTORS)
    guard.check_route(Route(switch="SEL1", output="OUT2", state="open"))
    with pytest.raises(EnvelopeViolation):
        guard.check_route(TO_SMU)
    with pytest.raises(EnvelopeViolation):
        guard.check_channel(3)  # no source at all


def test_rest_switch_returns_a_selector_through_the_rest_guard_without_a_plan() -> None:
    sim = lab_sim()
    sim.write("ERMOD 1")
    sim.write("ERSSP 0,2")
    sim.write("ERSSP 3,1")
    d = driver(sim, envelope=None)  # a safe_shutdown transaction has no plan guard
    assert d.rest_switch(SEL1) == "SEL1: ERMOD 1; ports 0, 1 -> open"
    assert d.rest_switch(SEL2).startswith("SEL2: ERMOD 1")
    assert at_rest(sim)


def test_scuu_and_asu_that_do_not_answer_are_not_installed() -> None:
    sim = lab_sim()  # the lab mainframe has neither an SCUU nor an ASU
    d = driver(sim, envelope=None)
    assert "not installed" in d.rest_switch(SCUU) and "not installed" in d.rest_switch(ASU3)
    assert d.switch_states([SCUU, ASU3]) == {}
    ok, _, after = verify_routes(d, [SCUU, ASU3])
    assert ok and after == {"SCUU1.OUT1": "not installed", "SCUU1.OUT2": "not installed", "ASU3.OUT": "not installed"}
    assert writes(sim) == []  # read first, nothing to restore


def test_an_scuu_with_both_outputs_open_counts_as_rest() -> None:
    assert SCUU.at_rest("OUT1", "open") and SCUU.at_rest("OUT1", "smu") and not SCUU.at_rest("OUT1", "cmu")
    assert not SEL1.at_rest("OUT1", "smu") and SEL1.at_rest("OUT2", "open") and not SEL1.at_rest("OUT9", "open")
    with pytest.raises(ValueError, match="rests on its SMU side"):
        SwitchSpec.model_validate({**ASU3.model_dump(mode="json"), "rest": "cmu",
                                   "ports": {"OUT": {"index": 3, "inputs": {"smu": 3, "cmu": None}}}})


def test_switch_states_skip_selectors_while_the_control_mode_is_off() -> None:
    sim = lab_sim()
    d = driver(sim, envelope=None)
    assert d.switch_states(SELECTORS) == {}  # ERMOD? 0: ERSSP? is not asked (the snapshot sends no setting)
    assert [r.command for r in sim.instrument.command_log] == ["ERMOD?"]


# -- transaction ------------------------------------------------------------------------------------------------------


def harness(tmp_path: Path) -> Harness:
    return make_harness(tmp_path, noiseless(load_scenario("fefet_lab")), switches=SELECTORS)


def test_apply_routes_waits_the_settle_time_verifies_and_audits(tmp_path: Path) -> None:
    h = harness(tmp_path)
    with h.transaction(envelope=ENVELOPE, intent="routes") as tx:
        start = h.sim.instrument.clock
        states = tx.apply_routes([TO_PGU], phase="program")
        assert h.sim.instrument.clock - start >= 0.01  # the relay settle time passed before the read-back
        assert states == {"SEL1.OUT1": "pgu", "SEL1.OUT2": "open"}
        tx.apply_routes([PGU_OPEN], phase="hold")
    events = [e for e in h.events() if e.ev == "checkpoint" and e.data and e.data.get("label") == "routes"]
    assert [(e.data["phase"], e.data["routes"]) for e in events] == [  # type: ignore[index]
        ("program", "SEL1.OUT1->pgu"), ("hold", "SEL1.OUT1->pgu_open")]
    assert "SEL1.OUT1 pgu" in str(events[0].data["readback"])  # type: ignore[index]
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state" and at_rest(h.sim)
    assert tx.cleanup.switches_after == {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open",
                                         "SEL2.OUT2": "open"}


def test_cleanup_step_5_runs_between_dz_and_cl_for_every_declared_port(tmp_path: Path) -> None:
    h = harness(tmp_path)
    with h.transaction(envelope=ENVELOPE, intent="routes") as tx:
        tx.apply_routes([TO_SMU], phase="read")
    steps = [s.step for s in tx.cleanup.steps]  # type: ignore[union-attr]
    assert steps == ["spgu_stop", "zero", "routes", "disconnect", "drain_errors", "verify"]
    assert [CLEANUP_ORDER.index(s) for s in steps] == sorted(CLEANUP_ORDER.index(s) for s in steps)
    sent = [r.command for r in h.log if r.outcome == "ok"]
    dz = sent.index("DZ")
    assert sent[dz:sent.index("CL", dz) + 1] == ["DZ", "ERMOD 1", "ERSSP 0,0", "ERSSP 1,0", "ERMOD 1",
                                                  "ERSSP 2,0", "ERSSP 3,0", "CL"]
    assert sent[-5:] == ["ERMOD?", "ERSSP? 0", "ERSSP? 1", "ERSSP? 2", "ERSSP? 3"]  # step 8, queries only


def test_a_stuck_selector_fails_the_route_and_latches_the_fault(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.sim.inject(SelectorStuck(port=0, state="pgu"))
    with pytest.raises(RouteNotVerified) as raised, h.transaction(envelope=ENVELOPE, intent="routes") as tx:
        tx.apply_routes([TO_SMU], phase="read")
    assert raised.value.readback == {"SEL1.OUT1": "pgu"}
    assert tx.cleanup is not None and tx.cleanup.verified == "unverified" and tx.cleanup.latched_fault
    assert tx.cleanup.switches_after["SEL1.OUT1"] == "pgu"
    assert [s.attempt for s in tx.cleanup.steps if s.step == "routes"] == [1, 2]  # device clear and one retry
    assert h.session.fault_latch.get() is not None
    assert any(e.ev == "cleanup_unverified" for e in h.events())


def test_safe_shutdown_returns_a_selector_a_human_left_on_pgu(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.sim.open()
    for command in ("ERMOD 1", "ERSSP 0,2", "ERSSP 2,1"):
        h.sim.write(command)
    h.sim.save_state()
    h.sim.close()
    report = h.session.safe_shutdown(reason="test")
    assert report.verified == "sim_state" and not report.latched_fault
    assert selector_states(h.sim) == {0: 0, 1: 0, 2: 0, 3: 0}


def test_the_transaction_snapshot_reads_switch_states_after_the_control_mode(tmp_path: Path) -> None:
    h = harness(tmp_path)
    with h.transaction(envelope=ENVELOPE, intent="routes") as tx:
        live = tx.snapshot()
    assert live.switch_states == {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open"}
    sent = [r.command for r in h.log if r.outcome == "ok"]
    assert sent[sent.index("LOP?") + 1:sent.index("LOP?") + 4] == ["ERMOD?", "ERMOD 1", "ERSSP? 0"]
    read_only = h.session.snapshot()  # the status snapshot: queries only; the mode is on now
    assert read_only.switch_states == live.switch_states


def test_a_session_without_switches_touches_none(tmp_path: Path) -> None:
    h = make_harness(tmp_path, noiseless(load_scenario("fefet_lab")))
    with h.transaction(envelope=CompiledEnvelope(channels={}), intent="none") as tx:
        assert tx.snapshot().switch_states is None
    assert "routes" not in [s.step for s in tx.cleanup.steps]  # type: ignore[union-attr]
    assert not [r for r in h.log if r.mnemonic.startswith(("ERMOD", "ERSSP"))]


def test_cleanup_scope_and_station_status_lines() -> None:
    station = StationProfile.model_validate(recorded_station())
    assert [s.id for s in cleanup_scope(station.switches)] == ["SEL1", "SEL2", "SCUU1", "ASU3", "ASU4"]
    live = LiveState.model_validate({"backend": "sim", "resource": "SIM::x", "taken_at": "2026-11-20T00:00:00Z",
                                     "switch_states": {"SEL1.OUT1": "pgu", "SEL1.OUT2": "open"}})
    lines = switch_status(station, live)
    assert lines["SEL1.OUT1"] == "off rest: pgu (rest open)" and lines["SEL1.OUT2"] == "open"
    assert lines["SEL2.OUT1"] == "not read" and lines["SCUU1.OUT1"] == "not read"
    absent = station.model_copy(update={"switches": [s.model_copy(update={"present": False})
                                                     for s in station.switches]})
    assert switch_status(absent, live) == {} and cleanup_scope(absent.switches) == []
