---
id: smu-search
title: SMU search — MOSFET threshold voltage by binary search at Id = I_crit x W/L (one trigger, no curve)
family: smu
intent: [Vth search, threshold voltage search, binary search, constant-current Vth, fast Vth, Vth mapping, search]
recipes: [mosfet.vth_search]
device_types: [nmos, pmos, igzo_tft]
modules: [HRSMU, MPSMU, HPSMU, GNDU]
routes: []
bringup_stage: L5
status: sim_validated
confirmation: never
knowledge: [knowledge/02-b1500-instrument.md#search-measurements-mm-9-14-15, knowledge/06b-analysis-time-pulse.md#threshold-voltage-by-search, knowledge/06-analysis-extraction.md#vth-constant-current, knowledge/02-b1500-instrument.md#data-status-codes]
manual: [PG p108-109 (2-20) "Binary Search", PG p366 (4-48) "BGI", PG p370 (4-52) "BSM", PG p374-375 (4-56) "BSV", PG p223 (3-43) "Binary Search"]
debug: [compliance-hit, noisy-data, current-too-high, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 3.1, 2.7 and 4.2, PG binary search p108-109, PG example Table 3-12 p222-223]
version: 1
---

# SMU search: threshold voltage

## 1. Purpose and applicable devices

What is the gate voltage at which the drain current reaches the critical current? `mosfet.vth_search` lets the
instrument bisect the gate (binary search, MM 15) with the drain at a constant bias until Id is within `limit_rel` of
I_crit = `i_crit_a` x `w_over_l`, and returns that gate voltage: the constant-current Vth in one trigger, without a
curve. Fast for wafer maps, Vth tracking between stress reads and many devices.

- Applies to n- and p-type MOSFETs and TFTs whose Id(Vg) is monotonic between `vg_start` and `vg_stop` (p-type:
  negative `vg_start`/`vg_stop`/`vd`; the target polarity follows `vd`).
- Not for: SS, gm, Ion/Ioff or hysteresis (need the curve: [mosfet-idvg](mosfet-idvg.md)), non-monotonic devices
  (FeFETs, ambipolar), breakdown searches ([tddb-bdv](../reliability/tddb-bdv.md), destructive).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: binary search source (`BSV`), not measured | SMU4 (HRSMU; MPSMU/HPSMU allowed) | forced between `vg_start` and `vg_stop` |
| drain | `drain`: constant `vd`, search monitor (`BGI`, Id) | SMU3 (HRSMU preferred) | the target current is read here |
| source | `source`: ground | GNDU | |

- Example pin map `mosfet-4t` (gate SMU4, drain SMU3, source/bulk GNDU), DUT profile `nmos-generic`. The pin map
  and DUT profile are the human's: never invent one.
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md); for a new device type one Id-Vg first
  ([mosfet-idvg](mosfet-idvg.md)) to confirm Vth lies inside `vg_start`..`vg_stop` and Id(Vg) is monotonic there.
- Choose `i_crit_a` and `w_over_l` as for `vth_constant_current` (the same criterion makes both comparable).
- `station_status` clean.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_start` | 0 V | -1..0 V | -10..10 V | search start (below Vth for n-type) | forced first |
| `vg_stop` | 2 V | 1..3 V | -10..10 V | search end (above Vth) | cautious control reaches it only when needed |
| `vd` | 50 mV | 20..100 mV | -5..5 V | drain bias (linear region) | target polarity follows it |
| `i_crit_a` | 100 nA | 10 nA..1 uA | 1 pA..1 mA | critical current per square | the target is `i_crit_a` x `w_over_l` |
| `w_over_l` | 1 | 0.1..100 | 0.001..10000 | channel W/L | scales the target |
| `limit_rel` | 0.01 | 0.001..0.02 | 0.0001..0.1 | stop within target x (1 +/- limit_rel) | 1 % ~ 0.4 mV at 80 mV/dec |
| `control` | `cautious` | - | `cautious`, `normal` | BSM output control | normal forces `vg_stop` second |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | gate guard | a leaky gate aborts (S) |
| `icomp_drain` | 1 mA | - | 1 nA..10 mA | drain compliance | at least the target (error 275) |
| `hold_s` | 0 s | - | 0..30 s | before the first point | 10 ms steps |
| `delay_s` | 0 s | 0..50 ms | 0..10 s | per point before the reading | slow (trap-rich) devices: longer |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | ADC preset of the drain | longer: less noise near the target |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.vth_search
params: {}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

## 5. Limits and confirmation

- Inside the DUT profile and the soft limits the plan is `ok` (no confirmation); levels beyond them need
  `dut_envelope`/`soft_limit`. The gate is forced at most to `vg_stop` (normal control forces it second, cautious
  only when the target lies near it): keep `vg_stop` inside the gate rating.
- Not destructive; synchronous; one `XE`. On hardware every run is `first_hw_run` until the recipe is validated.

## 6. Quality criteria

- The result row: `gate_V` with `gate_V_status` (`N` found, `G` target not in the range, `S` stopped by the automatic
  abort: gate or drain compliance, oscillation) and `drain_I` with its status. `kind_result`: `search_status`,
  `found`, `target`, `measurement_mode` 15.
- `rel_error` (reading vs target) within `limit_rel`; a reading far off with `N` means the search hit the output
  resolution (widen `limit_rel`).
- Re-measure (autonomous, at most two, stays `ok`): `integration`, `delay_s`, `control`; a wider range is a new plan.

## 7. Analysis method

- Default `vth_search_value`: Vth = `gate_V` at status `N` ([06b](../../knowledge/06b-analysis-time-pulse.md#threshold-voltage-by-search));
  `fit`: `i_measured_a`, `target`, `rel_error`. Same definition as `vth_constant_current` at the same criterion and
  `vd` (agrees within the search tolerance; no interpolation between sweep points).
- `G`: `failed` (move `vg_start`/`vg_stop`); `S`: refused (check compliance, then [mosfet-idvg](mosfet-idvg.md)).
- Report: Vth (derived, method `vth_search_value`, criterion `i_crit_a` x `w_over_l` at `vd`), the drain reading and
  its status; backend and SIMULATED on `sim`.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| Si nMOSFET, 100 nA x W/L, Vd 50 mV | 0.2..0.7 V, repeatable within 1 mV | `G` (Vth outside the range) |
| pMOSFET (negative range and `vd`) | -0.2..-0.8 V | `G` with a positive range (polarity) |
| IGZO TFT | 0..3 V, shifts with stress history | run-to-run drift > 10 mV (instability, see `vth-drift-igzo`) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| status `S`, drain `C` | target above the drain compliance or a short | `icomp_drain`, then an Id-Vg | `compliance-hit` |
| status `S`, gate `C` | gate leakage above `icomp_gate` (damaged oxide) | gate leakage check | `current-too-high` |
| Vth scatters between runs | noise at the target current, slow traps | `integration` long, `delay_s` | `noisy-data` |
| status `G` | Vth outside `vg_start`..`vg_stop`, wrong polarity | Id-Vg over a wider range | `errx-codes` |
| run `failed`, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | nmos_basic | nmos-generic | S20261122T095613Z-1640 | tier ok; N=2; Vth 0.31299 V vs constant-current Vth 0.31301 V of an Id-Vg (S20261122T095613Z-0657; -0.02 mV) and model 0.31301 V | - |
| hw | pending (bring-up stage L5) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware record: `validation/hw/mosfet.vth_search.yaml` (reviewed by a human after bring-up stage
L5, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
