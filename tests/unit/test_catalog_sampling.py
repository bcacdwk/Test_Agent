"""``smu_sampling`` without instrument I/O (WP7.4, blueprint v2 2.7): compile (roles, envelope, blocks, estimate,
preview, program), the parameter checks, and the table builder (time origin, ATV-22 fallbacks, dummy samples, index
gaps) on synthetic blocks. Acquisition runs in ``tests/safety``, ``tests/integration`` and ``tests/visa_loop``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import validate_table, with_trust
from b1500_test_agent.catalog.kinds import SamplingProgram, SmuSamplingKind, default_kinds
from b1500_test_agent.catalog.kinds.smu_sampling import SEGMENT_S, Block, _Rows, log_indices
from b1500_test_agent.catalog.planner import Planner, bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError, RawAcquisition
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.transport.sim.format import Element
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0, bundle, dut, engine, example_station, pin_map

pytestmark = pytest.mark.smu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = SmuSamplingKind()
GATE, DRAIN = 5, 3  # rules-factory mosfet-4t: gate SMU5 (MPSMU), drain SMU3 (HRSMU), source/bulk GNDU


def compile_recipe(recipe_id: str, *, pm: Any = None, **values: Any):
    rec = REGISTRY.get(recipe_id)
    binding = bind_roles(rec, pm or pin_map(), STATION, "mosfet-4t")
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION)


def program_of(compiled: Any) -> SamplingProgram:
    return SamplingProgram.model_validate(json.loads(json.dumps(compiled.program)))


def recipe_with(recipe_id: str, **role_settings: dict[str, Any]) -> Recipe:
    rec = REGISTRY.get(recipe_id)
    roles = {name: (role.model_copy(update={"settings": role_settings[name]}) if name in role_settings else role)
             for name, role in rec.roles.items()}
    return rec.model_copy(update={"roles": roles})


# -- compile ---------------------------------------------------------------------------------------------------------


def test_registered_for_sim_and_visa() -> None:
    kind = default_kinds()["smu_sampling"]
    assert isinstance(kind, SmuSamplingKind) and kind.implemented_on == {"sim", "visa"}
    for recipe_id in ("generic.smu_sampling", "mosfet.id_t_sampling", "reliability.tddb_cvs"):
        assert REGISTRY.effective_status(recipe_id, "sim") == "sim_validated"


def test_id_t_sampling_defaults_compile_to_one_block_like_the_lab_script() -> None:
    compiled = compile_recipe("mosfet.id_t_sampling")
    gate, drain = compiled.envelope.channels[GATE], compiled.envelope.channels[DRAIN]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == ("bias_v", 3.0, 1e-6, 0.0,
                                                                                         3.0)
    assert (drain.function, drain.max_abs_v, drain.max_abs_i, drain.v_start, drain.v_stop) == ("bias_v", 5.0, 1e-3,
                                                                                              5.0, 5.0)
    assert compiled.flex_preview == [
        "FMT 1,1", "TSC 1", "AAD 3,0", "AIT 0,2,1", "CN 5,3", "DV 3,0,5,0.001", "MCC", "ML 1",
        "MT 0.01,0.004,10001,0.1", "MSC 2,2", "MV 5,0,0,3,1E-06", "MM 10,3", "CMM 3,1", "TSR", "XE"]
    program = program_of(compiled)
    assert program.blocks == [Block(number=10001, h_bias=0.01, h_base=0.1)]
    assert program.source_columns == {"gate_V": 3.0, "drain_V": 5.0}
    assert compiled.estimate.points == 10001
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 0.1 + 0.01 + 40.0 + 0.004 + 0.5)
    assert compiled.estimate.max_segment_s == pytest.approx(compiled.estimate.duration_s - 1.0)
    assert KIND.checkpoint_total(PlanRecord.model_construct(program=compiled.program)) == 1


def test_a_long_linear_run_is_a_chain_of_blocks_that_hold_the_stress() -> None:
    compiled = compile_recipe("reliability.tddb_cvs", v_stress=4.5, duration=14400.0, interval=2.0)
    program = program_of(compiled)
    per = int(SEGMENT_S // 2.0)
    assert program.points == 7201 and sum(b.number for b in program.blocks) == 7201
    assert program.blocks[0] == Block(number=per, h_bias=0.0, h_base=0.0)  # samples at 0, 2, ..., 22 s
    assert program.blocks[1] == Block(number=per, h_bias=2.0, h_base=0.0, timing=True, hold_sources=True)
    assert all(b == Block(number=per, h_bias=2.0, h_base=0.0) for b in program.blocks[2:-1])
    last = program.blocks[-1]
    assert last.number == (7201 - per) % per and last.timing and len(program.blocks) == 601
    assert compiled.estimate.max_segment_s <= 30.0  # inside the default segment_max_s (R-RUN-02)
    assert compiled.estimate.duration_s > 4 * 3600
    preview = compiled.flex_preview
    xe = [i for i, line in enumerate(preview) if line == "XE"]
    assert len(xe) == len(program.blocks)
    assert preview[xe[0] + 1:xe[1]] == ["MT 2,2,12,0", "MV 5,0,4.5,4.5,0.001"]  # block 2: held stress
    assert preview[xe[1] + 1:xe[2]] == []  # later blocks: XE only
    assert preview.count("TSR") == 1 and preview.index("TSR") == xe[0] - 1


def test_log_and_short_runs_are_one_block_and_log_points_are_limited() -> None:
    compiled = compile_recipe("generic.smu_sampling", pm=pin_map(stress=5, bias=3, ground="GNDU"),
                              sampling_mode="log25", points=200, interval=0.002)
    program = program_of(compiled)
    assert program.mode == 3 and len(program.blocks) == 1
    last = log_indices(25, 200)[-1]
    assert compiled.estimate.duration_s == pytest.approx(1.0 + (last - 1) * 0.002 + 0.002 + 0.5, rel=1e-6)
    with pytest.raises(CompileError, match="at most 111 points"):
        compile_recipe("generic.smu_sampling", pm=pin_map(stress=5, bias=3, ground="GNDU"), sampling_mode="log10",
                       points=112)


def test_generic_sampling_with_an_optional_bias_and_a_ground_smu() -> None:
    pm = pin_map(stress=5, bias=3, ground=4)
    compiled = compile_recipe("generic.smu_sampling", pm=pm, base=0.5, bias=1.5, icomp=2e-4, bias_v=0.2,
                              bias_icomp=1e-4)
    program = program_of(compiled)
    ground = compiled.envelope.channels[4]
    assert (ground.function, ground.max_abs_v, ground.max_abs_i) == ("ground", 0.0, pytest.approx(3e-4))
    assert [m.role for m in program.measure] == ["stress", "bias"]
    assert program.source_columns == {"stress_V": 1.5, "bias_V": 0.2}
    assert "DV 3,0,0.2,0.0001" in compiled.flex_preview and "MV 5,0,0.5,1.5,0.0002" in compiled.flex_preview
    assert "MM 10,5,3" in compiled.flex_preview


def test_current_sources_compile_to_mi_with_the_current_envelope() -> None:
    rec = recipe_with("generic.smu_sampling",
                      stress={"i": 1e-6, "base": 0.0, "vcomp": 2.0})
    rec = rec.model_copy(update={"roles": {**rec.roles, "stress": rec.roles["stress"].model_copy(
        update={"function": "bias_i", "measure": ["V"]})}})
    binding = bind_roles(rec, pin_map(stress=5, bias=None, ground="GNDU"), STATION, "x")
    compiled = KIND.compile(rec, resolve_params(rec, {})[0], binding, STATION)
    stress = compiled.envelope.channels[5]
    assert (stress.function, stress.max_abs_i, stress.max_abs_v) == ("bias_i", 1e-6, 2.0)
    assert "MI 5,0,0,1E-06,2" in compiled.flex_preview and "CMM 5,2" in compiled.flex_preview
    assert program_of(compiled).source_columns == {"stress_I": 1e-6}


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"interval": 0.0025}, "off the MT resolution"),
        ({"interval": 0.000105}, "off the MT resolution"),
        ({"hold_bias": 0.015}, "10 ms steps"),
        ({"hold_base": 700.0}, "10 ms steps"),
        ({"interval": 0.0005, "sampling_mode": "log10"}, "needs linear sampling"),
        ({"sampling_mode": "log7"}, "sampling_mode must be one of"),
        ({"points": 100001, "interval": 0.0002}, "per block"),
    ],
)
def test_parameters_the_instrument_cannot_take_are_refused(values: dict[str, Any], match: str) -> None:
    with pytest.raises(CompileError, match=match):
        compile_recipe("generic.smu_sampling", pm=pin_map(stress=5, bias=3, ground="GNDU"), **values)


def test_negative_hold_bias_and_unsupported_roles_are_refused() -> None:
    rec = REGISTRY.get("generic.smu_sampling")
    binding = bind_roles(rec, pin_map(stress=5, bias=3, ground="GNDU"), STATION, "x")
    params = resolve_params(rec, {})[0]
    params["hold_bias"] = params["hold_bias"].model_copy(update={"value": -0.01})
    with pytest.raises(CompileError, match="hold_bias must be >= 0"):
        KIND.compile(rec, params, binding, STATION)
    swept = rec.model_copy(update={"roles": {**rec.roles, "bias": rec.roles["bias"].model_copy(
        update={"function": "sweep_v"})}})
    with pytest.raises(CompileError, match="cannot execute role"):
        KIND.compile(swept, resolve_params(swept, {})[0], binding, STATION)
    both = rec.model_copy(update={"roles": {**rec.roles, "bias": rec.roles["bias"].model_copy(
        update={"measure": ["I", "V"]})}})
    with pytest.raises(CompileError, match="one quantity per channel"):
        KIND.compile(both, resolve_params(both, {})[0], binding, STATION)


def test_points_and_duration_are_exclusive() -> None:
    rec = REGISTRY.get("reliability.tddb_cvs")
    params = resolve_params(rec, {"v_stress": 5.0})[0]
    params["points"] = params["duration"].model_copy(update={"value": 10, "unit": None})
    binding = bind_roles(rec, pin_map(), STATION, "mosfet-4t")
    with pytest.raises(CompileError, match="exactly one of points and duration"):
        KIND.compile(rec, params, binding, STATION)


def test_an_unbound_measured_role_leaves_an_empty_plan_for_the_rules() -> None:
    compiled = compile_recipe("mosfet.id_t_sampling", pm=pin_map(drain=None))
    assert compiled.program == {} and compiled.estimate.points == 0


def test_the_planner_tiers_and_summarises_a_destructive_long_tddb_run() -> None:
    cfg = bundle(pin_maps=[pin_map()], duts=[dut("dielectric-generic", "dielectric", gate=(6.0, 1e-2),
                                                  drain=(1.0, 1e-2), source=(1.0, 1e-2), bulk=(1.0, 1e-2))])
    planner = Planner(REGISTRY, clock=lambda: T0)
    req = PlanRequest.model_validate({"recipe_id": "reliability.tddb_cvs", "pin_map": "mosfet-4t",
                                      "dut_profile": "dielectric-generic",
                                      "params": {"v_stress": 5.5, "duration": 3600.0}})
    plan = planner.plan(req, cfg, engine(cfg))
    assert plan.mode == "async" and plan.tier == "needs_confirmation"
    assert set(plan.rules.confirm_reasons) == {"destructive", "long_run"}
    summary = plan.summary or ""
    assert "gate=SMU5" in summary and "bias 0..5.5 V" in summary and "async ~" in summary
    too_many = req.model_copy(update={"params": {"v_stress": 5.5, "duration": 86400.0, "interval": 1.0}})
    blocked = planner.plan(too_many, cfg, engine(cfg))
    assert blocked.tier == "blocked" and any(f.rule_id == "R-RUN-01" for f in blocked.rules.findings)


# -- table -----------------------------------------------------------------------------------------------------------

XE_AT = datetime(2026, 11, 19, 10, 0, 0, tzinfo=UTC)


def raw_block(body: str, *, xe_at: datetime = XE_AT, expected: int = 3) -> RawBlock:
    points = tuple(parse_fmt1(body))
    return RawBlock(raw=body, points=points, fmt=1, expected_points=expected, xe_at=xe_at, read_at=xe_at,
                    duration_s=0.0)


def chain_program() -> SamplingProgram:
    return program_of(compile_recipe("reliability.tddb_cvs", v_stress=4.5, duration=100.0, interval=2.0))


def element(index: int, t: float | None, value: float, status: str = "N", ch: int = GATE) -> str:
    """One sample of one measured channel as the simulator formats it: index, [time stamp,] value."""
    parts = [Element("N", ch, "X", float(index)).text()]
    if t is not None:
        parts.append(Element("N", ch, "T", t).text())
    parts.append(Element(status, ch, "I", value).text())
    return ",".join(parts)


def test_rows_count_t_s_from_the_bias_step_across_blocks() -> None:
    program = chain_program()  # 51 points: 12 per block (block 1: 0..22 s), each later one from 2 s after its trigger
    first, second = program.blocks[0], program.blocks[1]
    # the timer read 100 s at the step (an earlier TSR): t_s = stamp - origin
    b1 = ",".join(element(k, 100.0 + (k - 1) * 2.0, 1e-9) for k in range(1, first.number + 1))
    b2 = ",".join(element(k, 124.05 + 2.0 + (k - 1) * 2.0, 1e-9) for k in range(1, second.number + 1))
    plan = PlanRecord.model_construct(program=program.model_dump(mode="json"))
    raw = RawAcquisition(blocks=[raw_block(b1), raw_block(b2)])
    table = KIND.to_table(raw, plan)
    assert table["step"].tolist() == list(range(first.number + second.number))
    assert table["t_s"].iloc[0] == 0.0 and table["t_s"].iloc[first.number - 1] == pytest.approx(22.0)
    assert table["t_s"].iloc[first.number] == pytest.approx(26.05)
    assert list(table.columns) == ["step", "t_s", "gate_I", "gate_I_status", "gate_V"]
    assert (table["gate_V"] == 4.5).all()
    validate_table(with_trust(table))


def test_without_time_stamps_t_s_comes_from_the_index_and_the_host_trigger_times() -> None:
    """ATV-22 fallback: the sampling index on the MT grid, offset by the host's trigger times between blocks."""
    program = chain_program()
    first, second = program.blocks[0], program.blocks[1]
    b1 = ",".join(element(k, None, 1e-9) for k in range(1, first.number + 1))
    b2 = ",".join(element(k, None, 1e-9) for k in range(1, second.number + 1))
    later = XE_AT + timedelta(seconds=24.5)
    raw = RawAcquisition(blocks=[raw_block(b1), raw_block(b2, xe_at=later)])
    table = KIND.to_table(raw, PlanRecord.model_construct(program=program.model_dump(mode="json")))
    assert table["t_s"].iloc[1] == pytest.approx(2.0)
    assert table["t_s"].iloc[first.number] == pytest.approx(24.5 + 2.0)  # host offset + h_bias of block 2


