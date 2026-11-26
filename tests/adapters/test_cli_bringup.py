"""`b1500 bringup status | capture | record | next | done | check` on the simulator (blueprint v2 7.1; WP6.3; v2.1
plan §4.1, WP21.5; CLI only, no MCP tool).

A simulator station is a rehearsal: ``status`` works and says so, ``record`` and ``capture`` refuse simulator runs
(``S…``) before reading anything and refuse to draft on backend sim at all; nothing is written under
``work/bringup/records/`` or ``work/bringup/fixtures/``. Each refusal is audited (``tool_call`` ``bringup_record`` /
``bringup_capture``, status ``refused``), which is what acceptance scenario S17 grades. The step verbs: ``next``
prints D1 on an empty simulator ledger and the batch that can follow; ``done`` records the human's words and who ran
it (``human`` without a harness marker, ``human_via_agent`` with one) and exits 1 on a refusal or a recorded failure;
several step ids record a batch (WP21.14: one line per entry, the next batch); ``check`` exits 1 on a gap.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from b1500_test_agent.adapters.cli import TOOL_COMMANDS, app
from b1500_test_agent.adapters.cli import bringup as cli_bringup
from b1500_test_agent.devtools.skills.commands import command_problems, named_commands
from b1500_test_agent.models.validation import (
    STAGE_FILES_DIR,
    STEPS_FILE,
    BringupStatus,
    LedgerCheck,
    NextStep,
    RecordDraft,
    StepDone,
)
from b1500_test_agent.service import TOOL_NAMES
from tests.integration.helpers import REPO_ROOT, World

runner = CliRunner()


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args))


def as_json(result: Result) -> dict[str, Any]:
    return json.loads(result.stdout)


def _run_id(world: World) -> str:
    service = world.service()
    plan = service.validate_plan(recipe_id="basic.contact_resistor", params={"v_start": 0, "v_stop": 0},
                                 pin_map="resistor-2t", dut_profile="resistor-generic")
    assert plan.tier == "ok" and plan.plan_id is not None, plan.message
    run = service.run_plan(plan.plan_id)
    assert run.run_id is not None and run.run_id.startswith("S")
    return run.run_id


def _tool_calls(world: World, tool: str) -> list[dict[str, Any]]:
    return [e.data for e in world.audit_events() if e.ev == "tool_call" and e.data and e.data.get("tool") == tool]


def test_status_on_the_simulator(cli_world: World) -> None:
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), cli_world.root.joinpath(*STAGE_FILES_DIR))
    result = invoke("bringup", "status")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("[SIMULATED] ok: SIMULATED next stage S0: Physical prerequisites")
    assert "-> S0   open" in result.stdout and "no_stage_file" not in result.stdout  # every stage (L8: WP10.8)
    assert "next: simulator: a rehearsal; no record is ever drafted from simulator runs" in result.stdout
    status = BringupStatus.model_validate(as_json(invoke("bringup", "status", "--json")))
    assert status.next_stage == "S0" and status.simulated and len(status.stages) == 12
    l1 = next(s for s in status.stages if s.stage == "L1")
    assert [r.recipe_id for r in l1.records] == ["system.self_test", "system.self_cal", None]  # WGFMU ones: L8
    assert _tool_calls(cli_world, "bringup_status")[-1]["status"] == "ok"


def test_record_refuses_a_simulator_run(cli_world: World) -> None:
    run_id = _run_id(cli_world)
    result = invoke("bringup", "record", "L1", "--run", run_id)
    assert result.exit_code == 1
    assert f"refused: {run_id} is a simulator run" in result.stdout
    assert "never write a record, fixture or validation/hw/ file by hand" in result.stdout
    draft = RecordDraft.model_validate(as_json(invoke("bringup", "record", "L1", "--run", run_id, "--json")))
    assert draft.status == "refused" and draft.error_code == "invalid_input" and draft.record is None
    assert not (cli_world.root / "work" / "bringup" / "records").exists()
    calls = _tool_calls(cli_world, "bringup_record")
    assert len(calls) == 2 and all(c["status"] == "refused" and c["run_id"] == run_id for c in calls)


def test_record_refuses_a_simulator_station_even_without_runs(cli_world: World) -> None:
    result = invoke("bringup", "record", "S0", "--operator", "owner")
    assert result.exit_code == 1 and "this station runs backend sim" in result.stdout
    assert not (cli_world.root / "work" / "bringup" / "records").exists()


def test_capture_refuses_simulator_runs_and_simulated_probes(cli_world: World) -> None:
    run_id = _run_id(cli_world)
    result = invoke("bringup", "capture", run_id)
    assert result.exit_code == 1 and "a simulator run never becomes one" in result.stdout
    cli_world.use_scenario("lab_station")
    assert invoke("doctor", "--probe").exit_code == 0
    probe = invoke("bringup", "capture", "probe")
    assert probe.exit_code == 1 and "is a SIMULATED probe" in probe.stdout
    assert not (cli_world.root / "work" / "bringup" / "fixtures").exists()
    assert {c["status"] for c in _tool_calls(cli_world, "bringup_capture")} == {"refused"}


def test_usage_errors(cli_world: World) -> None:
    assert invoke("bringup", "capture").exit_code == 2
    assert invoke("bringup", "record").exit_code == 2
    help_text = invoke("bringup", "--help").stdout
    for command in ("status", "capture", "record", "propose-station", "next", "done", "check"):
        assert command in help_text
    assert invoke("bringup", "done").exit_code == 2
    assert invoke("bringup", "check", "S0", "--all").exit_code == 2


def test_bringup_commands_stay_cli_only() -> None:
    assert all(command[0] != "bringup" for command in TOOL_COMMANDS.values())
    assert len(TOOL_NAMES) == 10 and not any(n.startswith("bringup") for n in TOOL_NAMES)


# -- next | done | check (v2.1 plan §4.1) ------------------------------------------------------------------------------

AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "CODEX_MANAGED_BY_NPM")


@pytest.fixture
def steps_cli(cli_world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """The CLI world with the stage files and ``steps.yaml``, no harness marker and a passing doctor."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), cli_world.root.joinpath(*STAGE_FILES_DIR))
    shutil.copy2(REPO_ROOT.joinpath(*STEPS_FILE), cli_world.root.joinpath(*STEPS_FILE))
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli_bringup, "doctor_lines", lambda: [("python", "PASS", "3.12")])
    return cli_world


