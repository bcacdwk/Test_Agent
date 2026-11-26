---
id: wgfmu-memory-budget
title: WGFMU stored values over the memory budget (R-WG-02 block, R-RUN-01, error 3050)
maturity: seed
sources: [blueprint v2 0.1 (WGFMU limits), 2.8 (R-WG-02, R-RUN-01), 2.10 (npz data contract), WG p125 (4-55) "setMeasureEvent", WG p152 (4-82) "3050"]
---

# WGFMU memory budget

## Symptom

- `validate_plan` blocked by R-WG-02: "channel 202: N stored values exceed 4000000 per channel" (or the policy's
  `run_limits.max_points.wgfmu`), or by the waveform envelope's stored values.
- A run fails with error 3050 (measurement data memory overflow, WG p152 (4-82)) or reads fewer values than planned.
- A run is slow to read back or a table of millions of rows is hard to inspect.

## Likely causes

1. Points x sequence repeats x measuring channels too large: every repeat of a pattern stores its events' points
   again (a pulse train of 100,000 pulses with 10 samples = 1 M values per channel).
2. RAW events (average 0 in an events file, or raw sampling): each point is one stored value, and how many values
   fit depends on the averaging (WG p125 (4-55)); raw sampling at the 10 ns minimum interval fills about 4 M values
   in about 40 ms.
3. Both channels measure the same events (the lab layout): the budget applies per channel.
4. A policy limit lower than the module's about 4,000,000 values per channel (WG p125 (4-55); the human's
   `policy.yaml`).

## First safe checks

1. The plan summary: `<builder> ... N pts @interval` per channel; R-WG-02/R-RUN-01 findings with observed values.
2. Reduce the stored values inside the question: fewer `samples` per pulse, a larger `interval` with averaging over
   it (same time span, fewer points, less noise), fewer pulses or repeats, measurement on one channel only.
3. Split a long acquisition into several runs (each its own plan and confirmation) instead of one huge run.
4. Large tables are normal above 200,000 rows: `data.npz` + `preview.csv`; `get_run` shows a downsampled preview;
   ad-hoc analysis loads the npz (`load_run`).

## Physical checks to ask the human

- None needed for a plan-time block. After a 3050 at run time: was another program using the WGFMU meanwhile?

## Do not

- Ask the human to raise `max_points` or edit `policy.yaml` to get a plan through.
- Split one waveform into many patterns to dodge the count; the limit is per channel per run.

## Stop and call safe_shutdown

- A 3050 or 3015 at run time with the cleanup not verified: runbook `cleanup-failed-fault`.
