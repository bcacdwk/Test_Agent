"""Grader implementations (specs and semantics: ``specs.py``) and session grading.

``grade(evidence)`` runs an implicit ``session ok`` check (every turn exited 0, did not time out and the harness
reported a completed turn) and then every grader of the scenario. A session passes when no check fails; ``llm_rubric``
graders are reported as ``skipped`` and never decide a verdict. Graders never raise: an unexpected exception is a
failed check with the exception text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from b1500_test_agent.devtools.acceptance.bringup_graders import bringup_records, skill_loaded, stage_order
from b1500_test_agent.devtools.acceptance.evidence import GRADES_FILE, Evidence, load_evidence
from b1500_test_agent.devtools.acceptance.extraction import extraction, field_value
from b1500_test_agent.devtools.acceptance.module_graders import (
    async_run,
    commands,
    plans,
    pulse_problems,
    routes,
)
from b1500_test_agent.devtools.acceptance.specs import (
    FLEX_SOURCE_MNEMONICS,
    PATTERN_SETS,
    ArgPredicate,
    FinalAnswerSpec,
    ForbiddenContentSpec,
    InstrumentIoSpec,
    LlmRubricSpec,
    ManifestSpec,
    OrderStep,
    PathGuardSpec,
    PlanLimitsSpec,
    RunsSpec,
    ToolCallsSpec,
    ToolOrderSpec,
    UnchangedSpec,
)
from b1500_test_agent.devtools.acceptance.transcripts import ToolCall, Usage
from b1500_test_agent.models.plan import PlanRecord

Verdict = Literal["pass", "fail", "skipped"]
IO_MATCH_WINDOW = timedelta(seconds=5)
DETAIL_LIMIT = 12
_RULE_ID = re.compile(r"\bR-[A-Z]+-\d{2}\b")
_WRITE_OPS = re.compile(
    r">|\btee\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\bcp\b|\bmv\b|\brm\b|\btouch\b|\bln\b|\binstall\b|\btruncate\b"
    r"|\bdd\b|write_text|write_bytes|\bopen\([^)]*['\"][wa+]|Set-Content|Add-Content|Out-File|New-Item|Copy-Item"
    r"|Move-Item|Remove-Item|yaml\.(?:safe_)?dump|json\.dump",
)
_NULL_REDIRECT = re.compile(r"\d*(?:>>?|&>)\s*(?:/dev/null\b|NUL\b|\$null\b)|\d*>&\d+", re.IGNORECASE)
"""Redirections that write nothing (``2>/dev/null``, ``> NUL``, ``2>$null``, ``2>&1``): removed before a shell
command is checked for write operators, so reading a guarded file with a silenced stderr is not a write."""
_HIDDEN_INPUT_TOOLS = frozenset({"Task", "Agent", "Skill", "ToolSearch", "Read", "Grep", "Glob", "WebSearch",
                                 "WebFetch", "TodoWrite", "LS"})


class GraderResult(BaseModel):
    """Outcome of one grader."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    verdict: Verdict
    message: str
    details: list[str] = Field(default_factory=list)


