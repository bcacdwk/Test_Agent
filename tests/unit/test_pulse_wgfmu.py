"""Kind ``pulse_read``, WGFMU path (``catalog/kinds/pulse_wgfmu.py``; WP10.6; blueprint v2 2.7): the WGFMU source
(``WgfmuOp``, ``OpRequest`` incl. bipolar bursts), switching (PUND) reads in schedule ``cycles``, the catalog program
R-WG-02 checks, one execution per step (lead/tail), the envelope and pulse trains, RSU routes per phase, the estimate
(async for long plans), the stored program and the refusals (an SMU read with the WGFMU source, a measuring SMU role,
PUND with another schedule or a reference read or a non-zero rest)."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.kinds.pulse_schedules import parse_schedule
from b1500_test_agent.catalog.kinds.pulse_sources import MAX_COUNT, SourceRequest, WgfmuOp, WgfmuSourceKind
from b1500_test_agent.catalog.kinds.pulse_wgfmu import (
    build_catalog,
    execution,
    is_wgfmu_plan,
    step_keys,
    stored,
)
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.policy import DutProfile, DutTerminal, TerminalPulse
from b1500_test_agent.models.recipe import RoleSpec
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0, bundle, engine, pin_map_exact
from tests.unit.rules_factory_v2 import lab_station

pytestmark = pytest.mark.wgfmu

FECAP = pin_map_exact("fecap", {"top": "RSU201.OUT", "bottom": "RSU202.OUT"})
FEFET = pin_map_exact("fefet", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU", "bias": 5})
PULSE = TerminalPulse(max_abs_v=5.0, max_width_s=1e-3, max_duty=0.5, max_count=10**9)
CAP = DutProfile(name="cap", device_type="fecap", terminals={
    "top": DutTerminal(max_abs_v=4.0, max_abs_i=1e-3, impedance="high_z", pulse=PULSE),
    "bottom": DutTerminal(max_abs_v=4.0, max_abs_i=1e-3, impedance="high_z", pulse=PULSE)})
FET = DutProfile(name="fet", device_type="fefet", terminals={
    "gate": DutTerminal(max_abs_v=5.0, max_abs_i=1e-3, pulse=PULSE), "drain": DutTerminal(max_abs_v=1.0,
                                                                                          max_abs_i=1e-3),
    "source": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3), "bias": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3)})


def registry(tmp_path: Any = None, extra: dict[str, str] | None = None) -> RecipeRegistry:
    if not extra:
        return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    import shutil

    root = tmp_path / "recipes"
    shutil.copytree(REPO_ROOT / "recipes", root, dirs_exist_ok=True)
    for name, text in extra.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return RecipeRegistry.load(root, repo_root=REPO_ROOT)


def plan_of(recipe_id: str, pin_map: str = "fecap", dut: str = "cap", reg: RecipeRegistry | None = None,
            **params: Any) -> PlanRecord:
    cfg = bundle(station_profile=lab_station(), pin_maps=[FECAP, FEFET], duts=[CAP, FET])
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut,
                                      "params": params})
    return Planner(reg or registry(), clock=lambda: T0).plan(req, cfg, engine(cfg))


# -- the WGFMU source ------------------------------------------------------------------------------------------------


def request(*ops: Any, **settings: Any) -> SourceRequest:
    spec = RoleSpec.model_validate({"function": "wgfmu", "module_types": ["WGFMU"],
                                    "settings": {"program": 3.0, "erase": -3.0, "width": 1e-5, **settings}})
    return SourceRequest(role="top", spec=spec, channel=201, params={"period": Quantity(value=1e-4, unit="s")},
                         ops=tuple(ops))


def test_wgfmu_source_compiles_pulses_and_bursts() -> None:
    from b1500_test_agent.catalog.kinds.pulse_sources import OpRequest

    compiled = WgfmuSourceKind().compile(request(
        OpRequest(key="program", name="program", level=3.0, width=1e-5, runs=2),
        OpRequest(key="cycling_1000", name="program", level=3.0, width=1e-5, count=1000, period=1e-4,
                  then=(-3.0, 1e-5)), lead=1e-6))
    pulse, burst = compiled.ops["program"], compiled.ops["cycling_1000"]
    assert isinstance(pulse, WgfmuOp) and isinstance(burst, WgfmuOp)
    assert (pulse.count, pulse.output_s, pulse.then) == (1, pytest.approx(1e-4), None)
    assert (burst.count, burst.output_s, burst.then) == (1000, pytest.approx(0.1), (-3.0, 1e-5))
    assert [v for _, v in burst.vectors()] == [3.0, 3.0, 0.0, 0.0, -3.0, -3.0, 0.0, 0.0]
    trains = sorted((t.peak_v, t.count, round(t.delay_s, 12), t.repeat) for t in compiled.trains)
    assert trains == [(-3.0, 1000, 5e-5, 1), (3.0, 1, 0.0, 2), (3.0, 1000, 0.0, 1)]
    assert compiled.max_abs_i is None and compiled.max_abs_v == 3.0 and compiled.pulse.max_abs_v_dut == 3.0
    assert WgfmuSourceKind().seconds(burst) == pytest.approx(0.6) and WgfmuSourceKind().segment_s(burst) < 1


def test_wgfmu_source_refusals() -> None:
    from b1500_test_agent.catalog.kinds.pulse_sources import OpRequest

    with pytest.raises(CompileError, match="must exceed lead"):
        WgfmuSourceKind().compile(request(OpRequest(key="program", name="program", level=3.0, width=1e-4)))
    with pytest.raises(CompileError, match="lead and trail must be positive"):
        WgfmuSourceKind().compile(request(OpRequest(key="program", name="program", level=3.0, width=1e-6),
                                          lead=0.0))
    assert MAX_COUNT == 1_000_000


# -- switching reads -------------------------------------------------------------------------------------------------


def q(value: Any, unit: str | None = None) -> Quantity:
    return Quantity(value=value, unit=unit) if unit else Quantity(value=value)


def test_switching_reads_are_the_cycles() -> None:
    params = {"cycles": q(100, "1"), "cycle_reads": q("log"), "reads_per_decade": q(1, "1"),
              "cycle_period": q(1e-4, "s"), "initial_read": q(False)}
    plan = parse_schedule(params, source="wgfmu", switching_read=True)
    assert plan.checkpoints == [1, 10, 100] and plan.reads() == 3 and plan.bursts() == [8, 89]
    every = parse_schedule({"cycles": q(5, "1")}, source="wgfmu", switching_read=True)
    assert every.reads() == 5 and every.initial_read is False and every.bursts() == []
    with pytest.raises(CompileError, match="no separate reference read"):
        parse_schedule({"initial_read": q(True)}, source="wgfmu", switching_read=True)
    with pytest.raises(CompileError, match="erases the state that schedule retention reads"):
        parse_schedule({"schedule": q("retention"), "retention_time": q(10.0, "s")}, source="wgfmu",
                       switching_read=True)
    with pytest.raises(CompileError, match="need the HV-SPGU .* or the WGFMU"):
        parse_schedule(params, source="smu", switching_read=True)


# -- fecap.endurance_pund --------------------------------------------------------------------------------------------


def endurance(**params: Any) -> PlanRecord:
    return plan_of("fecap.endurance_pund", **{"cycles": 100, "reads_per_decade": 1, "cycle_period": 1e-4,
                                              **params})


def test_endurance_pund_plan() -> None:
    plan = endurance()
    assert plan.tier == "ok" and is_wgfmu_plan(plan), plan.summary  # the verified test station, in every band
    program, catalog, sources = stored(plan)
    assert program.switching_read and program.read.kind == "pund" and program.checkpoints == [1, 10, 100]
    assert list(program.ops) == ["cycling_8", "cycling_89"] and program.entries == ["cycling_8", "cycling_89", "read"]
    steps = program.steps()
    assert [(s.action, s.cycle, s.phase, s.op) for s in steps] == [
        ("read", 1, "read", ""), ("burst", 10, "cycling", "cycling_8"), ("read", 10, "read", ""),
        ("burst", 100, "cycling", "cycling_89"), ("read", 100, "read", "")]
    assert catalog.sequences[201] == [("top_cycling_8", 8.0), ("top_cycling_89", 89.0), ("top_read", 1.0)]
    assert catalog.sequences[202] == [("bottom_cycling_8", 8.0), ("bottom_cycling_89", 89.0), ("bottom_read", 1.0)]
    assert [e.event for e in catalog.events] == ["P", "U", "N", "D"] and catalog.points(202) == 800
    one = execution(program, catalog, step_keys(program, steps, 1))
    assert one.sequences[201] == [("top_cycling_8", 8.0)] and not one.events
    assert step_keys(program, steps, 0) == ["read"] and step_keys(program, steps, 4) == ["read"]
    env = plan.envelope
    assert env.channels[201].max_abs_i is None and env.channels[201].pulse is not None
    assert env.channels[202].pulse is None and env.channels[202].max_abs_v == 0.0
    assert env.waveform[202].max_points == 800 and env.waveform[201].total_time_s == pytest.approx(
        catalog.sequence_time_s(201))
    assert {str(r) for r in plan.routes_by_phase["waveform"]} == {"RSU201.OUT->wgfmu", "RSU202.OUT->wgfmu"}
    assert {str(r) for r in plan.routes_by_phase["rest"]} == {"RSU201.OUT->open", "RSU202.OUT->open"}
    trains = sources.pulses[201]
    assert sum(t.total_pulses for t in trains if t.peak_v > 0) == 97 + 2 * 3  # cycling + P, U per read
    assert plan.estimate.points == 3 * 800 and plan.flex_preview == []
    assert plan.mode == "sync" and plan.rules.confirm_reasons == []  # the verified test station, within the bands


def test_the_default_endurance_plan_is_long_and_async() -> None:
    plan = plan_of("fecap.endurance_pund")
    assert plan.mode == "async" and plan.estimate.duration_s > 600 and "long_run" in plan.rules.confirm_reasons
    program, catalog, _ = stored(plan)
    assert program.checkpoints[-1] == 10**7 and len(program.checkpoints) == 22
    assert max(len(items) for items in catalog.sequences.values()) < 100
    assert plan.estimate.max_segment_s <= 30.0


def test_a_read_kind_outside_the_recipe_choices_blocks() -> None:
    plan = endurance(read_kind="spot")
    assert plan.tier == "blocked" and any(f.rule_id == "R-PARAM-01" for f in plan.rules.findings)


def test_catalog_is_rebuilt_identically() -> None:
    plan = endurance()
    program, catalog, _ = stored(plan)
    assert build_catalog(program) == catalog


@pytest.mark.parametrize(("params", "message"), [
    ({"initial_read": True}, "no separate reference read"),
    ({"interval": 3e-7}, "not a whole number of sampling intervals"),
    ({"cycle_period": 2e-5}, "cycle period must be at least"),
])
def test_endurance_pund_refusals(params: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        endurance(**params)


# -- a FeFET through the WGFMU path (sweep reads, SMU bias) ---------------------------------------------------------

FEFET_RECIPE = """
id: generic.wgfmu_pulse_read
version: 1
title: WGFMU program/read (test recipe)
family: nvm
kind: pulse_read
status: draft
card: null
device_types: [fefet]
roles:
  gate:
    function: wgfmu
    module_types: [WGFMU]
    settings: {program: $v_program, erase: $v_erase, width: $width, start: -0.5, stop: 1.8, points: 24}
  drain:
    function: wgfmu
    measure: [I]
    module_types: [WGFMU]
    settings: {v: 0.05, pulse_bias: $vd_pulse, range: 100ua}
  source: {function: ground, allow_gndu: true}
  bias: {function: bias_v, module_types: [MPSMU, HRSMU], settings: {v: $vb, icomp: 1.0e-4}, optional: true}
