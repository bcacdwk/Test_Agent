"""Recipe, plan, rule-report and run models (blueprint 2.1, 2.4-2.8): validation and JSON/YAML round-trips."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from b1500_test_agent.models.analysis import (
    ExtractionResult,
    MethodRecord,
    QualityReport,
    Quantity,
    QuantityRange,
)
from b1500_test_agent.models.common import ConfigFile
from b1500_test_agent.models.plan import (
    AcEnvelope,
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    ParamFile,
    PlanRecord,
    PlanRequest,
    PulseEnvelope,
    RuleFinding,
    RulesReport,
    RunProgress,
    WaveformLimits,
    tier_from_findings,
)
from b1500_test_agent.models.recipe import (
    FUNCTION_INPUT,
    FUNCTION_MODULE_TYPES,
    ParamSpec,
    Recipe,
    RecipeSummary,
    RoleSpec,
    file_param_origin,
)
from b1500_test_agent.models.routing import SWITCH_STATES, Route, SwitchSpec, split_switch_target
from b1500_test_agent.models.run import (
    CleanupReport,
    CleanupStep,
    ClientInfo,
    FaultRecord,
    LockHolder,
    RunManifest,
    RunSummary,
)
from tests.unit.helpers import assert_roundtrip

T0 = datetime(2026, 11, 17, 6, 30, 12, tzinfo=UTC)
SHA = "0" * 64

# Blueprint 2.6 recipe example (abridged there), verbatim apart from the card path being null until WP2.5.
IDVG_YAML = """
id: mosfet.idvg
version: 1
title: MOSFET transfer curve (Id-Vg, linear region) for Vth/gm/SS/Ion-Ioff
family: smu
kind: smu_staircase
status: sim_validated
card: null
device_types: [nmos, pmos, igzo_tft]
roles:
  gate:   {function: sweep_v, measure: [I], module_types: [MPSMU, HRSMU, HPSMU],
           settings: {start: $vg_start, stop: $vg_stop, points: $vg_points, icomp: $icomp_gate}}
  drain:  {function: bias_v, measure: [I], module_types: [MPSMU, HRSMU, HPSMU], prefer: HRSMU,
           settings: {v: $vd, icomp: $icomp_drain}}
  source: {function: ground, allow_gndu: true}
params:
  vg_start: {unit: V, default: -1.0, recommended: [-2, 0], range: [-10, 10]}
  vg_stop:  {unit: V, default: 3.0, recommended: [1, 5], range: [-10, 10]}
  vg_points: {type: int, default: 101, range: [11, 1001]}
  vd: {unit: V, default: 0.05, recommended: [0.02, 0.1], range: [-5, 5]}
  icomp_gate: {unit: A, default: 1.0e-6, range: [1.0e-12, 1.0e-3]}
  icomp_drain: {unit: A, default: 1.0e-3, range: [1.0e-12, 1.0e-2]}
  integration: {type: enum, choices: [short, medium, long], default: medium}
