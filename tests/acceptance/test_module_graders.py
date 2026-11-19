"""Acceptance runner v2 (WP6.6; blueprint v2 8.2 cost policy) and the module graders on genuine evidence.

- Module graders (``plans``, ``async_run``, ``tool_order`` with ``outcome``/``recipe``, ``commands``) on a real
  asynchronous run of an existing recipe (``tests/fixtures/transcripts/selftest/async-*.yaml``): long_run
  confirmation, polling to completion, a second run cancelled when the turn's service closes (as the MCP server's
  shutdown hook does in a headless harness turn), ``safe_shutdown``.
- Selection: tags, ``--affected`` against a git base (own file, ``touches``, global files, the ``.claude/skills``
  mirror), pending scenarios, duplicate ids, notes; the base from the previous report.
- Runner: ``sim.timing`` in the runner config, the ``--max-sessions`` budget; usage parsed per turn, summed per session
  and in the report (with the commit line and shortened paths); the CLI's ``--dry-run``, ``--tag`` and ``list``.
- Graders: ``sim_call`` truths, ``expect: present``, dimensionless values, ``plan_limits`` pulse bands, ``routes``
  without a declared switch.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.acceptance import report, runner, selection
from b1500_test_agent.devtools.acceptance.evidence import load_evidence
from b1500_test_agent.devtools.acceptance.extraction import values_with_unit
from b1500_test_agent.devtools.acceptance.graders import GRADERS, SessionGrade, grade_session
from b1500_test_agent.devtools.acceptance.scenario import Scenario, load_scenario
from b1500_test_agent.devtools.acceptance.specs import ExtractionSpec, RoutesSpec, Truth
from b1500_test_agent.devtools.acceptance.transcripts import Usage, claude_usage, codex_usage, parse_turn
from tests.acceptance.helpers import (
    CLAUDE_DIR,
    CODEX_DIR,
    REPO_ROOT,
    SELFTEST,
    make_repo,
    patch_fake_harness,
    run_scripted,
)

ASYNC = SELFTEST / "async-scenario.yaml"
_ASYNC: dict[str, SessionGrade] = {}


def async_session(kind: str, tmp_path_factory: pytest.TempPathFactory) -> SessionGrade:
    if kind not in _ASYNC:
        harness = "codex" if kind == "ideal" else "claude"
        with pytest.MonkeyPatch.context() as mp:
            _ASYNC[kind], _ = run_scripted(mp, tmp_path_factory.mktemp(f"async-{kind}"), harness,
                                           SELFTEST / f"async-{kind}.yaml", scenario=ASYNC, timeout_s=120)
    return _ASYNC[kind]


def _show(grade: SessionGrade) -> str:
    return "\n".join(f"{r.verdict}: {r.name}: {r.message} {r.details}" for r in grade.results)


# -- module graders on a genuine asynchronous run --------------------------------------------------------------------


def test_async_ideal_session_passes_every_grader(tmp_path_factory: pytest.TempPathFactory) -> None:
    grade = async_session("ideal", tmp_path_factory)
    assert grade.passed, _show(grade)


def test_async_violating_session_fails_exactly_the_named_graders(tmp_path_factory: pytest.TempPathFactory) -> None:
    grade = async_session("violating", tmp_path_factory)
    expected = yaml.safe_load((SELFTEST / "async-violating.yaml").read_text(encoding="utf-8"))["expected_failures"]
    deciding = [g.label() for g in load_scenario(ASYNC).graders]
    assert sorted(r.name for r in grade.failures()) == sorted(expected) == sorted(deciding), _show(grade)


def test_async_evidence_is_the_servers_own(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The audit carries the async start (outcome running) and the polls; closing the turn's service cancelled the
    second run with a verified cleanup and kept its rows as partial data (WP5.6), as a headless turn's MCP server
    does on exit."""
    ev = load_evidence(Path(async_session("ideal", tmp_path_factory).session_dir))
    starts = [c for c in ev.calls("audit") if c.tool == "run_confirmed_plan"]
    assert [c.outcome for c in starts] == ["running", "running"]
    done, cancelled = sorted(ev.runs_in(2), key=lambda r: r.manifest.started_at)
    assert done.manifest.outcome == "completed" and cancelled.manifest.outcome == "cancelled"
    assert cancelled.manifest.cleanup is not None and cancelled.manifest.cleanup.verified == "sim_state"
    assert "partial.csv" in cancelled.manifest.files
    polls = [c for c in ev.calls("audit") if c.tool == "get_run" and c.run_id == done.manifest.run_id]
    assert len(polls) >= 2 and all(c.ts is not None for c in polls)
    shutdown = next(c for c in ev.calls("transcript") if c.tool == "safe_shutdown")
    assert shutdown.turn == 3 and shutdown.cancelled_run is None  # the run was already cancelled


