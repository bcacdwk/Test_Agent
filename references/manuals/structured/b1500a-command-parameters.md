# B1500A Command Parameters

Source: `B1500A Programming Guide.pdf`, mainly Chapter 1 Data Output Format, Chapter 2 Measurement Modes, and Chapter 4 Command Parameters.

Page convention: "PDF N" is the physical 1-based PDF page (as shown by a PDF viewer); "printed X-N" is the manual's chapter-page number. PDF = N + 20 / 88 / 180 / 318 / 572 for chapters 1 / 2 / 3 / 4 / 5. See `../b1500a-programming-guide-index.md`.

## Coverage

| Parameter Area | Coverage | Source Pages |
|---|---:|---|
| Channel numbering | Complete practical table | PDF 334 / printed 4-16 |
| MM measurement mode map | Complete mode list from guide/index | PDF 91-132; `XE` required-command table PDF 571-572 |
| Required commands before `XE` | Complete transcription | PDF 571-572 / printed 4-253 to 4-254 |
| FMT output formats | Complete Table 4-24 transcription | PDF 437 / printed 4-119; Chapter 1 PDF 45-75 |
| ASCII status/channel/type codes | Complete Tables 1-6 to 1-12 | PDF 50-55 / printed 1-30 to 1-35 |
| Voltage/current range concepts | Structured summary, not every numeric cell | PDF 335-346 / printed 4-17 to 4-28 |
| MFCMU measurement parameters | Complete Table 4-16 | PDF 347 / printed 4-29 |
| Timing/timestamp parameters | Practical extraction | PDF 76-78, 538-539, 564-568 |

## Channel Numbering

Source: Table 4-1, PDF 334 / printed 4-16.

| `chnum` | Meaning |
|---:|---|
| `101` or `1` | Subchannel 1 of module in slot 1 |
| `201` or `2` | Subchannel 1 of module in slot 2 |
| `301` or `3` | Subchannel 1 of module in slot 3 |
| `401` or `4` | Subchannel 1 of module in slot 4 |
| `501` or `5` | Subchannel 1 of module in slot 5 |
| `601` or `6` | Subchannel 1 of module in slot 6 |
| `701` or `7` | Subchannel 1 of module in slot 7 |
| `801` or `8` | Subchannel 1 of module in slot 8 |
| `901` or `9` | Subchannel 1 of module in slot 9 |
| `1001` or `10` | Subchannel 1 of module in slot 10 |
| `102` | Subchannel 2 of module in slot 1 |
| `202` | Subchannel 2 of module in slot 2 |
| `302` | Subchannel 2 of module in slot 3 |
| `402` | Subchannel 2 of module in slot 4 |
| `502` | Subchannel 2 of module in slot 5 |
| `602` | Subchannel 2 of module in slot 6 |
| `702` | Subchannel 2 of module in slot 7 |
| `802` | Subchannel 2 of module in slot 8 |
| `902` | Subchannel 2 of module in slot 9 |
| `1002` | Subchannel 2 of module in slot 10 |

Notes:

- HPSMU, HCSMU, and HVSMU occupy two slots. Use the smaller slot number as the channel number.
- For UHCU, HVMCU, and UHVU, use the channel number of the MCSMU/HCSMU connected to the V Control input on the N1265A/N1266A/N1268A expander.

## Measurement Mode Map

Source: Chapter 2 Measurement Modes (PDF 91-132) and `XE` command required-command table (PDF 571-572).

