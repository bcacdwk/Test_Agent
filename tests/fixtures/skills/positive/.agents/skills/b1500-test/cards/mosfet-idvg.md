---
id: mosfet-idvg
title: MOSFET transfer curve (Id-Vg) — Vth, gm_max, SS, Ion/Ioff
recipes: [mosfet.idvg]
device_types: [nmos, pmos]
modules: [2x SMU (HRSMU on drain preferred) + GNDU]
status: sim_validated
confirmation: conditional
knowledge: [knowledge/06-analysis-extraction.md#vth-linear-extrapolation, knowledge/06-analysis-extraction.md#legacy-ss]
debug: [noisy-data, compliance-hit]
sources: [deck slide 6, fixture for b1500 dev lint-skills]
version: 1
---

# MOSFET Id-Vg (fixture card)

## 1. Purpose and applicable devices

Threshold voltage and transfer metrics of an enhancement MOSFET in the linear region. Not for output curves.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | sweep | SMU1 (MPSMU) | low current |
| drain | bias | SMU3 (HRSMU) | measure Id |
| source, bulk | ground | GNDU | |

Example pin map `mosfet-4t` (config/pinmaps).

## 3. Pre-run checklist

- Contact check on a fresh landing; `station_status` clean; DUT profile chosen.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_start` | −1 V | -2..0 V | -10..10 V | start below Vth | off-current floor |
| `vg_stop` | 3 V | 1..5 V | [-10, 10] V | end in strong inversion | gm peak inside the sweep |
| `vg_points` | 101 | - | 11..1001 | step resolution | fit window points |
| `vd` | 50 mV | 20..100 mV | -5 to 5 V | linear region | Vd/2 correction |
| `icomp_gate` | 1 uA | — | 1 pA..1 mA | gate leakage guard | aborts on oxide damage |
| `icomp_drain` | 1e-3 | | 1 pA..10 mA | drain current guard | limits self-heating |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | noise vs time | SS accuracy |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.idvg
params: {vg_start: -1.0, vg_stop: 3.0, vd: 0.05}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

## 5. Limits and confirmation

Within the DUT profile envelope the plan is tier `ok`; raising compliance above it needs confirmation.

## 6. Quality criteria

C/T points limited; V X F D G S U untrusted; at most 5 % limited points in the fit window.

## 7. Analysis method

`vth_linear_extrapolation` (window max_gm, Vd/2 subtracted); see the knowledge entry.

## 8. Expected result shape

Vth 0.3-0.6 V on `nmos_basic`; red flag: no turn-on.

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| noisy Id floor | open contact | contact check | noisy-data |
| flat top | compliance | lower Vg stop | compliance-hit |

## 10. Validation record

| backend | date | scenario | run_id | result |
|---|---|---|---|---|
| sim | fixture | nmos_basic | - | - |
