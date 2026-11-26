"""Stop at the first infrastructure event (v2.1 plan §2.4; owner rule OD21-4 = a: strict, reconnect notices included).

A watcher per harness turn tails the turn's stdout (JSONL) and stderr as they grow. The first line that shows the
harness's login, API or network path failing is an **infra event**: the runner kills the turn's process tree, marks
the session ``infra_stopped``, starts no further session (no next rep, no re-run) and ``acceptance run`` /
``dev harness qualify`` exit 3 with the raw line. Owner rule: on any API, login or network error stop at once, no
retries; the human decides when to go on.

Generic by construction (any failed completion stops), so it needs no table per harness release:

- **Codex** stdout: ``turn.failed``; any ``error`` event, top level or item, including the transient
  ``Reconnecting... n/m`` and ``Falling back from WebSockets to HTTPS transport`` notices that ``session ok`` lists as
  notices (strict: they show the connection failing).
- **Claude Code** stdout: a ``result`` with ``is_error``, a subtype other than ``success`` or an ``api_error_status``;
  an ``assistant`` message carrying an ``error`` (authentication, billing, rate limit, server); a ``system`` event
  whose subtype names a retry or an error (``api_retry``); a ``rate_limit_event`` whose status is not ``allowed``
  (the informational ``allowed`` events, 84 in the WP11.5 batch, never stop); an ``error`` event.
- **stderr** (both, and non-JSON stdout lines): auth (401/403, not logged in, invalid API key, expired token), HTTP
  429/5xx and rate or usage limits, DNS and connection failures, timeouts of a request; lines below the warning level
  (``INFO``/``DEBUG``/``TRACE``) and Codex lines about the agent's own tool calls (an execution-policy ``Rejected``,
  a failed ``exec_command``: they quote the agent's command text) are skipped.
- **Exit**: a turn that ended by itself (not by the runner's timeout) without a completion event.

``scan_session`` applies the same rules to a recorded session folder (pinning on real transcripts, re-checks).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

InfraKind = Literal["turn_failed", "error_event", "result_error", "assistant_error", "api_retry", "rate_limit",
                    "auth", "http_status", "network", "no_completion"]
Stream = Literal["stdout", "stderr", "exit"]
LINE_CLIP = 600
"""Characters of the raw line kept in the event."""
SHORT_RAW = 200
"""Characters of the raw line shown next to the summary in messages and reports."""

_SKIP_LEVEL = re.compile(r"^\s*(?:\S+\s+)?(?:INFO|DEBUG|TRACE)\b")
"""A tracing line below the warning level (``2026-11-25T20:51:08Z  INFO codex_core: ...``)."""
_AGENT_TOOL_LINE = re.compile(r"codex_core::tools|exec_command failed|\bRejected\(")
"""A Codex stderr line about the agent's own tool call (an execution-policy rejection, a failed command): it quotes
the agent's command text, which may contain any word, and is graded as a shell attempt, never an infra event."""
_STDERR_RULES: tuple[tuple[InfraKind, re.Pattern[str]], ...] = (
    ("auth", re.compile(
        r"\b(?:status|http|code|error)\W{0,3}(?:401|403)\b|\b(?:401|403)\W{0,3}(?:unauthori[sz]ed|forbidden)\b"
        r"|\bunauthori[sz]ed\b|not logged in|\blog ?in (?:again|required)\b|please (?:run )?/?login"
        r"|invalid[ _-]api[ _-]key|authentication[ _-](?:error|failed|required)"
        r"|(?:access|refresh|oauth|auth) token\b.{0,40}\b(?:expired|invalid|revoked)|credentials? (?:expired|invalid)",
        re.IGNORECASE)),
    ("http_status", re.compile(
        r"\b(?:429|5\d\d)\b.{0,40}\b(?:status|too many requests|internal server error|bad gateway|"
        r"service unavailable|gateway time-?out|overloaded)|\b(?:status|http)(?: code)?[ :=]+(?:429|5\d\d)\b"
        r"|unexpected status (?:429|5\d\d)|too many requests|rate[ _-]?limit(?:ed|_error)?\b|usage limit"
        r"|quota (?:exceeded|exhausted)|insufficient_quota|overloaded_error|\boverloaded\b",
        re.IGNORECASE)),
    ("network", re.compile(
        r"dns error|failed to lookup address|could not resolve (?:host|hostname)|name or service not known"
        r"|nodename nor servname|getaddrinfo|\bENOTFOUND\b|\bEAI_AGAIN\b|connection (?:refused|reset|closed|aborted"
        r"|timed out|error)|\bECONNREFUSED\b|\bECONNRESET\b|\bETIMEDOUT\b|network is unreachable|no route to host"
        r"|error sending request|failed to connect|tls handshake|certificate verify failed|request timed out"
        r"|\btimed out\b.{0,40}\b(?:request|connect|stream|response)|stream disconnected|can't reach",
        re.IGNORECASE)),
)


