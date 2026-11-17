# B1500A Programming Guide Index

## Source

| Field | Value |
|-------|-------|
| PDF Path | `B1500A Programming Guide.pdf` (relative to workspace root) |
| Manual Title | Keysight B1500A/B1505A/B1506A/B1507A Device Analyzer Series Programming Guide |
| Part Number | B1500-90010 |
| Edition | Edition 15, May 2022 |
| Publisher | Keysight Technologies Japan K.K., 9-1, Takakura-cho, Hachioji-shi, Tokyo 192-8550 Japan |
| Total PDF Pages | 617 |
| Page Numbering Convention | **"PDF N" and the PDF Page(s) columns are physical 1-based PDF pages** (the page number a PDF viewer shows; PDF 1 is the cover). "Printed" pages are the manual's own `chapter-page` numbers (e.g., 1-3, 2-5, 4-33). Front matter (PDF 1–20) has no printed page numbers. Each chapter has an unnumbered title page (implicitly `X-1`) followed by content starting at `X-2`. Verified 2026-11-17 against the PDF page footers (Revision 3). |

### PDF Page ↔ Printed Page Mapping Formula

To convert printed page numbers to PDF page numbers:

| Chapter | Printed Page Format | Formula: PDF page = | Chapter Title PDF Page | Content Start PDF Page | Last Content PDF Page |
|---------|--------------------|--------------------|----------------------|----------------------|---------------------|
| Front Matter | (none) | N/A | — | PDF 1 (cover) | PDF 20 (end of Contents) |
| 1. Programming Basics | 1-N | N + 20 | PDF 21 | PDF 22 (printed 1-2) | PDF 88 (printed 1-68) |
| 2. Remote Mode Functions | 2-N | N + 88 | PDF 89 | PDF 90 (printed 2-2) | PDF 180 (printed 2-92) |
| 3. Programming Examples | 3-N | N + 180 | PDF 181 | PDF 182 (printed 3-2) | PDF 318 (printed 3-138) |
| 4. Command Reference | 4-N | N + 318 | PDF 319 | PDF 320 (printed 4-2) | PDF 572 (printed 4-254) |
| 5. Error Messages | 5-N | N + 572 | PDF 573 | PDF 574 (printed 5-2) | PDF 616 (printed 5-44) |
| Back cover | (none) | N/A | — | PDF 617 | PDF 617 |

**Example:** To find printed page 4-118 (FMT command), calculate: 118 + 318 = PDF page 436. Table 4-24 (FMT formats) is on the next page, printed 4-119 = PDF 437.

**Spot checks (PDF page → printed footer):** 22 → 1-2, 44 → 1-24, 53 → 1-33 (Table 1-10), 90 → 2-2, 180 → 2-92 (Table 2-13), 182 → 3-2, 320 → 4-2, 436 → 4-118 (`FMT`), 437 → 4-119 (Table 4-24), 572 → 4-254, 574 → 5-2, 616 → 5-44. Every page from PDF 22 to PDF 616 has a footer that matches these formulas, except the unnumbered chapter title pages.

**Correction note (Revision 3):** Earlier revisions used formulas `N + 19 / 87 / 179 / 317 / 571`, so most PDF numbers were one page low. Some Chapter 2 rows (MM10 to MM26) were already correct. All PDF numbers in this file were recomputed from their printed pages, not shifted, and PDF-only rows were checked against the page text.

## How To Use This Index

1. **Find a topic by name** → Use the Content To Page Map table below. Ctrl-F for a command name, concept, or keyword.
2. **Find what is on a specific page** → Use the Page To Content Map table. Look for the PDF page range that includes your page.
3. **Quick lookup for common tasks** → Jump to the High-Value Lookup Shortcuts section.
4. **Convert page references** → Use the formula table above.
5. **When reading the PDF programmatically:** Use physical page numbers (for example `pdftotext -f N -l N`). If a text extraction prints page markers such as `-- X of 617 --`, check whether a marker follows or precedes its page text before mapping; misreading this is the likely source of the old off-by-one numbers.
6. **For command syntax:** Go directly to Chapter 4 (PDF 319–572). The Command Summary table (PDF 321–333) gives a 1-line description of every command. The full Command Reference (PDF 350–572) has syntax, parameters, and examples alphabetically.

## Content To Page Map

### Front Matter (PDF 1–20)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Title Page | 1 | — | Manual title, model numbers (B1500A/B1505A/B1506A/B1507A) | — | — |
| Notices / Copyright | 2 | — | Copyright 2005–2022, part number B1500-90010, edition history (Ed 1–15), warranty, technology licenses | Edition 15, May 2022 | — |
| Blank pages | 3–4 | — | Blank | — | — |
| Measurement Resources | 5 | — | Table showing which measurement resources (HPSMU, MPSMU, MCSMU, MFCMU, HRSMU, HVSPGU, HVSMU, HVMCU, HCSMU, UHCU, UHVU) are supported by each mainframe model (B1500A, B1505A, B1506A, B1507A). Lists module model numbers. | B1510A, B1511A/B, B1514A, B1520A, B1517A, B1525A, B1513A/B/C, N1266A, B1512A, N1265A, N1268A | Essential for determining which commands apply to your hardware |
| In This Manual | 6 | — | Overview of 5 chapters: Programming Basics, Remote Mode Functions, Programming Examples, Command Reference, Error Messages | — | — |
| Table of Contents | 7–20 | — | Detailed TOC for all 5 chapters with printed page numbers | — | — |

### Chapter 1: Programming Basics (PDF 21–88, Printed 1-2 to 1-68)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 1 Title | 21 | — | Chapter divider page | — | — |
| Chapter Overview | 22 | 1-2 | Lists chapter sections, explains HP BASIC command notation convention (ASSIGN, OUTPUT, ENTER statements) | ASSIGN, OUTPUT, ENTER, @B1500, GPIB address 717 | HP BASIC used for examples in this chapter |
| Before Starting | 23–26 | 1-3 to 1-6 | How to prepare B1500 for remote GPIB control: terminate EasyEXPERT, configure Connection Expert (GPIB address, System Controller=No, Auto-discover=No), reboot. FlexGUI window description (status indicators, GPIB capturing/logging, debug tools). | EasyEXPERT, Connection Expert, GPIB0, 82350B, 82357A/B, GPIB-USB-HS, FlexGUI, RMT/LTN/TLK/SRQ indicators | Use even GPIB address with USB/GPIB to reduce serial poll errors. Start EasyEXPERT button must remain on screen/taskbar. |
| Getting Started | 27–41 | 1-7 to 1-21 | Step-by-step basics: reset (`*RST`), query response, self-test (`*TST?`), self-calibration (`*CAL?`), diagnostics (`DIAG?`), enable channels (`CN`), measurement mode (`MM`), force voltage/current (`DV`/`DI`), integration time (`AIT`), measurement range (`RI`/`RV`), pause (`PA`), start measurement (`XE`), force 0V (`DZ`), disable channels (`CL`), ASU control (`SAP`/`SAR`/`SAL`), SCUU control (`SSP`/`SSL`), read errors (`ERR?`/`ERRX?`/`EMG?`), read spot data, read sweep data, read timestamp data, high-speed spot measurement (`TI`/`TV`/`TIV`). | `*RST`, `*TST?`, `*CAL?`, `DIAG?`, `CN`, `MM`, `DV`, `DI`, `AIT`, `RI`, `RV`, `PA`, `XE`, `DZ`, `CL`, `SAP`, `SAR`, `SAL`, `SSP`, `SSL`, `ERR?`, `ERRX?`, `EMG?`, `TI`, `TV`, `TIV`, `NUB?` | MM mode table given here (modes 1–28). Query buffer stores only one response—read immediately. |
| Command Input Format | 42–44 | 1-22 to 1-24 | Explains GPIB command syntax: header (mnemonic), numeric data (integer/real/expression), terminator (CR/LF with EOI), special terminators (semicolons to combine commands), separator rules. | Header, NR1/NR2/NR3, terminator, CR/LF, EOI, semicolon separator | Multiple commands can be sent in one OUTPUT statement separated by semicolons |
| Data Output Format – ASCII | 45–55 | 1-25 to 1-35 | Comprehensive description of ASCII measurement data output. Covers: data format conventions, time stamp format (TSC/TSR), data format by measurement mode (spot, sweep, search, sampling, QSCV, C measurements), data elements (Table 1-6 layouts: `ABC`+12 digits for FMT 1/5, `ABC`+13 for FMT 11/15, `EEEFG`+13 for FMT 21/25, no header for FMT 2/12/22), source data status W/E (Table 1-7), summed `EEE` status for SMU/CMU (Tables 1-8/1-9), measurement status N/T/C/V/X/F/G/S/U/D (Table 1-10, PDF 53), channel numbers (A-J, a-j, V, Z; Table 1-11), data types (Table 1-12). | `FMT`, `TSC`, `TSR`, status N/T/C/V/X/F/G/S/U/D, W/E, EEE, channel A-J/a-j/V/Z, data type C/G codes, `NUB?`, `BC` | Status meanings: N=normal, T=another channel compliance, C=this channel compliance, V=over range or sweep aborted (data 199.999E+99), X=oscillation or source not settled, F=SMU force saturation, G/S=search not found/stopped (quasi-pulsed spot: detection time over / settling not detected), U=CMU NULL loop unbalance, D=CMU IV amplifier saturation. There is no `L` status. |
| Data Output Format – Binary | 56–74 | 1-36 to 1-54 | Binary data format (4-byte and 8-byte). Time stamp in binary. Data resolution formulas (PDF 57). 4-byte elements (PDF 61–67): type, parameter, 5-bit range, data count, 3-bit status (Table 1-13), 5-bit channel. 8-byte elements (PDF 68–74, Figure 1-3): type bit, 7-bit parameter, range byte, 4-byte data count, status byte (Table 1-15), 3-bit A/D converter, 5-bit channel; time data uses a 6-byte count. Data are integer counts scaled by range (for example SMU 8-byte data = Count × Range / 1000000, PDF 71), not IEEE 754 floats. | `FMT 3`, `FMT 4`, `FMT 13`, `FMT 14`, 4-byte binary, 8-byte binary, range codes, data count formula | FMT 3/4 = 4-byte; FMT 13/14 = 8-byte (PDF 57). FMT 5 is ASCII, not binary. 4-byte format has lower resolution than the high-resolution ADC and no time stamp. |
| GPIB Interface Capability | 75 | 1-55 | Table listing B1500's GPIB capabilities (SH1, AH1, T5, TE0, L4, LE0, SR1, RL1, PP0, DC1, DT1, C0, E1) | SH1, AH1, T5, L4, SR1, RL1, DC1 | — |
| Status Byte | 76–78 | 1-56 to 1-58 | Describes the 8-bit status byte register. Bit 0 (not used), Bit 1 (not used), Bit 2 (not used), Bit 3 (output buffer not empty), Bit 4 (set ready = operation complete), Bit 5 (error occurred), Bit 6 (RQS/SRQ), Bit 7 (not applicable). Masking with `*SRE`, reading with serial poll or `*STB?`. | `*SRE`, `*STB?`, serial poll, SRQ, status byte bits 3/4/5/6 | Bit 4 goes low on command receipt, high on completion. Use serial poll in ISR, `*STB?` otherwise. Masked bits behavior is non-trivial—read carefully. |
| Programming Tips | 78–88 | 1-58 to 1-68 | Practical optimization techniques: confirm operation (ERRX? after XE), confirm command completion (*OPC?), disable auto-cal (CM 0), optimize measurement range, optimize integration time (AIT), disable ADC zero (AZ 0), optimize source/measurement wait time (WT), use internal program memory, time data resolution, sweep source as constant source, start measurements simultaneously, quasi-sampling, interrupt command execution (AB), legacy program migration from 4142B/4155/4156/E5260/E5270. | `*OPC?`, `CM`, `AZ`, `WT`, `AB`, `SCR`, `END`, `DO`, `RU`, 4142B compatibility, E5260/E5270 compatibility | Unsupported 4142B commands listed in Table 1-15. Unsupported E5260/E5270 commands in Table 1-19. For 4155/4156 migration, verify US/FMT/CN compatibility. |

