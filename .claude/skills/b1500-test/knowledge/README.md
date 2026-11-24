<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->
# Knowledge index (skill b1500-test)

Background knowledge behind the test cards, one file per domain of the owner's deck (slides 4 and 10-17). Load only
the sections a card links or a question needs; never read every file. Knowledge explains; it never overrides the
skill's rules, a card, a recipe, the policy or a DUT profile, and it never authorises an instrument action.

## Domains

| Domain | Scope | When to load |
|---|---|---|
| [01 device physics](01-device-physics.md) | resistor (contact vs bulk), capacitor models, PN and Schottky diodes, MOSFET Vth/gm/SS/Ion-Ioff/Id-Vd, MOS-C | interpreting a curve's physics; choosing bias regions; explaining a derived value |
| [02 B1500A instrument](02-b1500-instrument.md) | modules and limits, GNDU and its 4.2 A return budget, channel numbering, `UNT?`, measurement modes, status letters, integration time, errors, interlock, self-test/cal, FLEX glossary | choosing modules or presets; reading status counts, errors, a plan's FLEX preview or an audit log |
| [02b SMU modes and long runs](02b-smu-modes.md) | sampling MM 10, pulsed MM 3/4/5/27/28, search MM 9/14/15, quasi-static C-V MM 13, zero-check floor, SMU conditioning (FL, SSR, AZ, AV, RM), long runs (async, CM 0, recovery) | planning or reading a sampling, pulsed, search, QSCV or long SMU run; a conditioning question |
| [03 probe station and wiring](03-probe-station-wiring.md) | signal path, triax, guard, Kelvin and four-wire R, ASU/SCUU/selector, shielding and grounding, probe contact, contact checks | low-current or low-resistance work; a fresh landing; suspect wiring or noise |
| [04 ferroelectric and oxide](04-ferroelectric-oxide.md) | Ec/Pr/Ps, FeFET operation, memory window by dual sweep, read disturb, pulse write/read, endurance, NLS switching kinetics, retention, PUND (reserved), IGZO TFTs | FeFET or FeCap requests; oxide TFT measurements |
| [05 reliability and defects](05-reliability-defects.md) | gate leakage safe envelope, BTI/HCI/TDDB, breakdown voltage ramps, Dit, SILC and trapping, IGZO instability, wake-up/imprint/fatigue | gate leakage; drift or hysteresis; any stress or breakdown request |
| [06 analysis and extraction](06-analysis-extraction.md) | run table and trust, quality gate, gm, Vth (3 methods), SS, Ion/Ioff, Ron/gds, R, diode fit, leakage, MW, plots, reporting rules | before `analyze_run`; writing the report; ad-hoc analysis |
| [06b time series, pulsed and search runs](06b-analysis-time-pulse.md) | sampling summary and relaxation fit, time to breakdown and Weibull, pulsed vs DC (two-run), pulse plateau, Vth by search, breakdown voltage, program/read memory window, switching kinetics (NLS), endurance, retention | analysing a sampling, TDDB, pulsed, search, program/read, kinetics, endurance or retention run |
| [07 compact models](07-compact-models.md) | level-1 and EKV model fits, model vs run comparison, SPICE `.model`/subcircuit and netlist export (ngspice, HSPICE), BSIM4/Verilog-A later | a model card, SPICE, netlist or simulation-comparison request; reading a model fit |
| [08 capacitance and C-V](08-capacitance-cv.md) | MFCMU pairs Cp-G/Cs-Rs/Z-theta, corrections, MOS-C HF C-V, Cox/EOT, 1/C^2 doping, flatband, Vth, hysteresis, split C-V, SCUU same landing, AC level, pulsed, C-f, C-t, QSCV, Dit over the gap (high-low, conductance), FeCap butterfly | any capacitance, C-V, QSCV or Dit request; before `analyze_run` on a C-V run |
| debug | skill `b1500-debug`: triage order, runbooks, cases | noisy, impossible, compliance-limited or drifting data; faults; VISA errors |
| [09 pulses, HV-SPGU and selector](09-pulse-spgu-selector.md) | HV-SPGU output and SER (open-load doubling, high_z residual), PG and ALWG trains, count/duration bounds, running a train, readings during a train, R-PULSE/R-SPGU rules, program/read (pulse_read) and its schedules (cycles, endurance bursts, grid, retention), simulator | any SPGU pulse or waveform plan; program/erase then read; a gate pulse that did nothing or too much |
| [11 switching and routing](11-switching-routing.md) | switches in the station profile, routes per phase, 16440A selector (ERSSP, PGU open, Force only), SCUU/ASU paths, RSU, guard and R-ROUTE rules, cleanup to rest, selector check, simulator | any plan through a switch target; selector wiring (L7); a run blocked or failed on a route |

