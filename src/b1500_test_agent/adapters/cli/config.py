"""`b1500 config` group (blueprint v2 7.1; CLI only, no MCP tool): ``check``, and the human-only bootstrap commands
``init [--visa]`` and ``adopt FILE --as station|settings|policy|pinmap|dut``.

``check`` validates the configuration (rule R-CFG-01) and shows which file each item comes from. ``init`` copies the
missing core examples into ``config/local/`` and never overwrites; ``adopt`` validates one file against its schema,
prints the diff against the local file it replaces, keeps that file as ``<file>.bak`` and copies the new one in. Both
then run the check. They belong to the human: the harness rules (Claude Code ``deny``, Codex ``forbidden``) and the
guard hook ``scripts/hooks/b1500_guard.py`` block them for agents, which only propose (``b1500 bringup
propose-station``). With ``$B1500_CONFIG_DIR`` set (tests, M3 runner) they write into that directory instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, get_args

import typer

from b1500_test_agent.config import ConfigLoader, adopt, init_local
from b1500_test_agent.models.bringup import ConfigAdoptReport, ConfigInitReport, ConfigKind
from b1500_test_agent.models.common import ConfigReport

config_app = typer.Typer(help="Configuration (config/local/ over committed examples).", no_args_is_help=True)

JsonOption = Annotated[bool, typer.Option("--json", help="Print the result model as JSON.")]
KINDS: tuple[str, ...] = get_args(ConfigKind)


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


def _check_tail(check: ConfigReport | None) -> list[str]:
    if check is None:
        return []
    return ["", "config check:", *[f"  {line}" for line in format_config_report(check).splitlines()]]


def format_init_report(report: ConfigInitReport) -> str:
    """Human-readable `b1500 config init` output."""
    lines = [f"config init: {'ok' if report.ok else 'PROBLEMS'} (into {report.target_dir})"]
    lines += [f"  copied  {path}" for path in report.copied]
    lines += [f"  kept    {path} (exists; never overwritten)" for path in report.kept]
    lines += [f"  note    {note}" for note in report.notes]
    lines += [f"  problem {problem}" for problem in report.problems]
    return "\n".join(lines + _check_tail(report.check))


def format_adopt_report(report: ConfigAdoptReport) -> str:
    """Human-readable `b1500 config adopt` output: verdict, diff, backup and the check afterwards."""
    if report.problems and not report.adopted and not report.unchanged:
        lines = [f"config adopt: REFUSED, nothing written ({report.source} as {report.kind})"]
        lines += [f"  problem {problem}" for problem in report.problems]
        return "\n".join(lines)
    if report.unchanged:
        lines = [f"config adopt: unchanged, {report.target} already has this content"]
    else:
        lines = [f"config adopt: {report.source} -> {report.target} (as {report.kind})"]
        if report.backup:
            lines.append(f"previous file kept as {report.backup}")
        lines += ["diff:", *[f"  {line}" for line in report.diff]]
    lines += [f"problem: {problem}" for problem in report.problems]
    return "\n".join(lines + _check_tail(report.check))


@config_app.command("check")
def config_check(as_json: JsonOption = False) -> None:
    """Validate the configuration (rule R-CFG-01) and show which file is used for each item and why.

    Exit code 0 when valid, 1 with structured problems (error code invalid_config) otherwise.
    """
    report = ConfigLoader().check()
    typer.echo(report.model_dump_json(indent=2) if as_json else format_config_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@config_app.command("init")
def config_init(
    visa: Annotated[bool, typer.Option("--visa", help="Write backend: visa into the settings file it creates.")] =
    False,
    as_json: JsonOption = False,
) -> None:
    """HUMAN ONLY: copy the missing config/{settings,station,policy}.example.yaml into config/local/ (never
    overwrites); then check the configuration. Exit 1 on a problem or an invalid configuration."""
    report = init_local(visa=visa)
    typer.echo(report.model_dump_json(indent=2) if as_json else format_init_report(report))
    if not report.ok or (report.check is not None and not report.check.ok):
        raise typer.Exit(code=1)


@config_app.command("adopt")
def config_adopt(
    file: Annotated[Path, typer.Argument(help="The YAML file to adopt (e.g. work/bringup/station.proposed.yaml).")],
    kind: Annotated[str, typer.Option("--as", help=f"What the file is: {', '.join(KINDS)}.")],
    as_json: JsonOption = False,
) -> None:
    """HUMAN ONLY: validate FILE against the schema, show the diff, keep the previous local file as .bak and copy
    FILE into config/local/; then check the configuration. Exit 1 when refused or the configuration is invalid."""
    if kind not in KINDS:
        raise typer.BadParameter(f"--as must be one of {', '.join(KINDS)}", param_hint="--as")
    report = adopt(file, kind)  # type: ignore[arg-type]  # checked against KINDS above
    typer.echo(report.model_dump_json(indent=2) if as_json else format_adopt_report(report))
    if not report.ok:
        raise typer.Exit(code=1)
