"""`b1500 bringup` group (blueprint v2 7.1; CLI only, no MCP tool; agents may run it).

- ``propose-station``: reads ``*IDN?`` and ``UNT?`` read-only and writes ``work/bringup/station.proposed.yaml``
  fitted to the live inventory, plus the diff against ``config/local/station.yaml`` (``bringup.propose_station``).
  Only the human adopts it (``b1500 config adopt FILE --as station``).
- ``status``: every bring-up stage with its records (reviewed in ``validation/hw/``, drafts in
  ``work/bringup/records/``) and the next stage (``bringup.bringup_status``).
- ``capture RUN_ID…|probe``: anonymized golden fixtures of hardware runs or of the newest hardware probe record in
  ``work/bringup/fixtures/`` (``bringup.capture``); simulator runs are refused.
- ``record STAGE --run H…``: a draft validation record in ``work/bringup/records/`` (``bringup.record``); simulator
  runs (``S…``) and a station on backend sim are refused; ``reviewer`` stays empty for the human.
- ``next`` (read-only), ``done STEP [evidence]``, ``check [STAGE|--all]``: the step sequence of
  ``.agents/skills/b1500-bringup/steps.yaml`` against the step ledger ``<data>/state/bringup/ledger-<backend>.jsonl``
  (``bringup_steps``; v2.1 plan §4.1). ``done`` runs ``b1500 doctor`` itself for a doctor step (``doctor_lines``)
  and records who ran it: ``agent`` when a harness marker is in the environment (``human_via_agent`` with the human's
  words), else ``human``.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from b1500_test_agent import bringup, bringup_steps
from b1500_test_agent.adapters.cli import core
from b1500_test_agent.adapters.cli.core import JsonOption, emit
from b1500_test_agent.devtools import doctor
from b1500_test_agent.devtools.update import agent_markers
from b1500_test_agent.models.bringup import StationProposal
from b1500_test_agent.models.validation import (
    BringupStatus,
    CaptureReport,
    LedgerActor,
    LedgerCheck,
    NextStep,
    RecordDraft,
    StepDone,
    StepView,
)

bringup_app = typer.Typer(help="Hardware bring-up helpers (read-only on the instrument; proposals, fixtures and draft "
                               "records go to work/bringup/, the step ledger to data/state/bringup/).",
                          no_args_is_help=True)


def doctor_lines() -> list[tuple[str, str, str]]:
    """``b1500 doctor`` as ``(name, status, detail)`` lines (tests replace this factory)."""
    return [(check.name, check.status, check.detail) for check in doctor.run_doctor().checks]


def actor_of(human: str | None) -> LedgerActor:
    """``agent`` in a harness session (``human_via_agent`` when it records the human's words), else ``human``."""
    if not agent_markers(os.environ):
        return "human"
    return "human_via_agent" if human else "agent"


def proposal_lines(result: StationProposal) -> list[str]:
    """The proposed modules, the notes and the diff against the local station file."""
    lines: list[str] = []
    if result.station is not None:
        lines.append("modules:")
        lines += [f"  slot {m.slot}: {m.model} {m.type} channels {','.join(map(str, m.channels))} alias {m.alias}"
                  for m in result.station.modules]
        unverified = [s.id for s in result.station.switches if s.certainty == "unverified"]
        if unverified:
            lines.append(f"switches unverified (wiring null until recorded at L7): {', '.join(unverified)}")
    lines += [f"note: {note}" for note in result.notes]
    if result.diff:
        lines += ["diff:", *[f"  {line}" for line in result.diff]]
    return lines


@bringup_app.command("propose-station")
def propose_station_command(as_json: JsonOption = False) -> None:
    """Read *IDN? and UNT? (queries only) and write work/bringup/station.proposed.yaml plus the diff against
    config/local/station.yaml. The human reviews and adopts it."""
    result = bringup.propose_station(core.make_service())
    emit(result, as_json, proposal_lines(result))


def status_lines(result: BringupStatus) -> list[str]:
    """One line per stage (state, file) and its records, then the notes."""
    lines = []
    for stage in result.stages:
        marker = "->" if stage.stage == result.next_stage else "  "
        steps = f"steps {stage.steps_done}/{stage.steps_total}" if stage.steps_total is not None else ""
        lines.append(f"{marker} {stage.stage:<4} {stage.state:<13} {steps:<12} {stage.title}")
        lines += [f"        {item.recipe_id or 'stage record'}: {item.state}"
                  + (f" ({item.path})" if item.path else "") for item in stage.records]
    if result.next_step:
        lines.append(f"next step: {result.next_step}" + (f" (ledger {result.ledger})" if result.ledger else ""))
    lines += [f"note: {note}" for note in result.notes]
    return lines


@bringup_app.command("status")
def status_command(as_json: JsonOption = False) -> None:
    """Bring-up stages done and next: the records each stage needs, reviewed (validation/hw/) or drafted
    (work/bringup/records/)."""
    result = bringup.bringup_status(core.make_service())
    emit(result, as_json, status_lines(result))


def capture_lines(result: CaptureReport) -> list[str]:
    lines = [f"  {item.path}  ({item.kind}: {item.command})" + ("" if item.parsed else "  PARSER REJECTED")
             for item in result.written]
    return lines + [f"skipped: {item}" for item in result.skipped]


@bringup_app.command("capture")
def capture_command(
    sources: Annotated[list[str], typer.Argument(help="Hardware run ids (H...) and/or 'probe' (the newest probe "
                                                      "record; or a probe-<UTC>.json name).", show_default=False)],
    as_json: JsonOption = False,
) -> None:
    """Write anonymized golden fixtures (tests/fixtures/flex format, IDN serial -> 0) of hardware runs or a probe
    record to work/bringup/fixtures/. Simulator runs are refused."""
    result = bringup.capture(core.make_service(), sources)
    emit(result, as_json, capture_lines(result))


def record_lines(result: RecordDraft) -> list[str]:
    if result.record is None:
        return []
    lines = [f"  {m.check or '-':<18} {m.quantity:<18} "
             + (f"{m.value:.6g} {m.unit}".strip() if m.value is not None else m.observed)
             + (f"  ref {m.reference:.6g}" if m.reference is not None else "")
             + (f"  [{m.tolerance}]" if m.tolerance else "")
             + {True: "  pass", False: "  FAIL", None: ""}[m.passed]
             + (f"  ({m.run_id})" if m.run_id else "") for m in result.record.measurements]
    return lines + [f"note: {note}" for note in result.notes]


@bringup_app.command("record")
def record_command(
    stage: Annotated[str, typer.Argument(help="Bring-up stage id: S0, L0 .. L10.", show_default=False)],
    run: Annotated[list[str] | None, typer.Option("--run", help="Hardware run id H... (repeatable).")] = None,
    recipe: Annotated[str | None, typer.Option("--recipe", help="Draft the record of this recipe (default: the "
                                                                "runs' recipe when it has checks in the stage, "
                                                                "else the stage record).")] = None,
    probe: Annotated[str | None, typer.Option("--probe", help="Attach a probe record: 'latest' or a "
                                                              "probe-<UTC>.json name (stage L0).")] = None,
    reference: Annotated[list[str] | None, typer.Option("--reference", help="Reference value of a stage check: "
                                                                            "CHECK=VALUE or CHECK@RUN_ID=VALUE "
                                                                            "(repeatable).")] = None,
    operator: Annotated[str, typer.Option("--operator", help="Who ran the stage.")] = "",
    dut_instance: Annotated[str | None, typer.Option("--dut-instance", help="Die, lot or standard label.")] = None,
    note: Annotated[list[str] | None, typer.Option("--note", help="Note for the reviewer (repeatable).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Draft a validation record of STAGE from hardware runs into work/bringup/records/ (reviewer empty). Refuses
    simulator runs (S...) and a station on backend sim."""
    result = bringup.record(core.make_service(), stage, run or [], recipe_id=recipe, probe=probe,
                            references=reference or [], operator=operator, dut_instance=dut_instance,
                            notes=note or [])
    emit(result, as_json, record_lines(result))


def step_lines(step: StepView) -> list[str]:
    """One step: id, who and kind, the expected values, the pass rule, the done line, the abort route."""
    lines = [f"step {step.id} ({step.group}, {step.who}, verify {step.verify}, {step.state})"]
    if step.last_reason:
        lines.append(f"  last FAIL: {step.last_reason}")
    lines += [f"  expected: {row}" for row in step.expected]
    lines += [f"  rule: {step.rule}", f"  done: {step.done}"]
    if step.on_fail:
        lines.append(f"  on failure: skill b1500-debug, runbooks {', '.join(step.on_fail)}")
    if step.state == "failed":
        lines += [f"  abort: {item}" for item in step.abort]
    return lines


def progress_line(progress: dict[str, str]) -> list[str]:
    return [f"steps passed: {', '.join(f'{k} {v}' for k, v in progress.items())}"] if progress else []


def next_lines(result: NextStep) -> list[str]:
    lines = [f"ledger: {result.ledger}"] if result.ledger else []
    if result.step is not None:
        lines += step_lines(result.step)
    if result.reconfirm:
        lines.append(f"confirm again after the break: {', '.join(result.reconfirm)}")
    if result.awaiting_review:
        lines.append(f"awaiting review: {', '.join(result.awaiting_review)}")
    return lines + progress_line(result.progress) + [f"note: {note}" for note in result.notes]


@bringup_app.command("next")
def next_command(as_json: JsonOption = False) -> None:
    """The next bring-up step (read-only): its text, expected values, pass rule, the exact `bringup done` line and,
    after a failure, the abort route; after a break the start steps and the steps to confirm again come first."""
    result = bringup_steps.next_step(core.make_service())
    emit(result, as_json, next_lines(result))


def done_lines(result: StepDone) -> list[str]:
    lines = [f"ledger: {result.ledger}"] if result.ledger else []
    if result.entry is not None:
        entry = result.entry
        lines.append(f"recorded: #{entry.seq} {entry.step} {entry.verdict} ({entry.verify}, {entry.actor})")
        summary = entry.evidence.summary()
        if summary:
            lines.append(f"  evidence: {summary}")
    if result.next is not None:
        lines += ["next:", *[f"  {line}" for line in step_lines(result.next)]]
    return lines + [f"note: {note}" for note in result.notes]


@bringup_app.command("done")
def done_command(
    step: Annotated[str, typer.Argument(help="Step id: D1.., R1.., E1.., <stage>.P<n>, <stage>.A<n>, <stage>.R "
                                              "(`uv run b1500 bringup next` names it).", show_default=False)],
    run: Annotated[list[str] | None, typer.Option("--run", help="Run id of the step (repeatable).")] = None,
    probe: Annotated[str | None, typer.Option("--probe", help="Probe record: 'latest' or a probe-<UTC>.json "
                                                              "name.")] = None,
    draft: Annotated[list[str] | None, typer.Option("--draft", help="A file of the step: proposal, adopted file, "
                                                                    "draft record or JUnit report "
                                                                    "(repeatable).")] = None,
    fixtures: Annotated[list[str] | None, typer.Option("--fixtures", help="Fixture folder written by `bringup "
                                                                          "capture`, one per captured run or probe "
                                                                          "record (repeatable).")] = None,
    observe: Annotated[list[str] | None, typer.Option("--observe", help="What was seen: KEY=VALUE "
                                                                        "(repeatable).")] = None,
    reference: Annotated[list[str] | None, typer.Option("--reference", help="Reference value of a stage check the "
                                                                            "human gave: CHECK=VALUE "
                                                                            "(repeatable).")] = None,
    human: Annotated[str | None, typer.Option("--human", help="The human's own words in chat, quoted.")] = None,
    by: Annotated[str | None, typer.Option("--by", help="The human's name.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Verify bring-up step STEP now and record pass or fail in the step ledger (data/state/bringup/, written only by
    this command); a refused call records nothing."""
    args = bringup_steps.StepArgs(runs=tuple(run or ()), probe=probe, drafts=tuple(draft or ()),
                                  fixtures=tuple(fixtures or ()),
                                  observe=tuple(observe or ()), references=tuple(reference or ()), human=human, by=by)
    result = bringup_steps.done(core.make_service(), step, args, actor=actor_of(human), doctor=doctor_lines)
    emit(result, as_json, done_lines(result))


def check_lines(result: LedgerCheck) -> list[str]:
    lines = [f"ledger: {result.ledger}"] if result.ledger else []
    lines += [f"gap: {gap.step}: {gap.reason}" for gap in result.gaps]
    return lines + progress_line(result.progress) + [f"note: {note}" for note in result.notes]


@bringup_app.command("check")
def check_command(
    stage: Annotated[str | None, typer.Argument(help="Check this stage completely (S0, L0 .. L10).",
                                                show_default=False)] = None,
    all_stages: Annotated[bool, typer.Option("--all", help="Check the deployment and every stage "
                                                           "completely.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Re-verify the step ledger against the current files (hash chain, runs, probe records, drafts, fixtures) and
    list the steps of the scope without a pass; exit 1 on a gap."""
    if stage is not None and all_stages:
        raise typer.BadParameter("give a stage or --all, not both")
    result = bringup_steps.check(core.make_service(), stage, all_stages=all_stages)
    emit(result, as_json, check_lines(result))
