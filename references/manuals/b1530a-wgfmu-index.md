# B1530A WGFMU Manual Index

## Source

| Field | Value |
|---|---|
| PDF path | `B1530A WGFMU.pdf` (workspace root) |
| Manual title | Agilent B1530A Waveform Generator/Fast Measurement Unit User's Guide |
| Part number | B1530-90000 |
| Edition | Edition 5, August 2012 |
| Copyright | © Agilent Technologies, Inc. 2008, 2009, 2011, 2012 |
| Total PDF pages | 164 |
| Chapters | 4 chapters + front matter |
| PDF-to-print mapping | See table below |

### PDF Page vs Printed Page Convention

Each chapter uses its own numbering: `ChapterNumber-PageNumber` (e.g., `1-3`, `4-66`). The PDF page differs from the printed page by a fixed chapter-specific offset. Title pages (one per chapter) carry no printed page number.

| Chapter | Printed range | PDF range | Offset formula |
|---|---|---|---|
| Front matter | — | 1–10 | N/A |
| 1 Introduction | 1-2 → 1-18 | 12–28 | PDF = printed_suffix + 10 |
| Ch 1 title page | — | 11 | N/A |
| 2 Installation | 2-2 → 2-18 | 30–46 | PDF = printed_suffix + 28 |
| Ch 2 title page | — | 29 | N/A |
| 3 Using Instrument Library | 3-2 → 3-30 | 48–76 | PDF = printed_suffix + 46 |
| Ch 3 title page | — | 47 | N/A |
| 4 Instrument Library Reference | 4-2 → 4-88 | 78–164 | PDF = printed_suffix + 76 |
| Ch 4 title page | — | 77 | N/A |

---

## How To Use This Index

1. **Find a topic** → scan the Content-To-Page Map (official section order) or the High-Value Lookup Shortcuts.
2. **Resolve a page reference** → use the Page-To-Content Map (PDF page ranges).
3. **Convert printed ↔ PDF pages** → apply the offset formula above. Example: printed `4-55` → PDF page `55 + 76 = 131`.
4. **Locate API details** → jump directly to Chapter 4, PDF 85–141 for alphabetical function reference; PDF 142–151 for parameter constant tables.
5. **Find error codes** → PDF 154–157 (return/error codes), PDF 158–164 (error messages).
6. **Build a measurement program** → PDF 49–51 (programming overview, 9-step flow), PDF 57 (8-step workflow procedure), PDF 58–75 (11 examples of increasing complexity).
7. **Understand timing constraints** → PDF 25–26 (settling/pulse/window specs), PDF 130–131 (setMeasureEvent parameters), PDF 86 (inter-sequence 50 ns), PDF 134 (range change ≥2 µs).

---

## Content To Page Map

### Front Matter (PDF 1–10)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Title page | 1 | — | Product name, branding (Agilent B1530A WGFMU User's Guide). | B1530A, WGFMU | — |
| Notices & legal | 2 | — | Copyright (2008–2012), warranty disclaimer, technology licenses, restricted rights legend. | Edition 5, B1530-90000 | — |
| WEEE / servicing info | 3 | — | WEEE directive compliance. Servicing requires returning B1500A + all plug-in modules + B1531A RSU + cable set. Lists cable part numbers (16493R-003/004/006/001/002/005). | 16493R, B1531A, servicing | Must return full system for service |
| "In This Manual" overview | 4 | — | Describes the four chapters. Notes that WGFMU is NOT supported by EasyEXPERT Classic Test; must use Instrument Library API or sample application tests. | EasyEXPERT, Instrument Library | Critical: WGFMU requires library-based control |
| Table of Contents | 5–10 | — | Full TOC for all four chapters. Two blank pages (9–10) at end. | — | — |

### Chapter 1 — Introduction (PDF 11–28)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 1 title page | 11 | — | "1 Introduction" divider. | — | — |
| Chapter intro | 12 | 1-2 | Lists sub-sections; key NOTE: WGFMU is not supported by EasyEXPERT Classic Test. Must use Instrument Library (~80 API functions). Table 1-1 shows control platforms: B1500A (EasyEXPERT app tests), Windows PC (Desktop EasyEXPERT, sample programs, or custom programs). | EasyEXPERT, ALWG, API, Table 1-1 | WGFMU needs library-based programming |
| Overview | 13–14 | 1-3 to 1-4 | Product positioning: first self-contained ALWG + fast IV measurement module. Two operation modes per channel: **Fast IV** (VFIM/VFVM, arbitrary waveforms, current meas down to 2 nA, 5 ns sampling) and **PG** (pulse generator, 50 Ω output, narrower pulses). Simplified circuit diagram (Fig 1-1). Key specs summary: 2 ch/module, voltage ranges (3/5/10/−10 V), current ranges (1 µA–10 mA), modes (PG/Fast IV/DC/SMU), min pulse widths (100 ns PG, 300 ns Fast IV). | ALWG, Fast IV, PG, DC, SMU, VFIM, VFVM, 5 ns sampling, 10 ns resolution, 50 Ω | No compliance feature (no output limiter like SMU) |
| WGFMU (connector panel) | 15–16 | 1-5 to 1-6 | Physical description: Ch1/Ch2 measurement channels, Sync Out/In (5-pin), TrigOut (SMA). Up to 5 WGFMUs per B1500A (10 channels total). Module rating system (WGFMU=10). Trigger modes: none, event, execution, sequence, pattern. Trigger output: TTL level, positive/negative polarity, 10 ns width (exec/seq/pattern) or adjustable (event). | Sync Out, Sync In, TrigOut, SMA, TTL, master/slave | CAUTION: Sync/Trig terminals must be connected correctly to avoid damage. For trigger period <20 ns use negative trigger. |
| RSU (B1531A) | 17–18 | 1-7 to 1-8 | RSU is required per channel, mounted near DUT on prober. Has Output (SMA), From SMU (triax), V Monitor (BNC), From B1530A terminals. Switching between WGFMU and SMU paths. V Monitor outputs buffered 1/10 signal (50 Ω source impedance). Internal 450 Ω + ×1 amplifier detail. Max output: ±10 V (WGFMU), ±25 V (SMU). | B1531A, RSU, Output, From SMU, V Monitor, triaxial, SMA, BNC, 450 Ω | CAUTION: Max ±25 V on From SMU terminal. Disconnect DUT before changing SMU cables. B1500A must be OFF before connecting/disconnecting WGFMU-RSU cable. |
| Specifications – conditions & general | 19 | 1-9 | Spec conditions: 23±5 °C, 20–60% humidity, 40 min warm-up + self-cal, 1 year cal period, ≤25 pF load capacitance, V Monitor open. Physical dimensions/weight of B1530A (1.3 kg) and B1531A (0.13 kg). | self-calibration, load capacitance, 25 pF | — |
| Specifications – detailed | 20–21 | 1-10 to 1-11 | Mode/function matrix (Table 1-2): Fast IV (VFIM/VFVM), PG (VFVM only), DC (VFIM/VFVM), SMU pass-through (±25 V, ±100 mA). RSU specs: 50 Ω source impedance in PG, SMA output, SMU path ±25 V/±100 mA. V Monitor: BNC, 50 Ω source, outputs 1/10 of RSU output into 50 Ω. Cable lengths: 1.5/3/5 m (or adapter combos: 0.6+2.4 m or 0.6+4.4 m). ALWG function, trigger output (TTL, 10 ns width). Software: Instrument Library, NBTI+general-purpose EasyEXPERT Application Tests, sample programs (NBTI, general-purpose, RTS data analysis). Supported prober vendors: Cascade Microtech, Suss MicroTec, Vector Semicon. **RF EMF sensitivity**: V/I accuracy and inter-module timing affected by RF fields >3 V/m (80 MHz–1 GHz, 1.4–2.0 GHz) or >1 V/m (2.0–2.7 GHz). | Table 1-2, VFIM, VFVM, 50 Ω, prober vendors, RF EMF, NBTI, RTS | RF field can degrade measurement accuracy |
| Specifications – supplemental data | 22 | 1-12 | RSU SMU path leakage <100 pA, residual resistance <300 mΩ. Jitter <1 ns, inter-channel skew <3 ns (no ESD), trigger output skew <3 ns. Current range change time <150 µs. References to timing tables (1-7, 1-8). | jitter, skew, range change time, leakage | Skew affected by ESD — keep hands off terminals during measurement |
| Specifications – voltage force (Table 1-3) | 23 | 1-13 | Voltage force accuracy ±(0.1% setting + 0.1% range). Resolution: 96 µV (3 V range), 160 µV (others). PG mode overshoot ±(5% + 20 mV). Noise max 0.1 mVrms. Rise/fall time accuracy −5% to +(5% + 10 ns), min 24 ns (PG, 50 Ω). Pulse period min 100 ns, pulse width min 50 ns (PG, 50 Ω). | accuracy, resolution, overshoot, rise time, fall time, pulse width | Cable length affects min rise/fall: 16 ns (1.5 m), 32 ns (3 m), 56 ns (5 m) |
| Specifications – voltage/current measurement (Tables 1-4, 1-5, 1-6) | 24 | 1-14 | V meas accuracy ±(0.1% rdg + 0.1% range), resolution 680 µV (5 V) / 1.4 mV (10 V), noise max 4 mVrms (max 1.5 mVrms supplemental). I meas accuracy ±(0.1% rdg + 0.2% range), resolution 0.014% range, noise max 0.2% range. V accuracy condition: 10,000 averaging samples (≥10 µA); 100,000 samples (1 µA). ALWG: max 2048 vectors, 512 sequences, 10^12 loop counts, vector length 10 ns–10000 s (actual firmware limit: 10995.116 s per error 3311), 10 ns resolution, sampling rate 5 ns or 10 ns–1 s, averaging 10 ns–20 ms, about 4M data points/channel (typical, not guaranteed). | 2048 vectors, 512 sequences, 4M data points (typical), 5 ns sampling, 10 ns resolution | V/I accuracy requires specified averaging counts |
| Specifications – minimum timing for current measurement (Table 1-7) | 25 | 1-15 | Detailed table of settling time, minimum pulse width, minimum measurement window, and noise for each current level (100 nA to 10 mA) and range. Example: 10 mA range → min pulse 145 ns, settling 125 ns, min meas window 20 ns, noise 1.9 µA rms. | settling time, measurement window, noise, Table 1-7 | Measured with resistive load and 20 pF cable capacitance |
| Specifications – minimum timing for voltage measurement (Table 1-8) | 26 | 1-16 | Voltage measurement: 5 V → min pulse 105 ns, settling 85 ns; 10 V → min pulse 130 ns, settling 110 ns. Noise 1.4 mV rms both. Min rise/fall recommendations: 30 ns (5 V) / 70 ns (10 V). | Table 1-8, voltage measurement timing | PG mode for 5 V, Fast IV for 10 V |
| Accessories and Options | 27–28 | 1-17 to 1-18 | Furnished accessories: 2× B1531A RSU, sync cable, CD, manual. Options table (Table 1-9): cable sets (B1530A-001 to -005), learning kit (-0KN), replacement cables (16493R-001 to -006), SSMC short-open cables (-101/-102), SMA-SSMC cables (-202), SMA-SMA cables (-302), adapter (-801), magnet stand (-802), sync cable (-803). | B1530A-0KN, 16493R, magnet stand | — |

