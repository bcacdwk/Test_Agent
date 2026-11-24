---
id: moscap-cv
title: MOS capacitor C-V — Cox, EOT, Nsub, Vfb, Vth, hysteresis (Cp-G DC bias sweep)
family: cmu
intent: [C-V, MOS capacitor, MOS-C, Cox, EOT, flatband, Vfb, doping, Nsub, 1/C^2, hysteresis, SCUU same landing]
recipes: [moscap.cv]
device_types: [moscap]
modules: [MFCMU]
routes: [scuu:cmu]
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#high-frequency-c-v-of-a-mos-capacitor, knowledge/08-capacitance-cv.md#oxide-capacitance-and-eot, knowledge/08-capacitance-cv.md#doping-from-1c2, knowledge/08-capacitance-cv.md#flatband-voltage, knowledge/08-capacitance-cv.md#scuu-same-landing-i-v-and-c-v]
manual: ['PG p256 (3-76) "CV (DC Bias) Sweep"', 'PG p549 (4-231) "WDCV"', 'PG p566 (4-248) "WTDCV"', 'PG p554 (4-236) "WMDCV"', 'PG p520 (4-202) "SSP"', 'AN-CV p6 (6) "SCUU"']
debug: [cmu-correction-stale, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 2.7, blueprint v2 2.10 (cv.py), blueprint v2 3.2 (moscap.cv), blueprint v2 4.2 (moscap)]
version: 1
---

# MOS capacitor C-V

## 1. Purpose and applicable devices

High-frequency C-V (Cp-G) of a MOS capacitor: Cox and EOT, substrate doping, flatband and threshold voltage, and
with a double sweep the hysteresis. One sweep per frequency of `freqs_hz`.

- Not for: a MOSFET's gate capacitance (`mosfet-split-cv`), one capacitance point (`cmu-spot`), gate leakage
  (`gate-leakage`; run it first on a new oxide).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (cmu_high) | MFCMU High (`7H`) | DC bias sweep and AC drive |
| bulk | `bulk` (cmu_low) | MFCMU Low (`7L`) | substrate / back contact |

Example pin map `moscap-cmu`, DUT `moscap-generic` (its `geometry.area_um2` is needed for Nsub, Vfb, Vth, EOT).

- Routes per phase: none with `moscap-cmu`; through an SCUU: measure `SCUU1.OUT1/OUT2 -> cmu`, then rest; cleanup:
  rest.

### SCUU same-landing I-V and C-V

With an SCUU the gate and bulk pads reach both the MFCMU and two SMUs without re-landing (pin map `moscap-scuu`:
gate `SCUU1.OUT1`, bulk `SCUU1.OUT2`). Ask the human to record `present: true` for SCUU1 in the station profile;
corrections run with the same SCUU pin map (they include the SCUU path); the run switches `SSP 7,4` (MFCMU) for
the sweep and back to the SCUU's rest state after it, and the cleanup verifies the rest state. The SCUU's SMUs are
never in `CN`. Run I-V (leakage) on the same landing through a map that uses the outputs as SMU terminals.

## 3. Pre-run checklist

- Gate leakage of this oxide below about 1 nA in the bias range (`gate-leakage`): leakage distorts C-V.
- `station_status.corrections` fresh with this pin map at every frequency; else card `cmu-correction`.
- Ask: substrate type (p: accumulation at negative gate bias) and the DUT envelope; sweep from inversion to
  accumulation (p substrate: positive `v_start`, negative `v_stop`) to avoid deep depletion.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `freqs_hz` | [1000] kHz | 100 kHz..1 MHz | 1 kHz..5 MHz | HF C-V; in the correction list | one sweep each |
