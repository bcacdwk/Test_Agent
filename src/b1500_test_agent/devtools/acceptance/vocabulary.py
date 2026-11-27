"""Known harness vocabulary (v2.1 plan §2.5, table-based part of the harness contract): WARN only, never a FAIL.

Baseline: the WP11.5 full-suite batches (2026-11-25, S1-S18 on codex-cli 0.170.0, batch
``20261125T204845Z-codex-0.170.0``, 40 sessions / 70 turns, and Claude Code 2.1.328, batch
``20261125T221153Z-claude-2.1.328``, 41 sessions / 71 turns), plus the types the transcript parser and the infra
watcher already handle. A type or tool outside these sets is listed as a WARN in the session's ``harness contract``
result and in the qualify report: the parser may be blind to it. Extend a set here only when such a WARN was checked
and is worth silencing (plan §2.7: no hand update per release is needed otherwise).
"""

from __future__ import annotations

from typing import Final

# -- Codex (codex exec --json and the rollout file) -----------------------------------------------------------------

CODEX_EVENTS: Final = frozenset({
    "thread.started", "turn.started", "item.started", "item.completed", "turn.completed",  # 11.5 batch
    "item.updated", "turn.failed", "error",  # handled by the parser and the infra watcher
})
CODEX_ITEMS: Final = frozenset({
    "agent_message", "command_execution", "mcp_tool_call", "web_search",  # 11.5 batch
    "file_change", "error",  # handled by the parser (patches, transport notices)
})
CODEX_ROLLOUT_RECORDS: Final = frozenset({
    "session_meta", "turn_context", "response_item", "event_msg", "token_usage_record", "world_state",
})
CODEX_ROLLOUT_PAYLOADS: Final = frozenset({
    # response_item payloads (11.5 batch)
    "message", "reasoning", "custom_tool_call", "custom_tool_call_output", "function_call", "function_call_output",
    "additional_tools",
    # event_msg payloads (11.5 batch)
    "item_completed", "token_count", "task_started", "task_complete", "thread_settings_applied",
    # handled by the parser
    "local_shell_call",
})
CODEX_TOOLS: Final = frozenset({"exec", "sleep"})
"""Tool names of the rollout's ``custom_tool_call``/``function_call`` records: the JavaScript code-mode tool ``exec``
(every shell command, patch and MCP call goes through it) and ``sleep``."""

# -- Claude Code (claude -p --output-format stream-json --verbose --include-hook-events) ----------------------------

CLAUDE_EVENTS: Final = frozenset({
    ("assistant", None), ("user", None), ("rate_limit_event", None), ("system", "init"),
    ("system", "thinking_tokens"), ("system", "hook_started"), ("system", "hook_response"),
    ("result", "success"),  # 11.5 batch
    ("system", "permission_denied"), ("system", "hook_progress"),  # handled by the parser (denials, hook events)
})
"""``(type, subtype)`` pairs; a ``result`` error subtype or a retry event is an infra event (``infra.py``)."""
CLAUDE_BLOCKS: Final = frozenset({
    ("assistant", "text"), ("assistant", "thinking"), ("assistant", "tool_use"),
    ("user", "tool_result"), ("user", "text"),
})
CLAUDE_TOOLS_OFFERED: Final = frozenset({
    "AskUserQuestion", "Bash", "CronCreate", "CronDelete", "CronList", "DesignSync", "Edit", "EnterPlanMode",
    "EnterWorktree", "ExitPlanMode", "ExitWorktree", "ListAgents", "ListMcpResourcesTool", "Monitor", "NotebookEdit",
    "PublishPlugin", "PushNotification", "Read", "ReadMcpResourceDirTool", "ReadMcpResourceTool", "RemoteTrigger",
    "ReportFindings", "ScheduleWakeup", "SendMessage", "ShareOnboardingGuide", "Skill", "Task", "TaskStop",
    "ToolSearch", "WebSearch", "Write",
}) | frozenset({
    "McpTaskCheck",  # 2.1.332 (WP21.9): the status of a background MCP task; input task_id; read-only
})
"""The 31 built-in tools of the ``init`` event of every 11.5 session (``mcp__`` tools excluded), plus the tools a later
version offered that were checked to neither run commands nor write files: ``McpTaskCheck`` (Claude Code 2.1.332;
"Check the status of a background MCP task", input ``task_id`` only, declared read-only, reads the harness's own task
registry; checked in WP21.9 from the 2.1.332 binary)."""
CLAUDE_TOOLS_KNOWN: Final = CLAUDE_TOOLS_OFFERED | frozenset({
    "Agent", "Glob", "Grep", "LS", "MultiEdit", "PowerShell", "TodoWrite", "WebFetch",
})
"""Built-in tool names a ``tool_use`` may carry without a WARN: the offered set plus names earlier versions offered
or the graders already know (``MultiEdit`` is in the hook matcher but no longer offered by 2.1.328)."""
UNGUARDED_RESIDUAL: Final = frozenset({
    "Monitor", "CronCreate", "RemoteTrigger", "ScheduleWakeup", "EnterWorktree", "PublishPlugin",
})
"""Built-ins that run commands or write outside the ``PreToolUse`` hook matcher (``Bash|PowerShell|Write|Edit|
MultiEdit|NotebookEdit``): the owner-accepted residual (OD21-5 = c, ``docs/safety-model.md``). ``Monitor`` runs a
shell command in the same environment as ``Bash``; the schedule and remote tools start work later or elsewhere;
``EnterWorktree`` creates a git worktree; ``PublishPlugin`` publishes files. Listed as a WARN in every Claude Code
session that offers them; a session that calls one gets a WARN naming the call."""
