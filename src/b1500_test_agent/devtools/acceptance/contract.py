"""Harness contract (v2.1 plan §2.5): what every session of a harness must show for the graders to see everything.

Run for every session as the implicit grader ``harness contract`` (after ``session ok``) and summed by ``dev harness
qualify`` at T1/T2. Read from the raw transcripts, never part of ``b1500 update``.

**Structural (FAIL)**, per turn that ended by itself (a timed-out or infra-stopped turn already fails ``session ok``):

- both harnesses: a session id, a completion event and its token usage;
- Codex: the rollout file (``transcripts/codex-rollout.jsonl``), the only place where code-mode tool inputs live;
- Claude Code: ``permissionMode`` ``default``, the b1500 server ``connected``, every project skill
  (``.agents/skills/*/SKILL.md``) in the ``init`` event's ``skills`` list, and a ``PreToolUse`` ``hook_response`` for
  every call of a tool of the hook matcher (``harness.HOOK_TOOLS``) in each turn launched with
  ``--include-hook-events`` (every runner turn; older recordings lack the events).

**Table-based (WARN only)**: event, item, block and rollout types and tool names outside the known vocabulary
(``vocabulary.py``), an ``init`` event without a ``skills`` field, and the owner-accepted residual (OD21-5 = c):
shell- or write-capable built-ins offered outside the hook matcher (``Monitor`` and the schedule/remote tools), with
a separate WARN when the agent called one.

Every finding carries the surface it puts at risk (plan §2.6), so ``qualify --escalate`` can pick the T3 set.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from b1500_test_agent.devtools.acceptance import vocabulary
from b1500_test_agent.devtools.acceptance.evidence import ROLLOUT_FILE, Evidence, TurnRecord
from b1500_test_agent.devtools.harness import HOOK_TOOLS, SERVER_NAME

Surface = Literal["format", "approval", "hook", "lifecycle", "instructions", "unclear"]
ContractVerdict = Literal["pass", "warn", "fail"]
PROJECT_SKILLS = ("b1500-bringup", "b1500-debug", "b1500-test")
"""Fallback when the session's repository has no readable ``.agents/skills/``."""
HOOK_FLAG = "--include-hook-events"
CLIP = 160


@dataclass(frozen=True)
class Finding:
    """One contract finding; ``surface`` ``None`` = the accepted residual (nothing to escalate)."""

    surface: Surface | None
    text: str


@dataclass
class ContractResult:
    """Structural problems (FAIL) and table-based warnings (WARN) of one session."""

    harness: str
    problems: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> ContractVerdict:
        return "fail" if self.problems else "warn" if self.warnings else "pass"

    def surfaces(self, *, warnings: bool = False) -> set[Surface]:
        """Surfaces of the problems (or of the warnings) that point at one (the residual points at none)."""
        items = self.warnings if warnings else self.problems
        return {f.surface for f in items if f.surface is not None}

    def outcome(self) -> tuple[ContractVerdict, str, list[str]]:
        head = f"structural: {len(self.problems)} problem(s)" if self.problems else "structural: ok"
        head += f"; {len(self.warnings)} WARN" if self.warnings else ""
        head += f" ({', '.join(self.checked)})" if self.checked else ""
        details = [f"FAIL [{f.surface}] {f.text}" for f in self.problems]
        details += [f"WARN [{f.surface or 'residual'}] {f.text}" for f in self.warnings]
        return self.verdict, head, list(dict.fromkeys(details))

    def problem(self, surface: Surface, text: str) -> None:
        self.problems.append(Finding(surface, text))

    def warn(self, surface: Surface | None, text: str) -> None:
        finding = Finding(surface, text)
        if finding not in self.warnings:
            self.warnings.append(finding)