| `ac_vrms` | 30 mV | 10..50 mV | 10..250 mV | small signal | above 50 mV: `soft_cmu` |
| `v_start` | 2 V | -3..3 V | -25..25 V | start in inversion | hold settles the inversion layer |
| `v_stop` | -2.5 V | -3..3 V | -25..25 V | end in strong accumulation | Cox extrapolation needs it |
| `points` | 91 | 51..201 | 11..1001 | at least 5 points in depletion | step = span/(points-1) |
| `sweep_mode` | single | single | single, double | double for hysteresis | 2 x points steps |
| `hold_s` | 1 s | 0.5..5 s | 0..60 s | settle at `v_start` | WTDCV hold |
| `delay_s` | 0 s | 0..0.1 s | 0..10 s | slow traps, return branch | WTDCV delay |
| `integration` | medium | medium | short, medium, long | MFCMU averaging | long for small C |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: moscap.cv
params: {}
pin_map: moscap-cmu
dut_profile: moscap-generic
sim_scenario: moscap_basic
```

## 5. Limits and confirmation

- R-CMU-01 (1 kHz..5 MHz, 10..250 mVrms, |DC| <= 25 V, DUT `ac.max_vrms`; `soft_cmu` above 10 V or 50 mVrms);
  R-DUT-01: the sweep range within the gate's `max_abs_v`; the MFCMU has no compliance, its nominal short-circuit
  AC current `sqrt(2) x Vac / 50 Ohm` above a terminal's `max_abs_i` adds `dut_envelope` (explain it: a C-V of an
  intact oxide draws only leakage).
- R-CORR-01 blocks without fresh corrections (next step card `cmu-correction`). `unverified_pin_map`,
  `unverified_topology` (SCUU), on hardware `first_hw_run`. Not destructive; sync (about 2 s per 91 points).

## 6. Quality criteria

- MFCMU status `N` only; `U`/`D`/`V` untrusted (automatic abort: the rest of the sweep is invalid); re-measure.
- Shape: C flat near Cmax in accumulation, monotonic through depletion, flat Cmin in inversion; G/w small.

## 7. Analysis method

Defaults: `cv_cox` (accumulation extrapolation, EOT), `cv_doping_profile` (1/C^2 slope in depletion),
`cv_flatband` (flatband capacitance), `cv_vth` (from Cox, Nsub, Vfb). Double sweep: `cv_hysteresis`.
Series resistance: `impedance_convert` (`series_r: accumulation`), then `rs_ohm` on the C-V methods. `plot_cv` for
C-V and 1/C^2. Report each value as derived with its window; Cmax is not Cox.

## 8. Expected result shape

| quantity | typical (5 nm SiO2, 1e4 um^2, p 1e17) | red flags |
|---|---|---|
| Cmax / Cox | 0.95..0.98 | > 1: correction or area wrong |
| Cmin / Cox | 0.1..0.3 | C below Cmin in inversion: deep depletion |
| Nsub | 1e15..1e18 cm^-3 | depth-dependent: non-uniform doping, traps |
| hysteresis | < 20 mV for a good oxide | > 100 mV: mobile ions or trapping |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked by R-CORR-01 | corrections missing, stale, other pin map, frequency | `station_status.corrections` | `cmu-correction-stale` |
| stretched or humped curve | interface traps, leakage, series R | G/w plot, leakage, `impedance_convert` | `noisy-data` |
| `U`/`D` status, sweep aborted | range, contact, large leakage | `get_run` audit; `quality_report` | `errx-codes` |
| fault latched, SCUU not at rest | interrupted run, SSP failure | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | moscap_basic | moscap-generic | S20261122T094617Z-1dba | Cox +0.16 %, Vfb -0.6 mV, Nsub +0.23 %, Vth -0.5 mV of the model; needs_confirmation (unverified_pin_map, dut_envelope) | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim row: the example plan run after the three corrections through `B1500Service` (temporary config/data dirs; folder
not kept; `tests/integration/test_recipes_cv.py` repeats it). Hardware record: `validation/hw/moscap.cv.yaml` (reviewed by a human after bring-up stage L6, skill
`b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
