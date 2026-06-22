# B1500A Command Parameters

Source: `B1500A Programming Guide.pdf`, mainly Chapter 1 Data Output Format, Chapter 2 Measurement Modes, and Chapter 4 Command Parameters.

## Coverage

| Parameter Area | Coverage | Source Pages |
|---|---:|---|
| Channel numbering | Complete practical table | PDF 333 / printed 4-16 |
| MM measurement mode map | Complete mode list from guide/index | PDF 90-132; `XE` required-command table PDF 570-571 |
| Required commands before `XE` | Complete transcription | PDF 570-571 / printed 4-253 to 4-254 |
| FMT output formats | Practical extraction | PDF 44-74; PDF 435-436 |
| ASCII status/channel/type codes | Practical extraction | PDF 48-54 |
| Voltage/current range concepts | Structured summary, not every numeric cell | PDF 334-345 / printed 4-17 to 4-28 |
| MFCMU measurement parameters | Complete Table 4-16 | PDF 346 / printed 4-29 |
| Timing/timestamp parameters | Practical extraction | PDF 75-77, 537-538, 563-566 |

## Channel Numbering

Source: Table 4-1, PDF 333 / printed 4-16.

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

Source: Chapter 2 Measurement Modes (PDF 90-132) and `XE` command required-command table (PDF 570-571).

| MM Mode | Measurement Type | Required Commands Before `XE` | Detail Pages |
|---:|---|---|---|
| none | High-speed spot | `TI`, `TV`, `TIV`, `TC`, `TTC`, `TTI`, `TTIV`, `TTV`; no `MM`/`XE` | PDF 534-544 / printed 4-217 to 4-227 |
| 1 | Spot | `CN`, `MM`, `DV` or `DI` | PDF 91 / 2-4 |
| 2 | Staircase sweep | `CN`, `MM`, `WV` or `WI` | PDF 95-97 / 2-8 to 2-10 |
| 3 | Pulsed spot | `CN`, `MM`, `PT`, `PV` or `PI` | PDF 92 / 2-5 |
| 4 | Pulsed sweep | `CN`, `MM`, `PT`, `PWV` or `PWI` | PDF 99-101 / 2-12 to 2-14 |
| 5 | Staircase sweep with pulsed bias | `CN`, `MM`, `PT`, `WV` or `WI`, `PV` or `PI` | PDF 97-99 / 2-10 to 2-12 |
| 9 | Quasi-pulsed spot | `CN`, `MM`, `BDV` | PDF 105-107 / 2-18 to 2-20 |
| 10 | Sampling | `CN`, `MM`, `MCC`, `ML`, `MT`, `MSC`, `MI`, `MV`, `MSP` | PDF 112-115 / 2-24 to 2-27 |
| 13 | Quasi-static CV | `CN`, `MM`, `QST`, `QSV` | PDF 115-118 / 2-27 to 2-30 |
| 14 | Linear search | `CN`, `MM`, `LSV` or `LSI`, `LGV` or `LGI` | PDF 109-111 / 2-22 to 2-24 |
| 15 | Binary search | `CN`, `MM`, `BSV` or `BSI`, `BGV` or `BGI` | PDF 107-109 / 2-20 to 2-22 |
| 16 | Multi channel sweep | `CN`, `MM`, `WI` or `WV`, `WNX` | PDF 101-103 / 2-14 to 2-16 |
| 17 | Spot C | `CN`, `MM`, `IMP`, `FC`, `ACV`, `DCV` | PDF 118-119 / 2-30 to 2-31 |
| 18 | CV (DC bias) sweep | `CN`, `MM`, `IMP`, `FC`, `ACV`, `WDCV` | PDF 121-124 / 2-33 to 2-36 |
| 19 | Pulsed spot C | `CN`, `MM`, `IMP`, `FC`, `ACV`, `PTDCV`, `PDCV` | PDF 119-121 / 2-31 to 2-33 |
| 20 | Pulsed sweep CV | `CN`, `MM`, `IMP`, `FC`, `ACV`, `PTDCV`, `PWDCV` | PDF 124-126 / 2-36 to 2-38 |
| 22 | C-f sweep | `CN`, `MM`, `IMP`, `DCV`, `ACV`, `WFC` | PDF 126-128 / 2-38 to 2-40 |
| 23 | CV (AC level) sweep | `CN`, `MM`, `IMP`, `FC`, `DCV`, `WACV` | PDF 128-129 / 2-40 to 2-41 |
| 26 | C-t sampling | `CN`, `MM`, `IMP`, `FC`, `ACV`, `MDCV`, `MTDCV` | PDF 130-132 / 2-42 to 2-44 |
| 27 | Multi channel pulsed spot | `CN`, `MM`, `MCPT`, `MCPNT`, `MCPNX` | PDF 93-94 / 2-6 to 2-7 |
| 28 | Multi channel pulsed sweep | `CN`, `MM`, `MCPT`, `MCPNT`, `MCPWS`, `MCPWNX` | PDF 103-105 / 2-16 to 2-18 |