### Chapter 2: Remote Mode Functions (PDF 89–180, Printed 2-2 to 2-92)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 2 Title | 89 | — | Chapter divider page | — | — |
| Chapter Overview | 90 | 2-2 | Lists all topics in this chapter. Note about synchronous output availability. | — | — |
| Measurement Modes – Overview | 91 | 2-3 | Lists all 19 measurement modes available. Note about search measurements. | MM modes 1–28 | — |
| Spot Measurements | 92 | 2-4 | MM1. Single-point IV measurement. Flowchart: CN→DV/DI→MM→XE→read data. Up to 10 channels measured sequentially. | MM 1, DV, DI, CN, XE, CMM | — |
| Pulsed Spot Measurements | 93 | 2-5 | MM3. Pulse output with measurement at pulse peak. Timing diagram with hold time, pulse width, pulse period. | MM 3, PT, PV, PI, AIT 2 | Only one channel for source and one for measurement |
| Multi Channel Pulsed Spot | 94–95 | 2-6 to 2-7 | MM27. Multiple channels pulsed simultaneously. Detailed timing with MCPT parameters. | MM 27, MCPT, MCPNT, MCPNX, AIT 2 | Up to 10 source channels, multiple measurement channels |
| Staircase Sweep Measurements | 96–98 | 2-8 to 2-10 | MM2. Stepped voltage/current sweep. Timing diagram showing hold, delay, step delay, measurement time per step. Synchronous sweep source (WSV/WSI). Automatic abort. | MM 2, WV, WI, WT, WM, WSV, WSI, AIT 0 | Start and stop must have same polarity for log sweep |
| Staircase Sweep with Pulsed Bias | 98–100 | 2-10 to 2-12 | MM5. Combined staircase sweep + pulsed bias on another channel. Timing with pulse period, pulse width, measurement during pulse. | MM 5, WV, WI, WM, PT, PV, PI, AIT 2 | Sweep and pulse channels must be different |
| Pulsed Sweep Measurements | 100–102 | 2-12 to 2-14 | MM4. Pulsed sweep with stepped pulse amplitudes. Each sweep step is one pulse. Timing diagram. | MM 4, PWV, PWI, PT, WM, WSV, WSI | — |
| Multi Channel Sweep | 102–104 | 2-14 to 2-16 | MM16. Multiple sweep sources output simultaneously with stepped values. WNX command for additional sources. | MM 16, WV, WI, WNX, WT, WM | High-speed ADC + fixed range channels measured simultaneously |
| Multi Channel Pulsed Sweep | 104–106 | 2-16 to 2-18 | MM28. Multiple pulsed sweep sources. MCPWS for sweep mode/steps. | MM 28, MCPT, MCPNT, MCPWS, MCPWNX | — |
| Quasi-Pulsed Spot | 106–108 | 2-18 to 2-20 | MM9. Applies voltage in quick ramp, measures when settled, ramps back. Detection modes (voltage/current). | MM 9, BDV, BDT, BDM | Timestamp not available |
| Binary Search Measurements | 108–110 | 2-20 to 2-22 | MM15. Binary search algorithm to find threshold. Uses search source + monitor channel. | MM 15, BSV, BSI, BGV, BGI, BSM, BSVM, BST | Timestamp not available |
| Linear Search Measurements | 110–112 | 2-22 to 2-24 | MM14. Linear step search to find threshold. More steps than binary but guaranteed coverage. | MM 14, LSV, LSI, LGV, LGI, LSM, LSTM, LSVM | Timestamp not available |
| Sampling Measurements | 112–115 | 2-24 to 2-27 | MM10. Time-domain sampling. Linear or log sampling modes. Timing with hold(base), hold(bias), interval, number of points. | MM 10, MCC, MSC, ML, MT, MI, MV, MSP, AIT 0 | Interval minimum depends on number of channels and ADC mode |
| Quasi-static CV Measurements | 115–118 | 2-27 to 2-30 | MM13. Charge-based CV using SMU (no CMU needed). Step voltage, measure charge current. Multiple integration modes. Leakage compensation. | MM 13, QSV, QST, QSM, QSL, QSO, QSC, QSR, QSZ | Complex setup; requires understanding of charge integration |
| Spot C Measurements | 118–119 | 2-30 to 2-31 | MM17 (impedance measurement mode). Single-point capacitance using MFCMU. Sets AC signal + DC bias + frequency. | MM 17, IMP, FC, ACV, DCV, LMN | Requires MFCMU (B1520A) |
| Pulsed Spot C Measurements | 119–121 | 2-31 to 2-33 | MM19. Pulsed DC bias with C measurement at pulse peak. | MM 19, IMP, FC, ACV, PTDCV, PDCV | — |
| CV (DC bias) Sweep Measurements | 121–124 | 2-33 to 2-36 | MM18. Sweep DC bias while measuring C at each point. | MM 18, IMP, FC, ACV, WDCV, WTDCV, WMDCV | First chnum in MM must be MFCMU |
| Pulsed Sweep CV Measurements | 124–126 | 2-36 to 2-38 | MM20. Pulsed DC bias sweep with C measurement. | MM 20, IMP, FC, ACV, PTDCV, PWDCV, WTDCV, WMDCV | — |
| C-f Sweep Measurements | 126–128 | 2-38 to 2-40 | MM22. Sweep frequency while measuring C. | MM 22, IMP, DCV, ACV, WFC, WTFC, WMFC | — |
| CV (AC level) Sweep Measurements | 128–129 | 2-40 to 2-41 | MM23. Sweep AC oscillator level while measuring C. | MM 23, IMP, FC, DCV, WACV, WTACV, WMACV | — |
| C-t Sampling Measurements | 130–132 | 2-42 to 2-44 | MM26. Time-domain capacitance sampling. | MM 26, IMP, FC, ACV, MDCV, MTDCV | — |
| Synchronous Output | 132–134 | 2-44 to 2-46 | Explains synchronous sweep source that tracks primary sweep. Available for staircase sweep, pulsed sweep, and search. | WSV, WSI, LSSV, LSSI, BSSV, BSSI | Same output mode as primary; does not support pulsed output |
| Automatic Abort Function | 134–135 | 2-46 to 2-47 | Explains when auto-abort triggers (compliance, overflow, oscillation). Post-measurement output behavior. | WM, BSM, LSM, MSC, WMDCV, WMFC, WMACV | If disabled, still aborts on power compliance for sweep source |
| Parallel Measurement Function | 136–137 | 2-48 to 2-49 | PAD command enables parallel A/D conversion for faster multi-channel measurement. Required conditions (high-speed ADC, non-pulsed, fixed range). | PAD | Only works with high-speed ADC, non-pulsed, and fixed measurement range |
| Program Memory | 137–140 | 2-49 to 2-52 | Internal program memory (up to 100 programs). SCR/END to store, DO/RU to execute. Variables %In/%Rn. Invalid commands list (Table 2-1). | SCR, END, DO, RU, PA, LST?, VAR, %In, %Rn | Some commands invalid inside program memory; see Table 2-1 |
| Dual HCSMU | 140–141 | 2-52 to 2-53 | Using two HCSMU as one dual channel (occupies 2 slots). | HCSMU, B1512A | — |
| SPGU Module | 141–152 | 2-53 to 2-64 | Comprehensive SPGU (B1525A) description. PG operation mode (2-level/3-level pulses, ALWG mode). Pulse timing parameters. Output configurations. ALWG waveform patterns. Trigger modes. | SPGU, B1525A, SIM, SPM, SPPER, SPT, SPV, SPRM, SRP, SPP, SPUPD, SOPC, SOVC | Two operation modes: PG and ALWG. PG for standard pulses, ALWG for arbitrary waveforms. |
| Module Selector | 152–153 | 2-64 to 2-65 | Describes N1258A/B1506A module selector for routing connections. | ERMOD, ERS? | — |
| External Relay Control Output | 153 | 2-65 | Digital I/O used for external relay control. | ERM, ERC | — |
| SMU/PG Selector | 154 | 2-66 | 16440A SMU/PGU selector (B1500A-A04). Switch between SMU and PGU. | ERSSP, ERMOD | — |
| Ultra High Current Expander/Fixture | 155–157 | 2-67 to 2-69 | N1265A operation: combines 2 MCSMU/HCSMU for up to 2000A. Self-test/calibration commands. | N1265A, ERPFUHCA, ERPFUHCTST?, ERPFUHCCAL?, ERMOD 4 | Requires ERMOD 4 to set DIO to N1265A control mode |
| HVSMU Current Expander | 157 | 2-69 | N1266A: combines HVSMU + 2 MCSMU for high voltage + medium current. | N1266A, ERHVCA, ERHVCTST?, ERHVPV | — |
| Ultra High Voltage Expander | 158 | 2-70 | N1268A: ultra high voltage output using MC/HCSMU pair. | N1268A, ERUHVA, ERMOD 16 | — |
| Digital I/O Port | 159–161 | 2-71 to 2-73 | 8-bit digital I/O port. Accessories (16445A adapters). Internal circuit diagram. Pin assignments. | ERM, ERC, 16445A | Default: all bits are output |
| Trigger Function | 162–174 | 2-74 to 2-86 | Comprehensive trigger system description. Trigger input (TGP, PAX, WSX), trigger output (TGP, TGXO, TGSO, TGMO), using trigger with sweep/sampling/SPGU. Timing diagrams for all modes. Internal circuit of Ext Trig In/Out. | TGP, TGPC, PAX, WSX, TGP, TGXO, TGSO, TGMO, TGSI, XE | 4 trigger I/O ports available. Edge or level trigger selectable. |
| Initial Settings | 175–180 | 2-87 to 2-92 | Complete tables of all initial/default settings: mainframe (Table 2-9, PDF 175), SMU (Table 2-10, PDF 176–177), CMU (Table 2-11, PDF 178), SPGU (Table 2-12, PDF 179), and combined mainframe/SMU/CMU table (Table 2-13, PDF 180). Every parameter's initial value and the command that sets it. Table 2-13 is the single most comprehensive reset-state reference. | `*RST`, initial values for all parameters, Table 2-13, trigger mode, DIO, FMT, program memory | Critical reference for understanding instrument state after reset. Table 2-13 (PDF 180) uniquely includes trigger, DIO, program memory, and data format initial settings. |

