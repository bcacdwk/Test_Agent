"""Bring-up steps, the step ledger and ``next | done | check`` on the simulator (v2.1 plan §4.1; WP21.5).

The world is a hermetic copy (``helpers.make_world``) with the committed stage files and ``steps.yaml``; the ledger is
the simulator ledger ``<data>/state/bringup/ledger-sim.jsonl``. The doctor is injected (the CLI runs the real one).
Covered: the committed sequence (every numbered stage item exactly once), ``next`` on an empty ledger (D1), refusals
that write nothing (unknown step, missing human words, out of order, not rehearsed, missing evidence), the walk through
the deployment, a session start, S0, L0 and the first runs of L1 with real simulator runs, probe and proposal files,
a failure that ``next`` stays on, a break that asks the start steps and the steps to confirm again, the end of a
session, ``check`` scopes and re-verification of a changed run file, a tampered ledger, ``bringup status`` steps and
the ``rehearsed`` state, and every verifier's pass and fail on simulator evidence.
"""

from __future__ import annotations

import itertools
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent import bringup, bringup_steps
from b1500_test_agent.bringup_ledger import (
    BREAK,
    effective_kind,
    ledger_path,
    load_steps,
    make_entry,
    read_ledger,
    stage_items,
)
from b1500_test_agent.bringup_verify import VERIFIERS, Ctx, Refused, StepArgs, model_digest, run_problems
from b1500_test_agent.models.run import FaultRecord
from b1500_test_agent.models.validation import (
    GENESIS_SHA256,
    STAGE_FILES_DIR,
    STAGES,
    STEPS_FILE,
    EvidenceItem,
    StepDone,
    StepSpec,
    ledger_entry_sha256,
)
from b1500_test_agent.service import B1500Admin, B1500Service
from b1500_test_agent.service import evidence as evidence_reader
from tests.integration.helpers import REPO_ROOT, World

STEPS = load_steps(REPO_ROOT)
DOCTOR_OK = [("python", "PASS", "3.12"), ("harness files", "PASS", "wired"),
             ("harness versions", "PASS", "= validated")]
HUMAN = {"human": "done", "by": "Owner"}


