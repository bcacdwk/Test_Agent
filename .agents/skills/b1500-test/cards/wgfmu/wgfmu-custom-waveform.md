---
id: wgfmu-custom-waveform
title: WGFMU custom waveform from CSV files and WGFMU DC spot — lab waveforms, long fast sampling, DC check via the RSU
family: wgfmu
intent: [WGFMU, custom waveform, arbitrary waveform, CSV waveform, waveform file, lab waveform, lwp, fast sampling, WGFMU DC, DC spot, RSU check, known resistor]
recipes: [wgfmu.custom_waveform, wgfmu.dc_spot]
device_types: [nmos, pmos, igzo_tft, fefet]
modules: [WGFMU, GNDU]
routes: [rsu:wgfmu]
bringup_stage: L8
status: sim_validated
confirmation: always
knowledge: [knowledge/10-wgfmu-fast-iv-noise.md#wgfmu-and-rsu-in-one-page, knowledge/11-switching-routing.md#rsu-of-the-wgfmu, knowledge/06-analysis-extraction.md#resistance-fit, knowledge/06b-analysis-time-pulse.md#pulse-plateau]
manual: [WG p125 (4-55) "setMeasureEvent", WG p128 (4-58) "setRangeEvent", WG p142 (4-72) "6001", WG p89 (4-19) "dcforceVoltage", WG p90 (4-20) "dcmeasureValue", WG p70 (3-30) "DC"]
debug: [wgfmu-memory-budget, wgfmu-range-overflow, wgfmu-library-error, cleanup-failed-fault]
sources: [blueprint v2 decision 21, blueprint v2 2.7.1 builders table and dc_spot, blueprint v2 2.10 npz data contract, blueprint v2 3.4, blueprint v2 4.4 lab sample, lwp/1530 LFN_noise_meas.cpp]
version: 1
---

# WGFMU custom waveform and DC spot

## 1. Purpose and applicable devices

- `wgfmu.custom_waveform`: run the lab's own WGFMU waveforms (lwp/1530 layout) on a transistor: one CSV per channel
  (gate, drain) and one events CSV; the gate's voltage and the drain's current are sampled as the events say, up to
  ~4 M values per channel (lwp: 504,000 points at 100 ns over 50.4 ms). Files come from the committed library
  `recipes/waveforms/` or from `work/waveforms/` (ad hoc, always confirmed: `adhoc_recipe`).
- `wgfmu.dc_spot`: WGFMU DC mode (no sequencer): terminal `a` steps through levels and measures its current; the
  known-resistor check through the RSU at bring-up L8 (I(R) +-3 %).
- Not for: pulsed Id-Vg or fast ramps (card `wgfmu-pulsed-iv`, no files needed); noise statistics of long constant
  bias runs (card `wgfmu-rtn-noise`); SMU DC checks (card `smu-spot-kelvin`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (wgfmu, custom_waveform) | WGFMU 201 via `RSU201.OUT` | waveform `gate_wave`; voltage measured (lab ch1) |
| drain | `drain` (wgfmu, custom_waveform) | WGFMU 202 via `RSU202.OUT` | waveform `drain_wave`; current measured (lab ch2) |
| source | `source` (ground) | GNDU | |
| a | `a` (wgfmu, dc_spot) | WGFMU 201 via `RSU201.OUT` | DC levels, current measured |
| b | `b` (ground, dc_spot) | GNDU | return |
| c | `c` (wgfmu, optional, dc_spot) | WGFMU 202 via `RSU202.OUT` | constant level, current measured |

- Example pin maps `mosfet-wgfmu` (custom waveform) and `resistor-wgfmu` (DC spot: a RSU201.OUT, b GNDU).
- Routes per phase: `waveform: RSU201.OUT -> wgfmu (and RSU202.OUT)` while the program runs; `rest`: back to the
  normal path; cleanup: abort, initialize, disconnect every channel, session closed, verified.

## 3. Pre-run checklist

- `station_status` clean; WGFMU library loadable on visa; RSUs at rest.
- Look at the files before validating: `time,level` rows (first time 0, strictly increasing, 10 ns grid, at most
  2,048 rows per waveform); events `t,points,interval,average,range1,range2` (range codes 1..5 = 1 uA..10 mA).
- Every waveform level within the DUT profile (`nmos-wgfmu`: gate +-5 V, drain +-3 V); the lab sample swings the gate
  to +-4 V.
- A file under `work/waveforms/` makes the plan `adhoc_recipe`: show the human the summary (levels, points, files).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `builder` (wgfmu.custom_waveform) | table | table | table | fixed builder | lab CSV layout |
| `builder` (wgfmu.dc_spot) | dc_spot | dc_spot | dc_spot | fixed builder | DC mode |
| `gate_wave` | recipes/waveforms/lwp_sample.csv | - | - | gate waveform (ch1) | 200 lab rows, 5.52 ms |
| `drain_wave` | recipes/waveforms/lwp_sample_drain.csv | - | - | drain waveform (ch2) | 0.1 V bias |
| `events` | recipes/waveforms/lwp_sample_events.csv | - | - | measurement rows | 55,200 points at 100 ns |
| `irange` (wgfmu.custom_waveform) | 100ua | - | 1ua, 10ua, 100ua, 1ma, 10ma | initial drain range | a time-0 code in `events` wins |
| `irange` (wgfmu.dc_spot) | 10ua | - | 1ua, 10ua, 100ua, 1ma, 10ma | DC current range | 1 uA reads at 10 % of 10 uA |
| `a_levels` | [-0.1, -0.05, 0, 0.05, 0.1] V | - | -10..10 V | DC steps of a | resistance line |
| `c_v` | 0 V | - | -10..10 V | constant level of c | - |
| `samples` | 1 | 1..10 | 1..100 | readings per level | each a row; keep 1 for the default `resistance` fit |
| `settle` | 1 ms | 0.1..10 ms | 0..1 s | wait after each step | settling |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: wgfmu.custom_waveform
params: {}
pin_map: mosfet-wgfmu
dut_profile: nmos-wgfmu
sim_scenario: nmos_rtn
```

## 5. Limits and confirmation

- The file content is part of the plan (sha256 in `files`); a file changed after validation makes the run
  `plan_stale`. The guard checks every vector of every pattern before the library sees it.
- Blocked: > 2,048 vectors per waveform, times off the 10 ns grid, a level outside the force range or the DUT
  envelope, an event ending after its waveform, a range event inside an averaging window or on a voltage channel,
  more stored values than ~4 M per channel or `run_limits.max_points.wgfmu` (R-WG-02); unreadable files (R-PARAM-01).
- Confirm: `adhoc_recipe` (any `work/waveforms/` file), `unverified_topology`, `dut_envelope`; on hardware
  `first_hw_run`. A 50 ms waveform with 504,000 points runs synchronously.

## 6. Quality criteria

- Status `V`: a reading at its range's full scale; `N` expected. Tables above 200,000 rows are `data.npz` with a
  2,000-row `preview.csv`; `get_run` shows at most 200 rows (downsampled); the raw readback is
  `raw/wgfmu-<ch>-000.npz` and the program `program.json`.
- `t_s` is the library's time stamp (centre of each averaging window); the event timing is exact on the 10 ns grid.

## 7. Analysis method

- `wgfmu.custom_waveform`: no default (any shape); `plot_timeseries` for a look, `pulse_plateau` with `x`/`y` for
  pulsed sections, ad-hoc analysis in `work/<run_id>/` importing `b1500_test_agent.analysis` (`load_run` reads npz).
- `wgfmu.dc_spot`: default `resistance` (a_V vs a_I: R, linearity, offset; open/short classification).

## 8. Expected result shape

| item | expected | red flags |
|---|---|---|
| custom waveform | gate_V follows the file; drain_I follows the device | gate_V flat at 0: RSU not connected |
| dc_spot on 100 kOhm | R within 3 %, offset near 0 | open (R > 1 GOhm): RSU or probe; V points: range too small |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| blocked on points or memory, error 3050 | too many stored values | events rows, points per channel | `wgfmu-memory-budget` |
| status V, clipped drain current | range too small for the current | `irange`, events range codes | `wgfmu-range-overflow` |
| library or session error, 33xx setup code | file content the library refuses | the plan's R-WG-02 findings, audit | `wgfmu-library-error` |
| fault latched after a run | a channel could not be disconnected | keep the fault; human checks | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | nmos_rtn | nmos-wgfmu | S20261124T052440Z-bb4e | needs_confirmation (unverified_topology); lab sample 5.52 ms, 55,200 points per channel at 100 ns, 110,400 N, timing exact on the 10 ns grid | - |
| hw | pending (bring-up stage L8) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware records: `validation/hw/wgfmu.custom_waveform.yaml`, `validation/hw/wgfmu.dc_spot.yaml`
(reviewed by a human after stage L8; drafts only from hardware `H...` runs). Until then every hardware plan needs
`first_hw_run` confirmation.
