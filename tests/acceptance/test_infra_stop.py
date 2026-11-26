"""Stop at the first infra event (v2.1 plan §2.4, WP21.2 AC; owner rule OD21-4 = a).

Pinned on real lines (``tests/fixtures/transcripts/infra/``: the ATV-36 logged-out runs of both harnesses, the 84
informational ``rate_limit_event`` lines of the WP11.5 Claude batch, a real Codex reconnect that gave up, the recorded
probes) and on forged ones per pattern. Through the real runner with the scripted agent (``fake_agent.py``): a forged
line stops the batch after that session (no next session, no re-run), the turn's process is killed at once, and
``acceptance run`` exits 3; the 84 allowed rate-limit events do not stop anything.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools.acceptance import infra, report, runner
from b1500_test_agent.devtools.acceptance.evidence import SESSION_FILE
from tests.acceptance.helpers import CLAUDE_DIR, CODEX_DIR, FIXTURES, make_repo, patch_fake_harness

INFRA = FIXTURES / "infra"
CONTRACT = FIXTURES / "contract"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# -- real lines ------------------------------------------------------------------------------------------------------


def test_the_84_allowed_rate_limit_events_never_stop() -> None:
    lines = _lines(INFRA / "claude-2.1.328-rate-limit-allowed.jsonl")
    assert len(lines) == 84 and all(json.loads(line)["rate_limit_info"]["status"] == "allowed" for line in lines)
    assert [infra.classify_stdout("claude", line) for line in lines] == [None] * 84


def test_atv36_claude_logged_out_stops_at_the_auth_error() -> None:
    lines = _lines(INFRA / "claude-2.1.328-logged-out.jsonl")
    events = infra.scan_turn("claude", lines, [], turn=1, exit_code=1, check_exit=True)
    assert [e.kind for e in events] == ["assistant_error", "result_error"]
    assert events[0].summary == "assistant error authentication_failed: Not logged in · Please run /login"
    assert "result success, is_error True: Not logged in" in events[1].describe()
    assert infra.completed("claude", lines)  # a failed completion, not a missing one


def test_atv36_codex_logged_out_stops_at_the_first_401_reconnect() -> None:
    out, err = _lines(INFRA / "codex-0.170.0-logged-out.jsonl"), _lines(INFRA / "codex-0.170.0-logged-out.stderr.txt")
    events = infra.scan_turn("codex", out, err, turn=1, exit_code=1, check_exit=True)
    assert events[0].kind == "error_event" and "Reconnecting... 2/5 (unexpected status 401" in events[0].summary
    kinds = {e.kind for e in events}
    assert {"error_event", "turn_failed", "network", "no_completion"} <= kinds
    assert any(e.stream == "stderr" and "failed to connect to Responses WebSocket" in e.line for e in events)


def test_a_real_reconnect_that_gave_up_stops() -> None:
    out = _lines(INFRA / "codex-0.170.0-reconnect-failed.jsonl")
    kinds = [e.kind for e in infra.scan_turn("codex", out, [])]
    assert kinds[0] == "error_event" and "turn_failed" in kinds


def test_strict_on_the_codex_background_errors_of_the_11_5_batch() -> None:
    """OD21-4 = a: the model-list refresh timeout and the connector's connection error on stderr stop a batch, though
    that WP11.5 session completed (one of 40)."""
    events = [infra.classify_text(line) for line in _lines(INFRA / "codex-0.170.0-stderr-11.5.txt")]
    assert events[0] is None  # "Reading additional input from stdin..."
    assert [e.kind for e in events[1:] if e] == ["network", "network"]


@pytest.mark.parametrize(("harness", "folder"), [("codex", CODEX_DIR), ("claude", CLAUDE_DIR)])
def test_recorded_probe_sessions_have_no_infra_event(harness: str, folder: Path) -> None:
    for name in ("probe-turn-1.jsonl", "probe-turn-2.jsonl"):
        assert infra.scan_turn(harness, _lines(folder / name), [], check_exit=True) == []


def test_real_11_5_sessions_and_an_execpolicy_rejection_have_none() -> None:
    claude = CONTRACT / "claude-2.1.328-S16" / "transcripts" / "turn-1.jsonl"
    codex = CONTRACT / "codex-0.170.0-S2" / "transcripts" / "turn-1.jsonl"
    assert infra.scan_turn("claude", _lines(claude), [], check_exit=True) == []
    assert infra.scan_turn("codex", _lines(codex), [], check_exit=True) == []
    rejected = _lines(CODEX_DIR / "rule-rejected.stderr.txt")  # quotes the agent's command: "atv5-forbidden"
    assert [infra.classify_text(line) for line in rejected] == [None, None]


# -- forged lines, one per pattern -----------------------------------------------------------------------------------


STOPS = [
    ("codex", '{"type":"turn.failed","error":{"message":"stream disconnected"}}', "turn_failed"),
    ("codex", '{"type":"error","message":"Reconnecting... 1/5 (stream disconnected before completion)"}',
     "error_event"),
    ("codex", ('{"type":"item.completed","item":{"id":"i","type":"error","message":"Falling back from WebSockets to '
              'HTTPS transport."}}'), "error_event"),
    ("claude", '{"type":"result","subtype":"success","is_error":true,"result":"API Error: 500"}', "result_error"),
    ("claude", '{"type":"result","subtype":"error_during_execution","is_error":false}', "result_error"),
    ("claude", '{"type":"result","subtype":"success","is_error":false,"api_error_status":529}', "result_error"),
    ("claude", '{"type":"assistant","error":"rate_limit","message":{"content":[{"type":"text","text":"x"}]}}',
     "assistant_error"),
    ("claude", '{"type":"system","subtype":"api_retry","attempt":1,"max_retries":10,"error_status":529}', "api_retry"),
    ("claude", '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","rateLimitType":"five_hour"}}',
     "rate_limit"),
    ("claude", '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning"}}', "rate_limit"),
    ("claude", '{"type":"error","error":{"type":"overloaded_error"}}', "error_event"),
]
STDERR_STOPS = [
    ("Error: 401 Unauthorized", "auth"),
    ("API Error: 403 {\"error\":{\"type\":\"forbidden\",\"message\":\"Request not allowed\"}}", "auth"),
    ("Invalid API key · Please run /login", "auth"),
    ("ERROR codex_core: OAuth token has expired; please log in again", "auth"),
    ("unexpected status 429 Too Many Requests", "http_status"),
    ("ERROR codex_api: unexpected status 503 Service Unavailable", "http_status"),
    ("You've hit your usage limit. Upgrade or try again later.", "http_status"),
    ("error: dns error: failed to lookup address information: nodename nor servname provided", "network"),
    ("Error: getaddrinfo ENOTFOUND api.anthropic.com", "network"),
    ("ERROR: connection refused (os error 61)", "network"),
    ("ERROR codex_models_manager::manager: failed to refresh available models: request timed out", "network"),
    ("Unable to connect to API: Can't reach the API server", "network"),
]
QUIET = [
    ("codex", '{"type":"turn.completed","usage":{"input_tokens":1}}'),
    ("codex", ('{"type":"item.completed","item":{"id":"c","type":"command_execution","command":"echo 401 timed out",'
              '"exit_code":1,"status":"failed"}}')),
    ("claude", '{"type":"result","subtype":"success","is_error":false,"result":"done"}'),
    ("claude", '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","rateLimitType":"five_hour"}}'),
    ("claude", '{"type":"system","subtype":"hook_response","hook_name":"PreToolUse:Bash","exit_code":0}'),
    ("claude", ('{"type":"user","message":{"content":[{"type":"tool_result","content":"HTTP 500 from the DUT log",'
               '"is_error":true}]}}')),
]


@pytest.mark.parametrize(("harness", "line", "kind"), STOPS)
def test_forged_stdout_events_stop(harness: str, line: str, kind: str) -> None:
    event = infra.classify_stdout(harness, line, turn=2)
    assert event is not None and event.kind == kind and event.stream == "stdout" and event.turn == 2
    assert event.line == line  # the raw line is reported


@pytest.mark.parametrize(("line", "kind"), STDERR_STOPS)
def test_forged_stderr_lines_stop(line: str, kind: str) -> None:
    event = infra.classify_text(line)
    assert event is not None and event.kind == kind and event.line == line


@pytest.mark.parametrize(("harness", "line"), QUIET)
def test_normal_events_never_stop(harness: str, line: str) -> None:
    assert infra.classify_stdout(harness, line) is None


@pytest.mark.parametrize("line", ["Reading additional input from stdin...", "",
                                  "2026-11-25T20:51:08Z  INFO codex_core: request timed out, retrying later",
                                  ('2026-11-17T16:20:59Z ERROR codex_core::tools::router: error=exec_command failed: '
                                  'CreateProcess { message: "Rejected(\\"`curl -s 401`\\")" }')])
def test_quiet_stderr_lines(line: str) -> None:
    assert infra.classify_text(line) is None


def test_the_watcher_reads_growing_files_line_by_line(tmp_path: Path) -> None:
    out, err = tmp_path / "turn-1.jsonl", tmp_path / "turn-1.stderr.txt"
    out.write_text('{"type":"thread.started","thread_id":"t"}\n{"type":"turn.fa', encoding="utf-8")
    err.write_text("", encoding="utf-8")
    watcher = infra.InfraWatcher("codex", out, err, turn=1)
    assert watcher.poll() is None  # half a line is not read yet
    with out.open("a", encoding="utf-8") as handle:
        handle.write('iled","error":{"message":"x"}}\n')
    event = watcher.poll()
    assert event is not None and event.kind == "turn_failed" and watcher.poll() is event


def test_a_turn_without_completion_is_a_stop_unless_it_timed_out() -> None:
    event = infra.exit_event("codex", ['{"type":"thread.started","thread_id":"t"}'], ["boom"], 1, turn=1)
    assert event is not None and event.kind == "no_completion" and "boom" in event.line
    assert infra.exit_event("claude", ['{"type":"result","subtype":"success"}'], [], 0) is None


# -- through the runner ----------------------------------------------------------------------------------------------


def _scenario(folder: Path, sid: str) -> Path:
    path = folder / f"{sid}.yaml"
    path.write_text(f"id: {sid}\ntitle: infra stop {sid}\nsafety: false\nturns:\n  - prompt: hello\n"
                    "    timeout_s: 120\ngraders:\n  - {type: runs, max: 0}\n", encoding="utf-8")
    return path


def _batch(tmp: Path, mp: pytest.MonkeyPatch, harness: str, actions: str, *, infra_stop: bool = True) \
        -> tuple[runner.BatchResult, float]:
    repo = make_repo(tmp)
    script = tmp / "agent.yaml"
    script.write_text(f"turns:\n  1:\n{actions}", encoding="utf-8")
    patch_fake_harness(mp, script, tmp=tmp)
    files = [_scenario(tmp, "TA"), _scenario(tmp, "TB")]
    options = runner.RunOptions(harness=harness, repo_root=repo, out_dir=tmp / "out", infra_stop=infra_stop)  # type: ignore[arg-type]
    started = time.monotonic()
    return runner.run_batch(files, options), time.monotonic() - started


FORGED = {"codex": "    - {raw: '{\"type\":\"turn.failed\",\"error\":{\"message\":\"unexpected status 401\"}}'}\n",
          "claude": "    - {stderr: 'API Error: 429 Too Many Requests'}\n"}


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_a_forged_infra_line_stops_the_batch_after_that_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                harness: str) -> None:
    actions = "    - {say: working}\n" + FORGED[harness] + "    - {sleep: 60}\n    - {say: never}\n"
    batch, took = _batch(tmp_path, monkeypatch, harness, actions)
    assert took < 45  # the watcher killed the sleeping turn; it did not wait for the end
    assert [s.scenario_id for s in batch.sessions] == ["TA"]  # no next session and no re-run of the failed one
    assert batch.skipped == {"TB": "not started: the batch stopped at an infra event"}
    stop = batch.infra_stop
    assert stop is not None and stop.scenario_id == "TA" and stop.rep == 1 and stop.session == "TA-r1"
    assert stop.event.kind == ("turn_failed" if harness == "codex" else "http_status")
    record = json.loads((Path(batch.sessions[0].session_dir) / SESSION_FILE).read_text(encoding="utf-8"))
    assert record["infra_stopped"] is True and "infra stop in turn 1" in record["error"]
    assert record["turns"][0]["infra_event"]["line"] == stop.event.line
    grade = batch.sessions[0]
    assert not grade.passed and grade.infra_event == stop.event
    assert any("stopped at an infra event" in d for d in grade.results[0].details)
    text = report.render([batch])
    assert "**Infra stop** (owner rule: stop, no retries): TA-r1:" in text and "| INCOMPLETE |" in text
    assert "Not started: TB (not started: the batch stopped at an infra event)" in text


def test_the_84_allowed_rate_limit_events_do_not_stop_a_batch(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    lines = _lines(INFRA / "claude-2.1.328-rate-limit-allowed.jsonl")
    actions = "".join(f"    - {{raw: {json.dumps(line)}}}\n" for line in lines) + "    - {say: done}\n"
    batch, _ = _batch(tmp_path, monkeypatch, "claude", actions)
    assert batch.infra_stop is None and [s.scenario_id for s in batch.sessions] == ["TA", "TB"]
    assert all(s.passed for s in batch.sessions), [r.message for s in batch.sessions for r in s.failures()]


def test_a_harness_that_exits_without_completing_stops_the_batch(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    batch, _ = _batch(tmp_path, monkeypatch, "codex", "    - {stderr: 'Error: something broke'}\n    - {exit: 1}\n")
    assert batch.infra_stop is not None and batch.infra_stop.event.kind == "no_completion"
    assert "last stderr line: Error: something broke" in batch.infra_stop.event.line
    assert len(batch.sessions) == 1


def test_no_infra_stop_is_the_offline_tests_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    batch, _ = _batch(tmp_path, monkeypatch, "codex", "    - {stream_error: 'Reconnecting... 1/5 (x)'}\n"
                                                      "    - {say: ok}\n", infra_stop=False)
    assert batch.infra_stop is None and len(batch.sessions) == 2 and all(s.passed for s in batch.sessions)


def test_acceptance_run_exits_3_at_an_infra_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    script = tmp_path / "agent.yaml"
    script.write_text("turns:\n  1:\n" + FORGED["codex"], encoding="utf-8")
    patch_fake_harness(monkeypatch, script, tmp=tmp_path)
    scenario = _scenario(tmp_path, "TA")
    result = CliRunner().invoke(app, ["dev", "acceptance", "run", "--harness", "codex", "--scenario", str(scenario),
                                      "--repo", str(repo), "--out", str(tmp_path / "out")])
    assert result.exit_code == 3, result.output
    assert "INFRA STOP at TA-r1" in result.output and "no retries" in result.output
