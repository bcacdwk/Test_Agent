---
domain: 07-compact-models
maturity: seed
sources:
  - src/b1500_test_agent/analysis/model.py (compact_model_fit, model_compare, export_spice_netlist; WP7.7)
  - src/b1500_test_agent/analysis/spice.py (SPICE export grammar; WP7.7)
  - docs/design/blueprint.md section 0 row 26, 2.10 (model.py) and 12 (OD-6)
  - "deck slides 7 and 16: plans only (level-1 first, BSIM4 and Verilog-A later; illustrative, not evidence)"
  - "lab: the offline EKV fit of the October 2025 lwp Id-Vg (config/sim/scenarios/lab_nmos_2025.yaml)"
  - "former 07-hspice-simulation.md (v1 reserved workflow, rewritten here; hspice.compare retired)"
last_reviewed: null
---

# Compact models and SPICE export (knowledge domain 7)

A compact model condenses a measured Id-Vg or Id-Vd run into a few parameters that a circuit simulator can use.
Three `analyze_run` methods do it on archived runs, never on the instrument: `compact_model_fit`, `model_compare`
and `export_spice_netlist` (card [compact-model-spice](../cards/smu/compact-model-spice.md)). Definitions here are
identical to the docstrings of `src/b1500_test_agent/analysis/model.py` and `spice.py`; the code wins on any
difference and a change to either must change both. Replaces the v1 reserved HSPICE workflow (`hspice.compare` is
retired).