@pytest.fixture
def steps_world(world: World) -> World:
    """The world with the committed stage files and ``steps.yaml`` (the step modules read them from the root)."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    shutil.copy2(REPO_ROOT.joinpath(*STEPS_FILE), world.root.joinpath(*STEPS_FILE))
    return world


def ledger_file(world: World) -> Path:
    return world.state_dir / "bringup" / "ledger-sim.jsonl"


def args_for(step_id: str, **extra: Any) -> StepArgs:
    """The evidence options a rehearsal gives ``step_id`` (the human's "done", observation keys), plus ``extra``."""
    spec = STEPS.get(step_id)
    if spec is None:
        return StepArgs(**extra)
    kind = effective_kind(spec, "sim")
    values: dict[str, Any] = {}
    if spec.who == "human" or kind == "confirm":
        values.update(HUMAN)
    if kind == spec.verify:
        values["observe"] = tuple(f"{key}=seen" for key in spec.keys)
    values.update(extra)
    return StepArgs(**values)


def done(service: B1500Service, step_id: str, *, doctor: list[tuple[str, str, str]] | None = None,
         now: datetime | None = None, **extra: Any) -> StepDone:
    lines = DOCTOR_OK if doctor is None else doctor
    return bringup_steps.done(service, step_id, args_for(step_id, **extra), doctor=lambda: lines, now=now)


def record(service: B1500Service, step_id: str, **extra: Any) -> StepDone:
    result = done(service, step_id, **extra)
    assert result.ok and result.recorded and result.entry is not None, result.message
    assert result.entry.verdict == "pass" and result.entry.step == step_id
    return result


def rehearsable(specs: list[StepSpec]) -> list[str]:
    return [s.id for s in specs if effective_kind(s, "sim") is not None]


def walk_deployment_and_start(service: B1500Service) -> None:
    for step_id in [*rehearsable(STEPS.deployment), *rehearsable(STEPS.session_start)]:
        record(service, step_id)


def walk_s0(service: B1500Service) -> None:
    for step_id in rehearsable(STEPS.stages["S0"]):
        record(service, step_id)


def walk_l0(service: B1500Service) -> None:
    admin = B1500Admin(service)
    for step_id in rehearsable(STEPS.stages["L0"]):
        extra: dict[str, Any] = {}
        spec = STEPS.get(step_id)
        assert spec is not None
        if spec.verify == "probe":
            report = admin.probe()
            assert report.ok and report.simulated, report.message
            extra["probe"] = "latest"
        elif spec.verify == "proposal" and effective_kind(spec, "sim") == "proposal":
            proposal = bringup.propose_station(service)
            assert proposal.ok and proposal.path is not None, proposal.message
            extra["drafts"] = (proposal.path,)
        record(service, step_id, **extra)


def confirmed_run(service: B1500Service, recipe_id: str, pin_map: str, dut: str, **params: Any) -> str:
    plan = service.validate_plan(recipe_id=recipe_id, params=params or None, pin_map=pin_map, dut_profile=dut)
    assert plan.plan_id is not None and plan.tier in ("ok", "needs_confirmation"), plan.message
    if plan.tier == "ok":
        result = service.run_plan(plan.plan_id)
    else:
        assert plan.summary is not None
        result = service.run_confirmed_plan(plan.plan_id, plan.summary)
    assert result.ok and result.run_id is not None and result.run_id.startswith("S"), result.message
    return result.run_id


def contact_run(service: B1500Service) -> str:
    return confirmed_run(service, "basic.contact_resistor", "resistor-2t", "resistor-generic", v_start=0, v_stop=0)


# -- the committed sequence -------------------------------------------------------------------------------------------


def test_the_committed_sequence_covers_every_numbered_stage_item_once() -> None:
    assert (len(STEPS.deployment), len(STEPS.session_start), len(STEPS.session_end)) == (12, 4, 5)
    assert [s.id for s in STEPS.deployment] == [f"D{n}" for n in range(1, 13)]
    assert list(STEPS.stages) == list(STAGES)
    items = 0
    for stage, specs in STEPS.stages.items():
        text = REPO_ROOT.joinpath(*STAGE_FILES_DIR, f"{STAGES[stage][0]}.md").read_text(encoding="utf-8")
        numbered = set(stage_items(text))
        items += len(numbered)
        named = [s.id.split(".", 1)[1] for s in specs if not s.is_review]
        assert sorted(named) == sorted(numbered) and len(named) == len(set(named)), stage
        assert specs[-1].id == f"{stage}.R" and specs[-1].verify == "review"
    # v2.1 plan §1.3: 148 = 58 physical + 90 agent; WP21.6 adds the §4.6 gap steps: 7 physical (L2.P5, L7.P7, L7.P8,
    # L8.P5, L9.P8, L9.P9, L10.P1) and 16 agent items (captures, the two-wire R, log sampling, the read window, the
    # negative control and its probe, ATV-17, the timer over hours, the correction drift, the session end)
    physical = sum(s.id.split(".")[1].startswith("P") for specs in STEPS.stages.values() for s in specs)
    assert items == 171 and physical == 65
    assert sum(len(v) for v in STEPS.stages.values()) == 183


def test_every_stage_check_is_fed_and_every_step_can_be_recorded_its_way() -> None:
    for stage, specs in STEPS.stages.items():
        front = bringup.load_stage(REPO_ROOT, stage)[1]
        assert front is not None
        fed = {check for spec in specs for check in spec.feeds}
        assert {c.id for c in front.checks} <= fed, stage
    for spec in STEPS.all():
        for backend in ("sim", "visa"):
            kind = effective_kind(spec, backend)  # type: ignore[arg-type]
            if kind is not None:
                assert kind in VERIFIERS
                line = bringup_steps.done_line(spec, kind)
                assert line.startswith(f"uv run b1500 bringup done {spec.id}")
                assert ("--human" in line) == (spec.who == "human" or kind == "confirm")


# -- next and refusals ------------------------------------------------------------------------------------------------


def test_next_on_an_empty_simulator_ledger_is_d1_and_writes_nothing(steps_world: World) -> None:
    result = bringup_steps.next_step(steps_world.service())
    assert result.ok and result.simulated and result.step is not None and result.step.id == "D1"
    assert result.message.startswith("SIMULATED next step D1 (D, human, verify confirm): Git for Windows")
    assert result.step.done == 'uv run b1500 bringup done D1 --human "<the human\'s own words>" --by <NAME>'
    assert result.progress["D"] == "0/7" and result.progress["S0"] == "0/14" and result.progress["E"] == "0/2"
    assert result.ledger == "data/state/bringup/ledger-sim.jsonl" or result.ledger.endswith("ledger-sim.jsonl")
    assert any("never signs a hardware stage" in note for note in result.notes)
    assert not ledger_file(steps_world).exists()


def test_refusals_write_nothing(steps_world: World) -> None:
    service = steps_world.service()
    cases = [
        ("D99", {}, "unknown step 'D99'"),
        ("D1", {"human": None, "by": None}, "records the human's own words"),
        ("D1", {"by": None}, "records the human's own words"),
        ("D2", {}, "not rehearsed on the simulator"),
        ("S0.A1", {}, "session 0 (deployment) is not complete: D1"),
        ("R1", {}, "session 0 (deployment) is not complete"),
    ]
    for step_id, extra, message in cases:
        result = done(service, step_id, **extra)
        assert not result.ok and result.status == "refused" and not result.recorded, result.message
        assert message in result.message, (step_id, result.message)
    without_doctor = bringup_steps.done(service, "D7", StepArgs(), doctor=None)
    assert without_doctor.status == "refused" and "runs `uv run b1500 doctor`" in without_doctor.message
    assert not ledger_file(steps_world).exists()
    calls = [e.data for e in steps_world.audit_events() if e.ev == "tool_call" and e.data
             and e.data.get("tool") == "bringup_done"]
    assert len(calls) == len(cases) + 1 and all(c["status"] == "refused" for c in calls)


def test_the_walk_records_a_hash_chain_and_moves_through_the_sequence(steps_world: World) -> None:
    service = steps_world.service()
    first = record(service, "D1")
    assert first.entry is not None and first.entry.seq == 1 and first.entry.prev_sha256 == GENESIS_SHA256
    assert first.entry.actor == "agent" and first.entry.verify == "confirm" and first.entry.backend == "sim"
    assert first.entry.evidence.human is not None and first.entry.evidence.human.quote == "done"
    assert first.next is not None and first.next.id == "D4"  # D2, D3 are lab only (skip on the simulator)
    walk = rehearsable(STEPS.deployment)[1:]
    for step_id in walk:
        record(service, step_id)
    after_deployment = bringup_steps.next_step(service)
    assert after_deployment.step is not None and after_deployment.step.id == "R1"
    refused = done(service, "S0.A1")
    assert refused.status == "refused" and "this session starts with R1, R2, R3, R4" in refused.message
    for step_id in rehearsable(STEPS.session_start):
        record(service, step_id)
    following = bringup_steps.next_step(service)
    assert following.step is not None and following.step.id == "S0.A1"
    assert following.step.text.startswith("`uv run b1500 bringup status`: confirm that S0 is next")
    assert "--observe next_stage=<VALUE>" in following.step.done
    entries = read_ledger(ledger_file(steps_world)).entries
    assert [e.seq for e in entries] == list(range(1, len(entries) + 1))
    for before, after in itertools.pairwise(entries):
        assert after.prev_sha256 == before.sha256
        assert after.sha256 == ledger_entry_sha256(after.model_dump(mode="json"))


def test_a_failure_is_recorded_and_next_stays_on_it(steps_world: World) -> None:
    service = steps_world.service()
    for step_id in rehearsable(STEPS.deployment)[:3]:  # D1, D4, D6
        record(service, step_id)
    failing = done(service, "D7", doctor=[("config", "FAIL", "broken"), ("python", "PASS", "")])
    assert failing.recorded and not failing.ok and failing.status == "error" and failing.entry is not None
    assert failing.entry.verdict == "fail" and "doctor: FAIL config" in failing.entry.reason
    assert any(step.startswith('stop: safe_shutdown("D7 failed') for step in failing.next_steps)
    stays = bringup_steps.next_step(service)
    assert stays.step is not None and stays.step.id == "D7" and stays.step.state == "failed"
    assert stays.step.last_reason is not None and "FAIL config" in stays.step.last_reason
    assert stays.message.startswith("SIMULATED stays on the failed step D7")
    again = record(service, "D7")
    assert again.next is not None and again.next.id == "D8"


def test_must_pass_lines_take_info_on_the_simulator_only_pass(steps_world: World) -> None:
    service = steps_world.service()
    for step_id in rehearsable(STEPS.deployment):
        record(service, step_id)
    warned = done(service, "R1", doctor=[("harness versions", "WARN", "run update")])
    assert warned.entry is not None and warned.entry.verdict == "fail"
    assert "must PASS: harness versions WARN" in warned.entry.reason
    record(service, "R1", doctor=[("harness versions", "INFO", "no harness CLI on PATH")])


def test_s0_and_l0_rehearsed_with_probe_and_proposal_files(steps_world: World) -> None:
    service = steps_world.service()
    walk_deployment_and_start(service)
    walk_s0(service)
    status = bringup.bringup_status(service)
    s0 = next(s for s in status.stages if s.stage == "S0")
    assert (s0.state, s0.steps_done, s0.steps_total) == ("rehearsed", 14, 14)
    assert status.next_stage == "L0" and status.next_step == "L0.P1"
    assert status.message.startswith("SIMULATED next stage L0:") and "(open, steps 0/11)" in status.message
    walk_l0(service)
    entries = {e.step: e for e in read_ledger(ledger_file(steps_world)).entries}
    assert entries["L0.A2"].evidence.probe is not None and entries["L0.A2"].verify == "probe"
    assert entries["L0.A4"].evidence.drafts[0].ref.endswith("work/bringup/station.proposed.yaml")
    assert entries["L0.A7"].verify == "refusal" and "simulator refuses" in entries["L0.A7"].reason
    assert entries["L0.P2"].verify == "confirm"  # config adoption: the human's done on the simulator
    checked = bringup_steps.check(service, "L0")
    assert checked.ok and checked.scope == "L0", [g.reason for g in checked.gaps]
    every = bringup_steps.check(service, all_stages=True)
    assert not every.ok and {g.step for g in every.gaps} >= {"L1.A1", "L10.A5"}
    assert "L0.R" not in {g.step for g in every.gaps}  # review steps are lab only
    l0 = next(s for s in bringup.bringup_status(service).stages if s.stage == "L0")
    assert l0.state == "rehearsed" and l0.records[0].state == "missing"


def test_runs_of_l1_and_a_break_with_reconfirm(steps_world: World) -> None:
    service = steps_world.service()
    walk_deployment_and_start(service)
    walk_s0(service)
    walk_l0(service)
    for step_id in ("L1.A1", "L1.A2", "L1.P1", "L1.P2"):
        record(service, step_id)
    self_test = confirmed_run(service, "system.self_test", "open-smus", "open-circuit")
    self_cal = confirmed_run(service, "system.self_cal", "open-smus", "open-circuit")
    missing = done(service, "L1.A3", runs=(self_test,))
    assert missing.entry is not None and missing.entry.verdict == "fail"
    assert "no run of system.self_cal among the runs given" in missing.entry.reason
    passed = record(service, "L1.A3", runs=(self_test, self_cal))
    assert passed.entry is not None and [r.ref for r in passed.entry.evidence.runs] == [self_test, self_cal]
    assert passed.next is not None and passed.next.id == "L1.A4"
    later = steps_world.clock() + BREAK + timedelta(hours=1)
    resumed = bringup_steps.next_step(service, now=later)
    assert resumed.step is not None and resumed.step.id == "R1"
    assert any("a new session" in note for note in resumed.notes)
    assert done(service, "L1.A4", now=later).status == "refused"
    for step_id in rehearsable(STEPS.session_start):
        record(service, step_id, now=later)
    again = bringup_steps.next_step(service, now=later)
    assert again.step is not None and again.step.id == "L1.P1" and again.step.state == "reconfirm"
    assert again.reconfirm == ["L1.P1"] and again.message.startswith("SIMULATED confirm again after the break L1.P1")
    record(service, "L1.P1", now=later)
    following = bringup_steps.next_step(service, now=later)
    assert following.step is not None and following.step.id == "L1.A4" and following.reconfirm == []


def test_the_end_steps_end_the_session(steps_world: World) -> None:
    service = steps_world.service()
    walk_deployment_and_start(service)
    record(service, "E1")
    ending = bringup_steps.next_step(service)
    assert ending.step is not None and ending.step.id == "E3"  # E2, E4, E5 are lab only
    record(service, "E3")
    fresh = bringup_steps.next_step(service)
    assert fresh.step is not None and fresh.step.id == "R1"


def test_check_reverifies_runs_and_a_tampered_ledger_stops_everything(steps_world: World) -> None:
    service = steps_world.service()
    run_id = contact_run(service)
    record(service, "D1")
    path = ledger_file(steps_world)
    entries = read_ledger(path).entries
    manifest = evidence_reader.run_facts(service.config.get(), run_id).manifest
    extra = make_entry(len(entries) + 1, entries[-1].sha256, step="D4", ts=steps_world.clock(), backend="sim",
                       actor="agent", verify="run", verdict="pass", reason="test entry",
                       evidence={"runs": [EvidenceItem(ref=run_id, sha256=model_digest(manifest))]})
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(extra.model_dump(mode="json")) + "\n")
    assert bringup_steps.check(service).ok
    run_dir = next(p for p in steps_world.runs_dir.rglob(run_id) if p.is_dir())
    (run_dir / "data.csv").write_text("step\n0\n", encoding="utf-8")
    changed = bringup_steps.check(service)
    assert not changed.ok and any(g.step == "D4" and "files changed since the run" in g.reason for g in changed.gaps)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"quote":"done"', '"quote":"done by me"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tampered = bringup_steps.check(service)
    assert not tampered.ok and tampered.gaps[0].step == "-"
    assert "line 1 (D1): its content does not match its sha256" in tampered.gaps[0].reason
    blocked = done(service, "D6")
    assert blocked.status == "refused" and "is damaged" in blocked.message
    shown = bringup_steps.next_step(service)
    assert not shown.ok and shown.status == "error" and "is damaged" in shown.message
    path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")  # a removed line breaks the chain too
    assert "the hash chain breaks here" in read_ledger(path).problems[0]


