"""Safety matrix of asynchronous runs (blueprint v2 2.6, 8.1 ``safety/`` "async" rows; WP5.6): cancel at a boundary
from a second process, server shutdown during a run (stdin EOF, SIGTERM), Ctrl-C of a foreground CLI run, kill →
in-flight recovery, busy contention between processes, an abort file written by another process. After every exit
the global invariant holds (``assert_async_invariant``): verified cleanup with the simulator safe (DZ and CL after the
last source command) or the fault latch with ``cleanup_unverified``; no lock, marker or abort request left.

The second processes are the real ``b1500``/``b1500-mcp`` console scripts (or ``multiprocessing`` spawn children)
against the same temporary config and data directories; the simulator runs ``timing: scaled(f)`` so the runs are
observable for a few seconds.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.session import AbortFile, InstrumentLock, read_inflight
from tests.integration.async_helpers import (
    IDVD_LONG,
    SCENARIO,
    assert_async_invariant,
    idvd_long,
    manifest_of,
    progress_of,
    run_dir,
    run_events,
    sim_state_safe,
    timed_world,
    wait_for,
)
from tests.integration.helpers import World, make_world

BIN = Path(sys.executable).parent
TIMEOUT_S = 120.0
SPAWN = multiprocessing.get_context("spawn")
needs_scripts = pytest.mark.skipif(shutil.which("b1500", path=str(BIN)) is None
                                   or shutil.which("b1500-mcp", path=str(BIN)) is None,
                                   reason="console scripts not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX signals")


@pytest.fixture
def world(tmp_path: Path) -> Any:
    w = make_world(tmp_path)
    yield w
    for service in w.services:
        service.close()
    for executor in w.executors:
        executor.close()


def child_env(world: World) -> dict[str, str]:
    """This process's environment plus the world's B1500_* overrides (UTF-8 I/O as on the lab PC)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("B1500_")}
    return {**env, "PYTHONUTF8": "1", **world.env()}


def cli(world: World, *args: str, timeout_s: float = TIMEOUT_S) -> tuple[int, dict[str, Any]]:
    """Run ``b1500 <args> --json`` in a second process; returns (exit code, result JSON)."""
    command = [shutil.which("b1500", path=str(BIN)) or "b1500", *args, "--json"]
    done = subprocess.run(command, env=child_env(world), capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout_s, check=False)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        raise AssertionError(f"exit {done.returncode}: {done.stdout}\n{done.stderr}") from None


def write_abort_request(state_dir: str, reason: str) -> None:
    """Child-process target (spawn): write an abort request as another process would."""
    AbortFile(Path(state_dir)).request(reason, adapter="cli")


def checkpoints_after(world: World, run_id: str, since: AuditEvent) -> int:
    """Progress checkpoints the run passed after the ``abort_requested`` event ``since``."""
    return sum(1 for e in run_events(world, run_id)
               if e.ev == "checkpoint" and e.data and e.data.get("label") == "progress" and e.ts > since.ts)


# -- cancel from a second process -------------------------------------------------------------------------------------


@needs_scripts
def test_b1500_shutdown_from_a_second_process_cancels_within_one_checkpoint(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    service = world.service(adapter="mcp")
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    run_id = started.run_id or ""
    wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=30)
    code, result = cli(world, "shutdown", "--reason", "second terminal")
    assert code == 0 and result["ok"] and result["cancelled_run"] == run_id, result
    assert result["cleanup"]["verified"] == "sim_state"
    manifest = assert_async_invariant(world, run_id)
    assert manifest.outcome == "cancelled" and "second terminal" in manifest.message
    [requested] = [e for e in world.audit_events() if e.ev == "abort_requested"]
    assert requested.data and requested.data["target"] == run_id and requested.data["by"] == "cli"
    assert checkpoints_after(world, run_id, requested) <= 1  # stopped within one checkpoint
    final = service.follow_run(run_id)
    assert final is not None and final.outcome == "cancelled"


def test_an_abort_file_written_by_another_process_cancels_the_run(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    service = world.service()
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    run_id = started.run_id or ""
    wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=30)
    child = SPAWN.Process(target=write_abort_request, args=(str(world.state_dir), "spawned writer"))
    child.start()
    child.join(60)
    assert child.exitcode == 0
    final = service.follow_run(run_id)
    assert final is not None and final.outcome == "cancelled" and "spawned writer" in final.message
    assert_async_invariant(world, run_id)


