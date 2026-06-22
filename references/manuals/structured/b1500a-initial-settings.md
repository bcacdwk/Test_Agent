# B1500A Initial Settings

Source: `B1500A Programming Guide.pdf`, Chapter 2 "Initial Settings", especially Table 2-13 on PDF 179 / printed 2-92.

## Coverage

| Item | Coverage | Source |
|---|---:|---|
| Table 2-13 Initial Settings of Mainframe, SMU, and CMU | Complete transcription | PDF 179, printed 2-92 |
| SPGU defaults | Partial summary only | PDF 178, printed 2-91 |
| `*RST` behavior | Cross-referenced from command reference and Table 2-13 | PDF 501, printed 4-184; PDF 179 |
| `IN` behavior | Cross-referenced from command reference/index | PDF 440, printed 4-123 |

## Reset and Initialize Commands

| Command | Effect | Clears program memory? | Source |
|---|---|---:|---|
| `*RST` | Resets B1500 to initial settings. Program memory is not cleared. | No | PDF 501 / printed 4-184; Table 2-13 PDF 179 |
| `IN` | Initializes specified channels to 0 V and behaves like a broader initialization route; use when program memory must also be cleared according to the command reference/index. | Yes | PDF 440 / printed 4-123; revised index notes |
| Device clear | Clears some runtime states but does not clear program memory per Table 2-13 note. | No | PDF 179 / printed 2-92 |

## Table 2-13: Initial Settings of Mainframe, SMU, and CMU

| Setup Item | Initial Setting | Commands | Source |
|---|---|---|---|
| Auto calibration | off | `CM` | PDF 179 / 2-92 |
| SMU output switch | open | `CN`, `CL` | PDF 179 / 2-92 |
| SMU filter / series resistor | off / off | `FL`, `SSR` | PDF 179 / 2-92 |
| ASU path / 1 pA auto range / indicator | SMU side / disable / enable | `SAP`, `SAR`, `SAL` | PDF 179 / 2-92 |
| SCUU path / indicator | open / enable | `SSP`, `SSL` | PDF 179 / 2-92 |
| SMU current measurement range, with pulse | compliance range | `RI` | PDF 179 / 2-92 |
| SMU current measurement range, without pulse | auto | `RI` | PDF 179 / 2-92 |
| SMU voltage measurement range, with pulse | compliance range | `RV` | PDF 179 / 2-92 |
| SMU voltage measurement range, without pulse | auto | `RV` | PDF 179 / 2-92 |
| SMU A/D converter | high speed ADC | `AAD` | PDF 179 / 2-92 |
| SMU ADC integration time | high speed ADC: auto, non-parallel; high resolution ADC: auto | `AIT`, `PAD` | PDF 179 / 2-92 |
| SMU ADC zero function | off | `AZ` | PDF 179 / 2-92 |
| SMU AV command parameter | number=1, mode=0 | `AV` | PDF 179 / 2-92 |
| CMU measurement parameter | Cp-G | `IMP` | PDF 179 / 2-92 |
| CMU measurement range | auto | `RC` | PDF 179 / 2-92 |
| CMU ADC integration time | auto | `ACT` | PDF 179 / 2-92 |
| CMU correction/compensation | Open/Short/Load: off/off/off; phase compensation: auto | `CORRST` (Table 2-13 uses labels OPEN/SHOR/LOAD but the actual command is `CORRST` with type parameter), `ADJ` | PDF 179 / 2-92 |
| CMU AC signal | 0 V, 1 kHz | `ACV` | PDF 179 / 2-92 |
| Sweep source parameters | cleared | `WV`, `WSV`, `WI`, `WSI`, `WDCV` | PDF 179 / 2-92 |
| Pulse source parameters | cleared | `PV`, `PI` | PDF 179 / 2-92 |
| Pulse sweep source parameters | cleared | `PWV`, `PWI` | PDF 179 / 2-92 |
| Search source parameters | cleared | `BSV`, `BSSV`, `BSI`, `BSSI`, `LSV`, `LSSV`, `LSI`, `LSSI` | PDF 179 / 2-92 |
| Search monitor parameters | cleared | `BGV`, `BGI`, `LGV`, `LGI` | PDF 179 / 2-92 |
| Search measurement data | source output value only | `BSVM`, `LSVM` | PDF 179 / 2-92 |
| Quasi-pulse source parameters | cleared | `BDV` | PDF 179 / 2-92 |
| Quasi-pulsed spot measurement mode | voltage | `BDM` | PDF 179 / 2-92 |
| Quasi-pulse settling detection interval | short | `BDM` | PDF 179 / 2-92 |
| Sampling source | cleared | `MI`, `MV` | PDF 179 / 2-92 |
| Sampling interval, sampling point | 2 ms, 1000 points | `MT` | PDF 179 / 2-92 |
| Automatic abort function | off | `WM`, `BSM`, `LSM`, `WMDCV`, `MSC` | PDF 179 / 2-92 |
| Output after measurement | start value; bias value for `MSC` | `WM`, `BSM`, `LSM`, `WMDCV`, `MSC` | PDF 179 / 2-92 |
| Pulse width | 0.001 s | `PT` | PDF 179 / 2-92 |
| Pulse period | 0.01 s | `PT` | PDF 179 / 2-92 |
| Hold time | 0 s | `WT`, `PT`, `BDT`, `BST`, `LSTM`, `WTDCV`, `MT` | PDF 179 / 2-92 |
| Delay time | 0 s | `WT`, `PT`, `BDT`, `BST`, `LSTM`, `WTDCV` | PDF 179 / 2-92 |
| Step delay time | 0 s | `WT`, `WTDCV` | PDF 179 / 2-92 |
| Trigger delay time | 0 s | `WT`, `PT`, `WTDCV` | PDF 179 / 2-92 |
| Trigger mode | `XE`, `TV`, `TI`, or GET | `TM` | PDF 179 / 2-92 |
| Trigger port: Ext Trig In | Start Measurement trigger input | `TGP` | PDF 179 / 2-92 |
| Trigger port: Ext Trig Out | Measurement Completion trigger output | `TGP` | PDF 179 / 2-92 |
| Digital I/O trigger state | cleared | `TGP` | PDF 179 / 2-92 |
| Start Step Output Setup trigger condition | with trigger for first sweep step | `TGSI` | PDF 179 / 2-92 |
| Type of output trigger | edge trigger | `TGXO`, `TGSO`, `TGMO` | PDF 179 / 2-92 |
| Digital I/O port | output for all port | `ERM` | PDF 179 / 2-92 |
| Program memory | cleared initially; not cleared by `*RST` or device clear | `SCR` | PDF 179 / 2-92 |
| Internal variable values | `%In`, `%Rn` = 0 | `VAR` | PDF 179 / 2-92 |
| Data output format | ASCII with header, `CR/LF^EOI` | `FMT` | PDF 179 / 2-92 |
| Data output buffer | cleared | `BC` | PDF 179 / 2-92 |
| Status byte | only bit 6 enabled | `*SRE` | PDF 179 / 2-92 |
| Error code register | cleared | `ERRX?`, `ERR?` | PDF 179 / 2-92 |

