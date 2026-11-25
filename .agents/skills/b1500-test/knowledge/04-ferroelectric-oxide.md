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
  - "NLS switching, e.g. A. K. Tagantsev et al., Phys. Rev. B 66, 214109 (2002); FeFET amplitude x width maps, e.g. H. Mulaosmanovic et al., ACS Appl. Mater. Interfaces 9, 3792 (2017) (not page-checked)"
  - AN-NVM (Keysight Advanced NVM Application Tests User's Guide; endurance and retention test flows)
last_reviewed: null
---

# Ferroelectric and oxide semiconductors (knowledge domain 4)

Seeded from deck slide 13. FeFETs and FeCaps on hafnia-based ferroelectrics, and IGZO/ITO oxide TFTs. The deck asks
for literature extraction against the group's own data; until a human reviews this file every number here is a
typical literature value marked `TODO(verify)`, never a limit. Limits come from the DUT profile.

## Scope and v1 status

- v1 measures FeFETs only by an SMU double (dual) sweep: recipe `fefet.dual_sweep_mw`, card `fefet-dual-sweep-mw`.
- Pulse programming with the HV-SPGU through the 16440A selector and SMU reads: `fefet.pulse_write_read` (memory
  window from program/erase pulses) and `spgu.program_smu_read` (generic), card `fefet-pulse-write-read` (WP9.4);
  `fefet.switching_kinetics` (amplitude x width grid or ISPP, card `fefet-switching-kinetics`), `fefet.endurance`
  and `fefet.retention` (card `fefet-endurance-retention`) (WP9.5). Through the WGFMU (WP10.6):
  `fefet.fast_program_read` (microsecond pulses and fast Id-Vg reads in one sequencer run, card
  `fefet-pulse-write-read`), FeCap PUND `fecap.pund` and its endurance `fecap.endurance_pund` (card `fecap-pund`).
  Never emulate them with sweep recipes.
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

Implemented: pulse write/read (`fefet.pulse_write_read`, WP9.4, card `fefet-pulse-write-read`), endurance and
retention (`fefet.endurance`, `fefet.retention`, WP9.5, card `fefet-endurance-retention`); the mechanics are in
[09](09-pulse-spgu-selector.md#program-and-read). Seeded from deck slide 13, the deck text and AN-NVM.

- Program and erase with short gate pulses (HVSPGU through the 16440A selector; WGFMU later), read with an SMU Id-Vg
  sweep. Deck text: pulse amplitude 3-5 V, width 100 ns to 10 us `TODO(verify)` per stack.
- **Endurance**: MW after N program/erase cycles. The film first opens (wake-up: pinned domains free up over 10^2 to
  10^4 cycles), then closes (fatigue: domain pinning, defect generation, interfacial-layer degradation), and a FeFET
  often fails earlier by charge trapping or breakdown of the interfacial layer; HZO FeFETs commonly reach 10^4 to
  10^6 cycles, capacitors far more `TODO(verify)`. Cycle with the same pulses as the reads' program/erase (bipolar,
  one cycle = one program + one erase), read at log-spaced cycle counts, and compare devices only at equal amplitude,
  width and cycling frequency (higher frequency, less fatigue per cycle in some stacks).
- The write-pulse envelope comes from the DUT profile's gate `pulse` block (amplitude, width, duty, count), reviewed
  by a human against film thickness and coercive field; never widen it to reach a larger window. 10^6 cycles are
  2 x 10^6 pulses: such plans need confirmation (`soft_pulse`, `dut_envelope` when the profile's `max_count` is
  smaller) and run asynchronously (`long_run`).

## Pulse switching kinetics

Recipe `fefet.switching_kinetics` (WP9.5, card `fefet-switching-kinetics`); fit definitions in
[06b](06b-analysis-time-pulse.md#switching-kinetics).

- Polycrystalline hafnia switches by nucleation-limited switching (NLS): independent regions nucleate reversed
  domains with a broad distribution of waiting times, so the switched fraction after a pulse of width `w` grows
  over decades of `w` rather than abruptly: `S(w) = 1 - exp(-(w / tau)^beta)`, `beta` about 0.5-1 for a broad
  distribution (KAI: 1-2 for single crystals) `TODO(verify)`.
- The switching time falls steeply with the field (Merz's law in field form): `tau(V) = tau0 exp((Va / |V|)^alpha)`,
  `alpha` about 2 for hafnia in several reports (fixed at 2 by default; free with three or more amplitudes); `tau0`
  is the high-field limit (sub-ns), `Va` the activation voltage. Report `tau(V)` at the measured amplitudes rather
  than only `tau0`, which is an extrapolation.
- Grid design: reset fully before every point (the opposite saturation, long enough), amplitudes spanning the
  coercive region up to the profile's limit, widths log-spaced from the shortest the source can give (HV-SPGU 10 ns
  with 8 ns edges) to beyond saturation (several `tau` at the lowest amplitude). ISPP (one reset, increasing
  amplitudes cumulatively) gives the program characteristic and `v50`, not NLS parameters.
- Below the coercive voltage a pulse only reaches a minor loop: the window an amplitude switches at saturation
  (`A(V)`) grows with the amplitude; the fit keeps one per amplitude. Wake the film up first (`precycles`): a pristine
  film switches less, and waking up during the grid would drift `A(V)`.
- Short pulses through cables and the 16440A: the edges and overshoot at the pad differ from the set values
  `TODO(verify)` at L7 with a scope; the shortest widths carry the largest relative error.

## Retention

Recipe `fefet.retention` (WP9.5, card `fefet-endurance-retention`); fit definitions in
[06b](06b-analysis-time-pulse.md#retention).

- After a write the polarization relaxes: depolarization field (the interfacial layer cannot fully compensate the
  ferroelectric charge), charge trapping that screens it, and imprint (a built-in bias that favours one state). Vth
  of each state drifts roughly linearly in `log t`; the window closes from both sides or, with imprint, mostly from
  one.
- Measure both states (write, then reads at log-spaced times, the gate unbiased between reads), first read at about
  1 s: a read right after the write disturbs a saturated state (the read sweep's top end clips it). Report the slope
  per decade of each state and of the window, and any extrapolation (to 10 years = 3.2 x 10^8 s) as a derived value
  with the decades extrapolated; data beyond the last read are a model, not a measurement.
- Temperature accelerates retention loss (bake tests at 85-125 C are the standard qualification `TODO(verify)`);
  this station measures at room temperature only.

## FeCap P-V and PUND

Implemented (WP10.6): `fecap.pund` and `fecap.endurance_pund` (card `fecap-pund`); the small-signal coercive voltage
also by the MFCMU C-V butterfly (`fecap.cv_butterfly`, card `fecap-cv-butterfly`;
[08](08-capacitance-cv.md#fecap-c-v-butterfly)).

- P-V loop: apply a triangular voltage across the capacitor and integrate the current: P = (1/A) integral of I dt.
  Leakage and linear (dielectric) displacement current distort the loop and fake extra polarization.
- PUND (positive-up-negative-down): a negative preset pulse poles the film, then four pulses P, U, N, D. P and N
  switch the polarization, U and D (same sign as the pulse before) do not. Switching charge = Q(P) - Q(U) and Q(N) -
  Q(D) = 2 Pr A; the U/D charge below the coercive field is the linear dielectric (C_lin). Definitions:
  [06b](06b-analysis-time-pulse.md#pund).
- Wiring (pin map `fecap-wgfmu`): top electrode on WGFMU 201 (forces the pulses), bottom electrode on WGFMU 202 at
  0 V (the current: the virtual ground), both through their RSUs; short leads, the switching current lasts the ramp.
- Choosing the waveform: amplitude 2-3 x Vc saturates the loop (within the DUT envelope; thin hafnia breaks down a
  few times Ec). The ramp sets dV/dt and so the current: peak switching current about A Ps dV/dt / (2 delta) plus
  C_lin dV/dt (10 us ramps to 3 V on 2500 um^2, Ps 25 uC/cm^2: about 0.2 mA, range 1 mA; 1 us ramps: 10 mA range).
  A triangle (`plateau` 0) resolves Vc best; `interval` 100 ns gives 200 points per 10 us ramp pair. Faster ramps
  raise the apparent Ec (switching kinetics) `TODO(verify)` on the lab's films.
- Every PUND cycles the film about 1.5 times; a pristine film wakes up (Pr grows over 10-1000 cycles) and fatigues
  later (Pr falls). Endurance by PUND: bipolar WGFMU cycling (`cycle_period`, `width`) with PUND reads at log-spaced
  cycle counts; the read is itself a cycle (no separate reference read). Record the cycle history of every device.

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
