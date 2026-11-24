---
id: wgfmu-pulsed-iv
title: WGFMU pulsed and fast I-V — Id at each pulse plateau, microsecond ramps, pulse trains, pulsed vs DC
family: wgfmu
intent: [WGFMU, pulsed Id-Vg, fast IV, fast I-V, ultra-fast IV, pulse train, short pulses, self-heating, isothermal, pulsed vs DC, fast hysteresis, RSU]
recipes: [wgfmu.pulsed_iv, wgfmu.fast_iv, wgfmu.pulse_train]
device_types: [nmos, pmos, igzo_tft, fefet]
modules: [WGFMU, MPSMU, HRSMU, GNDU]
routes: [rsu:wgfmu]
bringup_stage: L8
status: sim_validated
confirmation: always
knowledge: [knowledge/10-wgfmu-fast-iv-noise.md#fast-i-v-pulses-ramps-and-timing, knowledge/11-switching-routing.md#rsu-of-the-wgfmu, knowledge/06b-analysis-time-pulse.md#pulse-plateau, knowledge/06b-analysis-time-pulse.md#pulsed-versus-dc, knowledge/06-analysis-extraction.md#maximum-transconductance]
manual: [WG p63 (3-23) "Id-Vg", WG p125 (4-55) "setMeasureEvent", WG p126 (4-56) "average", WG p80 (4-10) "addSequence", WG p142 (4-72) "6003", WG p16 (1-4) "full scale"]
debug: [wgfmu-range-overflow, wgfmu-library-error, wgfmu-memory-budget, cleanup-failed-fault]
sources: [blueprint v2 2.7 wgfmu_waveform, blueprint v2 2.7.1 builders pulsed_iv fast_iv_ramp pulse_train, blueprint v2 3.4, WG Ex. 1-3 and 9, 1 us flash I-V application note]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# WGFMU pulsed and fast I-V

## 1. Purpose and applicable devices

Measure a transistor faster than it heats or its slow traps respond, with the WGFMU on gate and drain through their
RSUs (Fast IV mode, current measured on the drain):

- `wgfmu.pulsed_iv`: one gate pulse per level (vg_start..vg_stop), drain held at `vd`, Id averaged on each flat top:
  the isothermal / trap-free transfer curve. Compare with a DC Id-Vg at the same `vd` (`pulsed_vs_dc`).
- `wgfmu.fast_iv`: the gate ramps up and down in microseconds; Id sampled on both ramps (segments fwd/rev): fast
  hysteresis and a quick Id-Vg.
- `wgfmu.pulse_train`: `count` identical pulses with `samples` points on every plateau: drift of Id over a train.
- Not for: SMU pulses of 0.5 ms and longer (card `smu-pulsed-iv`); RTN or 1/f noise (card `wgfmu-rtn-noise`);
  arbitrary lab waveforms or WGFMU DC checks (card `wgfmu-custom-waveform`); PUND (card `fecap-pund`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (wgfmu) | WGFMU 201 via `RSU201.OUT` | pulsed / ramped; no measurement (programmed level in the table) |
| drain | `drain` (wgfmu) | WGFMU 202 via `RSU202.OUT` | bias `vd`, current on `irange` |
| source | `source` (ground) | GNDU | |
| bulk | `bulk` (bias_v, optional; pulsed_iv only) | SMU5 (MPSMU) | body bias held around the waveform |

- Example pin maps `mosfet-wgfmu` (gate RSU201.OUT, drain RSU202.OUT, source GNDU) and `mosfet-wgfmu-body` (+ bulk
  SMU5). The RSUs must sit at the probe tips (short cables): the WGFMU's speed is lost on long triax runs.
- Routes per phase: `waveform: RSU201.OUT -> wgfmu, RSU202.OUT -> wgfmu` while the sequencer runs (the library's
  connect, guarded); `rest`: both RSUs back on their normal path; cleanup: abort, initialize, disconnect, verified.

## 3. Pre-run checklist

- `station_status` clean: no fault, no active run, WGFMU library loadable (visa), RSUs at rest.
- DUT profile with a `pulse` envelope on the gate (`nmos-wgfmu`); the drain range covers the largest expected Id.
- A DC reference first (`mosfet.idvg` at the same `vd`) if the question is "pulsed vs DC".

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `builder` (wgfmu.pulsed_iv) | pulsed_iv | pulsed_iv | pulsed_iv | fixed builder | one pulse per level |
| `builder` (wgfmu.fast_iv) | fast_iv_ramp | fast_iv_ramp | fast_iv_ramp | fixed builder | up/down ramps |
| `builder` (wgfmu.pulse_train) | pulse_train | pulse_train | pulse_train | fixed builder | repeated pulse |
| `vg_base` | 0 V | -1..0 V | -5..5 V | gate between pulses | off state |
| `vg_start` | 0 V | -1..0.5 V | -5..5 V | first pulse level / ramp start | sweep start |
| `vg_stop` | 2 V | 1..3 V | -5..5 V | last pulse level / ramp top | sweep end |
| `vg_points` | 21 | 11..101 | 1..500 | pulses | 4 vectors per pulse |
| `vg_peak` | 2 V | 1..3 V | -5..5 V | pulse level | on state |
| `vd` | 1 V | 0.05..2 V | -5..5 V | drain bias | linear or saturation |
| `irange` | 1ma | - | 1ua, 10ua, 100ua, 1ma, 10ma | drain range | over-range reads V |
| `width` | 10 us | 1..100 us | 100 ns..10 ms | flat top | shorter = colder |
| `period` (wgfmu.pulsed_iv) | 1 ms | 0.1..10 ms | 1 us..1 s | repetition | duty = width / period |
| `period` (wgfmu.pulse_train) | 100 us | 10 us..10 ms | 1 us..1 s | repetition | duty = width / period |
| `edge` | 100 ns | 10 ns..1 us | 10 ns..100 us | rise and fall | slower = less ringing |
| `settle` | 1 us | 100 ns..10 us | 0..1 ms | edge to window (fast_iv: hold) | window = width - 2 settle |
| `vb` | 0 V | - | -2..2 V | body bias (bulk role) | Vth shift |
| `icomp_bulk` | 100 uA | - | 1 pA..1 mA | bulk SMU compliance | - |
| `ramp` | 10 us | 1 us..1 ms | 20 ns..1 s | one ramp | faster = less trapping |
| `interval` | 100 ns | 10 ns..10 us | 10 ns..20 ms | sample spacing | points per ramp = ramp / interval |
| `double` | true | - | - | ramp back down | segment rev |
| `cycles` | 1 | 1..10 | 1..1000 | up/down pairs | - |
| `count` | 100 | 1..10000 | 1..1000000 | pulses | soft band 10,000 |
| `samples` | 10 | 1..100 | 1..2000 | points per plateau | contiguous averages |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: wgfmu.pulsed_iv
params: {}
pin_map: mosfet-wgfmu
dut_profile: nmos-wgfmu
sim_scenario: nmos_wgfmu
```

## 5. Limits and confirmation

- No compliance: every level of every vector is checked against the channel envelope before the library sees it
  (vectors, 10 ns grid, output time, stored values); a short draws up to the range's full scale (10 mA range).
- Blocked: a gate pulse role on a terminal without a `pulse` envelope (R-PULSE-02), > 2,048 vectors (> 500 levels),
  levels outside the force range, an event outside its pattern (R-WG-02), a WGFMU role not on an RSU (R-WG-01).
- Confirm: `unverified_topology` (the example RSUs are unverified), `dut_envelope`, `soft_pulse` (above 5 V, 10,000
  pulses, 60 s at the pulse level, duty 0.5); on hardware `first_hw_run`. Runs are short (sync).

## 6. Quality criteria

- Status `V` = a reading at its range's full scale (saturated, no compliance): raise `irange` one step; never trust
  `V` points. `N` everywhere expected.
- The averaging window must lie on the flat top: `settle` >= the edge plus the ringing seen in a time-resolved
  `wgfmu.pulse_train` with many `samples`.
- Noise falls as 1/sqrt(window / 5 ns): a 10 us window averages 2,000 samples.

## 7. Analysis method

- `wgfmu.pulsed_iv`: defaults `pulse_plateau` (x gate_V, y drain_I: Id of the strongest pulse) and `gm_max`;
  `pulsed_vs_dc` with `reference_run` = the DC `mosfet.idvg` run at the same `vd` (drain_V must agree).
- `wgfmu.fast_iv`: default `gm_max` (segment fwd); `memory_window`-style up/down comparison by hand from the table.
- `wgfmu.pulse_train`: `pulse_plateau` per pulse (`pulse` = n, 0-based; the `cycle` column is the pulse number).
- Report: measured Id points vs derived values (method, window), status counts, SIMULATED flag.

## 8. Expected result shape

| item | expected | red flags |
|---|---|---|
| pulsed vs DC at low duty, no heating | ratio about 1 (within a few %) | pulsed far below DC: window on an edge or range overflow |
| self-heating device | pulsed > DC at high Id x Vd | pulsed > DC at negligible power: traps, or a different landing |
| fast_iv up vs down | overlap without trapping | large loop: trapping (oxide TFT, FeFET) or a ramp too fast for the cables |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| status V points, flat-topped Id | drain range too small | `irange` vs Id; quality report | `wgfmu-range-overflow` |
| library or session error, 30xx code | DLL, session, RSU, setup error | `station_status` WGFMU line, audit | `wgfmu-library-error` |
| plan blocked on points / memory | too many stored values (~4 M per channel) | summary pts, `samples`, `count` | `wgfmu-memory-budget` |
| no current at all, 3001 | RSU not on the WGFMU path, probe not landed | audit RSU states, contact check | `wgfmu-library-error` |
| fault latched after a run | a channel could not be disconnected | keep the fault; human checks | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | nmos_wgfmu | nmos-wgfmu | S20261124T052440Z-ebc3 | needs_confirmation (unverified_topology); 21 pulses 0..2 V, 10 us at 1 % duty, 21 N; Id(2 V) = model 2.04e-4 A; vs DC mosfet.idvg S20261124T052440Z-5a5f: pulsed/DC 1.0007, max rel. difference 0.26 % | - |
| hw | pending (bring-up stage L8) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware records: `validation/hw/wgfmu.pulsed_iv.yaml`, `validation/hw/wgfmu.fast_iv.yaml`,
`validation/hw/wgfmu.pulse_train.yaml` (reviewed by a human after stage L8; drafts only from hardware `H...` runs).
Until then every hardware plan needs `first_hw_run` confirmation.
