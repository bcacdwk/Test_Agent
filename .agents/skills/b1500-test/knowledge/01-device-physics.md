---
domain: 01-device-physics
maturity: seed
sources:
  - deck slide 4 (domain list)
  - deck slide 10 (domain 1 seed)
  - deck slide 6 (Vth example)
  - deck text PPT_slides_content.md (domain 1 page; 60 mV/dec, n = 1 vs 2)
  - "standard device physics: S. M. Sze, K. K. Ng, Physics of Semiconductor Devices, 3rd ed. (not page-checked)"
  - "D. K. Schroder, Semiconductor Material and Device Characterization, 3rd ed. (not page-checked)"
last_reviewed: null
---

# Device physics (knowledge domain 1)

Seeded from deck slide 10. What the quantities mean physically and which bias regions they come from. How the
code computes each derived value is in [06](06-analysis-extraction.md); this file never overrides it. Textbook
formulas below are standard but the file is not human-reviewed yet (`maturity: seed`); numbers marked
`TODO(verify)` are typical values, not limits. Limits come only from the DUT profile, the policy and the recipe.

## Scope and conventions

- Sign convention: currents flowing into the DUT terminal from the SMU are positive (SMU convention). PMOS and
  reverse-biased junctions therefore show negative voltages and currents; methods use magnitudes where noted.
