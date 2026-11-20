---
domain: 02-b1500-instrument
maturity: seed
sources:
  - deck slide 11 (module table, channel numbering, UNT?)
  - deck slide 3 (MCP layer, I-V sweep command sequence)
  - deck slides 8 and 9 (safety, status codes, pre-measurement checklist)
  - "B1500 Series Programming Guide Ed. 15 (PG), PDF pages cited inline"
  - "B1500A User's Guide Ed. 17 (UG), PDF pages cited inline"
  - references/manuals/structured (command parameters, command summary, error codes, initial settings)
  - code tables in src/b1500_test_agent/driver/modules.py and models/station.py
  - src/b1500_test_agent/analysis/floor.py (zero_floor; v2 WP7.1)
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# B1500A instrument (knowledge domain 2)

Seeded from deck slide 11. What the mainframe and its modules can do, how channels are numbered, and how to read
status letters, errors and the FLEX preview of a plan. FLEX appears here only so that plans and audit logs can be
understood: the agent never sends FLEX. Every instrument action goes through the `b1500` tools (validate a plan,
run it); there is no raw-command tool and none may be improvised. PDF page numbers are physical PDF pages.

## Mainframe slots and GNDU

- Ten module slots plus the built-in ground unit (GNDU) (UG PDF 44). HPSMU, HCSMU and HVSMU occupy two slots.
- GNDU: 0 V constant-voltage source used as the measurement ground reference; it sinks up to 4.2 A (UG PDF 58).
  Its cable must be the 16493L GNDU cable: an ordinary triaxial cable is rated 1 A (UG PDF 93).
- In pin maps a terminal bound to `GNDU` (source, bulk) is grounded through the GNDU.

## SMU and module table

Deck slide 11, corrected against the User's Guide. DC values; v1 sources DC only.

| Type | Model | Slots | Max DC V / I / P | Smallest ranges | Notes |
|---|---|---|---|---|---|
| HPSMU | B1510A | 2 | ±200 V / ±1 A / 20 W | 2 V, 1 nA | power devices (UG PDF 60) |
| MPSMU | B1511B | 1 | ±100 V / ±100 mA / 2 W | 0.5 V, 1 nA (1 pA with ASU) | general I-V; ASU only on B1511B (UG PDF 44, 63) |
| HRSMU | B1517A | 1 | ±100 V / ±100 mA / 2 W | 0.5 V, 10 pA (1 pA with ASU) | low current; 1 fA resolution on the 1 pA range (UG PDF 69-70) |
| MCSMU | B1514A | 1 | ±30 V / ±100 mA / 3 W | 0.2 V, 10 uA | 1 A and 30 W in pulse mode only (UG PDF 67) |
| MFCMU | B1520A | 1 | DC bias ±25 V (±100 V via SMU + SCUU) | — | 1 kHz-5 MHz, 10-250 mVrms; one per mainframe (UG PDF 73) |
| HVSPGU | B1525A | 1 | ±40 V open load, ±20 V into 50 ohm | — | 2 pulse channels, PG or ALWG (UG PDF 76) |
| WGFMU | B1530A | 1 | 0 to ±10 V or ±5 V (Fast IV, DC) | 1 uA | 2 channels + RSU, 5 ns sampling (UG PDF 77) |

- HRSMU/MPSMU output envelope: up to 100 mA at |V| ≤ 20 V, 50 mA to 40 V, 20 mA to 100 V (UG Table 2-12,
  PDF 70; PG Tables 4-6/4-7, PDF 341-342). Rule R-LIM-01 checks every plan against these corners.
- Deck slide 11 lists MCSMU as 30 V / 1 A: 1 A is pulse only, DC is 100 mA. The deck also notes the owner's
  station has no MCSMU, and WGFMU/HVSPGU matter most after SMU I-V (deck slide 7).
- On top of module ratings, v1 caps every plan at 42 V and 100 mA in code; the example policy asks for confirmation
  above 10 V or 10 mA compliance. `station_status` shows the live limits; the human owns them.
- Low current: prefer an HRSMU (smallest native range 10 pA) on the terminal whose current matters (drain for
  Ioff/SS, gate for leakage). The example station has SMU3/SMU4 as HRSMU.

## Channel numbering and UNT

