---
id: fefet-dual-sweep-mw
title: FeFET dual gate sweep (Id-Vg double sweep) — Vth_fwd, Vth_rev, memory window, per-branch Ion/Ioff
family: nvm
intent: [FeFET, memory window, hysteresis, dual sweep, Vth_fwd/Vth_rev]
recipes: [fefet.dual_sweep_mw]
device_types: [fefet]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L7
status: sim_validated
confirmation: conditional
knowledge: [knowledge/04-ferroelectric-oxide.md#fefet-memory-window-by-dual-sweep, knowledge/04-ferroelectric-oxide.md#read-disturb-and-sweep-rate-effects, knowledge/06-analysis-extraction.md#memory-window, knowledge/06-analysis-extraction.md#vth-constant-current, knowledge/05-reliability-defects.md#ferroelectric-wake-up-imprint-and-fatigue]
manual: [PG p568-569 (4-250) "WV", PG p552 (4-234) "WM"]
debug: [noisy-data, compliance-hit, vth-drift-igzo, current-too-high, errx-codes, cleanup-failed-fault]
sources: [blueprint 6.4, deck slide 13, deck slide 15]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# FeFET dual sweep and memory window

## 1. Purpose and applicable devices

The memory window of a ferroelectric FET: one gate double sweep `vg_start` → `vg_stop` → `vg_start` at a small
drain bias; the threshold voltage of the forward branch (`fwd`) and of the reverse branch (`rev`) with one method,
MW = Vth_fwd - Vth_rev, and Ion/Ioff per branch. This is the card for "memory window of this FeFET".

- The sweep itself programs and erases the ferroelectric: the device keeps the state the last branch left. That is
  the measurement, not a fault; record it.
- Not for: the memory window from program/erase pulses ([fefet-pulse-write-read](fefet-pulse-write-read.md));
  endurance and retention ([fefet-endurance-retention](fefet-endurance-retention.md)), PUND
  ([fecap-pund](fecap-pund.md)) or fast WGFMU sweeps ([wgfmu-pulsed-iv](../wgfmu/wgfmu-pulsed-iv.md)); never emulate
  pulses with repeated sweeps. Plain transistor Vth: [mosfet-idvg](../smu/mosfet-idvg.md).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: double sweep, measures Ig | SMU4 (HRSMU; MPSMU/HPSMU allowed) | switching and displacement currents flow here |
| drain | `drain`: bias Vd, measures Id | SMU3 (HRSMU preferred) | low Ioff on both branches |
| source | `source`: ground | GNDU | |
| bulk | `bulk`: ground (optional) | GNDU | |

- Example pin map `mosfet-4t` with DUT profile `fefet-generic` (gate 5 V, drain 1 V, 1 mA).
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU, ASU or RSU in the path).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](../smu/contact-resistor-check.md) with `resistor-2t` + `resistor-generic` (SMU3 =
  drain probe); `open` is the normal reading with the gate off, `short` stops the work.
- `station_status` clean (no fault, no lock holder, no errors). Pin map and a FeFET DUT profile from the human;
  unknown film thickness or coercive voltage: ask before choosing the amplitude; never invent a profile.
- Note the device history (fresh, after earlier loops, after a pause): the first loop can differ (wake-up).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_start` | -4 V | -5..-3 V | -10..10 V | beyond the negative coercive voltage: erase first | smaller \|V\|: minor loop, smaller MW |
| `vg_stop` | 4 V | 3..5 V | -10..10 V | beyond the positive coercive voltage: full program | capped by the profile's gate `max_abs_v` |
| `vg_points` | 161 | 81..321 | 11..1001 | points per branch (2x steps in total), 50 mV steps | sets the sweep rate together with `integration` |
| `vd` | 50 mV | 20..100 mV | -1..1 V | small read bias, linear region | larger: read disturb, lateral field |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | limits gate current through the stack | switching spikes stay far below |
| `icomp_drain` | 1 mA | - | 1 pA..10 mA | room for Ion | above the profile's `max_abs_i`: confirmation |
| `integration` | `medium` | `medium` | `short`, `medium`, `long` | keep fixed when comparing devices | changes the sweep rate, hence the MW |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: fefet.dual_sweep_mw
params: {}
pin_map: mosfet-4t
dut_profile: fefet-generic
sim_scenario: fefet_basic
```

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): |`vg_start`| or |`vg_stop`| above the profile's gate `max_abs_v` (`fefet-generic`:
  5 V; example `-6..6 V` needs confirmation), or `icomp_drain` above its `max_abs_i` (1 mA). `vd` stays within ±1 V.
