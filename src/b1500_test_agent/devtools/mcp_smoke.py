"""``b1500 dev mcp-smoke --config <.mcp.json | .codex/config.toml>``: start the MCP server exactly as a harness
config describes it and check it over stdio (blueprint 5.3, WP1.9 acceptance).

Steps: parse the config (Codex ``[mcp_servers.<name>]`` TOML or Claude Code ``mcpServers.<name>`` JSON, with
``${VAR}`` / ``${VAR:-default}`` expansion as Claude Code does), launch ``command`` + ``args`` with the configured
``env`` and ``cwd`` (Claude Code configs have no ``cwd``: the config file's folder, i.e. the project root), run the
MCP handshake, list the tools (exactly the ten of blueprint 5.1) and call ``station_status`` with
``refresh=false`` (no instrument I/O), which must report the expected backend (``sim`` by default).

The server gets a minimal environment (the MCP SDK's default variables plus the configured ``env``) and, unless
``data_dir`` is given, a fresh temporary ``B1500_DATA_DIR`` that is removed afterwards, so a smoke test never
touches ``data/``.

``--async`` (blueprint v2 2.6, WP5.6 AC, ATV-24) also proves that the stdio server keeps serving tool calls while an
asynchronous run works on its worker thread. The server gets a temporary ``B1500_CONFIG_DIR`` with the committed
example configuration and the simulator scenario ``smoke_async`` (``nmos_basic`` with ``timing: scaled(0.02)``, so
the ~9 min plan takes ~11 s of wall time); then: ``validate_plan`` of an Id-Vd family (21 gate steps of 40 points at
long integration: asynchronous, tier ok) → ``run_plan`` answers ``running`` within ``RUNNING_WITHIN_S`` →
``station_status`` answers ``busy`` naming the run → ``get_run include=[progress]`` advances → ``list_runs
status=running`` lists it → ``safe_shutdown`` cancels it with a verified cleanup → ``get_run`` shows ``cancelled``.
No confirmation is ever given: a plan that needs one is a finding.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, find_repo_root
from b1500_test_agent.service import TOOL_NAMES

DEFAULT_SERVER = "b1500"
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_TOOL_TIMEOUT_S = 120.0
LOG_TAIL_LINES = 15
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

ASYNC_SCENARIO = "smoke_async"
ASYNC_TIMING = "scaled(0.02)"
ASYNC_REQUEST: dict[str, Any] = {
    "recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic",
    "params": {"vd_points": 40, "vg_start": 0.5, "vg_stop": 1.5, "vg_points": 21, "integration": "long"},
    "label": "mcp-smoke --async",
}  # fmt: skip
"""An Id-Vd family estimated at ~9 min (21 segments of ~27 s): asynchronous, tier ok on the committed examples."""
RUNNING_WITHIN_S = 1.0
"""``run_plan`` of an asynchronous plan must answer ``running`` this fast (blueprint v2 10.1 row 5.6 AC)."""
PROGRESS_WAIT_S = 2.0
"""Wall time between the two progress reads (several segments at the scaled timing)."""
EXAMPLE_FILES = {
    "policy.yaml": "config/policy.example.yaml", "station.yaml": "config/station.example.yaml",
    "pinmaps/mosfet-4t.yaml": "config/pinmaps/mosfet-4t.example.yaml",
    "duts/nmos-generic.yaml": "config/duts/nmos-generic.example.yaml",
}  # fmt: skip


class SmokeConfigError(ValueError):
    """The config file cannot be read or has no usable stdio server entry."""


class ServerLaunch(BaseModel):
    """A stdio MCP server launch as a harness config describes it."""

    config: str
    server: str
    command: str
    args: list[str]
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S
    tool_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S


class AsyncSmoke(BaseModel):
    """What the ``--async`` part saw (see the module docstring)."""

    plan_id: str | None = None
    tier: str | None = None
    mode: str | None = None
    est_s: float | None = None
    run_id: str | None = None
    running_after_s: float | None = None
    busy_status: str | None = None
    progress: list[str] = Field(default_factory=list)
    listed_running: bool = False
    shutdown_status: str | None = None
    cancelled_run: str | None = None
    outcome: str | None = None
    cleanup_verified: str | None = None
    progress_state: str | None = None


class SmokeReport(BaseModel):
    """Outcome of one smoke test; ``ok`` iff the ten tools were listed and the backend matched (and, with
    ``--async``, every asynchronous-run check passed)."""

    ok: bool
    launch: ServerLaunch
    server_info: str | None = None
    tools: list[str] = Field(default_factory=list)
    backend: str | None = None
    simulated: bool | None = None
    status: str | None = None
    elapsed_s: float = 0.0
    problems: list[str] = Field(default_factory=list)
    server_log_tail: list[str] = Field(default_factory=list)
    async_run: AsyncSmoke | None = None


def _expand(value: str, environ: Mapping[str, str]) -> str:
    """Claude Code ``.mcp.json`` expansion: ``${VAR}`` and ``${VAR:-default}`` (unset VAR without default → '')."""
    return _VAR.sub(lambda m: environ.get(m.group(1)) or (m.group(2) or ""), value)


def _strings(value: Any, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SmokeConfigError(f"{what} must be a list of strings")
    return list(value)


def _env(value: Any, what: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise SmokeConfigError(f"{what} must be a table of strings")
    return {str(k): v for k, v in value.items()}


def load_launch(config: Path, server: str = DEFAULT_SERVER, environ: Mapping[str, str] | None = None) -> ServerLaunch:
    """Read the launch of ``server`` from a Codex TOML or Claude Code JSON config file."""
    env = os.environ if environ is None else environ
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as exc:
        raise SmokeConfigError(f"cannot read {config}: {exc}") from exc
    if config.suffix == ".toml":
        try:
            entry = tomllib.loads(text).get("mcp_servers", {}).get(server)
        except tomllib.TOMLDecodeError as exc:
            raise SmokeConfigError(f"{config}: not valid TOML ({exc})") from exc
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
            raise SmokeConfigError(f"{config}: no [mcp_servers.{server}] with a command")
        return ServerLaunch(
            config=config.as_posix(), server=server, command=entry["command"],
            args=_strings(entry.get("args", []), "args"), env=_env(entry.get("env"), "env"),
            cwd=entry.get("cwd"),
            startup_timeout_s=float(entry.get("startup_timeout_sec", DEFAULT_STARTUP_TIMEOUT_S)),
            tool_timeout_s=float(entry.get("tool_timeout_sec", DEFAULT_TOOL_TIMEOUT_S)),
        )  # fmt: skip
    if config.suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise SmokeConfigError(f"{config}: not valid JSON ({exc})") from exc
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        entry = servers.get(server) if isinstance(servers, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
            raise SmokeConfigError(f"{config}: no mcpServers.{server} with a command")
        if entry.get("type", "stdio") != "stdio":
            raise SmokeConfigError(f"{config}: mcpServers.{server} is not a stdio server")
        return ServerLaunch(
            config=config.as_posix(), server=server, command=_expand(entry["command"], env),
            args=[_expand(a, env) for a in _strings(entry.get("args", []), "args")],
            env={k: _expand(v, env) for k, v in _env(entry.get("env"), "env").items()},
            cwd=config.resolve().parent.as_posix(),
        )  # fmt: skip
    raise SmokeConfigError(f"{config}: expected a .toml (Codex) or .json (Claude Code) config")


def _payload(result: Any) -> dict[str, Any]:
    """The JSON object a tool returned (structured content, else the first text block)."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def write_async_config(config_dir: Path, repo_root: Path) -> None:
    """The ``--async`` server configuration: committed examples, sim backend, scenario ``smoke_async``."""
    for target, source in EXAMPLE_FILES.items():
        path = config_dir / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((repo_root / source).read_text(encoding="utf-8"), encoding="utf-8")
    settings = yaml.safe_load((repo_root / "config/settings.example.yaml").read_text(encoding="utf-8"))
    settings["backend"] = "sim"
    settings.setdefault("sim", {})["scenario"] = ASYNC_SCENARIO
    (config_dir / "settings.yaml").write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    scenario = yaml.safe_load((repo_root / "config/sim/scenarios/nmos_basic.yaml").read_text(encoding="utf-8"))
    scenario.update({"description": "nmos_basic with scaled timing (mcp-smoke --async)", "timing": ASYNC_TIMING,
                     "faults": None})
    path = config_dir / "sim" / "scenarios" / f"{ASYNC_SCENARIO}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")


