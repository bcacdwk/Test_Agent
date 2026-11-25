---
id: gate-leakage
title: Gate leakage (Ig-Vg, drain and source at 0 V) — leakage at the operating bias vs a limit
family: smu
intent: [gate leakage, Ig, oxide, Ig-Vg]
recipes: [mosfet.gate_leakage]
device_types: [nmos, pmos, igzo_tft, fefet]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L4
status: sim_validated
confirmation: conditional
knowledge: [knowledge/05-reliability-defects.md#gate-leakage-and-tddb-safe-envelope, knowledge/06-analysis-extraction.md#leakage-at-bias, knowledge/03-probe-station-wiring.md#guard-for-low-current, knowledge/03-probe-station-wiring.md#asu-and-the-1-pa-range, knowledge/05-reliability-defects.md#oxide-traps-silc-and-charge-trapping]
manual: [PG p568-569 (4-250) "WV", PG p564 (4-246) "WT", PG p552 (4-234) "WM", PG p505 (4-187) "SAP", PG p337 (4-19) "1 pA limited auto"]
debug: [compliance-hit, current-too-high, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint 6.4, deck slide 14]
version: 1
---

# Gate leakage

## 1. Purpose and applicable devices

Is the gate dielectric leaking at the operating bias? A gate staircase from 0 V with drain and source at 0 V gives
Ig(Vg); the leakage at `v_op` is compared with `leak_limit_a` (pass/fail). Non-destructive by construction: small
gate compliance, automatic abort on compliance, gate range inside the DUT profile.

- Applies to MOSFETs, oxide TFTs and FeFETs on the same landing as Id-Vg. On a FeFET a sweep beyond the coercive
  voltage also programs the device: run it after the dual sweep or keep `vg_stop` low.
- Not for: breakdown voltage, TDDB or any stress (destructive, always confirmed:
  [tddb-bdv](../reliability/tddb-bdv.md), [bti-stress-measure](../reliability/bti-stress-measure.md)); C-V; channel
  currents ([mosfet-idvg](mosfet-idvg.md)). This card measures leakage inside the envelope only.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate`: sweeps V, measures Ig | SMU4 (HRSMU required, `low_current`) | Guard connected; ASU for sub-pA work |
| drain | `drain`: held at 0 V, measures Id | SMU3 (HRSMU preferred) | shows a gate-drain path |
| source | `source`: ground | GNDU | |
| bulk | `bulk`: ground (optional) | GNDU | |

- Example pin map `mosfet-4t` (gate SMU4 = HRSMU) with DUT profile `nmos-generic`. A pin map with the gate on an
  MPSMU is blocked (R-PIN-01); ask the human for an HRSMU gate map instead of changing modules in a plan.
- ASU option (`asu_1pa: true`): the gate SMU's ASU (station `switches`, e.g. `ASU4`, `kind: asu`) must be declared
  `present: true` by the human (R-ASU-01 blocks otherwise; the example station says `null`). It stays on its SMU side.
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU or RSU; an ASU path is never switched).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md) with `resistor-2t` + `resistor-generic` (SMU3 =
  drain probe); `open` is the normal transistor reading, `short` stops the work.
- `station_status` clean (no fault, no lock holder, no errors); pin map and DUT profile listed and supplied by the
  human. The gate `max_abs_v` of the profile is the authority for the range; never extend it on your own.
- Choose `v_op` (inside the sweep) and `leak_limit_a` from the human's specification; say when you used defaults.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vg_start` | 0 V | -1..0 V | -10..10 V | sweep from 0 V outwards | a negative start adds a small reverse excursion first |
| `vg_stop` | 3 V | 1..5 V | -10..10 V | highest field last and briefly | capped by the profile's gate `max_abs_v` |
| `vg_points` | 31 | 16..61 | 2..1001 | 100 mV steps by default | more points: longer stress time |
| `icomp_gate` | 100 nA | 1 nA..1 uA | 1 pA..100 uA | limits the current through the oxide | a breakdown stops at this current |
| `hold_s` | 0.5 s | 0.1..2 s | 0..30 s | settle before the first step | shorter: displacement current at the start |
| `delay_s` | 50 ms | 10..500 ms | 0..10 s | settle each step | short delays show C·dV/dt instead of leakage |
| `v_op` | 1.5 V | 0.5..3 V | -10..10 V | operating bias of the judgement (analysis only) | must lie inside the sweep |
| `leak_limit_a` | 1 nA | 1 pA..100 nA | 1 fA..100 uA | pass/fail limit (analysis only) | below the floor it cannot pass meaningfully |
| `integration` | `long` | `long` | `short`, `medium`, `long` | pA currents need 16 PLC | shorter: noisier floor |
| `asu_1pa` | false | - | - | sub-pA gate leakage on an SMU with an ASU | gate read from the 1 pA range up (`RI gate,8`) |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.gate_leakage
params: {}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): |`vg_start`| or |`vg_stop`| above the profile's gate `max_abs_v` (`nmos-generic`: 3 V).
  Example: `vg_stop: 5` needs confirmation. The compliances stay far below every profile and soft limit.
