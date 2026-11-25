---
id: cmu-series-resistance
title: Series resistance in MFCMU data (Cp falls with frequency in accumulation, large D, Cp-G and Cs-Rs disagree)
maturity: seed
sources: [PG p347 (4-29) IMP parameter pairs, UG p74 (2-34) MFCMU measurement parameters, EX p320 (4-26) error correction, Nicollian & Brews (1982) eq. 5.12, src/b1500_test_agent/analysis/cv.py (impedance_convert, rs_ohm; WP8.3)]
---

# Series resistance (MFCMU)

## Symptom

- A MOS capacitor's Cp in strong accumulation falls with rising frequency (Cmax at 1 MHz below Cmax at 100 kHz);
  G/w rises in accumulation; D at Cmax above about 0.1.
- `impedance_convert` with `series_r: accumulation` reports `rs` of tens of Ohm or more; Cp-G and Cs-Rs of the
  same point disagree by more than D^2.
- `cv_cox` low against the geometry, `cf_dispersion`/`dit_conductance` Dit growing at the high frequencies, a
  split C-V (`mosfet.cgc_cv`) that rises late or stays below Cox W L (channel resistance of a long channel).

## Likely causes

1. Substrate or well resistance (lightly doped or thick wafer) between the depletion edge and the back contact.
2. Back contact: no chuck vacuum, oxide or resist on the backside, a top-side substrate pad far away or worn.
3. Probe contact resistance (worn tip, pad oxide), more with a light touch-down.
4. A missing or stale short correction (cable and probe resistance and inductance; runbook
   `cmu-correction-stale`); a long channel's distributed RC in split C-V.
- Why: the measured parallel pair of `C` behind `Rs` is `Cp = C / (1 + (w Rs C)^2)` and `G = w^2 Rs C^2 / (1 +
  (w Rs C)^2)`; with C = 69 pF at 1 MHz (`1/(wC)` = 2.3 kOhm) 230 Ohm cut Cp by 1 %, at 100 kHz by 0.01 %.

## First safe checks

1. `get_run(run_id, include=[summary, quality])`, then `impedance_convert(run_id, {series_r: accumulation})` at each
   frequency of the run: `rs = G/(G^2 + w^2 Cp^2)` at the largest C (Nicollian & Brews eq. 5.12). The same `rs` at
   every frequency is a series resistance; one that changes with frequency is not (traps, leakage: runbook
   [cmu-cv-distortion](cmu-cv-distortion.md)).
2. The last short correction: `short_rs_ohm` in its `kind_result` (cable and probe, below about 1 Ohm) and its age
   in `station_status.corrections`.
3. A validated re-run at a lower frequency (100 kHz; correction frequencies listed) or `moscap.cf` at an
   accumulation bias: Cp recovers towards Cox when Rs is the cause.
4. Correct the extraction, not the data: `options.rs_ohm` = the `rs` found, in `cv_cox`, `cv_flatband`,
   `cv_doping_profile`, `cf_dispersion`, `dit_conductance`; report both values, the method and `rs_ohm` used.
5. Split C-V of a long channel: 100 kHz or lower, and source and drain both on the Low side (card `mosfet-split-cv`).

## Physical checks to ask the human

- Chuck vacuum on, wafer flat, backside clean or metallised? Is the substrate contacted through the chuck or a
  top-side pad, and how far from the device?
- Probe tips clean and landed firmly (scrub mark visible)? Re-land on fresh pads if unsure, then corrections anew.
- Same cables as the corrections, the four-terminal pair kept to the probes (EX p320 (4-26))?

## Do not

- Report Cox or Dit from high-frequency data with Rs uncorrected, or subtract an `rs` that varies with frequency.
- Pick the frequency or `rs_ohm` that hits an expected Cox; raise the AC level (Rs does not depend on it).
- Edit the short correction record or skip the short correction to "remove" the resistance.

## Stop and call safe_shutdown

- `rs` grows from run to run on the same device (probe or pad damage), MFCMU status `U`/`D`, errors 320-323, a fault
  or `cleanup_unverified`: `safe_shutdown(reason)`, report what changed, hand over to the human.
