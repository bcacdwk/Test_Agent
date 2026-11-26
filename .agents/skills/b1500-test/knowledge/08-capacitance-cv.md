---
domain: 08-capacitance-cv
maturity: seed
sources:
  - blueprint v2 2.7 (kind cmu_measure), 2.10 (cv.py), 3.2 (MFCMU catalogue), 4.2 (moscap, mosfet +cv targets)
  - "B1500 Programming Guide Ed. 15 (PG), PDF pages cited inline"
  - "AN-CV: IV and CV with the MFCMU and SCUU (application note), PDF pages cited inline"
  - src/b1500_test_agent/analysis/cv.py, catalog/kinds/cmu_measure.py (v2 WP8.3)
  - src/b1500_test_agent/analysis/cv_variants.py, catalog/kinds/cmu_variants.py (v2 WP8.4)
  - src/b1500_test_agent/analysis/qscv.py, dit.py, catalog/kinds/smu_qscv.py (v2 WP8.5; QSCV, Dit over the gap)
  - "literature, not checked against a copy (TODO(cite)): Nicollian & Brews, MOS Physics and Technology (Wiley 1982)
    ch. 5, 9; Sze & Ng, Physics of Semiconductor Devices (2007) ch. 4; Koomen, Solid-State Electron. 16, 801 (1973)
    and Sodini et al., Solid-State Electron. 25, 833 (1982) (split C-V); Zerbst, Z. Angew. Phys. 22, 30 (1966)
    (C-t); Miller et al., J. Appl. Phys. 68, 6463 (1990) (FeCap C-V); Castagne & Vapaille, Surf. Sci. 28, 157 (1971)
    (high-low); Nicollian & Goetzberger, BSTJ 46, 1055 (1967) (conductance)"
  - CMU closure (v2 WP8.6) - correction data read-back (CORRDT?), bring-up stage L6, runbooks cmu-cv-distortion and cmu-series-resistance
last_reviewed: null
---

# Capacitance and C-V (knowledge domain 08)

What the MFCMU measures, how a C-V curve becomes Cox, doping, flatband and threshold voltage, what the split C-V of
a MOSFET adds, the variants (AC level, pulsed, C-f, C-t, FeCap butterfly), the SMU's quasi-static C-V and Dit over the
band gap. The definitions are those of `analysis/cv.py`, `cv_variants.py`, `qscv.py` and `dit.py` (their module
docstrings are the source); every value they return is derived. Debugging is skill `b1500-debug`: runbooks
`cmu-cv-distortion`, `cmu-series-resistance`, `cmu-correction-stale`.

## Contents