### Chapter 3: Programming Examples (PDF 181–318, Printed 3-2 to 3-138)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 3 Title | 181 | — | Chapter divider page | — | — |
| Chapter Overview | 182–183 | 3-2 to 3-3 | Lists all programming examples. Command notation conventions. Notes on template usage and safety (disconnect DUT after measurement). | — | PDF 183 (3-3) continues with notes on example format |
| Programming Basics for VB.NET | 184–189 | 3-4 to 3-9 | Template project setup for Visual Basic .NET with VISA COM. Complete template code (Table 3-1): connection, measurement subprogram skeleton, data save subprogram. Line-by-line explanation. | VISA COM, IResourceManager, IMessage, Open("GPIB0::17::INSTR"), WriteString, ReadString | All subsequent examples use this template or are standalone |
| High-Speed Spot Measurements | 189–192 | 3-9 to 3-12 | Example using TI/TV commands for fast single-point measurement without MM/XE. VB.NET code with explanations. | TI, TV, FMT, AV, FL, DV | Does not use MM command; direct trigger command |
| Spot Measurements | 192–195 | 3-12 to 3-15 | MM1 example. Multi-channel spot measurement. Complete code with source setup, measurement, data reading. | MM 1, DV, XE, FMT 1, CMM | — |
| Pulsed Spot Measurements | 195–198 | 3-15 to 3-18 | MM3 example. Set pulse timing, apply pulsed voltage, measure at peak. | MM 3, PT, PV, XE | — |
| Staircase Sweep Measurements | 198–208 | 3-18 to 3-28 | MM2 examples (multiple). Basic sweep, sweep with compliance check, log sweep, IV curve measurement. Detailed code. | MM 2, WV, WI, WT, WM, XE, NUB? | Multiple sub-examples showing different configurations |
| Pulsed Sweep Measurements | 208–212 | 3-28 to 3-32 | MM4 example. Pulsed sweep voltage measurement. | MM 4, PWV, PT, WM, XE | — |
| Staircase Sweep with Pulsed Bias | 212–216 | 3-32 to 3-36 | MM5 example. Combined sweep + pulsed bias. | MM 5, WV, PV, PT, WM, XE | — |
| Quasi Pulsed Spot Measurements | 216–219 | 3-36 to 3-39 | MM9 example. Fast pulsed measurement without full pulse generator. | MM 9, BDV, BDT, BDM, XE | — |
| Linear Search Measurements | 219–222 | 3-39 to 3-42 | MM14 example. Find threshold voltage by linear sweep. | MM 14, LSV, LGV, LSTM, LSM, LSVM, XE | — |
| Binary Search Measurements | 222–225 | 3-42 to 3-45 | MM15 example. Find threshold by binary search. | MM 15, BSV, BGV, BST, BSM, BSVM, XE | — |
| Multi Channel Sweep | 225–229 | 3-45 to 3-49 | MM16 example. Multiple sweep sources with WNX. | MM 16, WV, WNX, WT, WM, XE | — |
| Multi Channel Pulsed Spot | 229–232 | 3-49 to 3-52 | MM27 example. Multi-channel pulsed spot measurement. | MM 27, MCPT, MCPNT, MCPNX, XE | — |
| Multi Channel Pulsed Sweep | 232–236 | 3-52 to 3-56 | MM28 example. Multi-channel pulsed sweep. | MM 28, MCPT, MCPNT, MCPWS, MCPWNX, XE | — |
| Sampling Measurements | 236–241 | 3-56 to 3-61 | MM10 example. Time-domain current/voltage sampling. Linear and log modes. | MM 10, MCC, MSC, ML, MT, MV, MI, XE | — |
| Quasi-static CV Measurements | 241–246 | 3-61 to 3-66 | MM13 example. Charge-based CV measurement. | MM 13, QSV, QST, QSM, QSL, QSO, QSC, XE | — |
| High-Speed Spot C Measurements | 246–252 | 3-66 to 3-72 | MFCMU high-speed spot C (using TMACV/TMDCV/TC/TTC). Multiple sub-examples. | TMACV, TMDCV, TC, TTC, IMP, FC, ACV, DCV | Does not use MM/XE; direct measurement commands |
| Spot C Measurements | 252–256 | 3-72 to 3-76 | MM17 example. Single-point capacitance measurement. | MM 17, IMP, FC, ACV, DCV, XE | — |
| CV (DC Bias) Sweep Measurements | 256–261 | 3-76 to 3-81 | MM18 example. DC bias sweep capacitance measurement. | MM 18, IMP, FC, ACV, WDCV, WTDCV, WMDCV, XE | — |
| Pulsed Spot C Measurements | 261–265 | 3-81 to 3-85 | MM19 example. Pulsed DC bias with C measurement. | MM 19, IMP, FC, ACV, PTDCV, PDCV, XE | — |
| Pulsed Sweep CV Measurements | 265–270 | 3-85 to 3-90 | MM20 example. Pulsed bias sweep CV. | MM 20, IMP, FC, ACV, PTDCV, PWDCV, WTDCV, WMDCV, XE | — |
| CV (AC Level) Sweep Measurements | 270–275 | 3-90 to 3-95 | MM23 example. AC level sweep CV. | MM 23, IMP, FC, DCV, WACV, WTACV, WMACV, XE | — |
| C-f Sweep Measurements | 275–280 | 3-95 to 3-100 | MM22 example. Frequency sweep CV. | MM 22, IMP, DCV, ACV, WFC, WTFC, WMFC, XE | — |
| C-t Sampling Measurements | 280–284 | 3-100 to 3-104 | MM26 example. Time-domain capacitance sampling. | MM 26, IMP, FC, ACV, MDCV, MTDCV, XE | — |
| SPGU Pulse Output and Voltage Measurement | 285–291 | 3-105 to 3-111 | SPGU example. Configure 2-level and 3-level pulses from SPGU channels. Includes load impedance setting, pulse timing, trigger output. Separate spot voltage measurement using SMU. | SIM, SPPER, SPRM, SPM, SPT, SPV, SOPC, SPUPD, SRP, SPP, SPST?, STGP, CORRSER?, ODSW, TI | Complex example showing full SPGU workflow |
| Using Program Memory | 292–297 | 3-112 to 3-117 | Two examples of storing/executing programs in internal memory. Shows SCR/END storage, LST? display, DO execution, VAR usage. | SCR, END, LST?, DO, RU, PA, VAR | Tips: verify program before storing; some commands invalid in memory |
| Using Trigger Function | 298–310 | 3-118 to 3-130 | Multiple trigger examples: sweep with external trigger wait, triggered start, synchronization between SPGU and SMU measurement, trigger-per-step measurement. Detailed timing diagrams. | TGP, TGPC, PAX, WSX, TGXO, TGSO, TGMO, TGSI, XE | Very detailed section with multiple sub-examples |
| Reading Time Stamp Data | 310–311 | 3-130 to 3-131 | Example showing TSC/TSR usage to get measurement timestamps. | TSC, TSR, FMT | — |
| Reading Binary Output Data | 311–316 | 3-131 to 3-136 | Complete example of reading and parsing 4-byte binary data (FMT 3). Shows bit manipulation to extract status, type, mode, sign, range, count, channel from binary response. | FMT 3, TI, binary data parsing, bit manipulation | Critical for understanding binary format implementation |
| Using Programs for 4142B | 314–316 | 3-134 to 3-136 | Migration example from Keysight 4142B programs. Shows equivalent commands. | 4142B compatibility | — |
| Using Programs for 4155B/4156B/4155C/4156C | 316–318 | 3-136 to 3-138 | Migration example from Keysight 4155/4156 programs. | 4155B, 4156B, 4155C, 4156C compatibility | — |

