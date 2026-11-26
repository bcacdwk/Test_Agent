---
id: cmu-cv-distortion
title: C-V curve distorted (Cmax above Cox, stretch-out, humps, deep depletion, branches apart, status U/D)
maturity: seed
sources: [general practice (triage order; not checked against a source), example case example-cv-shape-abnormal (illustrative), PG p52 (1-32) CMU status, PG p251 (3-71) data correction, PG p348 (4-30) MFCMU ranges, EX p320 (4-26) four-terminal pair and error correction, "Nicollian & Brews, MOS Physics and Technology (1982): chapter numbers not checked, TODO(cite)", src/b1500_test_agent/analysis/cv.py and cv_variants.py (WP8.3-8.4), catalog/kinds/cmu_correction.py (correction data read-back, WP8.6)]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# C-V distortion (MFCMU, `cmu_measure` runs)

## Symptom

- `moscap.cv`, `mosfet.cgc_cv`/`cgd_cv`, `fecap.cv_butterfly` or `cmu.spot`: Cmax above the expected Cox (from the
  human's area and oxide thickness or EOT: ask; the DUT profile's nominal values are examples, not expectations), a
  stretched or humped depletion, a kink or step, C below Cmin in inversion, negative C or G, the two branches of a
  double sweep far apart, scatter at small C.
- `quality_report` or the run's status counts show MFCMU `U`/`D`/`V`; `cv_cox`, `cv_flatband` or
  `cv_doping_profile` refuse or warn; `cv_ac_dependence` gives an `ac_limit` below the AC level of the C-V.
- The correction runs read implausible data back (their `kind_result`): `open_cp_f` far above the station's open
  value (the probes were on a device during the open correction) or `short_rs_ohm` far above its short value (they
  were not on the short); both are recorded at bring-up L6 (`TODO(verify)[L6.A2]`), until then compare with earlier
  correction runs on this station.

## Likely causes

1. Corrections that do not fit this landing: measured with the wrong probe state, another pin map or landing, or
   a frequency of the plan not in the list (then an offset of about the open stray C). Runbook `cmu-correction-stale`.
2. Series resistance (substrate, back contact, probe): Cp falls at high f in accumulation. Runbook
   [cmu-series-resistance](cmu-series-resistance.md).
3. Gate leakage: a large G (D above 1, a rule of thumb not checked against a source) makes Cp unreliable, mostly in
   accumulation and inversion (simulator example (scenario `moscap_leaky`), not a real-device value: at 1 kHz Cp
   rises above Cox and loses its plateau, normal at 1 MHz).
4. AC level too large for a curved C-V: the swing averages the transition (C = C0 + C'' Vac^2 / 4, Vac in rms).
5. Sweep history: from accumulation into inversion (or too fast) drives deep depletion; a light leak generates
   carriers; border traps or mobile ions split the double sweep (hysteresis larger than the repeatability of the
   same double sweep on this landing; a technology threshold needs a source, `TODO(cite)`).
6. MFCMU status `U` (NULL loop unbalance) or `D` (IV amplifier saturation): range, too low an impedance at high
   frequency, a poor contact (PG p52 (1-32)); the Low terminal on the chuck picks up stray C (EX p320 (4-26)).
7. Only after 1-6: the device (interface traps stretch the depletion and depend on frequency; fixed charge shifts).

## First safe checks

Order (general practice, not a recorded lab procedure; example case `example-cv-shape-abnormal`, illustrative):
redo the corrections, lower the AC level, then measure the gate leakage first.

1. `get_run(run_id, include=[summary, quality, audit])`: status counts, the summary's `corr` age, the plan's
   frequencies and AC level; `get_run` of the last correction runs: result, `open_cp_f`, `short_rs_ohm`.
2. `plot_cv` (C and G/w, 1/C^2): where the distortion sits (accumulation, depletion, inversion).
3. `impedance_convert` with `series_r: accumulation`: `rs` and D at Cmax (above about 0.1, a rule of thumb not
   checked against a source: series R or leakage).
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
