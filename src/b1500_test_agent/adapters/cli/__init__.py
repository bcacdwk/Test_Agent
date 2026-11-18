"""`b1500` command-line interface (Typer, blueprint 5.3 v1 / 2.9 v2) over the same ``B1500Service`` as the MCP server.

Operator commands map one-to-one to the MCP tools (``TOOL_COMMANDS``; parity test) and print either a short human
summary or, with ``--json``, the service's result model. Exit code 0 when the result is ``ok``, 1 otherwise, 2 for
usage errors.

- ``status`` · ``recipes [ID] [--device T]`` · ``plan RECIPE -p k=v --pin-map X [--dut Y]`` / ``plan --file F`` /
  ``plan --plan-id P`` · ``run PLAN_ID [--dut-instance X]`` · ``run --confirm PLAN_ID`` · ``runs`` ·
  ``show RUN_ID`` · ``analyze RUN_ID METHOD -o k=v`` · ``note RUN_ID TEXT`` · ``shutdown [--reason]``
- human-only: ``fault clear`` (safe shutdown, then clears the latch only when the shutdown verified the safe state)
  and ``lock status``
- ``doctor`` (non-probe checks), ``config check``, ``harness init --codex|--claude [--check]`` (renders
  ``config/harness/`` templates into the gitignored ``.codex/config.toml`` / ``.mcp.json``), ``mcp`` (stdio server,
  same as ``b1500-mcp``)
- developer: ``dev tool-budget``, ``dev recipe-check``, ``dev mcp-smoke --config F`` (start the server as a harness
  config says and check it), ``dev sim-console`` (raw FLEX, simulator only), ``dev sync-harness [--check]``
  (generated ``.claude/skills/`` copy of ``.agents/skills/``), ``dev lint-skills`` (skill schema, budgets, links),
  ``dev gen-index [--check]`` (generated card index), ``dev acceptance`` (M3 harness acceptance runner,
  ``devtools/acceptance/cli.py``)
- manuals (CLI only, no MCP tool): ``manual search|page|toc|status`` (read-only queries of the committed page
  corpus) and ``manual build [--src DIR] [--check]``

Modules: ``core`` (the root ``app``, operator, human-only and installation commands, shared plumbing), ``dev`` (the
``dev`` group) and ``manual`` (the ``manual`` group); later work packages add ``config`` and ``bringup`` groups. The
console script ``b1500`` is ``main`` of this package.

``run --confirm`` re-validates the plan, prints its summary and asks y/N on an interactive terminal only; without
a TTY it exits non-zero and runs nothing (UX only: the harness tool confirmation is the approval, blueprint 4.3).
The run manifest records ``confirmed_via: cli --confirm``.
"""

from __future__ import annotations

from b1500_test_agent.adapters.cli.core import DEFAULT_MCP_APP_SPEC, TOOL_COMMANDS, app
from b1500_test_agent.adapters.cli.dev import dev_app
from b1500_test_agent.adapters.cli.manual import manual_app

app.add_typer(dev_app, name="dev")
app.add_typer(manual_app, name="manual")

__all__ = ["DEFAULT_MCP_APP_SPEC", "TOOL_COMMANDS", "app", "main"]


def main() -> None:
    """Entry point of the `b1500` console script."""
    app(prog_name="b1500")
