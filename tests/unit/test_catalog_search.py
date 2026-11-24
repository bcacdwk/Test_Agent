"""Kind ``smu_search`` (``catalog/kinds/smu_search.py``; WP7.5): method selection from the search role, the target's
polarity and scale, the compiled envelope, the estimate (one segment), the exact FLEX preview, the one-row table, and
the requests the kind refuses (``CompileError``)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SearchProgram, SmuSearchKind
from b1500_test_agent.catalog.kinds.smu_search import search_result, search_rows
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.models.recipe import Recipe
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map, pin_map_exact, recipe

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = SmuSearchKind()
MOSFET = pin_map(gate=4, drain=3)
DIODE = pin_map_exact("diode-2t", {"anode": 3, "cathode": "GNDU"})
FILM = pin_map_exact("film-2t", {"gate": 4, "bulk": "GNDU"})


def compile_recipe(rec: Recipe | str, pm: Any = MOSFET, **values: Any):
    rec = REGISTRY.get(rec) if isinstance(rec, str) else rec
    binding = bind_roles(rec, pm, STATION, pm.name)
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION)


def variant(recipe_id: str, **role_changes: dict[str, Any]) -> Recipe:
    data = REGISTRY.get(recipe_id).model_dump(mode="json", exclude={"sha256"}, by_alias=True)
    for role, changes in role_changes.items():
        data["roles"][role] = {**data["roles"][role], **copy.deepcopy(changes)}
    return recipe(data)


def test_vth_search_is_a_binary_search_mm15() -> None:
    compiled = compile_recipe("mosfet.vth_search")
    assert compiled.flex_preview == [
        "FMT 1,0", "AAD 3,0", "AIT 0,2,1", "CN 4,3", "DV 3,0,0.05,0.001", "MM 15", "BSM 1,2,1", "BSVM 1", "BST 0,0",
        "BGI 3,0,1E-09,0,1E-07", "BSV 4,0,0,2,1E-06", "XE"]
    gate, drain = compiled.envelope.channels[4], compiled.envelope.channels[3]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == ("sweep_v", 2.0, 1e-6, 0.0,
                                                                                            2.0)
    assert (drain.function, drain.max_abs_v, drain.max_abs_i) == ("bias_v", 0.05, 1e-3)
    assert compiled.estimate.points == 19
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 19 * 0.02)
    assert compiled.estimate.max_segment_s == compiled.estimate.duration_s  # one XE = one segment
    program = SearchProgram.model_validate(compiled.program)
    assert (program.method, program.mode, program.result_column, program.monitor_column) == (
        "binary", 15, "gate_V", "drain_I")
    assert program.source_columns == {"drain_V": 0.05} and program.expected_points == 2


def test_target_scale_limit_rel_and_the_polarity_follows_the_drain_bias() -> None:
    scaled = compile_recipe("mosfet.vth_search", w_over_l=10.0, limit_rel=0.02, control="normal")
    assert "BGI 3,0,2E-08,0,1E-06" in scaled.flex_preview and "BSM 0,2,1" in scaled.flex_preview
    pmos = compile_recipe("mosfet.vth_search", vg_start=0.0, vg_stop=-2.0, vd=-0.05)
    assert "BGI 3,0,1E-09,0,-1E-07" in pmos.flex_preview and "BSV 4,0,0,-2,1E-06" in pmos.flex_preview


def test_breakdown_search_is_a_linear_search_with_the_ramp_polarity() -> None:
    compiled = compile_recipe("basic.breakdown_search", DIODE, v_stop=-20.0)
    assert compiled.flex_preview == [
        "FMT 1,0", "AAD 3,0", "AIT 0,0,1", "CN 3", "MM 14", "LSM 2,1", "LSVM 1", "LSTM 0,0", "LGI 3,0,0,-1E-06",
        "LSV 3,0,0,-20,-0.1,0.001", "XE"]
    assert compiled.estimate.points == 201
    anode = compiled.envelope.channels[3]
    assert (anode.max_abs_v, anode.max_abs_i, anode.v_start, anode.v_stop) == (20.0, 1e-3, 0.0, -20.0)


def test_dielectric_bdv_methods() -> None:
    quasi = compile_recipe("dielectric.bdv", FILM, v_stop=30.0)
    assert quasi.flex_preview == ["FMT 1,0", "AAD 4,0", "AIT 0,0,1", "CN 4", "MM 9,4", "BDT 0,0", "BDM 0,0",
                                  "BDV 4,0,0,30,0.001", "XE"]
    program = SearchProgram.model_validate(quasi.program)
    assert (program.method, program.monitor_quantity, program.expected_points) == ("quasi_pulsed", "V", 1)
    assert quasi.estimate.points == 1 and quasi.estimate.duration_s == pytest.approx(1.0 + 30 / 6e3 + 1 / 50 / 128)
    linear = compile_recipe("dielectric.bdv", FILM, v_stop=10.0, method="linear")
    assert linear.flex_preview[4:10] == ["MM 14", "LSM 2,1", "LSVM 1", "LSTM 0,0", "LGI 4,1,0,0.0001",
                                         "LSV 4,0,0,10,0.05,0.001"]
    assert SearchProgram.model_validate(linear.program).monitor_column == "gate_I"
    with pytest.raises(CompileError, match="10 V"):
        compile_recipe("dielectric.bdv", FILM, v_stop=8.0)  # MM 9 needs |stop - start| >= 10 V


def test_the_table_is_one_row_with_the_search_statuses() -> None:
    compiled = compile_recipe("mosfet.vth_search")
    program = SearchProgram.model_validate(compiled.program)
    class Block:
        points = tuple(parse_fmt1("NDV+313.000E-03,NCI+99.9000E-09"))

    rows = search_rows(program, Block())  # type: ignore[arg-type]
    assert rows == [{"step": 0, "gate_V": 0.313, "gate_V_status": "N", "drain_I": 9.99e-08, "drain_I_status": "N",
                     "drain_V": 0.05}]
    result = search_result(program, Block())  # type: ignore[arg-type]
    assert result["found"] is True and result["search_status"] == "N" and result["target"] == 1e-7


@pytest.mark.parametrize(("make", "match"), [
    (lambda: variant("mosfet.vth_search", drain={"measure": ["V"]}), "compliance side"),
    (lambda: variant("mosfet.vth_search", gate={"measure": ["I"]}), "measures only its monitor"),
    (lambda: variant("mosfet.vth_search", drain={"settings": {"v": "$vd", "icomp": "$icomp_drain"}}),
     "exactly one monitor"),
    (lambda: variant("mosfet.vth_search", drain={"settings": {"v": "$vd", "icomp": "$icomp_drain",
                                                              "target": "$i_crit_a"}}), "exactly one of"),
    (lambda: variant("mosfet.vth_search", gate={"settings": {"search": "spiral", "start": 0.0, "stop": 1.0,
                                                             "icomp": 1e-6}}), "search must be one of"),
    (lambda: variant("mosfet.vth_search", gate={"function": "pulse_v"}), "cannot execute"),
    (lambda: variant("basic.breakdown_search", anode={"function": "sweep_i", "measure": ["V"],
                                                      "settings": {"search": "quasi_pulsed", "start": 0.0,
                                                                   "stop": 1e-3, "vcomp": 20.0}}), "forces voltage"),
])
def test_requests_the_kind_refuses(make: Any, match: str) -> None:
    rec = make()
    pm = DIODE if "anode" in rec.roles else MOSFET
    params = {"v_stop": -20.0} if "anode" in rec.roles else {}
    with pytest.raises(CompileError, match=match):
        compile_recipe(rec, pm, **params)


def test_a_negative_target_magnitude_is_refused() -> None:
    with pytest.raises(CompileError, match="magnitude"):
        compile_recipe(variant("mosfet.vth_search", drain={"settings": {
            "v": "$vd", "icomp": "$icomp_drain", "target": -1e-7, "limit_rel": "$limit_rel"}}))
