"""Asynchronous runs through the adapters (blueprint v2 2.6, 2.9, 8.1 ``adapters/``; WP5.6 AC):

- the in-memory FastMCP test of the AC: a 20-min simulator plan answers ``running`` in under 1 s, ``station_status``
  answers ``busy``, ``get_run`` progress advances, ``b1500 shutdown`` from a second process cancels it within one
  checkpoint with a verified cleanup;
- the ``running`` outcome schema, the additive tool arguments, the tool-schema budget (target 2,000 tokens);
- the CLI keeps an asynchronous run in the foreground with a progress line and cancels it on Ctrl-C;
- ``b1500 dev mcp-smoke --async`` over stdio (ATV-24: FastMCP serves tool calls while a worker thread runs).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.adapters.cli import core as cli
from b1500_test_agent.adapters.mcp_server import create_server, shutdown_hook
from b1500_test_agent.devtools import budget, mcp_smoke
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.service import TOOL_NAMES
from tests.adapters.helpers import call_tool, mcp_server
from tests.integration.async_helpers import (
    IDVD_LONG,
    assert_async_invariant,
    idvd_long,
    manifest_of,
    progress_of,
    run_events,
    stepped_long,
    timed_world,
    wait_for,
)
from tests.integration.helpers import World

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(sys.executable).parent
TARGET_TOKENS = 2000
runner = CliRunner()


def payload(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


def child_env(world: World) -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("B1500_")}
    return {**env, "PYTHONUTF8": "1", **world.env()}


# -- the AC ----------------------------------------------------------------------------------------------------------


@pytest.mark.wall_clock
@pytest.mark.skipif(shutil.which("b1500", path=str(BIN)) is None, reason="console scripts not installed")
def test_twenty_minute_plan_in_memory_running_busy_progress_and_shutdown_from_a_second_process(
        world: World) -> None:
    timed_world(world, timing="scaled(0.02)")  # 20 min of virtual time = ~25 s of wall time if never cancelled
    server = mcp_server(world)
    shutdown = [shutil.which("b1500", path=str(BIN)) or "b1500", "shutdown", "--reason", "AC second process",
                "--json"]

    async def scenario() -> dict[str, Any]:
        async with Client(server) as client:
            plan = payload(await client.call_tool("validate_plan", stepped_long(46)))
            assert plan["tier"] == "needs_confirmation" and plan["confirm_reasons"] == ["long_run"], plan
            assert plan["resolved"]["mode"] == "async" and 1150 < plan["resolved"]["est_s"] < 1300  # ~20 min
            t0 = time.monotonic()
            started = payload(await client.call_tool("run_confirmed_plan", {"plan_id": plan["plan_id"],
                                                                            "summary": plan["summary"]}))
            running_after = time.monotonic() - t0
            assert started["outcome"] == "running" and running_after < 1.0, (running_after, started)
            assert started["ok"] and started["eta_s"] == pytest.approx(plan["resolved"]["est_s"])
            run_id = started["run_id"]
            busy = payload(await client.call_tool("station_status", {"refresh": True}))
            assert (busy["status"], busy["active_run"]["run_id"]) == ("busy", run_id), busy
            first = payload(await client.call_tool("get_run", {"run_id": run_id, "include": ["progress"]}))
            for _ in range(200):
                later = payload(await client.call_tool("get_run", {"run_id": run_id, "include": ["progress"]}))
                if later["progress"]["done"] > first["progress"]["done"]:
                    break
                await asyncio.sleep(0.05)
            assert later["progress"]["done"] > first["progress"]["done"], (first, later)
            assert later["progress"]["total"] == 46
            listed = payload(await client.call_tool("list_runs", {"status": "running"}))
            assert [r["run_id"] for r in listed["runs"]] == [run_id]
            done = await asyncio.to_thread(subprocess.run, shutdown, env=child_env(world), capture_output=True,
                                           text=True, encoding="utf-8", timeout=120, check=False)
            stopped = json.loads(done.stdout)
            assert done.returncode == 0 and stopped["cancelled_run"] == run_id, (done.stdout, done.stderr)
            final = payload(await client.call_tool("get_run", {"run_id": run_id,
                                                               "include": ["summary", "progress", "data"]}))
            idle = payload(await client.call_tool("station_status", {"refresh": True}))
            return {"run_id": run_id, "final": final, "idle": idle, "stopped": stopped}

    out = asyncio.run(scenario())
    run_id, final = out["run_id"], out["final"]
    assert final["run"]["outcome"] == "cancelled" and final["run"]["cleanup_verified"] == "sim_state"
    assert final["progress"]["state"] == "cancelled" and final["progress"]["done"] < 46
    assert "PARTIAL" in final["data"]["note"]
    assert out["stopped"]["cleanup"]["verified"] == "sim_state" and out["idle"]["status"] == "ok"
    manifest = assert_async_invariant(world, run_id)
    assert manifest.outcome == "cancelled" and manifest.confirmed_via == "run_confirmed_plan"
    [requested] = [e for e in world.audit_events() if e.ev == "abort_requested"]
    after = [e for e in run_events(world, run_id) if e.ev == "checkpoint" and e.data
             and e.data.get("label") == "progress" and e.ts > requested.ts]
    assert len(after) <= 1  # within one checkpoint


# -- schema, arguments, budget -----------------------------------------------------------------------------------------


def test_running_outcome_schema_and_additive_arguments(world: World) -> None:
    timed_world(world, timing="scaled(0.01)")
    server = mcp_server(world)
    plan = call_tool(server, "validate_plan", **IDVD_LONG)
    started = call_tool(server, "run_plan", plan_id=plan["plan_id"])
    summary = RunSummary.model_validate(started)
    assert (summary.ok, summary.status, summary.outcome, summary.error_code) == (True, "ok", "running", None)
    assert summary.run_id and summary.eta_s and summary.eta_s > 300
    assert summary.next_steps and "get_run" in summary.next_steps[0] and "safe_shutdown" in summary.next_steps[0]
    status = call_tool(server, "station_status", refresh=False)
    assert status["active_run"]["mode"] == "async" and status["status"] == "busy"
    detail = call_tool(server, "get_run", run_id=summary.run_id, include=["progress"])
    assert detail["progress"]["state"] in ("running", "completed")
    stopped = call_tool(server, "safe_shutdown", reason="schema test")
    assert stopped["ok"] and stopped["cancelled_run"] == summary.run_id
    assert_async_invariant(world, summary.run_id)


def test_tool_text_names_the_async_additions(world: World) -> None:
    tools = {t.name: t for t in asyncio.run(_list(world))}
    get_run_include = tools["get_run"].input_schema["properties"]["include"]
    assert "progress" in json.dumps(get_run_include)
    assert "running" in tools["run_plan"].description and "eta_s" in tools["run_plan"].description
    assert "running" in tools["list_runs"].description
    assert "Cancel the running run" in tools["safe_shutdown"].description
    assert "busy" in tools["station_status"].description


async def _list(world: World) -> list[Any]:
    async with Client(mcp_server(world)) as client:
        return list(await client.list_tools())


def test_tool_schema_budget_meets_the_v2_target(world: World) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        report = budget.measure_app(mcp_server(world), label="b1500")
    assert [row.name for row in report.tools] == list(TOOL_NAMES)
    assert report.total_tokens <= TARGET_TOKENS, report.total_tokens
    assert max(row.tokens for row in report.tools) <= 700


# -- shutdown hook ---------------------------------------------------------------------------------------------------


def test_shutdown_hook_cancels_and_waits(world: World) -> None:
    timed_world(world, timing="scaled(0.01)")
    service = world.service(adapter="mcp")
    create_server(service, require_user_interaction=True)
    stop = shutdown_hook(service, wait_s=10)
    assert stop("idle") is True  # nothing running: nothing to do
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    assert stop("stdin closed") is True
    manifest = assert_async_invariant(world, started.run_id or "")
    assert manifest.outcome == "cancelled" and "MCP server stopping (stdin closed)" in manifest.message


# -- CLI ---------------------------------------------------------------------------------------------------------------


def test_cli_run_of_an_async_plan_stays_in_the_foreground_with_progress(world: World,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world)
    service = world.service()
    monkeypatch.setattr(cli, "make_service", lambda: service)
    plan_id = service.validate_plan(**IDVD_LONG).plan_id or ""
    result = runner.invoke(app, ["run", plan_id, "--json"])
    assert result.exit_code == 0, result.output
    final = RunSummary.model_validate_json(result.stdout[result.stdout.index("{"):])
    assert final.outcome == "completed" and final.cleanup_verified == "sim_state"
    assert "runs asynchronously" in result.stderr and "/21 sweep" in result.stderr
    assert_async_invariant(world, final.run_id or "")


def test_cli_ctrl_c_cancels_and_waits_for_the_cleanup(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world, timing="scaled(0.01)")
    service = world.service()
    monkeypatch.setattr(cli, "make_service", lambda: service)
    calls: list[str] = []
    original = service.follow_run

    def follow(run_id: str, **kwargs: Any) -> RunSummary | None:
        calls.append(run_id)
        if len(calls) == 1:
            wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=30)
            raise KeyboardInterrupt  # the operator presses Ctrl-C while the run goes on
        return original(run_id, **kwargs)

    monkeypatch.setattr(service, "follow_run", follow)
    plan_id = service.validate_plan(**IDVD_LONG).plan_id or ""
    result = runner.invoke(app, ["run", plan_id])
    assert result.exit_code == 1, result.output
    assert "Ctrl-C: cancelling the run" in result.stderr
    assert "outcome: cancelled" in result.stdout and "cleanup: sim_state" in result.stdout
    assert "partial data:" in result.stdout
    run_id = calls[0]
    manifest = manifest_of(world, run_id)
    assert manifest is not None and "operator Ctrl-C (cli)" in manifest.message
    assert_async_invariant(world, run_id)


def test_cli_status_and_show_describe_the_running_run(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world, timing="scaled(0.01)")
    service = world.service()
    monkeypatch.setattr(cli, "make_service", lambda: service)
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    run_id = started.run_id or ""
    wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=30)
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 1 and f"active run: {run_id} (async) mosfet.idvd" in status.stdout
    shown = runner.invoke(app, ["show", run_id, "--include", "progress", "--include", "summary"])
    assert shown.exit_code == 0 and "progress: running" in shown.stdout and "outcome: running" in shown.stdout
    plan = runner.invoke(app, ["plan", "mosfet.idvd", "--pin-map", "mosfet-4t", "--dut", "nmos-generic",
                               "-p", "vd_points=40", "-p", "vg_points=21", "-p", "integration=long"])
    assert "(asynchronous)" in plan.stdout
    stopped = runner.invoke(app, ["shutdown", "--reason", "cli test"])
    assert stopped.exit_code == 0 and f"cancelled run: {run_id}" in stopped.stdout
    assert_async_invariant(world, run_id)


def test_cli_sync_run_output_is_unchanged(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    timed_world(world)
    service = world.service()
    monkeypatch.setattr(cli, "make_service", lambda: service)
    plan_id = service.validate_plan(**idvd_long(vg_points=2)).plan_id or ""
    result = runner.invoke(app, ["run", plan_id])
    assert result.exit_code == 0 and "runs asynchronously" not in result.stderr


# -- mcp-smoke --async (stdio) -----------------------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_mcp_smoke_async_over_stdio(tmp_path: Path) -> None:
    """The AC ``uv run b1500 dev mcp-smoke --async``: the server started as Claude Code would start it serves tool
    calls while the asynchronous run works on its worker thread (ATV-24)."""
    result = runner.invoke(app, ["dev", "mcp-smoke", "--async", "--json"])
    assert result.exit_code == 0, result.output
    report = mcp_smoke.SmokeReport.model_validate_json(result.stdout)
    run = report.async_run
    assert report.ok and run is not None, report.problems
    assert run.mode == "async" and run.running_after_s is not None and run.running_after_s < 1.0
    assert run.busy_status == "busy" and run.listed_running and run.outcome == "cancelled"
    assert run.cleanup_verified == "sim_state" and run.progress_state == "cancelled"


def test_mcp_smoke_async_config_is_hermetic(tmp_path: Path) -> None:
    mcp_smoke.write_async_config(tmp_path, ROOT)
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.yaml")} == {
        "settings.yaml", "policy.yaml", "station.yaml", "pinmaps/mosfet-4t.yaml", "duts/nmos-generic.yaml",
        "sim/scenarios/smoke_async.yaml"}
    assert "scaled(0.02)" in (tmp_path / "sim/scenarios/smoke_async.yaml").read_text(encoding="utf-8")
