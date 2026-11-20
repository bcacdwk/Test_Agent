---
id: mosfet-idvg
title: MOSFET transfer curve (Id-Vg) — Vth, SS, gm_max, Ion/Ioff; families for DIBL and body effect
family: smu
intent: [Vth, gm, SS, Ion/Ioff, Id-Vg, transfer curve, DIBL, body effect, Vth vs Vd, saturation Vth]
recipes: [mosfet.idvg, mosfet.idvg_family, mosfet.idvg_sync, mosfet.body_effect]
device_types: [nmos, pmos, igzo_tft]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L4
status: sim_validated
confirmation: conditional
knowledge: [knowledge/06-analysis-extraction.md#vth-linear-extrapolation, knowledge/06-analysis-extraction.md#vth-constant-current, knowledge/06-analysis-extraction.md#vth-at-maximum-gm, knowledge/06-analysis-extraction.md#subthreshold-swing, knowledge/06-analysis-extraction.md#on-and-off-current, knowledge/06-analysis-extraction.md#dibl-and-body-effect, knowledge/06-analysis-extraction.md#quality-gate-and-noise, knowledge/01-device-physics.md#mosfet-threshold-voltage-definitions, knowledge/04-ferroelectric-oxide.md#igzo-and-oxide-tft-specifics]
manual: [PG p568-569 (4-250) "WV", PG p552 (4-234) "WM", PG p562 (4-244) "WSV"]
debug: [noisy-data, compliance-hit, current-too-high, vth-drift-igzo, errx-codes, cleanup-failed-fault]
sources: [deck slide 6, deck slide 9, deck slide 15, blueprint v2 3.1]
version: 1
---

# MOSFET Id-Vg

## 1. Purpose and applicable devices

Threshold voltage, subthreshold swing, peak transconductance and Ion/Ioff of an enhancement MOSFET or oxide TFT
(IGZO) in the linear region: `mosfet.idvg`, gate staircase at a small constant drain bias (deck slide 6 default: Vg
-1 → 3 V, Vd 50 mV). This is the card for "measure the Vth". Variants on the same landing: `mosfet.idvg_family`
(Id-Vg per drain bias → DIBL in mV/V, Vth(Vd)); `mosfet.idvg_sync` (the drain steps with the gate, `WSV`; default
Vd 0.2 → 1.2 V → saturation Vth, SS); `mosfet.body_effect` (Id-Vg per body bias, bulk on an SMU → dVth/dVsb).

- Not for: output curves, Ron, gds ([mosfet-idvd](mosfet-idvd.md)); gate oxide leakage ([gate-leakage](gate-leakage.md));
  hysteresis or memory window ([fefet-dual-sweep-mw](../nvm/fefet-dual-sweep-mw.md)); pulsed Id-Vg, BTI (other cards).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: sweeps V, measures Ig | SMU4 (HRSMU; MPSMU/HPSMU allowed) | Ig shows gate leakage or shorts |
| drain | `drain`: bias, step (family) or synchronous sweep (sync) Vd; measures Id | SMU3 (HRSMU preferred) | low-current Ioff and SS need the HRSMU |
| source | `source`: ground | GNDU | |
| bulk | `bulk` (`mosfet.body_effect` only): steps Vbs, measures Ib | SMU5 (MPSMU) in `mosfet-4t-body` | GNDU in `mosfet-4t` |

- Example pin maps `mosfet-4t` (gate SMU4, drain SMU3, source and bulk GNDU) and `mosfet-4t-body` (same, bulk on
  SMU5), DUT profile `nmos-generic`. IGZO/oxide TFT: three terminals, no body (no `mosfet.body_effect`). pMOS: sweep
  from off to on (`vg_start: 1`, `vg_stop: -3`, `vd: -0.05`), positive body biases, a pMOS profile from the human.
- Lab Id-Vg script wiring: `mosfet-3t-lab` (gate SMU3, drain SMU4, source SMU5; scenario `lab_nmos_2025`); the
  kernel differs on purpose (no `*RST`, 1 mA drain compliance, status letters kept): [02](../../knowledge/02-b1500-instrument.md#lab-scripts-vs-the-kernel).
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU, ASU or RSU in the path).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md) with `resistor-2t` + `resistor-generic` (SMU3 =
  drain probe): gate off reads `open` (expected, go on); `short` or a low R: stop and report.
