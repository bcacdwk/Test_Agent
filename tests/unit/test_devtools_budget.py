"""Unit tests for the MCP tool token counter (blueprint §5.2) on a tiny two-tool FastMCP app."""

from __future__ import annotations

import asyncio
import json
import math
import sys
import warnings

import pytest
from fastmcp import FastMCP
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app as cli_app
from b1500_test_agent.devtools import budget

SPEC = f"{__name__}:build_app"


def build_app() -> FastMCP:
    """Two tools: one with explicit annotations, one without."""
    mcp = FastMCP(name="budget-test")

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @mcp.tool
    def echo(text: str) -> str:
        """Echo the text back unchanged."""
        return text

    return mcp


APP = build_app()
NOT_AN_APP = "just a string"


def _char_counter() -> budget.TokenCounter:
    """Deterministic counter: one token per character."""
    return budget.TokenCounter(method="test:chars", count=len)


def _tools() -> dict[str, object]:
    return {tool.name: tool for tool in asyncio.run(budget.list_app_tools(APP))}


def test_serialization_is_compact_json_of_budget_fields_only() -> None:
    tools = _tools()
    assert set(tools) == {"add", "echo"}
    for tool in tools.values():
        text = budget.serialize_tool(tool)
        payload = json.loads(text)
        assert json.dumps(payload, ensure_ascii=False, separators=(",", ":")) == text
        assert set(payload) <= set(budget.BUDGET_FIELDS)
        assert {"name", "description", "inputSchema"} <= set(payload)
    add = json.loads(budget.serialize_tool(tools["add"]))
    assert add["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
    assert "annotations" not in json.loads(budget.serialize_tool(tools["echo"]))


def test_measure_app_reports_per_tool_and_total() -> None:
    report = budget.measure_app(APP, counter=_char_counter(), label="tiny")
    assert report.app == "tiny"
    assert report.method == "test:chars"
    assert report.warning is None
    assert report.tool_count == 2
    assert [row.name for row in report.tools] == ["add", "echo"]
    for row in report.tools:
        assert row.tokens == row.chars > 0
        assert row.chars_div4 == math.ceil(row.chars / 4)
    assert report.total_tokens == sum(row.tokens for row in report.tools)
    assert report.total_chars == sum(row.chars for row in report.tools)
    assert report.total_chars_div4 == sum(row.chars_div4 for row in report.tools)


def test_fallback_counter_warns_when_encoding_cannot_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(name: str) -> None:
        raise ConnectionError(f"cannot download {name}")

    monkeypatch.setattr("tiktoken.get_encoding", offline)
    with pytest.warns(RuntimeWarning, match="falling back to chars/3.5"):
        counter = budget.load_counter()
    assert counter.method == "chars/3.5"
    assert counter.count("x" * 7) == 2
    assert counter.count("x" * 8) == 3
    report = budget.measure_app(APP, counter=counter)
    assert report.warning is not None and "o200k_base" in report.warning
    assert all(row.tokens == math.ceil(row.chars / 3.5) for row in report.tools)


def test_fallback_when_tiktoken_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    with pytest.warns(RuntimeWarning):
        counter = budget.load_counter()
    assert counter.method == "chars/3.5"


def test_real_counter_uses_o200k_base_or_warned_fallback() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        counter = budget.load_counter()
    if counter.method == "tiktoken:o200k_base":
        assert counter.count("hello world") == 2
        assert not [w for w in caught if "falling back" in str(w.message)]
    else:
        assert counter.method == "chars/3.5"
        assert counter.warning
        assert any(issubclass(w.category, RuntimeWarning) for w in caught)


def test_load_app_accepts_instance_and_factory() -> None:
    assert budget.load_app(f"{__name__}:APP") is APP
    built = budget.load_app(SPEC)
    assert isinstance(built, FastMCP)
    assert built is not APP


@pytest.mark.parametrize(
    "spec",
    ["no_colon_here", ":APP", f"{__name__}:", "b1500_test_agent.no_such_module:mcp", f"{__name__}:missing_attr",
     f"{__name__}:NOT_AN_APP"],
)
def test_load_app_rejects_bad_specs(spec: str) -> None:
    with pytest.raises(budget.AppSpecError):
        budget.load_app(spec)


def test_format_report_lists_largest_first_and_keeps_totals() -> None:
    report = budget.measure_app(APP, counter=_char_counter(), label="tiny")
    text = budget.format_report(report, top=1)
    largest = max(report.tools, key=lambda row: row.tokens)
    smallest = min(report.tools, key=lambda row: row.tokens)
    assert largest.name in text
    assert f"  {smallest.name}\n" not in text
    assert "... 1 more tools" in text
    assert f"{report.total_tokens}" in text and "TOTAL (2 tools)" in text


def test_cli_tool_budget_json_and_text() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["dev", "tool-budget", "--app", SPEC, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["tool_count"] == 2
    assert payload["total_tokens"] == sum(row["tokens"] for row in payload["tools"])
    assert payload["serialized_fields"] == list(budget.BUDGET_FIELDS)

    text = runner.invoke(cli_app, ["dev", "tool-budget", "--app", SPEC])
    assert text.exit_code == 0, text.output
    assert "TOTAL (2 tools)" in text.stdout


def test_cli_tool_budget_reports_missing_app_cleanly() -> None:
    result = CliRunner().invoke(cli_app, ["dev", "tool-budget", "--app", "b1500_test_agent.no_such_module:mcp"])
    assert result.exit_code == 2
    assert "cannot import module" in result.stderr


def test_cli_help_and_mcp_placeholder(capsys: pytest.CaptureFixture[str]) -> None:
    from b1500_test_agent.adapters.cli import mcp_main

    help_result = CliRunner().invoke(cli_app, ["--help"])
    assert help_result.exit_code == 0
    assert "dev" in help_result.stdout
    with pytest.raises(SystemExit) as excinfo:
        mcp_main()
    assert excinfo.value.code != 0
    assert "WP1.8" in capsys.readouterr().err
