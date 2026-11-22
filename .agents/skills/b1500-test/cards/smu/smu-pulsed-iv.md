---
id: smu-pulsed-iv
title: SMU pulsed I-V — pulsed Id-Vg / Id-Vd, pulsed spot, multi-channel pulses; pulsed vs DC (self-heating)
family: smu
intent: [pulsed, pulse, pulsed IV, pulsed Id-Vg, pulsed Id-Vd, self-heating, isothermal, pulsed vs DC, trapping]
recipes: [mosfet.idvg_pulsed, mosfet.idvd_pulsed, basic.pulsed_spot, generic.smu_multi_pulsed]
device_types: [nmos, pmos, igzo_tft, resistor, diode]
modules: [HRSMU, MPSMU, HPSMU, GNDU]
routes: []
bringup_stage: L5
status: sim_validated
confirmation: conditional
knowledge: [knowledge/02-b1500-instrument.md#pulsed-measurements-mm-3-4-5-27-28, knowledge/06b-analysis-time-pulse.md#pulsed-versus-dc, knowledge/06b-analysis-time-pulse.md#pulse-plateau, knowledge/06-analysis-extraction.md#vth-constant-current, knowledge/02-b1500-instrument.md#data-status-codes]
manual: [PG p486-487 (4-168) "PT", PG p492 (4-174) "PWV", PG p488 (4-170) "PV", PG p464 (4-146) "MCPT", PG p100 (2-12) "Pulsed Sweep"]
debug: [compliance-hit, noisy-data, current-too-high, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 3.1, 2.7 and 4.2, PG pulsed measurements p93-105, PG examples Tables 3-4/3-8/3-9/3-14/3-15]
version: 1
---

# SMU pulsed I-V

## 1. Purpose and applicable devices

Which current flows when the bias is on only for a short pulse? `mosfet.idvg_pulsed` pulses the gate through a
transfer sweep (MM 4) with the drain at DC; `mosfet.idvd_pulsed` sweeps the drain (staircase) while the gate pulses
once per step (MM 5), one curve per level of `vg_levels`; `basic.pulsed_spot` pulses a two-terminal device to each of
`levels` and reads its current (MM 3); `generic.smu_multi_pulsed` pulses up to two terminals together and reads them
in parallel (MM 28 sweep, MM 27 with `points` 1). Each reading ends with its pulse.

- Uses: isothermal I-V of power, SOI or thin-film transistors; trap-free transfer curves (high-k, IGZO); pulsed
  resistance without DC stress; compare with DC (`pulsed_vs_dc`). Not for: pulses below 500 us (SMU limit: WGFMU `wgfmu-pulsed-iv`, reserved), program/erase pulses (SPGU), DC curves
  ([mosfet-idvg](mosfet-idvg.md), [mosfet-idvd](mosfet-idvd.md)), transients I(t) ([smu-sampling](smu-sampling.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: pulse (`mosfet.*_pulsed`) | SMU4 (HRSMU; MPSMU/HPSMU allowed) | not measured (MM 3/4/5 read one channel) |
| drain | `drain`: DC bias (`idvg_pulsed`) or staircase (`idvd_pulsed`), measures Id | SMU3 (HRSMU) | pulse-end reading |
| source | `source`: ground | GNDU | |
| a / b | `a` pulse + measure, `b` ground (`basic.pulsed_spot`, generic) | SMU3 / GNDU | generic: optional `c` pulse, `d` DC bias |

- Pin maps `mosfet-4t` (DUT `nmos-pulsed`: pulse envelopes on gate and drain), `resistor-2t` (`resistor-pulsed`:
  on `a`). A terminal without a DUT pulse envelope is blocked (R-PULSE-02): ask the human; never invent one.
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md); a DC curve first ([mosfet-idvg](mosfet-idvg.md)
  at the same `vd`) is also the reference for `pulsed_vs_dc`. Short, shielded cables (edges ring on long leads).
- `station_status` clean; pin map and DUT profile (with pulse envelopes) from the human.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_base` | 0 V | -1..0 V | -10..10 V | gate off between pulses | device cools, traps empty |
| `vg_start` | 0 V | -1..0 V | -10..10 V | first gate pulse level | |
| `vg_stop` | 3 V | 1..5 V | -10..10 V | last gate pulse level | above the profile: confirmation |
| `vg_points` | 61 | 31..101 | 2..1001 | pulses (steps) | one pulse per step |
| `vd` | 1 V | 0.05..3 V | -5..5 V | drain DC bias | self-heating needs power: use the DC run's `vd` |
| `vd_start` | 0 V | - | -10..10 V | drain staircase start | |
| `vd_stop` | 3 V | 1..3 V | -10..10 V | drain staircase stop | |
| `vd_points` | 31 | 21..101 | 2..1001 | drain steps | one gate pulse per step |
| `vg_levels` | 1, 1.5, 2, 2.5, 3 V | - | -10..10 V | gate pulse levels, one curve each | one trigger per level |
| `icomp_gate` | 100 uA | - | 1 pA..10 mA | gate guard (edge charging) | a gate short aborts |
| `icomp_drain` (`mosfet.idvg_pulsed`) | 1 mA | - | 1 pA..10 mA | drain current limit | sets the pulsed range |
| `icomp_drain` (`mosfet.idvd_pulsed`) | 1 mA | 100 uA..10 mA | 1 pA..100 mA | drain current limit | sets the pulsed range |
| `levels` | -0.1, -0.05, 0.05, 0.1 V | - | -42..42 V | pulse levels of `a` | one pulse each |
| `base` | 0 V | - | -42..42 V | `a` between pulses | |
| `icomp` | 100 uA | 1 nA..1 mA | 1 pA..0.1 A | compliance of `a` | pulsed range = compliance range |
| `start` | 0 V | - | -42..42 V | generic: first pulse of `a` | |
| `stop` | 0.5 V | - | -42..42 V | generic: last pulse of `a` | ignored with `points` 1 |
| `points` | 11 | - | 1..1001 | generic: pulses | 1 = MM 27 spot |
| `average` | 1 | 1..16 | 1..1023 | generic: pulses per reading (MCPT) | noise / sqrt(N) |
| `width` | 1 ms | 0.5..10 ms | 10 us..2 s | pulse width | HR/MP: 500 us-2 s in 100 us steps |
| `period` | 20 ms | 10..100 ms | 5 ms..5 s | pulse period | duty = width/period; >= width + 2 ms |
| `hold_s` | 0 s | 0..1 s | 0..30 s | before the first pulse | 10 ms steps |
| `meas_time` | 200 us | 100..500 us | 2 us..20 ms | pulsed ADC time, ends with the pulse | at most the width |

Generic `c`/`d`: `base_c` 0 V, `peak_c` 0.1 V, `icomp_c` 100 uA, `bias_v` 0 V, `bias_icomp` 100 uA (-42..42 V,
1 pA..0.1 A; `list_recipes(recipe_id)`). Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.idvg_pulsed
params: {vd: 3.0}
pin_map: mosfet-4t
dut_profile: nmos-pulsed
sim_scenario: nmos_selfheat
```

## 5. Limits and confirmation

- R-PULSE-01 blocks widths outside the SMU table (HR/MP/HPSMU 500 us-2 s, 100 us steps; period 5 ms-5 s, >= width +
  2 ms; PG p486-487 (4-168)); MM 4/5 sweep linearly only (log: generic multi-channel). Narrower pulses: WGFMU.
- R-PULSE-02: the DUT terminal's pulse envelope (level, width, duty, pulses per run) - outside it `dut_envelope`,
  missing it blocked. R-PULSE-03 (`soft_pulse`): above 5 V, 10,000 pulses, 60 s on-time or duty 0.5 per run. Generic:
  `adhoc_recipe` + `first_hw_run` on hardware; destructive: no; runs are synchronous.

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited (a sweep aborts at the first, `WM 2,1`; a host list stops after it);
  `V X F` untrusted: no extraction. `kind_result`: `triggers_done`, `stopped_early`, `stop_reason`.
- Pulsed auto ranging = the compliance range: set `icomp_drain` near the peak current; a short `meas_time` is noisier.
- Re-measure (autonomous, at most two, stays `ok`): `meas_time`, `period`, `vg_points`; a wider pulse or a higher
  level is a new plan.

## 7. Analysis method

- Defaults: `mosfet.idvg_pulsed` `vth_constant_current` (`i_crit_a` 1e-7) and `gm_max`; `mosfet.idvd_pulsed`
  `output_metrics` per gate level; `basic.pulsed_spot` `resistance`; generic: none (choose).
- Pulsed vs DC: run the DC recipe with the same bias (`mosfet.idvg` with the same `vd`, `vg_start`..`vg_stop`;
  `mosfet.idvd` with the same gate levels), then `analyze_run(pulsed_run, "pulsed_vs_dc", {"reference_run": dc_run})`:
  `pulsed_minus_dc` and `pulsed_over_dc` at the highest current, `max_rel_difference`
  ([06b](../../knowledge/06b-analysis-time-pulse.md#pulsed-versus-dc)). Bias mismatch: `failed`.
- `pulse_plateau`: the pulse-end level at a pulse level `v`. Report measured Id (points, status counts) and derived
  values with method and window; on `sim` say SIMULATED.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| Si bulk MOSFET, low power | pulsed = DC within noise | pulsed < DC by > 5 % (contact, edges, range) |
| SOI / TFT / power device at high Id x Vd | pulsed > DC, difference grows with power (self-heating) | difference at low power |
| high-k or IGZO transfer | pulsed curve steeper, less hysteresis than DC | step changes between pulses |
| resistor | pulsed = DC resistance | non-linear R at small levels (contact) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| `C` on the drain at high gate levels | compliance range too small | lower the top level or raise `icomp_drain` within the profile | `compliance-hit` |
| scattered pulsed readings | short `meas_time`, compliance range far above the current | longer `meas_time`, tighter compliance, `average` | `noisy-data` |
| pulsed current far above DC at low power | DC reference at another bias or a damaged device | compare `drain_V` of both runs | `current-too-high` |
| blocked R-PULSE-01 or error 233 | width/period outside the SMU table | 500 us steps of 100 us, period >= width + 2 ms | `errx-codes` |
| run `failed`, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | nmos_selfheat (`vd` 3 V) | nmos-pulsed | S20261122T082412Z-887f | tier ok; N=61; pulsed - DC (ref S20261122T082412Z-72c4) 75.4 uA vs model 74.0 uA (+1.8 %), ratio 1.163 vs 1.160 | - |
| sim | 2026-11-22 | nmos_selfheat | nmos-pulsed | S20261122T082413Z-2a63 | `mosfet.idvd_pulsed` tier ok; N=155; Ron 2.05 kOhm, Vd_sat 1.85 V at Vg 3 V | - |
| sim | 2026-11-22 | resistor_100k | resistor-pulsed | S20261122T082413Z-1552 | `basic.pulsed_spot` tier ok; R 100.05 kOhm (+0.05 %) | - |
| sim | 2026-11-22 | resistor_100k | resistor-pulsed | S20261122T082413Z-82d5 | `generic.smu_multi_pulsed` (MM 28) tier ok; R 99.56 kOhm (-0.4 %) | - |
| hw | pending (bring-up stage L5) | - | - | - | - | - |

Sim rows: example plans via `B1500Service` with temporary config/data dirs (folders not kept). Hardware records: `validation/hw/mosfet.idvg_pulsed.yaml`, `validation/hw/mosfet.idvd_pulsed.yaml`,
`validation/hw/basic.pulsed_spot.yaml` and `validation/hw/generic.smu_multi_pulsed.yaml` (reviewed by a human after
bring-up stage L5, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
