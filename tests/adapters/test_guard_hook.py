"""Scripted test of the Claude Code ``PreToolUse`` guard hook ``scripts/hooks/b1500_guard.py`` (blueprint 5.4, ATV-8).

The hook gets the documented hook JSON on standard input, exactly as Claude Code sends it, and must exit 2 (blocked,
reason on stderr) or 0. Whether Claude Code also runs hooks in ``bypassPermissions`` mode (ATV-8) is not tested here:
launching a bypass mode is forbidden for the executor (guardrail 5); the deny rules hold in every mode.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts" / "hooks" / "b1500_guard.py"
SETTINGS = ROOT / ".claude" / "settings.json"
BLOCKED_PREFIX = "Blocked by the b1500 guard hook"


def event(tool: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """A PreToolUse hook input as documented by Claude Code."""
    return {
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": str(ROOT),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_test",
    }


def run_hook(payload: dict[str, Any] | bytes, argv: list[str] | None = None) -> subprocess.CompletedProcess[bytes]:
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return subprocess.run(argv or [sys.executable, str(HOOK)], input=data, capture_output=True, timeout=60,
                          check=False)


def assert_blocked(result: subprocess.CompletedProcess[bytes]) -> str:
    stderr = result.stderr.decode("utf-8")
    assert result.returncode == 2, stderr
    assert BLOCKED_PREFIX in stderr
    return stderr


def assert_allowed(result: subprocess.CompletedProcess[bytes]) -> None:
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stderr == b""


@pytest.mark.parametrize(
    "command",
    [
        "b1500 fault clear",
        "uv run b1500 fault clear --by me",
        "b1500 run --confirm P-X",
        "uv run b1500 run --confirm P-X",
        "uv run b1500 run P-X --confirm",
        "uv run b1500 run P-X \\\n  --confirm",
        "cd /lab && b1500 'fault' clear",
        "B1500.exe fault clear",
        'python -c "import pyvisa"',
        "python -c 'from pyvisa import ResourceManager'",
        "python -c 'import visa_tools as v; v.ResourceManager()'",
    ],
)
def test_shell_commands_are_blocked(command: str) -> None:
    stderr = assert_blocked(run_hook(event("Bash", {"command": command, "description": "x"})))
    assert "MCP tools" in stderr


def test_raw_visa_advice_never_hands_the_code_to_the_human() -> None:
    """WP6.6: a blocked VISA command is refused for everyone (Claude Code passed the code on to the human after the
    shared human-only advice); a blocked human-only CLI command is still shown to the human."""
    lib = "py" + "visa"
    visa = assert_blocked(run_hook(event("Bash", {"command": f"python -c 'import {lib}'", "description": "x"})))
    assert "hand it to the human either" in visa and "show the human the command" not in visa
    command = "uv run b1500 " + "fa" + "ult clear"
    human = assert_blocked(run_hook(event("Bash", {"command": command, "description": "x"})))
    assert "show the human the command" in human


# The configuration bootstrap is human-only (blueprint v2 7.1, WP6.1). The command strings are built by
# concatenation so that no shell command of the executor that edits this file contains them (the hook would block it).
B1500 = "b1500"
CONFIG = "config"
BOOTSTRAP_COMMANDS = [
    f"uv run {B1500} {CONFIG} adopt x",  # the AC command
    f"uv run {B1500} {CONFIG} init",
    f"uv run {B1500} {CONFIG} init --visa",
    f"{B1500} {CONFIG} adopt work/bringup/station.proposed.yaml --as station",
    f"{B1500} {CONFIG} init",
    f"uv run --frozen {B1500} {CONFIG} adopt x --as pinmap",
    f"cd C:/b1500/test_agent && uv run {B1500}  {CONFIG}   adopt x",
    f"uv run {B1500} '{CONFIG}' \"adopt\" x",
    f"{B1500.upper()}.exe {CONFIG.upper()} INIT",
    f"uv run {B1500} {CONFIG} adopt\nx",
]


@pytest.mark.parametrize("command", BOOTSTRAP_COMMANDS)
def test_configuration_bootstrap_is_blocked(command: str) -> None:
    stderr = assert_blocked(run_hook(event("Bash", {"command": command, "description": "x"})))
    assert "config init" in stderr and "config adopt" in stderr and "propose-station" in stderr


@pytest.mark.parametrize("command", [
    f"uv run {B1500} {CONFIG} check",
    f"uv run {B1500} {CONFIG} check --json",
    f"uv run {B1500} bringup propose-station",
    f"uv run {B1500} doctor --probe",
    f"uv run {B1500} manual search 'ERSSP status'",
    f"uv run {B1500} {CONFIG} initialize-nothing",  # not a command, but not the bootstrap either
    "grep -rn 'adopt' docs/deployment-windows.md",
])
def test_reading_configuration_and_proposals_pass(command: str) -> None:
    assert_allowed(run_hook(event("Bash", {"command": command})))


def test_powershell_tool_is_guarded_too() -> None:
    assert_blocked(run_hook(event("PowerShell", {"command": "uv run b1500 fault clear"})))


@pytest.mark.parametrize(
    "command",
    [
        "b1500 status",
        "uv run b1500 run P-X --dut-instance W1-D3",
        "uv run b1500 runs --limit 5",
        "uv run b1500 shutdown --reason done",
        "uv run pytest -q -m 'not hardware and not acceptance'",
        "cat .codex/rules/b1500.rules",
        "git status",
    ],
)
def test_benign_shell_commands_pass(command: str) -> None:
    assert_allowed(run_hook(event("Bash", {"command": command})))


@pytest.mark.parametrize(
    "content",
    [
        "import pyvisa\nrm = pyvisa.ResourceManager()\n",
        "import os, pyvisa as visa\n",
        "from pyvisa.resources import MessageBasedResource\n",
        "def f():\n    import pyvisa\n",
        "x = 1; import pyvisa\n",
    ],
)
def test_write_importing_pyvisa_outside_transport_visa_is_blocked(content: str, tmp_path: Path) -> None:
    stderr = assert_blocked(run_hook(event("Write", {"file_path": str(tmp_path / "work" / "probe.py"),
                                                     "content": content})))
    assert "transport/visa.py" in stderr


@pytest.mark.parametrize(
    "path",
    [str(ROOT / "src" / "b1500_test_agent" / "transport" / "visa.py"),
     "C:\\lab\\test_agent\\src\\b1500_test_agent\\transport\\visa.py"],
)
def test_write_inside_transport_visa_passes(path: str) -> None:
    assert_allowed(run_hook(event("Write", {"file_path": path, "content": "import pyvisa\n"})))


@pytest.mark.parametrize(
    "content",
    ["import pyvisa_sim\n", "text = 'import pyvisa'\n", "# never import pyvisa here\nx = 1\n", "import os\n"],
)
def test_write_without_pyvisa_import_passes(content: str, tmp_path: Path) -> None:
    assert_allowed(run_hook(event("Write", {"file_path": str(tmp_path / "x.py"), "content": content})))


def test_edit_adding_pyvisa_import_is_blocked(tmp_path: Path) -> None:
    target = tmp_path / "scratch.py"
    target.write_text("import os\n", encoding="utf-8")
    edit = {"file_path": str(target), "old_string": "import os", "new_string": "from pyvisa import ResourceManager",
            "replace_all": False}
    assert_blocked(run_hook(event("Edit", edit)))


def test_edit_completing_an_import_in_the_file_is_blocked(tmp_path: Path) -> None:
    """The new text alone looks harmless; the resulting file imports pyvisa."""
    target = tmp_path / "scratch.py"
    target.write_text("import xyz\n", encoding="utf-8")
    assert_blocked(run_hook(event("Edit", {"file_path": str(target), "old_string": "xyz", "new_string": "pyvisa"})))
    edits = {"file_path": str(target), "edits": [{"old_string": "xyz", "new_string": "pyvisa"}]}
    assert_blocked(run_hook(event("MultiEdit", edits)))


def test_edit_without_pyvisa_passes(tmp_path: Path) -> None:
    target = tmp_path / "scratch.py"
    target.write_text("import os\n", encoding="utf-8")
    assert_allowed(run_hook(event("Edit", {"file_path": str(target), "old_string": "os", "new_string": "sys"})))


def test_notebooks_are_guarded(tmp_path: Path) -> None:
    notebook = {"cells": [{"cell_type": "code", "source": ["import numpy\n", "import pyvisa\n"]}], "nbformat": 4}
    assert_blocked(run_hook(event("Write", {"file_path": str(tmp_path / "a.ipynb"), "content": json.dumps(notebook)})))
    assert_blocked(run_hook(event("NotebookEdit", {"notebook_path": str(tmp_path / "a.ipynb"),
                                                   "new_source": "import pyvisa"})))


# -- debug cases (v2.1 plan D-7: only the human sets status: reviewed) ------------------------------------------------

CASE_FRONT = ("---\nid: 2026-11-05-x\ntitle: x\nstatus: {status}\nreviewed_by: {by}\nrunbook: new\n---\n\n# x\n\n"
              "## Symptom\n\nNoise.\n")


def case_file(tmp_path: Path, status: str = "draft", by: str = "null", copy: str = ".agents") -> Path:
    path = tmp_path / copy / "skills" / "b1500-debug" / "cases" / "2026-11-05-x.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CASE_FRONT.format(status=status, by=by), encoding="utf-8")
    return path


@pytest.mark.parametrize("copy", [".agents", ".claude"])
def test_writing_a_reviewed_case_is_blocked(tmp_path: Path, copy: str) -> None:
    path = case_file(tmp_path, copy=copy)
    reviewed = CASE_FRONT.format(status="reviewed", by="A. Owner")
    stderr = assert_blocked(run_hook(event("Write", {"file_path": str(path), "content": reviewed})))
    assert "reviewed only by the human" in stderr and "Never edit a reviewed case" in stderr
    windows = "C:\\lab\\test_agent\\.agents\\skills\\b1500-debug\\cases\\2026-11-05-x.md"
    assert_blocked(run_hook(event("Write", {"file_path": windows, "content": reviewed})))


def test_editing_a_case_to_reviewed_is_blocked(tmp_path: Path) -> None:
    path = case_file(tmp_path)
    flip = {"file_path": str(path), "old_string": "status: draft", "new_string": "status: reviewed"}
    assert_blocked(run_hook(event("Edit", flip)))
    assert_blocked(run_hook(event("MultiEdit", {"file_path": str(path), "edits": [flip]})))
    quoted = {"file_path": str(path), "old_string": "status: draft", "new_string": "status: 'reviewed'"}
    assert_blocked(run_hook(event("Edit", quoted)))


def test_a_reviewed_case_is_not_edited_at_all(tmp_path: Path) -> None:
    """Any edit of a case a human reviewed (the file as it is), even one that would downgrade it."""
    path = case_file(tmp_path, status="reviewed", by="A. Owner")
    assert_blocked(run_hook(event("Edit", {"file_path": str(path), "old_string": "Noise.", "new_string": "Hum."})))
    assert_blocked(run_hook(event("Write", {"file_path": str(path), "content": CASE_FRONT.format(status="draft",
                                                                                                by="null")})))


def test_drafting_cases_and_other_files_pass(tmp_path: Path) -> None:
    path = case_file(tmp_path)
    assert_allowed(run_hook(event("Edit", {"file_path": str(path), "old_string": "Noise.", "new_string": "Hum."})))
    template = "status: draft                    # draft (written by the agent) | reviewed (set only by a human)\n"
    assert_allowed(run_hook(event("Write", {"file_path": str(path.with_name("_TEMPLATE.md")), "content": template})))
    reviewed = CASE_FRONT.format(status="reviewed", by="A. Owner")
    assert_allowed(run_hook(event("Write", {"file_path": str(tmp_path / "docs" / "notes.md"), "content": reviewed})))
    mention = "Never set `status: reviewed` yourself.\n"  # prose, not a frontmatter line
    assert_allowed(run_hook(event("Write", {"file_path": str(path), "content": mention})))
    # Shell commands are not text-checked for cases (reading or grepping them stays possible)
    assert_allowed(run_hook(event("Bash", {"command": f"grep -l 'status: reviewed' {path.parent}/*.md"})))


def test_other_tools_pass() -> None:
    assert_allowed(run_hook(event("Read", {"file_path": str(ROOT / "README.md")})))
    assert_allowed(run_hook(event("mcp__b1500__station_status", {"refresh": True})))


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"[1, 2]", json.dumps(event("Bash", {})).encode(), json.dumps(event("Write", {"x": 1})).encode()],
)
def test_malformed_input_fails_closed(payload: bytes) -> None:
    assert_blocked(run_hook(payload))


def test_non_ascii_input_is_read_as_utf8(tmp_path: Path) -> None:
    folder = tmp_path / "测试 µ"
    assert_allowed(run_hook(event("Write", {"file_path": str(folder / "x.py"), "content": "# 中文\nx = 1\n"})))
    assert_blocked(run_hook(event("Bash", {"command": "echo 中文 && b1500 fault clear"})))


def hook_argv() -> list[str]:
    """The argv Claude Code runs for the guard hook of ``.claude/settings.json`` (exec form, placeholder resolved)."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    entries = [hook for entry in settings["hooks"]["PreToolUse"] for hook in entry["hooks"]]
    (hook,) = [h for h in entries if "b1500_guard.py" in json.dumps(h)]
    return [hook["command"], *(arg.replace("${CLAUDE_PROJECT_DIR}", str(ROOT)) for arg in hook["args"])]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_settings_hook_command_blocks_as_configured() -> None:
    """The exact command line of the committed settings blocks the human-only commands and lets others pass."""
    argv = hook_argv()
    assert_blocked(run_hook(event("Bash", {"command": "b1500 fault clear"}), argv))
    assert_blocked(run_hook(event("Bash", {"command": "uv run b1500 run --confirm P-X"}), argv))
    assert_allowed(run_hook(event("Bash", {"command": "uv run b1500 status"}), argv))
    assert_blocked(run_hook(event("Bash", {"command": f"uv run {B1500} {CONFIG} adopt x"}), argv))
    assert_blocked(run_hook(event("PowerShell", {"command": f"uv run {B1500} {CONFIG} init --visa"}), argv))
