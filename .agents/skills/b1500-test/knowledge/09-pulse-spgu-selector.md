---
domain: 09-pulse-spgu-selector
maturity: seed
sources:
  - "blueprint v2 0 (decision 9, sources without compliance), 2.7 (kind spgu_pulse), 2.8 (R-PULSE-01..03, R-SPGU-01), 2.9 (pulse summary), 11 (ATV-19, ATV-20)"
  - "B1500 Programming Guide Ed. 15 (PG), PDF pages cited inline"
  - lwp/matlab_B1500/lib/SPGU_pulse.m, test_SPGU.m (ERMOD 1, ERSSP p,2, SIM 0, SPRM, SPPER, SER, SPM, SPT, SPV, SPUPD, SRP, SPST? polling)
  - src/b1500_test_agent/models/spgu.py, driver/ops/spgu.py (WP9.1), catalog/kinds/spgu_train.py, catalog/blocks.py spgu_burst (WP9.3)
last_reviewed: null
---

# Pulses, HV-SPGU and the selector (knowledge domain 9)

How the kernel puts pulse trains and arbitrary linear waveforms on a pad with the HV-SPGU (B1525A), why the level at
the pad depends on the declared load, and what bounds every output. Routing through the 16440A selector is
[11 switching and routing](11-switching-routing.md); program/erase and read sequences (kind `pulse_read`) extend
this file with WP9.4.

## Contents

