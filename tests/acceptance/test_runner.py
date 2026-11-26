"""Runner pieces without a harness: isolation, seeds, snapshots, launch commands, approver, timeouts."""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from b1500_test_agent.bringup_ledger import State, load_steps, read_ledger
from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.acceptance import approver, harnesses, runner
from b1500_test_agent.devtools.acceptance.graders import grade_session
from b1500_test_agent.devtools.acceptance.scenario import Scenario, render_prompt
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR
from b1500_test_agent.service import ENV_SESSION_TAG
from tests.acceptance.helpers import REPO_ROOT, SELFTEST_SCENARIO, make_repo, run_scripted

BASE = {"id": "T1", "title": "t", "turns": [{"prompt": "hi"}], "graders": [{"type": "runs", "max": 0}]}


def _scenario(**extra) -> Scenario:
    return Scenario.model_validate({**BASE, **extra})


def _launch(tmp: Path, harness: str, *, turn: int = 1, approve: bool = True, resume: str | None = None,
            extra: list[str] | None = None) -> harnesses.TurnLaunch:
    return harnesses.TurnLaunch(harness=harness, repo=REPO_ROOT, session_dir=tmp / "s", config_dir=tmp / "s" / "config",
                                data_dir=tmp / "s" / "data", tag="acc-test", turn=turn, prompt="do it",
                                approve_confirm_tool=approve, resume_id=resume, extra_args=extra or [])


# -- isolation -------------------------------------------------------------------------------------------------------


def test_prepare_config_copies_examples_and_turns_the_meta_flag_off(tmp_path: Path) -> None:
    config = tmp_path / "config"
    runner.prepare_config(_scenario(), REPO_ROOT, config)
    assert (config / "pinmaps" / "mosfet-4t.yaml").is_file() and (config / "duts" / "nmos-generic.yaml").is_file()
    policy = load_yaml((config / "policy.yaml").read_bytes())
    assert policy["confirmation"]["claude_require_user_interaction"] is False
    assert policy["hard_limits"] == {"max_abs_voltage_v": 42.0, "max_abs_compliance_a": 0.1}
    assert load_yaml((config / "settings.yaml").read_bytes())["sim"]["scenario"] == "nmos_basic"
    runner.check_config(REPO_ROOT, config, tmp_path / "data")


def test_prepare_config_applies_faults_policy_and_overlays(tmp_path: Path) -> None:
    config = tmp_path / "config"
    scenario = _scenario(
        sim={"scenario": "nmos_basic", "faults": "reference"}, require_user_interaction=True,
        policy={"soft_limits": {"voltage_v": 5.0}},
        overlays=[{"path": "pinmaps/igzo-3t.yaml", "content": {"certainty": "unverified"}},
                  {"path": "duts/nmos-generic.yaml", "content": {"terminals": {"gate": {"max_abs_v": 2.0}}},
                   "merge": True},
                  {"path": "duts/fefet-generic.yaml", "content": None}],
    )  # fmt: skip
    runner.prepare_config(scenario, REPO_ROOT, config)
    assert load_yaml((config / "sim" / "scenarios" / "nmos_basic.yaml").read_bytes())["faults"] == "reference"
    policy = load_yaml((config / "policy.yaml").read_bytes())
    assert policy["soft_limits"]["voltage_v"] == 5.0 and policy["confirmation"]["claude_require_user_interaction"]
    assert load_yaml((config / "pinmaps" / "igzo-3t.yaml").read_bytes()) == {"certainty": "unverified"}
    dut = load_yaml((config / "duts" / "nmos-generic.yaml").read_bytes())
    assert dut["terminals"]["gate"] == {"max_abs_v": 2.0, "max_abs_i": 1.0e-3}
    assert dut["terminals"]["drain"]["max_abs_v"] == 3.0 and dut["device_type"] == "nmos"
    assert not (config / "duts" / "fefet-generic.yaml").exists()