Contents: [Status and boundaries](#status-and-boundaries) · [Workflow](#workflow) ·
[Level-1 model](#level-1-model) · [EKV model](#ekv-model) · [Points and trust](#points-and-trust) ·
[Fit](#fit) · [Comparing a model with a run](#comparing-a-model-with-a-run) · [SPICE export](#spice-export) ·
[Example files](#example-files) · [Reading the results](#reading-the-results) ·
[BSIM4 and Verilog-A later](#bsim4-and-verilog-a-later)

## Status and boundaries

- Analysis only: the methods read finished runs; they never source, never take the instrument lock and change no
  rule, limit or plan. A model is a derived result: report it with method, model, fit window, points and error.
- Running a SPICE simulator (HSPICE licence, ngspice install) is not part of v2 (OD-6). `export_spice_netlist`
  writes ready-to-run files; the human runs them. `model_compare` is the built-in evaluation of the model.
- Models: SPICE level 1 (square law) and a long-channel EKV interpolation with a constant slope factor (the model
  the simulator's `mosfet_ekv` uses). No BSIM, no short-channel effects, no temperature scaling beyond `U_T`.
- Devices: MOSFET-like three/four-terminal devices with `gate_V` and `drain_V` columns (`mosfet.idvg`,
  `mosfet.idvd`, `mosfet.idvg_family`, `mosfet.idvg_sync`, `mosfet.body_effect`, the pulsed Id-Vg/Id-Vd recipes,
  `generic.*` with those role names). IGZO TFTs fit within limits (no trap model); FeFETs only per branch.

## Workflow

1. Measure an Id-Vg that reaches from the noise floor through threshold into strong inversion (`mosfet.idvg`
   defaults, or `mosfet.idvg_family` for several drain biases) and an Id-Vd family (`mosfet.idvd`). Check quality.
2. `analyze_run(run, compact_model_fit)` on the Id-Vg (or the family): EKV by default; `fit_rs: true` when the
   run also has drain variation (Id-Vd or a family); level 1 with `model: level1` (and `w_um`/`l_um` for KP).
3. Validate on another run: `analyze_run(other_run, model_compare, {params: <the fit's parameters>})`. Without
   `params` the comparison fits the same run first and only measures the goodness of fit.
4. `analyze_run(run, export_spice_netlist, {params: ..., dialect: ngspice|hspice})` writes
   `analysis/spice-<model>-<n>.lib` and `.sp` into the run folder. Hand them to the human with the RMS error.

## Level-1 model

SPICE `LEVEL=1` (Shichman-Hodges), n-channel equations (p-channel: every voltage and the current change sign):

- `Vov = Vgs - VTO`; cutoff `Id = 0` for `Vov <= 0`; linear (`Vds < Vov`)
  `Id = beta (Vov Vds - Vds^2/2)(1 + LAMBDA Vds)`; saturation `Id = beta/2 Vov^2 (1 + LAMBDA Vds)`; a negative
  `Vds` swaps source and drain. `beta = KP W/L` (A/V^2).
- Fitted: `vto` (reported as quantity `vth`), `beta`, `lambda` (only with drain variation). `GAMMA = 0`: the fit
  holds at the run's bulk bias. With `w_um`/`l_um` the result adds `kp = beta L/W`.
- No subthreshold current, no mobility degradation, no series resistance: the fit uses only the points with
  `|Id| >= level1_fraction x max|Id|` (default 5 %); its `vth` is an extrapolated square-law threshold that differs
  from constant-current and EKV thresholds by a device- and criterion-dependent amount, and its error grows with
  gate overdrive.

## EKV model

Long-channel EKV interpolation with a constant slope factor; voltages referred to the bulk; `U_T = kT/q`:

- pinch-off `Vp = (Vg - VT0)/n`; forward/reverse `i_f,r = ln^2(1 + exp((Vp - Vs,d)/(2 U_T)))`;
  `I_spec = 2 n beta U_T^2`; smooth overdrive `Vov = 2 n U_T ln(1 + exp((Vg - VT0 - n min(Vs, Vd))/(2 n U_T)))`;
- `Id = I_spec (i_f - i_r)(1 + LAMBDA |Vd - Vs|)/(1 + THETA Vov)`; `rs` (Ohm) in series with source and drain
  each, the drop solved self-consistently.
- Parameters: `vt0` (V, quantity `vth`), `n` (subthreshold swing `SS = n U_T ln10`, for example 77 mV/dec for
  n = 1.3 at 300 K), `beta` (A/V^2 = mu Cox W/L), `theta` (1/V, mobility degradation), `lambda` (1/V), `rs` (Ohm).
- One equation covers weak inversion (exponential, slope from `n`) through strong inversion (square law with
  `theta`), so subthreshold and above-threshold points fit together. `vt0` is the gate voltage where the source
  end reaches pinch-off (there Id is about I_spec/2); where it lies relative to a constant-current or
  linear-extrapolation Vth depends on I_spec and the criterion, so compare like with like (the lab's October 2025
  Id-Vg: vt0 0.350 V, linear extrapolation 0.349 V, 0.296 V at 10 nA, about 0.68 V at 100 nA;
  `config/sim/scenarios/lab_nmos_2025.yaml`).

## Points and trust

- Terminal voltages from the `<role>_V` columns (roles `gate`, `drain`, `source`, `bulk`; a missing source is the
  GNDU at 0 V, a missing bulk follows the source); current `y` (default `drain_I`). The swept column is the one
  that changes most between rows; a column that changes only between curves is the step (a family); one that
  changes with the sweep is a synchronous source.
- Trust as every method ([06](06-analysis-extraction.md#run-table-and-trust-classes)): untrusted rows refuse the
  call unless `force` (flagged); limited `C`/`T` rows (compliance) never enter.
- Floor: points with `|Id| < i_min_a` stay out. Default: 3x the noise-floor detection limit found on the curves
  (rough log10|I|, as for Ion/Ioff), at least `1e-9 x max|Id|`; points at Vds = 0 never carry model information.
- A double sweep uses `segment` (default `fwd`).

## Fit

- Least squares on `asinh(Id_model/(2 i_min)) - asinh(Id/(2 i_min))`, which equals `ln(Id_model/Id)` above the
  floor: every point counts by its relative error, so subthreshold decades set `n` and `vt0`, strong inversion
  `beta` and `theta`. Levenberg-Marquardt within parameter bounds, from several starts (threshold candidates across
  the gate range x slope factors); `beta` is fitted on a log scale.
- `lambda` is fitted when the used points reach `|Vds| >= 0.5 V` (`fit_lambda` overrides), else held at 0.
- `rs` only with `fit_rs` (a second stage from the best fit): one Id-Vg at small Vd cannot separate `rs` from
  `theta` (`theta` then absorbs about `2 beta rs`); a family or an Id-Vd can.
- Every parameter result carries in `fit`: all parameters, standard errors `<name>_se` (from the Jacobian), `rms_log`
  (RMS of `ln(Id_model/Id)`, about the RMS relative error), `rms_rel`, `points`, `i_min`, `temperature_k`.
- Warnings: a parameter at its bound (the data do not determine it), `rms_log > 0.1` (poor fit), fewer than 5
  points below threshold (n and Vth from strong inversion only), `lambda`/`rs` held.

## Comparing a model with a run

- `model_compare` evaluates the model at every used point of the run: `rms_rel` (RMS of `(Id_model - Id)/|Id|`),
  `rms_log` (RMS of `log10(Id_model/Id)`, decades), `max_rel`, `rms_error` (A); a stepped run also gives
  `rms_rel@<step>=<level>` per curve in `fit`.
- `params` take the names the fit reports (`vt0` or `vth`, `n`, `beta`, `theta`, `lambda`, `rs`; level 1 `vto`
  or `vth`, `beta` or `kp` with `w_um`/`l_um`, `lambda`). Without `params`: fit first, then compare (goodness of
  fit, flagged; not a validation).
- A validation compares on bias conditions the fit did not see (fit the Id-Vg family, compare the Id-Vd). Report
  both numbers and where the largest deviation sits (per-curve errors).

## SPICE export

- Two files under `analysis/`: `spice-<model>-<n>.lib` (the model alone, for reuse) and `spice-<model>-<n>.sp` (a
  self-contained netlist: title line, header comments, the model inline, one device, a DC source per driven
  terminal, `.dc` reproducing the run's sweep, `.print dc I(VD)`, `.end`). Agent scripts use
  `write_spice_files(export, run_id=...)` (files under `work/<run_id>/spice/`).
- Level 1: `.model nch_level1 NMOS (LEVEL=1 VTO=... KP=... LAMBDA=... GAMMA=0 PHI=0.6)` and
  `M1 d g s b nch_level1 W=... L=...`; `KP = beta L/W` with the given geometry, else `W = L = 1u`, `KP = beta`
  (stated in the file).
- EKV: no portable built-in card (EKV 2.6 levels differ between simulators and derive n from GAMMA/PHI), so a
  subcircuit `nch_ekv d g s b` with one behavioural current source between the internal nodes (`RD`/`RS` resistors
  when `rs > 0`): ngspice `B1 di si I=...` with `ln`, HSPICE `G1 di si CUR='...'` with `log` (both natural logs).
  Values are written into the expression as numbers; long expressions continue on `+` lines, split after `*`.
- Sweep: inner `.dc` source = the swept terminal, outer = the stepped one; both must be uniform grids from the
  table. A synchronous or logarithmic sweep cannot be written as `.dc`: the export fails (fit and comparison work).
- Sign: `I(VD)` is the current into the source's `+` node; the measured drain current is `-I(VD)`.
- The header carries run id, recipe, backend (SIMULATED data for sim) and the error on the run. A SPICE-syntax
  parser test checks both dialects and that the deck's DC sweep reproduces the built-in model.

## Example files

Level-1 netlist from a simulated Id-Vg at Vd = 50 mV (values illustrative, not a real device):

```text
nch_level1 reproduces run S20261124T051045Z-81f2 (mosfet.idvg)
* b1500-test-agent compact model export (level1, ngspice); derived values, not measurements
.model nch_level1 NMOS (LEVEL=1 VTO=0.34 KP=0.0013 LAMBDA=0
+ GAMMA=0 PHI=0.6)
M1 d g s s nch_level1 W=1u L=1u
VG g 0 DC -1
VD d 0 DC 0.05
VS s 0 DC 0
.dc VG -1 3 0.04
.print dc I(VD)
.end
```

EKV (excerpt): `.subckt nch_ekv d g s b`, `RD d di 20`, `RS s si 20`,
`B1 di si I=3.47e-06*(ln(1+exp((((V(g,b)-(0.42))/1.3)-V(si,b))/0.0517))*...`, `.ends nch_ekv`, then
`X1 d g s s nch_ekv` and `.dc VD 0 3 0.03 VG 0.5 1.5 0.25` for an Id-Vd family.

## Reading the results

- Fit quality: the code warns above `rms_log` 0.1 (natural-log units, about 10 % RMS relative error). No reference
  for a good fit on the owner's devices is on record; the offline EKV fit of the October 2025 lab Id-Vg left
  0.022 decade RMS (about 0.05 in these units; `config/sim/scenarios/lab_nmos_2025.yaml`). Judge each parameter by
  its standard error `<name>_se`; `theta` includes series resistance unless `rs` was fitted.
- Level 1 on the same data: larger error near threshold and at high overdrive (by construction); use it only where
  a level-1 card is required, and say so.
- `n` from an Id-Vd family alone rests on strong inversion (warning): fit an Id-Vg for subthreshold parameters.
- A parameter at its bound, a large standard error or a poor-fit warning: the data do not support the model (too
  few decades, compliance-limited strong inversion, a damaged device); re-check the run quality first.
- IGZO TFTs: hysteresis and drift move the curve between sweeps; fit one segment and note the sweep direction.

## BSIM4 and Verilog-A later

- BSIM4 brings short-channel, DIBL and mobility models but needs many parameters and a dedicated extraction flow;
  not part of v2. DIBL and body effect are measured directly
  ([06](06-analysis-extraction.md#dibl-and-body-effect)).
- Verilog-A device models (FeFET polarization, oxide TFT traps) can run in HSPICE next to the exported cards; the
  deck plans experiment-simulation co-tuning with them (deck slides 7 and 16). Running any simulator remains the
  human's step (OD-6).
