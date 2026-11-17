"""Transcript parsers on the recorded real sessions (tests/fixtures/transcripts/, versions in meta.json)."""

from __future__ import annotations

import json
from datetime import datetime

from b1500_test_agent.devtools.acceptance.transcripts import (
    parse_claude,
    parse_codex,
    parse_codex_rollout,
    sanitize_lines,
    split_tool_name,
)
from tests.acceptance.helpers import CLAUDE_DIR, CODEX_DIR


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_codex_turn_with_denied_confirm_tool() -> None:
    t = parse_codex(_lines(CODEX_DIR / "probe-turn-1.jsonl"), turn=1)
    assert t.session_id == "01a1ea4b-00d8-7190-963d-569ff4a27d89"
    assert t.completed and not t.errors
    calls = {c.tool: c for c in t.tool_calls}
    assert calls["station_status"].status == "completed"
    assert calls["station_status"].server == "b1500"
    assert calls["station_status"].result["backend"] == "sim"
    confirm = calls["run_confirmed_plan"]
    assert confirm.status == "denied"
    assert "approval policy is never" in confirm.error
    assert confirm.arguments == {"plan_id": "P-AAAAAAAAAA", "summary": "acceptance probe"}
    assert confirm.plan_id == "P-AAAAAAAAAA"
    assert [s.command for s in t.shell] == ["/bin/zsh -lc pwd"]
    assert t.shell[0].exit_code == 0 and t.shell[0].output.startswith("<REPO>")
    assert [(f.path, f.kind, f.tool) for f in t.files] == [("<REPO>/work/acceptance-probe.txt", "add", "apply_patch")]
    assert t.final_answer.startswith("Backend: sim")


def test_codex_resumed_turn_reaches_the_server() -> None:
    t = parse_codex(_lines(CODEX_DIR / "probe-turn-2.jsonl"), turn=2)
    assert t.session_id == "01a1ea4b-00d8-7190-963d-569ff4a27d89"
    (call,) = t.tool_calls
    assert call.turn == 2 and call.status == "completed"
    assert call.result["error_code"] == "unknown_plan" and call.result["status"] == "refused"


def test_codex_rule_rejection_is_recovered_from_stderr() -> None:
    stderr = (CODEX_DIR / "rule-rejected.stderr.txt").read_text(encoding="utf-8")
    t = parse_codex(_lines(CODEX_DIR / "rule-rejected.jsonl"), stderr=stderr)
    assert not any("atv5-forbidden" in s.command for s in t.shell if s.status != "rejected")
    (rejected,) = [s for s in t.shell if s.status == "rejected"]
    assert rejected.command == "/bin/zsh -lc 'echo atv5-forbidden now'"
    assert "project rules are active" in rejected.output


def test_codex_rollout_gives_tool_inputs_and_patch_writes() -> None:
    bounds = [("2026-11-17T16:15:45+00:00", "2026-11-17T16:16:45+00:00"),
              ("2026-11-17T16:17:00+00:00", "2026-11-17T16:17:27+00:00")]
    windows = [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in bounds]

    def turn_of(ts):
        return next((i for i, (a, b) in enumerate(windows, start=1) if ts and a <= ts <= b), None)

    inputs, writes, contexts = parse_codex_rollout(_lines(CODEX_DIR / "probe-rollout.jsonl"), turn_of)
    assert {i.tool for i in inputs} == {"exec"}
    assert [i.turn for i in inputs].count(2) == 1
    assert any("exec_command" in i.text and "pwd" in i.text for i in inputs)
    assert any("mcp__b1500__run_confirmed_plan" in i.text for i in inputs)
    assert [(w.path, w.kind) for w in writes] == [("<REPO>/work/acceptance-probe.txt", "add")]
    assert [c["sandbox_policy"]["type"] for c in contexts] == ["workspace-write", "workspace-write"]
    assert {c["approval_policy"] for c in contexts} == {"never"}


