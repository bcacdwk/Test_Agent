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

from pydantic import BaseModel, Field

from b1500_test_agent.paths import ENV_DATA_DIR
from b1500_test_agent.service import TOOL_NAMES

DEFAULT_SERVER = "b1500"
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_TOOL_TIMEOUT_S = 120.0
LOG_TAIL_LINES = 15
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


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


class SmokeReport(BaseModel):
    """Outcome of one smoke test; ``ok`` iff the ten tools were listed and the backend matched."""

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


async def _exercise(launch: ServerLaunch, env: dict[str, str], errlog: Any, report: SmokeReport) -> None:
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


def _tail(handle: Any) -> list[str]:
    handle.seek(0)
    lines = [line.rstrip() for line in handle.read().splitlines() if line.strip()]
    return lines[-LOG_TAIL_LINES:]


def run_smoke(launch: ServerLaunch, *, data_dir: Path | None = None, expect_backend: str = "sim") -> SmokeReport:
    """Launch the server of ``launch`` and check it (see the module docstring); never raises for a failing server."""
    report = SmokeReport(ok=False, launch=launch)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="b1500-smoke-") as scratch:
        data = data_dir if data_dir is not None else Path(scratch) / "data"
        env = {**launch.env, ENV_DATA_DIR: str(data)}
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
            try:
                asyncio.run(_exercise(launch, env, errlog, report))
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
    lines += [f"  problem: {p}" for p in report.problems]
    if not report.ok:
        lines += [f"  server log: {line}" for line in report.server_log_tail]
    return "\n".join(lines)
