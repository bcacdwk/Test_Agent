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
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    PlanRequest,
    RuleFinding,
    RulesReport,
    tier_from_findings,
)
from b1500_test_agent.models.recipe import ParamSpec, Recipe, RecipeSummary, RoleSpec
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
    summary = RecipeSummary(id=recipe.id, title=recipe.title, kind=recipe.kind, status="draft", card=None)
    assert_roundtrip(summary)


@pytest.mark.parametrize(
    "change",
    [
        {"roles": {"gate": {"function": "sweep_v", "settings": {"start": "$vg_begin"}}}},  # undeclared parameter
        {"roles": {"gate": {"function": "sweep_v", "settings": {"start": "$Vg"}}}},  # malformed reference
        {"roles": {"gate": {"function": "pulse_v"}}},
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
    ]
    for spec in specs:
        assert_roundtrip(spec)


def test_role_settings_keep_literal_values() -> None:
    role = RoleSpec(function="bias_v", settings={"v": 0.0, "mode": "single", "icomp": "$icomp"})
    assert role.param_refs() == {"icomp"}


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
