"""Kind ``smu_qscv`` (``catalog/kinds/smu_qscv.py``; WP8.5): the compiled envelope, the SCUU routes of SMU roles
(``SSP 7,3``, no ``CN`` for the SCUU's modules), the estimate (one segment), the exact FLEX preview, the program
(offset measurement prompt), the table rows, the requests the kind refuses (``CompileError``) and the
``physical_setup`` confirmation R-ALWAYS-01 adds for an offset measurement."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import QscvProgram, SmuQscvKind
from b1500_test_agent.catalog.kinds.smu_qscv import OFFSET_SETUP_PROMPT, qscv_result, qscv_rows
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver.ops.core import RawBlock
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map_exact, recipe

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = SmuQscvKind()
SCUU = pin_map_exact("moscap-scuu", {"gate": "SCUU1.OUT1", "bulk": "SCUU1.OUT2"})
DIRECT = pin_map_exact("moscap-smu", {"gate": 3, "bulk": "GNDU"})
HALF = pin_map_exact("moscap-half", {"gate": "SCUU1.OUT1", "bulk": "GNDU"})


def compile_recipe(rec: Recipe | str = "moscap.qscv", pm: Any = SCUU, **values: Any):
    rec = REGISTRY.get(rec) if isinstance(rec, str) else rec
    binding = bind_roles(rec, pm, STATION, pm.name)
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION)


def variant(**role_changes: dict[str, Any]) -> Recipe:
    data = REGISTRY.get("moscap.qscv").model_dump(mode="json", exclude={"sha256"}, by_alias=True)
    for role, changes in role_changes.items():
        data["roles"][role] = {**data["roles"].get(role, {}), **copy.deepcopy(changes)}
    return recipe(data)


def test_qscv_through_the_scuu_routes_both_smus_and_never_enables_them() -> None:
    compiled = compile_recipe()
    assert compiled.flex_preview == [
        "FMT 1,1", "TSC 0", "SSP 7,3", "DV 5,0,0,1E-06", "MM 13,6", "QSC 0", "QSO 0", "QSL 1,1", "QSM 2,1",
        "QSR -12", "QST 0.1,0.1,5,0,0", "QSV 6,1,0,2,-2.5,0.05,89,1E-06", "QSZ 0", "XE"]
    gate, bulk = compiled.envelope.channels[6], compiled.envelope.channels[5]
    assert (gate.function, gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == ("sweep_v", 2.5, 1e-6, 2.0,
                                                                                            -2.5)
    assert (bulk.function, bulk.max_abs_v, bulk.max_abs_i) == ("ground", 0.0, 1e-6)
    measure = [Route(switch="SCUU1", output="OUT1", state="smu"), Route(switch="SCUU1", output="OUT2", state="smu")]
    assert compiled.envelope.routes == frozenset(measure)
    assert compiled.routes_by_phase == {"measure": measure}  # rest (smu) = measure: no rest phase
    program = QscvProgram.model_validate(compiled.program)
    assert program.enable == [] and sorted(program.switched) == [5, 6] and program.ssp == [(7, 3)]
    assert program.setup is None and not program.offset_run
    assert compiled.estimate.points == 89
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 5.0 + 0.3 + 88 * 0.2)
    assert compiled.estimate.max_segment_s == compiled.estimate.duration_s  # one XE = one segment


def test_direct_landing_and_one_scuu_output() -> None:
    compiled = compile_recipe(pm=DIRECT, irange_a=1e-10)  # HRSMU 3: the 100 pA range exists
    assert compiled.flex_preview[:4] == ["FMT 1,1", "TSC 0", "CN 3", "MM 13,3"]
    assert "QSR -10" in compiled.flex_preview and compiled.routes_by_phase == {}
    assert not compiled.envelope.routes and list(compiled.envelope.channels) == [3]  # the bulk is on the GNDU
    half = compile_recipe(pm=HALF)
    assert half.routes_by_phase["measure"] == [Route(switch="SCUU1", output="OUT1", state="smu"),
                                               Route(switch="SCUU1", output="OUT2", state="open")]
    assert half.routes_by_phase["rest"] == [Route(switch="SCUU1", output="OUT1", state="smu"),
                                            Route(switch="SCUU1", output="OUT2", state="smu")]
    assert half.flex_preview[2] == "SSP 7,1" and half.flex_preview[-1] == "SSP 7,3"


def test_offset_measurement_program() -> None:
    compiled = compile_recipe(offset="measure")
    program = QscvProgram.model_validate(compiled.program)
    assert program.offset_run and program.setup == OFFSET_SETUP_PROMPT and compiled.program["setup"] == program.setup
    assert compiled.flex_preview[-2:] == ["QSZ 0", "QSZ 2"] and compiled.estimate.points == 1
    assert compiled.estimate.duration_s == pytest.approx(1.0 + 0.3)
    cancel = compile_recipe(offset="cancel", leakage="data", operation="compatible", sweep_mode="double")
    assert "QSZ 1" in cancel.flex_preview and "QSL 1,0" in cancel.flex_preview and "QSC 1" in cancel.flex_preview
    assert "QSO 0" not in cancel.flex_preview and "QSV 6,3,0,2,-2.5,0.05,89,1E-06" in cancel.flex_preview
    assert cancel.estimate.points == 178


@pytest.mark.parametrize(("rec", "values", "message"), [
    ("moscap.qscv", {"step_v": 0.2}, "whole number"),
    ("moscap.qscv", {"cvoltage_v": 0.1}, "exceeds the step"),
    ("moscap.qscv", {"irange_a": 1e-10}, "MPSMU has no such current range"),  # SMU6 is an MPSMU
    ("moscap.qscv", {"irange_a": 2e-9}, "irange"),
    ("moscap.qscv", {"cinteg_s": 0.009}, "cinteg"),
])
def test_refused_requests(rec: str, values: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        compile_recipe(rec, **values)


def test_refused_role_layouts() -> None:
    with pytest.raises(CompileError, match="exactly one sweep_v"):
        compile_recipe(variant(bulk={"function": "sweep_v", "measure": ["I"]}))
    with pytest.raises(CompileError, match="must list I"):
        compile_recipe(variant(gate={"measure": []}))
    with pytest.raises(CompileError, match="also measure"):
        compile_recipe(variant(bulk={"measure": ["I"]}))
    with pytest.raises(CompileError, match="cannot execute"):
        compile_recipe(variant(bulk={"function": "bias_v"}))


def test_selector_routes_are_refused() -> None:
    pm = pin_map_exact("moscap-sel", {"gate": "SEL1.OUT1", "bulk": "GNDU"})
    with pytest.raises(CompileError, match="only through an SCUU"):
        compile_recipe(pm=pm)


def test_table_rows_and_result() -> None:
    compiled = compile_recipe(v_start=0.2, v_stop=0.0, step_v=0.05)  # three steps: 0.15, 0.1, 0.05 V
    program = QscvProgram.model_validate(compiled.program)
    raw = ("NFI+1.00000E-12,NFC+6.00000E-11,WFV+1.50000E-01,NFI+1.00000E-12,NFC+6.10000E-11,WFV+1.00000E-01,"
           "VFI+199.999E+99,VFC+199.999E+99,EFV+5.00000E-02")
    block = RawBlock(raw=raw, points=tuple(parse_fmt1(raw)), fmt=1, expected_points=9, xe_at=None,  # type: ignore[arg-type]
                     read_at=None, duration_s=0.0)  # type: ignore[arg-type]
    rows = qscv_rows(program, block)
    assert [r["dc_v"] for r in rows] == pytest.approx([0.15, 0.1, 0.05])
    assert rows[0] == {"step": 0, "dc_v": 0.15, "gate_Cp": 6.0e-11, "gate_Cp_status": "N", "gate_I": 1.0e-12,
                       "gate_I_status": "N"}
    assert rows[2]["gate_Cp_status"] == "V"
    result = qscv_result(program, block)
    assert result["points"] == 3 and result["capacitance_column"] == "gate_Cp" and result["leakage_column"] == "gate_I"
    offset = QscvProgram.model_validate(compile_recipe(offset="measure").program)
    one = RawBlock(raw="NFC+2.50000E-13", points=tuple(parse_fmt1("NFC+2.50000E-13")), fmt=1, expected_points=1,
                   xe_at=None, read_at=None, duration_s=0.0)  # type: ignore[arg-type]
    assert qscv_rows(offset, one) == [{"step": 0, "gate_Cp": 2.5e-13, "gate_Cp_status": "N"}]
    assert qscv_result(offset, one)["offset_f"] == pytest.approx(2.5e-13)