### Chapter 2 — Installation (PDF 29–46)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 2 title page | 29 | — | "2 Installation" divider. | — | — |
| Chapter intro | 30 | 2-2 | Overview of installation topics. Table 2-1 lists recommended tools (torque wrenches 8710-1582/1765, open-end wrenches 5185-2174/5188-4367). | torque wrench, open-end wrench | CAUTION: Use torque/open-end wrench for RF connectors. Use cable ties carefully. |
| RF Probes | 31 | 2-3 | RF measurement system for 3-terminal MOSFET (source/well shorted). Two RF probes: gate and drain. Signal line contacts gate/drain pad; ground lines contact source/well. Figure 2-1 (Cascade Microtech probes), Figure 2-2 (contact pad layout). | RF probe, MOSFET, gate, drain, source/well, GSG | — |
| DC Probes | 32 | 2-4 | DC probes for standard DC contact pads. Four probes needed (gate, drain, source, well) plus three SSMC short-open cables (16493R-101/102). Figure 2-3 shows connections. | DC probe, SSMC, 16493R-101, 16493R-102 | — |
| To Connect Measurement Cables – overview | 33 | 2-5 | Instructions overview. B1500A must be OFF and power cable disconnected during cable work. Notes: unused channels can be open (pass self-test, skip self-cal, but controlling causes error). All cables should be tied together to reduce noise. | cable connection, noise reduction | CAUTION: B1500A must be OFF |
| Connecting RSU | 34–38 | 2-6 to 2-10 | Detailed RSU-to-WGFMU cabling procedure. Table 2-2: connection example with 3 RSUs across 2 WGFMUs, showing cable routing, sync cable between slots 1 and 2, and SMU connections. Required accessories listed. Procedure: mount adapter, set RSU position, connect D-sub/triax cables, connect WGFMU-to-RSU, optional SMU triax, sync cable between master/slave. Figures 2-4 (magnet stand dims) and 2-5 (adapter dims with mounting hole layout). | D-sub, triax, 16493R-801 adapter, 16495H/J/K, magnet stand, master/slave | Master = lower slot. CAUTION: Sync Out/In must be connected correctly. |
| Connecting RF Probes | 39 | 2-11 | RF probe connection: two 16493R-302 SMA-SMA cables. Connect RSU1→Drain probe, RSU2→Gate probe. Figure 2-6. | 16493R-302, SMA-SMA | Use torque/open-end wrench |
| Connecting DC Probes | 40–41 | 2-12 to 2-13 | DC probe connection: two 16493R-202 SMA-SSMC cables + three 16493R-101/102 SSMC short-open cables. Detailed 5-step procedure: (1) Gate↔Well short-open, (2) Drain↔Source short-open, (3) Well↔Source short-open, (4) RSU1→Drain via SMA-SSMC, (5) RSU2→Gate via SMA-SSMC. Figure 2-7, 2-8 (SSMC cable internal connection). | 16493R-202, SMA-SSMC, current return path | Black sleeve plug orientation matters |
| To Perform Self-Test | 42 | 2-14 | Power-on self-test procedure: open terminals → connect power → turn on B1500A → EasyEXPERT start → Configuration → Module tab → verify PASS. Requires EasyEXPERT A.03.20+. | self-test, EasyEXPERT, power-on | Contact Agilent if self-test fails |
| To Install Instrument Library | 43–46 | 2-15 to 2-18 | System requirements: Windows XP SP2 or Vista Business 32-bit, .NET 2.0+, Agilent 82350B GPIB + IO Library Suite 15.0+, Visual Studio 2005+. Installation flow: GPIB interface → IO Library → programming software → B1530A Instrument Library CD. **Before Programming**: terminate EasyEXPERT, configure Connection Expert (GPIB address, System Controller=No, Auto-discover=No), reboot if changed. Start EasyEXPERT button must remain on screen for remote control. | GPIB, 82350B, IO Library Suite, Visual Studio, wgfmu.h, wgfmu.lib | System Controller must be "No". Start EasyEXPERT service must be running. |

### Chapter 3 — Using Instrument Library (PDF 47–76)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 3 title page | 47 | — | "3 Using Instrument Library" divider. | — | — |
| Chapter intro | 48 | 3-2 | Overview. References to Programming Overview, Examples, DC Measurement sections. | — | CAUTION: Connect RSU-WGFMU cable before power-on. Perform self-cal before measurement. |
| Programming Overview | 49–51 | 3-3 to 3-5 | **Core execution flow** (Table 3-1): (1) create pattern data, (2) define events (measure/range/trigger), (3) create sequences (addSequence), (4) open session, (5) set measurement conditions, (6) connect channels, (7) execute, (8) disconnect, (9) close session. Offline vs online distinction. Table 3-2: pattern creation functions (createPattern, addVector, setVector, createMergedPattern, etc.). Table 3-3: event functions (setMeasureEvent, setRangeEvent, setTriggerOutEvent). Table 3-4: measurement setup flow (setOperationMode → setForceVoltageRange → setMeasureEnabled → setMeasureMode → setMeasureCurrentRange → getMeasureValues). Table 3-5: utility functions (update, abort, getChannelIds, doSelfCalibration, exportAscii). | WGFMU_openSession, WGFMU_execute, WGFMU_createPattern, WGFMU_addVector, WGFMU_setMeasureEvent, WGFMU_addSequence, offline/online | exportAscii creates CSV for offline verification of waveform/timing before connecting hardware |
| Programming Examples – summary | 52 | 3-6 | Table 3-6: summary of 11 examples. Ex1: waveform output. Ex2: + sampling. Ex3–5: error handling variants. Ex6: two-channel. Ex7–8: data retrieval variants. Ex9: Id-Vg measurement. Ex10: SMU DC bias. Ex11: SMU sampling. | Examples 1–11 | — |
| To Create Your Project Template | 53–56 | 3-7 to 3-10 | Visual C++ project template setup: include paths (wgfmu.h, VISA headers), library paths (wgfmu.lib, visa32.lib). Table 3-7: complete template code with `checkError`, `checkError2`, `checkError3` error-handling helpers, `writeResults`/`writeResults2`/`writeResults3` data-saving helpers. | wgfmu.h, wgfmu.lib, visa32.lib, checkError, writeResults | visa32.lib optional (needed for Examples 10–11 only) |
| To Create Measurement Program | 57 | 3-11 | 8-step procedure for creating a measurement program from the project template: (1) plan measurements—device type, parameters (hFE, Vth, sheet resistance), waveform type (pulse/ALWG/DC), measurement conditions (V or I, sampling interval, timing); (2) copy template; (3) rename; (4) launch IDE; (5) open project; (6) write main using WGFMU library functions; (7) add display/store/calc; (8) save. | project template, measurement planning, hFE, Vth | Provides workflow guidance before the 11 examples |
| Example 1 – Pulse voltage output | 58–59 | 3-12 to 3-13 | Creates a 1 ms pulse pattern (0→1V→0V, 0.1ms rise, 0.4ms hold, 0.1ms fall, 0.4ms base) repeated 10× on ch101 in Fast IV mode. Figure 3-1 shows waveform. No measurement, no data saving. Demonstrates offline pattern creation → online execution. | WGFMU_createPattern, WGFMU_addVector, WGFMU_addSequence, WGFMU_openSession, WGFMU_execute, WGFMU_waitUntilCompleted | — |
| Example 2 – Pulse + sampling measurement | 60 | 3-14 | Adds `setMeasureEvent` to Example 1: 100 sampling points at 10 µs interval starting at t=0. Saves results to CSV via writeResults. | WGFMU_setMeasureEvent, WGFMU_MEASURE_EVENT_DATA_AVERAGED | — |
| Example 3 – Error handling (checkError) | 61 | 3-15 | Same measurement as Ex2 with try/catch error checking. Demonstrates intentional error (invalid WGFMU_MEASURE_MODE_CURRENT as operation mode) and overwrite warning (duplicate setMeasureEvent). | checkError, try/catch, error handling | Line 18 intentionally causes error for demo |
| Example 4 – Error handling (treatWarningsAsErrors) | 62 | 3-16 | Shows WGFMU_treatWarningsAsErrors(SEVERE) to promote severe warnings to errors. | WGFMU_treatWarningsAsErrors, warning level | — |
| Example 5 – Error handling (error summary) | 63 | 3-17 | Post-execution error summary retrieval using getErrorSummarySize + getErrorSummary. No subprogram dependency. | WGFMU_getErrorSummary, WGFMU_getErrorSummarySize | — |
| Example 6 – Two-channel measurement | 64–66 | 3-18 to 3-20 | Two channels (ch1=101, ch2=102) with constant-voltage patterns "v1" (0.5V) and "v2" (1.0V). Three measurement events on "v2" at different sampling rates: 10 kHz (100 µs interval), 100 kHz (10 µs), 1 MHz (1 µs), each with 32768 points and 10 ns averaging. Channel2 measures current. Figure 3-2 shows waveforms/events. | multi-channel, WGFMU_setMeasureMode(CURRENT), 32768 points, averaging | — |
| Example 7 – Polling channel status | 67 | 3-21 | Replaces waitUntilCompleted with polling loop using getChannelStatus, getMeasureValueSize, getCompletedMeasureEventSize. Demonstrates real-time progress monitoring. | WGFMU_getChannelStatus, WGFMU_getMeasureValueSize, polling | — |
| Example 8 – Event completion check | 68 | 3-22 | Uses isMeasureEventCompleted to wait for specific event ("100kHz") completion. Retrieves partial data using offset/size from the event. | WGFMU_isMeasureEventCompleted, WGFMU_MEASURE_EVENT_COMPLETED, partial data retrieval | — |
| Example 9 – Id-Vg measurement | 69–71 | 3-23 to 3-25 | Full Id-Vg sweep using two WGFMU channels: gate (staircase Vg sweep, 2–3 V, 10 mV steps, 100 ns rise, 500 ns hold) and drain (staircase Vd sweep, 0–10 V, 2 V steps). Measurement events ("Id") set on drain pattern at each Vd step. Polarity parameter controls sweep direction. Exports waveform CSV, saves Id-Vg data per Vd. Figure 3-3. Uses openLogFile. | Id-Vg, staircase sweep, WGFMU_exportAscii, gate/drain, vgStep, vdStep, polarity | Most complex example; demonstrates realistic device characterization |
| Example 10 – SMU DC bias + WGFMU | 72–73 | 3-26 to 3-27 | WGFMU pulse + sampling on ch101 while SMU ch201 applies DC bias (3V). Uses VISA viPrintf for SMU commands (CN, DV, CL). Requires visa32.lib. Error handling with checkError3 (discriminates VISA vs WGFMU errors). | VISA, viPrintf, viOpen, CN, DV, CL, SMU bias, visa32.lib | Requires VISA session alongside WGFMU session |
| Example 11 – SMU sampling + WGFMU | 74–75 | 3-28 to 3-29 | SMU sampling measurement alongside WGFMU. SMU setup: MV (voltage source), MT (sampling timing), MM (measurement mode). Sets timeout to 120s. XE triggers SMU measurement simultaneously with WGFMU_execute. NUB? reads number of SMU data points. | MV, MT, MM, XE, NUB?, SMU sampling, WGFMU_setTimeout(120) | Uses *RST to reset B1500A before setup |
| If You Perform DC Measurement | 76 | 3-30 | DC measurement flow (Table 3-19): openSession → setOperationMode(DC) → connect → dcforceVoltage → dcmeasureValue or dcmeasureAveragedValue → disconnect → closeSession. Simpler than ALWG flow — no pattern/sequence creation needed. | WGFMU_dcforceVoltage, WGFMU_dcmeasureValue, WGFMU_dcmeasureAveragedValue, DC mode | — |

