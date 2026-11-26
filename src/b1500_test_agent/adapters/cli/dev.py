"""Developer commands under ``b1500 dev`` (never needed for lab operation): ``tool-budget``, ``recipe-check``,
``mcp-smoke [--config F] [--async]`` (start the server as a harness config says and check it; ``--async`` also
runs an asynchronous simulator run through it), ``coverage [--write|--check]`` (generated ``docs/coverage.md``,
``devtools/coverage.py``), ``sync-harness [--check]``
(generated ``.claude/skills/`` copy of ``.agents/skills/``), ``lint-skills`` (skill schema, budgets, links; package
``devtools/skills/``), ``gen-index [--check]`` (generated card index ``cards/README.md``), ``sim-console`` (raw FLEX,
simulator only), ``acceptance`` (M3 harness acceptance runner, ``devtools/acceptance/cli.py``), ``harness qualify``
(the maintainer's ladder for a harness version, v2.1 plan §2.3, ``devtools/harness_qualify.py``) and ``cases list|check|
reproduce`` (the debug cases of skill ``b1500-debug`` and their simulator reproductions, v2.1 plan §3,
``devtools/cases.py``).
"""

from __future__ import annotations

import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from b1500_test_agent.adapters.cli import core
from b1500_test_agent.adapters.cli.core import DEFAULT_MCP_APP_SPEC, JsonOption
from b1500_test_agent.devtools import (
    budget,
    cases,
    coverage,
    harness,
    harness_qualify,
    mcp_smoke,
    recipe_check,
    sim_console,
    sync_harness,
    update,
)
from b1500_test_agent.devtools.acceptance import runner
from b1500_test_agent.devtools.acceptance.cli import acceptance_app
from b1500_test_agent.devtools.skills import index as card_index
from b1500_test_agent.devtools.skills import lint as lint_skills
from b1500_test_agent.paths import find_repo_root

dev_app = typer.Typer(help="Developer tools (never needed for lab operation).", no_args_is_help=True)
dev_app.add_typer(acceptance_app, name="acceptance")
harness_app = typer.Typer(help="Maintainer: qualify a harness version before operators get it (v2.1 plan §2.3).",
                          no_args_is_help=True)
dev_app.add_typer(harness_app, name="harness")
cases_app = typer.Typer(help="Debug cases of skill b1500-debug: list, check and reproduce them on the simulator "
                             "(v2.1 plan §3).", no_args_is_help=True)
dev_app.add_typer(cases_app, name="cases")


@cases_app.command("list")
def cases_list_command(
    reproduce: Annotated[bool, typer.Option("--reproduce/--no-reproduce", help="Run every reproduction on the "
                                                                               "simulator (temporary data folders) "
                                                                               "for its verdict.")] = True,
    as_json: JsonOption = False,
) -> None:
    """List the debug cases: status (draft or reviewed by whom), runbook, lab runs, reproduction verdict [SIMULATED]
    and open questions for the owner. Exit 1 on a case problem or a failed reproduction."""
    report = cases.cases_report(reproduce_all=reproduce)
    typer.echo(cases.report_json(report) if as_json else cases.format_cases(report))
    if not report.ok:
        raise typer.Exit(code=1)


