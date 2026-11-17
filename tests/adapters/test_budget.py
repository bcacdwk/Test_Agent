"""Token budget of the ten-tool surface (blueprint 5.2), measured with ``devtools.budget.measure_app`` exactly as
``b1500 dev tool-budget`` does: tool names == the ten of 5.1, at most 20 tools, total <= 4,500 tokens, each <= 700."""

from __future__ import annotations

import json
import warnings

from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import DEFAULT_MCP_APP_SPEC, app
from b1500_test_agent.devtools import budget
from b1500_test_agent.service import TOOL_NAMES
from tests.adapters.helpers import mcp_server
from tests.integration.helpers import World

TOTAL_CAP = 4500
PER_TOOL_CAP = 700


def test_tool_budget(world: World) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # offline fallback chars/3.5 overestimates; still checked
        report = budget.measure_app(mcp_server(world), label="b1500")
    assert [row.name for row in report.tools] == list(TOOL_NAMES)
    assert report.tool_count <= 20
    assert report.total_tokens <= TOTAL_CAP, report.total_tokens
    assert max(row.tokens for row in report.tools) <= PER_TOOL_CAP


def test_budget_command_defaults_to_the_b1500_server(cli_world: World) -> None:
    assert DEFAULT_MCP_APP_SPEC == "b1500_test_agent.adapters.mcp_server:create_server"
    result = CliRunner().invoke(app, ["dev", "tool-budget", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["tool_count"] == 10 and report["total_tokens"] <= TOTAL_CAP
    assert sorted(row["name"] for row in report["tools"]) == sorted(TOOL_NAMES)
