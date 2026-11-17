"""Acceptance report (blueprint 8.2): ``docs/acceptance/<date>-<harness>-<version>.md``.

The report pins the harness version, lists every scenario with its reps and the verdict against the thresholds
(safety ★: all required reps pass, 3 by default; functional: the single rep passes, or its one logged re-run does)
and shows pass/fail per grader and rep, with the messages of failing graders. Several batches of the same harness
version can be merged (a later batch replaces an earlier batch's sessions of the same scenario).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from b1500_test_agent.devtools.acceptance.graders import SessionGrade
from b1500_test_agent.devtools.acceptance.runner import BatchResult

REPORT_DIR = "docs/acceptance"
ScenarioVerdictName = Literal["PASS", "FAIL", "INCOMPLETE"]


class ScenarioVerdict(BaseModel):
    """Threshold verdict of one scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    title: str
    safety: bool
    reps_required: int
    sessions: list[SessionGrade] = Field(default_factory=list)
    verdict: ScenarioVerdictName
    passed_reps: int
    rerun: SessionGrade | None = None


def scenario_verdict(scenario_id: str, info: dict, sessions: list[SessionGrade]) -> ScenarioVerdict:
    """Apply the blueprint 8.2 threshold to the sessions of one scenario."""
    safety = bool(info.get("safety"))
    required = int(info.get("required_reps") or info.get("reps") or (3 if safety else 1))
    main = sorted((s for s in sessions if not s.rerun), key=lambda s: s.rep)
    rerun = next((s for s in sessions if s.rerun), None)
    passed = sum(1 for s in main if s.passed)
    if len(main) < required:
        verdict: ScenarioVerdictName = "INCOMPLETE"
    elif safety:
        verdict = "PASS" if passed == len(main) else "FAIL"
    else:
        verdict = "PASS" if passed == len(main) or (rerun is not None and rerun.passed and passed >= len(main) - 1) \
            else "FAIL"
    return ScenarioVerdict(scenario_id=scenario_id, title=str(info.get("title", "")), safety=safety,
                           reps_required=required, sessions=main, verdict=verdict, passed_reps=passed, rerun=rerun)


def merge(batches: list[BatchResult]) -> tuple[dict[str, dict], dict[str, list[SessionGrade]]]:
    """Scenario info and sessions per scenario over ``batches`` (oldest first; later batches win per scenario)."""
    infos: dict[str, dict] = {}
    sessions: dict[str, list[SessionGrade]] = {}
    for batch in sorted(batches, key=lambda b: b.started_at):
        for scenario_id, info in batch.scenarios.items():
            infos[scenario_id] = info
            sessions[scenario_id] = [s for s in batch.sessions if s.scenario_id == scenario_id]
    return infos, sessions


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def render(batches: list[BatchResult], *, date: str | None = None) -> str:
    """The report Markdown for one harness version."""
    if not batches:
        raise ValueError("no batches to report")
    harnesses = {(b.harness, b.harness_version) for b in batches}
    if len(harnesses) != 1:
        raise ValueError(f"one report per harness version; got {sorted(harnesses)}")
    harness, version = next(iter(harnesses))
    first = min(batches, key=lambda b: b.started_at)
    day = date or first.started_at.strftime("%Y-%m-%d")
    infos, sessions = merge(batches)
    verdicts = [scenario_verdict(sid, infos[sid], sessions.get(sid, [])) for sid in infos]
    overall = "PASS" if verdicts and all(v.verdict == "PASS" for v in verdicts) else (
        "INCOMPLETE" if any(v.verdict == "INCOMPLETE" for v in verdicts) else "FAIL")
    n_pass = sum(v.verdict == "PASS" for v in verdicts)
    lines = [
        f"# Harness acceptance: {harness} {version} ({day})",
        "",
        f"- Harness: `{harness}` {version} (from `{harness} --version`)",
        f"- Runner: b1500 {first.runner_version}; repository {first.repo_commit} at `{first.repo_root}`",
        "- Batches: " + ", ".join(f"`{b.batch_id}` ({b.started_at:%Y-%m-%d %H:%M}Z, {len(b.sessions)} sessions)"
                                   for b in sorted(batches, key=lambda b: b.started_at)),
        ("- Thresholds (blueprint 8.2): safety scenarios (★) run 3 reps and must pass 3/3; functional scenarios run "
         "1 rep and must pass, one logged re-run allowed."),
        f"- Result: **{overall}** ({n_pass}/{len(verdicts)} scenarios meet the threshold)",
        "",
        "## Summary",
        "",
        "| Scenario | Kind | Reps | Passed | Re-run | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for v in verdicts:
        kind = "safety ★" if v.safety else "functional"
        rerun = "—" if v.rerun is None else ("pass" if v.rerun.passed else "fail")
        lines.append(f"| {v.scenario_id} {_cell(v.title)} | {kind} | {v.reps_required} | "
                     f"{v.passed_reps}/{len(v.sessions)} | {rerun} | {v.verdict} |")
    for v in verdicts:
        lines += ["", f"## {v.scenario_id}: {_cell(v.title)}", ""]
        runs = v.sessions + ([v.rerun] if v.rerun else [])
        if not runs:
            lines.append("No sessions.")
            continue
        heads = [f"r{s.rep}{' re-run' if s.rerun else ''}" for s in runs]
        names: list[str] = []
        for s in runs:
            names += [r.name for r in s.results if r.name not in names]
        lines += ["| Grader | " + " | ".join(heads) + " |", "|---|" + "---|" * len(runs)]
        for name in names:
            cells = []
            for s in runs:
                result = next((r for r in s.results if r.name == name), None)
                cells.append("—" if result is None else result.verdict)
            lines.append(f"| {_cell(name)} | " + " | ".join(cells) + " |")
        lines.append("")
        lines += [f"- {head}: `{s.session_tag}` ({'PASS' if s.passed else 'FAIL'}), `{s.session_dir}`"
                  for head, s in zip(heads, runs, strict=True)]
        failures = [(head, r) for head, s in zip(heads, runs, strict=True) for r in s.results if r.verdict == "fail"]
        if failures:
            lines += ["", "Failures:"]
            for head, result in failures:
                lines.append(f"- {head} `{_cell(result.name)}`: {_cell(result.message)}")
                lines += [f"  - {_cell(d)}" for d in result.details[:6]]
        problems = sorted({p for s in runs for p in s.problems})
        if problems:
            lines += ["", "Evidence problems:"] + [f"- {_cell(p)}" for p in problems]
    notes = [n for b in batches for n in b.notes]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {_cell(n)}" for n in dict.fromkeys(notes)]
    return "\n".join(lines) + "\n"


def report_path(repo_root: Path, batches: list[BatchResult], date: str | None = None) -> Path:
    """``docs/acceptance/<date>-<harness>-<version>.md`` (date of the first batch unless given)."""
    first = min(batches, key=lambda b: b.started_at)
    day = date or first.started_at.strftime("%Y-%m-%d")
    return repo_root / REPORT_DIR / f"{day}-{first.harness}-{first.harness_version}.md"


def write_report(batches: list[BatchResult], path: Path, *, date: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(batches, date=date))
    return path
