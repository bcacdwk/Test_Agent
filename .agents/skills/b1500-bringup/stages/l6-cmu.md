---
stage: L6
title: CMU - phase compensation and open/short (the human lifts and lands), known capacitor, MOS-C C-V and its variants, QSCV and Dit, SCUU same landing, split C-V, FeCap butterfly
recipes: [cmu.phase_compensation, cmu.correction_open, cmu.correction_short, cmu.correction_load, cmu.spot, moscap.cv, moscap.cv_ac_level, moscap.pulsed_cv, moscap.cf, moscap.ct, moscap.cv_multi_freq, moscap.qscv, mosfet.cgc_cv, mosfet.cgd_cv, fecap.cv_butterfly]
checks:
  - {id: corrst_on, quantity: cmu_CMU1, reference: 'uv run b1500 doctor --probe after the corrections (CORRST?, ADJ? read-only)', text: 'open and short on, phase compensation in effect'}
  - {id: store_written, quantity: corrections_store, reference: station_status.corrections, text: 'fresh phase/open/short records of every pin map used'}
  - {id: scuu_rest, quantity: scuu_rest, reference: 'run manifests (rest routes, cleanup verified); only with an SCUU', text: 'SCUU back at its rest path after every run'}
  - {id: phase_result, recipe: cmu.phase_compensation, quantity: result_code, method: kind_result, unit: '1', reference: 'ADJ? result', tolerance: {max_abs: 0.5}, text: 0 (completed)}
  - {id: phase_cleanup, recipe: cmu.phase_compensation, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: open_result, recipe: cmu.correction_open, quantity: result_code, method: kind_result, unit: '1', reference: 'CORR? result', tolerance: {max_abs: 0.5}, text: 0 (completed)}
  - {id: open_stray_c, recipe: cmu.correction_open, quantity: open_cp_f, method: kind_result, unit: F, reference: 'stray C of the lifted probes (CORRDT? median)', tolerance: {max_abs: 5.0e-12}, text: below 5 pF}
  - {id: open_cleanup, recipe: cmu.correction_open, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: short_result, recipe: cmu.correction_short, quantity: result_code, method: kind_result, unit: '1', reference: 'CORR? result', tolerance: {max_abs: 0.5}, text: 0 (completed)}
  - {id: short_r, recipe: cmu.correction_short, quantity: short_rs_ohm, method: kind_result, unit: Ohm, reference: 'cable + probe resistance (CORRDT? median)', tolerance: {max_abs: 5.0}, text: below 5 Ohm}
  - {id: short_cleanup, recipe: cmu.correction_short, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: load_r, recipe: cmu.correction_load, quantity: load_rs_ohm, method: kind_result, unit: Ohm, reference: 'certificate of the load standard', text: recorded (only with a load standard)}
  - {id: load_cleanup, recipe: cmu.correction_load, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: known_c, recipe: cmu.spot, quantity: cp, method: impedance_convert, unit: F, reference: 'certificate of the reference capacitor at 100 kHz and 1 MHz', tolerance: {rel: 0.01}, text: '+-1 % of the certificate'}
  - {id: spot_cleanup, recipe: cmu.spot, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: mosc_cox, recipe: moscap.cv, quantity: cox, method: cv_cox, unit: F, reference: 'EasyEXPERT C-V of the same die, accumulation Cox', tolerance: {rel: 0.02}, text: '+-2 %'}
  - {id: mosc_vfb, recipe: moscap.cv, quantity: vfb, method: cv_flatband, unit: V, reference: 'EasyEXPERT C-V of the same die, same sweep direction', tolerance: {absolute: 0.03}, text: '+-30 mV'}
  - {id: mosc_nsub, recipe: moscap.cv, quantity: nsub, method: cv_doping_profile, unit: cm^-3, reference: wafer specification or EasyEXPERT, tolerance: {rel: 0.1}, text: '+-10 %'}
  - {id: mosc_hysteresis, recipe: moscap.cv, quantity: hysteresis, method: cv_hysteresis, unit: V, reference: double sweep, text: recorded}
  - {id: mosc_cleanup, recipe: moscap.cv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: ac_limit, recipe: moscap.cv_ac_level, quantity: ac_limit, method: cv_ac_dependence, unit: V, reference: 'the C-V AC level', text: recorded (above the AC level of the C-V)}
  - {id: ac_level_cleanup, recipe: moscap.cv_ac_level, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: pulsed_dvfb, recipe: moscap.pulsed_cv, quantity: delta_vfb, method: cv_pulsed_vs_dc, unit: V, reference: 'DC moscap.cv swept from accumulation (options.reference_run)', tolerance: {max_abs: 0.02}, text: '|dVfb| <= 20 mV'}
  - {id: pulsed_cleanup, recipe: moscap.pulsed_cv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: cf_dit, recipe: moscap.cf, quantity: dit, method: cf_dispersion, unit: cm^-2 eV^-1, reference: lab or process Dit, text: recorded}
  - {id: cf_cleanup, recipe: moscap.cf, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: ct_tau, recipe: moscap.ct, quantity: tau_recovery, method: ct_recovery, unit: s, reference: lab C-t data, text: recorded}
  - {id: ct_cleanup, recipe: moscap.ct, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: multi_freq_dit, recipe: moscap.cv_multi_freq, quantity: dit_mean, method: dit_conductance, unit: cm^-2 eV^-1, reference: 'dit_high_low where the energies overlap', text: recorded}
  - {id: multi_freq_cleanup, recipe: moscap.cv_multi_freq, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: qscv_offset, recipe: moscap.qscv, quantity: offset_f, method: kind_result, unit: F, reference: 'offset: measure with the probes lifted', tolerance: {max_abs: 5.0e-12}, text: below 5 pF}
  - {id: qscv_leakage, recipe: moscap.qscv, quantity: leakage_max_a, method: kind_result, unit: A, reference: 'card moscap-dit (gate leakage limit)', tolerance: {max_abs: 1.0e-9}, text: below 1 nA}
  - {id: qscv_cox, recipe: moscap.qscv, quantity: cox, method: cv_cox, unit: F, reference: 'cv_cox of the HF moscap.cv of the same landing', tolerance: {rel: 0.02}, text: '+-2 % of the HF Cox'}
  - {id: dit_mid, recipe: moscap.qscv, quantity: dit_mid, method: dit_high_low, unit: cm^-2 eV^-1, reference: lab or process Dit, text: recorded}
  - {id: qscv_cleanup, recipe: moscap.qscv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: cgc_plateau, recipe: mosfet.cgc_cv, quantity: cox, method: cv_cox, unit: F, reference: 'Cox per area of the MOS-C x W x L', tolerance: {rel: 0.05}, text: '+-5 %'}
  - {id: cgc_cleanup, recipe: mosfet.cgc_cv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: cgd_vth, recipe: mosfet.cgd_cv, quantity: vth, method: cv_vth, unit: V, reference: 'L4 vth_constant_current, same MOSFET', text: recorded (method differs)}
  - {id: cgd_cleanup, recipe: mosfet.cgd_cv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: butterfly_vc, recipe: fecap.cv_butterfly, quantity: vc, method: cv_butterfly, unit: V, reference: 'lab P-V or PUND of the same film', text: recorded}
  - {id: butterfly_cleanup, recipe: fecap.cv_butterfly, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
version: 1
---

# L6 - CMU

The MFCMU on hardware: phase compensation and open/short corrections (card `cmu-correction`) with the human lifting,
shorting and landing the probes, the known-capacitor check (`cmu-spot`), then a MOS capacitor (`moscap-cv`,
`moscap-cf-ct`, `moscap-dit`), the split C-V of the L4 MOSFET (`mosfet-split-cv`) and a FeCap if the lab has one
(`fecap-pund`). Corrections belong to one pin map and landing: every new pin map gets its own phase, open and
short. Every hardware plan needs consent (`first_hw_run`); each correction also `physical_setup`.

## 1. Preconditions

- L5 signed off; `uv run b1500 bringup status` names L6; `station_status` clean; `uv run b1500 doctor --probe` shows
  the `cmu CMU1` line (MFCMU slot 7; corrections off until this stage).
- A reference capacitor with a certificate (100 pF), a MOS capacitor with known area (and its EasyEXPERT C-V of the
  same die), the L4 MOSFET, optionally a load standard (`corrections.CMU1.load`, recorded by the human), a FeCap.
- An SCUU only if L0 recorded SCUU1 `present: true`; else the QSCV runs on an SMU landing (gate SMU, bulk GNDU).

## 2. Physical steps (human)

1. Adopt the pin maps and DUT profiles (copies of `capacitor-cmu`/`capacitor-100p`, `moscap-cmu`/`moscap-generic`
   with the real area and envelope, `moscap-scuu`, `mosfet-split-cv`/`nmos-cv`, `fecap-cmu`/`fecap-generic`):
   `uv run b1500 config adopt FILE --as pinmap`, `--as dut`.
2. For each correction set the state the agent asks for and keep it until it reports the run done: probes lifted
   (phase, open, QSCV `offset: measure`), on a short (short), on the load standard (load). Confirm in chat.
3. Land on the reference capacitor, then the MOS-C, the MOSFET, the FeCap, each when the agent asks; same cables
   as the corrections; shield box closed and dark; High on the chuck if a terminal must go there.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status` (`corrections` missing); the probe line `cmu CMU1`.
2. Corrections with the reference capacitor's pin map: validate `cmu.phase_compensation` and `cmu.correction_open`,
   show both summaries, ask to lift the probes, stop; run both after consent (`open_cp_f`). Then
   `cmu.correction_short` (`short_rs_ohm`); `cmu.correction_load` only with a load standard.
3. Land on the standard: `cmu.spot` at 100 kHz and 1 MHz (`impedance_convert` Cp). Then `uv run b1500 doctor
   --probe` (`corrst_on`) and `station_status.corrections` (`store_written`).
4. MOS-C (`moscap-cmu`): corrections again, then `moscap.cv` double sweep (`cv_cox`, `cv_flatband`,
   `cv_doping_profile`, `cv_hysteresis`); `moscap.cv_ac_level` (`cv_ac_dependence`); a DC `moscap.cv` from
   accumulation as `reference_run` of `moscap.pulsed_cv` (`cv_pulsed_vs_dc`).
5. C-f list: open and short with `freqs_hz` = the C-f list (a new list clears all: phase, open, short again), then
   `moscap.cf` (`cf_dispersion`), `moscap.ct` (`ct_recovery`), `moscap.cv_multi_freq` (`dit_conductance`).
6. Dit on one landing (`moscap-scuu`): corrections with it, `moscap.qscv` `offset: measure` (lifted), land,
   `offset: cancel` (`cv_cox`, `leakage_max_a`), `moscap.cv` on the same landing, `dit_high_low` (QSCV run,
   `reference_run` the HF run); `get_run` routes `SSP 7,3` / `7,4` and rest. No SCUU: QSCV on the SMU landing,
   `qscv_cox` and `dit_mid` recorded only (two landings, two states).
7. Split C-V on the L4 MOSFET: corrections, `mosfet.cgc_cv` (`cv_cox` plateau, `cv_vth`), `mosfet.cgd_cv`
   (`cv_vth`). FeCap: corrections with `fecap-cmu`, `fecap.cv_butterfly` (`cv_butterfly`).
8. Report every value as derived (method, window, status counts, backend visa, correction ages).

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `phase_result`, `open_result`, `short_result` | result 0 | pass/fail | `kind_result` |
| `open_stray_c`, `short_r`, `load_r` | stray C of lifted probes; cable + probe R; load R | < 5 pF; < 5 Ohm; recorded | `CORRDT?` |
| `corrst_on`, `store_written`, `scuu_rest` | on and in effect; fresh records; SCUU at rest | recorded | probe, status |
| `known_c` | Cp of the reference capacitor | +-1 % of the certificate | certificate |
| `mosc_cox`, `mosc_vfb`, `mosc_nsub` | Cox, flatband, doping of the MOS-C | +-2 %; +-30 mV; +-10 % | EasyEXPERT |
| `mosc_hysteresis`, `ac_limit`, `cf_dit`, `ct_tau`, `multi_freq_dit`, `dit_mid`, `cgd_vth`, `butterfly_vc` | as found | recorded | lab data |
| `pulsed_dvfb` | pulsed vs DC flatband, both from accumulation | <= 20 mV | DC run |
| `qscv_offset`, `qscv_leakage` | path offset; largest QSCV leakage | < 5 pF; < 1 nA | `kind_result` |
| `qscv_cox` | QSCV Cox vs HF Cox of the same landing (SCUU same-landing check) | +-2 % | HF run |
| `cgc_plateau` | Cgc plateau vs Cox per area x W x L | +-5 % | MOS-C |
| `phase_cleanup`, `open_cleanup`, `short_cleanup`, `load_cleanup`, `spot_cleanup`, `mosc_cleanup`, `ac_level_cleanup`, `pulsed_cleanup`, `cf_cleanup`, `ct_cleanup`, `multi_freq_cleanup`, `qscv_cleanup`, `cgc_cleanup`, `cgd_cleanup`, `butterfly_cleanup` | every run `verified: lop` | pass/fail | manifests |

- TODO(verify) here (simulator conventions; ATV-21, ATV-22, ATV-27, ATV-31): `ACT` auto time per N; fixed `RC` range
  saturation; `CORR?` time per frequency and timeout; the largest list (64); `DCORR?`/`CORRDT?` answers of unmeasured
  data; `*LRN? 81/90` text; `CL` leaves the SCUU path; SSP resets the SMUs; MFCMU DC current limit; pulsed C read at
  the pulse end; AC-level response; `WFC` rounding against the `CORRL` list; QSCV 50 Hz line (`line_hz`); corrections
  kept until `*RST`/device clear/power-off; FMT 1 CMU and C-t time-stamp blocks (`bringup capture`).

## 5. Abort criteria

- A correction fails twice (result 1/2) or reads `open_cp_f` above 5 pF or `short_rs_ohm` above 5 Ohm twice with
  the human confirming the state; errors 680-685 persist (runbook `cmu-correction-stale`).
- The reference capacitor outside +-1 % or status `U`/`D`/`V` after fresh corrections: no MOS-C before it is
  understood (runbooks `cmu-cv-distortion`, `cmu-series-resistance`).
- Errors 320-323, a QSCV offset above 5 pF, QSCV leakage above 1 nA, a fault, `cleanup_unverified`, an SCUU not back
  at rest. On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human.

## 6. Record

- Hardware: one record per recipe with checks, `uv run b1500 bringup record L6 --run H... --operator NAME` with
  `--reference known_c=<certificate F>`, `--reference mosc_cox=...`, `mosc_vfb`, `mosc_nsub` (EasyEXPERT),
  `--reference qscv_cox=<HF Cox>`, `--reference cgc_plateau=<Cox' W L>`; the stage record (`corrst_on`,
  `store_written`, `scuu_rest`). The human reviews them and moves them to `validation/hw/stage-l6.yaml` and
  `validation/hw/<recipe>.yaml` for the fifteen recipes; fixtures: `uv run b1500 bringup capture H...` of one C-V,
  one C-t and one QSCV run.
- Simulator rehearsal: no record; say which records hardware drafts.
