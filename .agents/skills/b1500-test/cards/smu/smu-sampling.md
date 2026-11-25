---
id: smu-sampling
title: SMU sampling — current transients I(t) after a bias step; drift, stretched-exponential tau and beta
family: smu
intent: [sampling, I(t), Id(t), transient, time dependence, bias-stress drift, IGZO, relaxation, tau]
recipes: [mosfet.id_t_sampling, generic.smu_sampling]
device_types: [nmos, pmos, igzo_tft]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L5
status: sim_validated
confirmation: conditional
knowledge: [knowledge/02b-smu-modes.md#sampling-measurement-mm-10, knowledge/06b-analysis-time-pulse.md#sampling-summary-and-relaxation-fit, knowledge/05-reliability-defects.md#igzo-instability-mechanisms, knowledge/02-b1500-instrument.md#data-status-codes]
manual: [PG p474-475 (4-156) "MT", PG p477 (4-159) "MV", PG p472-473 (4-154) "MSC", PG p538 (4-220) "TSC"]
debug: [smu-sampling-skips, vth-drift-igzo, compliance-hit, noisy-data, errx-codes, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 3.1 and 4.2, lwp lib/IVt_sampling.m, PG sampling measurements p112-114]
version: 1
---

# SMU sampling I(t)

## 1. Purpose and applicable devices

How does a current evolve after a bias step? `mosfet.id_t_sampling` holds the drain at `vd`, steps the gate from
`vg_base` to `vg` at the time origin and samples Id every `interval` (the lab's Id(t) script); the IGZO bias-stress
drift appears as a relaxing Id whose stretched exponential gives tau and beta. `generic.smu_sampling` does the same
for any three terminals named `stress` (stepped), `bias` (optional constant) and `ground` (ad-hoc pin map).

- Applies to oxide TFTs, MOSFETs (charge trapping, self-heating settling) and any two/three-terminal device whose
  current drifts under a constant bias.
- Not for: Vth(t) from repeated Id-Vg (stress-measure, BTI), breakdown life (destructive:
  [tddb-bdv](../reliability/tddb-bdv.md)), sub-ms transients (WGFMU), Id-Vg itself ([mosfet-idvg](mosfet-idvg.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: steps `vg_base` → `vg` (MV) | SMU4 (HRSMU; MPSMU/HPSMU allowed) | not measured (the lab measures only Id) |
| drain | `drain`: constant `vd` (DV), measures Id | SMU3 (HRSMU) | sampled channel |
| source | `source`: ground | GNDU (or an SMU at 0 V) | |

- Example pin map `mosfet-4t` with DUT profile `nmos-generic` (gate and drain ≤ 3 V); the lab's own wiring is
  `mosfet-3t-lab` (gate SMU3, drain SMU4, source SMU5; unverified: confirmation). No IGZO DUT profile is committed:
  for an IGZO sample ask the human for pins and limits (never invent them).
- Routes: none in every phase (direct SMU and GNDU wiring).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md); an Id-Vg first ([mosfet-idvg](mosfet-idvg.md))
  so `vg` sits above Vth and `vd` in the intended region.
- Rest the device before a transient (no bias for minutes): the previous run's stress is still relaxing. Keep the
  station dark and note the temperature (IGZO drift depends on both).
- `station_status` clean; pin map and DUT profile supplied by the human.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_base` | 0 V | - | -20..20 V | off state before the step | the step size sets the stress |
| `vg` | 3 V | 1..10 V | -20..20 V | stress gate level (lab) | above the profile: confirmation |
| `vd` | 5 V | 0.05..5 V | -20..20 V | drain read bias (lab 5 V) | 0.05-0.1 V: linear region, Id ∝ Vth shift |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | gate short guard | a gate short aborts the sampling |
| `icomp_drain` | 1 mA | 1 uA..10 mA | 1 pA..10 mA | drain current limit | compliance aborts the run |
| `interval` (`mosfet.id_t_sampling`) | 4 ms | 2 ms..1 s | 2 ms..65.535 s | time resolution (lab 4 ms) | 1 ms steps |
| `interval` (`generic.smu_sampling`) | 10 ms | 2 ms..1 s | 0.1 ms..65.535 s | time resolution | below 2 ms: 10 us steps, linear, one block |
| `points` (`mosfet.id_t_sampling`) | 10001 | 1001..10001 | 11..10001 | samples (lab 10001) | span = (points - 1) x interval |
| `points` (`generic.smu_sampling`) | 1001 | 101..10001 | 1..100001 | samples | the policy caps a run at 10001 |
| `hold_bias` (`mosfet.id_t_sampling`) | 10 ms | - | 0..655.35 s | gate step to the first sample | 10 ms steps |
| `hold_bias` (`generic.smu_sampling`) | 0 s | - | 0..655.35 s | step to the first sample | 10 ms steps |
| `hold_base` (`mosfet.id_t_sampling`) | 0.1 s | - | 0..655.35 s | off state before the step (lab) | counts into the first block |
| `hold_base` (`generic.smu_sampling`) | 0 s | - | 0..655.35 s | base level before the step | counts into the first block |
| `sampling_mode` | `linear` | `linear`, `log25` | `linear`, `log10`, `log25`, `log50`, `log100`, `log250`, `log500` | log for long relaxations | log: one block, at most 1 + 11 x density points |
| `integration` | `medium` | `short`, `medium` | `short`, `medium`, `long` | ADC preset | shortened by the instrument when longer than the interval |
| `base` | 0 V | - | -42..42 V | stepped terminal before the step | |
| `bias` | 1 V | - | -42..42 V | stepped terminal from the step on | |
| `icomp` | 100 uA | - | 1 pA..0.1 A | stepped terminal compliance | compliance aborts the run |
| `bias_v` | 0 V | - | -42..42 V | optional constant terminal | |
| `bias_icomp` | 100 uA | - | 1 pA..0.1 A | its compliance | |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.id_t_sampling
params: {vd: 0.1}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: igzo_transient
```

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): the lab default `vd` 5 V exceeds `nmos-generic` (3 V); the source ground compliance is
  the sum of the gate and drain compliances. Show the summary, stop, run after the human's consent.
- `adhoc_recipe` + `first_hw_run` on hardware for `generic.smu_sampling`; `unverified_pin_map` with `mosfet-3t-lab`.
- Long runs: sampling longer than 60 s runs as 25 s blocks (checkpoints); above `max_sync_run_s` (300 s) the run is
  asynchronous (`running`: poll `get_run` with `include: [progress]`, cancel with `safe_shutdown`), above 600 s it
  needs `long_run` confirmation. Log sampling is one block: keep it within the synchronous limit.
- Every sampling aborts automatically on compliance (any channel), overflow or oscillation (MSC 2); destructive: no.

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited (an aborting sample, excluded); `V X F` untrusted: the summary refuses.
- `kind_result`: `aborted` + `abort_reason` (which channel, when), `index_gaps` (samples skipped: integration longer
  than the interval or auto-range changes; the `t_s` steps show them), `time_source` (`timestamp` normally;
  `index`/`host` = time stamps missing, ATV-22 fallback: say so).
- Shape sanity: a smooth monotonic relaxation after the step; noise below the drift; no step in the middle.
- Re-measure (autonomous, at most two, stays `ok`): `interval`, `points`, `integration`, `sampling_mode`; a larger
  `vg` or `vd` is a new plan (confirmation when outside the profile).

## 7. Analysis method

- Default `sampling_summary` (`mosfet.id_t_sampling`: `y: drain_I`, `fit: stretched_exp`; generic: `y: stress_I`):
  `initial`, `final` (medians of the first/last 10 points), `mean`, `std`, `drift` = (final - initial)/|initial|
  and the relaxation `y = y_inf + (y0 - y_inf) exp(-(t/tau)^beta)` → `tau` (s), `beta`, `y_inf` (fit: `r2`,
  standard errors) over `t_s` (seconds since the gate step). Options: `y`, `fit`, `t_min`, `t_max`, `edge`.
- tau and beta of Id(t) equal those of Vth(t) when Id is linear in Vth (linear region, small `vd`); in saturation
  they are close (a few %). A tau beyond 3x the sampled span is flagged: sample longer or log-spaced.
- `plot_timeseries` (`log_time: true`) for the transient. Report measured Id(t) (points, interval, status counts)
  and the derived tau, beta with the fit window ([06b](../../knowledge/06b-analysis-time-pulse.md#sampling-summary-and-relaxation-fit)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| IGZO TFT, positive gate step | Id decays by % to tens of %; beta 0.3-0.7; tau s to hours | Id rising (negative shift: light, NBIS); sudden steps |
| Si MOSFET | small fast decay (charge trapping), then flat | drift > 10 % (heating, damaged oxide) |
| any | smooth, monotonic, noise ≪ drift | compliance abort; jumps; Id at the noise floor |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| Vth/Id differs every run | IGZO drift, light, humidity, previous stress | rest the device, repeat, compare `initial` | `vth-drift-igzo` |
| `aborted` with `C`/`T` | drain or gate in compliance | report the abort; lower `vg`/`vd` or check the gate | `compliance-hit` |
| scattered Id, tau unstable | noise, short integration at a short interval | `quality_report`; longer `interval`/`integration` | `noisy-data` |
| `index_gaps` > 0, host time | interval shorter than a sample, range changes | `kind_result`, `irange` | `smu-sampling-skips` |
| run `failed`, fault latched; `aborted` after the session ended | instrument error, unverified cleanup; server killed | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault`, `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-19 | igzo_transient | nmos-generic | S20261119T103557Z-e73c | tier ok; N=10001; tau 4.17 s (+4 %), beta 0.513 (+0.013) vs model 4 s, 0.5 | - |
| sim | 2026-11-19 | igzo_transient (lab defaults, `vd` 5 V) | nmos-generic | S20261119T103558Z-5925 | dut_envelope; tau 3.91 s (-2 %), beta 0.501 | - |
| hw | pending (bring-up stage L5) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run
folders were not kept. Hardware records: `validation/hw/mosfet.id_t_sampling.yaml` and
`validation/hw/generic.smu_sampling.yaml` (reviewed by a human after bring-up stage L5, skill `b1500-bringup`;
drafts only from hardware `H...` runs, never from simulator `S...` runs).
