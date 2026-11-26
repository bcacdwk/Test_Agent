"""The bring-up rehearsal as a test (v2.1 plan §4.4; WP21.7): the whole step sequence of ``steps.yaml`` walked on the
simulator with a scripted human (``tests/integration/rehearsal.py``), then the failure routing, the resume after a
break and a tampered ledger. The visa-loop walk of S0-L2 is ``tests/visa_loop/test_bringup_sequence_visa.py``.
Marker ``rehearsal`` (CI runs these alone, serially).

- **Whole walk**: every step ``b1500 bringup next`` names, in its order, from D1 through L10 (the deployment and the
  session start included, lab-only and review steps never named), every one recorded ``pass`` on the simulator
  ledger; real ``S...`` runs of every run step's recipes on the stage's devices (the drills end ``cancelled`` and
  ``aborted`` where the step asks for it), the refusals of every record and capture step seen before the step is
  recorded as rehearsed; then the end steps; ``bringup check --all`` without a gap, ``bringup status`` says
  ``rehearsed`` for every stage and never ``signed``; nothing drafted, captured or reviewed.
- **Failure routing**: a zero check whose cleanup DZ/CL writes time out (fault latched) records L1.A4 ``fail``;
  ``next`` stays on it and names runbook ``cleanup-failed-fault``; after the human's verified ``fault clear`` the
  retry passes.
- **Resume**: a new process a day later starts a new session (R1-R4 first, L1.A4 refused until then), then asks the
  human to confirm L1.P1 again before L1.A4.
- **Tamper**: a hand-edited ledger line makes ``b1500 bringup check`` exit 1 and stops ``next`` and ``done``.
"""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent import bringup, bringup_steps
from b1500_test_agent.adapters.cli import app
from b1500_test_agent.bringup_ledger import effective_kind, ledger_path, read_ledger
from b1500_test_agent.bringup_verify import StepArgs
from b1500_test_agent.models.validation import STAGE_FILES_DIR, STAGES, STEPS_FILE
from b1500_test_agent.service import B1500Admin
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.rehearsal import HUMAN, OWNER, STEPS, SimRehearsal, _stuck_cleanup

pytestmark = pytest.mark.rehearsal


