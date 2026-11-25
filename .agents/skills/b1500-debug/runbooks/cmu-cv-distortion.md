---
id: cmu-cv-distortion
title: C-V curve distorted (Cmax above Cox, stretch-out, humps, deep depletion, branches apart, status U/D)
maturity: seed
sources: [PG p52 (1-32) CMU status, PG p251 (3-71) data correction, PG p348 (4-30) MFCMU ranges, EX p320 (4-26) four-terminal pair and error correction, Nicollian & Brews (1982) ch. 5 and 9, src/b1500_test_agent/analysis/cv.py and cv_variants.py (WP8.3-8.4), catalog/kinds/cmu_correction.py (correction data read-back, WP8.6)]
---

# C-V distortion (MFCMU, `cmu_measure` runs)

## Symptom

- `moscap.cv`, `mosfet.cgc_cv`/`cgd_cv`, `fecap.cv_butterfly` or `cmu.spot`: Cmax above the expected Cox, a
  stretched or humped depletion, a kink or step, C below Cmin in inversion, negative C or G, a curve far from the
  DUT profile's nominal values, the two branches of a double sweep far apart, scatter at small C.
- `quality_report` or the run's status counts show MFCMU `U`/`D`/`V`; `cv_cox`, `cv_flatband` or
  `cv_doping_profile` refuse or warn; `cv_ac_dependence` gives an `ac_limit` below the AC level of the C-V.
- The correction runs read implausible data back (their `kind_result`): `open_cp_f` of tens of pF (the probes were
  on a device during the open correction) or `short_rs_ohm` of hundreds of Ohm (they were not on the short).

## Likely causes

1. Corrections that do not fit this landing: measured with the wrong probe state, another pin map or landing, or
   a frequency of the plan not in the list (then an offset of about the open stray C). Runbook `cmu-correction-stale`.
2. Series resistance (substrate, back contact, probe): Cp falls at high f in accumulation. Runbook
   [cmu-series-resistance](cmu-series-resistance.md).
3. Gate leakage: a large G (D above 1) makes Cp unreliable, mostly in accumulation and inversion.
4. AC level too large for a curved C-V: the swing averages the transition (C = C0 + C'' Vac^2 / 4).
5. Sweep history: from accumulation into inversion (or too fast) drives deep depletion; a light leak generates
   carriers; border traps or mobile ions split the double sweep (hysteresis above about 100 mV).
6. MFCMU status `U` (NULL loop unbalance) or `D` (IV amplifier saturation): range, too low an impedance at high
   frequency, a poor contact (PG p52 (1-32)); the Low terminal on the chuck picks up stray C (EX p320 (4-26)).
7. Only after 1-6: the device (interface traps stretch the depletion and depend on frequency; fixed charge shifts).

## First safe checks

1. `get_run(run_id, include=[summary, quality, audit])`: status counts, the summary's `corr` age, the plan's
   frequencies and AC level; `get_run` of the last correction runs: result, `open_cp_f`, `short_rs_ohm`.
2. `plot_cv` (C and G/w, 1/C^2): where the distortion sits (accumulation, depletion, inversion).
3. `impedance_convert` with `series_r: accumulation`: `rs` and D at Cmax (above about 0.1: series R or leakage).
4. One change per re-run, each a validated plan inside the card's ranges: a lower frequency (100 kHz), the default
   AC level, a sweep from inversion to accumulation with `hold_s`; `moscap.cv_ac_level` at the distorted bias
   (`ac_limit`); a double sweep (`cv_hysteresis`); `moscap.cf` at a depletion bias (traps: `cf_dispersion`).
5. Gate leakage: card `gate-leakage` on an SMU landing, or the QSCV run's `leakage_max_a`.

## Physical checks to ask the human

- Probes on the right pads and unchanged since the corrections? Which terminal is on the chuck (High is the one to
  connect there, EX p320 (4-26))? Back contact: chuck vacuum on, backside clean or metallised?
- Shield box closed and dark? Cable shields joined close to the probes (four-terminal pair kept to the DUT)?
- During the open correction were the probes really lifted, during the short really on the short?

## Do not

- Narrow a fit window, pick a frequency or tune `rs_ohm` until Cox or Vfb meets an expected value.
- Report Cmax as Cox, a deep-depletion branch as the HF curve, or values from `U`/`D`/`V` points (no `force`).
- Raise the AC level above `ac_limit` to cut the noise, or skip and edit corrections (`data/state/corrections/`).

## Stop and call safe_shutdown

- `U`/`D` on the known capacitor (card `cmu-spot`) right after fresh corrections, errors 320-323 (runbook
  `errx-codes`), a fault or `cleanup_unverified` (runbook `cleanup-failed-fault`).
- The C-V of the same device changes from run to run with nothing changed (damage, breakdown): stop, hand over.
