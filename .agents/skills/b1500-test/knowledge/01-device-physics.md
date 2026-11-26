---
domain: 01-device-physics
maturity: seed
sources:
  - "deck slides 4, 6, 10 and the deck text: topics only (illustrative, not evidence: owner 2026-11-26)"
  - "textbook device physics: relations, bounds and method conventions (no page-checked book in the repository;
    literature values carry TODO(cite))"
  - "manual pages cited inline: EX p317 (4-23), PG p180 (2-92), PG p337 (4-19)"
  - "lab data: lwp/matlab_B1500/IdVg_test_2025100*.csv (Id-Vg at Vd 0.1 V and open-probe runs, October 2025) and
    their offline fit in config/sim/scenarios/lab_nmos_2025.yaml"
last_reviewed: null
---

# Device physics (knowledge domain 1)

What the quantities mean physically and which bias regions they come from. How the code computes each derived
value is in [06](06-analysis-extraction.md); this file never overrides it. The textbook relations and bounds below
are standard, but the file is not human-reviewed yet (`maturity: seed`). A number without a source is left blank
with a marker that says how to get it, and a blank is never an expectation ([README](README.md#conventions)).
Limits come only from the DUT profile, the policy and the recipe.

## Scope and conventions

- Sign convention (the usual SMU convention): currents flowing into the DUT terminal from the SMU are positive.
  PMOS and reverse-biased junctions therefore show negative voltages and currents; methods use magnitudes where
  noted.
- Thermal voltage Vt = kT/q = 25.85 mV at 300 K (25.69 mV at 25 °C). ln(10) Vt = 59.5 mV at 300 K.
- "Measured" = a V or I read by an SMU with its status letter. "Derived" = anything computed (R, n, Vth, gm, SS,
  MW). Reporting rules: [06](06-analysis-extraction.md#reporting-rules-measured-versus-derived).

## Resistor contact versus bulk resistance

- Ohm's law V = I R; a DUT resistor is the slope of a straight I-V line through the origin. Bulk resistance
  R = rho L / A = Rsh L / W (Rsh = rho / t, sheet resistance in ohm/sq).
- Temperature coefficient: R(T) = R0 (1 + alpha (T - T0)). Metals: alpha positive, of order +0.004 /K
  (literature, `TODO(cite)`); doped semiconductor and thin-film resistors can be negative. A drifting R during a
  sweep can be self-heating (P = V I).
- A two-wire measurement reads R_meas = R_DUT + 2 R_contact + R_leads. It cannot separate contact from bulk.
  - Kelvin (four-wire) sensing removes leads and contacts for low R:
    [03](03-probe-station-wiring.md#kelvin-four-wire-connection).
  - Transfer length method (TLM): R_T(L) = 2 Rc + Rsh L / W over several pad spacings; intercept = 2 Rc, slope =
    Rsh / W. Needs a dedicated structure and several landings (no v1 recipe).
- The contact resistance of this station's tips on the owner's pads is unknown until bring-up measures it; no
  typical value is given: [03](03-probe-station-wiring.md#probe-contact-and-overdrive).
- Shape tells the contact story: straight and symmetric = ohmic; curved or asymmetric (S-shape, rectifying) =
  barrier at a contact (native oxide, Schottky-like metal/semiconductor), too little overdrive, or a damaged pad.
- Offset current at 0 V means leakage paths, bias from another channel, or instrument offset; an offset voltage
  can be thermoelectric (microvolts) and matters only for very low R.
- Open, short and in-range classification of a landing is done by the `resistance` analysis method:
  [06](06-analysis-extraction.md#resistance-fit); the physical checks are in
  [03](03-probe-station-wiring.md#contact-checks).

## Capacitor models Cs-Rs and Cp-G

Background for the MFCMU cards (C-V, C-f, C-t; corrections first): knowledge [08](08-capacitance-cv.md).

- Parallel plate: C = eps0 epsr A / d (eps0 = 8.854e-14 F/cm). Impedance |Z| = 1 / (2 pi f C).
- Charging time constant tau = R C. A swept voltage drives a displacement current I = C dV/dt through any
  capacitance, which adds to DC leakage in slow I-V sweeps of large-area capacitors (example: 100 pF at 1 V/s =
  100 pA).
- Series model Cs-Rs suits low impedance (large C, high f) where series resistance dominates the loss; parallel
  model Cp-G suits high impedance (small C, low f) or leaky dielectrics where shunt conductance dominates.
  Keysight's guidance: parallel mode (Cp-G, Cp-D) for small capacitances, |Z| about 100 ohm or more; series mode
  (Cs-Rs) for large capacitances, |Z| about 100 ohm or less (EX p317 (4-23)). The MFCMU initial setting is Cp-G
  (PG p180 (2-92), Table 2-13).
- Conversion: D = 2 pi f Cs Rs = G / (2 pi f Cp); Cp = Cs / (1 + D^2).

## PN diode Shockley equation and ideality factor

- Shockley with series resistance: I = Is [exp((V - I Rs) / (n Vt)) - 1].
- Ideality factor n: n = 1 when diffusion current dominates (low injection, quasi-neutral regions); n -> 2 when
  Shockley-Read-Hall recombination in the depletion region dominates (low forward bias) and again at high
  injection. n clearly above 2 points to tunneling, shunt paths or several junctions (`TODO(cite)`).
- In the exponential region log10 I is linear in V with slope 1 / (ln(10) n Vt): 59.5 n mV per decade at 300 K, so
  n = 1 / (ln(10) Vt S) for a slope S in decades per volt. Is is the intercept of that line at V = 0.
- Is is strongly temperature dependent (scales with ni^2); compare Is only at the same temperature.
- No typical Is or n is given here: Is scales with junction area and doping (compare only equal area and
  temperature), a checked literature range is missing (`TODO(cite)`), and the owner's diodes give their own values
  (`basic.diode_iv`).

## Diode series resistance reverse leakage and breakdown

- Series resistance Rs bends the forward curve at high current: V - n Vt ln(I / Is + 1) = I Rs. It includes the
  probes and cables in a two-wire measurement (see the resistor section).
- Shunt resistance shows at low forward and low reverse bias as a linear I = V / Rsh floor.
- Reverse leakage: ideal current saturates at -Is; real silicon junctions at room temperature are dominated by
  depletion-region generation (grows roughly with the square root of the reverse voltage) plus surface and
  perimeter leakage. Area versus perimeter scaling across device sizes separates bulk from edge leakage.
- Breakdown voltage BV: the reverse voltage at which |I| reaches a stated criterion current (for example 1 uA; the
  criterion must be reported). Avalanche (lightly doped, BV above about 6 V in Si, positive temperature
  coefficient) versus Zener tunneling (heavily doped, below about 5 V, negative coefficient) (`TODO(cite)`).
- Breakdown can be destructive. The diode I-V recipe stops before it (compliance and automatic abort); breakdown is
  measured only by the destructive recipes `basic.breakdown_search` and `dielectric.bdv` (card `tddb-bdv`), which
  always need confirmation.
- Schottky (metal-semiconductor) diodes follow thermionic emission:
  I = A A** T^2 exp(-q PhiB / kT) [exp((V - I Rs) / (n Vt)) - 1], n close to 1 for ideal thermionic emission (a
  quality threshold needs a source, `TODO(cite)`); barrier height PhiB = Vt ln(A A** T^2 / Is) (A** Richardson
  constant, about 112 A cm^-2 K^-2 for n-Si, `TODO(cite)`).
  Reverse leakage is larger than for a pn junction and grows with reverse bias (image-force lowering).

## MOSFET threshold voltage definitions

- Physical definition (NMOS): the gate voltage at which the surface reaches strong inversion,
  Vth = Vfb + 2 phiF + Qdep / Cox with phiF = Vt ln(NA / ni). Not directly measurable; every measured Vth is a
  method-dependent number, so a Vth without its method is meaningless.
- Long-channel linear region (small Vd): Id = mu Cox (W/L) (Vg - Vth - Vd/2) Vd. A straight line through the
  steepest part of Id(Vg) crosses Id = 0 at Vg0 = Vth + Vd/2, hence Vth = Vg0 - Vd/2 (linear extrapolation).
- Saturation: Id = (mu Cox W / 2L) (Vg - Vth)^2 (1 + lambda Vd); extrapolating sqrt(Id) gives a saturation Vth
  (no v1 method).
- Method families (code definitions in [06](06-analysis-extraction.md)):
  - linear extrapolation at maximum gm (the `mosfet.idvg` recipe's default analysis);
  - constant current: Vg where |Id| = Icrit x W/L; Icrit is a convention to report (code default 100 nA);
  - maximum gm: Vg at the gm peak (simple, but sits above the extrapolated Vth);
  - second derivative of Id (not implemented).
- Methods differ by tens to hundreds of mV on the same curve (the lab's October 2025 Id-Vg: 0.349 V linear
  extrapolation, 0.382 V maximum gm, 0.296 V at 10 nA; `config/sim/scenarios/lab_nmos_2025.yaml`); compare devices
  only with the same method, window, Vd and temperature.
- Short-channel and body effects: Vth falls with Vd (DIBL), rises with source-body reverse bias (body effect,
  Delta Vth = gamma (sqrt(2 phiF + Vsb) - sqrt(2 phiF))). Use the same Vd and bulk bias for comparisons. A
  constant-current Vth at very small Vd also carries the weak-inversion drain factor 1 - exp(-|Vd|/U_T)
  (Delta Vth = n U_T ln(1 / (1 - exp(-|Vd|/U_T))): about 0.55 n mV at Vd 0.1 V, 4 n mV at 50 mV, n the slope
  factor), which a two-point DIBL counts as barrier lowering: keep Vd_lo ≥ 0.1 V.
- PMOS: Vth negative, currents negative; the extraction uses |gm| and works for both polarities.

## MOSFET transconductance and mobility

- gm = dId/dVg at fixed Vd. Linear region ideal: gm = mu Cox (W/L) Vd, so the field-effect
  mobility is muFE = L gm_max / (W Cox Vd) (needs W, L and Cox from the DUT profile or the human).
- Saturation: gm = mu Cox (W/L) (Vg - Vth); gm/Id is the transconductance efficiency (maximum in subthreshold).
- gm peaks and then falls because of mobility degradation at high vertical field and source/drain series
  resistance. A gm peak at the end of the sweep means the sweep stopped too early.
- Effective mobility needs the inversion charge from split C-V (MFCMU card `mosfet-split-cv`).

## MOSFET subthreshold swing

- SS = dVg / d(log10 Id) = ln(10) Vt (1 + (Cd + Cit) / Cox), at least 59.5 mV/dec at 300 K for a conventional
  thermionic MOSFET; it scales with absolute temperature.
- Larger SS comes from interface traps (Cit = q Dit), a thick or low-k dielectric, short-channel effects, or a
  measurement that never reaches the steep part. Dit link: [05](05-reliability-defects.md#interface-traps-dit).
- Needs two or more decades of trusted current above the noise floor; a minimum below about 60 mV/dec at room
  temperature on an ordinary MOSFET is a red flag (noise steps, hysteresis, compliance on the gate, a ferroelectric
  or charge-trapping transient) until proven otherwise.
- No typical SS is given: the owner's devices are not on record (`TODO(owner)`: which device types and processes
  does the lab measure (Si MOSFET, IGZO or other oxide TFT, FeFET), and what device gave the October 2025 lwp Id-Vg
  curves?). That one lab curve (device type not recorded) shows about 210 mV/dec at Vd 0.1 V
  (`lwp/matlab_B1500/IdVg_test_20251001_*.csv`). The only fixed number is the 59.5 mV/dec bound at 300 K; compare
  with earlier runs of the same device type.

## MOSFET on-off current ratio

- Ion: drain current at a stated on-state bias (for example Vg = Vdd, or Vth plus a fixed overdrive) and stated
  Vd. Ioff: drain current at a stated off-state bias (for example Vg = 0, or Vth minus a fixed underdrive).
  Ion/Ioff without both bias points is not reportable.
- Ioff is often limited by the measurement, not the device: SMU range and integration time (noise floor), gate
  leakage reaching the drain terminal, junction leakage, gate-induced drain leakage at negative Vg (NMOS). When
  Ioff sits at the noise floor, report it as an upper bound ("< x A") and the ratio as a lower bound.
- Oxide TFTs can have very low Ioff (a literature range needs a source, `TODO(cite)`): measure the drain with an
  HRSMU (an MPSMU's smallest range is 1 nA without an ASU, PG p337 (4-19)). The lab's open-probe Id-Vg runs on an
  HRSMU read within about ±2e-13 A at 1 PLC (`lwp/matlab_B1500/IdVg_test_20251004_*.csv`).

## MOSFET output characteristics

- Linear (triode) region Vd < Vg - Vth: Id about mu Cox (W/L) (Vg - Vth) Vd; on-resistance
  Ron = dVd/dId at small Vd = 1 / (mu Cox (W/L) (Vg - Vth)) + Rsd.
- Saturation Vd >= Vdsat (= Vg - Vth for long channels; lower with velocity saturation): Id grows slowly with Vd
  through channel-length modulation (gds = dId/dVd about lambda Id) and DIBL. Output resistance ro = 1/gds;
  intrinsic gain = gm / gds.
- Red flags: negative gds at high power (self-heating, typical for TFTs and SOI), a kink (floating body), a sudden
  rise at high Vd (impact ionization, approaching breakdown), current that does not go to zero at Vd = 0 (offset,
  leakage, wrong source reference).
- Compliance: a C status in saturation truncates the family; the high-Vg curves carry the most power (P = Id Vd).

## MOS capacitor C-V regions

Measured by `moscap.cv`; extraction: [08](08-capacitance-cv.md#high-frequency-c-v-of-a-mos-capacitor).

- Regions (p-substrate): accumulation (Vg < Vfb, C about Cox), depletion (Cox in series with a growing depletion
  capacitance), inversion (low frequency or quasi-static: C returns to Cox; high frequency: C stays at Cmin).
- Cox = eps0 epsox A / tox; equivalent oxide thickness EOT = tox x 3.9 / epsr.
- Flat-band voltage Vfb = phi_ms - Qf / Cox (fixed charge Qf); found from the flat-band capacitance. A shift
  between up and down sweeps (hysteresis) indicates mobile or trapped charge.
- Interface traps stretch the curve along V and add a frequency-dependent hump:
  [05](05-reliability-defects.md#interface-traps-dit).

## Constants and typical magnitudes

| Quantity | Value | Note |
|---|---|---|
| kT/q | 25.85 mV at 300 K | 25.69 mV at 25 °C |
| ln(10) kT/q | 59.5 mV at 300 K | ideal SS; diode n = 1 slope per decade |
| eps0 | 8.854e-14 F/cm | |
| epsr | SiO2 3.9 (the EOT reference) | other films (Si3N4, Al2O3, HfO2, HZO) depend on film and process: epsr = Cox tox / (eps0 A) from a capacitor of known area and thickness (`moscap.cv`); literature values `TODO(cite)` |
| Cox of 1 nm SiO2 | 3.45 uF/cm^2 | scales with 1/tox |
| Si band gap, ni | 1.12 eV, about 1e10 cm^-3 at 300 K | material constants, `TODO(cite)` |