### Chapter 4 — Instrument Library Reference (PDF 77–164)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / Commands / Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 4 title page | 77 | — | "4 Instrument Library Reference" divider. | — | — |
| Chapter intro + function summary | 78–84 | 4-2 to 4-8 | Complete function classification table (Table 4-1) organized by group: Common-Initialize, Common-Error/Warning, Common-Setup, Common-Measurement, WGFMU-Initialize, WGFMU-Setup-Pattern, WGFMU-Setup-Pattern operation, WGFMU-Setup-Event, WGFMU-Setup-Sequence, WGFMU-Setup check-Pattern, WGFMU-Setup check-Sequence, WGFMU-Setup check-Event, WGFMU-Measurement, WGFMU-Data retrieve, WGFMU-Export, DC-Measurement. NOTE on function naming: C++ uses `WGFMU_name`, C# uses `WGFMU.name`, HTBasic uses `Wm_name`. | Table 4-1, function groups, WGFMU_, WGFMU., Wm_ | — |
| Function Reference (alphabetical) | 85–141 | 4-9 to 4-65 | Complete alphabetical reference for all ~50 API functions. Each entry has: description, syntax (C++), HTBasic syntax, parameters with types/ranges, example code, and remarks/notes. See detailed breakdown in sub-rows below. | — | — |
| — WGFMU_abort / abortChannel | 85 | 4-9 | Stops sequencer of all/specified channels. Channels keep last output voltage after abort. | WGFMU_abort, WGFMU_abortChannel | — |
| — WGFMU_addSequence / addSequences | 85–87 | 4-9 to 4-11 | Adds pattern+count to channel's sequence. Count range: 1 to 1,099,511,627,776 (~10^12). Non-integer count rounded to nearest integer. **Timing**: between repeats of same sequence: NO delay. Between different sequences in series: 50 ns delay (10 ns outputting last voltage of previous + 40 ns outputting initial voltage of next). HTBasic `Wm_addsequence`/`Wm_addsequences` with `slength` parameter. VB6 requires VarPtrStringArray. | addSequence, addSequences, 50 ns inter-sequence delay, 10^12 loops | Inter-sequence 50 ns delay is critical for timing calculations in stress-measure patterns |
| — WGFMU_addVector / addVectors | 88–89 | 4-12 to 4-13 | Appends vector(s) to pattern. dTime is incremental (10 ns to 10995 s, 10 ns resolution). Rounding to nearest 10 ns. | addVector, addVectors, dTime, incremental time | — |
| — WGFMU_clear | 90 | 4-14 | Clears all software setup (patterns, sequences, errors, warnings). Does NOT change hardware state. | WGFMU_clear | — |
| — WGFMU_closeLogFile / closeSession | 90 | 4-14 | Closes log file or GPIB session. | closeLogFile, closeSession | — |
| — WGFMU_connect / disconnect | 91, 96 | 4-15, 4-21 | Enables/disables WGFMU channel + RSU. | WGFMU_connect, WGFMU_disconnect | — |
| — WGFMU_createMergedPattern | 91–92 | 4-15 to 4-16 | Merges two patterns: AXIS_TIME (concatenate) or AXIS_VOLTAGE (add voltages). For AXIS_VOLTAGE, pattern2 events overwrite pattern1 events of same type in same time frame. | createMergedPattern, WGFMU_AXIS_TIME, WGFMU_AXIS_VOLTAGE | Event overwrite behavior is non-obvious |
| — WGFMU_createMultipliedPattern | 92–93 | 4-16 to 4-17 | Copies and scales pattern by factorT (time) and factorV (voltage). Event attributes time/interval/avgTime scaled by factorT; measPts unchanged. Negative factorT creates time-reversed (line-symmetric) pattern with recalculated measurement times. | createMultipliedPattern, factorT, factorV, time reversal | Negative factorT formula: newTime = period − time − interval×(pts−1) − avgTime |
| — WGFMU_createOffsetPattern | 93–94 | 4-17 to 4-18 | Copies pattern with time/voltage offset. Positive offsetT inserts initial-voltage vector at start. Negative offsetT trims beginning. Event attribute time shifted by offsetT. | createOffsetPattern, offsetT, offsetV | — |
| — WGFMU_createPattern | 94 | 4-18 | Creates new named pattern with initial voltage at t=0. | createPattern, initV | Pattern names must be unique |
| — WGFMU_dcforceVoltage | 95 | 4-19 | DC voltage output (DC mode only). Applies setup of setOperationMode, setForceVoltageRange, setMeasureCurrentRange, setMeasureVoltageRange, setMeasureMode. | dcforceVoltage | DC mode only |
| — WGFMU_dcmeasureAveragedValue | 95–96 | 4-19 to 4-20 | DC averaged measurement: points (1–65535), interval (1–65535, ×5 ns). Returns averaged V or I. DC mode only. | dcmeasureAveragedValue, points, interval, 5 ns | — |
| — WGFMU_dcmeasureValue | 96 | 4-20 | Single-point DC measurement returning V or A. DC mode only. | dcmeasureValue | — |
| — WGFMU_doSelfCalibration | 97 | 4-21 | Self-calibration for mainframe + all modules. Returns bitmask result (0=pass, 2^(N−1)=slot N fail, 1024=mainframe fail) + detail string. | doSelfCalibration, bitmask | — |
| — WGFMU_doSelfTest | 98 | 4-22 | Self-test with same result format as doSelfCalibration. | doSelfTest | — |
| — WGFMU_execute | 99 | 4-23 | Runs sequencer on all enabled channels (Fast IV or PG). If channels already running, stops and restarts. Applies pending setup. Channels keep last voltage after completion. | WGFMU_execute | — |
| — WGFMU_exportAscii | 99–100 | 4-23 to 4-24 | Exports setup summary (pattern data, event data, sequence data) to CSV file. Useful for offline waveform/timing verification before running hardware. Figure 4-1 shows example output (garbled in PDF OCR). | exportAscii, CSV, debugging | — |
| — WGFMU_getChannelIds / getChannelIdSize | 101 | 4-25 | Reads installed WGFMU channel IDs from connected B1500A. | getChannelIds, getChannelIdSize | — |
| — WGFMU_getChannelStatus | 101–102 | 4-25 to 4-26 | Returns status (Table 4-17), elapsed time, total time for a channel. | getChannelStatus, elapsedTime, totalTime | — |
| — WGFMU_getCompletedMeasureEventSize | 102 | 4-26 | Returns completed and total measurement event counts. | getCompletedMeasureEventSize | — |
| — WGFMU_getError / getErrorSize | 103 | 4-27 | Reads next error string (FIFO). Cleared by WGFMU_clear. | getError, getErrorSize | — |
| — WGFMU_getErrorSummary / getErrorSummarySize | 104 | 4-28 | Reads all accumulated errors as single string. | getErrorSummary, getErrorSummarySize | — |
| — WGFMU_getForceDelay / setForceDelay | 105, 128 | 4-29, 4-52 | Device delay for source channel: −50 ns to +50 ns, 625 ps resolution. | ForceDelay, 625 ps | — |
| — WGFMU_getForceValue / getForceValues / getForceValueSize | 105–107 | 4-29 to 4-31 | Reads setup (time, voltage) from sequence data by index or range. | getForceValue, getForceValues, getForceValueSize | — |
| — WGFMU_getForceVoltageRange / setForceVoltageRange | 107, 128 | 4-31, 4-53 | Gets/sets voltage output range. See Table 4-6 for constants. | ForceVoltageRange, auto/3V/5V/10V_NEG/10V_POS | Auto range is default |
| — WGFMU_getInterpolatedForceValue | 107–108 | 4-31 to 4-32 | Returns interpolated output voltage at arbitrary time. Useful for correlating measurement data with applied voltage. | getInterpolatedForceValue, interpolation | Used in writeResults3 helper |
| — WGFMU_getMeasureCurrentRange / setMeasureCurrentRange | 108, 129 | 4-32, 4-53 | Gets/sets current measurement range. See Table 4-9: 1 µA, 10 µA, 100 µA, 1 mA, 10 mA (default). | MeasureCurrentRange, 1µA–10mA | Not effective in voltage measurement mode |
| — WGFMU_getMeasureDelay / setMeasureDelay | 108–109, 129 | 4-33, 4-53 | Device delay for measurement channel: −50 ns to +50 ns, 625 ps resolution. | MeasureDelay, 625 ps | — |
| — WGFMU_getMeasureEvent / getMeasureEvents / getMeasureEventSize | 109–113 | 4-33 to 4-37 | Reads measurement event setup: pattern name, event name, cycle, loop, count, index, length. getMeasureEventAttribute reads the raw setMeasureEvent parameters (time, points, interval, average, rdata). | getMeasureEvent, getMeasureEventAttribute | — |
| — WGFMU_getMeasureMode / setMeasureMode | 114, 131–132 | 4-38, 4-56 | Gets/sets voltage or current measurement mode. See Table 4-7. Changing to current mode auto-sets voltage range to 5 V. | MeasureMode, VOLTAGE, CURRENT | Current mode forces 5 V voltage range |
| — WGFMU_getMeasureTime(s) / getMeasureTimeSize | 114–116 | 4-38 to 4-40 | Reads measurement start times from sequence for a channel. | getMeasureTime, getMeasureTimes, getMeasureTimeSize | — |
| — WGFMU_getMeasureValue / getMeasureValues / getMeasureValueSize | 116–118 | 4-40 to 4-42 | Reads actual measurement data (time + V or I). getMeasureValueSize returns measured count and total count. | getMeasureValue, getMeasureValues, getMeasureValueSize | — |
| — WGFMU_getMeasureVoltageRange / setMeasureVoltageRange | 118, 132 | 4-42, 4-56 | Gets/sets voltage measurement range. See Table 4-8: 5 V or 10 V (default). | MeasureVoltageRange, 5V, 10V | Not effective in current measurement mode |
| — WGFMU_getOperationMode / setOperationMode | 119, 133 | 4-43, 4-57 | Gets/sets operation mode. See Table 4-5: DC (2000), Fast IV (2001), PG (2002), SMU (2003, default). Fast IV: VFIM or VFVM. PG: VFVM only, 50 Ω divider. | OperationMode, DC, FASTIV, PG, SMU | SMU mode is default |
| — WGFMU_getPatternForceValue(s) / getPatternForceValueSize | 119–121 | 4-43 to 4-45 | Reads pattern-level setup data (time, voltage). Pattern-level (vs channel/sequence-level). | getPatternForceValue, pattern-level | — |
| — WGFMU_getPatternInterpolatedForceValue | 121 | 4-45 | Reads interpolated pattern voltage at specified time. | getPatternInterpolatedForceValue | — |
| — WGFMU_getPatternMeasureTime(s) / getPatternMeasureTimeSize | 121–123 | 4-45 to 4-47 | Reads pattern-level measurement start times. | getPatternMeasureTime | — |
| — WGFMU_getStatus | 123 | 4-47 | Returns overall WGFMU status (not per-channel). | getStatus | — |
| — WGFMU_getTriggerOutMode / setTriggerOutMode | 124, 136 | 4-48, 4-60 | Gets/sets trigger output mode and polarity. See Table 4-11: DISABLE, START_EXECUTION, START_SEQUENCE, START_PATTERN, EVENT. Polarity: POSITIVE or NEGATIVE. | TriggerOutMode, trigger polarity | — |
| — WGFMU_getWarningLevel / setWarningLevel | 124, 139 | 4-48, 4-63 | Gets/sets warning reporting level. See Table 4-4: OFF, SEVERE, NORMAL (default), INFORMATION. | WarningLevel | — |
| — WGFMU_getWarningSummary / getWarningSummarySize | 124–125 | 4-48 to 4-49 | Reads all warnings as single string. | getWarningSummary | — |
| — WGFMU_initialize | 125 | 4-49 | Resets all WGFMU channels. | WGFMU_initialize | — |
| — WGFMU_isMeasureEnabled / setMeasureEnabled | 126, 130 | 4-50, 4-54 | Checks/sets whether a channel can perform measurement. DISABLE prevents measurement even if pattern has events. Not available for DC mode. | MeasureEnabled, ENABLE, DISABLE | — |
| — WGFMU_isMeasureEventCompleted | 126–127 | 4-50 to 4-51 | Checks specific event completion. Returns complete flag, measId, index, size. | isMeasureEventCompleted | — |
| — WGFMU_openLogFile / closeLogFile | 127, 90 | 4-51, 4-14 | Opens/closes file for logging errors and warnings. | openLogFile | — |
| — WGFMU_openSession / closeSession | 128, 90 | 4-52, 4-14 | Opens/closes GPIB session. Address format: "GPIB0::17::INSTR". | openSession, GPIB address | — |
| — WGFMU_setMeasureEvent | 130–131 | 4-54 to 4-56 | **Key function**. Syntax: `setMeasureEvent(pattern, event, time, points, interval, average, rdata)`. Defines sampling measurement on a pattern. **time**: start time relative to pattern origin, 10 ns resolution. **points**: number of sampling points (positive integer). **interval**: 10 ns to 1.34217728 s, 10 ns resolution. **average**: 0 (no avg, uses 10 ns internally) or 10 ns to 0.020971512 s (~20 ms), 10 ns resolution; must not exceed interval. **rdata**: AVERAGED (12000, returns `points` data) or RAW (12001, returns `points×(1+int(average/5ns))` data). **eventEndTime** = time + interval×(points−1) + average (add 10 ns if average=0). Time/eventEndTime must be within pattern period. Event names are NOT unique — same name can be reused across patterns/events. During averaging, hardware samples at 5 ns intervals; reported time = (time + time+average)/2. Values not multiples of 10 ns are rounded to nearest 10 ns. | setMeasureEvent, interval, average, RAW, AVERAGED, eventEndTime, 5 ns internal sampling | ≥100 ns between events that change averaging (else runtime error). ~4M hardware data point limit per channel (typical). RAW mode can inflate data volume dramatically. |
| — WGFMU_setRangeEvent | 133–134 | 4-57 to 4-58 | Defines range change event during pattern output. Fast IV current measurement only. Time in 10 ns resolution. For ≥3 consecutive range changes: ≥2 µs between events. Range event must be outside averaging period of measurement events. | setRangeEvent, range change | ≥2 µs between 3+ consecutive range changes |
| — WGFMU_setTimeout | 134–135 | 4-58 to 4-59 | Sets session timeout (≥1 s, 1 s resolution, default 100 s). Auto-increases to 600 s for self-cal/self-test. Timeout occurs if GPIB address is wrong or operation takes too long. | setTimeout, 100 s default | — |
| — WGFMU_setTriggerOutEvent | 135–136 | 4-59 to 4-60 | Defines event trigger output on a pattern. Requires EVENT trigger mode. time=duration=0 outputs trigger at pattern initial voltage. | setTriggerOutEvent, duration | — |
| — WGFMU_setVector / setVectors | 137–138 | 4-61 to 4-62 | Like addVector but uses absolute time (not incremental). Can replace existing vector at same time. time=0 replaces initial voltage. | setVector, setVectors, absolute time | — |
| — WGFMU_treatWarningsAsErrors | 139 | 4-63 | Sets which warning levels are promoted to errors. OFF=none, SEVERE=severe only, NORMAL=normal+severe, INFORMATION=all. | treatWarningsAsErrors | — |
| — WGFMU_update / updateChannel | 140 | 4-64 | Applies pending setup and outputs initial voltage from createPattern. Updates all or specified channel. | update, updateChannel | — |
| — WGFMU_waitUntilCompleted | 141 | 4-65 | Blocks until all connected channels finish and data is ready. Error if no sequencer running or no Fast IV/PG channel. | waitUntilCompleted | — |
| Parameters (constant tables) | 142–151 | 4-66 to 4-75 | Tables 4-2 through 4-14. See detailed breakdown below. | — | — |
| — Table 4-2: Output Voltage ranges | 142 | 4-66 | Voltage ranges per mode: PG (3V: ±3V/96µV, 5V: ±5V/160µV), Fast IV (3V, 5V, −10V, +10V all 160µV except 3V), DC (same as Fast IV). | voltage range, resolution | — |
| — Table 4-3: Channel Numbers | 142–143 | 4-67 | chanId 101–1002: slot 1 Ch1=101, Ch2=102, ..., slot 10 Ch1=1001, Ch2=1002. | chanId, slot mapping | — |
| — Table 4-4: Warning Levels | 144 | 4-68 | OFF (1000), SEVERE (1001), NORMAL (1002, default for setWarningLevel), INFORMATION (1003). Describes what each level reports. | warning level constants | — |
| — Table 4-5: Operation Modes | 145 | 4-69 | DC (2000), FASTIV (2001), PG (2002), SMU (2003, default). SMU mode prohibits most measurement functions. | operation mode constants | — |
| — Table 4-6: Force Voltage Ranges | 146 | 4-70 | AUTO (3000, default), 3V (3001), 5V (3002), −10V (3003, Fast IV/DC only), +10V (3004, Fast IV/DC only). | force voltage range constants | ±10V ranges not available in PG mode |
| — Table 4-7: Measure Modes | 147 | 4-71 | VOLTAGE (4000, default), CURRENT (4001, Fast IV/DC only). Current mode forces voltage range to 5V. | measure mode constants | — |
| — Table 4-8: Measure Voltage Ranges | 147 | 4-71 | 5V (5001), 10V (5002, default). | measure voltage range constants | — |
| — Table 4-9: Measure Current Ranges | 148 | 4-72 | 1µA (6001), 10µA (6002), 100µA (6003), 1mA (6004), 10mA (6005, default). | measure current range constants | — |
| — Table 4-10: Measure Enabled | 149 | 4-73 | DISABLE (7000), ENABLE (7001, default). | measure enabled constants | — |
| — Table 4-11: Trigger Out Mode/Polarity | 149 | 4-73 | DISABLE (8000, default), START_EXECUTION (8001), START_SEQUENCE (8002), START_PATTERN (8003), EVENT (8004). Polarity: POSITIVE (8100, default), NEGATIVE (8101). | trigger mode constants | — |
| — Table 4-12: createMergedPattern direction | 150 | 4-74 | AXIS_TIME (9000): concatenate patterns. AXIS_VOLTAGE (9001): add voltage values. | merge direction constants | — |
| — Table 4-13: isMeasureEventCompleted | 151 | 4-75 | NOT_COMPLETED (11000), COMPLETED (11001). | event completion constants | — |
| — Table 4-14: setMeasureEvent rdata | 151 | 4-75 | AVERAGED (12000): returns `points` data. RAW (12001): returns `points × (1 + int(average/5ns))` data. | rdata, AVERAGED, RAW | RAW mode significantly increases data volume |
| Channel Execution Status | 152 | 4-76 | Explains how to monitor running sequences using getChannelStatus, getCompletedMeasureEventSize, getMeasureValueSize. Table 4-15 example: 3 sequences with different patterns/counts showing how total time, events, and points accumulate. 50 ns required between sequences. | channel status monitoring, Table 4-15 | — |
| WGFMU Setup Functions | 153 | 4-77 | Explains two-level parameter validation: (1) lowest-limit check at function call time, (2) highest-limit check at execute/exportAscii/update time. | parameter validation, setup check | — |
| Return Codes | 154–157 | 4-78 to 4-81 | Table 4-16: self-test/cal return (PASS=0, FAIL=1). Table 4-17: status codes (COMPLETED=10000, DONE=10001, RUNNING=10002, ABORT_COMPLETED=10003, ABORTED=10004, RUNNING_ILLEGAL=10005, IDLE=10006). Table 4-18: error codes (0=NO_ERROR, −1 to −15: PARAMETER_OUT_OF_RANGE, ILLEGAL_STRING, CONTEXT, FUNCTION_NOT_SUPPORTED, COMMUNICATION, FW, LIBRARY, ERROR, CHANNEL_NOT_FOUND, PATTERN_NOT_FOUND, EVENT_NOT_FOUND, PATTERN_ALREADY_EXISTS, SEQUENCER_NOT_RUNNING, RESULT_NOT_READY, RESULT_OUT_OF_DATE). Reserved codes: 0 to −9999. | status codes, error codes, WGFMU_NO_ERROR | RUNNING_ILLEGAL: setup changed during run, no data readable. IDLE: no data readable. |
| Error Messages – Operation Errors | 158–160 | 4-82 to 4-84 | Firmware error codes 3000–3327: module not found (3000), RSU not connected (3001), data corrupted (3015), memory overflow (3050), FIFO overflow (3051, caused by frequent averaging changes), range change error (3052, interval too short), sequence/waveform not ready (3201–3202), voltage limit (3301/3310), invalid range (3302), invalid mode for current meas (3303), ALWG data size limits (3304–3309), interval time limit (3311: 10 ns to 10995.116 s), measurement interval (3312: 10 ns to 1.342 s), invalid instruction codes (3313–3314), averaging time limit (3315: 0 or 10 ns to 20.972 ms), averaging > interval (3316), slot/channel invalid (3317–3318), delay limits (3319–3320: ±50 ns / 625 ps), mode/range invalid (3321–3323), WGMA?/WGMB? query size (3324), spot measurement count/interval/mode (3325–3327: DC mode only, reveals WGMS? command). | error codes 3000–3327, WGMS?, WGMA?, WGMB? | Errors 3324–3327 reveal undocumented low-level commands (WGMS?, WGMA?, WGMB?) used internally by the library |
| Error Messages – Self-test/Calibration Errors | 161–164 | 4-85 to 4-88 | Firmware error codes: **Init/EEPROM (3002–3014)**: initialization failure, FPGA not configured, CRC errors for system timing/DAC DCM/ADC DCM/DAC clock edge/ADC clock edge/DAC level cal/ADC level cal/DAC skew cal/ADC skew cal/RSU cal data, invalid EEPROM type. **Self-test (3400–3489)**: module TEST FAIL (3400), digital H/W (3401), CPLD (3402), FPGA config (3403), FPGA1/2 access (3404–3405), DCM clocks (3406–3413), FPGA communication (3414), CONVEND interrupt (3415), 10 MHz clock (3416), SYNC pins (3417–3419), IDELAY (3420), SDRAM Ch1/Ch2 (3421–3422), EEPROM access (3423–3425), EEPROM CRC (3426–3441), EEPROM data (3450–3452), DAC/ADC tests (3460–3465), frame config (3480–3482), PLL slave (3483), sync/reference/interrupt lines (3484–3489). **Emergency (3490)**. **Calibration (3500–3508)**: general cal fail, ADC gain, CMR, IM offset, VM offset, VF gain, VF offset, reference ADC missing, cable length cal. | self-test 3400–3489, calibration 3500–3508, FPGA, EEPROM, DAC, ADC, CRC, DCM, PLL | Last page of manual (PDF 164) |

