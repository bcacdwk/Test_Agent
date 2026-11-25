---
id: mosfet-split-cv
title: MOSFET split C-V — Cgc plateau (Cox*W*L, EOT), Cgd, C-V threshold voltage
family: cmu
intent: [split C-V, split CV, Cgc, Cgd, gate capacitance, gate-channel, gate-drain, Miller, Cox*W*L, EOT, inversion charge]
recipes: [mosfet.cgc_cv, mosfet.cgd_cv]
device_types: [nmos, pmos]
modules: [MFCMU, MPSMU, HRSMU, GNDU]
routes: [scuu:cmu]
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/08-capacitance-cv.md#split-c-v-cgc-and-cgd, knowledge/08-capacitance-cv.md#threshold-voltage-from-c-v, knowledge/08-capacitance-cv.md#scuu-same-landing-i-v-and-c-v]
manual: ['PG p256 (3-76) "CV (DC Bias) Sweep"', 'PG p470 (4-152) "MM"', 'PG p549 (4-231) "WDCV"', 'PG p396 (4-78) "DV"', 'PG p520 (4-202) "SSP"']
debug: [cmu-correction-stale, cmu-series-resistance, cmu-cv-distortion, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 2.7, blueprint v2 3.2 (mosfet.cgc_cv, mosfet.cgd_cv), blueprint v2 4.2 (mosfet +cv), Koomen 1973]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# MOSFET split C-V

## 1. Purpose and applicable devices

The gate capacitance of a MOSFET against gate bias: `mosfet.cgc_cv` (gate to channel: plateau Cox*W*L, EOT, C-V
threshold voltage) and `mosfet.cgd_cv` (gate to drain with the source grounded: about Cox*W*L/2 + Cov in
inversion, the Miller capacitance). Long-channel devices (L above about 1 um) at low frequency.

