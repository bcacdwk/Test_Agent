"""Kinds ``smu_staircase``/``smu_stepped`` v2 without I/O (blueprint v2 2.7, WP7.2): current primary (``WI``),
synchronous ``sync_v``/``sync_i`` (``WSV``/``WSI``), several sweep roles = MM 16 with ``WNX``, ``bias_i`` (``DI``),
``step_i`` (``DI`` per step): envelopes (a current source bounds |I| by its levels and |V| by its Vcomp), previews,
programs, refusals and the table columns of follower, bias and step sources."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SmuStaircaseKind, SmuSteppedKind, StaircaseProgram, SteppedProgram
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError, RawAcquisition
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.station import PinMap
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station
from tests.unit.rules_factory import recipe as factory_recipe

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
TWO = PinMap(name="two", certainty="verified", terminals={"a": 3, "b": 5, "c": 4, "d": 6, "g": "GNDU"})


def recipe(kind: str, roles: dict[str, Any], params: dict[str, Any] | None = None) -> Recipe:
    return factory_recipe({
        "id": "generic.test_sweep", "version": 1, "title": "test", "family": "smu", "kind": kind,
        "status": "draft", "card": None, "device_types": [], "roles": roles, "params": params or {},
        "quality": {"limited": ["C", "T"], "untrusted": ["V", "X", "F", "D", "G", "S", "U"]},
        "provenance": {"sources": ["tests"], "validation_runs": []},
    })


def compile_with(rec: Recipe, pin_map: PinMap = TWO, **values: Any):
    kind = SmuSteppedKind() if rec.kind == "smu_stepped" else SmuStaircaseKind()
    binding = bind_roles(rec, pin_map, STATION, pin_map.name)
    return kind.compile(rec, resolve_params(rec, values)[0], binding, STATION)


def registry_compile(recipe_id: str, terminals: dict[str, Any], **values: Any):
    return compile_with(REGISTRY.get(recipe_id), PinMap(name="pm", certainty="verified", terminals=terminals),
                        **values)


SWEEP_I = {"function": "sweep_i", "measure": ["V"], "settings": {"start": 1e-9, "stop": 1e-3, "points": 61,
                                                                 "vcomp": 2.0, "scale": "log"}}
SWEEP_V = {"function": "sweep_v", "measure": ["I"], "settings": {"start": 0.0, "stop": 1.0, "points": 11,
                                                                 "icomp": 1e-3}}
GROUND = {"function": "ground", "allow_gndu": True}


# -- current primary, bias_i -----------------------------------------------------------------------------------------


def test_iv_force_i_compiles_a_log_current_sweep() -> None:
    compiled = registry_compile("basic.iv_force_i", {"anode": 3, "cathode": "GNDU"})
    anode = compiled.envelope.channels[3]
    assert (anode.function, anode.max_abs_i, anode.max_abs_v, anode.v_start) == ("sweep_i", 1e-2, 2.0, None)
    assert compiled.flex_preview == ["FMT 1,1", "AAD 3,0", "AIT 0,2,1", "CN 3", "MM 2,3", "CMM 3,2",
                                     "WI 3,2,0,1E-09,0.01,71,2", "WT 0,0", "WM 2,1", "XE"]
    program = StaircaseProgram.model_validate(compiled.program)
    assert program.sweep.source == "I" and program.sweep.vcomp == 2.0 and program.sweep.icomp is None
    assert compiled.estimate.points == 71


def test_a_grounded_smu_returns_the_forced_currents() -> None:
    rec = recipe("smu_staircase", {"a": SWEEP_I, "b": {"function": "bias_i", "settings": {"i": -5e-6, "vcomp": 1.0}},
                                   "g": {"function": "ground"}})
    compiled = compile_with(rec, PinMap(name="g", certainty="verified", terminals={"a": 3, "b": 5, "g": 6}))
    ground = compiled.envelope.channels[6]
    assert ground.max_abs_i == pytest.approx(1e-3 + 5e-6)  # forced currents, not Vcomps
    bias = compiled.envelope.channels[5]
    assert (bias.function, bias.max_abs_i, bias.max_abs_v) == ("bias_i", 5e-6, 1.0)
    assert "DI 5,0,-5E-06,1" in compiled.flex_preview and "DV 6,0,0,0.001005" in compiled.flex_preview
    program = StaircaseProgram.model_validate(compiled.program)
    assert program.source_columns == {"b_I": -5e-6}  # bias_i writes its forced current


# -- synchronous sources ---------------------------------------------------------------------------------------------


def test_idvg_sync_compiles_wsv_after_wv() -> None:
    compiled = registry_compile("mosfet.idvg_sync", {"gate": 4, "drain": 3, "source": "GNDU"})
    assert compiled.flex_preview[-5:] == ["WV 4,1,0,0,1.2,121,1E-06", "WSV 3,0,0.2,1.2,0.001", "WT 0,0", "WM 2,1",
                                          "XE"]
    drain = compiled.envelope.channels[3]
    assert (drain.function, drain.max_abs_v, drain.v_start, drain.v_stop) == ("sync_v", 1.2, 0.2, 1.2)
    program = StaircaseProgram.model_validate(compiled.program)
    assert program.follower_roles == ["drain"] and program.sweep.sync is not None


def test_sync_i_follows_a_current_primary() -> None:
    rec = recipe("smu_staircase", {"a": SWEEP_I, "b": {"function": "sync_i", "measure": ["V"], "settings": {
        "start": 1e-10, "stop": 1e-4, "vcomp": 1.5}}, "g": GROUND})
    compiled = compile_with(rec)
    assert "WSI 5,0,1E-10,0.0001,1.5" in compiled.flex_preview
    assert compiled.envelope.channels[5].function == "sync_i"


# -- multi-channel sweep ---------------------------------------------------------------------------------------------


def test_two_sweep_roles_make_a_multi_channel_sweep() -> None:
    rec = recipe("smu_staircase", {
        "a": SWEEP_V,
        "c": {"function": "sweep_v", "measure": ["I"], "settings": {"start": 0.0, "stop": -1.0, "icomp": 1e-4}},
        "b": {"function": "sweep_i", "measure": ["V"], "settings": {"start": 0.0, "stop": 1e-5, "vcomp": 2.0}},
        "g": GROUND})
    compiled = compile_with(rec)
    preview = compiled.flex_preview
    assert preview[preview.index("MM 16,3,4,5"):] == [
        "MM 16,3,4,5", "CMM 3,1", "CMM 4,1", "CMM 5,2", "WV 3,1,0,0,1,11,0.001", "WNX 2,4,1,0,0,-1,0.0001",
        "WNX 3,5,2,0,0,1E-05,2", "WT 0,0", "WM 2,1", "XE"]
    program = StaircaseProgram.model_validate(compiled.program)
    assert program.follower_roles == ["c", "b"] and program.sweep.multi_channel


def test_an_unbound_optional_second_sweep_keeps_mm16() -> None:
    compiled = registry_compile("generic.smu_multi_sweep", {"a": 3, "b": "GNDU"})
    assert "MM 16,3" in compiled.flex_preview and not any(c.startswith("WNX") for c in compiled.flex_preview)


def test_follower_table_columns_follow_the_primary_steps() -> None:
    rec = recipe("smu_staircase", {
        "a": {**SWEEP_V, "settings": {**SWEEP_V["settings"], "points": 3, "mode": "double"}},
        "c": {"function": "sweep_v", "settings": {"start": 0.0, "stop": -1.0, "icomp": 1e-4}}, "g": GROUND})
    compiled = compile_with(rec)
    program = StaircaseProgram.model_validate(compiled.program)
    plan = PlanRecord.model_construct(program=compiled.program, plan_id="P-TEST")
    sources = ["+0.00000E+00", "+500.000E-03", "+1.00000E+00", "+1.00000E+00", "+500.000E-03", "+0.00000E+00"]
    raw = ",".join(f"NCI+{i}.00000E-06,{'E' if i == 5 else 'W'}CV{v}" for i, v in enumerate(sources))
    now = datetime.now(UTC)
    points = tuple(parse_fmt1(raw))
    block = RawBlock(raw=raw, points=points, fmt=1, expected_points=len(points), xe_at=now, read_at=now,
                     duration_s=0.0)
    table = SmuStaircaseKind().to_table(RawAcquisition(blocks=[block]), plan)
    assert list(table.columns) == ["step", "segment", "a_V", "c_V", "a_I", "a_I_status"]
    assert table["c_V"].tolist() == [0.0, -0.5, -1.0, -1.0, -0.5, 0.0] and program.steps == 6


@pytest.mark.parametrize(("roles", "message"), [
    ({"a": {**SWEEP_V, "function": "bias_v", "settings": {"v": 1, "icomp": 1e-3}}, "g": GROUND},
     "needs a sweep_v or sweep_i"),
    ({"a": SWEEP_V, "b": {"function": "sync_i", "settings": {"start": 0, "stop": 1e-6, "vcomp": 1}}, "g": GROUND},
     "must force what the primary"),
    ({"a": SWEEP_V, "c": SWEEP_V, "b": {"function": "sync_v", "settings": {"start": 0, "stop": 1, "icomp": 1e-4}}},
     "single-sweep staircase"),
    ({"a": SWEEP_V, "b": {"function": "sync_v", "settings": {"start": 0, "stop": 1, "icomp": 1e-4}},
      "c": {"function": "sync_v", "settings": {"start": 0, "stop": 1, "icomp": 1e-4}}}, "at most one synchronous"),
    ({"a": SWEEP_V, "c": {"function": "sweep_v", "settings": {"start": 0, "stop": 1, "icomp": 1e-4, "points": 5}}},
     "c.points: a following sweep source uses the primary's points"),
    ({"a": {**SWEEP_V, "settings": {**SWEEP_V["settings"], "scale": "log", "start": 0.1}},
      "c": {"function": "sweep_v", "settings": {"start": 0, "stop": 1, "icomp": 1e-4}}}, "same polarity"),
    ({"a": SWEEP_V, "b": {"function": "step_i", "settings": {"start": 1e-6, "stop": 2e-6, "points": 2,
                                                             "vcomp": 1}}}, "smu_stepped"),
    ({"a": SWEEP_V, "b": {"function": "bias_i", "settings": {"i": 1e-6}}}, "b.vcomp must be a finite number"),
])
def test_staircase_refuses_what_it_cannot_express(roles: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_with(recipe("smu_staircase", roles))


def test_more_than_ten_sweep_roles_are_refused() -> None:
    roles = {f"t{i}": {"function": "sweep_v", "settings": {"start": 0, "stop": 1, "points": 2, "icomp": 1e-6}}
             for i in range(11)}
    pin_map = PinMap(name="many", certainty="verified", terminals={f"t{i}": None for i in range(11)})
    with pytest.raises(CompileError, match="exceed the 10 sweep sources"):
        compile_with(recipe("smu_staircase", roles), pin_map)


# -- stepped: step_v families and step_i -----------------------------------------------------------------------------


def test_idvg_family_steps_the_drain_bias() -> None:
    compiled = registry_compile("mosfet.idvg_family", {"gate": 4, "drain": 3, "source": "GNDU"})
    drain = compiled.envelope.channels[3]
    assert (drain.function, drain.max_abs_v, drain.v_start, drain.v_stop) == ("step_v", 1.0, 0.1, 1.0)
    assert [c for c in compiled.flex_preview if c.startswith("DV")] == ["DV 3,0,0.1,0.001", "DV 3,0,0.55,0.001",
                                                                        "DV 3,0,1,0.001"]


def test_body_effect_steps_the_bulk() -> None:
    compiled = registry_compile("mosfet.body_effect", {"gate": 4, "drain": 3, "source": "GNDU", "bulk": 5})
    bulk = compiled.envelope.channels[5]
    assert (bulk.function, bulk.max_abs_v, bulk.max_abs_i) == ("step_v", 1.0, 1e-4)
    assert "DV 3,0,0.05,0.001" in compiled.flex_preview and "MM 2,4,3,5" in compiled.flex_preview
    program = SteppedProgram.model_validate(compiled.program)
    assert program.step_column == "bulk_V" and program.step_values == [0.0, -0.25, -0.5, -0.75, -1.0]


def test_step_i_forces_a_current_per_curve() -> None:
    rec = recipe("smu_stepped", {
        "a": SWEEP_V, "b": {"function": "step_i", "measure": ["V"], "settings": {
            "start": 1e-6, "stop": 3e-6, "points": 3, "vcomp": 1.5}}, "g": GROUND})
    compiled = compile_with(rec)
    step = compiled.envelope.channels[5]
    assert (step.function, step.max_abs_i, step.max_abs_v) == ("step_i", 3e-6, 1.5)
    assert [c for c in compiled.flex_preview if c.startswith("DI")] == ["DI 5,0,1E-06,1.5", "DI 5,0,2E-06,1.5",
                                                                        "DI 5,0,3E-06,1.5"]
    program = SteppedProgram.model_validate(compiled.program)
    assert (program.step_source, program.step_comp, program.step_column) == ("I", 1.5, "b_I")
    assert program.step_values == [1e-6, 2e-6, 3e-6]  # rounded to 1 fA, not to 1 nV
    assert program.staircase.source_columns == {} and program.staircase.biases == []


LIST = {"i_list": {"type": "float_list", "unit": "A", "default": [1e-6]}}


@pytest.mark.parametrize(("step", "values", "message"), [
    ({"function": "step_i", "measure": ["I"], "settings": {"values": "$i_list", "vcomp": 1}}, [1e-6],
     "must not measure I"),
    ({"function": "step_i", "settings": {"values": "$i_list"}}, [1e-6], "vcomp must be a finite number"),
    ({"function": "step_i", "settings": {"values": "$i_list", "vcomp": 1}}, [1e-6, 1e-6], "distinct"),
    ({"function": "step_i", "settings": {"values": "$i_list", "vcomp": 1}}, [1e-15, 1.4e-15], "distinct"),  # 1 fA
])
def test_step_i_refusals(step: dict[str, Any], values: list[float], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_with(recipe("smu_stepped", {"a": SWEEP_V, "b": step, "g": GROUND}, LIST), i_list=values)


def test_step_i_values_list_keeps_its_order() -> None:
    rec = recipe("smu_stepped", {"a": SWEEP_V, "b": {"function": "step_i", "settings": {
        "values": "$i_list", "vcomp": 1}}, "g": GROUND}, LIST)
    compiled = compile_with(rec, i_list=[3e-9, -1e-9, 2.5e-12])
    assert compiled.program["step_values"] == [3e-9, -1e-9, 2.5e-12]
    assert compiled.envelope.channels[5].max_abs_i == 3e-9