### Chapter 4: Command Reference (PDF 319–572, Printed 4-2 to 4-254)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 4 Title | 319 | — | Chapter divider page. The abbreviation list (ASU, CMU, DHC, HC, HP, HR, HV, HVMC, MC, MP, N1265A, N1266A, N1268A, SCUU, SMU, SPGU, UHC, UHV) is on the next page (PDF 320, printed 4-2). | — | — |
| Command Summary | 321–333 | 4-3 to 4-15 | Complete table of ALL GPIB commands organized by functional category. Categories: Reset, Diagnostics, Self-test, Self-Calibration, Interlock, MFCMU Data Correction, Abort, Pause/Continue, Data Output, Source Setup, Measurement Setup, Measurement Trigger, SMU Spot Measurement, Timing/Wait, Integration Time, Ranging, Status/Error, Program Memory, Channel Mapping, Trigger I/O, SPGU, Module Selector, Digital I/O, Expander Control, HVSMU Control. | All ~200+ commands listed | Best starting point for finding any command |
| Command Parameters | 333–350 | 4-15 to 4-32 | Detailed parameter reference tables: Table 4-1 (chnum channel numbers 1-10 and 101-1001), Table 4-2 (current measurement ranging), Table 4-3 (current output ranging), Table 4-4 (voltage output ranging), Table 4-5 (current output ranging by resource), Table 4-6 through 4-16 (output ranges, compliance values, impedance parameters for each resource type). | chnum, range, irange, vrange, compliance, IMP parameters | Essential for understanding parameter values across all commands |
| Command Reference (A–B) | 350–375 | 4-32 to 4-57 | Individual command pages: AAD, AB, ACH, ACT, ACV, ADJ, ADJ?, AIT, AITM, AITM?, ALS, ALS?, ALW, ALW?, AV, AZ, BC, BDM, BDT, BDV, BGI, BGV, BSI, BSM, BSSI, BSSV, BST, BSV, BSVM | AAD (ADC select), AB (abort), ACH (channel mapping), ACT (CMU integration time), ACV (CMU AC voltage), ADJ (phase compensation), AIT (SMU integration time), AV (averaging), AZ (ADC zero), BC (buffer clear), BDM/BDT/BDV (quasi-pulse), BGI/BGV (binary search monitor), BSI/BSM/BSSI/BSSV/BST/BSV/BSVM (binary search source/settings) | — |
| Command Reference (C) | 375–386 | 4-57 to 4-68 | CA, *CAL?, CL, CLCORR, CM, CMM, CN/CNX, CORR?, CORRDT, CORRDT?, CORRL, CORRL?, CORRSER?, CORRST, CORRST? | CA (self-cal), *CAL? (self-cal with result), CL (disable channel), CM (auto-cal on/off), CMM (measurement operation mode: compliance/current/voltage/force), CN/CNX (enable channel), CORR/CORRDT/CORRL/CORRST (CMU correction) | CN enables output switch; CNX used for SPGU |
| Command Reference (D) | 386–398 | 4-68 to 4-80 | DCORR, DCORR?, DCV, DI, DIAG?, DO, DSMPLARM, DSMPLFLUSH, DSMPLSETUP, DV, DZ | DCORR (CMU load correction data), DCV (CMU DC bias), DI (force current), DIAG? (diagnostics), DO (execute program memory), DSMPL* (data sampling setup), DV (force voltage), DZ (force 0V and store settings) | DZ stores channel settings before forcing 0V; use WZ? to check output state |
| Command Reference (E) | 398–435 | 4-80 to 4-117 | EMG?, END, ERC, ERCMAA/?, ERCMAGRD/?, ERCMAIO/?, ERCMAPFGD, ERHPA/?, ERHPE/?, ERHPL/?, ERHPP/?, ERHPQG/?, ERHPR/?, ERHPS/?, ERHVCA/?, ERHVCTST?, ERHVP/?, ERHVPV, ERHVS/?, ERM, ERMOD/?, ERPFDA/?, ERPFDP/?, ERPFDS/?, ERPFGA/?, ERPFGP/?, ERPFGR/?, ERPFQG/?, ERPFTEMP?, ERPFUHCA/?, ERPFUHCCAL?, ERPFUHCMAX?, ERPFUHCTST?, ERR?, ERRX?, ERS?, ERSSP/?, ERUHVA/? | EMG? (error message), ERC (DIO output), ERCMA* (B1506A/N1272A selector), ERHP* (B1274A adapter), ERHV* (N1266A expander), ERM (DIO mode), ERMOD (module selector mode), ERPF* (N1265A UHC fixture), ERR?/ERRX? (error query), ERS? (selector status), ERSSP (SMU/PG selector) | ERR? only supports codes 0-999; use ERRX? for all errors |
| Command Reference (F–H) | 435–440 | 4-117 to 4-122 | FC, FL, FMT, HSS, HVSMUOP, HVSMUOP? | FC (CMU frequency), FL (filter on/off), FMT (`FMT format[,mode]`: data output format 1-25 per Table 4-24, source data output mode 0-10 per Table 4-25; the terminator is fixed by format), HSS (SMU response mode, normal/fast), HVSMUOP (HVSMU operation mode) | FMT is critical (Table 4-24, PDF 437): 1/5 = ASCII 12 digits with header (5 has comma terminator), 2 = ASCII no header, 3/4 = 4-byte binary, 11/15 = ASCII 13 digits with header, 12/22 = no header, 13/14 = 8-byte binary, 21/25 = ASCII 13 digits with EEE header |
| Command Reference (I) | 440–443 | 4-122 to 4-125 | *IDN?, IMP, IN, INTLKVTH, INTLKVTH? | *IDN? (identification query), IMP (CMU measurement parameter: Cp-G, Cp-D, Cs-Rs, etc.), IN (initialize, similar to *RST but also clears program memory), INTLKVTH (interlock voltage threshold) | IN clears program memory unlike *RST |
| Command Reference (L) | 443–461 | 4-125 to 4-143 | LGI, LGV, LIM, LIM?, LMN, LOP?, *LRN?, LSI, LSM, LSSI, LSSV, LST?, LSTM, LSV, LSVM | LGI/LGV (linear search monitor), LIM (SMU current compliance limit), LMN (CMU monitor data output enable), *LRN? (learn query - returns all current settings by type parameter 0-56), LSI/LSV (linear search source), LSM (linear search abort), LST? (list program memory) | *LRN? is very powerful: 56 different query types to read back all instrument settings |
| Command Reference (M) | 461–478 | 4-143 to 4-160 | MCC, MCPNT, MCPNX, MCPT, MCPWS, MCPWNX, MDCV, MI, ML, MM, MSC, MSP, MT, MTDCV, MV | MCC (sampling measurement channel), MCPNT/MCPNX/MCPT/MCPWS/MCPWNX (multi-ch pulsed), MDCV (CMU sampling DC bias), MI (sampling current source), ML (sampling mode linear/log), MM (measurement mode selector), MSC (sampling abort), MSP (sampling post-measurement), MT (sampling timing), MV (sampling voltage source) | MM command is the central measurement mode selector (modes 1-28) |
| Command Reference (N–O) | 478–481 | 4-160 to 4-163 | NUB?, ODSW, ODSW?, *OPC?, OS, OSX | NUB? (number of data in output buffer), ODSW (pulse switch for SPGU), *OPC? (operation complete query), OS (obsolete output switch), OSX (output switch with external trigger) | *OPC? returns 1 when all pending operations complete |
| Command Reference (P) | 481–494 | 4-163 to 4-176 | PA, PAD, PAX, PCH, PCH?, PDCV, PI, PT, PTDCV, PV, PWDCV, PWI, PWV | PA (pause), PAD (parallel ADC), PAX (pause until trigger), PCH (parallel measurement channel), PDCV (CMU pulsed DC bias), PI (pulse current), PT (pulse timing), PTDCV (CMU pulse timing), PV (pulse voltage), PWDCV (CMU pulsed sweep DC bias), PWI (pulsed sweep current), PWV (pulsed sweep voltage) | PA waits for specified time or XE command |
| Command Reference (Q) | 494–500 | 4-176 to 4-182 | QSC, QSL, QSM, QSO, QSR, QST, QSV, QSZ | QSC (QSCV capacitance formula), QSL (QSCV leakage data), QSM (QSCV abort), QSO (QSCV offset cancel), QSR (QSCV range), QST (QSCV timing), QSV (QSCV voltage), QSZ (QSCV zero cancel) | All QS* commands are for quasi-static CV only |
| Command Reference (R) | 500–505 | 4-182 to 4-187 | RC, RCV, RI, RM, *RST, RU, RV, RZ | RC (CMU measurement range), RCV (recover failed channels after self-test), RI (SMU current measurement range), RM (measurement range auto/fixed), *RST (reset to initial), RU (run program memory sequentially), RV (SMU voltage measurement range), RZ (zero cancel for CMU) | *RST does NOT clear program memory (use IN for that) |
| Command Reference (S) | 505–522 | 4-187 to 4-204 | SAL, SAP, SAR, SCR, SER, SER?, SIM, SIM?, SOPC, SOPC?, SOVC, SOVC?, SPM, SPM?, SPP, SPPER, SPPER?, SPRM, SPRM?, SPST?, SPT, SPT?, SPUPD, SPV, SPV?, *SRE, *SRE?, SRP, SSL, SSP, SSR, ST | SA* (ASU control), SCR (start program recording), SER (series resistor for B1506A), SIM (SPGU operation mode), SOPC/SOVC (SPGU open/short compensation), SPM/SPP/SPPER/SPRM/SPST/SPT/SPUPD/SPV (SPGU pulse configuration), *SRE (service request enable), SRP (start SPGU output), SSL (SCUU indicator), SSP (SCUU path switch), SSR (series resistor), ST (obsolete) | SCR starts recording to program memory; END stops it |
| Command Reference (T) | 522–546 | 4-204 to 4-228 | STGP, STGP?, TACV, TC, TDCV, TDI, TDV, TGMO, TGP, TGPC, TGSI, TGSO, TGXO, TI, TIV, TM, TMACV, TMDCV, TSC, TSQ, TSR, *TST?, TTC, TTI, TTIV, TTV, TV | STGP (SPGU trigger output), TACV/TDCV/TDI/TDV (timer start output commands), TC (high-speed spot C measurement), TGMO/TGP/TGPC/TGSI/TGSO/TGXO (trigger configuration), TI/TIV/TV (high-speed spot I/V measurement), TM (trigger mode), TMACV/TMDCV (high-speed CMU measurement), TSC (timestamp enable), TSQ (timestamp query), TSR (timestamp reset), *TST? (self-test), TTC/TTI/TTIV/TTV (high-speed measurement with timestamp) | TI/TV are the fastest measurement commands (no MM/XE needed) |
| Command Reference (U–X) | 546–571 | 4-228 to 4-253 | UNT?, VAR, VAR?, WACV, WAT, WDCV, WFC, WI, WM, WMACV, WMDCV, WMFC, WNCC, WNU?, WNX, WS, WSI, WSV, WSX, WT, WTACV, WTDCV, WTFC, WV, WZ?, XE | UNT? (unit type query - identifies installed modules), VAR (program memory variable), WACV (CMU AC level sweep), WAT (obsolete wait), WDCV (CMU DC bias sweep), WFC (CMU frequency sweep), WI (sweep current), WM (sweep abort/post), WMA*/WMD*/WMF* (CMU sweep abort), WNX (multi-channel sweep source), WS (obsolete), WSI/WSV (synchronous sweep), WSX (sweep step with trigger), WT (sweep timing), WTA*/WTD*/WTF* (CMU sweep timing), WV (sweep voltage), WZ? (output voltage check), XE (execute measurement) | XE is the universal measurement trigger. UNT? is essential for slot/module identification. |

### Chapter 5: Error Messages (PDF 573–616, Printed 5-2 to 5-44; back cover PDF 617)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 5 Title | 573 | — | Chapter divider page | — | — |
| Chapter Overview | 574 | 5-2 | Introduction to error codes. Use ERR?/ERRX? to read errors. | ERR?, ERRX?, EMG? | ERR? only returns codes 0-999; ERRX? returns all |
| Operation Errors (codes 100–6413) | 575–601 | 5-3 to 5-29 | Complete listing of operation error codes and explanations. Ranges: 100–170 syntax/parameter, 201–290 setup conflicts, 301–335 hardware condition, 603–697 measurement setup, 940–999 DIO/expander, 1000–1022 pulse/PCH, 2000–2206 SPGU, 3000–3327 WGFMU/ALWG, 4304–6413 relay/HVSMU/expander/HCSMU/MCSMU (see Error Messages Quick Reference). Each error has code number, short message, and detailed explanation. | Error codes 100–6413 (gaps between ranges) | Examples: 100 (undefined GPIB command), 200 (channel output switch must be ON), 305 (excess current in HPSMU), 999 (use `ERRX?`) |
| Self-test/Calibration Errors | 602–616 | 5-30 to 5-44 | Self-test and calibration error codes: 700–935 (CPU/ADC/GNDU), 2400–2502, 3002–3508 (WGFMU/RSU), 4501–4701 (HVSMU), 5501–5701 (HCSMU), 6501–6606 (MCSMU), N760–N792 (SMU), N800–N933 (CMU/SCUU), where N is the slot number. | Error codes 700–6606 and N760–N933 | If self-test fails, contact Keysight service |

