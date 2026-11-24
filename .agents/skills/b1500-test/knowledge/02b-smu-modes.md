---
domain: 02b-smu-modes
maturity: seed
sources:
  - "B1500 Series Programming Guide Ed. 15 (PG), pages cited inline"
  - src/b1500_test_agent/catalog/kinds (smu_sampling, smu_pulsed, smu_search, stress_measure; WP7.3-WP7.6)
  - src/b1500_test_agent/analysis/floor.py (zero_floor; v2 WP7.1)
  - src/b1500_test_agent/driver/flex/smu.py (FL, SSR, AZ, AV, RM, WNCC; WP7.7)
  - docs/design/blueprint.md sections 1.2 (SMU scope), 2.6 (async runs, R-CAL-02) and 7.4 (L5, L9)
last_reviewed: null
---

# SMU measurement modes, conditioning and long runs (knowledge domain 2b)

Split from [02](02-b1500-instrument.md) when it reached 300 lines (WP7.7): the SMU modes beyond the staircase, the
zero-check floor, the conditioning settings and long SMU runs. Module table, channel numbering, status letters,
integration and ranging, cleanup and errors stay in 02. PDF page numbers are physical PDF pages.

Contents: [Sampling MM 10](#sampling-measurement-mm-10) · [Pulsed](#pulsed-measurements-mm-3-4-5-27-28) ·
[Search](#search-measurements-mm-9-14-15) · [Zero check floor](#zero-check-floor) ·
[Conditioning](#smu-output-conditioning) · [Long runs](#long-smu-runs)

## Sampling measurement MM 10

Kind `smu_sampling` (recipes `mosfet.id_t_sampling`, `generic.smu_sampling`, `reliability.tddb_cvs`); PG sampling
measurements PG p112-114 (2-24), `MT` PG p474-476 (4-156).

- On the trigger the synchronous sources (`MV`/`MI`) force their base value, `hold_base` later their bias value
  (the time origin, `t_s = 0`), `hold_bias` later the first sample; then one sample per `interval` (2 ms to 65 s
  in 1 ms steps; below 2 ms linear only). DC sources (`DV`/`DI`) are set before the trigger and keep their level.
- Each sample carries its sampling index (`FMT 1,1`) and, with `TSC 1`, a time stamp per channel (time since `TSR`);
  `t_s` comes from the stamps. A sample that would start while the channels are busy is skipped (index gap).
- `MSC 2,2`: compliance of any channel, overflow or oscillation stops the sampling at once (later data read
  `199.999E+99`, dropped from the table) and the sources go to their base value; a normal end keeps the bias.
- Runs with more than 60 s of linear sampling are chains of 25 s blocks: continuation blocks hold the stress
  (base = bias) and the time stamps run on, so `t_s` stays exact; each block is a checkpoint (progress, cancel).

## Pulsed measurements MM 3 4 5 27 28

Kind `smu_pulsed` (card `smu-pulsed-iv`); PG p93-105 (2-5), `PT` PG p486-487 (4-168), `MCPT` PG p464 (4-146).

- A pulse source sits at its base, pulses to its peak for `width` once per `period` and returns to base; the
  measurement (pulsed ADC, `AIT 2,3,<time>`) ends with the pulse. MM 3: one pulse, one reading; MM 4: one pulse per
  step of a `PWV` pulsed sweep; MM 5: a `WV`/`WI` staircase with one `PV` pulse per step; MM 27/28: up to ten
  channels pulse together (`MCPNX` bias, `MCPWNX` sweep, `WNX` staircase) and measure in parallel.
- HR/MP/HPSMU: width 500 us-2 s in 100 us steps, period 5 ms-5 s with period >= width + 2 ms (10 ms above 100 ms),
  no delay, one common width (R-PULSE-01, PG p462 (4-144)); MM 4/5 sweep linearly only (error 226).
- Auto ranging in a pulsed measurement means the compliance range (PG p337 (4-19)): set a tight compliance or
  `irange` for small pulsed currents. A pulse far shorter than the thermal time constant reads the device cold.

## Search measurements MM 9 14 15

Kind `smu_search` (cards `smu-search`, `tddb-bdv`); PG p108-111 (2-20), p106-107 (2-18). One `XE`, one result.
- Linear (`LSV`) steps, binary (`BSV`) halves its change until the monitor (`LGI`/`BGI`) meets the target: result
  `Data_search` (value forced there), `Data_sense`; `G` not in range, `S` aborted; binary cautious never forces stop.
- Quasi-pulsed (`BDV`): ramps until the source hits its compliance (breakdown, `C`) and reads the voltage there; it
  needs a 10 V change from start before the compliance (else `S`, PG p53 (1-33)): thin films use a linear ramp.

## Zero check floor

Implemented (`zero_floor`, M7; recipe `system.zero_check`; the definition shared with
`src/b1500_test_agent/analysis/floor.py`, kept here next to the ranging because the analysis file is at its line
budget).

- Every SMU at 0 V, terminals open: per measured current and range label (`<role>_range`) the offset = mean and the
  floor = sample standard deviation of the trusted readings (3 significant digits). One result per role:
  `<role>_floor` = floor on its lowest range; `fit` = the floor of every range (`10pA`, `1nA` ...), `offset` (lowest
  range) and `max_abs_offset`. Options `max_floor_a`, `max_offset_a` give `pass`/`fail`. C/T readings at 0 V are
  excluded and warned: the terminal is not open. Trust classes as in
  [06](06-analysis-extraction.md#run-table-and-trust-classes).

## SMU output conditioning

Blueprint v2 1.2 puts `RM`, `AV`, `AZ`, `FL` and `SSR` in the SMU scope (WP7.7). They are driver operations
(`set_filter`, `set_series_resistor`, `set_adc_zero`, `set_averaging`, `set_range_mode`; `WNCC` =
`clear_sweep_sources`), simulated and in the coverage ledger; no v2 recipe sends them, so every run keeps the
initial settings below (a kind that uses one restores it in its cleanup).

- `FL mode[,ch...]` (PG p436 (4-118) "FL"): SMU output filter, initial **disconnected** (0) on the B1500; connected it
  removes spikes and overshoot but slows the source. Never sent to "all channels" by the driver.
- `SSR ch,mode` (PG p521 (4-203) "SSR"): about 1 MOhm series resistor, initial disconnected; the set voltage then
  divides between it and the DUT. Not with an ASU, HCSMU, HVSMU or MCSMU; with the output on it forces 0 V for a
  moment. The simulator keeps the setting but not the divider.
- `AZ mode` (PG p363 (4-45) "AZ"): ADC zero (offset cancel) of the high-resolution ADC, initial off; on roughly
  doubles the integration time (the simulator models that) and helps low-voltage readings.
- `AV number[,mode]` (PG p362 (4-44) "AV"): high-speed ADC averaging (1-1023 samples, or -1..-100 PLC); the kinds
  set the same ADC with `AIT` presets instead.
- `RM ch,mode[,rate]` (PG p502 (4-184) "RM"): auto-range operation of a current measurement: 1 (initial), 2 (range up
  after a reading above range x rate/100), 3 (also down below range x rate/1000); rate 11-100, default 50.
- Out of scope with a reason in the ledger: high-speed spot (`TI`/`TV`), timer-start sources (`TDV`/`TDI`),
  signal monitor (`DSMPL*`), parallel measurement (`PAD`), the HRSMU PLC operation type (`AITM`), the wait-time
  factor (`WAT`), HV/HC units and expanders (the developers' coverage ledger records each reason).

## Long SMU runs

- A plan above `max_sync_run_s` (300 s) runs asynchronously: `run_plan`/`run_confirmed_plan` returns `running`,
  `get_run(include=[progress])` follows it, `safe_shutdown` (any process, also `uv run b1500 shutdown`) cancels it at
  the next checkpoint (outcome `cancelled`, verified cleanup, rows so far in `partial.csv`); above
  `long_run_confirm_s` (600 s) the plan needs `long_run` consent (blueprint v2 2.6).
- Sampling runs and stress holds are chains of MM 10 blocks of at most 25 s (one checkpoint each, the time stamps run
  on); a hold forces the stress level with one monitor sample per block (`stress_measure`, card
  `bti-stress-measure`).
- Asynchronous runs send `CM 0` first and the cleanup restores the auto-calibration state read by `*LRN? 31`
  (R-CAL-02): auto-calibration after 30 min would otherwise run with outputs off in the middle of a stress.
- A killed server leaves the outputs as they were until the next transaction: it finds the in-flight marker, runs
  the recovery cleanup (`AB`, `DZ`, `CL`, verify) and finalizes the run `aborted` (bring-up drill: L9).
