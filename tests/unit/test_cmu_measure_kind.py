"""Kind ``cmu_measure`` compile path (WP8.3): envelope, estimate, FLEX preview and program of the committed recipes,
the refusals of recipes the kind cannot express, the MFCMU path through an SCUU (routes per phase, no ``CN`` of the
SCUU's modules) and its binding rules (R-PIN-01 sides of SCUU outputs; correction roles bound through an SCUU)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.catalog.kinds import CmuMeasureKind, CmuProgram
from b1500_test_agent.catalog.kinds.cmu_routes import mfcmu_path
from b1500_test_agent.catalog.planner import Planner, bind_roles
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError, parse_recipe
from b1500_test_agent.config import ConfigBundle, load_config
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.recipe import side_terminals, target_cmu_side
from b1500_test_agent.models.station import PinMap, StationProfile
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules import RulesEngine
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0

pytestmark = pytest.mark.cmu

KIND = CmuMeasureKind()
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


def config(tmp_path: Path | None = None, *, scuu_present: bool = False) -> ConfigBundle:
    cfg = load_config(Paths.from_env({}, repo_root=REPO_ROOT))
    if not scuu_present:
        return cfg
    station = cfg.station.model_copy(update={"switches": [
        s.model_copy(update={"present": True}) if s.id == "SCUU1" else s for s in cfg.station.switches]})
    return cfg.model_copy(update={"station": station})


def plan(recipe_id: str, pin_map: str, dut: str | None, cfg: ConfigBundle | None = None,
         **params: Any) -> PlanRecord:
    cfg = cfg or config()
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut,
                                      "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, RulesEngine(cfg, clock=lambda: T0))


def blocks(record: PlanRecord) -> set[str]:
    return {f.rule_id for f in record.rules.findings if f.severity == "block"}


# -- compile ---------------------------------------------------------------------------------------------------------


def test_spot_compiles_to_mm17_per_frequency() -> None:
    record = plan("cmu.spot", "capacitor-cmu", "capacitor-100p")
    assert blocks(record) == {"R-CORR-01"}  # no correction records in this test
    program = CmuProgram.model_validate(record.program)
    assert program.mode == "spot" and program.freqs_hz == [1e5, 1e6] and program.samples == 3
    assert program.imp == 100 and program.act == (0, 2) and program.enable == [7] and not program.routes
    assert record.flex_preview == [
        "FMT 1,1", "TSC 0", "LMN 0", "IMP 100", "ACT 0,2", "RC 7,0", "CN 7",
        "FC 7,100000", "ACV 7,0.03", "DCV 7,0", "MM 17,7", "XE", "XE", "XE",
        "FC 7,1000000", "ACV 7,0.03", "DCV 7,0", "MM 17,7", "XE", "XE", "XE",
        "DCV 7,0", "ACV 7,0"]
    env = record.envelope.channels[7]
    assert env.function == "cmu_high" and env.ac is not None and env.max_abs_v == 0.0
    assert (env.ac.max_vrms, env.ac.f_min_hz, env.ac.f_max_hz) == (0.03, 1e5, 1e6)
    assert env.max_abs_i == pytest.approx(math.sqrt(2) * 0.03 / 50)
    assert record.estimate.points == 6 and record.estimate.max_segment_s is not None


def test_cv_compiles_to_one_mm18_sweep_per_frequency() -> None:
    record = plan("moscap.cv", "moscap-cmu", "moscap-generic", freqs_hz=[1e5, 1e6], sweep_mode="double")
    program = CmuProgram.model_validate(record.program)
    assert (program.mode, program.start, program.stop, program.points, program.double) == ("cv", 2.0, -2.5, 91, True)
    sweeps = [line for line in record.flex_preview if line.startswith(("MM", "WDCV", "WTDCV", "WMDCV"))]
    assert sweeps == ["MM 18,7", "WTDCV 1,0", "WMDCV 2,1", "WDCV 7,3,2,-2.5,91"] * 2
    env = record.envelope.channels[7]
    assert (env.v_start, env.v_stop, env.max_abs_v) == (2.0, -2.5, 2.5) and env.ac is not None
    assert env.ac.max_dc_v == 2.5 and record.estimate.points == 2 * 182
    assert record.estimate.duration_s == pytest.approx(2 * program.segment_s() + 1.0)


def test_cgd_drives_the_source_smu_at_0_v_and_cgc_leaves_it_floating() -> None:
    cgd = plan("mosfet.cgd_cv", "mosfet-split-cv", "nmos-cv")
    program = CmuProgram.model_validate(cgd.program)
    mfcmu_a = math.sqrt(2) * 0.03 / 50
    assert program.enable == [7, 6, 4] and [(b.role, b.channel, b.level, b.comp) for b in program.biases] == [
        ("source", 6, 0.0, 1e-3), ("bulk", 4, 0.0, pytest.approx(mfcmu_a))]
    assert "DV 6,0,0,0.001" in cgd.flex_preview and cgd.envelope.channels[6].max_abs_v == 0.0
    assert blocks(cgd) == {"R-CORR-01"}
    cgc = plan("mosfet.cgc_cv", "mosfet-split-cv", "nmos-cv")
    assert CmuProgram.model_validate(cgc.program).enable == [7, 4] and set(cgc.envelope.channels) == {7, 4}


def recipe_text(**roles: Any) -> bytes:
    data = yaml.safe_load((REPO_ROOT / "recipes/cmu/spot.yaml").read_text(encoding="utf-8"))
    data["roles"].update(roles)
    return yaml.safe_dump(data).encode("utf-8")


@pytest.mark.parametrize(("roles", "message"), [
    ({"c": {"function": "cmu_high", "module_types": ["MFCMU"]}}, "exactly one cmu_high"),
    ({"c": {"function": "sweep_v", "settings": {"start": 0, "stop": 1, "points": 3, "icomp": 1e-3}}},
     "functions this kind does not drive"),
])
def test_recipes_the_kind_cannot_express_refuse_to_compile(roles: dict[str, Any], message: str) -> None:
    recipe = parse_recipe(recipe_text(**roles), source="test")
    pm = PinMap(name="x", certainty="verified", terminals={"a": "7H", "b": "7L", "c": 4})
    binding = bind_roles(recipe, pm, config().station, "x")
    params = {name: Quantity(value=spec.default, unit=spec.unit) for name, spec in recipe.params.items()}
    with pytest.raises(CompileError, match=message):
        KIND.compile(recipe, params, binding, config().station)


def test_unknown_model_and_spot_smu_measurement_refuse() -> None:
    recipe = parse_recipe(recipe_text(c={"function": "ground", "measure": ["I"]}), source="test")
    station = config().station
    binding = bind_roles(recipe, PinMap(name="x", certainty="verified", terminals={"a": "7H", "b": "7L", "c": 4}),
                         station, "x")
    params = {name: Quantity(value=spec.default, unit=spec.unit) for name, spec in recipe.params.items()}
    with pytest.raises(CompileError, match="only during a C-V sweep"):
        KIND.compile(recipe, params, binding, station)
    params["model"] = Quantity(value="lp_g")
    with pytest.raises(CompileError, match="model must be one of"):
        KIND.compile(recipe, params, binding, station)


# -- SCUU ------------------------------------------------------------------------------------------------------------


def test_scuu_outputs_resolve_to_mfcmu_sides() -> None:
    station: StationProfile = config().station
    assert target_cmu_side("SCUU1.OUT1", station) == "H" and target_cmu_side("SCUU1.OUT2", station) == "L"
    assert target_cmu_side("SEL1.OUT1", station) is None and target_cmu_side("7L") == "L"
    terminals = {"gate": "SCUU1.OUT1", "bulk": "SCUU1.OUT2"}
    assert side_terminals("cmu_high", terminals, station) == ["gate"]
    assert side_terminals("cmu_high", terminals) == []  # without the station an SCUU output is not a side


def test_cv_through_the_scuu_routes_to_the_mfcmu_and_back_without_cn() -> None:
    record = plan("moscap.cv", "moscap-scuu", "moscap-generic", config(scuu_present=True))
    assert blocks(record) == {"R-CORR-01"}, record.summary
    assert record.routes_by_phase == {
        "measure": [r for r in sorted(record.envelope.routes, key=lambda r: r.sort_key())],
        "rest": [r.model_copy(update={"state": "smu"}) for r in sorted(record.envelope.routes,
                                                                        key=lambda r: r.sort_key())]}
    assert {(r.output, r.state) for r in record.envelope.routes} == {("OUT1", "cmu"), ("OUT2", "cmu")}
    preview = record.flex_preview
    assert preview[6] == "SSP 7,4" and not [line for line in preview if line.startswith("CN")]
    assert preview[-3:] == ["DCV 7,0", "ACV 7,0", "SSP 7,3"]
    correction = plan("cmu.correction_open", "moscap-scuu", None, config(scuu_present=True))
    assert correction.binding.roles["high"].via is not None and "SSP 7,4" in correction.flex_preview
    assert correction.tier == "needs_confirmation" and "unverified_topology" in correction.rules.confirm_reasons


def test_scuu_outputs_on_the_wrong_side_or_shared_are_blocked() -> None:
    cfg = config(scuu_present=True)
    swapped = PinMap(name="moscap-swapped", certainty="unverified",
                     terminals={"gate": "SCUU1.OUT2", "bulk": "SCUU1.OUT1"})
    cfg = cfg.model_copy(update={"pin_maps": {**cfg.pin_maps, "moscap-swapped": swapped}})
    recipe = REGISTRY.get("moscap.cv")
    binding = bind_roles(recipe, swapped, cfg.station, "moscap-swapped")
    with pytest.raises(CompileError, match="needs the MFCMU H side"):
        mfcmu_path(recipe, binding, cfg.station, kind_id="cmu_measure")
    mixed = bind_roles(recipe, PinMap(name="m", certainty="verified", terminals={"gate": "SCUU1.OUT1",
                                                                                 "bulk": "7L"}), cfg.station, "m")
    with pytest.raises(CompileError, match="both directly or both"):
        mfcmu_path(recipe, mixed, cfg.station, kind_id="cmu_measure")