- `station_status` clean; pin map and DUT profile listed: they come from the human (`mosfet-4t`, `nmos-generic` are
  examples). Unknown device or pins (a bulk on an SMU too): stop and ask; limits come from the profile, not memory.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_start` (`mosfet.idvg`) | -1 V | -2..0 V | -10..10 V | start below Vth: off state, Ioff | lower start: more subthreshold decades for SS |
| `vg_stop` (`mosfet.idvg`) | 3 V | 1..5 V | -10..10 V | end in strong inversion so the gm peak lies inside | capped by the profile's gate `max_abs_v` |
| `vg_points` (`mosfet.idvg`) | 101 | 101..401 | 11..1001 | 40 mV steps by default | denser: better SS; noisier gm (raise `smooth`) |
| `vd` | 50 mV | 20..100 mV | -5..5 V | linear region (Vd ≪ Vg - Vth) | `mosfet.idvg`: Vth corrected by Vd/2 |
| `delay_s` (`mosfet.idvg`) | 0 s | 0..50 ms | 0..10 s | settling per step (lab script: 10 ms) | slower; `hold_s` (0 s) waits before the first step |
| `vg_start` (`mosfet.idvg_family`, `mosfet.idvg_sync`, `mosfet.body_effect`) | 0 V | -1..0 V | -10..10 V | subthreshold points below the 100 nA criterion | sync: the drain starts here too |
| `vg_stop` (`mosfet.idvg_family`, `mosfet.idvg_sync`, `mosfet.body_effect`) | 1.2 V | 1..3 V | -10..10 V | above threshold, Id below 1 mA at the top Vd | compliance stops the loop |
| `vg_points` (`mosfet.idvg_family`, `mosfet.idvg_sync`, `mosfet.body_effect`) | 121 | 61..301 | 11..1001 | 10 mV steps | finer Vth interpolation |
| `vd_values` (`mosfet.idvg_family`) | [0.1, 0.55, 1] V | - | -5..5 V | lowest = linear curve, highest = saturation | Vd < 0.1 V adds drain-factor error |
| `vd_start` (`mosfet.idvg_sync`) | 0.2 V | 0.1..0.5 V | -5..5 V | with `vd_stop` 1.2 V: Vd ≥ Vg (saturation) | 0 V: drain factor steepens the apparent SS |
| `vbs_values` (`mosfet.body_effect`) | [0, -0.25, -0.5, -0.75, -1] V | - | -5..5 V | reverse body bias only | beyond the bulk `max_abs_v`: confirmation |
| `icomp_bulk` (`mosfet.body_effect`) | 100 uA | 1 uA..1 mA | 1 pA..1 mA | a forward junction stops the loop | |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | guard against a gate short | a gate short stops the sweep |
| `icomp_drain` | 1 mA | 100 uA..10 mA | 1 pA..10 mA | room for Ion | above the profile's `max_abs_i`: confirmation |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | noise vs time | `long` for a clean subthreshold region |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.idvg
params: {}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

Variants (tier `ok` on scenario `nmos_basic`): `uv run b1500 plan mosfet.idvg_family --pin-map mosfet-4t --dut
nmos-generic`; `uv run b1500 plan mosfet.idvg_sync --pin-map mosfet-4t --dut nmos-generic`; `uv run b1500 plan
mosfet.body_effect --pin-map mosfet-4t-body --dut nmos-generic`.

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): a level above the profile's `max_abs_v` or a compliance above its `max_abs_i`
  (`nmos-generic`: gate and drain 3 V, 1 mA; bulk 1 V). Example: `vg_stop: 4` or a Vbs of -1.5 V needs confirmation.
- `soft_limit` (R-LIM-03): none inside the recipe ranges (example policy 10 V, 10 mA); hard limits never reached. On
  hardware: `unverified_pin_map`, `first_hw_run` (until `hw_validated`). Destructive: no.

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited, excluded from derivatives and fits (> 5 % in the fit window: warning);
  `V X F D G S U` untrusted: every Vth method refuses. Never force silently.
- Noise gate: `drain_I` noise-dominated means **no Vth**, even when all points carry `N`. Do not force or raise bias:
  skill `b1500-debug` (`noisy-data`), contact check on the drain pair, ask the human to re-land the drain probe.
- Shape sanity: Id rises over decades, the |gm| maximum lies inside the sweep (else extend `vg_stop` within the
  profile), fit r2 ≥ 0.99. Families: a curve in compliance stops the loop (fewer curves, `stopped_early`).
- Re-measure (at most two): `integration: long`, points, ends inside the ranges; never beyond the profile yourself.

## 7. Analysis method

- Defaults (`run_plan` only previews them: report your own `analyze_run`): `mosfet.idvg` `vth_linear_extrapolation`
  `{window: max_gm, subtract_half_vd: true}` (line through the 5 trusted points around max |gm|; Vth = intercept -
  Vd/2); `mosfet.idvg_family` `dibl` (mV/V between the lowest- and highest-Vd curves, `vth_lin`, `vth_sat`);
  `mosfet.body_effect` `body_effect` (dVth/dVsb in V/V, `vth_vsb0`); `mosfet.idvg_sync` `vth_constant_current`,
  `subthreshold_swing`. Families use the constant-current Vth (`i_crit_a` 100 nA, x `w_over_l` when given).
- Alternatives: `vth_constant_current` (usual for TFTs); `vth_max_gm`; `subthreshold_swing` (`fit_points` or
  `decades`); `gm_max`; `ion_ioff` (`v_on`, `v_off`); `plot_iv`; options `fit_points`, `smooth`, `window: [lo, hi]`.
- Never mix Vth methods in one comparison. Report measured Id, Ig, status counts; derived values with method, window,
  points and criterion ([06](../../knowledge/06-analysis-extraction.md#reporting-rules-measured-versus-derived)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| Si nMOS | Vth 0.2-1 V; SS 65-90 mV/dec (never below about 60); Ion/Ioff 1e5-1e9 (Ioff at the floor: lower bound) | SS < 60 mV/dec at 300 K; gm peak at a sweep end |
| short / long channel | DIBL tens of mV/V (short), about 0-5 mV/V (long); body coefficient about 0.1-0.5 V/V | negative DIBL; body coefficient ≤ 0 |
| pMOS | mirror image: negative Vth, sweep towards negative Vg | positive Vth on a pMOS (wrong polarity or pins) |
| IGZO / oxide TFT | Vth negative to a few volts; SS 100-300 mV/dec; Ioff pA or below; history-dependent | Vth drifting run to run (`vth-drift-igzo`) |
| any | Ig ≪ Id; Ib at the floor (body effect) | Id at the floor everywhere (open drain); compliance from the first step (short); Ib rising (forward junction) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| Vth refused: `drain_I` noise-dominated | drain probe not landed, station noise | no Vth; contact check on the drain pair; ask for re-landing | `noisy-data` |
| gate, drain or bulk compliance early | gate-drain short, damaged oxide, forward junction, wrong pins | stop; gate-leakage card inside the envelope; ask the human | `compliance-hit` |
| currents orders of magnitude above expectation | wrong device, parallel path, short | contact check; compare pin map and wiring with the human | `current-too-high` |
| Vth differs between repeated runs (oxide TFT) | trapping, bias stress, light, humidity | repeat with identical plan; note dwell times | `vth-drift-igzo` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | nmos_basic | nmos-generic | S20261117T174641Z-82e7 | `mosfet.idvg` tier ok; Vth +10.6 mV vs truth (default method); SS +0.5 %; N=202 | - |
| sim | 2026-11-18 | open_drain_noisy (drain lifted) | nmos-generic | S20261117T174642Z-7df2 | Vth refused (`drain_I` noise-dominated), as required | - |
| sim | 2026-11-19 | nmos_basic | nmos-generic | S20261119T111103Z-1777 | `mosfet.idvg_family`: DIBL 2.8 mV/V (truth 0; drain factor + CLM); a copy with 60 mV/V: 62.7 (S20261119T111106Z-2959) | - |
| sim | 2026-11-19 | nmos_basic | nmos-generic | S20261119T111103Z-899f | `mosfet.idvg_sync`: SS 77.3 mV/dec (-0.2 % vs n·U_T·ln10); `mosfet.body_effect` (S20261119T111104Z-31fa): 0.300 V/V (truth 0.3) | - |
| hw | pending (bring-up stage L4) | - | - | - | - | - |

Hardware records (stage L4, `H...` runs only; until then `first_hw_run`): `validation/hw/mosfet.idvg.yaml`,
`validation/hw/mosfet.idvg_family.yaml`, `validation/hw/mosfet.idvg_sync.yaml`, `validation/hw/mosfet.body_effect.yaml`.