## Page To Content Map

| PDF Page(s) | Printed Page(s) | Section / Topic | What is explained there | Keywords / Commands / Concepts |
|---|---|---|---|---|
| 1 | — | Title | Cover page | B1500A/B1505A/B1506A/B1507A |
| 2 | — | Notices | Copyright, edition history (1-15), warranty, tech licenses | B1500-90010, Ed.15 May 2022 |
| 3–4 | — | Blank pages | — | — |
| 5 | — | Measurement Resources | Module compatibility table by mainframe model | HPSMU, MPSMU, MCSMU, MFCMU, HRSMU, SPGU, HVSMU, HVMCU, HCSMU, UHCU, UHVU |
| 6 | — | In This Manual | 5-chapter overview | — |
| 7–20 | — | Table of Contents | Detailed TOC with printed page references | — |
| 21 | — | Ch1 Title | "1 Programming Basics" divider | — |
| 22 | 1-2 | Ch1 Intro | Chapter overview, HP BASIC notation | OUTPUT, ENTER, ASSIGN |
| 23–26 | 1-3 to 1-6 | Before Starting / FlexGUI | GPIB setup procedure, FlexGUI window status indicators and debug logging | EasyEXPERT, GPIB address, FlexGUI, GPIB Capturing |
| 27–41 | 1-7 to 1-21 | Getting Started | All basic operations: reset, query, self-test, calibration, enable channels, select mode, force V/I, set integration time, set range, pause, start measurement, force 0V, disable channels, ASU/SCUU control, read errors, read data | `*RST`, `*TST?`, `*CAL?`, `CN`, `MM`, `DV`, `DI`, `AIT`, `RI`, `RV`, `PA`, `XE`, `DZ`, `CL`, `SAP`, `SSP`, `ERR?`, `TI`, `TV` |
| 42–44 | 1-22 to 1-24 | Command Input Format | Syntax rules: header, numeric data types, terminator, separator | CR/LF, EOI, semicolons |
| 45–55 | 1-25 to 1-35 | ASCII Data Output Format | Complete ASCII format spec: timestamps, data format by mode, data elements (status/channel/type codes), detailed code tables | `FMT`, `TSC`, `TSR`, status N/T/C/V/X/F/G/S/U/D, source W/E, EEE |
| 56–74 | 1-36 to 1-54 | Binary Data Output Format | 4-byte (FMT 3/4) and 8-byte (FMT 13/14) binary formats. Bit field definitions, range tables, data count calculations, resolution formulas | `FMT 3`, `FMT 4`, `FMT 13`, `FMT 14`, binary byte layout, range codes |
| 75 | 1-55 | GPIB Interface Capability | B1500 GPIB capability codes | SH1, AH1, T5, L4, SR1, RL1 |
| 76–78 | 1-56 to 1-58 | Status Byte | 8-bit status register description, masking, serial poll vs *STB? | `*SRE`, `*STB?`, serial poll, bits 3-6 |
| 78–88 | 1-58 to 1-68 | Programming Tips | Speed optimization, error checking, legacy migration | `*OPC?`, `CM 0`, `AZ 0`, `AB`, 4142B/4155/4156/E5260 compatibility |
| 89 | — | Ch2 Title | "2 Remote Mode Functions" divider | — |
| 90 | 2-2 | Ch2 Intro | Chapter overview and synchronous output note | — |
| 91–132 | 2-3 to 2-44 | Measurement Modes | All 19 measurement modes with timing diagrams and setup requirements (see detailed Ch2 content map above) | MM 1-28, all mode-specific commands |
| 132–134 | 2-44 to 2-46 | Synchronous Output | Synchronous sweep source tracking primary source | WSV, WSI, LSSV, LSSI, BSSV, BSSI |
| 134–137 | 2-46 to 2-49 | Abort & Parallel Measurement | Auto-abort conditions; parallel ADC for speed | WM, BSM, LSM, MSC, PAD |
| 137–140 | 2-49 to 2-52 | Program Memory | Internal program storage/execution (100 programs max) | SCR, END, DO, RU, PA, LST?, VAR |
| 140–152 | 2-52 to 2-64 | SPGU Module & Dual HCSMU | Pulse generator modes (PG/ALWG), timing, waveform setup | SIM, SPM, SPPER, SPT, SPV, SPRM, SRP, SPUPD, ALWG |
| 152–158 | 2-64 to 2-70 | Module Selector / Expanders | N1258A selector, SMU/PG selector, N1265A UHC, N1266A HVMC, N1268A UHV | ERMOD, ERSSP, ERPFUHCA, ERHVCA, ERUHVA |
| 159–161 | 2-71 to 2-73 | Digital I/O Port | 8-bit DIO, accessories, internal circuit | ERM, ERC, 16445A |
| 162–174 | 2-74 to 2-86 | Trigger Function | Complete trigger system: input/output configuration, timing diagrams, usage patterns | TGP, TGPC, PAX, WSX, TGXO, TGSO, TGMO, TGSI |
| 175–180 | 2-87 to 2-92 | Initial Settings | Complete reset state tables: mainframe (Table 2-9), SMU (Table 2-10), CMU (Table 2-11), SPGU (Table 2-12), combined (Table 2-13 on PDF 180) | `*RST` initial values, Table 2-13 |
| 181 | — | Ch3 Title | "3 Programming Examples" divider | — |
| 182–183 | 3-2 to 3-3 | Ch3 Overview | Lists all examples, command notation conventions, safety notes | — |
| 184–189 | 3-4 to 3-9 | VB.NET Programming Basics | Template project code, VISA COM setup | VISA COM, IResourceManager, IMessage |
| 189–198 | 3-9 to 3-18 | Spot & Pulsed Spot Examples | High-speed spot (TI/TV), spot (MM1), pulsed spot (MM3) | TI, TV, MM 1, MM 3, DV, PT, PV |
| 198–216 | 3-18 to 3-36 | Sweep Examples | Staircase sweep (MM2), pulsed sweep (MM4), sweep+pulsed bias (MM5) | MM 2, MM 4, MM 5, WV, WI, PWV, PT, WM |
| 216–236 | 3-36 to 3-56 | Search & Multi-Channel Examples | Quasi-pulsed (MM9), linear search (MM14), binary search (MM15), multi-ch sweep (MM16), multi-ch pulsed (MM27, MM28) | MM 9, MM 14, MM 15, MM 16, MM 27, MM 28, BDV, LSV, BSV, WNX, MCPNX |
| 236–246 | 3-56 to 3-66 | Sampling & QSCV Examples | Sampling (MM10), quasi-static CV (MM13) | MM 10, MM 13, MCC, MSC, MT, QSV, QST |
| 246–284 | 3-66 to 3-104 | CMU/Capacitance Examples | High-speed spot C, spot C (MM17), CV sweep (MM18), pulsed spot C (MM19), pulsed CV sweep (MM20), AC level sweep (MM23), C-f sweep (MM22), C-t sampling (MM26) | MM 17-23, MM 26, IMP, FC, ACV, DCV, WDCV, PTDCV |
| 285–291 | 3-105 to 3-111 | SPGU Examples | SPGU 2-level/3-level pulse output with voltage measurement | SIM, SPM, SPT, SPV, SPPER, SPRM, SPUPD, SRP |
| 292–310 | 3-112 to 3-130 | Program Memory & Trigger Examples | Program memory usage, trigger function examples with timing | SCR, END, DO, VAR, TGP, TGPC, PAX, TGXO |
| 310–318 | 3-130 to 3-138 | Timestamp, Binary Data & Legacy | Timestamp usage, binary data parsing, 4142B/4155/4156 migration | TSC, TSR, FMT 3, binary parsing |
| 319 | — | Ch4 Title | "4 Command Reference" divider | — |
| 320 | 4-2 | Ch4 Intro | Chapter overview, abbreviation definitions for all module types | ASU, CMU, DHC, HC, HP, HR, HV, MC, MP, SCUU, SPGU, UHC, UHV |
| 321–333 | 4-3 to 4-15 | Command Summary Table | All commands listed by category with 1-line description and syntax outline | ~200+ commands organized by function |
| 333–350 | 4-15 to 4-32 | Command Parameters | Reference tables for chnum, range/irange/vrange, compliance, output limits, impedance measurement parameters (IMP mode table) | Tables 4-1 through 4-16 |
| 350–375 | 4-32 to 4-57 | Commands AAD – BSVM | ADC selection, abort, channel map, CMU settings, averaging, binary/quasi-pulsed search commands | AAD, AB, ACH, ACT, ACV, ADJ, AIT, AV, AZ, BC, BDM, BDT, BDV, BGI, BGV, BSI, BSM, BSSI, BSSV, BST, BSV, BSVM |
| 375–398 | 4-57 to 4-80 | Commands CA – DZ | Calibration, channel enable/disable, CMU correction, force V/I, diagnostics, program memory execute, data sampling | CA, *CAL?, CL, CLCORR, CM, CMM, CN, CNX, CORR?, CORRDT, CORRL, CORRSER?, CORRST, DCORR, DCV, DI, DIAG?, DO, DSMPL*, DV, DZ |
| 398–435 | 4-80 to 4-117 | Commands EMG? – ERUHVA? | Error message query, digital I/O, all expander/selector/fixture control commands | EMG?, END, ERC, ERCMA*, ERHP*, ERHV*, ERM, ERMOD, ERPF*, ERR?, ERRX?, ERS?, ERSSP, ERUHVA |
| 435–443 | 4-117 to 4-125 | Commands FC – INTLKVTH? | CMU frequency, filter, data format, high-speed spot, HVSMU operation, identification, impedance param, initialize, interlock | FC, FL, FMT, HSS, HVSMUOP, *IDN?, IMP, IN, INTLKVTH |
| 443–478 | 4-125 to 4-160 | Commands LGI – MV | Linear search, compliance limit, CMU monitor, learn query, program memory list, multi-channel pulsed, sampling, measurement mode, sampling settings | LGI, LGV, LIM, LMN, LOP?, *LRN?, LSI, LSM, LSSI, LSSV, LST?, LSTM, LSV, LSVM, MCC, MCPNT, MCPNX, MCPT, MCPWS, MCPWNX, MDCV, MI, ML, MM, MSC, MSP, MT, MTDCV, MV |
| 478–500 | 4-160 to 4-182 | Commands NUB? – QSZ | Buffer count, pulse switch, operation complete, pause, parallel ADC, CMU pulsed, pulse source setup, pulsed sweep, quasi-static CV | NUB?, ODSW, *OPC?, OS, OSX, PA, PAD, PAX, PCH, PDCV, PI, PT, PTDCV, PV, PWDCV, PWI, PWV, QSC, QSL, QSM, QSO, QSR, QST, QSV, QSZ |
| 500–522 | 4-182 to 4-204 | Commands RC – SSR | CMU range, recover channels, SMU range, reset, run program, zero cancel, ASU control, program memory record, series resistor, SPGU all commands, service request, SCUU control | RC, RCV, RI, RM, *RST, RU, RV, RZ, SAL, SAP, SAR, SCR, SER, SIM, SOPC, SOVC, SPM, SPP, SPPER, SPRM, SPST?, SPT, SPUPD, SPV, *SRE, SRP, SSL, SSP, SSR |
| 522–546 | 4-204 to 4-228 | Commands ST – TV | SPGU trigger, timer/timestamp commands, high-speed spot measurements (TI/TV/TIV/TC and timestamped versions), trigger mode/port configuration, self-test | ST, STGP, TACV, TC, TDCV, TDI, TDV, TGMO, TGP, TGPC, TGSI, TGSO, TGXO, TI, TIV, TM, TMACV, TMDCV, TSC, TSQ, TSR, *TST?, TTC, TTI, TTIV, TTV, TV |
| 546–572 | 4-228 to 4-254 | Commands UNT? – XE | Unit identification, variables, CMU sweep sources (WACV/WDCV/WFC), sweep current/voltage, sweep abort/timing, multi-channel sweep, synchronous sweep, output voltage check, execute measurement | UNT?, VAR, WACV, WAT, WDCV, WFC, WI, WM, WMACV, WMDCV, WMFC, WNCC, WNU?, WNX, WS, WSI, WSV, WSX, WT, WTACV, WTDCV, WTFC, WV, WZ?, XE |
| 573 | — | Ch5 Title | "5 Error Messages" divider | — |
| 574 | 5-2 | Ch5 Intro | Error system overview: use ERR?/ERRX? to read, perform self-test if persistent | ERR?, ERRX? |
| 575–601 | 5-3 to 5-29 | Operation Errors | All operation errors, codes 100–6413: syntax/parameter, setup conflicts, hardware condition, measurement setup, DIO/expander, pulse/PCH, SPGU (2000s), WGFMU/ALWG (3000s), relay/HVSMU/expander/HCSMU/MCSMU (4304–6413) | Codes 100–6413 |
| 602–616 | 5-30 to 5-44 | Self-test/Calibration Errors | Hardware diagnostic errors: CPU/ADC/GNDU (700–935), 2400–2502, WGFMU/RSU (3002–3508), HVSMU (4501–4701), HCSMU (5501–5701), MCSMU (6501–6606), SMU (N760–N792), CMU/SCUU (N800–N933) | Codes 700–6606, N760–N933 |
| 617 | — | Back cover | Edition and part number | B1500-90010 |