- [Scope and status](#scope-and-status)
- [Impedance models Cp-G Cs-Rs Z-theta](#impedance-models-cp-g-cs-rs-z-theta)
- [Corrections and the measurement path](#corrections-and-the-measurement-path)
- [High-frequency C-V of a MOS capacitor](#high-frequency-c-v-of-a-mos-capacitor)
- [Oxide capacitance and EOT](#oxide-capacitance-and-eot)
- [Doping from 1/C^2](#doping-from-1c2)
- [Flatband voltage](#flatband-voltage)
- [Threshold voltage from C-V](#threshold-voltage-from-c-v)
- [Hysteresis](#hysteresis)
- [Split C-V Cgc and Cgd](#split-c-v-cgc-and-cgd)
- [SCUU same-landing I-V and C-V](#scuu-same-landing-i-v-and-c-v)
- [AC level dependence](#ac-level-dependence)
- [Pulsed C-V](#pulsed-c-v)
- [C-f and frequency dispersion](#c-f-and-frequency-dispersion)
- [C-t and deep-depletion recovery](#c-t-and-deep-depletion-recovery)
- [Quasi-static C-V](#quasi-static-c-v)
- [Dit over the band gap](#dit-over-the-band-gap)
- [FeCap C-V butterfly](#fecap-c-v-butterfly)
- [Reporting C-V results](#reporting-c-v-results)

## Scope and status

- Recipes (kind `cmu_measure`): `cmu.spot` (MM 17 spot C), `moscap.cv` (MM 18 C-V, single or double),
  `mosfet.cgc_cv`, `mosfet.cgd_cv` (split C-V); `moscap.cv_ac_level` (MM 23), `moscap.pulsed_cv` (MM 20, MM 19 for
  one point), `moscap.cf` (MM 22), `moscap.ct` (MM 26), `moscap.cv_multi_freq` (MM 18 per frequency),
  `fecap.cv_butterfly` (MM 18 double); kind `smu_qscv`: `moscap.qscv` (MM 13, SMU quasi-static C-V). Methods:
  `cv_cox`, `cv_flatband`, `cv_doping_profile`, `cv_vth`, `cv_hysteresis`, `impedance_convert`, `plot_cv`;
  `cv_ac_dependence`, `cv_pulsed_vs_dc`, `cf_dispersion`, `ct_recovery`, `cv_butterfly`; `dit_high_low`,
  `dit_conductance` (card `cmu/moscap-dit`).
- Every C-V run needs fresh phase, open and short corrections of the same pin map (rule R-CORR-01; card
  `cmu/cmu-correction`).
- All 15 MFCMU recipes are `sim_validated` (the module closed with WP8.6); on hardware they are validated at bring-up
  stage L6 (skill `b1500-bringup`: corrections, a reference capacitor within 1 % of its certificate, MOS-C against
  EasyEXPERT, QSCV
  against the HF Cox of the same landing), until then every hardware plan needs `first_hw_run` confirmation.

## Impedance models Cp-G Cs-Rs Z-theta

- The MFCMU returns one parameter pair per point (`IMP`, PG p441 (4-123) "IMP"; Table 4-16, PG p347 (4-29)):
  `cp_g` (default for C-V), `cp_d`, `cs_rs`, `cs_d`, `z_theta` (theta in radian in the run table).
- Parallel and series forms describe the same admittance `Y = G + jwCp`, `Z = 1/Y = Rs - j/(wCs)`: `Cs = Cp (1 +
  D^2)`, `D = G/(wCp) = Rs w Cs`. For a good capacitor (D < 0.01) Cp and Cs agree within 0.01 %.
- A MOS capacitor is a parallel network (oxide, depletion, traps, leakage), so C-V uses Cp-G; a series resistance
  (substrate, back contact, probe) adds to Z and makes Cp fall at high frequency in accumulation: `Cp = C / (1 +
  (w Rs C)^2)`, 1 % at `w Rs C` = 0.1 (69 pF at 1 MHz: Rs = 230 Ohm).
- `impedance_convert` reports a run in another pair at one point per frequency and can remove a series resistance:
  given (`series_r: value`, `rs_ohm`) or estimated in strong accumulation (`series_r: accumulation`): `Rs =
  G_ma / (G_ma^2 + w^2 C_ma^2)` from the parallel values at the largest capacitance (the standard series-resistance
  correction; reference not checked).
  The C-V methods take `rs_ohm` to correct before extracting. Full converted curves: `convert_table` (ad-hoc,
  `work/<run_id>/`).

## Corrections and the measurement path

- Phase compensation, then open and short at every frequency the measurement uses, with the probes where the human
  puts them for the C-V (lifted, shorted); a re-landing or another pin map makes them stale.
- Uncorrected, the open capacitance of cables and probe adds to every reading (simulator example, scenario
  `capacitor_100p`: 0.3 pF, not a real-device value; this station's: `TODO(verify)[L6.A2]`); the
  short path (resistance, inductance) matters above about 1 MHz and for large capacitances.
- Corrections act only at listed frequencies: list every C-V frequency in the correction recipes' `freqs_hz` (the
  23 default frequencies of `CLCORR 2`: 1-2-5 steps from 1 kHz to 1 MHz, then 1.2, 1.5, 2, 2.5, 2.7, 3, 3.2, 3.5,
  3.7, 4, 4.2, 4.5 and 5 MHz; PG p379 (4-61)). A C-f sweep's list (4 per decade, log) is not in them: run open and
  short with `freqs_hz` = the C-f list (plus the C-V frequencies); the new list clears the old corrections of that
  MFCMU (PG p384 (4-66)), so all are measured again (phase, open, short).
- Each data correction reads its data back (`CORRDT?`, medians over the list in the run's `kind_result`): the open's
  stray capacitance `open_cp_f` and the short's `short_rs_ohm`/`short_ls_h`. Normal values for this station are
  recorded at bring-up L6 (`TODO(verify)[L6.A2]`); L6's provisional criteria fail `open_cp_f` above 5 pF or
  `short_rs_ohm` above 5 Ohm. A value far from the recorded one means the human's probe state was wrong: repeat
  that correction before any C-V.
- Known-capacitor check: `cmu.spot` on a reference capacitor reads its value within its tolerance after the
  corrections (bring-up stage L6).

## High-frequency C-V of a MOS capacitor

- Regions (p substrate; mirrored for n): accumulation (gate negative, C near Cox), depletion (Cox in series with a
  shrinking depletion capacitance), inversion (high frequency: minority carriers cannot follow, C stays at Cmin).
  Background: [01](01-device-physics.md#mos-capacitor-c-v-regions).
- Sweep from inversion towards accumulation (p substrate: + to -) with a hold at the start: the inversion layer is
  in equilibrium and excess carriers recombine as the bias falls. Sweeping from accumulation into inversion faster
  than the inversion layer can form (thermal generation; the recovery time of the device is what `moscap.ct`
  measures) drives the surface into deep depletion: C falls below Cmin.
- 1 MHz is the usual high frequency. Interface traps respond at lower frequencies; minority carriers usually only
  far below the MFCMU's 1 kHz floor: for the low-frequency curve use QSCV ([below](#quasi-static-c-v)).
- MFCMU limits: 1 kHz to 5 MHz, 10 to 250 mVrms, DC bias within +-25 V (UG p73 (2-33) "MFCMU"). Keep the AC level
  small (10 to 50 mVrms) against the bias resolution; more than 50 mVrms needs `soft_cmu` confirmation.

## Oxide capacitance and EOT

- Cmax is Cox in series with the accumulation-layer capacitance, so it lies a few % below Cox for thin oxides
  (classical estimate: about 3 % for 5 nm SiO2 at 1.6 V beyond flatband; quantum confinement makes the gap larger
  in thin oxides).
- `cv_cox` extrapolates: in strong accumulation `Cs = Q/(2 kT/q)`, so `1/C = 1/Cox + 2 (kT/q) / Q` with the
  accumulation charge `Q`. Over the tail with `C >= acc_frac x Cmax` (default 0.85) `Q = Q0 + int C dV`, the offset
  Q0 is chosen for the straightest line of 1/C against 1/Q, and the intercept is 1/Cox. No flatband voltage needed.
- `EOT = 3.9 eps0 A / Cox` and Cox per area need the DUT profile's `geometry.area_um2`; without it only Cox (F).
- Too few strong-accumulation points: sweep further into accumulation (within the DUT envelope) or use more points.

## Doping from 1/C^2

- In depletion (depletion approximation with the kT/q Debye correction) `1/C^2 = 1/Cox^2 + 2 (V - Vfb - kT/q) /
  (q eps_s N A^2)`, so `N = 2 / (q eps_s A^2
  |d(1/C^2)/dV|)` from the slope; depth `W = eps_s A (1/C - 1/Cox)`.
- `cv_doping_profile` fits the slope only where the band bending `psi = |int_Vfb^V (1 - C/Cox) dV|` lies between
  4 kT/q and `2 phi_B - 3 kT/q` (`phi_B = (kT/q) ln(N/ni)`): nearer flatband the Debye tail, nearer threshold the
  inversion charge bend the line. Textbook silicon values: `eps_s = 11.7 eps0` (fixed in the code: the doping
  holds for silicon only), `ni = 1e10 cm^-3` and 300 K (options `ni_cm3`, `temperature_k`).
- Reported: `nsub` (cm^-3) with the fit window and depth range; needs `geometry.area_um2`. A non-uniform profile
  shows as a curved 1/C^2 plot (`plot_cv`).

## Flatband voltage

- Flatband capacitance `C_FB = A Cox' C_D / (Cox' + C_D)`, `C_D = eps_s / L_D`, Debye length `L_D = sqrt(eps_s
  (kT/q) / (q N))`; `cv_flatband` reports the bias where the curve crosses C_FB (`vfb`) and `c_fb`.
- Cox, N and Vfb are fitted together (the doping window depends on Vfb): a consistent set, not three independent
  measurements. Without `geometry.area_um2` the method refuses and names the field.
- `Vfb = phi_ms - Qf/Cox - Qit(0)/Cox`: a shift against the expected work-function difference means fixed or trapped
  charge; compare runs, not absolute values, when phi_ms is uncertain.

## Threshold voltage from C-V

- MOS capacitor (`cv_vth`): `Vth = Vfb + 2 phi_B + sqrt(2 q eps_s N 2 phi_B) / Cox'` from the fitted Cox, N, Vfb:
  the strong-inversion onset of the ideal electrostatics, not a crossing of the measured curve.
- Split C-V (`cv_vth` on `mosfet.cgc_cv`/`cgd_cv`): the onset of the inversion capacitance, the maximum of
  `d^2 Cgc / dVg^2` in the rising part. It is close to, but not identical with, the 2 phi_B threshold (size of the
  difference: `TODO(cite)`); an I-V Vth (linear extrapolation, constant current) of the same device differs by
  definition: report the method.

## Hysteresis

- A double sweep (`sweep_mode: double`) returns `fwd` and `rev` branches; `cv_hysteresis` reports `vfb_rev - vfb_fwd`
  at the forward branch's flatband capacitance (mid level `(Cmax + Cmin)/2` without an area).
- Charge trapped near the interface (border traps, mobile ions) moves the flatband with the sweep history; the sign
  says which charge: electrons trapped at positive gate bias shift Vfb positive on the branch that started there.
- The return branch into inversion may be in deep depletion; that does not change the flatband region.

## Split C-V Cgc and Cgd

- Cgc (`mosfet.cgc_cv`): gate on the MFCMU High side, drain on the Low side, source tied to the drain at the Low
  cable or left floating (never grounded), bulk grounded. The inversion charge of the whole channel returns through
  the Low side: Cgc rises from the overlap floor (accumulation) to about Cox W L (strong inversion).
- Cgd (`mosfet.cgd_cv`): source and bulk AC-grounded (an SMU at 0 V or the GNDU): only the drain half of the channel
  and the drain overlap are seen, about `Cox W L / 2 + Cov` in strong inversion.
- `cv_cox` on Cgc removes the floor (overlap capacitance, `c_floor`) and extrapolates the plateau like the
  accumulation of a MOS capacitor (inversion charge `Q = int c dV`): `cox` = Cox W L; Cox per area and EOT with the
  DUT profile's W and L. Cmax alone lies below Cox W L (inversion-layer capacitance; more for thinner oxides).
- Use a frequency low enough that the channel follows, so its resistance does not cut the measured capacitance near
  threshold (the recipe default 100 kHz is an example; long channels need lower: the channel is an RC line).
- Split C-V also gives the inversion charge `Qi(Vg) = int Cgc dVg` for effective mobility (with an Id-Vg at small
  Vd on the same device): an ad-hoc analysis in `work/`.

## SCUU same-landing I-V and C-V

- With an SCUU (SMU CMU unify unit) the MFCMU and two SMUs share two triax outputs: `SSP chnum,4` connects
  CMUH/CMUL, `SSP chnum,3` both SMUs (PG p520 (4-202) "SSP"); the SMU in the slot below the MFCMU feeds output 1,
  the one two slots below output 2. I-V and C-V then run without re-landing (AN-CV p6 (6)).
- Pin map: terminals on `SCUU1.OUT1`/`OUT2` (example `moscap-scuu`); the station profile must record the SCUU
  `present: true` (bring-up L6), else plans are blocked on hardware (R-ROUTE-01).
- The C-V and correction recipes route both outputs to the MFCMU (`measure` phase), measure, set the MFCMU to 0 V and
  0 mVrms and route back to the SCUU's rest state (`rest` phase); the cleanup restores and verifies the rest state on
  every exit. The SSP switches the units on: the SCUU's modules never take CN (error 323).
- Corrections through the SCUU are their own records: run them with the SCUU pin map. Details on routes:
  [11](11-switching-routing.md#scuu-and-asu-paths).
- SMU work on the same landing (`moscap.qscv`, kind `smu_qscv`): the SMU roles bind to the outputs' SMU inputs
  (output 1 = SMU6, output 2 = SMU5 for CMU1 in slot 7); the run routes `SSP 7,3` (both SMUs; it switches them on) in
  phase `measure`, and the cleanup restores the rest state. A QSCV and an HF C-V of one landing give the high-low Dit
  without moving a probe (scenario `moscap_dit`).

## AC level dependence

- The MFCMU reports the fundamental of the current. On a curved C-V the reading at bias V0 with level Vac (rms) is
  the average of C over the swing `+-sqrt(2) Vac`: `C = C(V0) + C''(V0) Vac^2 / 4` to second order; flat C-V
  regions (accumulation, strong inversion) do not move, depletion and the FeCap peaks do.
- `moscap.cv_ac_level` steps the level (WACV) at one bias; `cv_ac_dependence` fits C against Vac^2: `c_small_signal`
  (C0), the curvature (`fit.d2c_dv2`) and `ac_limit`, the level where C departs from C0 by `tolerance` (1 %).
- Choose `ac_vrms` of C-V runs below `ac_limit` of the most curved region; a larger level averages the transition
  and shifts the flatband slightly. Noise falls with the level (a fixed current error over a larger signal).

## Pulsed C-V

- `moscap.pulsed_cv` rests the gate at `v_base` and pulses it to each level (PWDCV; width >= 8 ms above 200 kHz,
  10 ms up to 200 kHz, 50 ms up to 10 kHz; period 0 = width + 2 ms; PG p487-488 (4-169) "PTDCV"); C is read during
  the pulse.
- From an accumulation base each point starts with no inversion charge and with emptied border traps: in inversion
  the pulse is shorter than the inversion-layer formation, so C stays below the HF minimum (deep depletion; the
  1/C^2 line continues, a deeper doping profile); in accumulation and depletion it equals a DC C-V swept from the
  same state (`cv_pulsed_vs_dc`: `delta_vfb` about 0, `cox_ratio` about 1, `c_ratio_inversion` < 1).
- A DC sweep that starts in inversion charges the border traps: its Vfb then differs from the pulsed one by the
  hysteresis. Compare like with like.

## C-f and frequency dispersion

- At a depletion bias interface traps exchange carriers with the bands with time constant `tau = 1/(sigma v_th
  p_s)` (p substrate): below `1/(2 pi tau)` they add capacitance (C falls with frequency: `c_dispersion`) and a
  conductance; towards midgap tau grows (peak at lower f), towards flatband it shrinks.
- `cf_dispersion` (conductance method): `Gp/w = w Cox^2 Gm / (Gm^2 + w^2 (Cox - Cm)^2)` from the measured Cm, Gm;
  continuum model `Gp/w = q A Dit ln(1 + (w tau)^2) / (2 w tau)`, peak `0.402 q A Dit` at `w tau = 1.98` (single
  level: `q A Dit / 2` at `w tau = 1`), fitted over the list: `dit`, `tau_it`, `f_peak`, `gp_w_max`.
- Cox: `options.cox_f` (the `cv_cox` result of a C-V) is better than the geometry estimate (`3.9 eps0 A / tox`,
  warned). Series resistance raises G at high frequency: `rs_ohm`. A peak outside the list fails: move the bias.
- One bias = Dit at one energy. Dit(E) over the gap: many biases (`dit_conductance`) or QSCV + HF (`dit_high_low`):
  [Dit over the band gap](#dit-over-the-band-gap).

## C-t and deep-depletion recovery

- `moscap.ct`: base (accumulation) for `hold_base_s`, step to the bias (inversion side), sample C every
  `interval_s` (MDCV, MTDCV; time stamps, `t_s` from the step). At the step no inversion charge exists: deep
  depletion, C below the HF minimum; thermal generation forms the inversion layer and C rises to equilibrium.
- In the depletion approximation 1/C^2 is linear in the inversion charge, so `ct_recovery` fits `1/C^2 = y_inf +
  (y0 - y_inf) exp(-(t/tau)^beta)`: `tau_recovery`, `beta` (1: one time constant), `c_initial`, `c_final`.
  A generation lifetime needs the doping and the Zerbst plot (ad-hoc, `work/`).
- Records longer than 60 s run as chained 25 s blocks holding the bias (time stamps run on); over 300 s async.
  Light generates carriers too: keep the shield box closed (S0).

## Quasi-static C-V

- QSCV (`moscap.qscv`, MM 13; PG p115-117 (2-27)): an SMU (not the MFCMU) steps the gate and, at every step,
  integrates the charge a small transition `cvoltage` moves over `cinteg`: `C = (I - Leak) cinteg / (V - V0)`. The
  leakage is measured before and after the transition (`linteg`) and interpolated to it (`QSL 1,1`, normal mode;
  `operation: compatible` = 4155C/4156C formula). Start and stop are not measured; the step must divide the span.
- It is the low-frequency curve: interface traps and (with enough time) the inversion layer follow. The curve
  dips in depletion (towards midgap), where `q Dit A` adds in parallel to the semiconductor capacitance in series
  with Cox, and rises back to Cox in inversion; a sweep from
  inversion to accumulation after `hold_s` stays in equilibrium (long generation times need a longer hold).
- Range `irange_a` (QSR, fixed): the charge current `C cvoltage / cinteg` plus the leakage must fit (an MPSMU from
  1 nA; a 1 GOhm path leak at 2 V is 2 nA: 10 nA range); compliance or overflow aborts the sweep (error 242).
- Offset: `offset: measure` (probes lifted, `physical_setup`) stores the path's guard capacitance in the instrument
  (`QSZ 2`; its size for this station is recorded at bring-up L6, `TODO(verify)[L6.A6]`); later runs with
  `offset: cancel` subtract it (`QSZ 1`). Without it C reads high by
  the offset: small for Cox, a bias of the high-low Dit (it lands on `C_LF`).
- Methods: `cv_cox` (accumulation extrapolation, as for HF), `plot_cv` (C and leakage against `dc_v`),
  `dit_high_low` with an HF C-V; flatband, doping and Vth refuse a QSCV run (they need the HF curve).

## Dit over the band gap

- High-low (`dit_high_low`, two-run, `options.reference_run`, either order): QSCV and HF C-V of the same device and
  landing; Cox, Vfb, Nsub, phi_B from the HF fit; `Dit = [C_LF Cox/(Cox - C_LF) - C_HF Cox/(Cox - C_HF)] / (q A)`;
  band bending from the LF curve (Berglund: `psi = int_Vfb^V (1 - C_LF/Cox) dV`), energy `e = psi - phi_B`. Window
  `6 kT/q <= psi <= 2 phi_B - 4 kT/q` (depletion: closer to flatband fast traps already follow the HF signal, deeper
  the minority carriers add to C_LF). Results: `dit_mid` (midgap), `dit_mean`, `dit_min`, `dit_max`; `fit` holds the
  profile every 0.05 eV (`e<k>`, `dit<k>`). Needs `geometry.area_um2`.
- Conductance (`dit_conductance`, `moscap.cv_multi_freq`): at each bias `Gp/w` over the frequencies, continuum fit
  -> Dit and tau; a bias counts when its peak lies inside the band. Energy from the HF depletion width (`psi = q N
  W^2 / (2 eps_s) + kT/q`). At room temperature 1 kHz..1 MHz reaches only the traps about 0.15-0.35 eV from midgap
  towards the majority band for a capture cross-section near 1e-16 cm^2 (v_th 1e7 cm/s, ni 1e10 cm^-3 assumed; each
  decade of sigma shifts it by about 0.06 eV; tau grows e-fold per kT/q towards midgap); midgap needs high-low (or a
  cold chuck).
- The two methods should agree where they overlap; a C_LF above C_HF in accumulation, negative Dit or a step in the
  profile mean the curves are not of one state (hysteresis, a re-landing, stale corrections, an uncancelled offset).
- Charge pumping (`mosfet.charge_pumping`, card `spgu/charge-pumping`) gives a mean Dit of a MOSFET's channel.

## FeCap C-V butterfly

- A ferroelectric capacitor's small-signal C is the dielectric part plus the reversible polarization response
  `dP/dV` of the branch being travelled: a peak near +Vc while the bias rises, near -Vc while it falls (two "wings").
- `fecap.cv_butterfly` (MM 18 double, beyond +-2 Vc); `cv_butterfly`: per branch the peak (parabola vertex):
  `vc` = half the peak distance, `v_imprint` = the mean (built-in field, imprint), `ec = vc / t` with
  `geometry.tox_nm` as the film thickness. The sweep poles and cycles the film: record the history.
- The butterfly gives the coercive voltage, not Pr; PUND through the WGFMU gives the switching charge
  ([04](04-ferroelectric-oxide.md#fecap-p-v-and-pund)).

## Reporting C-V results

- Measured: the C-V table (pair, frequency, AC level, DC bias), status counts, correction ages (summary `corr`)
  and, when asked, the correction runs' data read-back (`open_cp_f`, `short_rs_ohm`).
- Derived (method, window, options): Cox (and EOT), Nsub (depth window), Vfb (C_FB), Vth (method), hysteresis,
  plateau Cox W L and floor; Dit, tau and the Cox used (C-f); tau_recovery (C-t); C0 and ac_limit; Vc, Ec, imprint;
  QSCV Cox and the offset mode; Dit(E) (method, energy window, both run ids of high-low).
  Say SIMULATED for simulator runs and name the geometry used.
- Red flags: Cmax rising with falling frequency (series R or leakage), G/w peaks in depletion (traps), C below Cmin
  in inversion (deep depletion), a stretched transition (interface traps), status `U`/`D` (unbalance, saturation).
