"""Kind ``cmu_measure``, the C-V variants (WP8.4): compile path of ``moscap.cv_ac_level`` (MM 23),
``moscap.pulsed_cv`` (MM 20 / MM 19), ``moscap.cf`` (MM 22), ``moscap.ct`` (MM 26, chained blocks) and
``fecap.cv_butterfly`` (MM 18 double): program, envelope, estimate, FLEX preview, checkpoints, and the refusals of
settings the instrument would reject (pulse width per frequency, a C-f list off a WFC stair, a C-t interval shorter
than one measurement, a pulsed spot with two levels)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import CmuMeasureKind, CmuProgram
from b1500_test_agent.catalog.kinds.cmu_variants import (
    ct_blocks,
    frequency_resolution_hz,
    frequency_sweep,
    pulse_min_width_s,
    pulse_period_s,
    sweep_values,
)
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.config import load_config
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules import RulesEngine
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0

pytestmark = pytest.mark.cmu

KIND = CmuMeasureKind()
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
MOSCAP = ("moscap-cmu", "moscap-generic")
CF_LIST = [1e3, 1778.279, 3162.278, 5623.413, 1e4, 17782.79, 31622.78, 56234.13, 1e5, 177827.9, 316227.8, 562341.3,
           1e6]


def plan(recipe_id: str, pin_map: str = MOSCAP[0], dut: str | None = MOSCAP[1], **params: Any) -> PlanRecord:
    cfg = load_config(Paths.from_env({}, repo_root=REPO_ROOT))
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut,
                                      "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, RulesEngine(cfg, clock=lambda: T0))


def blocks(record: PlanRecord) -> set[str]:
    return {f.rule_id for f in record.rules.findings if f.severity == "block"}


def compile_error(recipe_id: str, **params: Any) -> str:
    """The message of the compile refusal of ``recipe_id`` with ``params`` (the planner reports it as an input
    error; here the kind is called directly)."""
    from b1500_test_agent.catalog.planner import bind_roles
    from b1500_test_agent.models.analysis import Quantity

    cfg = load_config(Paths.from_env({}, repo_root=REPO_ROOT))
    recipe = REGISTRY.get(recipe_id)
    binding = bind_roles(recipe, cfg.pin_maps[MOSCAP[0]], cfg.station, MOSCAP[0])
    values = {name: Quantity(value=params.get(name, spec.default), unit=spec.unit)
              for name, spec in recipe.params.items()}
    with pytest.raises(CompileError) as info:
        KIND.compile(recipe, values, binding, cfg.station)
    return str(info.value)


# -- helpers ---------------------------------------------------------------------------------------------------------


def test_pulse_width_and_period_rules_follow_ptdcv() -> None:
    assert [pulse_min_width_s(f) for f in (1e3, 1e4, 1.1e4, 2e5, 2.1e5, 5e6)] == [0.05, 0.05, 0.01, 0.01, 0.008,
                                                                                    0.008]
    assert pulse_period_s(0.01, 0.0) == pytest.approx(0.012) and pulse_period_s(0.2, 0.0) == pytest.approx(0.21)
    assert pulse_period_s(0.01, 0.05) == 0.05


def test_frequency_lists_map_onto_one_wfc_stair() -> None:
    assert frequency_sweep(CF_LIST, "x") == "log"
    assert frequency_sweep([1e5, 2e5, 3e5, 4e5], "x") == "linear"
    assert frequency_sweep([1e6, 1e5, 1e4, 1e3], "x") == "log"  # descending is a stair too
    assert [frequency_resolution_hz(f) for f in (9999, 1e4, 1e5, 1e6, 5e6)] == [1e-3, 1e-2, 0.1, 1.0, 1.0]
    for bad in ([1e3, 2e3, 5e3, 1e4], [1e3, 1e4], [1e5]):
        if len(bad) == 2:
            assert frequency_sweep(bad, "x") in ("log", "linear")  # two points are always a stair
            continue
        with pytest.raises(CompileError):
            frequency_sweep(bad, "x")
    assert sweep_values(1e3, 1e6, 4, "log") == pytest.approx([1e3, 1e4, 1e5, 1e6])


def test_long_ct_transients_split_into_blocks_of_at_most_25_s() -> None:
    assert [b.number for b in ct_blocks(0.02, 301, 0.0, 1.0)] == [301]  # 6 s: one block
    chain = ct_blocks(0.1, 900, 0.0, 1.0)
    assert sum(b.number for b in chain) == 900 and len(chain) == 4
    assert chain[0].h_base_s == 1.0 and not chain[0].continuation
    assert all(b.continuation and b.h_base_s == 0.0 and b.h_bias_s == pytest.approx(0.1) for b in chain[1:])
    assert all((b.number - 1) * 0.1 + b.h_bias_s <= 25.0 + 1e-9 for b in chain)
    assert ct_blocks(0.012, 6000, 0.0, 0.0)[1].h_bias_s == pytest.approx(0.02)  # rounded up to the 10 ms grid


# -- compile ---------------------------------------------------------------------------------------------------------


def test_ac_level_sweep_compiles_to_mm23() -> None:
    record = plan("moscap.cv_ac_level")
    assert blocks(record) == {"R-CORR-01"}
    program = CmuProgram.model_validate(record.program)
    assert (program.mode, program.mm, program.ac_vrms, program.ac_stop, program.points) == ("acv", 23, 0.01, 0.1, 10)
    assert record.flex_preview[7:] == ["MM 23,7", "FC 7,1000000", "DCV 7,-0.6", "WTACV 0.5,0", "WMACV 2,1",
                                       "WACV 7,1,0.01,0.1,10", "XE", "DCV 7,0", "ACV 7,0"]
    env = record.envelope.channels[7]
    assert env.ac is not None and (env.ac.max_vrms, env.ac.max_dc_v, env.v_start, env.v_stop) == (0.1, 0.6, -0.6,
                                                                                                   -0.6)
    assert env.max_abs_i == pytest.approx(math.sqrt(2) * 0.1 / 50)  # the largest level
    assert "soft_cmu" in record.rules.confirm_reasons and record.estimate.points == 10


def test_pulsed_cv_compiles_to_mm20_and_one_point_to_mm19() -> None:
    record = plan("moscap.pulsed_cv")
    program = CmuProgram.model_validate(record.program)
    assert (program.mode, program.mm, program.base_v, program.width_s, program.act) == ("pulsed", 20, -2.5, 0.01,
                                                                                         (0, 1))
    assert record.flex_preview[7:13] == ["MM 20,7", "FC 7,1000000", "ACV 7,0.03", "WMDCV 2,1", "PTDCV 1,0.01,0",
                                         "PWDCV 7,1,-2.5,-2.5,2,91"]
    env = record.envelope.channels[7]
    assert (env.max_abs_v, env.v_start, env.v_stop) == (2.5, -2.5, 2.0)
    assert record.estimate.max_segment_s == pytest.approx(0.5 + 1.0 + 91 * 0.012 + 0.008)
    spot = plan("moscap.pulsed_cv", points=1, v_start=1.5, v_stop=1.5)
    assert CmuProgram.model_validate(spot.program).mm == 19
    assert spot.flex_preview[7:13] == ["MM 19,7", "FC 7,1000000", "ACV 7,0.03", "PTDCV 1,0.01,0", "PDCV 7,-2.5,1.5",
                                       "XE"]
    double = plan("moscap.pulsed_cv", sweep_mode="double", points=11)
    assert "PWDCV 7,3,-2.5,-2.5,2,11" in double.flex_preview and double.estimate.points == 22


def test_cf_sweep_compiles_to_one_mm22_stair_over_the_list() -> None:
    record = plan("moscap.cf")
    program = CmuProgram.model_validate(record.program)
    assert (program.mode, program.mm, program.step_spacing, program.points) == ("cf", 22, "log", 13)
    assert program.loop_freqs == [1e3] and program.segments == 1 and KIND.checkpoint_total(record) == 1
    assert record.flex_preview[7:] == ["MM 22,7", "FC 7,1000", "ACV 7,0.03", "DCV 7,-0.6", "WTFC 1,0", "WMFC 2,1",
                                       "WFC 7,2,1000,1000000,13", "XE", "DCV 7,0", "ACV 7,0"]
    env = record.envelope.channels[7]
    assert env.ac is not None and (env.ac.f_min_hz, env.ac.f_max_hz) == (1e3, 1e6)
    linear = plan("moscap.cf", freqs_hz=[1e5, 2e5, 3e5, 4e5, 5e5])
    assert "WFC 7,1,100000,500000,5" in linear.flex_preview


def test_ct_compiles_to_mm26_with_time_stamps_and_chains_long_transients() -> None:
    record = plan("moscap.ct")
    program = CmuProgram.model_validate(record.program)
    assert (program.mode, program.mm, program.base_v, program.dc_v, program.interval_s) == ("ct", 26, -2.5, 2.0, 0.02)
    assert record.flex_preview[:2] == ["FMT 1,1", "TSC 1"]
    assert record.flex_preview[7:] == ["TSR", "MM 26,7", "FC 7,1000000", "ACV 7,0.03", "MTDCV 0,0.02,301,1",
                                       "MDCV 7,-2.5,2,2", "XE", "DCV 7,0", "ACV 7,0"]
    assert record.estimate.points == 301 and KIND.checkpoint_total(record) == 1
    env = record.envelope.channels[7]
    assert (env.max_abs_v, env.v_start, env.v_stop) == (2.5, -2.5, 2.0)
    long = plan("moscap.ct", interval_s=0.1, points=900, freqs_hz=[1e5, 1e6])
    chained = CmuProgram.model_validate(long.program)
    assert len(chained.ct_blocks) == 4 and KIND.checkpoint_total(long) == 8 and long.estimate.points == 1800
    assert long.estimate.max_segment_s is not None and long.estimate.max_segment_s <= 30.0
    assert long.flex_preview.count("TSR") == 2 and long.flex_preview.count("MDCV 7,2,2,2") == 6
    assert long.estimate.duration_s > 2 * 89.9


def test_fecap_butterfly_is_a_double_dc_sweep_on_the_fecap_landing() -> None:
    record = plan("fecap.cv_butterfly", "fecap-cmu", "fecap-generic")
    assert blocks(record) == {"R-CORR-01"} and record.rules.confirm_reasons == ["unverified_pin_map"]
    program = CmuProgram.model_validate(record.program)
    assert (program.mode, program.double, program.points, program.high_role) == ("cv", True, 121, "top")
    assert "WDCV 7,3,-3,3,121" in record.flex_preview and record.estimate.points == 242


# -- refusals --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("recipe_id", "params", "message"), [
    ("moscap.pulsed_cv", {"freqs_hz": [1e4], "width_s": 0.02}, "below the 50 ms"),
    ("moscap.pulsed_cv", {"freqs_hz": [1e5], "width_s": 0.008}, "below the 10 ms"),
    ("moscap.pulsed_cv", {"period_s": 0.011}, "at least width + 2 ms"),
    ("moscap.pulsed_cv", {"points": 1}, "stop = start"),
    ("moscap.pulsed_cv", {"width_s": 0.01234}, "off the PTDCV resolution"),
    ("moscap.cf", {"freqs_hz": [1e3, 2e3, 5e3, 1e4]}, "equally spaced"),
    ("moscap.cf", {"freqs_hz": [1e5]}, "at least two frequencies"),
    ("moscap.ct", {"interval_s": 0.01, "integration": "medium"}, "shorter than one MFCMU measurement"),
    ("moscap.ct", {"interval_s": 0.0125}, "1 ms grid"),
    ("moscap.ct", {"hold_bias_s": 0.005}, "10 ms steps"),
    ("moscap.cv_ac_level", {"ac_sweep": "log", "ac_start": 0.0}, "outside"),
])
def test_settings_the_instrument_rejects_refuse_to_compile(recipe_id: str, params: dict[str, Any],
                                                           message: str) -> None:
    if message == "outside":  # 0 V rms is outside the recipe range: the planner refuses before the kind
        record = plan(recipe_id, **params)
        assert "R-PARAM-01" in blocks(record)
        return
    assert message in compile_error(recipe_id, **params)


def test_an_unknown_measurement_or_an_smu_measurement_in_a_variant_refuse() -> None:
    import yaml

    from b1500_test_agent.catalog.planner import bind_roles
    from b1500_test_agent.catalog.schema import parse_recipe
    from b1500_test_agent.models.analysis import Quantity
    from b1500_test_agent.models.station import PinMap

    cfg = load_config(Paths.from_env({}, repo_root=REPO_ROOT))
    data = yaml.safe_load((REPO_ROOT / "recipes/moscap/cf.yaml").read_text(encoding="utf-8"))
    data["roles"]["gate"]["settings"]["measurement"] = "qscv"
    recipe = parse_recipe(yaml.safe_dump(data).encode("utf-8"), source="test")
    pm = PinMap(name="x", certainty="verified", terminals={"gate": "7H", "bulk": "7L", "c": 4})
    params = {name: Quantity(value=spec.default, unit=spec.unit) for name, spec in recipe.params.items()}
    with pytest.raises(CompileError, match="measurement must be one of"):
        KIND.compile(recipe, params, bind_roles(recipe, pm, cfg.station, "x"), cfg.station)
    data["roles"]["gate"]["settings"]["measurement"] = "cf"
    data["roles"]["c"] = {"function": "ground", "measure": ["I"], "module_types": ["HRSMU"]}
    recipe = parse_recipe(yaml.safe_dump(data).encode("utf-8"), source="test")
    with pytest.raises(CompileError, match="the cf measurement measures the MFCMU alone"):
        KIND.compile(recipe, params, bind_roles(recipe, pm, cfg.station, "x"), cfg.station)
