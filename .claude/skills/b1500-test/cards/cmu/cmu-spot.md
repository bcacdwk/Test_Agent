---
id: cmu-spot
title: MFCMU spot capacitance — C (Cp-G, Cs-Rs, Z-theta) at a frequency list, known-capacitor check
family: cmu
intent: [spot C, capacitance, known capacitor, 100 pF standard, Cp, Cs, impedance, Z-theta, D factor, correction check]
recipes: [cmu.spot]
device_types: [capacitor, moscap, fecap]
modules: [MFCMU]
routes: []
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#impedance-models-cp-g-cs-rs-z-theta, knowledge/08-capacitance-cv.md#corrections-and-the-measurement-path]
manual: ['PG p252 (3-72) "Spot C"', 'PG p470 (4-152) "MM"', 'PG p441 (4-123) "IMP"', 'PG p354 (4-36) "ACT"', 'PG p347 (4-29) "Cp"']
debug: [cmu-correction-stale, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 2.7 (kind cmu_measure), blueprint v2 3.2 (cmu.spot), blueprint v2 4.2 (fixture + capacitor)]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# MFCMU spot capacitance

## 1. Purpose and applicable devices

The impedance of a two-terminal capacitance at one DC bias and a list of frequencies (`samples` readings each):
the known-capacitor check after the corrections (bring-up L6: a 100 pF standard must read its value within its
tolerance), a capacitor's value, D or ESR, or one point of a MOS capacitor or FeCap.

- Not for: a C-V curve (card `moscap-cv`), split C-V of a MOSFET (`mosfet-split-cv`), the corrections themselves
  (`cmu-correction`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| a | `a` (cmu_high) | MFCMU High (Hc/Hp, `7H`) | DC bias and AC drive |
| b | `b` (cmu_low) | MFCMU Low (Lc/Lp, `7L`) | measuring point (virtual ground) |

Example pin map `capacitor-cmu` (DUT `capacitor-100p`). Another two-terminal DUT needs a pin map with terminals `a`
and `b` on the MFCMU sides and a DUT profile with an `ac` envelope on both (a human writes them).

- Routes: none in every phase.

## 3. Pre-run checklist

- `station_status`: no fault; `corrections` fresh for this MFCMU. Else load card `cmu-correction` and run phase
  compensation, open and short with this pin map at every frequency of `freqs_hz` (R-CORR-01 blocks otherwise).
- Same landing, cables and temperature as the corrections; the human has landed the probes on the DUT again.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `freqs_hz` | [100, 1000] kHz | 1 kHz..1 MHz | 1 kHz..5 MHz | each must be a correction frequency | one block per frequency |
| `ac_vrms` | 30 mV | 10..50 mV | 10..250 mV | small signal, low noise | above 50 mV: `soft_cmu` |
| `dc_v` | 0 V | -2..2 V | -25..25 V | DC bias of terminal a | within the DUT envelope |
| `samples` | 3 | 1..10 | 1..100 | readings per frequency | mean and spread |
| `model` | `cp_g` | `cp_g` | cp_g, cp_d, cs_rs, cs_d, z_theta | parameter pair (IMP) | columns of the table |
| `integration` | medium | medium | short, medium, long | MFCMU averaging (ACT) | long = 2 power-line cycles |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: cmu.spot
params: {}
pin_map: capacitor-cmu
dut_profile: capacitor-100p
sim_scenario: capacitor_100p
```

## 5. Limits and confirmation

- R-CMU-01: 1 kHz..5 MHz, 10..250 mVrms, |DC| <= 25 V and the hard limit; each DUT terminal's `ac.max_vrms`
  (a terminal without an `ac` envelope blocks). Above `policy.cmu` (10 V DC, 50 mVrms): `soft_cmu`.
- R-CORR-01: fresh phase/open/short records of this pin map covering every frequency (else blocked, next step the
  correction card); the summary shows `corr <age>`.
- The MFCMU has no compliance: its nominal short-circuit AC current `sqrt(2) x Vac / 50 Ohm` counts against the DUT
  terminals' `max_abs_i` (`dut_envelope` when above). Unverified pin maps: `unverified_pin_map`; on hardware also
  `first_hw_run` until `hw_validated`. Not destructive; sync (about 0.2 s per reading).

## 6. Quality criteria

- MFCMU status `N` only; `U` (NULL loop unbalance), `D` (IV amplifier saturation), `V` (over range) are untrusted:
  re-measure with a lower frequency or AC level, or check the contact.
- The spread of `samples` readings: above about 0.1 % on a 100 pF standard means noise or a loose contact.

## 7. Analysis method

Default `impedance_convert` (`to: cp_g`): mean Cp and G per frequency (`fit.std` = spread). Other pairs: `to:
cs_rs`, `z_theta`; `series_r: value` with `rs_ohm` removes a known series resistance. Report measured Cp per
frequency, the correction ages and the deviation from the standard's nominal value.

## 8. Expected result shape

| DUT | typical | red flags |
|---|---|---|
| 100 pF standard | Cp within its tolerance at 100 kHz and 1 MHz; D < 0.001 | +0.3 pF or more: open correction missing or stale |
| any capacitor | Cp flat over frequency | Cp falling with frequency: series R or inductance (short correction) |
| MOS capacitor | Cp between Cmin and Cox at its bias | Cp growing at low frequency: traps or leakage |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked by R-CORR-01 | corrections missing, stale or another pin map | `station_status.corrections` | `cmu-correction-stale` |
| reading off by about +0.3 pF | correction lost (power cycle, `*RST`) or not at this frequency | correction list vs `freqs_hz` | `cmu-correction-stale` |
| status `U`/`D`, scattered readings | contact, range, AC level | repeat once; `quality_report` | `noisy-data` |
| errors 320-323, fault latched | excess current, SCUU module in CN, interrupted run | `get_run` audit; `safe_shutdown` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | capacitor_100p | 100 pF standard | S20261122T094617Z-2cab | after phase + open + short: 99.989 pF (100 kHz), 99.987 pF (1 MHz); needs_confirmation (unverified_pin_map) | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim row: the example plan validated and run with its summary after the three corrections through `B1500Service` with
temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR` (run folder not kept; `tests/integration/test_recipes_cv.py` repeats it).
Hardware record: `validation/hw/cmu.spot.yaml` (reviewed by a human after bring-up stage L6, skill
`b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
