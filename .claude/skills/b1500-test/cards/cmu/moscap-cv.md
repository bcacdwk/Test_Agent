---
id: moscap-cv
title: MOS capacitor C-V — Cox, EOT, Nsub, Vfb, Vth, hysteresis; AC-level sweep; pulsed C-V
family: cmu
intent: [C-V, MOS capacitor, Cox, EOT, flatband Vfb, doping Nsub, hysteresis, SCUU same landing, AC level, small signal, pulsed C-V, deep depletion]
recipes: [moscap.cv, moscap.cv_ac_level, moscap.pulsed_cv]
device_types: [moscap]
modules: [MFCMU]
routes: [scuu:cmu]
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#high-frequency-c-v-of-a-mos-capacitor, knowledge/08-capacitance-cv.md#oxide-capacitance-and-eot, knowledge/08-capacitance-cv.md#doping-from-1c2, knowledge/08-capacitance-cv.md#flatband-voltage, knowledge/08-capacitance-cv.md#scuu-same-landing-i-v-and-c-v, knowledge/08-capacitance-cv.md#ac-level-dependence, knowledge/08-capacitance-cv.md#pulsed-c-v]
manual: ['PG p256 (3-76) "CV (DC Bias) Sweep"', 'PG p549 (4-231) "WDCV"', 'PG p554 (4-236) "WMDCV"', 'PG p520 (4-202) "SSP"', 'AN-CV p6 (6) "SCUU"', 'PG p270 (3-90) "CV (AC Level) Sweep"', 'PG p547 (4-229) "WACV"', 'PG p265 (3-85) "Pulsed Sweep CV"', 'PG p487 (4-169) "PTDCV"', 'PG p489 (4-171) "PWDCV"']
debug: [cmu-correction-stale, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 2.7, blueprint v2 2.10 (cv.py), blueprint v2 3.2 (moscap.cv, cv_ac_level, pulsed_cv), blueprint v2 4.2 (moscap)]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# MOS capacitor C-V

## 1. Purpose and applicable devices

High-frequency C-V (Cp-G) of a MOS capacitor: Cox and EOT, substrate doping, flatband and threshold voltage, and
with a double sweep the hysteresis (`moscap.cv`, one sweep per frequency of `freqs_hz`). Two variants:

- `moscap.cv_ac_level` (MM 23): C at one bias while the oscillator level steps up: the largest level that stays in
  the small-signal regime (C moves as `C0 + C'' Vac^2/4` on a curved C-V).
- `moscap.pulsed_cv` (MM 20; one point = pulsed spot C, MM 19): the gate rests at `v_base` and is pulsed to each
  level; a pulse is too short for the inversion layer (deep depletion) and every point starts from the base's trap
  state (trap-free C-V when the base empties the traps).
- Not for: a MOSFET's gate capacitance (`mosfet-split-cv`), one point (`cmu-spot`), C-f or C-t (`moscap-cf-ct`),
  gate leakage (`gate-leakage`; run it first on a new oxide).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (cmu_high) | MFCMU High (`7H`) | DC bias (sweep, level or pulses) and AC drive |
| bulk | `bulk` (cmu_low) | MFCMU Low (`7L`) | substrate / back contact |

Example pin map `moscap-cmu`, DUT `moscap-generic` (its `geometry.area_um2` is needed for Nsub, Vfb, Vth, EOT).

- Routes per phase: none with `moscap-cmu`; through an SCUU: measure `SCUU1.OUT1/OUT2 -> cmu`, then rest; cleanup:
  rest.

### SCUU same-landing I-V and C-V

With an SCUU the pads reach the MFCMU and two SMUs without re-landing (pin map `moscap-scuu`: gate `SCUU1.OUT1`,
bulk `SCUU1.OUT2`); the human records `present: true` for SCUU1. Corrections run with the same SCUU pin map; the run
switches `SSP 7,4` for the measurement and back to rest after it (verified by the cleanup); the SCUU's SMUs never
take `CN`. I-V (leakage) on the same landing uses a map with the outputs as SMU terminals.

