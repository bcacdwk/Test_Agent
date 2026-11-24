---
id: compact-model-spice
title: Compact model — EKV or level-1 fit of Id-Vg/Id-Vd runs, model vs run comparison, SPICE model card and netlist (analysis only)
family: smu
intent: [compact model, SPICE, HSPICE, ngspice, model card, netlist, EKV, level 1, model fit, simulation comparison]
recipes: []
analysis: [compact_model_fit, model_compare, export_spice_netlist]
device_types: [nmos, pmos, igzo_tft]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L4
status: sim_validated
confirmation: never
knowledge: [knowledge/07-compact-models.md#workflow, knowledge/07-compact-models.md#ekv-model, knowledge/07-compact-models.md#level-1-model, knowledge/07-compact-models.md#spice-export, knowledge/07-compact-models.md#reading-the-results, knowledge/06-analysis-extraction.md#reporting-rules-measured-versus-derived]
manual: [PG p568-569 (4-250) "WV"]
debug: [noisy-data, compliance-hit, current-too-high]
sources: [blueprint v2 0 row 26, 2.10 model.py, 12 OD-6, deck slide 16 (domain 7)]
version: 1
---

# Compact model and SPICE export

## 1. Purpose and applicable devices

Which compact model describes this transistor, how well does it reproduce another measurement, and what SPICE files
carry it? Analysis only: the card adds no measurement. It runs three `analyze_run` methods on finished Id-Vg/Id-Vd
runs: `compact_model_fit` (EKV: vth, n, beta, theta, lambda, rs; level 1: vto, beta, lambda),
`model_compare` (model vs a run: RMS errors) and `export_spice_netlist` (`.lib` + `.sp` under the run's
`analysis/`). Running the simulator is the human's step (OD-6); never claim a simulation ran.

- Data from `mosfet.idvg`, `mosfet.idvg_family`, `mosfet.body_effect` ([mosfet-idvg](mosfet-idvg.md)),
  `mosfet.idvd` ([mosfet-idvd](mosfet-idvd.md)) and the pulsed Id-Vg/Id-Vd ([smu-pulsed-iv](smu-pulsed-iv.md));
  `mosfet.idvg_sync` fits but cannot be exported (synchronous sweep).
- Not for: Vth, SS, gm by their standard definitions (the extractors of [mosfet-idvg](mosfet-idvg.md)), DIBL or
  body effect (measured directly), FeFET hysteresis (fit one branch only, say so), BSIM4 or Verilog-A (not in v2).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` of the measuring recipe | SMU4 (HRSMU) | its `gate_V` column is the gate voltage |
| drain | `drain` of the measuring recipe | SMU3 (HRSMU) | `drain_V`, `drain_I` (the fitted current) |
| source / bulk | `source` (GNDU) / `bulk` (SMU5 for body effect) | GNDU, MPSMU | a missing column = GNDU 0 V / bulk at the source |

- No instrument action: the measuring recipe's card owns wiring, pin map (`mosfet-4t`) and DUT profile.
- Routes: none in every phase (analysis only).

## 3. Pre-run checklist

- A completed run with quality `ok` (`get_run`); limited `C`/`T` rows are left out, untrusted rows refuse.
- For EKV subthreshold parameters: an Id-Vg that spans the noise floor to strong inversion (at least five points
  below threshold above the floor). For `lambda` and `rs`: drain variation (Id-Vd or a family, `fit_rs: true`).
- Geometry (`w_um`, `l_um`) from the DUT profile or the human for a level-1 `KP`; never guess it.

## 4. Recipe and parameters

The table lists the analysis options (`analyze_run` `options`); the measurement's own parameters are on its card.

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `model` | ekv | ekv; level1 when a level-1 card is required | ekv, level1 | model family | level 1: no subthreshold, square law |
| `params` | - (fit this run) | the fit result of another run | parameter bounds | compare/export a given model | without it: goodness of fit only |
| `fit_rs` | false | true on Id-Vd or a family | true, false | series resistance per S/D | false: `theta` absorbs about 2 beta rs |
| `fit_lambda` | auto (|Vds| >= 0.5 V) | auto | true, false | channel-length modulation | held at 0 on a small-Vd Id-Vg |
| `i_min_a` | auto (3x floor) | auto | > 0 A | floor of the used points | larger: fewer subthreshold points |
| `level1_fraction` | 0.05 | 0.05..0.2 | 0..1 | level-1 window (|Id| share of the maximum) | larger: strong inversion only |
| `w_um` | - | from the DUT profile | > 0 um | channel width: level-1 KP = beta L/W, netlist W | without: W = 1u |
| `l_um` | - | from the DUT profile | > 0 um | channel length: level-1 KP, netlist L | without: L = 1u, KP = beta |
| `dialect` | ngspice | the human's simulator | ngspice, hspice | B-source with `ln` or G-source with `log` | export syntax |
| `segment` | fwd | fwd | fwd, rev | branch of a double sweep | one branch per model |
| `temperature_k` | 300 K | measurement temperature | 0..600 K | `U_T` of the EKV equations | sets SS = n U_T ln10 |

Example plan of the measurement the methods analyse (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.idvg
params: {}
pin_map: mosfet-4t
dut_profile: nmos-generic
sim_scenario: nmos_basic
```

## 5. Limits and confirmation

- None: the methods read archived runs; no plan, no source, no lock. The measuring recipe's card sets its limits
  and confirmation (`mosfet.idvg` is `ok` on the simulator; on hardware `first_hw_run` until `hw_validated`).
- Exported files are derived: they stay in the run folder or `work/<run_id>/spice/`; never edit run files.

## 6. Quality criteria

- Run quality `ok`; refusal on untrusted rows is final unless the human asks for `force` (flagged).
- Fit: `rms_log` below about 0.02 for EKV on a clean Id-Vg; above 0.1 a poor-fit warning. Standard errors small
  against the values; no parameter at its bound; at least five used points below threshold for `n`.
- Validation (`model_compare` on another run): report `rms_rel`, `rms_log` and the worst curve; a level-1 error is
  expected to be larger.

## 7. Analysis method

1. `analyze_run(idvg_run, compact_model_fit)` (EKV). Report `vth`, `n`, `beta`, `theta` (+ `lambda`, `rs`) as
   derived: model, window, points, standard errors, `rms_log`; SIMULATED when the backend is sim.
2. Family or Id-Vd: `compact_model_fit` with `{fit_rs: true}` for `rs` and `lambda`.
3. `analyze_run(other_run, model_compare, {params: {vt0, n, beta, theta, lambda, rs}})` from step 1 or 2.
4. `analyze_run(run, export_spice_netlist, {params: ..., dialect: hspice})`: give the human the two file paths,
   the sign note (`-I(VD)` = Id) and the error; the human runs the simulator.

## 8. Expected result shape

- Long-channel Si MOSFET: n 1.1..1.6 (SS 65..95 mV/dec), EKV `vth` between the constant-current and the
  linear-extrapolation Vth, theta 0..1 1/V, lambda 0..0.2 1/V, rs ohms to hundreds of ohms.
- IGZO TFT: n often 2..5 (traps), large hysteresis: fit one branch, expect larger errors.
- Red flags: n at 1.0 or 5.0, `vth` outside the swept range, `rms_log` > 0.1, `rs` at its bound: re-check the run.

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| refused | untrusted rows (X, V, F ...) | `get_run` quality counts | noisy-data |
| n or vth unstable between runs | few subthreshold points, floor noise | Id-Vg span, `i_min_a` used | noisy-data |
| strong inversion poorly fitted | compliance-limited rows left out | status counts C/T | compliance-hit |
| currents far above the model | leakage or damaged device | gate leakage card first | current-too-high |
| export failed: synchronous/log sweep | `mosfet.idvg_sync` or a log sweep | fit and compare instead | - |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-24 | nmos_basic | nmos-generic | S20261124T052016Z-50ac (`mosfet.idvg`) | EKV vth 0.4206 V vs model 0.42 V, n 1.303 vs 1.3 | - |
| hw | pending (bring-up stage L4) | - | - | - | - | - |

No recipe of its own, so no `validation/hw/` record: the methods run on the L4 runs (`validation/hw/mosfet.idvg.yaml`
and `mosfet.idvd`) once those are reviewed; simulator runs never make a hardware record.
