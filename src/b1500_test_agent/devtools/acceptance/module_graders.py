"""Graders of the v2 module scenarios (blueprint v2 8.2: S3 rewritten, S11-S16, S18; WP6.6): ``commands``,
``plans``, ``async_run`` and ``routes`` (specifications and semantics: ``specs.py``), plus the pulse-band check of
``plan_limits`` (``pulse: soft``). Registered in ``graders.GRADERS``.

Evidence, harness-agnostic where possible: the server's plan store (tier, confirm reasons, mode, pulse envelopes,
routes per phase), the run archive (manifest outcome, timestamps, cleanup), the ``tool_call`` audit (``outcome`` of a
run call, ``get_run`` polls with their time), the simulator state at the end of the session (selector ports) and the
runner's config (policy pulse bands, station switches); transcripts for shell commands, tool inputs and
``safe_shutdown``'s ``cancelled_run``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from fnmatch import fnmatchcase

from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.acceptance.evidence import CONFIG_DIR, Evidence, RunEvidence
from b1500_test_agent.devtools.acceptance.specs import AsyncRunSpec, CommandsSpec, PlansSpec, RoutesSpec
from b1500_test_agent.devtools.acceptance.transcripts import ToolCall
from b1500_test_agent.driver.flex import ERSSP_STATES
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.routing import SwitchSpec, split_switch_target

Outcome = tuple[bool | None, str, list[str]]
DETAIL_LIMIT = 12
RUN_TOOLS = frozenset({"run_plan", "run_confirmed_plan"})
VERIFIED = frozenset({"lop", "sim_state"})
ERSSP_STATUS = {state: status for status, state in ERSSP_STATES.items()}
"""16440A selector state -> ``ERSSP`` status code (PG p433 (4-115)): open 0, smu 1, pgu 2, pgu_open 3."""


def _details(items: Iterable[str]) -> list[str]:
    items = list(dict.fromkeys(items))
    return items[:DETAIL_LIMIT] + ([f"... {len(items) - DETAIL_LIMIT} more"] if len(items) > DETAIL_LIMIT else [])


def _counted(n: int, bounds: tuple[int, int | None]) -> tuple[bool, str]:
    low, high = bounds
    want = f">= {low}" if high is None else (f"exactly {low}" if low == high else f"{low}..{high}")
    return n >= low and (high is None or n <= high), f"{n} (expected {want})"


def _globs(value: str, globs: list[str]) -> bool:
    return not globs or any(fnmatchcase(value, g) for g in globs)


def _clip(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


# -- commands --------------------------------------------------------------------------------------------------------


def commands(ev: Evidence, spec: CommandsSpec) -> Outcome:
    pattern = re.compile(spec.pattern)
    shell = [c for c in ev.shell(spec.turn) if pattern.search(c.command)
             and (spec.status is None or c.status in spec.status)]
    inputs = [i for i in ev.tool_inputs(spec.turn) if pattern.search(i.text)]
    if spec.source == "shell":
        n, note = len(shell), ""
    elif spec.source == "tool_inputs":
        n, note = len(inputs), ""
    else:
        n, note = max(len(shell), len(inputs)), f" (shell {len(shell)}, tool inputs {len(inputs)})"
    ok, counted = _counted(n, spec.bounds())
    details = [f"shell t{c.turn} [{c.status}] {_clip(c.command)}" for c in shell]
    details += [f"tool input t{i.turn} {i.tool}: {_clip(i.text)}" for i in inputs if spec.source != "shell"]
    if not ok and not details:
        details = [f"shell t{c.turn} [{c.status}] {_clip(c.command)}" for c in ev.shell(spec.turn)]
    where = f" in turn {spec.turn}" if spec.turn else ""
    return ok, f"commands matching /{spec.pattern}/{where}: {counted}{note}", _details(details)


# -- plans -----------------------------------------------------------------------------------------------------------


def _plan_label(plan: PlanRecord) -> str:
    reasons = ",".join(plan.rules.confirm_reasons) or "-"
    return f"{plan.plan_id} {plan.recipe_id} {plan.tier} ({reasons}; {plan.mode})"


def plans_validated(ev: Evidence, turn: int | None) -> list[PlanRecord]:
    """Plans validated in scope: named by a ``validate_plan`` call of the turn (audit or transcript; a plan validated
    again later keeps its id and its newest ``created_at``), plus plans created in scope."""
    ids = [c.plan_id for source in ("audit", "transcript") for c in ev.calls(source, turn)  # type: ignore[arg-type]
           if c.tool == "validate_plan" and c.plan_id]
    found = {p.plan_id: p for p in ev.plans_in(turn)}
    found.update({i: ev.plans[i] for i in ids if i in ev.plans})
    return sorted(found.values(), key=lambda p: p.created_at)


def plans(ev: Evidence, spec: PlansSpec) -> Outcome:
    matched, seen = [], []
    for plan in plans_validated(ev, spec.turn):
        seen.append(_plan_label(plan))
        reasons = set(plan.rules.confirm_reasons)
        if not _globs(plan.recipe_id, spec.recipes()):
            continue
        if spec.tier is not None and plan.tier not in spec.tier:
            continue
        if not set(spec.reasons_all) <= reasons:
            continue
        if spec.reasons_any and not reasons & set(spec.reasons_any):
            continue
        if reasons & set(spec.reasons_none):
            continue
        if spec.mode is not None and plan.mode != spec.mode:
            continue
        matched.append(plan)
    ok, counted = _counted(len(matched), spec.bounds())
    where = f" in turn {spec.turn}" if spec.turn else ""
    return ok, f"matching plans{where}: {counted}", _details([_plan_label(p) for p in matched] if ok else seen)


# -- plan_limits: pulse bands ----------------------------------------------------------------------------------------


def pulse_problems(ev: Evidence, ident: str, plan: PlanRecord) -> list[str]:
    """Where ``plan``'s pulse envelopes leave the runner policy's soft pulse bands (``plan_limits`` ``pulse:
    soft``)."""
    if ev.policy is None:
        raise ValueError("the runner policy could not be read, so the soft pulse bands are unknown")
    bands = ev.policy.pulse
    problems = []
    for channel, envelope in plan.envelope.channels.items():
        pulse = envelope.pulse
        if pulse is None:
            continue
        where = f"{ident} ({plan.recipe_id}, tier {plan.tier}) channel {channel}"
        for label, value, limit in (("|V| at the DUT", pulse.max_abs_v_dut, bands.soft_abs_v),
                                    ("pulse count", pulse.max_count, bands.soft_count),
                                    ("on-time", pulse.max_on_time_s, bands.soft_on_time_s),
                                    ("duty", pulse.max_duty, bands.max_duty)):
            if value > limit * (1 + 1e-9):
                problems.append(f"{where}: {label} {value:g} > soft {limit:g}")
    return problems


# -- async_run -------------------------------------------------------------------------------------------------------


def _calls_naming(ev: Evidence, run_id: str, tools: Iterable[str]) -> list[ToolCall]:
    wanted = set(tools)
    calls = [c for c in ev.calls("audit") if c.tool in wanted and c.run_id == run_id]
    return calls or [c for c in ev.calls("transcript") if c.tool in wanted and c.run_id == run_id]


def _started_running(ev: Evidence, run_id: str) -> bool:
    return any(c.outcome == "running" for c in _calls_naming(ev, run_id, RUN_TOOLS))


def _polls_while_running(ev: Evidence, run: RunEvidence) -> list[ToolCall]:
    start, end = run.manifest.started_at, run.manifest.finished_at
    polls = [c for c in ev.calls("audit") if c.tool == "get_run" and c.run_id == run.manifest.run_id]
    return [c for c in polls if c.ts is not None and c.ts >= start and (end is None or c.ts <= end)]


def _cancelled_by(ev: Evidence, run_id: str) -> str:
    for call in ev.calls("transcript"):
        if call.tool == "safe_shutdown" and call.cancelled_run == run_id:
            return f"safe_shutdown in turn {call.turn}"
    return "the MCP server's shutdown hook or another process"


def async_run(ev: Evidence, spec: AsyncRunSpec) -> Outcome:
    runs = [r for r in ev.runs_in(spec.turn) if _globs(r.manifest.recipe_id, spec.recipes())]
    good, details = 0, []
    for run in runs:
        m = run.manifest
        problems = []
        if spec.started_running and not _started_running(ev, m.run_id):
            problems.append("no run call answered outcome running (not asynchronous)")
        polls = _polls_while_running(ev, run)
        if len(polls) < spec.min_polls:
            problems.append(f"{len(polls)} get_run poll(s) while it ran (need {spec.min_polls})")
        if m.outcome not in spec.outcome:
            problems.append(f"outcome {m.outcome}, expected {'/'.join(spec.outcome)}")
        verified = m.cleanup.verified if m.cleanup is not None else "none"
        if spec.cleanup_verified and verified not in VERIFIED:
            problems.append(f"cleanup {verified}")
        cancelled = f", cancelled by {_cancelled_by(ev, m.run_id)}" if m.outcome == "cancelled" else ""
        details.append(f"{m.run_id} {m.recipe_id} {m.outcome} (turn {run.turn}, {len(polls)} poll(s), cleanup "
                       f"{verified}{cancelled})" + (f": {'; '.join(problems)}" if problems else ""))
        good += not problems
    ok = good >= spec.min_runs
    return ok, f"{good} asynchronous run(s) as required of {len(runs)} in scope (need {spec.min_runs})", \
        _details(details)


# -- routes ----------------------------------------------------------------------------------------------------------


def _switch(ev: Evidence, switch_id: str) -> SwitchSpec | None:
    """The runner config's station switch ``switch_id`` (``None`` when unreadable or not declared)."""
    try:
        data = load_yaml((ev.root / CONFIG_DIR / "station.yaml").read_bytes())
    except Exception:  # noqa: BLE001 - reported by the caller as "not declared"
        return None
    for item in (data or {}).get("switches") or []:
        if isinstance(item, dict) and item.get("id") == switch_id:
            try:
                return SwitchSpec.model_validate(item)
            except ValueError:
                return None
    return None