def test_dummy_samples_are_dropped_and_index_gaps_counted() -> None:
    program = program_of(compile_recipe("mosfet.id_t_sampling", points=6, interval=0.01, hold_bias=0.0,
                                        hold_base=0.0))
    body = ",".join([element(1, 0.0, 1e-6, ch=DRAIN), element(3, 0.02, 1e-6, ch=DRAIN),
                     element(4, 0.03, 1e-3, "C", ch=DRAIN), element(5, 0.04, 0.0, "V", ch=DRAIN)])
    rows = _Rows(program)
    out = rows.add(program.blocks[0], raw_block(body))
    assert [r["t_s"] for r in out] == pytest.approx([0.0, 0.02, 0.03])
    assert rows.gaps == 1 and rows.dummies == 1 and rows.aborted and rows.abort_t_s == pytest.approx(0.03)
    assert "drain_I C" in rows.abort_reason


def test_to_table_refuses_blocks_it_cannot_place() -> None:
    program = program_of(compile_recipe("mosfet.id_t_sampling", points=3))
    plan = PlanRecord.model_construct(program=program.model_dump(mode="json"))
    with pytest.raises(ValueError, match="expects 1..1 data blocks"):
        KIND.to_table(RawAcquisition(blocks=[]), plan)
    dummy = "NCX+1.00000E+00,NCT+0.00000E+00,VCI+199.999E+99"
    with pytest.raises(ValueError, match="no measured sample"):
        KIND.to_table(RawAcquisition(blocks=[raw_block(dummy)]), plan)


def test_dummy_data_without_a_flagged_sample_also_ends_the_chain() -> None:
    """The interlock zeroing the outputs (or an abort whose sample the read lost) leaves only dummy data: the chain
    stops there too."""
    program = program_of(compile_recipe("mosfet.id_t_sampling", points=4, interval=0.01, hold_bias=0.0,
                                        hold_base=0.0))
    body = ",".join([element(1, 0.0, 1e-6, ch=DRAIN), element(2, 0.01, 0.0, "V", ch=DRAIN),
                     element(3, 0.02, 0.0, "V", ch=DRAIN)])
    rows = _Rows(program)
    out = rows.add(program.blocks[0], raw_block(body))
    assert len(out) == 1 and rows.dummies == 2 and rows.aborted and rows.abort_t_s == 0.0
    assert "dummy data" in rows.abort_reason