- PG Table 4-1 (PDF 334): an SMU or MFCMU in slot n is channel n (also written n01). The two subchannels of a
  WGFMU or HVSPGU in slot n are n01 and n02 (the lab WGFMU in slot 2: 201, 202). A two-slot module uses the lower
  slot number.
- Deck slide 11 says channels 11-20 are the subchannels of slots 1-10. That contradicts PG Table 4-1 and the
  WGFMU channel ids 101-1002; the manual wins `TODO(verify)` whether any firmware mode accepts 11-20.
- `UNT?` returns model and revision per slot, `[FrameModel,FrameRevision;]Slot1Model,Slot1Revision;...`
  (PG PDF 545); an empty slot is assumed to read `0,0` (confirmed only at hardware bring-up). Rule R-INV-01 compares
  it with the station profile before every run, and `station_status` reports the inventory.
- Status letters and data blocks name channels by letter: `A`-`J` = slots 1-10, `a`-`j` = their subchannel 2,
  `V` = GNDU (PG Table 1-11, PDF 54).

## Measurement modes

Folded from the former mode-map stub and checked against PG Chapter 2 (PDF 91-132) and the `XE` required-command
table (PDF 571-572). Implemented: modes 1, 2, 10 and 16 (WP7.2 added the current, synchronous and multi-channel
sweeps; WP7.1 the spot, mode 1).

| MM | Mode | Modules | v1 |
|---|---|---|---|
| — | high-speed spot (`TI`, `TV`, no `MM`/`XE`) | SMU | not used |
| 1 | spot | SMU | `smu_spot` (all measured roles at once; host list of levels, range survey) |
| 2 | staircase sweep (`WV`/`WI` lin/log, single/double; one synchronous `WSV`/`WSI` source) | SMU | `smu_staircase`, `smu_stepped` (host loop over a stepped V or I bias) |
| 3, 4, 5 | pulsed spot, pulsed sweep, staircase with pulsed bias | SMU | reserved |
| 9 | quasi-pulsed spot | SMU | reserved |
| 10 | sampling | SMU | `smu_sampling` (I(t) transients, TDDB; section below) |
| 13 | quasi-static C-V | SMU | reserved |
| 14, 15 | linear / binary search | SMU | reserved |
| 16 | multi-channel sweep (`WV`/`WI` primary + `WNX` sources, either mode; PDF 102) | SMU | `smu_staircase` with two or more sweep roles |
| 17-20, 22, 23, 26 | spot C, C-V, pulsed C, C-f, C-V(AC level), C-t | MFCMU | driver + simulator (WP8.1); recipes M8 |
| 27, 28 | multi-channel pulsed spot / sweep | SMU | reserved |

WGFMU waveforms run through the B1530A instrument library and SPGU pulses through their own commands, not through
`MM` (the old stub listed them under sampling and pulsed sweep) `TODO(verify)` against the B1530A guide.

## Sampling measurement MM 10

Kind `smu_sampling` (recipes `mosfet.id_t_sampling`, `generic.smu_sampling`, `reliability.tddb_cvs`); PG sampling
measurements PG p112-114 (2-24), `MT` PG p474-476 (4-156).

- On the trigger the synchronous sources (`MV`/`MI`) force their base value, `hold_base` later their bias value
  (the time origin, `t_s = 0`), `hold_bias` later the first sample; then one sample per `interval` (2 ms to 65 s
  in 1 ms steps; below 2 ms linear only). DC sources (`DV`/`DI`) are set before the trigger and keep their level.
- Each sample carries its sampling index (`FMT 1,1`) and, with `TSC 1`, a time stamp per channel (time since `TSR`);
  `t_s` comes from the stamps. A sample that would start while the channels are busy is skipped (index gap).
- `MSC 2,2`: compliance of any channel, overflow or oscillation stops the sampling at once (later data read
  `199.999E+99`, dropped from the table) and the sources go to their base value; a normal end keeps the bias.
- Runs with more than 60 s of linear sampling are chains of 25 s blocks: continuation blocks hold the stress
  (base = bias) and the time stamps run on, so `t_s` stays exact; each block is a checkpoint (progress, cancel).

## Measurement sequence and cleanup

Deck slide 3 sketches one I-V sweep: reset, data format, ADC, enable channels, mode, measured quantity, range,
sweep source, trigger, wait, read, zero, disconnect. In v1 the recipe kind compiles that sequence from the plan;
`validate_plan` returns it as the plan's FLEX preview (writes only) so a human can audit it.

