---
id: spgu-pulse-train
title: HV-SPGU pulse train and ALWG waveform on a gate — bounded output, SER load, selector to PGU and back
family: spgu
intent: [SPGU pulse, pulse train, gate pulses, program pulse, erase pulse, ALWG, arbitrary waveform, SER, load impedance, 3-level pulse]
recipes: [spgu.pulse_train, spgu.alwg_sequence]
device_types: [fefet, nmos, pmos, fecap, capacitor]
modules: [HVSPGU]
routes: [selector_16440a:pgu]
bringup_stage: L7
status: sim_validated
confirmation: conditional
knowledge: [knowledge/09-pulse-spgu-selector.md#hv-spgu-output-and-the-ser-load, knowledge/09-pulse-spgu-selector.md#pg-pulse-trains, knowledge/09-pulse-spgu-selector.md#alwg-waveforms, knowledge/09-pulse-spgu-selector.md#running-a-train, knowledge/09-pulse-spgu-selector.md#guard-and-rules, knowledge/11-switching-routing.md#the-16440a-selector]
manual: [PG p507 (4-189) "SER", PG p512 (4-194) "SPRM", PG p142 (2-54) "SPST", PG p146 (2-58) "3-level", PG p149 (2-61) "ALWG", PG p433 (4-115) "ERSSP"]
debug: [spgu-pulse-no-effect, spgu-load-mismatch, spgu-selector-state, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 2.7 spgu_pulse, blueprint v2 2.8 R-PULSE-01..03 and R-SPGU-01, blueprint v2 3.3, lwp SPGU_pulse.m and test_SPGU.m]
version: 1
---

# HV-SPGU pulse train and ALWG waveform

## 1. Purpose and applicable devices

Put a bounded train of voltage pulses (or one arbitrary linear waveform, ALWG) on one gate from the HV-SPGU: FeFET
program/erase pulses, gate stress pulses, pulse checks into a known load at bring-up L7. No data are measured; the
run reports the outputs, pulses and output time, and every route and stop is read back.

- `spgu.pulse_train`: two-level (or three-level) pulses, period, `count` or `duration`. `spgu.alwg_sequence`: one
  pattern of linear ramps (`levels`, `times`), `repeat` per sequence, sequences `count`.
- Not for: reading the device after the pulses (card `fefet-pulse-write-read`, WP9.4); charge pumping (card
  `charge-pumping`); DC stress (card `bti-stress-measure`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (pgu) | HV-SPGU channel 101, usually via `SEL1.OUT1` (16440A, PGU input) | 50 Ohm source (UG p76 (2-36)), no compliance |

- Example pin map `fefet-sel` (gate `SEL1.OUT1`; only `gate` is used); a pin map naming `gate: 101` sets no route.
- Routes per phase: `pulse: SEL1.OUT1 -> pgu` before `CN`; `rest: SEL1.OUT1 -> open` after the train; cleanup:
  every declared selector output to rest, verified.
- Selector inputs must be recorded in `config/local/station.yaml` (L7); on the simulator the scenario's cabling
  stands in for a `null` input.

## 3. Pre-run checklist

- `station_status` clean: no fault, no active run, every selector output at rest, no SPGU output running.
- DUT profile with a `pulse` envelope and the right `impedance` on the pulsed terminal (a gate is `high_z`).
- `load_ohm` 1 MOhm for a gate or capacitor (`SER`, PG p507 (4-189); lab script `lwp/matlab_B1500/test_SPGU.m`: 1
  MOhm); 50 Ohm only into a real 50 Ohm load.
- The human confirms amplitude and width against the film (coercive field, breakdown) before the first train: the
  defaults (0 -> 4 V, 1 us, 20 ns edges) are examples, not program/erase values for your film (owner question:
  [04](../../knowledge/04-ferroelectric-oxide.md#pulse-write-read-endurance-and-retention); the lab script ran
  +-3 V, 2 us, 100 ns edges: what the lab ran, not a recommendation).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `mode` (spgu.pulse_train) | pg | pg | pg | fixed kind mode | PG pulses |
| `mode` (spgu.alwg_sequence) | alwg | alwg | alwg | fixed kind mode | ALWG waveform |
| `v_base` | 0 V | - | -40..40 V | level between pulses (example) | set level; SER-adjusted |
| `v_peak` | 4 V | - | -40..40 V | pulse level (example default: set it per device with the owner); module +-40 V open load, +-20 V into 50 Ohm (UG p76 (2-36)) | pad sees it at SER = load |
| `width` | 1 us | - | 10 ns..10 s | time at the peak (example) | >= t_edge / 0.8 (error 2111, PG p591 (5-19)) |
| `delay` | 0 s | - | 0..10 s | position in the period | - |
| `t_edge` | 20 ns | 20 ns..1 us | 8 ns..0.4 s | rise and fall (module 8 ns..400 ms, UG p76 (2-36)) | period >= delay + width + t_edge / 0.8 (error 2112, PG p592 (5-20)) |
| `period` | 100 us | 1 us..1 s | 20 ns..10 s | repetition (module 20 ns..10 s, UG p76 (2-36)) | 10 ns grid |
| `bound` | count | count, duration | count, duration | what ends the output | never free run |
| `count` (spgu.pulse_train) | 1000 | 1..10000 | 1..1000000 | pulses | soft band 10,000 per run |
| `count` (spgu.alwg_sequence) | 100 | 1..10000 | 1..1000000 | sequences | each sequence = the pattern x repeat |
| `duration` (spgu.pulse_train) | 0.1 s | 1 ms..10 s | 1 us..3600 s | output time | alternative bound |
| `duration` (spgu.alwg_sequence) | 10 ms | - | 1 us..3600 s | output time | alternative bound |
| `load_ohm` | 1 MOhm | 1 kOhm..1 MOhm | 0.1 Ohm..1 MOhm | declared load SER | 50 Ohm doubles the level on an open load (50 Ohm source, AN-TUT p149 (5-3)) |
| `three_level` | false | - | - | add source 2 | output = source 1 + source 2 |
| `v_base2` | 0 V | - | -40..40 V | source 2 base | three-level only |
| `v_peak2` | -4 V | - | -40..40 V | source 2 peak | three-level only |
| `width2` | 1 us | - | 10 ns..10 s | source 2 width | three-level only |
| `delay2` | 2 us | - | 0..10 s | source 2 delay | three-level only |
| `v_initial` | 0 V | - | -40..40 V | ALWG start and idle level | base of the waveform |
| `levels` | 4, 4, 0, 0, -4, -4, 0, 0 V | - | -40..40 V | ALWG vector levels | each vector ramps to its level |
| `times` | 100 ns, 1 us, 100 ns, 10 us, 100 ns, 1 us, 100 ns, 10 us | - | 10 ns..671.08863 ms | ALWG vector times | 10 ns grid |
| `repeat` | 1 | 1..1000 | 1..1048576 | pattern repeats per sequence | - |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: spgu.pulse_train
params: {}
pin_map: fefet-sel
dut_profile: fefet-lab
sim_scenario: fefet_lab
```

## 5. Limits and confirmation

- No compliance: the guard checks the open-load level `|V| (SER + 50) / SER`, width, duty, pulses and on-time per
  start against the pulse envelope at every setup and start; outputs are always bounded (count or duration).
- Blocked: a `high_z` terminal with `load_ohm` below 1 kOhm (50 Ohm on a gate doubles the level), an open-load level
  above 40 V, the hard limit or the DUT's pulse `max_abs_v`, timing outside the module (R-PULSE-01), a terminal
  without a `pulse` envelope (R-PULSE-02), a short-circuit current above the hard limit on a non-`high_z` terminal.
- A blocked request: name its rule ids, then `validate_plan` an in-envelope alternative (e.g. the asked width at
  <= 4 V, <= 10,000 pulses, `load_ohm` 1 MOhm) and show that plan's summary; it runs only after the human's consent.
- Confirm: `dut_envelope` (outside the DUT pulse envelope), `soft_pulse` (above 5 V at the pad, 10,000 pulses, 60 s
  at the pulse level or duty 0.5), `unverified_topology` / `unverified_pin_map`; on hardware `first_hw_run`.
- The summary shows the pulse, `SER` and the accepted short-circuit residual of a `high_z` gate, e.g.
  `gate=SPGU1:101 via SEL1.OUT1 pulse 0->4 V 1 us x1000 @10 kHz SER 1 MOhm Isc<=0.08 A residual`.

## 6. Quality criteria

- `kind_result`: `outputs`, `pulses_planned`, `output_s_planned`, `waited_s` (SPST? polling, within one poll of the
  planned time), `spp_fallbacks` 0; cleanup verified with every selector output at rest.
- `spp_fallbacks` > 0: `SPST?` did not fall at the end (ATV-19) and `SPP` stopped it: report it, check the train
  length on a scope at L7 before trusting the count.

## 7. Analysis method

- No `analyze_run` method (no data table). Report `kind_result`, the routes checkpoints of the audit (`pulse`,
  `rest` with read-backs), the cleanup and the SIMULATED flag. The device effect is measured by a read (separate
  recipe or `fefet.pulse_write_read`).

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| item | expected (source) | red flags |
|---|---|---|
| waited_s | about the planned output time (+ one poll) | much shorter (stopped early) or a fallback |
| routes | `SEL1.OUT1 pgu` then `open`, read back | `RouteNotVerified`, a port not at rest |
| device after the train (separate read) | the intended change | none: runbook `spgu-pulse-no-effect` |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| pulses did nothing | selector not on PGU, wrong port, too small/short | audit routes; `station_status` | `spgu-pulse-no-effect` |
| device changed more than expected | SER 50 Ohm on an open load, wrong load | plan `SER`, DUT `impedance` | `spgu-load-mismatch` |
| plan blocked, selector not at rest | earlier run or human left it on PGU | `safe_shutdown`, `station_status` | `spgu-selector-state` |
| `spp_fallbacks` > 0 or fault latched | SPST? stuck, output would not stop | keep the fault; human checks | `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | fefet_lab | fefet-lab | S20261122T092630Z-2406 | needs_confirmation (unverified_pin_map, unverified_topology); 1000 pulses 0->4 V 1 us at 10 kHz through SEL1.OUT1, FeFET programmed, cleanup verified, selectors open | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` (temporary config and data dirs; folder not kept). Hardware
records: `validation/hw/spgu.pulse_train.yaml`, `validation/hw/spgu.alwg_sequence.yaml` (reviewed by a human after
stage L7; drafts only from hardware `H...` runs). Until then every hardware plan needs `first_hw_run` confirmation.