## SPGU Defaults Summary

Source: Table 2-12 on PDF 178 / printed 2-91. This is summarized, not a full extraction of every SPGU row.

| Setup Item | Initial Setting | Commands | Source |
|---|---|---|---|
| Operation mode | PG mode | `SIM` | PDF 178 / 2-91 |
| Pulse period | 1.0 us | `SPPER` | PDF 178 / 2-91 |
| Channel output operation mode | Free run | `SPRM` | PDF 178 / 2-91 |
| Channel output mode | Pulse source 1, 2-level pulse output | `SPM` | PDF 178 / 2-91 |
| DC source setup | 0 V | `SPV` | PDF 178 / 2-91 |
| Pulse source setup | delay 0 s, width 100 ns, leading 20 ns, trailing 20 ns, base -0.5 V, peak 0.5 V | `SPT`, `SPV` | PDF 178 / 2-91 |
| ALWG setup | cleared | `ALW`, `ALS` | PDF 178 / 2-91 |
| Pulse switch | disable, normally open, delay 0 s, width 100 ns | `ODSW` | PDF 178 / 2-91 |
| DUT load impedance | 50 ohm | `SER` | PDF 178 / 2-91 |
| SPGU trigger output | disable | `STGP` | PDF 178 / 2-91 |
| SPGU setup in sampling measurement | cleared | `MSP` | PDF 178 / 2-91 |

## Practical Driver Notes

- After `*RST`, assume program memory persists. Do not use `*RST` to clear stored programs.
- `IN` clears program memory AND resets to initial settings. Use `IN` for full initialization.
- Default `FMT` is ASCII with header and `CR/LF^EOI`.
- Default status byte enables only bit 6 in `*SRE`; explicit SRQ behavior should be configured by the driver.
- Default SMU output switch state is open; call `CN`/`CNX` before source or measurement commands that require enabled output.
- `DZ`/`RZ` are stateful: `DZ` stores settings, `RZ` restores them and clears stored settings.
- Status byte bit 0 = Data ready (buffer not empty), bit 3 = Interlock open, bit 4 = Set ready, bit 5 = Error. See `b1500a-command-parameters.md` for full bit table.
- Query response buffer stores only ONE response; read immediately. Measurement data uses a separate output data buffer.
- "OPEN/SHOR/LOAD" in Table 2-13's Commands column are type labels for the `CORRST` command, not standalone GPIB mnemonics.

---

## Review Notes

| Field | Value |
|---|---|
| Review date | 2026-06-22 |
| Reviewer | opus-4.6-max |
| Passes | 5 |

Corrections applied:

- Annotated OPEN/SHOR/LOAD in CMU correction row as `CORRST` type labels, not standalone commands.
- Added practical driver notes about status byte bits, query buffer behavior, and OPEN/SHOR/LOAD disambiguation.
- Added `IN` vs `*RST` distinction note to practical section.
- SPGU pulse period confirmed as 1.0 μs (consistent with SPPER command page initial setting 1E-6 s; PDF table text shows "1.0 s" due to OCR rendering of μ).

Remaining uncertainties:

- Table 2-13 transcription is complete for PDF 179 content; however, separate Tables 2-9 (PDF 175), 2-10 (PDF 176), 2-11 (PDF 177) contain additional per-module detail not duplicated here.
- Device clear exact behavior (which states persist, which clear) is described in general terms but exact per-parameter behavior requires reading each command page's reset/device-clear notes.
