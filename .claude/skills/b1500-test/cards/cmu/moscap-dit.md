---
id: moscap-dit
title: MOS capacitor Dit over the band gap — quasi-static C-V (QSCV) with high-low, multi-frequency conductance
family: cmu
intent: [QSCV, quasi-static C-V, low-frequency C-V, leakage compensation, Dit, interface traps, high-low, conductance method, Dit profile, multi-frequency C-V, Gp/w, SCUU same landing]
recipes: [moscap.qscv, moscap.cv_multi_freq]
analysis: [cv_cox, dit_high_low, dit_conductance, plot_cv]
device_types: [moscap]
modules: [MPSMU, HRSMU, MFCMU, GNDU]
routes: [scuu:smu, scuu:cmu]
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#quasi-static-c-v, knowledge/08-capacitance-cv.md#dit-over-the-band-gap, knowledge/08-capacitance-cv.md#scuu-same-landing-i-v-and-c-v, knowledge/02b-smu-modes.md#quasi-static-c-v-mm-13]
manual: ['PG p115 (2-27) "Quasi-static CV"', 'PG p497 (4-179) "QSV"', 'PG p496 (4-178) "QST"', 'PG p493 (4-175) "QSL"', 'PG p499 (4-181) "QSZ"', 'PG p520 (4-202) "SSP"']
debug: [noisy-data, compliance-hit, cmu-correction-stale, cmu-series-resistance, cmu-cv-distortion, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 2.7 (kind smu_qscv), blueprint v2 2.10 (dit_high_low, dit_conductance), blueprint v2 3.2 (moscap.qscv, moscap.cv_multi_freq), blueprint v2 4.2 (moscap Dit)]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# MOS capacitor Dit over the band gap

## 1. Purpose and applicable devices

Interface-trap density Dit(E) of a MOS capacitor, by two methods on ONE landing:

- `moscap.qscv` (kind `smu_qscv`, MM 13): an SMU steps the gate and integrates the charge per step with leakage
  compensation: the low-frequency (quasi-static) C-V. Its `cv_cox` gives Cox; with a high-frequency `moscap.cv` of
  the same device (`analyze_run(qscv_run, dit_high_low, {reference_run: hf_run})`) it gives Dit from midgap to about
  +-0.3 eV.
- `moscap.cv_multi_freq` (kind `cmu_measure`, MM 18 per frequency): C-V at 1 kHz..1 MHz; `dit_conductance` fits
  Gp/w per bias: Dit(E) where the trap peak lies in the band (at room temperature 0.15-0.35 eV from midgap).