# -- busy contention ------------------------------------------------------------------------------------------------


@needs_scripts
def test_busy_contention_between_processes(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    service = world.service(adapter="mcp")
    started = service.run_plan(service.validate_plan(**IDVD_LONG).plan_id or "")
    run_id = started.run_id or ""
    wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=30)
    t0 = time.monotonic()
    code, status = cli(world, "status")
    assert code == 1 and (status["status"], status["error_code"]) == ("busy", "instrument_busy"), status
    assert status["active_run"]["run_id"] == run_id and status["active_run"]["pid"] == os.getpid()
    assert f"busy: run {run_id}" in status["message"]
    code, runs = cli(world, "runs", "--status", "running")
    assert code == 0 and [r["run_id"] for r in runs["runs"]] == [run_id]
    code, shown = cli(world, "show", run_id, "--include", "progress", "--include", "summary")
    assert code == 0 and shown["run"]["outcome"] == "running" and shown["progress"]["state"] == "running"
    other = world.service(lock_timeout_s=0.2)  # another executor on the same instrument (lock = another process)
    refused = other.run_plan(other.validate_plan(**idvd_long(vg_points=2)).plan_id or "")
    assert (refused.status, refused.error_code) == ("busy", "instrument_busy")
    assert f"busy: run {run_id}" in refused.message
    assert time.monotonic() - t0 < 30
    assert service.stop_runs("test end", wait_s=30)
    assert_async_invariant(world, run_id)


# -- kill during a run → in-flight recovery ----------------------------------------------------------------------------


@needs_scripts
def test_kill_during_a_run_and_the_next_transaction_recovers(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    plan_id = world.service().validate_plan(**IDVD_LONG).plan_id or ""
    command = [shutil.which("b1500", path=str(BIN)) or "b1500", "run", plan_id]
    with tempfile.TemporaryFile("w+", encoding="utf-8") as out:
        child = subprocess.Popen(command, env=child_env(world), stdout=out, stderr=subprocess.STDOUT)
        try:
            run_id = wait_for(lambda: next((p.name for p in world.runs_dir.rglob("S*") if p.is_dir()), None),
                              timeout_s=60)
            wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 2, timeout_s=60)
        finally:
            child.kill()  # SIGKILL / TerminateProcess: no cleanup, no finalize
            child.wait(30)
    # The OS releases the lock when the killed process is gone. On Windows ``b1500.exe`` is a console-script launcher:
    # its python.exe child dies with it through a job object, but after the launcher (WP6.5: once on
    # windows-latest the lock was still held right after ``wait``), so wait for that before reading what it left.
    wait_for(lambda: InstrumentLock(world.state_dir, f"SIM::{SCENARIO}").holder() is None, timeout_s=30)
    marker = read_inflight(world.state_dir / "inflight.json")
    assert marker is not None and marker.run == run_id and marker.adapter == "cli"
    assert manifest_of(world, run_id) is None
    assert sim_state_safe(world) != []  # the residual: outputs stay on until the next transaction
    service = world.service()
    status = service.station_status(refresh=False)
    assert status.inflight_marker and status.active_run is None
    result = service.safe_shutdown("after a kill")
    assert result.ok and result.cleanup is not None and result.cleanup.verified == "sim_state"
    recovered = [e for e in world.audit_events() if e.ev == "recovery_cleanup"]
    assert recovered and recovered[0].data and recovered[0].data["previous_run"] == run_id
    manifest = manifest_of(world, run_id)
    assert manifest is not None and manifest.outcome == "aborted" and manifest.cleanup is not None
    assert manifest.cleanup.verified == "sim_state"
    progress = progress_of(world, run_id)
    assert progress is not None and progress.state == "failed" and progress.done >= 2
    assert sim_state_safe(world) == []
    assert not (world.state_dir / "inflight.json").exists()


# -- MCP server shutdown during a run --------------------------------------------------------------------------------