- Thermal voltage Vt = kT/q = 25.85 mV at 300 K (25.69 mV at 25 °C). ln(10) Vt = 59.5 mV at 300 K.
- "Measured" = a V or I read by an SMU with its status letter. "Derived" = anything computed (R, n, Vth, gm, SS,
  MW). Reporting rules: [06](06-analysis-extraction.md#reporting-rules-measured-versus-derived).

## Resistor contact versus bulk resistance

Seeded from deck slide 10 (Ohm's law, temperature coefficient, contact vs bulk).

- Ohm's law V = I R; a DUT resistor is the slope of a straight I-V line through the origin. Bulk resistance
  R = rho L / A = Rsh L / W (Rsh = rho / t, sheet resistance in ohm/sq).
- Temperature coefficient: R(T) = R0 (1 + alpha (T - T0)). Metals: alpha about +0.004 /K; doped semiconductor and
  thin-film resistors can be negative. A drifting R during a sweep can be self-heating (P = V I).
- A two-wire measurement reads R_meas = R_DUT + 2 R_contact + R_leads. It cannot separate contact from bulk.
  - Kelvin (four-wire) sensing removes leads and contacts for low R:
    [03](03-probe-station-wiring.md#kelvin-four-wire-connection).
  - Transfer length method (TLM): R_T(L) = 2 Rc + Rsh L / W over several pad spacings; intercept = 2 Rc, slope =
    Rsh / W. Needs a dedicated structure and several landings (no v1 recipe).
- Probe-to-pad contact resistance on clean metal pads is typically below about 1 ohm (deck text for slide 12)
  `TODO(verify)` for this station's probes and pad metal.
- Shape tells the contact story: straight and symmetric = ohmic; curved or asymmetric (S-shape, rectifying) =
  barrier at a contact (native oxide, Schottky-like metal/semiconductor), too little overdrive, or a damaged pad.
- Offset current at 0 V means leakage paths, bias from another channel, or instrument offset; an offset voltage
  can be thermoelectric (microvolts) and matters only for very low R.
- Open, short and in-range classification of a landing is done by the `resistance` analysis method:
  [06](06-analysis-extraction.md#resistance-fit); the physical checks are in
  [03](03-probe-station-wiring.md#contact-checks).

## Capacitor models Cs-Rs and Cp-G

Seeded from deck slide 10. Background only: C-V and C-f kinds are reserved in v1 (MFCMU needs correction, SCUU and
leakage flows first).

- Parallel plate: C = eps0 epsr A / d (eps0 = 8.854e-14 F/cm). Impedance |Z| = 1 / (2 pi f C).
- Charging time constant tau = R C. A swept voltage drives a displacement current I = C dV/dt through any
  capacitance, which adds to DC leakage in slow I-V sweeps of large-area capacitors (example: 100 pF at 1 V/s =
  100 pA).
- Series model Cs-Rs suits low impedance (large C, high f) where series resistance dominates the loss; parallel
  model Cp-G suits high impedance (small C, low f) or leaky dielectrics where shunt conductance dominates.
  Rule of thumb |Z| < about 100 ohm: series, |Z| > about 10 kohm: parallel `TODO(verify)` (Keysight impedance
  measurement guidance). The MFCMU initial setting is Cp-G (Programming Guide Table 2-13, PDF 180).
- Conversion: D = 2 pi f Cs Rs = G / (2 pi f Cp); Cp = Cs / (1 + D^2).

## PN diode Shockley equation and ideality factor

Seeded from deck slide 10 and the deck text (n = 1 diffusion, n = 2 recombination).

- Shockley with series resistance: I = Is [exp((V - I Rs) / (n Vt)) - 1].
- Ideality factor n: n = 1 when diffusion current dominates (low injection, quasi-neutral regions); n -> 2 when
  Shockley-Read-Hall recombination in the depletion region dominates (low forward bias) and again at high
  injection. n clearly above 2 points to tunneling, shunt paths or several junctions `TODO(verify)`.
- In the exponential region log10 I is linear in V with slope 1 / (ln(10) n Vt): 59.5 n mV per decade at 300 K, so
  n = 1 / (ln(10) Vt S) for a slope S in decades per volt. Is is the intercept of that line at V = 0.
- Is is strongly temperature dependent (scales with ni^2); compare Is only at the same temperature.
- Typical small silicon junction: Is from about 1e-15 to 1e-12 A depending on area and doping, n from 1.0 to
  1.2 in the diffusion region `TODO(verify)`.

## Diode series resistance reverse leakage and breakdown

- Series resistance Rs bends the forward curve at high current: V - n Vt ln(I / Is + 1) = I Rs. It includes the
  probes and cables in a two-wire measurement (see the resistor section).
- Shunt resistance shows at low forward and low reverse bias as a linear I = V / Rsh floor.
- Reverse leakage: ideal current saturates at -Is; real silicon junctions at room temperature are dominated by
  depletion-region generation (grows roughly with the square root of the reverse voltage) plus surface and
  perimeter leakage. Area versus perimeter scaling across device sizes separates bulk from edge leakage.
- Breakdown voltage BV: the reverse voltage at which |I| reaches a stated criterion current (for example 1 uA; the
  criterion must be reported). Avalanche (lightly doped, BV above about 6 V in Si, positive temperature
  coefficient) versus Zener tunneling (heavily doped, below about 5 V, negative coefficient) `TODO(verify)`.
- Breakdown can be destructive. v1 diode measurements stop before it (compliance plus automatic abort); a breakdown
  test is a separate destructive recipe that always needs confirmation and does not exist in v1.
- Schottky (metal-semiconductor) diodes follow thermionic emission:
  I = A A** T^2 exp(-q PhiB / kT) [exp((V - I Rs) / (n Vt)) - 1], n about 1.0 to 1.1 for good contacts; barrier
  height PhiB = Vt ln(A A** T^2 / Is) (A** Richardson constant, about 112 A cm^-2 K^-2 for n-Si `TODO(verify)`).
  Reverse leakage is larger than for a pn junction and grows with reverse bias (image-force lowering).

## MOSFET threshold voltage definitions

Seeded from deck slides 6, 10 and 15 ("three common extraction methods").

- Physical definition (NMOS): the gate voltage at which the surface reaches strong inversion,
  Vth = Vfb + 2 phiF + Qdep / Cox with phiF = Vt ln(NA / ni). Not directly measurable; every measured Vth is a
  method-dependent number, so a Vth without its method is meaningless.
- Long-channel linear region (small Vd): Id = mu Cox (W/L) (Vg - Vth - Vd/2) Vd. A straight line through the
  steepest part of Id(Vg) crosses Id = 0 at Vg0 = Vth + Vd/2, hence Vth = Vg0 - Vd/2 (linear extrapolation).
- Saturation: Id = (mu Cox W / 2L) (Vg - Vth)^2 (1 + lambda Vd); extrapolating sqrt(Id) gives a saturation Vth
  (no v1 method).
- Method families (code definitions in [06](06-analysis-extraction.md)):
  - linear extrapolation at maximum gm (deck slide 6 default; v1 M1 method);
  - constant current: Vg where Id = Icrit x W/L, Icrit typically 10 to 100 nA (deck: W/L x 100 nA);
  - maximum gm: Vg at the gm peak (simple, but sits above the extrapolated Vth);
  - second derivative of Id (not implemented).
- Methods differ by tens to hundreds of mV on the same curve; compare devices only with the same method, window,
  Vd and temperature.
- Short-channel and body effects: Vth falls with Vd (DIBL), rises with source-body reverse bias (body effect,
  Delta Vth = gamma (sqrt(2 phiF + Vsb) - sqrt(2 phiF))). Use the same Vd and bulk bias for comparisons. A
  constant-current Vth at very small Vd also carries the weak-inversion drain factor 1 - exp(-|Vd|/U_T) (about
  +0.7 mV at Vd 0.1 V, +5 mV at 50 mV), which a two-point DIBL counts as barrier lowering: keep Vd_lo ≥ 0.1 V.
- PMOS: Vth negative, currents negative; the extraction uses |gm| and works for both polarities.

## MOSFET transconductance and mobility

- gm = dId/dVg at fixed Vd (deck slide 10). Linear region ideal: gm = mu Cox (W/L) Vd, so the field-effect
  mobility is muFE = L gm_max / (W Cox Vd) (needs W, L and Cox from the DUT profile or the human).
- Saturation: gm = mu Cox (W/L) (Vg - Vth); gm/Id is the transconductance efficiency (maximum in subthreshold).
- gm peaks and then falls because of mobility degradation at high vertical field and source/drain series
  resistance. A gm peak at the end of the sweep means the sweep stopped too early.
- Effective mobility needs the inversion charge from split C-V (reserved, CMU).

## MOSFET subthreshold swing

Seeded from deck slide 10 and the deck text (room-temperature limit 60 mV/dec).

- SS = dVg / d(log10 Id) = ln(10) Vt (1 + (Cd + Cit) / Cox), at least 59.5 mV/dec at 300 K for a conventional
  thermionic MOSFET; it scales with absolute temperature.
- Larger SS comes from interface traps (Cit = q Dit), a thick or low-k dielectric, short-channel effects, or a
  measurement that never reaches the steep part. Dit link: [05](05-reliability-defects.md#interface-traps-dit).
- Needs two or more decades of trusted current above the noise floor; a minimum below about 60 mV/dec at room
  temperature on an ordinary MOSFET is a red flag (noise steps, hysteresis, compliance on the gate, a ferroelectric
  or charge-trapping transient) until proven otherwise.
- Typical: Si bulk MOSFET 65 to 90 mV/dec; IGZO TFT 100 to 300 mV/dec (deck text) `TODO(verify)`.

## MOSFET on-off current ratio

- Ion: drain current at a stated on-state bias (for example Vg = Vdd, or Vth plus a fixed overdrive) and stated
  Vd. Ioff: drain current at a stated off-state bias (for example Vg = 0, or Vth minus a fixed underdrive).
  Ion/Ioff without both bias points is not reportable.
- Ioff is often limited by the measurement, not the device: SMU range and integration time (noise floor), gate
  leakage reaching the drain terminal, junction leakage, gate-induced drain leakage at negative Vg (NMOS). When
  Ioff sits at the noise floor, report it as an upper bound ("< x A") and the ratio as a lower bound.
- Oxide TFTs reach very low Ioff (pA and below) and ratios of 1e7 or more (deck text): use an HRSMU on the drain.

## MOSFET output characteristics

Seeded from deck slide 10 (Id-Vd linear and saturation regions).

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

Seeded from deck slide 10. Measured by `moscap.cv`; extraction: [08](08-capacitance-cv.md#high-frequency-c-v-of-a-mos-capacitor).

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
| epsr | SiO2 3.9, Si3N4 about 7, Al2O3 about 9, HfO2 about 20 to 25 | `TODO(verify)` for the owner's films |
| Cox of 1 nm SiO2 | 3.45 uF/cm^2 | scales with 1/tox |
| Si band gap, ni | 1.12 eV, about 1e10 cm^-3 at 300 K | |
