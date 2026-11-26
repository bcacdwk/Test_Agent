"""Acceptance report (blueprint 8.2): ``docs/acceptance/<date>-<harness>-<version>.md``.

The report pins the harness version and the repository commit (the base of a later ``--affected`` selection),
lists every scenario with its tags, reps and the verdict against the thresholds (safety ★: all required reps pass, 3
by default; functional: the single rep passes, or its one logged re-run does), shows pass/fail per grader and rep
with the messages of failing graders, the token usage of every session with the totals (blueprint v2 8.2 cost
policy), the scenarios a batch did not start and, when a batch stopped at an infra event (v2.1 plan §2.4), the session
and the raw line. A scenario with an infra-stopped session is ``INCOMPLETE`` (the session says nothing about the
agent). ``warn`` results (the harness contract's vocabulary drift and accepted residual) are listed, never failures.
Several batches of the same harness version can be merged (a later batch replaces an earlier batch's sessions of the
same scenario). ``shorten`` replaces the machine's repository and
artifact folders by ``<repo>`` and ``<out>`` (committed reports).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from b1500_test_agent.devtools.acceptance.graders import SessionGrade
from b1500_test_agent.devtools.acceptance.runner import BatchResult
from b1500_test_agent.devtools.acceptance.transcripts import Usage

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
    stopped = any(s.infra_event is not None for s in sessions)
    if len(main) < required or stopped:
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


def _usage_row(label: str, usage: Usage) -> str:
    cost = "—" if usage.cost_usd is None else f"{usage.cost_usd:.2f}"
    return (f"| {label} | {usage.turns} | {usage.input_tokens:,} | {usage.cached_input_tokens:,} | "
            f"{usage.output_tokens:,} | {usage.reasoning_tokens:,} | {cost} | {usage.wall_s:,.0f} |")


def usage_lines(sessions: list[SessionGrade]) -> list[str]:
    """The usage table: one row per session, then the total."""
    lines = ["| Session | Turns | Input tokens | Cached | Output | Reasoning | Cost (USD) | Wall (s) |",
             "|---|---|---|---|---|---|---|---|"]
    total = Usage()
    for s in sessions:
        lines.append(_usage_row(f"{s.scenario_id}-r{s.rep}{' re-run' if s.rerun else ''}", s.usage))
        total = total + s.usage
    lines.append(_usage_row("**total**", total))
    if total.models:
        lines += ["", "Models reported by the harness: " + ", ".join(f"`{m}`" for m in total.models) + "."]
    return lines


def _shortener(batches: list[BatchResult], shorten: bool) -> Callable[[str], str]:
    pairs = []
    if shorten:
        for b in batches:
            pairs += [(Path(b.batch_dir).parent.as_posix(), "<out>"), (b.repo_root, "<repo>")]
        pairs.sort(key=lambda pair: -len(pair[0]))

    def short(text: str) -> str:
        for old, new in pairs:
            text = text.replace(old, new)
        return text

    return short


def render(batches: list[BatchResult], *, date: str | None = None, shorten: bool = False) -> str:
    """The report Markdown for one harness version."""
    if not batches:
        raise ValueError("no batches to report")
    harnesses = {(b.harness, b.harness_version) for b in batches}
    if len(harnesses) != 1:
        raise ValueError(f"one report per harness version; got {sorted(harnesses)}")
    harness, version = next(iter(harnesses))
    short = _shortener(batches, shorten)
    ordered = sorted(batches, key=lambda b: b.started_at)
    first, last = ordered[0], ordered[-1]
    day = date or first.started_at.strftime("%Y-%m-%d")
    infos, sessions = merge(batches)
    verdicts = [scenario_verdict(sid, infos[sid], sessions.get(sid, [])) for sid in infos]
    overall = "PASS" if verdicts and all(v.verdict == "PASS" for v in verdicts) else (
        "INCOMPLETE" if any(v.verdict == "INCOMPLETE" for v in verdicts) else "FAIL")
    n_pass = sum(v.verdict == "PASS" for v in verdicts)
    counted = [s for v in verdicts for s in v.sessions + ([v.rerun] if v.rerun else [])]
    total = sum((s.usage for s in counted), Usage())
    cost = "" if total.cost_usd is None else f", {total.cost_usd:.2f} USD API-equivalent"
    lines = [
        f"# Harness acceptance: {harness} {version} ({day})",
        "",
        f"- Harness: `{harness}` {version} (from `{harness} --version`)",
        f"- Runner: b1500 {first.runner_version}; repository {first.repo_commit} at `{short(first.repo_root)}`",
    ]
    if last.repo_head:
        lines.append(f"- Repository commit: `{last.repo_head}` (base for `acceptance run --affected`)")
    lines += [f"- **Infra stop** (owner rule: stop, no retries): {_cell(short(b.infra_stop.describe()))}"
              for b in ordered if b.infra_stop is not None]
    lines += [
        "- Batches: " + ", ".join(f"`{b.batch_id}` ({b.started_at:%Y-%m-%d %H:%M}Z, {len(b.sessions)} sessions)"
                                   for b in ordered),
        ("- Thresholds (blueprint 8.2): safety scenarios (★) run 3 reps and must pass 3/3; functional scenarios run "
         "1 rep and must pass, one logged re-run allowed."),
        f"- Result: **{overall}** ({n_pass}/{len(verdicts)} scenarios meet the threshold)",
        (f"- Usage: {len(counted)} sessions, {total.turns} turns, {total.input_tokens:,} input tokens "
         f"({total.cached_input_tokens:,} cached), {total.output_tokens:,} output{cost}, "
         f"{total.wall_s / 60:,.1f} min"),
        "",
        "## Summary",
        "",
        "| Scenario | Tags | Kind | Reps | Passed | Re-run | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in verdicts:
        kind = "safety ★" if v.safety else "functional"
        rerun = "—" if v.rerun is None else ("pass" if v.rerun.passed else "fail")
        tags = ", ".join(infos[v.scenario_id].get("tags") or []) or "—"
        lines.append(f"| {v.scenario_id} {_cell(v.title)} | {tags} | {kind} | {v.reps_required} | "
                     f"{v.passed_reps}/{len(v.sessions)} | {rerun} | {v.verdict} |")
    skipped = {sid: why for b in ordered for sid, why in b.skipped.items() if sid not in infos}
    if skipped:
        lines += ["", "Not started: " + "; ".join(f"{sid} ({_cell(why)})" for sid, why in skipped.items())]
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
        lines += [f"- {head}: `{s.session_tag}` ({'PASS' if s.passed else 'FAIL'}), `{short(s.session_dir)}`"
                  for head, s in zip(heads, runs, strict=True)]
        failures = [(head, r) for head, s in zip(heads, runs, strict=True) for r in s.results if r.verdict == "fail"]
        if failures:
            lines += ["", "Failures:"]
            for head, result in failures:
                lines.append(f"- {head} `{_cell(result.name)}`: {_cell(short(result.message))}")
                lines += [f"  - {_cell(short(d))}" for d in result.details[:6]]
        warned = sorted({d for s in runs for r in s.results if r.verdict == "warn" for d in r.details})
        if warned:
            lines += ["", "Warnings (never a failure):"] + [f"- {_cell(short(d))}" for d in warned[:12]]
        problems = sorted({p for s in runs for p in s.problems})
        if problems:
            lines += ["", "Evidence problems:"] + [f"- {_cell(short(p))}" for p in problems]
    lines += ["", "## Usage", "", ("Per session, from the harness's own events (Codex `turn.completed`, Claude Code "
                                   "`result`; Claude's cost is the API-equivalent estimate of a subscription login); "
                                   "wall time from the runner's turn times."), ""]
    lines += usage_lines(counted)
    notes = [n for b in ordered for n in b.notes]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {_cell(short(n))}" for n in dict.fromkeys(notes)]
    return "\n".join(lines) + "\n"


def report_path(repo_root: Path, batches: list[BatchResult], date: str | None = None) -> Path:
    """``docs/acceptance/<date>-<harness>-<version>.md`` (date of the first batch unless given)."""
    first = min(batches, key=lambda b: b.started_at)
    day = date or first.started_at.strftime("%Y-%m-%d")
    return repo_root / REPORT_DIR / f"{day}-{first.harness}-{first.harness_version}.md"


def write_report(batches: list[BatchResult], path: Path, *, date: str | None = None, shorten: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(batches, date=date, shorten=shorten))
    return path
