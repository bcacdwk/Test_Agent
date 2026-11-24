"""Kind ``pulse_read`` compile (WP9.4; blueprint v2 2.7): roles and binding (a read role on the pulsed pad through
``RoleSpec.terminal``), the HV-SPGU and SMU pulse sources, routes per phase in the S12 contract order, the source plan
and SPGU programs R-PULSE-01 checks, the envelope, steps/checkpoints, the FLEX preview, the estimate, and the refusals
(the WGFMU source and read arrive in WP10.6, unknown schedules, unsupported roles)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import PulseReadKind, default_kinds
from b1500_test_agent.catalog.kinds.pulse_read import MAX_CYCLES, PulseReadProgram, stored_program
from b1500_test_agent.catalog.kinds.pulse_sources import PENDING_SOURCES, SOURCES, SmuOp, SpguOp, source_for
from b1500_test_agent.catalog.planner import bind_roles, planning_station
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.recipe import RoleSpec
from b1500_test_agent.models.sources import source_plan
from b1500_test_agent.models.spgu import spgu_programs
from tests.sim.pulse_read_helpers import PROGRAM_READ, SMU_PULSE_READ, WRITE_READ, pr_plan, registry
from tests.sim.spgu_pulse_helpers import repo_bundle

pytestmark = pytest.mark.spgu


def routes(plan: Any) -> dict[str, list[str]]:
    return {phase: [str(r) for r in items] for phase, items in plan.routes_by_phase.items()}


# -- binding ---------------------------------------------------------------------------------------------------------


def test_a_read_role_binds_to_the_terminal_it_names(tmp_path: Path) -> None:
    """``gate_read`` (sweep_v, ``terminal: gate``) and ``gate`` (pgu) bind to the same pad through their own inputs."""
    recipe = registry(tmp_path).get("fefet.pulse_write_read")
    bundle = repo_bundle(tmp_path, "fefet_lab")
    binding = bind_roles(recipe, bundle.pin_maps["fefet-sel"], planning_station(bundle), "fefet-sel")
    gate, read = binding.roles["gate"], binding.roles["gate_read"]
    assert (gate.terminal, gate.channel, str(gate.via)) == ("gate", 101, "SEL1.OUT1->pgu")
    assert (read.terminal, read.channel, str(read.via)) == ("gate", 3, "SEL1.OUT1->smu")
    assert binding.roles["drain"].channel == 4 and binding.roles["source"].gndu


def test_terminal_names_only_a_terminal_bound_role() -> None:
    assert RoleSpec(function="sweep_v", terminal="gate").pin_terminal("gate_read", {"gate": 3}) == "gate"
    assert RoleSpec(function="sweep_v", terminal="gate").pin_terminal("gate_read", {"drain": 4}) is None
    with pytest.raises(ValueError, match="cmu_side role finds its terminal"):
        RoleSpec(function="cmu_high", bind="cmu_side", terminal="gate")


# -- HV-SPGU source --------------------------------------------------------------------------------------------------


def test_write_read_plan_routes_programs_and_sources(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, WRITE_READ)
    assert plan.tier == "needs_confirmation" and plan.kind == "pulse_read"
    assert sorted(plan.rules.confirm_reasons) == ["unverified_pin_map", "unverified_topology"]
    # S12 contract: the program/erase phases (-> pgu) before the read phase (-> smu), rest last
    assert routes(plan) == {"erase": ["SEL1.OUT1->pgu"], "program": ["SEL1.OUT1->pgu"], "read": ["SEL1.OUT1->smu"],
                            "rest": ["SEL1.OUT1->open"]}
    assert {str(r) for r in plan.envelope.routes} == {"SEL1.OUT1->pgu", "SEL1.OUT1->smu"}
    program, programs = stored_program(plan)
    assert (program.source, program.pulse_role, program.pulse_channel) == ("spgu", "gate", 101)
    assert program.sequence == ["erase", "program"] and program.smu == [3, 4] and program.enable == [3, 4, 101]
    erase, write = program.ops["erase"], program.ops["program"]
    assert isinstance(erase, SpguOp) and isinstance(write, SpguOp)
    assert (erase.level, write.level, write.width, write.count, write.chunks) == (-4.0, 4.0, 1e-6, 1, 1)
    assert [p.model_dump(mode="json") for p in programs] == plan.program["spgu_programs"]
    assert [p.channels[101].sources[1].peak_v for p in programs] == [4.0, -4.0]  # type: ignore[union-attr]
    assert all(p.count == 1 and p.period_s == 1e-5 and p.channels[101].load_ohm == 1e6  # type: ignore[union-attr]
               for p in programs)
    trains = source_plan(plan.program).trains(101)
    assert sorted((t.peak_v, t.count, t.repeat, t.load_ohm) for t in trains) == [(-4.0, 1, 1, 1e6), (4.0, 1, 1, 1e6)]
    gate = plan.envelope.channels[101]
    assert gate.function == "pgu" and gate.max_abs_i is None and gate.pulse is not None
    assert gate.pulse.max_abs_v_dut == pytest.approx(4.0 * (1e6 + 50) / 1e6)
    read = plan.envelope.channels[3]
    assert (read.role, read.function, read.max_abs_v, read.max_abs_i) == ("gate_read", "sweep_v", 1.8, 1e-6)
    assert plan.envelope.channels[4].max_abs_v == 0.05


def test_steps_checkpoints_and_cycles(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, WRITE_READ, cycles=3, sequence="program_erase", initial_read=False)
    program, _ = stored_program(plan)
    steps = program.steps()
    assert [(s.action, s.cycle, s.phase) for s in steps[:4]] == [
        ("pulse", 1, "program"), ("read", 1, "program"), ("pulse", 1, "erase"), ("read", 1, "erase")]
    assert len(steps) == 12 and program.reads == 6
    assert PulseReadKind.checkpoint_total(plan) == 12
    assert sorted((t.peak_v, t.repeat) for t in source_plan(plan.program).trains(101)) == [(-4.0, 3), (4.0, 3)]
    assert plan.estimate.points == 6 * 47
    assert list(plan.routes_by_phase)[:2] == ["program", "erase"]  # in the sequence's order


def test_preview_lists_routes_pulses_and_reads_in_order(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, WRITE_READ)
    preview = plan.flex_preview
    assert preview[:2] == ["ERMOD 1", "ERSSP 0,1"] and preview.index("CN 3,4,101") < preview.index("XE")
    pulses = [i for i, line in enumerate(preview) if line == "ERSSP 0,2"]
    reads = [i for i, line in enumerate(preview) if line == "ERSSP 0,1"]
    assert len(pulses) == 2 and len(reads) == 3 and preview[-2:] == ["ERMOD 1", "ERSSP 0,0"]
    erase_level = preview.index("SPV 101,1,0,-4")
    assert pulses[0] < erase_level < preview.index("SRP") < reads[1] < preview.index("SPV 101,1,0,4")
    before = preview[pulses[0] - 3:pulses[0] - 1]
    assert before == ["DV 4,0,0,0.001", "DV 3,0,0,1E-06"]  # every read SMU at 0 V before the relay moves
    assert preview.count("XE") == 3 and preview.count("SPRM 1,1") == 2


def test_spot_reads_hold_the_read_role_at_its_level(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, PROGRAM_READ)
    program, _ = stored_program(plan)
    assert program.read.kind == "spot" and program.read.spot is not None and program.read.spot.samples == 3
    assert {o.role: o.level for o in program.read.outputs} == {"gate_read": 0.9, "drain": 0.05}
    assert {o.role: o.level for o in program.pulse_levels} == {"gate_read": 0.0, "drain": 0.0}
    assert plan.rules.confirm_reasons.count("adhoc_recipe") == 1
    assert program.sequence == ["program", "erase"] and program.cycles == 3


def test_a_drain_pulse_bias_widens_its_envelope(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, PROGRAM_READ, vd_pulse=0.5)
    program, _ = stored_program(plan)
    assert {o.role: o.level for o in program.pulse_levels}["drain"] == 0.5
    assert plan.envelope.channels[4].max_abs_v == 0.5


def test_program_only_sequence_stores_one_operation(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, PROGRAM_READ, sequence="program", cycles=2)
    program, programs = stored_program(plan)
    assert list(program.ops) == ["program"] and len(programs) == 1
    assert routes(plan) == {"program": ["SEL1.OUT1->pgu"], "read": ["SEL1.OUT1->smu"], "rest": ["SEL1.OUT1->open"]}
    assert [(t.peak_v, t.repeat) for t in source_plan(plan.program).trains(101)] == [(4.0, 2)]


def test_long_outputs_get_wait_checkpoints(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, PROGRAM_READ, count=100000, period=2.5e-4, width=1e-6, cycles=1)
    program, _ = stored_program(plan)
    op = program.ops["program"]
    assert isinstance(op, SpguOp) and op.output_s == pytest.approx(25.0) and op.chunks == 3
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s < 30.0


# -- SMU pulse source ------------------------------------------------------------------------------------------------


def test_smu_pulse_source_pulses_and_reads_with_one_smu(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, SMU_PULSE_READ)
    assert plan.tier == "needs_confirmation", plan.rules.findings
    program, programs = stored_program(plan)
    assert program.source == "smu" and programs == [] and program.enable == [3, 4]
    assert routes(plan) == {"read": ["SEL1.OUT1->smu"], "rest": ["SEL1.OUT1->open"]}
    op = program.ops["program"]
    assert isinstance(op, SmuOp) and op.setup.mode == 3 and op.setup.pulses[0].peak == 4.0
    assert (op.setup.period, op.setup.pulses[0].width, op.setup.pulses[0].comp) == (5e-3, 1e-3, 1e-6)
    gate = plan.envelope.channels[3]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i) == ("pulse_v", 4.0, 1e-6) and gate.pulse is not None
    assert gate.pulse.max_count == 1 and gate.pulse.max_short_circuit_a == 0.0
    trains = source_plan(plan.program).trains(3)
    assert sorted((t.peak_v, t.count, t.repeat, t.load_ohm) for t in trains) == [(-4.0, 1, 1, None), (4.0, 1, 1, None)]
    assert program.read.staircase is not None and program.read.staircase.sweep_role == "gate"
    assert {o.role: o.level for o in program.pulse_levels} == {"gate": 0.0, "drain": 0.0}
    assert "PT 0,0.001,0.005" in plan.flex_preview and "PV 3,0,0,4,1E-06" in plan.flex_preview
    assert not any(line.startswith(("SPV", "ERSSP 0,2")) for line in plan.flex_preview)


def test_smu_pulse_outside_the_pt_table_is_blocked(tmp_path: Path) -> None:
    """An HRSMU pulse of 400 us is below the PT minimum of 500 us (R-PULSE-01)."""
    recipe = tmp_path / "recipes" / "generic" / "smu_pulse_read.yaml"
    plan = pr_plan(tmp_path, SMU_PULSE_READ)
    text = recipe.read_text(encoding="utf-8").replace("range: [5.0e-4, 1.0e-3]", "range: [1.0e-4, 1.0e-3]")
    recipe.write_text(text, encoding="utf-8")
    plan = pr_plan(tmp_path, SMU_PULSE_READ, width=4e-4)
    assert plan.tier == "blocked"
    assert any(f.rule_id == "R-PULSE-01" and "pulse width" in f.message for f in plan.rules.findings)


# -- refusals --------------------------------------------------------------------------------------------------------


def test_the_wgfmu_source_is_refused_at_plan_time(tmp_path: Path) -> None:
    """No stub that pretends to run: a wgfmu pulse role is a compile error naming WP10.6."""
    assert PENDING_SOURCES == {"wgfmu": "WP10.6"} and "wgfmu" not in SOURCES
    with pytest.raises(CompileError, match="WGFMU source arrives in WP10.6"):
        source_for("gate", "wgfmu", "pulse_read")
    recipe = tmp_path / "recipes" / "fefet" / "pulse_write_read.yaml"
    registry(tmp_path)
    text = recipe.read_text(encoding="utf-8").replace("    function: pgu\n    module_types: [HVSPGU]",
                                                      "    function: wgfmu\n    module_types: [WGFMU]")
    recipe.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidInputError, match="WGFMU source arrives in WP10.6"):
        pr_plan(tmp_path, WRITE_READ)


def test_the_wgfmu_read_is_refused_at_plan_time(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="read_kind wgfmu arrives in WP10.6"):
        pr_plan(tmp_path, SMU_PULSE_READ, read_kind="wgfmu")


@pytest.mark.parametrize(("change", "message"), [
    ({"roles": {"gate": {"function": "pgu", "settings": {"program": 1.0, "width": 1e-6, "load_ohm": 1e6}},
                "other": {"function": "pgu", "settings": {}}, "drain": {"function": "bias_v", "measure": ["I"],
                                                                     "settings": {"v": 0.1, "icomp": 1e-3}}}},
     "exactly one pulse role"),
    ({"roles": {"gate": {"function": "pgu", "settings": {}},
                "drain": {"function": "sweep_i", "measure": ["V"], "settings": {}}}}, "cannot execute role"),
    ({"roles": {"gate": {"function": "pgu", "settings": {}},
                "drain": {"function": "bias_v", "settings": {"v": 0.1, "icomp": 1e-3}}}}, "no read role measures"),
    ({"roles": {"gate": {"function": "pgu", "measure": ["I"], "settings": {}},
                "drain": {"function": "bias_v", "measure": ["I"], "settings": {}}}}, "cannot measure"),
])
def test_role_structures_the_kind_refuses(change: dict[str, Any], message: str, tmp_path: Path) -> None:
    recipe = registry(tmp_path).get("fefet.pulse_write_read").model_copy(update={
        "roles": {k: RoleSpec.model_validate(v) for k, v in change["roles"].items()}})
    with pytest.raises(CompileError, match=message):
        PulseReadKind()._check_roles(recipe)


@pytest.mark.parametrize(("params", "message"), [
    ({"schedule": "grid"}, "schedule must be one of"),
    ({"cycles": MAX_CYCLES + 1}, "cycles must be an integer"),
    ({"settle": -1.0}, "settle must not be negative"),
])
def test_parameters_the_kind_refuses(params: dict[str, Any], message: str, tmp_path: Path) -> None:
    recipe = tmp_path / "recipes" / "generic" / "smu_pulse_read.yaml"
    registry(tmp_path)
    text = recipe.read_text(encoding="utf-8").replace(
        "  cycles: {type: int, default: 1, range: [1, 200], doc: Cycles.}",
        "  cycles: {type: int, default: 1, range: [1, 1000], doc: Cycles.}\n"
        "  schedule: {type: enum, choices: [cycles, grid], default: cycles, doc: Schedule.}")
    text = text.replace("range: [0.0, 600.0], doc: Wait", "range: [-5.0, 600.0], doc: Wait")
    recipe.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidInputError, match=message):
        pr_plan(tmp_path, SMU_PULSE_READ, **params)


def test_a_sequence_operation_needs_its_level(tmp_path: Path) -> None:
    recipe = tmp_path / "recipes" / "generic" / "smu_pulse_read.yaml"
    registry(tmp_path)
    recipe.write_text(recipe.read_text(encoding="utf-8").replace(" erase: $v_erase,", ""), encoding="utf-8")
    assert pr_plan(tmp_path, SMU_PULSE_READ, sequence="program").tier == "needs_confirmation"
    with pytest.raises(InvalidInputError, match="setting erase"):
        pr_plan(tmp_path, SMU_PULSE_READ)


def test_a_double_read_sweep_is_refused(tmp_path: Path) -> None:
    recipe = tmp_path / "recipes" / "fefet" / "pulse_write_read.yaml"
    registry(tmp_path)
    recipe.write_text(recipe.read_text(encoding="utf-8").replace("points: $vg_points,", "points: $vg_points, "
                                                                 "mode: double,"), encoding="utf-8")
    with pytest.raises(InvalidInputError, match="single sweep"):
        pr_plan(tmp_path, WRITE_READ)


def test_kind_is_registered_on_both_backends() -> None:
    kind = default_kinds()["pulse_read"]
    assert isinstance(kind, PulseReadKind) and kind.implemented_on == {"sim", "visa"}


def test_stored_program_round_trips(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, WRITE_READ, cycles=2)
    program, programs = stored_program(plan)
    again = PulseReadProgram.model_validate(program.model_dump(mode="json"))
    assert again == program and spgu_programs(plan.program) == programs


def test_a_long_settle_is_cut_into_checkpoint_segments(tmp_path: Path) -> None:
    plan = pr_plan(tmp_path, WRITE_READ, settle=25.0)
    program, _ = stored_program(plan)
    assert program.settle_chunks == 3 and program.settle_segments() == [10.0, 10.0, 5.0]
    assert [s.chunks for s in program.steps() if s.action == "pulse"] == [4, 4]
    assert PulseReadKind.checkpoint_total(plan) == 3 + 8
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s <= 10.5


def test_the_smu_pulse_block_refuses_other_modes_and_counts_before_any_io(tmp_path: Path) -> None:
    from b1500_test_agent.catalog.blocks import smu_pulse_burst

    op = stored_program(pr_plan(tmp_path, SMU_PULSE_READ))[0].ops["program"]
    assert isinstance(op, SmuOp)
    with pytest.raises(ValueError, match="positive pulse count"):
        smu_pulse_burst(None, op.setup, 0)  # type: ignore[arg-type]
    swept = op.setup.model_copy(update={"mode": 4})
    with pytest.raises(ValueError, match="single pulses"):
        smu_pulse_burst(None, swept, 1)  # type: ignore[arg-type]