- [HV-SPGU output and the SER load](#hv-spgu-output-and-the-ser-load)
- [PG pulse trains](#pg-pulse-trains)
- [ALWG waveforms](#alwg-waveforms)
- [Running a train](#running-a-train)
- [Readings during a train](#readings-during-a-train)
- [Guard and rules](#guard-and-rules)
- [Simulator behaviour](#simulator-behaviour)
- [Troubleshooting pulses](#troubleshooting-pulses)

## HV-SPGU output and the SER load

- Two channels per module (`101`, `102` in slot 1). 50 Ohm output, **no compliance**: 0 to +-40 V into an open
  load, +-20 V into 50 Ohm (PG p141 (2-53) "SPGU"). Nothing limits the current but the source and load resistances.
- The output level is adjusted to the load the channel is told it drives, `SER` (0.1 Ohm to 1 MOhm, initial 50 Ohm;
  PG p507 (4-189) "SER"). A load `R` sees `V_set (SER + 50) / SER x R / (R + 50)`: the set level when `SER` = `R`,
  **twice the set level on an open load at SER 50 Ohm**. A gate or a capacitor is an open load: declare `SER` 1 MOhm
  (`load_ohm`), then the pad sees the set level (x 1.00005).
- Short-circuit current behind the terminal's series resistance: `V_open / (50 + min_series_ohm)`; 4 V open gives
  0.08 A into a short. A DUT terminal declared `impedance: high_z` makes this an accepted residual the plan summary
  shows (`Isc<=0.08 A residual`); otherwise it must stay within the hard current limit (R-SPGU-01).
- `CORRSER?` measures the load during one pulse (PG p386 (4-68) "CORRSER?"); the kernel uses only mode 0 (no
  automatic `SER` change) and no recipe runs it yet (bring-up L7 checks pulses into a known 1 MOhm load instead).

## PG pulse trains

- One pulse period for every channel (`SPPER`, 20 ns to 10 s on a 10 ns grid). Per channel one pulse source
  (two-level) or the sum of two (three-level: e.g. +4 V then -4 V within one period; PG p146 (2-58)). Per source:
  delay, width, leading and trailing time (`SPT`), base and peak (`SPV`).
- Timing limits (R-PULSE-01): width >= leading / 0.8; period >= delay + width + trailing / 0.8 (errors 2111/2112);
  transitions 8 ns to 0.4 s; levels on 1 mV.
- Every output is bounded: `SPRM 1,count` (1 to 1,000,000 pulses) or `SPRM 2,duration` (PG p512 (4-194) "SPRM").
  Free run (`SPRM 0`, the power-on setting) is never built; a recipe picks `bound: count|duration`.
- Recipe `spgu.pulse_train` (card `spgu/spgu-pulse-train`): one gate, 2- or 3-level, count or duration. The guard
  view of a three-level channel is one train: base = sum of bases, level = the largest magnitude, width = the union of
  both windows; the summary lists every level (`0->-4..4 V`).

## ALWG waveforms

- `SIM 1`: per channel up to 512 patterns of linear vectors (level reached over an incremental time on the 10 ns
  grid, at most 1024 - patterns vectors), one sequence of `(pattern, repeat)` shared by all channels (PG p149 (2-61)
  "ALWG"). 50 ns setup delay between different patterns. Bounded by sequences (`count`) or `duration`.
- Recipe `spgu.alwg_sequence`: one pattern (`levels`, `times`, `v_initial`), `repeat` per sequence. Default: a
  bipolar program/erase pair (+4 V and -4 V, 1 us each, 100 ns ramps, 10 us at 0 V after each).
- Guard view: the time away from the initial level per sequence is the width, the sequence period the period; the
  pulse count of the summary counts sequences.

## Running a train

1. `SPST?` must read 0 (no output left running by an earlier program).
2. Phase `pulse`: a gate on a selector output is switched to PGU (`ERMOD 1`, `ERSSP p,2`), read back.
3. `CN` of the SPGU channel(s) (and the SMUs of a read); setup `SIM`, `SPRM`, `SPPER`, `SER`, `SPM`, `SPT`, `SPV`,
   `ODSW`, `STGP` (or `ALW`/`ALS` blocks), each channel checked by the guard first; `SPUPD` (the base level appears),
   `ERRX?` drain, `SRP`.
4. `SPST?` polls (every 0.1-1 s, abort checks between) until 0 at the end of the count or duration
   (PG p142 (2-54) "SPST?"). ATV-19 fallback: still 1 after the planned time plus 2 s (or 5 %) -> `SPP`, verified
   by `SPST?` 0, counted in `kind_result.spp_fallbacks`; a fault latches if it will not stop.
5. `ERRX?` drain; phase `rest` (selector back to open, read back); the cleanup (`SPP` if active, `DZ`, routes to
   rest, `CL`, verify `SPST?` 0 and every selector port) runs whatever happened.

## Readings during a train

- A recipe with SMU roles (`bias_v`, `ground`, `measure_only`) reads them with spot measurements while each train
  runs: `settle` after `SRP`, then `samples` readings; `SPST?` must still read 1 afterwards, else the run fails
  (raise `duration`). Every train must last at least `settle + 2 x samples x read time + 50 ms`.
- An SMU integrates over many periods: it reads the time average of its terminal current over the train, plus any DC
  current the train pumps (charge pumping, [05](05-reliability-defects.md#charge-pumping)).
- Grids: a `float_list` base level (one pgu role) and a `float_list` frequency give one train per point, base outer.

## Guard and rules

- `OutputGuard.check_pulse` at every setup, start and `SER` change: the open-load level at the DUT, width, duty,
  pulses and on-time per start inside the channel's pulse envelope (built from the plan's trains).
- R-PULSE-01: every stored SPGU program inside the module spec (timing, levels, counts, ALWG vectors); R-PULSE-02:
  the DUT terminal declares a `pulse` envelope (missing -> blocked; outside -> `dut_envelope`); R-PULSE-03: above the
  policy soft bands (5 V at the DUT, 10,000 pulses per run, 60 s at the pulse level, duty 0.5) -> `soft_pulse`.
- R-SPGU-01: `SER` = the recipe's `load_ohm`; open-load level within 40 V, the hard limit and the DUT's pulse
  `max_abs_v`; **a `high_z` terminal with `load_ohm` below 1 kOhm is blocked** (50 Ohm would double the level);
  short-circuit current within the hard limit unless `high_z` (then the residual in the summary).
- Summary form: `gate=SPGU1:101 via SEL1.OUT1 pulse 0->4 V 1 us x1000 @10 kHz SER 1 MOhm Isc<=0.08 A residual`.

## Simulator behaviour

- The level at the pad follows the SER divider exactly; a run drives the circuit in virtual time (FeFET switching
  kinetics), `SPST?` reads 1 until the count/duration ends; pulses are 50 %-width rectangles (edges only in the
  checks and in the charge-pumping energy window). Faults `spgu_no_stop` (ignores stops until an `SPP`) and
  `spgu_load_mismatch` (a different load than declared).
- An SMU reading while a train runs is the time average over one period plus the charge-pumping current of a MOSFET
  with interface traps (scenario `nmos_cv`); `MM 10` sampling still sees the static levels.
- On the simulator a selector input recorded `null` in the station profile takes the scenario's cabling (rehearsal);
  on hardware it blocks until a human records it at L7.

## Troubleshooting pulses

| symptom | likely cause | first safe check |
|---|---|---|
| plan blocked R-SPGU-01 "high_z but SER" | `load_ohm` 50 Ohm on a gate | declare 1 MOhm (`load_ohm`), never raise the DUT limit |
| pulses had no effect on the device | selector not on PGU, wrong port, amplitude/width too small | runbook `spgu-pulse-no-effect` |
| level at the pad differs from the set level | load is not the declared `SER` | runbook `spgu-load-mismatch` |
| `spp_fallbacks` > 0, or SPST? stuck | ATV-19: status not falling at the end | runbook `spgu-selector-state`; `safe_shutdown` |
| plan blocked "is pgu, not its rest state" | a run left the selector on PGU | `safe_shutdown`; runbook `spgu-selector-state` |
