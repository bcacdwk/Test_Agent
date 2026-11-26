---
domain: 03-probe-station-wiring
maturity: seed
sources:
  - deck slide 12 (domain 3 seed)
  - deck slide 2 (layer 1 physical safety)
  - deck text PPT_slides_content.md (domain 3 page; contact resistance below 1 ohm)
  - "B1500A User's Guide Ed. 17 (UG), PDF pages cited inline"
  - "B1500A Configuration and Connection Guide (CCG), PDF pages cited inline"
  - config/station.example.yaml (topology fields)
  - src/b1500_test_agent/analysis/resistor.py (kelvin_resistance; v2 WP7.1)
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Probe station and wiring (knowledge domain 3)

Seeded from deck slide 12, which itself notes that probe-station details still need the prober vendor's manual.
All physical work (landing, cabling, shield box, interlock) is done by the human. The agent explains, asks, and
uses safe software checks; it never claims a physical state it cannot observe. The station's real cabling is
recorded by a human in the station profile (`topology`); `station_status` shows it, `null` means unknown.

## Signal path from SMU to pad

- SMU force (and sense) -> triaxial cable -> connector plate on the shield box or prober -> manipulator or probe
  card -> probe needle -> DUT pad (deck slide 12).
- Standard cable lengths are 1.5 m or 3 m (CCG PDF 12-14); 0.4, 0.8 and 4 m triaxial cables exist too (CCG PDF 44).
  Longer cables add capacitance (slower settling, displacement current in sweeps) and more insulation leakage. The
  deck recommends 1.5 m and at most 3 m `TODO(verify)` against the specification for low-current ranges.
- Every interface (connector plate, manipulator coax, probe tip) can add leakage and noise; the weakest link sets
  the noise floor, so measure the floor of the actual path (see contact checks).

## Triaxial cables and terminals

- SMU terminals: Force, Sense, Guard, Circuit Common. Force, Guard and Sense normally sit at the same potential
  (UG PDF 9).
- Triaxial cable: centre conductor = signal, inner shield = guard (driven to the signal potential, so no leakage
  flows through the insulation), outer shield = circuit common (CCG PDF 44).
- BNC (coaxial) cables are not suitable below about nA level; use triaxial cables for low current (CCG PDF 44); the
  16494A triaxial cable in a low-noise environment maximises the guard effect (CCG PDF 46).
- GNDU: use the 16493L GNDU cable (4.2 A); an ordinary triaxial cable is rated 1 A (UG PDF 93, CCG PDF 46).
- Never connect Guard to anything: not to an output, circuit common, chassis or another guard. Doing so damages the
  SMU (UG PDF 93, CCG PDF 77). Guard carries the output voltage: do not touch it.

## Guard for low current

Seeded from deck slide 12 (guard driven to the signal potential; required for pA-level currents).

- A unity-gain buffer keeps the guard at the force potential, so no current flows between force and guard and the
  current measured equals the current at the DUT terminal (CCG PDF 76-77).
- Extend the guard (outer conductor of the probe coax) as close to the needle as possible; never connect it to the
  needle or the DUT (UG PDF 9, CCG PDF 76). This also reduces induced noise.
- Needed whenever the current of interest is in the pA range: gate leakage, Ioff, subthreshold region, reverse
  diode leakage, open-circuit floor checks. Without guarding, cable and fixture leakage adds to the reading and
  rises with the applied voltage (it looks like a resistive leak, I proportional to V).
- Low-current points also need settling time: charging the cable and fixture capacitance through a small current
  range is slow, so short integration or short delays show up as drift, `X` statuses or a sweep-direction offset.

## Kelvin four-wire connection

Seeded from deck slide 12 (separate force and sense; cancels cable and contact resistance).

- Force and Sense lines run separately to the DUT and meet at the pad (or as close to it as possible); the SMU
  regulates the voltage at the sense point, so the drop across cables, probes and contacts is excluded
  (CCG PDF 78-79, UG PDF 94). Sense-line residual resistance up to about 10 ohm does not matter (CCG PDF 79).
- Use it for low-resistance and high-current measurements (milliohm to ohm level, deck slide 12).
- Non-Kelvin (two-wire): connect Force only and leave Sense open (UG PDF 9, 94). The reading then includes leads
  and contacts, typically ohms in total, so a two-wire R below about 10 ohm says more about the contacts than the
  DUT `TODO(verify)` with this station's probes.
