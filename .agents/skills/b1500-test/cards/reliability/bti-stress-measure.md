---
id: bti-stress-measure
title: BTI stress-measure-stress — dVth(t) = A t^n at log read times, recovery; destructive
family: reliability
intent: [BTI, NBTI, PBTI, bias temperature instability, stress-measure-stress, Vth shift, dVth, power law, time exponent n, recovery]
recipes: [reliability.bti_sms]
device_types: [nmos, pmos, igzo_tft]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L9
status: sim_validated
confirmation: always
knowledge: [knowledge/05-reliability-defects.md#bti-stress-measure-stress, knowledge/05-reliability-defects.md#stress-measure-analysis, knowledge/06-analysis-extraction.md#vth-constant-current]
manual: [PG p474-475 (4-156) "MT", PG p472-473 (4-154) "MSC", PG p568 (4-250) "WV", PG p396 (4-78) "DV"]
debug: [vth-drift-igzo, compliance-hit, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 3.1 2.7 and 4.2, deck slide 14, Kaczer et al. IRPS 2008]
version: 1
---

# BTI stress-measure-stress

## 1. Purpose and applicable devices

How fast does the threshold drift under a gate bias, and how much comes back? `reliability.bti_sms` reads an Id-Vg
(reference), stresses the gate at `vg_stress` (drain, source, bulk at 0 V), interrupts the stress for an Id-Vg read
at log-spaced cumulative stress times and, with `recovery_time`, reads again while the gate rests at `vg_recovery`.
`bti_power_law` fits dVth = A t^n and the recovered fraction. DESTRUCTIVE (part of the shift is permanent).

- Applies to MOSFETs (nMOS PBTI: `vg_stress` > 0; pMOS NBTI: `vg_stress` < 0) and TFTs (prefer
  [igzo-bias-stress](igzo-bias-stress.md) for the stretched-exponential IGZO law).
- Not for: drain stress (HCI: [hci-silc](hci-silc.md)), leakage growth (SILC: [hci-silc](hci-silc.md)), breakdown
  life ([tddb-bdv](tddb-bdv.md)), µs reads without recovery (`wgfmu.fast_bti`, reserved), a single Id-Vg
  ([mosfet-idvg](../smu/mosfet-idvg.md)). Never imitate a stress with repeated sweeps.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: read sweep `vg_start`..`vg_stop`; stress `vg_stress`; recovery `vg_recovery` | SMU4 (HRSMU) | measures Ig in every phase |
| drain | `drain`: read `vd`; stress `vd_stress` (0 V) | SMU3 (HRSMU) | measures Id |
| source | `source`: ground | GNDU | |
| bulk | `bulk`: ground (optional) | GNDU | |

- Example pin map `mosfet-4t` with DUT profile `nmos-generic` (gate, drain ≤ 3 V, 1 mA). The pin map and the
  profile are the human's: never invent them.
- Routes: none in every phase (direct SMU and GNDU wiring); ASU-bound roles get the ASU path at the start.

## 3. Pre-run checklist

- A fresh, unstressed device: [contact-resistor-check](../smu/contact-resistor-check.md), then one
  [mosfet-idvg](../smu/mosfet-idvg.md) so the read sweep spans the Vth criterion (100 nA by default) with margin for
  the shift; check the gate leakage ([gate-leakage](../smu/gate-leakage.md)) below `icomp_gate` at `vg_stress`.
- Record the temperature (BTI is thermally activated; the station has no chuck control in the kernel).
- `station_status` clean; plan one device per stress condition.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_stress` | required | - | -10..10 V | gate stress | higher: faster shift (power of V); above the profile: confirmation |
| `stress_time` | 1000 s | 100..10000 s | 0.1..86400 s | total stress (last read) | > 600 s `long_run`; > 300 s async |
| `schedule` | `log` | `log` | `log`, `list` | read times | list = `read_times` |
| `first_read` | 1 s | 0.1..10 s | 0.02..3600 s | first read (also recovery) | 10 ms grid |
| `reads_per_decade` | 3 | 2..5 | 1..20 | log density | more reads: more recovery during reads |
| `read_times` | [1, 10, 100, 1000] s | - | 0.02..86400 s | list schedule | ignored for `log` |
| `recovery_time` | 0 s | 0..3600 s | 0..86400 s | recovery after the stress | 0 = none |
| `vg_recovery` | 0 V | - | -10..10 V | gate during recovery | |
| `read_kind` | `staircase` | `staircase` | `staircase`, `spot` | Vth per read | spot: Id at `vg_read` (faster) |
| `vg_start` | -0.2 V | -1..0 V | -10..10 V | read sweep start | |
| `vg_stop` | 1.5 V | 1..3 V | -10..10 V | read sweep stop | |
| `vg_points` | 35 | 21..61 | 11..401 | read points | fewer: a shorter read |
| `vg_read` | 1 V | - | -10..10 V | spot read gate level | |
| `vd` | 50 mV | 20..100 mV | -5..5 V | read drain bias | linear region |
| `vd_stress` | 0 V | - | -5..5 V | drain during stress | 0 V for BTI |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | gate limit, every phase | a breakdown stops the run |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | drain limit | |
| `samples` | 1 | - | 1..100 | spot samples per read | |
| `integration` | `medium` | `short`, `medium` | `short`, `medium`, `long` | read ADC | `short`: shorter reads |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: reliability.bti_sms
params: {vg_stress: 2.0, stress_time: 1800}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_bti
```

## 5. Limits and confirmation

- `destructive` (R-ALWAYS-01) on every plan; `long_run` above 600 s; asynchronous above `max_sync_run_s` (300 s):
  `running`, poll `get_run` with `include: [progress]`; `safe_shutdown` cancels within one 25 s hold block (outputs
  zeroed and verified, rows kept as PARTIAL). Blocked above 24 h or 10001 points (R-RUN-01/02).
- The summary shows the read levels, `stress <V> V` per channel and `stress <time> x<n> reads`: read it back.
- `dut_envelope` (R-DUT-01) when `vg_stress` or a read level exceeds the profile; hard limits 42 V / 100 mA.
- A compliance, overflow or oscillation in a hold block or a read stops the run (`kind_result.stop_reason`).

## 6. Quality criteria

- Every read all `N`; a read with `C`/`T` stops the run (widen the compliance only after asking the human).
- `kind_result`: `reads_done`/`reads_planned`, `holds_done`, `stress_s_done`, `stopped_early`.
- The constant-current crossing must stay inside the read sweep for every read (a shift past `vg_stop` fails it).
- The hold rows' gate current should stay flat; a rising Ig is SILC or soft breakdown (stop and report).

## 7. Analysis method

- Default `bti_power_law` (`vth_method: constant_current`, 100 nA; `linear_extrapolation` uses `vd`): `n`, `a`
  (|dVth| at 1 s), `dvth` (signed, last stress read); with recovery reads `recovery`, `recovery_rate`.
  `min_change` (1 mV) drops reads lost in the noise; `t_min`/`t_max` restrict the fit.
- `degradation_vs_time` (`quantity: id`, `at_v`) for the drain current loss; `plot_timeseries` (`log_time: true`).
- Report: stress V, time, read times and read duration, `n` and `A` with r2 and reads used, measured status counts.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| nMOS PBTI (SiO2/HfO2) | dVth > 0, n 0.1-0.3 `TODO(verify)` | n > 0.5 (charging, temperature drift) |
| pMOS NBTI | dVth < 0 (Vth more negative), n 0.1-0.25 | no shift at a high field (contact, wiring) |
| recovery | fast first decades, log-like | negative recovery (still stressing) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| stopped: read with `C` on the drain | `icomp_drain` too low for the read | Id at `vg_stop` from the reference read | `compliance-hit` |
| stopped: hold block `C` on the gate | gate breakdown / leaky stack | low-voltage gate leakage | `current-too-high` |
| dVth scattered, n off | noisy reads, recovery during reads | fewer points, `short` | `noisy-data` |
| Vth drifts without stress | trapping, temperature | rest the device, repeat the reference read | `vth-drift-igzo` |
| run `failed`, fault latched | instrument error, unverified cleanup | `safe_shutdown`, skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-20 | nmos_bti | nmos-generic | S20261120T041646Z-6a34 | destructive + long_run, async; 2 V, 1800 s, 11 reads: n 0.199 vs 0.2, A 20.2 mV vs 20 mV | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware record: `validation/hw/reliability.bti_sms.yaml` (reviewed by a human after bring-up
stage L9, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