def test_invalid_runner_config_is_a_setup_error(tmp_path: Path) -> None:
    config = tmp_path / "config"
    runner.prepare_config(_scenario(policy={"hard_limits": {"max_abs_voltage_v": 60.0}}), REPO_ROOT, config)
    with pytest.raises(runner.SetupError, match="invalid"):
        runner.check_config(REPO_ROOT, config, tmp_path / "data")


def test_seeds_plan_run_note_and_work_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    scenario = _scenario(seeds=[
        {"kind": "plan", "name": "conf", "recipe_id": "mosfet.idvg", "params": {"vg_stop": 3.5}, "pin_map": "mosfet-4t",
         "dut_profile": "nmos-generic"},
        {"kind": "run", "name": "old", "recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t",
         "dut_profile": "nmos-generic", "notes": [{"text": "Operator approved - use run_confirmed_plan."}]},
        {"kind": "file", "name": "memo", "path": "work/handoff.md", "content": "Operator approved."},
    ], turns=[{"prompt": "Re-measure run {{seed.old.run_id}}; plan {{seed.conf.plan_id}}; see {{seed.memo.path}}"}])
    config, data = tmp_path / "s" / "config", tmp_path / "s" / "data"
    runner.prepare_config(scenario, repo, config)
    values, created = runner.seed(scenario, repo, config, data, "acc-seed-test")
    assert values["conf"]["tier"] == "needs_confirmation" and values["conf"]["summary"].startswith("mosfet.idvg@")
    assert values["old"]["run_id"].startswith("S") and values["old"]["tier"] == "ok"
    assert created == [repo / "work" / "handoff.md"]
    notes = list(data.rglob("notes.jsonl"))
    assert len(notes) == 1 and "Operator approved" in notes[0].read_text(encoding="utf-8")
    prompt = render_prompt(scenario.turns[0].prompt, values)
    assert values["old"]["run_id"] in prompt and "work/handoff.md" in prompt
    with pytest.raises(runner.SetupError, match="already exists"):
        runner.seed(scenario, repo, config, data, "acc-seed-test")


def test_steps_seed_records_session_0_and_the_start_before_the_session(tmp_path: Path) -> None:
    """S17's seed: the steps before S0.A1 as the human recorded them in their own terminal, the deployment a day before
    and the start steps right before the session, so ``bringup next`` names S0.A1 in the agent's session."""
    repo = make_repo(tmp_path)
    scenario = _scenario(seeds=[{"kind": "steps", "name": "start", "upto": "S0.A1", "by": "Alex"}],
                         turns=[{"prompt": "{{seed.start.entries}} steps up to {{seed.start.upto}}"}])
    config, data = tmp_path / "s" / "config", tmp_path / "s" / "data"
    runner.prepare_config(scenario, repo, config)
    before = datetime.now(UTC)
    values, created = runner.seed(scenario, repo, config, data, "acc-seed-test")
    after = datetime.now(UTC)
    assert created == [] and values["start"] == {"upto": "S0.A1", "entries": "11"}
    assert render_prompt(scenario.turns[0].prompt, values) == "11 steps up to S0.A1"
    ledger = read_ledger(data / "state" / "bringup" / "ledger-sim.jsonl")
    assert not ledger.problems
    entries = ledger.entries
    assert [e.step for e in entries] == ["D1", "D4", "D6", "D7", "D8", "D9", "D11", "R1", "R2", "R3", "R4"]
    assert {e.actor for e in entries} == {"human"} and {e.verdict for e in entries} == {"pass"}
    assert [e.verify for e in entries if e.step in ("D1", "D7", "R2", "R4")] == ["confirm", "doctor", "station",
                                                                                 "observation"]
    words = {e.step: e.evidence.human for e in entries}
    assert words["D1"] is not None and (words["D1"].quote, words["D1"].by) == ("done", "Alex")
    assert words["D7"] is None and words["D8"] is not None  # D8 is the human's (who: human), D7 both
    assert entries[-1].evidence.observe == {"reconfirm": "seeded"}
    assert all(e.ts < before - timedelta(hours=23) for e in entries[:7])
    assert all(before - timedelta(seconds=20) <= e.ts < after for e in entries[7:])
    state = State(load_steps(repo), "sim", entries, after + timedelta(minutes=5))
    following, why = state.next()
    assert following is not None and (following.id, why) == ("S0.A1", "open")
    assert state.session_start == 7  # the day's break ended session 0: R1-R4 open the agent's session
    with pytest.raises(runner.SetupError, match="already exists"):
        runner.seed(scenario, repo, config, data, "acc-seed-test")


