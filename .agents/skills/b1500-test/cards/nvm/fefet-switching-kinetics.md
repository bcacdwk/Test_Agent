---
id: fefet-switching-kinetics
title: FeFET switching kinetics — amplitude x width grid or ISPP of gate pulses, NLS tau0, Va, beta
family: nvm
intent: [FeFET, switching kinetics, switching time, NLS, nucleation limited switching, pulse amplitude width map, ISPP, incremental step pulse, tau0, Merz law]
recipes: [fefet.switching_kinetics]
device_types: [fefet]
modules: [HVSPGU, HRSMU, MPSMU, GNDU]
routes: [selector_16440a:pgu, selector_16440a:smu]
bringup_stage: L7
status: sim_validated
confirmation: conditional
knowledge: [knowledge/04-ferroelectric-oxide.md#pulse-switching-kinetics, knowledge/06b-analysis-time-pulse.md#switching-kinetics, knowledge/09-pulse-spgu-selector.md#program-and-read, knowledge/09-pulse-spgu-selector.md#hv-spgu-output-and-the-ser-load, knowledge/11-switching-routing.md#the-16440a-selector]
manual: [PG p433 (4-115) "ERSSP", PG p507 (4-189) "SER", PG p512 (4-194) "SPRM", PG p146 (2-58) "3-level", PG p142 (2-54) "SPST"]
debug: [spgu-pulse-no-effect, spgu-selector-state, spgu-load-mismatch, compliance-hit, noisy-data, cleanup-failed-fault]
sources: [blueprint v2 2.7 pulse_read, blueprint v2 2.10 nvm.py, blueprint v2 3.3, blueprint v2 4.2 ferro, "NLS model form after Tagantsev et al., Phys. Rev. B 66, 214109 (2002), not page-checked (TODO(cite))"]
version: 1
---

# FeFET switching kinetics (amplitude x width grid, ISPP)

## 1. Purpose and applicable devices

How fast and how far a FeFET switches versus pulse amplitude and width: the HV-SPGU resets the gate (erase) and then
gives one program pulse per point of an amplitude x width grid through the 16440A selector; after every pulse an SMU
Id-Vg read gives Vth. The nucleation-limited-switching fit gives `tau0`, `Va`, `beta` (`tau(V)` per amplitude).

- `fefet.switching_kinetics` `grid_mode: reset` (default): reset before every point, NLS fit.
- `grid_mode: ispp`: one reset per width, amplitudes in increasing order cumulatively: the program characteristic
  (`v50`, step slope); no NLS parameters.
- Not for: the memory window of one pulse pair ([fefet-pulse-write-read](fefet-pulse-write-read.md)), cycling or
  retention ([fefet-endurance-retention](fefet-endurance-retention.md)), the DC loop
  ([fefet-dual-sweep-mw](fefet-dual-sweep-mw.md)); pulses below 10 ns (no module: SPGU width >= 10 ns, PG p514 (4-196);
  WGFMU >= 100 ns in PG mode, 300 ns in Fast IV mode, WG p16 (1-4)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (pgu): reset, grid and wake-up pulses | SPGU 101 via `SEL1.OUT1` (PGU input) | 50 Ohm, no compliance, SER-adjusted |
| gate | `gate_read` (sweep_v, `terminal: gate`): read sweep, Ig | SMU3 via `SEL1.OUT1` (SMU input) | Force only through the selector |
| drain | `drain`: read bias Vd, Id | SMU4 (HRSMU preferred) | 0 V while the pulses run |
| source / bulk | ground | GNDU | bulk optional |

- Pin map `fefet-sel`, DUT profile `fefet-lab` (gate pulse envelope 5 V, 1 ms, duty 0.5); selector inputs recorded
  at L7. Routes per phase: `cycling` (wake-up), `erase` (reset), `program` (grid): `SEL1.OUT1 -> pgu`; `read`:
  `SEL1.OUT1 -> smu`; `rest`: `SEL1.OUT1 -> open`; cleanup returns every declared selector output to rest, verified.

## 3. Pre-run checklist

- `station_status` clean (no fault, no active run, selector outputs at rest, SPGU stopped).
- DUT profile with the gate's `pulse` envelope reviewed by the human (largest amplitude x SER gain within it: 4.8 V
  at SER 1 MOhm puts 4.80024 V on the open gate); a DC loop first shows the coercive region.
- Shortest width >= `t_edge` / 0.8 (10 ns at 8 ns edges; PG p514 (4-196), PG p591 (5-19)); `period` above the longest width.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `amplitudes` | [3.2, 3.6, 4.0, 4.4, 4.8] V | - | -10..10 V | grid amplitudes (program direction): example default, span your film's coercive region (ask) | below Vc: small windows |
| `widths` | [10 ns, 20 ns, 50 ns, 100 ns, 200 ns, 500 ns, 1 us, 2 us, 5 us, 10 us, 100 us] | - | 10 ns..1 ms | log-spaced example grid; reach beyond your film's saturation | span sets the fit window |
| `grid_mode` | reset | - | reset, ispp | reset: NLS fit | ispp: cumulative, v50 |
| `reset_read` | true | - | - | read after each reset | checks complete resets |
| `v_program` | 4 V | - | -10..10 V | wake-up cycle program level: example default | - |
| `v_erase` | -4 V | - | -10..10 V | reset level (and wake-up): example default | must saturate the erased state |
| `width` | 1 us | - | 10 ns..1 ms | reset and wake-up width: example default | long enough to saturate |
| `period` | 1 ms | 100 us..10 ms | 20 ns..1 s | period of reset and grid pulses | > longest width + edges |
| `count` | 1 | 1..1 | 1..100 | pulses per reset or grid point | more: cumulative switching |
| `t_edge` | 8 ns | 8 ns..20 ns | 8 ns..0.4 s | rise and fall | widths >= t_edge / 0.8 |
| `load_ohm` | 1 MOhm | 1 kOhm..1 MOhm | 0.1 Ohm..1 MOhm | declared load SER | 50 Ohm doubles the level |
| `sequence` | erase_program | - | erase_program, program_erase | reset, then grid operation | program_erase: erase kinetics |
| `precycles` | 1000 | 0..10000 | 0..1000000 | wake-up bipolar cycles first: example default (wake-up length of your film unknown) | stable A(V) during the grid |
| `cycle_period` | 10 us | 4 us..1 ms | 40 ns..1 s | wake-up cycle period | >= 2 x (width + t_edge / 0.8) |
| `initial_read` | true | - | - | reference read after wake-up | `vth` before the grid |
| `schedule` | grid | - | grid | amplitude x width grid | - |
| `read_kind` | staircase | - | staircase, spot | Id-Vg per read | spot: no fit |
| `vg_start` | -0.5 V | - | -5..5 V | read sweep start: example default | below your programmed Vth |
| `vg_stop` | 1.8 V | - | -5..5 V | read sweep stop: example default; stays below your film's Vc (ask) | higher: read disturb |
| `vg_points` | 47 | 31..101 | 11..401 | 50 mV steps | fewer: shorter reads |
| `vg_read` | 0.6 V | - | -5..5 V | spot read level: example default, between your two Vth | - |
| `vd` | 50 mV | 20..100 mV | -1..1 V | read drain bias | larger: read disturb |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | read gate compliance | a compliance stops the run |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | read drain compliance | - |
| `settle` | 0 s | 0..1 s | 0..60 s | wait before each read | relaxation after the pulse |
| `samples` | 1 | - | 1..100 | spot readings per read | - |
| `integration` | `medium` | `medium` | `short`, `medium`, `long` | read ADC preset | keep fixed between devices |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fefet.switching_kinetics
params: {}
pin_map: fefet-sel
dut_profile: fefet-lab
sim_scenario: fefet_lab
```

## 5. Limits and confirmation

- The guard checks every pulse at the pad (open-load level, width, duty, count, on-time) and every read level;
  routes are only the plan's or a rest state. 55 points x 2 reads take about 4.5 min (sync).
- Blocked: a width below `t_edge` / 0.8 or off the 2.5 ns grid (R-PULSE-01; PG p514 (4-196)), `load_ohm` < 1 kOhm on the `high_z`
  gate or an open-load level above the gate's pulse limit (R-SPGU-01), no gate `pulse` envelope (R-PULSE-02).
- Confirm: `unverified_topology`/`unverified_pin_map`, `dut_envelope`, `soft_pulse` (above 5 V at the pad), on
  hardware `first_hw_run`. Every point rewrites the film; the wake-up cycles add to its history.

## 6. Quality criteria

- Reads: `N` ok; `C`/`T` limited (excluded); `V X F D G S U` untrusted (that point drops out with a warning). A read
  in compliance stops the run. A `vth_reset` spread within your read repeatability (`TODO(verify)[L7.A7]`) means
  complete resets; `r2` of the fit near 1.

## 7. Analysis method

- Default `switching_kinetics_fit` (`{vth_method: constant_current, i_crit_a: 1e-7}`): NLS `Vth = V0 + A(V) (1 -
  exp(-(w/tau(V))^beta))`, `tau(V) = tau0 exp((Va/|V|)^alpha)`, `alpha` 2 (a fit convention, not your film's value;
  `alpha: null` frees it): `tau0`, `va`, `beta`, `tau@<V>V` and `window@<V>V` in the fit, `vth_reset`
  ([06b](../../knowledge/06b-analysis-time-pulse.md#switching-kinetics)). ISPP: `v50`, `ispp_slope`.
- Report: tau(V) at the measured amplitudes (tau0 is an extrapolation), beta, the width window, points used,
  status counts, backend (SIMULATED on `sim`).

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| device | expected (source) | red flags |
|---|---|---|
| FeFET, NLS grid | tau falls with the amplitude (Merz form, physics); tau(V) and beta unknown for your films ([04](../../knowledge/04-ferroelectric-oxide.md#pulse-switching-kinetics)) | no switching at any width (selector, amplitude) |
| any | dVth grows with log(width), saturates per amplitude (NLS, physics) | vth_reset spread beyond the read repeatability (incomplete reset) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| no Vth change at any point | selector not on PGU, amplitude below Vc | `kind_result.routes`, audit read-backs | `spgu-pulse-no-effect` |
| plan blocked, selector not at rest | earlier run left it switched | `safe_shutdown`, `station_status` | `spgu-selector-state` |
| switching faster than plausible | SER 50 Ohm on the open gate | plan `SER`, DUT `impedance` | `spgu-load-mismatch` |
| read compliance, run stopped | damaged stack | stop; report; gate leakage | `compliance-hit` |
| noisy Vth, poor fit | integration too short, contact | reads' status counts | `noisy-data` |
| fault latched | relay stuck, SPGU will not stop | keep the fault; human checks | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | fefet_lab | fefet-lab | S20261124T094145Z-887b | needs_confirmation (unverified_pin_map, unverified_topology); tau0 9.98e-10 s vs truth 1e-9 s, beta 0.9996 vs 1.0, Va 8.001 V vs 8 V; 55 points, N=10434, routes PGU -> SMU per pulse, rest verified | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim row: the example plan through `B1500Service` (temporary config/data; folder not kept). Hardware record:
`validation/hw/fefet.switching_kinetics.yaml` (human-reviewed after L7).
