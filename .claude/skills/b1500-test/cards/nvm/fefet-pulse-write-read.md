---
id: fefet-pulse-write-read
title: FeFET pulse write/read — erase/program pulses (SPGU via the selector, or WGFMU in microseconds), reads, memory window
family: nvm
intent: [FeFET, memory window from pulses, program pulse, erase pulse, write read, program verify, pulse then read, SPGU program SMU read, fast read, WGFMU program read]
recipes: [fefet.pulse_write_read, spgu.program_smu_read, fefet.fast_program_read]
device_types: [fefet, flash, nvm]
modules: [HVSPGU, HRSMU, MPSMU, GNDU, WGFMU]
routes: [selector_16440a:pgu, selector_16440a:smu, rsu:wgfmu]
bringup_stage: L7
recipe_stages: {fefet.fast_program_read: L8}
status: sim_validated
confirmation: conditional
knowledge: [knowledge/09-pulse-spgu-selector.md#program-and-read, knowledge/09-pulse-spgu-selector.md#hv-spgu-output-and-the-ser-load, knowledge/06b-analysis-time-pulse.md#program-read-memory-window, knowledge/04-ferroelectric-oxide.md#pulse-write-read-endurance-and-retention, knowledge/11-switching-routing.md#the-16440a-selector, knowledge/10-wgfmu-fast-iv-noise.md#pund-program-read-and-the-pulse_read-wgfmu-path]
manual: [PG p433 (4-115) "ERSSP", PG p507 (4-189) "SER", PG p512 (4-194) "SPRM", PG p142 (2-54) "SPST", PG p568-569 (4-250) "WV", WG p125 (4-55) "setMeasureEvent", WG p80 (4-10) "addSequence"]
debug: [spgu-pulse-no-effect, spgu-selector-state, spgu-load-mismatch, compliance-hit, noisy-data, wgfmu-range-overflow, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 2.7 pulse_read, blueprint v2 2.7.1 program_read, blueprint v2 2.10 nvm.py, blueprint v2 3.3, blueprint v2 3.4 (fefet.fast_program_read), blueprint v2 4.2 ferro, lwp/matlab_B1500/test_SPGU.m and lib/SPGU_pulse.m (lab script settings, not recommendations)]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# FeFET pulse write/read and memory window from pulses

## 1. Purpose and applicable devices

FeFET memory window from program/erase pulses, each followed by a read: MW = Vth(after erase) - Vth(after program).

- `fefet.pulse_write_read`: HV-SPGU through the 16440A selector, SMU Id-Vg reads (about a second after each pulse).
- `spgu.program_smu_read`: the same flow for any gated device (spot reads; ad hoc: always `adhoc_recipe`).
- `fefet.fast_program_read` (stage L8): gate and drain on the WGFMU, pulses and microsecond Id-Vg reads in ONE sequencer run (each read starts the rest of the period after its pulse, before the state relaxes).
- Not for: the DC loop ([fefet-dual-sweep-mw](fefet-dual-sweep-mw.md)), kinetics ([fefet-switching-kinetics](fefet-switching-kinetics.md)), endurance/retention ([fefet-endurance-retention](fefet-endurance-retention.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (pgu): erase/program pulses | SPGU 101 via `SEL1.OUT1` (PGU input) | 50 Ohm, no compliance, SER-adjusted |
| gate | `gate_read` (sweep_v, `terminal: gate`): read sweep, Ig | SMU3 via `SEL1.OUT1` (SMU input) | Force only through the selector |
| drain | `drain`: read bias Vd, Id | SMU4 (HRSMU preferred) | 0 V while the pulses run (`vd_pulse`) |
| source / bulk | ground | GNDU | bulk optional |
| gate / drain | `gate`, `drain` (wgfmu; `fefet.fast_program_read`) | WGFMU 201 / 202 via `RSU201.OUT` / `RSU202.OUT` | no compliance: `irange` |

- Pin maps `fefet-sel`, `fefet-wgfmu`; DUT `fefet-lab` (example envelope, not a measured device). Routes per phase: `erase`/
  `program`: `SEL1.OUT1 -> pgu`, `read`: `-> smu`, `rest`: `-> open`; WGFMU `waveform`: `RSU201/202.OUT -> wgfmu`.

## 3. Pre-run checklist

- `station_status` clean (no fault, no run, selectors at rest, no SPGU output); DUT profile with the gate's `pulse`
  envelope, reviewed by the human against the film; never invent or widen one. Pulse levels, widths and the read
  sweep are the human's (knowledge 04); the read stays well inside the coercive voltage (a DC loop shows where).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_program` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | 4 V | - | -10..10 V | positive: lowers Vth (n-FeFET); the request, else the DUT profile (`v_program`), else ask; example default | beyond the coercive field: saturated state |
| `v_program` (`spgu.program_smu_read`) | 4 V | - | -20..20 V | program level: example default | set level at the pad (SER = load) |
| `v_erase` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | -4 V | - | -10..10 V | negative: raises Vth; the request, else the DUT profile (`v_erase`), else ask; example default | asymmetric levels shift both states |
| `v_erase` (`spgu.program_smu_read`) | -4 V | - | -20..20 V | erase level: example default | used when the sequence erases |
| `width` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | 1 us | - | 10 ns..1 ms | time at the pulse level: the request, else the DUT profile (`width`), else ask; example default; WGFMU Fast IV pulses >= 300 ns (WG p16 (1-4)) | NLS: switched fraction grows with log width |
| `width` (`spgu.program_smu_read`) | 1 us | - | 10 ns..1 s | program width: example default | - |
| `period` | 10 us | 1 us..1 ms | 20 ns..1 s | repetition (count > 1) | >= width + t_edge / 0.8 (PG p591 (5-19)) |
| `count` (`fefet.pulse_write_read`) | 1 | 1..10 | 1..1000 | pulses per operation | soft band 10,000 per run |
| `count` (`spgu.program_smu_read`) | 1 | 1..100 | 1..100000 | pulses per operation | soft band 10,000 per run |
| `count` (`fefet.fast_program_read`) | 1 | 1..10 | 1..100 | pulses per operation | 4 vectors each |
| `t_edge` (`fefet.pulse_write_read`, `spgu.program_smu_read`) | 20 ns | 20 ns..1 us | 8 ns..0.4 s | rise and fall | width >= t_edge / 0.8 |
| `t_edge` (`fefet.fast_program_read`) | 100 ns | 70 ns..1 us | 10 ns..100 us | WGFMU edges (>= 70 ns limits overshoot, WG5 p25 (1-15)) | period > 2 t_edge + width |
| `load_ohm` | 1 MOhm | 1 kOhm..1 MOhm | 0.1 Ohm..1 MOhm | declared load SER | 50 Ohm doubles the level on the open gate |
| `sequence` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | erase_program | - | erase_program, program_erase | order per cycle | each operation is followed by a read |
| `sequence` (`spgu.program_smu_read`) | program_erase | - | program_erase, erase_program, program, erase | order per cycle | `program`: cumulative program pulses |
| `cycles` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | 1 | 1..5 | 1..50 | repetitions | MW per cycle and its spread |
| `cycles` (`spgu.program_smu_read`) | 3 | 1..20 | 1..200 | repetitions | many cycles: async run |
| `initial_read` | true | - | - | reference read before any pulse (`schedule` cycles only) | `vth_initial` / `i_initial` |
| `read_kind` (`fefet.pulse_write_read`) | staircase | - | staircase, spot | Id-Vg per read | Vth and MW |
| `read_kind` (`spgu.program_smu_read`) | spot | - | spot, staircase | Id at vg_read | read currents and their ratio |
| `vg_start` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | -0.5 V | - | -5..5 V | read sweep start, below your programmed Vth | `vg_stop` 1.8 V is an example: above the erased Vth, below the film's Vc (the request, else the DUT profile `read_vg_max`, else ask) |
| `vg_start` (`spgu.program_smu_read`) | -0.5 V | - | -10..10 V | read sweep start (`read_kind` staircase) | `vg_stop` 1.8 V (-10..10 V) |
| `vg_points` | 47 | - | 11..401 | 50 mV steps | fewer points: shorter read, less disturb |
| `vg_read` (`fefet.pulse_write_read`) | 0.6 V | - | -5..5 V | spot read level: example default | between your two Vth |
| `vg_read` (`spgu.program_smu_read`) | 0.9 V | - | -10..10 V | spot read level: example default | between your two Vth |
| `vd` (`fefet.pulse_write_read`, `fefet.fast_program_read`) | 50 mV | 20..100 mV | -1..1 V | read drain bias (linear region) | larger: read disturb |
| `vd` (`spgu.program_smu_read`) | 50 mV | 20..500 mV | -5..5 V | read drain bias | larger: read disturb |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | read gate compliance | a compliance stops the run |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | read drain compliance | above the profile's `max_abs_i`: confirmation |
| `settle` | 0 s | 0..1 s | 0..60 s | wait before each read | relaxation after the pulse |
| `samples` (`spgu.program_smu_read`) | 3 | 1..10 | 1..100 | spot readings per read | averaged |
| `integration` | `medium` | `medium` | `short`, `medium`, `long` | read ADC preset | keep fixed between devices |
| `irange` | 100ua | - | 1ua, 10ua, 100ua, 1ma, 10ma | drain range | saturates above: status V |
| `read_edge` | 100 ns | 70 ns..1 us | 10 ns..100 us | between read levels (>= 70 ns, WG5 p25 (1-15)) | - |
| `read_width` | 1 us | 500 ns..10 us | 20 ns..10 ms | flat time per read level | `read_settle` 500 ns not averaged |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fefet.pulse_write_read
params: {}
pin_map: fefet-sel
dut_profile: fefet-lab
sim_scenario: fefet_lab
```

## 5. Limits and confirmation

- The guard checks every pulse at the pad (SPGU open-load `|V| (SER + 50) / SER`, width, duty, count, on-time; every
  WGFMU pattern before the first library call) and every read level; routes only the plan's or a rest state.
- Blocked: `load_ohm` < 1 kOhm on the `high_z` gate (R-SPGU-01), timing outside the module (R-PULSE-01, R-WG-02), no
  gate `pulse` envelope (R-PULSE-02), `read_kind: wgfmu` with the SPGU, selector not at rest.
- Confirm: `unverified_topology`/`unverified_pin_map`, `dut_envelope`, `soft_pulse` (5 V, 10,000 pulses, 60 s, duty
  0.5), `adhoc_recipe` (`spgu.program_smu_read`), `long_run` (async), `first_hw_run`. Every run rewrites the state.

## 6. Quality criteria

- `N` ok; `C`/`T` limited; `V X F D G S U` untrusted (WGFMU `V`: range saturated); a compliance stops the run.
  `kind_result`: `reads_done` = `reads_planned`, `spp_fallbacks` 0, `routes` PGU -> SMU per operation; cleanup verified.

## 7. Analysis method

- `memory_window_pulse` (constant current 100 nA): MW = mean Vth(erase) - mean Vth(program); `vth_program`,
  `vth_erase`, per-cycle spread ([06b](../../knowledge/06b-analysis-time-pulse.md#program-read-memory-window)); spot reads: `current_ratio`.
- Report: name the method id next to every derived value (`MW = <value> V; memory_window_pulse`), sign, both state
  Vths, amplitude/width/count, cycles, status counts, routes and cleanup verified, backend (SIMULATED on `sim`).

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| device | expected (source) | red flags |
|---|---|---|
| FeFET, program/erase pulses | MW > 0: Vth(erase) above Vth(program) for an n-FeFET (physics); MW size unknown for your films ([04](../../knowledge/04-ferroelectric-oxide.md#pulse-write-read-endurance-and-retention)); read repeatability `TODO(verify)[L7.A7]` | MW ~ 0 (below Vc, wrong path); shrinking (fatigue) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| MW ~ 0, reads identical | selector not on PGU, pulses too small | `kind_result.routes`, audit read-backs | `spgu-pulse-no-effect` |
| plan blocked, selector not at rest | earlier run or human left it switched | `safe_shutdown`, `station_status` | `spgu-selector-state` |
| states shifted more than expected | SER 50 Ohm on the open gate, wrong load | plan `SER`, DUT `impedance` | `spgu-load-mismatch` |
| read or pulse compliance, run stopped | damaged stack, short | stop; report; gate-leakage card | `compliance-hit` |
| fault latched; long run `aborted` after the session ended | relay stuck; server killed mid-run | keep the fault; `safe_shutdown` recovers | `cleanup-failed-fault`, `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T052416Z-c250 | fefet.pulse_write_read: needs_confirmation (unverified_pin_map, unverified_topology); MW 0.9903 V vs truth 0.9904 V (-0.01 %); routes PGU -> SMU per operation, rest verified; N=282 | - |
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T052416Z-f7e8 | spgu.program_smu_read: needs_confirmation (+ adhoc_recipe); 3 cycles, spot reads, current_ratio 6.4e3; N=21 | - |
| sim | 2026-11-25 | fefet_lab | fefet-lab | S20261125T112522Z-4966 | fefet.fast_program_read: needs_confirmation (unverified_pin_map, unverified_topology); MW 0.916 V vs truth 0.911 V (+0.5 %), each read within 10 us of its pulse; N=141 | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim rows: example plans via `B1500Service`. Hardware records (L7; L8 for the WGFMU recipe): `validation/hw/fefet.pulse_write_read.yaml`,
`validation/hw/spgu.program_smu_read.yaml`, `validation/hw/fefet.fast_program_read.yaml`.
