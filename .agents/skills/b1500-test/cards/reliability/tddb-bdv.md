---
id: tddb-bdv
title: Dielectric and junction breakdown — TDDB constant-voltage stress, breakdown voltage (BDV ramp, quasi-pulse), junction breakdown search; destructive
family: reliability
intent: [TDDB, time to breakdown, t_bd, dielectric breakdown, gate oxide reliability, Weibull, constant voltage stress, BDV, breakdown voltage, V-ramp, junction breakdown, avalanche]
recipes: [reliability.tddb_cvs, dielectric.bdv, basic.breakdown_search]
device_types: [dielectric, moscap, nmos, pmos, diode]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L9
status: sim_validated
confirmation: always
knowledge: [knowledge/05-reliability-defects.md#tddb-constant-voltage-stress, knowledge/05-reliability-defects.md#breakdown-voltage-ramps, knowledge/06b-analysis-time-pulse.md#time-to-breakdown-and-weibull, knowledge/06b-analysis-time-pulse.md#breakdown-voltage, knowledge/02b-smu-modes.md#sampling-measurement-mm-10, knowledge/02b-smu-modes.md#search-measurements-mm-9-14-15]
manual: [PG p472-473 (4-154) "MSC", PG p474-475 (4-156) "MT", PG p106-107 (2-18) "Quasi-Pulsed Spot", PG p365 (4-47) "BDV", PG p110-111 (2-22) "Linear Search", PG p459-460 (4-141) "LSV"]
debug: [compliance-hit, current-too-high, smu-sampling-skips, errx-codes, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 3.1 and 4.2, JEDEC JESD92, JEDEC JESD35, McPherson and Mogul J. Appl. Phys. 84 1513 (1998), PG examples Tables 3-10 and 3-11]
version: 2
---

# Dielectric and junction breakdown (TDDB, BDV, breakdown search)

## 1. Purpose and applicable devices

Three DESTRUCTIVE measurements, one site each:

- `reliability.tddb_cvs`: how long does a gate dielectric survive a constant voltage? The gate steps to `v_stress`,
  the leakage is sampled every `interval` until breakdown drives the source into its compliance (`icomp`); the
  sampling stops at once (automatic abort, source to 0 V). `time_to_breakdown` reports t_bd; Weibull over sites.
- `dielectric.bdv`: at which voltage does the film break? `method: quasi_pulsed` (MM 9) ramps the gate as a
  quasi-pulse and reads the voltage where the source hits `icomp` (needs the breakdown 10 V or more above `v_start`);
  `method: linear` (MM 14) ramps in `v_step` steps until the gate current reaches `i_bd` (any film; within one step).
- `basic.breakdown_search` (MM 14): junction breakdown voltage at the current criterion `i_bd` (reverse ramp).

Not for: non-destructive leakage ([gate-leakage](../smu/gate-leakage.md)), transients ([smu-sampling](../smu/smu-sampling.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: stress, ramp or quasi-pulse; measures Ig (and V for MM 9) | SMU4 (HRSMU; MPSMU/HPSMU allowed) | |
| bulk / source / drain | `bulk` ground; `source`, `drain` optional grounds | GNDU / SMU at 0 V | the current returns here |
| anode / cathode | `basic.breakdown_search`: anode ramps and measures; cathode ground | SMU3 / GNDU | pin map `diode-2t` |

- Pin map `mosfet-4t` with DUT `dielectric-generic` (5 nm, gate 6 V) or `dielectric-thick` (20 nm, gate 30 V);
  `diode-2t` with `diode-generic`. The profiles are the human's: never invent the film's or junction's limits.
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- A fresh, unstressed site; a low-voltage leakage check first ([gate-leakage](../smu/gate-leakage.md)); record the
  temperature (breakdown is thermally activated).
- TDDB: `v_stress` at 80-95 % of BDV from `dielectric.bdv` on a sacrificial site; one run per site for a Weibull set.
- BDV: expected breakdown inside the ramp; MM 9 only when it lies 10 V or more above `v_start`, else `method: linear`.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_stress` | required | - | -40..40 V | TDDB stress voltage | higher: shorter life |
| `icomp` (reliability.tddb_cvs) | 1 mA | 10 uA..10 mA | 1 nA..0.1 A | breakdown current limit | post-breakdown current never exceeds it |
| `interval` (reliability.tddb_cvs) | 1 s | 0.1..10 s | 10 ms..60 s | t_bd resolution | points = duration / interval + 1 |
| `duration` | 3600 s | 60..86400 s | 1..86400 s | longest stress | ends earlier at breakdown |
| `hold_bias` | 0 s | - | 0..655.35 s | stress start to first sample | 10 ms steps |
| `method` | `quasi_pulsed` | - | `quasi_pulsed`, `linear` | BDV: quasi-pulse or voltage ramp | linear for BDV < v_start + 10 V |
| `v_start` (dielectric.bdv) | 0 V | - | -42..42 V | ramp start | MM 9: 10 V below the breakdown or more |
| `v_start` (basic.breakdown_search) | 0 V | -1..0 V | -42..42 V | ramp start | |
| `v_stop` | required | - | -42..42 V | ramp end, beyond the breakdown | none found: a lower bound |
| `v_step` (dielectric.bdv) | 50 mV | 10..200 mV | 5 mV..2 V | linear: resolution | at most 1001 steps |
| `v_step` (basic.breakdown_search) | 100 mV | 20..500 mV | 5 mV..5 V | resolution | at most 1001 steps |
| `icomp` (dielectric.bdv, basic.breakdown_search) | 1 mA | 10 uA..10 mA | 1 nA..0.1 A | MM 9 detection; post-breakdown limit | at least `i_bd` |
| `i_bd` (dielectric.bdv) | 100 uA | 1 uA..1 mA | 0.1 nA..0.1 A | linear: breakdown criterion | magnitude, polarity of the ramp |
| `i_bd` (basic.breakdown_search) | 1 uA | 100 nA..100 uA | 0.1 nA..0.1 A | breakdown criterion | magnitude |
| `interval` (dielectric.bdv) | `short` | - | `short`, `long` | MM 9 settling detection | long: stray C or icomp < 1 uA |
| `hold_s` | 0 s | - | 0..30 s | at v_start before the ramp | 10 ms steps |
| `delay_s` (dielectric.bdv, basic.breakdown_search) | 0 s | - | 0..1 s | before each reading | slower ramp |
| `integration` (reliability.tddb_cvs) | `medium` | `short`, `medium` | `short`, `medium`, `long` | ADC preset | |
| `integration` (dielectric.bdv, basic.breakdown_search) | `short` | - | `short`, `medium`, `long` | ADC preset | short keeps the ramp fast |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: reliability.tddb_cvs
params: {v_stress: 5.5, duration: 600}
pin_map: mosfet-4t
dut_profile: dielectric-generic
sim_scenario: dielectric_tddb
```

BDV on the same film: `{recipe_id: dielectric.bdv, params: {method: linear, v_stop: 10.0}}`; quasi-pulsed on scenario
`dielectric_thick` with DUT `dielectric-thick`: `{v_stop: 30.0}` (an SMU on an RSU's From SMU input takes at most
+-25 V: R-RSU-01); junction: `basic.breakdown_search` on `diode-2t` (scenario `diode_basic`) with `{v_stop: -20.0}`.

## 5. Limits and confirmation

- `destructive` (R-ALWAYS-01) on every plan of the three recipes: show the summary verbatim, stop, run only after the
  human's consent. Ramps beyond the DUT profile add `dut_envelope`, above 10 V `soft_limit`; hard limits 42 V / 100 mA.
- TDDB: `long_run` above 600 s, asynchronous above 300 s (poll `get_run`; `safe_shutdown` cancels within one 25 s
  block), blocked above 24 h or 10001 points. BDV/breakdown search: one `XE`, synchronous, short.

## 6. Quality criteria

- TDDB: the breakdown sample reads `C` (`completed_with_flags`, the expected end); `time_source` must be `timestamp`.
- BDV / search: one row. Linear: source column status `N` (criterion reached), `G` (no breakdown up to `v_stop`),
  `S` (aborted); the current reads `C` at a hard breakdown. Quasi-pulsed: `C` = breakdown, `N` = reached `v_stop`,
  `S` = compliance before a 10 V change from `v_start` (use `method: linear`), `G` = detection timeout.
- Never re-stress or re-ramp a broken site; a new site is a new plan.

## 7. Analysis method

- TDDB `time_to_breakdown`: t_bd at the first `C` sample, a `jump_factor` (10) jump or `i_bd_a`; resolution one
  interval; no breakdown: the last time as a lower bound (censored). Weibull over sites in an agent script:
  `weibull_fit([load_run(r) for r in runs])` ([06b](../../knowledge/06b-analysis-time-pulse.md#time-to-breakdown-and-weibull)).
- BDV / search `breakdown_voltage` ([06b](../../knowledge/06b-analysis-time-pulse.md#breakdown-voltage)): BDV signed
  as forced (`fit.magnitude_v`), linear within one step (`window`); no breakdown: `v_stop` as a lower bound.
- Report: stress or ramp (V, field if `tox` is known), criterion, step, measured values and status counts; derived
  t_bd / BDV with method and resolution; SIMULATED on `sim`.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| thin SiO2 (2-5 nm) | E_bd 10-14 MV/cm; TDDB: slow rise, then a hard step | breakdown at the first point (site broken) |
| thick oxide / MIM (10-35 nm) | quasi-pulsed BDV 10-42 V, ramp-rate dependent | BDV far below the field (defects) |
| pn junction | reverse BV at 1 uA, soft knee | breakdown at a few volts (damaged, Zener) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| t_bd / BDV at the first point | site broken or leaky before the stress | low-voltage leakage on that site | `current-too-high` |
| `C` on a ground terminal, `S` | ground limited, wiring, compliance below the criterion | pin map, `icomp` >= `i_bd` | `compliance-hit` |
| quasi-pulsed `S` | breakdown within 10 V of `v_start` | `method: linear` | `errx-codes` |
| CVS `index_gaps`, host time | interval vs integration | `kind_result` | `smu-sampling-skips` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-19 | dielectric_tddb | dielectric-generic | S20261119T103619Z-174e | destructive + long_run; t_bd 120.08 s vs model 119.43 s (one 1 s interval); abort in block 5 of 25 | - |
| sim | 2026-11-22 | dielectric_tddb | dielectric-generic | S20261122T095613Z-c529 | `dielectric.bdv` linear: BDV 6.00 V vs model 6.00 V (+-2 %); quasi-pulsed reads `S` | - |
| sim | 2026-11-22 | dielectric_thick | dielectric-thick | S20261122T095614Z-bc98 | `dielectric.bdv` quasi-pulsed (MM 9): BDV 24.0 V vs model 24.0 V (+-2 %), status C | - |
| sim | 2026-11-22 | diode_basic | diode-generic | S20261122T095613Z-7dff | `basic.breakdown_search`: -12.0 V at 1 uA vs model -11.99995 V (one 0.1 V step) | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: plans via `B1500Service` with temporary config/data dirs (folders not kept). Hardware records:
`validation/hw/reliability.tddb_cvs.yaml`, `validation/hw/dielectric.bdv.yaml` and
`validation/hw/basic.breakdown_search.yaml` (reviewed by a human after bring-up stage L9, skill `b1500-bringup`; drafts
only from hardware `H...` runs, never from simulator `S...` runs).
