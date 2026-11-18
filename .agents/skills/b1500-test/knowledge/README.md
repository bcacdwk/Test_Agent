# Knowledge index (skill b1500-test)

Background knowledge behind the test cards, one file per domain of the owner's deck (slides 4 and 10-17). Load only
the sections a card links or a question needs; never read every file. Knowledge explains; it never overrides the
skill's rules, a card, a recipe, the policy or a DUT profile, and it never authorises an instrument action.

## Domains

| Domain | Scope | When to load |
|---|---|---|
| [01 device physics](01-device-physics.md) | resistor (contact vs bulk), capacitor models, PN and Schottky diodes, MOSFET Vth/gm/SS/Ion-Ioff/Id-Vd, MOS-C | interpreting a curve's physics; choosing bias regions; explaining a derived value |
| [02 B1500A instrument](02-b1500-instrument.md) | modules and limits, channel numbering, `UNT?`, measurement modes, status letters, integration time, errors, interlock, self-test/cal, FLEX glossary | choosing modules or presets; reading status counts, errors, a plan's FLEX preview or an audit log |
| [03 probe station and wiring](03-probe-station-wiring.md) | signal path, triax, guard, Kelvin, ASU/SCUU/selector, shielding and grounding, probe contact, contact checks | low-current or low-resistance work; a fresh landing; suspect wiring or noise |
| [04 ferroelectric and oxide](04-ferroelectric-oxide.md) | Ec/Pr/Ps, FeFET operation, memory window by dual sweep, read disturb, pulse write (reserved), PUND (reserved), IGZO TFTs | FeFET or FeCap requests; oxide TFT measurements |
| [05 reliability and defects](05-reliability-defects.md) | gate leakage safe envelope, BTI/HCI/TDDB (reserved), Dit, SILC and trapping, IGZO instability, wake-up/imprint/fatigue | gate leakage; drift or hysteresis; any stress request |
| [06 analysis and extraction](06-analysis-extraction.md) | run table and trust, quality gate, gm, Vth (3 methods), SS, Ion/Ioff, Ron/gds, R, diode fit, leakage, MW, plots, reporting rules | before `analyze_run`; writing the report; ad-hoc analysis |
| [07 HSPICE simulation](07-hspice-simulation.md) | reserved workflow: level-1 model card, netlist, comparison, BSIM4/Verilog-A later | a simulation-comparison request (answer: reserved) |
| 08 debug | skill `b1500-debug`: triage order, runbooks, cases | noisy, impossible, compliance-limited or drifting data; faults; VISA errors |

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
- [FLEX glossary for reading plans and audit logs](02-b1500-instrument.md#flex-glossary-for-reading-plans-and-audit-logs)
- [Data status codes](02-b1500-instrument.md#data-status-codes)
- [Integration time and ranging](02-b1500-instrument.md#integration-time-and-ranging)
- [Status byte errors and interlock](02-b1500-instrument.md#status-byte-errors-and-interlock)
- [Self-test self-calibration and auto calibration](02-b1500-instrument.md#self-test-self-calibration-and-auto-calibration)
- [Manual extracts and page conventions](02-b1500-instrument.md#manual-extracts-and-page-conventions)

### 03 probe station and wiring

- [Signal path from SMU to pad](03-probe-station-wiring.md#signal-path-from-smu-to-pad)
- [Triaxial cables and terminals](03-probe-station-wiring.md#triaxial-cables-and-terminals)
- [Guard for low current](03-probe-station-wiring.md#guard-for-low-current)
- [Kelvin four-wire connection](03-probe-station-wiring.md#kelvin-four-wire-connection)
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
- [FeCap P-V and PUND](04-ferroelectric-oxide.md#fecap-p-v-and-pund)
- [IGZO and oxide TFT specifics](04-ferroelectric-oxide.md#igzo-and-oxide-tft-specifics)

### 05 reliability and defects

- [Scope and v1 status](05-reliability-defects.md#scope-and-v1-status)
- [Gate leakage and TDDB-safe envelope](05-reliability-defects.md#gate-leakage-and-tddb-safe-envelope)
- [BTI stress-measure-stress](05-reliability-defects.md#bti-stress-measure-stress)
- [Hot-carrier injection HCI](05-reliability-defects.md#hot-carrier-injection-hci)
- [TDDB constant-voltage stress](05-reliability-defects.md#tddb-constant-voltage-stress)
- [Interface traps Dit](05-reliability-defects.md#interface-traps-dit)
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
- [Resistance fit](06-analysis-extraction.md#resistance-fit)
- [Diode fit Is n and Rs](06-analysis-extraction.md#diode-fit-is-n-and-rs)
- [Leakage at bias](06-analysis-extraction.md#leakage-at-bias)
- [Memory window](06-analysis-extraction.md#memory-window)
- [Plots](06-analysis-extraction.md#plots)
- [Reporting rules measured versus derived](06-analysis-extraction.md#reporting-rules-measured-versus-derived)
- [C-V extraction reserved](06-analysis-extraction.md#c-v-extraction-reserved)

### 07 HSPICE simulation

- [Status and boundaries](07-hspice-simulation.md#status-and-boundaries)
- [Planned workflow](07-hspice-simulation.md#planned-workflow)
- [Level-1 model card from measured parameters](07-hspice-simulation.md#level-1-model-card-from-measured-parameters)
- [Example netlist](07-hspice-simulation.md#example-netlist)
- [Comparing measured and simulated curves](07-hspice-simulation.md#comparing-measured-and-simulated-curves)
- [BSIM4 and Verilog-A later](07-hspice-simulation.md#bsim4-and-verilog-a-later)

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
