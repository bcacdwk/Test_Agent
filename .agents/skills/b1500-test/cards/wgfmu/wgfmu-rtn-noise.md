---
id: wgfmu-rtn-noise
title: WGFMU random telegraph noise and low-frequency noise — constant bias, long fast sampling, tau_c/tau_e, 1/f^gamma PSD
family: wgfmu
intent: [RTN, random telegraph noise, trap, capture time, emission time, LFN, low-frequency noise, 1/f noise, flicker noise, PSD, noise spectrum, WGFMU]
recipes: [wgfmu.rtn, wgfmu.lfn]
device_types: [nmos, pmos, igzo_tft]
modules: [WGFMU, GNDU]
routes: [rsu:wgfmu]
bringup_stage: L8
status: sim_validated
confirmation: always
knowledge: [knowledge/10-wgfmu-fast-iv-noise.md#random-telegraph-noise-physics, knowledge/10-wgfmu-fast-iv-noise.md#low-frequency-noise-physics, knowledge/10-wgfmu-fast-iv-noise.md#choosing-range-sampling-and-record-length, knowledge/10-wgfmu-fast-iv-noise.md#rtn-analysis-rtn_levels, knowledge/10-wgfmu-fast-iv-noise.md#psd-analysis-psd_welch-and-plot_psd, knowledge/11-switching-routing.md#rsu-of-the-wgfmu]
manual: [WG p125 (4-55) "setMeasureEvent", WG p126 (4-56) "average", WG p142 (4-72) "6003", WG p16 (1-4) "full scale", AN-RTN p3 (3) "RTN", AN-RTN p5 (5) "400", AN-RTN p7 (7) "2.4 MHz", AN-RTN p8 (8) "RTN"]
debug: [wgfmu-range-overflow, wgfmu-memory-budget, noisy-data, wgfmu-library-error, wgfmu-rsu-route, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 2.7.1 builder dc_sample, blueprint v2 2.10 noise.py, blueprint v2 3.4, blueprint v2 4.2 noise targets, Keysight application note 5990-3705 RTN, lwp/1530 LFN_noise_meas.cpp]
version: 1
---

# WGFMU random telegraph and low-frequency noise

## 1. Purpose and applicable devices

Hold a transistor at a constant gate and drain bias and sample the drain current fast and long with the WGFMU
(Fast IV, through the RSUs), then extract the noise:

- `wgfmu.rtn`: random telegraph noise of a single trap: `tau_c` (mean time to capture, dwell at the higher |Id|),
  `tau_e` (mean time to emission, dwell at the lower |Id|), `dI` and `dI/I` (`rtn_levels`), plus `it_statistics`.
  Default 400,000 points at 10 us (4 s).
- `wgfmu.lfn`: low-frequency noise in the lab's layout (`lwp/1530/LFN_noise_meas.cpp`: channel 1 = gate measures its
  voltage, channel 2 = drain measures its current on 100 uA, 5 V range, 504,000 points at 100 ns): Welch PSD
  `S_I(f)`, `S_I/I^2`, `gamma` of 1/f^gamma, RTN corner (`psd_welch`), plot `plot_psd`.
- Not for: waveforms that change the bias during the record (card `wgfmu-custom-waveform`); pulsed I-V (card
  `wgfmu-pulsed-iv`); slow drift over minutes or hours with SMUs (card `smu-sampling`; the noise methods also read
  `generic.smu_sampling` runs).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (wgfmu) | WGFMU 201 via `RSU201.OUT` | holds `vg`; lfn: voltage measured (lab ch1) |
| drain | `drain` (wgfmu) | WGFMU 202 via `RSU202.OUT` | holds `vd`; current on `irange` (lab ch2) |
| source | `source` (ground) | GNDU | bulk on the common as well (AN-RTN p4 (4)) |

- Example pin map `mosfet-wgfmu` (gate RSU201.OUT, drain RSU202.OUT, source GNDU); RSUs at the probe tips, current
  loop short (cables bundled, source and bulk to the shields; AN-RTN p6 (6)).
