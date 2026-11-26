---
id: spgu-load-mismatch
title: SPGU level at the pad differs from the set level (SER vs real load)
maturity: seed
sources: [blueprint v2 0 (decision 9), 2.8 (R-SPGU-01), 11 (ATV-20), PG p141 (2-53) "Output impedance", PG p142 (2-54) "CORRSER", PG p507 (4-189) "SER", PG p386 (4-68) "CORRSER", lwp/matlab_B1500/test_SPGU.m (load 1 MOhm)]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# SPGU level at the pad differs from the set level

## Symptom

- The device reacts as if pulsed harder or softer than planned: a FeFET switches at a "too low" amplitude, a gate
  degrades, a charge-pumping plateau sits at shifted base levels.
- A scope at bring-up L7 shows about twice the set level on an open load, or a lower level into a low impedance.
- R-SPGU-01 blocked a plan: "terminal gate is high_z but SER is 50 Ohm", or "open-load ... exceeds".

## Likely causes

1. `load_ohm` (`SER`) does not match the real load. The HV-SPGU (50 Ohm output, no compliance) adjusts its level to
   the declared load: a real load `R` sees `V_set (SER + 50) / SER x R / (R + 50)`; at SER 50 Ohm an open gate sees
   2x the set level (50 Ohm output: PG p141 (2-53); SER: PG p507 (4-189) "SER"; ATV-20).
2. The DUT terminal is declared with the wrong `impedance` (a gate declared `resistive`, a resistor `high_z`).
3. A low-impedance path at the pad (gate leakage, a short, a parallel probe) loads the 50 Ohm output.
4. Simulator only: fault `spgu_load_mismatch` replaces the load.

## First safe checks

1. The plan summary: `SER` and the `Isc<=... A` bound of every pulse channel; the DUT profile's terminal
   `impedance`, `min_series_ohm` and `pulse` envelope.
2. For a gate or capacitor: `load_ohm` 1 MOhm (the pad then sees the set level; the manual's example `SER
   101,1000000`, PG p507 (4-189); the lab script `lwp/matlab_B1500/test_SPGU.m` sets 1 MOhm too). For a real
   resistive load: `SER` = that resistance. Validate a new plan; never raise the DUT envelope.
3. Leakage: an SMU gate-leakage check (card `gate-leakage`) on the pulsed terminal.

## Physical checks to ask the human

- What is on the pulsed pad: a gate, a capacitor, a resistor, a 50 Ohm termination? Anything in parallel?
- At bring-up L7: scope the selector output into a known 1 MOhm load and into 50 Ohm, compare with the set level.
- `CORRSER?` (load measurement, mode 0) is a bring-up check only; no recipe runs it yet. It needs a load of 40 Ohm
  to at most 5 kOhm depending on the level (PG p142 (2-54)): it cannot characterise a high-impedance gate.

## Do not

- Set `load_ohm` low to get more voltage, or edit `impedance`/`min_series_ohm` in a DUT profile to pass R-SPGU-01:
  those are the human's facts about the device.
- Pulse a terminal whose profile has no `pulse` envelope (R-PULSE-02 blocks; the human adds one).

## Stop and call safe_shutdown

- A suspected short at the pad (the level collapses, the SPGU reports an error): no further pulses.
- Device damage after a train: hand over to the human with the plan summary and the run's audit.