- `soft_limit`: none inside the recipe ranges (≤ 10 V, ≤ 100 uA) with the example policy (10 V, 10 mA; live
  limits in `station_status`). Hard limits 42 V / 100 mA hold anyway.
- On hardware: `unverified_pin_map`, `first_hw_run`. Destructive: no, as long as the gate stays inside the profile
  and `icomp_gate` stays small. After a compliance hit never re-run with more voltage or compliance on your own: a
  suspected breakdown goes to the human.
- `asu_1pa: true` without a declared, present ASU on the gate SMU: blocked (R-ASU-01); never edit the station
  profile, ask the human. A missing ASU on the instrument aborts the run before `XE` (`RI` error).

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited; `V X F D G S U` untrusted (refusal unless forced; never force silently).
  The rows after a compliance abort count as `aborted`, not as data.
- A gate compliance between 0 V and `v_op` is a result, not a refusal: leakage ≥ `icomp_gate` (lower bound), `fail`.
- Ig at the noise floor is the normal result for a good dielectric: an upper bound (3 noise sigma), `pass` when it
  is within the limit. A limit below the floor cannot be judged: say so and ask (longer integration, ASU).
- Displacement current (Ig of alternating sign or a constant offset that scales with step rate): raise `delay_s` or
  `hold_s` inside the recommended range (autonomous, at most two re-measures, stays `ok`).

## 7. Analysis method

- Default `leakage_at` (`run_plan` only previews it; report the value from your own `analyze_run` call): |Ig(v)| at v
  = the plan's `v_op`, linearly interpolated between the bracketing trusted points (x `gate_V`, y `gate_I`), compared
  with the plan's `leak_limit_a`: class `pass`/`fail`, bound `exact`, `upper` (noise floor) or `lower` (compliance
  stop at or below `v_op`).
- Alternatives: another bias or limit `analyze_run(run_id, "leakage_at", {"v": 1.0, "limit_a": 1e-10})`; the
  gate-drain path `{"y": "drain_I"}`; `plot_iv` with `scale: log`; `quality_report` for the floor.
- Report: measured Ig and Id with status counts; derived leakage at `v_op` with bound, limit and class; sweep range,
  compliance, integration; current density only when the human gives the gate area
  ([06](../../knowledge/06-analysis-extraction.md#leakage-at-bias)).

## 8. Expected result shape

| dielectric | typical | red flags |
|---|---|---|
| thick SiO2 or high-k on a small test transistor | Ig at or near the HRSMU floor (sub-pA to pA) at a few volts; smooth rise with \|Vg\| | compliance within the first steps |
| thin oxide (direct tunnelling) | nA range and steep exponential rise | abrupt jump (hard breakdown); noisy staircase rise (soft breakdown) |
| oxide TFT or FeFET stack | pA to nA; switching or displacement spikes on a FeFET gate | Id mirrors Ig (gate-drain path); higher low-bias leakage in a repeat run (damage) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| gate compliance at the first steps, `fail` with a lower bound | gate-drain or gate-source short, damaged oxide, wrong pads | stop; report the bound; ask the human to inspect | `compliance-hit` |
| leakage orders of magnitude above earlier devices | damage, probe touching a neighbour line | contact check; compare with earlier runs (`list_runs`) | `current-too-high` |
| Ig scattered around zero, sign changes | at the floor, displacement current, open guard | `quality_report`; longer delay; ask about Guard | `noisy-data` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | nmos_basic | nmos-generic | S20261117T174642Z-a9b2 | tier ok; leakage at `v_op` +0.1 % vs model truth, `pass`; N=62 | - |
| sim | 2026-11-18 | gd_short (gate-drain short) | nmos-generic | S20261117T174642Z-7e07 | gate compliance at the first step: lower bound = `icomp_gate`, `fail`, as required | - |
| hw | pending (bring-up stage L4) | - | - | - | - | - |

Sim rows: the example plan (or the named damaged scenario) run through `B1500Service` with temporary
`B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run folders were not kept. Hardware record: `validation/hw/mosfet.gate_leakage.yaml`
(reviewed by a human after bring-up stage L4, skill `b1500-bringup`; drafts only from hardware `H...` runs,
never from simulator `S...` runs). Until it exists every hardware plan needs `first_hw_run` confirmation.
