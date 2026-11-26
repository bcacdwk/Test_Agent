"""The RSU "From SMU" input limit on the simulator (WP21.13; WG p20 (1-8) "Or the RSU will be damaged" above +-25 V
at the From SMU input; WG p16 (1-4) "Maximum current: 100 mA").

- ``ConfigBundle.planning_station`` (simulator only): an RSU input recorded ``null`` takes the scenario's ``rsu_smu``
  cabling (``nmos_wgfmu``: SMU4 -> RSU201, SMU3 -> RSU202), as a null selector input takes the scenario's selector
  cabling; recorded inputs are never replaced, and the station profile itself is untouched.
- ``validate_plan`` on the lab example station: an SMU plan above +-25 V on SMU3 is blocked by R-RSU-01 on that
  scenario (SMU3 feeds RSU202), and only needs the usual confirmations on a scenario without RSU cabling; a plan
  within the limit runs, and the executor's session (whose ``OutputGuard`` holds the switches) sees the same cabling.
- The ``OutputGuard`` at run time: a body that leaves a wide (stale or buggy) envelope's level on SMU3 beyond 25 V
  never reaches the simulator; the cleanup verifies and the global invariant holds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.catalog.planner import planning_station
from b1500_test_agent.config import load_config
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.routing import rsu_smu_inputs
from b1500_test_agent.models.station import StationProfile
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.test_plan_goldens import GENERIC_3T
from tests.safety.helpers import DRAIN, GATE, assert_global_invariant, make_harness
from tests.sim.helpers import load_scenario, noiseless
from tests.sim.spgu_pulse_helpers import repo_bundle

pytestmark = pytest.mark.wgfmu

SWEEP = {"recipe_id": "generic.smu_staircase", "pin_map": "generic-3t", "dut_profile": "generic-3t"}
"""``generic.smu_staircase`` (range +-42 V) on the test pin map ``generic-3t``: sweep SMU3, bias SMU4, ground GNDU."""


def example_station(**rsu_inputs: dict[str, Any]) -> dict[str, Any]:
    """``config/station.example.yaml`` with the ``inputs`` of RSU ``id`` replaced (``RSU202={"wgfmu": 202, ...}``)."""
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    for switch in station["switches"]:
        if switch["id"] in rsu_inputs:
            switch["ports"]["OUT"]["inputs"] = rsu_inputs[switch["id"]]
    return station


def from_smu(switches: Any) -> dict[str, int | None]:
    """RSU output -> the SMU on its From SMU input (``None`` = unknown) of a station's switches."""
    return {item.target: item.channel for item in rsu_smu_inputs(switches)}


def prepare(world: World, scenario: str) -> None:
    world.use_scenario(scenario)
    for rel, data in GENERIC_3T.items():
        world.write_config(rel, data)


# -- planning station --------------------------------------------------------------------------------------------------


def test_planning_station_takes_the_scenarios_rsu_cabling_on_the_simulator_only(tmp_path: Path) -> None:
    sim = repo_bundle(tmp_path / "a", "nmos_wgfmu")
    assert from_smu(sim.station.switches) == {"RSU201.OUT": None, "RSU202.OUT": None}  # the profile is untouched
    assert from_smu(planning_station(sim).switches) == {"RSU201.OUT": 4, "RSU202.OUT": 3}  # rsu_smu {201: 4, 202: 3}
    filled = planning_station(sim).switch("RSU202")
    assert filled is not None and filled.certainty == "unverified"  # R-ROUTE-02 still asks
    plain = repo_bundle(tmp_path / "b", "nmos_basic")  # no RSU cabling in the scenario: nothing to fill
    assert from_smu(planning_station(plain).switches) == {"RSU201.OUT": None, "RSU202.OUT": None}
    recorded = repo_bundle(tmp_path / "c", "nmos_wgfmu", station=example_station(
        RSU201={"wgfmu": 201}, RSU202={"wgfmu": 202, "smu": 4}))
    assert from_smu(planning_station(recorded).switches) == {"RSU202.OUT": 4}  # recorded inputs are never replaced


