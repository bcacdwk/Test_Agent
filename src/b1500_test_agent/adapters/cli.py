"""`b1500` command-line interface (Typer) and the `b1500-mcp` entry point.

Commands so far: `b1500 config check` (WP1.1) and the developer command `b1500 dev tool-budget` (WP0.3). Later
work packages add the operator commands of blueprint §5.3 on top of the same service layer as the MCP server.
"""

from __future__ import annotations

import sys
import warnings
from typing import Annotated

import typer

from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.devtools import budget
from b1500_test_agent.models.common import ConfigReport

# The 10-tool server arrives in WP1.8; until then pass --app explicitly.
DEFAULT_MCP_APP_SPEC = "b1500_test_agent.adapters.mcp_server:mcp"

app = typer.Typer(
    name="b1500",
    help="B1500A test agent: safety-gated measurement kernel (simulator by default).",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Configuration (config/local/ over committed examples).", no_args_is_help=True)
app.add_typer(config_app, name="config")
dev_app = typer.Typer(help="Developer tools (never needed for lab operation).", no_args_is_help=True)
app.add_typer(dev_app, name="dev")


@app.callback()
def _root() -> None:
    """B1500A test agent: safety-gated measurement kernel (simulator by default)."""


def format_config_report(report: ConfigReport) -> str:
    """Human-readable `b1500 config check` output: verdict, backend reason, files used, paths, problems."""
    lines = [f"config: {'valid' if report.ok else 'INVALID (invalid_config)'}"]
    if report.backend is not None:
        lines.append(f"backend: {report.backend_reason}")
    if report.files:
        lines.append("files used:")
        width = max(len(f.key) for f in report.files)
        lines += [f"  {f.key:<{width}}  {f.source:<8}  {f.path}  sha256:{f.sha256[:12]}" for f in report.files]
    if report.paths:
        lines.append("paths:")
        lines += [f"  {name}: {value}" for name, value in report.paths.items()]
    if report.warnings:
        lines.append("warnings:")
        lines += [f"  - {warning}" for warning in report.warnings]
    if report.problems:
        lines.append("problems:")
        for problem in report.problems:
            where = problem.file or "config"
            if problem.location:
                where += f" [{problem.location}]"
            lines.append(f"  - {where}: {problem.message}")
    return "\n".join(lines)


@config_app.command("check")
def config_check(
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Validate the configuration (rule R-CFG-01) and show which file is used for each item and why.

    Exit code 0 when valid, 1 with structured problems (error code invalid_config) otherwise.
    """
    report = ConfigLoader().check()
    typer.echo(report.model_dump_json(indent=2) if as_json else format_config_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


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
