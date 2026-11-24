"""Kind ``smu_pulsed`` (``catalog/kinds/smu_pulsed.py``, ``pulsed_roles.py``; WP7.3): mode selection from the roles,
the compiled envelope (pulse envelope from the source plan), the ``SourcePlan`` in ``program["sources"]``, the
estimate, the exact FLEX preview, and the requests the kind refuses (``CompileError``)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import PulsedProgram, SmuPulsedKind
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.sources import source_plan
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map, pin_map_exact, recipe

pytestmark = pytest.mark.smu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = SmuPulsedKind()
MOSFET = pin_map(gate=4, drain=3)
RESISTOR = pin_map_exact("resistor-2t", {"a": 3, "b": "GNDU"})
FOUR = pin_map_exact("generic-4t", {"a": 3, "b": "GNDU", "c": 4, "d": 5})


def compile_recipe(rec: Recipe | str, pm: Any = MOSFET, **values: Any):
    rec = REGISTRY.get(rec) if isinstance(rec, str) else rec
    binding = bind_roles(rec, pm, STATION, pm.name)
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION)


def variant(recipe_id: str, **role_changes: dict[str, Any]) -> Recipe:
    data = REGISTRY.get(recipe_id).model_dump(mode="json", exclude={"sha256"}, by_alias=True)
    for role, changes in role_changes.items():
        data["roles"][role] = {**data["roles"][role], **copy.deepcopy(changes)}
    return recipe(data)


def test_idvg_pulsed_is_a_pulsed_sweep_mm4() -> None:
    compiled = compile_recipe("mosfet.idvg_pulsed", vd=3.0)
    assert compiled.flex_preview == [
        "FMT 1,1", "CN 4,3", "DV 3,0,3,0.001", "AIT 2,3,0.0002", "MM 4,3", "CMM 3,1", "PT 0,0.001,0.02",
        "PWV 4,1,0,0,0,3,61,0.0001", "WM 2,1", "XE"]
    gate = compiled.envelope.channels[4]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i) == ("pulse_v", 3.0, 1e-4)
    assert gate.pulse is not None and (gate.pulse.max_abs_v_dut, gate.pulse.max_count, gate.pulse.max_duty) == (
        3.0, 61, 0.05)
    assert gate.pulse.max_short_circuit_a == 0.0  # the SMU's compliance bounds the current
    (train,) = source_plan(compiled.program).trains(4)
    assert (train.base_v, train.peak_v, train.width_s, train.period_s, train.count, train.repeat) == (
        0.0, 3.0, 1e-3, 0.02, 61, 1)
    assert compiled.estimate.points == 61
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 61 * 0.02 + 0.2)
    assert compiled.estimate.max_segment_s == pytest.approx(61 * 0.02 + 0.2)
    program = PulsedProgram.load(compiled.program)
    assert program.data_format == (1, 1) and program.triggers == [None] and program.width == 2


def test_idvd_pulsed_is_a_staircase_with_pulsed_bias_and_a_host_list() -> None:
    compiled = compile_recipe("mosfet.idvd_pulsed", vg_levels=[1.0, 2.0])
    assert compiled.flex_preview == [
        "FMT 1,1", "CN 3,4", "AIT 2,3,0.0002", "MM 5,3", "CMM 3,1", "PT 0,0.001,0.02", "WV 3,1,0,0,3,31,0.001",
        "PV 4,0,0,1,0.0001", "WM 2,1", "XE", "PV 4,0,0,2,0.0001", "XE"]
    (train,) = source_plan(compiled.program).trains(4)
    assert (train.peak_v, train.count, train.repeat, train.total_pulses) == (2.0, 31, 2, 62)
    assert compiled.envelope.channels[3].function == "sweep_v" and compiled.estimate.points == 62
    assert compiled.envelope.channels[4].max_abs_v == 2.0


def test_pulsed_spot_is_mm3_and_the_generic_recipe_mm28_or_mm27() -> None:
    spot = compile_recipe("basic.pulsed_spot", RESISTOR)
    assert [c for c in spot.flex_preview if c.startswith(("FMT", "MM", "PV", "XE"))] == [
        "FMT 1,0", "MM 3,3", "PV 3,0,0,-0.1,0.0001", "XE", "PV 3,0,0,-0.05,0.0001", "XE", "PV 3,0,0,0.05,0.0001",
        "XE", "PV 3,0,0,0.1,0.0001", "XE"]
    multi = compile_recipe("generic.smu_multi_pulsed", RESISTOR)
    assert "MM 28,3" in multi.flex_preview and "MCPWNX 1,3,1,0,0,0,0.5,0.0001" in multi.flex_preview
    one = compile_recipe("generic.smu_multi_pulsed", RESISTOR, points=1, start=0.2)
    assert "MM 27,3" in one.flex_preview and "MCPNX 1,3,1,0,0,0.2,0.0001" in one.flex_preview
    both = compile_recipe("generic.smu_multi_pulsed", FOUR, average=4)
    assert [c for c in both.flex_preview if c.startswith(("MCP", "MM", "DV"))] == [
        "DV 5,0,0,0.0001", "MCPT 0,0.02,0,4", "MCPNT 3,0,0.001", "MCPNT 4,0,0.001", "MCPWS 1,11",
        "MCPWNX 1,3,1,0,0,0,0.5,0.0001", "MCPNX 2,4,1,0,0,0.1,0.0001", "MM 28,3,4,5"]
    assert source_plan(both.program).trains(4)[0].count == 44  # 11 steps x 4 averaged pulses


@pytest.mark.parametrize(("rec", "values", "match"), [
    (variant("mosfet.idvg_pulsed", gate={"settings": {"base": 0.0, "start": 0.1, "stop": 3.0, "points": 11,
                                                      "scale": "log", "icomp": 1e-4, "width": 1e-3,
                                                      "period": 0.02}}), {}, "linearly only"),
    (variant("mosfet.idvg_pulsed", gate={"settings": {"base": 0.0, "start": 0.0, "stop": 3.0, "points": 11,
                                                      "icomp": 1e-4, "width": 1e-3, "period": 0.02,
                                                      "meas_time": 2e-3}}), {}, "inside the pulse width"),
    (variant("mosfet.idvg_pulsed", drain={"function": "sweep_v", "settings": {"start": 0, "stop": 1, "points": 11,
                                                                              "icomp": 1e-3}}), {},
     "no staircase role"),
    (variant("mosfet.idvd_pulsed", gate={"settings": {"base": 0.0, "peak": 1.0, "values": "$vg_levels",
                                                      "icomp": 1e-4, "width": 1e-3, "period": 0.02}}), {},
     "exactly one of peak"),
    (variant("mosfet.idvd_pulsed", source={"function": "step_v", "settings": {"start": 0.0, "stop": 0.5, "points": 2,
                                                                               "icomp": 1e-3}}),
     {}, "cannot execute"),
])
def test_requests_the_kind_cannot_express(rec: Recipe, values: dict[str, Any], match: str) -> None:
    with pytest.raises(CompileError, match=match):
        compile_recipe(rec, **values)


def test_pulse_roles_share_one_timing() -> None:
    rec = variant("generic.smu_multi_pulsed", c={"settings": {"base": 0.0, "peak": 0.1, "icomp": 1e-4,
                                                               "width": 2e-3}})
    with pytest.raises(CompileError, match="shares the timing"):
        compile_recipe(rec, FOUR)
    same = variant("generic.smu_multi_pulsed", c={"settings": {"base": 0.0, "peak": 0.1, "icomp": 1e-4,
                                                                "width": 1e-3}})
    assert "MM 28,3,4,5" in compile_recipe(same, FOUR).flex_preview


def test_default_measurement_time_is_half_the_width_on_the_2_us_grid() -> None:
    rec = variant("mosfet.idvg_pulsed", gate={"settings": {"base": 0.0, "start": 0.0, "stop": 3.0, "points": 11,
                                                           "icomp": 1e-4, "width": 1.3e-3, "period": 0.02}})
    assert "AIT 2,3,0.00065" in compile_recipe(rec).flex_preview
