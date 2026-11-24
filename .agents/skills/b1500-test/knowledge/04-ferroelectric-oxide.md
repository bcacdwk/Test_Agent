---
domain: 04-ferroelectric-oxide
maturity: seed
sources:
  - deck slide 13 (domain 4 seed)
  - deck text PPT_slides_content.md (domain 4 page; FeFET and IGZO reference parameters)
  - deck slide 7 (pulse work priority after SMU I-V)
  - "ferroelectric HfO2 literature, e.g. T. S. Boescke et al., Appl. Phys. Lett. 99, 102903 (2011) (not page-checked)"
  - "oxide TFT literature, e.g. K. Nomura et al., Nature 432, 488 (2004) (not page-checked)"
  - references/manuals/structured/README.md (the WGFMU manual has no FeFET, FeCap or PUND workflows)
last_reviewed: null
---

# Ferroelectric and oxide semiconductors (knowledge domain 4)

Seeded from deck slide 13. FeFETs and FeCaps on hafnia-based ferroelectrics, and IGZO/ITO oxide TFTs. The deck asks
for literature extraction against the group's own data; until a human reviews this file every number here is a
typical literature value marked `TODO(verify)`, never a limit. Limits come from the DUT profile.

## Scope and v1 status

- v1 measures FeFETs only by an SMU double (dual) sweep: recipe `fefet.dual_sweep_mw`, card `fefet-dual-sweep-mw`.
- Pulse programming with the HV-SPGU through the 16440A selector and SMU reads: `fefet.pulse_write_read` (memory
  window from program/erase pulses) and `spgu.program_smu_read` (generic), card `fefet-pulse-write-read` (WP9.4).
  Switching kinetics, endurance, retention (WP9.5), WGFMU fast program/read and FeCap PUND (`fecap.pund`, reserved,
  `not_implemented`) follow. Never emulate them with sweep recipes.
- Oxide TFTs use the MOSFET recipes (`mosfet.idvg` lists `igzo_tft`); their quirks are below.

## Ferroelectric basics Ec Pr Ps

Seeded from deck slide 13.

- A ferroelectric has a spontaneous polarization that an electric field can reverse; P(E) is a hysteresis loop.
  Coercive field Ec: field at which P crosses zero. Remanent polarization Pr: P at zero field. Saturation
  polarization Ps: P at high field (loop tips). Coercive voltage Vc = Ec x t_FE.
- Hafnia/zirconia ferroelectrics (HfO2, ZrO2, Hf0.5Zr0.5O2 "HZO") are ferroelectric in the non-centrosymmetric
  orthorhombic phase, stabilised by doping (Si, Al, La, Zr), thickness (about 5-20 nm), capping and anneal (deck).
- Typical HZO: Ec about 1-1.5 MV/cm, Pr about 10-25 uC/cm^2, epsr about 30 `TODO(verify)`. Example: 10 nm with Ec
  1 MV/cm gives Vc about 1 V across the ferroelectric layer alone.
