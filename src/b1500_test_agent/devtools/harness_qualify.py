"""``uv run b1500 dev harness qualify`` (v2.1 plan §2.3): the maintainer's cost ladder for one harness version.

The operator never pays for a check: ``b1500 update`` installs only versions this command qualified. Per harness
(``--harness``, else every installed one), on the installed version or, after installing it, on ``--candidate
VERSION|latest`` (same installer and guard as ``update``: a human terminal, no agent session):

- **T0** (free): the operator's checks of ``update`` step 7, one by one (``update.operator_checks``; every action is a
  FAIL except the Codex user-config bypass default, which the runner overrides on every turn: a WARN; unreadable
  output is a WARN); the install method (D-11); every flag of the runner's command lines in the harness's
  ``--help``, derived from the argv builders of ``harnesses.py`` (no hand list); the offline harness tests
  (``tests/adapters/test_harness*.py``, ``test_guard_hook.py``, ``test_mcp_smoke.py``, ``tests/acceptance -m "not
  acceptance"``). Any FAIL stops the ladder.
- **T1** (probes, 1 rep, no re-run): ``smoke`` (with its shell step), ``atv-confirm`` and, for Claude Code,
  ``atv12``; every session also carries the harness contract (``contract.py``: structural gaps FAIL, vocabulary drift
  and the accepted residual WARN).
- **T2** (canary, 1 rep, no re-run; a ★ 1-rep is a detector, not a §8.2 verdict): S4, S5, S16.
- **T3** (``--escalate`` [``--max-sessions N``]): the scenarios mapped to the failed or at-risk surface (§2.6) with
  the §8.2 reps and thresholds. A T2 failure whose scenarios all pass T3 is cleared (T2 detects, T3 decides); T0 and
  T1 failures stay failures.

Every tier stops at the first login/API/network event (the runner's infra watcher, owner rule OD21-4 = a): no
further tier, harness or install runs, exit 3.

Outcomes: PASS of the full ladder (T0-T2) writes ``docs/acceptance/<date>-<harness>-<version>-qualify.md``, bumps
``config/harness/validated.yaml`` when the version differs (the maintainer commits both) and, with ``--pin``, the
sanitized T1 sessions as ``tests/fixtures/transcripts/<harness>-<version>/``. FAIL leaves ``validated.yaml`` as it
is, names the failed checks, their surfaces and the T3 set, and puts a candidate back to the validated version.
``--up-to 0|1`` runs a partial ladder (report under ``work/harness/``, never a bump). ``--windows`` (the lab PC,
OD21-3 = a) runs T0 + T1 + S16 on the installed, validated version, writes no bump and records the qualification in
``<state>/harness/windows.json`` (``update`` notes while it is missing) with its report under ``work/harness/``.
Exit codes: 0 PASS, 1 FAIL (or nothing to qualify), 2 refused, 3 infra stop.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field

from b1500_test_agent.devtools import harness_versions, update
from b1500_test_agent.devtools.acceptance import harnesses, runner
from b1500_test_agent.devtools.acceptance.contract import Surface, check_contract
from b1500_test_agent.devtools.acceptance.evidence import DATA_DIR, SESSION_FILE, TRANSCRIPTS_DIR, load_evidence
from b1500_test_agent.devtools.acceptance.graders import SessionGrade
from b1500_test_agent.devtools.acceptance.report import scenario_verdict
from b1500_test_agent.devtools.acceptance.scenario import find_scenario, load_scenario, scenario_files
from b1500_test_agent.devtools.acceptance.transcripts import Usage, sanitize_lines
from b1500_test_agent.devtools.harness_versions import LABELS, HarnessName, Installed

TierName = Literal["T0", "T1", "T2", "T3"]
TierVerdict = Literal["PASS", "FAIL", "INFRA_STOP"]
Verdict = Literal["PASS", "FAIL", "INFRA_STOP", "SKIPPED"]
CheckVerdict = Literal["pass", "warn", "fail"]

T1_PROBES: Final[dict[HarnessName, tuple[str, ...]]] = {"codex": ("smoke", "atv-confirm"),
                                                        "claude": ("smoke", "atv-confirm", "atv12")}
T2_CANARY: Final = ("S4", "S5", "S16")
WINDOWS_CANARY: Final = ("S16",)
ESCALATION: Final[dict[Surface, tuple[str, ...]]] = {
    "format": (),
    "approval": ("S4", "S11", "S12", "S15"),
    "hook": ("S5", "S6", "S16", "S17", "S18"),
    "lifecycle": ("S14", "S15"),
    "instructions": ("S2", "S3", "S5", "S6", "S8", "S9", "S18"),
}
"""Plan §2.6: the scenarios that cover a surface; ``unclear`` (or several surfaces) = every ★ scenario of the suite."""
SCENARIO_SURFACE: Final[dict[str, Surface]] = {"smoke": "unclear", "atv-confirm": "approval", "atv12": "approval",
                                               "S4": "approval", "S5": "instructions", "S16": "hook"}
"""The surface a failing T1/T2 session points at when its failure is not a harness-contract gap."""
OFFLINE_TESTS: Final = ("tests/adapters/test_harness*.py", "tests/adapters/test_guard_hook.py",
                        "tests/adapters/test_mcp_smoke.py", "tests/acceptance")
TESTS_TIMEOUT_S: Final = 1800.0
HELP_TIMEOUT_S: Final = 60.0
REPORT_DIR: Final = "docs/acceptance"
WORK_DIR: Final = "work/harness"
PIN_DIR: Final = "tests/fixtures/transcripts"
CHECKLIST: Final[dict[HarnessName, tuple[str, ...]]] = {
    "codex": (("Step 8.2 (deployment-windows.md): `codex doctor --summary` in the clone shows the workspace-write "
               "sandbox row and an approval other than Never"),
              "Step 8.5, ATV-11: Codex's approval prompt for `run_confirmed_plan` shows the `summary` argument"),
    "claude": ("Step 9.4, ATV-8: `/hooks` lists the PreToolUse hook `scripts/hooks/b1500_guard.py`",
               ("Step 9.5, ATV-7/ATV-11: the `run_confirmed_plan` prompt appears in the default mode and shows the "
                "`summary`")),
}
"""Interactive-only facts (plan §1.1 row 13): not testable headless; the report lists them for the human."""


class QualifyRefused(RuntimeError):
    """The command cannot run as asked (agent session for an install, conflicting options)."""


class Check(BaseModel):
    """One T0 check."""

    name: str
    verdict: CheckVerdict
    detail: str
    surface: str | None = None


class SessionSummary(BaseModel):
    """One T1-T3 session as the qualify report shows it."""

    session: str
    scenario_id: str
    rep: int
    passed: bool
    failed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    surfaces: list[str] = Field(default_factory=list)
    infra: str | None = None


class TierResult(BaseModel):
    """One tier: verdict, T0 checks or sessions, batches, usage."""

    tier: TierName
    verdict: TierVerdict
    checks: list[Check] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    sessions: list[SessionSummary] = Field(default_factory=list)
    batches: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    surfaces: list[str] = Field(default_factory=list)
    """Surfaces of the failures (or, after a PASS, of the at-risk warnings)."""
    infra: str | None = None


class HarnessQualification(BaseModel):
    """The qualification of one harness version."""

    harness: HarnessName
    version: str | None = None
    method: str | None = None
    validated: str | None = None
    candidate: str | None = None
    verdict: Verdict = "SKIPPED"
    tiers: list[TierResult] = Field(default_factory=list)
    t3_set: list[str] = Field(default_factory=list)
    report: str | None = None
    bumped: bool = False
    restored: str | None = None
    pinned: str | None = None
    windows_record: str | None = None
    actions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def usage(self) -> Usage:
        return sum((t.usage for t in self.tiers), Usage())


class QualifyReport(BaseModel):
    """``--json``: every harness and the exit code."""

    started_at: datetime
    repo_head: str
    harnesses: list[HarnessQualification] = Field(default_factory=list)
    exit_code: int = 1


@dataclass(frozen=True)
class QualifyOptions:
    """The command line (module docstring)."""

    harness: HarnessName | None = None
    candidate: str | None = None
    up_to: int = 2
    escalate: bool = False
    max_sessions: int | None = None
    windows: bool = False
    pin: bool = False
    timeout_s: float | None = None

    def problems(self) -> list[str]:
        found = []
        if self.up_to not in (0, 1, 2):
            found.append("--up-to is 0, 1 or 2")
        if self.max_sessions is not None and not self.escalate:
            found.append("--max-sessions caps the T3 sessions: give --escalate")
        if self.windows and (self.candidate or self.pin or self.escalate):
            found.append("--windows qualifies the installed, validated version on the lab PC: no --candidate, --pin "
                         "or --escalate there")
        if self.pin and self.up_to != 2:
            found.append("--pin needs the full ladder (T0-T2): leave out --up-to")
        if self.candidate is not None and self.candidate != "latest" and \
                not re.fullmatch(r"\d+\.\d+\.\d+([-+.][0-9A-Za-z.]+)?", self.candidate):
            found.append(f"--candidate is a version (x.y.z) or latest, not {self.candidate!r}")
        return found


BatchRunner = Callable[[list[Path], runner.RunOptions, list[str]], runner.BatchResult]
TestRunner = Callable[[Path, dict[str, str]], tuple[bool, str]]


@dataclass
class QualifyContext:
    """What ``qualify`` touches, injectable for tests: the ``update`` context (repo, environment, platform, prompts,
    commands, server smoke, doctor), the artifacts folder, the date, the batch and test runners."""

    ops: update.UpdateContext
    out_dir: Path
    today: date
    run_batch: BatchRunner
    run_tests: TestRunner
    _tests: tuple[bool, str] | None = field(default=None, init=False)

    @property
    def repo(self) -> Path:
        return self.ops.repo

    def say(self, text: str) -> None:
        self.ops.say(text)


def default_batch_runner(say: Callable[[str], None]) -> BatchRunner:
    def run(files: list[Path], options: runner.RunOptions, notes: list[str]) -> runner.BatchResult:
        return runner.run_batch(files, options, progress=say, notes=notes)
    return run


def default_test_runner(repo: Path, environ: dict[str, str]) -> tuple[bool, str]:
    """The offline harness tests (``OFFLINE_TESTS``) with ``pytest -n auto`` when xdist is installed."""
    paths = sorted({p.relative_to(repo).as_posix() for glob in OFFLINE_TESTS for p in repo.glob(glob)})
    if not paths:
        return False, "no offline harness tests found (tests/ missing: run qualify from a full clone)"
    parallel = ["-n", "auto"] if importlib.util.find_spec("xdist") is not None else []
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not acceptance and not hardware",
            *parallel, *paths]
    try:
        result = subprocess.run(argv, cwd=repo, env=harnesses.clean_env(environ), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=TESTS_TIMEOUT_S, stdin=subprocess.DEVNULL,
                                check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"pytest could not run ({exc})"
    out = update.Output(result.returncode, result.stdout, result.stderr)
    return out.ok, f"{len(paths)} path(s): {out.last_line()}"


# -- T0 --------------------------------------------------------------------------------------------------------------


def _operator_check(found: update.OperatorCheck) -> Check:
    """An operator check as a T0 check (module docstring: every action fails except the runner-overridden Codex
    bypass default; notes warn)."""
    if found.actions and found.name == "bypass default" and found.harness == "codex":
        return Check(name=found.name, verdict="warn", detail="; ".join(found.actions) + " (not a T0 FAIL: the runner "
                     "passes -s workspace-write and sandbox_mode on every turn and fails any turn without it; `update` "
                     "makes it an action for the operator)")
    if found.actions:
        surface = {"trusted": "instructions", "claude doctor": "hook", "execpolicy": "hook",
                   "server": "lifecycle"}.get(found.name, "unclear")
        return Check(name=found.name, verdict="fail", detail="; ".join(found.actions), surface=surface)
    if found.notes:
        return Check(name=found.name, verdict="warn", detail="; ".join(found.notes))
    return Check(name=found.name, verdict="pass", detail="; ".join(found.passed) or "ok")


def runner_argvs(harness: HarnessName, repo: Path) -> list[list[str]]:
    """The runner's command lines for this harness (new turn with and without the confirm approval, a resumed turn),
    built by ``harnesses.py`` itself with throw-away paths."""
    with tempfile.TemporaryDirectory(prefix="b1500-qualify-argv-") as scratch:
        base = Path(scratch)
        argvs = []
        for resume, approve in ((None, False), (None, True), ("00000000-0000-0000-0000-000000000000", True)):
            launch = harnesses.TurnLaunch(harness=harness, repo=repo, session_dir=base, config_dir=base / "config",
                                          data_dir=base / "data", tag="qualify-argv", turn=2 if resume else 1,
                                          prompt="probe", approve_confirm_tool=approve, resume_id=resume)
            argvs.append(harnesses.turn_argv(launch, harness)[0])
        return argvs


def runner_flags(harness: HarnessName, repo: Path) -> dict[tuple[str, ...], list[str]]:
    """Every flag of the runner's command lines, by subcommand path (``("exec",)``, ``("exec", "resume")``, ``()``)."""
    found: dict[tuple[str, ...], list[str]] = {}
    for argv in runner_argvs(harness, repo):
        words = argv[1:]
        path = tuple(next((words[:i] for i, w in enumerate(words) if w.startswith("-")), words))
        flags = found.setdefault(path, [])
        for word in words:
            if word.startswith("-") and word != harnesses.STDIN_PROMPT and word not in flags:
                flags.append(word)
    return found


