"""Schedules of kind ``pulse_read`` (WP9.5; blueprint v2 2.7 "per cycle/amplitude x width grid/retention schedule"):
parameter parsing and bounds, checkpoint cycle counts and bursts, the steps and checkpoints of every schedule, the
compiled operations (two-level pulses, three-level bipolar cycling bursts), routes per phase, the source plan the
rules see, the FLEX preview, the estimate's segments and the refusals (an SMU cannot burst, single-operation
sequences, too many reads)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import PulseReadKind
from b1500_test_agent.catalog.kinds.pulse_read import PulseReadProgram, stored_program
from b1500_test_agent.catalog.kinds.pulse_schedules import (
    MAX_CYCLES,
    MAX_READS,
    MAX_STRESS_CYCLES,
    burst_counts,
    cycling_key,
    log_cycles,
    parse_schedule,
)
from b1500_test_agent.catalog.kinds.pulse_sources import MAX_COUNT, SpguOp
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.sources import source_plan
from b1500_test_agent.models.spgu import SpguPulseProgram
from tests.sim.pulse_read_helpers import BASE, SMU_PULSE_READ, WRITE_READ, pr_plan, registry

pytestmark = pytest.mark.spgu

KINETICS = {"recipe_id": "fefet.switching_kinetics", **BASE}
ENDURANCE = {"recipe_id": "fefet.endurance", **BASE}
RETENTION = {"recipe_id": "fefet.retention", **BASE}


def q(**values: Any) -> dict[str, Quantity]:
    return {k: Quantity(value=v) for k, v in values.items()}


def routes(plan: Any) -> dict[str, list[str]]:
    return {phase: [str(r) for r in items] for phase, items in plan.routes_by_phase.items()}


# -- pure helpers ----------------------------------------------------------------------------------------------------


def test_log_cycles_are_distinct_rounded_powers_ending_at_the_total() -> None:
    assert log_cycles(1000, 3) == [1, 2, 5, 10, 22, 46, 100, 215, 464, 1000]
    assert log_cycles(1, 3) == [1] and log_cycles(7, 1) == [1, 7]
    assert log_cycles(10**6, 1) == [1, 10, 100, 1000, 10000, 100000, 1000000]


def test_bursts_are_cut_at_the_spgu_count_limit() -> None:
    assert burst_counts(0) == [] and burst_counts(5) == [5]
    assert burst_counts(2 * MAX_COUNT + 7) == [MAX_COUNT, MAX_COUNT, 7] and cycling_key(7) == "cycling_7"


def test_endurance_schedule_lists_checkpoints_and_bursts() -> None:
    plan = parse_schedule(q(cycle_reads="log", cycles=1000, reads_per_decade=1, cycle_period=1e-5), source="spgu")
    assert plan.checkpoints == [1, 10, 100, 1000] and plan.cycles == 1000
    assert plan.bursts() == [8, 89, 899] and plan.reads() == 1 + 4 * 2
    listed = parse_schedule(q(cycle_reads="list", cycles=50, read_cycles=[1.0, 3.0, 20.0], cycle_period=1e-5),
                            source="spgu")
    assert listed.checkpoints == [1, 3, 20, 50] and listed.bursts() == [1, 16, 29]


def test_grid_schedule_orders_points_by_mode() -> None:
    reset = parse_schedule(q(schedule="grid", amplitudes=[3.0, 4.0], widths=[1e-7, 1e-6]), source="spgu")
    assert [(p.cycle, p.level, p.width, p.row, p.op) for p in reset.grid] == [
        (1, 3.0, 1e-7, 0, "g1"), (2, 3.0, 1e-6, 0, "g2"), (3, 4.0, 1e-7, 1, "g3"), (4, 4.0, 1e-6, 1, "g4")]
    assert reset.grid_op == "program" and reset.reads() == 1 + 4 + 4
    ispp = parse_schedule(q(schedule="grid", grid_mode="ispp", amplitudes=[3.0, 4.0], widths=[1e-7, 1e-6],
                            reset_read=False), source="spgu")
    assert [(p.level, p.width, p.row) for p in ispp.grid] == [(3.0, 1e-7, 0), (4.0, 1e-7, 0), (3.0, 1e-6, 1),
                                                             (4.0, 1e-6, 1)]
    assert ispp.reads() == 1 + 4


def test_retention_schedule_reads_at_log_times() -> None:
    plan = parse_schedule(q(schedule="retention", retention_time=100.0, first_read=1.0, sequence="program_erase"),
                          source="smu")
    assert plan.read_times == [1.0, 2.15, 4.64, 10.0, 21.54, 46.42, 100.0] and plan.reads() == 1 + 2 * 7


@pytest.mark.parametrize(("params", "message"), [
    ({"schedule": "sweep"}, "schedule must be one of"),
    ({"cycles": MAX_CYCLES + 1}, "cycles must be an integer 1 to 200"),
    ({"cycle_reads": "log", "cycles": MAX_STRESS_CYCLES + 1, "cycle_period": 1e-5}, "cycles must be an integer"),
    ({"cycle_reads": "log", "cycles": 100}, "cycle_period"),
    ({"cycle_reads": "log", "cycles": 100, "cycle_period": 1e-5, "sequence": "program"}, "two-operation sequence"),
    ({"cycle_reads": "list", "cycles": 100, "read_cycles": [10.0, 5.0], "cycle_period": 1e-5}, "increase strictly"),
    ({"schedule": "grid", "amplitudes": [3.0], "widths": [1e-6], "sequence": "program"}, "erase_program or"),
    ({"schedule": "grid", "amplitudes": [3.0, 0.0], "widths": [1e-6]}, "must not contain 0 V"),
    ({"schedule": "grid", "amplitudes": [3.0], "widths": [-1e-6]}, "must be positive"),
    ({"schedule": "grid", "widths": [1e-6]}, "amplitudes"),
    ({"schedule": "grid", "grid_mode": "ispp", "amplitudes": [4.0, 3.0], "widths": [1e-6]}, "strictly increasing"),
    ({"schedule": "grid", "amplitudes": [3.0] * 20, "widths": [1e-6] * 11}, "grid points"),
    ({"schedule": "retention"}, "retention_time"),
    ({"schedule": "retention", "retention_time": 10.0, "first_read": 0.01}, "first_read"),
    ({"schedule": "retention", "retention_time": 10.0, "settle": 1.0}, "settle must be 0"),
    ({"schedule": "retention", "retention_time": 10.0, "cycles": 3}, "applies to schedule cycles only"),
    ({"precycles": 10, "cycle_period": 1e-5}, "need the HV-SPGU source"),
])
def test_schedule_parameters_that_are_refused(params: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        parse_schedule(q(**params), source="spgu" if "precycles" not in params else "smu")


def test_the_read_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every schedule's own bounds keep a plan within ``MAX_READS``; the final check still refuses a plan beyond it."""
    from b1500_test_agent.catalog.kinds import pulse_schedules

    assert parse_schedule(q(schedule="grid", amplitudes=[3.0] * 20, widths=[1e-6] * 10),
                          source="spgu").reads() == MAX_READS
    monkeypatch.setattr(pulse_schedules, "MAX_READS", 10)
    with pytest.raises(CompileError, match="13 reads, more than 10"):
        parse_schedule(q(cycles=6), source="spgu")


