---
id: stress-degradation-unexpected
title: Stress-measure result unexpected (no shift, wrong sign, huge shift, early breakdown, odd exponent)
maturity: seed
sources: [knowledge 05 sections BTI/HCI/SILC/TDDB and "Stress-measure analysis" (skill b1500-test), src/b1500_test_agent/analysis/stress.py (WP7.6), src/b1500_test_agent/catalog/kinds/stress_measure.py, general practice (causes; not checked against a source)]
---

# Unexpected stress degradation

## Symptom

- `bti_power_law`, `degradation_vs_time` or `silc` on a `stress_measure` run (`reliability.bti_sms`,
  `reliability.hci`, `reliability.silc`, `igzo.bias_stress`) gives no measurable shift (`failed`: below
  `min_change`), a shift of the wrong sign, a shift far above what the human expects for this device, or an
  exponent n/m the human finds implausible for the technology. No checked range of shifts or exponents is on record
  (knowledge 05 "BTI stress-measure-stress" and "Hot-carrier injection HCI", skill `b1500-test`): ask the human what
  they expect, and check the fit's `r2` and the reads used before calling a value odd.
- Recovery larger than the stress shift; reads that jump from one read to the next; gate current rising by decades
  during the stress (`silc_ratio` huge) or the run stopping with C/T (`completed_with_flags`, early stop).

## Likely causes

1. Stress too weak or too short for this oxide (no shift), or the read itself is a stress (shift without stress).
2. Recovery between stress and read: slow reads (long staircase, high integration) let BTI relax; the exponent drops.
3. Wrong polarity: NBTI needs a negative gate on p-FETs; sign conventions in `stress_measure` (`stress <V> V` in
   the summary) were misread.
4. Read noise near the floor: Vth from a curve that barely reaches the criterion; Id at a bias in the noise.
5. Oxide breakdown or soft breakdown during stress (SILC jump, gate C), or HCI with the wrong drain bias.
6. IGZO: moisture, light and temperature drift mimic or mask bias stress (see [vth-drift-igzo](vth-drift-igzo.md)).

## First safe checks

1. `get_run(run_id, include=[summary, quality, data])`: the stress levels and times in the summary, every read's
   status counts, `phase`/`cycle` columns, `t_s`, any C/T; `plot_timeseries` of the read quantity.
2. The reference read (cycle 0) against the device's L4/earlier Id-Vg: a different starting Vth means a different
   or already damaged device.
3. Re-analyse with the same method and window on every read (`analyze_run` options of the card); compare
   `vth_constant_current` and the read's Id at fixed Vg; never mix methods across reads.
4. On the simulator, compare with the scenario's stated model (`nmos_bti`): a mismatch there is a software issue.

## Physical checks to ask the human

- Is this a fresh sacrificial device? Was it stressed before (earlier runs, ESD)?
- Temperature of the chuck and the room during the run; light on the sample; for IGZO, humidity.
- Hardware only: gate probe contact (a lifting probe looks like recovery or noise).

## Do not

- Rerun on the same stressed device and average with the first run; stress is cumulative.
- Raise the stress voltage or time to "get a shift": stress levels come from the human's request or DUT profile
  (a new plan, new consent, the human's decision), never a debug fix.
- Fit the exponent over a window chosen to match the literature; report the window and points used.

## Stop and call safe_shutdown

- Gate current at its compliance or a sudden jump in Ig: breakdown suspected; stop all stress on this device.
- Any fault, `cleanup_unverified`, or an outcome `aborted`: `safe_shutdown(reason)`, report, wait for the human.