- Routes per phase: `waveform: RSU201.OUT -> wgfmu, RSU202.OUT -> wgfmu` for the record; `rest`: both RSUs back on
  their normal path; cleanup: abort, initialize, disconnect, verified.

## 3. Pre-run checklist

- `station_status` clean: no fault, no active run, WGFMU library loadable (visa), RSUs at rest; shield box closed,
  probe station vibration isolated (noise records pick up everything; AN-RTN p6 (6)).
- Expected Id at the bias (a DC Id-Vg first): choose `irange` just above it; keep vg/vd inside the DUT profile.
- Know roughly the time scale: interval <= the shortest dwell / 10, record >= 100 x (tau_c + tau_e) (rules of thumb).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `builder` | dc_sample | dc_sample | dc_sample | fixed builder | constant bias, one long event |
| `vg` | 1 V | - | -5..5 V | gate bias (example default: set it per device) | RTN taus and levels move with it |
| `vd` | 0.1 V | 0.05..0.5 V | -5..5 V | drain bias (method convention: linear region) | linear region, little stress |
| `irange` | 100ua | - | 1ua, 10ua, 100ua, 1ma, 10ma | drain range | floor and bandwidth scale with it |
| `vrange` | 5v | - | 3v, 5v, -10v, 10v | force range (lab: 5 V) | must hold vg and vd |
| `points` (wgfmu.rtn) | 400000 | 100000..4000000 | 1000..4000000 | record length | transitions, memory |
| `points` (wgfmu.lfn) | 504000 | 100000..4000000 | 1000..4000000 | record length (lab 504,000) | lowest frequency |
| `interval` (wgfmu.rtn) | 10 us | 100 ns..1 ms | 10 ns..1 s | sampling | <= tau_min / 10 |
| `interval` (wgfmu.lfn) | 100 ns | 100 ns..100 us | 10 ns..1 s | sampling (lab 100 ns) | fit up to 1/(10 interval) |
| `average` (wgfmu.rtn) | 10 us | 100 ns..1 ms | 0..20 ms | averaging per point | = interval: anti-alias |
| `average` (wgfmu.lfn) | 100 ns | 100 ns..100 us | 0..20 ms | averaging per point (lab 100 ns) | = interval: anti-alias |
| `edge` | 1 us | 100 ns..10 us | 10 ns..1 ms | ramp to the bias | no gate overshoot |
| `settle` (wgfmu.rtn) | 10 ms | 1 ms..1 s | 0..10 s | hold before the record | traps in equilibrium |
| `settle` (wgfmu.lfn) | 1 ms | 1 ms..1 s | 0..10 s | hold before the record | transients gone |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: wgfmu.rtn
params: {}
pin_map: mosfet-wgfmu
dut_profile: nmos-wgfmu
sim_scenario: nmos_rtn
```

## 5. Limits and confirmation

- No compliance: the levels are checked against the channel envelopes before the library sees them; a short draws up
  to the range's full scale. No pulse envelope is needed (no pulses: a constant bias).
- Blocked: more than about 4,000,000 points per channel (typical memory, WG5 p25 (1-15)) or the policy's WGFMU
  points, `average` > `interval`, an interval above 1.34 s, levels outside `vrange` (R-WG-02); a WGFMU role not on an
  RSU (R-WG-01); levels outside the DUT profile (R-DUT-01).
- Confirm: `unverified_topology` (the example RSUs are unverified); on hardware `first_hw_run`; records longer than
  `long_run_confirm_s` need `long_run`, above `max_sync_run_s` they run asynchronously (poll `get_run`).

## 6. Quality criteria

- Status `V` = saturated at full scale: never trusted; analyses refuse. Raise `irange` one step.
- RTN resolved (analysis thresholds): `separation` >= 5 (below 3: refused), >= 200 transitions, each tau >= 10
  sampling intervals, dwell `cv` about 1 (one trap); otherwise read the warnings and change interval, record or bias.
- PSD: the floor of the range lies below the 1/f part; `rms_log` < 0.3; `gamma` not at 0.2 or 2.5.

## 7. Analysis method

- `wgfmu.rtn`: defaults `rtn_levels` (tau_c, tau_e, dI, dI/I) and `it_statistics`; `psd_welch` and `plot_psd` work on
  the same run (the RTN corner then appears as `corner_frequency`, 1/(2 pi fc) = 1/(1/tau_c + 1/tau_e)).
- `wgfmu.lfn`: defaults `psd_welch` (gamma, `flicker_norm_1hz`, PSD at `f_ref`, model auto) and `it_statistics`;
  `plot_psd` for the figure; `gm_s` gives the input-referred `S_Vg = S_I/gm^2`; `y=gate_V` analyses channel 1.
- Options: `t_min`/`t_max`, `segments`, `f_min`/`f_max`, `model`, `hysteresis`, `baseline_s`, `smooth`.
- Report: measured record (points, interval, range, status counts) vs derived values (method, window, model),
  SIMULATED flag.

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| item | expected (source) | red flags |
|---|---|---|
| `it_statistics` of an RTN record | bimodality > 5/9 (bimodality-coefficient convention); noise_rel device-dependent, no typical value | std at the range floor: no device signal |
| `rtn_levels` | two levels, cv ~1, taus >> dt | levels < 3 sigma apart: failed; cv << 1: several traps |
| `psd_welch` | gamma near 1 (a range needs a checked source: [10](../../knowledge/10-wgfmu-fast-iv-noise.md#low-frequency-noise-physics)); Lorentzian bump if RTN | gamma ~2: one Lorentzian fitted as a power law |
| corner from `psd_welch` | 1/(2 pi fc) = 1/(1/tau_c + 1/tau_e) of `rtn_levels` | mismatch: several traps or a missed fast dwell |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| `V` points, clipped record | range below Id | `irange` vs Id; quality report | `wgfmu-range-overflow` |
| plan blocked on points | record above ~4 M values per channel (WG5 p25 (1-15)) | summary pts; `points`, `interval` | `wgfmu-memory-budget` |
| no two levels / PSD at the floor | no RTN at this bias, probe open, range too big | `it_statistics`; contact check | `noisy-data` |
| spikes at 50 Hz and harmonics | line pickup, ground loop | shield, cable bundling (AN-RTN p6 (6)) | `noisy-data` |
| library error, 30xx code | DLL, session, RSU | `station_status` WGFMU line, audit | `wgfmu-library-error` |
| record at the open-circuit floor, 3001 | RSU not on the WGFMU path, cabling | audit RSU states | `wgfmu-rsu-route` |
| fault latched after a run | a channel could not be disconnected | keep the fault; human checks | `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | nmos_rtn | nmos-wgfmu | S20261124T100201Z-b6ad | needs_confirmation (unverified_topology); 400,000 N; tau_c 1.06 ms, tau_e 0.51 ms (truth 1, 0.5 ms), dI/I 4.95 % (5 %), 5,108 transitions | - |
| sim | 2026-11-24 | nmos_rtn | nmos-wgfmu | S20261124T100204Z-12a6 | wgfmu.lfn: 504,000 x 2 N (ch1 V, ch2 I); gamma 1.03 +- 0.03 (truth 1), model power_lorentzian, fc 360 Hz (477 Hz) | - |
| hw | pending (bring-up stage L8) | - | - | - | - | - |

Sim rows: the example plans run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`
(`tests/integration/test_recipes_noise.py`); the run folders were not kept. Hardware records:
`validation/hw/wgfmu.rtn.yaml`, `validation/hw/wgfmu.lfn.yaml` (reviewed by a human after stage L8; drafts only from
hardware `H...` runs). Until then every hardware plan needs `first_hw_run` confirmation.
