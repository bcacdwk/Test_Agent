"""The acceptance runner's answer to Claude Code permission prompts in headless sessions (blueprint 8.2, ATV-5).

``claude -p`` cannot show a permission prompt, and the project's ``ask`` rule on ``mcp__b1500__run_confirmed_plan``
outranks ``--allowedTools`` (deny > ask > allow), so the runner passes ``--permission-prompt-tool
mcp__acceptance_runner__permission_prompt``: Claude Code then sends every prompt (tool name and full input, i.e.
what the human would have seen) to this stdio MCP server, which plays the human of blueprint 8.2:

- it allows exactly the tools in ``$B1500_APPROVER_ALLOW`` (comma-separated; the runner sets
  ``mcp__b1500__run_confirmed_plan`` on turns that auto-approve it, nothing otherwise);
- it denies every other prompt (Bash commands outside the read-only set, file writes, ...), as an unanswered prompt
  in a headless run would be;
- it appends each prompt and decision to ``$B1500_APPROVER_LOG`` (JSONL) as grading evidence.

Claude Code hides a permission-prompt tool from the model's tool list. A tool flagged with
``_meta["anthropic/requiresUserInteraction"]`` is refused before this server is asked (ATV-12), so the runner's
config turns that policy flag off.

Run with ``python -m b1500_test_agent.devtools.acceptance.approver`` (the runner's MCP config does this).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ENV_LOG = "B1500_APPROVER_LOG"
ENV_ALLOW = "B1500_APPROVER_ALLOW"
SERVER_NAME = "acceptance_runner"
TOOL_NAME = "permission_prompt"
DENY_MESSAGE = "Denied by the acceptance runner: nobody approves this in a headless run."


def decide(tool_name: str, tool_input: dict[str, Any], *, allow: set[str], log: Path | None,
           tool_use_id: str | None = None) -> dict[str, Any]:
    """The permission decision for one prompt (Claude Code's permission-prompt-tool protocol), logged."""
    allowed = tool_name in allow
    if log is not None:
        record = {"ts": datetime.now(UTC).isoformat(), "tool_name": tool_name, "input": tool_input,
                  "tool_use_id": tool_use_id, "decision": "allow" if allowed else "deny"}
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    if allowed:
        return {"behavior": "allow", "updatedInput": tool_input}
    return {"behavior": "deny", "message": DENY_MESSAGE}


def create_server() -> Any:
    """The FastMCP app (one tool, plain text result: Claude Code expects exactly one text block)."""
    from fastmcp import FastMCP

    allow = {name.strip() for name in os.environ.get(ENV_ALLOW, "").split(",") if name.strip()}
    log_value = os.environ.get(ENV_LOG)
    log = Path(log_value) if log_value else None
    app = FastMCP(SERVER_NAME)

    @app.tool(name=TOOL_NAME, output_schema=None,
              description="Internal to the B1500 acceptance runner: answers harness permission prompts.")
    def permission_prompt(tool_name: str, input: dict[str, Any], tool_use_id: str | None = None) -> str:
        return json.dumps(decide(tool_name, input, allow=allow, log=log, tool_use_id=tool_use_id))

    return app


def main() -> None:
    """Serve the permission-prompt tool on stdio."""
    create_server().run(show_banner=False)


if __name__ == "__main__":
    main()
