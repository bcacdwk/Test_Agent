"""``smu_stepped`` without any I/O (blueprint 2.6): compile (envelope over every step, estimate, FLEX preview,
program), the step-value forms and refusals, the planner/summary path, and ``to_table`` (column naming and the
global step index) on synthetic blocks. Acquisition runs in ``tests/safety`` and ``tests/integration``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import validate_table, with_trust
from b1500_test_agent.catalog.kinds import SmuSteppedKind, SteppedProgram, default_kinds
from b1500_test_agent.catalog.kinds.smu_stepped import STEP_OVERHEAD_S
from b1500_test_agent.catalog.planner import Planner, bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError, RawAcquisition
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.recipe import Recipe
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import IDVD, T0, bundle, dut, engine, example_station, pin_map, recipe

pytestmark = pytest.mark.smu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = SmuSteppedKind()


def compile_stepped(rec: Recipe | None = None, *, pm: Any = None, **values: Any):
    rec = rec or REGISTRY.get("mosfet.idvd")
    binding = bind_roles(rec, pm or pin_map(), STATION, "mosfet-4t")
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION)


def with_gate(**settings: Any) -> dict[str, Any]:
    """The rules-factory Id-Vd recipe with the gate (step) role's settings replaced."""
    data = json.loads(json.dumps(IDVD))
    data["roles"]["gate"]["settings"] = settings
    return data


# -- compile ---------------------------------------------------------------------------------------------------------


def test_idvd_compiles_to_envelope_estimate_preview_and_program() -> None:
    compiled = compile_stepped(vg_stop=2.0, vg_points=4)  # four gate steps 0.5 .. 2.0 V
    gate, drain = compiled.envelope.channels[5], compiled.envelope.channels[3]
    assert (gate.role, gate.function, gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == \
        ("gate", "step_v", 2.0, 1e-6, 0.5, 2.0)
    assert (drain.role, drain.function, drain.max_abs_v, drain.max_abs_i, drain.v_start, drain.v_stop) == \
        ("drain", "sweep_v", 3.0, 1e-3, 0.0, 3.0)
    assert set(compiled.envelope.channels) == {5, 3}  # the source is on the GNDU
    assert compiled.flex_preview == [
        "FMT 1,1", "AAD 3,0", "AAD 5,0", "AIT 0,2,1", "CN 3,5", "MM 2,3,5", "CMM 3,1", "CMM 5,1",
        "WV 3,1,0,0,3,101,0.001", "WT 0,0", "WM 2,1",
        "DV 5,0,0.5,1E-06", "XE", "DV 5,0,1,1E-06", "XE", "DV 5,0,1.5,1E-06", "XE", "DV 5,0,2,1E-06", "XE",
    ]
    program = SteppedProgram.model_validate(json.loads(json.dumps(compiled.program)))
    assert program.step_values == [0.5, 1.0, 1.5, 2.0] and program.step_channel == 5 and program.step_comp == 1e-6
    assert program.step_source == "V"
    assert program.step_role == "gate" and program.step_column == "gate_V"
    assert program.staircase.biases == [] and program.staircase.source_columns == {}  # the step is not a bias
    assert [m.role for m in program.staircase.measure] == ["drain", "gate"] and program.staircase.width == 3
    assert compiled.estimate.points == program.points == 4 * 101
    sweep = program.sweep_estimate_s
    assert sweep == pytest.approx(1.0 + 101 * 2 * 0.02)  # one sweep: setup allowance + 101 x 2 channels x 1 PLC
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 4 * (sweep - 1.0 + STEP_OVERHEAD_S))


def test_values_list_parameter_keeps_its_order() -> None:
    data = with_gate(values="$vg_list", icomp="$icomp_gate")
    data["params"] = {**data["params"], "vg_list": {"type": "float_list", "unit": "V", "default": [1.2, 0.0, -0.4]}}
    compiled = compile_stepped(recipe(data))
    gate = compiled.envelope.channels[5]
    assert (gate.max_abs_v, gate.v_start, gate.v_stop) == (1.2, 1.2, -0.4)
    assert compiled.program["step_values"] == [1.2, 0.0, -0.4]
    assert [line for line in compiled.flex_preview if line.startswith("DV 5,")] == \
        ["DV 5,0,1.2,1E-06", "DV 5,0,0,1E-06", "DV 5,0,-0.4,1E-06"]


