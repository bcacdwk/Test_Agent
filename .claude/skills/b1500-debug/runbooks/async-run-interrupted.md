---
id: async-run-interrupted
title: Asynchronous run interrupted (harness closed, server killed at turn end, host crash, stop request)
maturity: seed
sources: [blueprint v2 2.6 (async runs, abort file, shutdown hook, residual), blueprint v2 7.4 stage L9, progress WP5.6, progress WP7.7 (codex-cli headless turn end), session/transaction.py (in-flight recovery), catalog/running.py (orphaned run)]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Asynchronous run interrupted

## Symptom

- A long run that returned `outcome: running` is no longer followed: the turn ended, the coding agent or its MCP
  server was closed or restarted, the PC rebooted.
- `get_run(run_id, include=[summary, progress])`: `cancelled` with "MCP server stopping (stdin closed)" or
  "(SIGTERM)"; or no manifest and the progress frozen at `running`; or `aborted` with "ended without finalizing
  it ... in-flight recovery".
- `station_status`: in-flight marker set and no `active_run`; `run_plan` refused with "in-flight marker" (R-FAULT-01).

## Likely causes

1. The harness closed the server's stdin or sent SIGTERM (Claude Code, a closed session): the server's shutdown hook
   asked the run to stop; it cancelled at its next checkpoint with a verified cleanup and auto-calibration
   restored: `cancelled`, rows in `partial.csv`. Nothing is left to recover.
2. The server died without its hook: codex-cli ends the MCP server at the end of every headless turn (WP7.7), or Task
   Manager, a crash, a power cut. The run's transaction never ended: outputs stay as they were (SMU bias, SPGU output
   and selector route, WGFMU connection, `CM 0`) until the next transaction, and its in-flight marker stays. That
   transaction (call `safe_shutdown` first) runs the recovery cleanup over every bus, restores auto-calibration from
   the marker and archives the run `aborted` with its consent record and partial rows.
3. A stop request from another process (`safe_shutdown`, or the human's `uv run b1500 shutdown`): `cancelled` at a
   checkpoint. Not a fault.
4. The recovery could not verify the outputs (link lost, stuck output): fault latched.

## First safe checks

1. `safe_shutdown("interrupted run <id>")`: never gated; cancels the run if it still runs in any process, else its
   transaction is the recovery. Read "cleanup verified (...)", `cancelled_run` and the cleanup's `restore` step.
2. `station_status`: no in-flight marker, no `active_run`, lock free, no fault latched.
3. `get_run(run_id, include=[summary, progress, data, audit])`: outcome `cancelled` or `aborted`,
   `cleanup_verified`, done/total, the data note PARTIAL, audit `run_cancelled` or `recovery_cleanup`.
4. `list_runs(status="running")` is empty afterwards; an entry without a live process is an orphan (check 1 ends it).

## Physical checks to ask the human

- Hardware, cause 2: how long the station sat between the kill and the recovery (the stress, pulse or WGFMU level
  stayed on that long: extra stress on the DUT); front panel outputs and the high-voltage LED; is the same DUT
  still landed.
- Whether the session was ended on purpose. Long plans need a session that stays open while they run: an
  interactive one, or the human polls `uv run b1500 runs --status running` in their own terminal.
- Whether to repeat the measurement, on this DUT (pre-stressed: say so) or on a fresh one.

## Do not

- Restart, resume or "continue" the run: a repeat is a new `validate_plan` and, for `needs_confirmation`, the
  human's new consent.
- Report partial rows as a complete run, merge them with another run, or derive values the card does not allow
  from partial data (label them partial, with the time or cycles reached).
- Delete or edit `inflight.json`, `abort.json`, lock files or anything under `data/**`; kill processes; run
  `b1500 fault clear` (human only).
- Write "cleanup verified" before a tool result says so.

## Stop and call safe_shutdown

- Always first (check 1). Report: run id, outcome, cleanup verified or not, the `restore` step, partial rows with
  done/total, and (cause 2) that the outputs stayed on until the recovery.
- Recovery unverified, a fault latched, the lock held by a process that is gone, or the run still `running` after
  `safe_shutdown`: stop, runbook [cleanup-failed-fault](cleanup-failed-fault.md), wait for the human.