async def _exercise_async(session: Any, launch: ServerLaunch, report: SmokeReport) -> None:
    """The ``--async`` checks (module docstring); every deviation is a problem, nothing is ever confirmed."""
    run = report.async_run = AsyncSmoke()

    async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.wait_for(session.call_tool(tool, arguments), launch.tool_timeout_s)
        return _payload(result)

    plan = await call("validate_plan", dict(ASYNC_REQUEST))
    resolved = plan.get("resolved") or {}
    run.plan_id, run.tier, run.mode, run.est_s = plan.get("plan_id"), plan.get("tier"), resolved.get("mode"), \
        resolved.get("est_s")
    if run.tier != "ok" or run.mode != "async" or not run.plan_id:
        report.problems.append(f"async plan is not an asynchronous plan of tier ok: tier {run.tier}, mode "
                               f"{run.mode}: {plan.get('message')}")
        return
    started = time.monotonic()
    result = await call("run_plan", {"plan_id": run.plan_id})
    run.running_after_s = round(time.monotonic() - started, 3)
    run.run_id = result.get("run_id")
    if result.get("outcome") != "running" or not run.run_id:
        report.problems.append(f"run_plan did not answer running: {result.get('outcome')}: {result.get('message')}")
        return
    if run.running_after_s > RUNNING_WITHIN_S:
        report.problems.append(f"run_plan answered running after {run.running_after_s} s (> {RUNNING_WITHIN_S} s)")
    status = await call("station_status", {"refresh": True})
    run.busy_status = status.get("status")
    active = status.get("active_run") or {}
    if run.busy_status != "busy" or active.get("run_id") != run.run_id:
        report.problems.append(f"station_status during the run is {run.busy_status} (active run "
                               f"{active.get('run_id')}), expected busy naming {run.run_id}")
    first = await call("get_run", {"run_id": run.run_id, "include": ["progress"]})
    await asyncio.sleep(PROGRESS_WAIT_S)
    second = await call("get_run", {"run_id": run.run_id, "include": ["progress"]})
    done = []
    for sample in (first, second):
        progress = sample.get("progress") or {}
        run.progress.append(f"{progress.get('state')} {progress.get('done')}/{progress.get('total')}")
        done.append(progress.get("done"))
    if not all(isinstance(d, int) for d in done) or done[1] <= done[0]:
        report.problems.append(f"get_run progress did not advance: {run.progress}")
    listed = await call("list_runs", {"status": "running"})
    run.listed_running = any(r.get("run_id") == run.run_id for r in listed.get("runs") or [])
    if not run.listed_running:
        report.problems.append(f"list_runs status=running does not list {run.run_id}")
    stop = await call("safe_shutdown", {"reason": "mcp-smoke --async"})
    run.shutdown_status, run.cancelled_run = stop.get("status"), stop.get("cancelled_run")
    if run.shutdown_status != "ok" or run.cancelled_run != run.run_id:
        report.problems.append(f"safe_shutdown did not cancel {run.run_id}: {stop.get('status')}: "
                               f"{stop.get('message')}")
    final = await call("get_run", {"run_id": run.run_id, "include": ["summary", "progress"]})
    brief = final.get("run") or {}
    run.outcome, run.cleanup_verified = brief.get("outcome"), brief.get("cleanup_verified")
    run.progress_state = (final.get("progress") or {}).get("state")
    if run.outcome != "cancelled" or run.cleanup_verified not in ("sim_state", "lop"):
        report.problems.append(f"after safe_shutdown the run is {run.outcome} with cleanup {run.cleanup_verified}, "
                               "expected cancelled with a verified cleanup")
    if run.progress_state != "cancelled":
        report.problems.append(f"final progress state {run.progress_state}, expected cancelled")