## High-Value Lookup Shortcuts

### Connection / GPIB / Remote Mode Setup

| What you need | Where to look | PDF Page(s) |
|---|---|---|
| Initial GPIB setup procedure | Ch1 "Before Starting" | 23–26 (1-3 to 1-6) |
| GPIB address configuration | Ch1 "Before Starting" | 23 (1-3) |
| FlexGUI status window | Ch1 "Before Starting" | 24–26 (1-4 to 1-6) |
| GPIB interface capability table | Ch1 "GPIB Interface Capability" | 75 (1-55) |
| VB.NET VISA COM template | Ch3 "Programming Basics for VB.NET" | 184–189 (3-4 to 3-9) |

### Query Response Buffer vs Measurement Output Buffer

| What you need | Where to look | PDF Page(s) |
|---|---|---|
| Query buffer (stores 1 response only, always ASCII) | Ch1 "To Read Query Response" | 28 (1-8) |
| Data output buffer (stores measurement data) | Ch1 "Data Output Format" | 45 (1-25) |
| Clear output buffer | BC command | 364 (4-46) |
| Check number of data in buffer | NUB? command | 478 (4-160) |
| FMT command (selects output format) | Ch4 "FMT" | 436–437 (4-118 to 4-119) |
| ASCII data format details | Ch1 "ASCII Data Output Format" | 45–55 (1-25 to 1-35) |
| Binary data format details | Ch1 "Binary Data Output Format" | 56–74 (1-36 to 1-54) |

### System and Initialization Commands

| Command | What it does | PDF Page |
|---|---|---|
| `*IDN?` | Returns instrument identification string | 440 (4-122) |
| `*RST` | Resets to initial settings (does NOT clear program memory) | 502 (4-184) |
| `IN` | Initialize (like *RST but ALSO clears program memory) | 441 (4-123) |
| `*TST?` | Performs self-test, returns result (0=pass, non-zero=fail slot info) | 540 (4-222) |
| `*CAL?` | Performs self-calibration, returns result (0=pass) | 376 (4-58) |
| `CA` | Performs self-calibration without returning result | 375 (4-57) |
| `UNT?` | Returns installed module types by slot (essential for discovery) | 545 (4-227) |
| `ERR?` | Returns oldest error code (0-999 only) | 430 (4-112) |
| `ERRX?` | Returns oldest error code + message (all codes including self-test) | 431 (4-113) |
| `EMG?` | Returns error message text for a given code | 398 (4-80) |
| `*LRN?` | Returns current instrument settings (type 0-56) | 447–453 (4-129 to 4-135) |
| `*OPC?` | Returns 1 when all pending operations complete | 479 (4-161) |
| `AB` | Aborts current operation immediately | 351 (4-33) |
| `DIAG?` | Performs diagnostics, returns result | 392 (4-74) |

### Channel Control

| Command | What it does | PDF Page |
|---|---|---|
| `CN` / `CNX` | Enable (connect) SMU/SPGU channel output switches | 380–381 (4-62 to 4-63) |
| `CL` | Disable (disconnect) channel output switches | 378 (4-60) |
| `DZ` | Store channel settings and force 0V | 397 (4-79) |
| `WZ?` | Check if any output exceeds ±2V threshold | 570 (4-252) |
| `SAP` | ASU path selection (SMU side / ASU side) | 505 (4-187) |
| `SAR` | ASU 1pA auto-range enable/disable | 506 (4-188) |
| `SAL` | ASU indicator LED enable/disable | 505 (4-187) |
| `SSP` | SCUU path switch (open/SMU/CMU) | 519–520 (4-201 to 4-202) |
| `SSL` | SCUU indicator enable/disable | 519 (4-201) |
| `ACH` | Channel number mapping/remapping | 353 (4-35) |
| `CMM` | SMU measurement operation mode (compliance/current/voltage/force side) | 380 (4-62) |

### Interlock and Safety

| Command | What it does | PDF Page |
|---|---|---|
| `INTLKVTH` | Set interlock voltage threshold (voltage above which interlock must be closed) | 442 (4-124) |
| `INTLKVTH?` | Query current interlock voltage threshold | 443 (4-125) |
| `WZ?` | Check if any channel output exceeds ±2V (safety check before disconnect) | 570 (4-252) |
| `DZ` | Store settings and force all specified channels to 0V | 397 (4-79) |
| `RZ` | Recover stored settings (undo DZ) | 504 (4-186) |
| Interlock description | Conditions requiring closed interlock circuit | 23–24 (1-3 to 1-4) |

### Data Formats

| Command / Topic | What it does | PDF Page |
|---|---|---|
| `FMT` command | `FMT format[,mode]`: output format (Table 4-24) and source data mode (Table 4-25); terminator fixed by format | 436–437 (4-118 to 4-119) |
| FMT 1 | ASCII 12 digits with header, `<CR/LF^EOI>` (default) | 437 (4-119) |
| FMT 2 | ASCII 12 digits without header, `<CR/LF^EOI>` | 437 (4-119) |
| FMT 3 | 4-byte binary, `<CR/LF^EOI>` | 437 (4-119) |
| FMT 4 | 4-byte binary, `<^EOI>` | 437 (4-119) |
| FMT 5 | ASCII 12 digits with header, comma terminator (not binary) | 437 (4-119) |
| FMT 11 / 12 / 15 | ASCII 13 digits: 11 with header, 12 without, 15 with header and comma terminator | 437 (4-119) |
| FMT 13 / 14 | 8-byte binary, `<CR/LF^EOI>` / `<^EOI>` | 437 (4-119); 57 (1-37) |
| FMT 21 / 22 / 25 | ASCII 13 digits, 4155/4156 compatible: 21 with `EEEFG` header, 22 without, 25 with header and comma terminator | 437 (4-119) |
| FMT `mode` (source data) | Table 4-25 | 438 (4-120) |
| ASCII element layouts | Table 1-6: `ABC` (FMT 1/5/11/15), `EEEFG` (FMT 21/25), none (FMT 2/12/22) | 50 (1-30) |
| Source data status (W/E) and summed EEE status (SMU/CMU) | Tables 1-7, 1-8, 1-9 | 52 (1-32) |
| Measurement status codes `A` | Table 1-10: N, T, C, V, X, F, G, S, U, D (no `L`; `D` = CMU IV amplifier saturation) | 53 (1-33) |
| ASCII channel codes table | A-J (slot 1-10), a-j (subchannel 2), V (GNDU), Z (extraneous data: `TSQ` response or invalid data) | 54 (1-34) |
| ASCII data type codes | Table 1-12: `C`: V, I, F; `C` or `G`: Z, Y, C, L, R (phase rad), P (phase deg), D, Q, X (sampling index), T; `G`: V, I, v, i, f, z (invalid) | 55 (1-35) |
| Binary 4-byte element structure (FMT 3/4) | Figure 1-2: type, parameter, range, data count, 3-bit status (Table 1-13), channel (Table 1-14) | 61–67 (1-41 to 1-47) |
| Binary 8-byte element structure (FMT 13/14) | Figure 1-3: type bit, 7-bit parameter, range byte, 4-byte data count, status byte (Table 1-15), A/D converter, channel; not IEEE 754 | 68–74 (1-48 to 1-54) |
| Binary range code tables | Range values for the 4-byte (PDF 62, 1-42) and 8-byte (PDF 70–71) formats | 70–71 (1-50 to 1-51) |