@cases_app.command("check")
def cases_check_command(
    reproduce: Annotated[bool, typer.Option("--reproduce", help="Also run every reproduction and check its symptom "
                                                                "signature and discriminator.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Lint the case template and the cases (keys, sections, review rules, runbook links, reproduction references,
    open questions); with --reproduce also run each reproduction. Exit 0 iff everything passes."""
    report = cases.cases_report(reproduce_all=reproduce)
    typer.echo(cases.report_json(report) if as_json else cases.format_cases(report, verbose=False))
    if not report.ok:
        raise typer.Exit(code=1)


@cases_app.command("reproduce")
def cases_reproduce_command(
    case_id: Annotated[str, typer.Argument(help="Case id (file name without .md).")],
    out: Annotated[Path | None, typer.Option("--out", help="Empty or new folder for data/ and report.json (default "
                                                           "work/cases/<case>/<UTC stamp>/).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Run one case's simulator reproduction (backend sim, committed config only) and show each step's run and every
    expectation with the values it read; the runs stay in the output folder. Exit 1 when it does not reproduce."""
    try:
        report = cases.reproduce(case_id, out=out)
    except (cases.CaseRefused, FileExistsError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(cases.report_json(report) if as_json else cases.format_reproduction(report))
    if not report.ok:
        raise typer.Exit(code=1)


@harness_app.command("qualify")
def harness_qualify_command(
    harness_name: Annotated[str | None, typer.Option("--harness", help="codex or claude (default: every installed "
                                                                       "harness).")] = None,
    candidate: Annotated[str | None, typer.Option("--candidate", help="Install this version (x.y.z or latest) with "
                                                                      "the one installer first; needs your own "
                                                                      "terminal. A FAIL puts the validated version "
                                                                      "back.")] = None,
    up_to: Annotated[int, typer.Option("--up-to", min=0, max=2, help="Highest tier: 0 free checks, 1 probes, 2 "
                                                                     "canary (default; only a full ladder bumps).")]
    = 2,
    escalate: Annotated[bool, typer.Option("--escalate", help="T3: run the scenarios mapped to a failed or at-risk "
                                                              "surface with the §8.2 reps.")] = False,
    max_sessions: Annotated[int | None, typer.Option("--max-sessions", min=1, help="Cap the T3 sessions.")] = None,
    windows: Annotated[bool, typer.Option("--windows", help="Lab PC: T0 + T1 + S16 on the installed, validated "
                                                            "version; records data/state/harness/windows.json, no "
                                                            "bump.")] = False,
    pin: Annotated[bool, typer.Option("--pin", help="On PASS also write the sanitized T1 sessions to "
                                                    "tests/fixtures/transcripts/<harness>-<version>/.")] = False,
    out: Annotated[Path | None, typer.Option("--out", help=f"Session artifacts (default ${runner.ENV_OUT} or "
                                                           "<system temp>/b1500-acceptance).")] = None,
    timeout: Annotated[float | None, typer.Option("--timeout", min=1, help="Per-turn timeout in seconds.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Qualify a harness version: T0 free checks, T1 probes, T2 canary (S4, S5, S16), T3 with --escalate. A PASS of
    the full ladder writes docs/acceptance/<date>-<harness>-<version>-qualify.md and bumps
    config/harness/validated.yaml (you commit both). Exit 0 PASS, 1 FAIL, 2 refused, 3 stopped at a login/API/network
    event (nothing runs after it)."""
    if harness_name not in (None, "codex", "claude"):
        raise typer.BadParameter("--harness must be codex or claude")
    ops = update.UpdateContext.default(interactive=sys.stdin.isatty(), ask=lambda _q: False,
                                       say=lambda text: typer.echo(text, err=True))
    ctx = harness_qualify.QualifyContext(ops=ops, out_dir=(out or runner.default_out()).resolve(), today=date.today(),
                                         run_batch=harness_qualify.default_batch_runner(ops.say),
                                         run_tests=harness_qualify.default_test_runner)
    opts = harness_qualify.QualifyOptions(harness=harness_name, candidate=candidate,  # type: ignore[arg-type]
                                          up_to=up_to, escalate=escalate, max_sessions=max_sessions, windows=windows,
                                          pin=pin, timeout_s=timeout)
    try:
        report = harness_qualify.run_qualify(ctx, opts)
    except harness_qualify.QualifyRefused as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(report.model_dump_json(indent=2) if as_json else harness_qualify.format_summary(report))
    if report.exit_code:
        raise typer.Exit(code=report.exit_code)


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
    $param references, waveform files, hardware promotion). Exit code 0 iff there are none."""
    report = recipe_check.check_recipes()
    typer.echo(report.model_dump_json(indent=2) if as_json else recipe_check.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@dev_app.command("mcp-smoke")
def mcp_smoke_command(
    config: Annotated[Path | None, typer.Option("--config", help="Harness config: .mcp.json or "
                                                                 ".codex/config.toml (default: the Claude Code "
                                                                 "config rendered for this clone).")] = None,
    server: Annotated[str, typer.Option("--server", help="Server name in the config.")] = mcp_smoke.DEFAULT_SERVER,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", help="B1500_DATA_DIR for the server (default: a "
                                                                     "temporary folder, removed afterwards).")] = None,
    expect_backend: Annotated[str, typer.Option("--expect-backend", help="Backend station_status must report.")] =
    "sim",
    async_check: Annotated[bool, typer.Option("--async", help="Also run an asynchronous simulator run through the "
                                                              "server: running, busy, progress, list, "
                                                              "safe_shutdown cancels it.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Start the MCP server exactly as a harness config says, list its tools (exactly ten) and call
    station_status without instrument I/O (backend must match); with --async also check an asynchronous run
    end to end over stdio. Exit 1 on any problem."""
    repo_root = find_repo_root()
    with tempfile.TemporaryDirectory(prefix="b1500-smoke-config-") as scratch:
        try:
            if config is None:
                target = harness.TARGETS["claude"]
                config = Path(scratch) / Path(target.output).name
                config.write_text(harness.render(target, (repo_root / target.template).read_text(encoding="utf-8"),
                                                 repo_root), encoding="utf-8")
            launch = mcp_smoke.load_launch(config, server)
        except mcp_smoke.SmokeConfigError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        report = mcp_smoke.run_smoke(launch, data_dir=data_dir, expect_backend=expect_backend,
                                     async_check=async_check, repo_root=repo_root)
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


@dev_app.command("gen-index")
def gen_index_command(
    check: Annotated[bool, typer.Option("--check", help="Write nothing; exit 1 when cards/README.md differs from "
                                                        "the generated index.")] = False,
    root: Annotated[Path | None, typer.Option("--root", help="Root with .agents/skills/ and recipes/ (default: this "
                                                             "clone).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Write the generated card index .agents/skills/b1500-test/cards/README.md from the card frontmatter and the
    recipe registry; --check only compares. Exit 1 on drift or invalid card frontmatter."""
    report = card_index.gen_index(root, check=check)
    typer.echo(report.model_dump_json(indent=2) if as_json else card_index.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@dev_app.command("coverage")
def coverage_command(
    write: Annotated[bool, typer.Option("--write", help="Write docs/coverage.md (the default).")] = False,
    check: Annotated[bool, typer.Option("--check", help="Write nothing; exit 1 when docs/coverage.md differs from "
                                                        "the generated page or the coverage has a gap.")] = False,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root (default: this clone).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Generate docs/coverage.md: per module the kinds, recipes, cards, rules, simulator model, bring-up stages and
    ledger counts, the in-scope modes and the recipes; --check only compares. Exit 1 on drift or any coverage gap
    (module without recipe, unused kind, rule in no table, open ledger entry, recipe without card or stage)."""
    if write and check:
        typer.echo("error: --write and --check exclude each other", err=True)
        raise typer.Exit(code=2)
    report = coverage.coverage(root, check=check)
    typer.echo(report.model_dump_json(indent=2) if as_json else coverage.format_report(report))
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