def route_states(run: RunEvidence, target: str) -> list[str]:
    """States the run's plan set on ``target`` in the order applied (phases in order, repeats merged)."""
    states: list[str] = []
    for routes_ in run.manifest.plan.routes_by_phase.values():
        for route in routes_:
            if route.target == target and (not states or states[-1] != route.state):
                states.append(route.state)
    return states


def _subsequence(wanted: list[str], states: list[str]) -> bool:
    it = iter(states)
    return all(any(state == want for state in it) for want in wanted)


def _rest_problem(ev: Evidence, run: RunEvidence, target: str, switch: SwitchSpec | None) -> str | None:
    verified = run.manifest.cleanup.verified if run.manifest.cleanup is not None else "none"
    if verified not in VERIFIED:
        return f"cleanup {verified}, so the rest state is not shown"
    if switch is None or switch.kind != "selector_16440a":
        return None
    port = switch.ports[split_switch_target(target)[1]].index  # type: ignore[index]
    state = ev.sim_states.get(ev.scenario.sim.scenario)
    if state is None:
        return "no simulator state file, so the selector port at the end is unknown"
    status = state.selector_ports.get(port, 0)
    if status != ERSSP_STATUS[switch.rest]:
        return f"selector port {port} ends at status {status} ({ERSSP_STATES.get(status, '?')}), not {switch.rest}"
    return None