async def _exercise(launch: ServerLaunch, env: dict[str, str], errlog: Any, report: SmokeReport, *,
                    async_check: bool = False) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=launch.command, args=launch.args, env=env, cwd=launch.cwd)
    async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
        init = await asyncio.wait_for(session.initialize(), launch.startup_timeout_s)
        info = init.server_info
        report.server_info = f"{info.name} {info.version}"
        listed = await asyncio.wait_for(session.list_tools(), launch.startup_timeout_s)
        report.tools = [tool.name for tool in listed.tools]
        result = await asyncio.wait_for(session.call_tool("station_status", {"refresh": False}), launch.tool_timeout_s)
        payload = _payload(result)
        report.backend = payload.get("backend")
        report.simulated = payload.get("simulated")
        report.status = payload.get("status")
        if getattr(result, "is_error", False):
            report.problems.append(f"station_status returned an error: {payload or result}")
        if async_check and report.backend == "sim":
            await _exercise_async(session, launch, report)


def _tail(handle: Any) -> list[str]:
    handle.seek(0)
    lines = [line.rstrip() for line in handle.read().splitlines() if line.strip()]
    return lines[-LOG_TAIL_LINES:]


def run_smoke(launch: ServerLaunch, *, data_dir: Path | None = None, expect_backend: str = "sim",
              async_check: bool = False, repo_root: Path | None = None) -> SmokeReport:
    """Launch the server of ``launch`` and check it (see the module docstring); never raises for a failing server.
    ``async_check`` adds the asynchronous-run checks (simulator only; config from ``repo_root``'s examples)."""
    report = SmokeReport(ok=False, launch=launch)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="b1500-smoke-") as scratch:
        data = data_dir if data_dir is not None else Path(scratch) / "data"
        env = {**launch.env, ENV_DATA_DIR: str(data)}
        if async_check:
            config_dir = Path(scratch) / "config"
            write_async_config(config_dir, repo_root or find_repo_root())
            env[ENV_CONFIG_DIR] = str(config_dir)
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
            try:
                asyncio.run(_exercise(launch, env, errlog, report, async_check=async_check))
            except TimeoutError:
                report.problems.append("timed out (startup or tool call)")
            except Exception as exc:  # noqa: BLE001 - any failure of the launched server is the finding
                report.problems.append(f"server failed: {type(exc).__name__}: {exc}")
            report.server_log_tail = _tail(errlog)
    report.elapsed_s = round(time.monotonic() - started, 2)
    if report.server_info is not None:
        missing = sorted(set(TOOL_NAMES) - set(report.tools))
        extra = sorted(set(report.tools) - set(TOOL_NAMES))
        if missing or extra or len(report.tools) != len(TOOL_NAMES):
            report.problems.append(f"expected exactly the {len(TOOL_NAMES)} tools; missing {missing}, extra {extra}")
        if report.backend != expect_backend:
            report.problems.append(f"station_status backend is {report.backend!r}, expected {expect_backend!r}")
        if async_check and report.async_run is None:
            report.problems.append("the asynchronous-run checks did not run (backend is not sim)")
    report.ok = report.server_info is not None and not report.problems
    return report