### Measurement Modes (MM Command Map)

| MM Mode | Measurement Type | Required Commands Before XE | PDF Page (mode detail) |
|---|---|---|---|
| (none) | High-speed spot | TI, TV, TIV, TC, TTC, TTI, TTV, TTIV (no MM/XE needed) | 535–545 (4-217 to 4-227) |
| MM 1 | Spot | CN, MM, DV or DI | 92 (2-4) |
| MM 2 | Staircase sweep | CN, MM, WV or WI | 96–98 (2-8 to 2-10) |
| MM 3 | Pulsed spot | CN, MM, PT, PV or PI | 93 (2-5) |
| MM 4 | Pulsed sweep | CN, MM, PT, PWV or PWI | 100–102 (2-12 to 2-14) |
| MM 5 | Staircase sweep + pulsed bias | CN, MM, PT, WV or WI, PV or PI | 98–100 (2-10 to 2-12) |
| MM 9 | Quasi-pulsed spot | CN, MM, BDV | 106–108 (2-18 to 2-20) |
| MM 10 | Sampling | CN, MM, MCC, ML, MT, MSC, MI or MV, MSP | 112–115 (2-24 to 2-27) |
| MM 13 | Quasi-static CV | CN, MM, QST, QSV | 115–118 (2-27 to 2-30) |
| MM 14 | Linear search | CN, MM, LSV or LSI, LGV or LGI | 110–112 (2-22 to 2-24) |
| MM 15 | Binary search | CN, MM, BSV or BSI, BGV or BGI | 108–110 (2-20 to 2-22) |
| MM 16 | Multi channel sweep | CN, MM, WI or WV, WNX | 102–104 (2-14 to 2-16) |
| MM 17 | Spot C | CN, MM, IMP, FC, ACV, DCV | 118–119 (2-30 to 2-31) |
| MM 18 | CV (DC bias) sweep | CN, MM, IMP, FC, ACV, WDCV | 121–124 (2-33 to 2-36) |
| MM 19 | Pulsed spot C | CN, MM, IMP, FC, ACV, PTDCV, PDCV | 119–121 (2-31 to 2-33) |
| MM 20 | Pulsed sweep CV | CN, MM, IMP, FC, ACV, PTDCV, PWDCV | 124–126 (2-36 to 2-38) |
| MM 22 | C-f sweep | CN, MM, IMP, DCV, ACV, WFC | 126–128 (2-38 to 2-40) |
| MM 23 | CV (AC level) sweep | CN, MM, IMP, FC, DCV, WACV | 128–129 (2-40 to 2-41) |
| MM 26 | C-t sampling | CN, MM, IMP, FC, ACV, MDCV, MTDCV | 130–132 (2-42 to 2-44) |
| MM 27 | Multi channel pulsed spot | CN, MM, MCPT, MCPNT, MCPNX | 94–95 (2-6 to 2-7) |
| MM 28 | Multi channel pulsed sweep | CN, MM, MCPT, MCPNT, MCPWS, MCPWNX | 104–106 (2-16 to 2-18) |

### SMU IV Related Source/Measurement Commands

| Command | Function | PDF Page |
|---|---|---|
| `DV` | Force DC voltage (spot) | 396 (4-78) |
| `DI` | Force DC current (spot) | 391 (4-73) |
| `WV` | Set sweep voltage source | 568–569 (4-250 to 4-251) |
| `WI` | Set sweep current source | 551–552 (4-233 to 4-234) |
| `WSV` | Set synchronous sweep voltage | 561–563 (4-243 to 4-245) |
| `WSI` | Set synchronous sweep current | 560–561 (4-242 to 4-243) |
| `PV` | Set pulse voltage | 488 (4-170) |
| `PI` | Set pulse current | 485 (4-167) |
| `PWV` | Set pulsed sweep voltage | 492–493 (4-174 to 4-175) |
| `PWI` | Set pulsed sweep current | 490–491 (4-172 to 4-173) |
| `PT` | Set pulse timing (hold, width, period) | 486 (4-168) |
| `MV` | Set sampling voltage source | 477 (4-159) |
| `MI` | Set sampling current source | 468 (4-150) |
| `MT` | Set sampling timing (interval, points) | 474–475 (4-156 to 4-157) |
| `TI` | High-speed spot current measurement | 535 (4-217) |
| `TV` | High-speed spot voltage measurement | 545 (4-227) |
| `TIV` | High-speed spot I+V measurement | 535 (4-217) |
| `RI` | Set current measurement range | 501 (4-183) |
| `RV` | Set voltage measurement range | 503 (4-185) |
| `LIM` / `LIM?` | Current compliance limit query | 444–445 (4-126 to 4-127) |

### CMU/MFCMU Related Commands

| Command | Function | PDF Page |
|---|---|---|
| `IMP` | Set impedance measurement parameter (Cp-G, Cp-D, Cs-Rs, etc.) | 441 (4-123) |
| `FC` | Set CMU output signal frequency | 435 (4-117) |
| `ACV` | Set CMU AC signal level | 354 (4-36) |
| `DCV` | Set CMU DC bias | 390 (4-72) |
| `RC` | Set CMU measurement range | 500 (4-182) |
| `ACT` | Set CMU ADC integration time | 354 (4-36) |
| `ADJ` / `ADJ?` | Phase compensation mode (auto/manual/load-adaptive) | 355 (4-37) |
| `LMN` | Enable/disable oscillator level + DC bias monitor data output | 445 (4-127) |
| `WDCV` | Set CMU DC bias sweep source | 549 (4-231) |
| `WACV` | Set CMU AC level sweep source | 547 (4-229) |
| `WFC` | Set CMU frequency sweep source | 550 (4-232) |
| `MDCV` | Set CMU sampling DC bias | 467 (4-149) |
| `MTDCV` | Set CMU sampling timing | 476 (4-158) |
| `PTDCV` | Set CMU pulse timing | 487 (4-169) |
| `PDCV` | Set CMU pulsed DC bias | 484 (4-166) |
| `PWDCV` | Set CMU pulsed sweep DC bias | 489 (4-171) |
| `WTDCV` | Set CMU sweep timing (hold/delay) | 566 (4-248) |
| `WMDCV` | Set CMU sweep abort function | 554–555 (4-236 to 4-237) |
| `CORRST` | Enable/disable open/short/load correction | 387 (4-69) |
| `CORR?` | Perform correction data measurement (open/short/load) | 382 (4-64) |
| `CORRL` | Add frequency for correction measurement | 384 (4-66) |
| `CORRL?` | Query correction frequency list | 385 (4-67) |
| `CLCORR` | Clear correction frequency list | 379 (4-61) |
| `DCORR` | Set calibration/reference value for load standard | 389 (4-71) |
| `DCORR?` | Query load standard calibration values | 389 (4-71) |
| `CORRDT` | Set/read correction data directly | 383 (4-65) |
| `CORRSER?` | Perform series correction measurement (returns series R) | 385 (4-67) |
| `RZ` | Zero cancel (offset cancel) for CMU | 504 (4-186) |

### Timing, Timestamp, Wait, Status Byte

| Command | Function | PDF Page |
|---|---|---|
| `WT` | Set sweep hold/delay/step-delay/trigger-delay times | 564–565 (4-246 to 4-247) |
| `PT` | Set pulse hold/width/period/trigger-delay | 486 (4-168) |
| `PA` | Pause execution for specified time | 481 (4-163) |
| `PAX` | Pause until external trigger received | 482 (4-164) |
| `WAT` | Obsolete wait command | 547 (4-229) |
| `TSC` | Enable/disable timestamp function | 538 (4-220) |
| `TSR` | Reset timestamp counter to 0 | 539 (4-221) |
| `TSQ` | Query current timestamp value | 539 (4-221) |
| `TDI` / `TDV` | Timer-start with DC output | 526–528 (4-208 to 4-210) |
| `TACV` / `TDCV` | Timer-start with CMU output | 523, 524 (4-206, 4-207) |
| `*OPC?` | Wait for operation complete (returns 1) | 479 (4-161) |
| `*STB?` | Read status byte | 523 (4-205) |
| `*SRE` / `*SRE?` | Set/read service request enable mask | 517–518 (4-199 to 4-200) |
| Status byte description | Bit meanings (3=buffer, 4=ready, 5=error, 6=RQS) | 76–78 (1-56 to 1-58) |

### Data Buffers and Status

| Command / Topic | What it does | PDF Page |
|---|---|---|
| `NUB?` | Returns number of data items in output buffer | 478 (4-160) |
| `BC` | Clears output data buffer | 364 (4-46) |
| `*OPC?` | Returns 1 when all operations complete (use to synchronize) | 479 (4-161) |
| `*STB?` | Read status byte register | 523 (4-205) |
| `*SRE` | Set service request enable mask (controls which bits trigger SRQ) | 517 (4-199) |
| `*SRE?` | Query service request enable mask | 518 (4-200) |
| Status byte bit 3 | Output buffer not empty (data ready to read) | 76 (1-56) |
| Status byte bit 4 | Set ready (operation complete, goes LOW on command receipt) | 76–77 (1-56 to 1-57) |
| Status byte bit 5 | Error occurred (read with ERR?/ERRX?) | 77 (1-57) |
| Status byte bit 6 | RQS/SRQ (service request generated) | 77 (1-57) |
| Query buffer behavior | Stores ONE response only; must read before next query | 28 (1-8) |

### Error Messages Quick Reference

Code ranges and pages verified against the PDF text (Revision 3). Operation errors are PDF 575–601 (printed 5-3 to 5-29); self-test/calibration errors are PDF 602–616 (printed 5-30 to 5-44). Code numbers overlap between the two sections. See also `structured/b1500a-error-codes.yaml`.

