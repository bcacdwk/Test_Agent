---
id: moscap-cf-ct
title: MOS capacitor C-f and C-t — frequency dispersion (Dit, trap time constant), deep-depletion recovery
family: cmu
intent: [C-f, frequency dispersion, conductance Gp/w, Dit, interface traps, trap time constant, C-t, transient, deep depletion, recovery, generation, inversion layer formation]
recipes: [moscap.cf, moscap.ct]
device_types: [moscap]
modules: [MFCMU]
routes: [scuu:cmu]
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#c-f-and-frequency-dispersion, knowledge/08-capacitance-cv.md#c-t-and-deep-depletion-recovery, knowledge/08-capacitance-cv.md#corrections-and-the-measurement-path, knowledge/08-capacitance-cv.md#high-frequency-c-v-of-a-mos-capacitor]
manual: ['PG p275 (3-95) "C-f Sweep"', 'PG p550 (4-232) "WFC"', 'PG p126 (2-38) "C-f Sweep"', 'PG p280 (3-100) "C-t Sampling"', 'PG p467 (4-149) "MDCV"', 'PG p476 (4-158) "MTDCV"', 'PG p348 (4-30) "Setting resolution"']
debug: [cmu-correction-stale, cmu-series-resistance, cmu-cv-distortion, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 2.7 (kind cmu_measure MM 22/26), blueprint v2 2.10 (cf_dispersion), blueprint v2 3.2 (moscap.cf, moscap.ct), blueprint v2 4.2 (moscap Dit, deep depletion)]
version: 1
---

# MOS capacitor C-f and C-t

## 1. Purpose and applicable devices

Two time/frequency views of a MOS capacitor at one gate bias:

- `moscap.cf` (MM 22): Cp-G over a frequency list at a depletion bias. Interface traps follow the signal only below
  `1/(2 pi tau)`: C rises and the trap conductance `Gp/w` peaks at low frequency. Gives Dit at that bias's energy,
  the trap time constant and the dispersion. The list IS the sweep (log or linear stair).
- `moscap.ct` (MM 26): Cp after a step from `v_base` (accumulation) to `v_bias` (inversion side), sampled in time:
  deep depletion (C below the HF minimum) recovering as the inversion layer forms (generation). Long transients run
  as chained blocks with progress and cancel.
