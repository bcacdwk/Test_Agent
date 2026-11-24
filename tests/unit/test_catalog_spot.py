"""Kind ``smu_spot`` and the shared SMU ranging (blueprint v2 2.7, WP7.1): compile (envelope, program, exact FLEX
preview, estimate and checkpoint segments, refusals), the range settings ``irange``/``asu_1pa``/``ranges``
(``catalog/kinds/ranging.py``) in ``smu_spot`` and ``smu_staircase``, the table rows, and the rules that read them
(R-ASU-01 with ``asu_1pa``; R-COMP-01 for a 0 A current source)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SmuSpotKind, SpotProgram, default_kinds
from b1500_test_agent.catalog.kinds.ranging import range_label
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver.b1500 import RawBlock
from b1500_test_agent.driver.parser import parse_data
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.routing import SwitchPort, SwitchSpec
from b1500_test_agent.models.station import StationProfile
from tests.unit.rules_factory import T0, bundle, dut, engine, example_station, pin_map_exact

pytestmark = pytest.mark.smu

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
KIND = SmuSpotKind()
OPEN = pin_map_exact("open-smus", {"smu3": 3, "smu4": 4, "smu5": 5, "smu6": 6})
OPEN_DUT = dut("open-circuit", "open", **{f"smu{n}": (0.1, 1e-3) for n in range(1, 11)})
KELVIN_MAP = pin_map_exact("resistor-4w", {"a": 3, "b": "GNDU"})
KELVIN_DUT = dut("resistor-1r", "resistor", a=(1.0, 0.02), b=(1.0, 0.02))
SPOT_MAP = pin_map_exact("spot-4t", {"a": 3, "b": "GNDU", "c": 4, "d": 5})
SPOT_DUT = dut("spot-4t", "resistor", a=(1.0, 1e-3), b=(1.0, 1e-3), c=(1.0, 1e-3), d=(1.0, 1e-3))
LEAK_MAP = pin_map_exact("mosfet-4t", {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"})


def with_asu(station: StationProfile, switch_id: str, channel: int, present: bool | None) -> StationProfile:
    others = [s for s in station.switches if s.id != switch_id]
    asu = SwitchSpec(id=switch_id, kind="asu", present=present, rest="smu",
                     ports={"OUT": SwitchPort(index=channel, inputs={"smu": channel, "cmu": None})})
    return station.model_copy(update={"switches": [*others, asu]})


def make_plan(recipe_id: str, pm: Any, du: Any, *, station: StationProfile | None = None,
              **params: Any) -> PlanRecord:
    cfg = bundle(pin_maps=[pm], duts=[du], station_profile=station)
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pm.name, "dut_profile": du.name,
                                      "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


# -- compile -------------------------------------------------------------------------------------------------------


def test_kelvin_envelope_program_and_preview() -> None:
    plan = make_plan("resistor.kelvin_4w", KELVIN_MAP, KELVIN_DUT)
    assert plan.tier == "ok" and plan.kind == "smu_spot"
    env = plan.envelope.channels[3]
    assert (env.function, env.max_abs_i, env.max_abs_v, env.v_start) == ("bias_i", 0.01, 1.0, None)
    assert plan.flex_preview == [
        "FMT 1,0", "AAD 3,0", "AIT 0,2,16", "CN 3", "MM 1,3", "CMM 3,2",
        *[line for current in ("-0.01", "-0.005", "0.005", "0.01") for line in (f"DI 3,0,{current},1", *["XE"] * 4)]]
    program = SpotProgram.model_validate(plan.program)
    assert program.rows == 16 and program.list_column == "a_I" and program.source_columns == {}
    assert plan.estimate.points == 16 and plan.estimate.duration_s == pytest.approx(1 + 4 * 0.05 + 16 * 0.33)
    assert "a=SMU3(HRSMU) bias I<=10 mA Vcomp 1 V" in plan.summary


def test_zero_check_survey_maps_each_range_to_the_smu() -> None:
    plan = make_plan("system.zero_check", OPEN, OPEN_DUT)
    assert plan.tier == "ok"
    program = SpotProgram.model_validate(plan.program)
    labels = [[r.label for r in group] for group in program.groups]
    assert labels == [["10pA", "10pA", "1nA", "1nA"], ["1nA"] * 4, ["100nA"] * 4, ["10uA"] * 4, ["1mA"] * 4]
    assert [r.code for r in program.groups[0]] == [-9, -9, -11, -11]
    assert program.rows == 500 and program.chunk == 100 and KIND.checkpoint_total(plan) == 5
    assert all(env.max_abs_v == 0.0 and env.max_abs_i == 1e-4 for env in plan.envelope.channels.values())
    assert plan.flex_preview[11:16] == ["MM 1,3,4,5,6", "CMM 3,1", "CMM 4,1", "CMM 5,1", "CMM 6,1"]
    assert plan.flex_preview.count("XE") == 500 and plan.estimate.max_segment_s == pytest.approx(9.1)


def test_zero_check_long_runs_split_into_short_segments() -> None:
    plan = make_plan("system.zero_check", OPEN, OPEN_DUT, integration="long", samples=200)
    program = SpotProgram.model_validate(plan.program)
    assert program.chunk == 7 and KIND.checkpoint_total(plan) == 5 * 29  # 200 samples in chunks of 7
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s <= 10.0


def test_generic_spot_with_a_bias_and_a_voltmeter() -> None:
    plan = make_plan("generic.smu_spot", SPOT_MAP, SPOT_DUT, a_levels=[0.1, -0.1], c_v=0.2, d_i=0.0, d_vcomp=0.5,
                     samples=2)
    assert plan.tier == "ok", plan.rules.findings
    channels = plan.envelope.channels
    assert (channels[4].function, channels[4].max_abs_v, channels[4].max_abs_i) == ("bias_v", 0.2, 1e-4)
    assert (channels[5].function, channels[5].max_abs_v, channels[5].max_abs_i) == ("bias_i", 0.5, 0.0)
    assert plan.flex_preview[5:] == ["CN 3,4,5", "DV 4,0,0.2,0.0001", "DI 5,0,0,0.5", "MM 1,3,4,5", "CMM 3,1",
                                     "CMM 4,1", "CMM 5,2", "DV 3,0,0.1,0.001", "XE", "XE", "DV 3,0,-0.1,0.001",
                                     "XE", "XE"]
    program = SpotProgram.model_validate(plan.program)
    assert program.source_columns == {"c_V": 0.2, "d_I": 0.0} and program.list_column == "a_V"


def recipe_with(**roles: Any) -> Any:
    base = REGISTRY.get("generic.smu_spot")
    return base.model_copy(update={"roles": {**base.roles, **roles}})


@pytest.mark.parametrize(("change", "message"), [
    ({"c": {"function": "bias_v", "measure": ["I"], "optional": True,
            "settings": {"values": "$a_levels", "icomp": "$c_icomp"}}}, "at most one role"),
    ({"b": {"function": "measure_only", "measure": ["V"], "settings": {"icomp": 1e-3}}}, "measures I only"),
    ({"c": {"function": "sweep_v", "measure": ["I"], "optional": True,
            "settings": {"start": 0, "stop": 1, "points": 2, "icomp": 1e-3}}}, "cannot execute"),
    ({"a": {"function": "bias_v", "measure": ["I"], "settings": {"v": 0.1, "values": "$a_levels",
                                                                 "icomp": "$a_icomp"}}}, "either v or values"),
    ({"a": {"function": "bias_v", "measure": ["V"], "settings": {"values": "$a_levels", "icomp": "$a_icomp",
                                                                 "irange": 1e-9}}}, "does not measure I"),
    ({"a": {"function": "bias_v", "measure": ["I"], "settings": {"values": "$a_levels", "icomp": "$a_icomp",
                                                                 "irange": 3e-9}}}, "no 3e-09 A current range"),
])
def test_compile_refusals(change: dict[str, Any], message: str) -> None:
    from b1500_test_agent.models.recipe import RoleSpec

    recipe = recipe_with(**{name: RoleSpec.model_validate(spec) for name, spec in change.items()})
    plan = make_plan("generic.smu_spot", SPOT_MAP, SPOT_DUT)
    with pytest.raises(CompileError, match=message):
        KIND.compile(recipe, dict(plan.resolved_params), plan.binding, example_station())


def test_ground_without_any_source_needs_its_own_compliance() -> None:
    from b1500_test_agent.models.recipe import RoleSpec

    recipe = REGISTRY.get("system.zero_check")
    roles = {**recipe.roles, "smu3": RoleSpec(function="measure_only", measure=["I"], optional=True,
                                               settings={"ranges": "$ranges"})}
    plan = make_plan("system.zero_check", OPEN, OPEN_DUT)
    with pytest.raises(CompileError, match="without a compliance"):
        KIND.compile(recipe.model_copy(update={"roles": roles}), dict(plan.resolved_params), plan.binding,
                     example_station())


def test_samples_must_be_a_positive_integer() -> None:
    blocked = make_plan("generic.smu_spot", SPOT_MAP, SPOT_DUT, samples=0)  # outside the recipe range
    assert blocked.tier == "blocked" and any(f.rule_id == "R-PARAM-01" for f in blocked.rules.findings)
    plan = make_plan("generic.smu_spot", SPOT_MAP, SPOT_DUT)
    params = dict(plan.resolved_params)
    params["samples"] = params["samples"].model_copy(update={"value": 0})
    with pytest.raises(CompileError, match="samples must be an integer"):
        KIND.compile(REGISTRY.get("generic.smu_spot"), params, plan.binding, example_station())


def test_registered_for_sim_and_visa() -> None:
    assert default_kinds()["smu_spot"].implemented_on == {"sim", "visa"}


# -- ranging -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("full_scale", "fixed", "label"), [
    (1e-12, False, "1pA+"), (1e-11, True, "10pA"), (1e-10, True, "100pA"), (1e-9, True, "1nA"), (1e-5, True, "10uA"),
    (1e-3, True, "1mA"), (0.1, True, "100mA"), (1.0, True, "1A"),
])
def test_range_labels(full_scale: float, fixed: bool, label: str) -> None:
    assert range_label(full_scale, fixed=fixed) == label


def test_zero_check_uses_the_asu_range_only_on_a_present_asu() -> None:
    station = with_asu(example_station(), "ASU3", 3, True)
    plan = make_plan("system.zero_check", OPEN, OPEN_DUT, station=station, ranges=[1e-12])
    program = SpotProgram.model_validate(plan.program)
    assert [(r.channel, r.code, r.label) for r in program.groups[0]] == [
        (3, -8, "1pA"), (4, -9, "10pA"), (5, -11, "1nA"), (6, -11, "1nA")]
    assert not any(f.rule_id == "R-ASU-01" for f in plan.rules.findings)


def test_gate_leakage_asu_option_in_the_staircase() -> None:
    plain = make_plan("mosfet.gate_leakage", LEAK_MAP, dut())
    assert "ranges" not in plain.program and not any(line.startswith("RI") for line in plain.flex_preview)
    station = with_asu(example_station(), "ASU4", 4, True)
    asu = make_plan("mosfet.gate_leakage", LEAK_MAP, dut(), station=station, asu_1pa=True)
    assert asu.tier == "ok", asu.rules.findings
    assert asu.flex_preview[-2:] == ["RI 4,8", "XE"]
    assert asu.program["ranges"] == [{"channel": 4, "role": "gate", "code": 8, "label": "1pA+"}]


@pytest.mark.parametrize(("present", "fragment"), [(None, "unknown presence"), (False, "declared absent")])
def test_r_asu_01_blocks_asu_1pa_without_a_present_asu(present: bool | None, fragment: str) -> None:
    station = with_asu(example_station(), "ASU4", 4, present)
    plan = make_plan("mosfet.gate_leakage", LEAK_MAP, dut(), station=station, asu_1pa=True)
    blocks = [f for f in plan.rules.findings if f.rule_id == "R-ASU-01" and f.severity == "block"]
    assert plan.tier == "blocked" and len(blocks) == 1 and fragment in blocks[0].message
    assert blocks[0].source.endswith("present") or "switches" in blocks[0].source


def test_r_asu_01_blocks_asu_1pa_on_an_smu_without_a_declared_asu() -> None:
    station = example_station()
    station = station.model_copy(update={"switches": [s for s in station.switches if s.kind != "asu"]})
    plan = make_plan("mosfet.gate_leakage", LEAK_MAP, dut(), station=station, asu_1pa=True)
    [block] = [f for f in plan.rules.findings if f.rule_id == "R-ASU-01"]
    assert block.severity == "block" and "none is declared" in block.message
    assert "settings.asu_1pa" in str(next(f for f in plan.rules.findings if f.rule_id == "R-ASU-01").source) or \
        block.source.endswith("switches")


def test_r_comp_01_accepts_a_zero_ampere_current_source_with_a_voltage_compliance() -> None:
    plan = make_plan("generic.smu_spot", SPOT_MAP, SPOT_DUT, d_i=0.0, d_vcomp=0.5)
    assert plan.tier == "ok" and not any(f.rule_id == "R-COMP-01" for f in plan.rules.findings)


# -- table ---------------------------------------------------------------------------------------------------------


def _block(text: str) -> RawBlock:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    points = tuple(parse_data(text, 1))
    return RawBlock(raw=text, points=points, fmt=1, expected_points=len(points), xe_at=now, read_at=now, duration_s=0.0)


def test_rows_carry_levels_ranges_and_statuses() -> None:
    plan = make_plan("system.zero_check", OPEN, OPEN_DUT, ranges=[1e-11, 1e-9], samples=10)
    program = SpotProgram.model_validate(plan.program)
    block = _block("NCI+1.00000E-13,NDI-2.00000E-13,NEI+3.00000E-12,NFI-4.00000E-12")  # channel letters C-F
    rows = SmuSpotKind.rows_of(program, [block, block], first_index=9)
    assert rows[0]["step"] == 9 and rows[0]["smu3_range"] == "10pA" and rows[1]["smu3_range"] == "1nA"
    assert rows[0]["smu5_range"] == "1nA" and rows[1]["smu4_I"] == -2e-13 and rows[1]["smu6_I_status"] == "N"
    with pytest.raises(ValueError, match="expected 4 elements"):
        SmuSpotKind.rows_of(program, [_block("NCI+1.00000E-13")])
    with pytest.raises(ValueError, match="is not I of channel"):
        SmuSpotKind.rows_of(program, [_block("NCV+1.00000E-13,NDI-2.00000E-13,NEI+3.00000E-12,NFI-4.00000E-12")])