class InfraEvent(BaseModel):
    """The first infrastructure event of a turn: kind, where it was seen and the raw line (clipped)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: InfraKind
    stream: Stream
    line: str = Field(description="The raw line (or the exit fact), clipped to LINE_CLIP characters.")
    turn: int | None = Field(default=None, ge=1)
    summary: str = Field(default="", description="What the event says (its message, status or error), for people.")

    def describe(self) -> str:
        where = f"turn {self.turn} " if self.turn else ""
        if self.summary and self.summary != self.line:
            return f"{where}{self.stream}: {self.kind}: {self.summary} (raw: {self.line[:SHORT_RAW]})"
        return f"{where}{self.stream}: {self.kind}: {self.line}"


class InfraStop(BaseModel):
    """Where a batch stopped (``BatchResult.infra_stop``): the session folder, scenario, rep and the event."""

    model_config = ConfigDict(extra="forbid")

    session: str
    scenario_id: str
    rep: int
    rerun: bool = False
    event: InfraEvent

    def describe(self) -> str:
        return f"{self.session}: {self.event.describe()}"


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= LINE_CLIP else text[: LINE_CLIP - 3] + "..."


def _event(kind: InfraKind, stream: Stream, line: str, turn: int | None, summary: str = "") -> InfraEvent:
    return InfraEvent(kind=kind, stream=stream, line=_clip(line), turn=turn, summary=_clip(summary))


def _message(value: Any) -> str:
    """The message of an error field (a string or ``{message|type: ...}``)."""
    if isinstance(value, dict):
        return str(value.get("message") or value.get("type") or json.dumps(value, ensure_ascii=False))
    return "" if value is None else str(value)


def _text(record: dict[str, Any]) -> str:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    blocks = message.get("content") if isinstance(message.get("content"), list) else []
    return " ".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text")


def classify_text(line: str, *, stream: Stream = "stderr", turn: int | None = None) -> InfraEvent | None:
    """A diagnostic text line (stderr, or a non-JSON stdout line) that shows a login, API or network failure."""
    if not line.strip() or _SKIP_LEVEL.match(line) or _AGENT_TOOL_LINE.search(line):
        return None
    for kind, pattern in _STDERR_RULES:
        if pattern.search(line):
            return _event(kind, stream, line, turn)
    return None


def _codex_record(record: dict[str, Any], line: str, turn: int | None) -> InfraEvent | None:
    kind = record.get("type")
    if kind == "turn.failed":
        return _event("turn_failed", "stdout", line, turn, f"turn.failed: {_message(record.get('error'))}")
    if kind == "error":
        return _event("error_event", "stdout", line, turn, f"error: {_message(record.get('message'))}")
    item = record.get("item")
    if isinstance(kind, str) and kind.startswith("item.") and isinstance(item, dict) and item.get("type") == "error":
        return _event("error_event", "stdout", line, turn, f"error item: {_message(item.get('message'))}")
    return None


def _claude_record(record: dict[str, Any], line: str, turn: int | None) -> InfraEvent | None:
    kind, subtype = record.get("type"), str(record.get("subtype") or "")
    if kind == "result" and (record.get("is_error") or subtype != "success"
                             or record.get("api_error_status") not in (None, "", 0)):
        status = record.get("api_error_status")
        return _event("result_error", "stdout", line, turn, f"result {subtype or '?'}, is_error "
                      f"{record.get('is_error')}" + (f", API status {status}" if status else "")
                      + f": {_message(record.get('result'))}")
    if kind == "assistant" and record.get("error"):
        return _event("assistant_error", "stdout", line, turn, f"assistant error {_message(record.get('error'))}: "
                      f"{_text(record)}")
    if kind == "system" and re.search(r"retry|error", subtype, re.IGNORECASE):
        detail = {k: record.get(k) for k in ("attempt", "max_retries", "error_status", "error") if k in record}
        return _event("api_retry" if "retry" in subtype.lower() else "error_event", "stdout", line, turn,
                      f"system/{subtype} {json.dumps(detail, ensure_ascii=False)}")
    if kind == "rate_limit_event":
        info = record.get("rate_limit_info") if isinstance(record.get("rate_limit_info"), dict) else {}
        if info.get("status") != "allowed":
            return _event("rate_limit", "stdout", line, turn, f"rate limit status {info.get('status')!r} "
                          f"({info.get('rateLimitType')})")
    if kind == "error":
        return _event("error_event", "stdout", line, turn, f"error: {_message(record.get('error'))}")
    return None


def classify_stdout(harness: str, line: str, *, turn: int | None = None) -> InfraEvent | None:
    """One stdout line of a turn: a harness event (JSON) or, when not JSON, a diagnostic text line."""
    text = line.strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return classify_text(text, stream="stdout", turn=turn)
    if not isinstance(record, dict):
        return None
    return _codex_record(record, text, turn) if harness == "codex" else _claude_record(record, text, turn)


def completed(harness: str, lines: list[str]) -> bool:
    """The turn's stdout has its completion event (Codex ``turn.completed``, Claude Code ``result``)."""
    wanted = "turn.completed" if harness == "codex" else "result"
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("type") == wanted:
            return True
    return False