params:
  v_program: {unit: V, default: 4.0, range: [-10.0, 10.0]}
  v_erase: {unit: V, default: -4.0, range: [-10.0, 10.0]}
  width: {unit: s, default: 1.0e-6, range: [1.0e-8, 1.0e-3]}
  period: {unit: s, default: 1.0e-5, range: [1.0e-8, 1.0]}
  vd_pulse: {unit: V, default: 0.0, range: [-1.0, 1.0]}
  vb: {unit: V, default: 0.0, range: [-1.0, 1.0]}
  cycles: {type: int, default: 2, range: [1, 200]}
  schedule: {type: enum, choices: [cycles, grid, retention], default: cycles}
  read_kind: {type: enum, choices: [wgfmu, staircase], default: wgfmu}
  wgfmu_read: {type: enum, choices: [sweep, pund], default: sweep}
  amplitudes: {type: float_list, default: [3.0, 4.0], range: [-10.0, 10.0]}
  widths: {type: float_list, unit: s, default: [1.0e-7, 1.0e-6], range: [1.0e-8, 1.0e-3]}
  retention_time: {unit: s, default: 1.0, range: [0.01, 100.0]}
  first_read: {unit: s, default: 0.1, range: [0.01, 10.0]}
  settle: {unit: s, default: 0.0, range: [0.0, 10.0]}
  initial_read: {type: bool, default: true}
