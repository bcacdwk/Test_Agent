"""Claude Code ``PreToolUse`` guard of the B1500A test agent (blueprint 5.4, second safety layer).

Claude Code runs this script before every shell or file-editing tool call and passes the documented hook JSON
(``tool_name``, ``tool_input``, ...) on standard input. Exit code 2 blocks the call and shows standard error to
the agent; exit code 0 lets it through. It backs the deny rules of ``.claude/settings.json`` (prefix rules alone
are not a boundary):

- shell commands (``Bash``, ``PowerShell``): blocked when the command matches
  ``b1500\\s+(fault|run\\b.*--confirm|config\\s+(init|adopt)\\b)|import\\s+pyvisa|from\\s+pyvisa|ResourceManager\\(``
  (case-insensitive, also after removing quotes and backslashes, and also for ``b1500.exe``, with or without
  ``uv run``); ``b1500 fault clear``, ``b1500 run --confirm`` and the configuration bootstrap ``b1500 config
  init|adopt`` (blueprint v2 7.1, WP6.1) are the human's commands, and the instrument is reached only through the
  MCP tools;
- file edits (``Write``, ``Edit``, ``MultiEdit``, ``NotebookEdit``): blocked when the new text or the resulting file
  has a statement ``import pyvisa...`` / ``from pyvisa... import`` (at a line start or after ``;``) anywhere but
  ``src/b1500_test_agent/transport/visa.py``. Dynamic imports are left to the AST lint test
  (``tests/unit/test_lint_pyvisa.py``), so test files that spell such imports in strings stay editable;
- debug cases (v2.1 plan D-7): a file edit under ``b1500-debug/cases/`` (the skill source or its generated copy) is
  blocked when the new text, the resulting file or the file as it is has a line ``status: reviewed``: only the human
  reviews a case (they edit the file in their editor and commit); an agent drafts with ``status: draft`` and never
  edits a reviewed case. Shell commands are not text-checked for this (a mention is no write); the case lint and the
  human's commit review stay the backstop, and Codex has no hook (its skill text says the same).

Malformed input for a guarded tool fails closed (exit 2). Standard library only, so any Python 3.8+ runs it; it
never touches the instrument and never writes files.
By hand: ``python scripts/hooks/b1500_guard.py < hook.json``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BLOCK = 2
ALLOW = 0

SHELL_TOOLS = frozenset({"Bash", "PowerShell"})
EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
VISA_MODULE = "src/b1500_test_agent/transport/visa.py"

SHELL_PATTERN = re.compile(
    r"b1500(?:\.exe)?\s+(?:fault|run\b.*--confirm|config\s+(?:init|adopt)\b)|import\s+pyvisa|from\s+pyvisa"
    r"|ResourceManager\(",
    re.IGNORECASE | re.DOTALL,
)
PYVISA_IMPORT = re.compile(
    r"(?:^|;)[ \t]*(?:import[ \t]+(?:[\w.]+[ \t]*(?:as[ \t]+\w+[ \t]*)?,[ \t]*)*pyvisa\b|from[ \t]+pyvisa\b)",
    re.MULTILINE,
)

SHELL_ADVICE = (
    "Reach the instrument only through the b1500 MCP tools (validate_plan, run_plan, run_confirmed_plan, "
    "safe_shutdown). 'b1500 fault clear', 'b1500 run --confirm', 'b1500 config init' and 'b1500 config adopt' are "
    "for the human in their own terminal; show the human the command instead of running it (proposals go to "
    "work/bringup/, e.g. 'b1500 bringup propose-station')."
)
VISA_ADVICE = (
    "Reach the instrument only through the b1500 MCP tools. Own VISA or raw FLEX code is refused for everyone: do "
    "not run it, write it or hand it to the human either; offer a recipe through validate_plan instead."
)
"""Advice for a blocked pyvisa/ResourceManager command (WP6.6): unlike the human-only CLI commands, raw instrument
code is not something to pass on to the human."""
EDIT_ADVICE = (
    "Only src/b1500_test_agent/transport/visa.py may import pyvisa. Use the b1500 MCP tools for measurements "
    "and b1500_test_agent.analysis for offline analysis of archived runs."
)
CASE_DIR = re.compile(r"b1500-debug[/\\]+cases(?:[/\\]|$)", re.IGNORECASE)
"""A path inside a debug-case folder (``.agents/skills/b1500-debug/cases/`` or its ``.claude/skills/`` copy)."""
REVIEWED_LINE = re.compile(r"^[ \t]*status[ \t]*:[ \t]*[\"']?reviewed\b", re.IGNORECASE | re.MULTILINE)
"""A YAML line that sets ``status: reviewed`` (the template's ``status: draft  # ... | reviewed`` is not one)."""
CASE_ADVICE = (
    "A debug case is reviewed only by the human: draft it with status: draft and reviewed_by: null, put what only "
    "the human knows under 'Open questions for the owner' and tell them the draft waits for their review (they set "
    "status: reviewed with their name and commit). Never edit a reviewed case; propose the change in chat."
)
"""Advice for a blocked debug-case write (v2.1 plan D-7)."""


def _block(message: str) -> int:
    sys.stderr.write(f"Blocked by the b1500 guard hook (scripts/hooks/b1500_guard.py): {message}\n")
    return BLOCK


def check_shell(command: object) -> str | None:
    """Why a shell command is blocked, or ``None`` when it may run."""
    if not isinstance(command, str):
        return "the shell tool input has no command string (fail closed)"
    unquoted = re.sub(r"[\"'`\\^]", "", command)
    for text in (command, unquoted):
        match = SHELL_PATTERN.search(text)
        if match:
            advice = VISA_ADVICE if re.search(r"pyvisa|ResourceManager", match.group(0), re.IGNORECASE) \
                else SHELL_ADVICE
            return f"the command contains {match.group(0)[:60]!r}. {advice}"
    return None


def _is_visa_module(path: str) -> bool:
    return path.replace("\\", "/").endswith(VISA_MODULE)


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _notebook_sources(text: str) -> str:
    """The cell sources of a notebook given as JSON text (the text itself when it is not a notebook)."""
    try:
        cells = json.loads(text).get("cells", [])
    except (ValueError, AttributeError):
        return text
    parts = []
    for cell in cells if isinstance(cells, list) else []:
        source = cell.get("source", "") if isinstance(cell, dict) else ""
        parts.append("".join(source) if isinstance(source, list) else str(source))
    return "\n".join(parts)


def _apply_edits(original: str | None, edits: list[tuple[str, str, bool]]) -> str | None:
    """The file text after ``edits`` (old, new, replace_all), or ``None`` when they do not apply."""
    if original is None:
        return None
    text = original
    for old, new, replace_all in edits:
        if not old or old not in text:
            return None
        text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    return text


def edited_texts(tool: str, tool_input: dict) -> list[str] | None:
    """The texts to scan for a file-editing call: the new text and, when it can be computed, the whole resulting
    file. ``None`` when the input has an unknown shape."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str):
        return None
    if tool == "Write":
        content = tool_input.get("content")
        if not isinstance(content, str):
            return None
        return [content, _notebook_sources(content)] if path.endswith(".ipynb") else [content]
    if tool == "NotebookEdit":
        source = tool_input.get("new_source", "")
        return [source] if isinstance(source, str) else None
    raw = tool_input.get("edits") if tool == "MultiEdit" else [tool_input]
    if not isinstance(raw, list):
        return None
    edits: list[tuple[str, str, bool]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("new_string"), str):
            return None
        old = item.get("old_string")
        edits.append((old if isinstance(old, str) else "", item["new_string"], bool(item.get("replace_all"))))
    texts = [new for _, new, _ in edits]
    result = _apply_edits(_read_text(path), edits)
    if result is not None:
        texts.append(result)
    return texts


def check_edit(tool: str, tool_input: dict) -> str | None:
    """Why a file edit is blocked, or ``None`` when it may proceed."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    texts = edited_texts(tool, tool_input)
    if texts is None:
        return f"the {tool} tool input has an unexpected shape (fail closed)"
    if isinstance(path, str) and CASE_DIR.search(path):
        current = _read_text(path)
        if any(REVIEWED_LINE.search(text) for text in [*texts, current or ""]):
            return f"{path} is or would become a debug case with status: reviewed. {CASE_ADVICE}"
    if isinstance(path, str) and _is_visa_module(path):
        return None
    for text in texts:
        match = PYVISA_IMPORT.search(text)
        if match:
            return f"{path} would import pyvisa ({match.group(0).strip()[:60]!r}). {EDIT_ADVICE}"
    return None


def evaluate(event: object) -> str | None:
    """Why the tool call described by the hook ``event`` is blocked, or ``None`` when it may proceed."""
    if not isinstance(event, dict):
        return "the hook input is not a JSON object (fail closed)"
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if tool not in SHELL_TOOLS and tool not in EDIT_TOOLS:
        return None
    if not isinstance(tool_input, dict):
        return f"the {tool} tool input is missing (fail closed)"
    if tool in SHELL_TOOLS:
        return check_shell(tool_input.get("command"))
    return check_edit(str(tool), tool_input)


def main() -> int:
    """Read the hook JSON from standard input; exit 2 (blocked, reason on stderr) or 0."""
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        return _block(f"cannot read the hook input as JSON ({exc}); fail closed")
    reason = evaluate(event)
    return _block(reason) if reason else ALLOW


if __name__ == "__main__":
    sys.exit(main())