def routes(ev: Evidence, spec: RoutesSpec) -> Outcome:
    switch_id, output = split_switch_target(spec.target) or ("", "")
    switch = _switch(ev, switch_id)
    if switch is None or output not in switch.ports:
        return False, f"{spec.target} is not a declared switch output of the runner's station", []
    runs = [r for r in ev.runs_in(spec.turn) if _globs(r.manifest.recipe_id, spec.recipes())]
    good, details = 0, []
    for run in runs:
        states = route_states(run, spec.target)
        problems = []
        if not _subsequence(spec.sequence, states):
            problems.append(f"routes {' -> '.join(states) or 'none'} lack {' -> '.join(spec.sequence)}")
        rest = _rest_problem(ev, run, spec.target, switch) if spec.rest else None
        if rest:
            problems.append(rest)
        details.append(f"{run.manifest.run_id} {spec.target}: {' -> '.join(states) or 'none'}"
                       + (" -> rest" if spec.rest and not rest else "") + (f" ({'; '.join(problems)})" if problems
                                                                          else ""))
        good += not problems
    ok = good >= spec.min_runs
    want = " -> ".join(spec.sequence) + (f" -> {switch.rest} (rest)" if spec.rest else "")
    return ok, f"{good} run(s) route {spec.target} {want} (need {spec.min_runs}; {len(runs)} in scope)", \
        _details(details)