- `soft_limit`: none inside the recipe ranges with the example policy (10 V, 10 mA; `station_status` shows the
  live limits). Hard limits 42 V / 100 mA and module ratings hold anyway.
- On hardware: `unverified_pin_map`, `first_hw_run`. Destructive: no (recipe not `always_confirm`), but every run
  rewrites the polarization; repeated full loops add fatigue: keep the run count per device purposeful.

## 6. Quality criteria

- Status letters per branch: `N` ok; `C`/`T` limited, excluded; `V X F D G S U` untrusted: that branch's Vth is
  refused and with it the MW. Never force silently.
- Noise gate per branch: a noise-dominated `drain_I` gives no Vth (contact check, skill `b1500-debug`). Each branch
  must cross the criterion current: `failed` "no crossing" means the window lies outside the sweep or the drain is
  not conducting; extend the sweep only within the recommended range and the profile.
- Sign: MW > 0 for an n-channel FeFET swept upwards first; MW < 0 gets a warning (trapping dominates, polarity or
  direction). Report the sign, never only the magnitude.
- Re-measure (autonomous, at most two, stays `ok`): one identical repeat to check loop reproducibility (wake-up);
  `vg_points` inside the recommended range. Compare MW only between runs with identical sweep settings.

## 7. Analysis method

- Default `memory_window` with `{vth_method: vth_constant_current, i_crit_a: 1e-7}` (`run_plan` only previews it;
  report the value from your own `analyze_run` call): Vth of `fwd` (first branch, start → stop) and `rev` (stop →
  start) by the same method; MW = Vth_fwd - Vth_rev; per-branch Ion/Ioff from `ion_ioff` (default the sweep ends;
  ratio in the Ion result's `fit`).
- Options: `vth_method` `vth_linear_extrapolation` or `vth_max_gm` (method offsets cancel in MW; branch Vths do not),
  `i_crit_a`, `w_over_l`, `v_on`, `v_off`, `smooth`. Single-branch extractions: the Id-Vg methods with `segment: rev`.
- Report: MW with sign and method; **both** branch Vths (`vth_fwd`, `vth_rev`) with method and criterion, each
  on its own line as `Vth_fwd = <x> V` and `Vth_rev = <y> V` (a table alone hides which value is which);
  Ion/Ioff per branch; amplitude, points, integration, start state and loop index; status counts
  ([06](../../knowledge/06-analysis-extraction.md#memory-window)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| hafnia (HZO) FeFET, ±3-5 V loop | MW positive, a fraction of a volt up to about 2 V (at most about 2·Ec·t_FE); Vth_fwd > Vth_rev; similar Ion on both branches | MW ≈ 0 (amplitude below the coercive voltage, or no ferroelectric switching) |
| trapping-dominated stack | MW negative (clockwise) | MW changing sign between identical runs |
| any | Ioff near the floor on both branches; gate current spikes at switching | gate compliance; MW drifting run to run (wake-up, fatigue, read disturb) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| a branch Vth refused, drain current noise-dominated | drain probe not landed | contact check; ask for re-landing | `noisy-data` |
| gate or drain compliance during the loop | damaged stack, short, wrong pins | stop; report; gate-leakage card inside the envelope | `compliance-hit` |
| MW or branch Vths differ between identical runs | wake-up, imprint, trapping, read disturb | identical repeat; record loop index and pauses | `vth-drift-igzo` |
| currents far above expectation | short, wrong device | contact check; compare pin map and wiring | `current-too-high` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | fefet_basic | fefet-generic | S20261117T174642Z-df3b | tier ok; MW +0.01 % vs model loop truth, both branch Vths reported; with linear extrapolation branch Vths within 2 mV of the loop; N=644 | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim rows: the example plan (or the named damaged scenario) run through `B1500Service` with temporary
`B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run folders were not kept. Hardware record: `validation/hw/fefet.dual_sweep_mw.yaml`
(reviewed by a human after bring-up stage L7, skill `b1500-bringup`; drafts only from hardware `H...` runs,
never from simulator `S...` runs). Until it exists every hardware plan needs `first_hw_run` confirmation.
