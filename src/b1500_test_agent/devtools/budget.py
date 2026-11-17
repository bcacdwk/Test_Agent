"""Token budget of an MCP tool surface (blueprint §5.2).

The counter builds a FastMCP app in-process, lists its tools through the in-memory client and serializes
exactly the fields a client receives for the budget (``name``, ``description``, ``inputSchema``,
``outputSchema``, ``annotations``) as compact JSON, one document per tool. Tokens are counted with the
``tiktoken`` encoding ``o200k_base``; ``chars / 4`` is reported as a cross-check. When the encoding cannot be
loaded (for example offline without a cached BPE file) the counter falls back to ``ceil(chars / 3.5)`` and
emits a warning.

``fastmcp`` is imported lazily so that importing this module (and the CLI) stays cheap.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mcp.types import Tool

ENCODING_NAME = "o200k_base"
FALLBACK_CHARS_PER_TOKEN = 3.5
CROSS_CHECK_CHARS_PER_TOKEN = 4
BUDGET_FIELDS: tuple[str, ...] = ("name", "description", "inputSchema", "outputSchema", "annotations")


class AppSpecError(ValueError):
    """Raised when a ``module:attribute`` app spec cannot be resolved to a FastMCP app."""


@dataclass(frozen=True)
class TokenCounter:
    """A named token-counting function; ``warning`` is set when a fallback method is in use."""

    method: str
    count: Callable[[str], int]
    warning: str | None = None


class ToolBudget(BaseModel):
    """Budget of one tool as serialized for a client."""

    name: str
    tokens: int = Field(ge=0)
    chars: int = Field(ge=0)
    chars_div4: int = Field(ge=0, description="Cross-check estimate: ceil(chars / 4).")


class BudgetReport(BaseModel):
    """Per-tool and total token budget of one MCP tool surface."""

    app: str = Field(description="Label of the measured app (usually its module:attribute spec).")
    method: str = Field(description="Counting method, e.g. 'tiktoken:o200k_base' or 'chars/3.5'.")
    warning: str | None = None
    serialized_fields: list[str] = Field(default_factory=lambda: list(BUDGET_FIELDS))
    tool_count: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    total_chars_div4: int = Field(ge=0)
    tools: list[ToolBudget]


def load_counter(encoding_name: str = ENCODING_NAME) -> TokenCounter:
    """Return a tiktoken counter for ``encoding_name``, or the chars/3.5 fallback with a warning."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(encoding_name)
    # ImportError: package missing; OSError: offline download (requests errors derive from it) or unreadable
    # cache; ValueError: unknown encoding name or a cached BPE file failing its hash check.
    except (ImportError, OSError, ValueError) as exc:
        message = (
            f"tiktoken encoding {encoding_name!r} unavailable ({type(exc).__name__}: {exc}); "
            f"falling back to chars/{FALLBACK_CHARS_PER_TOKEN}"
        )
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        return fallback_counter(warning=message)

    def count(text: str) -> int:
        # Special-token text inside descriptions is counted as ordinary text instead of raising.
        return len(encoding.encode(text, disallowed_special=()))

    return TokenCounter(method=f"tiktoken:{encoding_name}", count=count)


def fallback_counter(warning: str | None = None) -> TokenCounter:
    """Return the offline estimate ``ceil(chars / 3.5)``."""
    return TokenCounter(
        method=f"chars/{FALLBACK_CHARS_PER_TOKEN}",
        count=lambda text: math.ceil(len(text) / FALLBACK_CHARS_PER_TOKEN),
        warning=warning,
    )


def serialize_tool(tool: Tool) -> str:
    """Serialize the budgeted fields of one listed tool as compact JSON (absent fields are omitted)."""
    payload = tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    selected = {key: payload[key] for key in BUDGET_FIELDS if key in payload}
    return json.dumps(selected, ensure_ascii=False, separators=(",", ":"))


def measure_tools(tools: Sequence[Tool], counter: TokenCounter | None = None, label: str = "") -> BudgetReport:
    """Count tokens per tool and in total for already-listed tools; rows keep the listing order."""
    active = counter if counter is not None else load_counter()
    rows: list[ToolBudget] = []
    for tool in tools:
        text = serialize_tool(tool)
        rows.append(
            ToolBudget(
                name=tool.name,
                tokens=active.count(text),
                chars=len(text),
                chars_div4=math.ceil(len(text) / CROSS_CHECK_CHARS_PER_TOKEN),
            )
        )
    total_chars = sum(row.chars for row in rows)
    return BudgetReport(
        app=label,
        method=active.method,
        warning=active.warning,
        tool_count=len(rows),
        total_tokens=sum(row.tokens for row in rows),
        total_chars=total_chars,
        total_chars_div4=sum(row.chars_div4 for row in rows),
        tools=rows,
    )


async def list_app_tools(app: Any) -> list[Tool]:
    """List the tools of a FastMCP app through the in-memory client (what an MCP client receives)."""
    from fastmcp import Client

    async with Client(app) as client:
        return list(await client.list_tools())


def measure_app(app: Any, counter: TokenCounter | None = None, label: str = "") -> BudgetReport:
    """Build the budget report of a FastMCP app; must be called outside a running event loop."""
    tools = asyncio.run(list_app_tools(app))
    return measure_tools(tools, counter=counter, label=label)


def load_app(spec: str) -> Any:
    """Resolve ``package.module:attribute`` to a FastMCP app; a zero-argument factory is called once."""
    from fastmcp import FastMCP

    module_name, sep, attribute = spec.partition(":")
    if not sep or not module_name or not attribute:
        raise AppSpecError(f"app spec must look like 'package.module:attribute', got {spec!r}")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AppSpecError(f"cannot import module {module_name!r} ({exc})") from exc
    try:
        target = getattr(module, attribute)
    except AttributeError as exc:
        raise AppSpecError(f"module {module_name!r} has no attribute {attribute!r}") from exc
    if not isinstance(target, FastMCP) and callable(target):
        target = target()
    if not isinstance(target, FastMCP):
        raise AppSpecError(f"{spec!r} is not a FastMCP app (got {type(target).__name__})")
    return target


def format_report(report: BudgetReport, top: int | None = None) -> str:
    """Render a plain-text table, largest tools first; ``top`` limits the listed rows, not the totals."""
    rows = sorted(report.tools, key=lambda row: (-row.tokens, row.name))
    shown = rows if top is None else rows[:top]
    lines = [
        f"app: {report.app or '(unnamed)'}",
        f"counter: {report.method} (cross-check chars/{CROSS_CHECK_CHARS_PER_TOKEN})",
        f"fields: {', '.join(report.serialized_fields)}",
        f"{'tokens':>8} {'chars/4':>8} {'chars':>8}  tool",
    ]
    lines.extend(f"{row.tokens:>8} {row.chars_div4:>8} {row.chars:>8}  {row.name}" for row in shown)
    if len(shown) < len(rows):
        lines.append(f"{'':>8} {'':>8} {'':>8}  ... {len(rows) - len(shown)} more tools")
    lines.append(
        f"{report.total_tokens:>8} {report.total_chars_div4:>8} {report.total_chars:>8}  "
        f"TOTAL ({report.tool_count} tools)"
    )
    return "\n".join(lines)