Unused/reserved MM numbers: 6, 7, 8, 11, 12, 21, 24, 25.

## FMT Data Output Formats

Sources: Chapter 1 Data Output Format PDF 44-74; `FMT` command PDF 435-436 / printed 4-118 to 4-119.

| FMT Mode | Meaning | Notes |
|---:|---|---|
| 1 | ASCII with header | Default format; includes status/channel/type style prefixes |
| 2 | ASCII without header | Numeric data only, easier parser when channel/type is fixed |
| 3 | 4-byte binary | Compact binary; no timestamp support for `TSC`; resolution lower than high-resolution ADC |
| 4 | 4-byte binary | Similar 4-byte binary mode; terminator behavior differs per command page |
| 5 | 8-byte binary / double-precision style output | Uses IEEE 754 double precision data element style |
| 11, 12, 15, 21, 22, 25 | ASCII formats with extended timestamp resolution | Per PDF 538 / 4-221 (TSR remarks): these modes support 1000 s timer-clear interval for 100 μs best resolution (vs 100 s for FMT 1/2/5). Exact output differences vs modes 1/2/5 should be verified on `FMT` command page PDF 435-436 |

Default from Table 2-13: ASCII with header, `CR/LF^EOI` (PDF 179 / printed 2-92).

## ASCII Status Codes

Source: ASCII Data Output Format, PDF 48-52 / printed 1-29 to 1-33.

| Code | Meaning | Parser Note |
|---|---|---|
| `N` | Normal data | Normal measurement |
| `T` | Another channel reached compliance | Data valid but another channel compliance occurred |
| `C` | This channel reached compliance | Treat as compliance-limited |
| `W` | Warning / other channel condition | Check measurement context |
| `X` | Oscillation detected | Treat as suspect/invalid |
| `U` | Unused/undefined or special condition | Verify exact page when seen |
| `V` | Overflow | Data out of range |
| `G` | Search-related status | Used in search modes |
| `D` | Search-related status | Used in search modes |
| `S` | Search-related status | Used in search modes |

## ASCII Channel and Data Type Codes

Sources: PDF 53-54 / printed 1-34 to 1-35.

| Code Family | Meaning |
|---|---|
| `A`-`J` | Slot/channel 1-10 style channel code |
| `a`-`j` | Subchannel code for two-channel modules |
| `V` | GNDU |
| `Z` | Invalid or not applicable channel |

| Data Type Code | Meaning |
|---|---|
| `V` | Voltage |
| `I` | Current |
| `F` | Frequency |
| `Z` | Impedance |
| `Y` | Admittance |
| `C` | Capacitance |
| `L` | Inductance |
| `R` | Resistance |
| `P` | Phase |
| `D` | Dissipation factor |
| `Q` | Quality factor |
| `X` | Reactance |
| `T` | Time |

## Query Response Buffer vs Output Data Buffer

Sources: PDF 27 / printed 1-8; PDF 44 / printed 1-25; `BC` command PDF 363, `NUB?` PDF 477.

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

Sources: Tables 4-2 through 4-15, PDF 334-345 / printed 4-17 to 4-28.

### General Rules

| Concept | Meaning | Source |
|---|---|---|
| Auto ranging (`0`) | Instrument selects the minimum range that covers the measurement or output value | PDF 335, 338 |
| Limited auto ranging | Instrument auto-ranges but never uses a range lower than specified | PDF 335, 338 |
| Fixed range (negative values) | Instrument uses specified fixed range where supported | PDF 334-337 |
| Compliance range for pulse | In pulse measurement, measurement range may be based on compliance range | PDF 334, 336 |
| ASU 1 pA support | 1 pA range requires ASU and `SAR` to enable 1 pA auto-ranging | PDF 335 |
| Module selector current limit | Dual HCSMU through N1258A/N1259A-300 selector must be limited to +/-30 A | PDF 339 |

### Voltage Measurement Ranging Examples

Source: Table 4-2, PDF 334-335.