---

## Page To Content Map

| PDF Page(s) | Printed Page(s) | Section / Topic | What is explained there | Keywords / Commands / Concepts |
|---|---|---|---|---|
| 1 | — | Title page | Agilent B1530A WGFMU User's Guide cover. | B1530A |
| 2 | — | Notices | Copyright, warranty, legal. Edition 5, Aug 2012. | B1530-90000 |
| 3 | — | WEEE / servicing | Product disposal; servicing requires B1500A + all modules + RSU + cables. | 16493R, servicing |
| 4 | — | In This Manual | Four-chapter summary. NOTE: WGFMU not supported by EasyEXPERT Classic Test. | EasyEXPERT |
| 5–8 | — | Table of Contents (part 1) | TOC for all chapters including detailed function listing for Ch4. | — |
| 9–10 | — | Table of Contents (part 2) / blank | End of TOC, blank page 10. | — |
| 11 | — | Ch 1 title | "1 Introduction" divider page. | — |
| 12 | 1-2 | Ch 1 intro | Chapter overview, Table 1-1 (control platforms), note on library-based control. | EasyEXPERT, Instrument Library |
| 13–14 | 1-3 to 1-4 | Overview | WGFMU product overview: ALWG + fast IV, two modes (Fast IV, PG), spec highlights, circuit diagram. No compliance feature. | ALWG, Fast IV, PG, 5 ns, 50 Ω |
| 15–16 | 1-5 to 1-6 | WGFMU connector panel | Physical terminals: Ch1/Ch2, Sync Out/In, TrigOut. Module limit (5 per B1500A). Trigger modes and specifications. | Sync, TrigOut, master/slave, TTL |
| 17–18 | 1-7 to 1-8 | RSU (B1531A) | RSU terminals (Output, From SMU, V Monitor, From B1530A). Switching, V Monitor 1/10 buffered output. | RSU, B1531A, V Monitor, ±25V |
| 19 | 1-9 | Spec conditions + general | Environmental conditions, calibration period, load capacitance limit, physical dimensions. | 23°C±5°C, 25 pF, self-cal |
| 20–22 | 1-10 to 1-12 | Detailed specifications | Mode/function matrix (Table 1-2), RSU specs (50 Ω source, SMA, ±25 V/±100 mA SMU path), V Monitor (BNC, 1/10 into 50 Ω), cable lengths (1.5/3/5 m or adapter combos), ALWG+trigger (TTL, 10 ns), software (library + NBTI app tests + RTS sample), prober vendors, RF EMF sensitivity. Supplemental: jitter <1 ns, inter-channel skew <3 ns (no ESD), trigger skew <3 ns, range change time <150 µs, RSU leakage <100 pA, residual R <300 mΩ. | Table 1-2, jitter <1ns, skew <3ns, RF EMF, NBTI, RTS |
| 23 | 1-13 | V force specs (Table 1-3) | Voltage force accuracy, resolution, overshoot, rise/fall time, pulse period/width minimums. | accuracy, overshoot, rise time |
| 24 | 1-14 | V/I meas + ALWG specs (Tables 1-4/5/6) | V meas: ±(0.1% rdg + 0.1% range), 680 µV/1.4 mV resolution, 4 mVrms noise. I meas: ±(0.1% rdg + 0.2% range), 0.014% range resolution. Accuracy requires 10,000 or 100,000 averaging samples. ALWG: 2048 vectors, 512 sequences, 10^12 loops, 10 ns–10000 s vectors, 5 ns or 10 ns–1 s sampling, 10 ns–20 ms averaging, ~4M points/ch (typical). | 2048 vectors, 4M points (typical), accuracy conditions |
| 25 | 1-15 | Current meas timing (Table 1-7) | Settling times, min pulse widths, min meas windows, noise for 100 nA–10 mA (DUT current) on ranges 1 µA–10 mA. Measured with resistive load + 20 pF cable cap, 10 V applied, 10 mA force range, separate sense channel at 0 V. Key: 10 mA → 145 ns pulse, 125 ns settle; 100 nA → 47 µs pulse, 37 µs settle. | settling time, meas window, 20 pF |
| 26 | 1-16 | Voltage meas timing (Table 1-8) | 5 V: settle 85 ns, min window 20 ns, min pulse 105 ns, noise 1.4 mV, min rise/fall 30 ns (PG mode). 10 V: settle 110 ns, min pulse 130 ns, noise 1.4 mV, min rise/fall 70 ns (Fast IV). Measured with 1 kΩ–10 MΩ load, 20 pF cable cap, same channel force+measure. | voltage meas timing, 20 pF, settle |
| 27–28 | 1-17 to 1-18 | Accessories and Options (Table 1-9) | Full options/accessories list with model numbers. | B1530A-001 to -005, 16493R |
| 29 | — | Ch 2 title | "2 Installation" divider page. | — |
| 30 | 2-2 | Ch 2 intro | Installation overview, recommended tools table. | torque wrench |
| 31 | 2-3 | RF Probes | RF probe system for 3-terminal MOSFET, probe layout, ground/signal assignment. | RF probe, GSG |
| 32 | 2-4 | DC Probes | DC probe system for 4-pad MOSFET, SSMC short-open cables for current return paths. | DC probe, SSMC |
| 33 | 2-5 | Cable connection overview | Safety (B1500A OFF), unused channels, noise reduction. | — |
| 34–38 | 2-6 to 2-10 | Connecting RSU | Full cabling procedure, connection example (Table 2-2), adapter/plate mounting, magnet stand dimensions. | RSU cabling, adapter, D-sub |
| 39 | 2-11 | Connecting RF Probes | RF probe SMA-SMA cable connections. | SMA-SMA, 16493R-302 |
| 40–41 | 2-12 to 2-13 | Connecting DC Probes | DC probe SSMC cable connections, 5-step procedure, SSMC cable internal diagram. | SMA-SSMC, 16493R-202 |
| 42 | 2-14 | Self-Test procedure | Power-on self-test via EasyEXPERT A.03.20+. | self-test, EasyEXPERT |
| 43–46 | 2-15 to 2-18 | Install Instrument Library | System requirements, installation flow, GPIB configuration, Before Programming checklist. | GPIB, IO Library, wgfmu.h |
| 47 | — | Ch 3 title | "3 Using Instrument Library" divider page. | — |
| 48 | 3-2 | Ch 3 intro | Chapter overview, safety notes. | — |
| 49–51 | 3-3 to 3-5 | Programming Overview | Core 9-step execution flow (Tables 3-1 to 3-5). Pattern creation, event definition, sequence building, online execution, data retrieval. | execution flow, offline/online |
| 52 | 3-6 | Programming Examples summary | Table 3-6: overview of 11 examples. | Examples 1–11 |
| 53–56 | 3-7 to 3-10 | Project Template | Visual C++ project setup, include/lib paths, error handling and data-saving helper functions. | wgfmu.h, wgfmu.lib, template |
| 57 | 3-11 | To Create Measurement Program | 8-step workflow for building measurement programs from project template. Covers planning (device, parameters, waveform, conditions). | project template, measurement planning |
| 58–59 | 3-12 to 3-13 | Example 1 | Pulse voltage output (1 ms pulse, 0→1V→0V, 10 repeats, ch101, Fast IV). No template subprograms needed. | pulse, addVector, addSequence |
| 60 | 3-14 | Example 2 | Pulse + 100-point sampling measurement + CSV save. | setMeasureEvent, sampling |
| 61 | 3-15 | Example 3 | Error handling with checkError/try-catch. | checkError, error demo |
| 62 | 3-16 | Example 4 | Warning-to-error promotion with treatWarningsAsErrors. | treatWarningsAsErrors |
| 63 | 3-17 | Example 5 | Post-execution error summary retrieval. | getErrorSummary |
| 64–66 | 3-18 to 3-20 | Example 6 | Two-channel constant voltage + 3 sampling events at 10kHz/100kHz/1MHz. | multi-channel, 32768 pts |
| 67 | 3-21 | Example 7 | Polling loop replacing waitUntilCompleted. | getChannelStatus, polling |
| 68 | 3-22 | Example 8 | Event-specific completion check + partial data retrieval. | isMeasureEventCompleted |
| 69–71 | 3-23 to 3-25 | Example 9 | **Full Id-Vg measurement**: gate staircase Vg (2–3V, 10mV steps), drain Vd (0–10V, 2V steps), polarity parameter, per-Vd data files. | Id-Vg, staircase, polarity |
| 72–73 | 3-26 to 3-27 | Example 10 | WGFMU + SMU DC bias via VISA commands (CN, DV, CL). | SMU bias, VISA, viPrintf |
| 74–75 | 3-28 to 3-29 | Example 11 | WGFMU + SMU sampling via VISA (MV, MT, MM, XE, NUB?). | SMU sampling, VISA |
| 76 | 3-30 | DC Measurement guide | DC measurement flow (Table 3-19): simpler than ALWG — no patterns/sequences. | dcforceVoltage, dcmeasureValue |
| 77 | — | Ch 4 title | "4 Instrument Library Reference" divider page. | — |
| 78–84 | 4-2 to 4-8 | Function summary (Table 4-1) | Complete function classification by group: Common-Initialize, Common-Error/Warning, Common-Setup, Common-Measurement, WGFMU-Setup-Pattern, WGFMU-Setup-Pattern operation, WGFMU-Setup-Event (setMeasureEvent/setRangeEvent/setTriggerOutEvent), WGFMU-Setup-Sequence, WGFMU-Setup check (Pattern/Sequence/Event), WGFMU-Measurement, WGFMU-Data retrieve (value/event), WGFMU-Export, DC-Measurement. Naming: C++ `WGFMU_name`, C# `WGFMU.name`, HTBasic `Wm_name`. | Table 4-1, API groups, ~50 functions |
| 85–87 | 4-9 to 4-11 | abort, addSequence(s) | Stop sequencer; add pattern+count to channel sequence. Inter-sequence 50ns delay. | abort, addSequence, 50ns delay |
| 88–90 | 4-12 to 4-14 | addVector(s), clear, closeLogFile, closeSession | Add vectors to pattern (incremental time); clear setup; close log/session. | addVector, clear |
| 91–94 | 4-15 to 4-18 | connect, createMergedPattern, createMultipliedPattern, createOffsetPattern, createPattern | Enable channel; pattern manipulation (merge/multiply/offset/create). | pattern operations |
| 95–96 | 4-19 to 4-20 | dcforceVoltage, dcmeasureAveragedValue, dcmeasureValue, disconnect | DC force/measure functions; disable channel. | DC functions |
| 97–98 | 4-21 to 4-22 | doSelfCalibration, doSelfTest | Self-cal/test with bitmask result + detail string. | self-cal, self-test |
| 99–100 | 4-23 to 4-24 | execute, exportAscii | Run all enabled channels; export setup to CSV for debugging. | execute, exportAscii |
| 101–102 | 4-25 to 4-26 | getChannelIds/Size, getChannelStatus, getCompletedMeasureEventSize | Channel discovery, status monitoring, event completion tracking. | channel status |
| 103–104 | 4-27 to 4-28 | getError(Size), getErrorSummary(Size) | Error retrieval (single error FIFO and full summary). | error handling |
| 105–108 | 4-29 to 4-32 | getForceDelay, getForceValue(s/Size), getForceVoltageRange, getInterpolatedForceValue, getMeasureCurrentRange | Read force/measure setup parameters. | setup readback |
| 109–113 | 4-33 to 4-37 | getMeasureDelay, getMeasureEvent(s/Size/Attribute) | Read measurement events setup and attributes. | event readback |
| 114–118 | 4-38 to 4-42 | getMeasureMode, getMeasureTime(s/Size), getMeasureValue(s/Size), getMeasureVoltageRange | Read measurement mode, timing, and actual measurement data. | data retrieval |
| 119–123 | 4-43 to 4-47 | getOperationMode, getPatternForceValue(s/Size), getPatternInterpolatedForceValue, getPatternMeasureTime(s/Size), getStatus | Pattern-level readback functions, overall status. | pattern readback |
| 124–127 | 4-48 to 4-51 | getTriggerOutMode, getWarningLevel, getWarningSummary(Size), initialize, isMeasureEnabled, isMeasureEventCompleted, openLogFile | Trigger/warning readback, initialization, measurement enable/event check, logging. | trigger, warning, logging |
| 128–129 | 4-52 to 4-53 | openSession, setForceDelay, setForceVoltageRange, setMeasureCurrentRange, setMeasureDelay | Session open, force/measure setup functions. | setup functions |
| 130–132 | 4-54 to 4-56 | setMeasureEnabled, **setMeasureEvent**, setMeasureMode, setMeasureVoltageRange | Key measurement event definition (timing, points, interval, averaging, data mode). | **setMeasureEvent** |
| 133–136 | 4-57 to 4-60 | setOperationMode, **setRangeEvent**, setTimeout, **setTriggerOutEvent**, setTriggerOutMode | Operation mode, range change events, timeout, trigger events/mode. | setRangeEvent, setTriggerOutEvent |
| 137–139 | 4-61 to 4-63 | setVector(s), setWarningLevel, treatWarningsAsErrors | Absolute-time vector setting, warning configuration. | setVector, absolute time |
| 140–141 | 4-64 to 4-65 | update, updateChannel, waitUntilCompleted | Apply setup to hardware, block until complete. | update, waitUntilCompleted |
| 142 | 4-66 | Table 4-2: Output Voltage | Voltage ranges and resolutions per mode. | voltage table |
| 142–143 | 4-67 | Table 4-3: Channel Numbers | Slot-to-chanId mapping (101–1002). | chanId |
| 144 | 4-68 | Table 4-4: Warning Levels | OFF/SEVERE/NORMAL/INFORMATION constants and behaviors. | warning constants |
| 145 | 4-69 | Table 4-5: Operation Modes | DC/FASTIV/PG/SMU constants. | operation mode constants |
| 146 | 4-70 | Table 4-6: Force Voltage Ranges | AUTO/3V/5V/−10V/+10V constants. | force range constants |
| 147 | 4-71 | Tables 4-7/4-8: Measure Mode/Voltage Range | VOLTAGE/CURRENT; 5V/10V constants. | measure mode/range constants |
| 148 | 4-72 | Table 4-9: Measure Current Ranges | 1µA/10µA/100µA/1mA/10mA constants. | current range constants |
| 149 | 4-73 | Tables 4-10/4-11: Measure Enabled / Trigger Out | ENABLE/DISABLE; trigger modes and polarity constants. | trigger constants |
| 150 | 4-74 | Table 4-12: createMergedPattern direction | AXIS_TIME/AXIS_VOLTAGE constants. | merge constants |
| 151 | 4-75 | Tables 4-13/4-14: Event completion / rdata | COMPLETED/NOT_COMPLETED; AVERAGED/RAW data modes. | event/rdata constants |
| 152 | 4-76 | Channel Execution Status | How to monitor running sequences: getChannelStatus (status + elapsed/total time), getCompletedMeasureEventSize (completed/total events), getMeasureValueSize (completed/total points). Table 4-15 example: 3 sequences with counts 3/1/2, lengths 10/50/20 µs, events 7/6/5, pts/event 5/4/3. Total time = 3×10+50ns+1×50+50ns+2×20 = 120.1 µs. Total events = 37. Total points = 159. 50 ns between sequences. | execution monitoring, Table 4-15, total time calculation |
| 153 | 4-77 | WGFMU Setup Functions | Two-level parameter validation: immediate (lowest) and deferred (highest, at execute/export/update). | parameter validation |
| 154–157 | 4-78 to 4-81 | Return Codes (Tables 4-16/17/18) | Self-test result codes (PASS/FAIL), status codes (COMPLETED through IDLE), error codes (0 to −15). | return codes, error codes |
| 158–160 | 4-82 to 4-84 | Error Messages – Operation | Firmware errors 3000–3327: module/RSU detection (3000–3001), data corruption (3015), memory/FIFO overflow (3050–3051), range change timing (3052), sequence/waveform not ready (3201–3202), voltage/range/timing/mode violations (3301–3327). Reveals hidden internal commands: WGMS? (spot measurement), WGMA?/WGMB? (data queries). | operation errors 3000–3327, WGMS?, WGMA?, WGMB? |
| 161–164 | 4-85 to 4-88 | Error Messages – Self-test/Cal | Init/EEPROM CRC errors (3002–3014), self-test failures covering FPGA/CPLD/DCM/SDRAM/EEPROM/DAC/ADC/sync/PLL (3400–3489), emergency interrupt (3490), calibration failures: ADC gain/CMR/IM offset/VM offset/VF gain/VF offset/cable length (3500–3508). | self-test 3400–3489, cal 3500–3508, FPGA, EEPROM |