@pytest.fixture
def rehearsal(world: World) -> SimRehearsal:
    """The world with the committed stage files and ``steps.yaml`` (the step modules read them from the root)."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    shutil.copy2(REPO_ROOT.joinpath(*STEPS_FILE), world.root.joinpath(*STEPS_FILE))
    return SimRehearsal(world)


def rehearsable(specs: list) -> list[str]:
    return [s.id for s in specs if effective_kind(s, "sim") is not None and not s.is_review]


def files_under(root: Path, *parts: str) -> list[str]:
    folder = root.joinpath(*parts)
    return sorted(p.relative_to(root).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []


# -- the whole sequence ------------------------------------------------------------------------------------------------


def test_the_whole_sequence_is_rehearsed_on_the_simulator(rehearsal: SimRehearsal, world: World) -> None:
    walked = rehearsal.walk()
    stages = [s for specs in STEPS.stages.values() for s in rehearsable(specs)]
    assert walked == [*rehearsable(STEPS.deployment), *rehearsable(STEPS.session_start), *stages]
    assert len(walked) == 176 and len(stages) == 165
    # the session ends: E1 (safe_shutdown, station clean) and E3 (the ledger re-verified); then a new session
    assert rehearsal.walk() == []  # nothing left but the end steps (no review awaits on the simulator)
    rehearsal.step("E1")
    shown = bringup_steps.next_step(rehearsal.service)
    assert shown.step is not None and shown.step.id == "E3"  # E2, E4, E5 are lab only
    rehearsal.step("E3")
    fresh = bringup_steps.next_step(rehearsal.service)
    assert fresh.step is not None and fresh.step.id == "R1"

    entries = read_ledger(ledger_path(rehearsal.service.config.get())).entries
    assert [e.step for e in entries] == [*walked, "E1", "E3"]
    assert {e.verdict for e in entries} == {"pass"} and {e.backend for e in entries} == {"sim"}
    runs = [r.ref for e in entries for r in e.evidence.runs]
    assert runs and all(r.startswith("S") for r in runs)
    run_steps = [s for s in walked if (spec := STEPS.get(s)) is not None and effective_kind(spec, "sim") == "run"]
    assert len(run_steps) == 53 and all(rehearsal.runs[s] for s in run_steps)
    outcomes = {s: [rehearsal.facts[r][1] for r in rehearsal.runs[s]] for s in ("L1.A6", "L9.A3", "L9.A5")}
    assert outcomes == {"L1.A6": ["cancelled"], "L9.A3": ["cancelled"], "L9.A5": ["aborted"]}
    recipes = {rehearsal.facts[r][0] for r in runs}
    required = {r for s in run_steps if (spec := STEPS.get(s)) is not None for r in spec.required_recipes}
    assert required <= recipes
    refused = [line.split(":")[0] for line in rehearsal.refusals]
    refusal_steps = [s for s in walked if (spec := STEPS.get(s)) is not None and spec.rehearsal == "refusal"]
    assert refused == refusal_steps and len(refused) == 12
    assert all("simulator" in line or "backend sim" in line for line in rehearsal.refusals), rehearsal.refusals

    checked = bringup_steps.check(rehearsal.service, all_stages=True)
    assert checked.ok and checked.scope == "all" and checked.gaps == [], [g.reason for g in checked.gaps]
    assert checked.verified == len(entries)
    status = bringup.bringup_status(rehearsal.service)
    assert {s.stage: s.state for s in status.stages} == dict.fromkeys(STAGES, "rehearsed")
    assert all(s.steps_done == s.steps_total for s in status.stages)
    for parts in (("work", "bringup", "records"), ("work", "bringup", "fixtures"), ("validation",)):
        assert files_under(world.root, *parts) == []


# -- failure routing ---------------------------------------------------------------------------------------------------


def test_a_failed_step_stays_next_with_its_runbook_until_the_human_cleared_the_fault(
        rehearsal: SimRehearsal) -> None:
    rehearsal.walk(until="L1.A4")
    service = rehearsal.service
    rehearsal.land("lab_station", ("lab_station_stuck", _stuck_cleanup))
    plan = service.validate_plan(recipe_id="system.zero_check", params={}, pin_map="open-smus",
                                 dut_profile="open-circuit")
    assert plan.plan_id is not None and plan.tier == "ok", plan.message
    stuck = service.run_plan(plan.plan_id)
    assert stuck.run_id is not None and stuck.cleanup_verified == "unverified", stuck.message
    failed = bringup_steps.done(service, "L1.A4", StepArgs(runs=(stuck.run_id,)))
    assert failed.recorded and not failed.ok and failed.entry is not None and failed.entry.verdict == "fail"
    assert "cleanup verified 'unverified', fault latched True" in failed.entry.reason
    assert failed.next_steps[0].startswith('stop: safe_shutdown("L1.A4 failed: ')
    assert "load skill b1500-debug (runbooks cleanup-failed-fault, current-too-high)" in failed.next_steps[1]
    assert "cleared only by the human" in failed.next_steps[2]
    stays = bringup_steps.next_step(service)
    assert stays.step is not None and (stays.step.id, stays.step.state) == ("L1.A4", "failed")
    assert stays.step.on_fail == ["cleanup-failed-fault", "current-too-high"]
    assert stays.step.last_reason == failed.entry.reason and stays.message.startswith("SIMULATED stays on the failed")
    blocked = service.validate_plan(recipe_id="system.zero_check", params={}, pin_map="open-smus",
                                    dut_profile="open-circuit")
    assert blocked.tier == "blocked" and "R-FAULT-01" in blocked.message
    # the human: the stuck writes fixed (a clean landing), then the fault cleared after a verified shutdown
    rehearsal.land("lab_station")
    cleared = B1500Admin(service).fault_clear(by=OWNER)
    assert cleared.ok and cleared.cleared, cleared.message
    retried = rehearsal.step("L1.A4")
    assert retried.entry is not None and retried.entry.verdict == "pass"
    assert retried.next is not None and retried.next.id == "L1.A5"
    entries = read_ledger(ledger_path(service.config.get())).entries
    assert [(e.step, e.verdict) for e in entries[-2:]] == [("L1.A4", "fail"), ("L1.A4", "pass")]
    assert bringup_steps.check(service).ok  # the failed entry stays in the chain; the latest one passes


# -- resume after a break ----------------------------------------------------------------------------------------------


def test_a_new_process_a_day_later_starts_a_session_and_asks_to_confirm_again(rehearsal: SimRehearsal,
                                                                              world: World) -> None:
    rehearsal.walk(until="L1.A4")
    world.clock.offset += timedelta(days=1)
    rehearsal.new_process()
    service = rehearsal.service
    shown = bringup_steps.next_step(service)
    assert shown.step is not None and shown.step.id == "R1"
    assert any("a new session: the start steps first" in note for note in shown.notes)
    refused = bringup_steps.done(service, "L1.A4", StepArgs(runs=()))
    assert refused.status == "refused" and "this session starts with R1, R2, R3, R4" in refused.message
    assert rehearsal.walk(until="L1.P1") == ["R1", "R2", "R3", "R4"]
    again = bringup_steps.next_step(service)
    assert again.step is not None and (again.step.id, again.step.state) == ("L1.P1", "reconfirm")
    assert again.reconfirm == ["L1.P1"] and again.message.startswith("SIMULATED confirm again after the break L1.P1")
    rehearsal.step("L1.P1")
    following = bringup_steps.next_step(service)
    assert following.step is not None and following.step.id == "L1.A4" and following.reconfirm == []
    rehearsal.step("L1.A4")
    entries = read_ledger(ledger_path(service.config.get())).entries
    assert [e.step for e in entries[-6:]] == ["R1", "R2", "R3", "R4", "L1.P1", "L1.A4"]
    assert entries[-6].ts - entries[-7].ts > timedelta(hours=23)


# -- tamper ------------------------------------------------------------------------------------------------------------


def test_a_tampered_ledger_fails_the_check_and_stops_the_walk(rehearsal: SimRehearsal, world: World) -> None:
    rehearsal.walk(until="S0.A3")
    env = world.env()
    runner = CliRunner()
    clean = runner.invoke(app, ["bringup", "check"], env=env)
    assert clean.exit_code == 0, clean.output
    assert "SIMULATED ledger" in clean.output and "no gap" in clean.output
    path = ledger_path(rehearsal.service.config.get())
    lines = path.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if '"step":"S0.P4"' in line)
    quote = '"quote":"' + HUMAN["human"] + '"'
    assert quote in lines[index]
    lines[index] = lines[index].replace(quote, '"quote":"done, and the shield box was open"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tampered = runner.invoke(app, ["bringup", "check"], env=env)
    assert tampered.exit_code == 1, tampered.output
    assert f"gap: -: hash chain: line {index + 1} (S0.P4): its content does not match its sha256" in tampered.output
    shown = bringup_steps.next_step(rehearsal.service)
    assert not shown.ok and shown.status == "error" and "is damaged" in shown.message
    refused = bringup_steps.done(rehearsal.service, "S0.A3", rehearsal.args(STEPS.get("S0.A3")))  # type: ignore[arg-type]
    assert refused.status == "refused" and not refused.recorded and "is damaged" in refused.message
