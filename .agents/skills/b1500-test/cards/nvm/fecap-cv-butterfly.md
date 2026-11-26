---
id: fecap-cv-butterfly
title: Ferroelectric capacitor C-V butterfly — coercive voltage, imprint, Ec (MFCMU)
family: nvm
intent: [FeCap, ferroelectric capacitor, C-V butterfly, coercive voltage, coercive field, Ec, Vc, imprint, HZO, small-signal C-V]
recipes: [fecap.cv_butterfly]
device_types: [fecap]
modules: [MFCMU]
routes: []
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#fecap-c-v-butterfly, knowledge/04-ferroelectric-oxide.md#ferroelectric-basics-ec-pr-ps, knowledge/04-ferroelectric-oxide.md#fecap-p-v-and-pund, knowledge/08-capacitance-cv.md#corrections-and-the-measurement-path]
manual: ['PG p256 (3-76) "CV (DC Bias) Sweep"', 'PG p549 (4-231) "WDCV"', 'PG p554 (4-236) "WMDCV"']
debug: [cmu-correction-stale, cmu-cv-distortion, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 3.2 (fecap.cv_butterfly), blueprint v2 4.2 (ferro FeCap), blueprint v2 6.3 (fecap-pund; split from it in WP10.6 so each card has one bring-up stage)]
version: 1
---

# Ferroelectric capacitor: C-V butterfly

## 1. Purpose and applicable devices

A ferroelectric capacitor (FeCap, e.g. HfZrO between two electrodes) characterised two ways:

- **C-V butterfly** (`fecap.cv_butterfly`, MFCMU, MM 18 double sweep): the small-signal capacitance is the
  dielectric part plus the reversible polarization response of the branch being travelled, so it peaks near +Vc
  while the bias rises and near -Vc while it falls. Gives Vc (and Ec with the film thickness) and the imprint
  (shift of the loop centre) without switching-current integration. The sweep itself poles the film.