def test_a_latched_fault_fails_the_station_step(steps_world: World) -> None:
    service = steps_world.service()
    for step_id in rehearsable(STEPS.deployment):
        record(service, step_id)
    record(service, "R1")
    steps_world.state_dir.mkdir(parents=True, exist_ok=True)
    fault = FaultRecord(reason="test fault", run_id=None, set_at=datetime.now(UTC))
    (steps_world.state_dir / "fault.json").write_text(fault.model_dump_json(), encoding="utf-8")
    result = done(service, "R2")
    assert result.entry is not None and result.entry.verdict == "fail"
    assert "fault latched: test fault" in result.entry.reason
    assert any("station: fault latched" in fact for fact in result.entry.evidence.facts)


# -- verifiers on simulator evidence ----------------------------------------------------------------------------------


def ctx_for(service: B1500Service, spec: StepSpec, args: StepArgs) -> Ctx:
    bundle = service.config.get()
    return Ctx(service, bundle, STEPS, spec, spec.verify, args)


def spec(**fields: Any) -> StepSpec:
    values: dict[str, Any] = {"id": "L2.A3", "who": "agent", "verify": "run", "rehearsal": "run_sim"}
    values.update(fields)
    return StepSpec.model_validate(values)


def test_run_verifier_on_simulator_runs(steps_world: World) -> None:
    service = steps_world.service()
    run_id = contact_run(service)
    good = spec(recipes=["basic.contact_resistor"])
    verdict, reason = VERIFIERS["run"](ctx_for(service, good, StepArgs(runs=(run_id,))))
    assert verdict == "pass" and run_id in reason
    other = spec(recipes=["mosfet.idvg"])
    verdict, reason = VERIFIERS["run"](ctx_for(service, other, StepArgs(runs=(run_id,))))
    assert verdict == "fail" and "is a run of basic.contact_resistor; L2.A3 takes mosfet.idvg" in reason
    assert "no run of mosfet.idvg" in reason
    drill = spec(recipes=["basic.contact_resistor"], outcomes=["aborted", "cancelled"])
    verdict, reason = VERIFIERS["run"](ctx_for(service, drill, StepArgs(runs=(run_id,))))
    assert verdict == "fail" and "L2.A3 needs aborted or cancelled" in reason
    for runs, message in [((), "give the runs"), (("S1",), "not run ids"),
                          (("S20261201T093012Z-1a2b",), "run S20261201T093012Z-1a2b")]:
        with pytest.raises(Refused, match=message):
            VERIFIERS["run"](ctx_for(service, good, StepArgs(runs=runs)))
    bundle = service.config.get()
    assert run_problems(evidence_reader.run_facts(bundle, run_id), good, "visa") == [
        f"run {run_id} ran on backend sim: the visa ledger takes hardware runs (H...) only"]
    run_dir = next(p for p in steps_world.runs_dir.rglob(run_id) if p.is_dir())
    (run_dir / "data.csv").write_text("step\n0\n", encoding="utf-8")
    verdict, reason = VERIFIERS["run"](ctx_for(service, good, StepArgs(runs=(run_id,))))
    assert verdict == "fail" and "files changed since the run (data.csv)" in reason


