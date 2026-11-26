---
id: hci-silc
title: HCI and SILC — drain-current degradation b t^m under hot-carrier stress; stress-induced gate leakage; destructive
family: reliability
intent: [HCI, hot carrier, hot-carrier injection, drain degradation, dId/Id0, Idlin, SILC, stress-induced leakage, gate leakage growth, injected charge]
recipes: [reliability.hci, reliability.silc]
device_types: [nmos, pmos]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L9
status: sim_validated
confirmation: always
knowledge: [knowledge/05-reliability-defects.md#hot-carrier-injection-hci, knowledge/05-reliability-defects.md#oxide-traps-silc-and-charge-trapping, knowledge/05-reliability-defects.md#stress-measure-analysis]
manual: [PG p474-475 (4-156) "MT", PG p472-473 (4-154) "MSC", PG p470 (4-152) "MM", PG p396 (4-78) "DV"]
debug: [stress-degradation-unexpected, compliance-hit, current-too-high, noisy-data, errx-codes, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 3.1 2.7 and 4.2, deck slide 14, Takeda and Suzuki IEEE EDL 4 111 (1983), DiMaria and Cartier JAP 78 3883 (1995)]
version: 1
---

# HCI and SILC

## 1. Purpose and applicable devices

Two stress-measure-stress tests on the kind of [bti-stress-measure](bti-stress-measure.md), with spot reads:

- `reliability.hci`: gate at `vg_stress` and drain at `vd_stress` together (channel on, hot carriers at the
  drain), reads of the linear-region Id at `vg_read`, `vd_read`; `degradation_vs_time` fits dId/Id0 = b t^m.
- `reliability.silc`: a high-field gate stress (`vg_stress`; drain, source, bulk at 0 V), reads of the low-field gate
  leakage at `v_sense`; `silc` reports (Ig - Ig0)/Ig0, its exponent, Ig0 and the injected charge q_inj.

Both DESTRUCTIVE. Not for: gate-only stress (BTI), breakdown life ([tddb-bdv](tddb-bdv.md)), a non-destructive
leakage check ([gate-leakage](../smu/gate-leakage.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: read `vg_read` (HCI) / `v_sense` (SILC); stress `vg_stress` | SMU4 (HRSMU) | measures Ig; SILC wants an HRSMU |
| drain | HCI `drain`: read `vd_read`, stress `vd_stress`; SILC `drain`: 0 V | SMU3 (HRSMU) | HCI measures Id |
| source | `source`: ground | GNDU | |
| bulk | `bulk`: ground | GNDU | the SILC current returns here |

- Example pin map `mosfet-4t` with DUT profile `nmos-generic` (gate, drain ≤ 3 V, 1 mA): the profile is the
  human's. HCI damage sits at the drain end: a reverse read needs a pin map with drain and source swapped.
- SMU4/SMU3 on the RSUs' "From SMU" inputs (lab layout after L8) take at most +-25 V (WG p20 (1-8), R-RSU-01).
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- A fresh device: [contact-resistor-check](../smu/contact-resistor-check.md), one Id-Vg
  ([mosfet-idvg](../smu/mosfet-idvg.md)); HCI: the stress drain current below `icomp_drain`; SILC: the leakage at
  `v_sense` above the floor ([gate-leakage](../smu/gate-leakage.md)) and `vg_stress` below the breakdown voltage.
- HCI: keep `vg_stress` below the BTI onset (about Vd/2 for long NMOS); record the temperature.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_stress` (`reliability.hci`) | required | - | -10..10 V | gate stress | Vg ~ Vd/2 (long NMOS) |
| `vg_stress` (`reliability.silc`) | required | - | -40..40 V | high-field gate stress | below breakdown |
| `vd_stress` | required | - | -10..10 V | HCI drain stress | b ~ Vd^k |
| `stress_time` | 1000 s | 100..10000 s | 0.1..86400 s | total stress | > 600 s `long_run`, async |
| `schedule` | `log` | `log` | `log`, `list` | read times | |
| `first_read` | 1 s | 0.1..10 s | 0.02..3600 s | first read | 10 ms grid |
| `reads_per_decade` | 3 | 2..5 | 1..20 | log density | |
| `read_times` | [1, 10, 100, 1000] s | - | 0.02..86400 s | list schedule | ignored for `log` |
| `recovery_time` (`reliability.hci`) | 0 s | 0..600 s | 0..86400 s | rest at 0 V | HCI hardly recovers |
| `recovery_time` (`reliability.silc`) | 0 s | 0..600 s | 0..86400 s | rest at 0 V | |
| `read_kind` | `spot` | `spot` | `spot`, `staircase` | the read | staircase: a sweep per read |
| `vg_read` | 1.5 V | 1..3 V | -10..10 V | HCI read gate | strong inversion |
| `vd_read` | 50 mV | 20..100 mV | -5..5 V | HCI read drain | linear region |
| `v_sense` | 1.5 V | 0.5..2 V | -40..40 V | SILC sense level | low field, stress polarity |
| `vg_start` (`reliability.hci`) | -0.2 V | - | -10..10 V | sweep reads | |
| `vg_start` (`reliability.silc`) | 0 V | - | -40..40 V | sweep reads | |
| `vg_stop` (`reliability.hci`) | 1.5 V | - | -10..10 V | sweep reads | |
| `vg_stop` (`reliability.silc`) | 2 V | - | -40..40 V | sweep reads | |
| `vg_points` (`reliability.hci`) | 35 | - | 11..401 | sweep reads | |
| `vg_points` (`reliability.silc`) | 21 | - | 11..401 | sweep reads | |
| `icomp_gate` (`reliability.hci`) | 1 uA | - | 1 pA..1 mA | gate limit | |
| `icomp_gate` (`reliability.silc`) | 100 uA | 1 uA..1 mA | 1 pA..10 mA | breakdown current limit | a breakdown stops the run |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | HCI drain limit | above the stress current |
| `samples` (`reliability.hci`) | 3 | - | 1..100 | spot samples averaged | |
| `samples` (`reliability.silc`) | 5 | - | 1..100 | spot samples averaged | sets the noise threshold |
| `integration` (`reliability.hci`) | `medium` | `medium` | `short`, `medium`, `long` | read ADC | |
| `integration` (`reliability.silc`) | `long` | `long` | `short`, `medium`, `long` | read ADC | pA leakage |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: reliability.hci
params: {vg_stress: 1.2, vd_stress: 2.5}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_bti
```

SILC: `recipe_id: reliability.silc`, `params: {vg_stress: 2.8}`, same pin map, profile and scenario.

## 5. Limits and confirmation

- `destructive` on every plan; `long_run` above 600 s; asynchronous above 300 s (`get_run` with
  `include: [progress]`; `safe_shutdown` cancels within one 25 s hold block, rows kept as PARTIAL).
- The summary shows `stress <V> V` per channel (HCI: gate and drain) and `stress <time> x<n> reads`.
- `dut_envelope` above the profile; hard limits 42 V / 100 mA. A compliance in a hold block or read stops the run.

## 6. Quality criteria

- Reads all `N`; a `C` on the gate during a SILC hold is a breakdown (stop; report it, never retry higher).
- `kind_result`: `reads_done`, `holds_done`, `stress_s_done`, `stopped_early`, `stop_reason`.
- HCI: the reference Id noise (samples) well below 0.1 %; SILC: the reference leakage above the floor.

## 7. Analysis method

- HCI default `degradation_vs_time` (`quantity: id`, `y: drain_I`, relative): `delta`, `b` (signed dId/Id0 at 1 s),
  `m`; `min_change` 1e-3. With `read_kind: staircase` also `bti_power_law` for the Vth part.
- SILC default `silc` (`v_sense` from the plan): `silc_ratio`, `silc_exponent` (reads above max(2 %, 3 sigma of the
  reference read)), `ig0`, `q_inj` (C, the stress current integrated over `t_s`).
- Report stress conditions, read times, derived values with r2 and reads used, measured status counts.

## 8. Expected result shape

| test | typical | red flags |
|---|---|---|
| HCI (long NMOS) | dId/Id0 < 0, m 0.3-0.6 `TODO(verify)` | dId > 0 (heating, trapping), m > 1 |
| SILC (thin SiO2) | ratio rises steadily, exponent 0.3-1 | a step of decades (breakdown) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| stopped: hold `C` on the drain | stress current above `icomp_drain` | Id at the stress bias (reference Id-Vd) | `compliance-hit` |
| stopped: hold `C` on the gate | oxide breakdown | low-voltage leakage | `current-too-high` |
| m or exponent scattered | read noise vs a small change | more `samples`, `long` integration | `noisy-data` |
| no shift, wrong sign, huge shift | stress too weak, recovery, polarity, breakdown | reference read, Ig trend | `stress-degradation-unexpected` |
| run `failed`, fault latched | instrument error, unverified cleanup | `safe_shutdown`, skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-20 | nmos_bti | nmos-generic | S20261120T041648Z-b07e | HCI 1.2/2.5 V, 1000 s: m 0.450 vs 0.45, b -6.45e-3 vs -6.64e-3 | - |
| sim | 2026-11-20 | nmos_bti | nmos-generic | S20261120T041648Z-b051 | SILC 2.8 V, 1000 s: ratio 2.77 vs 2.76, exponent 0.995 vs 1 | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: the example plans run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run
folders were not kept. Hardware records: `validation/hw/reliability.hci.yaml`, `validation/hw/reliability.silc.yaml`
(reviewed by a human after bring-up stage L9, skill `b1500-bringup`; drafts only from hardware `H...` runs).
