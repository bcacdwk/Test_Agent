"""`b1500` command-line interface (Typer, blueprint 5.3 v1 / 2.9 v2) over the same ``B1500Service`` as the MCP server.

Operator commands map one-to-one to the MCP tools (``TOOL_COMMANDS``; parity test) and print either a short human
summary or, with ``--json``, the service's result model. Exit code 0 when the result is ``ok``, 1 otherwise, 2 for
usage errors.

- ``status`` · ``recipes [ID] [--device T]`` · ``plan RECIPE -p k=v --pin-map X [--dut Y]`` / ``plan --file F`` /
  ``plan --plan-id P`` · ``run PLAN_ID [--dut-instance X]`` · ``run --confirm PLAN_ID`` · ``runs`` ·
  ``show RUN_ID`` · ``analyze RUN_ID METHOD -o k=v`` · ``note RUN_ID TEXT`` · ``shutdown [--reason]``
- human-only: ``fault clear`` (safe shutdown, then clears the latch only when the shutdown verified the safe state)
  and ``lock status``
- ``doctor`` (installation checks), ``doctor --probe`` (read-only instrument probe: queries only, PASS/WARN/FAIL
  lines, raw answers to ``work/bringup/probe-<UTC>.json``), ``update [--check]`` (human only: pull, sync, harness
  wiring and validated harness versions, free checks, "Ready." or a numbered list), ``harness init
  --codex|--claude [--check]`` (renders
  ``config/harness/`` templates into the gitignored ``.codex/config.toml`` / ``.mcp.json``), ``mcp`` (stdio server,
  same as ``b1500-mcp``)
- configuration (CLI only, no MCP tool): ``config check``; human-only ``config init [--visa]`` (copies the missing
  core examples into ``config/local/``, never overwrites) and ``config adopt FILE --as
  station|settings|policy|pinmap|dut`` (validates, shows the diff, copies; blocked for agents by the harness rules
  and the guard hook)
- bring-up (CLI only, no MCP tool), agents may run all four: ``bringup propose-station`` (read-only
  ``*IDN?``/``UNT?`` -> ``work/bringup/station.proposed.yaml`` + diff vs ``config/local/station.yaml``),
  ``bringup status`` (stages and their records), ``bringup capture RUN_ID...|probe`` (anonymized golden fixtures of
  hardware runs) and ``bringup record STAGE --run H...`` (draft validation record; simulator runs refused)
- developer: ``dev tool-budget``, ``dev recipe-check``, ``dev mcp-smoke --config F`` (start the server as a harness
  config says and check it), ``dev sim-console`` (raw FLEX, simulator only), ``dev sync-harness [--check]``
  (generated ``.claude/skills/`` copy of ``.agents/skills/``), ``dev lint-skills`` (skill schema, budgets, links),
  ``dev gen-index [--check]`` (generated card index and owner questions), ``dev acceptance`` (M3 harness
  acceptance runner, ``devtools/acceptance/cli.py``)
- manuals (CLI only, no MCP tool): ``manual search|page|toc|status`` (read-only queries of the committed page
  corpus) and ``manual build [--src DIR] [--check]``

Modules: ``core`` (the root ``app``, operator, human-only and installation commands, shared plumbing), ``dev`` (the
``dev`` group), ``manual`` (the ``manual`` group), ``config`` (the ``config`` group) and ``bringup`` (the ``bringup``
group). The console script ``b1500`` is ``main`` of this package.

``run --confirm`` re-validates the plan, prints its summary and asks y/N on an interactive terminal only; without
a TTY it exits non-zero and runs nothing (UX only: the harness tool confirmation is the approval, blueprint 4.3).
The run manifest records ``confirmed_via: cli --confirm``.
"""

from __future__ import annotations

from b1500_test_agent.adapters.cli.bringup import bringup_app
from b1500_test_agent.adapters.cli.config import config_app
from b1500_test_agent.adapters.cli.core import DEFAULT_MCP_APP_SPEC, TOOL_COMMANDS, app
from b1500_test_agent.adapters.cli.dev import dev_app
from b1500_test_agent.adapters.cli.manual import manual_app
from b1500_test_agent.adapters.streams import safe_streams

app.add_typer(config_app, name="config")
app.add_typer(bringup_app, name="bringup")
app.add_typer(dev_app, name="dev")
app.add_typer(manual_app, name="manual")

__all__ = ["DEFAULT_MCP_APP_SPEC", "TOOL_COMMANDS", "app", "main"]


def main() -> None:
    """Entry point of the `b1500` console script (output never fails on a legacy Windows code page:
    ``adapters/streams.py``)."""
    safe_streams()
    app(prog_name="b1500")