def test_claude_turn_without_approval() -> None:
    t = parse_claude(_lines(CLAUDE_DIR / "probe-turn-1.jsonl"), turn=1)
    assert t.session_id == "7bd19fdf-9044-417d-a4f5-2818e2a704b9"
    assert t.completed and t.info["permissionMode"] == "default"
    by_tool = {(c.server, c.tool): c for c in t.tool_calls}
    assert by_tool[("b1500", "station_status")].status == "completed"
    assert by_tool[("b1500", "station_status")].result["simulated"] is True
    confirm = by_tool[("b1500", "run_confirmed_plan")]
    assert confirm.status == "denied" and "haven't granted" in confirm.error
    assert by_tool[(None, "ToolSearch")].status == "completed"
    assert [(s.command, s.status) for s in t.shell] == [("pwd", "completed")]
    (write,) = t.files
    assert write.status == "denied" and write.content == "probe\n" and write.path.endswith("work/acceptance-probe.txt")
    assert "Backend: `sim`" in t.final_answer
    assert any(i.tool == "Write" and "probe" in i.text for i in t.tool_inputs)


def test_claude_allowed_tools_does_not_beat_the_ask_rule() -> None:
    t = parse_claude(_lines(CLAUDE_DIR / "allowedtools-ask-denied.jsonl"), turn=2)
    (call,) = [c for c in t.tool_calls if c.server == "b1500"]
    assert call.tool == "run_confirmed_plan" and call.status == "denied"


def test_claude_turn_approved_by_the_runner() -> None:
    t = parse_claude(_lines(CLAUDE_DIR / "probe-turn-2.jsonl"), turn=2)
    (call,) = [c for c in t.tool_calls if c.server == "b1500"]
    assert call.status == "completed" and call.result["error_code"] == "unknown_plan"
    assert call.plan_id == "P-AAAAAAAAAA"


def test_claude_flagged_tool_is_refused_even_when_allowed() -> None:
    for name, text in (("atv12-flag-denied.jsonl", "requires permission"),
                       ("atv12-flag-prompt-tool.jsonl", "requires user interaction")):
        t = parse_claude(_lines(CLAUDE_DIR / name))
        (call,) = [c for c in t.tool_calls if c.tool == "run_confirmed_plan"]
        assert call.status in ("denied", "failed") and text in call.error


def test_split_tool_name() -> None:
    assert split_tool_name("mcp__b1500__validate_plan") == ("b1500", "validate_plan")
    assert split_tool_name("mcp__acceptance_runner__permission_prompt") == ("acceptance_runner", "permission_prompt")
    assert split_tool_name("Bash") == (None, "Bash")
    assert split_tool_name("mcp__broken") == (None, "mcp__broken")


def test_parsers_tolerate_garbage_and_truncation() -> None:
    started = ('{"type":"item.started","item":{"id":"i","type":"mcp_tool_call","server":"b1500",'
               '"tool":"run_plan","arguments":{"plan_id":"P-X"},"status":"in_progress"}}')
    t = parse_codex(["not json", '{"type":"thread.started","thread_id":"x"}', started])
    assert t.errors and not t.completed
    assert t.tool_calls[0].status == "pending"
    use = ('{"type":"assistant","message":{"content":[{"type":"tool_use","id":"u1","name":"Bash",'
           '"input":{"command":"ls"}}]}}')
    c = parse_claude([use])
    assert c.shell[0].status == "pending" and not c.completed


def test_sanitize_replaces_paths_and_trims_account_details() -> None:
    raw = [json.dumps({"type": "system", "subtype": "init", "cwd": "/home/u/r", "tools": ["Bash", "PublishPlugin",
                                                                                          "mcp__b1500__x"],
                       "skills": ["a"], "memory_paths": {"auto": "/home/u/m"}}),
           json.dumps({"type": "rate_limit_event", "rate_limit_info": {}}),
           json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "signature": "abc"}]},
                       "note": "C:\\Users\\u\\r"})]
    out = sanitize_lines(raw, {"/home/u/r": "<REPO>", "/home/u": "<HOME>", "C:\\Users\\u": "<HOME>"})
    assert len(out) == 2
    init = json.loads(out[0])
    assert init["cwd"] == "<REPO>" and init["tools"] == ["Bash", "mcp__b1500__x"]
    assert "skills" not in init and "memory_paths" not in init
    assert '"signature": "<signature>"' in out[1] and "<HOME>" in out[1]
