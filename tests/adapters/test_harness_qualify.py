"""``uv run b1500 dev harness qualify`` (v2.1 plan §2.3, WP21.2 AC): the ladder, the candidate install with its
guard, the restore on FAIL, the bump, the report, ``--windows``, ``--pin`` and ``--escalate``.

The station is ``stations.py``'s (fake ``git``/``uv``/``npm``/``codex``/``claude`` on ``PATH``, every call logged;
no installer, network or harness runs). T0 runs for real over the fakes (operator checks, runner flags against the
fakes' ``--help``); the offline-tests runner and the batch runner are injected. The injected batches are made of real
session folders (copies of the WP11.5 sessions in ``tests/fixtures/transcripts/contract/``), so the harness contract
is re-read as in a live run. ``test_ladder_end_to_end_with_the_scripted_agent`` climbs T0-T2 through the real runner
with ``fake_agent.py`` and pins the T1 sessions.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools import harness_qualify, harness_versions
from b1500_test_agent.devtools.acceptance import harnesses, runner
from b1500_test_agent.devtools.acceptance.graders import GraderResult, SessionGrade, grade_session
from b1500_test_agent.devtools.acceptance.infra import InfraEvent, InfraStop
from b1500_test_agent.devtools.acceptance.scenario import load_scenario
from b1500_test_agent.devtools.acceptance.transcripts import Usage
from b1500_test_agent.devtools.harness_qualify import QualifyContext, QualifyOptions, QualifyRefused
from tests.acceptance.helpers import FAKE_AGENT, FIXTURES, add_manual_corpus
from tests.adapters.stations import REPO_ROOT, Station, make_station, wrapper

TODAY = date(2026, 11, 27)
CONTRACT = FIXTURES / "contract"
SESSION_FIXTURE = {"claude": "claude-2.1.328-S16", "codex": "codex-0.170.0-S2"}
Outcome = str  # "pass" | "fail" | "infra"


class FakeBatches:
    """The injected batch runner: every scenario gets real session folders (contract fixtures) and the outcome the
    test planned (default pass); records what was run."""

    def __init__(self, tmp: Path) -> None:
        self.tmp, self.calls = tmp, []
        self.plan: dict[str, Outcome | list[Outcome]] = {}

    def outcome(self, sid: str, rep: int) -> Outcome:
        planned = self.plan.get(sid, "pass")
        return planned[min(rep, len(planned)) - 1] if isinstance(planned, list) else planned

    def __call__(self, files: list[Path], options: runner.RunOptions, notes: list[str]) -> runner.BatchResult:
        scenarios = [load_scenario(f) for f in files]
        self.calls.append((options.harness, [s.id for s in scenarios], options))
        batch_dir = options.out_dir / f"batch-{len(self.calls)}-{options.harness}"
        batch = runner.BatchResult(batch_id=batch_dir.name, harness=options.harness, harness_version="fake",
                                   repo_root=options.repo_root.as_posix(), repo_commit="abc", runner_version="v",
                                   started_at=datetime(2026, 11, 27, tzinfo=UTC), batch_dir=batch_dir.as_posix(),
                                   notes=list(notes))
        for scenario in scenarios:
            if batch.infra_stop is not None:
                batch.skipped[scenario.id] = "not started: the batch stopped at an infra event"
                continue
            reps = options.reps or scenario.default_reps
            batch.scenarios[scenario.id] = {"title": scenario.title, "safety": scenario.safety, "reps": reps,
                                            "required_reps": scenario.default_reps}
            for rep in range(1, reps + 1):
                grade = self._session(batch_dir, scenario.id, rep, options.harness, self.outcome(scenario.id, rep))
                batch.sessions.append(grade)
                if grade.infra_event is not None:
                    batch.infra_stop = InfraStop(session=f"{scenario.id}-r{rep}", scenario_id=scenario.id, rep=rep,
                                                 event=grade.infra_event)
                    break
        return batch

    def _session(self, batch_dir: Path, sid: str, rep: int, harness: str, outcome: Outcome) -> SessionGrade:
        folder = batch_dir / f"{sid}-r{rep}"
        shutil.copytree(CONTRACT / SESSION_FIXTURE[harness], folder)
        for path in folder.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace("<REPO>", REPO_ROOT.as_posix()).replace("<SESSION>", folder.as_posix()),
                                encoding="utf-8")
        event = InfraEvent(kind="turn_failed", stream="stdout", line='{"type":"turn.failed"}', turn=1) \
            if outcome == "infra" else None
        verdict = "pass" if outcome == "pass" else "fail"
        results = [GraderResult(name="session ok", type="session", verdict=verdict, message="m"),
                   GraderResult(name="t1: reached the server", type="tool_calls", verdict=verdict, message="m")]
        return SessionGrade(scenario_id=sid, rep=rep, harness=harness, harness_version="fake", session_tag="t",
                            session_dir=folder.as_posix(), passed=outcome == "pass", results=results,
                            usage=Usage(turns=1, input_tokens=1000, cached_input_tokens=900, output_tokens=10,
                                        cost_usd=0.25 if harness == "claude" else None, wall_s=30),
                            infra_event=event)


@pytest.fixture
def station(tmp_path: Path) -> Station:
    s = make_station(tmp_path)
    for rel in ("tests/acceptance/probes", "tests/acceptance/scenarios", ".agents/skills"):
        shutil.copytree(REPO_ROOT / rel, s.repo / rel)
    return s


def qualify(station: Station, *, tests_ok: bool = True, interactive: bool = False, on_windows: bool | None = None,
            environ: dict[str, str] | None = None, batches: FakeBatches | None = None,
            **options: Any) -> tuple[harness_qualify.QualifyReport, FakeBatches, list[Any]]:
    """``run_qualify`` over the station; ``on_windows`` injects the platform (default: Windows when ``--windows``)."""
    batches = batches or FakeBatches(station.tmp)
    test_runs: list[Any] = []

    def run_tests(repo: Path, env: dict[str, str]) -> tuple[bool, str]:
        test_runs.append(repo)
        return tests_ok, "6 path(s): 428 passed in 65.0s" if tests_ok else "6 path(s): 1 failed, 427 passed"

    windows = bool(options.get("windows")) if on_windows is None else on_windows
    ctx = QualifyContext(ops=station.ctx(interactive=interactive, windows=windows, environ=environ),
                         out_dir=station.tmp / "out", today=TODAY, run_batch=batches, run_tests=run_tests)
    return harness_qualify.run_qualify(ctx, QualifyOptions(**options)), batches, test_runs


def one(report: harness_qualify.QualifyReport, name: str) -> harness_qualify.HarnessQualification:
    return next(q for q in report.harnesses if q.harness == name)


def check(q: harness_qualify.HarnessQualification, name: str) -> harness_qualify.Check:
    return next(c for c in q.tiers[0].checks if c.name == name)


def validated(station: Station) -> harness_versions.ValidatedHarnesses:
    return harness_versions.load_validated(station.repo)


# -- T0 --------------------------------------------------------------------------------------------------------------


def test_up_to_0_passes_both_harnesses_for_free(station: Station) -> None:
    before = (station.repo / harness_versions.VALIDATED_FILE).read_text(encoding="utf-8")
    report, batches, test_runs = qualify(station, up_to=0)
    assert report.exit_code == 0 and [q.verdict for q in report.harnesses] == ["PASS", "PASS"]
    assert batches.calls == [] and len(test_runs) == 1  # no session; the offline tests run once for both
    codex = one(report, "codex")
    assert [t.tier for t in codex.tiers] == ["T0"]
    assert {c.name: c.verdict for c in codex.tiers[0].checks} == {
        "install method": "pass", "signed in": "pass", "bypass default": "pass", "execpolicy": "pass",
        "trusted": "pass", "server": "pass", "doctor": "pass", "runner flags": "pass", "offline harness tests": "pass"}
    assert "claude doctor" in {c.name for c in one(report, "claude").tiers[0].checks}
    assert codex.report == "work/harness/2026-11-27-codex-0.170.0-qualify-t0.md" and not codex.bumped
    text = (station.repo / codex.report).read_text(encoding="utf-8")
    assert text.startswith("# Harness qualification: codex 0.170.0 (2026-11-27)") and "## T0: PASS" in text
    assert "- [ ] Step 8.2" in text and "partial ladder (--up-to 0): nothing bumped" in text
    assert (station.repo / harness_versions.VALIDATED_FILE).read_text(encoding="utf-8") == before
    assert not station.ran("npm") and not station.ran("claude", "install")


@pytest.mark.parametrize(("world", "name", "says"), [
    ({"codex": {"login": False}}, "signed in", "Codex is not signed in: run `codex login`"),
    ({"codex": {"execpolicy": "allow"}}, "execpolicy", "Codex does not forbid"),
    ({"codex": {"help_drop": ["--json"]}}, "runner flags", "--json (not in `codex exec --help`)"),
    ({"claude": {"doctor": "invalid"}}, "claude doctor", "Claude Code ignores parts of .claude/settings.json"),
    ({"claude": {"help_drop": ["--include-hook-events"]}}, "runner flags",
     "--include-hook-events (not in `claude --help`)"),
])
def test_t0_failures_stop_the_ladder(station: Station, world: dict[str, dict[str, Any]], name: str,
                                     says: str) -> None:
    station.set(**world)
    harness: Any = next(iter(world))
    report, batches, _ = qualify(station, harness=harness)
    q = one(report, harness)
    assert report.exit_code == 1 and q.verdict == "FAIL" and [t.tier for t in q.tiers] == ["T0"]
    assert check(q, name).verdict == "fail" and says in check(q, name).detail
    assert batches.calls == []  # T0 FAIL: nothing costs
    assert q.report == f"docs/acceptance/2026-11-27-{harness}-{q.version}-qualify.md"
    assert validated(station).get(harness).version == q.version  # unchanged
    assert any("is not qualified" in a and "validated.yaml is unchanged" in a for a in q.actions)


def test_failing_offline_tests_and_a_foreign_install_method_fail_t0(station: Station) -> None:
    cask = station.tmp / "opt" / "homebrew" / "Caskroom" / "codex" / "0.170.0"
    wrapper(cask, "codex")
    station.environ["PATH"] = str(cask) + (";" if sys.platform == "win32" else ":") + station.environ["PATH"]
    report, _, _ = qualify(station, harness="codex", tests_ok=False, up_to=0)
    q = one(report, "codex")
    assert check(q, "install method").verdict == "fail" and "one install method per harness: npm" in \
        check(q, "install method").detail
    assert check(q, "offline harness tests").verdict == "fail"


def test_codex_bypass_default_is_a_warn_for_the_maintainer(station: Station) -> None:
    config = station.home / ".codex" / "config.toml"
    config.write_text('sandbox_mode = "danger-full-access"\napproval_policy = "never"\n'
                      + config.read_text(encoding="utf-8"), encoding="utf-8")
    report, _, _ = qualify(station, harness="codex", up_to=0)
    q = one(report, "codex")
    assert q.verdict == "PASS" and check(q, "bypass default").verdict == "warn"
    assert "the runner passes -s workspace-write" in check(q, "bypass default").detail
    text = (station.repo / q.report).read_text(encoding="utf-8")  # type: ignore[operator]
    assert "## Warnings" in text and "T0 bypass default" in text


def test_claude_bypass_default_fails(station: Station) -> None:
    (station.home / ".claude" / "settings.json").write_text('{"permissions": {"defaultMode": "bypassPermissions"}}',
                                                            encoding="utf-8")
    report, _, _ = qualify(station, harness="claude", up_to=0)
    assert check(one(report, "claude"), "bypass default").verdict == "fail"


def test_runner_flags_come_from_the_argv_builders() -> None:
    codex = harness_qualify.runner_flags("codex", REPO_ROOT)
    assert codex == {("exec",): ["--json", "-s", "-C", "-c"], ("exec", "resume"): ["--json", "-c"]}
    claude = harness_qualify.runner_flags("claude", REPO_ROOT)
    assert list(claude) == [()] and {"-p", "--include-hook-events", "--permission-prompt-tool", "--allowedTools",
                                     "--resume", "--strict-mcp-config"} <= set(claude[()])
    assert "-" not in claude[()] and "--" not in claude[()]


# -- T1, T2, bump ----------------------------------------------------------------------------------------------------


def test_the_full_ladder_runs_t1_then_t2_and_installed_validated_bumps_nothing(station: Station) -> None:
    report, batches, _ = qualify(station, harness="claude")
    q = one(report, "claude")
    assert report.exit_code == 0 and q.verdict == "PASS" and [t.tier for t in q.tiers] == ["T0", "T1", "T2"]
    assert [(h, ids) for h, ids, _ in batches.calls] == [("claude", ["smoke", "atv-confirm", "atv12"]),
                                                         ("claude", ["S4", "S5", "S16"])]
    options = batches.calls[1][2]
    assert options.reps == 1 and not options.rerun_failed_functional and options.infra_stop  # a ★ 1-rep detector
    assert not q.bumped and any("already the validated version" in n for n in q.notes)
    text = (station.repo / "docs/acceptance/2026-11-27-claude-2.1.328-qualify.md").read_text(encoding="utf-8")
    assert "- Result: **PASS**" in text and "- Repository commit: `" in text
    assert "owner-accepted residual (OD21-5 = c)" in text and "Step 9.4, ATV-8" in text
    assert "6 turns, 6,000 input tokens" in text and "1.50 USD" in text


def test_a_newer_installed_version_that_passes_is_bumped(station: Station) -> None:
    station.set(codex={"version": "0.171.0"})
    report, _, _ = qualify(station, harness="codex")
    q = one(report, "codex")
    assert q.verdict == "PASS" and q.bumped
    entry = validated(station).codex
    assert (entry.version, entry.install, entry.validated) == ("0.171.0", "npm", TODAY)
    assert entry.report == "docs/acceptance/2026-11-27-codex-0.171.0-qualify.md"
    assert validated(station).claude.version == "2.1.328"  # the other harness is untouched
    text = (station.repo / harness_versions.VALIDATED_FILE).read_text(encoding="utf-8")
    assert text.startswith("# Harness versions validated") and "codex:  {version: 0.171.0, install: npm," in text
    assert any("commit config/harness/validated.yaml" in a for a in q.actions)


def test_a_t1_failure_fails_without_t2_and_names_the_t3_set(station: Station) -> None:
    station.set(codex={"version": "0.171.0"})
    batches = FakeBatches(station.tmp)
    batches.plan["atv-confirm"] = "fail"
    report, _, _ = qualify(station, harness="codex", batches=batches)
    q = one(report, "codex")
    assert q.verdict == "FAIL" and [t.tier for t in q.tiers] == ["T0", "T1"] and not q.bumped
    assert q.tiers[1].surfaces == ["approval"] and q.t3_set == ["S4", "S11", "S12", "S15"]
    assert validated(station).codex.version == "0.170.0"
    assert any("T3 set for the surface: S4, S11, S12, S15" in a for a in q.actions)


# -- candidate, guard, restore ---------------------------------------------------------------------------------------


def test_a_candidate_needs_a_human_terminal(station: Station) -> None:
    with pytest.raises(QualifyRefused, match="needs a human terminal"):
        qualify(station, harness="codex", candidate="0.172.0", interactive=True,
                environ={**station.environ, "CLAUDECODE": "1"})
    with pytest.raises(QualifyRefused, match="no interactive terminal"):
        qualify(station, harness="codex", candidate="0.172.0", interactive=False)
    assert not station.ran("npm")


def test_a_failing_candidate_is_put_back_to_the_validated_version(station: Station) -> None:
    batches = FakeBatches(station.tmp)
    batches.plan["S5"] = "fail"
    report, _, _ = qualify(station, harness="codex", candidate="0.172.0", interactive=True, batches=batches)
    q = one(report, "codex")
    assert q.verdict == "FAIL" and q.version == "0.172.0" and q.restored == "0.170.0"
    installs = [row[1:] for row in station.calls("npm")]
    assert installs == [["install", "-g", "@openai/codex@0.172.0"], ["install", "-g", "@openai/codex@0.170.0"]]
    assert station.world()["codex"]["version"] == "0.170.0" and validated(station).codex.version == "0.170.0"
    assert q.tiers[-1].tier == "T2" and q.t3_set == ["S2", "S3", "S5", "S6", "S8", "S9", "S18"]


def test_a_passing_latest_candidate_is_bumped(station: Station) -> None:
    station.set(claude={"latest": "2.1.331"})
    report, _, _ = qualify(station, harness="claude", candidate="latest", interactive=True)
    q = one(report, "claude")
    assert q.verdict == "PASS" and q.version == "2.1.331" and q.bumped and q.restored is None
    assert station.ran("claude", "install", "latest") and validated(station).claude.version == "2.1.331"


def test_a_candidate_that_does_not_install_fails_at_once(station: Station) -> None:
    station.set(npm={"install": "fail"})
    report, batches, test_runs = qualify(station, harness="codex", candidate="0.172.0", interactive=True)
    q = one(report, "codex")
    assert q.verdict == "FAIL" and q.tiers == [] and batches.calls == [] and test_runs == []
    assert "Codex 0.172.0 was not installed" in q.actions[0]


# -- infra stop ------------------------------------------------------------------------------------------------------


def test_an_infra_stop_ends_everything_without_an_install(station: Station) -> None:
    batches = FakeBatches(station.tmp)
    batches.plan["smoke"] = "infra"
    report, _, _ = qualify(station, candidate=None, batches=batches)
    assert report.exit_code == 3 and [q.verdict for q in report.harnesses] == ["INFRA_STOP"]  # claude never ran
    q = one(report, "codex")
    assert [h for h, _, _ in batches.calls] == ["codex"] and q.tiers[1].infra is not None
    assert q.report == "work/harness/2026-11-27-codex-0.170.0-qualify-infra-stop.md"
    text = (station.repo / q.report).read_text(encoding="utf-8")
    assert "Infra stop (owner rule: stop, no retries)" in text


def test_an_infra_stop_after_a_candidate_install_installs_nothing_more(station: Station) -> None:
    batches = FakeBatches(station.tmp)
    batches.plan["atv-confirm"] = "infra"
    report, _, _ = qualify(station, harness="codex", candidate="0.172.0", interactive=True, batches=batches)
    q = one(report, "codex")
    assert report.exit_code == 3 and q.restored is None
    assert len(station.calls("npm")) == 1 and "npm install -g @openai/codex@0.170.0" in q.actions[0]


# -- escalation ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("t3", "verdict"), [("pass", "PASS"), ("fail", "FAIL")])
def test_escalation_after_a_t2_failure(station: Station, t3: Outcome, verdict: str) -> None:
    batches = FakeBatches(station.tmp)

    def outcome(sid: str, rep: int) -> Outcome:  # S4 fails its T2 canary (call 2), then as planned in T3 (call 3)
        if sid != "S4":
            return "pass"
        return "fail" if len(batches.calls) == 2 else t3

    batches.outcome = outcome  # type: ignore[method-assign]
    report, _, _ = qualify(station, harness="codex", escalate=True, max_sessions=12, batches=batches)
    q = one(report, "codex")
    assert [t.tier for t in q.tiers] == ["T0", "T1", "T2", "T3"] and q.t3_set == ["S4", "S11", "S12", "S15"]
    t3_options = batches.calls[-1][2]
    assert t3_options.reps is None and t3_options.max_sessions == 12 and t3_options.rerun_failed_functional
    assert q.verdict == verdict
    if verdict == "PASS":
        assert any("T2 failure cleared by T3" in n for n in q.notes)


def test_t3_sets_follow_the_escalation_map(station: Station) -> None:
    assert harness_qualify.t3_set(station.repo, {"format"}) == []
    assert harness_qualify.t3_set(station.repo, {"hook"}) == ["S5", "S6", "S16", "S17", "S18"]
    assert harness_qualify.t3_set(station.repo, {"lifecycle", "format"}) == ["S14", "S15"]
    every_star = ["S2", "S3", "S5", "S6", "S8", "S9", "S11", "S12", "S15", "S17", "S18"]
    assert harness_qualify.t3_set(station.repo, {"unclear"}) == every_star
    assert harness_qualify.t3_set(station.repo, {"approval", "hook"}) == every_star


# -- --windows -------------------------------------------------------------------------------------------------------


def test_windows_records_the_lab_pc_qualification(station: Station) -> None:
    report, batches, _ = qualify(station, windows=True)
    assert report.exit_code == 0
    assert [ids for _, ids, _ in batches.calls] == [["smoke", "atv-confirm"], ["S16"],
                                                     ["smoke", "atv-confirm", "atv12"], ["S16"]]
    record = harness_versions.load_windows_qualification(station.tmp / "state")
    assert record is not None and record.version("codex") == "0.170.0" and record.version("claude") == "2.1.328"
    assert record.codex is not None and record.codex.report == "work/harness/2026-11-27-codex-0.170.0-windows.md"
    text = (station.repo / record.codex.report).read_text(encoding="utf-8")
    assert text.startswith("# Harness Windows qualification (lab PC): codex 0.170.0")
    assert not one(report, "codex").bumped and validated(station).codex.version == "0.170.0"


def test_windows_refuses_off_windows_and_a_non_validated_version(station: Station) -> None:
    off_windows = QualifyContext(ops=station.ctx(windows=False), out_dir=station.tmp / "o", today=TODAY,
                                 run_batch=FakeBatches(station.tmp), run_tests=lambda repo, env: (True, "ok"))
    with pytest.raises(QualifyRefused, match="Windows lab PC"):
        harness_qualify.run_qualify(off_windows, QualifyOptions(windows=True))
    station.set(codex={"version": "0.171.0"})
    report, batches, _ = qualify(station, windows=True, harness="codex")
    assert one(report, "codex").verdict == "FAIL" and batches.calls == []
    assert "run `uv run b1500 update` first" in one(report, "codex").actions[0]
    assert harness_versions.load_windows_qualification(station.tmp / "state") == \
        harness_versions.WindowsQualification()


@pytest.mark.parametrize(("options", "says"), [
    ({"max_sessions": 3}, "--max-sessions caps the T3 sessions"),
    ({"windows": True, "pin": True}, "no --candidate, --pin or --escalate"),
    ({"pin": True, "up_to": 1}, "--pin needs the full ladder"),
    ({"candidate": "newest", "harness": "codex"}, "--candidate is a version"),
    ({"candidate": "0.172.0"}, "give --harness"),
])
def test_conflicting_options_are_refused(station: Station, options: dict[str, Any], says: str) -> None:
    with pytest.raises(QualifyRefused, match=says.replace("-", "\\-")):
        qualify(station, interactive=True, **options)


def test_cli_refusals_exit_2() -> None:
    result = CliRunner().invoke(app, ["dev", "harness", "qualify", "--max-sessions", "3"])
    assert result.exit_code == 2 and "--max-sessions caps the T3 sessions" in result.output
    assert CliRunner().invoke(app, ["dev", "harness", "qualify", "--harness", "gemini"]).exit_code == 2


# -- end to end: the real runner, the scripted agent, --pin ----------------------------------------------------------

PROBE_SCRIPTS = {
    "smoke": {1: [{"call": "station_status", "args": {"refresh": False}}, {"cli": "bringup status"},
                  {"say": "Backend: sim (SIMULATED). bringup status printed [SIMULATED] first."}]},
    "atv-confirm": {1: [{"deny": "run_confirmed_plan", "args": {"plan_id": "P-AAAAAAAAAA",
                                                                "summary": "acceptance probe"}},
                        {"say": "The call was denied."}],
                    2: [{"call": "run_confirmed_plan", "args": {"plan_id": "P-AAAAAAAAAA",
                                                                "summary": "acceptance probe"}},
                        {"say": "refused: unknown_plan"}]},
    "atv12": {1: [{"deny": "run_confirmed_plan", "args": {"plan_id": "P-AAAAAAAAAA",
                                                          "summary": "acceptance probe"}},
                  {"say": "The call was refused before the server."}]},
}
SUITE_SCRIPTS = {"S4": "S04-ideal.yaml", "S5": "S05-ideal.yaml", "S16": "S16-ideal.yaml"}


def _scripted_harness(mp: pytest.MonkeyPatch, tmp: Path) -> None:
    scripts: dict[str, Path] = {}
    for sid, turns in PROBE_SCRIPTS.items():
        scripts[sid] = tmp / f"{sid}.agent.yaml"
        scripts[sid].write_text(yaml.safe_dump({"turns": turns}), encoding="utf-8")
    for sid, name in SUITE_SCRIPTS.items():
        scripts[sid] = tmp / name
        shutil.copyfile(FIXTURES / "scenarios" / name, scripts[sid])
    mp.setenv("CODEX_HOME", str(tmp / "codex-home"))
    mp.setenv("FAKE_AGENT_VARS", "{}")

    real = harnesses.turn_argv

    def fake_argv(launch: harnesses.TurnLaunch, exe: str) -> tuple[list[str], Any]:
        sid = launch.session_dir.name.rsplit("-r", 1)[0]
        if sid not in scripts:  # T0 derives the runner flags from the real argv builders
            return real(launch, exe)
        return ([sys.executable, str(FAKE_AGENT), "--harness", launch.harness, "--turn", str(launch.turn),
                 "--resume", launch.resume_id or "new", "--script", str(scripts[sid])], None)

    mp.setattr(harnesses, "turn_argv", fake_argv)
    mp.setattr(harnesses, "executable", lambda harness: sys.executable)
    mp.setattr(harnesses, "harness_version", lambda harness: "0.171.0" if harness == "codex" else "2.1.328")


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_ladder_end_to_end_with_the_scripted_agent(station: Station, monkeypatch: pytest.MonkeyPatch,
                                                   harness: str) -> None:
    for rel in ("config", "recipes"):
        shutil.copytree(REPO_ROOT / rel, station.repo / rel, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("local"))
    add_manual_corpus(station.repo)
    station.set(codex={"version": "0.171.0"})
    _scripted_harness(monkeypatch, station.tmp)
    ctx = QualifyContext(ops=station.ctx(), out_dir=station.tmp / "out", today=TODAY,
                         run_batch=harness_qualify.default_batch_runner(station.lines.append),
                         run_tests=lambda repo, env: (True, "offline tests injected"))
    report = harness_qualify.run_qualify(ctx, QualifyOptions(harness=harness, pin=True))  # type: ignore[arg-type]
    q = one(report, harness)
    failures = [(s.session, s.failed) for t in q.tiers for s in t.sessions if not s.passed]
    assert q.verdict == "PASS" and report.exit_code == 0, (failures, q.actions, q.notes)
    assert [t.tier for t in q.tiers] == ["T0", "T1", "T2"]
    assert q.bumped == (harness == "codex")
    pin = station.repo / f"tests/fixtures/transcripts/{harness}-{q.version}"
    assert q.pinned == pin.relative_to(station.repo).as_posix()
    meta = json.loads((pin / "meta.json").read_text(encoding="utf-8"))
    assert {k.split("/")[0] for k in meta["files"]} == set(harness_qualify.T1_PROBES[harness])
    pinned_text = "\n".join(p.read_text(encoding="utf-8") for p in pin.rglob("*") if p.is_file())
    assert station.repo.as_posix() not in pinned_text and str(station.tmp) not in pinned_text
    smoke = station.tmp / "regrade" / "smoke"
    shutil.copytree(pin / "smoke", smoke)
    for path in smoke.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("<REPO>", station.repo.as_posix()).replace("<SESSION>", smoke.as_posix()),
                            encoding="utf-8")
    regraded = grade_session(smoke, write=False)
    assert regraded.passed, [(r.name, r.message, r.details) for r in regraded.failures()]
    assert {r.name: r.verdict for r in regraded.results}["shell step: bringup status printed [SIMULATED]"] == "pass"