- Not for: a MOS capacitor (`moscap-cv`), I-V threshold voltage (`mosfet-idvg`), gate leakage (`gate-leakage`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (cmu_high) | MFCMU High (`7H`) | DC bias sweep and AC drive |
| drain | `drain` (cmu_low) | MFCMU Low (`7L`) | measuring point |
| source | none (`cgc_cv`); `source` ground (`cgd_cv`) | SMU6 (MPSMU) or GNDU | Cgc: floating (SMU off) or tied to drain; Cgd: 0 V |
| bulk | `bulk` (ground) | SMU4 at 0 V or the GNDU | AC ground (substrate) |

Example pin map `mosfet-split-cv` (one landing for both recipes), DUT `nmos-cv` (`geometry` W, L for EOT).
Never ground the source for Cgc (that measures Cgd).

- Routes per phase: none with `mosfet-split-cv`; with gate and drain on `SCUU1.OUT1/OUT2`: measure `-> cmu`, then
  rest (same-landing I-V through the SCUU's SMUs; the source and bulk stay on other SMUs or the GNDU).

## 3. Pre-run checklist

- Gate leakage below about 1 nA in the range (`gate-leakage`); the device conducts (`mosfet-idvg`) on this landing.
- Fresh corrections with this pin map at every frequency (`station_status.corrections`; card `cmu-correction`).
- Ask: n or p channel (p: sweep from positive to negative), W, L and the gate envelope.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `freqs_hz` | [100] kHz | 10..100 kHz | 1 kHz..5 MHz | channel follows the AC | one sweep each |
| `ac_vrms` | 30 mV | 10..50 mV | 10..250 mV | small signal | above 50 mV: `soft_cmu` |
| `vg_start` | -1.5 V | -3..0 V | -25..25 V | accumulation (n channel) | overlap floor |
| `vg_stop` | 2.5 V | 1..3 V | -25..25 V | strong inversion | plateau extrapolation |
| `points` | 81 | 41..201 | 11..1001 | step 50 mV | onset Vth resolution |
| `sweep_mode` | single | single | single, double | double: hysteresis check | 2 x points |
| `hold_s` | 0.5 s | 0..2 s | 0..60 s | settle at the start | WTDCV hold |
| `delay_s` | 0 s | 0..0.1 s | 0..10 s | slow traps | WTDCV delay |
| `icomp_source` (`mosfet.cgd_cv`) | 1 mA | 1 uA..1 mA | 1 nA..10 mA | source SMU at 0 V | compliance only |
| `integration` | medium | medium | short, medium, long | averaging | long for small C |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.cgc_cv
params: {}
pin_map: mosfet-split-cv
dut_profile: nmos-cv
sim_scenario: nmos_cv
```

## 5. Limits and confirmation

- R-CMU-01 (MFCMU and DUT `ac` envelopes of gate and drain; `soft_cmu` above 10 V or 50 mVrms), R-DUT-01 (gate
  range, source/bulk at 0 V), R-CORR-01 (blocked without fresh corrections; next step card `cmu-correction`).
- `unverified_pin_map`, `unverified_topology` (SCUU), `dut_envelope` when the MFCMU's nominal short-circuit AC current
  exceeds a terminal's `max_abs_i`; on hardware `first_hw_run`. Not destructive; sync (a few seconds per sweep).

## 6. Quality criteria

- MFCMU status `N` only (`U`/`D`/`V` untrusted, automatic abort). The source SMU of `cgd_cv` must not reach
  compliance (`C`): a gate short or a wrong landing.
- Shape: flat overlap floor in accumulation, one monotonic rise, plateau in inversion; a dip near threshold at high
  frequency means the channel resistance cuts the reading (lower the frequency).

## 7. Analysis method

`mosfet.cgc_cv` defaults: `cv_cox` (floor removed, plateau extrapolated: `cox` = Cox*W*L, `c_floor`, per area and
EOT with W and L) and `cv_vth` (onset of the inversion capacitance). `mosfet.cgd_cv`: `cv_vth`; read the plateau
from the table (about Cox*W*L/2 + Cov). `plot_cv` for the curves. Effective mobility (Qi from Cgc with an Id-Vg) is
an ad-hoc analysis in `work/`.

## 8. Expected result shape

| quantity | typical | red flags |
|---|---|---|
| Cgc floor | 2 x Cov (tied source) or Cov (floating source) | rising floor: source or bulk path wrong |
| Cgc plateau | Cox*W*L within a few % (Cmax 1-3 % below) | plateau far from eps_ox*W*L/tox: geometry or landing |
| Cgd plateau | about half of Cgc + Cov | equal to Cgc: source not grounded |
| C-V Vth | near the I-V Vth (different definition) | difference above 0.2 V: wrong device or traps |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked by R-CORR-01 | corrections missing or stale for this pin map | `station_status.corrections` | `cmu-correction-stale` |
| plateau sagging near Vth, frequency-dependent | channel resistance (long L, high f) | repeat at 10 kHz | `cmu-series-resistance` |
| `U`/`D` status, source SMU in compliance | contact, gate leakage, short | `get_run` audit; `gate-leakage` | `cmu-cv-distortion`, `errx-codes` |
| fault latched | interrupted run | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | nmos_cv | nmos-cv | S20261122T094617Z-6731 | `mosfet.cgc_cv`: plateau -0.74 % of Cox*W*L, onset Vth -43 mV of the model | - |
| sim | 2026-11-22 | nmos_cv | nmos-cv | S20261122T094618Z-4b6b | `mosfet.cgd_cv`: every point = model Cgd within 0.3 %, onset Vth -43 mV | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim rows: the example requests run after the three corrections through `B1500Service` (temporary config/data dirs;
folders not kept; `tests/integration/test_recipes_cv.py` repeats them). Hardware records:
`validation/hw/mosfet.cgc_cv.yaml`, `validation/hw/mosfet.cgd_cv.yaml` (reviewed by a human
after bring-up stage L6, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...`
runs).