- Pin maps bind one channel per terminal; whether Sense is landed is a physical fact recorded in the station
  profile (`topology.kelvin`, per-cable `kelvin`). Recipe `resistor.kelvin_4w` (card `smu-spot-kelvin`) forces
  current and senses voltage on Kelvin roles (`kelvin: true`): they never go through a 16440A selector, whose SMU
  path is Force only (R-ROUTE-01). Without Sense landed the same recipe silently reads leads and contacts too.

## Four-wire resistance

Implemented (`kelvin_resistance`, M7; recipe `resistor.kelvin_4w`; the definition shared with
`src/b1500_test_agent/analysis/resistor.py`, kept here next to the wiring because the analysis file is at its line
budget).

- Least-squares line V = R·I + V0 of the sensed voltage against the forced current (defaults: the source current
  column that varies most and the measured voltage of the same role, `a_I`/`a_V`) over the trusted points: R
  (`resistance`, Ohm), offset voltage V0 (`offset_voltage`, V; thermoelectric and amplifier offsets, which ±I
  reversal removes from R), r2 (`linearity_r2`); `fit.residual_v` = residual standard deviation. Needs two distinct
  currents. Trust classes and refusals as in [06](06-analysis-extraction.md#run-table-and-trust-classes).
- `classification`: `open` = voltage compliance (status C): R ≥ |V|/|I| at the first such point (lower bound,
  nothing fitted); `short` = the voltage span is below 10x the residual: R ≤ 10 x residual / current span (upper
  bound); else `in_range`. A non-positive R with a clean signal: `failed` (sense swapped or not landed).
- R excludes leads and contacts only when Sense is landed at both pads ([above](#kelvin-four-wire-connection)); the
  two-wire fit of the same pads is `resistance` ([06](06-analysis-extraction.md#resistance-fit)).

## ASU and the 1 pA range

Seeded from deck slide 12.

- E5288A ASU (atto sense and switch unit): enables the 1 pA range of HRSMU or B1511B MPSMU and switches the DUT
  terminal between the SMU and an AUX input (UG PDF 44-45, 98). With an ASU all SMU measurements are Kelvin; the
  sense information returns over the ASU's D-sub cable (CCG PDF 81).
- Connect or disconnect the ASU only with the instrument off (UG PDF 57, 98). The ASU must stay with the SMU it
  was calibrated with (UG PDF 98).
- Commands: `SAP` path, `SAR` 1 pA auto range, `SAL` indicator (PG PDF 505-506), read back by `*LRN? 62`/`63`
  (PG PDF 451); after reset the path is SMU side and 1 pA auto ranging is disabled (PG Table 2-13, PDF 180); `CN`
  and `CL` also return the path to the SMU side. The station profile declares an ASU under `switches`
  (`kind: asu`, `present: null` until a human checks it at bring-up). Option `asu_1pa` of `mosfet.gate_leakage`
  (`RI gate,8`) needs that ASU declared and `present: true` (R-ASU-01); a missing ASU makes `RI 8` an instrument
  error, which aborts the run before the trigger.

## SCUU GSWU and the 16440A selector

- N1301A-100 SCUU (SMU CMU unify unit): switches the DUT between the MFCMU and one of two HRSMU/MPSMU, so I-V and
  C-V run on the same pads without re-probing (deck slide 12; UG PDF 45, 103). With SMUs its outputs behave like
  Kelvin SMU outputs; for C-V only the force outputs are used (CCG PDF 80).
- N1301A-200 GSWU (guard switch unit): joins the CMU high and low guards near the DUT for accurate impedance
  measurements; it opens while the SCUU is in SMU state (UG PDF 103).
- 16440A SMU/PGU selector (with the 16445A adapter): switches a DUT terminal between an SMU and an SPGU channel,
  used for pulse program plus SMU read (UG PDF 44-45). Ports, states, PGU open, routes, cleanup and the selector
  check: [11 switching and routing](11-switching-routing.md#the-16440a-selector).
- SCUU path command `SSP chnum,path` with the MFCMU's channel (PG p520 (4-202)): 1 Force1 only, 2 Force2 only, 3 both
  SMUs, 4 CMUH/CMUL; Force1 is the SMU in slot `cmu_slot - 1`, Force2 the one in `cmu_slot - 2`. Power-on and `*RST`
  leave it open, which no `SSP` path restores (so a declared SCUU rests at `smu` or `cmu`). A connection switches the
  unit's output on; switching an SMU's output to the MFCMU sets it to 0 V, 100 V range, 20 mA, back to SMU 0 V, 20 V
  range, 100 uA. Its modules are never named in `CN` (error 323); the path reads back with `*LRN? 81`.
- MFCMU sides: a pin map puts the High pair (Hc/Hp: DC bias and AC drive) on `7H` and the Low pair (Lc/Lp: the
  virtual ground the current is measured at) on `7L` for the MFCMU in slot 7; roles `cmu_high`/`cmu_low` bind to
  them. With an SCUU the same pads are its outputs (CMUH/Force1, CMUL/Force2).

## Shielding grounding and interlock

Seeded from deck slide 12 (shield box tied to the instrument chassis; GNDU reference sinks up to 4.2 A) and deck
slide 2 (layer 1: interlock, shield box, grounding, cables).

- Put the DUT in a closed, dark shield box connected to the B1500A chassis or circuit common. Light causes
  photocurrent in semiconductors (oxide TFTs and photodiodes especially); an open lid also lets in mains pickup.
- One ground reference: the GNDU and circuit common; avoid ground loops through the prober chuck, microscope lamp
  supply or other instruments. A floating chuck or a chuck tied to a noisy ground shows up as mains-frequency noise.
- Vibration and air flow move probes and cables (triboelectric currents); let the setup settle after touching it.
- Interlock: the shield box door switch must open the B1500A Interlock terminal; while it is open SMU output is
  limited to ±42 V (UG PDF 55). Check the interlock function daily (UG PDF 142). v1 stays at or below 42 V, and
  whether the station's interlock is wired is recorded as `interlock.available` (unknown until bring-up).

## Probe contact and overdrive

Seeded from deck slide 12 and the deck text.

- Overdrive (travel after first touch) too small: high, unstable contact resistance through pad oxide or
  contamination; too large: pad damage, probe skating off the pad, damage to underlying layers or nearby tracks.
- Good probe-to-pad contact on metal pads is typically below about 1 ohm (deck text) `TODO(verify)` for this
  station's tips and pad metal. Aluminium pads carry a native oxide that a light scrub breaks.
- A probe touching a neighbouring track or pad gives currents orders of magnitude too high (deck slide 17 case);
  re-landing and a fresh contact check are the first response, never higher voltage or compliance.
- Every fresh landing gets a contact check before the real measurement (skill workflow, card
  `contact-resistor-check`).

## Contact checks

What the contact check is for and how to read it. The method that classifies the result is the `resistance`
analysis ([06](06-analysis-extraction.md#resistance-fit)); the physics of contact versus bulk is in
[01](01-device-physics.md#resistor-contact-versus-bulk-resistance).

- Contact (resistor) check: a small ±0.1 V staircase between two terminals of a known structure (resistor, the
  two ends of a metal line, or two probes on one pad). Outputs: R, linearity, offset, and a class open / short /
  in-range against the expected value from the DUT profile.
- Open: current at the noise floor (for example below 10 pA at 0.1 V means more than about 10 Gohm): probe not
  down, wrong pad, broken track, or wrong pin map.
- Short: R far below the expected value: probes touching each other, a shorted structure, or the wrong pads.
- Non-linear or asymmetric: oxide or barrier at one contact; repeat the landing before trusting the DUT.
- Offset at 0 V: leakage from another biased channel, thermoelectric voltage, or a charging cable.
- Open-circuit floor check: with the probes lifted, a 0 V or low-voltage measurement shows the noise and leakage
  floor of the path; compare it with the smallest current the measurement must resolve.
- These are safe software checks the agent may propose; physical actions (re-landing, cleaning tips, closing the
  box, checking guard) are requests to the human. Triage order and symptoms: skill `b1500-debug`.

## Station topology records

- `config/local/station.yaml` (human-owned, gitignored; the agent never edits it) records `topology`: `shield_box`,
  `guard`, `kelvin`, per-module `cables` (cable type, `length_m`, guard, kelvin), plus `interlock.available`. `null`
  means nobody has checked.
- `switches` declares the switch accessories (16440A selectors `SEL1`/`SEL2`, WGFMU `RSU201`/`RSU202`, SCUU, ASU):
  `present` (`null` = unknown), `certainty` and, per DUT-side output, the channel wired to each input (`null` = not
  recorded yet). A pin map reaches a pad through one with `SEL1.OUT1`; plans through an unrecorded input or an
  `unverified` switch are blocked or need confirmation. Recording the selector wiring is bring-up stage L7, the
  RSUs' From SMU inputs L8 (the SMU there takes +-25 V at most: R-RSU-01, [11](11-switching-routing.md#rsu-of-the-wgfmu)).
- When a measurement depends on an unknown wiring fact (guarded low-current path, Kelvin sense), say so in the
  report's assumptions and ask the human to confirm or record it.