def test_probe_proposal_and_capture_refusal_verifiers(steps_world: World) -> None:
    service = steps_world.service()
    probe_spec = spec(id="L0.A2", verify="probe")
    with pytest.raises(Refused, match="no probe record"):
        VERIFIERS["probe"](ctx_for(service, probe_spec, StepArgs(probe="latest")))
    assert B1500Admin(service).probe().ok
    verdict, reason = VERIFIERS["probe"](ctx_for(service, probe_spec, StepArgs(probe="latest")))
    assert verdict == "pass" and "no FAIL" in reason
    proposal = bringup.propose_station(service)
    assert proposal.path is not None
    station = spec(id="L0.A4", verify="proposal", config=["station"])
    verdict, _ = VERIFIERS["proposal"](ctx_for(service, station, StepArgs(drafts=(proposal.path,))))
    assert verdict == "pass"
    pin_map = spec(id="L1.A2", verify="proposal", config=["pinmap", "dut"])
    verdict, reason = VERIFIERS["proposal"](ctx_for(service, pin_map, StepArgs(drafts=(proposal.path,))))
    assert verdict == "fail" and "not a pinmap" in reason and "no pinmap, dut proposal among the files" in reason
    outside = steps_world.root / "config" / "pinmaps" / "open-smus.example.yaml"
    with pytest.raises(Refused, match="a proposal file lies under"):
        VERIFIERS["proposal"](ctx_for(service, pin_map, StepArgs(drafts=(str(outside),))))
    work = steps_world.root / "work" / "bringup"
    shutil.copy2(outside, work / "open-smus.yaml")
    shutil.copy2(steps_world.root / "config" / "duts" / "open-circuit.example.yaml", work / "open-circuit.yaml")
    verdict, reason = VERIFIERS["proposal"](ctx_for(service, pin_map, StepArgs(
        drafts=("work/bringup/open-smus.yaml", "work/bringup/open-circuit.yaml"))))
    assert verdict == "pass" and "dut, pinmap" in reason
    run_id = contact_run(service)
    capture = spec(id="L1.A8", verify="capture", rehearsal="refusal", recipes=["basic.contact_resistor"])
    verdict, reason = VERIFIERS["refusal"](ctx_for(service, capture, StepArgs(runs=(run_id,))))
    assert verdict == "pass" and "refuses" in reason


