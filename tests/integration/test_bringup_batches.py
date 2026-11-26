"""Batches of ``b1500 bringup done`` on the simulator (WP21.14): several steps in one call, every check as strict as
one step per call.

A batch is the steps ``next`` names one after another from the next step, within one stage (or the D, R or E
steps), each evidence option (``--run``, ``--probe``, ``--draft``, ``--fixtures``) and ``--observe`` key taken by at
most one of its steps. Covered: ``next`` shows the batch that can follow and its exact line (none after a failure,
cut where an option would be taken twice); a batch appends one entry per step in order on the hash chain, routes each
option to its step and the human's words to every step that records them (``human_via_agent``; the agent's steps
``agent``), and its audit event names the steps; the refusals that write nothing (not the next step, a skipped
predecessor, two groups, a step named twice, an option no step takes or two steps take, missing human words, no
doctor); the first failing step is recorded ``fail`` and ends the call, a step without its evidence ends it
unrecorded; ``check`` re-verifies batch entries like any other.
"""

from __future__ import annotations

import itertools
import shutil
from datetime import UTC, datetime
from typing import Any

import pytest

from b1500_test_agent import bringup, bringup_steps
from b1500_test_agent.bringup_ledger import State, effective_kind, load_steps, make_entry, read_ledger
from b1500_test_agent.bringup_steps import batch_line, conflicts, evidence_options, plan_batch
from b1500_test_agent.bringup_verify import Refused, StepArgs
from b1500_test_agent.models.validation import GENESIS_SHA256, STAGE_FILES_DIR, STEPS_FILE, StepDone, StepSpec
from b1500_test_agent.service import B1500Admin, B1500Service
from tests.integration.helpers import REPO_ROOT, World

STEPS = load_steps(REPO_ROOT)
DOCTOR_OK = [("python", "PASS", "3.12"), ("harness files", "PASS", "wired"),
             ("harness versions", "PASS", "= validated")]
WORDS = {"human": "done, all of them", "by": "Owner"}
DEPLOYMENT = ["D1", "D4", "D6", "D7", "D8", "D9", "D11"]
"""The deployment steps the simulator rehearses."""
S0 = ["S0.A1", "S0.A2", *(f"S0.P{n}" for n in range(1, 9)), "S0.A3", "S0.A4", "S0.A5", "S0.A6"]


