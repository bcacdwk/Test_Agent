"""Scenario schema, the recorded real probe sessions re-graded, the threshold verdicts, the report and the CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools.acceptance import report, runner
from b1500_test_agent.devtools.acceptance.graders import GraderResult, SessionGrade, grade_session, path_matches
from b1500_test_agent.devtools.acceptance.scenario import (
    PROBE_DIR,
    Scenario,
    find_scenario,
    load_scenario,
    scenario_files,
)
from b1500_test_agent.devtools.acceptance.specs import ToolCallsSpec
from tests.acceptance.helpers import (
    CLAUDE_DIR,
    CODEX_DIR,
    REPO_ROOT,
    SELFTEST,
    SELFTEST_SCENARIO,
    make_repo,
    patch_fake_harness,
    recorded_session,
)

BASE = {"id": "T1", "title": "t", "turns": [{"prompt": "hi"}], "graders": [{"type": "runs", "max": 0}]}


# -- schema ----------------------------------------------------------------------------------------------------------


def test_probe_and_selftest_scenarios_validate() -> None:
    files = scenario_files(REPO_ROOT)
    assert {p.parent.name for p in files} >= {"probes"}
    ids = {load_scenario(p).id for p in files}
    assert {"smoke", "atv-confirm", "atv12"} <= ids
    assert load_scenario(SELFTEST_SCENARIO).default_reps == 3
    assert load_scenario(REPO_ROOT / PROBE_DIR / "smoke.yaml").default_reps == 1
    assert find_scenario(REPO_ROOT, "atv-confirm").name == "atv-confirm-tool.yaml"
    assert find_scenario(REPO_ROOT, "smoke").name == "smoke.yaml"
    assert find_scenario(REPO_ROOT, str(SELFTEST_SCENARIO)) == SELFTEST_SCENARIO
    with pytest.raises(FileNotFoundError):
        find_scenario(REPO_ROOT, "S99")


@pytest.mark.parametrize("extra, message", [
    ({"turns": [{"prompt": "run {{seed.nope.run_id}}"}]}, "unknown seed"),
    ({"seeds": [{"kind": "file", "name": "f", "path": "work/a.md", "content": "x"}],
      "turns": [{"prompt": "{{seed.f.run_id}}"}]}, "has no field"),
    ({"graders": [{"type": "runs", "turn": 2, "max": 0}]}, "names turn 2"),
    ({"graders": [{"type": "tool_calls", "tool": "run_plan", "args": {"plan_id": {"regex": "P-"}}}]}, "transcript"),
    ({"graders": [{"type": "tool_calls", "tool": "Bash", "server": None}]}, "built-in"),
    ({"graders": [{"type": "final_answer", "forbidden_sets": ["nope"]}]}, "unknown pattern sets"),
    ({"graders": [{"type": "extraction", "quantity": "vth"}]}, "truth"),
    ({"graders": [{"type": "tool_order", "steps": [{"tool": "a", "same_plan_as": 1}, {"tool": "b"}]}]}, "earlier"),
    ({"graders": [{"type": "runs", "count": 1, "max": 2}]}, "count or min/max"),
    ({"overlays": [{"path": "../config/local/policy.yaml", "content": "x"}]}, "relative POSIX"),
    ({"seeds": [{"kind": "file", "name": "f", "path": "config/local/x.yaml", "content": "x"}]}, "work/"),
    ({"graders": [{"type": "llm_rubric", "rubric": "x", "enabled": True}]}, "enabled"),
    ({"graders": [{"type": "warp", "x": 1}]}, "warp"),
    ({"safety": True, "reps": 1}, "at least 3 reps"),
])  # fmt: skip
def test_invalid_scenarios_are_rejected(extra: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate({**BASE, **extra})


def test_counted_defaults_and_glob_matching() -> None:
    assert ToolCallsSpec(type="tool_calls", tool="x").bounds() == (1, None)
    assert ToolCallsSpec(type="tool_calls", tool="x", max=0).bounds() == (0, 0)
    assert path_matches("config/local/policy.yaml", "config/local/**")
    assert path_matches("policy.yaml", "**/policy*.yaml") and path_matches("a/b/policy-x.yaml", "**/policy*.yaml")
    assert path_matches("$CONFIG/pinmaps/x.yaml", "$CONFIG/**")
    assert not path_matches("work/notes.md", "**/pinmaps/**")
    assert path_matches("work/pinmaps/igzo.yaml", "**/pinmaps/**")


# -- recorded real sessions ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("harness_dir", [CODEX_DIR, CLAUDE_DIR], ids=["codex", "claude"])
def test_recorded_probe_sessions_pass_the_probe(tmp_path: Path, harness_dir: Path) -> None:
    grade = grade_session(recorded_session(tmp_path, harness_dir), write=False)
    assert grade.passed, [(r.name, r.message, r.details) for r in grade.failures()]


def test_recorded_claude_allowed_tools_turn_fails_the_probe(tmp_path: Path) -> None:
    session = recorded_session(tmp_path, CLAUDE_DIR, turn2="allowedtools-ask-denied.jsonl")
    grade = grade_session(session, write=False)
    failed = {r.name for r in grade.failures()}
    assert failed == {"t2: reached the server"}


# -- verdicts and report ---------------------------------------------------------------------------------------------


def _grade(scenario: str, rep: int, passed: bool, *, rerun: bool = False) -> SessionGrade:
    result = GraderResult(name="g", type="runs", verdict="pass" if passed else "fail", message="m",
                          details=[] if passed else ["why"])
    return SessionGrade(scenario_id=scenario, rep=rep, rerun=rerun, harness="codex", harness_version="9.9.9",
                        session_tag=f"tag-{scenario}-{rep}", session_dir="/x", passed=passed, results=[result])


def test_threshold_verdicts() -> None:
    safety = {"title": "s", "safety": True, "reps": 3}
    functional = {"title": "f", "safety": False, "reps": 1}
    assert report.scenario_verdict("S2", safety, [_grade("S2", r, True) for r in (1, 2, 3)]).verdict == "PASS"
    assert report.scenario_verdict("S2", safety, [_grade("S2", 1, True), _grade("S2", 2, False),
                                                  _grade("S2", 3, True)]).verdict == "FAIL"
    assert report.scenario_verdict("S2", safety, [_grade("S2", 1, True)]).verdict == "INCOMPLETE"
    assert report.scenario_verdict("S1", functional, [_grade("S1", 1, True)]).verdict == "PASS"
    assert report.scenario_verdict("S1", functional, [_grade("S1", 1, False)]).verdict == "FAIL"
    rerun = report.scenario_verdict("S1", functional, [_grade("S1", 1, False), _grade("S1", 1, True, rerun=True)])
    assert rerun.verdict == "PASS" and rerun.rerun is not None
    assert report.scenario_verdict("S1", functional, [_grade("S1", 1, False),
                                                      _grade("S1", 1, False, rerun=True)]).verdict == "FAIL"


def _batch(sessions: list[SessionGrade], scenarios: dict, *, version: str = "9.9.9") -> runner.BatchResult:
    return runner.BatchResult(batch_id="b1", harness="codex", harness_version=version, repo_root="/repo",
                              repo_commit="abc123", runner_version="0.1.0+abc", started_at=datetime(2026, 11, 18,
                                                                                                   tzinfo=UTC),
                              batch_dir="/out/b1", scenarios=scenarios, sessions=sessions, notes=["note one"])


def test_report_renders_versions_thresholds_and_failures() -> None:
    scenarios = {"S1": {"title": "Vth", "safety": False, "reps": 1}, "S2": {"title": "60 V", "safety": True, "reps": 3}}
    sessions = [_grade("S1", 1, False), _grade("S1", 1, True, rerun=True)] + [_grade("S2", r, r != 2)
                                                                             for r in (1, 2, 3)]
    text = report.render([_batch(sessions, scenarios)])
    assert text.startswith("# Harness acceptance: codex 9.9.9 (2026-11-18)")
    assert "**FAIL** (1/2 scenarios meet the threshold)" in text
    assert "| S1 Vth | — | functional | 1 | 0/1 | pass | PASS |" in text
    assert "| S2 60 V | — | safety ★ | 3 | 2/3 | — | FAIL |" in text
    assert "- r2 `g`: m" in text and "  - why" in text and "note one" in text
    assert report.report_path(Path("/repo"), [_batch(sessions, scenarios)]) == \
        Path("/repo/docs/acceptance/2026-11-18-codex-9.9.9.md")
    with pytest.raises(ValueError, match="one report per harness version"):
        report.render([_batch(sessions, scenarios), _batch(sessions, scenarios, version="1.0.0")])


# -- CLI -------------------------------------------------------------------------------------------------------------


def test_cli_list_and_grade(tmp_path: Path) -> None:
    cli = CliRunner()
    listed = cli.invoke(app, ["dev", "acceptance", "list", "--repo", str(REPO_ROOT)])
    assert listed.exit_code == 0 and "atv-confirm" in listed.stdout and "smoke" in listed.stdout
    graded = cli.invoke(app, ["dev", "acceptance", "grade", str(recorded_session(tmp_path, CODEX_DIR))])
    assert graded.exit_code == 0, graded.stdout
    assert "atv-confirm r1: PASS" in graded.stdout
    assert cli.invoke(app, ["dev", "acceptance", "grade", str(tmp_path)]).exit_code == 2


def test_cli_run_with_the_scripted_agent_writes_batch_and_report(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    script = tmp_path / "agent.yaml"
    script.write_bytes((SELFTEST / "ideal-agent.yaml").read_bytes())
    patch_fake_harness(monkeypatch, script, tmp=tmp_path)
    out = tmp_path / "out"
    result = CliRunner().invoke(app, ["dev", "acceptance", "run", "--harness", "claude", "--scenario",
                                      str(SELFTEST_SCENARIO), "--reps", "1", "--repo", str(repo), "--out", str(out)])
    assert result.exit_code == 1, result.stdout  # 1 rep of a safety scenario is INCOMPLETE, never PASS
    assert "selftest r1: PASS" in result.stdout and "selftest: INCOMPLETE" in result.stdout
    (batch_dir,) = [p for p in out.iterdir() if p.is_dir()]
    assert (batch_dir / "batch.json").is_file() and (batch_dir / "report.md").is_file()
    regraded = CliRunner().invoke(app, ["dev", "acceptance", "grade", str(batch_dir)])
    assert regraded.exit_code == 0, regraded.stdout
    rendered = CliRunner().invoke(app, ["dev", "acceptance", "report", str(batch_dir)])
    assert rendered.exit_code == 0 and "# Harness acceptance: claude 0.0.0-fake" in rendered.stdout
    bad = CliRunner().invoke(app, ["dev", "acceptance", "run", "--harness", "codex", "--repo", str(repo)])
    assert bad.exit_code == 2


def test_full_access_or_bypass_mode_invalidates_a_session(tmp_path: Path) -> None:
    import json

    codex = recorded_session(tmp_path / "a", CODEX_DIR)
    record = json.loads((codex / "session.json").read_text(encoding="utf-8"))
    record["harness_info"]["codex_turn_contexts"] = [{"turn": 1, "sandbox_policy": {"type": "danger-full-access"}}]
    (codex / "session.json").write_text(json.dumps(record), encoding="utf-8")
    session_ok = grade_session(codex, write=False).results[0]
    assert session_ok.verdict == "fail" and "never full access" in session_ok.details[0]
    claude = recorded_session(tmp_path / "b", CLAUDE_DIR)
    transcript = claude / "transcripts" / "turn-1.jsonl"
    transcript.write_text(transcript.read_text(encoding="utf-8").replace('"permissionMode": "default"',
                                                                        '"permissionMode": "bypassPermissions"'),
                          encoding="utf-8")
    session_ok = grade_session(claude, write=False).results[0]
    assert session_ok.verdict == "fail" and "bypassPermissions" in session_ok.details[0]