def test_hw_suite_verifier_reads_the_junit_file(steps_world: World) -> None:
    service = steps_world.service()
    suite = spec(id="E2", who="human", verify="hw_suite", rehearsal="skip", text="hardware suite")
    work = steps_world.root / "work" / "bringup"
    work.mkdir(parents=True, exist_ok=True)
    cases = {
        "pass.xml": (('<testcase name="test_stage_records[L1]"/><testcase name="test_stage_records[L2]">'
                      '<skipped message="no record of stage L2 yet"/></testcase>'), "pass"),
        "fail.xml": ('<testcase name="test_stage_records[L1]"><failure message="boom"/></testcase>', "1 failed"),
        "gate.xml": (('<testcase name="test_probe"><skipped message="hardware test: B1500_HW is unset, not 1"/>'
                      '</testcase>'), "skipped by the gate"),
        "empty.xml": ("", "lists no test"),
    }
    for name, (body, expected) in cases.items():
        (work / name).write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite>'
                                 "</testsuites>", encoding="utf-8")
        verdict, reason = VERIFIERS["hw_suite"](ctx_for(service, suite, StepArgs(drafts=(f"work/bringup/{name}",))))
        assert (verdict == "pass") == (expected == "pass") and (expected == "pass" or expected in reason), reason
    (work / "broken.xml").write_text("<testsuites>", encoding="utf-8")
    verdict, reason = VERIFIERS["hw_suite"](ctx_for(service, suite, StepArgs(drafts=("work/bringup/broken.xml",))))
    assert verdict == "fail" and "not a JUnit XML file" in reason
    with pytest.raises(Refused, match="JUnit file"):
        VERIFIERS["hw_suite"](ctx_for(service, suite, StepArgs()))