| MM Mode | Measurement Type | Required Commands Before `XE` | Detail Pages |
|---:|---|---|---|
| none | High-speed spot | `TI`, `TV`, `TIV`, `TC`, `TTC`, `TTI`, `TTIV`, `TTV`; no `MM`/`XE` | PDF 535-545 / printed 4-217 to 4-227 |
| 1 | Spot | `CN`, `MM`, `DV` or `DI` | PDF 92 / 2-4 |
| 2 | Staircase sweep | `CN`, `MM`, `WV` or `WI` | PDF 96-98 / 2-8 to 2-10 |
| 3 | Pulsed spot | `CN`, `MM`, `PT`, `PV` or `PI` | PDF 93 / 2-5 |
| 4 | Pulsed sweep | `CN`, `MM`, `PT`, `PWV` or `PWI` | PDF 100-102 / 2-12 to 2-14 |
| 5 | Staircase sweep with pulsed bias | `CN`, `MM`, `PT`, `WV` or `WI`, `PV` or `PI` | PDF 98-100 / 2-10 to 2-12 |
| 9 | Quasi-pulsed spot | `CN`, `MM`, `BDV` | PDF 106-108 / 2-18 to 2-20 |
| 10 | Sampling | `CN`, `MM`, `MCC`, `ML`, `MT`, `MSC`, `MI`, `MV`, `MSP` | PDF 112-115 / 2-24 to 2-27 |
| 13 | Quasi-static CV | `CN`, `MM`, `QST`, `QSV` | PDF 115-118 / 2-27 to 2-30 |
| 14 | Linear search | `CN`, `MM`, `LSV` or `LSI`, `LGV` or `LGI` | PDF 110-112 / 2-22 to 2-24 |
| 15 | Binary search | `CN`, `MM`, `BSV` or `BSI`, `BGV` or `BGI` | PDF 108-110 / 2-20 to 2-22 |
| 16 | Multi channel sweep | `CN`, `MM`, `WI` or `WV`, `WNX` | PDF 102-104 / 2-14 to 2-16 |
| 17 | Spot C | `CN`, `MM`, `IMP`, `FC`, `ACV`, `DCV` | PDF 118-119 / 2-30 to 2-31 |
| 18 | CV (DC bias) sweep | `CN`, `MM`, `IMP`, `FC`, `ACV`, `WDCV` | PDF 121-124 / 2-33 to 2-36 |
| 19 | Pulsed spot C | `CN`, `MM`, `IMP`, `FC`, `ACV`, `PTDCV`, `PDCV` | PDF 119-121 / 2-31 to 2-33 |
| 20 | Pulsed sweep CV | `CN`, `MM`, `IMP`, `FC`, `ACV`, `PTDCV`, `PWDCV` | PDF 124-126 / 2-36 to 2-38 |
| 22 | C-f sweep | `CN`, `MM`, `IMP`, `DCV`, `ACV`, `WFC` | PDF 126-128 / 2-38 to 2-40 |
| 23 | CV (AC level) sweep | `CN`, `MM`, `IMP`, `FC`, `DCV`, `WACV` | PDF 128-129 / 2-40 to 2-41 |
| 26 | C-t sampling | `CN`, `MM`, `IMP`, `FC`, `ACV`, `MDCV`, `MTDCV` | PDF 130-132 / 2-42 to 2-44 |
| 27 | Multi channel pulsed spot | `CN`, `MM`, `MCPT`, `MCPNT`, `MCPNX` | PDF 94-95 / 2-6 to 2-7 |
| 28 | Multi channel pulsed sweep | `CN`, `MM`, `MCPT`, `MCPNT`, `MCPWS`, `MCPWNX` | PDF 104-106 / 2-16 to 2-18 |

Unused/reserved MM numbers: 6, 7, 8, 11, 12, 21, 24, 25.

## FMT Data Output Formats

Sources: Table 4-24 `FMT` format parameter, PDF 437 / printed 4-119; Table 4-25 `FMT` mode parameter, PDF 438 / printed 4-120; Chapter 1 Data Output Format, PDF 45-75 / printed 1-25 to 1-55.

Syntax: `FMT format[,mode]`. `format` is 1 to 25 (Table 4-24); `mode` 0 to 10 selects source data returned with measurement data (Table 4-25). The terminator is fixed by `format`; there is no separate terminator parameter. `FMT` clears the output data buffer and is not allowed in a multi-command statement (PDF 436 / printed 4-118).

