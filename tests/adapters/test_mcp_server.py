"""The ``b1500`` MCP server through the FastMCP in-memory client (blueprint 5.1, 8.1 ``adapters/``, ATV-12): exactly
the ten tools, explicit annotations, the ``requiresUserInteraction`` flag following the policy, instructions and
description limits, schema-valid outputs that always carry ``backend``/``simulated``."""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest
from pydantic import BaseModel

from b1500_test_agent.adapters import mcp_server
from b1500_test_agent.adapters.mcp_server import INSTRUCTIONS, REQUIRES_USER_INTERACTION
from b1500_test_agent.models.common import ResultEnvelope
from b1500_test_agent.models.results import (
    AnalysisResult,
    NoteResult,
    PlanValidation,
    RecipeList,
    RunDetail,
    RunList,
    ShutdownResult,
    StationStatus,
)
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.service import TOOL_NAMES, B1500Service
from tests.adapters.helpers import call_tool, call_tools, list_tools
from tests.adapters.helpers import mcp_server as server_for
from tests.integration.helpers import IDVG, World

READ_ONLY = {"station_status", "list_recipes", "validate_plan", "list_runs", "get_run"}
DESTRUCTIVE = {"run_plan", "run_confirmed_plan"}
RESULT_MODELS: dict[str, type[BaseModel]] = {
    "station_status": StationStatus, "list_recipes": RecipeList, "validate_plan": PlanValidation,
    "run_plan": RunSummary, "run_confirmed_plan": RunSummary, "list_runs": RunList, "get_run": RunDetail,
    "analyze_run": AnalysisResult, "annotate_run": NoteResult, "safe_shutdown": ShutdownResult,
}


def wire(tool: Any) -> dict[str, Any]:
    """The tool exactly as a client receives it in ``tools/list`` (MCP field names)."""
    return tool.model_dump(by_alias=True, exclude_none=True, mode="json")


def tools_by_name(world: World, **kwargs: Any) -> dict[str, dict[str, Any]]:
    return {tool.name: wire(tool) for tool in list_tools(server_for(world, **kwargs))}


def test_exactly_the_ten_tools_and_no_raw_flex(world: World) -> None:
    tools = [wire(t) for t in list_tools(server_for(world))]
    assert [t["name"] for t in tools] == list(TOOL_NAMES)
    assert len(tools) == 10
    text = " ".join(f"{t['name']} {t['description']} {t['inputSchema']}" for t in tools).lower()
    for forbidden in ("flex", "raw command", "pyvisa", "force_voltage", "fault_clear"):
        assert forbidden not in text


def test_every_tool_has_explicit_annotations(world: World) -> None:
    for name, tool in tools_by_name(world).items():
        ann = tool["annotations"]
        assert ann == {"readOnlyHint": name in READ_ONLY, "destructiveHint": name in DESTRUCTIVE,
                       "openWorldHint": False}, name


@pytest.mark.parametrize("flag", [True, False])
def test_requires_user_interaction_follows_the_policy(world: World, flag: bool) -> None:
    if not flag:
        world.write_config("policy.yaml", {"confirmation": {"claude_require_user_interaction": False}})
    tools = tools_by_name(world)
    meta = tools["run_confirmed_plan"].get("_meta", {})  # ATV-12: _meta reaches tools/list
    assert meta.get(REQUIRES_USER_INTERACTION, False) is flag
    for name, tool in tools.items():
        if name != "run_confirmed_plan":
            assert REQUIRES_USER_INTERACTION not in tool.get("_meta", {}), name


def test_flag_stays_on_when_the_config_is_invalid(world: World) -> None:
    world.write_config("policy.yaml", {"hard_limits": {"max_abs_voltage_v": 99.0}})
    meta = tools_by_name(world)["run_confirmed_plan"].get("_meta", {})
    assert meta.get(REQUIRES_USER_INTERACTION) is True


def test_explicit_override_wins(world: World) -> None:
    tools = tools_by_name(world, require_user_interaction=False)
    assert REQUIRES_USER_INTERACTION not in tools["run_confirmed_plan"].get("_meta", {})


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def test_instructions_and_descriptions_stay_small(world: World) -> None:
    assert len(INSTRUCTIONS) <= 400 and "b1500-test" in INSTRUCTIONS
    server = server_for(world)
    assert server.instructions == INSTRUCTIONS and server.name == "b1500"
    for name, tool in tools_by_name(world).items():
        description = tool.get("description", "")
        assert len(description) <= 400, name
        assert sentences(description) <= 3, name
        assert re.search(r"\bUse\b.*\b(after|before|first)\b", description), name
        assert "outputSchema" not in tool, name  # suppressed (blueprint 5.2); the description states the shape


