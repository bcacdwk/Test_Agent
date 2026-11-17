---
id: vth-drift-igzo
title: IGZO or oxide TFT Vth differs from run to run
maturity: seed
sources: [deck slide 17, PPT_slides_content.md p.18 (temperature cause)]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Vth drift on IGZO and oxide TFTs

## Symptom

- Repeated Id-Vg runs of the same plan on the same `dut_instance` give different Vth (shift beyond the run's own
  fit uncertainty), often in one direction with every run.
- Hysteresis between sweep directions, or a slow return between sessions.

No simulator scenario models this: it is a hardware runbook.

## Likely causes

1. Moisture adsorption or desorption on the back channel shifts its potential (deck slide 17).
2. The measurement itself is a bias stress: each sweep shifts Vth (deck slide 17).
3. Temperature changes alter the oxygen-vacancy concentration (deck text).
4. Light on the sample (microscope lamp); not from the deck, TODO(verify) with the owner.

## First safe checks

1. `list_runs` plus `get_run` for every run on this device: timestamps, plan, dut_instance, quality. Use the same
   analysis method and window for all of them, or the comparison is meaningless.
2. Rule out the other runbooks first: quality `ok`, no C or T in the fit window, SNR fine.
3. Tabulate Vth against run start time and rest time between runs, and report it as a trend, not as one value.
4. Deck order step 2 and 3 as new plans inside the card's recommended range that stay tier `ok`: a narrower gate
   sweep (smaller stress), then fewer points or `integration: short` (shorter measurement). At most two re-runs.

## Physical checks to ask the human

Deck order (slide 17): control temperature and humidity, reduce the sweep voltage range, shorten the
measurement time.

- Temperature and humidity at the prober; is a dry nitrogen purge or a chuck temperature control available?
- How long has the sample been in air, or out of the chamber, since the last anneal?
- Is the microscope light on during the sweep?
- How long did the device rest between runs?

## Do not

- Average drifting values into one "Vth" or report the run that matches the expectation.
- Widen the sweep or raise the drain bias to "stabilise" the curve: more stress, more drift.
- Change the fit window between runs to make the numbers agree.

## Stop and call safe_shutdown

- Vth keeps moving in one direction after two re-runs with reduced stress: hand the environment questions to the
  human and report the trend with timestamps.
- Gate current rises from run to run (possible degradation): see [compliance-hit](compliance-hit.md).