def test_review_verifier_needs_every_record_of_the_stage(steps_world: World) -> None:
    service = steps_world.service()
    review = spec(id="S0.R", who="human", verify="review", rehearsal="skip")
    verdict, reason = VERIFIERS["review"](ctx_for(service, review, StepArgs()))
    assert verdict == "fail" and "validation/hw/stage-s0.yaml missing" in reason


def test_status_and_record_steps_without_a_ledger(steps_world: World) -> None:
    service = steps_world.service()
    status = bringup.bringup_status(service)
    assert status.next_step == "D1" and status.ledger is None
    l1 = next(s for s in status.stages if s.stage == "L1")
    assert (l1.state, l1.steps_done, l1.steps_total) == ("open", 0, 12)
    steps, missing = bringup_steps.record_steps(service, service.config.get(), "L1")
    assert steps == [] and missing[:2] == ["L1.A1", "L1.A2"] and "L1.A8" in missing and "L1.R" not in missing


def test_status_without_steps_yaml_keeps_the_v2_states(world: World) -> None:
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    status = bringup.bringup_status(world.service())
    assert status.ok and status.next_stage == "S0" and status.next_step is None
    assert all(s.steps_total is None and s.state == "open" for s in status.stages)
    assert any("steps.yaml is missing" in note for note in status.notes)
    assert ledger_path(world.service().config.get()).name == "ledger-sim.jsonl"