def test_single_point_and_rounding() -> None:
    one = compile_stepped(vg_points=1)
    assert one.program["step_values"] == [0.5] and one.estimate.points == 101
    three = compile_stepped(recipe(with_gate(start=0.0, stop=0.3, points=4, icomp="$icomp_gate")))
    assert three.program["step_values"] == [0.0, 0.1, 0.2, 0.3]  # 1 nV rounding removes 0.30000000000000004


def test_grounded_source_smu_gets_the_summed_compliance_including_the_step() -> None:
    compiled = compile_stepped(pm=pin_map(source=6))
    source = compiled.envelope.channels[6]
    assert (source.function, source.max_abs_v, source.max_abs_i) == ("ground", 0.0, pytest.approx(1e-3 + 1e-6))
    assert "DV 6,0,0,0.001001" in compiled.flex_preview


def test_unbound_step_or_sweep_compiles_to_no_program() -> None:
    no_step = compile_stepped(pm=pin_map(gate=None))
    assert no_step.program == {} and no_step.flex_preview == [] and list(no_step.envelope.channels) == [3]
    no_sweep = compile_stepped(pm=pin_map(drain=None))
    assert no_sweep.program == {} and no_sweep.estimate.points == 0


@pytest.mark.parametrize(("data", "message"), [
    ({**IDVD, "roles": {**IDVD["roles"], "gate": {**IDVD["roles"]["gate"], "function": "bias_v"}}},
     "exactly one step_v or step_i role"),
    ({**IDVD, "roles": {**IDVD["roles"], "bulk": {**IDVD["roles"]["gate"]}}}, "exactly one step_v or step_i role"),
    ({**IDVD, "roles": {**IDVD["roles"], "gate": {**IDVD["roles"]["gate"], "measure": ["V"]}}}, "must not measure V"),
    (with_gate(start=1.0, stop=1.0, points=3, icomp="$icomp_gate"), "distinct"),
    (with_gate(start=0.0, stop=1.0, icomp="$icomp_gate"), "points must be a positive integer"),
    (with_gate(start=0.0, stop=1.0, points=2), "icomp must be a finite number"),
])
def test_refuses_what_it_cannot_express(data: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_stepped(recipe(data))


def test_values_and_range_are_exclusive() -> None:
    data = with_gate(values="$vg_list", start=0.0, icomp="$icomp_gate")
    data["params"] = {**data["params"], "vg_list": {"type": "float_list", "unit": "V", "default": [1.0]}}
    with pytest.raises(CompileError, match="either values or start/stop/points"):
        compile_stepped(recipe(data))


def test_registered_for_sim_and_visa() -> None:
    kind = default_kinds()["smu_stepped"]
    assert isinstance(kind, SmuSteppedKind) and kind.implemented_on == {"sim", "visa"}
    assert REGISTRY.get("mosfet.idvd").status == "sim_validated" and REGISTRY.runnable("mosfet.idvd", "sim")  # WP2.2
    assert REGISTRY.problems() == []


# -- planner and summary ---------------------------------------------------------------------------------------------


def make_plan(**params: Any) -> PlanRecord:
    cfg = bundle(pin_maps=[pin_map()], duts=[dut()])
    req = PlanRequest.model_validate({"recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t",
                                      "dut_profile": "nmos-generic", "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


def test_plan_tier_and_summary() -> None:
    plan = make_plan()
    assert plan.kind == "smu_stepped" and plan.tier == "ok"
    assert not any(f.rule_id == "R-REC-01" for f in plan.rules.findings)  # sim_validated on sim (WP2.2)
    assert plan.summary == ("mosfet.idvd@1 | drain=SMU3(HRSMU) sweep 0..3 V Icomp 1 mA; gate=SMU5(MPSMU) step "
                            "0.5..1.5 V Icomp 1 uA | DUT nmos-generic | pins mosfet-4t | sim")
    beyond = make_plan(vg_stop=3.5)  # the DUT gate envelope is 3 V: every step value is checked
    assert beyond.tier == "needs_confirmation" and beyond.rules.confirm_reasons == ["dut_envelope"]


# -- to_table --------------------------------------------------------------------------------------------------------


def _block(currents: list[tuple[float, float]], *, abort_from: int | None = None) -> RawBlock:
    """One sweep block of the idvd program shape: per step drain I (channel 3 = C), gate I (channel 5 = E) and the
    drain source value; steps from ``abort_from`` on carry the dummy value with status V."""
    elements = []
    last = len(currents) - 1
    for i, (i_d, i_g) in enumerate(currents):
        source = "E" if i == last else "W"
        if abort_from is not None and i >= abort_from:
            elements += ["VCI+199.999E+99", "VEI+199.999E+99", f"{source}CV+199.999E+99"]
        else:
            elements += [f"NCI{i_d:+.5E}", f"NEI{i_g:+.5E}", f"{source}CV{0.03 * i:+.5E}"]
    points = parse_fmt1(",".join(elements))
    now = datetime.now(UTC)
    return RawBlock(raw="", points=tuple(points), fmt=1, expected_points=len(points), xe_at=now, read_at=now,
                    duration_s=0.0)


def test_to_table_names_the_step_column_and_numbers_steps_globally() -> None:
    plan = make_plan(vd_points=11, vg_points=3, vg_stop=2.0)
    sweep = [(1e-6 * k, 1e-12) for k in range(11)]
    table = KIND.to_table(RawAcquisition(blocks=[_block(sweep), _block(sweep), _block(sweep)]), plan)
    assert list(table.columns) == ["step", "drain_V", "gate_V", "drain_I", "drain_I_status", "gate_I",
                                   "gate_I_status"]
    assert table["step"].tolist() == list(range(33))
    assert table["gate_V"].tolist() == [0.5] * 11 + [1.25] * 11 + [2.0] * 11
    assert [len(curve) for _, curve in table.groupby("gate_V", sort=False)] == [11, 11, 11]
    assert table["drain_V"].iloc[12] == pytest.approx(0.03)
    tidy = validate_table(with_trust(table))  # the data.csv contract accepts it: gate_V is a source column
    assert "gate_V_status" not in tidy.columns and tidy["trust"].unique().tolist() == ["ok"]


def test_to_table_after_an_early_stop_has_only_the_measured_curves() -> None:
    plan = make_plan(vd_points=11, vg_points=4, vg_stop=2.0)
    sweep = [(1e-6 * k, 1e-12) for k in range(11)]
    table = KIND.to_table(RawAcquisition(blocks=[_block(sweep), _block(sweep, abort_from=6)]), plan)
    assert len(table) == 22 and table["gate_V"].unique().tolist() == [0.5, 1.0]
    assert table["drain_I_status"].tolist()[11:] == ["N"] * 6 + ["V"] * 5
    with pytest.raises(ValueError, match="1..4 data blocks"):
        KIND.to_table(RawAcquisition(blocks=[]), plan)
    with pytest.raises(ValueError, match="expected 33 elements"):
        KIND.to_table(RawAcquisition(blocks=[_block(sweep[:5])]), plan)


def test_double_sweep_segments_per_curve() -> None:
    data = REGISTRY.get("mosfet.idvd").model_dump(mode="json", by_alias=True, exclude={"sha256"})
    data["roles"]["drain"]["settings"] = {**data["roles"]["drain"]["settings"], "mode": "double"}
    compiled = compile_stepped(recipe(data), vd_points=11, vd_stop=0.3, vg_points=2)
    program = SteppedProgram.model_validate(compiled.program)
    assert program.staircase.steps == 22 and compiled.estimate.points == 22 * 2
    assert "WV 3,3,0,0,0.3,11,0.001" in compiled.flex_preview
    plan = make_plan(vd_points=11, vg_points=2).model_copy(update={"program": compiled.program})
    sweep = [(1e-6 * k, 1e-12) for k in range(22)]
    table = KIND.to_table(RawAcquisition(blocks=[_block(sweep), _block(sweep)]), plan)
    assert table["segment"].tolist() == (["fwd"] * 11 + ["rev"] * 11) * 2
    assert list(table.columns)[:4] == ["step", "segment", "drain_V", "gate_V"]