| `format` | Data format (Table 4-24) | Terminator | Element layout (Table 1-6) | Notes |
|---:|---|---|---|---|
| 1 | ASCII, 12 digits, with header | `<CR/LF^EOI>` | `ABC` + 12 digits | Default (`FMT 1,0`). 4142B compatible |
| 2 | ASCII, 12 digits, no header | `<CR/LF^EOI>` | 12 digits | No status/channel/type. 4142B compatible |
| 3 | 4-byte binary | `<CR/LF^EOI>` | Binary (status in bit field, Table 1-13) | No time stamp (`TSC` ineffective). 4142B compatible |
| 4 | 4-byte binary | `<^EOI>` | Binary (Table 1-13) | No time stamp. 4142B compatible |
| 5 | ASCII, 12 digits, with header | `,` (comma) | `ABC` + 12 digits | Same elements as FMT 1, comma terminator. 4142B compatible |
| 11 | ASCII, 13 digits, with header | `<CR/LF^EOI>` | `ABC` + 13 digits | |
| 12 | ASCII, 13 digits, no header | `<CR/LF^EOI>` | 13 digits | 4155/4156 FLEX compatible |
| 13 | 8-byte binary | `<CR/LF^EOI>` | Binary (status byte, Table 1-15) | Time stamp available |
| 14 | 8-byte binary | `<^EOI>` | Binary (Table 1-15) | Time stamp available |
| 15 | ASCII, 13 digits, with header | `,` (comma) | `ABC` + 13 digits | |
| 21 | ASCII, 13 digits, with header | `<CR/LF^EOI>` | `EEEFG` + 13 digits | Three-digit summed status. 4155/4156 FLEX compatible |
| 22 | ASCII, 13 digits, no header | `<CR/LF^EOI>` | 13 digits | 4155/4156 FLEX compatible |
| 25 | ASCII, 13 digits, with header | `,` (comma) | `EEEFG` + 13 digits | Three-digit summed status. 4155/4156 FLEX compatible |

- 8-byte binary is FMT 13 or FMT 14 only ("enter the FMT13 or FMT14 command", PDF 57 / printed 1-37). FMT 5 is ASCII.
- 12-digit data: `sn.nnnnnEsnn`, `snn.nnnnEsnn`, or `snnn.nnnEsnn`; 13-digit data adds one mantissa digit (PDF 437).
- For the best time stamp resolution (100 μs), clear the timer with `TSR` every 100 s or less for FMT 1, 2, or 5, and every 1000 s or less for FMT 11, 12, 15, 21, 22, or 25 (PDF 82 / printed 1-62; PDF 539 / printed 4-221). These are not separate time stamp modes; Table 4-24 distinguishes them only by digits, header, and terminator.

Default from Table 2-13: ASCII with header, `CR/LF^EOI` (PDF 180 / printed 2-92).

## ASCII Data Element Codes

Source: Data Elements, Tables 1-6 to 1-12, PDF 50-55 / printed 1-30 to 1-35.

| `FMT` | Element | Status field |
|---|---|---|
| 1, 5 | `A B C` + 12-digit data `D` | `A`: one character |
| 11, 15 | `A B C` + 13-digit data `D` | `A`: one character |
| 21, 25 | `EEE F G` + 13-digit data `D` | `EEE`: three digits, summed |
| 2, 12, 22 | Data only | None |

`A`/`EEE` = status, `B`/`F` = channel (Table 1-11), `C`/`G` = data type (Table 1-12).

### Measurement Data Status `A` (FMT 1, 5, 11, 15)

Source: Table 1-10, PDF 53 / printed 1-33.

| Code | Meaning (manual) | Parser Note |
|---|---|---|
| `N` | No status error occurred | Normal |
| `T` | Another channel reached its compliance setting | Flag: another channel is compliance-limited |
| `C` | This channel reached its compliance setting | Compliance-limited |
| `V` | Measurement data is over the measurement range, or the sweep was aborted by the automatic stop function or power compliance. Data is `199.999E+99` (no meaning) | Treat value as invalid |
| `X` | One or more channels are oscillating, or source output did not settle before measurement | Suspect; lengthen wait/delay or adjust compliance/range per footnote a |
| `F` | SMU is in the force saturation condition | Suspect |
| `G` | Linear/binary search: target not found within the search range (returns the source output value). Quasi-pulsed spot: detection time over the limit (3 s Short, 12 s Long) | Meaning depends on `MM` |
| `S` | Linear/binary search: search stopped (returns the source output value; see `Data_sense` status). Quasi-pulsed spot: output slew rate too slow for settling detection, or the source reached current compliance before the output changed 10 V from the start | Meaning depends on `MM` |
| `U` | CMU is in the NULL loop unbalance condition | CMU only |
| `D` | CMU is in the IV amplifier saturation condition | CMU only |

