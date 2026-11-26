"""Harness contract (v2.1 plan §2.5, WP21.2 AC): structural checks FAIL on forged gaps; vocabulary drift and
``Monitor`` (the owner-accepted residual, OD21-5 = c) only WARN, and a WARN never fails a session.

Evidence: two real WP11.5 sessions (``tests/fixtures/transcripts/contract/``: Claude Code 2.1.328 S16 with five
hooked ``Bash`` calls, codex-cli 0.170.0 S2 with its trimmed rollout) copied into a temporary folder, the paths put
back, then forged one gap at a time. The regrade of the whole local WP11.5 batches is the free regression of the WP
(progress row): every verdict unchanged, the contract adds WARNs only.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from b1500_test_agent.devtools.acceptance import report, runner
from b1500_test_agent.devtools.acceptance.contract import ContractResult, check_contract
from b1500_test_agent.devtools.acceptance.evidence import ROLLOUT_FILE, load_evidence
from b1500_test_agent.devtools.acceptance.graders import grade_session
from b1500_test_agent.devtools.acceptance.vocabulary import UNGUARDED_RESIDUAL
from tests.acceptance.helpers import FIXTURES, REPO_ROOT

CONTRACT = FIXTURES / "contract"
CLAUDE = "claude-2.1.328-S16"
CODEX = "codex-0.170.0-S2"


def session_copy(tmp: Path, name: str) -> Path:
    """A regradable copy of a contract fixture (``<REPO>`` and ``<SESSION>`` put back)."""
    folder = tmp / name
    shutil.copytree(CONTRACT / name, folder)
    for path in folder.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("<REPO>", REPO_ROOT.as_posix()).replace("<SESSION>", folder.as_posix()),
                            encoding="utf-8")
    return folder


def edit_transcript(folder: Path, change: Callable[[list[dict]], list[dict]], turn: int = 1) -> None:
    path = folder / "transcripts" / f"turn-{turn}.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in change(records)) + "\n", encoding="utf-8")


def contract(folder: Path) -> ContractResult:
    return check_contract(load_evidence(folder))


def texts(result: ContractResult) -> list[str]:
    return [f.text for f in result.problems] + [f.text for f in result.warnings]


def _init(records: list[dict]) -> dict:
    return next(r for r in records if r.get("type") == "system" and r.get("subtype") == "init")


# -- the real sessions -----------------------------------------------------------------------------------------------


def test_real_claude_session_meets_the_contract_and_warns_about_the_residual(tmp_path: Path) -> None:
    result = contract(session_copy(tmp_path, CLAUDE))
    assert result.problems == [] and result.verdict == "warn"
    (residual,) = result.warnings
    assert residual.surface is None and "owner-accepted residual (OD21-5 = c)" in residual.text
    for name in sorted(UNGUARDED_RESIDUAL):
        assert name in residual.text
    assert result.checked == ["1 turn(s), 5 guarded call(s)"]


def test_real_codex_session_meets_the_contract(tmp_path: Path) -> None:
    result = contract(session_copy(tmp_path, CODEX))
    assert result.verdict == "pass", texts(result)
    assert result.checked == ["1 turn(s), rollout"]


def test_the_contract_is_an_implicit_grader_and_a_warn_never_fails(tmp_path: Path) -> None:
    grade = grade_session(session_copy(tmp_path, CLAUDE), write=False)
    names = [r.name for r in grade.results]
    assert names[:2] == ["session ok", "harness contract"]
    contract_result = grade.results[1]
    assert contract_result.verdict == "warn" and contract_result.type == "harness_contract"
    assert contract_result.message.startswith("structural: ok; 1 WARN")
    batch = runner.BatchResult(batch_id="b", harness="claude", harness_version="2.1.328", repo_root="/r",
                               repo_commit="c", runner_version="v", started_at=datetime(2026, 11, 25, tzinfo=UTC),
                               batch_dir="/o/b", scenarios={"S16": {"title": "t", "safety": False, "reps": 1}},
                               sessions=[grade])
    text = report.render([batch])
    assert "| harness contract | warn |" in text and "Warnings (never a failure):" in text


# -- structural gaps FAIL --------------------------------------------------------------------------------------------


def _drop_hook_response(records: list[dict]) -> list[dict]:
    index = next(i for i, r in enumerate(records) if r.get("subtype") == "hook_response")
    return records[:index] + records[index + 1:]


def _drop_result(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("type") != "result"]


def _result_without_usage(records: list[dict]) -> list[dict]:
    for record in records:
        if record.get("type") == "result":
            record.pop("usage")
    return records


def _init_edit(**fields: object) -> Callable[[list[dict]], list[dict]]:
    def change(records: list[dict]) -> list[dict]:
        init = _init(records)
        for key, value in fields.items():
            if value is None:
                init.pop(key, None)
            else:
                init[key] = value
        return records
    return change


CLAUDE_GAPS = [
    ("hook did not run", _drop_hook_response, "hook", "1 Bash call(s) without a PreToolUse hook_response"),
    ("no completion", _drop_result, "format", "no result event (completion)"),
    ("no usage", _result_without_usage, "format", "result carries no usage"),
    ("bypass mode", _init_edit(permissionMode="bypassPermissions"), "approval", "permissionMode 'bypassPermissions'"),
    ("server failed", _init_edit(mcp_servers=[{"name": "b1500", "status": "failed"}]), "lifecycle",
     "the b1500 server is failed"),
    ("skill missing", _init_edit(skills=["b1500-bringup", "b1500-debug"]), "instructions",
     "project skill(s) b1500-test not in the init skills list"),
    ("no session id", _init_edit(session_id=None), "format", "init event without a session_id"),
]


@pytest.mark.parametrize(("label", "change", "surface", "text"), CLAUDE_GAPS, ids=[g[0] for g in CLAUDE_GAPS])
def test_claude_structural_gaps_fail(tmp_path: Path, label: str, change: Callable, surface: str, text: str) -> None:
    folder = session_copy(tmp_path, CLAUDE)
    edit_transcript(folder, change)
    result = contract(folder)
    assert result.verdict == "fail", label
    assert [(f.surface, f.text) for f in result.problems if text in f.text] == \
        [(surface, next(f.text for f in result.problems if text in f.text))]
    grade = grade_session(folder, write=False)
    assert not grade.passed and grade.results[1].verdict == "fail"


def test_hook_coverage_counts_only_turns_launched_with_hook_events(tmp_path: Path) -> None:
    folder = session_copy(tmp_path, CLAUDE)
    edit_transcript(folder, _drop_hook_response)
    record = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    record["turns"][0]["argv"] = [a for a in record["turns"][0]["argv"] if a != "--include-hook-events"]
    (folder / "session.json").write_text(json.dumps(record), encoding="utf-8")
    assert contract(folder).problems == []  # older recordings carry no hook events


def test_codex_structural_gaps_fail(tmp_path: Path) -> None:
    folder = session_copy(tmp_path, CODEX)
    (folder / ROLLOUT_FILE).unlink()
    result = contract(folder)
    assert [(f.surface, f.text.split(":")[0]) for f in result.problems] == [("format", "Codex rollout file missing")]
    folder = session_copy(tmp_path / "b", CODEX)
    edit_transcript(folder, lambda rs: [{**r, "usage": None} if r.get("type") == "turn.completed" else r for r in rs])
    assert [f.text for f in contract(folder).problems] == ["turn 1: turn.completed carries no usage"]
    folder = session_copy(tmp_path / "c", CODEX)
    edit_transcript(folder, lambda rs: [r for r in rs if r.get("type") != "thread.started"])
    assert "turn 1: no thread.started with a thread_id (session id)" in texts(contract(folder))


def test_a_timed_out_turn_is_not_a_format_gap(tmp_path: Path) -> None:
    folder = session_copy(tmp_path, CODEX)
    edit_transcript(folder, lambda rs: [r for r in rs if r.get("type") != "turn.completed"])
    record = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    record["turns"][0]["timed_out"] = True
    (folder / "session.json").write_text(json.dumps(record), encoding="utf-8")
    assert contract(folder).problems == []  # `session ok` fails it already


# -- vocabulary drift and the residual WARN --------------------------------------------------------------------------


def test_claude_vocabulary_drift_and_a_residual_call_only_warn(tmp_path: Path) -> None:
    folder = session_copy(tmp_path, CLAUDE)

    def drift(records: list[dict]) -> list[dict]:
        _init(records)["tools"].append("Teleport")
        sid = _init(records)["session_id"]
        extra = [{"type": "system", "subtype": "ui_invalidate", "session_id": sid},
                 {"type": "assistant", "session_id": sid, "parent_tool_use_id": None, "message": {"content": [
                     {"type": "server_tool_use", "id": "s1"},
                     {"type": "tool_use", "id": "m1", "name": "Monitor", "input": {"command": "uv run b1500 status"}},
                     {"type": "tool_use", "id": "n1", "name": "Hyperlink", "input": {}}]}}]
        return records[:2] + extra + records[2:]

    edit_transcript(folder, drift)
    result = contract(folder)
    assert result.problems == [] and result.verdict == "warn"
    warned = {(f.surface, f.text.split(":")[0]) for f in result.warnings}
    assert ("format", "unknown event system/ui_invalidate") in warned
    assert ("format", "unknown assistant content block 'server_tool_use'") in warned
    assert ("hook", "new built-in tool offered") in warned
    assert ("hook", "unknown tool used") in warned
    assert (None, "residual tool called outside the hook (turn 1)") in warned
    assert grade_session(folder, write=False).results[1].verdict == "warn"
    assert result.surfaces(warnings=True) == {"format", "hook"}


def test_an_init_without_skills_field_warns(tmp_path: Path) -> None:
    folder = session_copy(tmp_path, CLAUDE)
    edit_transcript(folder, _init_edit(skills=None))
    result = contract(folder)
    assert result.problems == []
    assert any("init event has no skills field" in f.text for f in result.warnings)


def test_codex_vocabulary_drift_only_warns(tmp_path: Path) -> None:
    folder = session_copy(tmp_path, CODEX)
    edit_transcript(folder, lambda rs: [*rs[:2], {"type": "turn.plan_updated"},
                                        {"type": "item.completed", "item": {"id": "x", "type": "todo_list"}}, *rs[2:]])
    with (folder / ROLLOUT_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": "2026-11-25T20:51:30Z", "type": "response_item",
                                 "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}}) + "\n")
        handle.write(json.dumps({"type": "compacted", "payload": {}}) + "\n")
    result = contract(folder)
    assert result.problems == [] and result.verdict == "warn"
    warned = {f.text.split(" (")[0] for f in result.warnings}
    assert warned == {"turn 1: unknown event type 'turn.plan_updated'", "turn 1: unknown item type 'todo_list'",
                      "rollout: unknown record type 'compacted'", "rollout: unknown tool 'shell'"}