---

## High-Value Lookup Shortcuts

### WGFMU Architecture and B1500A Integration

- **Product overview**: PDF 13–14 (printed 1-3/1-4) — ALWG + fast IV module, circuit diagram
- **Module slot system**: PDF 15 (1-5) — up to 5 WGFMUs (10 channels), rating formula
- **Channel numbering**: PDF 142–143 (4-67) — chanId 101–1002, slot mapping
- **Control platforms**: PDF 12 (1-2) — EasyEXPERT app tests vs Instrument Library API
- **Not supported by EasyEXPERT Classic Test**: PDF 4, 12

### Channels, Terminals, Connection Topology, Grounding, and Safety

- **WGFMU connector panel**: PDF 15–16 (1-5/1-6) — Ch1/Ch2, Sync In/Out, TrigOut
- **RSU terminals**: PDF 17–18 (1-7/1-8) — Output (SMA), From SMU (triax ±25V), V Monitor (BNC, 1/10), From B1530A
- **RF probe setup**: PDF 31 (2-3) — GSG probes, 3-terminal MOSFET
- **DC probe setup**: PDF 32 (2-4) — 4 probes + SSMC short-open cables for current return
- **RSU cabling procedure**: PDF 34–38 (2-6/2-10) — master/slave sync, adapter mounting
- **Safety cautions**: PDF 15 (Sync/Trig damage), 17–18 (±25V limit, cable before power-on), 33 (B1500A OFF during cabling)
- **V Monitor details**: PDF 17–18 (1-7/1-8) — 450Ω + ×1 amp, 50Ω: shows 1/10, high-Z: shows 1/1