# -- validate_plan and run ---------------------------------------------------------------------------------------------


def test_an_smu_above_25_v_on_an_rsu_input_is_blocked(world: World) -> None:
    prepare(world, "nmos_wgfmu")
    service = world.service()
    validation = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 30.0})
    assert validation.tier == "blocked" and validation.simulated
    [finding] = [f for f in validation.findings if f.rule_id == "R-RSU-01"]
    assert finding.severity == "block" and (finding.observed, finding.limit) == (30.0, 25.0)
    assert "From SMU input of RSU202.OUT" in finding.message and "WG p20 (1-8)" in finding.message
    assert finding.source == "code:b1500_test_agent.driver.modules.WGFMU_SPEC.smu_mode_max_v (WG p20 (1-8))"
    at_limit = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 25.0})
    assert not [f for f in at_limit.findings if f.rule_id == "R-RSU-01"]  # a value equal to the limit passes
    bias = service.validate_plan(**SWEEP, params={"stop": 1.0, "bias_v": -26.0})  # SMU4 feeds RSU201
    assert bias.tier == "blocked" and [f.observed for f in bias.findings if f.rule_id == "R-RSU-01"] == [26.0]
    assert world.sim_log("nmos_wgfmu") == []  # validation sends nothing


def test_without_rsu_cabling_the_same_plan_only_needs_confirmation(world: World) -> None:
    prepare(world, "nmos_basic")
    validation = world.service().validate_plan(**SWEEP, params={"start": 0.0, "stop": 30.0})
    assert validation.tier == "needs_confirmation"
    assert not [f for f in validation.findings if f.rule_id == "R-RSU-01"]  # unknown input: hardware blocks only


def test_a_plan_within_the_input_runs_and_the_session_holds_the_cabling(world: World) -> None:
    prepare(world, "nmos_wgfmu")
    service = world.service()
    validation = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 1.0, "points": 11})
    assert not [f for f in validation.findings if f.rule_id == "R-RSU-01"]
    assert validation.plan_id is not None
    result = (service.run_plan(validation.plan_id) if validation.tier == "ok" else
              service.run_confirmed_plan(validation.plan_id, summary=validation.summary or ""))
    assert result.outcome == "completed" and result.cleanup_verified == "sim_state", result.message
    session = world.executor().session(load_config(world.paths))
    assert from_smu(session.switches) == {"RSU201.OUT": 4, "RSU202.OUT": 3}  # the guard's = the planning station's


# -- OutputGuard at run time ------------------------------------------------------------------------------------------


WIDE = CompiledEnvelope(channels={
    GATE: ChannelEnvelope(role="gate", max_abs_v=2.0, max_abs_i=1e-4),
    DRAIN: ChannelEnvelope(role="drain", max_abs_v=40.0, max_abs_i=1e-3),
})
"""A stale or buggy plan's envelope: 40 V on SMU3 (R-RSU-01 would block it; the guard must stop it alone)."""


def test_a_body_beyond_the_input_never_reaches_the_simulator(tmp_path: Path) -> None:
    station = StationProfile.model_validate(example_station(RSU202={"wgfmu": 202, "smu": DRAIN}))
    rsus = [s for s in station.switches if s.kind == "rsu"]  # SMU3 (the drain) on RSU202's From SMU input
    h = make_harness(tmp_path, noiseless(load_scenario("nmos_basic")), switches=rsus)
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=WIDE) as tx:
        tx.driver.enable([GATE, DRAIN])
        tx.driver.force_v(DRAIN, 25.0, icomp=1e-3)  # at the limit: written
        tx.driver.force_v(DRAIN, 26.0, icomp=1e-3)
    assert caught.value.reason == "rsu_input_exceeded" and caught.value.limit == 25.0
    assert_global_invariant(h, envelope=WIDE)
    sources = [r.command for r in h.log if r.source]
    assert sources == ["DV 3,0,25,0.001"]  # the 26 V request never reached the transport
    violation = next(e for e in h.events() if e.ev == "envelope_violation")
    assert violation.data is not None and violation.data["reason"] == "rsu_input_exceeded"
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
