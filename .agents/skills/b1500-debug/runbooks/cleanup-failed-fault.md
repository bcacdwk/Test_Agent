---
id: cleanup-failed-fault
title: Failed cleanup and the fault latch
maturity: seed
sources: [blueprint 2.4, 4.3 point 5 and 5.3, session/fault.py, session/transaction.py]
---

# Failed cleanup, fault latched

## Symptom

- A tool result with status `fault` and `fault_latched` (every sourcing call refuses) or `cleanup_unverified`
  (the run's cleanup could not prove the outputs safe).
- `station_status` shows `fault: LATCHED: <reason>`, possibly `inflight marker: yes`.
- A run whose cleanup report says `verified: unverified` or lists a FAILED step.

## Likely causes

After every run the core aborts, zeroes, disconnects, drains the error queue and verifies that every output is
off. When that cannot be verified, even after a device clear and one retry, it latches the fault.

1. The instrument link dropped or timed out during the run or the cleanup (see
   [visa-no-connection](visa-no-connection.md)).
2. An output did not go to 0 V (stuck output; simulator fault `ignore_dz`), or zero/disconnect commands failed.
3. A previous process died mid-run: the inflight marker is recovered automatically by the next transaction or
   `safe_shutdown`.
4. A `safe_shutdown` without an instrument link (fail safe), or an unreadable latch file (counts as latched).

## First safe checks

1. `safe_shutdown(reason)`: never gated, also runs with a latched fault. It may verify the outputs now, but it
   never clears the latch.
2. `station_status`: fault reason and run id, outputs on, instrument errors, lock holder.
3. `get_run(run_id, include=[summary, audit])` for the run named in the fault: which cleanup step failed, the
   outputs read back, errors drained.
4. Read-only tools keep working (`station_status`, `list_runs`, `get_run`, `analyze_run`); runs refuse until the
   human clears the latch. Do not retry them.

## Physical checks to ask the human

- Front panel: is any output still on, the high-voltage LED lit, an error shown?
- Is the DUT still biased? If an output may be on, the human makes the station safe by the lab's own procedure
  before anything else.
- Cables, GPIB link and instrument power, if the link dropped.

Only the human clears the fault latch, in their own terminal, after these checks. Show them the command and stop:

```text
uv run b1500 fault clear
```

It runs a safe shutdown first and clears the latch only if every output reads off at 0 V and the error queue was
read and empty. If it refuses and lists instrument errors, the human reviews them and runs it again.

## Do not

- Run that command yourself, in any form or wrapper (the harness blocks it; it is human-only by design).
- Delete or edit the latch file, the inflight marker or anything under `data/**`.
- Work around the latch with the sim console, own scripts, another backend or config edits.
- Call the fault "probably harmless" and continue measuring.

## Stop and call safe_shutdown

- Always: a latched fault ends the measurement session. Call `safe_shutdown(reason)`, report the fault reason,
  the run id, the failed step and the outputs read back, show the clear command, and wait for the human.
- After the human cleared it: back to skill `b1500-test`; start with `station_status` and a new `validate_plan`.
