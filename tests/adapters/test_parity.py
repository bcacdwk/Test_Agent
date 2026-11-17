"""MCP ↔ CLI parity (blueprint 5.3): each of the ten tools has one ``b1500`` command that calls the same
``B1500Service`` method and returns the same result model (the CLI's ``--json`` output is that model)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters import cli
from b1500_test_agent.adapters.cli import TOOL_COMMANDS, app
from b1500_test_agent.adapters.mcp_server import create_server
from b1500_test_agent.models.common import ResultEnvelope
from b1500_test_agent.service import TOOL_NAMES, B1500Service
from tests.adapters.helpers import call_tool
from tests.adapters.test_mcp_server import RESULT_MODELS
from tests.integration.helpers import IDVG, World

runner = CliRunner()


class Spy:
    """Wraps a ``B1500Service`` and records every tool method called and its result."""

    def __init__(self, inner: B1500Service) -> None:
        self.inner = inner
        self.calls: list[tuple[str, ResultEnvelope]] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if name not in TOOL_NAMES:
            return attr

        def recorded(*args: Any, **kwargs: Any) -> ResultEnvelope:
            result = attr(*args, **kwargs)
            self.calls.append((name, result))
            return result

        return recorded


def test_every_tool_has_exactly_one_command() -> None:
    assert list(TOOL_COMMANDS) == list(TOOL_NAMES)
    assert all(hasattr(B1500Service, name) for name in TOOL_NAMES)
    public = {n for n in vars(B1500Service) if not n.startswith("_") and callable(getattr(B1500Service, n))}
    assert public == set(TOOL_NAMES) | {"close", "session_tag"}


def prepared(world: World) -> dict[str, str]:
    """A run and a needs_confirmation plan to call the tools with."""
    service = world.service()
    ok_plan = service.validate_plan(**IDVG)
    run = service.run_plan(ok_plan.plan_id or "")
    confirm = service.validate_plan(**IDVG, params={"vg_stop": 3.5})
    assert run.run_id and confirm.summary and confirm.plan_id
    return {"plan_id": ok_plan.plan_id or "", "run_id": run.run_id, "confirm_id": confirm.plan_id,
            "summary": confirm.summary}


def cases(ids: dict[str, str]) -> dict[str, tuple[list[str], dict[str, Any]]]:
    """tool → (CLI arguments after the command, MCP arguments)."""
    return {
        "station_status": ([], {}),
        "list_recipes": (["mosfet.idvg"], {"recipe_id": "mosfet.idvg"}),
        "validate_plan": (["mosfet.idvg", "--pin-map", "mosfet-4t", "--dut", "nmos-generic"], dict(IDVG)),
        "run_plan": ([ids["plan_id"]], {"plan_id": ids["plan_id"]}),
        "run_confirmed_plan": ([ids["confirm_id"]], {"plan_id": ids["confirm_id"], "summary": ids["summary"]}),
        "list_runs": ([], {}),
        "get_run": ([ids["run_id"]], {"run_id": ids["run_id"]}),
        "analyze_run": ([ids["run_id"], "quality_report"], {"run_id": ids["run_id"], "method": "quality_report"}),
        "annotate_run": ([ids["run_id"], "parity note"], {"run_id": ids["run_id"], "text": "parity note"}),
        "safe_shutdown": (["--reason", "parity"], {"reason": "parity"}),
    }


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_cli_and_mcp_call_the_same_method_with_the_same_model(world: World, monkeypatch: pytest.MonkeyPatch,
                                                              tool: str) -> None:
    ids = prepared(world)
    cli_args, mcp_args = cases(ids)[tool]
    cli_spy = Spy(world.service(adapter="cli"))
    monkeypatch.setattr(cli, "make_service", lambda: cli_spy)
    monkeypatch.setattr(cli, "is_interactive", lambda: True)
    result = runner.invoke(app, [*TOOL_COMMANDS[tool], *cli_args, "--json"], input="y\n")
    assert result.exit_code == 0, result.output
    expected = [tool] if tool != "run_confirmed_plan" else ["validate_plan", "run_confirmed_plan"]
    assert [name for name, _ in cli_spy.calls] == expected
    cli_result = cli_spy.calls[-1][1]
    printed = json.loads(result.stdout[result.stdout.index("{"):])
    assert type(cli_result).model_validate(printed) == cli_result  # --json prints exactly the service model

    mcp_spy = Spy(world.service(adapter="mcp"))
    payload = call_tool(create_server(mcp_spy), tool, **mcp_args)  # type: ignore[arg-type]
    assert [name for name, _ in mcp_spy.calls] == [tool]
    mcp_result = mcp_spy.calls[-1][1]
    assert type(mcp_result) is type(cli_result) is RESULT_MODELS[tool]
    assert type(mcp_result).model_validate(payload) == mcp_result
    assert set(payload) == set(printed)
