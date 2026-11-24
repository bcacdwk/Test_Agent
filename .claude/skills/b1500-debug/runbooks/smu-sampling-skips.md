---
id: smu-sampling-skips
title: SMU sampling run with skipped samples, uneven time steps, host time or an early stop
maturity: seed
sources: [Programming Guide Ed. 15 sampling measurement PG p112-114 (2-24), MT PG p474-476 (4-156), time stamp PG p539 (4-221), src/b1500_test_agent/catalog/kinds/smu_sampling.py (kind_result; WP7.4)]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Sampling skips and time-base problems (MM 10)

## Symptom

- `get_run` of a `smu_sampling` run (`generic.smu_sampling`, `mosfet.id_t_sampling`, `reliability.tddb_cvs`):
  `kind_result.index_gaps` > 0, fewer `samples_measured` than `samples_planned`, larger `t_s` steps in the table.
- `kind_result.time_source` is `index` or `host` instead of `timestamp` (time from the sampling index or from the
  host's trigger times: ATV-22 fallback, flagged).
- `aborted: true` with `abort_reason`/`abort_t_s`, `samples_after_abort` > 0, or `stopped_early` (later blocks not
  triggered); `sampling_summary` or `time_to_breakdown` warns about the time axis.

## Likely causes

1. Interval shorter than one measurement: integration preset (`long` = 16 PLC), several measured roles or a high-
   resolution ADC. The instrument skips a sample that would start while the channels are busy (index gap).
2. Auto ranging: a range change during a sample discards it (PG p49 (1-29)); fast transients cross ranges.
3. Automatic abort (`MSC 2,2`): compliance, overflow or oscillation stopped the sampling; the rest is dummy data
   (`199.999E+99`, dropped). In TDDB that is the breakdown itself.
4. Time stamps missing or running backwards (format, timer reset): the kind falls back to index/host time.
5. Long runs are chains of 25 s blocks: the gap between blocks is the host round trip (a few ms), not a skip.

## First safe checks

1. `get_run(run_id, include=[summary, quality, data])`: `kind_result` fields above, status counts, the `t_s`
   column around the gaps; `plot_timeseries` to see where they sit.
2. Compare the plan: `interval` against the estimated time per sample (integration preset x measured roles; the
   plan's estimate) and the card's recommended interval.
3. Abort: which channel and letter (C/T/V/X) at `abort_t_s`; for TDDB report `time_to_breakdown`, for the others
   follow [compliance-hit](compliance-hit.md).
4. One re-run inside the card's recommended range that stays tier `ok` and changes one thing: a longer `interval`,
   `integration: short`, fewer measured roles, or a fixed/limited `irange` to stop range changes.

## Physical checks to ask the human

- Is the device stable (no light, no moving probe)? A transient across many decades forces range changes.
- Hardware only: any front-panel error? Was the instrument restarted or the timer reset (`TSR`) by another program
  while the run was going?

## Do not

- Interpolate missing samples or relabel host time as instrument time; report `time_source` with the data.
- Treat dummy samples after an abort as data, or raise the compliance to "finish" the sampling.
- Shorten the interval below the measurement time to "speed it up": more gaps, not more data.

## Stop and call safe_shutdown

- A run that aborts on compliance without the plan expecting it (possible breakdown), cleanup `unverified`, or a
  fault: `safe_shutdown(reason)`, report the timeline, hand over to the human.
- Gaps persist after two re-runs with longer interval and short integration: report and stop.
