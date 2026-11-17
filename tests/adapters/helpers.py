"""Helpers of the adapter tests: MCP servers over a test world and calls through the FastMCP in-memory client."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp import Client, FastMCP

from b1500_test_agent.adapters.mcp_server import create_server
from tests.integration.helpers import World


def mcp_server(world: World, **kwargs: Any) -> FastMCP:
    """The b1500 server over a service of ``world`` (adapter ``mcp``)."""
    return create_server(world.service(adapter="mcp"), **kwargs)


async def _list_tools(server: FastMCP) -> list[Any]:
    async with Client(server) as client:
        return list(await client.list_tools())


def list_tools(server: FastMCP) -> list[Any]:
    return asyncio.run(_list_tools(server))


async def _call(server: FastMCP, calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    async with Client(server) as client:
        for name, args in calls:
            result = await client.call_tool(name, args, raise_on_error=False)
            assert not result.is_error, result.content
            out.append(json.loads(result.content[0].text))
    return out


def call_tools(server: FastMCP, calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Call tools in order through the in-memory client; returns each result's JSON text, parsed."""
    return asyncio.run(_call(server, calls))


def call_tool(server: FastMCP, name: str, **args: Any) -> dict[str, Any]:
    return call_tools(server, [(name, args)])[0]