### Waveform Definition and Output

- **Pattern creation**: PDF 94 (4-18) — `createPattern(name, initV)`
- **Adding vectors**: PDF 88–89 (4-12/4-13) — `addVector(pattern, dTime, voltage)`, dTime = incremental (time delta from previous point), 10 ns resolution, range 10 ns to 10995.116 s. Vectors define linear ramps between points.
- **Setting vectors (absolute time)**: PDF 137–138 (4-61/4-62) — `setVector(pattern, time, voltage)` — can replace existing vector at same time; time=0 replaces initial voltage
- **Pattern operations**: PDF 91–94 (4-15/4-18) — merge (AXIS_TIME=concatenate, AXIS_VOLTAGE=add voltages), multiply (scale time/voltage by factors, negative factorT reverses pattern), offset (shift time/voltage)
- **Sequence building**: PDF 85–87 (4-9/4-11) — `addSequence(chanId, pattern, count)`, inter-sequence 50 ns delay
- **ALWG limits**: PDF 24 (1-14) — 2048 vectors/pattern, 512 sequences/channel, 10^12 max loop count, vector dTime 10 ns–10000 s (firmware max 10995.116 s), 10 ns time resolution throughout
- **Hardware memory**: ~4M data points/channel (typical) — depends on averaging mode (RAW inflates data by factor of 1+int(average/5ns))
- **Operation modes**: PDF 145 (4-69) — DC/FastIV/PG/SMU
- **Voltage ranges**: PDF 142, 146 (4-66, 4-70) — 3V, 5V, ±10V ranges and resolutions
- **Pulse specifications**: PDF 23 (1-13) — min width 50 ns (PG), rise/fall min 24 ns
- **Programming Example 1** (basic pulse): PDF 58–59 (3-12/3-13)
- **To Create Measurement Program** (workflow): PDF 57 (3-11) — 8-step procedure from template to measurement
- **exportAscii for verification**: PDF 99–100 (4-23/4-24)