@pytest.fixture
def steps_world(world: World) -> World:
    """The world with the committed stage files and ``steps.yaml`` (the step modules read them from the root)."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    shutil.copy2(REPO_ROOT.joinpath(*STEPS_FILE), world.root.joinpath(*STEPS_FILE))
    return world


def batch(service: B1500Service, ids: list[str], *, doctor: list[tuple[str, str, str]] | None = DOCTOR_OK,
          **options: Any) -> StepDone:
    lines = doctor
    return bringup_steps.done(service, ids, StepArgs(**options),
                              doctor=None if lines is None else (lambda: lines))


def entries(world: World) -> list[Any]:
    return read_ledger(world.state_dir / "bringup" / "ledger-sim.jsonl").entries


def done_calls(world: World) -> list[dict[str, Any]]:
    return [e.data for e in world.audit_events() if e.ev == "tool_call" and e.data
            and e.data.get("tool") == "bringup_done"]


def walk_to_s0(service: B1500Service) -> None:
    assert batch(service, DEPLOYMENT, **WORDS).ok
    assert batch(service, ["R1", "R2", "R3", "R4"], observe=("reconfirm=none",), **WORDS).ok


def spec(**fields: Any) -> StepSpec:
    values: dict[str, Any] = {"id": "L2.A3", "who": "agent", "verify": "observation", "rehearsal": "run_sim",
                              "keys": ["seen"]}
    values.update(fields)
    return StepSpec.model_validate(values)


# -- next shows the batch ----------------------------------------------------------------------------------------------


def test_next_shows_the_batch_that_can_follow_and_its_line(steps_world: World) -> None:
    service = steps_world.service()
    shown = bringup_steps.next_step(service)
    assert shown.step is not None and shown.step.id == "D1"
    assert [b.id for b in shown.step.batch] == DEPLOYMENT[1:]
    assert shown.step.batch[2].verify == "doctor" and shown.step.batch[2].text.startswith("`uv sync --frozen`")
    assert shown.step.batch_done == ("uv run b1500 bringup done D1 D4 D6 D7 D8 D9 D11 --human "
                                     "\"<the human's own words>\" --by <NAME>")
    assert any(step.endswith(shown.step.batch_done) and "7 steps, in order" in step for step in shown.next_steps)
    walk_to_s0(service)
    s0 = bringup_steps.next_step(service)
    assert s0.step is not None and s0.step.id == "S0.A1" and [b.id for b in s0.step.batch] == S0[1:]
    assert ("--observe next_stage=<VALUE> --observe handed_over=<VALUE> --observe compared=<VALUE> --human "
            in s0.step.batch_done)
    assert batch(service, S0, observe=("next_stage=S0", "handed_over=1-8", "compared=as expected"), **WORDS).ok
    l0 = bringup_steps.next_step(service)
    assert l0.step is not None and l0.step.id == "L0.P1"
    assert [b.id for b in l0.step.batch] == ["L0.A1", "L0.A2"]  # L0.A3 takes --probe too: the batch ends at L0.A2
    assert l0.step.batch_done == ("uv run b1500 bringup done L0.P1 L0.A1 L0.A2 --probe latest --human "
                                  "\"<the human's own words>\" --by <NAME>")


def test_conflicts_name_an_option_or_key_two_steps_take_and_where_runs_and_records_go() -> None:
    """At most one step per evidence option or ``--observe`` key; a run step ends its batch (its verdict decides
    whether the stage goes on), a record step starts it (its draft embeds the ledger entries before it)."""
    pairs = [(STEPS.get(i), "run") for i in ("L1.A4", "L1.A5")]
    assert conflicts(pairs) == ["L1.A4, L1.A5 each take --run",  # type: ignore[arg-type]
                                "L1.A4 is a run step: it ends its batch (recorded before the next step is done)"]
    after_run = [(STEPS.get("L1.A5"), "run"), (STEPS.get("L1.P3"), "confirm")]
    assert conflicts(after_run) == [  # type: ignore[arg-type]
        "L1.A5 is a run step: it ends its batch (recorded before the next step is done)"]
    assert conflicts([(STEPS.get("L1.P2"), "config"), (STEPS.get("L1.A3"), "run")]) == []  # type: ignore[list-item]
    record = [(STEPS.get("S0.A4"), "doctor"), (STEPS.get("S0.A5"), "record"), (STEPS.get("S0.A6"), "confirm")]
    assert conflicts(record) == [  # type: ignore[arg-type]
        "S0.A5 drafts records from the ledger: it starts its batch (the steps before it recorded first)"]
    assert conflicts(record[1:]) == [] and conflicts([(STEPS.get("S0.A5"), "refusal")]) == []  # type: ignore[list-item]
    probes = [(STEPS.get(i), "probe") for i in ("L0.A2", "L0.A3")]
    assert conflicts(probes) == ["L0.A2, L0.A3 each take --probe"]  # type: ignore[arg-type]
    keyed = [(spec(id="L2.A3"), "observation"), (spec(id="L2.A4"), "observation")]
    assert conflicts(keyed) == ["L2.A3, L2.A4 each take --observe seen"]
    assert conflicts([(spec(id="L2.A3"), "observation"), (spec(id="L2.A4", keys=["other"]), "observation")]) == []
    line = batch_line([(spec(id="L2.A3"), "observation"), (spec(id="L2.P1", who="human", keys=["dmm"]), "confirm")])
    assert line == ("uv run b1500 bringup done L2.A3 L2.P1 --observe seen=<VALUE> --human \"<the human's own words>\" "
                    "--by <NAME>")  # the waived key of a human_done rehearsal is not asked for


def ledger_up_to(step_id: str, backend: str = "sim") -> list[Any]:
    """Passing entries of every step ``next`` names before ``step_id`` (a recorded history, never written)."""
    entries: list[Any] = []
    now = datetime.now(UTC)
    while True:
        following, _why = State(STEPS, backend, entries, now).next()  # type: ignore[arg-type]
        assert following is not None
        if following.id == step_id:
            return entries
        kind = effective_kind(following, backend)  # type: ignore[arg-type]
        entries.append(make_entry(len(entries) + 1, GENESIS_SHA256, step=following.id, ts=now, backend=backend,
                                  actor="agent", verify=kind, verdict="pass"))


def test_plan_batch_keeps_runs_last_and_records_first() -> None:
    now = datetime.now(UTC)
    sim = ledger_up_to("L1.A5")
    with pytest.raises(Refused, match="L1.A5 is a run step: it ends its batch"):
        plan_batch(STEPS, "sim", sim, now, [(STEPS.get("L1.A5"), "run"), (STEPS.get("L1.P3"), "confirm")],  # type: ignore[list-item]
                   StepArgs(runs=("S20261201T093012Z-1a2b",), **WORDS), "agent")
    planned = plan_batch(STEPS, "sim", ledger_up_to("L1.P3"), now,
                         [(STEPS.get("L1.P3"), "confirm"), (STEPS.get("L1.A6"), "run")],  # type: ignore[list-item]
                         StepArgs(runs=("S20261201T093012Z-1a2b",), **WORDS), "agent")
    assert [(p.spec.id, p.args.runs, p.args.human, p.actor) for p in planned] == [
        ("L1.P3", (), WORDS["human"], "human_via_agent"), ("L1.A6", ("S20261201T093012Z-1a2b",), None, "agent")]
    visa = ledger_up_to("S0.A4", "visa")
    with pytest.raises(Refused, match="S0.A5 drafts records from the ledger: it starts its batch"):
        plan_batch(STEPS, "visa", visa, now, [(STEPS.get("S0.A4"), "doctor"), (STEPS.get("S0.A5"), "record")],  # type: ignore[list-item]
                   StepArgs(drafts=("work/bringup/records/stage-s0.yaml",)), "agent")
    record_first = plan_batch(STEPS, "visa", ledger_up_to("S0.A5", "visa"), now,
                              [(STEPS.get("S0.A5"), "record"), (STEPS.get("S0.A6"), "confirm")],  # type: ignore[list-item]
                              StepArgs(drafts=("work/bringup/records/stage-s0.yaml",), human="Continue.", by="Owner"),
                              "human")
    assert [(p.spec.id, p.args.drafts, p.actor) for p in record_first] == [
        ("S0.A5", ("work/bringup/records/stage-s0.yaml",), "human"), ("S0.A6", (), "human")]  # the human's terminal


# -- a batch records one entry per step --------------------------------------------------------------------------------


def test_a_batch_appends_one_verified_entry_per_step_on_the_hash_chain(steps_world: World) -> None:
    service = steps_world.service()
    result = batch(service, DEPLOYMENT, **WORDS)
    assert result.ok and result.status == "ok" and result.recorded, result.message
    assert [e.step for e in result.entries] == DEPLOYMENT and result.entry == result.entries[-1]
    assert result.message.startswith("SIMULATED 7 steps pass: D1 (the human's words (Owner)); D4 ")
    written = entries(steps_world)
    assert written == result.entries and [e.seq for e in written] == list(range(1, 8))
    for before, after in itertools.pairwise(written):
        assert after.prev_sha256 == before.sha256
    by_step = {e.step: e for e in written}
    assert by_step["D7"].verify == "doctor" and by_step["D7"].actor == "agent"  # the agent's step: no words
    assert by_step["D7"].evidence.human is None and "doctor: 3 checks" in by_step["D7"].evidence.facts[0]
    for step in ("D1", "D4", "D6", "D8", "D9", "D11"):
        entry = by_step[step]
        assert entry.actor == "human_via_agent" and entry.evidence.human is not None
        assert entry.evidence.human.quote == WORDS["human"] and entry.evidence.human.by == "Owner"
    assert result.next is not None and result.next.id == "R1" and [b.id for b in result.next.batch] == ["R2", "R3",
                                                                                                           "R4"]
    assert result.next_steps[0].startswith("next: R1: uv run b1500 bringup done R1")
    assert result.next_steps[1].endswith("uv run b1500 bringup done R1 R2 R3 R4 --observe reconfirm=<VALUE> --human "
                                         "\"<the human's own words>\" --by <NAME>")
    calls = done_calls(steps_world)
    assert len(calls) == 1 and calls[0]["status"] == "ok" and calls[0]["steps"] == " ".join(DEPLOYMENT)
    start = batch(service, ["R1", "R2", "R3", "R4"], observe=("reconfirm=none",), **WORDS)
    assert start.ok and [e.actor for e in start.entries] == ["agent", "agent", "human_via_agent", "agent"]
    assert start.entries[3].evidence.observe == {"reconfirm": "none"} and start.entries[2].evidence.observe == {}
    assert bringup_steps.check(service).ok


def test_each_option_goes_to_the_step_that_takes_it(steps_world: World) -> None:
    service = steps_world.service()
    walk_to_s0(service)
    assert batch(service, S0, observe=("next_stage=S0", "handed_over=1-8", "compared=as expected"), **WORDS).ok
    assert B1500Admin(service).probe(wgfmu_session=True).ok
    first = batch(service, ["L0.P1", "L0.A1", "L0.A2"], probe="latest", **WORDS)
    assert first.ok, first.message
    assert first.entries[0].evidence.probe is None and first.entries[2].evidence.probe is not None
    assert B1500Admin(service).probe().ok
    proposal = bringup.propose_station(service)
    assert proposal.ok and proposal.path is not None
    pair = batch(service, ["L0.A3", "L0.A4"], probe="latest", drafts=(proposal.path,),
                 observe=("terminations=every answer complete",), references=("terminations=1",))
    assert pair.ok, pair.message
    probe_entry, proposal_entry = pair.entries
    assert probe_entry.evidence.probe is not None and probe_entry.evidence.drafts == []
    assert probe_entry.evidence.observe == {"terminations": "every answer complete"}
    assert probe_entry.evidence.references == {"terminations": 1.0}
    assert proposal_entry.evidence.probe is None and proposal_entry.evidence.observe == {}
    assert [d.ref for d in proposal_entry.evidence.drafts] == [proposal.path]
    assert probe_entry.actor == proposal_entry.actor == "agent"
    assert bringup_steps.check(service, "L0").ok is False  # L0.P2 ... still open: a gap of the stage, not of an entry
    assert bringup_steps.check(service).ok


# -- refusals write nothing --------------------------------------------------------------------------------------------


def test_batch_refusals_write_nothing(steps_world: World) -> None:
    service = steps_world.service()
    cases: list[tuple[list[str], dict[str, Any], str]] = [
        (["D4", "D6"], WORDS, "after D4 comes D1, not D6"),  # D4 alone could go first; D6 never before D1
        (["D1", "D6"], WORDS, "after D1 comes D4, not D6"),
        (["D1", "D1"], WORDS, "D1 named twice"),
        (["D1", "D4"], {**WORDS, "runs": ("S20261201T093012Z-1a2b",)}, "--run given, but no step of D1, D4 takes it"),
        (["D1", "D4"], {**WORDS, "observe": ("seen=yes",)}, "--observe seen: no step of D1, D4 takes it"),
        (["D1", "D4"], {"by": "Owner"}, "step D1 records the human's own words"),
        (["D1", "D4", "D6", "D7"], WORDS, "a doctor step runs `uv run b1500 doctor`"),
        (["D1", "D2"], WORDS, "D2 is not rehearsed on the simulator"),
    ]
    for ids, options, message in cases:
        result = batch(service, ids, doctor=None if "doctor step" in message else DOCTOR_OK, **options)
        assert not result.ok and result.status == "refused" and not result.recorded, result.message
        assert message in result.message, (ids, result.message)
    assert not (steps_world.state_dir / "bringup" / "ledger-sim.jsonl").exists()
    assert {c["status"] for c in done_calls(steps_world)} == {"refused"}
    assert all("steps" not in c for c in done_calls(steps_world))
    assert batch(service, DEPLOYMENT[:-1], **WORDS).ok
    across = batch(service, ["D11", "R1"], **WORDS)
    assert across.status == "refused" and "a batch stays within one stage (or the D, R or E steps), not D, R" in \
        across.message
    assert [e.step for e in entries(steps_world)] == DEPLOYMENT[:-1]
    assert batch(service, ["D11"], **WORDS).ok
    stage = batch(service, ["S0.A1", "S0.A2"], observe=("next_stage=S0", "handed_over=1-8"))
    assert stage.status == "refused" and "this session starts with R1, R2, R3, R4" in stage.message  # the first
    assert [e.step for e in entries(steps_world)] == DEPLOYMENT  # step obeys the order rule of one `done`


def test_the_session_ends_with_one_call(steps_world: World) -> None:
    """E1 (outside what ``next`` names: the session ends when the agent and the human decide) may start a batch like
    one ``done`` of it could; the end steps ``next`` names after it follow in the same call."""
    service = steps_world.service()
    walk_to_s0(service)
    shown = bringup_steps.next_step(service)
    assert any(step.startswith("to end the session: E1 first (`uv run b1500 bringup done E1 E3`")
               for step in shown.next_steps)
    ended = batch(service, ["E1", "E3"])
    assert ended.ok and [(e.step, e.verify) for e in ended.entries] == [("E1", "station"), ("E3", "ledger")]
    fresh = bringup_steps.next_step(service)
    assert fresh.step is not None and fresh.step.id == "R1" and [b.id for b in fresh.step.batch] == ["R2", "R3", "R4"]
    assert any("a new session" in note for note in fresh.notes)
    across = batch(service, ["E1", "E3", "R1"])
    assert across.status == "refused" and "not E, R" in across.message


def test_two_steps_taking_one_option_are_refused(steps_world: World) -> None:
    service = steps_world.service()
    walk_to_s0(service)
    assert batch(service, S0, observe=("next_stage=S0", "handed_over=1-8", "compared=as expected"), **WORDS).ok
    assert B1500Admin(service).probe().ok
    assert batch(service, ["L0.P1", "L0.A1"], **WORDS).ok
    refused = batch(service, ["L0.A2", "L0.A3"], probe="latest", observe=("terminations=complete",))
    assert refused.status == "refused" and not refused.recorded
    assert "L0.A2, L0.A3 each take --probe: one `done` call for each of them (nothing written)" in refused.message
    assert [e.step for e in entries(steps_world)][-2:] == ["L0.P1", "L0.A1"]


# -- failures and missing evidence end the call ------------------------------------------------------------------------


def test_the_first_failing_step_is_recorded_fail_and_ends_the_batch(steps_world: World) -> None:
    service = steps_world.service()
    failing = batch(service, DEPLOYMENT, doctor=[("config", "FAIL", "broken")], **WORDS)
    assert failing.recorded and not failing.ok and failing.status == "error"
    assert [(e.step, e.verdict) for e in failing.entries] == [("D1", "pass"), ("D4", "pass"), ("D6", "pass"),
                                                              ("D7", "fail")]
    assert failing.message.startswith("SIMULATED D7 FAIL recorded: doctor: FAIL config")
    assert "(the batch stopped at D7: D1, D4, D6 passed; not recorded: D8, D9, D11)" in failing.message
    assert failing.next_steps[0].startswith('stop: safe_shutdown("D7 failed')
    assert [e.step for e in entries(steps_world)] == ["D1", "D4", "D6", "D7"]
    stays = bringup_steps.next_step(service)
    assert stays.step is not None and (stays.step.id, stays.step.state) == ("D7", "failed")
    assert stays.step.batch == [] and stays.step.batch_done == ""  # a failed step is shown alone
    assert done_calls(steps_world)[-1]["steps"] == "D1 D4 D6 D7"
    again = batch(service, DEPLOYMENT[3:], **WORDS)
    assert again.ok and [e.step for e in again.entries] == DEPLOYMENT[3:]
    assert bringup_steps.check(service).ok


def test_a_step_without_its_evidence_ends_the_batch_unrecorded(steps_world: World) -> None:
    service = steps_world.service()
    walk_to_s0(service)
    assert batch(service, S0, observe=("next_stage=S0", "handed_over=1-8", "compared=as expected"), **WORDS).ok
    stopped = batch(service, ["L0.P1", "L0.A1", "L0.A2"], probe="latest", **WORDS)  # no probe was run
    assert stopped.recorded and not stopped.ok and stopped.status == "refused"
    assert [e.step for e in stopped.entries] == ["L0.P1", "L0.A1"]
    assert stopped.message.startswith("SIMULATED L0.P1, L0.A1 pass; L0.A2 not recorded: no probe record")
    assert stopped.next is not None and stopped.next.id == "L0.A2"
    call = done_calls(steps_world)[-1]
    assert (call["status"], call["steps"]) == ("refused", "L0.P1 L0.A1")
    first = batch(service, ["L0.A2", "L0.A3"], probe="latest")
    assert first.status == "refused" and not first.recorded  # --probe taken twice: nothing written
    nothing = bringup_steps.done(service, ["L0.A2"], StepArgs(probe="latest"))
    assert nothing.status == "refused" and not nothing.recorded and nothing.message.startswith("L0.A2 not recorded")


def test_the_options_a_step_takes_cover_its_done_line() -> None:
    """``evidence_options`` (how a batch routes ``--run``, ``--probe``, ``--draft``, ``--fixtures``: what the step's
    verifier reads) covers the options the ``done`` line of every step names on both backends, and the line of one
    step is the batch line of that step alone."""
    for step in STEPS.all():
        for backend in ("sim", "visa"):
            kind = effective_kind(step, backend)  # type: ignore[arg-type]
            if kind is None:
                continue
            line = bringup_steps.done_line(step, kind)
            assert line == batch_line([(step, kind)])
            named = {option for option in ("run", "probe", "draft", "fixtures") if f"--{option} " in line}
            assert named <= evidence_options(kind), (step.id, backend, line)
    assert evidence_options("config") == {"draft"} and evidence_options("refusal") == {"run"}
    assert evidence_options("confirm") == evidence_options("observation") == frozenset()