There is no `L` status code. SMU severity (PDF 51 / printed 1-31): `N<G<S<T<C<V<X` in general; `N<T<C<V<X<G` or `S` for quasi-pulsed spot measurement.

### Source Data Status (all header formats)

Source: Table 1-7, PDF 52 / printed 1-32. Applies to `Source_data` (sweep source output, enabled by `FMT` `mode`), in the `A` or `EEE` position. Severity `W<E`.

| Code | Meaning |
|---|---|
| `W` | Data is for the first or intermediate sweep step |
| `E` | Data is for the last sweep step |

### Summed Status `EEE` (FMT 21, 25)

Sources: Table 1-8 (SMU) and Table 1-9 (CMU), PDF 52 / printed 1-32. If several conditions occur, the sum of the values is returned (for example, A/D overflow plus SMU oscillation gives 3). Ignore `EEE` for Time values (PDF 51).

| Value | SMU (Table 1-8) | CMU (Table 1-9) |
|---:|---|---|
| 1 | A/D converter overflowed | A/D converter overflowed |
| 2 | Oscillation or force saturation occurred | NULL loop unbalance |
| 4 | Another unit reached its compliance setting | IV amplifier saturation |
| 8 | This unit reached its compliance setting | Not assigned |
| 16 | Target value was not found within the search range | Not assigned |
| 32 | Search measurement was automatically stopped | Not assigned |
| 64 | Invalid data is returned; `D` is not used | Invalid data is returned; `D` is not used |
| 128 | EOD (End of Data) | EOD (End of Data) |

Binary formats use their own status fields: Table 1-13 (4-byte, PDF 66 / printed 1-46) and Table 1-15 (8-byte, PDF 74 / printed 1-54).

### Channel Codes `B`/`F`

Source: Table 1-11, PDF 54 / printed 1-34.

| Code | Meaning |
|---|---|
| `A`-`J` | Subchannel 1 of the module in slot 1-10 |
| `a`-`j` | Subchannel 2 of the module in slot 1-10 (SMU and CMU have no subchannel 2) |
| `V` | Ground unit (GNDU) |
| `Z` | Status code for extraneous data in the channel: `TSQ` command response or invalid data |

### Data Type Codes `C`/`G`

Source: Table 1-12, PDF 55 / printed 1-35.

| Code | Position | Meaning |
|---|---|---|
| `V` | `C` | Voltage (V) |
| `I` | `C` | Current (A) |
| `F` | `C` | Frequency (Hz) |
| `Z` | `C` or `G` | Impedance, resistance, or reactance (ohm) |
| `Y` | `C` or `G` | Admittance, conductance, or susceptance (S) |
| `C` | `C` or `G` | Capacitance (F) |
| `L` | `C` or `G` | Inductance (H) |
| `R` | `C` or `G` | Phase (radian) |
| `P` | `C` or `G` | Phase (degree) |
| `D` | `C` or `G` | Dissipation factor |
| `Q` | `C` or `G` | Quality factor |
| `X` | `C` or `G` | Sampling index |
| `T` | `C` or `G` | Time (second) |
| `V` | `G` | Voltage measurement value (V) |
| `I` | `G` | Current measurement value (A) |
| `v` | `G` | Voltage output value (V) |
| `i` | `G` | Current output value (A) |
| `f` | `G` | Frequency (Hz) |
| `z` | `G` | Invalid data |

## Query Response Buffer vs Output Data Buffer

Sources: PDF 28 / printed 1-8; PDF 45 / printed 1-25; `BC` command PDF 364 / printed 4-46, `NUB?` PDF 478 / printed 4-160.