| Range Value | Meaning |
|---:|---|
| `0` | Auto ranging; pulse uses compliance range |
| `2`, `5`, `20`/`11`, `50`, `200`/`12`, `400`/`13` | Limited auto ranges for 0.2 V, 0.5 V, 2 V, 5 V, 20 V, 40 V where supported |
| `1000`/`14`, `2000`/`15`, `5000`, `15000`, `30000` | Limited auto ranges for high-voltage resources where supported |
| Negative values such as `-20`/`-11` | Fixed range |

### Current Measurement Ranging Examples

Source: Table 4-3, PDF 336-337.

| Range Value | Meaning |
|---:|---|
| `0` | Auto ranging; pulse uses compliance range |
| `8` | 1 pA limited auto (ASU; B1511B MPSMU note) |
| `9` to `23` | 10 pA through 40 A limited auto ranges, resource-dependent |
| `-8` to `-23` | Fixed current ranges from 1 pA through 40 A, resource-dependent |
| `26`, `28` | UHCU 500 A / 2000 A limited auto where supported |
| `-26`, `-28` | UHCU fixed 500 A / 2000 A where supported |

### Output Ranging Examples

Sources: Table 4-4 and Table 4-5, PDF 338-339.

| Parameter | Examples | Notes |
|---|---|---|
| Voltage output range / `vrange` | `0`, `2`, `5`, `20`/`11`, `200`/`12`, `1000`/`14`, `30000`, `103` | `103` maps to 10 kV limited auto for UHVU |
| Current output range / `irange` | `0`, `8`-`23`, `26`, `28` | ASU 1 pA range and UHC high-current ranges are resource-dependent |

## MFCMU Measurement Parameters (`IMP`)

Source: Table 4-16, PDF 346 / printed 4-29.

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

Sources: Tables 4-17 through 4-20, PDF 347-348.

| Parameter | Extracted Values | Source |
|---|---|---|
| MFCMU fixed impedance ranges | 50 ohm, 100 ohm, 300 ohm, 1 kohm, 3 kohm, 10 kohm, 30 kohm, 100 kohm, 300 kohm depending on frequency | PDF 347 |
| Frequency setting resolution | 0.001 Hz (1 kHz to <10 kHz), 0.01 Hz (10 kHz to <100 kHz), 0.1 Hz (100 kHz to <1 MHz), 1 Hz (1 MHz to 5 MHz) | PDF 347 |
| AC level ranges | 0.016, 0.032, 0.064, 0.125, 0.250 V shown in extracted table | PDF 347 |
| DC bias ranges | 8, 12, 25, 100; 100 V may route through SMU/SCUU while MFCMU uses 25 V range | PDF 348 |

## Timing, Wait, Trigger, Timestamp

| Command | Parameters / Meaning | Source |
|---|---|---|
| `WT` | Sweep hold, delay, step delay, trigger delay times | PDF 563-564 / printed 4-246 to 4-247 |
| `WTDCV` | CMU sweep hold, delay, step delay, trigger delays; includes `Mdelay` | PDF 565 / printed 4-248 |
| `WTFC` | C-f sweep hold, delay, step delay, trigger delays | PDF 566-567 / printed 4-249 to 4-250 |
| `PT` | Pulse hold, pulse width, pulse period, trigger output delay | PDF 485 / printed 4-168 |
| `PA` | Pause command execution until time elapses or trigger/event releases | PDF 480 / printed 4-163 |
| `PAX` | Pause until external trigger | PDF 481 / printed 4-164 |
| `TSC` | Enable/disable timestamp function | PDF 537 / printed 4-220 |
| `TSR` | Reset timestamp counter | PDF 538 / printed 4-221 |
| `TSQ` | Query current timestamp value | PDF 538 / printed 4-221 |

Timestamp caveats:

- `TSC` is not available for 4-byte binary `FMT 3`/`FMT 4`, high-speed spot, quasi-pulsed spot (`MM9`), and search (`MM14`/`MM15`) measurements.
- For best resolution, reset timestamp periodically; Chapter 3 suggests every 100 s or less for `FMT 1`, `FMT 2`, or `FMT 5`, and every 1000 s or less for `FMT 11`, `FMT 12`, `FMT 15`, `FMT 21`, `FMT 22`, or `FMT 25`.

## Status Byte

Source: PDF 75-77 / printed 1-56 to 1-58; also Table 4-29 on PDF 517 / printed 4-200.

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
- Default from Table 2-13: only bit 6 is enabled in `*SRE` (PDF 179 / printed 2-92).

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
