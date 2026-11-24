---
domain: 08-capacitance-cv
maturity: seed
sources:
  - blueprint v2 2.7 (kind cmu_measure), 2.10 (cv.py), 3.2 (MFCMU catalogue), 4.2 (moscap, mosfet +cv targets)
  - "B1500 Programming Guide Ed. 15 (PG), PDF pages cited inline"
  - "AN-CV: IV and CV with the MFCMU and SCUU (application note), PDF pages cited inline"
  - Nicollian & Brews, MOS Physics and Technology (Wiley 1982) ch. 5, 9; Sze & Ng, Physics of Semiconductor Devices (2007) ch. 4
  - Koomen, Solid-State Electron. 16, 801 (1973); Sodini et al., Solid-State Electron. 25, 833 (1982) (split C-V)
  - src/b1500_test_agent/analysis/cv.py, catalog/kinds/cmu_measure.py (v2 WP8.3)
last_reviewed: null
---

# Capacitance and C-V (knowledge domain 08)

What the MFCMU measures, how a C-V curve becomes Cox, doping, flatband and threshold voltage, and what the split
C-V of a MOSFET adds. The definitions are those of `analysis/cv.py` (its module docstring is the source); every
value they return is derived. Debugging (distortion, series resistance, stale corrections) is skill `b1500-debug`.

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
- [Reporting C-V results](#reporting-c-v-results)

## Scope and status

- Recipes (kind `cmu_measure`): `cmu.spot` (MM 17 spot C), `moscap.cv` (MM 18 C-V, single or double),
  `mosfet.cgc_cv`, `mosfet.cgd_cv` (split C-V). Methods: `cv_cox`, `cv_flatband`, `cv_doping_profile`, `cv_vth`,
  `cv_hysteresis`, `impedance_convert`, `plot_cv`.
- Not covered here: pulsed C-V, C-f, C-t, AC-level sweeps, QSCV and interface-trap density (conductance and
  high-low methods). Those arrive with the C-V variants and the Dit work packages and extend this file.
- Every C-V run needs fresh phase, open and short corrections of the same pin map (rule R-CORR-01; card
  `cmu/cmu-correction`).

## Impedance models Cp-G Cs-Rs Z-theta

- The MFCMU returns one parameter pair per point (`IMP`, PG p441 (4-123) "IMP"; Table 4-16, PG p347 (4-29)):
  `cp_g` (default for C-V), `cp_d`, `cs_rs`, `cs_d`, `z_theta` (theta in radian in the run table).
- Parallel and series forms describe the same admittance `Y = G + jwCp`, `Z = 1/Y = Rs - j/(wCs)`: `Cs = Cp (1 +
  D^2)`, `D = G/(wCp) = Rs w Cs`. For a good capacitor (D < 0.01) Cp and Cs agree within 0.01 %.
- A MOS capacitor is a parallel network (oxide, depletion, traps, leakage), so C-V uses Cp-G; a series resistance
  (substrate, back contact, probe) adds to Z and makes Cp fall at high frequency in accumulation.
- `impedance_convert` reports a run in another pair at one point per frequency and can remove a series resistance:
  given (`series_r: value`, `rs_ohm`) or estimated in strong accumulation (`series_r: accumulation`): `Rs =
  G_ma / (G_ma^2 + w^2 C_ma^2)` from the parallel values at the largest capacitance (Nicollian & Brews eq. 5.12).
  The C-V methods take `rs_ohm` to correct before extracting. Full converted curves: `convert_table` (ad-hoc,
  `work/<run_id>/`).

## Corrections and the measurement path

- Phase compensation, then open and short at every frequency the measurement uses, with the probes where the human
  puts them for the C-V (lifted, shorted); a re-landing or another pin map makes them stale.
- Uncorrected, the open capacitance of cables and probe (about 0.3 pF in the simulator) adds to every reading; the
  short path (resistance, inductance) matters above about 1 MHz and for large capacitances.
- Corrections act only at listed frequencies: list every C-V frequency in the correction recipes' `freqs_hz` (the
  23 default frequencies cover 1 kHz to 5 MHz in 1-2-5 steps).
