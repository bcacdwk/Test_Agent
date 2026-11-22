---
id: tddb-bdv
title: Dielectric breakdown — TDDB constant-voltage stress (t_bd, Weibull over sites); destructive
family: reliability
intent: [TDDB, time to breakdown, t_bd, dielectric breakdown, gate oxide reliability, Weibull, constant voltage stress]
recipes: [reliability.tddb_cvs]
device_types: [dielectric, moscap, nmos, pmos]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L9
status: sim_validated
confirmation: always
knowledge: [knowledge/05-reliability-defects.md#tddb-constant-voltage-stress, knowledge/06b-analysis-time-pulse.md#time-to-breakdown-and-weibull, knowledge/02-b1500-instrument.md#sampling-measurement-mm-10]
manual: [PG p472-473 (4-154) "MSC", PG p474-475 (4-156) "MT", PG p477 (4-159) "MV"]
debug: [compliance-hit, current-too-high, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 3.1 and 4.2, JEDEC JESD92, McPherson and Mogul J. Appl. Phys. 84 1513 (1998)]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Dielectric breakdown (TDDB)

## 1. Purpose and applicable devices

How long does a gate dielectric survive a constant voltage? `reliability.tddb_cvs` steps the gate from 0 V to
`v_stress` and samples the leakage every `interval` until breakdown drives the stress source into its compliance
(`icomp`): the sampling stops at once (automatic abort, the source returns to 0 V) and `time_to_breakdown` reports
t_bd. One site per run; Weibull statistics over many sites with `weibull_fit` (section 7). DESTRUCTIVE.

- Applies to MOS capacitors, MOSFET gate oxides (source, drain, bulk grounded) and MIM/high-k test structures.
- Not for: a non-destructive leakage check ([gate-leakage](../smu/gate-leakage.md)), current transients without
  breakdown ([smu-sampling](../smu/smu-sampling.md)). The voltage-ramp breakdown (BDV) part of this card arrives
  with `dielectric.bdv` (WP7.5).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: 0 → `v_stress` (MV), measures Ig | SMU4 (HRSMU; MPSMU/HPSMU allowed) | stress and sense |
| bulk | `bulk`: ground | GNDU | the stress current returns here |
| source, drain | `source`, `drain` (optional): ground | GNDU / SMU at 0 V | MOSFET landings only |

- Example pin map `mosfet-4t` (gate SMU4, drain SMU3 at 0 V, source and bulk GNDU) with DUT profile
  `dielectric-generic` (gate up to 6 V, 10 mA). The profile is the human's: never invent the oxide's limits.
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- A fresh, unstressed site; a gate-leakage check at low voltage first ([gate-leakage](../smu/gate-leakage.md)):
  a site that is already leaky or broken gives t_bd at the first sample (warning) and wastes nothing else.
- Choose `v_stress` from the film's breakdown voltage (80-95 % of BDV) on a sacrificial site; record the
  temperature (TDDB is thermally activated).
- `station_status` clean; plan one run per site, same stress, for a Weibull set.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_stress` | required | - | -40..40 V | constant stress voltage | higher: shorter life (field acceleration) |
| `icomp` | 1 mA | 10 uA..10 mA | 1 nA..0.1 A | breakdown current limit | the post-breakdown current never exceeds it |
| `interval` | 1 s | 0.1..10 s | 10 ms..60 s | t_bd resolution | 1 ms steps; points = duration / interval + 1 (≤ 10001) |
| `duration` | 3600 s | 60..86400 s | 1..86400 s | longest stress | the run ends earlier at breakdown |
| `hold_bias` | 0 s | - | 0..655.35 s | stress start to the first sample | 10 ms steps |
| `integration` | `medium` | `short`, `medium` | `short`, `medium`, `long` | ADC preset | |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: reliability.tddb_cvs
params: {v_stress: 5.5, duration: 600}
pin_map: mosfet-4t
dut_profile: dielectric-generic
sim_scenario: dielectric_tddb
```

## 5. Limits and confirmation

- `destructive` (R-ALWAYS-01) on every plan: show the summary verbatim, stop, run only after the human's consent.
- `long_run` above 600 s; above `max_sync_run_s` (300 s) the run is asynchronous (`running`: poll `get_run` with
  `include: [progress]`; `safe_shutdown` cancels within one 25 s block, outputs zeroed and verified); blocked above
  24 h. Points above the policy's 10001 are blocked (R-RUN-01): raise `interval` for long stresses.
- `dut_envelope` (R-DUT-01): `v_stress` or `icomp` beyond the profile's gate envelope; hard limits 42 V / 100 mA.
- Breakdown stops the stress at once (MSC automatic abort, source to 0 V); the cleanup zeroes and verifies.

## 6. Quality criteria

- The breakdown sample reads `C` (the gate in compliance): one limited point, so the run is `completed_with_flags`
  (`data quality limited`); that is the expected end of a TDDB run, not a fault. `V X F` before it are untrusted.
- `kind_result`: `aborted`, `abort_t_s`, `abort_reason`, `blocks_done`/`blocks_planned` (25 s blocks), `stopped_early`;
  `time_source` must be `timestamp` (else t_bd is from the sampling index: say so).
- Shape sanity: a slowly rising leakage (charge trapping, SILC), then a step of orders of magnitude.
- Never re-stress a broken site; a new site is a new plan.

## 7. Analysis method

- Default `time_to_breakdown` (`y`: the gate current): t_bd = `t_s` of the first sample in compliance (`C`), or with
  a current jump of `jump_factor` (10) over the median of the previous `window` (5) samples, or at `i_bd_a`;
  resolution one interval (`fit.t_prev_s`, `resolution_s`). No breakdown: the last time as a lower bound,
  `classification: no_breakdown` (censored).
- Weibull over sites (agent script; [06b](../../knowledge/06b-analysis-time-pulse.md#time-to-breakdown-and-weibull)):
  `from b1500_test_agent.analysis import load_run, weibull_fit` then `weibull_fit([load_run(r) for r in runs])` →
  `weibull_beta`, `weibull_eta` (63 % life) by MLE with censoring; at least 2 breakdowns.
- Report: stress (V, field if `tox` is known), interval, measured Ig(t) and status counts; derived t_bd with its
  resolution, or the censored time; Weibull beta, eta with n, failures, censored.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| thin SiO2 (2-5 nm) | Ig rises slowly, soft breakdown noise, then a hard step | step at the first sample (site already broken) |
| high-k stacks | trapping (Ig falls first), then progressive breakdown | t_bd spread far above Weibull beta ~1-2 |
| any | t_bd falls exponentially with `v_stress` | no breakdown even near BDV (contact open) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| t_bd = first sample | site broken or leaky before the stress | low-voltage gate leakage on that site | `current-too-high` |
| aborted with `C` on the drain or bulk | ground terminal limited, wiring | check the pin map and the ground compliance | `compliance-hit` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-19 | dielectric_tddb | dielectric-generic | S20261119T103619Z-174e | destructive + long_run; t_bd 120.08 s vs model 119.43 s (one 1 s interval); abort in block 5 of 25 | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware record: `validation/hw/reliability.tddb_cvs.yaml` (reviewed by a human after bring-up
stage L9, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