quality: {limited: [C, T], untrusted: [V, X, F, D, G, S, U]}
provenance: {sources: [test], validation_runs: []}
"""


def fefet_plan(tmp_path: Any, **params: Any) -> PlanRecord:
    reg = registry(tmp_path, {"generic/wgfmu_pulse_read.yaml": FEFET_RECIPE})
    return plan_of("generic.wgfmu_pulse_read", "fefet", "fet", reg, **params)


def test_sweep_reads_every_cycle_with_lead_and_tail(tmp_path: Any) -> None:
    plan = fefet_plan(tmp_path, vd_pulse=0.1, vb=0.2)
    assert plan.tier == "ok", plan.summary
    program, catalog, _ = stored(plan)
    assert program.entries == ["lead", "program", "erase", "read", "tail"]
    steps = program.steps()
    assert [(s.action, s.cycle, s.phase) for s in steps][:3] == [("read", 0, "read"), ("pulse", 1, "erase"),
                                                                ("read", 1, "erase")]
    assert step_keys(program, steps, 0) == ["lead", "read"] and step_keys(program, steps, len(steps) - 1) == \
        ["read", "tail"]
    drain = catalog.patterns["drain_read"]
    assert drain.v0 == 0.1 and {v for _, v in drain.vectors} == {0.05, 0.1}
    assert catalog.patterns["drain_program"].vectors == [(pytest.approx(1e-5), 0.1)]
    assert program.columns == ["step", "cycle", "phase", "gate_V", "drain_V", "bias_V", "drain_I", "drain_I_status"]
    assert plan.flex_preview == ["CN 5", "DV 5,0,0.2,0.0001"]
    assert program.read.steps == 24 and plan.estimate.points == 5 * 24


def test_grid_and_retention_with_sweep_reads(tmp_path: Any) -> None:
    grid = fefet_plan(tmp_path, schedule="grid", cycles=1)
    program, catalog, _ = stored(grid)
    assert [p.op for p in program.grid] == ["g1", "g2", "g3", "g4"] and "g4" in program.entries
    retention = fefet_plan(tmp_path, schedule="retention", cycles=1)
    program, catalog, _ = stored(retention)
    holds = [s for s in program.steps() if s.action == "hold"]
    assert holds and all(program.entry(s) in program.entries for s in holds)
    assert program.columns[:3] == ["step", "t_s", "cycle"]
    assert catalog.patterns[f"gate_{program.entry(holds[0])}"].duration_s == pytest.approx(holds[0].seconds)


@pytest.mark.parametrize(("params", "message"), [
    ({"read_kind": "staircase"}, "the WGFMU source reads with the WGFMU"),
    ({"wgfmu_read": "pund", "initial_read": False}, "a PUND needs setting amplitude"),
])
def test_wgfmu_path_refusals(tmp_path: Any, params: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        fefet_plan(tmp_path, **params)


def test_a_measuring_smu_role_is_refused(tmp_path: Any) -> None:
    text = FEFET_RECIPE.replace("bias: {function: bias_v,", "bias: {function: bias_v, measure: [I],")
    reg = registry(tmp_path, {"generic/wgfmu_pulse_read.yaml": text})
    with pytest.raises(InvalidInputError, match="holds a bias and measures nothing"):
        plan_of("generic.wgfmu_pulse_read", "fefet", "fet", reg)


def test_a_pund_read_needs_zero_rest_levels(tmp_path: Any) -> None:
    text = FEFET_RECIPE.replace("start: -0.5,", "amplitude: 3.0, start: -0.5,")
    reg = registry(tmp_path, {"generic/wgfmu_pulse_read.yaml": text})
    with pytest.raises(InvalidInputError, match="base and pulse_bias must be 0"):
        plan_of("generic.wgfmu_pulse_read", "fefet", "fet", reg, wgfmu_read="pund", vd_pulse=0.1,
                initial_read=False)


def test_builders_on_the_wgfmu_waveform_kind_list() -> None:
    assert {"pund", "program_read"} <= set(wf.BUILDERS)
