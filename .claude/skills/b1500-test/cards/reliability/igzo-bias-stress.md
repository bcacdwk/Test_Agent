---
id: igzo-bias-stress
title: IGZO TFT bias stress (PBS/NBS) — dVth(t) stretched exponential tau, beta, dV_inf; recovery; destructive
family: reliability
intent: [IGZO, oxide TFT, bias stress, PBS, NBS, positive bias stress, negative bias stress, Vth shift, dVth(t), stretched exponential, tau, beta]
recipes: [igzo.bias_stress]
device_types: [igzo_tft, nmos]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L9
status: sim_validated
confirmation: always
knowledge: [knowledge/05-reliability-defects.md#igzo-instability-mechanisms, knowledge/05-reliability-defects.md#stress-measure-analysis, knowledge/06b-analysis-time-pulse.md#sampling-summary-and-relaxation-fit]
manual: [PG p474-475 (4-156) "MT", PG p472-473 (4-154) "MSC", PG p568 (4-250) "WV", PG p396 (4-78) "DV"]
debug: [stress-degradation-unexpected, vth-drift-igzo, compliance-hit, noisy-data, errx-codes, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 3.1 2.7 and 4.2, deck slide 17, Libsch and Kanicki APL 62 1286 (1993)]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# IGZO bias stress (PBS/NBS)

## 1. Purpose and applicable devices

How does the TFT threshold move under a constant gate bias, and with what time constant? `igzo.bias_stress` reads a
reference Id-Vg, holds the gate at `vg_stress` (PBS > 0: Vth up; NBS < 0: Vth down; drain and source at 0 V) and
reads Id-Vg at log-spaced cumulative stress times; with `recovery_time` it reads again while the gate rests at
`vg_recovery`. `degradation_vs_time` fits dVth(t) = dV_inf (1 - exp(-(t/tau)^beta)). DESTRUCTIVE.

- Applies to IGZO and other oxide TFTs (dark, at the station temperature); MOSFETs work too (power-law view:
  [bti-stress-measure](bti-stress-measure.md)).
- Not for: the continuous Id(t) after a gate step ([smu-sampling](../smu/smu-sampling.md), non-destructive at
  modest bias), a single Id-Vg ([mosfet-idvg](../smu/mosfet-idvg.md)), illumination stress (NBIS: no light source).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: read sweep `vg_start`..`vg_stop`; stress `vg_stress`; recovery `vg_recovery` | SMU4 (HRSMU) | measures Ig |
| drain | `drain`: read `vd`; 0 V during the holds | SMU3 (HRSMU) | measures Id |
| source | `source`: ground | GNDU | |

- Example pin map `mosfet-4t` with DUT profile `nmos-generic` (3 V): no IGZO DUT profile is committed; for an IGZO
  sample ask the human for its pins and limits (never invent them). Typical IGZO stresses (10-20 V) need a profile.
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- Rest the TFT unbiased (minutes) and keep the station dark; note temperature and humidity (back-channel
  adsorption, [05](../../knowledge/05-reliability-defects.md#igzo-instability-mechanisms)).
- One Id-Vg first ([mosfet-idvg](../smu/mosfet-idvg.md)): the read sweep must span the 1 nA crossing after the
  expected shift (PBS moves it right, NBS left).
- `station_status` clean; one device per stress condition.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_stress` | required | - | -20..20 V | PBS > 0, NBS < 0 | dV_inf scales with it; above the profile: confirmation |
| `stress_time` | 300 s | 100..10000 s | 0.1..86400 s | total stress | > 300 s async; > 600 s `long_run` |
| `schedule` | `log` | `log` | `log`, `list` | read times | |
| `first_read` | 100 ms | 0.1..1 s | 0.02..3600 s | first read (also recovery) | 10 ms grid |
| `reads_per_decade` | 4 | 3..6 | 1..20 | log density | the fit needs 8 reads |
| `read_times` | [0.1, 1, 10, 100, 300] s | - | 0.02..86400 s | list schedule | ignored for `log` |
| `recovery_time` | 0 s | 0..3600 s | 0..86400 s | recovery after the stress | 0 = none |
| `vg_recovery` | 0 V | - | -20..20 V | gate during recovery | |
| `read_kind` | `staircase` | `staircase` | `staircase`, `spot` | Vth per read | spot: Id at `vg_read` |
| `vg_start` | -1 V | -3..0 V | -20..20 V | read sweep start | |
| `vg_stop` | 3 V | 2..10 V | -20..20 V | read sweep stop | |
| `vg_points` | 41 | 21..81 | 11..401 | read points | fewer: less disturbance |
| `vg_read` | 2 V | - | -20..20 V | spot read level | |
| `vd` | 100 mV | 50..500 mV | -20..20 V | read drain bias | linear region |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | gate limit | |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | drain limit | |
| `samples` | 1 | - | 1..100 | spot samples per read | |
| `integration` | `medium` | `short`, `medium` | `short`, `medium`, `long` | read ADC | |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: igzo.bias_stress
params: {vg_stress: 3.0}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: igzo_transient
```

## 5. Limits and confirmation

- `destructive` (R-ALWAYS-01) on every plan; asynchronous above 300 s (poll `get_run` with `include: [progress]`;
  `safe_shutdown` cancels within one 25 s hold block, rows kept as PARTIAL); `long_run` above 600 s.
- The summary shows `stress <V> V` on the gate and `stress <time> x<n> reads`: check the polarity (PBS/NBS).
- `dut_envelope` (R-DUT-01) above the profile's gate envelope; hard limits 42 V / 100 mA.
- A compliance, overflow or oscillation in a hold block or a read stops the run (`kind_result.stop_reason`).

## 6. Quality criteria

- Every read all `N`; the 1 nA crossing inside every read; reads in order (`cycle` 0..n, `t_s` rising).
- `kind_result`: `reads_done`, `holds_done`, `stress_s_done`, `stopped_early`.
- A shift that never saturates within the stress (tau beyond 3x the last read) is flagged: stress longer.

## 7. Analysis method

- Default `degradation_vs_time` (`quantity: vth`, `fit: stretched_exp`, `i_crit_a: 1e-9`): `delta` (dVth at the
  last read), `tau` (s), `beta`, `delta_inf` (V); with recovery reads `recovery`.
- `bti_power_law` (`i_crit_a: 1e-9`) for the power-law exponent; `plot_timeseries` with `log_time: true`.
- Report: stress V and polarity, read times, Vth criterion, tau, beta, dV_inf with r2 and reads, status counts.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| IGZO PBS (dark) | dVth > 0, beta 0.3-0.7, tau s..h `TODO(verify)` | dVth < 0 under PBS (hydrogen, light) |
| IGZO NBS (dark) | small dVth < 0 | large NBS shift in the dark (light leak) |
| recovery | slow, partial | full recovery in seconds (only fast traps) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| reference Vth differs run to run | previous stress, humidity, light | rest the device, repeat one Id-Vg | `vth-drift-igzo` |
| stopped: read with `C` | read compliance too low | Id at `vg_stop` of the reference read | `compliance-hit` |
| tau/beta at the grid edge | too few reads, short stress | more reads per decade, longer stress | `noisy-data` |
| no shift, wrong sign, huge shift | stress too weak, recovery, polarity, breakdown | reference read, Ig trend | `stress-degradation-unexpected` |
| run `failed`, fault latched | instrument error, unverified cleanup | `safe_shutdown`, skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-20 | igzo_transient | nmos-generic | S20261120T041647Z-1061 | destructive, async; PBS 3 V, 300 s, 15 reads: tau 3.84 s vs 4 s, beta 0.484 vs 0.5, dV_inf 0.150 V | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware record: `validation/hw/igzo.bias_stress.yaml` (reviewed by a human after bring-up stage
L9, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
