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
"""

from __future__ import annotations

from typing import Annotated

import typer

from b1500_test_agent import bringup
from b1500_test_agent.adapters.cli import core
from b1500_test_agent.adapters.cli.core import JsonOption, emit
from b1500_test_agent.models.bringup import StationProposal
from b1500_test_agent.models.validation import BringupStatus, CaptureReport, RecordDraft

bringup_app = typer.Typer(help="Hardware bring-up helpers (read-only; proposals, fixtures and draft records go to "
                               "work/bringup/).", no_args_is_help=True)


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
        lines.append(f"{marker} {stage.stage:<4} {stage.state:<13} {stage.title}")
        lines += [f"        {item.recipe_id or 'stage record'}: {item.state}"
                  + (f" ({item.path})" if item.path else "") for item in stage.records]
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