| Buffer | Stores | Format | Capacity | Clear Method |
|---|---|---|---|---|
| Query response buffer | Response from query commands (`*IDN?`, `UNT?`, `ERR?`, `ERRX?`, `*LRN?`, `NUB?`, `*STB?`, `*OPC?`, `WZ?`, etc.) | Always ASCII | One response only; must be read before next query | Overwritten by next query; cleared by device clear |
| Output data buffer | Measurement data from `XE`, `TI`, `TV`, `TIV`, `TSQ`, sweep/sampling results | Depends on `FMT` setting | Large (thousands of data items); overflow causes error 260 | `BC` command, `*RST`, device clear |

Key driver implications:

- Query buffer stores only ONE response. A second query overwrites the first. Read immediately after sending any query command.
- Measurement data goes to the output data buffer, not the query buffer. Use `NUB?` to check how many data items are available before reading.
- Status byte Bit 0 (Data ready) indicates whether the output buffer is empty.
- `FMT` affects output data buffer format, not query responses (queries always return ASCII).

## Measurement and Output Ranging Concepts

Sources: Tables 4-2 through 4-15, PDF 335-346 / printed 4-17 to 4-28.

### General Rules

| Concept | Meaning | Source |
|---|---|---|
| Auto ranging (`0`) | Instrument selects the minimum range that covers the measurement or output value | PDF 336, 339 |
| Limited auto ranging | Instrument auto-ranges but never uses a range lower than specified | PDF 336, 339 |
| Fixed range (negative values) | Instrument uses specified fixed range where supported | PDF 335-338 |
| Compliance range for pulse | In pulse measurement, measurement range may be based on compliance range | PDF 335, 337 |
| ASU 1 pA support | 1 pA range requires ASU and `SAR` to enable 1 pA auto-ranging | PDF 336 |
| Module selector current limit | Dual HCSMU through N1258A/N1259A-300 selector must be limited to +/-30 A | PDF 340 |

### Voltage Measurement Ranging Examples

Source: Table 4-2, PDF 335-336.

| Range Value | Meaning |
|---:|---|
| `0` | Auto ranging; pulse uses compliance range |
| `2`, `5`, `20`/`11`, `50`, `200`/`12`, `400`/`13` | Limited auto ranges for 0.2 V, 0.5 V, 2 V, 5 V, 20 V, 40 V where supported |
| `1000`/`14`, `2000`/`15`, `5000`, `15000`, `30000` | Limited auto ranges for high-voltage resources where supported |
| Negative values such as `-20`/`-11` | Fixed range |

### Current Measurement Ranging Examples

Source: Table 4-3, PDF 337-338.

| Range Value | Meaning |
|---:|---|
| `0` | Auto ranging; pulse uses compliance range |
| `8` | 1 pA limited auto (ASU; B1511B MPSMU note) |
| `9` to `23` | 10 pA through 40 A limited auto ranges, resource-dependent |
| `-8` to `-23` | Fixed current ranges from 1 pA through 40 A, resource-dependent |
| `26`, `28` | UHCU 500 A / 2000 A limited auto where supported |
| `-26`, `-28` | UHCU fixed 500 A / 2000 A where supported |

### Output Ranging Examples

Sources: Table 4-4 and Table 4-5, PDF 339-340.

| Parameter | Examples | Notes |
|---|---|---|
| Voltage output range / `vrange` | `0`, `2`, `5`, `20`/`11`, `200`/`12`, `1000`/`14`, `30000`, `103` | `103` maps to 10 kV limited auto for UHVU |
| Current output range / `irange` | `0`, `8`-`23`, `26`, `28` | ASU 1 pA range and UHC high-current ranges are resource-dependent |

## MFCMU Measurement Parameters (`IMP`)

Source: Table 4-16, PDF 347 / printed 4-29.

