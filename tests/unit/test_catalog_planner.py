"""Planner and kinds without any I/O (blueprint 2.1, 2.6): parameter resolution, binding, compilation (envelope,
estimate, FLEX preview, program), plan identity and the plan store's tamper check."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.catalog.kinds import SmuStaircaseKind, StaircaseProgram, SystemKind
from b1500_test_agent.catalog.kinds.smu_staircase import INTEGRATION_PRESETS, measurement_time_s
from b1500_test_agent.catalog.planner import (
    Planner,
    PlanStore,
    UnknownPlanError,
    bind_roles,
    coerce_param,
    plan_hash_of,
    plan_id_for,
    resolve_params,
)
from b1500_test_agent.catalog.registry import RecipeRegistry, UnknownRecipeError
from b1500_test_agent.catalog.schema import CompileError, RawAcquisition
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.recipe import ParamSpec, Recipe
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import IDVD, IDVG, SYSTEM, T0, bundle, dut, engine, example_station, pin_map, recipe

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()


def params_of(rec: Recipe, **values: Any) -> dict[str, Quantity]:
    return resolve_params(rec, values)[0]


def compile_idvg(rec: Recipe | None = None, *, pm: Any = None, **values: Any):
    rec = rec or recipe()
    binding = bind_roles(rec, pm or pin_map(), STATION, "mosfet-4t")
    return SmuStaircaseKind().compile(rec, params_of(rec, **values), binding, STATION)


def make_plan(**request: Any) -> PlanRecord:
    cfg = bundle(pin_maps=[pin_map()], duts=[dut()])
    req = PlanRequest.model_validate({"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t",
                                      "dut_profile": "nmos-generic", **request})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


# -- resolution and binding ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("spec", "value", "expected", "ok"), [
    (ParamSpec(type="int"), 101.0, 101, True),
    (ParamSpec(type="int"), 101.5, 101.5, False),
    (ParamSpec(type="int"), True, True, False),
    (ParamSpec(type="float", unit="V"), 3, 3.0, True),
    (ParamSpec(type="float"), "3", "3", False),
    (ParamSpec(type="float"), False, False, False),
    (ParamSpec(type="float_list"), [1, 2.5], [1.0, 2.5], True),
    (ParamSpec(type="float_list"), [], [], False),
    (ParamSpec(type="enum", choices=["a", "b"]), "b", "b", True),
    (ParamSpec(type="enum", choices=["a", "b"]), "c", "c", False),
    (ParamSpec(type="bool"), 1, 1, False),
])
def test_coerce_param(spec: ParamSpec, value: Any, expected: Any, ok: bool) -> None:
    out, well_typed = coerce_param(spec, value)
    assert out == expected and type(out) is type(expected) and well_typed is ok


def test_resolve_params_defaults_units_and_mistyped() -> None:
    rec = recipe()
    resolved, mistyped = resolve_params(rec, {"vg_stop": 2, "vg_points": "many", "bogus": 1})
    assert resolved["vg_stop"] == Quantity(value=2.0, unit="V") and resolved["vd"] == Quantity(value=0.05, unit="V")
    assert resolved["vg_points"] == Quantity(value="many") and resolved["integration"].value == "medium"
    assert mistyped == ["vg_points"] and "bogus" not in resolved


def test_bind_roles() -> None:
    rec = recipe()
    binding = bind_roles(rec, pin_map(gate=5, drain=4, source=None), STATION, "mosfet-4t")
    assert set(binding.roles) == {"gate", "drain"}
    gate = binding.roles["gate"]
    assert (gate.channel, gate.slot, gate.module_type, gate.module_model, gate.alias) == \
        (5, 5, "MPSMU", "B1511B", "SMU5")
    assert gate.via is None and gate.cmu_side is None
    assert binding.roles["drain"].module_type == "HRSMU"
    grounded = bind_roles(rec, pin_map(), STATION, "mosfet-4t").roles["source"]
    assert grounded.gndu and grounded.channel is None
    assert bind_roles(rec, None, STATION, "ghost").roles == {}
    assert bind_roles(rec, pin_map(gate=9), STATION, "x").roles["gate"].module_type is None


# -- staircase kind --------------------------------------------------------------------------------------------------


def test_idvg_compiles_to_envelope_estimate_preview_and_program() -> None:
    compiled = compile_idvg()
    gate, drain = compiled.envelope.channels[5], compiled.envelope.channels[3]
    assert (gate.role, gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == ("gate", 3.0, 1e-6, -1.0, 3.0)
    assert (drain.role, drain.max_abs_v, drain.max_abs_i, drain.function) == ("drain", 0.05, 1e-3, "bias_v")
    assert compiled.flex_preview == ["FMT 1,1", "AAD 5,0", "AAD 3,0", "AIT 0,2,1", "CN 5,3", "DV 3,0,0.05,0.001",
                                     "MM 2,5,3", "CMM 5,1", "CMM 3,1", "WV 5,1,0,-1,3,101,1E-06", "WT 0,0", "WM 2,1",
                                     "XE"]
    assert compiled.routes_by_phase == {} and compiled.envelope.routes == frozenset()
    assert compiled.estimate.points == 101
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 101 * 2 * 0.02)
    program = StaircaseProgram.model_validate(json.loads(json.dumps(compiled.program)))
    assert program.width == 3 and program.steps == 101 and program.source_columns == {"drain_V": 0.05}
    assert [m.role for m in program.measure] == ["gate", "drain"]


def test_ground_on_an_smu_gets_the_summed_compliance_unless_explicit() -> None:
    compiled = compile_idvg(pm=pin_map(source=6))
    source = compiled.envelope.channels[6]
    assert (source.max_abs_v, source.max_abs_i, source.function) == (0.0, pytest.approx(1e-3 + 1e-6), "ground")
    assert "DV 6,0,0,0.001001" in compiled.flex_preview and "CN 5,3,6" in compiled.flex_preview
    explicit = recipe(IDVG, roles={**IDVG["roles"], "source": {"function": "ground", "allow_gndu": True,
                                                              "settings": {"icomp": 5e-3}}})
    assert compile_idvg(explicit, pm=pin_map(source=6)).envelope.channels[6].max_abs_i == 5e-3


def test_presets_double_sweep_and_unbound_sweep() -> None:
    assert measurement_time_s(INTEGRATION_PRESETS["long"]) == pytest.approx(16 / 50)
    assert "AIT 0,0,1" in compile_idvg(integration="short").flex_preview
    double = recipe(IDVG, roles={**IDVG["roles"], "gate": {**IDVG["roles"]["gate"], "settings": {
        **IDVG["roles"]["gate"]["settings"], "mode": "double"}}})
    compiled = compile_idvg(double)
    assert compiled.estimate.points == 202 and "WV 5,3,0,-1,3,101,1E-06" in compiled.flex_preview
    unbound = compile_idvg(pm=pin_map(gate=None))
    assert unbound.program == {} and unbound.flex_preview == [] and list(unbound.envelope.channels) == [3]


@pytest.mark.parametrize(("base", "roles", "message"), [
    (IDVD, IDVD["roles"], "smu_stepped"),
    (IDVG, {**IDVG["roles"], "gate": {**IDVG["roles"]["gate"], "function": "bias_v"}}, "needs a sweep_v or sweep_i"),
    (IDVG, {**IDVG["roles"], "drain": {"function": "sync_i", "settings": {"start": 0, "stop": 1e-6, "vcomp": 1}}},
     "must force what the primary"),
    (IDVG, {**IDVG["roles"], "drain": {**IDVG["roles"]["drain"], "measure": ["I", "V"]}}, "one quantity per channel"),
    (IDVG, {**IDVG["roles"], "gate": {**IDVG["roles"]["gate"], "measure": []},
            "drain": {**IDVG["roles"]["drain"], "measure": []}}, "no bound role measures"),
    (IDVG, {**IDVG["roles"], "drain": {"function": "pgu"}}, r"cannot execute role\(s\) drain \(pgu\)"),
    (IDVG, {**IDVG["roles"], "drain": {"function": "pulse_v", "measure": ["I"]}}, "pulse_v"),
])
def test_staircase_refuses_what_it_cannot_express(base: dict[str, Any], roles: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_idvg(recipe(base, roles=roles))


def test_to_table_checks_the_element_count() -> None:
    plan = make_plan()
    with pytest.raises(ValueError, match="expected 303 elements"):
        SmuStaircaseKind().to_table(RawAcquisition(blocks=[_block(3)]), plan)
    with pytest.raises(ValueError, match="one data block"):
        SmuStaircaseKind().to_table(RawAcquisition(blocks=[]), plan)


def _block(n: int) -> RawBlock:
    points = parse_fmt1(",".join(["NAI+1.00000E-09"] * n))
    now = datetime.now(UTC)
    return RawBlock(raw="", points=tuple(points), fmt=1, expected_points=n, xe_at=now, read_at=now, duration_s=0.0)


# -- other kinds -----------------------------------------------------------------------------------------------------


def test_system_kind() -> None:
    rec = recipe(SYSTEM, params={"operation": {"type": "enum", "choices": ["self_test"], "default": "self_test"}})
    compiled = SystemKind().compile(rec, params_of(rec), bind_roles(rec, None, STATION, "x"), STATION)
    assert compiled.flex_preview == ["*TST?"] and compiled.program == {"operation": "self_test"}
    assert compiled.envelope.channels == {} and compiled.estimate.duration_s > 0
    with pytest.raises(CompileError, match="operation"):
        SystemKind().compile(recipe(SYSTEM), {}, bind_roles(rec, None, STATION, "x"), STATION)
    with pytest.raises(CompileError, match="no DUT roles"):
        SystemKind().compile(recipe(), params_of(recipe()), bind_roles(recipe(), pin_map(), STATION, "x"), STATION)


# -- planner and identity --------------------------------------------------------------------------------------------


def test_planned_idvg_is_ok_and_hash_identified() -> None:
    plan = make_plan(label="a")
    assert plan.tier == "ok" and plan.rules.findings == [] and plan.plan_id == plan_id_for(plan.plan_hash)
    assert plan.plan_hash == plan_hash_of(plan) and plan.expires_at == T0.replace(day=18)
    relabelled = make_plan(label="b")
    assert relabelled.plan_id == plan.plan_id
    assert make_plan(params={"vd": 0.06}).plan_id != plan.plan_id
    edited = plan.model_copy(update={"flex_preview": ["XE"]})
    assert plan_hash_of(edited) != plan.plan_hash
    assert plan_hash_of(plan.model_copy(update={"summary": "x", "tier": "blocked"})) == plan.plan_hash


def test_mistyped_parameters_give_a_blocked_uncompiled_plan() -> None:
    plan = make_plan(params={"vg_points": "many"})
    assert plan.tier == "blocked" and plan.program == {} and plan.envelope.channels == {}
    assert any(f.rule_id == "R-PARAM-01" and "vg_points" in f.message for f in plan.rules.findings)


def test_unknown_recipe_and_unexplained_compile_errors(tmp_path: Path) -> None:
    with pytest.raises(UnknownRecipeError):
        make_plan(recipe_id="nope.nothing")
    data = yaml.safe_load((REPO_ROOT / "recipes/mosfet/idvg.yaml").read_text(encoding="utf-8"))
    data["roles"]["gate"]["settings"]["scale"] = "log"  # log sweep from -1 V: the kind cannot compile it
    (tmp_path / "recipes/mosfet").mkdir(parents=True)
    (tmp_path / "recipes/mosfet/idvg.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    registry = RecipeRegistry.load(tmp_path / "recipes")
    cfg = bundle(pin_maps=[pin_map()], duts=[dut()])
    req = PlanRequest(recipe_id="mosfet.idvg", pin_map="mosfet-4t", dut_profile="nmos-generic")
    with pytest.raises(InvalidInputError, match="invalid sweep"):
        Planner(registry).plan(req, cfg, engine(cfg))


def test_plan_store_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    plan = make_plan()
    path = store.save(plan)
    assert path == tmp_path / "plans" / f"{plan.plan_id}.json" and store.load(plan.plan_id) == plan
    data = json.loads(path.read_text(encoding="utf-8"))
    data["resolved_params"]["vd"]["value"] = 0.5
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(UnknownPlanError, match="does not match its hash"):
        store.load(plan.plan_id)
    other = make_plan(params={"vd": 0.07})
    path.write_text(other.model_dump_json(), encoding="utf-8")  # a valid plan stored under the wrong id
    with pytest.raises(UnknownPlanError):
        store.load(plan.plan_id)
    for bad in ("P-0000000000", "x", "P-ABC"):
        with pytest.raises(UnknownPlanError):
            store.load(bad)