- Every run is one transaction: rules re-checked under the instrument lock, output guard on every source command,
  then cleanup abort, SPGU stop, zero, disconnect, verify (deck slide 8: zero and disconnect after any error and
  after every measurement), whatever happened. Unverified cleanup latches a fault that only a human clears.
- SPGU stop (cleanup step 2, mainframes with an HV-SPGU, e.g. the lab's slot 1): `SPST?` and, while it reads 1,
  `SPP` (PG PDF 511, 513-514); the verification also needs `SPST?` = 0. `DZ` does not stop a running SPGU output
  (it is not a stop condition, PG PDF 142); an SPGU that ignores `SPP` latches the fault unless the retry stops it.
- On hardware the verification is `LOP?` (PG PDF 446-447: `00` = output off, `01` = forcing voltage, `1x` =
  compliance). Its positive control: right after `CN` (outputs on at 0 V, before any level) the run reads `LOP?`
  once and every switched-on SMU must show a non-`00` code; only then does the all-`00` answer after `CL` prove
  the outputs off (`verified: lop`; evidence in the run's `manifest.json` `cleanup.positive_control` and the
  `lop_positive_control` line of `get_run` `audit`). A control that reads `00` stops the run before any level and
  latches the fault (`cleanup_unverified`): report it, `safe_shutdown`, skill `b1500-debug`.
- Before `XE` the instrument needs channels enabled, a mode and its sources (PG PDF 571-572); missing pieces are
  instrument errors, which v1 drains with `ERRX?` and treats as a reason to abort before triggering.
- The deck's pre-measurement checklist (slide 9) maps to rules: modules and channel map via `UNT?` (R-INV-01),
  calibration state (R-CAL-01), C-V correction (R-CORR-01), compliance set (R-COMP-01).

## Lab scripts vs the kernel

The lab's MATLAB scripts (`lwp/matlab_B1500`, read-only; transcripts in `tests/fixtures/lab/`) send the same Id-Vg
measurement as `mosfet.idvg` on pin map `mosfet-3t-lab` with these deliberate differences (full list with reasons:
`tests/integration/test_lab_idvg_sequence.py`):

- No `*RST`: it drops MFCMU corrections, sets the SPGU to free-run, resets the selector paths and hides the
  instrument's prior state (PG PDF 179-180); only kind `system` may send it.
- `FMT 1,1` instead of `FMT 21,1`: one status letter per value, which the kernel keeps; the lab parser keeps only
  the number, so its compliance and overflow points look like readings.
- Compliances: drain 1 mA (lab 100 mA for a 0.4 uA device), gate 1 uA (lab 10 mA), source the sum of the two;
  10 mA gate or 100 mA drain is outside the recipe ranges (blocked).
- Auto ranging (lab: `RI` 1 nA limited, `WV` 20 V limited), `WT 0,0` (lab 10 ms delay; `delay_s: 0.01` matches
  it), `WM 2,1` automatic abort (lab off), `AAD` written explicitly.
- No `ERSSP` (the lab sends `ERSSP p,0` = open without `ERMOD 1`); `ERRX?` drained before the trigger and in the
  cleanup, both `0,` and `+0,` read as no error; a verified cleanup instead of a bare `DZ`, `CL`. The lab's SPGU
  script never sends `CL` at all.
- Id(t) sampling (`lib/IVt_sampling.m` vs `mosfet.id_t_sampling` on `mosfet-3t-lab`; reasons in
  `tests/integration/test_lab_ivt_sequence.py`): same `ML 1`, `MT`, `MV` step and `MM 10` drain; `FMT 1,1` (status
  letters and the sampling index) instead of `FMT 21,0`, `MSC 2,2` automatic abort (lab off), `MCC` and `TSR`
  (the lab relies on `*RST`), compliances 1 uA gate / 1 mA drain (lab 10 mA / 100 mA).

## FLEX glossary for reading plans and audit logs

| Mnemonic | Meaning | PG PDF |
|---|---|---|
| `*RST`, `*IDN?`, `UNT?` | reset to initial settings; identity; module inventory | 502, 440, 545 |
| `FMT` | data output format (v1: ASCII with status header) | 436-438 |
| `CN`, `CL` | output switch on / off for channels | 380, 378 |
| `DV`, `DI`, `DZ` | force DC voltage / current; set channels to 0 V | 396, 391, 397 |
| `WV`, `WT`, `WM` | staircase voltage sweep; hold/delay times; abort and post-sweep output | 568, 564, 552 |
| `WI`, `WSV`, `WSI`, `WNX` | current sweep; synchronous V/I source (MM 2); multi-channel source N (MM 16) | 551, 561, 560, 557 |
| `MM`, `CMM` | measurement mode and channels; measured quantity per channel | 470, 380 |
| `RI`, `RV` | current / voltage measurement range | 501, 503 |
| `AAD`, `AIT` | ADC type; integration time | 351, 356-359 |
| `XE`, `AB`, `*OPC?`, `NUB?` | trigger; abort; wait for completion; data count | 570, 351, 479, 478 |
| `ERRX?`, `LOP?` | oldest error code and message; per-slot output state | 431, 446-447 |
| `*TST?`, `*CAL?`, `CM` | self-test; self-calibration; auto-calibration on/off | 540, 376, 379 |
| `SAP`, `SAR`, `SAL`, `SSP` | ASU path; ASU 1 pA auto range; ASU indicator; SCUU path | 505, 506, 505, 519 |
| `SIM`, `SPRM`, `SPPER` | SPGU mode PG/ALWG; count or duration (free run never); pulse period | 508, 512-513, 512 |
| `SER`, `SPM`, `SPT`, `SPV` | SPGU load (sets the open-load level); 2/3-level mode; timing; levels | 507, 510-511, 514-517 |
| `SPUPD`, `SRP`, `SPP`, `SPST?` | apply setup (base level); start; stop; output active | 515-516, 518, 511, 513-514 |
| `ODSW`, `STGP`, `CORRSER?`, `ALW`/`ALS` | pulse switch; trigger out; load measurement; ALWG data blocks | 478, 523, 385-386, 360-362 |

## Data status codes

Measurement status letter `A` of each data element (PG Table 1-10, PDF 53):

| Letter | Meaning (manual) | v1 trust class |
|---|---|---|
| `N` | no status error | ok |
| `T` | another channel reached its compliance | limited (excluded from fits) |
| `C` | this channel reached its compliance | limited |
| `V` | over the measurement range, or sweep aborted (automatic abort or power compliance); value 199.999E+99 | untrusted |
| `X` | a channel oscillating, or the output did not settle before the measurement | untrusted |
| `F` | SMU force saturation | untrusted |
| `G`, `S` | search target not found / search stopped (quasi-pulsed spot: timing problems) | untrusted |
| `U`, `D` | CMU null-loop unbalance / CMU IV amplifier saturation | untrusted |

- Deck slide 9 glosses `V` as "output overvoltage or unstable" and `D` as "data invalid"; the manual definitions
  above win. Any other letter (or none) counts as untrusted. Source-data elements carry `W`/`E` instead (sweep step
  intermediate/last, PG Table 1-7, PDF 52); they are not measurement statuses.
- Severity for SMUs: N < G < S < T < C < V < X (PG PDF 51).
- In `data.csv` each measured value has a `<role>_<V|I>_status` column; trust and refusal rules:
  [06](06-analysis-extraction.md#run-table-and-trust-classes).
- Deck slide 9 suggests re-measuring when more than 10 % of points are abnormal; v1 warns when more than 5 % of the
  points inside a fit window are limited and refuses extraction on any untrusted point.

## Integration time and ranging

- ADC types (`AAD`, PG PDF 351): high-speed (initial setting, every SMU), high-resolution (not on MCSMU, HCSMU,
  HVSMU), high-speed for pulses. Integration (`AIT`, PG PDF 356-359): auto, manual sample count, power-line cycles
  (PLC, 1-100), or time.
- v1 recipes expose only an `integration` preset: `short` = high-speed ADC auto with N = 1 (fastest, noisiest),
  `medium` (default) = 1 PLC, `long` = 16 PLC. Estimates assume 50 Hz (20 ms per PLC).
- Longer integration lowers noise and improves repeatability at the cost of time; low currents and low voltages
  need it most (PG PDF 80). Raising the preset is an autonomous re-measure knob (skill part 7) as long as the
  new plan stays `ok` and inside the run-time limit.
- Ranging: auto (initial), limited auto (never below a given range) or fixed; fewer range changes are faster
  (PG PDF 80). Recipes choose it per role: `irange` (limited auto from that range, `RI ch,+code`), `asu_1pa`
  (limited auto from the ASU's 1 pA range, R-ASU-01) or a `ranges` survey (fixed ranges, the zero check). Low-current points need settling time after a range change; slow settling shows as `X` or drift.
- The wait before a measurement grows with cable and DUT capacitance; slow-response devices need longer hold and
  delay times (PG PDF 81).

## Zero check floor

Implemented (`zero_floor`, M7; recipe `system.zero_check`; the definition shared with
`src/b1500_test_agent/analysis/floor.py`, kept here next to the ranging because the analysis file is at its line
budget).

- Every SMU at 0 V, terminals open: per measured current and range label (`<role>_range`) the offset = mean and the
  floor = sample standard deviation of the trusted readings (3 significant digits). One result per role:
  `<role>_floor` = floor on its lowest range; `fit` = the floor of every range (`10pA`, `1nA` ...), `offset` (lowest
  range) and `max_abs_offset`. Options `max_floor_a`, `max_offset_a` give `pass`/`fail`. C/T readings at 0 V are
  excluded and warned: the terminal is not open. Trust classes as in
  [06](06-analysis-extraction.md#run-table-and-trust-classes).

## Status byte errors and interlock

- Status byte (PG PDF 76-78): bit 0 data ready, bit 1 wait, bit 3 interlock open (with output above the allowed
  threshold), bit 4 set ready, bit 5 error, bit 6 service request.
- `ERRX?` returns the oldest error code with its message (PG PDF 431). Families (PG PDF 575-601): 100-299
  syntax, parameter and setup (100 undefined command, 200 output switch must be on, 201 compliance must be set,
  202 interlock must be closed, 203 cannot enable channel), 300-399 hardware condition (305 excess current in
  HPSMU: outputs switched off), 600-699 setup conflicts. Lookup:
  `references/manuals/structured/b1500a-error-codes.yaml` (partial).
- Interlock: with the Interlock terminal open, SMU output is limited to ±42 V (UG PDF 55); a red LED lights above
  ±42 V (UG PDF 49); the interlock function must be checked daily (UG PDF 142). v1 never exceeds 42 V, so no v1
  workflow needs a closed interlock (deck slide 8 rule kept as R-IL-01 for later).
- `station_status.interlock` says what the reading means: on the simulator the scenario's state (`SIMULATED
  open`); on hardware "not used at this station" plus status bit 3, which the B1500A sets only for a refused
  request above 42 V with the interlock open (PG PDF 76), so a clear bit never means "closed".

## Self-test self-calibration and auto calibration

- Self-test `*TST?` (PG PDF 540) and self-calibration `*CAL?` (PG PDF 376) are recipes `system.self_test` and
  `system.self_cal` (simulator and hardware); they always need confirmation and require open measurement terminals
  (UG PDF 142): ask the human to lift the probes first. Both leave every module in the `CL` state; a failed module
  stays disabled until service (PG PDF 541).
- Auto calibration (`CM`, PG PDF 79): when on, the instrument self-calibrates every 30 minutes after a
  measurement and needs open terminals; with a DUT left connected it may calibrate badly or put unexpected output on
  the terminals. Initial setting after reset: off (PG Table 2-13, PDF 180). Deck slide 9: "may auto-calibrate every
  30 minutes". Rule R-CAL-01 records the state as a warning.

## Manual extracts and page conventions

Structured extracts (read-only, outside this skill; open them by path):

- `references/manuals/structured/b1500a-command-parameters.md`: channel numbers, modes, FMT, status/channel/type
  codes, status byte, ranging, timing.
- `references/manuals/structured/b1500a-command-summary.yaml`: command lookup with PDF pages.
- `references/manuals/structured/b1500a-error-codes.yaml`: error codes (partial, sampled).
- `references/manuals/structured/b1500a-initial-settings.md`: reset defaults (Table 2-13).
- `references/manuals/structured/b1530a-*`: WGFMU library, timing and errors (reserved pulse work).

"PDF N" is the physical 1-based page of the PDF; printed pages look like `4-62`. For PG chapter 4,
PDF = printed + 318 (see `references/manuals/b1500a-programming-guide-index.md`).