| Mode | Primary Parameter | Secondary Parameter |
|---:|---|---|
| 1 | R (resistance, ohm) | X (reactance, ohm) |
| 2 | G (conductance, S) | B (susceptance, S) |
| 10 | Z (impedance, ohm) | theta (phase, radian) |
| 11 | Z (impedance, ohm) | theta (phase, degree) |
| 20 | Y (admittance, S) | theta (phase, radian) |
| 21 | Y (admittance, S) | theta (phase, degree) |
| 100 | Cp (parallel capacitance, F) | G (conductance, S) |
| 101 | Cp (parallel capacitance, F) | D (dissipation factor) |
| 102 | Cp (parallel capacitance, F) | Q (quality factor) |
| 103 | Cp (parallel capacitance, F) | Rp (parallel resistance, ohm) |
| 200 | Cs (series capacitance, F) | Rs (series resistance, ohm) |
| 201 | Cs (series capacitance, F) | D (dissipation factor) |
| 202 | Cs (series capacitance, F) | Q (quality factor) |
| 300 | Lp (parallel inductance, H) | G (conductance, S) |
| 301 | Lp (parallel inductance, H) | D (dissipation factor) |
| 302 | Lp (parallel inductance, H) | Q (quality factor) |
| 303 | Lp (parallel inductance, H) | Rp (parallel resistance, ohm) |
| 400 | Ls (series inductance, H) | Rs (series resistance, ohm) |
| 401 | Ls (series inductance, H) | D (dissipation factor) |
| 402 | Ls (series inductance, H) | Q (quality factor) |

## MFCMU Range and Frequency Practical Notes

Sources: Tables 4-17 through 4-20, PDF 348-349.

| Parameter | Extracted Values | Source |
|---|---|---|
| MFCMU fixed impedance ranges | 50 ohm, 100 ohm, 300 ohm, 1 kohm, 3 kohm, 10 kohm, 30 kohm, 100 kohm, 300 kohm depending on frequency | PDF 348 |
| Frequency setting resolution | 0.001 Hz (1 kHz to <10 kHz), 0.01 Hz (10 kHz to <100 kHz), 0.1 Hz (100 kHz to <1 MHz), 1 Hz (1 MHz to 5 MHz) | PDF 348 |
| AC level ranges | 0.016, 0.032, 0.064, 0.125, 0.250 V shown in extracted table | PDF 348 |
| DC bias ranges | 8, 12, 25, 100; 100 V may route through SMU/SCUU while MFCMU uses 25 V range | PDF 349 |

## Timing, Wait, Trigger, Timestamp

| Command | Parameters / Meaning | Source |
|---|---|---|
| `WT` | Sweep hold, delay, step delay, trigger delay times | PDF 564-565 / printed 4-246 to 4-247 |
| `WTDCV` | CMU sweep hold, delay, step delay, trigger delays; includes `Mdelay` | PDF 566 / printed 4-248 |
| `WTFC` | C-f sweep hold, delay, step delay, trigger delays | PDF 567-568 / printed 4-249 to 4-250 |
| `PT` | Pulse hold, pulse width, pulse period, trigger output delay | PDF 486 / printed 4-168 |
| `PA` | Pause command execution until time elapses or trigger/event releases | PDF 481 / printed 4-163 |
| `PAX` | Pause until external trigger | PDF 482 / printed 4-164 |
| `TSC` | Enable/disable timestamp function | PDF 538 / printed 4-220 |
| `TSR` | Reset timestamp counter | PDF 539 / printed 4-221 |
| `TSQ` | Query current timestamp value | PDF 539 / printed 4-221 |

Timestamp caveats:

- `TSC` is not available for 4-byte binary `FMT 3`/`FMT 4`, high-speed spot, quasi-pulsed spot (`MM9`), and search (`MM14`/`MM15`) measurements.
- For best resolution, reset timestamp periodically; Chapter 3 suggests every 100 s or less for `FMT 1`, `FMT 2`, or `FMT 5`, and every 1000 s or less for `FMT 11`, `FMT 12`, `FMT 15`, `FMT 21`, `FMT 22`, or `FMT 25`.

## Status Byte

Source: PDF 76-78 / printed 1-56 to 1-58; also Table 4-29 on PDF 518 / printed 4-200.

