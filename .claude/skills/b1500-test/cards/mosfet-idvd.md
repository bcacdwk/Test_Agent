---
id: mosfet-idvd
title: MOSFET output curves (Id-Vd family over gate steps) — Ron, gds, saturation onset
recipes: [mosfet.idvd]
device_types: [nmos, pmos, igzo_tft]
modules: [2x SMU (HRSMU, MPSMU or HPSMU) + GNDU]
status: sim_validated
confirmation: conditional
knowledge: [knowledge/06-analysis-extraction.md#output-metrics-ron-and-gds, knowledge/01-device-physics.md#mosfet-output-characteristics, knowledge/02-b1500-instrument.md#data-status-codes, knowledge/02-b1500-instrument.md#integration-time-and-ranging]
debug: [compliance-hit, current-too-high, noisy-data, errx-codes, cleanup-failed-fault]
sources: [deck slide 6, deck slide 10, deck slide 15, PG Ed. 15 WV PDF 568-569, PG Ed. 15 WM PDF 552-553]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# MOSFET Id-Vd

## 1. Purpose and applicable devices

The output family of an nMOS, pMOS or oxide TFT: one drain staircase per gate step (host loop over the gate, all in
one transaction). Gives the on-resistance Ron at the lowest |Vd|, the saturation output conductance gds and the
saturation onset Vd_sat per curve.

- Not for: Vth, SS, Ion/Ioff ([mosfet-idvg](mosfet-idvg.md)); breakdown or hot-carrier stress (destructive,
  [reserved](reserved/README.md)); high-current power devices beyond the DUT profile.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| drain | `drain`: sweeps Vd, measures Id | SMU3 (HRSMU; MPSMU/HPSMU allowed) | carries the full output current |
| gate | `gate`: steps Vg, measures Ig | SMU4 (HRSMU; MPSMU/HPSMU allowed) | Ig flags gate damage |
| source | `source`: ground | GNDU | |
| bulk | (no role) | GNDU via the pin map | |

- Example pin map `mosfet-4t` with DUT profile `nmos-generic`; the same landing serves Id-Vg and gate leakage.
- Two-wire connection: Ron includes probe, cable and contact resistance (no Kelvin recipe in v1).
- pMOS: negative `vd_stop` and gate steps with a pMOS DUT profile written by the human.

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md) with `resistor-2t` + `resistor-generic` (SMU3 =
  drain probe). Gate off reads `open` on a healthy transistor; `short` stops the work.
- `station_status` clean (no fault, no lock holder, no errors); pin map and DUT profile listed and supplied by the
  human. Unknown device: ask; never invent a profile.
- Usually after [mosfet-idvg](mosfet-idvg.md): choose gate steps above its Vth so every curve conducts.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `vd_start` | 0 V | - | -10..10 V | Ron is taken at the lowest \|Vd\| | keep 0 V |
| `vd_stop` | 3 V | 1..3 V | -10..10 V | reach saturation | above the profile's drain limit: confirmation |
| `vd_points` | 101 | 51..201 | 11..1001 | 30 mV steps by default | finer: better Ron and Vd_sat |
| `vg_start` | 0.5 V | 0..1 V | -10..10 V | first gate step (above Vth) | below Vth the curve stays near zero |
| `vg_stop` | 1.5 V | 1..3 V | -10..10 V | last gate step | more drive, more current: watch `icomp_drain` |
| `vg_points` | 5 | 3..6 | 1..21 | number of gate steps | each step is one drain sweep |
| `icomp_drain` | 1 mA | 100 uA..10 mA | 1 pA..100 mA | output current limit | above 10 mA or the profile: confirmation |
| `icomp_gate` | 1 uA | - | 1 pA..1 mA | guard against a gate short | a gate short stops the loop |
| `integration` | `medium` | `short`, `medium` | `short`, `medium`, `long` | output currents are large | `long` only for weak drive |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.idvd
params: {}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

## 5. Limits and confirmation

- `soft_limit` (R-LIM-03): `icomp_drain` above 10 mA, the only parameter whose recipe range exceeds the example
  policy's soft limits (10 V, 10 mA; live limits in `station_status`).