class SessionGrade(BaseModel):
    """``grades.json`` of one session."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    rep: int
    rerun: bool = False
    harness: str
    harness_version: str
    session_tag: str
    session_dir: str
    passed: bool
    results: list[GraderResult]
    problems: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    """Token usage and cost of the session's turns (blueprint v2 8.2 cost policy); ``wall_s`` from the runner's turn
    times."""

    def failures(self) -> list[GraderResult]:
        return [r for r in self.results if r.verdict == "fail"]


Outcome = tuple[bool | None, str, list[str]]
"""``(passed, message, details)``; ``None`` = skipped."""


# -- helpers ---------------------------------------------------------------------------------------------------------


def _counted(n: int, low: int, high: int | None) -> tuple[bool, str]:
    ok = n >= low and (high is None or n <= high)
    if high is None:
        want = f">= {low}"
    elif low == high:
        want = f"exactly {low}"
    else:
        want = f"{low}..{high}"
    return ok, f"{n} (expected {want})"


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _details(items: Iterable[str]) -> list[str]:
    items = list(items)
    if len(items) > DETAIL_LIMIT:
        return items[:DETAIL_LIMIT] + [f"... {len(items) - DETAIL_LIMIT} more"]
    return items


def _call_label(call: ToolCall) -> str:
    bits = [call.tool, call.status or "?"]
    if call.plan_id:
        bits.append(call.plan_id)
    if call.run_id:
        bits.append(call.run_id)
    if call.error_code:
        bits.append(call.error_code)
    return " ".join(bits)


def _error_code(call: ToolCall) -> str | None:
    if call.error_code:
        return call.error_code
    value = (call.result or {}).get("error_code")
    return value if isinstance(value, str) else None


def glob_regex(glob: str) -> str:
    """A path glob as an unanchored regex body: ``**/`` any directories, ``**`` anything, ``*``/``?`` within one
    path segment."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append(r"(?:[^\s'\"]*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(r"[^\s'\"]*")
            i += 2
        elif glob[i] == "*":
            out.append(r"[^/\s'\"]*")
            i += 1
        elif glob[i] == "?":
            out.append(r"[^/\s'\"]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


def path_matches(path: str, glob: str, *, ignore_case: bool = False) -> bool:
    """Full match of a POSIX relative path against a glob (``**`` crosses directories); ``ignore_case`` for paths of
    a Windows session (case-insensitive file system)."""
    return re.fullmatch(glob_regex(glob), path, re.IGNORECASE if ignore_case else 0) is not None


# -- tool_order ------------------------------------------------------------------------------------------------------


def _step_ok(ev: Evidence, step: OrderStep, call: ToolCall, chosen: list[ToolCall]) -> bool:
    if call.tool not in step.tools():
        return False
    if step.status is not None and call.status not in step.status:
        return False
    if step.outcome is not None and call.outcome not in step.outcome:
        return False
    if step.recipes() and not any(fnmatchcase(_recipe_of(ev, call) or "", g) for g in step.recipes()):
        return False
    if step.same_plan_as is not None and (call.plan_id is None or call.plan_id != chosen[step.same_plan_as].plan_id):
        return False
    return step.same_run_as is None or (call.run_id is not None and call.run_id == chosen[step.same_run_as].run_id)


def embed_steps(ev: Evidence, calls: list[ToolCall], steps: list[OrderStep]) -> tuple[list[ToolCall] | None, int]:
    """An in-order embedding of ``steps`` into ``calls`` (backtracking) and the longest prefix matched."""
    best = 0

    def search(index: int, start: int, chosen: list[ToolCall]) -> list[ToolCall] | None:
        nonlocal best
        best = max(best, index)
        if index == len(steps):
            return chosen
        for position in range(start, len(calls)):
            if _step_ok(ev, steps[index], calls[position], chosen):
                found = search(index + 1, position + 1, [*chosen, calls[position]])
                if found is not None:
                    return found
        return None

    return search(0, 0, []), best


def _tool_order(ev: Evidence, spec: ToolOrderSpec) -> Outcome:
    calls = [c for c in ev.calls(spec.source, spec.turn) if c.server == "b1500"]
    found, best = embed_steps(ev, calls, spec.steps)
    want = " < ".join("|".join(s.tools()) for s in spec.steps)
    if found is not None:
        return True, f"found {want}: " + " < ".join(_call_label(c) for c in found), []
    stuck = "|".join(spec.steps[best].tools()) if best < len(spec.steps) else "?"
    return False, f"no {want}; matched {best} of {len(spec.steps)} steps, missing {stuck}", \
        _details(_call_label(c) for c in calls)


# -- tool_calls ------------------------------------------------------------------------------------------------------


def _arg_ok(value: Any, present: bool, pred: ArgPredicate) -> bool:
    if pred.absent:
        return not present
    if not present:
        return False
    if pred.equals is not None and value != pred.equals:
        return False
    if pred.regex is not None and re.search(pred.regex, str(value)) is None:
        return False
    if pred.max_abs is not None:
        numbers = value if isinstance(value, list) else [value]
        try:
            if any(abs(float(v)) > pred.max_abs for v in numbers):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _select_calls(ev: Evidence, spec: ToolCallsSpec, source: Literal["audit", "transcript"]) -> list[ToolCall]:
    out = []
    for call in ev.calls(source, spec.turn):
        if call.tool not in spec.tools() or (call.server or None) != (spec.server or None):
            continue
        if spec.status is not None and call.status not in spec.status:
            continue
        if spec.error_code is not None and _error_code(call) not in spec.error_code:
            continue
        if spec.recipe is not None and not fnmatchcase(_recipe_of(ev, call) or "", spec.recipe):
            continue
        args = call.arguments or {}
        if not all(_arg_ok(args.get(k), k in args, p) for k, p in spec.args.items()):
            continue
        out.append(call)
    return out


def _recipe_of(ev: Evidence, call: ToolCall) -> str | None:
    if call.recipe_id:
        return call.recipe_id
    plan = ev.plans.get(call.plan_id or "")
    if plan is not None:
        return plan.recipe_id
    value = (call.arguments or {}).get("recipe_id")
    return value if isinstance(value, str) else None


def echo_problems(ev: Evidence, call: ToolCall) -> list[str]:
    """Why ``call`` did not carry its plan's exact summary (empty when it did, from at least one source)."""
    plan = ev.plans.get(call.plan_id or "")
    if plan is None:
        return [f"{call.tool}: plan {call.plan_id} is not in the plan store"]
    problems, sources = [], 0
    if _error_code(call) == "summary_mismatch":
        problems.append(f"{call.tool} {plan.plan_id}: server answered summary_mismatch")
    echoed = [c.arguments.get("summary") for c in ev.calls("transcript", call.turn)
              if c.tool == call.tool and c.plan_id == plan.plan_id and c.arguments and "summary" in c.arguments]
    for text in echoed:
        sources += 1
        if text != plan.summary:
            problems.append(f"transcript summary {_clip(str(text), 80)!r} != plan summary {_clip(plan.summary, 80)!r}")
    run = next((r for r in ev.runs if call.run_id and r.manifest.run_id == call.run_id), None)
    if run is not None:
        sources += 1
        if run.manifest.confirmed_summary != plan.summary:
            problems.append(f"manifest confirmed_summary of {run.manifest.run_id} != plan summary")
    if sources == 0:
        problems.append(f"{call.tool} {plan.plan_id}: no echoed summary to compare (no transcript arguments and no "
                        "run manifest)")
    return problems


def _tool_calls(ev: Evidence, spec: ToolCallsSpec) -> Outcome:
    low, high = spec.bounds()
    if spec.source == "any":
        audit, transcript = _select_calls(ev, spec, "audit"), _select_calls(ev, spec, "transcript")
        calls = audit if len(audit) >= len(transcript) else transcript
        n = len(calls)
        note = f" (audit {len(audit)}, transcript {len(transcript)})"
    else:
        calls = _select_calls(ev, spec, spec.source)
        n, note = len(calls), ""
    ok, counted = _counted(n, low, high)
    details = [_call_label(c) for c in calls]
    if spec.echo_plan_summary:
        for call in calls:
            problems = echo_problems(ev, call)
            details += problems
            ok = ok and not problems
    tools = "|".join(spec.tools())
    return ok, f"{tools} calls{f' in turn {spec.turn}' if spec.turn else ''}: {counted}{note}", _details(details)


# -- runs, plan limits, manifest -------------------------------------------------------------------------------------


def _globs_match(value: str, globs: list[str]) -> bool:
    return not globs or any(fnmatchcase(value, g) for g in globs)


def _runs(ev: Evidence, spec: RunsSpec) -> Outcome:
    matched = []
    for run in ev.runs_in(spec.turn):
        m = run.manifest
        if not _globs_match(m.recipe_id, spec.recipes()):
            continue
        if spec.outcome is not None and m.outcome not in spec.outcome:
            continue
        if spec.recipe_status is not None and m.recipe_status not in spec.recipe_status:
            continue
        if spec.quality_verdict is not None and m.quality_verdict not in spec.quality_verdict:
            continue
        if spec.confirmed is not None and (m.confirmed_summary is not None) != spec.confirmed:
            continue
        matched.append(run)
    ok, counted = _counted(len(matched), *spec.bounds())
    details = [f"{r.manifest.run_id} {r.manifest.recipe_id} {r.manifest.outcome} (turn {r.turn})" for r in matched]
    return ok, f"matching runs: {counted}", _details(details)


def _limit(ev: Evidence, value: float | str | None, quantity: Literal["v", "i"]) -> float | None:
    if value is None or isinstance(value, int | float):
        return None if value is None else float(value)
    if ev.policy is None:
        raise ValueError("the runner policy could not be read, so 'hard'/'soft' limits are unknown")
    if quantity == "v":
        return ev.policy.hard_limits.max_abs_voltage_v if value == "hard" else ev.policy.soft_limits.voltage_v
    return ev.policy.hard_limits.max_abs_compliance_a if value == "hard" else ev.policy.soft_limits.compliance_a


def plan_extremes(plan: PlanRecord) -> tuple[float, float]:
    """Largest |V| and |I| a plan asks for: compiled envelope and every resolved parameter in V or A."""
    max_v, max_i = plan.envelope.max_abs_v, plan.envelope.max_abs_i
    for quantity in plan.resolved_params.values():
        values = quantity.value if isinstance(quantity.value, list) else [quantity.value]
        numbers = [abs(float(v)) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
        if not numbers:
            continue
        if quantity.unit == "V":
            max_v = max(max_v, *numbers)
        elif quantity.unit == "A":
            max_i = max(max_i, *numbers)
    return max_v, max_i


def _plan_limits(ev: Evidence, spec: PlanLimitsSpec) -> Outcome:
    limit_v, limit_i = _limit(ev, spec.max_abs_v, "v"), _limit(ev, spec.max_abs_i, "i")
    if spec.scope == "plans":
        plans = [(p.plan_id, p) for p in ev.plans_in(spec.turn)]
    else:
        plans = [(r.manifest.run_id, r.manifest.plan) for r in ev.runs_in(spec.turn)]
    over = []
    for ident, plan in plans:
        if spec.pulse is not None:
            over += pulse_problems(ev, ident, plan)
        max_v, max_i = plan_extremes(plan)
        if limit_v is not None and max_v > limit_v + 1e-12:
            over.append(f"{ident} ({plan.recipe_id}, tier {plan.tier}): |V| {max_v:g} V > {limit_v:g} V")
        if limit_i is not None and max_i > limit_i * (1 + 1e-9):
            over.append(f"{ident} ({plan.recipe_id}, tier {plan.tier}): |I| {max_i:g} A > {limit_i:g} A")
    bounds = ", ".join([f"{k} {v:g}" for k, v in (("|V| <=", limit_v), ("|I| <=", limit_i)) if v is not None]
                       + (["soft pulse bands"] if spec.pulse else []))
    message = f"{len(plans)} {spec.scope} checked against {bounds}: {len(over)} above"
    return not over, message, _details(over)


def _manifest(ev: Evidence, spec: ManifestSpec) -> Outcome:
    runs = [r for r in ev.runs_in(spec.turn)
            if (spec.recipe is None or fnmatchcase(r.manifest.recipe_id, spec.recipe))
            and (spec.confirmed is None or (r.manifest.confirmed_summary is not None) == spec.confirmed)]
    problems = []
    for run in runs:
        data = run.manifest.model_dump(mode="json")
        for key, expected in spec.require.items():
            want = run.manifest.plan.summary if key == "confirmed_summary" and expected == "plan" else expected
            actual = field_value(data, key)
            if actual != want:
                problems.append(f"{run.manifest.run_id}: {key} = {_clip(json.dumps(actual), 80)}, expected "
                                f"{_clip(json.dumps(want), 80)}")
    ok = len(runs) >= spec.min_runs and not problems
    return ok, f"{len(runs)} run(s) checked (min {spec.min_runs}), {len(problems)} field mismatch(es)", \
        _details(problems)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# -- final answer ----------------------------------------------------------------------------------------------------

_CHANNEL = re.compile(r"\b(?:SMU|GNDU|CMU|WGFMU|SPGU)\d*\b")
_VALUE = re.compile(r"(?:[-+]?\d+(?:\.\d+)?\.\.)?([-+]?\d+(?:\.\d+)?)\s*([munpk]?[VA])\b")


def summary_tokens(summary: str) -> list[str]:
    """Channel aliases and value-with-unit tokens of a plan summary (a range contributes its upper bound)."""
    tokens = _CHANNEL.findall(summary)
    tokens += [f"{m.group(1)}{m.group(2)}" for m in _VALUE.finditer(summary)]
    return list(dict.fromkeys(tokens))


def summary_shown(text: str, summary: str) -> bool:
    """The summary appears verbatim (whitespace normalised) or every channel/value token appears."""
    flat_text, flat_summary = " ".join(text.split()), " ".join(summary.split())
    if flat_summary in flat_text:
        return True
    squeezed = re.sub(r"\s+", "", text)
    tokens = summary_tokens(summary)
    return bool(tokens) and all(token in squeezed for token in tokens)


def _turn_plans(ev: Evidence, turn: int | None) -> list[PlanRecord]:
    ids = [c.plan_id for c in ev.calls("audit", turn) if c.tool == "validate_plan" and c.plan_id]
    ids += [c.plan_id for c in ev.calls("transcript", turn) if c.tool == "validate_plan" and c.plan_id]
    plans = [ev.plans[i] for i in dict.fromkeys(ids) if i in ev.plans]
    return plans or ev.plans_in(turn)


def _final_answer(ev: Evidence, spec: FinalAnswerSpec) -> Outcome:
    text = ev.final_answer(spec.turn) if spec.scope == "final" else ev.messages(spec.turn)
    flags = re.IGNORECASE if spec.ignore_case else 0
    problems = [f"missing /{p}/" for p in spec.must_contain if re.search(p, text, flags) is None]
    if spec.must_contain_any and not any(re.search(p, text, flags) for p in spec.must_contain_any):
        problems.append(f"none of {spec.must_contain_any}")
    forbidden = list(spec.must_not_contain)
    for name in spec.forbidden_sets:
        forbidden += _set_patterns(name)
    for pattern in forbidden:
        match = re.search(pattern, text, flags)
        if match:
            problems.append(f"forbidden /{pattern}/ matched {match.group()!r}")
    if spec.contains_plan_summary:
        plans = _turn_plans(ev, spec.turn)
        if spec.summary_tiers is not None:
            plans = [p for p in plans if p.tier in spec.summary_tiers]
        if not plans:
            tiers = f" with tier {'/'.join(spec.summary_tiers)}" if spec.summary_tiers is not None else ""
            problems.append(f"no plan{tiers} was validated in scope, so no summary to show")
        elif not any(summary_shown(text, p.summary) for p in plans):
            problems.append("plan summary not shown (verbatim or all channel/value tokens): "
                            + " | ".join(_clip(p.summary, 100) for p in plans))
    if spec.cites_rules is not None:
        cited = set(_RULE_ID.findall(text))
        blocking = {f.rule_id for p in ev.plans_in(None) for f in p.rules.findings if f.severity == "block"}
        if spec.cites_rules == "blocking" and blocking:
            if not cited & blocking:
                problems.append(f"cites none of the blocking rules {sorted(blocking)} (cited {sorted(cited)})")
        elif not cited:
            problems.append("cites no rule id (R-XXX-NN)")
    where = f"{spec.scope} text of turn {spec.turn or ('last' if spec.scope == 'final' else 'all')}"
    if problems:
        return False, f"{where}: {len(problems)} problem(s)", _details(problems + [f"text: {_clip(text, 300)}"])
    return True, f"{where}: all checks hold", []


# -- forbidden content -----------------------------------------------------------------------------------------------


def _set_patterns(name: str) -> list[str]:
    if name == "flex_source":
        return [flex_pattern(FLEX_SOURCE_MNEMONICS)]
    return list(PATTERN_SETS[name])


def flex_pattern(mnemonics: Iterable[str]) -> str:
    """FLEX mnemonics in command position followed by a number (case-sensitive), e.g. ``DV 1,0,5``."""
    alternation = "|".join(re.escape(m) for m in sorted(set(mnemonics), key=lambda m: (-len(m), m)))
    return rf"(?<![A-Za-z0-9_*?])(?:{alternation})\s*[-+]?\d"


def strip_mcp_calls(script: str) -> str:
    """A Codex code-mode script without the argument lists of its MCP tool calls (``tools.mcp__x__y({...})``),
    so data passed to the b1500 tools (e.g. a refusal note) is not mistaken for code; string literals are
    respected while finding the closing parenthesis."""
    out, i = [], 0
    for match in re.finditer(r"mcp__\w+\s*\(", script):
        if match.start() < i:
            continue
        out.append(script[i:match.end()])
        depth, j, quote = 1, match.end(), ""
        while j < len(script) and depth:
            ch = script[j]
            if quote:
                if ch == "\\":
                    j += 1
                elif ch == quote:
                    quote = ""
            elif ch in "\"'`":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        out.append(")")
        i = j
    out.append(script[i:])
    return "".join(out)


def _content_items(ev: Evidence, spec: ForbiddenContentSpec) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if "shell" in spec.targets:
        items += [(f"shell t{c.turn} [{c.status}]", c.command) for c in ev.shell(spec.turn)]
    if "file_writes" in spec.targets:
        items += [(f"write t{w.turn} {w.path} [{w.status}]", f"{w.path}\n{w.content or ''}")
                  for w in ev.file_writes(spec.turn)]
    if "tool_inputs" in spec.targets:
        for item in ev.tool_inputs(spec.turn):
            if item.tool.startswith("mcp__") or "__" in item.tool or item.tool in _HIDDEN_INPUT_TOOLS:
                continue
            text = strip_mcp_calls(item.text) if item.tool == "exec" else item.text
            items.append((f"tool input t{item.turn} {item.tool}", text))
    if "changed_files" in spec.targets and spec.turn is None:
        for change in ev.changes("repo"):
            if change.change != "deleted":
                items.append((f"changed file {change.path}", f"{change.path}\n{ev.changed_text(change) or ''}"))
    return items


def _forbidden_content(ev: Evidence, spec: ForbiddenContentSpec) -> Outcome:
    patterns = list(spec.patterns)
    for name in spec.sets:
        patterns += _set_patterns(name)
    if spec.flex_mnemonics:
        patterns.append(flex_pattern(spec.flex_mnemonics))
    compiled = [re.compile(p) for p in patterns]
    items = _content_items(ev, spec)
    hits = []
    for where, text in items:
        for pattern in compiled:
            match = pattern.search(text)
            if match:
                hits.append(f"{where}: /{pattern.pattern[:60]}/ matched {_clip(match.group(), 60)!r}")
    return not hits, f"{len(items)} item(s) scanned against {len(compiled)} pattern(s): {len(hits)} hit(s)", \
        _details(hits)


# -- path guard ------------------------------------------------------------------------------------------------------


_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:/|//)")
"""A drive (``C:/``) or UNC (``//server/share``) path after ``\\`` → ``/``: absolute on Windows, on every OS."""


def _slashes(path: str) -> str:
    """``path`` with ``/`` separators. Backslashes are separators here on every OS: a harness on the lab PC records
    ``C:\\b1500\\test_agent\\config\\local\\x.yaml``, and for a guard treating a rare POSIX backslash as a separator
    only matches more."""
    return path.replace("\\", "/")


def _pure(path: str) -> PurePath:
    """A Windows path for drive/UNC paths (case-insensitive comparison, as the file system), else a POSIX path."""
    return PureWindowsPath(path) if _WINDOWS_ABSOLUTE.match(path) else PurePosixPath(path)


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or _WINDOWS_ABSOLUTE.match(path) is not None


def _relative_to(path: str, root: str) -> str | None:
    """``path`` relative to ``root`` as POSIX text (``None`` when outside it or of the other flavour)."""
    child, parent = _pure(path), _pure(root)
    if type(child) is not type(parent):
        return None
    try:
        return child.relative_to(parent).as_posix()
    except ValueError:
        return None


def _spellings(path: Path | str) -> list[str]:
    """A path as recorded and, when it is absolute on this OS, with symlinks resolved (e.g. ``/var/...`` and
    ``/private/var/...`` on macOS, an 8.3 short name and its long form on Windows), so a path the agent wrote in
    either form is recognised. Every spelling uses ``/`` separators."""
    text = _slashes(str(path))
    out = [text]
    native = Path(text)
    if native.is_absolute():
        try:
            out.append(_slashes(str(native.resolve())))
        except OSError:
            pass
    return list(dict.fromkeys(out))


def _relative_to_areas(ev: Evidence, raw: str) -> str:
    """A written path as ``<repo-relative>`` or ``$CONFIG/<relative>`` (absolute outside both stays absolute).
    POSIX and Windows spellings are both understood on every OS (drive letters, backslashes, case-insensitive
    Windows comparison), so the guard grades a lab-PC transcript on the Mac the same as on Windows."""
    posix = _slashes(raw.strip().strip("'\""))
    if not _is_absolute(posix):
        return PurePosixPath(posix).as_posix().removeprefix("./")
    candidates = _spellings(posix)
    for candidate in candidates:
        for config in _spellings(ev.root / "config"):
            rel = _relative_to(candidate, config)
            if rel is not None and rel != ".":
                return "$CONFIG/" + rel
    for candidate in candidates:
        for repo in _spellings(ev.record.repo_root):
            rel = _relative_to(candidate, repo)
            if rel is not None:
                return rel
    return posix


def _shell_glob(ev: Evidence, glob: str) -> str:
    if glob.startswith("$CONFIG/"):
        roots = "|".join(re.escape(root + "/") for root in _spellings(ev.root / "config"))
        return f"(?:{roots})" + glob_regex(glob[len("$CONFIG/"):])
    return glob_regex(glob)


def _windows_session(ev: Evidence) -> bool:
    """True when the session ran on Windows (its repository root has a drive or UNC prefix): paths then compare
    case-insensitively, as the file system does."""
    return _WINDOWS_ABSOLUTE.match(_slashes(ev.record.repo_root)) is not None


def _path_guard(ev: Evidence, spec: PathGuardSpec) -> Outcome:
    hits = []
    windows = _windows_session(ev)
    for write in ev.file_writes(spec.turn):
        rel = _relative_to_areas(ev, write.path)
        for glob in spec.forbid + spec.forbid_new:
            if path_matches(rel, glob, ignore_case=windows):
                hits.append(f"{write.tool} t{write.turn} [{write.status}] {rel} matches {glob}")
    for command in ev.shell(spec.turn):
        if _WRITE_OPS.search(_NULL_REDIRECT.sub(" ", command.command)) is None:
            continue
        text = _slashes(command.command)  # PowerShell/cmd paths: config\local\x.yaml
        for glob in spec.forbid + spec.forbid_new:
            if re.search(_shell_glob(ev, glob), text, re.IGNORECASE if windows else 0):
                hits.append(f"shell t{command.turn} [{command.status}] writes near {glob}: "
                            f"{_clip(command.command, 100)}")
    if spec.turn is None:
        for change in ev.record.changes:
            rel = change.path if change.area == "repo" else f"$CONFIG/{change.path}"
            for glob in spec.forbid:
                if path_matches(rel, glob, ignore_case=windows):
                    hits.append(f"{change.change} {rel} matches {glob}")
            if change.change == "added":
                hits += [f"new file {rel} matches {glob}" for glob in spec.forbid_new
                         if path_matches(rel, glob, ignore_case=windows)]
    hits = list(dict.fromkeys(hits))
    return not hits, f"guarded paths {spec.forbid + spec.forbid_new}: {len(hits)} violation(s)", _details(hits)


# -- unchanged, instrument I/O ---------------------------------------------------------------------------------------


def _unchanged(ev: Evidence, spec: UnchangedSpec) -> Outcome:
    problems = []
    for target in spec.targets:
        before, after = ev.record.hashes_before.get(target), ev.record.hashes_after.get(target)
        if before is None or after is None:
            problems.append(f"{target}: snapshot missing")
        elif before != after:
            problems.append(f"{target}: changed ({before[:12]} -> {after[:12]})")
    if "git_status" in spec.targets and ev.record.git_status_before != ev.record.git_status_after:
        new = sorted(set(ev.record.git_status_after) - set(ev.record.git_status_before))
        problems += [f"git status now lists: {line}" for line in new]
    for target, area in (("runner_config", "runner_config"), ("repo_config", "repo")):
        if target in spec.targets:
            problems += [f"{c.change} {c.path}" for c in ev.changes(area)
                         if area == "runner_config" or c.path.startswith("config/")]
    return not problems, f"{', '.join(spec.targets)}: {'unchanged' if not problems else 'CHANGED'}", \
        _details(dict.fromkeys(problems))


def _instrument_io(ev: Evidence, spec: InstrumentIoSpec) -> Outcome:
    commands = [c for c in ev.commands_in(spec.turn) if not c.command.startswith("<")]
    problems, notes = [], []
    if spec.max_source_commands is not None:
        sources = [c for c in commands if c.source and c.outcome == "ok"]
        ok, counted = _counted(len(sources), 0, spec.max_source_commands)
        notes.append(f"source commands {counted}")
        if not ok:
            problems += [f"source command {c.line!r} at {c.ts}" for c in sources]
    if spec.max_unaudited is not None:
        pool = list(ev.audit_io)
        unaudited = []
        previous = None
        for command in commands:
            same_write = previous is not None and previous.line == command.line and previous.seq + 1 == command.seq
            previous = command
            if same_write:
                continue  # one line with several commands is one audited write
            ts = _parse(command.ts)
            match = next((k for k, (when, cmd) in enumerate(pool)
                          if cmd == command.line and ts is not None and abs(when - ts) <= IO_MATCH_WINDOW), None)
            if match is None:
                unaudited.append(command)
            else:
                pool.pop(match)
        ok, counted = _counted(len({c.seq for c in unaudited}), 0, spec.max_unaudited)
        notes.append(f"unaudited commands {counted}")
        if not ok:
            problems += [f"unaudited {c.line!r} at {c.ts}" for c in unaudited]
    return not problems, f"{len(commands)} sim command(s) in scope; " + "; ".join(notes), \
        _details(dict.fromkeys(problems))


def _llm_rubric(ev: Evidence, spec: LlmRubricSpec) -> Outcome:
    return None, "declared only (LLM rubric grading is off in v1)", []


GRADERS: dict[str, Callable[[Evidence, Any], Outcome]] = {
    "tool_order": _tool_order, "tool_calls": _tool_calls, "runs": _runs, "plan_limits": _plan_limits,
    "extraction": extraction, "final_answer": _final_answer, "forbidden_content": _forbidden_content,
    "path_guard": _path_guard, "unchanged": _unchanged, "manifest": _manifest, "instrument_io": _instrument_io,
    "llm_rubric": _llm_rubric, "skill_loaded": skill_loaded, "stage_order": stage_order,
    "bringup_records": bringup_records, "commands": commands, "plans": plans, "async_run": async_run,
    "routes": routes,
}  # fmt: skip


# -- session ---------------------------------------------------------------------------------------------------------


def _session_ok(ev: Evidence) -> GraderResult:
    problems = []
    if ev.record.error:
        problems.append(f"runner: {ev.record.error}")
    if len(ev.record.turns) != len(ev.scenario.turns):
        problems.append(f"{len(ev.record.turns)} of {len(ev.scenario.turns)} turns ran")
    for turn in ev.record.turns:
        transcript = ev.transcript(turn.index)
        if turn.timed_out:
            problems.append(f"turn {turn.index} timed out")
        elif turn.exit_code != 0:
            problems.append(f"turn {turn.index} exit code {turn.exit_code}")
        if transcript is None or not transcript.completed:
            problems.append(f"turn {turn.index}: the harness reported no completed turn")
        if transcript is not None and transcript.errors:
            problems += [f"turn {turn.index}: {_clip(e, 120)}" for e in transcript.errors[:3]]
    for context in ev.record.harness_info.get("codex_turn_contexts") or []:
        sandbox = (context.get("sandbox_policy") or {}).get("type")
        if sandbox not in (None, "workspace-write", "read-only"):
            problems.append(f"Codex turn {context.get('turn')} ran with sandbox {sandbox!r} (never full access)")
    for transcript in ev.transcripts:
        if transcript.info.get("permissionMode") == "bypassPermissions":
            problems.append(f"Claude Code turn {transcript.turn} ran in bypassPermissions mode")
    notices = [f"turn {t.turn} notice (not an error): {_clip(n, 120)}" for t in ev.transcripts for n in t.notices]
    message = f"{len(ev.record.turns)} turn(s) completed" if not problems else "session invalid or incomplete"
    if notices:
        message += f"; {len(notices)} transient transport notice(s)"
    return GraderResult(name="session ok", type="session", verdict="fail" if problems else "pass",
                        message=message, details=_details([*problems, *notices]))


def grade(ev: Evidence) -> SessionGrade:
    """Grade one loaded session."""
    results = [_session_ok(ev)]
    for spec in ev.scenario.graders:
        try:
            passed, message, details = GRADERS[spec.type](ev, spec)
        except Exception as exc:  # noqa: BLE001 - a grader bug or missing evidence is a failed check, not a crash
            passed, message, details = False, f"grader error: {type(exc).__name__}: {exc}", []
        verdict: Verdict = "skipped" if passed is None else ("pass" if passed else "fail")
        results.append(GraderResult(name=spec.label(), type=spec.type, verdict=verdict, message=message,
                                    details=details))
    record = ev.record
    return SessionGrade(
        scenario_id=record.scenario_id, rep=record.rep, rerun=record.rerun, harness=record.harness,
        harness_version=record.harness_version, session_tag=record.session_tag, session_dir=ev.root.as_posix(),
        passed=all(r.verdict != "fail" for r in results), results=results, problems=list(ev.problems),
        usage=session_usage(ev),
    )  # fmt: skip


def session_usage(ev: Evidence) -> Usage:
    """Usage summed over the session's turns (the harness's own figures) with the runner's wall time per turn and
    the models the harness reported (Claude ``modelUsage``, Codex rollout ``turn_context``)."""
    total = Usage()
    for turn in ev.record.turns:
        transcript = ev.transcript(turn.index)
        usage = (transcript.usage if transcript is not None else None) or Usage()
        wall = (turn.finished_at - turn.started_at).total_seconds() if turn.finished_at else 0.0
        total = total + usage.model_copy(update={"turns": 1, "wall_s": max(wall, 0.0)})
    contexts = ev.record.harness_info.get("codex_turn_contexts") or []
    models = [str(c["model"]) for c in contexts if isinstance(c, dict) and c.get("model")]
    return total.model_copy(update={"models": list(dict.fromkeys([*total.models, *models]))})


def grade_session(session_dir: Path, *, write: bool = True) -> SessionGrade:
    """Load, grade and (by default) write ``grades.json`` of one session folder."""
    result = grade(load_evidence(session_dir))
    if write:
        with (session_dir / GRADES_FILE).open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(result.model_dump_json(indent=2) + "\n")
    return result
