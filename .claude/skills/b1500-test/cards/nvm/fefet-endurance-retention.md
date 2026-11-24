---
id: fefet-endurance-retention
title: FeFET endurance and retention — bipolar cycling with checkpoint reads, reads at log times after a write
family: nvm
intent: [FeFET, endurance, cycling, program erase cycles, wake-up, fatigue, retention, data retention, memory window versus cycles, memory window versus time, 10 years]
recipes: [fefet.endurance, fefet.retention]
device_types: [fefet]
modules: [HVSPGU, HRSMU, MPSMU, GNDU]
routes: [selector_16440a:pgu, selector_16440a:smu]
bringup_stage: L9
status: sim_validated
confirmation: conditional
knowledge: [knowledge/04-ferroelectric-oxide.md#pulse-write-read-endurance-and-retention, knowledge/04-ferroelectric-oxide.md#retention, knowledge/06b-analysis-time-pulse.md#endurance, knowledge/06b-analysis-time-pulse.md#retention, knowledge/09-pulse-spgu-selector.md#program-and-read, knowledge/05-reliability-defects.md#ferroelectric-wake-up-imprint-and-fatigue]
manual: [PG p433 (4-115) "ERSSP", PG p507 (4-189) "SER", PG p512 (4-194) "SPRM", PG p146 (2-58) "3-level", PG p142 (2-54) "SPST"]
debug: [spgu-pulse-no-effect, spgu-selector-state, spgu-load-mismatch, compliance-hit, noisy-data, cleanup-failed-fault]
sources: [blueprint v2 2.6 async runs, blueprint v2 2.7 pulse_read, blueprint v2 2.10 nvm.py, blueprint v2 3.3, blueprint v2 4.2 ferro, AN-NVM]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# FeFET endurance and retention

## 1. Purpose and applicable devices

How long the FeFET memory window lasts, in cycles and in time: HV-SPGU writes through the 16440A selector, SMU Id-Vg
reads; long runs (asynchronous: `running`, poll `get_run`, cancel with `safe_shutdown`).

- `fefet.endurance`: bipolar program/erase cycling to `cycles` (default 10^6); at log-spaced cycle counts one cycle
  runs as erase -> read -> program -> read; the cycles in between are three-level SPGU bursts (`cycling`). MW(N):
  wake-up, fatigue, cycles to failure.
- `fefet.retention`: write the programmed, then the erased state; reads at log times after each write up to
  `retention_time` (gate and drain held at 0 V between reads). Vth and MW versus log t, slopes, 10-year extrapolation.
- Not for: one MW measurement ([fefet-pulse-write-read](fefet-pulse-write-read.md)), kinetics
  ([fefet-switching-kinetics](fefet-switching-kinetics.md)); FeCap PUND endurance (WP10.6).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (pgu): cycling bursts, program/erase | SPGU 101 via `SEL1.OUT1` (PGU input) | 50 Ohm, no compliance, SER-adjusted |
| gate | `gate_read` (sweep_v, `terminal: gate`): reads, 0 V holds | SMU3 via `SEL1.OUT1` (SMU input) | Force only through the selector |
| drain | `drain`: read bias Vd, Id; 0 V otherwise | SMU4 (HRSMU preferred) | - |
| source / bulk | ground | GNDU | bulk optional |

- Pin map `fefet-sel`, DUT profile `fefet-lab`. Routes per phase: `cycling` (endurance bursts), `erase`, `program`:
  `SEL1.OUT1 -> pgu`; `read` (and the retention holds): `SEL1.OUT1 -> smu`; `rest`: `SEL1.OUT1 -> open`; the
  cleanup returns every declared selector output to rest, verified, also after a cancel.

## 3. Pre-run checklist

- `station_status` clean (no fault, no active run, selectors at rest). The run holds the instrument throughout (18 min
  endurance, 5.7 h retention by default): agree the time with the human first. Retention: room temperature; record it.
- Endurance: 10^6 cycles are 2 x 10^6 gate pulses: the human checks the profile's pulse `max_count` and the film.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `cycles` | 1000000 | 1000..10000000 | 1..1000000000 | total cycles (last checkpoint) | time = cycles x cycle_period |
| `cycle_reads` | log | - | log, list | checkpoint placement | list: `read_cycles` |
| `reads_per_decade` | 3 | 2..5 | 1..20 | checkpoints (or reads) per decade | more: longer run |
| `read_cycles` | [1, 10, 100, 1000, 10000, 100000] | - | 1..1000000000 | listed checkpoints | integers |
| `cycle_period` (`fefet.endurance`) | 1 ms | 10 us..10 ms | 40 ns..1 s | one bipolar cycle in a burst | sets the run time |
| `cycle_period` (`fefet.retention`) | 10 us | 4 us..1 ms | 40 ns..1 s | one wake-up cycle | - |
| `retention_time` | 10000 s | 1000..30000 s | 20 ms..43200 s | last read after each write | both states: 2x the time |
| `first_read` | 1 s | 1..10 s | 20 ms..3600 s | first read after the write | earlier: read disturb |
| `precycles` | 0 | 0..10000 | 0..1000000 | wake-up before the writes | woken film |
| `sequence` (`fefet.endurance`) | erase_program | - | erase_program, program_erase | operation order per cycle | - |
| `sequence` (`fefet.retention`) | program_erase | - | program_erase, erase_program, program, erase | states written in turn | one state: no MW |
| `v_program` | 4 V | 3..5 V | -10..10 V | program level (n-FeFET positive) | - |
| `v_erase` | -4 V | -5..-3 V | -10..10 V | erase level | - |
| `width` | 1 us | 100 ns..100 us | 10 ns..1 ms | program/erase width | - |
| `period` | 10 us | 1 us..1 ms | 20 ns..1 s | period with count > 1 | - |
| `count` | 1 | 1..10 | 1..1000 | pulses per write | - |
| `t_edge` | 20 ns | 20 ns..1 us | 8 ns..0.4 s | rise and fall | width >= t_edge / 0.8 |
| `load_ohm` | 1 MOhm | 1 kOhm..1 MOhm | 0.1 Ohm..1 MOhm | declared load SER | 50 Ohm doubles the level |
| `initial_read` | true | - | - | reference read before the first pulse | - |
| `schedule` (`fefet.endurance`) | cycles | - | cycles | checkpoints in cycles | - |
| `schedule` (`fefet.retention`) | retention | - | retention | reads at log times | - |
| `read_kind` | staircase | - | staircase, spot | Id-Vg per read | spot: currents only |
| `vg_start` | -0.5 V | -1..0 V | -5..5 V | read sweep start | - |
| `vg_stop` | 1.8 V | 1.5..2 V | -5..5 V | read sweep stop, below Vc | higher: read disturb |
| `vg_points` | 47 | 31..101 | 11..401 | 50 mV steps | - |
| `vg_read` | 0.6 V | 0..1.5 V | -5..5 V | spot read level | - |
| `vd` | 50 mV | 20..100 mV | -1..1 V | read drain bias | - |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | gate compliance (reads, holds) | a compliance stops the run |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | drain compliance | - |
| `settle` | 0 s | 0..1 s | 0..60 s | wait before each endurance read | - |
| `samples` | 1 | - | 1..100 | spot readings per read | - |
| `integration` | `medium` | `medium` | `short`, `medium`, `long` | read ADC preset | keep fixed between devices |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fefet.endurance
params: {}
pin_map: fefet-sel
dut_profile: fefet-lab
sim_scenario: fefet_lab
```

## 5. Limits and confirmation

- The guard checks every pulse, burst, read and hold level at the pad; routes are only the plan's or a rest state;
  bursts are bounded SPGU outputs (`SPRM 1`, at most 1,000,000 cycles each, never free run).
- Blocked: a cycle period too short for both pulses, timing outside the SPGU (R-PULSE-01), `load_ohm` < 1 kOhm on
  the `high_z` gate (R-SPGU-01), no gate `pulse` envelope (R-PULSE-02), a run longer than 24 h (R-RUN-02).
- Confirm: `long_run`, `soft_pulse` (> 10,000 pulses), `dut_envelope` (> the profile's `max_count`), unverified
  topology/pin map; on hardware `first_hw_run`. Endurance wears the film out: cycle a spare device first.

## 6. Quality criteria

- Reads: `N` ok; `C`/`T` limited; `V X F D G S U` untrusted (the read drops out). A compliance in a read or hold
  stops the run (`stop_reason`); cancelled rows are PARTIAL. `kind_result`: `cycles_done`, `burst_cycles_done`
  (endurance), `hold_blocks`, `held_s`, `hold_i_max_a` (retention); `spp_fallbacks` 0; cleanup verified.

## 7. Analysis method

- `endurance_summary` (endurance default): MW per checkpoint; `memory_window_initial`, `_max`, `_final`, `wake_up`,
  `fatigue`, `cycles_to_failure` (MW below half its maximum) ([06b](../../knowledge/06b-analysis-time-pulse.md#endurance)).
- `retention_fit` (retention default): slope per state and of the MW (V/dec), `memory_window_at_target` (10 years),
  `retention_time` ([06b](../../knowledge/06b-analysis-time-pulse.md#retention)). Extrapolations are derived: say so.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| HZO FeFET, +-4 V 1 us | MW opens a few % (wake-up), closes after 10^4-10^6 cycles | MW collapses abruptly (breakdown), Ig rising |
| HZO FeFET, room temperature | Vth of each state drifts tens of mV per decade | one state drifts much faster (imprint, trapping) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| MW ~ 0 from the first checkpoint | selector not on PGU, pulses too small | `kind_result.routes`, audit read-backs | `spgu-pulse-no-effect` |
| plan blocked, selector not at rest | earlier run left it switched | `safe_shutdown`, `station_status` | `spgu-selector-state` |
| states shifted more than expected | SER 50 Ohm on the open gate | plan `SER`, DUT `impedance` | `spgu-load-mismatch` |
| read or hold compliance, run stopped | gate breakdown during cycling | stop; report cycles reached | `compliance-hit` |
| scattered Vth between reads | contact drift over hours, noise | reads' status counts, re-land | `noisy-data` |
| fault latched after a cancel | relay stuck, SPGU will not stop | keep the fault; human checks | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T094146Z-801e | fefet.endurance: needs_confirmation (dut_envelope, long_run, soft_pulse, unverified_pin_map, unverified_topology), async ~18 min; 10^6 cycles; MW 0.911 -> 0.985 V (wake-up, 464 cycles) -> 0.090 V; cycles to failure 1.01e5; N=3666 | - |
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T094149Z-0610 | fefet.retention: needs_confirmation (long_run, unverified_pin_map, unverified_topology), async ~5.7 h; slopes 0.01363 / -0.01351 V/dec vs truth 0.01367 / -0.01367 V/dec; N=2538 | - |
| hw | pending (bring-up stage L9) | - | - | - | - | - |

Sim rows: the example plan and the retention defaults through `B1500Service` (folders not kept). Hardware records:
`validation/hw/fefet.endurance.yaml`, `validation/hw/fefet.retention.yaml` (human-reviewed after L9).
