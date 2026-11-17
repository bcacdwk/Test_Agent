"""`b1500` command-line interface (Typer) and the `b1500-mcp` entry point.

WP0.3 skeleton: only the developer command `b1500 dev tool-budget` exists. Later work packages add the operator
commands of blueprint §5.3 on top of the same service layer as the MCP server.
"""

from __future__ import annotations

import sys
import warnings
from typing import Annotated

import typer

from b1500_test_agent.devtools import budget

# The 10-tool server arrives in WP1.8; until then pass --app explicitly.
DEFAULT_MCP_APP_SPEC = "b1500_test_agent.adapters.mcp_server:mcp"

app = typer.Typer(
    name="b1500",
    help="B1500A test agent: safety-gated measurement kernel (simulator by default).",
    no_args_is_help=True,
    add_completion=False,
)
dev_app = typer.Typer(help="Developer tools (never needed for lab operation).", no_args_is_help=True)
app.add_typer(dev_app, name="dev")


@app.callback()
def _root() -> None:
    """B1500A test agent: safety-gated measurement kernel (simulator by default)."""


@dev_app.command("tool-budget")
def tool_budget(
    app_spec: Annotated[
        str,
        typer.Option("--app", help="FastMCP app or zero-argument factory as 'package.module:attribute'."),
    ] = DEFAULT_MCP_APP_SPEC,
    top: Annotated[int | None, typer.Option("--top", min=1, help="List only the N largest tools.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full report as JSON.")] = False,
) -> None:
    """Count the tokens of an MCP tool surface as a client receives it (tiktoken o200k_base)."""
    try:
        mcp_app = budget.load_app(app_spec)
    except budget.AppSpecError as exc:
        hint = " (the b1500 MCP server arrives in WP1.8; pass --app)" if app_spec == DEFAULT_MCP_APP_SPEC else ""
        typer.echo(f"error: {exc}{hint}", err=True)
        raise typer.Exit(code=2) from exc
    with warnings.catch_warnings():
        # The fallback warning is carried in the report and echoed once below.
        warnings.simplefilter("ignore", RuntimeWarning)
        report = budget.measure_app(mcp_app, label=app_spec)
    if report.warning:
        typer.echo(f"warning: {report.warning}", err=True)
    typer.echo(report.model_dump_json(indent=2) if as_json else budget.format_report(report, top=top))


def main() -> None:
    """Entry point of the `b1500` console script."""
    app(prog_name="b1500")


def mcp_main() -> None:
    """Entry point of the `b1500-mcp` console script; a placeholder until the server lands in WP1.8."""
    sys.stderr.write("b1500-mcp: the MCP server arrives in WP1.8; nothing to serve yet.\n")
    raise SystemExit(1)