### Measurement Timing and Sampling

- **setMeasureEvent** (core function): PDF 130–131 (4-54/4-56) — `setMeasureEvent(pattern, event, time, points, interval, average, rdata)`. Interval: 10 ns–1.34217728 s in 10 ns steps. Average: 0 (no averaging) or 10 ns–0.020971512 s in 10 ns steps. eventEndTime = time + interval×(points−1) + average. If average=0, add 10 ns to formula.
- **Averaging mechanics**: During average period, hardware samples at 5 ns intervals. E.g., average=20 ns → samples at 0, 5, 10, 15 ns → reported time = (0+20)/2 = 10 ns. RAW mode returns all sub-samples: count = points × (1 + int(average/5ns)).
- **Minimum timing for current measurement**: PDF 25 (1-15, Table 1-7) — measured with resistive load, 20 pF cable capacitance, 10 V applied, force channel in 10 mA range. Key values: 10 mA range → settling 125 ns, min meas window 20 ns, min pulse 145 ns; 1 µA range → settling 37 µs, window 1.64 µs, pulse 38.7 µs.
- **Minimum timing for voltage measurement**: PDF 26 (1-16, Table 1-8) — 5 V → settling 85 ns, min window 20 ns, min pulse 105 ns (PG mode); 10 V → settling 110 ns, min pulse 130 ns (Fast IV mode). Min rise/fall for overshoot control: 30 ns (5 V), 70 ns (10 V).
- **Sampling rate**: 5 ns native (fixed), or 10 ns–1 s programmable interval (PDF 24, Table 1-6)
- **Hardware memory**: about 4M data points per channel (typical, not guaranteed) (PDF 24)
- **Force/measure delay**: ±50 ns in 625 ps steps (PDF 105, 129) — compensates for cable/path timing differences between force and measure channels
- **Event timing constraint**: ≥100 ns between events that change averaging (PDF 131)
- **Range change constraint**: ≥2 µs between ≥3 consecutive range events (PDF 134)
- **Inter-sequence delay**: 50 ns (PDF 86)

### Triggering / Synchronization

- **Trigger output modes**: PDF 149 (4-73, Table 4-11) — DISABLE, START_EXECUTION, START_SEQUENCE, START_PATTERN, EVENT
- **Trigger polarity**: POSITIVE (default) or NEGATIVE
- **setTriggerOutMode**: PDF 136 (4-60)
- **setTriggerOutEvent**: PDF 135–136 (4-59/4-60) — time, duration; time=duration=0 triggers at pattern start
- **Physical trigger**: PDF 16 (1-6) — TrigOut SMA, TTL level, 10 ns width (exec/seq/pattern), adjustable (event)
- **Multi-WGFMU sync**: PDF 15 (1-5) — Sync Out → Sync In (master = lower slot)
- **50Ω termination note**: PDF 16 (1-6) — if trigger input is 50Ω: for period >10 µs, TTL high duration must be ≥5 µs; for period ≤10 µs, duty must be ≥50%. Use negative trigger for period <20 ns.

### Data Readout and Formats

- **getMeasureValue(s)**: PDF 116–118 (4-40/4-42) — returns time + voltage/current
- **getMeasureValueSize**: PDF 116 (4-40) — measured count vs total count
- **getInterpolatedForceValue**: PDF 107–108 (4-31/4-32) — correlate measurement with applied voltage
- **isMeasureEventCompleted**: PDF 126–127 (4-50/4-51) — check specific event, get offset/size for partial read
- **getCompletedMeasureEventSize**: PDF 102 (4-26) — completed vs total events
- **getChannelStatus**: PDF 101–102 (4-25/4-26) — status + elapsed/total time
- **Data output modes (rdata)**: PDF 151 (4-75) — AVERAGED (points), RAW (points × (1 + int(avg/5ns)))
- **Channel Execution Status examples**: PDF 152 (4-76, Table 4-15)
- **exportAscii**: PDF 99–100 (4-23/4-24) — setup summary CSV
- **writeResults helpers**: PDF 53–56 (3-7/3-10) — template functions for CSV data saving (writeResults: time+measured, writeResults2: time+measured+forced, writeResults3: time+measured+interpolated force)
- **Data indexing**: getMeasureEvent returns `index` and `length` for each event — use with getMeasureValues(chanId, index, &length, time[], value[]) for event-specific data extraction
- **Partial data readout while running**: Use getMeasureValueSize to check available points, then read available data without waiting for completion (Example 7/8)

### Reliability / Stress-Measure Workflows

- **Id-Vg measurement example**: PDF 69–71 (3-23/3-25, Example 9) — staircase gate/drain sweeps, per-Vd data files; polarity parameter for bidirectional sweeps; most complex example in manual
- **Multi-channel with SMU DC bias**: PDF 72–73 (3-26/3-27, Example 10) — WGFMU pulse+sampling on ch101 while SMU ch201 applies DC bias via VISA (CN/DV/CL commands)
- **Multi-channel with SMU sampling**: PDF 74–75 (3-28/3-29, Example 11) — simultaneous WGFMU + SMU measurement; uses XE to trigger SMU sampling synchronously with WGFMU_execute
- **NBTI application tests**: PDF 21 (1-11) — listed as included software on CD: "NBTI and general-purpose EasyEXPERT Application Tests". Implementation details NOT in this manual.
- **RTS data analysis**: PDF 21 (1-11) — listed as sample program on CD. Implementation details NOT in this manual.
- **Stress-measure pattern building**: Use createPattern/addVector for stress voltage waveform, setMeasureEvent for sense windows during or after stress; repeat with addSequence (loop count up to 10^12 for endurance). Key timing: 50 ns inter-sequence delay between stress and sense patterns.
- **Range change during stress**: PDF 133–134 (4-57/4-58) — setRangeEvent for mid-waveform current range switching (e.g., high range during stress → low range during sense). Constraint: ≥2 µs between 3+ consecutive range changes; range event must be outside averaging period.
- **Offline verification**: Use exportAscii (PDF 99–100) to dump pattern/sequence/event setup to CSV before running on hardware — essential for debugging complex stress-sense sequences
- **Real-time monitoring**: Use getChannelStatus/getMeasureValueSize/getCompletedMeasureEventSize (PDF 101–102, 152) to monitor long stress sequences without blocking

### FeFET / FeCap / NVM-Relevant Pulse Workflows

- **No explicit FeFET/FeCap/NVM/PUND/endurance/retention/wake-up content** in this manual. No ferroelectric-specific application notes, pulse protocols, or characterization recipes are included.
- **No NBTI/RTN/BTI methodology details** — only mentioned as titles of bundled software (PDF 21): "NBTI and general-purpose EasyEXPERT Application Tests" and "RTS data analysis" sample programs on CD. Their implementation is not documented here.
- However, the WGFMU's capabilities are directly applicable to NVM/FeFET characterization:
  - Arbitrary pulse waveforms (PDF 13, 88): programmable rise/fall, width, amplitude for P/E pulses. Vectors define linear ramps → trapezoidal pulses natural.
  - Fast IV mode for current sensing after pulses (PDF 13–14): 5 ns sampling, 2 nA resolution for Id readback
  - Multi-pattern sequences (PDF 85–87): stress-sense cycling with loop counts up to 10^12 — ideal for endurance
  - Id-Vg measurement (PDF 69–71): staircase gate sweep for threshold voltage (Vth) extraction
  - DC measurement mode (PDF 76): for static characterization between stress pulses
  - ±10V range (PDF 146): sufficient for typical FeFET gate pulses (most FeFET operate within ±5 V)
  - Range change events (PDF 133–134): mid-waveform current range switching for sense windows after stress
  - Force/measure delay (PDF 105, 129): ±50 ns / 625 ps fine timing alignment between force and sense channels
  - Two-channel operation (PDF 64–66): simultaneous gate stress + drain sense
  - SMU integration (PDF 72–75): DC bias on substrate/well during pulse characterization