- Not for: one bias (`moscap-cf-ct`), Cox/Vfb/Nsub alone (`moscap-cv`), MOSFET channels (`charge-pumping`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (sweep_v / cmu_high) | `SCUU1.OUT1`: SMU6 (MPSMU) or MFCMU High | QSCV source; C-V High |
| bulk | `bulk` (ground / cmu_low) | `SCUU1.OUT2`: SMU5 at 0 V or MFCMU Low | or the GNDU without an SCUU |

Pin map `moscap-scuu`, DUT `moscap-generic` (`geometry.area_um2` for Dit). The station must record SCUU1
`present: true` (stage L6). Without an SCUU, QSCV needs an SMU landing (gate on an SMU, bulk GNDU) and the HF C-V
its own MFCMU landing and corrections: a re-landing makes the two curves two states.

- Routes per phase: QSCV `measure: SCUU1.OUT1/OUT2 -> smu` (SSP 7,3 switches SMU6/SMU5 on; no CN); C-V
  `measure: -> cmu` (SSP 7,4), `rest: -> smu`; cleanup: rest, verified.

## 3. Pre-run checklist

- Gate leakage below about 1 nA at the sweep ends; HF corrections (phase, open, short) with `moscap-scuu` at every
  frequency of the C-V runs (card `cmu-correction`; the 10 default `freqs_hz` are in the default list).
- QSCV offset (optional, recommended for Dit): human lifts the probes, `moscap.qscv` with `offset: measure`
  (`physical_setup`), lands again; later QSCV runs use `offset: cancel`. Ask the substrate type (p: accumulation at
  negative bias) and keep both sweeps inside the DUT envelope.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_start` (`moscap.qscv`) | 2 V | -3..3 V | -25..25 V | inversion side first | not measured |
| `v_stop` (`moscap.qscv`) | -2.5 V | -3..3 V | -25..25 V | accumulation for Cox | not measured |
| `step_v` | 50 mV | 20..100 mV | 1 mV..10 V | span = whole steps | profile resolution |
| `cvoltage_v` | 50 mV | 20..100 mV | 1 mV..10 V | = step joins steps | charge per step |
| `cinteg_s` | 0.1 s | 0.1..1 s | 0.02..400 s | whole line periods | noise vs time |
| `linteg_s` | 0.1 s | 0.1..0.5 s | 0.02..2 s | leakage integration | compensation noise |
| `hold_s` (`moscap.qscv`) | 5 s | 2..10 s | 0..655.35 s | form the inversion layer | equilibrium start |
| `delay_s` (`moscap.qscv`) | 0 s | 0..0.5 s | 0..65.535 s | settle per step | QST delay1 |
| `irange_a` | 10 nA | 1..100 nA | 10 pA..1 uA | C cvoltage/cinteg + leak | overflow aborts |
| `icomp_a` | 1 uA | 0.1..1 uA | 1 nA..1 mA | within DUT `max_abs_i` | compliance aborts |
| `sweep_mode` (`moscap.qscv`) | single | single | single, double | double: both branches | 2 x steps |
| `leakage` | compensate | compensate | compensate, data, off | QSL 1,1 | leak column `gate_I` |
| `operation` | normal | normal | normal, compatible | QSC | compatible: 4155C |
| `offset` | off | cancel | off, cancel, measure | path guard C | measure: probes up |
| `freqs_hz` (`moscap.cv_multi_freq`) | [1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000] Hz | 1 kHz..1 MHz | 1 kHz..5 MHz | Gp/w peak in band | corrections each |
| `ac_vrms` (`moscap.cv_multi_freq`) | 30 mV | 10..50 mV | 10..250 mV | small signal | above 50 mV: `soft_cmu` |
| `v_start` (`moscap.cv_multi_freq`) | 0.5 V | -3..3 V | -25..25 V | inversion side of depletion | per frequency |
| `v_stop` (`moscap.cv_multi_freq`) | -1.5 V | -3..3 V | -25..25 V | past flatband | per frequency |
| `points` (`moscap.cv_multi_freq`) | 81 | 41..201 | 11..1001 | 25 mV steps | bias resolution |
| `hold_s` (`moscap.cv_multi_freq`) | 1 s | 0.5..5 s | 0..60 s | settle per sweep | WTDCV hold |
| `delay_s` (`moscap.cv_multi_freq`) | 0 s | 0..0.1 s | 0..10 s | settle per step | WTDCV delay |
| `integration` (`moscap.cv_multi_freq`) | medium | medium | short, medium, long | MFCMU averaging | long for small G |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: moscap.qscv
params: {}
pin_map: moscap-scuu
dut_profile: moscap-generic
sim_scenario: moscap_dit
```

## 5. Limits and confirmation

- R-DUT-01/R-LIM-01: the QSV sweep within `max_abs_v`, Icomp within `max_abs_i`; QSR range on the module (MPSMU >= 1
  nA; the kind refuses others). R-CMU-01 and R-CORR-01 for `cv_multi_freq` (MFCMU `dut_envelope` from its AC current).
- Always confirmed: `unverified_pin_map`, `unverified_topology` (SCUU wiring); `offset: measure` adds
  `physical_setup`; on hardware `first_hw_run`. R-GNDU-01 if the bulk is on the GNDU (tiny currents). Not
  destructive. One XE: a sweep longer than `segment_max_s` cannot run async.

## 6. Quality criteria

- SMU status `N` only (`C`/`T`, `V` = overflow or abort: error 242, dummy data, untrusted). Leakage `gate_I` smooth
  and small against `C cvoltage / cinteg`; QSCV and HF C-V equal in accumulation (else not one state).
- `cv_multi_freq`: MFCMU status `N`; G/w peaks inside the band at depletion biases.

## 7. Analysis method

`moscap.qscv`: `cv_cox` (accumulation extrapolation of the quasi-static curve), `plot_cv` (C and |leak| vs `dc_v`);
`dit_high_low` with the HF run as `reference_run` (either order): `dit_mid`, `dit_mean`, `dit_min`, `dit_max`, profile
in `fit` (`e<k>`, `dit<k>`, window `psi_min`..`psi_max`; options `cox_f`, `psi_min`, `psi_margin`, `e_step`).
`moscap.cv_multi_freq`: `cv_cox` (1 MHz), `dit_conductance`: `dit_mean/min/max`, `tau_min/max`, per bias `v<k>`,
`e<k>`, `dit<k>` (options `cox_f`, `rs_ohm`, `model`). Report derived values with method, window, both run ids.

## 8. Expected result shape

| quantity | typical (5 nm SiO2, p 1e17, Dit 2e11) | red flags |
|---|---|---|
| QSCV `cox` | = HF Cox within 1-2 % | low: series R, leak not compensated |
| QSCV offset | 0.1..1 pF | > 5 pF: probes not lifted |
| `dit_mid` | 1e10..1e12 cm^-2 eV^-1 | negative, > 1e13: offset, two states |
| `dit_conductance` | rises towards the band edge | no bias counted: sweep through depletion |
| `tau_min/max` | us..ms | at a band end: move the frequency list |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| QSCV status V, error 242 | range too small for charge + leak | `irange_a` up one decade | `compliance-hit` |
| QSCV status C | Icomp below the charging current | `icomp_a` within the DUT envelope | `compliance-hit` |
| C-V blocked by R-CORR-01 | corrections of another pin map | corrections with `moscap-scuu` | `cmu-correction-stale` |
| scattered Dit; QSCV and HF Cox apart | noise in C_LF; series R, two states | longer `cinteg_s`, `offset: cancel`; `impedance_convert` | `noisy-data`, `cmu-series-resistance` |
| plan invalid "whole number" | span not a multiple of the step | adjust `step_v` | `errx-codes` |
| fault after cancel | interrupted cleanup | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | moscap_dit | moscap-generic | S20261124T101200Z-c4d7 | `moscap.qscv`: Cox -0.03 % of the model | - |
| sim | 2026-11-24 | moscap_dit | moscap-generic | S20261124T101201Z-af29 | offset cancelled; with HF run S20261124T101201Z-b52e `dit_high_low`: Dit(midgap) +2.5 %, profile -4..+8 % | - |
| sim | 2026-11-24 | moscap_dit | moscap-generic | S20261124T101201Z-7ace | `moscap.cv_multi_freq`: `dit_conductance` 11 biases, -9..-4 % | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim rows: the example request (offset measured, then cancelled; corrections before the C-V runs) through
`B1500Service` (temporary config and data dirs; folders not kept; `tests/integration/test_recipes_qscv.py` repeats them).
Hardware records: `validation/hw/moscap.qscv.yaml`, `validation/hw/moscap.cv_multi_freq.yaml` (reviewed by a human
after stage L6, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
