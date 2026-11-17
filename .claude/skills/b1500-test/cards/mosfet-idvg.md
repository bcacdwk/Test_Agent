---
id: mosfet-idvg
title: MOSFET transfer curve (Id-Vg, linear region) — Vth, SS, gm_max, Ion/Ioff
recipes: [mosfet.idvg]
device_types: [nmos, pmos, igzo_tft]
modules: [2x SMU (HRSMU on drain preferred) + GNDU]
status: sim_validated
confirmation: conditional
knowledge: [knowledge/06-analysis-extraction.md#vth-linear-extrapolation, knowledge/06-analysis-extraction.md#vth-constant-current, knowledge/06-analysis-extraction.md#vth-at-maximum-gm, knowledge/06-analysis-extraction.md#subthreshold-swing, knowledge/06-analysis-extraction.md#on-and-off-current, knowledge/06-analysis-extraction.md#quality-gate-and-noise, knowledge/01-device-physics.md#mosfet-threshold-voltage-definitions, knowledge/04-ferroelectric-oxide.md#igzo-and-oxide-tft-specifics]
debug: [noisy-data, compliance-hit, current-too-high, vth-drift-igzo, errx-codes, cleanup-failed-fault]
sources: [deck slide 6, deck slide 9, deck slide 15, PG Ed. 15 WV PDF 568-569, PG Ed. 15 WM PDF 552-553]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# MOSFET Id-Vg

## 1. Purpose and applicable devices

Threshold voltage, subthreshold swing, peak transconductance and Ion/Ioff of an enhancement MOSFET or oxide TFT
(IGZO) in the linear region: gate staircase at a small constant drain bias (deck slide 6 default: Vg -1 → 3 V,
Vd 50 mV). This is the card for "measure the Vth".

- Not for: output curves, Ron, gds ([mosfet-idvd](mosfet-idvd.md)); gate oxide leakage
  ([gate-leakage](gate-leakage.md)); hysteresis or memory window ([fefet-dual-sweep-mw](fefet-dual-sweep-mw.md));
  fast pulsed Id-Vg, BTI ([reserved](reserved/README.md)). A saturation-region Vth needs a large Vd: ask the human.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: sweeps V, measures Ig | SMU4 (HRSMU; MPSMU/HPSMU allowed) | Ig shows gate leakage or shorts |
| drain | `drain`: bias Vd, measures Id | SMU3 (HRSMU preferred) | low-current Ioff and SS need the HRSMU |
| source | `source`: ground | GNDU | |
| bulk | (no role) | GNDU via the pin map | body bias needs another pin map and the human |

- Example pin map `mosfet-4t` (gate SMU4, drain SMU3, source and bulk GNDU) with DUT profile `nmos-generic`.
- IGZO/oxide TFT: three terminals, no body; the human's pin map leaves bulk unconnected.
- pMOS: same wiring, sweep from off to on (for example `vg_start: 1`, `vg_stop: -3`, `vd: -0.05`) with a pMOS DUT
  profile written by the human (none is committed).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md) with `resistor-2t` + `resistor-generic` (SMU3 =
  drain probe against source/bulk). With the gate off a healthy transistor reads `open`: expected, go on. `short`
  or a low R: stop and report. The landing itself is proven by this Id-Vg (Id rising by decades with Vg).