def format_report(report: SmokeReport) -> str:
    launch = report.launch
    verdict = "ok" if report.ok else "FAIL"
    head = f"mcp-smoke: {verdict} ({launch.config}, server {launch.server}, {report.elapsed_s:g} s)"
    cwd = f"  (cwd {launch.cwd})" if launch.cwd else ""
    lines = [head, f"  launch: {launch.command} {' '.join(launch.args)}{cwd}"]
    if report.server_info:
        lines.append(f"  server: {report.server_info}")
    if report.tools:
        lines.append(f"  tools ({len(report.tools)}): {', '.join(report.tools)}")
    if report.backend is not None:
        lines.append(f"  station_status: backend: {report.backend}, simulated: {report.simulated}, "
                     f"status: {report.status}")
    if report.async_run is not None:
        run = report.async_run
        lines.append(f"  async: plan {run.plan_id} ({run.mode}, ~{run.est_s} s) -> run {run.run_id} running after "
                     f"{run.running_after_s} s; station_status {run.busy_status}; progress {', '.join(run.progress)}; "
                     f"listed running {run.listed_running}; safe_shutdown {run.shutdown_status} -> {run.outcome}, "
                     f"cleanup {run.cleanup_verified}")
    lines += [f"  problem: {p}" for p in report.problems]
    if not report.ok:
        lines += [f"  server log: {line}" for line in report.server_log_tail]
    return "\n".join(lines)