## Sections by file

Cards cite `knowledge/<file>.md#<heading-id>` (GitHub heading ids). Renaming a heading breaks those links;
`b1500 dev lint-skills` reports it.

### 01 device physics

- [Scope and conventions](01-device-physics.md#scope-and-conventions)
- [Resistor contact versus bulk resistance](01-device-physics.md#resistor-contact-versus-bulk-resistance)
- [Capacitor models Cs-Rs and Cp-G](01-device-physics.md#capacitor-models-cs-rs-and-cp-g)
- [PN diode Shockley equation and ideality factor](01-device-physics.md#pn-diode-shockley-equation-and-ideality-factor)
- [Diode series resistance reverse leakage and breakdown](01-device-physics.md#diode-series-resistance-reverse-leakage-and-breakdown)
- [MOSFET threshold voltage definitions](01-device-physics.md#mosfet-threshold-voltage-definitions)
- [MOSFET transconductance and mobility](01-device-physics.md#mosfet-transconductance-and-mobility)
- [MOSFET subthreshold swing](01-device-physics.md#mosfet-subthreshold-swing)
- [MOSFET on-off current ratio](01-device-physics.md#mosfet-on-off-current-ratio)
- [MOSFET output characteristics](01-device-physics.md#mosfet-output-characteristics)
- [MOS capacitor C-V regions](01-device-physics.md#mos-capacitor-c-v-regions)
- [Constants and typical magnitudes](01-device-physics.md#constants-and-typical-magnitudes)

### 02 B1500A instrument

- [Mainframe slots and GNDU](02-b1500-instrument.md#mainframe-slots-and-gndu)
- [SMU and module table](02-b1500-instrument.md#smu-and-module-table)
- [Channel numbering and UNT](02-b1500-instrument.md#channel-numbering-and-unt)
- [Measurement modes](02-b1500-instrument.md#measurement-modes)
- [Measurement sequence and cleanup](02-b1500-instrument.md#measurement-sequence-and-cleanup)
- [Lab scripts vs the kernel](02-b1500-instrument.md#lab-scripts-vs-the-kernel)
- [FLEX glossary for reading plans and audit logs](02-b1500-instrument.md#flex-glossary-for-reading-plans-and-audit-logs)
- [Data status codes](02-b1500-instrument.md#data-status-codes)
- [Integration time and ranging](02-b1500-instrument.md#integration-time-and-ranging)
- [Status byte errors and interlock](02-b1500-instrument.md#status-byte-errors-and-interlock)
- [Self-test self-calibration and auto calibration](02-b1500-instrument.md#self-test-self-calibration-and-auto-calibration)
- [MFCMU phase compensation and correction](02-b1500-instrument.md#mfcmu-phase-compensation-and-correction)
- [Manual extracts and page conventions](02-b1500-instrument.md#manual-extracts-and-page-conventions)

### 02b SMU modes, conditioning and long runs

- [Sampling measurement MM 10](02b-smu-modes.md#sampling-measurement-mm-10)
- [Pulsed measurements MM 3 4 5 27 28](02b-smu-modes.md#pulsed-measurements-mm-3-4-5-27-28)
- [Search measurements MM 9 14 15](02b-smu-modes.md#search-measurements-mm-9-14-15)
- [Quasi-static C-V MM 13](02b-smu-modes.md#quasi-static-c-v-mm-13)
- [Zero check floor](02b-smu-modes.md#zero-check-floor)
- [SMU output conditioning](02b-smu-modes.md#smu-output-conditioning)
- [Long SMU runs](02b-smu-modes.md#long-smu-runs)

### 03 probe station and wiring

- [Signal path from SMU to pad](03-probe-station-wiring.md#signal-path-from-smu-to-pad)
- [Triaxial cables and terminals](03-probe-station-wiring.md#triaxial-cables-and-terminals)
- [Guard for low current](03-probe-station-wiring.md#guard-for-low-current)
- [Kelvin four-wire connection](03-probe-station-wiring.md#kelvin-four-wire-connection)
- [Four-wire resistance](03-probe-station-wiring.md#four-wire-resistance)
- [ASU and the 1 pA range](03-probe-station-wiring.md#asu-and-the-1-pa-range)
- [SCUU GSWU and the 16440A selector](03-probe-station-wiring.md#scuu-gswu-and-the-16440a-selector)
- [Shielding grounding and interlock](03-probe-station-wiring.md#shielding-grounding-and-interlock)
- [Probe contact and overdrive](03-probe-station-wiring.md#probe-contact-and-overdrive)
- [Contact checks](03-probe-station-wiring.md#contact-checks)
- [Station topology records](03-probe-station-wiring.md#station-topology-records)

### 04 ferroelectric and oxide

- [Scope and v1 status](04-ferroelectric-oxide.md#scope-and-v1-status)
- [Ferroelectric basics Ec Pr Ps](04-ferroelectric-oxide.md#ferroelectric-basics-ec-pr-ps)
- [FeFET operation](04-ferroelectric-oxide.md#fefet-operation)
- [FeFET memory window by dual sweep](04-ferroelectric-oxide.md#fefet-memory-window-by-dual-sweep)
- [Read disturb and sweep-rate effects](04-ferroelectric-oxide.md#read-disturb-and-sweep-rate-effects)
- [Pulse write read endurance and retention](04-ferroelectric-oxide.md#pulse-write-read-endurance-and-retention)
- [Pulse switching kinetics](04-ferroelectric-oxide.md#pulse-switching-kinetics)
- [Retention](04-ferroelectric-oxide.md#retention)
- [FeCap P-V and PUND](04-ferroelectric-oxide.md#fecap-p-v-and-pund)
- [IGZO and oxide TFT specifics](04-ferroelectric-oxide.md#igzo-and-oxide-tft-specifics)

### 05 reliability and defects

- [Scope and v1 status](05-reliability-defects.md#scope-and-v1-status)
- [Gate leakage and TDDB-safe envelope](05-reliability-defects.md#gate-leakage-and-tddb-safe-envelope)
- [BTI stress-measure-stress](05-reliability-defects.md#bti-stress-measure-stress)
- [Hot-carrier injection HCI](05-reliability-defects.md#hot-carrier-injection-hci)
- [TDDB constant-voltage stress](05-reliability-defects.md#tddb-constant-voltage-stress)
- [Breakdown voltage ramps](05-reliability-defects.md#breakdown-voltage-ramps)
- [Interface traps Dit](05-reliability-defects.md#interface-traps-dit)
- [Charge pumping](05-reliability-defects.md#charge-pumping)
- [Oxide traps SILC and charge trapping](05-reliability-defects.md#oxide-traps-silc-and-charge-trapping)
- [IGZO instability mechanisms](05-reliability-defects.md#igzo-instability-mechanisms)
- [Ferroelectric wake-up imprint and fatigue](05-reliability-defects.md#ferroelectric-wake-up-imprint-and-fatigue)

### 06 analysis and extraction

- [Run table and trust classes](06-analysis-extraction.md#run-table-and-trust-classes)
- [Quality gate and noise](06-analysis-extraction.md#quality-gate-and-noise)
- [Transconductance gm](06-analysis-extraction.md#transconductance-gm)
- [Vth linear extrapolation](06-analysis-extraction.md#vth-linear-extrapolation)
- [Vth constant current](06-analysis-extraction.md#vth-constant-current)
- [Vth at maximum gm](06-analysis-extraction.md#vth-at-maximum-gm)
- [Subthreshold swing](06-analysis-extraction.md#subthreshold-swing)
- [Maximum transconductance](06-analysis-extraction.md#maximum-transconductance)
- [On and off current](06-analysis-extraction.md#on-and-off-current)
- [Output metrics Ron and gds](06-analysis-extraction.md#output-metrics-ron-and-gds)
- [DIBL and body effect](06-analysis-extraction.md#dibl-and-body-effect)
- [Resistance fit](06-analysis-extraction.md#resistance-fit)
- [Diode fit Is n and Rs](06-analysis-extraction.md#diode-fit-is-n-and-rs)
- [Forward voltage](06-analysis-extraction.md#forward-voltage)
- [Leakage at bias](06-analysis-extraction.md#leakage-at-bias)
- [Memory window](06-analysis-extraction.md#memory-window)
- [Plots](06-analysis-extraction.md#plots)
- [Reporting rules measured versus derived](06-analysis-extraction.md#reporting-rules-measured-versus-derived)
- [C-V extraction](06-analysis-extraction.md#c-v-extraction)

### 06b time series, pulsed and search runs

- [Sampling summary and relaxation fit](06b-analysis-time-pulse.md#sampling-summary-and-relaxation-fit)
- [Time to breakdown and Weibull](06b-analysis-time-pulse.md#time-to-breakdown-and-weibull)
- [Pulsed versus DC](06b-analysis-time-pulse.md#pulsed-versus-dc)
- [Pulse plateau](06b-analysis-time-pulse.md#pulse-plateau)
- [Threshold voltage by search](06b-analysis-time-pulse.md#threshold-voltage-by-search)
- [Breakdown voltage](06b-analysis-time-pulse.md#breakdown-voltage)
- [Program read memory window](06b-analysis-time-pulse.md#program-read-memory-window)
- [Switching kinetics](06b-analysis-time-pulse.md#switching-kinetics)
- [Endurance](06b-analysis-time-pulse.md#endurance)
- [Retention](06b-analysis-time-pulse.md#retention)
- [SMU method index](06b-analysis-time-pulse.md#smu-method-index)

### 07 compact models

- [Status and boundaries](07-compact-models.md#status-and-boundaries)
- [Workflow](07-compact-models.md#workflow)
- [Level-1 model](07-compact-models.md#level-1-model)
- [EKV model](07-compact-models.md#ekv-model)
- [Points and trust](07-compact-models.md#points-and-trust)
- [Fit](07-compact-models.md#fit)
- [Comparing a model with a run](07-compact-models.md#comparing-a-model-with-a-run)
- [SPICE export](07-compact-models.md#spice-export)
- [Example files](07-compact-models.md#example-files)
- [Reading the results](07-compact-models.md#reading-the-results)
- [BSIM4 and Verilog-A later](07-compact-models.md#bsim4-and-verilog-a-later)

### 08 capacitance and C-V

- [Scope and status](08-capacitance-cv.md#scope-and-status)
- [Impedance models Cp-G Cs-Rs Z-theta](08-capacitance-cv.md#impedance-models-cp-g-cs-rs-z-theta)
- [Corrections and the measurement path](08-capacitance-cv.md#corrections-and-the-measurement-path)
- [High-frequency C-V of a MOS capacitor](08-capacitance-cv.md#high-frequency-c-v-of-a-mos-capacitor)
- [Oxide capacitance and EOT](08-capacitance-cv.md#oxide-capacitance-and-eot)
- [Doping from 1/C^2](08-capacitance-cv.md#doping-from-1c2)
- [Flatband voltage](08-capacitance-cv.md#flatband-voltage)
- [Threshold voltage from C-V](08-capacitance-cv.md#threshold-voltage-from-c-v)
- [Hysteresis](08-capacitance-cv.md#hysteresis)
- [Split C-V Cgc and Cgd](08-capacitance-cv.md#split-c-v-cgc-and-cgd)
- [SCUU same-landing I-V and C-V](08-capacitance-cv.md#scuu-same-landing-i-v-and-c-v)
- [AC level dependence](08-capacitance-cv.md#ac-level-dependence)
- [Pulsed C-V](08-capacitance-cv.md#pulsed-c-v)
- [C-f and frequency dispersion](08-capacitance-cv.md#c-f-and-frequency-dispersion)
- [C-t and deep-depletion recovery](08-capacitance-cv.md#c-t-and-deep-depletion-recovery)
- [Quasi-static C-V](08-capacitance-cv.md#quasi-static-c-v)
- [Dit over the band gap](08-capacitance-cv.md#dit-over-the-band-gap)
- [FeCap C-V butterfly](08-capacitance-cv.md#fecap-c-v-butterfly)
- [Reporting C-V results](08-capacitance-cv.md#reporting-c-v-results)

### 09 pulses, HV-SPGU and selector

- [HV-SPGU output and the SER load](09-pulse-spgu-selector.md#hv-spgu-output-and-the-ser-load)
- [PG pulse trains](09-pulse-spgu-selector.md#pg-pulse-trains)
- [ALWG waveforms](09-pulse-spgu-selector.md#alwg-waveforms)
- [Running a train](09-pulse-spgu-selector.md#running-a-train)
- [Readings during a train](09-pulse-spgu-selector.md#readings-during-a-train)
- [Guard and rules](09-pulse-spgu-selector.md#guard-and-rules)
- [Program and read](09-pulse-spgu-selector.md#program-and-read)
- [Simulator behaviour](09-pulse-spgu-selector.md#simulator-behaviour)
- [Troubleshooting pulses](09-pulse-spgu-selector.md#troubleshooting-pulses)

### 11 switching and routing

- [Switches in the station profile](11-switching-routing.md#switches-in-the-station-profile)
- [Routes and phases](11-switching-routing.md#routes-and-phases)
- [The 16440A selector](11-switching-routing.md#the-16440a-selector)
- [SCUU and ASU paths](11-switching-routing.md#scuu-and-asu-paths)
- [RSU of the WGFMU](11-switching-routing.md#rsu-of-the-wgfmu)
- [Guard and rules](11-switching-routing.md#guard-and-rules)
- [Cleanup and verification](11-switching-routing.md#cleanup-and-verification)
- [Selector check and recording the wiring](11-switching-routing.md#selector-check-and-recording-the-wiring)
- [Simulator behaviour](11-switching-routing.md#simulator-behaviour)
- [Troubleshooting routes](11-switching-routing.md#troubleshooting-routes)

## Manual documents

Ids for `uv run b1500 manual search|page|toc` and for citations (`references/manuals/catalog.yaml`; the committed
page corpus answers without the PDFs). Knowledge files first; the manuals are the ground truth for commands,
ranges and error codes. Prefer PG, WG, SEL and CC; WG5 only where an extract cites it.

| id | document | edition | pages | language | use for |
|---|---|---|---|---|---|
| PG | B1500 Series Programming Guide | Ed. 15, 2022 | 617 | en | FLEX commands (one outline entry each), modes, data formats, errors |
| EX | EasyEXPERT Software User's Guide | Ed. 5, 2020 | 700 | en | EasyEXPERT tests and settings (golden comparisons) |
| UG | B1500A User's Guide | Ed. 17, 2021 | 160 | en | safety, installation, module specifications, calibration |
| WG | B1530A WGFMU User's Guide | Ed. 8, 2021 | 160 | en | WGFMU instrument library (one entry per function), RSU |
| WG5 | B1530A WGFMU User's Guide (old) | Ed. 5, 2012 | 164 | en | pages cited by the structured WGFMU extracts; prefer WG |
| CC | B1500A Configuration and Connection Guide | Ed. 10, 2020 | 122 | en | cabling, Kelvin, guard, ASU/SCUU, prober connections |
| AC | B1500A Configuration Guide (accessories) | 2024 | 24 | en | accessories and ordering |
| SEL | 16440A SMU/Pulse Generator Selector User's Guide | Ed. 6, 2014 | 32 | en | selector ports, states, wiring |
| DS | B1500A technical overview (data sheet) | 2019 | 17 | zh | specifications summary |
| AN-REL | CMOS reliability test solutions | 2019 | 10 | zh | BTI, HCI, TDDB methods |
| AN-CHAR | CMOS device characterization | 2014 | 7 | zh | standard I-V/C-V characterization |
| AN-TUT | B1500A self-study training tutorial | Ed. 9, 2021 | 186 | zh | operation basics, corrections (mostly images) |
| AN-NVM | Advanced NVM Application Tests User's Guide | Ed. 1, 2019 | 90 | en | NVM (flash) pulse tests, endurance, retention |
| AN-RTN | Random telegraph noise with the WGFMU | 2019 | 10 | zh | RTN measurement and analysis |
| AN-CV | IV and CV with MFCMU and SCUU | 2019 | 8 | zh | SCUU same-landing IV/CV, CMU corrections |
| AN-FIV | 1 us flash-cell IV with the WGFMU | 2014 | 8 | zh | fast IV with short pulses |

## Conventions

- Frontmatter: `domain`, `maturity` (`seed` = generated from sources, unreviewed; `draft` = reworked, still
  unreviewed; `reviewed` = checked by a human), `sources` (at least one), `last_reviewed` (date of the human
  review, else null). Only a human sets `reviewed` and `last_reviewed`; all files start as `seed`.
- `TODO(verify)` marks a fact that is plausible or typical but not checked against a primary source or the
  owner's devices. Treat it as orientation, never as a limit or a pass/fail criterion.
- Deck citations: "deck slide N" is slide N of the owner's 2026-11-04 deck (title = slide 1; domains 1-8 = slides
  10-17). The deck text file `PPT_slides_content.md` labels those slides as pages 11-18 (it adds a domain overview
  page) and carries a few values not shown on the slides; those are cited as "deck text".
- Manual citations: `PG p433 (4-115)` = document id (table above), physical 1-based PDF page, printed page label;
  an optional quoted keyword must occur on the page. Older text writes "PG PDF 433" (same page) and "CCG" for CC.
  `b1500 dev lint-skills` checks every citation against the catalog. Manual definitions win over the deck.
- Links stay inside the skill folder (lint rule); repository files are named as code spans.
- Maintenance (human-reviewed changes): each file stays at or below 300 lines, a domain that outgrows it becomes a
  folder `knowledge/NN-name/`; after an edit run `uv run b1500 dev lint-skills` and `uv run b1500 dev sync-harness`.
