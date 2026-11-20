"""``stress_measure`` and the shared blocks without instrument I/O (WP7.6, blueprint v2 2.7): compile (roles, envelope
over every phase, read programs, schedule, holds, estimate, preview, program, routes), the parameter checks, the
timeline, the block helpers and the table replay on synthetic blocks. Acquisition runs in ``tests/safety``,
``tests/integration`` and ``tests/visa_loop``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import validate_table, with_trust
from b1500_test_agent.catalog.blocks import (
    MONITOR_INTERVAL_S,
    SEGMENT_S,
    Monitor,
    RouteStep,
    hold_chunks,
    route_steps,
)
from b1500_test_agent.catalog.kinds import UNIMPLEMENTED_KINDS, StressMeasureKind, StressProgram, default_kinds
from b1500_test_agent.catalog.kinds.smu_staircase import INTEGRATION_PRESETS, MeasureColumn
from b1500_test_agent.catalog.kinds.stress_measure import MAX_READS, log_times
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError, RawAcquisition
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import source_plan
from b1500_test_agent.transport.sim.format import Element
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = StressMeasureKind()
GATE, DRAIN = 5, 3  # rules-factory mosfet-4t: gate SMU5 (MPSMU), drain SMU3 (HRSMU), source/bulk GNDU
SMALL = {"vg_stress": 2.0, "stress_time": 30.0, "reads_per_decade": 1, "recovery_time": 10.0}


def compile_recipe(recipe_id: str = "reliability.bti_sms", *, rec: Recipe | None = None, pm: Any = None,
                   station: Any = None, **values: Any) -> Any:
    rec = rec or REGISTRY.get(recipe_id)
    station = station or STATION
    binding = bind_roles(rec, pm or pin_map(), station, "mosfet-4t")
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, station)


def program_of(compiled: Any) -> StressProgram:
    return StressProgram.model_validate(json.loads(json.dumps(compiled.program)))


def role_settings(recipe_id: str, role: str, **changes: Any) -> Recipe:
    rec = REGISTRY.get(recipe_id)
    spec = rec.roles[role]
    settings = {k: v for k, v in {**spec.settings, **changes}.items() if v is not None}
    return rec.model_copy(update={"roles": {**rec.roles, role: spec.model_copy(update={"settings": settings})}})


# -- registration ----------------------------------------------------------------------------------------------------


def test_registered_for_sim_and_visa_and_the_placeholder_is_gone() -> None:
    kind = default_kinds()["stress_measure"]
    assert isinstance(kind, StressMeasureKind) and kind.implemented_on == {"sim", "visa"}
    assert "smu_stress_measure" not in UNIMPLEMENTED_KINDS and "smu_stress_measure" not in default_kinds()
    for recipe_id in ("reliability.bti_sms", "igzo.bias_stress", "reliability.hci", "reliability.silc"):
        recipe = REGISTRY.get(recipe_id)
        assert recipe.kind == "stress_measure" and recipe.family == "reliability"
        assert recipe.always_confirm == ["destructive"]
        assert REGISTRY.effective_status(recipe_id, "sim") == "sim_validated"


# -- compile ---------------------------------------------------------------------------------------------------------


def test_the_envelope_covers_every_phase() -> None:
    compiled = compile_recipe(**{**SMALL, "vg_stress": 2.5, "vg_recovery": -0.5})
    gate, drain = compiled.envelope.channels[GATE], compiled.envelope.channels[DRAIN]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == ("sweep_v", 2.5, 1e-6, -0.2,
                                                                                         1.5)
    assert (drain.function, drain.max_abs_v, drain.max_abs_i, drain.v_start, drain.v_stop) == ("bias_v", 0.05, 1e-3,
                                                                                              0.05, 0.05)
    program = program_of(compiled)
    assert [(o.role, o.channel, o.level, o.comp) for o in program.stress] == [("gate", GATE, 2.5, 1e-6),
                                                                             ("drain", DRAIN, 0.0, 1e-3)]
    assert [(o.role, o.level) for o in program.recovery] == [("gate", -0.5), ("drain", 0.0)]
    assert program.hold_columns == {"stress": {"gate_V": 2.5, "drain_V": 0.0},
                                    "recovery": {"gate_V": -0.5, "drain_V": 0.0}}
    sources = source_plan(compiled.program)
    assert sources.dc_stress(GATE).level_v == 2.5 and sources.dc_stress(GATE).recovery_v == -0.5
    assert sources.schedule is not None and sources.schedule.model_dump() == {
        "stress_s": 30.0, "reads": 3, "recovery_s": 10.0, "recovery_reads": 2}
    assert compiled.envelope.routes == frozenset() and compiled.routes_by_phase == {}


def test_phase_changes_lower_falling_outputs_first() -> None:
    """HCI: entering the stress the gate falls (1.5 -> 1.2 V) before the drain rises (0.05 -> 2.5 V); leaving it the
    drain falls (2.5 -> 0.05 V) before the gate rises (1.2 -> 1.5 V)."""
    compiled = compile_recipe("reliability.hci", vg_stress=1.2, vd_stress=2.5, stress_time=1.0, reads_per_decade=1)
    levels = [line for line in compiled.flex_preview if line.startswith("DV ")]
    assert levels == ["DV 5,0,1.5,1E-06", "DV 3,0,0.05,0.001",  # reference read (from 0 V)
                      "DV 5,0,1.2,1E-06", "DV 3,0,2.5,0.001",  # stress: gate falls first
                      "DV 3,0,0.05,0.001", "DV 5,0,1.5,1E-06"]  # read: drain falls first


def test_hci_widens_the_drain_envelope_by_its_stress() -> None:
    compiled = compile_recipe("reliability.hci", vg_stress=1.2, vd_stress=2.5)
    drain = compiled.envelope.channels[DRAIN]
    assert (drain.function, drain.max_abs_v, drain.v_start) == ("bias_v", 2.5, 0.05)
    program = program_of(compiled)
    assert program.read.kind == "spot" and program.read.spot is not None and program.read.spot.samples == 3
    assert [(o.role, o.level) for o in program.stress] == [("gate", 1.2), ("drain", 2.5)]


def test_the_log_schedule_and_its_holds() -> None:
    program = program_of(compile_recipe(vg_stress=2.0, stress_time=1800.0))
    stress = [s for s in program.segments if s.phase == "stress"]
    assert [s.cycle for s in stress] == list(range(1, 12))
    assert [s.seconds for s in stress] == [1.0, 1.15, 2.49, 5.36, 11.54, 24.88, 53.58, 115.44, 248.72, 535.84, 800.0]
    ops = program.timeline()
    assert len(ops) == KIND.checkpoint_total(PlanRecord.model_construct(program=program.model_dump(mode="json"))) == 90
    reads = [op for op in ops if op.kind == "read"]
    assert [op.t_s for op in reads] == [0.0, 1.0, 2.15, 4.64, 10.0, 21.54, 46.42, 100.0, 215.44, 464.16, 1000.0,
                                        1800.0]
    holds = [op for op in ops if op.kind == "hold"]
    assert len(holds) == 78 and max(op.h_bias for op in holds) == pytest.approx(SEGMENT_S - program.monitor.period)


def test_a_list_schedule_ends_at_the_stress_time() -> None:
    program = program_of(compile_recipe(vg_stress=2.0, stress_time=600.0, schedule="list",
                                        read_times=[1.0, 60.0, 300.0]))
    assert [s.seconds for s in program.segments] == [1.0, 59.0, 240.0, 300.0]
    assert [op.t_s for op in program.timeline() if op.kind == "read"] == [0.0, 1.0, 60.0, 300.0, 600.0]


@pytest.mark.parametrize(("values", "message"), [
    ({"schedule": "list", "read_times": [10.0, 5.0]}, "increase strictly"),
    ({"schedule": "list", "read_times": [0.01, 5.0]}, "increase strictly"),
    ({"schedule": "list", "read_times": [5.0, 2000.0]}, "after stress_time"),
    ({"recovery_time": -1.0}, "recovery_time must be >= 0"),
    ({"reads_per_decade": 20, "stress_time": 86400.0, "first_read": 0.02, "recovery_time": 86400.0},
     f"exceed {MAX_READS}"),
    ({"read_kind": "spectral"}, "read_kind must be one of"),
    ({"schedule": "random"}, "schedule must be one of"),
])
def test_schedule_and_read_parameters_are_checked(values: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_recipe(**{"vg_stress": 2.0, "stress_time": 1000.0, **values})


def test_log_times_on_the_10_ms_grid() -> None:
    assert log_times(1.0, 30.0, 1) == [1.0, 10.0, 30.0]
    assert log_times(0.1, 1.0, 4) == [0.1, 0.18, 0.32, 0.56, 1.0]
    assert log_times(5.0, 2.0, 3) == [2.0]  # the first read later than the stress: one read at its end


def test_hold_chunks_keep_every_block_within_the_segment() -> None:
    assert hold_chunks(30.0, 0.02) == [24.98, 4.98]
    assert hold_chunks(50.0, 0.02) == [24.98, 24.98]
    assert hold_chunks(0.02, 0.02) == [0.0]
    assert hold_chunks(1.0, 0.0003125) == [1.0]  # short integration: the sample takes 0.3 ms
    with pytest.raises(ValueError, match="multiple"):
        hold_chunks(1.005, 0.02)


def test_the_monitor_period_follows_the_integration() -> None:
    measure = [MeasureColumn(channel=GATE, role="gate", quantity="I"),
               MeasureColumn(channel=DRAIN, role="drain", quantity="I")]
    assert Monitor.of(measure, INTEGRATION_PRESETS["medium"]).period == MONITOR_INTERVAL_S  # 2 x 20 ms, shortened
    assert Monitor.of(measure, INTEGRATION_PRESETS["short"]).period == pytest.approx(2 / 50 / 128)
    setup = Monitor.of(measure, INTEGRATION_PRESETS["long"]).setup(4.98)
    assert (setup.mode, setup.h_bias, setup.interval, setup.number, setup.abort, setup.sources) == (
        1, 4.98, MONITOR_INTERVAL_S, 1, True, ())


def test_the_estimate_and_the_segments_stay_within_r_run_02() -> None:
    compiled = compile_recipe(vg_stress=2.0, stress_time=1800.0)
    program = program_of(compiled)
    holds = [op for op in program.timeline() if op.kind == "hold"]
    assert compiled.estimate.points == 12 * 35 + 78
    assert compiled.estimate.duration_s == pytest.approx(
        1.0 + 12 * program.read_estimate_s + sum(op.h_bias + 0.02 + 0.5 for op in holds))
    assert compiled.estimate.max_segment_s == pytest.approx(25.5) and compiled.estimate.max_segment_s < 30


def test_the_preview_lists_every_write_of_one_cycle_in_order() -> None:
    compiled = compile_recipe(vg_stress=2.0, stress_time=1.0, reads_per_decade=1)
    read = ["FMT 1,1", "DV 3,0,0.05,0.001", "MM 2,5,3", "CMM 5,1", "CMM 3,1", "WV 5,1,0,-0.2,1.5,35,1E-06",
            "WT 0,0", "WM 2,1", "XE"]
    assert compiled.flex_preview == [
        "TSC 0", "AAD 5,0", "AAD 3,0", "AIT 0,2,1", "CN 5,3", *read,
        "DV 3,0,0,0.001", "DV 5,0,2,1E-06", "FMT 1,1", "MCC", "ML 1", "MT 0.98,0.02,1,0", "MSC 2,2", "MM 10,5,3",
        "CMM 5,1", "CMM 3,1", "XE", *read]


# -- compile refusals ------------------------------------------------------------------------------------------------


def test_role_functions_and_read_settings_are_checked() -> None:
    rec = REGISTRY.get("reliability.bti_sms")
    current = rec.model_copy(update={"roles": {**rec.roles, "drain": rec.roles["drain"].model_copy(
        update={"function": "bias_i", "settings": {"i": 1e-6, "vcomp": 1.0, "stress": 0.0}})}})
    with pytest.raises(CompileError, match=r"cannot execute role\(s\) drain \(bias_i\)"):
        compile_recipe(rec=current, **SMALL)
    two = rec.model_copy(update={"roles": {**rec.roles, "drain": rec.roles["gate"].model_copy()}})
    with pytest.raises(CompileError, match="at most one sweep_v role"):
        compile_recipe(rec=two, **SMALL)
    with pytest.raises(CompileError, match="needs setting stress"):
        compile_recipe(rec=role_settings("reliability.bti_sms", "drain", stress=None), **SMALL)
    with pytest.raises(CompileError, match="lacks"):
        compile_recipe(rec=role_settings("reliability.bti_sms", "gate", v=None), **SMALL, read_kind="spot")
    with pytest.raises(CompileError, match="single sweep"):
        compile_recipe(rec=role_settings("reliability.bti_sms", "gate", mode="double"), **SMALL)
    with pytest.raises(CompileError, match="range surveys belong to smu_spot"):
        compile_recipe(rec=role_settings("reliability.bti_sms", "drain", ranges=[1e-6]), **SMALL, read_kind="spot")


def test_an_unbound_read_role_leaves_the_plan_to_the_rules() -> None:
    compiled = compile_recipe(pm=pin_map(gate=None), **SMALL)
    assert compiled.program == {} and compiled.estimate.points == 0


# -- routes ----------------------------------------------------------------------------------------------------------


def test_an_asu_bound_gate_compiles_its_route_and_a_selector_is_refused() -> None:
    station = STATION.model_copy(update={"switches": [
        s.model_copy(update={"present": True}) if s.id == "ASU4" else s for s in STATION.switches]})
    pm = pin_map(gate="ASU4.OUT", drain=3)
    rec = REGISTRY.get("reliability.bti_sms")
    binding = bind_roles(rec, pm, station, "mosfet-4t")
    assert route_steps(binding, station, kind_id="stress_measure") == [
        RouteStep(route=Route(switch="ASU4", output="OUT", state="smu"), switch_kind="asu", index=4)]
    compiled = compile_recipe(rec=rec, pm=pm, station=station, **SMALL)
    route = Route(switch="ASU4", output="OUT", state="smu")
    assert compiled.envelope.routes == frozenset({route}) and compiled.routes_by_phase == {"setup": [route]}
    assert compiled.flex_preview[0] == "SAP 4,0"
    wired = STATION.model_copy(update={"switches": [s.model_copy(update={"ports": {
        **s.ports, "OUT1": s.ports["OUT1"].model_copy(update={"inputs": {"smu": 4, "pgu": 101}})}})
        if s.id == "SEL1" else s for s in STATION.switches]})
    selector = pin_map(gate="SEL1.OUT1", drain=3)
    assert bind_roles(rec, selector, wired, "mosfet-4t").roles["gate"].channel == 4
    with pytest.raises(CompileError, match="routes only ASU paths"):
        compile_recipe(rec=rec, pm=selector, station=wired, **SMALL)
    assert route_steps(bind_roles(rec, selector, STATION, "mosfet-4t"), STATION, kind_id="stress_measure") == []


# -- table replay ----------------------------------------------------------------------------------------------------


def _block(texts: list[str], fmt: int = 1) -> RawBlock:
    raw = ",".join(texts)
    now = datetime(2026, 11, 20, tzinfo=UTC)
    return RawBlock(raw=raw, points=tuple(parse_fmt1(raw)), fmt=fmt, expected_points=len(texts), xe_at=now,
                    read_at=now, duration_s=0.0)


def _read_block(program: StressProgram, drain_a: float) -> RawBlock:
    sweep = program.read.staircase
    assert sweep is not None
    texts: list[str] = []
    for k in range(sweep.steps):
        vg = -0.2 + 1.7 * k / (sweep.steps - 1)
        texts += [Element("N", GATE, "I", 1e-12).text(), Element("N", DRAIN, "I", drain_a * (k + 1)).text(),
                  Element("E" if k == sweep.steps - 1 else "W", GATE, "V", vg).text()]
    return _block(texts)


def _hold_block(gate_a: float, status: str = "N") -> RawBlock:
    return _block([Element("N", GATE, "X", 1.0).text(), Element(status, GATE, "I", gate_a).text(),
                   Element("N", DRAIN, "I", 0.0).text()])


def test_to_table_replays_reads_and_hold_blocks() -> None:
    compiled = compile_recipe(**SMALL)
    program = program_of(compiled)
    plan = PlanRecord.model_construct(program=compiled.program)
    blocks: list[RawBlock] = []
    for op in program.timeline():
        blocks.append(_read_block(program, 1e-6 * (1 + op.cycle)) if op.kind == "read" else _hold_block(2e-12))
    table = KIND.to_table(RawAcquisition(blocks=blocks), plan)
    assert list(table.columns) == ["step", "t_s", "cycle", "phase", "gate_V", "drain_V", "gate_I", "gate_I_status",
                                   "drain_I", "drain_I_status"]
    assert len(table) == 6 * 35 + 5 and list(table["step"]) == list(range(len(table)))
    holds = table[table["phase"] != "read"]
    assert list(holds["phase"]) == ["stress"] * 3 + ["recovery"] * 2
    assert list(holds["t_s"]) == [1.0, 10.0, 30.0, 31.0, 40.0] and list(holds["gate_V"]) == [2.0] * 3 + [0.0] * 2
    validate_table(with_trust(table))
    # a stopped run: the blocks end after the second hold block
    partial = KIND.to_table(RawAcquisition(blocks=blocks[:4]), plan)
    assert list(partial["cycle"].unique()) == [0, 1, 2] and partial.iloc[-1]["phase"] == "stress"
    with pytest.raises(ValueError, match="blocks exceed"):
        KIND.to_table(RawAcquisition(blocks=[*blocks, blocks[0]]), plan)


def test_the_stop_reason_and_the_kind_result() -> None:
    compiled = compile_recipe(**SMALL)
    program = program_of(compiled)
    ops = program.timeline()
    result = KIND._result(program, ops, 4, "stress cycle 2 block 1 reported status C")
    assert result == {"read_kind": "staircase", "reads_planned": 6, "reads_done": 2, "holds_planned": 5,
                      "holds_done": 2, "stress_s_planned": 30.0, "stress_s_done": 10.0, "recovery_s_planned": 10.0,
                      "recovery_s_done": 0.0, "stopped_early": True,
                      "stop_reason": "stress cycle 2 block 1 reported status C"}
