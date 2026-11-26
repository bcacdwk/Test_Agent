---
id: bti-stress-measure
title: BTI stress-measure-stress — dVth(t) = A t^n at log read times (SMU reads or WGFMU µs reads), recovery; destructive
family: reliability
intent: [BTI, NBTI, PBTI, bias temperature instability, stress-measure-stress, fast BTI, ultra-fast BTI, WGFMU, Vth shift, dVth, power law, recovery]
recipes: [reliability.bti_sms, wgfmu.fast_bti]
device_types: [nmos, pmos, igzo_tft]
modules: [HRSMU, MPSMU, GNDU, WGFMU]
routes: [rsu:wgfmu]
bringup_stage: L9
status: sim_validated
confirmation: always
knowledge: [knowledge/05-reliability-defects.md#bti-stress-measure-stress, knowledge/05-reliability-defects.md#stress-measure-analysis, knowledge/06-analysis-extraction.md#vth-constant-current, knowledge/11-switching-routing.md#rsu-of-the-wgfmu]
manual: [PG p474-475 (4-156) "MT", PG p472-473 (4-154) "MSC", PG p396 (4-78) "DV", WG p125 (4-55) "setMeasureEvent", WG p66 (3-26) "Example 10", WG p19 (1-7) "SMU input"]
debug: [stress-degradation-unexpected, vth-drift-igzo, compliance-hit, noisy-data, wgfmu-range-overflow, wgfmu-library-error, errx-codes, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 3.1 3.4 2.7 2.7.1 and 4.2, "deck slide 14 (topics only, illustrative: not evidence)", AN-REL p7, "Kaczer et al. IRPS 2008 (not page-checked, TODO(cite))", "WG Ex. 10 and 11 (SMU bias and SMU sampling with the WGFMU via the RSU SMU path, WG p66 (3-26), WG p68 (3-28); not BTI examples)"]
version: 2
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# BTI stress-measure-stress

## 1. Purpose and applicable devices

How fast does the threshold drift under a gate bias, and how much comes back? A reference read, then the gate at
`vg_stress` (drain, source, bulk at 0 V) interrupted by reads at log-spaced stress times, then (`recovery_time`)
reads at `vg_recovery`. DESTRUCTIVE (part of the shift is permanent). nMOS PBTI `vg_stress` > 0, pMOS NBTI < 0.

- `reliability.bti_sms` (SMUs): an Id-Vg per read (about a second; part of the shift recovers during it).
- `wgfmu.fast_bti` (WGFMU on gate and drain via the RSUs): the WGFMU holds the stress and senses for ~20 µs
  (`vg_points` x (`edge` + `width`)) or ~1 µs (`read_kind: spot`): read before it recovers; first reads from 10 µs.
- Not for: HCI/SILC ([hci-silc](hci-silc.md)), breakdown ([tddb-bdv](tddb-bdv.md)), IGZO TFTs ([igzo-bias-stress](igzo-bias-stress.md)), one Id-Vg ([mosfet-idvg](../smu/mosfet-idvg.md)); no sweeps as stress.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: read sweep, `vg_stress`, `vg_recovery` | SMU4 (HRSMU) / WGFMU 201 via `RSU201.OUT` | SMU: measures Ig; WGFMU: no measurement |
| drain | `drain`: read `vd`, `vd_stress` (0 V) | SMU3 (HRSMU) / WGFMU 202 via `RSU202.OUT` | measures Id (WGFMU: on `irange`) |
| source | `source`: ground | GNDU | |
| bulk | `bulk`: ground (SMU) / optional SMU bias `vb` (WGFMU) | GNDU / SMU5 (MPSMU) | WGFMU: body bias held, Ib read between executions |

- SMU: pin map `mosfet-4t`, profile `nmos-generic`; WGFMU: `mosfet-wgfmu` (bulk SMU5: `mosfet-wgfmu-body`),
  `nmos-wgfmu`. With SMU4/SMU3 on the RSUs' "From SMU" inputs (then at most +-25 V, 100 mA: WG p20 (1-8), R-RSU-01)
  DC Id-Vg on `mosfet-4t` before and after a fast run reaches its device (ATV-32). Never invent pin maps or profiles.
- Routes per phase: WGFMU RSU20x.OUT -> wgfmu (`waveform`), then rest (`unverified_topology` until verified); SMU: none.

## 3. Pre-run checklist

- A fresh, unstressed device: [contact-resistor-check](../smu/contact-resistor-check.md), one
  [mosfet-idvg](../smu/mosfet-idvg.md) so the read sweep spans the Vth criterion (SMU 100 nA, WGFMU 1 µA) with margin
  for the shift; gate leakage ([gate-leakage](../smu/gate-leakage.md)) below `icomp_gate` at `vg_stress`.
- WGFMU: `irange` above Id at `vg_stop` (saturation stops the run; no compliance, <= 10 V: WG p16 (1-4)). Record the
  temperature (BTI is thermally activated, AN-REL p7); plan one device per stress condition.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_stress` | required | - | -10..10 V | gate stress | higher: faster shift; above the profile: confirmation |
| `stress_time` (reliability.bti_sms) | 1000 s | 100..10000 s | 0.1..86400 s | total stress | > 600 s `long_run`; > 300 s async |
| `stress_time` (wgfmu.fast_bti) | 1000 s | 10..10000 s | 100 us..86400 s | total stress | as above |
| `schedule` | `log` | `log` | `log`, `list` | read times | list = `read_times` |
| `first_read` (reliability.bti_sms) | 1 s | 0.1..10 s | 0.02..3600 s | first read (also recovery) | 10 ms grid |
| `first_read` (wgfmu.fast_bti) | 1 ms | 0.1..10 ms | 10 us..3600 s | first read (also recovery) | 10 ns grid |
| `reads_per_decade` | 3 | 2..5 | 1..20 | log density | SMU: more reads, more recovery |
| `recovery_time` | 0 s | 0..3600 s | 0..86400 s | recovery after the stress | 0 = none |
| `vg_recovery` | 0 V | - | -10..10 V | gate during recovery | |
| `read_kind` | `staircase` | `staircase` | `staircase`, `spot` | Vth per read | spot: one level (shortest read) |
| `vg_start` (reliability.bti_sms) | -0.2 V | -1..0 V | -10..10 V | read sweep start | |
| `vg_stop` (reliability.bti_sms) | 1.5 V | 1..3 V | -10..10 V | read sweep stop | |
| `vg_points` (reliability.bti_sms) | 35 | 21..61 | 11..401 | read points | fewer: a shorter read |
| `vg_start` (wgfmu.fast_bti) | 0.2 V | 0..0.5 V | -10..10 V | sense staircase start | |
| `vg_stop` (wgfmu.fast_bti) | 1 V | 0.8..1.5 V | -10..10 V | sense staircase stop | Id(vg_stop) < `irange` |
| `vg_points` (wgfmu.fast_bti) | 17 | 9..33 | 2..201 | sense steps | read_s = steps x (edge + width) + edge |
| `vg_read` (wgfmu.fast_bti) | 0.5 V | - | -10..10 V | spot sense level | near the reference Vth |
| `vd` (reliability.bti_sms) | 50 mV | 20..100 mV | -5..5 V | read drain bias | linear region |
| `vd` (wgfmu.fast_bti) | 100 mV | 50..100 mV | -5..5 V | sense drain bias | linear region |
| `vd_stress` | 0 V | - | -5..5 V | drain during stress | 0 V for BTI |
| `irange` (wgfmu.fast_bti) | `100ua` | - | `1ua`, `10ua`, `100ua`, `1ma`, `10ma` | drain range | saturates (V) above it |
| `width` (wgfmu.fast_bti) | 1 us | 0.5..10 us | 20 ns..1 ms | flat time per sense step | longer: less noise, more recovery |
| `edge` (wgfmu.fast_bti) | 100 ns | 70 ns..1 us | 10 ns..10 us | between levels (>= 70 ns limits overshoot, WG5 p25 (1-15)) | |
| `settle` (wgfmu.fast_bti) | 500 ns | 100 ns..5 us | 0..1 ms | left out of each average | |
| `icomp_gate` (reliability.bti_sms) | 1 uA | - | 1 pA..1 mA | gate limit, every phase | a breakdown stops the run |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: wgfmu.fast_bti
params: {vg_stress: 2.0, stress_time: 100}
pin_map: mosfet-wgfmu
dut_profile: nmos-wgfmu
sim_scenario: nmos_bti
```

## 5. Limits and confirmation

- `destructive` (R-ALWAYS-01) always; WGFMU also `unverified_topology`; `long_run` > 600 s; async > 300 s: poll
  `get_run` (`include: [progress]`); `safe_shutdown` cancels (SMU: one 25 s hold block, WGFMU: one 1 s poll; outputs
  zeroed and verified, rows kept as PARTIAL). The summary shows `stress <V> V` per channel and `stress <t> x<n> reads`.
- `dut_envelope` (R-DUT-01) above the profile; hard limits 42 V / 100 mA; WGFMU levels R-WG-02.
- A compliance, overflow or oscillation (SMU) or a saturated WGFMU reading (`V`) stops the run (`stop_reason`).

## 6. Quality criteria

- Every read all `N`; `C`/`T`/`V` stops the run (widen a compliance or range only after asking the human).
- `kind_result`: `reads_done`/`reads_planned`, `holds_done`, `stress_s_done`, `stopped_early` (+ WGFMU `read_s`).
- The Vth criterion stays inside every read sweep; a rising hold-row Ig is SILC or soft breakdown (stop, report).

## 7. Analysis method

- SMU: `bti_power_law` (`constant_current` 100 nA or `linear_extrapolation`): `n`, `a` (|dVth| at 1 s), `dvth`,
  with recovery reads `recovery`, `recovery_rate`; `min_change` (1 mV) drops reads lost in the noise.
- WGFMU: `fast_bti_shift` (`auto`: own staircase at 1 µA, spot reads against the reference read's curve): the
  same results, `fit.read_s` and `fit.read_fraction` (warning above 2 % of the first stress interval).
- `degradation_vs_time` (`quantity: id`), `plot_timeseries` (`log_time: true`). Report stress V and time, read times
  and duration; `n`, `A` as results of the named method (Vth criterion, r2, reads used); status counts; backend.
- After a stop (`safe_shutdown`): run id, outcome (`cancelled`, or `aborted` when a recovery finalized it), "cleanup
  verified" (or not, from the `cleanup` result) and the rows so far as partial data.

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| device | expected (source) | red flags |
|---|---|---|
| nMOS PBTI | dVth > 0 (sign); n unknown for your stack ([05](../../knowledge/05-reliability-defects.md#bti-stress-measure-stress)): report n with r2 | n changing between identical runs, poor r2 (charging, temperature drift) |
| pMOS NBTI | dVth < 0, Vth more negative (AN-REL p7); n unknown for your stack | no shift at a high field (contact, wiring) |
| fast vs SMU reads | fast dVth >= SMU dVth (recovery during slow reads, AN-REL p7) | fast < SMU (wrong landing, range) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| stopped: `C` (SMU) or `V` (WGFMU) on the drain | compliance or `irange` below the read current | Id at `vg_stop` in the reference read | `compliance-hit`, `wgfmu-range-overflow` |
| stopped: gate `C` in a hold | gate breakdown / leaky stack | low-voltage gate leakage | `current-too-high` |
| dVth scattered, n off | noise, recovery during reads | fewer points, longer `width` (WGFMU) | `noisy-data` |
| no shift, wrong sign, huge shift | stress too weak, polarity, breakdown | reference read, Ig trend | `stress-degradation-unexpected` |
| WGFMU library error; run `failed`, fault latched | library, RSU; unverified cleanup | `safe_shutdown`, `b1500 doctor` | `wgfmu-library-error`, `errx-codes`, `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-20 | nmos_bti | nmos-generic | S20261120T041646Z-6a34 | bti_sms on mosfet-4t, 2 V, 1800 s, 11 reads: n 0.199 vs 0.2, A 20.2 mV vs 20 mV | - |
| sim | 2026-11-24 | nmos_bti | nmos-wgfmu | S20261124T103806Z-d763 | fast_bti 2 V, 100 s, 16 reads: n 0.202, A 19.6 mV, dVth(100 s) 50.3 vs 50.2 mV | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: example plans via `B1500Service` (temporary config and data; folders not kept). Hardware records (human-reviewed
after L9, `b1500-bringup`; only from `H...` runs): `validation/hw/reliability.bti_sms.yaml`, `validation/hw/wgfmu.fast_bti.yaml`.