## 3. Pre-run checklist

- Gate leakage below about 1 nA (`gate-leakage`); `station_status.corrections` fresh with this pin map at every
  frequency, else card `cmu-correction`.
- Ask: substrate type (p: accumulation at negative bias) and the DUT envelope; DC sweep from inversion to accumulation
  (p: `v_start` > 0 > `v_stop`); pulsed base in accumulation; AC-level `ac_stop` within the DUT `ac.max_vrms`.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `freqs_hz` | [1000] kHz | 100 kHz..1 MHz | 1 kHz..5 MHz | HF C-V; in the correction list | one sweep each |
| `ac_vrms` | 30 mV | 10..50 mV | 10..250 mV | small signal | above 50 mV: `soft_cmu` |
| `v_start` (`moscap.cv`) | 2 V | -3..3 V | -25..25 V | start in inversion | hold settles it |
| `v_stop` (`moscap.cv`) | -2.5 V | -3..3 V | -25..25 V | strong accumulation | Cox extrapolation |
| `points` (`moscap.cv`) | 91 | 51..201 | 11..1001 | >= 5 points in depletion | step = span/(points-1) |
| `sweep_mode` | single | single | single, double | double: hysteresis, both ways | 2 x points |
| `hold_s` (`moscap.cv`, `moscap.pulsed_cv`) | 1 s | 0.5..5 s | 0..60 s | settle at the start/base | hold |
| `delay_s` (`moscap.cv`, `moscap.cv_ac_level`) | 0 s | 0..0.1 s | 0..10 s | slow traps | per step |
| `integration` (`moscap.cv`, `moscap.cv_ac_level`) | medium | medium | short, medium, long | averaging | long: small C |
| `ac_start` | 10 mV | 10..30 mV | 10..250 mV | small-signal end | first level |
| `ac_stop` | 100 mV | 50..100 mV | 10..250 mV | DUT `ac` envelope | last level |
| `points` (`moscap.cv_ac_level`) | 10 | 5..25 | 2..1001 | >= 3 levels | levels per sweep |
| `ac_sweep` | linear | linear | linear, log | level spacing | WACV mode |
| `dc_v` | -0.6 V | -3..3 V | -25..25 V | a depletion bias (curved C-V) | the bias tested |
| `hold_s` (`moscap.cv_ac_level`) | 0.5 s | 0..2 s | 0..60 s | settle at the bias | hold |
| `v_base` | -2.5 V | -3..3 V | -25..25 V | accumulation: traps emptied | between pulses |
| `v_start` (`moscap.pulsed_cv`) | -2.5 V | -3..3 V | -25..25 V | first pulse level | PWDCV start |
| `v_stop` (`moscap.pulsed_cv`) | 2 V | -3..3 V | -25..25 V | into inversion | deep depletion there |
| `points` (`moscap.pulsed_cv`) | 91 | 51..201 | 1..1001 | 1 = pulsed spot C (MM 19) | one pulse each |
| `width_s` | 10 ms | 8..100 ms | 8 ms..10 s | >= 8/10/50 ms (> 200 kHz/<= 200 kHz/<= 10 kHz) | PTDCV width |
| `period_s` | 0 s | 0..0.2 s | 0..20 s | 0 = width + 2 ms | PTDCV period |
| `integration` (`moscap.pulsed_cv`) | short | short | short, medium, long | 8 ms fits the pulse | read at the pulse end |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: moscap.cv
params: {}
pin_map: moscap-cmu
dut_profile: moscap-generic
sim_scenario: moscap_basic
```

## 5. Limits and confirmation

- R-CMU-01 (1 kHz..5 MHz, 10..250 mVrms, |DC| <= 25 V, DUT `ac.max_vrms`; `soft_cmu` above 10 V or 50 mVrms, so
  the default AC-level sweep to 100 mVrms needs it); R-DUT-01: every DC level (sweep, pulse base and levels) within
  the gate's `max_abs_v`; the MFCMU has no compliance: its nominal AC current `sqrt(2) x Vac / 50 Ohm` above a
  terminal's `max_abs_i` adds `dut_envelope` (an intact oxide draws only leakage).
- R-CORR-01 blocks without fresh corrections (next step card `cmu-correction`). `unverified_pin_map`,
  `unverified_topology` (SCUU), on hardware `first_hw_run`. Not destructive; sync (about 2 s per 91 points).

## 6. Quality criteria

- MFCMU status `N` only; `U`/`D`/`V` untrusted (automatic abort: the rest of the sweep is invalid); re-measure.
- Shape: C flat near Cmax in accumulation, monotonic through depletion, flat Cmin in inversion (pulsed: below Cmin).

## 7. Analysis method

`moscap.cv`: `cv_cox` (accumulation extrapolation, EOT), `cv_doping_profile` (1/C^2), `cv_flatband`, `cv_vth`; double
sweep `cv_hysteresis`; series R `impedance_convert` (`series_r: accumulation`), then `rs_ohm`. `moscap.cv_ac_level`:
`cv_ac_dependence` (C0, curvature, `ac_limit` at 1 %). `moscap.pulsed_cv`: `cv_cox`, `cv_flatband`,
`cv_doping_profile`, and `cv_pulsed_vs_dc` with `options.reference_run` = a `moscap.cv` swept from accumulation
(`delta_vfb`, `cox_ratio`, `c_ratio_inversion`). `plot_cv` for any. Report values as derived; Cmax is not Cox.

## 8. Expected result shape

| quantity | typical (5 nm SiO2, 1e4 um^2, p 1e17) | red flags |
|---|---|---|
| Cmax / Cox | 0.95..0.98 | > 1: correction or area wrong |
| Cmin / Cox | 0.1..0.3 | C below Cmin in a DC sweep: deep depletion |
| hysteresis | < 20 mV for a good oxide | > 100 mV: mobile ions or trapping |
| `ac_limit` | 30..100 mVrms in depletion | < 10 mVrms: very curved C-V; keep `ac_vrms` below it |
| pulsed vs DC | `delta_vfb` ~0, `c_ratio_inversion` < 1 | `delta_vfb` = hysteresis when DC started in inversion |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked by R-CORR-01 | corrections missing, stale, other pin map, frequency | `station_status.corrections` | `cmu-correction-stale` |
| stretched or humped curve | interface traps, leakage, series R | G/w plot, leakage, `impedance_convert` | `noisy-data` |
| `U`/`D` status, sweep aborted; invalid pulse width | range, contact, leakage; width < 8/10/50 ms | `get_run` audit; `width_s` | `errx-codes` |
| fault latched, SCUU not at rest | interrupted run, SSP failure | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | moscap_basic | moscap-generic | S20261122T094617Z-1dba | `moscap.cv`: Cox +0.16 %, Vfb -0.6 mV, Nsub +0.23 % of the model | - |
| sim | 2026-11-24 | moscap_basic | moscap-generic | S20261124T054019Z-50a4 | `moscap.cv_ac_level`: C0 -0.01 % of the model, ac_limit 61 mVrms | - |
| sim | 2026-11-24 | moscap_basic | moscap-generic | S20261124T054019Z-646b | `moscap.pulsed_cv`: Cox +0.07 %, Vfb -0.5 mV, Nsub -0.03 % | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim rows: after the three corrections through `B1500Service` (`tests/integration/test_recipes_cv*.py`). Hardware:
`validation/hw/moscap.cv.yaml`, `validation/hw/moscap.cv_ac_level.yaml`, `validation/hw/moscap.pulsed_cv.yaml`
(reviewed by a human after stage L6, skill `b1500-bringup`; drafts only from hardware `H...` runs).