def test_next_prints_d1_on_the_simulator(steps_cli: World) -> None:
    result = invoke("bringup", "next")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("[SIMULATED] ok: SIMULATED next step D1 (D, human, verify confirm): Git for")
    assert 'done: uv run b1500 bringup done D1 --human "<the human\'s own words>" --by <NAME>' in result.stdout
    assert "steps passed: D 0/7, S0 0/14" in result.stdout
    model = NextStep.model_validate(as_json(invoke("bringup", "next", "--json")))
    assert model.step is not None and model.step.id == "D1" and model.simulated
    assert not (steps_cli.data / "state" / "bringup").exists()
    for tokens in named_commands(f"`{model.step.done}`"):
        assert command_problems(tokens) == [], tokens


def test_done_records_the_human_words_and_who_ran_it(steps_cli: World, monkeypatch: pytest.MonkeyPatch) -> None:
    refused = invoke("bringup", "done", "D1")
    assert refused.exit_code == 1 and "records the human's own words" in refused.stdout
    mine = invoke("bringup", "done", "D1", "--human", "Git, uv and Python are installed", "--by", "Owner", "--json")
    assert mine.exit_code == 0, mine.output
    entry = StepDone.model_validate(as_json(mine)).entry
    assert entry is not None and entry.actor == "human" and entry.evidence.human is not None
    assert entry.evidence.human.quote == "Git, uv and Python are installed"
    monkeypatch.setenv("CLAUDECODE", "1")
    relayed = invoke("bringup", "done", "D4", "--human", "both signed in", "--by", "Owner", "--json")
    assert relayed.exit_code == 0 and StepDone.model_validate(as_json(relayed)).entry.actor == "human_via_agent"
    assert invoke("bringup", "done", "D6", "--human", "cloned", "--by", "Owner").exit_code == 0
    monkeypatch.setattr(cli_bringup, "doctor_lines", lambda: [("config", "FAIL", "broken")])
    failed = invoke("bringup", "done", "D7")
    assert failed.exit_code == 1 and "D7 FAIL recorded: doctor: FAIL config" in failed.stdout
    assert "recorded: #4 D7 fail (doctor, agent)" in failed.stdout
    assert 'next: stop: safe_shutdown("D7 failed' in failed.stdout
    monkeypatch.setattr(cli_bringup, "doctor_lines", lambda: [("config", "PASS", "valid")])
    passed = invoke("bringup", "done", "D7")
    assert passed.exit_code == 0 and "recorded: #5 D7 pass (doctor, agent)" in passed.stdout
    assert "next:" in passed.stdout and "step D8 (D, human, verify doctor, open)" in passed.stdout
    calls = _tool_calls(steps_cli, "bringup_done")
    assert [c["status"] for c in calls] == ["refused", "ok", "ok", "ok", "error", "ok"]


