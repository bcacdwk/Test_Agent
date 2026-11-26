"""``b1500 dev acceptance``: run, grade and report the harness acceptance scenarios (blueprint 8.2; v2 8.2 cost
policy).

- ``run --harness codex|claude`` with ``--scenario ID`` (repeatable), ``--all`` (the suite in
  ``tests/acceptance/scenarios/``), ``--tag F`` (repeatable; scenarios carrying any of the tags) and/or
  ``--affected [--since REF]`` (scenarios touched by the changes since the last committed report of this harness);
  pending scenarios (requirements not met) are left out; ``--max-sessions N`` caps the sessions; ``--dry-run`` only
  prints the selection. Exit 0 when every started scenario meets its threshold, 3 when the batch stopped at an infra
  event (login/API/network, v2.1 plan §2.4: nothing started after it; owner rule: stop, no retries).
- ``grade DIR``: re-grade a session folder, or every session of a batch folder.
- ``report BATCH_DIR... [--docs | --out FILE]``: write the Markdown report (``--docs``:
  ``docs/acceptance/<date>-<harness>-<version>.md`` in the repository, machine paths shortened).
- ``list``: the scenarios and probes with kind, default reps, tags and pending requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from b1500_test_agent.devtools.acceptance import report as report_mod
from b1500_test_agent.devtools.acceptance import runner, selection
from b1500_test_agent.devtools.acceptance.evidence import SESSION_FILE
from b1500_test_agent.devtools.acceptance.graders import SessionGrade, grade_session
from b1500_test_agent.devtools.acceptance.scenario import (
    PROBE_DIR,
    SUITE_DIR,
    load_scenario,
    missing_requirements,
    recipe_statuses,
    scenario_files,
)

acceptance_app = typer.Typer(help="Harness acceptance: isolated, graded Codex / Claude Code sessions on the "
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
    tail += f" ({len(grade.infra_notes)} infra note(s), not a stop)" if grade.infra_notes else ""
    return f"{grade.scenario_id} r{grade.rep}{' re-run' if grade.rerun else ''}: " \
           f"{'PASS' if grade.passed else 'FAIL'}{tail}"


@acceptance_app.command("run")
def run_command(
    harness: Annotated[str, typer.Option("--harness", help="codex or claude.")],
    scenario: Annotated[list[str] | None, typer.Option("--scenario", help="Scenario id or file (repeatable).")] = None,
    all_: Annotated[bool, typer.Option("--all", help=f"Every runnable scenario in {SUITE_DIR}/.")] = False,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Only scenarios with this tag (repeatable: any of "
                                                                "them), e.g. a family: smu, cmu, spgu, wgfmu.")]
    = None,
    affected: Annotated[bool, typer.Option("--affected", help="Only scenarios whose own file or touches: globs "
                                                              "match a file changed since the base.")] = False,
    since: Annotated[str | None, typer.Option("--since", help="Base for --affected (default: merge-base of HEAD "
                                                              "and the newest committed report of this harness).")]
    = None,
    max_sessions: Annotated[int | None, typer.Option("--max-sessions", min=1, help="Start no more sessions than "
                                                                                   "this (a scenario only when all "
                                                                                   "its reps fit).")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the selection and the session count; launch "
                                                            "nothing.")] = False,
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
    no_infra_stop: Annotated[bool, typer.Option("--no-infra-stop", hidden=True, help="Offline tests only: do not "
                                                                                     "stop at infra events.")] = False,
    docs: Annotated[bool, typer.Option("--docs", help="Also write docs/acceptance/<date>-<harness>-<version>.md.")]
    = False,
    as_json: JsonOption = False,
) -> None:
    """Run scenarios against a real harness (simulator only), grade them and write the report. Exit 0 when every
    started scenario meets its threshold (safety 3/3, functional 1 + one logged re-run); exit 3 when the batch
    stopped at the first login/API/network event (nothing started after it)."""
    if harness not in ("codex", "claude"):
        raise typer.BadParameter("--harness must be codex or claude")
    root = _repo(repo)
    try:
        chosen = selection.select(root, harness=harness, scenarios=scenario, all_=all_, tags=tag, affected=affected,
                                  since=since)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if dry_run:
        _print_selection(chosen, reps, max_sessions)
        return
    if not chosen.selected:
        typer.echo("no scenario selected" + "".join(f"\n  {k}: {v}" for k, v in chosen.skipped.items()), err=True)
        raise typer.Exit(code=2)
    options = runner.RunOptions(harness=harness, repo_root=root, out_dir=(out or runner.default_out()).resolve(),
                                reps=reps, timeout_s=timeout, extra_args=list(harness_arg or []),
                                rerun_failed_functional=not no_rerun, max_sessions=max_sessions,
                                infra_stop=not no_infra_stop)
    batch = runner.run_batch([item.path for item in chosen.selected], options, progress=_progress,
                             notes=chosen.notes())
    batch_dir = Path(batch.batch_dir)
    written = [report_mod.write_report([batch], batch_dir / "report.md")]
    if docs:
        written.append(report_mod.write_report([batch], report_mod.report_path(root, [batch]), shorten=True))
    infos, sessions = report_mod.merge([batch])
    verdicts = [report_mod.scenario_verdict(sid, infos[sid], sessions.get(sid, [])) for sid in infos]
    if as_json:
        typer.echo(batch.model_dump_json(indent=2))
    else:
        for grade in batch.sessions:
            typer.echo(_summary_line(grade))
        for verdict in verdicts:
            typer.echo(f"{verdict.scenario_id}: {verdict.verdict}")
        for sid, why in batch.skipped.items():
            typer.echo(f"{sid}: NOT STARTED ({why})")
        for path in written:
            typer.echo(f"report: {path}")
    if batch.infra_stop is not None:
        typer.echo(f"INFRA STOP at {batch.infra_stop.describe()}\nNothing was started after it. Owner rule: stop, no "
                   "retries; tell the owner and wait.", err=True)
        raise typer.Exit(code=3)
    if not all(v.verdict == "PASS" for v in verdicts):
        raise typer.Exit(code=1)


def _print_selection(chosen: selection.Selection, reps: int | None, max_sessions: int | None) -> None:
    """``run --dry-run``: the scenarios, why each was chosen, the planned sessions and what was left out."""
    for item in chosen.selected:
        n = reps or item.reps
        kind = "safety" if item.scenario.safety else "functional"
        typer.echo(f"{item.scenario.id:6} {kind:10} {n} session(s)  [{', '.join(item.scenario.tags)}]  "
                   f"{'; '.join(item.why)}")
    planned = chosen.sessions(reps)
    cap = f" (--max-sessions {max_sessions})" if max_sessions else ""
    typer.echo(f"planned: {len(chosen.selected)} scenario(s), {planned} session(s) without re-runs{cap}")
    for note in chosen.notes():
        typer.echo(note)


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
    docs: Annotated[bool, typer.Option("--docs", help="Write docs/acceptance/<date>-<harness>-<version>.md "
                                                      "(machine paths shortened).")] = False,
    shorten: Annotated[bool, typer.Option("--shorten", help="Print <repo> and <out> instead of this machine's "
                                                            "folders.")] = False,
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
            typer.echo(report_mod.render(loaded, shorten=shorten), nl=False)
            return
        typer.echo(f"report: {report_mod.write_report(loaded, path, shorten=shorten or docs)}")
    except (OSError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@acceptance_app.command("list")
def list_command(repo: RepoOption = None) -> None:
    """List the suite scenarios and the harness probes (kind, reps, tags; pending ones with what they still miss)."""
    root = _repo(repo)
    statuses = recipe_statuses(root)
    for path in scenario_files(root):
        where = "probe" if path.parent.name == Path(PROBE_DIR).name else "suite"
        try:
            scenario = load_scenario(path)
        except (ValueError, TypeError) as exc:
            typer.echo(f"{path.name}: INVALID ({str(exc).splitlines()[0]})", err=True)
            continue
        kind = "safety" if scenario.safety else "functional"
        missing = missing_requirements(scenario, root, statuses)
        pending = f"  PENDING: missing {', '.join(missing)}" if missing else ""
        tags = f"  [{', '.join(scenario.tags)}]" if scenario.tags else ""
        typer.echo(f"{scenario.id:13} {where:5} {kind:10} reps {scenario.default_reps}  {scenario.title}{tags}"
                   f"{pending}")
    sys.stdout.flush()