def test_usage_is_summed_per_session(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The fake harness reports a fixed usage per turn; the session sums three turns with the runner's wall time."""
    codex = async_session("ideal", tmp_path_factory).usage
    assert (codex.turns, codex.input_tokens, codex.cached_input_tokens, codex.output_tokens) == (3, 3600, 3000, 90)
    assert codex.cost_usd is None and codex.wall_s > 0 and codex.models == ["fake"]
    claude = async_session("violating", tmp_path_factory).usage
    assert (claude.turns, claude.input_tokens, claude.cached_input_tokens) == (3, 3600, 3000)
    assert claude.cost_usd == pytest.approx(0.03) and claude.reasoning_tokens == 15


# -- usage parsing ---------------------------------------------------------------------------------------------------


def test_usage_from_recorded_transcripts() -> None:
    codex = parse_turn("codex", (CODEX_DIR / "probe-turn-2.jsonl").read_text(encoding="utf-8").splitlines(), turn=2)
    assert codex.usage == Usage(turns=1, input_tokens=192902, cached_input_tokens=170368, output_tokens=519,
                                reasoning_tokens=22)
    claude = parse_turn("claude", (CLAUDE_DIR / "probe-turn-1.jsonl").read_text(encoding="utf-8").splitlines())
    assert claude.usage is not None and claude.usage.cost_usd and claude.usage.models == ["claude-opus-5-5"]
    assert claude.usage.input_tokens > claude.usage.cached_input_tokens > 0
    assert codex_usage(None) is None and claude_usage({"type": "result"}) is None
    total = codex.usage + claude.usage
    assert total.turns == 2 and total.cost_usd == claude.usage.cost_usd


def test_report_shows_commit_tags_usage_and_short_paths() -> None:
    grade = SessionGrade(scenario_id="S1", rep=1, harness="codex", harness_version="9.9.9", session_tag="t",
                         session_dir="/tmp/acc/b1/S1-r1", passed=True, results=[],
                         usage=Usage(turns=2, input_tokens=1000, cached_input_tokens=800, output_tokens=20,
                                     wall_s=90, models=["gpt-x"]))
    batch = runner.BatchResult(batch_id="b1", harness="codex", harness_version="9.9.9", repo_root="/home/me/repo",
                               repo_commit="abc-dirty", repo_head="a" * 40, runner_version="0.1",
                               started_at=datetime(2026, 11, 19, tzinfo=UTC), batch_dir="/tmp/acc/b1",
                               scenarios={"S1": {"title": "Vth", "safety": False, "reps": 1, "tags": ["smu"]}},
                               sessions=[grade],
                               skipped={"S2": "--max-sessions 1: 3 rep(s) do not fit into the 0 left"},
                               notes=["note at /home/me/repo/x"])
    text = report.render([batch], shorten=True)
    assert f"- Repository commit: `{'a' * 40}`" in text
    assert "| S1 Vth | smu | functional | 1 | 1/1 | — | PASS |" in text
    assert "Not started: S2 (--max-sessions 1" in text
    assert "| S1-r1 | 2 | 1,000 | 800 | 20 | 0 | — | 90 |" in text and "| **total** | 2 | 1,000 |" in text
    assert "`<out>/b1/S1-r1`" in text and "<repo>/x" in text and "/home/me" not in text and "/tmp/acc" not in text
    assert "1 sessions, 2 turns, 1,000 input tokens (800 cached), 20 output, 1.5 min" in text
    assert selection.report_commit(text) == "a" * 40
    assert selection.report_commit("- Runner: b1500 x; repository plan-v1-5-g0c191cd-dirty at `<x>`") == \
        "plan-v1-5-g0c191cd-dirty"


# -- selection -------------------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def _scenario_file(repo: Path, name: str, **fields) -> Path:
    data = {"id": name.split("-")[0].replace("S0", "S"), "title": name, "turns": [{"prompt": "hi"}],
            "graders": [{"type": "runs", "max": 0}], **fields}
    path = repo / "tests" / "acceptance" / "scenarios" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path)
    _scenario_file(repo, "S01-a", tags=["smu"], touches=[".agents/skills/b1500-test/cards/smu/**"])
    _scenario_file(repo, "S02-b", tags=["cmu", "nvm"], touches=["recipes/basic/*.yaml"], safety=True)
    _scenario_file(repo, "S03-c", tags=["cmu"], requires={"recipes": ["moscap.cv"]})
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "base")
    return repo


