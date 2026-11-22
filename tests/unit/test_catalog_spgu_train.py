"""Kind ``spgu_pulse`` pulse modes (``catalog/kinds/spgu_train.py``, WP9.3): compile of the committed recipes (programs,
source plan, envelopes, routes, preview, estimate, checkpoints, grids, bounds, three-level, ALWG), the refusals,
``blocks.spgu_burst`` (the ATV-19 fallback), R-PULSE-01 on stored SPGU programs and the simulator planning station."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.blocks import BurstResult, spgu_burst, spgu_poll_s, spgu_stop_timeout_s
from b1500_test_agent.catalog.kinds import SpguPulseKind
from b1500_test_agent.catalog.kinds.spgu_train import WAIT_SEGMENT_S, stored_program
from b1500_test_agent.catalog.planner import planning_station
from b1500_test_agent.driver.errors import DriverError, SpguStillActive
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, source_plan
from b1500_test_agent.models.spgu import SPGU_PROGRAMS_KEY, AlwgProgram, SpguPulseProgram, spgu_programs
from b1500_test_agent.rules import RulesEngine
from b1500_test_agent.rules.tiers import with_rules
from tests.sim.selector_helpers import recorded_station
from tests.sim.spgu_pulse_helpers import ALWG, CHARGE_PUMPING, PULSE_TRAIN, REGISTRY, compile_plan, repo_bundle
from tests.unit.rules_factory import T0

pytestmark = pytest.mark.spgu

PGU_ROUTE = Route(switch="SEL1", output="OUT1", state="pgu")
REST = Route(switch="SEL1", output="OUT1", state="open")


def train_plan(tmp_path: Path, **params: Any) -> Any:
    return compile_plan(tmp_path, "fefet_lab", PULSE_TRAIN, **params)


# -- pg --------------------------------------------------------------------------------------------------------------


def test_pulse_train_compiles_the_lab_sequence_with_routes_and_bounds(tmp_path: Path) -> None:
    plan = train_plan(tmp_path)
    program, programs = stored_program(plan)
    assert program.mode == "pg" and program.pgu == {"gate": 101} and program.spot is None
    assert [p.model_dump() for p in programs] == [SpguPulseProgram.model_validate({
        "period_s": 1e-4, "count": 1000, "channels": {101: {"load_ohm": 1e6, "sources": {1: {
            "width_s": 1e-6, "base_v": 0.0, "peak_v": 4.0, "lead_s": 2e-8, "trail_s": 2e-8}}}}}).model_dump()]
    assert plan.routes_by_phase == {"pulse": [PGU_ROUTE], "rest": [REST]}
    assert plan.envelope.routes == frozenset({PGU_ROUTE})
    entry = plan.envelope.channels[101]
    assert (entry.role, entry.function, entry.max_abs_i) == ("gate", "pgu", None)
    assert entry.pulse is not None and entry.pulse.max_abs_v_dut == pytest.approx(4.0 * (1e6 + 50) / 1e6)
    assert entry.pulse.max_count == 1000 and entry.pulse.max_short_circuit_a == pytest.approx(0.080004)
    assert plan.flex_preview == ["ERMOD 1", "ERSSP 0,2", "CN 101", "SIM 0", "SPRM 1,1000", "SPPER 0.0001",
                                 "SER 101,1000000", "SPM 101,1", "SPT 101,1,0,1E-06,2E-08,2E-08", "SPV 101,1,0,4",
                                 "ODSW 101,0", "STGP 101,0", "SPUPD 101", "SRP", "ERSSP 0,0"]
    assert plan.estimate.points == 0 and plan.estimate.duration_s == pytest.approx(1.0 + 0.12 + 0.05 + 0.1 + 0.1)
    assert program.chunks == [1] and SpguPulseKind().checkpoint_total(plan) == 1
    trains = source_plan(plan.program).trains(101)
    assert len(trains) == 1 and trains[0] == programs[0].guard_train(101)


def test_duration_bound_three_level_and_long_trains(tmp_path: Path) -> None:
    plan = train_plan(tmp_path, bound="duration", duration=25.0, three_level=True)
    _, programs = stored_program(plan)
    program = programs[0]
    assert isinstance(program, SpguPulseProgram) and program.duration_s == 25.0 and program.count is None
    channel = program.channels[101]
    assert channel.levels == "three_level" and sorted(channel.sources) == [1, 2]
    assert program.away_levels(101) == [-4.0, 4.0] and program.guard_train(101).width_s == pytest.approx(2e-6)
    assert "SPM 101,3" in plan.flex_preview and "SPRM 2,25" in plan.flex_preview
    stored, _ = stored_program(plan)
    assert stored.chunks == [3]  # 25 s of output: a checkpoint every WAIT_SEGMENT_S of waiting
    assert plan.estimate.max_segment_s == pytest.approx(WAIT_SEGMENT_S + 0.05 + spgu_poll_s(25.0))


def test_charge_pumping_grid_rounds_periods_and_reads_during_every_train(tmp_path: Path) -> None:
    plan = compile_plan(tmp_path, "nmos_cv", CHARGE_PUMPING, v_base=[-2.5, -2.0], frequency=[3e4, 1e5])
    program, programs = stored_program(plan)
    assert [(p.levels["gate"], round(p.freq_hz, 3)) for p in program.points] == [
        (-2.5, round(1 / 3.333e-5, 3)), (-2.5, 1e5), (-2.0, round(1 / 3.333e-5, 3)), (-2.0, 1e5)]
    first = programs[0]
    assert isinstance(first, SpguPulseProgram) and first.period_s == pytest.approx(3.333e-5)  # 10 ns grid
    assert first.channels[101].sources[1].width_s == pytest.approx(1.666e-5)  # duty 0.5 on the 10 ns grid (half even)
    assert first.channels[101].sources[1].peak_v == pytest.approx(1.5)  # amplitude kept over the base list
    assert program.spot is not None and [m.role for m in program.spot.measure] == ["bulk"]
    assert plan.estimate.points == 4 and set(plan.envelope.channels) == {101, 4, 5, 6}
    assert plan.flex_preview.count("SRP") == plan.flex_preview.count("XE") == 4
    assert plan.flex_preview[:2] == ["ERMOD 1", "ERSSP 0,2"] and "CN 4,5,6,101" in plan.flex_preview
    assert len(source_plan(plan.program).trains(101)) == 4  # four distinct trains


def test_identical_trains_merge_into_one_with_repeat(tmp_path: Path) -> None:
    plan = compile_plan(tmp_path, "nmos_cv", CHARGE_PUMPING, frequency=[1e5, 1e5, 1e5])
    trains = source_plan(plan.program).trains(101)
    assert len(trains) == 1 and trains[0].repeat == 3 and len(spgu_programs(plan.program)) == 3


@pytest.mark.parametrize(("request_", "params", "message"), [
    (PULSE_TRAIN, {"bound": "count", "count": 0}, "count"),  # R-PARAM-01 range, or the kind
    (CHARGE_PUMPING, {"duration": 0.05}, "ends before its read"),
    (PULSE_TRAIN, {"period": 1e-6, "width": 2e-6}, "SPGU program is not valid"),
])
def test_requests_the_kind_cannot_express(tmp_path: Path, request_: dict[str, Any], params: dict[str, Any],
                                          message: str) -> None:
    from b1500_test_agent.errors import InvalidInputError

    scenario = "nmos_cv" if request_ is CHARGE_PUMPING else "fefet_lab"
    try:
        plan = compile_plan(tmp_path, scenario, request_, **params)
    except InvalidInputError as exc:
        assert message in str(exc)
    else:
        assert plan.tier == "blocked" and any(message in f.message for f in plan.rules.findings)


# -- alwg ------------------------------------------------------------------------------------------------------------


def test_alwg_sequence_compiles_one_pattern_and_the_block_headers(tmp_path: Path) -> None:
    plan = compile_plan(tmp_path, "fefet_lab", ALWG)
    program, programs = stored_program(plan)
    alwg = programs[0]
    assert isinstance(alwg, AlwgProgram) and alwg.sequence == [(1, 1)] and alwg.count == 100
    assert alwg.away_levels(101) == [-4.0, 4.0] and alwg.sequence_time_s() == pytest.approx(22.4e-6)
    assert program.points[0].freq_hz == pytest.approx(1 / 22.4e-6) and program.points[0].levels == {"gate": 0.0}
    assert plan.flex_preview[3:8] == ["SIM 1", "SPRM 1,100", "SER 101,1000000", "ODSW 101,0", "STGP 101,0"]
    assert plan.flex_preview[8].startswith("ALW 101,") and plan.flex_preview[9] == "ALS 26"


# -- spgu_burst ------------------------------------------------------------------------------------------------------


class FakeDriver:
    """The SPGU part of the driver ``spgu_burst`` uses; ``stuck``: ``wait_pulses_stopped`` raises SpguStillActive;
    ``spp_stops``: ``SPP`` ends the output."""

    def __init__(self, *, stuck: bool, spp_stops: bool) -> None:
        self.calls: list[str] = []
        self.stuck, self.spp_stops, self.active = stuck, spp_stops, False

    def configure_spgu(self, program: Any) -> None:
        self.calls.append("configure")

    def apply_pulse_setup(self) -> None:
        self.calls.append("SPUPD")

    def start_pulses(self) -> None:
        self.calls.append("SRP")
        self.active = True

    def errors(self, drain: bool = True) -> list[Any]:
        return []

    def pulse_output_active(self) -> bool:
        return self.active

    def wait_pulses_stopped(self, *, timeout_s: float, poll_s: float, check: Any) -> float:
        check()
        if self.stuck:
            raise SpguStillActive("still active", waited_s=timeout_s)
        self.active = False
        return poll_s

    def stop_pulses(self) -> None:
        self.calls.append("SPP")
        if self.spp_stops:
            self.active = False


class FakeTx:
    def __init__(self, driver: FakeDriver) -> None:
        self.driver, self.marks, self.aborts = driver, [], 0

    def mark(self, label: str) -> None:
        self.marks.append(label)

    def check_abort(self) -> None:
        self.aborts += 1


def program() -> SpguPulseProgram:
    return SpguPulseProgram.model_validate({"period_s": 1e-4, "count": 10, "channels": {101: {
        "load_ohm": 1e6, "sources": {1: {"width_s": 1e-6, "base_v": 0.0, "peak_v": 4.0}}}}})


def test_burst_runs_during_and_waits_for_the_end() -> None:
    tx = FakeTx(FakeDriver(stuck=False, spp_stops=True))
    result = spgu_burst(tx, program(), during=lambda: "read")  # type: ignore[arg-type]
    assert result == BurstResult(waited_s=spgu_poll_s(1e-3), stopped_by_spp=False, during="read")
    assert tx.driver.calls == ["configure", "SPUPD", "SRP"] and tx.aborts == 1


def test_burst_atv19_fallback_completes_when_spp_stops_the_output() -> None:
    tx = FakeTx(FakeDriver(stuck=True, spp_stops=True))
    result = spgu_burst(tx, program())  # type: ignore[arg-type]
    assert result.stopped_by_spp and result.waited_s == spgu_stop_timeout_s(1e-3)
    assert tx.driver.calls[-1] == "SPP" and any("ATV-19 fallback" in m for m in tx.marks)


def test_burst_fails_when_spp_does_not_stop_or_the_train_ends_before_the_read() -> None:
    with pytest.raises(DriverError, match="did not stop"):
        spgu_burst(FakeTx(FakeDriver(stuck=True, spp_stops=False)), program())  # type: ignore[arg-type]
    driver = FakeDriver(stuck=False, spp_stops=True)
    tx = FakeTx(driver)

    def read() -> None:
        driver.active = False  # the train ended while reading

    with pytest.raises(DriverError, match="ended before the measurement"):
        spgu_burst(tx, program(), during=read)  # type: ignore[arg-type]


# -- R-PULSE-01 on stored programs, summary, planning station --------------------------------------------------------


def test_r_pulse_01_checks_the_stored_programs_against_the_module(tmp_path: Path) -> None:
    bundle = repo_bundle(tmp_path, "fefet_lab")
    plan = train_plan(tmp_path / "p")
    programs = plan.program[SPGU_PROGRAMS_KEY]
    bad = [{**programs[0], "period_s": 1.5e-4 + 1e-9}]  # off the 10 ns period grid
    tampered = plan.model_copy(update={"program": {**plan.program, SPGU_PROGRAMS_KEY: bad}})
    from b1500_test_agent.catalog.planner import Planner

    planner = Planner(REGISTRY, clock=lambda: T0)
    report = RulesEngine(bundle, clock=lambda: T0).evaluate(planner.context(tampered, bundle), "plan")
    blocks = [f.message for f in report.findings if f.rule_id == "R-PULSE-01" and f.severity == "block"]
    assert any("SPGU program 0: channel 101: period" in m and "10 ns resolution" in m for m in blocks)
    assert any("outputs a train that is not among the channel's compiled pulse trains" in m for m in blocks)
    assert with_rules(tampered, report).tier == "blocked"
    clean = RulesEngine(bundle, clock=lambda: T0).evaluate(planner.context(plan, bundle), "plan")
    assert not [f for f in clean.findings if f.rule_id == "R-PULSE-01"]


def test_planning_station_fills_null_selector_inputs_on_the_simulator_only(tmp_path: Path) -> None:
    sim = repo_bundle(tmp_path / "a", "fefet_lab")
    filled = planning_station(sim).switch("SEL1")
    assert filled is not None and filled.ports["OUT1"].inputs == {"smu": 3, "pgu": 101}
    assert filled.certainty == "unverified" and sim.station.switch("SEL1").ports["OUT1"].inputs == {  # type: ignore[union-attr]
        "smu": None, "pgu": None}  # the station profile itself is untouched
    assert planning_station(sim).switch("SEL2").ports["OUT2"].inputs == {"smu": 6, "pgu": None}  # type: ignore[union-attr]
    plain = repo_bundle(tmp_path / "b", "nmos_basic")  # no selector cabling in the scenario
    assert planning_station(plain) == plain.station
    recorded = repo_bundle(tmp_path / "c", "fefet_lab", station=recorded_station())
    assert planning_station(recorded) == recorded.station  # recorded inputs are never replaced
    assert SOURCE_PLAN_KEY == "sources"
