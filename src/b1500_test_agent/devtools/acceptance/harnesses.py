"""Headless harness launch for the acceptance runner (blueprint 8.2, 9.6; never a bypass mode).

**Codex** (``codex exec``): ``codex exec --json -s workspace-write -C <repo> -c ... <prompt>``, later turns
``codex exec resume --json -c ... <thread_id> <prompt>``. The b1500 server is passed as ``-c mcp_servers.b1500.*``
overrides rendered from ``config/harness/codex.config.toml`` (same launch, timeouts and approval modes as
``harness init``) plus the temporary ``B1500_CONFIG_DIR``/``B1500_DATA_DIR``/``B1500_SESSION_TAG`` in its ``env``.
``run_confirmed_plan`` gets ``approval_mode = "approve"`` on turns that auto-approve it (``exec`` runs with approval
policy ``never``, which denies a ``prompt`` tool: ATV-6), else ``"prompt"``. ``sandbox_mode = "workspace-write"``
is passed on every turn because ``exec resume`` has no ``-s`` and a user config may default to full access.

**Claude Code** (``claude -p``): ``claude -p --output-format stream-json --verbose --include-hook-events
--forward-subagent-text --mcp-config <turn>.json --strict-mcp-config --setting-sources user,project
--permission-prompt-tool mcp__acceptance_runner__permission_prompt [--allowedTools mcp__b1500__run_confirmed_plan]
[--resume <session_id>] -- <prompt>``. The project's ``ask`` rule outranks ``--allowedTools`` (ATV-5), so the
runner's permission-prompt server (``approver.py``) answers prompts: it allows ``run_confirmed_plan`` on
auto-approving turns and denies everything else. ``--setting-sources user,project`` leaves out the personal
``.claude/settings.local.json``; ``CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`` keeps the user's auto-memory out.

Both harnesses inherit a cleaned environment (no ``CLAUDE*``/``B1500_*`` of a calling session) plus the three
``B1500_*`` variables, so the agent's own ``b1500`` CLI calls use the same temporary dirs and are audited with the
same session tag.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from b1500_test_agent.devtools.acceptance import approver
from b1500_test_agent.devtools.acceptance.transcripts import HarnessName
from b1500_test_agent.devtools.harness import CONFIRM_TOOL, SERVER_NAME, TARGETS, render
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR
from b1500_test_agent.service import ENV_SESSION_TAG

EXECUTABLES: dict[HarnessName, str] = {"codex": "codex", "claude": "claude"}
ENV_DROP_PREFIXES = ("CLAUDE", "B1500_", "AI_AGENT", "CODEX_SANDBOX")
ENV_KEEP = frozenset({"CLAUDE_CONFIG_DIR"})
CLAUDE_CONFIRM = f"mcp__{SERVER_NAME}__{CONFIRM_TOOL}"
CLAUDE_PROMPT_TOOL = f"mcp__{approver.SERVER_NAME}__{approver.TOOL_NAME}"
APPROVER_MODULE = "b1500_test_agent.devtools.acceptance.approver"
FORBIDDEN_ARGS = ("--yolo", "--dangerously-bypass-approvals-and-sandbox", "--dangerously-skip-permissions",
                  "--allow-dangerously-skip-permissions", "bypassPermissions", "danger-full-access", "--ignore-rules",
                  "--approve-for-me", "--dangerously-bypass-hook-trust", "--full-auto")
_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.]+)?")


class HarnessError(RuntimeError):
    """The harness cannot be launched (not installed, forbidden argument, unreadable template)."""


@dataclass
class TurnLaunch:
    """Everything one harness invocation needs."""

    harness: HarnessName
    repo: Path
    session_dir: Path
    config_dir: Path
    data_dir: Path
    tag: str
    turn: int
    prompt: str
    approve_confirm_tool: bool
    resume_id: str | None = None
    extra_args: list[str] = field(default_factory=list)

    @property
    def prompt_log(self) -> Path:
        return self.session_dir / "transcripts" / "prompts.jsonl"


def executable(harness: HarnessName) -> str:
    """Absolute path of the harness CLI (``HarnessError`` when it is not on PATH)."""
    found = shutil.which(EXECUTABLES[harness])
    if found is None:
        raise HarnessError(f"{EXECUTABLES[harness]} is not installed or not on PATH")
    return found


def harness_version(harness: HarnessName) -> str:
    """``codex --version`` / ``claude --version`` reduced to the version number (raw text if none is found)."""
    result = subprocess.run([executable(harness), "--version"], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60, env=clean_env(os.environ), stdin=subprocess.DEVNULL,
                            check=False)
    text = (result.stdout or result.stderr).strip()
    match = _VERSION.search(text)
    return match.group() if match else (text or "unknown")


def clean_env(base: Mapping[str, str]) -> dict[str, str]:
    """``base`` without the variables of a calling harness session or a previous runner (see module docstring)."""
    return {k: v for k, v in base.items() if k in ENV_KEEP or not k.startswith(ENV_DROP_PREFIXES)}


def server_env(launch: TurnLaunch) -> dict[str, str]:
    """Environment of the b1500 MCP server (and of the agent's shell): UTF-8 plus the runner's temp dirs and tag."""
    return {"PYTHONUTF8": "1", ENV_CONFIG_DIR: str(launch.config_dir), ENV_DATA_DIR: str(launch.data_dir),
            ENV_SESSION_TAG: launch.tag}


def process_env(launch: TurnLaunch, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment of the harness process."""
    env = clean_env(os.environ if base is None else base)
    env.update(server_env(launch))
    if launch.harness == "claude":
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return env


def check_extra_args(args: list[str]) -> None:
    """Refuse any bypass-mode argument (guardrail 9.0.5)."""
    for arg in args:
        if any(bad.lower() in arg.lower() for bad in FORBIDDEN_ARGS):
            raise HarnessError(f"refused harness argument {arg!r}: bypass and full-access modes are never used")


# -- Codex -----------------------------------------------------------------------------------------------------------


def toml_value(value: Any) -> str:
    """``value`` as an inline TOML value (strings as JSON-escaped basic strings)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_toml_key(k)} = {toml_value(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def codex_server(launch: TurnLaunch) -> dict[str, Any]:
    """The ``[mcp_servers.b1500]`` table for this turn (rendered template + env + confirm-tool approval mode)."""
    target = TARGETS["codex"]
    try:
        template = (launch.repo / target.template).read_text(encoding="utf-8")
        server = tomllib.loads(render(target, template, launch.repo))["mcp_servers"][SERVER_NAME]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise HarnessError(f"cannot render {target.template}: {exc}") from exc
    server["env"] = {**server.get("env", {}), **server_env(launch)}
    tools = server.setdefault("tools", {})
    tools.setdefault(CONFIRM_TOOL, {})["approval_mode"] = "approve" if launch.approve_confirm_tool else "prompt"
    return server


def codex_overrides(launch: TurnLaunch) -> list[str]:
    """``-c`` values: the b1500 server table flattened, plus the workspace-write sandbox."""
    server = codex_server(launch)
    prefix = f"mcp_servers.{SERVER_NAME}"
    out = []
    for key, value in server.items():
        if key == "tools":
            for tool, table in value.items():
                out += [f"{prefix}.tools.{tool}.{k}={toml_value(v)}" for k, v in table.items()]
        else:
            out.append(f"{prefix}.{key}={toml_value(value)}")
    out.append('sandbox_mode="workspace-write"')
    return out


def codex_argv(launch: TurnLaunch, exe: str = "codex") -> list[str]:
    check_extra_args(launch.extra_args)
    flags = [part for value in codex_overrides(launch) for part in ("-c", value)]
    if launch.resume_id is None:
        return [exe, "exec", "--json", "-s", "workspace-write", "-C", str(launch.repo), *flags, *launch.extra_args,
                launch.prompt]
    return [exe, "exec", "resume", "--json", *flags, *launch.extra_args, launch.resume_id, launch.prompt]


def codex_home(env: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if env is None else env
    return Path(environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_rollout(thread_id: str, env: Mapping[str, str] | None = None) -> Path | None:
    """The rollout file Codex keeps for a session (read-only)."""
    sessions = codex_home(env) / "sessions"
    if not sessions.is_dir() or not re.fullmatch(r"[0-9A-Za-z-]+", thread_id):
        return None
    matches = sorted(sessions.glob(f"*/*/*/rollout-*-{thread_id}.jsonl"))
    return matches[-1] if matches else None


def codex_project_trusted(repo: Path, env: Mapping[str, str] | None = None) -> bool | None:
    """Whether the user's Codex config lists ``repo`` as a trusted project (read-only; ``None`` = unknown)."""
    try:
        data = tomllib.loads((codex_home(env) / "config.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
    entry = projects.get(str(repo)) or projects.get(repo.as_posix())
    return isinstance(entry, dict) and entry.get("trust_level") == "trusted"


# -- Claude Code -----------------------------------------------------------------------------------------------------


def claude_mcp_config(launch: TurnLaunch) -> dict[str, Any]:
    """The ``--mcp-config`` content for this turn: the b1500 server (rendered template + env) and the runner's
    permission-prompt server."""
    target = TARGETS["claude"]
    try:
        template = (launch.repo / target.template).read_text(encoding="utf-8")
        config = json.loads(render(target, template, launch.repo))
        server = config["mcpServers"][SERVER_NAME]
    except (OSError, KeyError, ValueError) as exc:
        raise HarnessError(f"cannot render {target.template}: {exc}") from exc
    server["env"] = {**server.get("env", {}), **server_env(launch)}
    allow = CLAUDE_CONFIRM if launch.approve_confirm_tool else ""
    config["mcpServers"][approver.SERVER_NAME] = {
        "type": "stdio", "command": "uv",
        "args": ["run", "--frozen", "--project", launch.repo.as_posix(), "python", "-m", APPROVER_MODULE],
        "env": {"PYTHONUTF8": "1", approver.ENV_LOG: str(launch.prompt_log), approver.ENV_ALLOW: allow},
    }  # fmt: skip
    return config


def claude_argv(launch: TurnLaunch, mcp_config: Path, exe: str = "claude") -> list[str]:
    check_extra_args(launch.extra_args)
    argv = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-hook-events",
            "--forward-subagent-text", "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--setting-sources", "user,project", "--permission-prompt-tool", CLAUDE_PROMPT_TOOL]
    if launch.approve_confirm_tool:
        argv += ["--allowedTools", CLAUDE_CONFIRM]
    if launch.resume_id is not None:
        argv += ["--resume", launch.resume_id]
    return [*argv, *launch.extra_args, "--", launch.prompt]


def turn_argv(launch: TurnLaunch, exe: str) -> tuple[list[str], dict[str, Any] | None]:
    """argv for one turn and, for Claude Code, the MCP config to write to ``mcp/turn-<n>.json`` first."""
    if launch.harness == "codex":
        return codex_argv(launch, exe), None
    config = claude_mcp_config(launch)
    return claude_argv(launch, launch.session_dir / "mcp" / f"turn-{launch.turn}.json", exe), config