def test_done_records_a_batch_and_next_prints_the_batch_line(steps_cli: World,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """WP21.14: ``next`` prints the steps one ``done`` call can record with the next step and that call's line; ``done``
    with several ids records one entry per step (the evidence printed once when it repeats) and prints the next
    batch; the audit event names the steps."""
    shown = invoke("bringup", "next")
    assert shown.exit_code == 0, shown.output
    assert "  batch: one `done` call can record it with the 6 step(s) after it, in order" in shown.stdout
    assert "    D7 (both, verify doctor): `uv sync --frozen`;" in shown.stdout
    assert ('  batch done: uv run b1500 bringup done D1 D4 D6 D7 D8 D9 D11 --human "<the human\'s own words>" --by '
            "<NAME>") in shown.stdout
    for tokens in named_commands(f"`{NextStep.model_validate(as_json(invoke('bringup', 'next', '--json'))).step}`"):
        assert command_problems(tokens) == [], tokens
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli_bringup, "doctor_lines", lambda: [("python", "PASS", "3.12"),
                                                              ("harness files", "PASS", "wired"),
                                                              ("harness versions", "PASS", "= validated")])
    result = invoke("bringup", "done", "D1", "D4", "D6", "D7", "D8", "D9", "D11", "--human",
                    "Deployment done, every step", "--by", "Owner")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("[SIMULATED] ok: SIMULATED 7 steps pass: D1 (the human's words (Owner)); D4")
    for line in ("recorded: #1 D1 pass (confirm, human_via_agent)", "recorded: #4 D7 pass (doctor, agent)",
                 "recorded: #7 D11 pass (confirm, human_via_agent)", "step R1 (R, agent, verify doctor, open)",
                 "  batch done: uv run b1500 bringup done R1 R2 R3 R4 --observe reconfirm=<VALUE> --human"):
        assert line in result.stdout, line
    # the evidence is printed when it differs from the entry before: D1, D8 (with its doctor line), D9
    assert result.stdout.count('evidence: "Deployment done, every step" (Owner)') == 3
    model = StepDone.model_validate(as_json(invoke("bringup", "done", "R1", "R2", "--json")))
    assert model.ok and [e.step for e in model.entries] == ["R1", "R2"] and model.entry == model.entries[-1]
    refused = invoke("bringup", "done", "R3", "R4", "--observe", "reconfirm=none")
    assert refused.exit_code == 1 and "step R3 records the human's own words" in refused.stdout
    calls = _tool_calls(steps_cli, "bringup_done")
    assert [(c["status"], c.get("steps")) for c in calls] == [("ok", "D1 D4 D6 D7 D8 D9 D11"), ("ok", "R1 R2"),
                                                               ("refused", None)]


def test_check_exits_1_on_a_gap(steps_cli: World) -> None:
    assert invoke("bringup", "done", "D1", "--human", "done", "--by", "Owner").exit_code == 0
    clean = invoke("bringup", "check")
    assert clean.exit_code == 0 and "1 entries, 1 re-verified, no gap (scope recorded)" in clean.stdout
    stage = invoke("bringup", "check", "S0", "--json")
    assert stage.exit_code == 1
    model = LedgerCheck.model_validate(as_json(stage))
    assert model.scope == "S0" and [g.step for g in model.gaps][:2] == ["S0.A1", "S0.A2"]
    ledger = steps_cli.data / "state" / "bringup" / "ledger-sim.jsonl"
    ledger.write_text(ledger.read_text(encoding="utf-8").replace('"by":"Owner"', '"by":"Someone"'), encoding="utf-8")
    tampered = invoke("bringup", "check")
    assert tampered.exit_code == 1 and "gap: -: hash chain: line 1 (D1)" in tampered.stdout
    assert invoke("bringup", "next").exit_code == 1


def test_status_shows_the_steps_per_stage(steps_cli: World) -> None:
    assert invoke("bringup", "done", "D1", "--human", "done", "--by", "Owner").exit_code == 0
    result = invoke("bringup", "status")
    assert result.exit_code == 0
    assert "-> S0   open          steps 0/14   Physical prerequisites" in result.stdout
    assert "next step: D4 (ledger " in result.stdout
    status = BringupStatus.model_validate(as_json(invoke("bringup", "status", "--json")))
    assert status.next_step == "D4" and status.ledger is not None and status.ledger.endswith("ledger-sim.jsonl")


def test_done_passes_one_fixture_folder_per_capture(steps_cli: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """v2.1 (WP21.6): ``--fixtures`` is repeatable (one folder per captured run or probe record); the CLI hands every
    folder and run to the step verifier in order."""
    seen: dict[str, Any] = {}

    def fake_done(service: Any, steps: Any, args: Any, **_kwargs: Any) -> StepDone:
        seen.update(steps=steps, runs=args.runs, fixtures=args.fixtures)
        return StepDone(ok=False, status="refused", backend="sim", simulated=True, message="seen")

    monkeypatch.setattr(cli_bringup.bringup_steps, "done", fake_done)
    result = invoke("bringup", "done", "L2.A10", "--run", "H20261126T080000Z-0a0b", "--fixtures",
                    "work/bringup/fixtures/H20261126T080000Z-0a0b", "--run", "H20261126T080100Z-0c0d",
                    "--fixtures", "work/bringup/fixtures/H20261126T080100Z-0c0d")
    assert result.exit_code == 1 and seen["steps"] == ("L2.A10",)
    assert seen["runs"] == ("H20261126T080000Z-0a0b", "H20261126T080100Z-0c0d")
    assert seen["fixtures"] == ("work/bringup/fixtures/H20261126T080000Z-0a0b",
                                "work/bringup/fixtures/H20261126T080100Z-0c0d")