def test_tool_parameters_mirror_the_service_methods(world: World) -> None:
    for name, tool in tools_by_name(world).items():
        method = inspect.signature(getattr(B1500Service, name))
        expected = [p for p in method.parameters if p != "self"]
        assert list(tool["inputSchema"]["properties"]) == expected, name
        required = [p.name for p in method.parameters.values() if p.name != "self" and p.default is p.empty]
        assert sorted(tool["inputSchema"].get("required", [])) == sorted(required), name


def assert_envelope(name: str, payload: dict[str, Any]) -> BaseModel:
    """The tool's JSON validates as its result model and carries backend/simulated."""
    assert "backend" in payload and "simulated" in payload, name
    model = RESULT_MODELS[name].model_validate(payload)
    assert isinstance(model, ResultEnvelope) and model.backend == "sim" and model.simulated is True
    return model


def test_schema_valid_outputs_for_every_tool(world: World) -> None:
    server = server_for(world)
    first = call_tools(server, [
        ("station_status", {}),
        ("list_recipes", {}),
        ("list_recipes", {"recipe_id": "mosfet.idvg"}),
        ("validate_plan", {**IDVG, "params": {"vd": 0.1}, "label": "mcp"}),
    ])
    for name, payload in zip(["station_status", "list_recipes", "list_recipes", "validate_plan"], first, strict=True):
        assert_envelope(name, payload)
    plan = PlanValidation.model_validate(first[3])
    assert plan.tier == "ok" and plan.plan_id is not None
    run = RunSummary.model_validate(call_tool(server, "run_plan", plan_id=plan.plan_id, dut_instance="D1"))
    assert run.ok and run.run_id is not None
    confirm = PlanValidation.model_validate(call_tool(server, "validate_plan", **IDVG, params={"vg_stop": 3.5}))
    refused = call_tool(server, "run_plan", plan_id=confirm.plan_id)
    assert assert_envelope("run_plan", refused).error_code == "confirmation_required"  # type: ignore[attr-defined]
    rest = call_tools(server, [
        ("run_confirmed_plan", {"plan_id": confirm.plan_id, "summary": confirm.summary}),
        ("list_runs", {"limit": 5}),
        ("get_run", {"run_id": run.run_id, "include": ["summary", "data", "notes"], "max_points": 20}),
        ("analyze_run", {"run_id": run.run_id, "method": "vth_linear_extrapolation"}),
        ("annotate_run", {"run_id": run.run_id, "text": "probe re-landed", "tags": ["handling"]}),
        ("safe_shutdown", {"reason": "end of test"}),
    ])
    names = ["run_confirmed_plan", "list_runs", "get_run", "analyze_run", "annotate_run", "safe_shutdown"]
    models = [assert_envelope(name, payload) for name, payload in zip(names, rest, strict=True)]
    assert all(m.ok for m in models), [m.message for m in models]  # type: ignore[attr-defined]
    detail = models[2]
    assert isinstance(detail, RunDetail) and detail.data is not None and detail.data.rows_returned <= 20


def test_errors_are_results_not_exceptions(world: World) -> None:
    server = server_for(world)
    payloads = call_tools(server, [
        ("run_plan", {"plan_id": "P-AAAAAAAAAA"}),
        ("get_run", {"run_id": "not-a-run"}),
        ("analyze_run", {"run_id": "S20261117T000000Z-0000", "method": "gm_max"}),
        ("validate_plan", {}),
    ])
    codes = [p["error_code"] for p in payloads]
    assert codes == ["unknown_plan", "invalid_input", "invalid_input", "invalid_input"]
    for name, payload in zip(["run_plan", "get_run", "analyze_run", "validate_plan"], payloads, strict=True):
        assert payload["ok"] is False
        assert_envelope(name, payload)


def test_module_registers_nothing_else() -> None:
    source = inspect.getsource(mcp_server)
    assert source.count("@mcp.tool(") == 10
    assert "B1500Admin" not in source and "fault_clear" not in source
