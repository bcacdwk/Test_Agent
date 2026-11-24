---
id: fefet-pulse-write-read
title: FeFET pulse write/read — erase/program pulses via the selector, SMU reads, memory window from pulses
family: nvm
intent: [FeFET, memory window from pulses, program pulse, erase pulse, write read, program verify, pulse then read, SPGU program SMU read]
recipes: [fefet.pulse_write_read, spgu.program_smu_read]
device_types: [fefet, flash, nvm]
modules: [HVSPGU, HRSMU, MPSMU, GNDU]
routes: [selector_16440a:pgu, selector_16440a:smu]
bringup_stage: L7
status: sim_validated
confirmation: conditional
knowledge: [knowledge/09-pulse-spgu-selector.md#program-and-read, knowledge/09-pulse-spgu-selector.md#hv-spgu-output-and-the-ser-load, knowledge/06b-analysis-time-pulse.md#program-read-memory-window, knowledge/04-ferroelectric-oxide.md#pulse-write-read-endurance-and-retention, knowledge/11-switching-routing.md#the-16440a-selector]
manual: [PG p433 (4-115) "ERSSP", PG p507 (4-189) "SER", PG p512 (4-194) "SPRM", PG p142 (2-54) "SPST", PG p568-569 (4-250) "WV"]
debug: [spgu-pulse-no-effect, spgu-selector-state, spgu-load-mismatch, compliance-hit, noisy-data, cleanup-failed-fault]
sources: [blueprint v2 2.7 pulse_read, blueprint v2 2.10 nvm.py, blueprint v2 3.3, blueprint v2 4.2 ferro, lwp SPGU_pulse.m]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# FeFET pulse write/read and memory window from pulses

## 1. Purpose and applicable devices

The memory window of a FeFET from program/erase pulses (HV-SPGU through the 16440A selector), each operation followed
by an SMU read (Id-Vg at a small drain bias, or spot Id): MW = Vth(after erase) - Vth(after program).

- `fefet.pulse_write_read`: erase, read, program, read per cycle (or program first), Id-Vg reads, MW.
- `spgu.program_smu_read`: the same flow for any device with a gate pulse envelope (spot read currents; `v_base`,
  `erase_width`, drain level while pulsing `vd_pulse`); ad hoc by design: always confirmed (`adhoc_recipe`).
- Not for: the DC loop ([fefet-dual-sweep-mw](fefet-dual-sweep-mw.md)), pulses without reads
  ([spgu-pulse-train](../spgu/spgu-pulse-train.md)); kinetics ([fefet-switching-kinetics](fefet-switching-kinetics.md)),
  endurance and retention ([fefet-endurance-retention](fefet-endurance-retention.md)); WGFMU (WP10.6).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (pgu): erase/program pulses | SPGU 101 via `SEL1.OUT1` (PGU input) | 50 Ohm, no compliance, SER-adjusted |
| gate | `gate_read` (sweep_v, `terminal: gate`): read sweep, Ig | SMU3 via `SEL1.OUT1` (SMU input) | Force only through the selector |
| drain | `drain`: read bias Vd, Id | SMU4 (HRSMU preferred) | 0 V while the pulses run (`vd_pulse`) |
| source / bulk | ground | GNDU | bulk optional |

- Pin map `fefet-sel`, DUT profile `fefet-lab` (gate 5 V; pulse envelope 5 V, 1 ms, duty 0.5); selector inputs
  recorded at L7. Routes per phase: `erase`/`program`: `SEL1.OUT1 -> pgu`; `read`: `SEL1.OUT1 -> smu`; `rest`:
  `SEL1.OUT1 -> open` (`resolved.routes`); cleanup: every declared selector output to rest, verified.

## 3. Pre-run checklist

- `station_status` clean: no fault, no active run, every selector output at rest, no SPGU output running.
- DUT profile with the gate's `pulse` envelope and `impedance: high_z`, amplitude/width reviewed by the human against
  the film (knowledge 04). Never invent a profile or widen an envelope.
- Read sweep well inside the coercive voltage (it must not program the film); a DC loop shows where that is.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_program` (`fefet.pulse_write_read`) | 4 V | 3..5 V | -10..10 V | positive: lowers Vth (n-FeFET) | beyond the coercive field: saturated state |
| `v_program` (`spgu.program_smu_read`) | 4 V | -5..5 V | -20..20 V | program level | set level at the pad (SER = load) |
| `v_erase` (`fefet.pulse_write_read`) | -4 V | -5..-3 V | -10..10 V | negative: raises Vth | asymmetric levels shift both states |
| `v_erase` (`spgu.program_smu_read`) | -4 V | -5..5 V | -20..20 V | erase level | used when the sequence erases |
| `width` (`fefet.pulse_write_read`) | 1 us | 100 ns..100 us | 10 ns..1 ms | time at the pulse level | NLS: switched fraction grows with log width |
| `width` (`spgu.program_smu_read`) | 1 us | 100 ns..1 ms | 10 ns..1 s | program width | - |
| `period` | 10 us | 1 us..1 ms | 20 ns..1 s | repetition (count > 1) | >= width + t_edge / 0.8 |
| `count` (`fefet.pulse_write_read`) | 1 | 1..10 | 1..1000 | pulses per operation | soft band 10,000 per run |
| `count` (`spgu.program_smu_read`) | 1 | 1..100 | 1..100000 | pulses per operation | soft band 10,000 per run |
| `t_edge` | 20 ns | 20 ns..1 us | 8 ns..0.4 s | rise and fall | width >= t_edge / 0.8 |
| `load_ohm` | 1 MOhm | 1 kOhm..1 MOhm | 0.1 Ohm..1 MOhm | declared load SER | 50 Ohm doubles the level on the open gate |
| `sequence` (`fefet.pulse_write_read`) | erase_program | - | erase_program, program_erase | order per cycle | each operation is followed by a read |
| `sequence` (`spgu.program_smu_read`) | program_erase | - | program_erase, erase_program, program, erase | order per cycle | `program`: cumulative program pulses |
| `cycles` (`fefet.pulse_write_read`) | 1 | 1..5 | 1..50 | repetitions | MW per cycle and its spread |
| `cycles` (`spgu.program_smu_read`) | 3 | 1..20 | 1..200 | repetitions | many cycles: async run |
| `initial_read` | true | - | - | reference read before any pulse (`schedule` cycles only) | `vth_initial` / `i_initial` |
| `read_kind` (`fefet.pulse_write_read`) | staircase | - | staircase, spot | Id-Vg per read | Vth and MW |
| `read_kind` (`spgu.program_smu_read`) | spot | - | spot, staircase | Id at vg_read | read currents and their ratio |
| `vg_start` (`fefet.pulse_write_read`) | -0.5 V | -1..0 V | -5..5 V | read sweep start, below the programmed Vth | `vg_stop` 1.8 V: above the erased Vth, below Vc |
| `vg_start` (`spgu.program_smu_read`) | -0.5 V | -2..0 V | -10..10 V | read sweep start (`read_kind` staircase) | `vg_stop` 1.8 V (-10..10 V) |
| `vg_points` | 47 | - | 11..401 | 50 mV steps | fewer points: shorter read, less disturb |
| `vg_read` (`fefet.pulse_write_read`) | 0.6 V | 0..1.5 V | -5..5 V | spot read level | between the two Vth |
| `vg_read` (`spgu.program_smu_read`) | 0.9 V | -2..2 V | -10..10 V | spot read level | between the two Vth |
| `vd` (`fefet.pulse_write_read`) | 50 mV | 20..100 mV | -1..1 V | read drain bias (linear region) | larger: read disturb |
| `vd` (`spgu.program_smu_read`) | 50 mV | 20..500 mV | -5..5 V | read drain bias | larger: read disturb |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | read gate compliance | a compliance stops the run |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | read drain compliance | above the profile's `max_abs_i`: confirmation |
| `settle` | 0 s | 0..1 s | 0..60 s | wait before each read | relaxation after the pulse |
| `samples` (`spgu.program_smu_read`) | 3 | 1..10 | 1..100 | spot readings per read | averaged |
| `integration` | `medium` | `medium` | `short`, `medium`, `long` | read ADC preset | keep fixed between devices |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fefet.pulse_write_read
params: {}
pin_map: fefet-sel
dut_profile: fefet-lab
sim_scenario: fefet_lab
```

## 5. Limits and confirmation

- The guard checks every pulse at the pad (open-load level `|V| (SER + 50) / SER`, width, duty, count, on-time)
  and every read level and compliance; outputs are always bounded; routes are only the plan's or a rest state.
- Blocked: `load_ohm` below 1 kOhm on the `high_z` gate (R-SPGU-01), timing outside the SPGU (R-PULSE-01), no gate
  `pulse` envelope (R-PULSE-02), a `wgfmu` pulse role or `read_kind: wgfmu` (WP10.6), selector not at rest.
- Confirm: `unverified_topology`/`unverified_pin_map` (lab wiring unverified), `dut_envelope` (outside the gate's
  pulse or DC envelope), `soft_pulse` (above 5 V at the pad, 10,000 pulses, 60 s on-time, duty 0.5),
  `adhoc_recipe` (always for `spgu.program_smu_read`), `long_run` (long plans run async); on hardware `first_hw_run`.
  Not destructive within the envelope; every run rewrites the polarization (wake-up/fatigue cycles add up).

## 6. Quality criteria

- Reads: `N` ok; `C`/`T` limited (excluded); `V X F D G S U` untrusted (that read refused). A compliance in a read
  or SMU pulse stops the run (`kind_result.stop_reason`): report it, never re-run blindly. `kind_result`: `reads_done`
  = `reads_planned`, `spp_fallbacks` 0, `routes` PGU before and SMU after every operation, `rest` last; cleanup verified.

## 7. Analysis method

- Default `memory_window_pulse` (`fefet.pulse_write_read`: `{vth_method: constant_current, i_crit_a: 1e-7}`):
  MW = mean Vth(erase) - mean Vth(program) of the Id-Vg reads; `vth_program`, `vth_erase`, `vth_initial`; per-cycle
  spread in the MW `fit` ([06b](../../knowledge/06b-analysis-time-pulse.md#program-read-memory-window)); spot reads
  (`spgu.program_smu_read` default): `i_program`, `i_erase`, `i_initial`, `current_ratio`.
- Report: MW with sign and method, both state Vths, amplitude/width/count, cycles, status counts, SIMULATED flag.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| hafnia FeFET, +-4 V 1 us pulses | MW positive, a fraction of a volt to about 2 V; erase Vth > program Vth | MW ~ 0 (pulses below Vc, wrong path) |
| any | reads repeat within a few mV between cycles | MW shrinking each cycle (fatigue); negative MW (trapping) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| MW ~ 0, reads identical | selector not on PGU, pulses too small | `kind_result.routes`, audit read-backs | `spgu-pulse-no-effect` |
| plan blocked, selector not at rest | earlier run or human left it switched | `safe_shutdown`, `station_status` | `spgu-selector-state` |
| states shifted more than expected | SER 50 Ohm on the open gate, wrong load | plan `SER`, DUT `impedance` | `spgu-load-mismatch` |
| read or pulse compliance, run stopped | damaged stack, short | stop; report; gate-leakage card | `compliance-hit` |
| fault latched, cleanup unverified | relay stuck, SPGU will not stop | keep the fault; human checks | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T052416Z-c250 | fefet.pulse_write_read: needs_confirmation (unverified_pin_map, unverified_topology); MW 0.9903 V vs truth 0.9904 V (-0.01 %); routes PGU -> SMU per operation, rest verified; N=282 | - |
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T052416Z-f7e8 | spgu.program_smu_read: needs_confirmation (+ adhoc_recipe); 3 cycles, spot reads, current_ratio 6.4e3; N=21 | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim rows: the example plans through `B1500Service` (temporary config/data; folders not kept). Hardware records:
`validation/hw/fefet.pulse_write_read.yaml`, `validation/hw/spgu.program_smu_read.yaml` (human-reviewed after L7).
