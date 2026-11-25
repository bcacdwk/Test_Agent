"""Compile of kind ``stress_measure``'s WGFMU path (``catalog/kinds/stress_wgfmu.py``; WP10.7) through the real planner
and the committed ``wgfmu.fast_bti`` recipe: envelope (WGFMU channels without compliance, waveform limits, RSU
routes per phase, the SMU bias), source plan (stress levels, schedule), estimate (segments within 30 s, async when
long), FLEX preview of the SMU side, checkpoint total, role and parameter errors; kind ``wgfmu_waveform`` builds the
same program with builder ``fast_bti``; the plan summary names the WGFMU stress level.
"""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import stress_wgfmu as sw
from b1500_test_agent.catalog.kinds.stress_measure import StressMeasureKind
from b1500_test_agent.catalog.kinds.wgfmu_waveform import WgfmuWaveformKind
from b1500_test_agent.catalog.planner import Planner, bind_roles
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.policy import DutProfile, DutTerminal
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import source_plan
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0, bundle, engine, pin_map_exact
from tests.unit.rules_factory_v2 import lab_station

pytestmark = pytest.mark.wgfmu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
PIN = pin_map_exact("fast", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU", "bulk": 5})
PIN_NO_BULK = pin_map_exact("fast-3t", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU"})
DUT = DutProfile(name="fast", device_type="nmos", terminals={
    "gate": DutTerminal(max_abs_v=5.0, max_abs_i=1e-3), "drain": DutTerminal(max_abs_v=3.0, max_abs_i=1e-2),
    "source": DutTerminal(max_abs_v=1.0, max_abs_i=1e-2), "bulk": DutTerminal(max_abs_v=2.0, max_abs_i=1e-3)})


def make_plan(pin: str = "fast", **params: Any) -> PlanRecord:
    cfg = bundle(station_profile=lab_station(), pin_maps=[PIN, PIN_NO_BULK], duts=[DUT])
    req = PlanRequest.model_validate({"recipe_id": "wgfmu.fast_bti", "pin_map": pin, "dut_profile": "fast",
                                      "params": {"vg_stress": 2.0, "stress_time": 100.0, **params}})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


def test_the_envelope_routes_and_source_plan() -> None:
    plan = make_plan(vb=-0.5)
    assert plan.tier == "needs_confirmation" and plan.rules.confirm_reasons == ["destructive"], plan.summary
    env = plan.envelope
    assert set(env.channels) == {201, 202, 5}
    gate, drain, bulk = env.channels[201], env.channels[202], env.channels[5]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i) == ("wgfmu", 2.0, None)
    assert (drain.function, drain.max_abs_v, drain.max_abs_i) == ("wgfmu", 0.1, None)
    assert (bulk.function, bulk.max_abs_v, bulk.max_abs_i) == ("bias_v", 0.5, 1e-4)
    assert env.routes == {Route(switch="RSU201", output="OUT", state="wgfmu"),
                          Route(switch="RSU202", output="OUT", state="wgfmu")}
    assert set(plan.routes_by_phase) == {"waveform", "rest"}
    assert set(env.waveform) == {201, 202} and env.waveform[202].max_points > 0
    sources = source_plan(plan.program)
    assert sources.waveform is not None and sources.waveform.builder == "fast_bti"
    assert sources.dc_stress(201) is not None and sources.dc_stress(201).level_v == 2.0  # type: ignore[union-attr]
    assert sources.dc_stress(202).level_v == 0.0  # type: ignore[union-attr]
    assert sources.schedule is not None and (sources.schedule.stress_s, sources.schedule.reads) == (100.0, 16)
    assert sources.pulses == {} and sources.library is False
    assert "gate=WGFMU1:201 via RSU201.OUT fast_bti 0..2 V stress 2 V" in (plan.summary or "")


def test_the_estimate_and_the_checkpoints() -> None:
    plan = make_plan()
    program = sw.WgfmuStressProgram.model_validate({k: v for k, v in plan.program.items() if k != "sources"})
    assert StressMeasureKind.checkpoint_total(plan) == len(program.ops) == 33
    assert plan.estimate.points == 17 * 17 + 16
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s <= 30.0
    assert 100.0 < plan.estimate.duration_s < 110.0 and plan.mode == "sync"
    assert program.read_s == pytest.approx(17 * 1.1e-6 + 1e-7)
    long = make_plan(stress_time=3600.0)
    assert long.mode == "async" and "long_run" in long.rules.confirm_reasons
    assert long.estimate.max_segment_s is not None and long.estimate.max_segment_s <= 30.0


def test_the_flex_preview_holds_the_smu_side_only() -> None:
    plan = make_plan(vb=-0.5)
    program = sw.WgfmuStressProgram.model_validate({k: v for k, v in plan.program.items() if k != "sources"})
    assert plan.flex_preview[:2] == ["CN 5", "DV 5,0,-0.5,0.0001"]
    assert plan.flex_preview[2:5] == ["FMT 1,0", "MM 1,5", "CMM 5,1"]
    assert plan.flex_preview[5:] == ["XE"] * (len(program.runs) - 1)
    assert make_plan("fast-3t").flex_preview == []


def _recipe(**roles: dict[str, Any]) -> Recipe:
    data = REGISTRY.get("wgfmu.fast_bti").model_dump(mode="json")
    for name, change in roles.items():
        if change is None:
            data["roles"].pop(name)
        else:
            data["roles"][name] = {**data["roles"].get(name, {}), **change}
    data.pop("sha256")
    return Recipe.model_validate({**data, "sha256": "0" * 64})


def _compile(recipe: Recipe, **params: Any) -> Any:
    values = {k: v.default for k, v in recipe.params.items() if v.default is not None}
    values.update({"vg_stress": 2.0, "stress_time": 10.0, **params})
    quantities = {k: Quantity(value=v) for k, v in values.items()}
    station = lab_station()
    binding = bind_roles(recipe, PIN, station, "fast")
    return StressMeasureKind().compile(recipe, quantities, binding, station)


@pytest.mark.parametrize(("roles", "params", "message"), [
    ({"drain": {"measure": ["V"]}}, {}, "measures \\[I\\]"),
    ({"drain": {"settings": {"v": "$vd", "range": "$irange"}}}, {}, "needs setting stress"),
    ({"drain": {"settings": {"v": "$vd", "stress": 0.0, "start": 0.0, "stop": 0.1, "points": 3}}}, {},
     "exactly one WGFMU role gives the sense staircase"),
    ({"gate": {"settings": {"start": "$vg_start", "stop": "$vg_stop", "points": "$vg_points",
                            "stress": "$vg_stress"}}}, {"read_kind": "spot"}, "lacks"),
    ({"bulk": {"function": "pulse_v", "module_types": ["HRSMU"]}}, {}, "cannot execute role"),
    ({"bulk": {"measure": ["V"]}}, {}, "measures \\[I\\] \\(bias_v only\\)"),
    ({}, {"width": 4e-7, "settle": 5e-7}, "no averaging window"),
    ({}, {"first_read": 1e-6}, "first_read must be at least"),
])
def test_unusable_roles_and_parameters_are_compile_errors(roles: dict[str, Any], params: dict[str, Any],
                                                          message: str) -> None:
    with pytest.raises(CompileError, match=message):
        _compile(_recipe(**roles), **params)


def test_the_wgfmu_waveform_builder_builds_the_same_program() -> None:
    recipe = _recipe(bulk=None)
    data = recipe.model_dump(mode="json")
    data.update(id="wgfmu.fast_bti_raw", kind="wgfmu_waveform", family="wgfmu", analysis_defaults=[])
    data["params"]["builder"] = {"type": "enum", "choices": ["fast_bti"], "default": "fast_bti"}
    raw = Recipe.model_validate(data)
    values = {k: Quantity(value=v.default) for k, v in raw.params.items() if v.default is not None}
    values.update({"vg_stress": Quantity(value=2.0), "stress_time": Quantity(value=10.0)})
    station = lab_station()
    waveform_plan = WgfmuWaveformKind().compile(raw, values, bind_roles(raw, PIN, station, "fast"), station)
    stress_plan = StressMeasureKind().compile(_recipe(bulk=None), {k: v for k, v in values.items()
                                                                   if k != "builder"},
                                              bind_roles(_recipe(bulk=None), PIN, station, "fast"), station)
    assert source_plan(waveform_plan.program).waveform == source_plan(stress_plan.program).waveform
    assert waveform_plan.estimate.max_segment_s is not None