def exit_event(harness: str, stdout_lines: list[str], stderr_lines: list[str], exit_code: int | None, *,
               turn: int | None = None) -> InfraEvent | None:
    """A turn that ended by itself without a completion event (a failed completion: login, crash, refused launch)."""
    if completed(harness, stdout_lines):
        return None
    last = next((line.strip() for line in reversed(stderr_lines) if line.strip()), "")
    fact = f"exit {exit_code} without a completion event" + (f"; last stderr line: {last}" if last else "")
    return _event("no_completion", "exit", fact, turn)


class _Tail:
    """New complete lines of a growing file (bytes decoded as UTF-8, damaged bytes replaced)."""

    def __init__(self, path: Path) -> None:
        self.path, self.offset, self.rest = path, 0, b""

    def read(self, *, final: bool = False) -> list[str]:
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
        except OSError:
            return []
        self.offset += len(chunk)
        data = self.rest + chunk
        parts = data.split(b"\n")
        self.rest = b"" if final else parts.pop()
        return [part.decode("utf-8", errors="replace").rstrip("\r") for part in parts if part.strip()]


class InfraWatcher:
    """Tails one turn's stdout and stderr files; ``poll`` returns the first infra event (once found, always it)."""

    def __init__(self, harness: str, stdout: Path, stderr: Path, *, turn: int | None = None) -> None:
        self.harness, self.turn = harness, turn
        self._out, self._err = _Tail(stdout), _Tail(stderr)
        self.event: InfraEvent | None = None

    def poll(self, *, final: bool = False) -> InfraEvent | None:
        if self.event is None:
            for line in self._out.read(final=final):
                self.event = classify_stdout(self.harness, line, turn=self.turn)
                if self.event is not None:
                    break
        if self.event is None:
            for line in self._err.read(final=final):
                self.event = classify_text(line, turn=self.turn)
                if self.event is not None:
                    break
        return self.event


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def scan_turn(harness: str, stdout_lines: list[str], stderr_lines: list[str], *, turn: int | None = None,
              exit_code: int | None = None, check_exit: bool = False) -> list[InfraEvent]:
    """Every infra event of one recorded turn (stdout first, then stderr; with ``check_exit`` the exit rule too)."""
    events = [e for line in stdout_lines if (e := classify_stdout(harness, line, turn=turn)) is not None]
    events += [e for line in stderr_lines if (e := classify_text(line, turn=turn)) is not None]
    if check_exit:
        found = exit_event(harness, stdout_lines, stderr_lines, exit_code, turn=turn)
        events += [found] if found is not None else []
    return events


def scan_session(session_dir: Path) -> list[InfraEvent]:
    """Every infra event of a recorded session folder (``session.json`` turns; timed-out turns skip the exit rule)."""
    record = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    events: list[InfraEvent] = []
    for turn in record.get("turns") or []:
        events += scan_turn(record["harness"], _lines(session_dir / turn["transcript"]),
                            _lines(session_dir / turn["stderr"]), turn=turn.get("index"),
                            exit_code=turn.get("exit_code"), check_exit=not turn.get("timed_out"))
    return events