- `dut_envelope` (R-DUT-01): |Vd| or |Vg| above the profile's `max_abs_v`, or a compliance above `max_abs_i`
  (`nmos-generic`: 3 V, 1 mA). Example: "Id-Vd up to 3 V with 20 mA compliance" gives both reasons: show the
  summary verbatim, stop, and run only after the human's own consent.
- Self-heating: power Id·Vd stays in the mW range inside the example envelope; larger compliances heat small
  devices (gds turns negative). Hard limits 42 V / 100 mA and the module rating (R-LIM-01) hold regardless.
- On hardware: `unverified_pin_map`, `first_hw_run`. Destructive: no.

## 6. Quality criteria

- Status letters: `N` ok; `C` (this channel) and `T` (other channel at compliance) limited and excluded; `V X F D G
  S U` untrusted: the curve's metrics are refused. Never force silently.
- A drain compliance aborts that curve (its later points read `V`, then no further gate steps: `stopped_early`).
  `output_metrics` refuses a curve with untrusted points and by default reports the strongest one: pick a clean
  curve with `curve` (an existing step level; the refusal lists them) and report the stop, or re-plan with a lower
  `vg_stop` (autonomous, inside the recommended range).
- Shape sanity: curves ordered by gate drive, near 0 A at Vd = 0, monotonic Ron decrease with Vg, small positive gds.
- Re-measure (autonomous, at most two, stays `ok`): `vg_stop`, `vg_points`, `vd_points`, `integration` inside the
  recommended ranges. Raising `icomp_drain` above the profile or 10 mA is a new plan with confirmation.

## 7. Analysis method

- Default `output_metrics` (x `drain_V`, y `drain_I`, curves grouped by `gate_V`; `run_plan` only previews it; report
  the value from your own `analyze_run` call): per curve Ron = 1/gd at the lowest |Vd| (gd from a local quadratic fit
  over `smooth` points); gds = slope of a line over the top `sat_window` (0.2) of the |Vd| span; Vd_sat = first |Vd|
  where gd falls to `sat_ratio` (0.1) x gd(Vd_min).
- The results are those of one curve (`curve`, default the largest |Vg|; its level in `fit.step_v`); every curve's
  value is in `fit` under `gate_V=<level>`. Options: `curve`, `smooth`, `sat_window`, `sat_ratio`.
- Alternatives: `plot_iv` (`scale: linear`) for the family; Vth and gm belong to the Id-Vg card.
- Report: measured family (gate steps, Vd range, status counts, stopped early or not); derived Ron, gds, Vd_sat per
  gate step with method and window; flags for curves that hit compliance
  ([06](../knowledge/06-analysis-extraction.md#output-metrics-ron-and-gds)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| long-channel Si MOSFET | linear rise, then saturation; Vd_sat roughly Vg - Vth; Ron falls with Vg; gds small and positive | curves crossing; negative gds (self-heating) |
| short-channel MOSFET | earlier, softer saturation; larger gds (channel-length modulation, DIBL) | no saturation at all (series R, short) |
| oxide TFT | lower currents, larger Vd_sat; Id may drift during the sweep | hysteresis between curves; heating at high Vd |
| any | Ig ≪ Id; Id ≈ 0 at Vd = 0 | compliance on the top curves; Id offset at Vd = 0; Ig comparable to Id |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| top curves stop with `C`, `stopped_early` | drain current above `icomp_drain` | report the stop; analyse a clean `curve`; next plan with lower `vg_stop` | `compliance-hit` |
| currents far above expectation, no saturation | short, wrong device or pins | contact check; Id-Vg card; ask the human | `current-too-high` |
| curves scattered, Ron unstable | noise, poor contact | `quality_report`; contact check | `noisy-data` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | nmos_basic | nmos-generic | S20261117T174641Z-2537 | tier ok; 5 curves, N=1010; reported curve (Vg 1.5 V) vs analytic model: Ron +0.2 %, gds +7 %, Vd_sat +1 mV | - |
| hw (M4) | pending M4 | - | - | - | - | - |

Sim rows: the example plan (or the named damaged scenario) run through `B1500Service` with temporary
`B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run folders were not kept. Hardware rows need the M4 bring-up.