# -- compile: switching kinetics -------------------------------------------------------------------------------------


def test_kinetics_plan_compiles_resets_grid_pulses_and_precycles(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, KINETICS)
    assert plan.tier == "needs_confirmation" and plan.mode == "sync"
    assert sorted(plan.rules.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    assert routes(plan) == {"cycling": ["SEL1.OUT1->pgu"], "erase": ["SEL1.OUT1->pgu"],
                            "program": ["SEL1.OUT1->pgu"], "read": ["SEL1.OUT1->smu"], "rest": ["SEL1.OUT1->open"]}
    program, programs = stored_program(plan)
    assert program.schedule == "grid" and program.grid_mode == "reset" and len(program.grid) == 55
    assert list(program.ops)[:2] == ["erase", "g1"] and "cycling_1000" in program.ops
    burst = program.ops["cycling_1000"]
    assert isinstance(burst, SpguOp) and burst.bipolar and burst.count == 1000 and burst.name == "erase"
    three = programs[burst.program]
    assert isinstance(three, SpguPulseProgram) and three.channels[101].levels == "three_level"
    sources = three.channels[101].sources
    assert (sources[1].peak_v, sources[1].delay_s, sources[2].peak_v, sources[2].delay_s) == (-4.0, 0.0, 4.0, 5e-6)
    assert three.period_s == 1e-5 and three.count == 1000
    point = program.grid[-1]
    grid_op = program.ops[point.op]
    assert (point.level, point.width) == (4.8, 1e-4) and (grid_op.level, grid_op.width) == (4.8, 1e-4)
    steps = program.steps()
    assert [s.action for s in steps[:6]] == ["burst", "read", "pulse", "read", "pulse", "read"]
    assert [(s.cycle, s.phase) for s in steps[2:6]] == [(1, "erase"), (1, "erase"), (1, "program"), (1, "program")]
    assert program.reads == 111 and PulseReadKind.checkpoint_total(plan) == sum(s.chunks for s in steps)
    trains = source_plan(plan.program).trains(101)
    assert sum(t.total_pulses for t in trains) == 1000 + 55 + 55  # the burst counts one guard pulse per cycle
    assert plan.envelope.channels[101].pulse is not None
    assert plan.envelope.channels[101].pulse.min_width_s == 1e-8
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s < 30.0


def test_ispp_resets_once_per_width_row(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, KINETICS, grid_mode="ispp", amplitudes=[3.0, 3.5, 4.0], widths=[1e-7, 1e-6],
                   precycles=0)
    program, _ = stored_program(plan)
    pulses = [(s.op, s.cycle) for s in program.steps() if s.action == "pulse"]
    assert pulses == [("erase", 1), ("g1", 1), ("g2", 2), ("g3", 3), ("erase", 4), ("g4", 4), ("g5", 5), ("g6", 6)]
    assert program.reads == 1 + 2 + 6 and "cycling" not in plan.routes_by_phase


def test_kinetics_widths_below_the_edge_limit_are_blocked(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, KINETICS, t_edge=2e-8, precycles=0)
    assert plan.tier == "blocked"
    assert any(f.rule_id == "R-PULSE-01" and "leading / 0.8" in f.message for f in plan.rules.findings)


# -- compile: endurance -----------------------------------------------------------------------------------------------


def test_endurance_plan_bursts_between_checkpoints_and_runs_async(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, ENDURANCE)
    assert plan.mode == "async" and plan.tier == "needs_confirmation"
    assert sorted(plan.rules.confirm_reasons) == ["dut_envelope", "long_run", "soft_pulse", "unverified_pin_map",
                                                 "unverified_topology"]
    program, programs = stored_program(plan)
    assert program.cycle_reads == "log" and program.checkpoints[0] == 1 and program.checkpoints[-1] == 10**6
    assert len(program.checkpoints) == 19 and program.reads == 1 + 2 * 19
    bursts = [s for s in program.steps() if s.action == "burst"]
    assert sum(program.ops[s.op].count for s in bursts) == 10**6 - 19  # every cycle but the checkpoint cycles
    assert all(s.cycle in program.checkpoints for s in bursts)
    assert all(programs[program.ops[s.op].program].channels[101].levels == "three_level" for s in bursts)
    reads = [s for s in program.steps() if s.action == "read"]
    assert [r.cycle for r in reads[1:5]] == [1, 1, 2, 2] and reads[-1].cycle == 10**6
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s <= 30.0
    assert "SPM 101,3" in plan.flex_preview and "SPRM 1,1000000" not in plan.flex_preview
    assert routes(plan)["cycling"] == ["SEL1.OUT1->pgu"]


def test_endurance_beyond_one_spgu_run_splits_bursts(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, ENDURANCE, cycles=3_000_000, cycle_reads="list", read_cycles=[1.0], cycle_period=3e-6)
    program, _ = stored_program(plan)
    counts = [program.ops[s.op].count for s in program.steps() if s.action == "burst"]
    assert counts == [MAX_COUNT, MAX_COUNT, MAX_COUNT - 2] and program.checkpoints == [1, 3_000_000]


def test_an_smu_pulse_source_cannot_cycle_in_bursts(tmp_path: Path) -> None:
    recipe = tmp_path / "recipes" / "generic" / "smu_pulse_read.yaml"
    registry(tmp_path)
    text = recipe.read_text(encoding="utf-8").replace(
        "  cycles: {type: int, default: 1, range: [1, 200], doc: Cycles.}",
        "  cycles: {type: int, default: 1, range: [1, 1000], doc: Cycles.}\n"
        "  cycle_reads: {type: enum, choices: [every, log], default: every, doc: Reads.}\n"
        "  cycle_period: {unit: s, default: 1.0e-2, range: [1.0e-3, 1.0], doc: Cycle period.}")
    recipe.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidInputError, match="need the HV-SPGU source"):
        pr_plan(tmp_path, SMU_PULSE_READ, cycle_reads="log", cycles=100)


