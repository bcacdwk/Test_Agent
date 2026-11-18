"""CLI and MCP server coexist (blueprint v2 10.1 row 5.5 AC, 7.1 "Per-transaction VISA; CLI + MCP coexist", 8.1
``visa_loop/``): an MCP server process that has measured and now sits idle on stdio holds neither the VISA session,
nor its exclusive lock, nor the instrument lock, so ``b1500 status`` in a second process succeeds against the same
instrument.

``visa-loop``: both processes run backend visa from ``config/local/`` through the real ``VisaTransport`` over the
visa-loop bus (``serve.py`` injects only the resource manager); a client that keeps the VISA lock (EasyEXPERT, or
v1's server, which held its session from the first call until exit) makes both report ``busy``. ``sim``: the real
``b1500-mcp`` and ``b1500`` console scripts against the shared simulator state.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from b1500_test_agent.session import InstrumentLock
from b1500_test_agent.transport.sim import sim_state_file
from b1500_test_agent.transport.sim.state import load_state_file
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import REPO_ROOT, VisaWorld
from tests.visa_loop.loop import DEFAULT_RESOURCE

TIMEOUT_S = 120.0
IDVG = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
SERVE = ["-m", "tests.visa_loop.serve"]
BIN = Path(sys.executable).parent


def child_env(extra: dict[str, str]) -> dict[str, str]:
    """This process's environment without B1500_* overrides, plus ``extra`` (UTF-8 I/O as on the lab PC)."""
    env = {k: v for k, v in os.environ.items() if k not in (ENV_HOME, ENV_CONFIG_DIR, ENV_DATA_DIR)}
    return {**env, "PYTHONUTF8": "1", **extra}


def payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return json.loads(text)
    raise AssertionError(f"no JSON payload in {result!r}")


def run_cli(command: list[str], env: dict[str, str]) -> tuple[int, dict[str, Any]]:
    done = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                          timeout=TIMEOUT_S, check=False)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        raise AssertionError(f"CLI exit {done.returncode}: {done.stdout}\n{done.stderr}") from None


Tool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def with_mcp_server(command: str, args: list[str], env: dict[str, str],
                    body: Callable[[Tool], Awaitable[None]]) -> None:
    """Start the MCP server process, run ``body(call_tool)`` while it lives, then stop it (stdin EOF)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario() -> None:
        params = StdioServerParameters(command=command, args=args, env=env, cwd=str(REPO_ROOT))
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
            try:
                async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
                    await session.initialize()

                    async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
                        return payload(await session.call_tool(tool, arguments))

                    await body(call)
            except BaseException:
                errlog.seek(0)
                sys.stderr.write("MCP server log:\n" + errlog.read()[-4000:])
                raise

    asyncio.run(asyncio.wait_for(scenario(), TIMEOUT_S))


async def measure(call: Tool, *, confirm: bool) -> dict[str, Any]:
    """validate_plan + run (``run_confirmed_plan`` with the plan's own summary when the tier asks for it)."""
    validation = await call("validate_plan", dict(IDVG))
    assert validation["ok"], validation
    if validation["tier"] == "needs_confirmation":
        assert confirm, validation
        return await call("run_confirmed_plan", {"plan_id": validation["plan_id"], "summary": validation["summary"]})
    return await call("run_plan", {"plan_id": validation["plan_id"]})


def test_cli_status_succeeds_while_the_mcp_server_is_idle_on_visa_loop(world: VisaWorld) -> None:
    bus = world.bus("nmos_basic")  # this process's view: probes the VISA lock and plays the foreign client
    env = child_env(world.env(bus))
    cli = [sys.executable, *SERVE, "cli"]
    instrument_lock = InstrumentLock(world.state_dir, DEFAULT_RESOURCE)

    async def body(call: Tool) -> None:
        first = await call("station_status", {"refresh": True})
        assert (first["status"], first["backend"], first["live"]) == ("ok", "visa", "fresh"), first
        run = await measure(call, confirm=True)
        assert (run["outcome"], run["cleanup_verified"], run["backend"]) == ("completed", "lop", "visa"), run
        # the server is idle now and holds nothing
        assert bus.lock_is_free() and instrument_lock.holder() is None and not instrument_lock.is_held()
        code, status = await asyncio.to_thread(run_cli, [*cli, "status", "--json"], env)
        assert code == 0 and (status["status"], status["live"], status["backend"]) == ("ok", "fresh", "visa"), status
        assert status["outputs_on"] == [] and status["fault"] is None
        code, runs = await asyncio.to_thread(run_cli, [*cli, "runs", "--json"], env)
        assert code == 0 and runs["runs"][0]["run_id"] == run["run_id"]  # the CLI sees the server's run
        # negative control: a client that keeps the VISA lock blocks both processes, which then report busy
        with bus.foreign_lock():
            code, busy = await asyncio.to_thread(run_cli, [*cli, "status", "--json"], env)
            assert code == 1 and (busy["status"], busy["error_code"]) == ("busy", "instrument_busy"), busy
            server_busy = await call("station_status", {"refresh": True})
            assert server_busy["status"] == "busy", server_busy
        again = await call("station_status", {"refresh": True})
        assert again["status"] == "ok", again

    with_mcp_server(sys.executable, [*SERVE, "mcp"], env, body)
    state = load_state_file(bus.state_file)  # one instrument: both processes' commands in one persisted log
    assert state is not None
    assert sum(r.mnemonic == "*IDN?" for r in state.command_log) >= 4
    assert bus.lock_is_free() and instrument_lock.holder() is None


@pytest.mark.skipif(shutil.which("b1500-mcp", path=str(BIN)) is None, reason="console scripts not installed")
def test_real_entry_points_coexist_on_the_simulator(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    env = child_env(world.env())
    server = shutil.which("b1500-mcp", path=str(BIN))
    cli = shutil.which("b1500", path=str(BIN))
    assert server is not None and cli is not None
    instrument_lock = InstrumentLock(world.state_dir, "SIM::nmos_basic")

    async def body(call: Tool) -> None:
        first = await call("station_status", {"refresh": True})
        assert (first["status"], first["backend"], first["simulated"]) == ("ok", "sim", True), first
        run = await measure(call, confirm=False)
        assert run["outcome"] == "completed" and run["cleanup_verified"] == "sim_state", run
        assert instrument_lock.holder() is None and not instrument_lock.is_held()
        code, status = await asyncio.to_thread(run_cli, [cli, "status", "--json"], env)
        assert code == 0 and (status["status"], status["live"]) == ("ok", "fresh"), status
        assert status["outputs_on"] == []
        assert (await call("station_status", {"refresh": True}))["status"] == "ok"

    with_mcp_server(server, [], env, body)
    state = load_state_file(sim_state_file(world.state_dir, "nmos_basic"))
    assert state is not None and sum(r.mnemonic == "*IDN?" for r in state.command_log) >= 4