def _with_server(world: World, body: Any) -> str:
    """Start ``b1500-mcp`` on stdio, run ``body(call, process_ids)`` and close stdin; returns the server's log."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = shutil.which("b1500-mcp", path=str(BIN)) or "b1500-mcp"

    async def scenario(errlog: Any) -> None:
        params = StdioServerParameters(command=server, args=[], env=child_env(world), cwd=str(world.root))
        async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
                result = await session.call_tool(tool, arguments)
                return json.loads(result.content[0].text)  # type: ignore[union-attr]

            await body(call)

    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
        asyncio.run(asyncio.wait_for(scenario(errlog), TIMEOUT_S))
        errlog.seek(0)
        return errlog.read()


@needs_scripts
def test_mcp_server_stdin_eof_during_a_run_cancels_it_with_a_verified_cleanup(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    holder: dict[str, str] = {}

    async def body(call: Any) -> None:
        plan = await call("validate_plan", dict(IDVD_LONG))
        started = await call("run_plan", {"plan_id": plan["plan_id"]})
        assert started["outcome"] == "running", started
        holder["run"] = started["run_id"]
        for _ in range(200):
            progress = (await call("get_run", {"run_id": holder["run"], "include": ["progress"]}))["progress"]
            if progress and progress["done"] >= 1:
                break
            await asyncio.sleep(0.05)
        # leaving the block closes stdin: the server's shutdown hook cancels the run

    log = _with_server(world, body)
    run_id = holder["run"]
    manifest = wait_for(lambda: manifest_of(world, run_id), timeout_s=60)
    assert manifest.outcome == "cancelled" and "MCP server stopping (stdin closed)" in manifest.message, log
    assert_async_invariant(world, run_id)
    assert "cancelling the running run" in log


@needs_scripts
@posix_only
def test_sigterm_to_the_mcp_server_cancels_the_run(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    plan_id = world.service().validate_plan(**IDVD_LONG).plan_id or ""
    server = shutil.which("b1500-mcp", path=str(BIN)) or "b1500-mcp"
    child = subprocess.Popen([server], env=child_env(world), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        assert child.stdin is not None and child.stdout is not None
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "run_plan", "arguments": {"plan_id": plan_id}}},
        ]
        for message in messages:
            child.stdin.write(json.dumps(message) + "\n")
            child.stdin.flush()
        replies = [json.loads(child.stdout.readline()) for _ in range(2)]
        started = json.loads(replies[1]["result"]["content"][0]["text"])
        assert started["outcome"] == "running", started
        run_id = started["run_id"]
        wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=30)
        child.send_signal(signal.SIGTERM)
        child.wait(60)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(30)
    assert child.returncode == 128 + signal.SIGTERM
    manifest = manifest_of(world, run_id)
    assert manifest is not None and manifest.outcome == "cancelled" and "SIGTERM" in manifest.message
    assert_async_invariant(world, run_id)


# -- Ctrl-C of a foreground CLI run ------------------------------------------------------------------------------------


@needs_scripts
@posix_only
def test_ctrl_c_cancels_a_foreground_cli_run_after_its_cleanup(world: World) -> None:
    timed_world(world, timing="scaled(0.02)")
    plan_id = world.service().validate_plan(**IDVD_LONG).plan_id or ""
    command = [shutil.which("b1500", path=str(BIN)) or "b1500", "run", plan_id, "--json"]
    child = subprocess.Popen(command, env=child_env(world), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8")
    try:
        run_id = wait_for(lambda: next((p.name for p in world.runs_dir.rglob("S*") if p.is_dir()), None),
                          timeout_s=60)
        wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=60)
        child.send_signal(signal.SIGINT)
        stdout, stderr = child.communicate(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(30)
    assert child.returncode == 1, stderr
    result = json.loads(stdout)
    assert (result["outcome"], result["error_code"], result["cleanup_verified"]) == ("cancelled", "run_cancelled",
                                                                                     "sim_state")
    assert "Ctrl-C: cancelling the run" in stderr and "runs asynchronously" in stderr
    manifest = assert_async_invariant(world, run_id)
    assert "operator Ctrl-C (cli)" in manifest.message


def test_run_dir_helper_matches_the_archive_layout(world: World) -> None:
    timed_world(world)
    service = world.service()
    result = service.run_plan(service.validate_plan(**idvd_long(vg_points=2)).plan_id or "")
    assert (run_dir(world, result.run_id or "") / "manifest.json").is_file()