- Not for: C-V (`moscap-cv`), Dit over the band gap from many biases or QSCV (card `moscap-dit`), oxide leakage
  (`gate-leakage`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (cmu_high) | MFCMU High (`7H`, or `SCUU1.OUT1`) | DC bias, AC drive |
| bulk | `bulk` (cmu_low) | MFCMU Low (`7L`, or `SCUU1.OUT2`) | substrate / back contact |

Pin map `moscap-cmu` (direct) or `moscap-scuu` (through SCUU1: the simulator's `moscap_dit` lands this way, so QSCV
and C-V share one landing, card `moscap-dit`), DUT `moscap-generic` (`geometry.area_um2` and `tox_nm` for Dit and the
geometry Cox).

- Routes per phase: none with `moscap-cmu`; with `moscap-scuu`: measure `SCUU1.OUT1/OUT2 -> cmu`, then rest;
  cleanup: rest.

## 3. Pre-run checklist

- A `moscap.cv` first: Cox (`cv_cox`), Vfb and Vth; choose the C-f bias between Vfb and Vth (depletion) and the C-t
  levels (base below Vfb, bias beyond Vth), inside the DUT envelope.
- **Corrections cover every frequency**: the C-f list holds points the 23 default correction frequencies lack, so
  run `cmu.correction_open` and `cmu.correction_short` with `freqs_hz` = the C-f list (plus any C-V frequency) after
  the phase compensation (card `cmu-correction`); the list rewrite clears the older corrections of that MFCMU.
- `station_status.corrections` fresh with this pin map; R-CORR-01 names the first uncovered frequency.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `freqs_hz` (`moscap.cf`) | [1000, 1778.279, 3162.278, 5623.413, 10000, 17782.79, 31622.78, 56234.13, 100000, 177827.9, 316227.8, 562341.3, 1000000] Hz | 1 kHz..1 MHz | 1 kHz..5 MHz | 4 per decade log stair | the sweep; correction list |
| `freqs_hz` (`moscap.ct`) | [1000] kHz | 100 kHz..1 MHz | 1 kHz..5 MHz | HF: minority carriers do not follow | one transient each |
| `ac_vrms` | 30 mV | 10..50 mV | 10..250 mV | small signal | above 50 mV: `soft_cmu` |
| `dc_v` | -0.6 V | -3..3 V | -25..25 V | depletion: traps respond | picks the trap energy |
| `sweep_mode` | single | single | single, double | double: up and down | 2 x points |
| `hold_s` | 1 s | 0.5..5 s | 0..60 s | settle at the bias | WTFC hold |
| `delay_s` | 0 s | 0..0.1 s | 0..10 s | settle per frequency | WTFC delay |
| `integration` (`moscap.cf`) | medium | medium | short, medium, long | averaging | long for small G |
| `v_base` | -2.5 V | -3..3 V | -25..25 V | accumulation: no inversion charge | level before the step |
| `v_bias` | 2 V | -3..3 V | -25..25 V | inversion side | deep depletion depth |
| `interval_s` | 20 ms | 10 ms..1 s | 8 ms..655.35 s | >= one measurement time | 1 ms grid |
| `points` | 301 | 101..2001 | 10..10001 | about 10 x the recovery time | > 60 s: chained blocks |
| `hold_bias_s` | 0 s | 0..0.1 s | 0..655.35 s | first sample at the step | 10 ms grid |
| `hold_base_s` | 1 s | 0.5..10 s | 0..655.35 s | empty the inversion layer | 10 ms grid |
| `integration` (`moscap.ct`) | short | short | short, medium, long | 8 ms fits the interval | per sample |

A log list: `f_k = f_1 (f_n/f_1)^(k/(n-1))`, each value at the MFCMU resolution (1 mHz below 10 kHz, 10 mHz below
100 kHz, 0.1 Hz below 1 MHz, 1 Hz above; PG p348 Table 4-18); 2..64 points.

Example plan (validated on the simulator by `b1500 dev lint-skills`, corrections over the C-f list first):

```yaml
recipe_id: moscap.cf
params: {}
pin_map: moscap-scuu
dut_profile: moscap-generic
sim_scenario: moscap_dit
```

## 5. Limits and confirmation

- R-CMU-01 (1 kHz..5 MHz, 10..250 mVrms, |DC| <= 25 V, DUT `ac.max_vrms`; `soft_cmu` above 10 V or 50 mVrms);
  R-DUT-01: bias, base and step levels within `max_abs_v`; the MFCMU's nominal AC current above a terminal's
  `max_abs_i` adds `dut_envelope` (explain it: an intact oxide draws only leakage).
- R-CORR-01 at every listed frequency (next step card `cmu-correction`); `unverified_pin_map`, on hardware
  `first_hw_run`. C-t over `max_sync_run_s` (300 s) runs async (`get_run` progress, cancel `safe_shutdown`); over
  `long_run_confirm_s` needs `long_run`. Not destructive.

## 6. Quality criteria

- MFCMU status `N` only; `U`/`D`/`V` untrusted (a C-f sweep aborts automatically); re-measure.
- C-f: C falls with frequency in depletion; G/w rises to a peak inside the list. C-t: C rises monotonically to a
  plateau; no plateau means the record is too short (`points` x `interval_s`).

## 7. Analysis method

`moscap.cf`: `cf_dispersion` (Gp/w = w Cox^2 Gm / (Gm^2 + w^2 (Cox - Cm)^2), continuum fit): `dit`, `tau_it`,
`f_peak`, `gp_w_max`, `c_dispersion`. Cox from the geometry (EOT estimate, warned) unless `options.cox_f` = the
`cv_cox` result; `rs_ohm` removes a series resistance; `model: single` for one trap level. A peak outside the list
fails: move the bias. `moscap.ct`: `ct_recovery` (1/C^2 relaxation): `tau_recovery`, `beta`, `c_initial`, `c_final`.
`plot_cv` draws C against frequency or time. Report every value as derived with method and window; SIMULATED.

## 8. Expected result shape

| quantity | typical (5 nm SiO2, p 1e17, Dit 2e11) | red flags |
|---|---|---|
| `dit` | 1e10..1e12 cm^-2 eV^-1 | > 1e13: leakage or series R, not traps |
| `f_peak` | 1 kHz..1 MHz, lower towards midgap | at a list end: move the bias |
| `c_dispersion` | 0.01..0.3 | < 0: series R at high f (use `rs_ohm`) |
| `tau_recovery` | ms..minutes (generation lifetime) | no recovery: leaky oxide or a too-short record |
| `c_initial` / `c_final` | 0.5..0.9 | > 1: the bias is not in inversion |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked by R-CORR-01 "does not cover" | correction list lacks a C-f point | run open/short with the C-f list | `cmu-correction-stale` |
| invalid plan "equally spaced" | the list is not one log/linear stair | rebuild the list (section 4) | `errx-codes` |
| `dit` failed: peak outside | bias too near midgap or flatband | `moscap.cv`, pick a depletion bias | `noisy-data` |
| scattered G/w, negative G | noise, uncorrected path | integration long, corrections | `cmu-cv-distortion` |
| C and Dit drift at the top frequencies | series resistance | `impedance_convert` (`series_r`) | `cmu-series-resistance` |
| fault latched after a cancel | interrupted cleanup | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | moscap_dit | moscap-generic | S20261124T054018Z-fdba | `moscap.cf`: Dit -3.4 %, tau -0.5 % of the model at -0.6 V | - |
| sim | 2026-11-24 | moscap_dit | moscap-generic | S20261124T054018Z-6252 | `moscap.ct`: tau -0.2 %, C_final -0.3 % | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim rows: the example requests after the corrections over the C-f list through `B1500Service` (temporary config
and data dirs; folders not kept; `tests/integration/test_recipes_cv_variants.py` repeats them).
Hardware records: `validation/hw/moscap.cf.yaml`, `validation/hw/moscap.ct.yaml` (reviewed by a human after stage L6,
skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