- Not for: the switching charge Pr/Ps and Ec from switching currents (PUND through the WGFMU:
  [fecap-pund](fecap-pund.md)), a FeFET (`fefet-dual-sweep-mw`), a MOS capacitor (`moscap-cv`), leakage
  (`gate-leakage`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| top | `top` (cmu_high) | MFCMU High (`7H`) | DC bias sweep and AC drive |
| bottom | `bottom` (cmu_low) | MFCMU Low (`7L`) | measuring point |

Example pin map `fecap-cmu`, DUT `fecap-generic` (`geometry.tox_nm` = the film thickness for Ec, `area_um2`). PUND
lands the same film on the WGFMU channels (pin map `fecap-wgfmu`, card [fecap-pund](fecap-pund.md)); corrections
belong to the MFCMU landing.

- Routes: none in every phase (MFCMU sides directly).

## 3. Pre-run checklist

- Corrections fresh with `fecap-cmu` at every frequency (`station_status.corrections`; card `cmu-correction`).
- Ask: film thickness and expected Ec (DUT profile); the sweep exceeds +-Vc (about 2x Vc to saturate: general
  practice, not checked) but stays within the terminals' `max_abs_v`. The film's breakdown field and its margin over
  Ec are unknown ([04](../../knowledge/04-ferroelectric-oxide.md#ferroelectric-basics-ec-pr-ps)): ask before sweeping beyond 2x Vc.
- A virgin film may need wake-up cycles before its loop opens: record the cycle history in the run label.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `freqs_hz` | [100] kHz | 10 kHz..1 MHz | 1 kHz..5 MHz | reactance 1/(2πfC): about 27 kOhm for the profile's example 60 pF | one double sweep each |
| `ac_vrms` | 30 mV | 10..50 mV | 10..250 mV | small against Vc | above 50 mV: `soft_cmu` |
| `v_start` | -3 V | - | -25..25 V | one saturated polarity, about 2x the film's Vc: the request, else the DUT profile (`-sweep_v`), else ask; example default | the hold poles the film |
| `v_stop` | 3 V | - | -25..25 V | the other polarity: the request, else the DUT profile (`sweep_v`), else ask | turning point |
| `points` | 121 | 61..241 | 21..1001 | >= 5 points across each peak | step = span/(points-1) |
| `sweep_mode` | double | double | single, double | both branches for Vc | 2 x points |
| `hold_s` | 1 s | 0.5..5 s | 0..60 s | pole at `v_start` | WTDCV hold |
| `delay_s` | 0 s | 0..0.1 s | 0..10 s | slow switching | per step |
| `integration` | medium | medium | short, medium, long | averaging | long for small C |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fecap.cv_butterfly
params: {}
pin_map: fecap-cmu
dut_profile: fecap-generic
sim_scenario: fecap_basic
```

## 5. Limits and confirmation

- R-CMU-01 (1 kHz..5 MHz, 10..250 mVrms, |DC| <= 25 V: UG p73 (2-33); DUT `ac.max_vrms`; `soft_cmu` above 10 V or 50 mVrms);
  R-DUT-01: the sweep within `max_abs_v` of both terminals. The sweep switches the film repeatedly (one cycle per
  double sweep): not destructive, but it changes the device state (wake-up, fatigue): say so.
- R-CORR-01 blocks without fresh corrections (next step card `cmu-correction`); `unverified_pin_map`; on hardware
  `first_hw_run`.

## 6. Quality criteria

- MFCMU status `N` only; `U`/`D`/`V` untrusted; G/w small against C (a leaky film adds G and distorts C).
- Shape: two peaks of similar height, one per branch, at opposite polarity; a flat curve means no switching in the
  swept range (too small a span, or a dead film).

## 7. Analysis method

`cv_butterfly`: per branch the maximum of C refined by a parabola through five points: `v_peak_up`, `v_peak_down`,
`vc` = half their distance, `v_imprint` = their mean, `c_peak`, `ec` = vc / `geometry.tox_nm` (MV/cm; refused
without it, naming the field). A peak at a branch end fails: widen the sweep. The butterfly Vc is a small-signal
estimate; PUND (WGFMU) gives the switching Ec and Pr. `plot_cv` shows both branches. Report as derived; SIMULATED.

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| quantity | expected (source) | red flags |
|---|---|---|
| `vc` | Ec·t_FE of your film; Ec unknown until measured ([04](../../knowledge/04-ferroelectric-oxide.md#ferroelectric-basics-ec-pr-ps)) | peaks not separated: paraelectric or dead film |
| `v_imprint` | report it; no expected range | grows after a long hold in one state (imprint) |
| `c_peak` / C(end of sweep) | a peak above the background on each branch (physics); no threshold yet | no peak above the background: weak switching, or leakage-dominated (large G) |
| `ec` | `vc` / `tox_nm`; Ec of your film unknown ([04](../../knowledge/04-ferroelectric-oxide.md#ferroelectric-basics-ec-pr-ps)) | far from the human's expected Ec: ask the human to confirm thickness and expected Ec |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked by R-CORR-01 | corrections missing, stale, other pin map | `station_status.corrections` | `cmu-correction-stale` |
| `cv_butterfly` failed: peak at a branch end | sweep too narrow | widen within the DUT envelope | `noisy-data` |
| large G, drifting C | leaky film | gate leakage check first | `cmu-cv-distortion` |
| `U`/`D` status, sweep aborted | range, contact | `get_run` audit | `errx-codes` |
| fault latched | interrupted cleanup | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | fecap_basic | fecap-generic | S20261124T054020Z-403b | `fecap.cv_butterfly`: peaks +1.001 V / -1.001 V, Vc +0.08 %, Ec +0.08 % of the model | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim row: after the corrections through `B1500Service` (`tests/integration/test_recipes_cv_variants.py`). Hardware
record: `validation/hw/fecap.cv_butterfly.yaml` (reviewed by a human after stage L6, skill `b1500-bringup`; drafts
only from hardware `H...` runs, never from simulator `S...` runs).
