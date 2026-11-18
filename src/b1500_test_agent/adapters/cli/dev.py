"""Developer commands under ``b1500 dev`` (never needed for lab operation): ``tool-budget``, ``recipe-check``,
``mcp-smoke --config F`` (start the server as a harness config says and check it), ``sync-harness [--check]``
(generated ``.claude/skills/`` copy of ``.agents/skills/``), ``lint-skills`` (skill schema, budgets, links; package
``devtools/skills/``), ``sim-console`` (raw FLEX, simulator only) and ``acceptance`` (M3 harness acceptance runner,
``devtools/acceptance/cli.py``).
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Annotated

import typer

from b1500_test_agent.adapters.cli import core
from b1500_test_agent.adapters.cli.core import DEFAULT_MCP_APP_SPEC, JsonOption
from b1500_test_agent.devtools import budget, mcp_smoke, recipe_check, sim_console, sync_harness
from b1500_test_agent.devtools.acceptance.cli import acceptance_app
from b1500_test_agent.devtools.skills import lint as lint_skills
from b1500_test_agent.paths import find_repo_root

dev_app = typer.Typer(help="Developer tools (never needed for lab operation).", no_args_is_help=True)
dev_app.add_typer(acceptance_app, name="acceptance")


@dev_app.command("tool-budget")
def tool_budget(
    app_spec: Annotated[
        str,
        typer.Option("--app", help="FastMCP app or zero-argument factory as 'package.module:attribute'."),
    ] = DEFAULT_MCP_APP_SPEC,
    top: Annotated[int | None, typer.Option("--top", min=1, help="List only the N largest tools.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Count the tokens of an MCP tool surface as a client receives it (tiktoken o200k_base)."""
    try:
        mcp_app = budget.load_app(app_spec)
    except budget.AppSpecError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    with warnings.catch_warnings():
        # The fallback warning is carried in the report and echoed once below.
        warnings.simplefilter("ignore", RuntimeWarning)
        report = budget.measure_app(mcp_app, label=app_spec)
    if report.warning:
        typer.echo(f"warning: {report.warning}", err=True)
    typer.echo(report.model_dump_json(indent=2) if as_json else budget.format_report(report, top=top))


@dev_app.command("recipe-check")
def recipe_check_command(as_json: JsonOption = False) -> None:
    """Load recipes/ against the measurement kinds and list every problem (schema, kind, card, analysis method,
    $param references, reserved slots). Exit code 0 iff there are none."""
    report = recipe_check.check_recipes()
    typer.echo(report.model_dump_json(indent=2) if as_json else recipe_check.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@dev_app.command("mcp-smoke")
def mcp_smoke_command(
    config: Annotated[Path, typer.Option("--config", help="Harness config: .mcp.json or .codex/config.toml.")],
    server: Annotated[str, typer.Option("--server", help="Server name in the config.")] = mcp_smoke.DEFAULT_SERVER,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", help="B1500_DATA_DIR for the server (default: a "
                                                                     "temporary folder, removed afterwards).")] = None,
    expect_backend: Annotated[str, typer.Option("--expect-backend", help="Backend station_status must report.")] =
    "sim",
    as_json: JsonOption = False,
) -> None:
    """Start the MCP server exactly as a harness config says, list its tools (exactly ten) and call
    station_status without instrument I/O (backend must match). Exit 1 on any problem."""
    try:
        launch = mcp_smoke.load_launch(config, server)
    except mcp_smoke.SmokeConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    report = mcp_smoke.run_smoke(launch, data_dir=data_dir, expect_backend=expect_backend)
    typer.echo(report.model_dump_json(indent=2) if as_json else mcp_smoke.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@dev_app.command("sync-harness")
def sync_harness_command(
    check: Annotated[bool, typer.Option("--check", help="Write nothing; exit 1 on any drift (missing, extra or "
                                                        "changed file).")] = False,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root (default: this clone).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Copy .agents/skills/<skill>/ into .claude/skills/ for Claude Code (full copy, GENERATED line after each
    Markdown frontmatter, stale files deleted); --check only reports drift. Exit 1 on drift or problems."""
    repo_root = root if root is not None else find_repo_root()
    report = sync_harness.check(repo_root) if check else sync_harness.sync(repo_root)
    typer.echo(report.model_dump_json(indent=2) if as_json else sync_harness.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@dev_app.command("lint-skills")
def lint_skills_command(
    root: Annotated[Path | None, typer.Option("--root", help="Root with .agents/skills/, recipes/ and config/ "
                                                             "(default: this clone).")] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", help="Config folder for the example plans "
                                                                         "(default: <root>/config).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Check skill frontmatter, budgets, links and the card/recipe/knowledge/runbook graph; validate each card's
    example plan on the simulator. Exit 1 with one line per problem."""
    report = lint_skills.lint_skills(root, config_dir=config_dir)
    typer.echo(report.model_dump_json(indent=2) if as_json else lint_skills.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@dev_app.command("sim-console")
def sim_console_command() -> None:
    """Raw FLEX console for the SIMULATOR only (refuses any other backend); cleanup runs when it ends."""

    def read_line(prompt: str) -> str | None:
        typer.echo(prompt, nl=False)
        line = sys.stdin.readline()
        return line if line else None

    try:
        sent = sim_console.run_console(core.make_service(), read_line, typer.echo)
    except sim_console.SimConsoleRefused as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.echo(f"error: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"{sent} line(s) sent to the simulator")