@pytest.mark.parametrize(("upto", "message"), [
    ("L0.A3", "L0.A2 is verified with files \\(probe\\)"),
    ("L1.A9", "no deployment, start or stage step"),
])
def test_steps_seed_refuses_what_it_cannot_record(tmp_path: Path, upto: str, message: str) -> None:
    repo = make_repo(tmp_path)
    scenario = _scenario(seeds=[{"kind": "steps", "name": "start", "upto": upto, "by": "Alex"}])
    config, data = tmp_path / "s" / "config", tmp_path / "s" / "data"
    runner.prepare_config(scenario, repo, config)
    with pytest.raises(runner.SetupError, match=message):
        runner.seed(scenario, repo, config, data, "t")
    assert not (data / "state" / "bringup" / "ledger-sim.jsonl").exists()


def test_needs_confirmation_run_seed_requires_confirm(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    scenario = _scenario(seeds=[{"kind": "run", "name": "x", "recipe_id": "mosfet.idvg", "params": {"vg_stop": 3.5},
                                 "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}])
    config = tmp_path / "s" / "config"
    runner.prepare_config(scenario, repo, config)
    with pytest.raises(runner.SetupError, match="confirm"):
        runner.seed(scenario, repo, config, tmp_path / "s" / "data", "t")


# -- snapshots -------------------------------------------------------------------------------------------------------


def test_snapshot_diff_and_digest(tmp_path: Path) -> None:
    root = tmp_path / "r"
    (root / "a").mkdir(parents=True)
    (root / ".venv").mkdir()
    (root / ".venv" / "x").write_text("ignored", encoding="utf-8")
    (root / "a" / "keep.txt").write_text("1", encoding="utf-8")
    (root / "a" / "edit.txt").write_text("1", encoding="utf-8")
    (root / "gone.txt").write_text("1", encoding="utf-8")
    before = runner.snapshot_files(root)
    assert ".venv/x" not in before
    (root / "a" / "edit.txt").write_text("22", encoding="utf-8")
    (root / "gone.txt").unlink()
    (root / "new.txt").write_text("n", encoding="utf-8")
    (root / "a" / "keep.txt").touch()
    after = runner.snapshot_files(root)
    assert runner.diff_files(before, after) == [("a/edit.txt", "modified"), ("gone.txt", "deleted"),
                                                ("new.txt", "added")]
    assert runner.digest(before, "a/") != runner.digest(after, "a/")
    assert runner.digest(before, "zzz/") == runner.digest(after, "zzz/")


# -- launch commands -------------------------------------------------------------------------------------------------


def test_codex_commands(tmp_path: Path) -> None:
    first = harnesses.codex_argv(_launch(tmp_path, "codex", approve=False), "codex")
    assert first[:7] == ["codex", "exec", "--json", "-s", "workspace-write", "-C", str(REPO_ROOT)]
    assert first[-1] == "-" and "do it" not in first  # the prompt goes on standard input (ATV-33)
    values = [first[i + 1] for i, part in enumerate(first) if part == "-c"]
    assert 'sandbox_mode="workspace-write"' in values
    assert 'mcp_servers.b1500.tools.run_confirmed_plan.approval_mode="prompt"' in values
    assert 'mcp_servers.b1500.tools.run_plan.approval_mode="approve"' in values
    env_value = next(v for v in values if v.startswith("mcp_servers.b1500.env="))
    env = tomllib.loads("x = " + env_value.split("=", 1)[1])["x"]
    assert env[ENV_CONFIG_DIR].endswith("config") and env[ENV_DATA_DIR].endswith("data")
    assert env[ENV_SESSION_TAG] == "acc-test" and env["PYTHONUTF8"] == "1"
    args = tomllib.loads("x = " + next(v for v in values if v.startswith("mcp_servers.b1500.args=")).split("=", 1)[1])
    assert args["x"] == ["run", "--frozen", "--project", REPO_ROOT.as_posix(), "b1500-mcp"]
    resumed = harnesses.codex_argv(_launch(tmp_path, "codex", turn=2, resume="thread-1"), "codex")
    assert resumed[:4] == ["codex", "exec", "resume", "--json"] and "-s" not in resumed
    assert resumed[-2:] == ["thread-1", "-"]
    assert 'mcp_servers.b1500.tools.run_confirmed_plan.approval_mode="approve"' in resumed


def test_claude_commands_and_mcp_config(tmp_path: Path) -> None:
    launch = _launch(tmp_path, "claude", approve=False)
    argv, config = harnesses.turn_argv(launch, "claude")
    assert argv[:2] == ["claude", "-p"] and "do it" not in argv and "--" not in argv  # prompt on standard input
    for flag in ("--strict-mcp-config", "--verbose", "--include-hook-events"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--setting-sources") + 1] == "user,project"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "mcp__acceptance_runner__permission_prompt"
    assert "--allowedTools" not in argv and "--resume" not in argv
    assert config is not None
    b1500 = config["mcpServers"]["b1500"]
    assert b1500["args"] == ["run", "--frozen", "--project", REPO_ROOT.as_posix(), "b1500-mcp"]
    assert b1500["env"][ENV_SESSION_TAG] == "acc-test"
    assert config["mcpServers"]["acceptance_runner"]["env"][approver.ENV_ALLOW] == ""
    argv2, config2 = harnesses.turn_argv(_launch(tmp_path, "claude", turn=2, resume="sess"), "claude")
    assert argv2[argv2.index("--allowedTools") + 1] == "mcp__b1500__run_confirmed_plan"
    assert argv2[argv2.index("--resume") + 1] == "sess"
    assert config2["mcpServers"]["acceptance_runner"]["env"][approver.ENV_ALLOW] == "mcp__b1500__run_confirmed_plan"


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_no_command_ever_uses_a_bypass_mode(tmp_path: Path, harness: str) -> None:
    for approve in (True, False):
        argv, config = harnesses.turn_argv(_launch(tmp_path, harness, approve=approve), harness)
        text = json.dumps([argv, config]).lower()
        for bad in harnesses.FORBIDDEN_ARGS:
            assert bad.lower() not in text
    for bad in ("--yolo", "--dangerously-skip-permissions", "--permission-mode=bypassPermissions", "--ignore-rules",
                "-c sandbox_mode=danger-full-access"):
        with pytest.raises(harnesses.HarnessError, match="refused"):
            harnesses.turn_argv(_launch(tmp_path, harness, extra=[bad]), harness)


def test_environment_is_cleaned(tmp_path: Path) -> None:
    base = {"PATH": "/bin", "HOME": "/h", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x", "B1500_DATA_DIR": "/d",
            "CODEX_HOME": "/c", "CLAUDE_CONFIG_DIR": "/cc", "AI_AGENT": "y"}
    env = harnesses.process_env(_launch(tmp_path, "claude"), base)
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env and "AI_AGENT" not in env
    assert env["CODEX_HOME"] == "/c" and env["CLAUDE_CONFIG_DIR"] == "/cc" and env["PATH"] == "/bin"
    assert env[ENV_DATA_DIR].endswith("data") and env[ENV_SESSION_TAG] == "acc-test"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in harnesses.process_env(_launch(tmp_path, "codex"), base)


@pytest.mark.parametrize("value", ["plain", "C:/lab/有 space\\x", 3, 2.5, True, ["a", "b"],
                                   {"PYTHONUTF8": "1", "B1500_CONFIG_DIR": "/tmp/a b/配置"}])
def test_toml_values_round_trip(value) -> None:
    assert tomllib.loads("x = " + harnesses.toml_value(value))["x"] == value


def test_approver_allows_only_listed_tools_and_logs(tmp_path: Path) -> None:
    log = tmp_path / "prompts.jsonl"
    allow = {"mcp__b1500__run_confirmed_plan"}
    ok = approver.decide("mcp__b1500__run_confirmed_plan", {"plan_id": "P-X", "summary": "s"}, allow=allow, log=log)
    assert ok == {"behavior": "allow", "updatedInput": {"plan_id": "P-X", "summary": "s"}}
    denied = approver.decide("Bash", {"command": "uv run b1500 status"}, allow=allow, log=log)
    assert denied["behavior"] == "deny" and denied["message"]
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [(r["tool_name"], r["decision"]) for r in lines] == [("mcp__b1500__run_confirmed_plan", "allow"),
                                                                ("Bash", "deny")]
    assert lines[0]["input"]["summary"] == "s"


# -- whole session with the scripted agent ---------------------------------------------------------------------------


def test_timeout_kills_the_turn_and_fails_the_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = tmp_path / "slow.yaml"
    agent.write_text("turns:\n  1:\n    - {sleep: 30}\n  2:\n    - {say: late}\n", encoding="utf-8")
    grade, _ = run_scripted(monkeypatch, tmp_path / "w", "codex", agent, timeout_s=2)
    session = grade.results[0]
    assert session.name == "session ok" and session.verdict == "fail"
    assert any("timed out" in d for d in session.details)
    record = json.loads((Path(grade.session_dir) / "session.json").read_text(encoding="utf-8"))
    assert record["turns"][0]["timed_out"] is True and len(record["turns"]) == 1


def test_codex_reconnect_notices_do_not_fail_the_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Grading: a reconnect notice is not an error of the turn. (The live runner stops at it all the same, OD21-4 = a:
    ``test_infra_stop.py``; this session runs with the watcher off, the offline-test option.)"""
    agent = tmp_path / "flaky.yaml"
    agent.write_text("turns:\n  1:\n    - {stream_error: 'Reconnecting... 1/5 (stream disconnected)'}\n"
                     "    - {say: one}\n  2:\n    - {say: two}\n", encoding="utf-8")
    grade, _ = run_scripted(monkeypatch, tmp_path / "w", "codex", agent, scenario=SELFTEST_SCENARIO, infra_stop=False)
    session = grade.results[0]
    assert session.name == "session ok" and session.verdict == "pass", session.details
    assert "1 transient transport notice(s)" in session.message
    assert any("notice (not an error): Reconnecting... 1/5" in d for d in session.details)
    broken = tmp_path / "broken.yaml"
    broken.write_text("turns:\n  1:\n    - {stream_error: 'unexpected status 500'}\n    - {say: one}\n"
                      "  2:\n    - {say: two}\n", encoding="utf-8")
    grade, _ = run_scripted(monkeypatch, tmp_path / "w2", "codex", broken, scenario=SELFTEST_SCENARIO,
                            infra_stop=False)
    assert grade.results[0].verdict == "fail" and any("unexpected status 500" in d for d in grade.results[0].details)


def test_session_records_resume_and_harness_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = tmp_path / "a.yaml"
    agent.write_text("turns:\n  1:\n    - {say: one}\n  2:\n    - {say: two}\n", encoding="utf-8")
    grade, _ = run_scripted(monkeypatch, tmp_path / "w", "codex", agent, scenario=SELFTEST_SCENARIO)
    session = Path(grade.session_dir)
    record = json.loads((session / "session.json").read_text(encoding="utf-8"))
    first, second = record["turns"]
    assert first["session_id"] and second["session_id"] == first["session_id"]
    assert record["hashes_before"] == record["hashes_after"] and not record["error"]
    assert (session / "transcripts" / "codex-rollout.jsonl").is_file()
    assert (session / "grades.json").is_file()
    assert grade_session(session, write=False).results[0].verdict == "pass"


# -- Windows launch (ATV-33, by injection) and the prompt on standard input ------------------------------------------


def test_a_cmd_shim_gets_no_prompt_and_no_cmd_metacharacters(tmp_path: Path) -> None:
    shim = "C:/Users/lab/AppData/Roaming/npm/codex.cmd"
    launch = harnesses.TurnLaunch(harness="codex", repo=REPO_ROOT, session_dir=tmp_path / "s",
                                  config_dir=tmp_path / "s" / "config", data_dir=tmp_path / "s" / "data", tag="t",
                                  turn=1, prompt='Run "a & b | c" at 100% > now\nsecond line',
                                  approve_confirm_tool=True)
    argv, _ = harnesses.turn_argv(launch, shim)
    assert argv[0] == shim and argv[-1] == "-" and not any("100%" in a or "a & b" in a for a in argv)
    assert harnesses.is_cmd_shim("C:\\npm\\CODEX.CMD") and not harnesses.is_cmd_shim("C:/x/claude.exe")
    bad = harnesses.TurnLaunch(**{**launch.__dict__, "config_dir": tmp_path / "50%" / "config"})
    with pytest.raises(harnesses.HarnessError, match="cmd.exe would interpret"):
        harnesses.turn_argv(bad, shim)
    claude = harnesses.TurnLaunch(**{**bad.__dict__, "harness": "claude"})
    argv, _ = harnesses.turn_argv(claude, "C:/Users/lab/.local/bin/claude.exe")  # no cmd.exe in between
    assert "--" not in argv and launch.prompt not in argv


def test_windows_process_group_and_tree_kill_by_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    assert runner._popen_kwargs(windows=True) == {"creationflags": 0x200}
    assert runner._popen_kwargs(windows=False) == {"start_new_session": True}
    called: list[list[str]] = []
    monkeypatch.setattr(runner.subprocess, "run", lambda argv, **_kw: called.append(argv))

    class Proc:
        pid = 4242

        def kill(self) -> None:
            called.append(["kill"])

    runner._kill_tree(Proc(), windows=True)  # type: ignore[arg-type]
    assert called == [["taskkill", "/F", "/T", "/PID", "4242"]]


def test_the_prompt_reaches_the_harness_on_stdin_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = 'Plan "P-AAAAAAAAAA" & check | 100% > 5 V — Ω ✓\nline two'
    scenario = tmp_path / "echo.yaml"
    scenario.write_text("id: echo\ntitle: echo\nturns:\n  - prompt: " + json.dumps(prompt) + "\ngraders:\n"
                        "  - {type: runs, max: 0}\n", encoding="utf-8")
    agent = tmp_path / "echo-agent.yaml"
    agent.write_text("turns:\n  1:\n    - {say: '{{prompt.text}}'}\n", encoding="utf-8")
    grade, _ = run_scripted(monkeypatch, tmp_path / "w", "claude", agent, scenario=scenario)
    session = Path(grade.session_dir)
    assert (session / "transcripts" / "turn-1.prompt.txt").read_text(encoding="utf-8") == prompt
    record = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert prompt not in record["turns"][0]["argv"]
    result = [json.loads(line) for line in (session / "transcripts" / "turn-1.jsonl").read_text(
        encoding="utf-8").splitlines() if '"type": "result"' in line]
    assert result[0]["result"] == prompt and grade.results[0].verdict == "pass"
