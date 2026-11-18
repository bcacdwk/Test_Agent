"""``B1500Service``: the only API the adapters (MCP server, CLI) call (blueprint 2.9, 5.1; v2 2.6, 2.9).

One method per MCP tool, with the tool's name and keyword arguments, each returning a ``ResultEnvelope``-derived
model (``models/results.py``; the run tools return ``models.run.RunSummary``). Every call

1. re-reads the configuration through the digest-cached ``ConfigLoader`` (an edited file takes effect on the next
   call; an invalid configuration makes every tool refuse with ``invalid_config`` except ``station_status``, which
   still answers and shows the problems, and ``safe_shutdown``, which falls back to the last valid configuration of
   this process when there is one);
2. appends one ``tool_call`` audit event (adapter, tool, sha256 of the canonical arguments, ``B1500_SESSION_TAG``,
   result status and the plan/run/recipe ids involved) to ``<state_dir>/audit/YYYY-MM-DD.jsonl``;
3. never raises to adapters: package errors become their error code, anything unexpected ``internal``
   (``KeyboardInterrupt``/``SystemExit`` still propagate).

Calls are serialized per service object (a re-entrant lock), so a FastMCP worker thread and the CLI never interleave
in one process; other processes are kept apart by the instrument lock. An asynchronous run (v2 2.6) runs on its own
worker thread outside that lock: while it runs, ``station_status`` answers ``busy`` from the cached snapshot, a second
run request is ``busy`` at once, ``get_run``/``list_runs`` show its progress and ``safe_shutdown`` cancels it (the
abort file reaches a run of any process). ``follow_run`` (CLI foreground runs) and ``stop_runs`` (the MCP server's
shutdown hook, the CLI's Ctrl-C) are the two non-tool lifecycle methods.

Responses stay at or below ``RESPONSE_TOKEN_BUDGET`` (2k) tokens (blueprint 5.1): ``get_run`` downsamples data rows
and trims audit lines, ``list_runs`` trims entries, both measured with the conservative ``approx_tokens`` estimate (no
tokenizer download at run time).

Modules: ``core`` (``B1500Service``: tool methods, call plumbing, ``list_recipes``, ``validate_plan``), ``status``
(``station_status``), ``runs`` (``list_runs``, ``get_run``, ``analyze_run``, ``annotate_run``), ``shutdown``
(``safe_shutdown`` and ``B1500Admin``, the human-only CLI operations ``b1500 fault clear`` and ``b1500 lock status``,
never MCP tools) and ``common`` (constants and helpers).
"""

from b1500_test_agent.service.common import (
    DEFAULT_MAX_POINTS,
    DEFAULT_RUN_LIMIT,
    ENV_SESSION_TAG,
    MAX_POINTS_LIMIT,
    MAX_RUN_LIMIT,
    NPZ_MAX_POINTS,
    RESPONSE_TOKEN_BUDGET,
    TOOL_NAMES,
    TRIM_TARGET,
    approx_tokens,
    args_digest,
    status_for,
    validation_message,
)
from b1500_test_agent.service.core import B1500Service
from b1500_test_agent.service.shutdown import B1500Admin

__all__ = [
    "DEFAULT_MAX_POINTS",
    "DEFAULT_RUN_LIMIT",
    "ENV_SESSION_TAG",
    "MAX_POINTS_LIMIT",
    "MAX_RUN_LIMIT",
    "NPZ_MAX_POINTS",
    "RESPONSE_TOKEN_BUDGET",
    "TOOL_NAMES",
    "TRIM_TARGET",
    "B1500Admin",
    "B1500Service",
    "approx_tokens",
    "args_digest",
    "status_for",
    "validation_message",
]