- Agents needing FeFET workflows should combine this manual's waveform/measurement primitives with application-specific pulse protocols (PUND, switching kinetics, retention, endurance, wake-up)

### Waveform/Pulse Concept Quick Reference

| Concept | Key Info | Where |
|---|---|---|
| Pattern | Named waveform template with initial voltage; contains vectors (linear ramps) + events | PDF 94 (createPattern) |
| Vector | A (dTime, voltage) point defining a linear ramp endpoint from previous point. dTime = incremental time, 10 ns resolution. | PDF 88–89 (addVector) |
| Sequence | A (pattern, count) pair assigned to a channel; count up to 10^12 | PDF 85–87 (addSequence) |
| Event (Measure) | Sampling measurement within a pattern: start time + points + interval + averaging + data mode | PDF 130–131 (setMeasureEvent) |
| Event (Range) | Mid-waveform current range change (Fast IV only) | PDF 133–134 (setRangeEvent) |
| Event (Trigger) | Trigger pulse output at specified time within pattern | PDF 135–136 (setTriggerOutEvent) |
| Offline phase | Pattern/sequence/event creation — no hardware connection needed | PDF 49 (Programming Overview) |
| Online phase | openSession → initialize → setMode → connect → execute → wait → getData → disconnect → close | PDF 49–51 |
| ALWG | Arbitrary Linear Waveform Generator — the core voltage source engine in the WGFMU | PDF 13 |
| Fast IV mode | VFIM or VFVM, output ±10V, min pulse 300 ns, current measurement available | PDF 14, 145 |
| PG mode | VFVM only, 50Ω source impedance, output halved into 50Ω load, min pulse 100 ns, no current meas | PDF 14, 145 |
| DC mode | Static voltage force + I or V measurement, no patterns/sequences needed | PDF 76, 145 |
| Trapezoidal pulse | Created by: createPattern(p, baseV) → addVector(p, rise, peakV) → addVector(p, hold, peakV) → addVector(p, fall, baseV) → addVector(p, tail, baseV) | PDF 58–59 (Example 1) |
| Staircase sweep | Multiple addVector calls with incrementing voltage; see Example 9 for Id-Vg | PDF 69–71 |

### Errors, Limitations, Cautions

- **No compliance feature**: PDF 14 (1-4) — WGFMU has no built-in output limiter
- **ESD sensitivity**: PDF 17 (1-7) — keep hands off terminals during measurement (affects inter-channel timing)
- **Cable length affects pulse quality**: PDF 23 (1-13) — min rise/fall depends on cable: 16/32/56 ns for 1.5/3/5 m
- **Hardware memory limit**: ~4M data points/channel (typical, not guaranteed); must read data before overflow (PDF 24, 131). In RAW mode, actual data count = points × (1 + int(average/5ns)) — can exhaust memory much faster.
- **FIFO overflow (error 3051)**: Caused by frequently changing averaging conditions between events; keep ≥100 ns between events that change averaging.
- **Inter-sequence delay**: 50 ns (PDF 86) — 10 ns last voltage + 40 ns next initial voltage; affects total timing calculation
- **Range change timing**: ≥2 µs for 3+ consecutive changes (PDF 134), must be outside averaging window
- **Measurement event spacing**: ≥100 ns between events with different averaging (PDF 131)
- **Load capacitance**: ≤25 pF for specified accuracy (PDF 19)
- **V force in PG mode**: halved into 50Ω load (PDF 14) — e.g., ±5V open → ±2.5V into 50Ω
- **SMU ±25V limit on RSU From SMU terminal**: PDF 18 (1-8)
- **Error codes**: PDF 154–157 (library errors 0 to −15), PDF 158–164 (firmware errors 3000–3508)
- **WGFMU_RESULT_OUT_OF_DATE_ERROR** (−15): data invalidated by setup change before reading (PDF 157)
- **RUNNING_ILLEGAL status** (10005): setup changed during run, data unreadable (PDF 155)

---

## Gaps / Ambiguities

1. **OCR artifacts on PDF page 100 (4-24)**: The `exportAscii` output example (Figure 4-1) is garbled — appears as mojibake characters in OCR extraction. Cannot determine actual CSV column format from the OCR text. The function description says it creates a "setup summary report" as CSV.
2. **No explicit reliability test application notes**: The manual mentions "NBTI and general-purpose EasyEXPERT Application Tests" and "RTS data analysis" sample programs (PDF 21) but does not include their implementation, parameters, or methodology. These are separate deliverables on the included CD.
3. **No FeFET/FeCap/NVM-specific guidance**: This is a generic hardware manual. No PUND, endurance, retention, wake-up, switching kinetics, or polarization measurement protocols are documented. Must be derived from ALWG primitives.
4. **No NBTI/BTI/RTN methodology**: Only the software titles are mentioned. No stress-measure-stress timing diagrams, no Vth extraction methods, no ΔVth vs stress time recipes.
5. **HTBasic function names truncated**: Some HTBasic equivalents (e.g., `Wm_getmeevtsz` for getMeasureEventSize) are highly abbreviated. The PDF TOC has a typo: "WGFMU_getMeasueValue" (missing 'r'). Not all HTBasic examples are shown.
6. **Page 10 appears blank in OCR**: May contain content not captured by text extraction (likely intentionally blank per book printing conventions).
7. **Table formatting in OCR**: Multi-column specification tables (Tables 1-2 through 1-8) lose their alignment in OCR. The Content-To-Page Map above reconstructs the key numeric values but may have minor transcription differences.
8. **Firmware version dependency**: Some behaviors may differ with firmware versions newer than the August 2012 edition. The manual references EasyEXPERT A.03.20+ as minimum for self-test.
9. **Missing information on waveform memory architecture**: The manual states "about 4M data points/channel" (typical) but does not detail how memory is partitioned between force and measurement data, how sequences interact with hardware memory, or what triggers overflow vs FIFO overflow (error 3050 vs 3051).
10. **No timing diagram for inter-sequence 50 ns delay**: The 10 ns (last voltage) + 40 ns (next initial voltage) behavior is mentioned only in addSequence/addSequences remarks (PDF 86–87). No visual diagram provided.
11. **Undocumented internal commands**: Error messages 3324–3327 reference WGMS?, WGMA?, WGMB? commands that appear to be internal GPIB commands used by the library. Their syntax, parameters, and behavior are not documented in this manual.
12. **No explicit discussion of DUT protection**: WGFMU has no compliance feature (noted PDF 14). No guidance on how to protect sensitive DUTs from overcurrent beyond choosing appropriate voltage ranges.
13. **V Monitor accuracy unspecified in dynamic waveforms**: V Monitor behavior is specified for DC output (1/10 ratio) but behavior during fast transients (rise/fall <100 ns) is not characterized.

---

## Revision Notes

### Revision 2 — 2026-06-22

**Context**: Second-pass revision against source PDF `B1530A WGFMU.pdf` (164 pages). Systematic multi-pass audit comparing OCR-extracted PDF text to existing index.

**What was improved**:
- **Added missing "To Create Measurement Program" section** (PDF 57, printed 3-11): 8-step workflow procedure that was absent from both tables. This is a distinct TOC entry in the official manual.
- **Corrected Example 1 page range**: Was PDF 57–59 (printed 3-11–3-13), corrected to PDF 58–59 (printed 3-12–3-13). PDF 57 is the "To Create Measurement Program" section.
- **Improved ALWG specification precision**: Added firmware-limit dTime maximum (10995.116 s from error 3311 vs rounded 10000 s in spec table). Clarified "about 4M data points" is typical/supplemental, not guaranteed.
- **Added RF electromagnetic field sensitivity note**: >3 V/m (80 MHz–2 GHz) and >1 V/m (2–2.7 GHz) affect accuracy (PDF 20).
- **Expanded error messages documentation**: Detailed all error code ranges with specific firmware error meanings. Documented hidden internal commands (WGMS?, WGMA?, WGMB?) revealed by error messages 3324–3327.
- **Improved setMeasureEvent description**: Added averaging mechanics (5 ns internal sampling, reported time formula), RAW data inflation formula, and eventEndTime calculation with average=0 edge case.
- **Enhanced measurement timing shortcuts**: Added precise settling/pulse/window values for key ranges, measurement conditions (resistive load, 20 pF cable capacitance), and overshoot-minimizing rise/fall recommendations.
- **Improved trigger/50Ω termination note**: Added the actual period-dependent duty cycle rules from the manual.
- **Enhanced waveform definition shortcuts**: Added vector-as-linear-ramp concept, setVector replace behavior, pattern operation details (merge/multiply/offset mechanics).
- **Expanded FeFET/NVM section**: Made explicit that NO FeFET/PUND/endurance/retention/wake-up/BTI methodology content exists. Listed specific applicable primitives with rationale.
- **Expanded Reliability section**: Added offline verification (exportAscii), real-time monitoring functions, and practical timing constraints for stress-sense patterns.
- **Added 4 new items to Gaps/Ambiguities**: Undocumented commands, DUT protection absence, V Monitor dynamic behavior, and NBTI/BTI methodology gap.
- **Added V/I accuracy conditions**: 10,000 averaging samples for ≥10 µA ranges; 100,000 for 1 µA range.
- **Detailed specifications row (PDF 20–22)**: Added V Monitor specs, cable adapter combinations, trigger specs, software package list, RF EMF sensitivity, and all supplemental data values.

**Verification method**: Multi-pass OCR text comparison. Sampled ~70% of PDF pages (all front matter, all chapter intros, all specification tables, key API functions, all error code pages). Not every page was character-by-character verified.

**What still needs future extraction**:
1. Full exportAscii CSV format (Figure 4-1 is garbled in OCR — may need image-based extraction)
2. NBTI/RTS application test methodology from companion CD software
3. Detailed FeFET/NVM pulse recipe construction using WGFMU primitives (application note level)
4. Programming Example 9 (Id-Vg) step-by-step timing breakdown for Vth extraction agents
5. Complete C#/.NET and HTBasic syntax cross-reference table
6. Investigation of WGMS?/WGMA?/WGMB? internal commands (may require firmware documentation)
7. Practical memory budget calculator: given pattern complexity + measurement events + loop counts, estimate whether 4M limit will be hit