def _records(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= CLIP else text[: CLIP - 3] + "..."


def project_skills(repo_root: str) -> tuple[str, ...]:
    """The skills of the session's repository (folders of ``.agents/skills/`` with a ``SKILL.md``)."""
    folder = Path(repo_root) / ".agents" / "skills"
    try:
        found = tuple(sorted(p.parent.name for p in folder.glob("*/SKILL.md")))
    except OSError:
        found = ()
    return found or PROJECT_SKILLS


def _ended_by_itself(turn: TurnRecord) -> bool:
    return not turn.timed_out and turn.infra_event is None


# -- Codex -----------------------------------------------------------------------------------------------------------


def _codex(ev: Evidence, out: ContractResult) -> None:
    session_ids = []
    for turn in ev.record.turns:
        records = _records(ev.root / turn.transcript)
        types = Counter(str(r.get("type")) for r in records)
        thread = next((r.get("thread_id") for r in records if r.get("type") == "thread.started"), None)
        if thread:
            session_ids.append(thread)
        for kind in sorted(set(types) - vocabulary.CODEX_EVENTS):
            out.warn("format", f"turn {turn.index}: unknown event type {kind!r} ({types[kind]}x)")
        items = Counter(str(r["item"].get("type")) for r in records if isinstance(r.get("item"), dict))
        for kind in sorted(set(items) - vocabulary.CODEX_ITEMS):
            out.warn("format", f"turn {turn.index}: unknown item type {kind!r} ({items[kind]}x)")
        if not _ended_by_itself(turn):
            continue
        if not thread:
            out.problem("format", f"turn {turn.index}: no thread.started with a thread_id (session id)")
        done = [r for r in records if r.get("type") == "turn.completed"]
        if not done:
            out.problem("format", f"turn {turn.index}: no turn.completed event")
        elif not isinstance(done[-1].get("usage"), dict):
            out.problem("format", f"turn {turn.index}: turn.completed carries no usage")
    rollout = ev.root / ROLLOUT_FILE
    if session_ids and not rollout.is_file():
        out.problem("format", "Codex rollout file missing: code-mode tool inputs (shell commands, patches) are not "
                              "graded")
    elif rollout.is_file():
        _codex_rollout(_records(rollout), out)
    out.checked.append(f"{len(ev.record.turns)} turn(s)" + (", rollout" if rollout.is_file() else ""))


def _codex_rollout(records: list[dict[str, Any]], out: ContractResult) -> None:
    kinds, payloads, tools = Counter(), Counter(), Counter()
    for record in records:
        kinds[str(record.get("type"))] += 1
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record.get("type") in ("response_item", "event_msg") and payload.get("type"):
            payloads[str(payload["type"])] += 1
        if payload.get("type") in ("custom_tool_call", "function_call"):
            tools[str(payload.get("name"))] += 1
    for kind in sorted(set(kinds) - vocabulary.CODEX_ROLLOUT_RECORDS):
        out.warn("format", f"rollout: unknown record type {kind!r} ({kinds[kind]}x)")
    for kind in sorted(set(payloads) - vocabulary.CODEX_ROLLOUT_PAYLOADS):
        out.warn("format", f"rollout: unknown payload type {kind!r} ({payloads[kind]}x)")
    for name in sorted(set(tools) - vocabulary.CODEX_TOOLS):
        out.warn("hook", f"rollout: unknown tool {name!r} ({tools[name]}x): check that its inputs are graded")


# -- Claude Code -----------------------------------------------------------------------------------------------------


def _claude_init(turn: TurnRecord, init: dict[str, Any], skills: tuple[str, ...], out: ContractResult) -> None:
    if not init.get("session_id"):
        out.problem("format", f"turn {turn.index}: init event without a session_id")
    mode = init.get("permissionMode")
    if mode != "default":
        out.problem("approval", f"turn {turn.index}: permissionMode {mode!r}, expected 'default'")
    servers = init.get("mcp_servers") if isinstance(init.get("mcp_servers"), list) else []
    status = next((s.get("status") for s in servers if isinstance(s, dict) and s.get("name") == SERVER_NAME), None)
    if status != "connected":
        out.problem("lifecycle", f"turn {turn.index}: the {SERVER_NAME} server is {status or 'not listed'}, "
                                 "expected connected")
    listed = init.get("skills")
    if not isinstance(listed, list):
        out.warn("format", "init event has no skills field: cannot confirm that the project skills loaded")
    else:
        missing = [s for s in skills if s not in listed]
        if missing:
            out.problem("instructions", f"turn {turn.index}: project skill(s) {', '.join(missing)} not in the init "
                                        "skills list")
    offered = {str(t) for t in init.get("tools") or [] if not str(t).startswith("mcp__")}
    for name in sorted(offered - vocabulary.CLAUDE_TOOLS_OFFERED):
        out.warn("hook", f"new built-in tool offered: {name} (outside the 2.1.328 baseline; does it run commands "
                         "or write files outside the hook matcher?)")
    residual = sorted(offered & vocabulary.UNGUARDED_RESIDUAL)
    if residual:
        out.warn(None, f"owner-accepted residual (OD21-5 = c): {', '.join(residual)} offered outside the hook "
                       f"matcher {'|'.join(HOOK_TOOLS)}")


def _claude_turn(turn: TurnRecord, records: list[dict[str, Any]], out: ContractResult) -> tuple[Counter[str], int]:
    """Vocabulary, tool use and hook coverage of one turn; returns the guarded calls without a hook response and the
    number of guarded calls."""
    uses: Counter[str] = Counter()
    hooks: Counter[str] = Counter()
    for record in records:
        kind = str(record.get("type"))
        subtype = record.get("subtype") if kind in ("system", "result") else None
        if kind != "result" and (kind, subtype) not in vocabulary.CLAUDE_EVENTS:  # result errors: infra.py
            out.warn("format", f"unknown event {kind}{'/' + str(subtype) if subtype else ''}")
        if kind == "system" and subtype == "hook_response" and record.get("hook_event") == "PreToolUse":
            hooks[str(record.get("hook_name", "")).removeprefix("PreToolUse:")] += 1
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        blocks = (message.get("content") or []) if kind in ("assistant", "user") else []
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            if (kind, block.get("type")) not in vocabulary.CLAUDE_BLOCKS:
                out.warn("format", f"unknown {kind} content block {block.get('type')!r}")
            if kind == "assistant" and block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                if name.startswith("mcp__"):
                    continue
                uses[name] += 1
                if name not in vocabulary.CLAUDE_TOOLS_KNOWN:
                    out.warn("hook", f"unknown tool used: {name} (turn {turn.index})")
                if name in vocabulary.UNGUARDED_RESIDUAL:
                    text = json.dumps(block.get("input"), ensure_ascii=False)
                    out.warn(None, f"residual tool called outside the hook (turn {turn.index}): {name} "
                                   f"{_clip(text)}")
    unhooked = Counter({tool: uses[tool] - hooks[tool] for tool in HOOK_TOOLS if uses[tool] > hooks[tool]})
    return unhooked, sum(uses[tool] for tool in HOOK_TOOLS)


def _claude(ev: Evidence, out: ContractResult) -> None:
    skills = project_skills(ev.record.repo_root)
    guarded = 0
    for turn in ev.record.turns:
        records = _records(ev.root / turn.transcript)
        unhooked, calls = _claude_turn(turn, records, out)
        guarded += calls
        if not _ended_by_itself(turn):
            continue
        init = next((r for r in records if r.get("type") == "system" and r.get("subtype") == "init"), None)
        if init is None:
            out.problem("format", f"turn {turn.index}: no system/init event (session id, tools, servers)")
        else:
            _claude_init(turn, init, skills, out)
        result = next((r for r in reversed(records) if r.get("type") == "result"), None)
        if result is None:
            out.problem("format", f"turn {turn.index}: no result event (completion)")
        elif not isinstance(result.get("usage"), dict):
            out.problem("format", f"turn {turn.index}: result carries no usage")
        if HOOK_FLAG in turn.argv:
            for tool, missing in sorted(unhooked.items()):
                out.problem("hook", f"turn {turn.index}: {missing} {tool} call(s) without a PreToolUse "
                                    "hook_response (the guard hook did not run)")
    out.checked.append(f"{len(ev.record.turns)} turn(s), {guarded} guarded call(s)")


def check_contract(ev: Evidence) -> ContractResult:
    """The contract result of one loaded session (see the module docstring)."""
    out = ContractResult(harness=ev.record.harness)
    (_codex if ev.record.harness == "codex" else _claude)(ev, out)
    return out