def test_a_cycle_period_too_short_for_both_pulses_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="cycle period must be at least"):
        pr_plan(tmp_path, ENDURANCE, cycle_period=2e-6)


# -- compile: retention ----------------------------------------------------------------------------------------------


def test_retention_plan_holds_between_reads(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, RETENTION, retention_time=100.0)
    program, programs = stored_program(plan)
    assert program.schedule == "retention" and program.monitor is not None and len(programs) == 2
    assert [m.role for m in program.monitor.measure] == ["gate_read", "drain"]
    steps = program.steps()
    assert [(s.action, s.phase) for s in steps[:4]] == [("read", "read"), ("pulse", "program"),
                                                        ("hold", "retention"), ("read", "program")]
    holds = [s for s in steps if s.action == "hold"]
    assert [h.seconds for h in holds[:7]] == [1.0, 1.15, 2.49, 5.36, 11.54, 24.88, 53.58]
    assert sum(h.seconds for h in holds) == pytest.approx(200.0)
    assert [s.t_s for s in steps if s.action == "read"][1:3] == [1.0, 2.15]
    assert holds[-1].chunks == 3 and PulseReadKind.checkpoint_total(plan) == sum(s.chunks for s in steps)
    assert plan.flex_preview.count("MM 10,3,4") == 14 and "MSC 2,2" in plan.flex_preview
    assert routes(plan) == {"program": ["SEL1.OUT1->pgu"], "erase": ["SEL1.OUT1->pgu"], "read": ["SEL1.OUT1->smu"],
                            "rest": ["SEL1.OUT1->open"]}


def test_the_default_retention_plan_is_a_long_async_run(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, RETENTION)
    assert plan.mode == "async" and "long_run" in plan.rules.confirm_reasons
    assert plan.estimate.duration_s > 2 * 10_000 and plan.estimate.max_segment_s is not None
    assert plan.estimate.max_segment_s <= 30.0


# -- back compatibility ----------------------------------------------------------------------------------------------


def test_a_wp94_program_without_schedule_fields_still_validates(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, WRITE_READ, cycles=2)
    program, _ = stored_program(plan)
    old = {k: v for k, v in program.model_dump(mode="json").items()
           if k not in ("schedule", "cycle_reads", "checkpoints", "cycle_period", "grid", "grid_mode", "reset_read",
                        "read_times", "monitor", "precycles")}
    again = PulseReadProgram.model_validate(old)
    assert again.steps() == program.steps() and again.schedule == "cycles"