quality: {limited: [C, T], untrusted: [V, X, F, D, G, S, U], max_limited_fraction_in_fit: 0.05}
analysis_defaults: [{method: vth_linear_extrapolation, options: {window: max_gm, subtract_half_vd: true}}]
provenance: {sources: ["deck slide 6", "Programming Guide WV/FMT pages"], validation_runs: []}
"""


def idvg_data() -> dict[str, Any]:
    data = yaml.safe_load(IDVG_YAML)
    data["sha256"] = hashlib.sha256(IDVG_YAML.encode("utf-8")).hexdigest()
    return data


def finding(rule_id: str, severity: str, reason: str | None = None) -> RuleFinding:
    return RuleFinding(rule_id=rule_id, severity=severity, message=f"{rule_id} {severity}", observed=3.0, limit=1.0,
                       source="config/policy.example.yaml#soft_limits.voltage_v", reason=reason)


def plan_record(**changes: Any) -> PlanRecord:
    report = RulesReport.from_findings("plan", [finding("R-LIM-03", "confirm", "soft_limit")], policy_digest=SHA,
                                       evaluated_at=T0)
    data: dict[str, Any] = {
        "plan_id": "P-ABCDEFGH23",
        "plan_hash": "a" * 64,
        "request": PlanRequest(recipe_id="mosfet.idvg", params={"vg_stop": 3.0, "vg_points": 101},
                               pin_map="mosfet-4t", dut_profile="nmos-generic", label="W3-D12 batch"),
        "recipe_id": "mosfet.idvg",
        "recipe_version": 1,
        "recipe_sha": "b" * 64,
        "kind": "smu_staircase",
        "resolved_params": {"vg_stop": Quantity(value=3.0, unit="V"), "vg_points": Quantity(value=101),
                            "integration": Quantity(value="medium")},
        "binding": ChannelBinding(pin_map="mosfet-4t", roles={
            "gate": BoundChannel(role="gate", terminal="gate", channel=1, slot=1, module_type="MPSMU",
                                 module_model="B1511B", alias="SMU1"),
            "source": BoundChannel(role="source", terminal="source", gndu=True),
        }),
        "envelope": CompiledEnvelope(channels={1: ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=1e-6),
                                               3: ChannelEnvelope(role="drain", max_abs_v=0.05, max_abs_i=1e-3)}),
        "estimate": Estimate(points=101, duration_s=2.5),
        "flex_preview": ["CN 1,3", "WV 1,1,0,-1.0,3.0,101,1E-6", "XE"],
        "hashes": {"station": SHA, "policy": SHA, "pin_map": SHA, "dut_profile": SHA},
        "backend": "sim",
        "rules": report,
        "tier": report.tier,
        "summary": "mosfet.idvg@1 | gate=SMU1(MPSMU) sweep -1..3 V Icomp 1 uA | DUT nmos-generic | pins mosfet-4t | "
                   "sim | R-LIM-03 soft_limit",
        "created_at": T0,
        "expires_at": T0 + timedelta(hours=24),
    }
    data.update(changes)
    return PlanRecord(**data)


# -- Recipes ---------------------------------------------------------------------------------------------------------


def test_blueprint_recipe_example_validates() -> None:
    recipe = Recipe.model_validate(idvg_data())
    assert recipe.roles["drain"].prefer == "HRSMU"
    assert recipe.roles["gate"].param_refs() == {"vg_start", "vg_stop", "vg_points", "icomp_gate"}
    assert recipe.params["vg_points"].default == 101 and recipe.params["vg_start"].unit == "V"
    assert recipe.quality.max_limited_fraction_in_fit == 0.05
    assert recipe.quality.classify("C") == "limited" and recipe.quality.classify("V") == "untrusted"
    assert_roundtrip(recipe)
    assert recipe.family == "smu"
    summary = RecipeSummary(id=recipe.id, title=recipe.title, family=recipe.family, kind=recipe.kind, status="draft",
                            card=None)
    assert_roundtrip(summary)


@pytest.mark.parametrize(
    "change",
    [
        {"roles": {"gate": {"function": "sweep_v", "settings": {"start": "$vg_begin"}}}},  # undeclared parameter
        {"roles": {"gate": {"function": "sweep_v", "settings": {"start": "$Vg"}}}},  # malformed reference
        {"roles": {"gate": {"function": "pulse_v", "module_types": ["HVSPGU"]}}},  # SMU function on an SPGU
        {"roles": {"gate": {"function": "cmu_high", "module_types": ["HRSMU"]}}},  # MFCMU function on an SMU
        {"roles": {"gate": {"function": "sweep_x"}}},
        {"family": "fefet"},
        {"roles": {"gate": {"function": "sweep_v", "module_types": ["MPSMU"], "prefer": "HRSMU"}}},
        {"id": "idvg"},
        {"version": 0},
        {"status": "validated"},
        {"always_confirm": ["destructive", "destructive"]},
        {"sha256": "xyz"},
        {"quality": {"limited": ["C", "T", "V"], "untrusted": ["X", "F", "D", "G", "S", "U"]}},
    ],
)
def test_recipe_rejects_bad_definitions(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Recipe.model_validate({**idvg_data(), **change})


def test_recipe_card_is_required_but_may_be_null() -> None:
    data = idvg_data()
    del data["card"]
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "enum", "default": "medium"},  # choices missing
        {"type": "float", "choices": ["a"]},
        {"type": "enum", "choices": ["a", "a"], "default": "a"},
        {"type": "enum", "choices": ["short"], "default": "long"},
        {"type": "float", "default": 20.0, "range": [-10, 10]},
        {"type": "float", "range": [10, -10]},
        {"type": "float", "recommended": [-20, 0], "range": [-10, 10]},
        {"type": "int", "default": 1.5},
        {"type": "int", "default": True},
        {"type": "float", "default": "1 V"},
        {"type": "bool", "unit": "V"},
        {"type": "bool", "range": [0, 1]},
        {"type": "float_list", "default": [0.0, 20.0], "range": [-5, 5]},
        {"type": "float", "unit": "volt"},
        {"type": "file", "unit": "V"},
        {"type": "file", "range": [0, 1]},
        {"type": "file", "default": "work/waveforms/adhoc.csv"},  # a recipe default is a committed library file
        {"type": "file", "default": "recipes/waveforms/../secret.csv"},
        {"type": "file", "default": "recipes/waveforms/table.txt"},
        {"type": "file", "default": 3},
    ],
)
def test_param_spec_rejects_inconsistent_specs(spec: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ParamSpec.model_validate(spec)


def test_param_spec_accepts_every_type() -> None:
    specs = [
        ParamSpec(unit="V", default=-1.0, recommended=(-2, 0), range=(-10, 10)),
        ParamSpec(type="int", default=101, range=(11, 1001)),
        ParamSpec(type="bool", default=True),
        ParamSpec(type="enum", choices=["short", "medium"], default="medium"),
        ParamSpec(type="float_list", unit="V", default=[0.0, 0.5, 1.0], range=(-5, 5)),
        ParamSpec(type="float", unit="A"),  # required parameter (no default)
        ParamSpec(type="file", default="recipes/waveforms/lwp_sample.csv", doc="waveform table"),
        ParamSpec(type="file"),  # required file parameter
    ]
    for spec in specs:
        assert_roundtrip(spec)


def test_role_settings_keep_literal_values() -> None:
    role = RoleSpec(function="bias_v", settings={"v": 0.0, "mode": "single", "icomp": "$icomp"})
    assert role.param_refs() == {"icomp"}


@pytest.mark.parametrize(("function", "types", "resource"), [
    ("sweep_i", ["HRSMU"], "smu"), ("bias_i", ["MPSMU"], "smu"), ("step_i", [], "smu"), ("sync_v", [], "smu"),
    ("pulse_v", ["HRSMU", "MPSMU"], "smu"), ("pgu", ["HVSPGU"], "pgu"), ("wgfmu", ["WGFMU"], "wgfmu"),
    ("cmu_high", ["MFCMU"], "cmu"), ("cmu_low", ["MFCMU"], "cmu"),
])
def test_v2_role_functions_and_their_resources(function: str, types: list[str], resource: str) -> None:
    role = RoleSpec(function=function, module_types=types)
    assert role.resource == resource == FUNCTION_INPUT[function]
    assert set(types) <= FUNCTION_MODULE_TYPES[function]
    assert_roundtrip(role)


def test_file_param_paths() -> None:
    assert file_param_origin("recipes/waveforms/lwp_sample.csv") == "library"
    assert file_param_origin("work/waveforms/run7/ch1.csv") == "work"
    for bad in ("work/waveforms/../x.csv", "/tmp/x.csv", "recipes/waveforms/x.CSV", "work\\waveforms\\x.csv",
                "config/local/x.csv", "work/waveforms/.hidden.csv", 3, None):
        assert file_param_origin(bad) is None, bad


# -- Rule findings and reports ---------------------------------------------------------------------------------------


def test_reason_is_set_exactly_for_confirm_findings() -> None:
    with pytest.raises(ValidationError):
        finding("R-LIM-03", "confirm")
    with pytest.raises(ValidationError):
        finding("R-LIM-02", "block", "soft_limit")
    with pytest.raises(ValidationError):
        finding("LIM-02", "block")
    assert_roundtrip(finding("R-QUAL-*", "info"))


@pytest.mark.parametrize(
    ("severities", "tier"),
    [([], "ok"), (["info", "warn"], "ok"), (["warn", "confirm"], "needs_confirmation"),
     (["confirm", "block", "info"], "blocked")],
)
def test_tier_follows_the_worst_finding(severities: list[str], tier: str) -> None:
    findings = [finding("R-LIM-03", s, "soft_limit" if s == "confirm" else None) for s in severities]
    assert tier_from_findings(findings) == tier
    report = RulesReport.from_findings("pre_execute", findings, policy_digest=SHA, evaluated_at=T0)
    assert report.tier == tier
    assert_roundtrip(report)


def test_rules_report_rejects_a_tier_that_contradicts_findings() -> None:
    findings = [finding("R-LIM-02", "block")]
    with pytest.raises(ValidationError):
        RulesReport(phase="plan", tier="ok", findings=findings, confirm_reasons=[], policy_digest=SHA,
                    evaluated_at=T0)
    with pytest.raises(ValidationError):
        RulesReport(phase="plan", tier="needs_confirmation", findings=[finding("R-PIN-02", "confirm", "soft_limit")],
                    confirm_reasons=["unverified_pin_map"], policy_digest=SHA, evaluated_at=T0)


def test_confirm_reasons_are_deduplicated_in_order() -> None:
    findings = [finding("R-LIM-03", "confirm", "soft_limit"), finding("R-DUT-01", "confirm", "dut_envelope"),
                finding("R-LIM-03", "confirm", "soft_limit")]
    report = RulesReport.from_findings("plan", findings, policy_digest=SHA, evaluated_at=T0)
    assert report.confirm_reasons == ["soft_limit", "dut_envelope"]


# -- Plans -----------------------------------------------------------------------------------------------------------


def test_plan_record_roundtrip() -> None:
    plan = plan_record()
    assert plan.tier == "needs_confirmation"
    assert plan.envelope.max_abs_v == 3.0 and plan.envelope.max_abs_i == 1e-3
    assert type(plan.resolved_params["vg_points"].value) is int
    assert_roundtrip(plan)


@pytest.mark.parametrize(
    "changes",
    [
        {"plan_id": "P-abcdefgh23"},
        {"plan_id": "P-ABCDEFGH1"},
        {"tier": "ok"},
        {"summary": "x" * 401},
        {"summary": "gate=SMU1 sweep 0…3 V"},  # non-ASCII
        {"recipe_id": "mosfet.idvd"},
        {"expires_at": T0},
        {"backend": "gpib"},
        {"hashes": {"station": "short"}},
    ],
)
def test_plan_record_rejects_inconsistent_records(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        plan_record(**changes)


@pytest.mark.parametrize(
    "data",
    [
        {"recipe_id": "mosfet.idvg"},  # pin map required
        {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "params": {"vg": {"value": 1}}},
        {"recipe_id": "mosfet.idvg", "pin_map": "../local/x"},
        {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "params": {"vg": float("nan")}},
    ],
)
def test_plan_request_rejects_bad_requests(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlanRequest.model_validate(data)


def test_plan_request_keeps_param_types() -> None:
    request = PlanRequest(recipe_id="mosfet.idvg", pin_map="mosfet-4t",
                          params={"vg_points": 101, "double": True, "integration": "long", "vg_list": [0.0, 1.0]})
    assert [type(v) for v in request.params.values()] == [int, bool, str, list]
    assert_roundtrip(request)


def test_bound_channel_is_a_channel_or_the_gndu() -> None:
    with pytest.raises(ValidationError):
        BoundChannel(role="source", terminal="source", gndu=True, channel=4)
    with pytest.raises(ValidationError):
        BoundChannel(role="source", terminal="source")
    route = Route(switch="SEL1", output="OUT1", state="pgu")
    with pytest.raises(ValidationError):
        BoundChannel(role="gate", terminal="gate", gndu=True, via=route)
    with pytest.raises(ValidationError):
        BoundChannel(role="gate", terminal="gate", cmu_side="H")  # an MFCMU side needs its channel
    unknown_wiring = BoundChannel(role="gate", terminal="gate", via=route)  # switch input not recorded yet
    assert unknown_wiring.channel is None and unknown_wiring.via == route
    wired = BoundChannel(role="gate", terminal="gate", via=route, channel=101, slot=1, module_type="HVSPGU",
                         module_model="B1525A", alias="SPGU1")
    side = BoundChannel(role="gate", terminal="gate", channel=7, slot=7, module_type="MFCMU", cmu_side="H")
    for bound in (unknown_wiring, wired, side):
        assert_roundtrip(bound)


# -- Routing (blueprint v2 2.3) --------------------------------------------------------------------------------------


def selector(**changes: Any) -> SwitchSpec:
    data: dict[str, Any] = {"id": "SEL1", "kind": "selector_16440a", "present": True,
                            "ports": {"OUT1": {"index": 0, "inputs": {"smu": 5, "pgu": 101}},
                                      "OUT2": {"index": 1, "inputs": {"smu": None}}}}
    data.update(changes)
    return SwitchSpec.model_validate(data)


def test_routes_are_frozen_hashable_and_ordered() -> None:
    a = Route(switch="SEL1", output="OUT1", state="pgu")
    assert a == Route.model_validate({"switch": "SEL1", "output": "OUT1", "state": "pgu"})
    assert len({a, Route(switch="SEL1", output="OUT1", state="pgu"), Route(switch="SEL1", output="OUT1",
                                                                        state="smu")}) == 2
    assert a.target == "SEL1.OUT1" and str(a) == "SEL1.OUT1->pgu"
    with pytest.raises(ValidationError):
        a.state = "smu"  # type: ignore[misc]  # frozen
    for bad in ({"switch": "SEL1", "output": "OUT1", "state": "on"}, {"switch": "1SEL", "output": "OUT1",
                                                                     "state": "smu"},
                {"switch": "SEL1", "output": "OUT.1", "state": "smu"}):
        with pytest.raises(ValidationError):
            Route.model_validate(bad)
    assert_roundtrip(a)


def test_switch_spec_states_inputs_and_pgu_open() -> None:
    spec = selector()
    assert spec.certainty == "unverified" and spec.rest == "open"
    assert spec.allows("OUT1", "pgu_open") and not spec.allows("OUT2", "pgu_open")  # PGU open only on CH 1
    assert spec.allows("OUT2", "smu") and not spec.allows("OUT1", "cmu") and not spec.allows("OUT3", "smu")
    assert spec.input_channel("OUT1", "pgu") == spec.input_channel("OUT1", "pgu_open") == 101
    assert spec.input_channel("OUT1", "open") is None and spec.input_channel("OUT2", "smu") is None
    assert spec.input_channel("OUT2", "pgu") is None  # not connected
    assert SWITCH_STATES["rsu"] == {"open", "smu", "wgfmu"} and split_switch_target("RSU201.OUT") == ("RSU201", "OUT")
    assert split_switch_target("GNDU") is None
    assert_roundtrip(spec)


@pytest.mark.parametrize("changes", [
    {"rest": "pgu_open"},
    {"rest": "cmu"},
    {"kind": "router"},
    {"present": "maybe"},
    {"ports": {}},
    {"ports": {"OUT1": {"index": 0}, "OUT2": {"index": 0}}},
    {"ports": {"OUT1": {"index": 4}}},
    {"ports": {"OUT1": {"index": 0, "inputs": {"wgfmu": 201}}}},
    {"ports": {"OUT 1": {"index": 0}}},
    {"certainty": "verified"},  # OUT2's smu input is unknown
])
def test_switch_spec_rejects_inconsistent_specs(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        selector(**changes)


# -- Envelope v2 ------------------------------------------------------------------------------------------------------


PULSE = PulseEnvelope(max_abs_v_dut=4.0, min_width_s=1e-6, max_width_s=1e-6, max_duty=0.1, max_count=1000,
                      max_on_time_s=1e-3, max_short_circuit_a=0.08)
AC = AcEnvelope(max_vrms=0.03, max_dc_v=2.0, f_min_hz=1e3, f_max_hz=1e6)


def test_v2_envelopes_roundtrip_and_check_their_bounds() -> None:
    pgu = ChannelEnvelope(role="gate", max_abs_v=4.0, max_abs_i=None, function="pgu", pulse=PULSE)
    cmu = ChannelEnvelope(role="gate", max_abs_v=2.0, max_abs_i=1e-3, function="cmu_high", ac=AC)
    waveform = WaveformLimits(max_vectors=1825, max_points=504000, total_time_s=0.06)
    assert waveform.grid_s == 1e-8
    envelope = CompiledEnvelope(channels={101: pgu, 7: cmu}, waveform={201: waveform},
                                routes=frozenset({Route(switch="SEL1", output="OUT1", state="pgu")}))
    assert envelope.max_abs_v == 4.0 and envelope.max_abs_i == 1e-3  # the compliance-free channel adds no current
    for model in (PULSE, AC, waveform, pgu, cmu, envelope):
        assert_roundtrip(model)
    with pytest.raises(ValidationError):
        ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=None, function="sweep_v")  # an SMU always has Icomp
    with pytest.raises(ValidationError):
        ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=None, function="pgu", pulse=PULSE)  # 4 V at the DUT
    with pytest.raises(ValidationError):
        ChannelEnvelope(role="gate", max_abs_v=1.0, max_abs_i=1e-3, function="cmu_high", ac=AC)  # 2 V DC bias
    for bad in ({**PULSE.model_dump(), "min_width_s": 1e-3}, {**PULSE.model_dump(), "max_duty": 1.5},
                {**PULSE.model_dump(), "max_count": 0}):
        with pytest.raises(ValidationError):
            PulseEnvelope.model_validate(bad)
    with pytest.raises(ValidationError):
        AcEnvelope.model_validate({**AC.model_dump(), "f_min_hz": 2e6})
    with pytest.raises(ValidationError):
        WaveformLimits(max_vectors=0, max_points=1, total_time_s=1.0)


def test_route_sets_serialise_sorted_so_the_plan_hash_is_deterministic() -> None:
    routes = [Route(switch=s, output=o, state="smu") for s, o in (("SEL2", "OUT1"), ("SEL1", "OUT2"), ("SEL1", "OUT1"))]
    one = CompiledEnvelope(channels={}, routes=frozenset(routes)).model_dump(mode="json")
    other = CompiledEnvelope(channels={}, routes=frozenset(reversed(routes))).model_dump(mode="json")
    assert one == other
    assert [(r["switch"], r["output"]) for r in one["routes"]] == [("SEL1", "OUT1"), ("SEL1", "OUT2"),
                                                                   ("SEL2", "OUT1")]


def test_plan_record_v2_fields() -> None:
    plan = plan_record()
    assert (plan.mode, plan.routes_by_phase, plan.files, plan.est_s) == ("sync", {}, {}, 2.5)
    route = Route(switch="SEL1", output="OUT1", state="pgu")
    record = ParamFile(path="work/waveforms/a.csv", origin="work", sha256="c" * 64, size_bytes=12)
    v2 = plan_record(mode="async", routes_by_phase={"program": [route], "read": [route.model_copy(
        update={"state": "smu"})]}, files={"wave": record})
    assert v2.routes_by_phase["read"][0].state == "smu" and v2.files["wave"].origin == "work"
    assert_roundtrip(v2)
    with pytest.raises(ValidationError):
        plan_record(mode="background")


def test_param_file_has_content_or_a_problem() -> None:
    assert ParamFile(path="work/waveforms/a.csv", origin="work", problem="missing").sha256 is None
    for bad in ({"path": "x.csv", "origin": "work"},
                {"path": "x.csv", "origin": "work", "sha256": "c" * 64, "size_bytes": 1, "problem": "x"},
                {"path": "x.csv", "origin": "elsewhere", "problem": "x"}):
        with pytest.raises(ValidationError):
            ParamFile.model_validate(bad)


def test_run_progress() -> None:
    progress = RunProgress(state="running", done=40, total=120, phase="stress", elapsed_s=12.5, eta_s=25.0,
                           last_values={"drain_I": 1.2e-6}, updated_at=T0)
    assert_roundtrip(progress)
    assert RunProgress(state="completed", done=0, total=0, elapsed_s=0.0, updated_at=T0).eta_s is None
    for bad in ({"done": 130}, {"state": "paused"}, {"eta_s": -1.0}, {"updated_at": datetime(2026, 11, 17)}):
        with pytest.raises(ValidationError):
            RunProgress.model_validate({**progress.model_dump(), **bad})


# -- Runs ------------------------------------------------------------------------------------------------------------


def extraction() -> ExtractionResult:
    return ExtractionResult(
        method="vth_linear_extrapolation",
        quantity="vth",
        value=0.43,
        unit="V",
        method_record=MethodRecord(name="vth_linear_extrapolation", version="1", params={"window": "max_gm"}),
        window=QuantityRange(low=0.6, high=0.9, unit="V"),
        points_used=7,
        points_excluded={"C": 2},
        fit={"slope": 1.2e-4, "intercept": -5.1e-5},
        warnings=[],
    )


def cleanup() -> CleanupReport:
    steps = [CleanupStep(step=s, ok=True) for s in ("abort", "zero", "disconnect", "drain_errors", "verify")]
    return CleanupReport(steps=steps, verified="sim_state", outputs_after={1: "off", 3: "off"}, latched_fault=False)


def manifest(**changes: Any) -> RunManifest:
    plan = plan_record()
    data: dict[str, Any] = {
        "run_id": "S20261117T063012Z-7f3a",
        "plan": plan,
        "plan_hash": plan.plan_hash,
        "recipe_id": plan.recipe_id,
        "recipe_version": 1,
        "recipe_sha": plan.recipe_sha,
        "recipe_status": "sim_validated",
        "backend": "sim",
        "simulated": True,
        "hashes": plan.hashes,
        "config_files": [ConfigFile(key="policy", path="config/policy.example.yaml", source="example", sha256=SHA)],
        "rules": [plan.rules],
        "tier": plan.tier,
        "confirmed_summary": plan.summary,
        "confirmed_via": "run_confirmed_plan",
        "client": ClientInfo(adapter="mcp", session_tag="m3-s4"),
        "software_version": "v0.1.0-12-gabcdef0-dirty",
        "started_at": T0,
        "finished_at": T0 + timedelta(seconds=3),
        "outcome": "completed",
        "cleanup": cleanup(),
        "files": {"data.csv": SHA, "raw/block-000.txt": SHA},
    }
    data.update(changes)
    return RunManifest(**data)


def test_run_models_roundtrip() -> None:
    assert_roundtrip(manifest())
    assert_roundtrip(extraction())
    assert_roundtrip(cleanup())
    assert_roundtrip(QualityReport(counts={"N": 99, "C": 2}, fractions={"ok": 0.98, "limited": 0.02, "untrusted": 0.0},
                                   verdict="limited"))
    assert_roundtrip(FaultRecord(reason="cleanup_unverified", run_id="S20261117T063012Z-7f3a", set_at=T0))
    assert_roundtrip(LockHolder(pid=4242, host="lab-pc", adapter="cli", plan_id="P-ABCDEFGH23", since=T0))
    summary = RunSummary(ok=True, status="ok", backend="sim", simulated=True, run_id="S20261117T063012Z-7f3a",
                         plan_id="P-ABCDEFGH23", outcome="completed", status_counts={"N": 101}, quality_verdict="ok",
                         analyses=[extraction()], cleanup_verified="sim_state", artifacts={"data": "data.csv"})
    assert_roundtrip(summary)


@pytest.mark.parametrize(
    "changes",
    [
        {"backend": "visa", "simulated": False},  # an S run id on hardware
        {"simulated": False},
        {"confirmed_via": None},
        {"plan_hash": "c" * 64},
        {"outcome": "done"},
        {"run_id": "S2026-11-17-7f3a"},
    ],
)
def test_run_manifest_rejects_inconsistent_manifests(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        manifest(**changes)


def test_extraction_is_always_derived() -> None:
    data = extraction().model_dump()
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({**data, "derived": False})
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({**data, "unit": "volt"})


def test_run_summary_is_a_result_envelope() -> None:
    refused = RunSummary(ok=False, status="needs_confirmation", backend="sim", simulated=True,
                         error_code="confirmation_required", outcome="confirmation_required", plan_id="P-ABCDEFGH23")
    assert refused.run_id is None
    with pytest.raises(ValidationError):
        RunSummary(ok=True, status="ok", backend="visa", simulated=True, outcome="completed")
