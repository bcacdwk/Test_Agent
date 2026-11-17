"""``b1500 dev acceptance``: run, grade and report the M3 harness acceptance scenarios (blueprint 8.2).

- ``run --harness codex|claude --scenario ID [--reps N]`` (repeatable ``--scenario``) or ``--all`` (the suite in
  ``tests/acceptance/scenarios/``); exit 0 when every scenario meets its threshold.
- ``grade DIR``: re-grade a session folder, or every session of a batch folder.
- ``report BATCH_DIR... [--docs | --out FILE]``: write the Markdown report (``--docs``:
  ``docs/acceptance/<date>-<harness>-<version>.md`` in the repository).
- ``list``: the scenarios and probes with kind and default reps.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from b1500_test_agent.devtools.acceptance import report as report_mod
from b1500_test_agent.devtools.acceptance import runner
from b1500_test_agent.devtools.acceptance.evidence import SESSION_FILE
from b1500_test_agent.devtools.acceptance.graders import SessionGrade, grade_session
from b1500_test_agent.devtools.acceptance.scenario import (
    PROBE_DIR,
    SUITE_DIR,
    find_scenario,
    load_scenario,
    scenario_files,
)

acceptance_app = typer.Typer(help="M3 harness acceptance: isolated, graded Codex / Claude Code sessions on the "
                                  "simulator (blueprint 8.2).", no_args_is_help=True)

RepoOption = Annotated[Path | None, typer.Option("--repo", help=f"Repository root the harness is launched from "
                                                                f"(default ${runner.ENV_REPO} or the current "
                                                                "directory).")]
JsonOption = Annotated[bool, typer.Option("--json", help="Print JSON.")]


def _repo(repo: Path | None) -> Path:
    root = (repo or runner.default_repo()).resolve()
    if not (root / "pyproject.toml").is_file() or not (root / "config").is_dir():
        raise typer.BadParameter(f"{root} is not the repository root (no pyproject.toml / config/)")
    return root


def _progress(message: str) -> None:
    typer.echo(message, err=True)


def _summary_line(grade: SessionGrade) -> str:
    failed = [r.name for r in grade.failures()]
    tail = f" (failed: {', '.join(failed)})" if failed else ""
    return f"{grade.scenario_id} r{grade.rep}{' re-run' if grade.rerun else ''}: " \
           f"{'PASS' if grade.passed else 'FAIL'}{tail}"


@acceptance_app.command("run")
def run_command(
    harness: Annotated[str, typer.Option("--harness", help="codex or claude.")],
    scenario: Annotated[list[str] | None, typer.Option("--scenario", help="Scenario id or file (repeatable).")] = None,
    all_: Annotated[bool, typer.Option("--all", help=f"Every scenario in {SUITE_DIR}/.")] = False,
    reps: Annotated[int | None, typer.Option("--reps", min=1, help="Reps per scenario (default: safety 3, "
                                                                   "functional 1).")] = None,
    repo: RepoOption = None,
    out: Annotated[Path | None, typer.Option("--out", help=f"Artifacts folder (default ${runner.ENV_OUT} or "
                                                           "<system temp>/b1500-acceptance).")] = None,
    timeout: Annotated[float | None, typer.Option("--timeout", min=1, help="Per-turn timeout in seconds.")] = None,
    harness_arg: Annotated[list[str] | None, typer.Option("--harness-arg", help="Extra argument for the harness "
                                                                                "(repeatable; bypass modes are "
                                                                                "refused).")] = None,
    no_rerun: Annotated[bool, typer.Option("--no-rerun", help="No re-run of a failed functional scenario.")] = False,
    docs: Annotated[bool, typer.Option("--docs", help="Also write docs/acceptance/<date>-<harness>-<version>.md.")]
    = False,
    as_json: JsonOption = False,
) -> None:
    """Run scenarios against a real harness (simulator only), grade them and write the report. Exit 0 when every
    scenario meets its threshold (safety 3/3, functional 1 + one logged re-run)."""
    if harness not in ("codex", "claude"):
        raise typer.BadParameter("--harness must be codex or claude")
    root = _repo(repo)
    if all_ == bool(scenario):
        raise typer.BadParameter("give --scenario ID (repeatable) or --all")
    try:
        files = scenario_files(root, probes=False) if all_ else [find_scenario(root, s) for s in scenario or []]
        for path in files:
            load_scenario(path)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if not files:
        typer.echo(f"error: no scenarios in {SUITE_DIR}/", err=True)
        raise typer.Exit(code=2)
    options = runner.RunOptions(harness=harness, repo_root=root, out_dir=(out or runner.default_out()).resolve(),
                                reps=reps, timeout_s=timeout, extra_args=list(harness_arg or []),
                                rerun_failed_functional=not no_rerun)
    batch = runner.run_batch(files, options, progress=_progress)
    batch_dir = Path(batch.batch_dir)
    written = [report_mod.write_report([batch], batch_dir / "report.md")]
    if docs:
        written.append(report_mod.write_report([batch], report_mod.report_path(root, [batch])))
    infos, sessions = report_mod.merge([batch])
    verdicts = [report_mod.scenario_verdict(sid, infos[sid], sessions.get(sid, [])) for sid in infos]
    if as_json:
        typer.echo(batch.model_dump_json(indent=2))
    else:
        for grade in batch.sessions:
            typer.echo(_summary_line(grade))
        for verdict in verdicts:
            typer.echo(f"{verdict.scenario_id}: {verdict.verdict}")
        for path in written:
            typer.echo(f"report: {path}")
    if not all(v.verdict == "PASS" for v in verdicts):
        raise typer.Exit(code=1)


@acceptance_app.command("grade")
def grade_command(
    folder: Annotated[Path, typer.Argument(help="A session folder (session.json) or a batch folder (batch.json).")],
    as_json: JsonOption = False,
) -> None:
    """Re-grade recorded sessions from their artifacts (no harness is launched). Exit 0 when all pass."""
    if (folder / SESSION_FILE).is_file():
        grades = [grade_session(folder)]
    elif (folder / runner.BATCH_FILE).is_file():
        batch = runner.load_batch(folder)
        grades = [grade_session(Path(s.session_dir)) for s in batch.sessions]
        batch.sessions = grades
        runner.write_json(folder / runner.BATCH_FILE, batch)
        report_mod.write_report([batch], folder / "report.md")
    else:
        typer.echo(f"error: {folder} has neither {SESSION_FILE} nor {runner.BATCH_FILE}", err=True)
        raise typer.Exit(code=2)
    if as_json:
        typer.echo("[" + ",\n".join(g.model_dump_json(indent=2) for g in grades) + "]")
    else:
        for grade in grades:
            typer.echo(_summary_line(grade))
            for result in grade.results:
                typer.echo(f"  {result.verdict:7} {result.name}: {result.message}")
    if not all(g.passed for g in grades):
        raise typer.Exit(code=1)


@acceptance_app.command("report")
def report_command(
    batches: Annotated[list[Path], typer.Argument(help="Batch folders of one harness version.")],
    out: Annotated[Path | None, typer.Option("--out", help="Report file.")] = None,
    docs: Annotated[bool, typer.Option("--docs", help="Write docs/acceptance/<date>-<harness>-<version>.md.")] =
    False,
    repo: RepoOption = None,
) -> None:
    """Write the Markdown report of one or more batches."""
    try:
        loaded = [runner.load_batch(b) for b in batches]
        if docs:
            path = report_mod.report_path(_repo(repo), loaded)
        elif out is not None:
            path = out
        else:
            typer.echo(report_mod.render(loaded), nl=False)
            return
        typer.echo(f"report: {report_mod.write_report(loaded, path)}")
    except (OSError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@acceptance_app.command("list")
def list_command(repo: RepoOption = None) -> None:
    """List the suite scenarios and the harness probes."""
    root = _repo(repo)
    for path in scenario_files(root):
        where = "probe" if path.parent.name == Path(PROBE_DIR).name else "suite"
        try:
            scenario = load_scenario(path)
        except (ValueError, TypeError) as exc:
            typer.echo(f"{path.name}: INVALID ({str(exc).splitlines()[0]})", err=True)
            continue
        kind = "safety" if scenario.safety else "functional"
        typer.echo(f"{scenario.id:12} {where:5} {kind:10} reps {scenario.default_reps}  {scenario.title}")
    sys.stdout.flush()
