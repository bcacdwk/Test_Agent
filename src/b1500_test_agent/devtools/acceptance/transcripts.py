"""Normalised harness transcripts (blueprint 8.2): one event model for Codex ``exec --json`` and Claude Code
``-p --output-format stream-json`` sessions.

Both formats are reduced, per turn, to MCP and built-in tool calls, shell commands, file writes, the raw text the
model submitted to its tools (``tool_inputs``), agent messages and the final answer. Formats were pinned with real
sessions (``tests/fixtures/transcripts/``, harness versions in their ``meta.json``):

- **Codex** (``codex exec --json``, 0.167.1): ``thread.started`` (``thread_id`` = session id), ``turn.started``,
  ``item.started``/``item.completed`` with items ``agent_message`` (``text``), ``command_execution`` (``command``,
  ``aggregated_output``, ``exit_code``, ``status``), ``file_change`` (``changes[{path, kind}]``), ``mcp_tool_call``
  (``server``, ``tool``, ``arguments``, ``result{content, structured_content}``, ``error{message}``, ``status``),
  ``turn.completed`` / ``turn.failed``. An ``error`` event (top level or item) is a transcript error, except the
  transient stream notices that codex-cli 0.170.0 emits while it retries a dropped connection,
  ``Reconnecting... n/m (...)``, and while it switches transport, ``Falling back from WebSockets to HTTPS transport``
  (WP6.6 handoff, fixed WP7.7): they go to ``notices``; a retry that gives up still ends in ``turn.failed`` (an error)
  or no ``turn.completed`` (the session fails either way). A command refused by an
  execution-policy rule never becomes an item; it is
  recovered from the ``Rejected(...)`` line Codex prints on stderr. Codex may drive its tools through a
  JavaScript "code mode" tool, so the session rollout file (``$CODEX_HOME/sessions/**/rollout-*-<id>.jsonl``) is
  read as well: every ``custom_tool_call``/``function_call``/``local_shell_call`` input becomes a ``ToolInput``
  and every ``*** Add/Update/Delete File:`` of an ``apply_patch`` a ``FileWrite``.
- **Claude Code** (``claude -p --output-format stream-json --verbose``, 2.1.326): ``system``/``init``
  (``session_id``), ``assistant`` messages with ``text``/``tool_use`` blocks (MCP tools are named
  ``mcp__<server>__<tool>``), ``user`` messages with ``tool_result`` blocks (``tool_use_id``, ``is_error``),
  ``system``/``permission_denied`` and the final ``result`` (``result`` text). Denied calls stay in the stream, so
  attempts are visible.

Token usage per turn (blueprint v2 8.2 cost policy) is read into ``TurnTranscript.usage``: Codex ``turn.completed``
``usage`` (``input_tokens`` includes ``cached_input_tokens``; ``reasoning_output_tokens``), Claude Code ``result``
(``usage``: input = ``input_tokens`` + ``cache_creation_input_tokens`` + ``cache_read_input_tokens``, cached =
``cache_read_input_tokens``; ``total_cost_usd``, the API-equivalent estimate for a subscription login).

``sanitize_lines`` prepares a real transcript for committing as a fixture (paths replaced, account details and
long signatures dropped; the Claude ``init`` keeps its built-in tool names and the project's ``b1500-*`` skills, the
evidence of the harness contract, ``contract.py``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HarnessName = Literal["codex", "claude"]
OUTPUT_CLIP = 4000
"""Characters of command output / tool result text kept per event."""

_ID_KEYS = ("plan_id", "run_id", "recipe_id", "tier", "outcome", "cancelled_run")
_APPROVAL_DENIED = re.compile(r"requires approval|approval policy|denied|rejected|not granted|permission",
                              re.IGNORECASE)
_TRANSIENT = re.compile(r"^\s*(?:Re-?connecting\s*(?:\.\.\.|\u2026)\s*\d+\s*/\s*\d+"
                        r"|Falling back from WebSockets to HTTPS transport\b)", re.IGNORECASE)
"""A Codex stream-retry or transport-fallback notice (``Reconnecting... 2/5 (stream disconnected before completion:
...)``, ``Falling back from WebSockets to HTTPS transport. workspace routing discovery failed``): not an error of the
turn by itself."""
_REJECTED = re.compile(r'Rejected\(\\?"`(?P<cmd>[^`]*)` rejected: (?P<why>[^"\\]*)')
_PATCH_FILE = re.compile(r"\*\*\* (?P<kind>Add|Update|Delete) File: (?P<path>[^\n\\\"]+)")


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=1)


class ToolCall(_Event):
    """One tool call. ``source`` ``transcript`` = what the harness reported (attempts included, ``status`` one of
    ``completed``, ``failed``, ``denied``, ``pending``); ``audit`` = what the b1500 server received (``status`` =
    the result status, e.g. ``ok``, ``refused``, ``needs_confirmation``). ``server`` is ``None`` for a harness
    built-in tool (``Bash``, ``Write``, ``Skill`` ...). An audit call outside every turn window has ``turn``
    ``None``."""

    turn: int | None = Field(default=None, ge=1)  # type: ignore[assignment]
    source: Literal["transcript", "audit"]
    server: str | None = None
    tool: str
    arguments: dict[str, Any] | None = None
    status: str | None = None
    error_code: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    plan_id: str | None = None
    run_id: str | None = None
    recipe_id: str | None = None
    tier: str | None = None
    outcome: str | None = None
    """Run outcome of a ``run_plan``/``run_confirmed_plan`` result (``running`` for an asynchronous start, v2 2.6)."""
    cancelled_run: str | None = None
    """The run a ``safe_shutdown`` stopped (its result's ``cancelled_run``; transcripts only)."""
    steps: list[str] | None = None
    """The bring-up steps a ``bringup_done`` call recorded, in order (audit only; ``None`` when the event names none:
    nothing recorded, or an audit line written before batches existed)."""
    adapter: str | None = None
    call_id: str | None = None
    subagent: bool = False
    ts: datetime | None = None


class ShellCommand(_Event):
    """A shell command the agent ran or attempted (``status`` ``completed``, ``failed``, ``denied``, ``rejected``
    by an execution-policy rule, or ``pending``)."""

    command: str
    status: str
    exit_code: int | None = None
    output: str = ""
    subagent: bool = False


class FileWrite(_Event):
    """A file the agent wrote or attempted to write through a harness file tool. ``content`` is the new text when
    the harness reports it (Claude ``Write``/``Edit``; Codex ``file_change`` items carry paths only)."""

    path: str
    kind: str
    tool: str
    status: str
    content: str | None = None
    subagent: bool = False


class ToolInput(_Event):
    """Raw text the model submitted to one tool (Codex code-mode script or patch, Claude tool input as JSON)."""

    tool: str
    text: str
    ts: datetime | None = None


class Usage(BaseModel):
    """Token usage and cost of one turn or a sum of turns (module docstring). ``input_tokens`` counts every input
    token including the cached ones; ``cost_usd`` is ``None`` when the harness reports none (Codex)."""

    model_config = ConfigDict(extra="forbid")

    turns: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    wall_s: float = Field(default=0.0, ge=0)
    models: list[str] = Field(default_factory=list)

    def __add__(self, other: Usage) -> Usage:
        cost = None if self.cost_usd is None and other.cost_usd is None else \
            (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(turns=self.turns + other.turns, input_tokens=self.input_tokens + other.input_tokens,
                     cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
                     output_tokens=self.output_tokens + other.output_tokens,
                     reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens, cost_usd=cost,
                     wall_s=self.wall_s + other.wall_s, models=list(dict.fromkeys([*self.models, *other.models])))


def _int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def codex_usage(usage: Any, model: str | None = None) -> Usage | None:
    """A Codex ``turn.completed`` ``usage`` object as ``Usage`` (``None`` when absent)."""
    if not isinstance(usage, dict):
        return None
    return Usage(turns=1, input_tokens=_int(usage, "input_tokens"), cached_input_tokens=_int(usage,
                 "cached_input_tokens"), output_tokens=_int(usage, "output_tokens"),
                 reasoning_tokens=_int(usage, "reasoning_output_tokens"), models=[model] if model else [])


def claude_usage(result: dict[str, Any]) -> Usage | None:
    """A Claude Code ``result`` event's ``usage`` and ``total_cost_usd`` as ``Usage`` (``None`` when absent)."""
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return None
    cached = _int(usage, "cache_read_input_tokens")
    details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
    cost = result.get("total_cost_usd")
    models = sorted(result["modelUsage"]) if isinstance(result.get("modelUsage"), dict) else []
    return Usage(turns=1, input_tokens=_int(usage, "input_tokens") + _int(usage, "cache_creation_input_tokens")
                 + cached, cached_input_tokens=cached, output_tokens=_int(usage, "output_tokens"),
                 reasoning_tokens=_int(details, "thinking_tokens"),
                 cost_usd=float(cost) if isinstance(cost, int | float) and cost >= 0 else None, models=models)


class TurnTranscript(BaseModel):
    """Everything one harness turn reported, normalised."""

    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=1)
    harness: HarnessName
    session_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    shell: list[ShellCommand] = Field(default_factory=list)
    files: list[FileWrite] = Field(default_factory=list)
    tool_inputs: list[ToolInput] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    final_answer: str = ""
    completed: bool = False
    errors: list[str] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    info: dict[str, Any] = Field(default_factory=dict)
    usage: Usage | None = None


# -- helpers ---------------------------------------------------------------------------------------------------------


def _json_lines(lines: Iterable[str], errors: list[str]) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except ValueError:
            errors.append(f"line {number}: not JSON: {text[:120]}")
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _clip(text: str, limit: int = OUTPUT_CLIP) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def parse_result_text(text: str) -> dict[str, Any] | None:
    """A tool result's JSON object, or ``None`` when the text is not a JSON object."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _mcp_result(result: Any) -> dict[str, Any] | None:
    """The JSON object of an MCP ``CallToolResult``: structured content, else the first text block."""
    if not isinstance(result, dict):
        return None
    for key in ("structured_content", "structuredContent"):
        if isinstance(result.get(key), dict):
            return result[key]
    for block in result.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            data = parse_result_text(block["text"])
            if data is not None:
                return data
    return None


def _ids(call: ToolCall) -> ToolCall:
    """Fill the ids, ``tier``, ``outcome`` and ``cancelled_run`` from the result, else the arguments."""
    for key in _ID_KEYS:
        if getattr(call, key) is None:
            for source in (call.result, call.arguments):
                value = source.get(key) if isinstance(source, dict) else None
                if isinstance(value, str) and value:
                    setattr(call, key, value)
                    break
    return call


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def split_tool_name(name: str) -> tuple[str | None, str]:
    """``mcp__b1500__station_status`` → ``("b1500", "station_status")``; a built-in name → ``(None, name)``."""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return parts[1], parts[2]
    return None, name


# -- Codex -----------------------------------------------------------------------------------------------------------


def _codex_status(status: Any, error: str | None) -> str:
    if status == "completed":
        return "completed"
    if status == "in_progress" or status is None:
        return "pending"
    if error and _APPROVAL_DENIED.search(error):
        return "denied"
    return "failed" if status != "declined" else "denied"


def parse_codex(lines: Iterable[str], *, turn: int = 1, stderr: str = "") -> TurnTranscript:
    """Parse one ``codex exec --json`` turn (stdout lines) plus its stderr (execution-policy rejections)."""
    out = TurnTranscript(turn=turn, harness="codex")
    items: dict[str, dict[str, Any]] = {}
    for record in _json_lines(lines, out.errors):
        kind = record.get("type")
        if kind == "thread.started":
            out.session_id = record.get("thread_id")
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = record.get("item")
            if isinstance(item, dict):
                key = str(item.get("id", len(items)))
                items[key] = item  # dicts keep first-insertion order; the latest state wins
        elif kind == "turn.completed":
            out.completed = True
            out.info["usage"] = record.get("usage")
            out.usage = codex_usage(record.get("usage"))
        elif kind == "turn.failed":
            error = record.get("error")
            out.errors.append(str(error.get("message") if isinstance(error, dict) else error))
        elif kind == "error":
            _codex_error(out, str(record.get("message", record)))
    for item in items.values():
        _codex_item(out, item)
    for match in _REJECTED.finditer(stderr):
        out.shell.append(ShellCommand(turn=turn, command=match.group("cmd"), status="rejected",
                                      output=match.group("why").strip()))
    texts = [m for m in out.messages if m.strip()]
    out.final_answer = texts[-1] if texts else ""
    return out


def _codex_item(out: TurnTranscript, item: dict[str, Any]) -> None:
    kind = item.get("type")
    turn = out.turn
    if kind == "agent_message":
        out.messages.append(str(item.get("text", "")))
    elif kind == "command_execution":
        exit_code = item.get("exit_code")
        status = _codex_status(item.get("status"), None)
        out.shell.append(ShellCommand(turn=turn, command=str(item.get("command", "")), status=status,
                                      exit_code=exit_code if isinstance(exit_code, int) else None,
                                      output=_clip(str(item.get("aggregated_output") or ""))))
    elif kind == "file_change":
        status = _codex_status(item.get("status"), None)
        for change in item.get("changes") or []:
            if isinstance(change, dict):
                out.files.append(FileWrite(turn=turn, path=str(change.get("path", "")),
                                           kind=str(change.get("kind", "update")), tool="apply_patch",
                                           status=status))
    elif kind == "mcp_tool_call":
        error = item.get("error")
        message = str(error.get("message")) if isinstance(error, dict) and error.get("message") else None
        arguments = item.get("arguments")
        call = ToolCall(turn=turn, source="transcript", server=item.get("server"), tool=str(item.get("tool", "")),
                        arguments=arguments if isinstance(arguments, dict) else None,
                        status=_codex_status(item.get("status"), message), error=message,
                        result=_mcp_result(item.get("result")), call_id=item.get("id"))
        out.tool_calls.append(_ids(call))
    elif kind == "error":
        _codex_error(out, str(item.get("message", "")))


def _codex_error(out: TurnTranscript, message: str) -> None:
    """An ``error`` event: a transient reconnect notice goes to ``notices``, anything else to ``errors``."""
    (out.notices if _TRANSIENT.match(message) else out.errors).append(message)


def parse_codex_rollout(lines: Iterable[str], turn_of: Callable[[datetime | None], int | None]) \
        -> tuple[list[ToolInput], list[FileWrite], list[dict[str, Any]]]:
    """Tool inputs and patch file writes from a Codex rollout file, attributed to turns by timestamp, plus each
    ``turn_context`` (sandbox and approval policy, model) as harness facts."""
    errors: list[str] = []
    inputs: list[ToolInput] = []
    writes: list[FileWrite] = []
    contexts: list[dict[str, Any]] = []
    for record in _json_lines(lines, errors):
        ts = _ts(record.get("timestamp"))
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record.get("type") == "turn_context":
            contexts.append({"ts": record.get("timestamp"), "turn": turn_of(ts),
                             **{k: payload.get(k) for k in ("approval_policy", "sandbox_policy", "model", "effort")}})
            continue
        if record.get("type") != "response_item":
            continue
        kind = payload.get("type")
        if kind == "custom_tool_call":
            text = str(payload.get("input", ""))
        elif kind == "function_call":
            text = str(payload.get("arguments", ""))
        elif kind == "local_shell_call":
            action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
            command = action.get("command")
            text = " ".join(command) if isinstance(command, list) else str(command or "")
        else:
            continue
        turn = turn_of(ts)
        if turn is None:
            continue
        name = str(payload.get("name") or kind)
        inputs.append(ToolInput(turn=turn, tool=name, text=text, ts=ts))
        for match in _PATCH_FILE.finditer(text):
            writes.append(FileWrite(turn=turn, path=match.group("path").strip(), kind=match.group("kind").lower(),
                                    tool="apply_patch", status="requested"))
    return inputs, writes, contexts


# -- Claude Code -----------------------------------------------------------------------------------------------------


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def parse_claude(lines: Iterable[str], *, turn: int = 1) -> TurnTranscript:
    """Parse one ``claude -p --output-format stream-json --verbose`` turn."""
    out = TurnTranscript(turn=turn, harness="claude")
    uses: dict[str, dict[str, Any]] = {}
    results: dict[str, tuple[str, bool, str | None]] = {}
    denied: dict[str, str] = {}
    last_text: list[str] = []
    result_text: str | None = None
    for record in _json_lines(lines, out.errors):
        kind = record.get("type")
        subtype = record.get("subtype")
        if kind == "system" and subtype == "init":
            out.session_id = record.get("session_id")
            out.info.update({k: record.get(k) for k in ("model", "permissionMode", "mcp_servers", "cwd",
                                                        "claude_code_version")})
        elif kind == "system" and subtype == "permission_denied":
            denied[str(record.get("tool_use_id"))] = str(record.get("message", "permission denied"))
        elif kind == "assistant":
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            sub = record.get("parent_tool_use_id") is not None
            texts = []
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and not sub:
                    texts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    uses[str(block.get("id"))] = {"name": str(block.get("name", "")), "input": block.get("input"),
                                                  "subagent": sub}
            if texts:
                out.messages.extend(texts)
                last_text = texts
        elif kind == "user":
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            meta = {m.get("id"): m for m in record.get("tool_result_meta") or [] if isinstance(m, dict)}
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    use_id = str(block.get("tool_use_id"))
                    decision = (meta.get(use_id) or {}).get("permission_decision") or {}
                    rejected = decision.get("decision") == "reject" if isinstance(decision, dict) else False
                    results[use_id] = (_block_text(block.get("content")), bool(block.get("is_error")),
                                       "denied" if rejected else None)
        elif kind == "result":
            out.completed = True
            if isinstance(record.get("result"), str):
                result_text = record["result"]
            if record.get("is_error"):
                out.errors.append(f"result {record.get('subtype')}: {record.get('result')}")
            out.info["permission_denials"] = record.get("permission_denials")
            out.usage = claude_usage(record)
    for use_id, use in uses.items():
        _claude_use(out, use_id, use, results.get(use_id), denied.get(use_id))
    out.final_answer = result_text if result_text is not None else "\n".join(last_text)
    return out


def _claude_use(out: TurnTranscript, use_id: str, use: dict[str, Any], result: tuple[str, bool, str | None] | None,
                denial: str | None) -> None:
    name = use["name"]
    data = use["input"] if isinstance(use["input"], dict) else {}
    sub = bool(use["subagent"])
    text, is_error, decision = result if result is not None else ("", False, None)
    if denial is not None or decision == "denied":
        status = "denied"
    elif result is None:
        status = "pending"
    else:
        status = "failed" if is_error else "completed"
    turn = out.turn
    out.tool_inputs.append(ToolInput(turn=turn, tool=name, text=json.dumps(data, ensure_ascii=False)))
    server, tool = split_tool_name(name)
    call = ToolCall(turn=turn, source="transcript", server=server, tool=tool, arguments=data, status=status,
                    error=(denial or text) if status in ("denied", "failed") else None,
                    result=parse_result_text(text) if status == "completed" else None, call_id=use_id,
                    subagent=sub)
    out.tool_calls.append(_ids(call))
    if name in ("Bash", "PowerShell"):
        out.shell.append(ShellCommand(turn=turn, command=str(data.get("command", "")), status=status,
                                      output=_clip(text), subagent=sub))
    elif name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = data.get("file_path") or data.get("notebook_path") or ""
        if name == "Write":
            content = data.get("content")
        elif name == "Edit":
            content = data.get("new_string")
        elif name == "MultiEdit":
            content = "\n".join(str(e.get("new_string", "")) for e in data.get("edits") or [] if isinstance(e, dict))
        else:
            content = data.get("new_source")
        out.files.append(FileWrite(turn=turn, path=str(path), kind=name.lower(), tool=name, status=status,
                                   content=content if isinstance(content, str) else None, subagent=sub))


def parse_turn(harness: HarnessName, lines: Iterable[str], *, turn: int = 1, stderr: str = "") -> TurnTranscript:
    """Parse one turn of either harness."""
    return parse_codex(lines, turn=turn, stderr=stderr) if harness == "codex" else parse_claude(lines, turn=turn)


# -- fixtures --------------------------------------------------------------------------------------------------------

_SIGNATURE = re.compile(r'"signature":\s*"[^"]*"')
_CLAUDE_INIT_DROP = ("slash_commands", "terminal_slash_commands", "plugins", "agents", "memory_paths",
                     "messaging_socket_path", "capabilities")
PROJECT_SKILL_PREFIX = "b1500-"
"""Skills a sanitized ``init`` keeps (the user's own skills and plugins are left out)."""


def sanitize_lines(lines: Iterable[str], replacements: Mapping[str, str], *,
                   drop_types: Iterable[str] = ("rate_limit_event",)) -> list[str]:
    """A real transcript prepared for committing: each ``replacements`` key (raw and JSON-escaped) replaced by its
    value (longest first), lines of ``drop_types`` removed, Claude ``init`` without the user's slash commands,
    plugins, agents and memory paths and with only the project's skills (built-in and ``mcp__`` tool names stay),
    account fields and thinking signatures blanked."""
    drop = set(drop_types)
    pairs: list[tuple[str, str]] = []
    for old, new in sorted(replacements.items(), key=lambda kv: -len(kv[0])):
        pairs.append((old, new))
        escaped = json.dumps(old)[1:-1]
        if escaped != old:
            pairs.append((escaped, new))
    cleaned = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if isinstance(record, dict):
            if record.get("type") in drop:
                continue
            if record.get("type") == "system" and record.get("subtype") == "init":
                for key in _CLAUDE_INIT_DROP:
                    record.pop(key, None)
                skills = record.get("skills")
                if isinstance(skills, list):
                    record["skills"] = [s for s in skills if str(s).startswith(PROJECT_SKILL_PREFIX)]
            for key in ("credential_expires_at", "rate_limit_info"):
                record.pop(key, None)
            line = json.dumps(record, ensure_ascii=False)
        line = _SIGNATURE.sub('"signature": "<signature>"', line.rstrip("\n"))
        for old, new in pairs:
            line = line.replace(old, new)
        cleaned.append(line)
    return cleaned