- Known-capacitor check: `cmu.spot` on a reference capacitor reads its value within its tolerance after the
  corrections (bring-up stage L6).

## High-frequency C-V of a MOS capacitor

- Regions (p substrate; mirrored for n): accumulation (gate negative, C near Cox), depletion (Cox in series with a
  shrinking depletion capacitance), inversion (high frequency: minority carriers cannot follow, C stays at Cmin).
  Background: [01](01-device-physics.md#mos-capacitor-c-v-regions).
- Sweep from inversion towards accumulation (p substrate: + to -) with a hold at the start: the inversion layer is
  in equilibrium and excess carriers recombine as the bias falls. Sweeping from accumulation into inversion faster
  than the generation lifetime (ms to s) drives the surface into deep depletion: C falls below Cmin.
- 1 MHz is the usual high frequency; low frequencies (below about 1 kHz) let minority carriers and traps respond.
- MFCMU limits: 1 kHz to 5 MHz, 10 to 250 mVrms, DC bias within +-25 V (UG p73 (2-33) "MFCMU"). Keep the AC level
  small (10 to 50 mVrms) against the bias resolution; more than 50 mVrms needs `soft_cmu` confirmation.

## Oxide capacitance and EOT

- Cmax is Cox in series with the accumulation-layer capacitance, so it lies a few % below Cox for thin oxides
  (about 3 % for 5 nm SiO2 at 1.6 V beyond flatband).
- `cv_cox` extrapolates: in strong accumulation `Cs = Q/(2 kT/q)`, so `1/C = 1/Cox + 2 (kT/q) / Q` with the
  accumulation charge `Q`. Over the tail with `C >= acc_frac x Cmax` (default 0.85) `Q = Q0 + int C dV`, the offset
  Q0 is chosen for the straightest line of 1/C against 1/Q, and the intercept is 1/Cox. No flatband voltage needed.
- `EOT = 3.9 eps0 A / Cox` and Cox per area need the DUT profile's `geometry.area_um2`; without it only Cox (F).
- Too few strong-accumulation points: sweep further into accumulation (within the DUT envelope) or use more points.

## Doping from 1/C^2

- In depletion `1/C^2 = 1/Cox^2 + 2 (V - Vfb - kT/q) / (q eps_s N A^2)` exactly, so `N = 2 / (q eps_s A^2
  |d(1/C^2)/dV|)` from the slope; depth `W = eps_s A (1/C - 1/Cox)`.
- `cv_doping_profile` fits the slope only where the band bending `psi = |int_Vfb^V (1 - C/Cox) dV|` lies between
  4 kT/q and `2 phi_B - 3 kT/q` (`phi_B = (kT/q) ln(N/ni)`): nearer flatband the Debye tail, nearer threshold the
  inversion charge bend the line. Silicon `eps_s = 11.7 eps0`, `ni = 1e10 cm^-3`, 300 K (options).
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
  `d^2 Cgc / dVg^2` in the rising part. It agrees with the 2 phi_B threshold within a few tens of mV; an I-V Vth
  (linear extrapolation, constant current) of the same device differs by definition: report the method.

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
  DUT profile's W and L. Cmax alone lies 1-3 % low (inversion-layer capacitance).
- Use a low frequency (100 kHz) so the channel resistance does not cut the measured capacitance near threshold;
  long channels need lower frequencies (the channel is an RC line).
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

## Reporting C-V results

- Measured: the C-V table (pair, frequency, AC level, DC bias), status counts, correction ages (summary `corr`).
- Derived (method, window, options): Cox (and EOT), Nsub (depth window), Vfb (C_FB), Vth (method), hysteresis,
  plateau Cox W L and floor. Say SIMULATED for simulator runs and name the geometry used.
- Red flags: Cmax rising with falling frequency (series R or leakage), G/w peaks in depletion (traps), C below Cmin
  in inversion (deep depletion), a stretched transition (interface traps), status `U`/`D` (unbalance, saturation).