| Bit | Decimal | Meaning | Clear Condition |
|---:|---:|---|---|
| 0 | 1 | Data ready (output buffer not empty; set to 1 if unread data/query response exists) | All data read, or `*RST`, `BC`, `FMT`, device clear |
| 1 | 2 | Wait (instrument in wait state from `PA`, `WS`, `PAX`, or `WSX`) | Wait condition complete, or `*RST`, device clear |
| 2 | 4 | Not applicable (always 0) | — |
| 3 | 8 | Interlock open (interlock circuit is open AND voltage output/compliance exceeds allowable threshold) | Serial poll, `*RST`, device clear |
| 4 | 16 | Set ready (operation complete; goes LOW on command/trigger receipt, HIGH on completion) | Set to 0 on command receipt |
| 5 | 32 | Error (set to 1 if any error occurred) | Serial poll, `*RST`, `ERR?`, `ERRX?`, `CA`, `*TST?`, `*CAL?`, `DIAG?`, device clear |
| 6 | 64 | RQS / SRQ (service request; set to 1 whenever any other unmasked bit is set to 1; cannot be masked) | Serial poll, `*RST`, device clear |
| 7 | 128 | Not applicable (always 0) | — |

Notes:

- If Bit 3 and Bit 5 are masked in `*SRE`, they are NOT set to 0 by a serial poll. Removing a mask from a bit that is already set to 1 does NOT retroactively trigger SRQ.
- Use serial polling inside interrupt service routines; use `*STB?` in normal polling.
- Default from Table 2-13: only bit 6 is enabled in `*SRE` (PDF 180 / printed 2-92).

---

## Review Notes

| Field | Value |
|---|---|
| Review date | 2026-06-22 |
| Reviewer | opus-4.6-max |
| Passes | 5 |

Corrections applied:

- **CRITICAL**: Status Byte table completely rewritten. Previous version had bits 0-3 wrong (claimed bit 0-2 unused, bit 3 = buffer not empty). Verified against PDF 75-77: bit 0 = data ready, bit 1 = wait, bit 3 = interlock open.
- Added Query Response Buffer vs Output Data Buffer section with driver implications.
- FMT modes 11/12/15/21/22/25 description updated from "compatibility/alternate" to "extended timestamp resolution formats" per PDF 538 remarks.
- Added clear conditions and decimal values to status byte table.

Remaining uncertainties:

- FMT 11/12/15/21/22/25 exact output format differences vs FMT 1/2/5 not fully documented (need FMT command page 435-436 detailed read).
- MFCMU range/frequency tables (PDF 347-348) values were extracted in a prior pass; not individually re-verified.
- Voltage/current range tables are "structured summary, not every numeric cell" as stated in coverage.

### Corrections 2026-11-17

Verified against `B1500A Programming Guide.pdf` Edition 15 page text.

- **Page numbering:** every "PDF N" now uses the physical PDF page. Earlier PDF numbers were mostly one lower (text before page marker `-- N of 617 --` was attributed to page N, but the marker ends page N). Some Chapter 2 entries were already correct, so each number was recomputed from its printed page rather than shifted. The 2026-06-22 notes above keep their original (old) PDF numbers.
- **FMT:** FMT 5 is ASCII 12-digit with header and a comma terminator (Table 4-24, PDF 437); 8-byte binary is FMT 13/14 (PDF 57). The "extended timestamp resolution" gloss for FMT 11-25 was removed: they are 13-digit ASCII formats. The FMT syntax is `FMT format[,mode]`.
- **Status codes:** replaced with Tables 1-7 to 1-10 (PDF 52-53). `D` is CMU IV amplifier saturation, `U` is CMU NULL loop unbalance, `W`/`E` are source data step status, `F` is SMU force saturation, there is no `L`, and `V` data is `199.999E+99`. Added the FMT 21/25 summed `EEE` codes (Tables 1-8/1-9) and the element layouts (Table 1-6).
- **Data type codes:** `R` is phase in radians and `X` is sampling index (not resistance/reactance); added the `G`-position codes `v`, `i`, `f`, `z` (Table 1-12, PDF 55).
- Resolved: the FMT 11/12/15/21/22/25 uncertainty listed above.