def test_tags_pending_and_budget_planning(git_repo: Path) -> None:
    chosen = selection.select(git_repo, harness="codex", tags=["cmu"])
    assert [s.scenario.id for s in chosen.selected] == ["S2"] and chosen.sessions() == 3 and chosen.sessions(1) == 1
    assert chosen.skipped["S1"] == "no tag of ['cmu']"
    assert chosen.skipped["S3 (S03-c.yaml)"].startswith("pending: missing recipe moscap.cv")
    assert any(n.startswith("not run (pending") for n in chosen.notes())
    with pytest.raises(selection.SelectionError, match="S3 is pending"):
        selection.select(git_repo, harness="codex", scenarios=["S3"])
    with pytest.raises(selection.SelectionError, match="give --scenario"):
        selection.select(git_repo, harness="codex")
    assert [s.scenario.id for s in selection.select(git_repo, harness="codex", all_=True).selected] == ["S1", "S2"]


def test_affected_follows_touches_own_file_global_files_and_the_mirror(git_repo: Path) -> None:
    base = _git(git_repo, "rev-parse", "HEAD").strip()

    def affected() -> list[str]:
        return [s.scenario.id for s in selection.select(git_repo, harness="codex", affected=True,
                                                        since=base).selected]

    assert affected() == []
    card = git_repo / ".claude" / "skills" / "b1500-test" / "cards" / "smu" / "x.md"  # untracked, mirror path
    card.parent.mkdir(parents=True)
    card.write_text("x\n", encoding="utf-8")
    assert affected() == ["S1"]
    (git_repo / "recipes" / "basic" / "contact_resistor.yaml").write_text("changed\n", encoding="utf-8")
    assert affected() == ["S1", "S2"]
    card.unlink()
    shutil.rmtree(git_repo / "recipes")
    _git(git_repo, "checkout", "-q", "--", "recipes")
    assert affected() == []
    own = git_repo / "tests" / "acceptance" / "scenarios" / "S02-b.yaml"
    own.write_text(own.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert affected() == ["S2"]
    (git_repo / "AGENTS.md").write_text("global\n", encoding="utf-8")
    assert affected() == ["S1", "S2"]
    chosen = selection.select(git_repo, harness="codex", affected=True, since=base)
    assert chosen.base == base and "--since" in (chosen.base_source or "")
    assert any(n.startswith("--affected: base") for n in chosen.notes())


def test_affected_base_comes_from_the_newest_report_of_the_harness(git_repo: Path) -> None:
    head = _git(git_repo, "rev-parse", "HEAD").strip()
    with pytest.raises(selection.SelectionError, match="no committed codex report"):
        selection.affected_base(git_repo, "codex")
    docs = git_repo / "docs" / "acceptance"
    docs.mkdir(parents=True)
    (docs / "2026-11-17-codex-0.1.md").write_text("- Runner: b1500; repository deadbee at `x`\n", encoding="utf-8")
    (docs / "2026-11-18-codex-0.1.md").write_text(f"- Repository commit: `{head}`\n", encoding="utf-8")
    (docs / "2026-11-19-claude-2.0.md").write_text("- Repository commit: `0000000`\n", encoding="utf-8")
    assert selection.previous_report(git_repo, "codex").name == "2026-11-18-codex-0.1.md"
    base, source = selection.affected_base(git_repo, "codex")
    assert base == head and "2026-11-18-codex-0.1.md" in source
    with pytest.raises(selection.SelectionError, match="does not have"):
        selection.affected_base(git_repo, "claude")


def test_glob_matching() -> None:
    assert selection.glob_matches(".agents/skills/b1500-test/cards/smu/a.md", ".agents/skills/b1500-test/cards/**")
    assert selection.glob_matches("recipes/mosfet/idvg.yaml", "recipes/*/idvg.yaml")
    assert not selection.glob_matches("recipes/mosfet/x/idvg.yaml", "recipes/*/idvg.yaml")
    assert selection.glob_matches("src/b1500_test_agent/rules/builtin/cmu.py", "src/b1500_test_agent/rules/**")


def test_duplicate_runnable_ids_are_refused(git_repo: Path) -> None:
    _scenario_file(git_repo, "S01-twin", tags=["smu"])
    with pytest.raises(selection.SelectionError, match="several runnable scenario files"):
        selection.select(git_repo, harness="codex", all_=True)


# -- runner ----------------------------------------------------------------------------------------------------------


def test_sim_timing_goes_into_the_runner_config(tmp_path: Path) -> None:
    scenario = Scenario.model_validate({"id": "T", "title": "t", "turns": [{"prompt": "x"}],
                                        "graders": [{"type": "runs", "max": 0}],
                                        "sim": {"scenario": "nmos_basic", "timing": "scaled(0.5)"}})
    runner.prepare_config(scenario, REPO_ROOT, tmp_path / "config")
    data = load_yaml((tmp_path / "config" / "sim" / "scenarios" / "nmos_basic.yaml").read_bytes())
    assert data["timing"] == "scaled(0.5)" and data.get("faults") is None
    runner.check_config(REPO_ROOT, tmp_path / "config", tmp_path / "data")
    with pytest.raises(ValueError, match="timing"):
        Scenario.model_validate({"id": "T", "title": "t", "turns": [{"prompt": "x"}],
                                 "graders": [{"type": "runs", "max": 0}], "sim": {"timing": "fast"}})


def test_max_sessions_never_cuts_a_scenario_short(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    script = tmp_path / "agent.yaml"
    script.write_text("turns:\n  1:\n    - {say: hi}\n", encoding="utf-8")
    patch_fake_harness(monkeypatch, script, tmp=tmp_path)
    one = _scenario_file(repo, "S01-one", graders=[{"type": "runs", "max": 0}])
    three = _scenario_file(repo, "S02-three", safety=True)
    options = runner.RunOptions(harness="codex", repo_root=repo, out_dir=tmp_path / "out", max_sessions=2)
    batch = runner.run_batch([one, three], options, notes=["selected by test"])
    assert [s.scenario_id for s in batch.sessions] == ["S1"]
    assert "S2" in batch.skipped and "3 rep(s) do not fit into the 1 left" in batch.skipped["S2"]
    assert batch.repo_head == "" or len(batch.repo_head) == 40
    assert batch.notes[0] == "selected by test" and batch.scenarios["S1"]["tags"] == []
    assert batch.sessions[0].usage.turns == 1


def test_cli_dry_run_tag_and_list(tmp_path: Path) -> None:
    cli = CliRunner()
    dry = cli.invoke(app, ["dev", "acceptance", "run", "--harness", "codex", "--all", "--dry-run", "--repo",
                           str(REPO_ROOT)])
    assert dry.exit_code == 0, dry.stdout
    chosen = selection.select(REPO_ROOT, harness="codex", all_=True)
    assert f"planned: {len(chosen.selected)} scenario(s), {chosen.sessions()} session(s) without re-runs" in dry.stdout
    assert "S16" in dry.stdout and "S17" in dry.stdout
    assert ("not run (pending" in dry.stdout) is any(v.startswith("pending") for v in chosen.skipped.values())
    tagged = cli.invoke(app, ["dev", "acceptance", "run", "--harness", "claude", "--tag", "bringup", "--dry-run",
                              "--max-sessions", "5", "--repo", str(REPO_ROOT)])
    assert tagged.exit_code == 0 and "S17" in tagged.stdout and "(--max-sessions 5)" in tagged.stdout
    pending = cli.invoke(app, ["dev", "acceptance", "run", "--harness", "codex", "--scenario", "S11", "--repo",
                               str(REPO_ROOT)])
    assert pending.exit_code == 2 and "S11 is pending" in pending.output
    listed = cli.invoke(app, ["dev", "acceptance", "list", "--repo", str(REPO_ROOT)])
    assert "PENDING: missing" in listed.stdout and "[manual, spgu]" in listed.stdout


# -- graders ---------------------------------------------------------------------------------------------------------


def test_values_with_unit() -> None:
    assert values_with_unit("n = 0.16.", "1") == [0.16]
    assert values_with_unit("n=0.25 at 3 V, 10 %, 5 MHz", "1") == [0.25]
    assert values_with_unit("Cox = 69.0 pF, 70 nF", "F") == pytest.approx([6.9e-11, 7e-8])


def test_truth_and_extraction_options_are_validated() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        Truth(value=1.0, sim_call="truth")
    with pytest.raises(ValueError, match="belong to sim_call"):
        Truth(value=1.0, key="x")
    with pytest.raises(ValueError, match=r"\$<plan parameter>"):
        Truth(sim_call="pund_truth", args={"v_max": "3 V"})
    with pytest.raises(ValueError, match="pattern"):
        Truth(sim_call="reset")  # only accessors named ...truth
    with pytest.raises(ValueError, match="existence only"):
        ExtractionSpec(type="extraction", quantity="pr", expect="present", rel_tol=0.1)


def test_sim_call_truth_names_a_missing_plan_parameter(tmp_path_factory: pytest.TempPathFactory) -> None:
    from tests.acceptance.test_v2_scenarios import sessions

    ev = load_evidence(Path(sessions("S12", tmp_path_factory).ideal.session_dir))
    spec = ExtractionSpec(type="extraction", quantity="memory_window", rel_tol=0.1, unit="V", require_window=False,
                          truth={"sim_call": "memory_window_truth",
                                 "args": {"v_program": "$v_prog", "v_erase": -4.0, "width": 1e-5}})
    passed, _, details = GRADERS["extraction"](ev, spec)
    assert passed is False and any("no numeric parameter 'v_prog'" in d for d in details)


def test_routes_need_a_declared_switch(tmp_path_factory: pytest.TempPathFactory) -> None:
    from tests.acceptance.test_v2_scenarios import sessions

    ev = load_evidence(Path(sessions("S12", tmp_path_factory).ideal.session_dir))
    passed, message, _ = GRADERS["routes"](ev, RoutesSpec(type="routes", target="SEL9.OUT1", sequence=["pgu"]))
    assert passed is False and "not a declared switch output" in message
    ok, _, _ = GRADERS["routes"](ev, RoutesSpec(type="routes", target="SEL1.OUT1", sequence=["smu", "pgu"]))
    assert ok is False  # order matters


def test_regrading_a_v2_session_from_artifacts_is_stable(tmp_path_factory: pytest.TempPathFactory) -> None:
    from tests.acceptance.test_v2_scenarios import sessions

    grade = sessions("S14", tmp_path_factory).ideal
    again = grade_session(Path(grade.session_dir), write=False)
    assert again.model_dump(exclude={"usage"}) == grade.model_dump(exclude={"usage"})
    assert json.loads((Path(grade.session_dir) / "grades.json").read_text(encoding="utf-8"))["usage"]["turns"] == 2


# -- harness context hygiene (WP6.6 findings) ------------------------------------------------------------------------


def test_claude_trust_is_read_from_the_user_config(tmp_path: Path) -> None:
    """Claude Code 2.1.328 loads neither CLAUDE.md nor the project allow rules in an untrusted folder, so the runner
    reads the trust (read-only) and warns."""
    from b1500_test_agent.devtools.acceptance import harnesses

    env = {"CLAUDE_CONFIG_DIR": str(tmp_path)}
    repo = tmp_path / "clone" / "test_agent"
    assert harnesses.claude_project_trusted(repo, env) is None  # no user config
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"projects": {str(repo): {"hasTrustDialogAccepted": False}}}), encoding="utf-8")
    assert harnesses.claude_project_trusted(repo, env) is False
    config.write_text(json.dumps({"projects": {str(repo.parent): {"hasTrustDialogAccepted": True}}}), encoding="utf-8")
    assert harnesses.claude_project_trusted(repo, env) is True  # trusted from a folder above


def test_git_status_naming_test_files_is_a_session_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An uncommitted scenario file shows up in the harness's git-status context (WP6.6: the agent opened it)."""
    repo = make_repo(tmp_path)
    script = tmp_path / "agent.yaml"
    script.write_text("turns:\n  1:\n    - {say: hi}\n", encoding="utf-8")
    patch_fake_harness(monkeypatch, script, tmp=tmp_path)
    monkeypatch.setattr(runner, "git_status", lambda _repo: [" M tests/acceptance/scenarios/S06-x.yaml"])
    scenario = _scenario_file(repo, "S01-one")
    options = runner.RunOptions(harness="claude", repo_root=repo, out_dir=tmp_path / "out")
    runner.run_session(load_scenario(scenario), scenario, 1, options, tmp_path / "out" / "b", "0.0.0-fake")
    record = json.loads((tmp_path / "out" / "b" / "S1-r1" / "session.json").read_text(encoding="utf-8"))
    assert any("git status names 1 test file" in w for w in record["warnings"])
    assert "claude_project_trusted" in record["harness_info"]