| Error Range | Category | PDF Page(s) |
|---|---|---|
| 0 | No error. `ERR?`/`EMG?` cover codes 0–999; `ERRX?` covers all codes | 574 (5-2) |
| 100–170 | Operation: command syntax, parameter, channel number, and setup errors | 575–577 (5-3 to 5-5) |
| 201–290 | Operation: compliance, sweep, pulse, search, QSCV, and CV setup conflicts | 577–582 (5-5 to 5-10) |
| 301–335 | Operation: line power, excess current/voltage, interlock, cable, turn-on detection | 583–584 (5-11 to 5-12) |
| 603–697 | Operation: measurement setup, trigger, abort, CMU correction, selector/expander state | 584–587 (5-12 to 5-15) |
| 940–999 | Operation: DIO/expander mismatch; 999 = error not supported by `ERR?` (use `ERRX?`) | 587–588 (5-15 to 5-16) |
| 1000–1022 | Operation: pulse limits, application setup, parallel measurement (`PCH`), module settings | 588–590 (5-16 to 5-18) |
| 2000–2206 | Operation: SPGU (operation mode, timing, ALWG data, load impedance) | 590–593 (5-18 to 5-21) |
| 3000–3327 | Operation: WGFMU/RSU and ALWG | 593–596 (5-21 to 5-24) |
| 4304–5413 | Operation: external relay, HVSMU, expanders/fixtures (N1265A, N1266A, N1268A, B1506A), HCSMU emergencies | 596–601 (5-24 to 5-29) |
| 6401–6413 | Operation: MCSMU emergencies | 601 (5-29) |
| 700–935 | Self-test/calibration: CPU, ADC, GNDU | 602–603 (5-30 to 5-31) |
| 2400–2502 | Self-test/calibration: digital hardware, FPGA, EEPROM, power amplifier, frame configuration | 603–604 (5-31 to 5-32) |
| 3002–3508 | Self-test/calibration: WGFMU and RSU | 604–607 (5-32 to 5-35) |
| 4501–4701 | Self-test/calibration: HVSMU | 607–609 (5-35 to 5-37) |
| 5501–5701 | Self-test/calibration: HCSMU | 609–610 (5-37 to 5-38) |
| 6501–6606 | Self-test/calibration: MCSMU | 610–611 (5-38 to 5-39) |
| N760–N792 | Self-test/calibration: SMU (N = slot number) | 611–612 (5-39 to 5-40) |
| N800–N933 | Self-test/calibration: CMU and SCUU (N = slot number) | 612–616 (5-40 to 5-44) |

## Gaps / Ambiguities

1. **PDF text extraction quality:** The PDF is cleanly extracted with good OCR quality. No major garbled text detected. Tables retain structure reasonably well in text form but column alignment is lost—you must read the actual PDF for precise table data (especially range tables in Ch4 Command Parameters section).

2. **Printed page numbering gaps:** Pages like "1-1", "2-1", "3-1", etc. are title pages without printed numbers. No content pages are missing from the sequence.

3. **MM mode numbering gaps:** There are no MM modes 6, 7, 8, 11, 12, 21, 24, or 25. These numbers are simply unused/reserved.

4. **Chapter 3 tail pages (PDF 317–318):** The very end of Chapter 3 covers 4155/4156 legacy compatibility but the content was partially truncated in my inspection. These 2 pages likely finish the compatibility tables.

5. **Command Reference individual pages:** Not every individual command page was inspected in full detail. The structure is consistent throughout (Syntax → Parameters → Query Response / Output Data → Example Statements → See Also). For precise parameter value ranges, always read the specific command page.

6. **DSMPL commands (PDF 393–396, printed 4-75 to 4-78):** DSMPLARM (PDF 393), DSMPLFLUSH (PDF 394), DSMPLSETUP (PDF 395) are signal monitor commands for MM27/MM28 measurements using HVSMU/HCSMU/MCSMU. They monitor channel V/I during multi-channel pulsed measurements. Not "newer" — they are documented in the TOC at 4-75 to 4-77.

7. **Error code range 400–599:** These codes are not listed in the Operation Error section and don't appear in the Self-test section either. They may be reserved or firmware-version-specific.

8. **B1505A/B1506A/B1507A specific commands:** Many commands in the ER* family (ERCMA*, ERPF*, ERHP*, ERHV*) are specific to B1505A/B1506A/B1507A with their fixture/selector accessories. These may not apply to standalone B1500A usage.

9. **FMT format details:** Table 4-24 (printed 4-119, PDF 437) defines formats 1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 21, 22, and 25; Table 4-25 (PDF 438) defines the source data `mode`. Element layouts and status codes are in Chapter 1 (PDF 50–55 ASCII, PDF 56–74 binary).

10. **Remaining uncertainty on some Ch3 PDF page boundaries:** The Ch3 section entries have been corrected using the verified formula `3-N → N + 179`. However, some multi-page section boundaries (especially for longer examples like Staircase Sweep at 3-18 to 3-28) were computed from the TOC rather than individually verified by reading each page. A ±1 page error is possible at section boundaries where content from one section bleeds into the next page.

11. **Recommended next extraction tasks:**
    - Extract the complete Command Summary table (PDF 321–333) into a structured command-to-category lookup.
    - Extract the complete Command Parameters tables (PDF 333–350) for range/compliance reference.
    - Extract error message table (PDF 575–601) into a searchable error code database.
    - Extract the initial settings tables (PDF 175–180, especially Table 2-13 on PDF 180) for reset-state reference.
    - Individually verify each high-value command page number by reading the PDF page content (especially for commands in the D–F range where errors were found).

## Revision Notes

### Revision 3 — 2026-11-17

**Context:** Re-verified against `B1500A Programming Guide.pdf` (Edition 15, 617 pages) with per-page text extraction (`pdftotext -f N -l N`) and the printed footer on every page.

**Corrections applied:**

1. **Page numbering (all sections above):** PDF numbers are now physical 1-based PDF pages. Formulas changed from `N + 19 / 87 / 179 / 317 / 571` to `N + 20 / 88 / 180 / 318 / 572`. The old offset was not uniform: about 85% of page pairs were one page low, but Chapter 2 rows from Sampling (2-24) to C-t Sampling (2-44) were already correct, and a few rows were off by two (`SSL`). So every PDF number was recomputed from its printed page (printed pages were checked against the manual's Contents, PDF 7–20), and PDF-only rows were checked against page text. Front matter is PDF 1–20; chapter title pages are PDF 21, 89, 181, 319, 573; Chapter 5 ends at PDF 616 (printed 5-44, not 5-46); PDF 617 is the back cover.
2. **Printed-page fixes:** `*OPC?` is 4-161 (not 4-162); `PWV` spans 4-174 to 4-175; SPGU Module ends at 2-64.
3. **FMT:** FMT 5 is ASCII 12 digits with header and a comma terminator (Table 4-24, PDF 437). 8-byte binary is FMT 13/14 (PDF 57). The 8-byte format is an integer data count with range/status/channel fields (Figure 1-3, PDF 68), not IEEE 754.
4. **Data status codes:** Table 1-10 (PDF 53) lists N, T, C, V, X, F, G, S, U, D. `D` is CMU IV amplifier saturation (not search), `U` is CMU NULL loop unbalance, `W`/`E` are source data step status (Table 1-7), `F` is SMU force saturation, and there is no `L`. FMT 21/25 use summed `EEE` codes (Tables 1-8/1-9, PDF 52).
5. **Error quick reference:** Rebuilt from the PDF. The old code ranges (for example 700–799 "execution", 3001–3701 "HPSMU/MPSMU self-test", 9001–9999 "SPGU") did not match the manual.

**Not changed (observed):** The Status Byte rows (Content To Page Map; Data Buffers and Status table) still describe bit 0 as unused and bit 3 as "output buffer not empty". `structured/b1500a-command-parameters.md` (verified 2026-06-22) gives bit 0 = data ready and bit 3 = interlock open. Re-verify against PDF 76–78 before relying on these rows.

### Revision 2 — 2026-06-22

> Page numbers in this Revision 2 note use the old numbering (one page lower than the physical PDF page in most places). They are kept as written for history; Revision 3 governs.

**Context:** Second-pass audit against source PDF. Multi-pass verification using PDF page markers (`-- X of 617 --`) to validate formula table and page mappings.

**Major corrections applied:**

1. **Chapter boundary error (CRITICAL):** Chapter 2 extends to PDF 179 (printed 2-92), not PDF 178 (2-91). PDF 179 contains Table 2-13 "Initial Settings of Mainframe, SMU, and CMU" — the most comprehensive single reset-state reference. Chapter 3 title is at PDF 180, not 179.

2. **Formula table fixed:** Added "Last Content PDF Page" column. Corrected Ch3 Title (180, not 179) and Content Start (181, not 180). Added correction note explaining the off-by-one source.

3. **All Chapter 3 PDF page numbers corrected:** Every Content-To-Page entry for Chapter 3 was systematically wrong (off by 1–2 pages). Root cause: original index likely used incorrect offset (N+177 or N+178) instead of the correct N+179. Verified by reading PDF pages 180–188 directly: PDF 180 = Ch3 title, PDF 181 = printed 3-2, PDF 183 = printed 3-4 (VB.NET section start).

4. **High-Value Lookup page numbers corrected:** Multiple entries had wrong PDF page numbers:
   - `DZ`: was 400, corrected to 396 (verified: PDF 396 = printed 4-79, DZ command)
   - `DV`: was 396, corrected to 395 (verified: PDF 395 = printed 4-78)
   - `DI`: was 393, corrected to 390 (formula: 73+317=390)
   - `DIAG?`: was 393, corrected to 391 (formula: 74+317=391)
   - `SAP`: was 505, corrected to 504 (formula: 187+317=504)
   - `SAR`: was 506, corrected to 505 (formula: 188+317=505)
   - `ACH`: was 351, corrected to 352 (formula: 35+317=352)
   - `CMM`: was 380, corrected to 379 (formula: 62+317=379)

5. **Page-To-Content Map corrected:** Chapter 2/3 boundary, Ch3 entries realigned to correct pages.

6. **DSMPL commands clarified:** Corrected the Gaps entry — these are documented signal monitor commands (TOC 4-75 to 4-77), not undocumented additions.

7. **Table 2-13 discovery:** Added explicit reference to Table 2-13 (PDF 179), which is a combined initial-settings table covering mainframe, SMU, CMU, trigger, DIO, program memory, and data format settings in one reference — previously not called out separately.

**Verification method:**
- Directly read PDF text at page markers to confirm printed page numbers match formula predictions
- Verified: PDF 181 = "3-2", PDF 183 = "3-4", PDF 355 = "4-38", PDF 395 = "4-78", PDF 396 = "4-79", PDF 439 = "4-122"
- Cross-checked TOC printed page numbers against formula for ~20 commands

**What was NOT re-verified (remaining uncertainty):**
- Individual command pages in ranges E (ERCMA*, ERHP*, ERPF*) — page numbers carried forward from original index with formula-based correction only
- Some Ch3 section-end boundaries (±1 page possible where TOC doesn't list sub-sections)
- Chapter 5 error code page ranges (carried forward unchanged)
- Exact page extent of multi-page commands (e.g., *LRN? spans 4-129 to 4-135 per TOC but each sub-page not individually verified)

**What still needs future extraction:**
- Command Summary table (PDF 320–332) as structured data
- Command Parameters tables (PDF 332–349) for range/compliance values
- Error code lookup table (PDF 574–600)
- Table 2-13 complete extraction (PDF 179)
- Individual verification of all remaining lookup shortcut page numbers