- Leakage and breakdown fields of thin hafnia are only a few times Ec, so the safe programming window is narrow
  (gate leakage envelope: [05](05-reliability-defects.md#gate-leakage-and-tddb-safe-envelope)).

## FeFET operation

- A FeFET puts the ferroelectric in the gate stack: metal-ferroelectric-insulator-semiconductor (MFIS, thin
  interfacial SiO2/SiON) or with an internal metal (MFMIS). The polarization adds charge at the channel and shifts
  Vth: for an n-channel FeFET, polarization pointing to the channel (after a positive gate excursion) lowers Vth
  ("program", low-Vth state); the opposite polarization raises it ("erase", high-Vth state).
- Only part of the gate voltage drops across the ferroelectric (capacitive divider with the interfacial layer and
  the semiconductor), so the gate voltage needed to switch is larger than Vc of the film alone.
- Competing effect: charge trapping in the interfacial layer and at the ferroelectric interface. Electrons
  injected at positive gate voltage raise Vth, which is the opposite direction of ferroelectric switching.

## FeFET memory window by dual sweep

Seeded from deck slide 13 ("memory window = Vth of the forward sweep minus Vth of the reverse sweep; measured by a
bidirectional Id-Vg sweep") and the deck text reference parameters.

- Double sweep at a small constant drain bias: gate from low to high (forward, `segment` fwd) and straight back
  from high to low (reverse, `segment` rev). Vth is extracted on each branch with the same method and window rule.
- Definition used by v1: MW = Vth_fwd - Vth_rev (code: [06](06-analysis-extraction.md#memory-window)).
- Sign is physics: for an n-channel FeFET, ferroelectric switching makes the forward branch turn on later than the
  reverse branch, so MW > 0. Charge trapping alone gives the opposite order (MW < 0); a mixture shrinks MW. Report
  the sign, never only the magnitude. P-channel devices reverse the picture `TODO(verify)`.
- Upper bound for a saturated loop is about 2 Ec t_FE (MFIS, full switching) `TODO(verify)`; for 10 nm HZO with
  Ec about 1 MV/cm that is about 2 V. Real stacks reach less (interfacial-layer voltage drop, trapping).
- The sweep amplitude decides how much of the loop is switched: sweeps smaller than the switching voltage give
  minor loops and a smaller MW; MW versus amplitude is a useful map, run one plan per amplitude.
- Deck reference parameters: gate about -3 V to +3 V (scale with Ec and film thickness), drain 50-100 mV,
  sweep rate matters. Actual ranges come from `list_recipes(recipe_id=...)` and the card; the DUT profile caps
  the gate voltage. Unknown film thickness or Ec: ask before choosing an amplitude.
- Report per branch: Vth (method, window), Ion/Ioff, the sweep start state and loop index, amplitude, points,
  integration preset. Compare windows only between runs with identical sweep settings.

## Read disturb and sweep-rate effects

- A full-amplitude dual sweep is itself a write: it programs and erases the device. The state after a run is the
  state the last branch left. A read that must not disturb uses gate voltages well inside the coercive range
  (minor-loop-free read window) `TODO(verify)` for the owner's stacks.
- The first loop after landing or after a long pause can differ from later loops (wake-up, relaxation, imprint);
  record which loop a value comes from.
- Sweep rate: ferroelectric switching is time dependent (nucleation-limited switching), and trapping/detrapping is
  slow, so the MW depends on how long each point takes. In v1 the effective rate follows from the number of points,
  the integration preset and hold/delay times; keep them fixed when comparing devices.
- Displacement current (C dV/dt of the gate stack) and switching current flow in the gate during the sweep; drain
  current is the measured quantity, so keep the drain bias small and the gate compliance low.

## Pulse write read endurance and retention

Pulse write/read implemented (`fefet.pulse_write_read`, WP9.4, card `fefet-pulse-write-read`; the mechanics are in
[09](09-pulse-spgu-selector.md#program-and-read)); endurance and retention recipes follow (WP9.5). Seeded from deck
slide 13 and the deck text.

- Program and erase with short gate pulses (HVSPGU through the 16440A selector; WGFMU later), read with an SMU Id-Vg
  sweep. Deck text: pulse amplitude 3-5 V, width 100 ns to 10 us `TODO(verify)` per stack.
- Endurance: Vth (or MW) after N program/erase cycles; the window closes by fatigue or breakdown. Retention: Vth
  of each state versus time after writing; imprint shows as an asymmetric drift.
- The write-pulse envelope comes from the DUT profile's gate `pulse` block (amplitude, width, duty, count), reviewed
  by a human against film thickness and coercive field; never widen it to reach a larger window.

## FeCap P-V and PUND

Reserved (`fecap.pund`, `not_implemented`). Seeded from deck slide 13. The coercive voltage is measurable now by the
MFCMU C-V butterfly (`fecap.cv_butterfly`, card `fecap-pund`; [08](08-capacitance-cv.md#fecap-c-v-butterfly)).

- P-V loop: apply a triangular voltage across the capacitor and integrate the current: P = (1/A) integral of I dt.
  Leakage and linear (dielectric) displacement current distort the loop and fake extra polarization.
- PUND (positive-up-negative-down): four pulses P, U, N, D. P and N switch the polarization, U and D (same sign as
  the pulse before) do not. Switching charge = Q(P) - Q(U) and Q(N) - Q(D); this removes non-switching current, so
  2 Pr is about (Q(P) - Q(U)) / A `TODO(verify)` convention.
- Wiring: top electrode to a WGFMU channel (pulse and fast current sampling), bottom electrode to the second
  channel or ground; short leads, as the switching current lasts microseconds or less.

## IGZO and oxide TFT specifics

Seeded from deck slide 13 and the deck text (typical values and reference parameters).

- n-type amorphous oxide semiconductors (a-IGZO, ITO, IZO); the TFT works in accumulation. Three terminals (gate,
  source, drain): there is no body contact, and the back channel (the semiconductor surface away from the gate)
  can conduct. Map gate, drain and source only; `mosfet.idvg` has no bulk role.
- Typical (deck text): mobility 5-50 cm^2/Vs, SS 100-300 mV/dec, Ioff at pA level or below, on/off ratio 1e7 or
  more `TODO(verify)`. Vth may be negative (depletion-mode) or positive depending on process.
- Very low Ioff needs the HRSMU on the drain, guarding and long integration; otherwise Ioff is the instrument
  floor (report it as an upper bound).
- Environment sensitive: water and oxygen adsorption on the back channel, temperature, and light (photo-excited
  oxygen vacancies, negative-bias illumination instability). Keep the shield box closed and dark, record ambient
  temperature and humidity if known (deck: IGZO is sensitive to moisture).
- Bias stress during the measurement itself shifts Vth; prefer the smallest sufficient gate range and short
  measurement time, and do not repeat sweeps rapidly on the same device when comparing Vth. Mechanisms:
  [05](05-reliability-defects.md#igzo-instability-mechanisms).
- Hysteresis in oxide TFTs is mostly charge trapping (clockwise, forward branch left of the reverse branch).
- Deck reference parameters: Vgs -10 V to +20 V (adjust to Vth), Vds 0.1 V (linear region) and 1-10 V
  (saturation), compliance 1 mA to avoid channel burn-out. In v1, `mosfet.idvg` allows gate voltages only within
  its recipe range and every plan stays at or below the policy limits (42 V hard; above 10 V needs confirmation).
  A gate sweep beyond the recipe range is blocked: explain it and offer the in-range sweep; changing ranges or
  limits is a human decision, never a plan parameter.
- Oxide TFT versus Si MOSFET: thicker gate dielectrics (larger voltages for the same field), larger SS, Vth that
  depends on history and environment, possible self-heating at high Vds on glass or flexible substrates, and gate
  leakage through a shared bottom gate on test chips.