def flags_check(ctx: QualifyContext, harness: HarnessName, exe: str) -> Check:
    """Every runner flag appears in the ``--help`` of its (sub)command (plan §1.1 row 1)."""
    missing, read = [], []
    try:
        flags = runner_flags(harness, ctx.repo)
    except harnesses.HarnessError as exc:
        return Check(name="runner flags", verdict="fail", detail=str(exc), surface="format")
    for path, wanted in flags.items():
        out = ctx.ops.run([exe, *path, "--help"], timeout=HELP_TIMEOUT_S)
        command = " ".join([harness, *path, "--help"])
        if not out.ok or not out.text.strip():
            missing.append(f"`{command}` failed ({out.last_line()})")
            continue
        absent = [f for f in wanted if re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", out.text) is None]
        missing += [f"{f} (not in `{command}`)" for f in absent]
        read.append(f"{command}: {len(wanted)}")
    if missing:
        return Check(name="runner flags", verdict="fail", detail="; ".join(missing), surface="format")
    return Check(name="runner flags", verdict="pass", detail="every flag documented (" + "; ".join(read) + ")")


def tests_check(ctx: QualifyContext) -> Check:
    if ctx._tests is None:
        ctx.say("T0: offline harness tests (once per run)")
        ctx._tests = ctx.run_tests(ctx.repo, dict(ctx.ops.environ))
    ok, detail = ctx._tests
    return Check(name="offline harness tests", verdict="pass" if ok else "fail", detail=detail,
                 surface=None if ok else "unclear")


def tier0(ctx: QualifyContext, harness: HarnessName, found: Installed, backend: str) -> TierResult:
    want = harness_versions.INSTALL_METHOD[harness]
    checks = [Check(name="install method", verdict="pass" if found.method == want else "fail",
                    detail=f"{found.method} at {found.executable}" + ("" if found.method == want else
                                                                      f" (one install method per harness: {want})"),
                    surface=None if found.method == want else "unclear")]
    checks += [_operator_check(c) for c in update.operator_checks(ctx.ops, [harness], backend=backend)]
    checks.append(flags_check(ctx, harness, found.executable))
    checks.append(tests_check(ctx))
    failed = [c for c in checks if c.verdict == "fail"]
    return TierResult(tier="T0", verdict="FAIL" if failed else "PASS", checks=checks,
                      surfaces=sorted({c.surface for c in failed if c.surface}))


# -- T1-T3 -----------------------------------------------------------------------------------------------------------


def _summary(grade: SessionGrade) -> SessionSummary:
    folder = Path(grade.session_dir)
    surfaces: set[str] = set()
    warnings: list[str] = []
    try:
        contract = check_contract(load_evidence(folder))
        surfaces |= contract.surfaces()
        at_risk = contract.surfaces(warnings=True) - {"format"}
        warnings = [f"[{f.surface or 'residual'}] {f.text}" for f in contract.warnings]
    except Exception as exc:  # noqa: BLE001 - an unreadable session is a failed one; the grade says why
        warnings.append(f"contract not re-read: {type(exc).__name__}: {exc}")
        at_risk = set()
    failed = [r.name for r in grade.failures()]
    if [name for name in failed if name != "harness contract"]:
        surfaces.add(SCENARIO_SURFACE.get(grade.scenario_id, "unclear"))
    if grade.passed:
        surfaces = set(at_risk)
    return SessionSummary(session=folder.name, scenario_id=grade.scenario_id, rep=grade.rep, passed=grade.passed,
                          failed=failed, warnings=warnings, surfaces=sorted(surfaces),
                          infra=grade.infra_event.describe() if grade.infra_event else None)


def run_tier(ctx: QualifyContext, opts: QualifyOptions, harness: HarnessName, tier: TierName,
             scenario_ids: list[str]) -> TierResult:
    """One live tier through the acceptance runner (infra watcher on)."""
    files = [find_scenario(ctx.repo, sid) for sid in scenario_ids]
    escalated = tier == "T3"
    options = runner.RunOptions(harness=harness, repo_root=ctx.repo, out_dir=ctx.out_dir,
                                reps=None if escalated else 1, rerun_failed_functional=escalated,
                                max_sessions=opts.max_sessions if escalated else None, timeout_s=opts.timeout_s)
    ctx.say(f"{tier}: {', '.join(scenario_ids)} ({LABELS[harness]})")
    batch = ctx.run_batch(files, options, [f"dev harness qualify {tier} ({LABELS[harness]})"])
    sessions = [_summary(g) for g in batch.sessions]
    result = TierResult(tier=tier, verdict="PASS", scenarios=list(scenario_ids), sessions=sessions,
                        batches=[batch.batch_dir], usage=sum((g.usage for g in batch.sessions), Usage()))
    if batch.infra_stop is not None:
        result.verdict, result.infra = "INFRA_STOP", batch.infra_stop.describe()
        return result
    if escalated:
        verdicts = [scenario_verdict(sid, info, [g for g in batch.sessions if g.scenario_id == sid])
                    for sid, info in batch.scenarios.items()]
        failed = [v.scenario_id for v in verdicts if v.verdict != "PASS"] + list(batch.skipped)
    else:
        failed = [s.scenario_id for s in sessions if not s.passed]
        missing = [sid for sid in scenario_ids if sid not in {s.scenario_id for s in sessions}]
        failed += missing
    result.verdict = "FAIL" if failed else "PASS"
    picked = [s for s in sessions if not s.passed] if failed else sessions
    result.surfaces = sorted({x for s in picked for x in s.surfaces})
    return result


def _order(sid: str) -> tuple[int, str]:
    return (int(sid[1:]), sid) if sid[1:].isdigit() else (999, sid)


def t3_set(repo: Path, surfaces: set[str]) -> list[str]:
    """Plan §2.6: the scenarios of the one failed or at-risk surface; ``unclear`` or several surfaces: every ★
    scenario of the suite; the event format alone: none (fix the parser, re-grade)."""
    known = {s for s in surfaces if s != "format"}
    if not known:
        return []
    if "unclear" in known or len(known) > 1:
        scenarios = [load_scenario(p) for p in scenario_files(repo, probes=False)]
        return sorted({s.id for s in scenarios if s.safety}, key=_order)
    (surface,) = known
    return sorted(ESCALATION[surface], key=_order)  # type: ignore[index]


# -- install, restore, bump, pin, record ------------------------------------------------------------------------------


def _guard(ctx: QualifyContext) -> None:
    markers = update.agent_markers(ctx.ops.environ)
    if markers or not ctx.ops.interactive:
        why = f"agent session marker {', '.join(markers)}" if markers else "no interactive terminal"
        raise QualifyRefused(f"installing a harness needs a human terminal ({why}): run `uv run b1500 dev harness "
                             "qualify --candidate ...` yourself in a terminal window, not through the agent")


def install(ctx: QualifyContext, harness: HarnessName, version: str, found: Installed | None) -> Installed | None:
    """The one installer of the harness (``update``'s), then the CLI read again; ``None`` when it did not take."""
    label = LABELS[harness]
    tool = ctx.ops.which("npm") if harness == "codex" else (found.executable if found else ctx.ops.which("claude"))
    if tool is None:
        return None
    command = harness_versions.installer_command(harness, version)
    ctx.say(f"installing {label} {version}: {command}")
    out = ctx.ops.run(harness_versions.installer_argv(harness, version, tool), timeout=update.INSTALL_TIMEOUT_S,
                      terminal=True)
    again = harness_versions.find_installed(harness, which=ctx.ops.which, run=ctx.ops.runner())
    if not out.ok or again is None or again.version is None:
        return None
    return again if version == "latest" or again.version == version else None


def report_path(ctx: QualifyContext, opts: QualifyOptions, q: HarnessQualification) -> Path:
    """``docs/acceptance/`` for a full ladder with a verdict (the maintainer commits it); ``work/harness/`` for the
    lab PC, a partial ladder or an infra stop."""
    stem = f"{ctx.today.isoformat()}-{q.harness}-{q.version}"
    if opts.windows:
        return ctx.repo / WORK_DIR / f"{stem}-windows.md"
    if q.verdict == "INFRA_STOP":
        return ctx.repo / WORK_DIR / f"{stem}-qualify-infra-stop.md"
    if opts.up_to < 2:
        return ctx.repo / WORK_DIR / f"{stem}-qualify-t{opts.up_to}.md"
    return ctx.repo / REPORT_DIR / f"{stem}-qualify.md"


ROLLOUT_KEEP: Final = frozenset({"custom_tool_call", "function_call", "local_shell_call"})
"""Rollout records a pin keeps besides ``turn_context`` (the graded tool inputs; the instructions and messages are
left out, as in the 0.167.1 pin)."""


def _pin_text(rel: str, text: str, pairs: dict[str, str]) -> str:
    lines = text.splitlines()
    if rel.endswith("codex-rollout.jsonl"):
        kept = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload") if isinstance(record, dict) else None
            if record.get("type") == "turn_context" or (isinstance(payload, dict)
                                                        and payload.get("type") in ROLLOUT_KEEP):
                kept.append(line)
        lines = kept
    return "\n".join(sanitize_lines(lines, pairs)) + "\n"


def pin_sessions(ctx: QualifyContext, q: HarnessQualification) -> Path:
    """The T1 sessions as regradable fixtures (``<harness>-<version>/<probe>/``), sanitized (plan D-9)."""
    target = ctx.repo / PIN_DIR / f"{q.harness}-{q.version}"
    if target.exists():
        shutil.rmtree(target)
    t1 = next(t for t in q.tiers if t.tier == "T1")
    temp = Path(tempfile.gettempdir())
    replacements = {str(ctx.repo): "<REPO>", ctx.repo.as_posix(): "<REPO>", str(ctx.out_dir): "<OUT>",
                    str(ctx.ops.home): "<HOME>", str(temp): "<TMP>", str(temp.resolve()): "<TMP>"}
    files: dict[str, str] = {}
    for batch in t1.batches:
        for session in sorted(Path(batch).glob(f"*/{SESSION_FILE}")):
            folder, probe = session.parent, session.parent.name.rsplit("-r", 1)[0]
            pairs = {**replacements, str(folder): "<SESSION>", folder.as_posix(): "<SESSION>"}
            wanted = [SESSION_FILE, "scenario.yaml", "config/policy.yaml", "config/settings.yaml"]
            wanted += [p.relative_to(folder).as_posix() for p in (folder / TRANSCRIPTS_DIR).glob("*")]
            wanted += [p.relative_to(folder).as_posix() for p in (folder / DATA_DIR / "state").rglob("*.json*")]
            for rel in wanted:
                source = folder / rel
                if not source.is_file():
                    continue
                dest = target / probe / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(_pin_text(rel, source.read_text(encoding="utf-8", errors="replace"), pairs),
                                encoding="utf-8", newline="\n")
                files[f"{probe}/{rel}"] = "sanitized copy" + (" (turn_context and tool calls only)"
                                                              if rel.endswith("codex-rollout.jsonl") else "")
    meta = {"harness": q.harness, "version": q.version, "captured": ctx.today.isoformat(),
            "how": "uv run b1500 dev harness qualify --pin: the T1 probe sessions (regrade a copy with "
                   "`uv run b1500 dev acceptance grade` after replacing <REPO> and <SESSION>)",
            "sanitized": "paths replaced by <REPO>, <SESSION>, <OUT>, <HOME>, <TMP>; Claude init without the "
                         "user's commands, plugins and skills; signatures blanked; rate-limit events dropped",
            "files": files}
    (target / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                      newline="\n")
    return target


# -- one harness -----------------------------------------------------------------------------------------------------


def _climb(ctx: QualifyContext, opts: QualifyOptions, q: HarnessQualification, found: Installed, backend: str) -> None:
    """T0 → T1 → T2 (→ T3) for one installed version; sets ``q.verdict`` and ``q.tiers``."""
    t0 = tier0(ctx, q.harness, found, backend)
    q.tiers.append(t0)
    ctx.say(f"T0 {t0.verdict} ({LABELS[q.harness]} {q.version})")
    if t0.verdict == "FAIL" or opts.up_to == 0:
        q.verdict = "FAIL" if t0.verdict == "FAIL" else "PASS"
        return
    t1 = run_tier(ctx, opts, q.harness, "T1", list(T1_PROBES[q.harness]))
    q.tiers.append(t1)
    t2 = None
    if t1.verdict == "PASS" and opts.up_to == 2:
        t2 = run_tier(ctx, opts, q.harness, "T2", list(WINDOWS_CANARY if opts.windows else T2_CANARY))
        q.tiers.append(t2)
    live = [t for t in (t1, t2) if t is not None]
    if any(t.verdict == "INFRA_STOP" for t in live):
        q.verdict = "INFRA_STOP"
        return
    surfaces = {s for t in live for s in t.surfaces}
    failed = [t for t in live if t.verdict == "FAIL"]
    q.verdict = "FAIL" if failed else "PASS"
    if opts.escalate and surfaces:
        q.t3_set = t3_set(ctx.repo, surfaces)
        if not q.t3_set:
            q.notes.append("the failed or at-risk surface is the event format only: fix the parser, then `uv run "
                           "b1500 dev acceptance grade` the T1/T2 batches (no T3 sessions)")
            return
        t3 = run_tier(ctx, opts, q.harness, "T3", q.t3_set)
        q.tiers.append(t3)
        if t3.verdict == "INFRA_STOP":
            q.verdict = "INFRA_STOP"
        elif t3.verdict == "FAIL":
            q.verdict = "FAIL"
        elif failed == [t2] and t2 is not None and {s.scenario_id for s in t2.sessions if not s.passed} <= \
                set(q.t3_set):
            q.verdict = "PASS"
            q.notes.append("T2 failure cleared by T3: every failed canary scenario met the §8.2 threshold in T3")
    elif surfaces:
        q.t3_set = t3_set(ctx.repo, surfaces)
        if q.verdict == "PASS" and q.t3_set:
            q.notes.append(f"at-risk surface(s) {', '.join(sorted(surfaces))} (harness-contract WARN): `--escalate` "
                           f"would run {', '.join(q.t3_set)}")


def qualify_harness(ctx: QualifyContext, opts: QualifyOptions, harness: HarnessName,
                    validated: harness_versions.ValidatedHarnesses, backend: str, state_dir: Path) \
        -> HarnessQualification:
    label, want = LABELS[harness], validated.get(harness)
    q = HarnessQualification(harness=harness, validated=want.version, candidate=opts.candidate)
    found = harness_versions.find_installed(harness, which=ctx.ops.which, run=ctx.ops.runner())
    if opts.candidate is not None:
        installed = install(ctx, harness, opts.candidate, found)
        if installed is None:
            q.verdict = "FAIL"
            now = harness_versions.find_installed(harness, which=ctx.ops.which, run=ctx.ops.runner())
            q.actions.append(f"{label} {opts.candidate} was not installed (`{harness} --version` now: "
                             f"{now.version if now else 'none'}): check the installer's output; `uv run b1500 update` "
                             f"brings back the validated {want.version}")
            return q
        found = installed
    if found is None:
        q.notes.append(f"{label} is not installed: nothing to qualify")
        return q
    q.version, q.method = found.version, found.method
    if found.version is None:
        q.verdict = "FAIL"
        q.actions.append(f"`{harness} --version` is unreadable ({found.raw!r})")
        return q
    if opts.windows and found.version != want.version:
        q.verdict = "FAIL"
        q.actions.append(f"{label} {found.version} is installed, {want.version} is validated: run `uv run b1500 "
                         "update` first, then qualify the validated version here")
        return q
    _climb(ctx, opts, q, found, backend)
    _finish(ctx, opts, q, want, state_dir)
    return q


def _finish(ctx: QualifyContext, opts: QualifyOptions, q: HarnessQualification,
            want: harness_versions.ValidatedVersion, state_dir: Path) -> None:
    """Report, then bump / pin / record on PASS, restore a candidate on FAIL; infra stops change nothing."""
    assert q.version is not None
    label = LABELS[q.harness]
    path = report_path(ctx, opts, q)
    q.report = path.relative_to(ctx.repo).as_posix()
    full = opts.up_to == 2 and not opts.windows
    if q.verdict == "PASS" and full:
        if q.version != want.version:
            entry = harness_versions.ValidatedVersion(version=q.version, install=harness_versions.INSTALL_METHOD[
                q.harness], validated=ctx.today, report=q.report)
            harness_versions.write_validated(ctx.repo, q.harness, entry)
            q.bumped = True
            q.actions.append(f"commit {harness_versions.VALIDATED_FILE} and {q.report}: operators get {label} "
                             f"{q.version} with their next `uv run b1500 update`")
        else:
            q.notes.append(f"{label} {q.version} is already the validated version: {harness_versions.VALIDATED_FILE} "
                           "unchanged")
        if opts.pin:
            q.pinned = pin_sessions(ctx, q).relative_to(ctx.repo).as_posix()
            q.actions.append(f"review and commit the pinned transcripts {q.pinned}/")
    elif q.verdict == "PASS" and opts.windows:
        record = harness_versions.QualifiedVersion(version=q.version, qualified=ctx.today.isoformat(),
                                                   report=q.report)
        harness_versions.record_windows_qualification(state_dir, q.harness, record)
        q.windows_record = harness_versions.windows_qualification_path(state_dir).as_posix()
    elif q.verdict == "PASS":
        q.notes.append(f"partial ladder (--up-to {opts.up_to}): nothing bumped")
    elif q.verdict == "FAIL" and q.candidate is not None:
        ctx.say(f"FAIL: putting {label} back to the validated {want.version}")
        found = harness_versions.find_installed(q.harness, which=ctx.ops.which, run=ctx.ops.runner())
        back = install(ctx, q.harness, want.version, found)
        q.restored = want.version if back is not None else None
        if back is None:
            q.actions.append(f"{label} is still on the candidate {q.version}: put it back yourself with "
                             f"`{harness_versions.installer_command(q.harness, want.version)}`")
    elif q.verdict == "INFRA_STOP" and q.candidate is not None:
        q.actions.append(f"{label} is still on the candidate {q.version} (no install after an infra stop): when the "
                         f"owner says so, `{harness_versions.installer_command(q.harness, want.version)}` puts the "
                         f"validated {want.version} back")
    if q.verdict == "FAIL":
        failed = [c.name for t in q.tiers for c in t.checks if c.verdict == "fail"]
        failed += [f"{s.session}: {', '.join(s.failed) or 'failed'}" for t in q.tiers for s in t.sessions
                   if not s.passed]
        q.actions.append(f"{label} {q.version} is not qualified ({'; '.join(failed) or 'see the report'}); "
                         f"{harness_versions.VALIDATED_FILE} is unchanged" + (
                             f"; T3 set for the surface: {', '.join(q.t3_set)}" if q.t3_set else ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(ctx, opts, q), encoding="utf-8", newline="\n")


# -- report ----------------------------------------------------------------------------------------------------------


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def render(ctx: QualifyContext, opts: QualifyOptions, q: HarnessQualification) -> str:
    """The qualify report (Markdown)."""
    usage = q.usage
    out_text = ctx.out_dir.as_posix()
    cost = "" if usage.cost_usd is None else f", {usage.cost_usd:.2f} USD API-equivalent"
    kind = "Windows qualification (lab PC)" if opts.windows else "qualification"
    candidate = f"; candidate `{q.candidate}`" if q.candidate else ""
    ladder = " → ".join(f"{t.tier} {t.verdict}" for t in q.tiers) or "not run"
    partial = f" (--up-to {opts.up_to})" if opts.up_to < 2 else ""
    bumped = f"; `{harness_versions.VALIDATED_FILE}` bumped to {q.version}" if q.bumped else ""
    restored = f"; restored to {q.restored}" if q.restored else ""
    lines = [f"# Harness {kind}: {q.harness} {q.version} ({ctx.today.isoformat()})", "",
             f"- Harness: `{q.harness}` {q.version} ({q.method}); validated before: {q.validated}{candidate}",
             f"- Repository commit: `{runner.repo_head(ctx.repo)}` ({runner.repo_commit(ctx.repo)})",
             f"- Ladder: {ladder}{partial}",
             f"- Result: **{q.verdict}**{bumped}{restored}",
             (f"- Usage: {usage.turns} turns, {usage.input_tokens:,} input tokens ({usage.cached_input_tokens:,} "
              f"cached), {usage.output_tokens:,} output{cost}, {usage.wall_s / 60:,.1f} min")]
    lines += [f"- Infra stop (owner rule: stop, no retries): {_cell(t.infra)}" for t in q.tiers if t.infra]
    for tier in q.tiers:
        lines += ["", f"## {tier.tier}: {tier.verdict}", ""]
        if tier.checks:
            lines += ["| Check | Verdict | Detail |", "|---|---|---|"]
            lines += [f"| {c.name} | {c.verdict} | {_cell(c.detail)} |" for c in tier.checks]
            continue
        batches = ", ".join(f"`{b.replace(out_text, '<out>')}`" for b in tier.batches)
        lines += [f"Scenarios: {', '.join(tier.scenarios)}; batches: {batches}", "",
                  "| Session | Verdict | Failed graders | Surfaces |", "|---|---|---|---|"]
        lines += [f"| {s.session} | {'PASS' if s.passed else 'FAIL'} | {_cell(', '.join(s.failed)) or '—'} | "
                  f"{', '.join(s.surfaces) or '—'} |" for s in tier.sessions]
    warnings = sorted({w for t in q.tiers for s in t.sessions for w in s.warnings})
    warned_checks = [f"T0 {c.name}: {c.detail}" for t in q.tiers for c in t.checks if c.verdict == "warn"]
    if warnings or warned_checks:
        lines += ["", "## Warnings (never a FAIL; harness contract §2.5, accepted residual OD21-5 = c)", ""]
        lines += [f"- {_cell(w)}" for w in [*warned_checks, *warnings]]
    if q.t3_set:
        lines += ["", f"T3 set for the failed or at-risk surface (plan §2.6): {', '.join(q.t3_set)}"]
    lines += ["", "## Interactive checks for the human (not testable headless, plan §1.1 row 13)", ""]
    lines += [f"- [ ] {item}" for item in CHECKLIST[q.harness]]
    if q.actions or q.notes:
        lines += ["", "## Next", ""] + [f"- {_cell(a)}" for a in q.actions] + [f"- note: {_cell(n)}" for n in q.notes]
    return "\n".join(lines) + "\n"


# -- run -------------------------------------------------------------------------------------------------------------


def run_qualify(ctx: QualifyContext, opts: QualifyOptions) -> QualifyReport:
    """Qualify each selected harness (module docstring); raises ``QualifyRefused`` before anything runs."""
    problems = opts.problems()
    if problems:
        raise QualifyRefused("; ".join(problems))
    if opts.windows and not ctx.ops.windows:
        raise QualifyRefused("--windows records the lab PC's qualification: run it on the Windows lab PC")
    if opts.candidate is not None:
        if opts.harness is None:
            raise QualifyRefused("--candidate installs one harness: give --harness codex|claude")
        _guard(ctx)
    try:
        validated = harness_versions.load_validated(ctx.repo)
    except harness_versions.ValidatedError as exc:
        raise QualifyRefused(str(exc)) from exc
    _lab, state_dir, backend = update.station_facts(ctx.ops)
    report = QualifyReport(started_at=datetime.now(UTC), repo_head=runner.repo_head(ctx.repo))
    names: list[HarnessName] = [opts.harness] if opts.harness else list(harness_versions.HARNESSES)
    for name in names:
        q = qualify_harness(ctx, opts, name, validated, backend, state_dir)
        if q.verdict == "SKIPPED" and opts.harness is not None:
            q.verdict = "FAIL"
            q.actions.append(f"{LABELS[name]} is not installed (`uv run b1500 update` or deployment Step 1.6)")
        report.harnesses.append(q)
        ctx.say(f"{LABELS[name]}: {q.verdict}" + (f" (report {q.report})" if q.report else ""))
        if q.verdict == "INFRA_STOP":
            ctx.say("INFRA STOP: nothing more runs (owner rule: stop, no retries; tell the owner and wait)")
            break
    verdicts = [q.verdict for q in report.harnesses]
    if "INFRA_STOP" in verdicts:
        report.exit_code = 3
    elif "FAIL" in verdicts or not any(v == "PASS" for v in verdicts):
        report.exit_code = 1
    else:
        report.exit_code = 0
    return report


def format_summary(report: QualifyReport) -> str:
    """The terminal summary: per harness the ladder, the verdict, the report and what to do next."""
    lines = []
    for q in report.harnesses:
        ladder = " → ".join(f"{t.tier} {t.verdict}" for t in q.tiers) or "not run"
        lines.append(f"{LABELS[q.harness]} {q.version or ''}: {q.verdict} ({ladder})".replace("  ", " "))
        for tier in q.tiers:
            lines += [f"  {tier.tier} {c.verdict:4} {c.name}: {c.detail}" for c in tier.checks if c.verdict != "pass"]
            lines += [f"  {tier.tier} FAIL {s.session}: {', '.join(s.failed)}" for s in tier.sessions if not s.passed]
        lines += [f"  report: {q.report}"] if q.report else []
        lines += [f"  do: {a}" for a in q.actions] + [f"  note: {n}" for n in q.notes]
    return "\n".join(lines)
