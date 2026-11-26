"""``b1500 bringup next | done | check`` (v2.1 plan §4.1): the step sequence of
``.agents/skills/b1500-bringup/steps.yaml`` walked against the step ledger.

Imports only ``service``, ``models``, ``bringup_ledger`` (stage-file readers, ``steps.yaml``, the ledger, ``State``)
and ``bringup_verify`` (the verifiers); ``bringup.py`` imports this module for ``status`` and ``record``, never the
reverse. Every verb runs like a tool call (``B1500Admin.call``: configuration reload, error mapping, one
``tool_call`` audit event ``bringup_next``, ``bringup_done`` or ``bringup_check``).

- ``next`` (read-only): the next step (``State.next``) with the stage file's text for a stage step, the expected
  values of the checks it feeds, the pass rule, the exact ``done`` line and the abort route; the steps to confirm again
  after a break and the review steps awaiting the human.
- ``done STEP``: refused (nothing written) for an unknown step, a step the simulator does not rehearse, a step out of
  order (``State.order_problem``), missing evidence options or missing human words (a human step, or ``confirm``);
  otherwise verified now (``bringup_verify``; on the simulator the step's ``rehearsal`` mode decides the kind) and
  appended as ``pass`` or ``fail`` with the reason; a failure prints the abort route.
- ``check [STAGE|--all]``: the hash chain, every latest passing entry re-verified against the current files, and the
  required steps of the scope without a pass (a stage, ``all`` = deployment and every stage, review steps included;
  by default everything before the next step, which passed by construction). Exit 1 on a gap.

``progress`` and ``record_steps`` serve ``b1500 bringup status`` (steps per stage) and ``b1500 bringup record``
(the ledger entries a draft record embeds, schema version 2).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from b1500_test_agent.bringup_ledger import (
    State,
    append_entry,
    effective_kind,
    ledger_path,
    load_stage,
    load_steps,
    make_entry,
    read_ledger,
    stage_items,
    stage_sections,
)
from b1500_test_agent.bringup_verify import (
    CONFIG_KEYS,
    DEFAULT_OUTCOMES,
    OBSERVE,
    VERIFIERS,
    Ctx,
    DoctorLines,
    Refused,
    StepArgs,
    reverify,
)
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.validation import (
    STAGES,
    HumanWords,
    LedgerActor,
    LedgerCheck,
    LedgerEntry,
    LedgerGap,
    NextStep,
    RecordStep,
    StageFrontmatter,
    StepDone,
    StepEvidence,
    StepsFile,
    StepSpec,
    StepView,
)
from b1500_test_agent.service import B1500Admin, B1500Service

# == views ============================================================================================================

RULES: dict[str, str] = {
    "run": "archived runs of {recipes} on this backend ({ids}): outcome {outcomes}, cleanup verified{lop}, files "
           "unchanged since the run, quality not untrusted",
    "probe": "the newest probe record (`uv run b1500 doctor --probe`) of this backend without a FAIL line",
    "config": "the human adopted {config}: `uv run b1500 config check` valid, the files in config/local equal to the "
              "file adopted",
    "proposal": "schema-valid {config} proposal file(s) under work/bringup/",
    "record": "draft records of this stage in work/bringup/records/ (`uv run b1500 bringup record`), result not fail",
    "capture": "fixture files written by `uv run b1500 bringup capture` in work/bringup/fixtures/<run id or probe>",
    "observation": "what was seen, as --observe KEY=VALUE",
    "hw_suite": "the JUnit file of `pytest -m hardware`: no failure or error, nothing skipped by the gate",
    "confirm": "the human's own words in chat, quoted, and their name",
    "review": "every record of the stage reviewed (reviewer, reviewed_on, result pass) in validation/hw/",
    "station": "station_status clean: no fault latched, no lock holder, no running run",
    "doctor": "`uv run b1500 doctor` without FAIL{must}",
    "ledger": "`uv run b1500 bringup check` without a gap",
    "refusal": "SIMULATED rehearsal: on hardware this step drafts records or captures fixtures; the simulator refuses "
               "both by design (say which the stage would draft; never write one by hand)",
}
REVIEW_TEXT = ("The human reviews the draft records of stage {stage} in work/bringup/records/ against the raw runs, "
               "fills reviewer and reviewed_on and moves each to the name in its header under validation/hw/ "
               "({keys}); fixtures go to tests/fixtures/hw/. The agent never does it.")


def done_line(spec: StepSpec, kind: str) -> str:
    """The exact ``done`` command of ``spec`` with placeholders."""
    parts = [f"uv run b1500 bringup done {spec.id}"]
    if kind == "run":
        parts += ["--run <RUN_ID>"] * max(1, len(spec.required_recipes))
    elif kind == "probe":
        parts.append("--probe latest")
    elif kind == "capture":
        parts += (["--run <RUN_ID>", "--fixtures work/bringup/fixtures/<RUN_ID>"] if spec.recipes
                  else ["--probe latest", "--fixtures work/bringup/fixtures/<PROBE_NAME>"])
    elif kind == "config":
        parts += ["--draft <ADOPTED_FILE>" for item in spec.config if item in CONFIG_KEYS]
    elif kind == "proposal":
        parts += ["--draft work/bringup/<PROPOSAL>.yaml"] * len(spec.config)
    elif kind == "record":
        parts.append("--draft work/bringup/records/<DRAFT>.yaml")
    elif kind == "hw_suite":
        parts.append("--draft work/bringup/hw-<UTC>.xml")
    parts += [f"--observe {key}=<VALUE>" for key in (spec.keys if kind == spec.verify else [])]
    if spec.who == "human" or kind == "confirm":
        parts.append('--human "<the human\'s own words>" --by <NAME>')
    return " ".join(parts)


def rule_text(spec: StepSpec, kind: str, backend: Backend) -> str:
    text = RULES[kind].format(
        recipes=", ".join(spec.recipes) + (f" (optional: {', '.join(spec.optional)})" if spec.optional else ""),
        ids="H... hardware runs" if backend == "visa" else "S... simulator runs",
        outcomes=" or ".join(spec.outcomes or DEFAULT_OUTCOMES),
        lop=" with LOP? (and a passing positive control)" if backend == "visa" else "",
        config=", ".join(spec.config), must=f"; {', '.join(spec.must_pass)} PASS" if spec.must_pass else "")
    if spec.keys and kind not in ("observation", "confirm", "refusal"):
        text += f"; plus --observe {', '.join(spec.keys)}"
    if spec.who == "human" and kind != "confirm":
        text += "; plus the human's own words and name"
    return text


def view(spec: StepSpec, kind: str, state: str, repo_root: Path, backend: Backend, *,
         last_reason: str | None = None) -> StepView:
    """The step as ``next`` and ``done`` show it."""
    text = spec.text or ""
    expected: list[str] = []
    abort: list[str] = []
    if spec.group in STAGES:
        path, front, _problem = load_stage(repo_root, spec.group)
        body = path.read_text(encoding="utf-8") if path.is_file() else ""
        item = spec.id.split(".", 1)[1]
        if item == "R":
            keys = ", ".join(f"{k or 'stage-' + spec.group.lower()}" for k in front.record_keys()) if front else ""
            text = REVIEW_TEXT.format(stage=spec.group, keys=keys or "see the stage file, part 6")
        else:
            text = stage_items(body).get(item, f"(item {item} is not in {path.name}: uv run b1500 dev lint-skills)")
        sections = stage_sections(body)
        expected = [" | ".join(c.strip() for c in row.strip().strip("|").split("|")) for row in sections.get(4, [])
                    if row.startswith("|") and any(f"`{check}`" in row for check in spec.feeds)]
        abort = [line[2:].strip() for line in sections.get(5, []) if line.startswith("- ")]
    return StepView(id=spec.id, group=spec.group, who=spec.who, verify=kind, state=state, text=text,  # type: ignore[arg-type]
                    expected=expected, rule=rule_text(spec, kind, backend), done=done_line(spec, kind), abort=abort,
                    on_fail=list(spec.on_fail), last_reason=last_reason)


def abort_steps(spec: StepSpec, reason: str) -> list[str]:
    runbooks = f" (runbooks {', '.join(spec.on_fail)})" if spec.on_fail else ""
    return [(f"stop: safe_shutdown(\"{spec.id} failed: {reason[:120]}\"), report what you saw and which criterion "
            "it hit"),
            f"load skill b1500-debug{runbooks}; never relax a criterion, tolerance or limit",
            "wait for the human; a latched fault is cleared only by the human (`uv run b1500 fault clear --by NAME`)",
            f"then record {spec.id} again with `uv run b1500 bringup done {spec.id} ...` (`uv run b1500 bringup next`)"]


def _now(service: B1500Service, now: datetime | None) -> datetime:
    return (now or service.executor.now()).astimezone(UTC)


def _flag(backend: Backend) -> str:
    return "SIMULATED " if backend == "sim" else ""


def _shown(bundle: Any, path: Path) -> str:
    return bundle.paths.display(path)


def _refused(result_type: Any, backend: Backend, message: str, steps: Sequence[str] = (), **extra: Any) -> Any:
    return result_type(ok=False, status="refused", error_code="invalid_input", backend=backend,
                       simulated=backend == "sim", message=message, next_steps=list(steps), **extra)


SIM_NOTE = ("SIMULATED rehearsal ledger: it never signs a hardware stage; on the lab PC the human creates config/local "
            "with backend visa at D7 (`uv run b1500 config init --visa`), so the hardware ledger holds every step")


# == next =============================================================================================================


def next_step(service: B1500Service, *, now: datetime | None = None) -> NextStep:
    """The next step to do (read-only; module docstring)."""
    return B1500Admin(service).call("bringup_next", {}, NextStep, lambda bundle: _next(service, bundle, now))


def _next(service: B1500Service, bundle: Any, now: datetime | None) -> NextStep:
    backend: Backend = bundle.backend
    repo = Path(bundle.paths.repo_root)
    try:
        steps = load_steps(repo)
    except ValueError as exc:
        return _refused(NextStep, backend, f"no step sequence: {exc}")
    path = ledger_path(bundle)
    ledger = read_ledger(path)
    state = State(steps, backend, ledger.entries, _now(service, now))
    notes = [SIM_NOTE] if backend == "sim" else []
    shown = _shown(bundle, path)
    if ledger.problems:
        return NextStep(ok=False, status="error", backend=backend, simulated=backend == "sim", ledger=shown,
                        message=f"{_flag(backend)}the step ledger {shown} is damaged: {ledger.problems[0]}",
                        next_steps=[("`uv run b1500 bringup check` shows where; only the human decides what to do "
                                    "with the file (nothing is recorded until then)")],
                        progress=state.progress(), notes=notes)
    spec, why = state.next()
    reconfirm = [s.id for s in state.reconfirm(state.position())]
    waiting = state.awaiting_review()
    if state.entries and state.session_start == len(state.entries) and not state.open_deployment():
        notes.append("a new session: the start steps first, then the steps to confirm again")
    if spec is None:
        message = f"{_flag(backend)}every required step is recorded" + (
            f"; awaiting review: {', '.join(waiting)}" if waiting else "")
        return NextStep(ok=True, status="ok", backend=backend, simulated=backend == "sim", ledger=shown,
                        message=message, awaiting_review=waiting, progress=state.progress(), notes=notes,
                        next_steps=["end the session with E1 (`uv run b1500 bringup done E1`)"] if waiting else [])
    kind = effective_kind(spec, backend)
    assert kind is not None
    last = state.latest.get(spec.id)
    shown_step = view(spec, kind, why, repo, backend,
                      last_reason=last.reason if last is not None and last.verdict == "fail" else None)
    head = {"failed": "stays on the failed step", "reconfirm": "confirm again after the break", "open": "next step"}
    message = f"{_flag(backend)}{head[why]} {spec.id} ({spec.group}, {spec.who}, verify {kind}): {shown_step.text}"
    next_steps = abort_steps(spec, shown_step.last_reason or "") if why == "failed" else []
    next_steps.append(f"record it: {shown_step.done}")
    if spec.group not in ("D", "E"):
        next_steps.append("to end the session: E1 (`uv run b1500 bringup done E1`), then `uv run b1500 bringup next`")
    return NextStep(ok=True, status="ok", backend=backend, simulated=backend == "sim", ledger=shown,
                    message=message[:1000], next_steps=next_steps, step=shown_step, reconfirm=reconfirm,
                    awaiting_review=waiting, progress=state.progress(), notes=notes)


# == done =============================================================================================================


def done(service: B1500Service, step_id: str, args: StepArgs, *, actor: LedgerActor = "agent",
         doctor: Callable[[], DoctorLines] | None = None, now: datetime | None = None) -> StepDone:
    """Verify ``step_id`` now and append ``pass`` or ``fail`` to the ledger (module docstring)."""
    call = {"step": step_id, "run_ids": list(args.runs), "run_id": args.runs[0] if args.runs else None,
            "probe": args.probe, "drafts": list(args.drafts), "actor": actor}
    return B1500Admin(service).call("bringup_done", call, StepDone,
                                    lambda bundle: _done(service, bundle, step_id, args, actor, doctor, now))


def _parse_observe(args: StepArgs, spec: StepSpec, kind: str, front: StageFrontmatter | None
                   ) -> tuple[dict[str, str], dict[str, float]]:
    """``--observe`` and ``--reference`` values; the step's keys are required when it is verified its own way (not in
    a ``human_done`` or ``refusal`` rehearsal)."""
    observe: dict[str, str] = {}
    for item in args.observe:
        match = OBSERVE.match(item.strip())
        if match is None:
            raise Refused(f"--observe {item!r} is not KEY=VALUE (key: lower case, digits, _)")
        observe[match["key"]] = match["value"].strip()
    references: dict[str, float] = {}
    checks = {c.id for c in front.checks} if front is not None else set()
    for item in args.references:
        match = OBSERVE.match(item.strip())
        if match is None or match["key"] not in checks:
            raise Refused(f"--reference {item!r}: CHECK=VALUE with a check of stage {spec.group}"
                          + (f" ({', '.join(sorted(checks))})" if checks else " (this step has no stage)"))
        try:
            references[match["key"]] = float(match["value"])
        except ValueError:
            raise Refused(f"--reference {item!r}: {match['value']!r} is not a number") from None
    missing = [key for key in (spec.keys if kind == spec.verify else []) if not observe.get(key)]
    if missing:
        raise Refused(f"step {spec.id} needs --observe {' '.join(f'{k}=<VALUE>' for k in missing)}")
    return observe, references


def _done(service: B1500Service, bundle: Any, step_id: str, args: StepArgs, actor: LedgerActor,
          doctor: Callable[[], DoctorLines] | None, now: datetime | None) -> StepDone:
    backend: Backend = bundle.backend
    repo = Path(bundle.paths.repo_root)
    try:
        steps = load_steps(repo)
    except ValueError as exc:
        return _refused(StepDone, backend, f"no step sequence: {exc}")
    path = ledger_path(bundle)
    shown = _shown(bundle, path)
    ledger = read_ledger(path)
    if ledger.problems:
        return _refused(StepDone, backend, f"the step ledger {shown} is damaged: {ledger.problems[0]}; nothing "
                                           "recorded", ["`uv run b1500 bringup check`; the human decides"],
                        ledger=shown)
    spec = steps.get(step_id)
    if spec is None:
        return _refused(StepDone, backend, f"unknown step {step_id!r} (D1.., R1.., E1.., <stage>.P<n>, <stage>.A<n>, "
                                           "<stage>.R; `uv run b1500 bringup next` names the next one)", ledger=shown)
    kind = effective_kind(spec, backend)
    if kind is None:
        return _refused(StepDone, backend, f"{step_id} is not rehearsed on the simulator (lab only); "
                                           "`uv run b1500 bringup next` skips it", ledger=shown)
    moment = _now(service, now)
    state = State(steps, backend, ledger.entries, moment)
    problem = state.order_problem(spec)
    if problem is not None:
        return _refused(StepDone, backend, f"{step_id} not recorded: {problem}", ledger=shown)
    front = load_stage(repo, spec.group)[1] if spec.group in STAGES else None
    ctx = Ctx(service, bundle, steps, spec, kind, args, doctor,
              gaps=lambda: _check(service, bundle, None, all_stages=False, now=moment).gaps)
    try:
        observe, references = _parse_observe(args, spec, kind, front)
        human = None
        quote, name = (args.human or "").strip(), (args.by or "").strip()
        if args.human is not None or args.by is not None or spec.who == "human" or kind == "confirm":
            if not quote or not name:
                raise Refused(f"step {step_id} records the human's own words: --human \"QUOTE\" --by NAME (quote "
                              "what they wrote in chat; never write it for them)")
            human = HumanWords(quote=quote, by=name)
        verdict, reason = VERIFIERS[kind](ctx)
    except Refused as exc:
        return _refused(StepDone, backend, f"{step_id} not recorded: {exc}", ledger=shown)
    evidence = StepEvidence(runs=ctx.ev.get("runs", []), probe=ctx.ev.get("probe"), drafts=ctx.ev.get("drafts", []),
                            fixtures=ctx.ev.get("fixtures"), config=ctx.ev.get("config", []), observe=observe,
                            references=references, human=human, facts=ctx.ev.get("facts", []))
    try:
        station = bundle.sha256("station")
    except KeyError:
        station = None
    try:
        entry = append_entry(path, lambda seq, prev: make_entry(
            seq, prev, step=spec.id, ts=moment, backend=backend, station=station, actor=actor, verify=kind,
            evidence=evidence, verdict=verdict, reason=reason[:2000]))
    except (ValueError, TimeoutError) as exc:
        return _refused(StepDone, backend, f"{step_id} not recorded: {exc}", ledger=shown)
    after = State(steps, backend, [*ledger.entries, entry], moment)
    following, why = after.next()
    next_view = None
    if following is not None:
        following_kind = effective_kind(following, backend)
        assert following_kind is not None
        next_view = view(following, following_kind, why, repo, backend)
    flag = _flag(backend)
    if verdict == "pass":
        message = f"{flag}{step_id} pass ({reason})"
        next_steps = [f"next: {next_view.id}: {next_view.done}"] if next_view else ["every required step recorded"]
    else:
        message = f"{flag}{step_id} FAIL recorded: {reason}"
        next_steps = abort_steps(spec, reason)
    return StepDone(ok=verdict == "pass", status="ok" if verdict == "pass" else "error", backend=backend,
                    simulated=backend == "sim", message=message[:1000], next_steps=next_steps, ledger=shown,
                    recorded=True, entry=entry, next=next_view,
                    notes=[SIM_NOTE] if backend == "sim" and entry.seq == 1 else [])


# == check ============================================================================================================


def check(service: B1500Service, stage: str | None = None, *, all_stages: bool = False,
          now: datetime | None = None) -> LedgerCheck:
    """Re-verify the ledger (module docstring); ``ok`` iff no gap."""
    return B1500Admin(service).call("bringup_check", {"stage": stage, "all": all_stages}, LedgerCheck,
                                    lambda bundle: _check(service, bundle, stage, all_stages=all_stages, now=now))


def _check(service: B1500Service, bundle: Any, stage: str | None, *, all_stages: bool,
           now: datetime | None = None) -> LedgerCheck:
    backend: Backend = bundle.backend
    repo = Path(bundle.paths.repo_root)
    try:
        steps = load_steps(repo)
    except ValueError as exc:
        return _refused(LedgerCheck, backend, f"no step sequence: {exc}")
    if stage is not None and stage not in steps.stages:
        return _refused(LedgerCheck, backend, f"unknown stage {stage!r}: {', '.join(steps.stages)}")
    path = ledger_path(bundle)
    ledger = read_ledger(path)
    state = State(steps, backend, ledger.entries, _now(service, now))
    gaps = [LedgerGap(step="-", reason=f"hash chain: {p}") for p in ledger.problems]
    notes: list[str] = []
    verified = 0
    for step_id, entry in state.latest.items():
        spec = steps.get(step_id)
        if spec is None:
            notes.append(f"{step_id}: no longer a step of steps.yaml (entry kept)")
            continue
        if entry.verdict != "pass":
            continue
        problems, moved = reverify(Ctx(service, bundle, steps, spec, entry.verify, StepArgs()), entry)
        gaps += [LedgerGap(step=step_id, reason=p) for p in problems]
        notes += [f"{step_id}: {n}" for n in moved]
        verified += 1
    position = state.position()
    if stage is not None:
        scope, required = stage, [s for s in steps.stages[stage] if state.required(s)]
    elif all_stages:
        scope = "all"
        required = [s for s in [*steps.deployment, *(s for v in steps.stages.values() for s in v)]
                    if state.required(s)]
    else:  # everything before the next step passed by construction: the entries are re-verified above
        scope, required = "recorded", []
    for spec in required:
        entry = state.latest.get(spec.id)
        if entry is None:
            gaps.append(LedgerGap(step=spec.id, reason="no entry"))
        elif entry.verdict != "pass":
            gaps.append(LedgerGap(step=spec.id, reason=f"last entry failed: {entry.reason[:200]}"))
    if position is not None and scope == "recorded":
        order = list(steps.stages)
        ahead = [s.id for name, specs in steps.stages.items() for s in specs
                 if s.id in state.latest and not s.is_review and s.id != position.id
                 and (order.index(name), specs.index(s)) > (order.index(position.group),
                                                            steps.stages[position.group].index(position))]
        if ahead:
            notes.append(f"recorded ahead of {position.id}: {', '.join(ahead[:8])}")
    shown = _shown(bundle, path)
    flag = _flag(backend)
    message = (f"{flag}ledger {shown}: {len(ledger.entries)} entries, {verified} re-verified, "
               + (f"{len(gaps)} gap(s)" if gaps else "no gap") + f" (scope {scope})")
    return LedgerCheck(ok=not gaps, status="ok" if not gaps else "error", backend=backend,
                       simulated=backend == "sim", message=message, ledger=shown, scope=scope,
                       entries=len(ledger.entries), verified=verified, gaps=gaps, progress=state.progress(),
                       notes=notes + ([SIM_NOTE] if backend == "sim" else []),
                       next_steps=[] if not gaps else [("record the missing steps (`uv run b1500 bringup next`); an "
                                                       "entry that no longer verifies is recorded again")])


# == status and records ===============================================================================================


@dataclass
class Progress:
    """The ledger as ``b1500 bringup status`` and ``record`` read it (no re-verification: ``check`` does that)."""

    steps: StepsFile | None
    ledger: str | None
    passed: set[str]
    required: dict[str, list[StepSpec]]
    next_step: str | None
    problems: list[str]
    entries: dict[str, LedgerEntry]


def progress(service: B1500Service, bundle: Any, *, now: datetime | None = None) -> Progress:
    try:
        steps = load_steps(Path(bundle.paths.repo_root))
    except ValueError as exc:
        return Progress(None, None, set(), {}, None, [str(exc)], {})
    path = ledger_path(bundle)
    ledger = read_ledger(path)
    state = State(steps, bundle.backend, ledger.entries, _now(service, now))
    required = {stage: [s for s in specs if state.required(s)] for stage, specs in steps.stages.items()}
    passed = {step for step, e in state.latest.items() if e.verdict == "pass"}
    following, _why = state.next()
    return Progress(steps, _shown(bundle, path) if path.is_file() else None, passed, required,
                    following.id if following else None,
                    [f"step ledger damaged: {p} (`uv run b1500 bringup check`)" for p in ledger.problems],
                    dict(state.latest))


def record_steps(service: B1500Service, bundle: Any, stage: str) -> tuple[list[RecordStep], list[str]]:
    """The ledger entries of ``stage`` a draft record embeds (latest per step, in sequence order) and the required
    steps of the stage that do not pass yet (``StepSpec.after_drafting`` left out: they come with or after the
    draft)."""
    found = progress(service, bundle)
    if found.steps is None or stage not in found.steps.stages:
        return [], [f"no steps of stage {stage}: {'; '.join(found.problems) or 'not in steps.yaml'}"]
    out = [RecordStep(step=e.step, verify=e.verify, verdict=e.verdict, ts=e.ts, actor=e.actor,
                      evidence=e.evidence.summary()[:500], entry_sha256=e.sha256)
           for s in found.steps.stages[stage] if (e := found.entries.get(s.id)) is not None]
    missing = [s.id for s in found.required[stage] if not s.after_drafting and s.id not in found.passed]
    return out, missing + [f"ledger: {p}" for p in found.problems]
