---
id: fecap-pund
title: Ferroelectric capacitor PUND through the WGFMU — Pr, Ps, Ec; endurance by PUND (Pr versus cycles)
family: nvm
intent: [FeCap, PUND, remanent polarization, Pr, Ps, coercive field, Ec, switching charge, P-V loop, endurance, fatigue, wake-up]
recipes: [fecap.pund, fecap.endurance_pund]
analysis: [pund_polarization, plot_pund]
device_types: [fecap]
modules: [WGFMU]
routes: [rsu:wgfmu]
bringup_stage: L8
recipe_stages: {fecap.endurance_pund: L9}
status: sim_validated
confirmation: always
knowledge: [knowledge/04-ferroelectric-oxide.md#fecap-p-v-and-pund, knowledge/06b-analysis-time-pulse.md#pund, knowledge/04-ferroelectric-oxide.md#ferroelectric-basics-ec-pr-ps, knowledge/10-wgfmu-fast-iv-noise.md#pund-program-read-and-the-pulse_read-wgfmu-path, knowledge/11-switching-routing.md#rsu-of-the-wgfmu]
manual: [WG p125 (4-55) "setMeasureEvent", WG p126 (4-56) "average", WG p80 (4-10) "addSequence", WG p142 (4-72) "6003", WG p16 (1-4) "full scale"]
debug: [wgfmu-range-overflow, wgfmu-library-error, wgfmu-rsu-route, wgfmu-memory-budget, noisy-data, cleanup-failed-fault]
sources: [blueprint v2 3.4 (fecap.pund, fecap.endurance_pund), blueprint v2 2.7.1 (builder pund), blueprint v2 2.10 (pund_polarization), blueprint v2 4.2 (ferro FeCap), blueprint v2 6.3 (fecap-pund)]
version: 1
---

# Ferroelectric capacitor PUND and endurance by PUND

## 1. Purpose and applicable devices

The switching (remanent) polarization Pr, the saturation polarization Ps and the coercive field Ec of a ferroelectric
capacitor (FeCap, e.g. HfZrO between two electrodes) from switching currents, and how Pr changes with cycling.

- `fecap.pund`: a negative preset, then P, U, N, D ramps on the top electrode, the current sampled on the bottom
  electrode (one WGFMU run): Pr = (Q_P - Q_U) / 2A, Ps, Vc and Ec from the switching-current peaks, imprint.
- `fecap.endurance_pund`: bipolar WGFMU cycling with a PUND read at log-spaced cycle counts (a long, asynchronous
  run): Pr per checkpoint, wake-up, fatigue, cycles to failure.
- Not for: the small-signal coercive voltage ([fecap-cv-butterfly](fecap-cv-butterfly.md), MFCMU), a FeFET
  ([fefet-pulse-write-read](fefet-pulse-write-read.md)), leakage (`gate-leakage`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| top | `top` (wgfmu): PUND and cycling pulses | WGFMU 201 via `RSU201.OUT` | Fast IV, no compliance |
| bottom | `bottom` (wgfmu, measure I): the current | WGFMU 202 via `RSU202.OUT` | 0 V: the virtual ground |

- Pin map `fecap-wgfmu`, DUT `fecap-generic` (`geometry.area_um2` for Pr/Ps, `geometry.tox_nm` for Ec; the pulse
  envelope bounds amplitude, width, duty and count). Routes per phase: `waveform`: `RSU201.OUT -> wgfmu`, `RSU202.OUT ->
  wgfmu`; `rest`: both `-> open` (the cleanup's WGFMU safe state disconnects them, verified).

## 3. Pre-run checklist

- `station_status` clean (no fault, no active run). Ask the film thickness, area and expected Ec (DUT profile);
  never invent geometry: without it Pr/Ps/Ec are refused (`q_switch` and Vc still come out).
- Amplitude about 2-3 x Vc within the terminals' pulse `max_abs_v`; a C-V butterfly first shows where Vc is.
- Each PUND cycles the film (~1.5 cycles); a pristine film wakes up: record the device's cycle history.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `builder` | pund | - | pund | the PUND waveform | - |
| `v_max` | 3 V | 2..4 V | 0.1..10 V | PUND amplitude, beyond Vc | too low: Pr under-read |
| `rise` | 10 us | 1..100 us | 100 ns..10 ms | ramp 0 V -> v_max | current ~ dV/dt |
| `plateau` | 0 s | 0..10 us | 0..10 ms | flat top (0 = triangle) | triangle resolves Vc best |
| `delay` | 10 us | 1 us..1 ms | 100 ns..1 s | at 0 V after each pulse | relaxation |
| `interval` | 100 ns | 10 ns..1 us | 10 ns..1 ms | sampling = averaging | 2 rise + plateau = n x interval |
| `preset` | true | - | - | negative preset first | P switches from -Pr |
| `irange` | 1ma | - | 1ua, 10ua, 100ua, 1ma, 10ma | bottom current range | saturates above: status V |
| `cycles` | 10000000 | 100000..1000000000 | 1..1000000000 | total cycles (last read) | time = cycles x cycle_period |
| `cycle_reads` | log | - | log, list | read placement | list: `read_cycles` |
| `reads_per_decade` | 3 | 2..5 | 1..20 | PUND reads per decade | more: longer run |
| `read_cycles` | [1, 10, 100, 1000, 10000, 100000, 1000000] | - | 1..1000000000 | listed reads | integers |
| `cycle_period` | 100 us | 10 us..1 ms | 100 ns..1 s | one bipolar cycle | sets the run time |
| `v_program` | 3 V | 2..4 V | -10..10 V | first cycling pulse | positive polarization |
| `v_erase` | -3 V | -4..-2 V | -10..10 V | second cycling pulse | negative polarization |
| `width` | 10 us | 1..100 us | 10 ns..1 ms | flat time per cycling pulse | duty = width / cycle_period |
| `t_edge` | 1 us | 100 ns..10 us | 10 ns..1 ms | cycling edges | half period > 2 t_edge + width |
| `sequence` | program_erase | - | program_erase, erase_program | cycling polarity order | - |
| `initial_read` | false | - | - | must stay false | the first read is cycle 1 |
| `schedule` | cycles | - | cycles | cycles with PUND reads | - |
| `read_kind` | wgfmu | - | wgfmu | the WGFMU reads | - |
| `wgfmu_read` | pund | - | pund | a PUND at each read | - |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fecap.pund
params: {}
pin_map: fecap-wgfmu
dut_profile: fecap-generic
sim_scenario: fecap_basic
```

## 5. Limits and confirmation

- The guard admits every WGFMU pattern before the first library call (levels within the channel envelope, 10 ns
  grid, vector and value counts); the RSUs connect only on the plan's routes; no compliance: the range bounds the
  reading, not the current, so the DUT envelope must be right.
- Blocked: timing off the 10 ns grid or a pulse that does not fit its period (R-WG-02, R-PULSE-01), no terminal
  `pulse` envelope (R-PULSE-02), above 4,000,000 values per execution, a run longer than 24 h (R-RUN-02).
- Confirm: unverified pin map/topology (always on the example), `dut_envelope` (pulses beyond the profile's count),
  `soft_pulse` (> 10,000 pulses or 60 s on-time), `long_run` (endurance: async above 5 min, confirm above 10 min);
  on hardware `first_hw_run`. Endurance wears the film out: cycle a spare capacitor first.

## 6. Quality criteria

- WGFMU status `N` ok; `V` = the range saturated: the read is refused (every sample enters the integrals); a
  saturated read stops an endurance run (`stop_reason`). P and U (N and D) must differ: no difference = no switching.
- `kind_result` (endurance): `cycles_done`, `burst_cycles_done`, `reads_done` = `reads_planned`, `executions`;
  cancelled rows are PARTIAL; cleanup verified (WGFMU disconnected, session closed, RSUs at rest).

## 7. Analysis method

- `pund_polarization` (default): `pr`, `ps` (uC/cm^2), `ec` (MV/cm), `vc`, `v_imprint` (V), `c_lin` (F), `q_switch`
  (C); several reads add `pr_initial`, `pr_max`, `wake_up`, `fatigue`, `cycles_to_failure`
  ([06b](../../knowledge/06b-analysis-time-pulse.md#pund)). `plot_pund`: currents, P-V, Pr versus cycles.
- Report every one as derived, the method id and the window (forcing-voltage span) next to each value:
  `Pr = 17.0 uC/cm^2 (derived; pund_polarization; window -3..3 V)`, the same for Ps, Ec (and Vc); then the cycle
  count, status counts and the SIMULATED flag. Never call Pr or Ec measured.

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| 10 nm HZO, +-3 V, 10 us ramps | Pr 10-25 uC/cm^2, Ec 1-1.5 MV/cm, imprint < 0.2 V | Pr ~ 0 (paraelectric, dead film, wrong path) |
| endurance | Pr rises 10-20 % (wake-up), falls after 10^5-10^7 cycles | sudden drop with large U current: breakdown |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| `V` samples, read refused | range below the switching current | `irange` vs A Ps dV/dt | `wgfmu-range-overflow` |
| Pr ~ 0, P equals U | no switching: amplitude below Vc, or an RSU off the WGFMU path | `kind_result`, audit RSU states | `wgfmu-rsu-route` |
| large U/D charge, leaky loop | leakage, broken film | `c_lin`, gate-leakage card | `noisy-data` |
| library error, run stopped | WGFMU session or RSU | the error text | `wgfmu-library-error` |
| plan blocked: too many values | interval too fine for the read | points per read | `wgfmu-memory-budget` |
| fault latched | stuck RSU relay, interrupted cleanup | keep the fault; human checks | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-25 | fecap_basic | fecap-generic | S20261125T112520Z-5096 | fecap.pund: needs_confirmation (unverified_pin_map, unverified_topology); Pr 17.01 vs truth 17.01 uC/cm^2 (pristine wake-up scale), Ps 20.75 vs 20.75, Ec 1.006 vs 1.000 MV/cm (+0.6 %), C_lin 66.4 pF; N=800 | - |
| sim | 2026-11-25 | fecap_basic | fecap-generic | S20261125T112520Z-2b80 | fecap.endurance_pund: needs_confirmation (dut_envelope, long_run, soft_pulse, unverified_pin_map, unverified_topology), async ~17 min; 10^7 cycles, 22 PUND reads; Pr 17.03 -> 19.55 (wake-up, 464 cycles) -> 4.81 uC/cm^2 (truth 4.81); cycles to failure 1.10e6; N=17600 | - |
| hw | pending (bring-up stage L8) | - | - | - | - | - |

Sim rows: the example plan and the endurance defaults through `B1500Service` (folders not kept). Hardware records:
`validation/hw/fecap.pund.yaml` (human-reviewed after L8), `validation/hw/fecap.endurance_pund.yaml` (after L9).
