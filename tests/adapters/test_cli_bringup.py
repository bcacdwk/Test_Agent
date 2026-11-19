"""`b1500 bringup status | capture | record` on the simulator (blueprint v2 7.1; WP6.3; CLI only, no MCP tool).

A simulator station is a rehearsal: ``status`` works and says so, ``record`` and ``capture`` refuse simulator runs
(``S…``) before reading anything and refuse to draft on backend sim at all; nothing is written under
``work/bringup/records/`` or ``work/bringup/fixtures/``. Each refusal is audited (``tool_call`` ``bringup_record`` /
``bringup_capture``, status ``refused``), which is what acceptance scenario S17 grades.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

from typer.testing import CliRunner, Result

from b1500_test_agent.adapters.cli import TOOL_COMMANDS, app
from b1500_test_agent.models.validation import STAGE_FILES_DIR, BringupStatus, RecordDraft
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
    assert "-> S0   open" in result.stdout and "L5   no_stage_file" in result.stdout
    assert "next: simulator: a rehearsal; no record is ever drafted from simulator runs" in result.stdout
    status = BringupStatus.model_validate(as_json(invoke("bringup", "status", "--json")))
    assert status.next_stage == "S0" and status.simulated and len(status.stages) == 12
    l1 = next(s for s in status.stages if s.stage == "L1")
    assert [r.recipe_id for r in l1.records] == ["system.self_test", "system.self_cal", None]
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
    for command in ("status", "capture", "record", "propose-station"):
        assert command in help_text


def test_bringup_commands_stay_cli_only() -> None:
    assert all(command[0] != "bringup" for command in TOOL_COMMANDS.values())
    assert len(TOOL_NAMES) == 10 and not any(n.startswith("bringup") for n in TOOL_NAMES)