- `station_status` clean: no fault, no lock holder, no pending errors; pin map and DUT profile listed.
- Pin map and DUT profile come from the human (`mosfet-4t`, `nmos-generic` are examples). Unknown device or pins:
  stop and ask; never invent a profile or guess pins. Gate limits come from the profile, not from memory.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_start` | -1 V | -2..0 V | -10..10 V | start below Vth: off state, Ioff | lower start: more subthreshold decades for SS |
| `vg_stop` | 3 V | 1..5 V | -10..10 V | end in strong inversion so the gm peak lies inside | capped by the profile's gate `max_abs_v` |
| `vg_points` | 101 | 101..401 | 11..1001 | 40 mV steps by default | denser: better SS; noisier gm (raise `smooth`) |
| `vd` | 50 mV | 20..100 mV | -5..5 V | linear region (Vd ≪ Vg - Vth) | Vth is corrected by Vd/2 |
| `icomp_gate` | 1 uA | 100 nA..1 uA | 1 pA..1 mA | guard against a gate short | a gate short stops the sweep |
| `icomp_drain` | 1 mA | 100 uA..1 mA | 1 pA..10 mA | room for Ion | above the profile's `max_abs_i`: confirmation |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | noise vs time | `long` for a clean subthreshold region |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.idvg
params: {}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): |`vg_start`|, |`vg_stop`| or |`vd`| above the profile's `max_abs_v`, or a compliance
  above its `max_abs_i` (`nmos-generic`: gate and drain 3 V, 1 mA). Example: `vg_stop: 4` needs confirmation.
- `soft_limit` (R-LIM-03): none, the recipe ranges end at the example policy's soft limits (10 V, 10 mA). Hard limits
  42 V / 100 mA and module ratings (R-LIM-01) are never reached.
- On hardware: `unverified_pin_map`, `first_hw_run` (until `hw_validated`). Destructive: no.

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited, excluded from derivatives and fits (> 5 % in the fit window: warning);
  `V X F D G S U` untrusted: every Vth method refuses. Never force silently.
- Noise gate: `drain_I` noise-dominated (signal range < 10x noise, refusal "noise-dominated") means **no Vth**,
  even when all points carry `N`. Do not force, do not raise bias. Load skill `b1500-debug` (runbook `noisy-data`),
  run [contact-resistor-check](contact-resistor-check.md) on the drain pair, and ask the human to re-land the drain
  probe: an Id at the floor over the whole gate sweep means the drain path is not connected.
- Shape sanity: Id rises over several decades and then roughly linearly; the |gm| maximum lies inside the sweep
  (warning "at a sweep end": extend `vg_stop` within the profile); fit r2 ≥ 0.99; Vth inside the sweep.
- Re-measure (autonomous, at most two, stays `ok`): `integration: long`, `vg_points`, `vg_start`/`vg_stop` and `vd`
  inside the recommended ranges and the profile. Never raise a compliance or |V| beyond the profile on your own.

## 7. Analysis method

- Default `vth_linear_extrapolation` with `{window: max_gm, subtract_half_vd: true}` (`run_plan` only previews it;
  report the value from your own `analyze_run` call): line through the `fit_points` (5) trusted points around max
  |gm|; Vth = Vg-axis intercept - Vd/2, Vd from the plan's `vd`. Options: `fit_points`, `smooth` (5; raise for dense
  or noisy sweeps), `window: [lo, hi]` in volts.
- Alternatives (`analyze_run`): `vth_constant_current` (`i_crit_a` 100 nA, x `w_over_l` when given; the usual
  definition for TFTs); `vth_max_gm` (maximum of dgm/dVg, minus Vd/2); `subthreshold_swing` (minimum mV/dec over
  `fit_points` or `decades`); `gm_max`; `ion_ioff` (`v_on`, `v_off`; default the sweep ends); `plot_iv`.
- Vth values of different methods differ by definition: never mix them in one comparison.
- Report: measured Id, Ig, status counts; derived Vth with method, window and points (for example "Vth = x V,
  linear extrapolation at max gm, Vd/2 corrected, window a..b V, 5 points"), SS, gm_max, Ion/Ioff with bias points
  and bounds ([06](../knowledge/06-analysis-extraction.md#reporting-rules-measured-versus-derived)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| Si nMOS test transistor | Vth about 0.2-1 V; SS 65-90 mV/dec at room temperature (never below about 60); Ion/Ioff 1e5-1e9, Ioff often at the floor (ratio then a lower bound) | SS < 60 mV/dec at 300 K (noise or wrong window); gm peak at a sweep end |
| pMOS | mirror image: negative Vth, sweep towards negative Vg | positive Vth on a pMOS (wrong polarity or pins) |
| IGZO / oxide TFT | Vth negative to a few volts; SS 100-300 mV/dec; Ioff at pA or below; history-dependent | Vth drifting run to run (see `vth-drift-igzo`) |
| any | Ig ≪ Id in the on state | Id at the floor everywhere (open drain); Id at compliance from the first step (short); Ig comparable to Id |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| Vth refused: `drain_I` noise-dominated | drain probe not landed, station noise | no Vth; contact check on the drain pair; ask for re-landing | `noisy-data` |
| gate or drain compliance early in the sweep | gate-drain short, damaged oxide, wrong pins | stop; gate-leakage card inside the envelope; ask the human | `compliance-hit` |
| currents orders of magnitude above expectation | wrong device, parallel path, short | contact check; compare pin map and wiring with the human | `current-too-high` |
| Vth differs between repeated runs (oxide TFT) | trapping, bias stress, light, humidity | repeat with identical plan; note dwell times | `vth-drift-igzo` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | nmos_basic | nmos-generic | S20261117T174641Z-82e7 | tier ok; Vth +10.6 mV vs model truth (default method, 5 points); SS +0.5 %; N=202, quality ok | - |
| sim | 2026-11-18 | open_drain_noisy (drain lifted) | nmos-generic | S20261117T174642Z-7df2 | Vth refused (`drain_I` noise-dominated): no value, as required | - |
| hw (M4) | pending M4 | - | - | - | - | - |

Sim rows: the example plan (or the named damaged scenario) run through `B1500Service` with temporary
`B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run folders were not kept. Hardware rows need the M4 bring-up.
