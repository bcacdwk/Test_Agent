"""``b1500 bringup next | done | check`` (v2.1 plan §4.1): the step sequence of
``.agents/skills/b1500-bringup/steps.yaml`` walked against the step ledger.

Imports only ``service``, ``models``, ``bringup_ledger`` (stage-file readers, ``steps.yaml``, the ledger, ``State``)
and ``bringup_verify`` (the verifiers); ``bringup.py`` imports this module for ``status`` and ``record``, never the
reverse. Every verb runs like a tool call (``B1500Admin.call``: configuration reload, error mapping, one
``tool_call`` audit event ``bringup_next``, ``bringup_done`` or ``bringup_check``).

- ``next`` (read-only): the next step (``State.next``) with the stage file's text for a stage step, the expected
  values of the checks it feeds, the pass rule, the exact ``done`` line and the abort route; the steps to confirm again
  after a break and the review steps awaiting the human.
- ``done STEP [STEP ...]``: refused (nothing written) for an unknown step, a step the simulator does not rehearse, a
  step out of order (``State.order_problem``), missing evidence options or missing human words (a human step, or
  ``confirm``); otherwise verified now (``bringup_verify``; on the simulator the step's ``rehearsal`` mode decides the
  kind) and appended as ``pass`` or ``fail`` with the reason; a failure prints the abort route. Several ids are a
  **batch** (``plan_batch``, WP21.14): a first step one ``done`` could record, then the steps ``next`` names one after
  another, within one stage (or the D, R or E steps), each evidence option and ``--observe`` key taken by at most one
  of them, a run step last, a record step first; each option goes to its step, the human's words (one message
  confirmed them) to every step that records them. Every step is verified and appended on its own, in order (one
  entry each, the hash chain unchanged); the first failing step is recorded ``fail`` and ends the call, a step whose
  evidence is missing ends it unrecorded (the steps before it stay). ``next`` (and ``done``'s next step) shows the
  batch that can follow (``batch_after``) with its exact line, and the line that ends the session (``end_line``).
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
from functools import partial
from pathlib import Path
from typing import Any, Literal

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
    GENESIS_SHA256,
    STAGES,
    HumanWords,
    LedgerActor,
    LedgerCheck,
    LedgerEntry,
    LedgerGap,
    NextStep,
    RecordStep,
    StageFrontmatter,
    StepBrief,
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
    "capture": "fixture folders written by `uv run b1500 bringup capture` (work/bringup/fixtures/<run id or probe>), "
               "one per captured run or probe record; runs of {recipes}",
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


HUMAN_WORDS = '--human "<the human\'s own words>" --by <NAME>'
EVIDENCE_OPTIONS: dict[str, frozenset[str]] = {
    "run": frozenset({"run"}), "probe": frozenset({"probe"}), "capture": frozenset({"run", "probe", "fixtures"}),
    "config": frozenset({"draft"}), "proposal": frozenset({"draft"}), "record": frozenset({"draft"}),
    "hw_suite": frozenset({"draft"}), "refusal": frozenset({"run"}),
}
"""Effective kind -> the evidence options (``--run``, ``--probe``, ``--draft``, ``--fixtures``) its verifier reads;
the ``done`` line names the required ones (a config step reads an optional ``--draft``: the file the human adopted,
compared with config/local). A batch gives each option to the one step that reads it."""


def evidence_options(kind: str) -> frozenset[str]:
    """The evidence options the verifier of ``kind`` reads (``EVIDENCE_OPTIONS``)."""
    return EVIDENCE_OPTIONS.get(kind, frozenset())


def takes_words(spec: StepSpec, kind: str) -> bool:
    """``spec`` records the human's own words: a human step, or a step the human's ``confirm`` verifies."""
    return spec.who == "human" or kind == "confirm"


def done_line(spec: StepSpec, kind: str) -> str:
    """The exact ``done`` command of ``spec`` with placeholders."""
    return batch_line([(spec, kind)])


def batch_line(batch: Sequence[tuple[StepSpec, str]]) -> str:
    """The exact ``done`` command recording the steps of ``batch`` (with their effective kinds) in one call: the ids in
    order, each step's evidence options, the human's words once."""
    parts = ["uv run b1500 bringup done", *(spec.id for spec, _kind in batch)]
    for spec, kind in batch:
        parts += done_options(spec, kind)
    if any(takes_words(spec, kind) for spec, kind in batch):
        parts.append(HUMAN_WORDS)
    return " ".join(parts)


def done_options(spec: StepSpec, kind: str) -> list[str]:
    """The evidence options of ``spec``'s ``done`` line with placeholders (the human's words left out)."""
    parts: list[str] = []
    if kind == "run":
        parts += ["--run <RUN_ID>"] * max(1, len(spec.required_recipes))
    elif kind == "probe":
        parts.append("--probe latest")
    elif kind == "capture":
        parts += ([part for _ in range(max(1, len(spec.required_recipes)))
                   for part in ("--run <RUN_ID>", "--fixtures work/bringup/fixtures/<RUN_ID>")] if spec.recipes
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
    return parts


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
         last_reason: str | None = None, batch: Sequence[StepSpec] = ()) -> StepView:
    """The step as ``next`` and ``done`` show it; ``batch``: the steps after it one ``done`` call can record with it
    (``batch_after``)."""
    expected: list[str] = []
    abort: list[str] = []
    body, front, name = "", None, ""
    if spec.group in STAGES:
        path, front, _problem = load_stage(repo_root, spec.group)
        body, name = (path.read_text(encoding="utf-8") if path.is_file() else ""), path.name
        sections = stage_sections(body)
        expected = [" | ".join(c.strip() for c in row.strip().strip("|").split("|")) for row in sections.get(4, [])
                    if row.startswith("|") and any(f"`{check}`" in row for check in spec.feeds)]
        abort = [line[2:].strip() for line in sections.get(5, []) if line.startswith("- ")]
    items = stage_items(body)

    def text_of(step: StepSpec) -> str:
        if step.group not in STAGES:
            return step.text or ""
        item = step.id.split(".", 1)[1]
        if item == "R":
            keys = ", ".join(f"{k or 'stage-' + step.group.lower()}" for k in front.record_keys()) if front else ""
            return REVIEW_TEXT.format(stage=step.group, keys=keys or "see the stage file, part 6")
        return items.get(item, f"(item {item} is not in {name}: uv run b1500 dev lint-skills)")

    together = [(spec, kind), *((step, effective_kind(step, backend) or "") for step in batch)]
    briefs = [StepBrief(id=step.id, who=step.who, verify=step_kind, text=text_of(step))  # type: ignore[arg-type]
              for step, step_kind in together[1:]]
    return StepView(id=spec.id, group=spec.group, who=spec.who, verify=kind, state=state,  # type: ignore[arg-type]
                    text=text_of(spec), expected=expected, rule=rule_text(spec, kind, backend),
                    done=done_line(spec, kind), abort=abort, on_fail=list(spec.on_fail), last_reason=last_reason,
                    batch=briefs, batch_done=batch_line(together) if briefs else "")


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


def end_line(steps: StepsFile, backend: Backend, entries: Sequence[LedgerEntry], now: datetime) -> str:
    """The ``done`` line that ends the session: its first end step and the end steps one call can record with it."""
    first = next((s for s in steps.session_end if effective_kind(s, backend) is not None), None)
    if first is None:
        return ""
    more = batch_after(steps, backend, entries, now, first)
    return batch_line([(s, effective_kind(s, backend) or "") for s in (first, *more)])


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
    ending = end_line(steps, backend, ledger.entries, state.now)
    if spec is None:
        message = f"{_flag(backend)}every required step is recorded" + (
            f"; awaiting review: {', '.join(waiting)}" if waiting else "")
        return NextStep(ok=True, status="ok", backend=backend, simulated=backend == "sim", ledger=shown,
                        message=message, awaiting_review=waiting, progress=state.progress(), notes=notes,
                        next_steps=[f"end the session: E1 first (`{ending}`, the end steps done so far)"]
                        if waiting else [])
    kind = effective_kind(spec, backend)
    assert kind is not None
    last = state.latest.get(spec.id)
    more = batch_after(steps, backend, ledger.entries, state.now, spec) if why != "failed" else []
    shown_step = view(spec, kind, why, repo, backend,
                      last_reason=last.reason if last is not None and last.verdict == "fail" else None, batch=more)
    head = {"failed": "stays on the failed step", "reconfirm": "confirm again after the break", "open": "next step"}
    message = f"{_flag(backend)}{head[why]} {spec.id} ({spec.group}, {spec.who}, verify {kind}): {shown_step.text}"
    next_steps = abort_steps(spec, shown_step.last_reason or "") if why == "failed" else []
    next_steps.append(f"record it: {shown_step.done}")
    if shown_step.batch_done:
        next_steps.append(f"or with the steps after it in one call, once they are done ({len(more) + 1} steps, in "
                          f"order; a call may stop earlier): {shown_step.batch_done}")
    if spec.group not in ("D", "E"):
        next_steps.append(f"to end the session: E1 first (`{ending}`, the end steps done so far), then "
                          "`uv run b1500 bringup next`")
    return NextStep(ok=True, status="ok", backend=backend, simulated=backend == "sim", ledger=shown,
                    message=message[:1000], next_steps=next_steps, step=shown_step, reconfirm=reconfirm,
                    awaiting_review=waiting, progress=state.progress(), notes=notes)


# == batches ==========================================================================================================


def _passed(spec: StepSpec, kind: str, backend: Backend, now: datetime, seq: int) -> LedgerEntry:
    """A passing entry of ``spec`` as ``done`` would append it (the order walk of a batch; never written)."""
    return make_entry(seq, GENESIS_SHA256, step=spec.id, ts=now, backend=backend, actor="agent", verify=kind,
                      verdict="pass")


def named_after(steps: StepsFile, backend: Backend, entries: Sequence[LedgerEntry], now: datetime,
                passed: Sequence[tuple[StepSpec, str]]) -> tuple[StepSpec | None, str]:
    """The step ``next`` names (and why) once the steps of ``passed`` (with their kinds) passed after ``entries``."""
    walked = [*entries, *(_passed(spec, kind, backend, now, len(entries) + index)
                          for index, (spec, kind) in enumerate(passed, 1))]
    return State(steps, backend, walked, now).next()


def conflicts(batch: Sequence[tuple[StepSpec, str]]) -> list[str]:
    """Why the steps of ``batch`` cannot share one ``done`` call (empty: they can): an evidence option
    (``evidence_options``: read by the step's verifier, given or not) or an ``--observe`` key that two of them take;
    a run step that is not the last (its verdict decides whether the stage goes on: recorded before the next step is
    done); a record step that is not the first (its draft embeds the stage's ledger entries: the steps before it are
    recorded before it is drafted)."""
    takers: dict[str, list[str]] = {}
    for spec, kind in batch:
        for option in sorted(evidence_options(kind)):
            takers.setdefault(f"--{option}", []).append(spec.id)
        for key in spec.keys:
            takers.setdefault(f"--observe {key}", []).append(spec.id)
    problems = [f"{', '.join(ids)} each take {option}" for option, ids in takers.items() if len(ids) > 1]
    problems += [f"{spec.id} is a run step: it ends its batch (recorded before the next step is done)"
                 for spec, kind in batch[:-1] if kind == "run"]
    problems += [f"{spec.id} drafts records from the ledger: it starts its batch (the steps before it recorded first)"
                 for spec, kind in batch[1:] if kind == "record"]
    return problems


def batch_after(steps: StepsFile, backend: Backend, entries: Sequence[LedgerEntry], now: datetime,
                first: StepSpec) -> list[StepSpec]:
    """The steps ``next`` names after ``first``, one after another, that one ``done`` call can record together with
    it: of the same stage (or the deployment, start or end group), none failed before, without a ``conflicts``
    problem (an option or key taken twice, a run step before the last, a record step after the first). Empty:
    ``first`` goes alone."""
    chosen: list[tuple[StepSpec, str]] = [(first, effective_kind(first, backend) or "")]
    while True:
        following, why = named_after(steps, backend, entries, now, chosen)
        if (following is None or following.group != first.group or why == "failed"
                or any(following.id == spec.id for spec, _kind in chosen)):
            break
        candidate = [*chosen, (following, effective_kind(following, backend) or "")]
        if conflicts(candidate):
            break
        chosen = candidate
    return [spec for spec, _kind in chosen[1:]]


@dataclass(frozen=True)
class Planned:
    """One step of a ``done`` call: the step, its effective kind, its share of the options and who records it."""

    spec: StepSpec
    kind: str
    args: StepArgs
    actor: LedgerActor


def _route(items: Sequence[str], option: str, ids: Sequence[str],
           takers_of: Callable[[str], list[str]]) -> dict[str, list[str]]:
    """``KEY=VALUE`` items by the one step that takes their key (``Refused``: malformed, or no step or several)."""
    routed: dict[str, list[str]] = {}
    for item in items:
        match = OBSERVE.match(item.strip())
        if match is None:
            raise Refused(f"{option} {item!r} is not KEY=VALUE (key: lower case, digits, _)")
        takers = takers_of(match["key"])
        if len(takers) != 1:
            raise Refused(f"{option} {match['key']}: " + (f"{', '.join(takers)} each take it (record them in "
                                                          "separate calls)" if takers else
                                                          f"no step of {', '.join(ids)} takes it"))
        routed.setdefault(takers[0], []).append(item)
    return routed


def plan_batch(steps: StepsFile, backend: Backend, entries: Sequence[LedgerEntry], now: datetime,
               batch: Sequence[tuple[StepSpec, str]], args: StepArgs, actor: LedgerActor) -> list[Planned]:
    """The steps of a ``done`` call naming several steps, each with its share of ``args`` (``Refused``: the batch
    cannot be one call; nothing is written).

    A batch starts with a step one ``done`` could record now (``State.order_problem``, checked by the caller), then
    takes what ``next`` names one after another (``named_after``: no step before its predecessor), within one stage
    (or the deployment, start or end group), each evidence option and ``--observe`` key taken by at most one of its
    steps, a run step last and a record step first (``conflicts``). Every option given goes to the step that takes
    it (``--run``, ``--probe``, ``--draft``, ``--fixtures`` by the options its verifier reads, ``--observe KEY`` by
    its keys, ``--reference CHECK`` by the checks it feeds; an option no step takes is refused); the human's words go
    to every step that records them (``takes_words``: one message of the human confirmed them), recorded
    ``human_via_agent`` unless the human ran the call (``actor`` ``human``); the agent's steps are ``agent``."""
    ids = [spec.id for spec, _kind in batch]
    groups = list(dict.fromkeys(spec.group for spec, _kind in batch))
    if len(groups) > 1:
        raise Refused(f"a batch stays within one stage (or the D, R or E steps), not {', '.join(groups)}")
    for index, (spec, _kind) in enumerate(batch[1:], 1):
        following, _why = named_after(steps, backend, entries, now, batch[:index])
        if following is None or following.id != spec.id:
            raise Refused(f"a batch takes the steps `uv run b1500 bringup next` names, one after another: after "
                          f"{ids[index - 1]} comes {following.id if following else 'no step'}, not {spec.id}")
    problems = conflicts(batch)
    if problems:
        raise Refused("; ".join(problems) + ": one `done` call for each of them")
    owner: dict[str, str] = {}
    for option, value in (("run", args.runs), ("probe", args.probe), ("draft", args.drafts),
                          ("fixtures", args.fixtures)):
        takers = [spec.id for spec, kind in batch if option in evidence_options(kind)]
        if value and not takers:
            raise Refused(f"--{option} given, but no step of {', '.join(ids)} takes it")
        if value:
            owner[option] = takers[0]
    observe = _route(args.observe, "--observe", ids, lambda key: [s.id for s, _k in batch if key in s.keys])
    references = _route(args.references, "--reference", ids, lambda key: [s.id for s, _k in batch if key in s.feeds])
    words = {spec.id for spec, kind in batch if takes_words(spec, kind)}
    if (args.human is not None or args.by is not None) and not words:
        raise Refused(f"--human/--by given, but no step of {', '.join(ids)} records the human's words")
    planned = []
    for spec, kind in batch:
        mine = spec.id in words
        share = StepArgs(runs=args.runs if owner.get("run") == spec.id else (),
                         probe=args.probe if owner.get("probe") == spec.id else None,
                         drafts=args.drafts if owner.get("draft") == spec.id else (),
                         fixtures=args.fixtures if owner.get("fixtures") == spec.id else (),
                         observe=tuple(observe.get(spec.id, ())), references=tuple(references.get(spec.id, ())),
                         human=args.human if mine else None, by=args.by if mine else None)
        planned.append(Planned(spec, kind, share, actor if actor == "human" else
                               ("human_via_agent" if mine else "agent")))
    return planned


# == done =============================================================================================================


def done(service: B1500Service, step_ids: str | Sequence[str], args: StepArgs, *, actor: LedgerActor = "agent",
         doctor: Callable[[], DoctorLines] | None = None, now: datetime | None = None) -> StepDone:
    """Verify the step (or each step of a batch, in order) now and append ``pass`` or ``fail`` to the ledger (module
    docstring)."""
    ids = [step_ids] if isinstance(step_ids, str) else list(step_ids)
    call: dict[str, Any] = {"step": ids[0] if ids else "", "run_ids": list(args.runs),
                            "run_id": args.runs[0] if args.runs else None, "probe": args.probe,
                            "drafts": list(args.drafts), "actor": actor}
    if len(ids) > 1:
        call["steps"] = ids
    return B1500Admin(service).call("bringup_done", call, StepDone,
                                    lambda bundle: _done(service, bundle, ids, args, actor, doctor, now))


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


def _prepared(item: Planned, front: StageFrontmatter | None) -> tuple[dict[str, str], dict[str, float],
                                                                      HumanWords | None]:
    """What a step's options say before anything is verified: observations, references and the human's words
    (``Refused`` when one is malformed or missing)."""
    spec, kind, args = item.spec, item.kind, item.args
    observe, references = _parse_observe(args, spec, kind, front)
    quote, name = (args.human or "").strip(), (args.by or "").strip()
    if args.human is not None or args.by is not None or takes_words(spec, kind):
        if not quote or not name:
            raise Refused(f"step {spec.id} records the human's own words: --human \"QUOTE\" --by NAME (quote what "
                          "they wrote in chat; never write it for them)")
        return observe, references, HumanWords(quote=quote, by=name)
    return observe, references, None


def _done(service: B1500Service, bundle: Any, ids: list[str], args: StepArgs, actor: LedgerActor,
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
    if not ids:
        return _refused(StepDone, backend, "name the step to record (`uv run b1500 bringup next`)", ledger=shown)
    batch: list[tuple[StepSpec, str]] = []
    for step_id in ids:
        spec = steps.get(step_id)
        if spec is None:
            return _refused(StepDone, backend, f"unknown step {step_id!r} (D1.., R1.., E1.., <stage>.P<n>, "
                                               "<stage>.A<n>, <stage>.R; `uv run b1500 bringup next` names the next "
                                               "one)", ledger=shown)
        kind = effective_kind(spec, backend)
        if kind is None:
            return _refused(StepDone, backend, f"{step_id} is not rehearsed on the simulator (lab only); "
                                               "`uv run b1500 bringup next` skips it", ledger=shown)
        batch.append((spec, kind))
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        return _refused(StepDone, backend, f"{', '.join(twice)} named twice: a batch records each step once",
                        ledger=shown)
    single = len(batch) == 1
    head = ids[0] if single else f"batch {ids[0]}..{ids[-1]}"
    moment = _now(service, now)
    problem = State(steps, backend, ledger.entries, moment).order_problem(batch[0][0])
    if problem is not None:
        return _refused(StepDone, backend, f"{head} not recorded: {problem}", ledger=shown)
    try:
        planned = ([Planned(batch[0][0], batch[0][1], args, actor)] if single
                   else plan_batch(steps, backend, ledger.entries, moment, batch, args, actor))
        prepared = []
        for item in planned:
            front = load_stage(repo, item.spec.group)[1] if item.spec.group in STAGES else None
            prepared.append((item, *_prepared(item, front)))
        if not single and doctor is None and any(item.kind == "doctor" for item in planned):
            raise Refused("a doctor step runs `uv run b1500 doctor`: record it with `uv run b1500 bringup done`")
    except Refused as exc:
        return _refused(StepDone, backend, f"{head} not recorded: {exc}" + ("" if single else " (nothing written)"),
                        ledger=shown)
    try:
        station = bundle.sha256("station")
    except KeyError:
        station = None
    entries: list[LedgerEntry] = []
    stopped: str | None = None
    for index, (item, observe, references, human) in enumerate(prepared):
        spec, kind = item.spec, item.kind
        if index:  # another `done` (a second window) may have written since: the step must still be the next one
            moment = _now(service, now)
            current = read_ledger(path)
            following = None if current.problems else State(steps, backend, current.entries, moment).next()[0]
            if following is None or following.id != spec.id:
                stopped = f"{spec.id} not recorded: the ledger changed during the batch (`uv run b1500 bringup next`)"
                break
        ctx = Ctx(service, bundle, steps, spec, kind, item.args, doctor,
                  gaps=partial(_gaps, service, bundle, moment))
        try:
            verdict, reason = VERIFIERS[kind](ctx)
        except Refused as exc:
            stopped = f"{spec.id} not recorded: {exc}"
            break
        evidence = StepEvidence(runs=ctx.ev.get("runs", []), probe=ctx.ev.get("probe"),
                                drafts=ctx.ev.get("drafts", []), fixtures=ctx.ev.get("fixtures", []),
                                config=ctx.ev.get("config", []), observe=observe, references=references, human=human,
                                facts=ctx.ev.get("facts", []))
        fields = {"step": spec.id, "ts": moment, "backend": backend, "station": station, "actor": item.actor,
                  "verify": kind, "evidence": evidence, "verdict": verdict, "reason": reason[:2000]}
        try:
            entry = append_entry(path, partial(_built, fields))
        except (ValueError, TimeoutError) as exc:
            stopped = f"{spec.id} not recorded: {exc}"
            break
        entries.append(entry)
        if verdict == "fail":
            break
    if not entries:
        return _refused(StepDone, backend, (stopped or f"{head} not recorded")
                        + ("" if single else " (the batch stopped there: nothing recorded)"), ledger=shown)
    return _done_result(steps, repo, backend, ids, [*ledger.entries, *entries], entries, stopped, moment, shown)


def _gaps(service: B1500Service, bundle: Any, moment: datetime) -> list[LedgerGap]:
    """The gaps ``check`` finds now (the ``ledger`` verifier)."""
    return _check(service, bundle, None, all_stages=False, now=moment).gaps


def _built(fields: dict[str, Any], seq: int, prev: str) -> LedgerEntry:
    return make_entry(seq, prev, **fields)


def _done_result(steps: StepsFile, repo: Path, backend: Backend, ids: list[str], ledger: list[LedgerEntry],
                 entries: list[LedgerEntry], stopped: str | None, moment: datetime, shown: str) -> StepDone:
    """The result of a ``done`` call that recorded ``entries`` (the last one failed, or ``stopped`` says why the next
    step was not recorded), with the next step and the batch after it."""
    after = State(steps, backend, ledger, moment)
    following, why = after.next()
    next_view = None
    if following is not None:
        following_kind = effective_kind(following, backend)
        assert following_kind is not None
        more = batch_after(steps, backend, ledger, moment, following) if why != "failed" else []
        next_view = view(following, following_kind, why, repo, backend, batch=more)
    flag, last = _flag(backend), entries[-1]
    recorded = [e.step for e in entries]
    left = ids[len(entries):]
    status: Literal["ok", "error", "refused"] = "ok"
    if last.verdict == "fail":
        status = "error"
        failed = steps.get(last.step)
        assert failed is not None
        message = f"{flag}{last.step} FAIL recorded: {last.reason}"
        if len(ids) > 1:
            message += (f" (the batch stopped at {last.step}: " + (f"{', '.join(recorded[:-1])} passed; " if
                                                                    recorded[:-1] else "")
                        + (f"not recorded: {', '.join(left)}" if left else "nothing after it") + ")")
        next_steps = abort_steps(failed, last.reason)
    elif stopped is not None:
        status = "refused"
        message = f"{flag}{', '.join(recorded)} pass; {stopped}" + (
            f"; not recorded after it: {', '.join(left[1:])}" if left[1:] else "")
        next_steps = ["give what the refusal asks, then record the rest (`uv run b1500 bringup next` names it)"]
    elif len(ids) == 1:
        message = f"{flag}{last.step} pass ({last.reason})"
    else:
        message = f"{flag}{len(entries)} steps pass: " + "; ".join(f"{e.step} ({e.reason[:120]})" for e in entries)
    if status == "ok":
        next_steps = [f"next: {next_view.id}: {next_view.done}"] if next_view else ["every required step recorded"]
        if next_view is not None and next_view.batch_done:
            next_steps.append(f"or with the steps after it in one call, once they are done: {next_view.batch_done}")
    return StepDone(ok=status == "ok", status=status, error_code="invalid_input" if status == "refused" else None,
                    backend=backend, simulated=backend == "sim", message=message[:1000], next_steps=next_steps,
                    ledger=shown, recorded=True, entry=last, entries=entries, next=next_view,
                    notes=[SIM_NOTE] if backend == "sim" and entries[0].seq == 1 else [])


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
