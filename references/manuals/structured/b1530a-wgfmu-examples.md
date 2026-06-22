# B1530A WGFMU Programming Examples Extraction

Source: `B1530A WGFMU.pdf`, Chapter 3, "Using Instrument Library".  
Index used: `../b1530a-wgfmu-index.md`.

This file extracts the manual's examples into a structured form for future agents building WGFMU pulse, waveform, sampling, and reliability tooling. Page ranges are PDF pages with printed chapter pages.

## Example Coverage Notes

| Scope | Coverage / Limitation | Page Reference |
|---|---|---|
| Examples 1-11 | Covered from Chapter 3 programming examples | PDF 58-75, printed 3-12 to 3-29 |
| Project template | Error handlers and data writers summarized, not fully reproduced | PDF 53-56, printed 3-7 to 3-10 |
| `exportAscii` sample output | Function is included, but Figure 4-1 CSV example is OCR-garbled and not parsed here | PDF 99-100, printed 4-23/4-24 |
| Reliability/NVM workflows | NBTI/RTS are only listed as bundled software; FeFET/PUND/endurance/retention methods are not in this manual | PDF 21, printed 1-11 |

## Programming Support Sections

| Section | Page Range | Workflow Intent | Major API Calls / Concepts | Timing / Waveform Lesson | Data Readout Lesson | Notes |
|---|---|---|---|---|---|---|
| Programming Overview | PDF 49-51, printed 3-3 to 3-5 | Establish the canonical offline/online WGFMU programming sequence | `WGFMU_createPattern`, `WGFMU_addVector`, `WGFMU_setMeasureEvent`, `WGFMU_setRangeEvent`, `WGFMU_setTriggerOutEvent`, `WGFMU_addSequence`, `WGFMU_openSession`, `WGFMU_execute`, `WGFMU_getMeasureValues`, `WGFMU_exportAscii` | Separate offline pattern/event/sequence creation from online hardware execution | Read data after execute/wait or monitor progress through status functions | Table 3-1 to 3-5 are the best high-level API roadmap |
| Programming Examples Summary | PDF 52, printed 3-6 | List 11 examples by increasing complexity | Examples 1-11 | Shows progression from pulse output to SMU integration | Identifies which examples save data | Table 3-6 summary |
| Project Template | PDF 53-56, printed 3-7 to 3-10 | Set up Visual C++ project and helper functions | `wgfmu.h`, `wgfmu.lib`, `visa32.lib`, `checkError`, `checkError2`, `checkError3`, `writeResults`, `writeResults2`, `writeResults3` | Template not a waveform itself; prepares reusable program skeleton | `writeResults` saves measured data; `writeResults2` includes force data; `writeResults3` uses interpolated force | `visa32.lib` is needed only for Examples 10-11 |
| To Create Measurement Program | PDF 57, printed 3-11 | 8-step workflow from template to measurement program | Plan device/parameters/waveform/conditions, copy/rename template, write main, add display/store/calc | Decide pulse/ALWG/DC waveform before coding | Add storage/calculation code as needed | Distinct manual section, not Example 1 |
| DC Measurement Guide | PDF 76, printed 3-30 | Simplified flow for DC force/measure without ALWG patterns | `WGFMU_openSession`, `WGFMU_initialize`, `WGFMU_setOperationMode(DC)`, `WGFMU_setForceVoltageRange`, `WGFMU_setMeasureMode`, `WGFMU_setMeasureCurrentRange`, `WGFMU_setMeasureVoltageRange`, `WGFMU_connect`, `WGFMU_dcforceVoltage`, `WGFMU_dcmeasureValue`, `WGFMU_dcmeasureAveragedValue`, `WGFMU_disconnect`, `WGFMU_closeSession` | No vectors, events, or sequences needed | Measurement returned immediately by DC functions | Optional logging and optional setup steps called out in Table 3-19 |

## Manual Examples

| Example | Page Range | Workflow Intent | Major API Calls | Timing / Waveform Lesson | Data Readout Lesson | Notes |
|---|---|---|---|---|---|---|
| Example 1: Pulse voltage output | PDF 58-59, printed 3-12 to 3-13 | Create and output a basic pulse waveform on channel 101 | `WGFMU_clear`, `WGFMU_createPattern`, `WGFMU_addVector`, `WGFMU_addSequence`, `WGFMU_openSession`, `WGFMU_initialize`, `WGFMU_setOperationMode(FASTIV)`, `WGFMU_connect`, `WGFMU_execute`, `WGFMU_waitUntilCompleted`, `WGFMU_closeSession` | Pattern `pulse`: 0 V initial, 0.1 ms rise to 1 V, 0.4 ms hold, 0.1 ms fall to 0 V, 0.4 ms base; repeated 10 times with `addSequence` | No measurement and no saved data | Does not require project-template subprograms; cleanest minimal pulse example |
| Example 2: Pulse voltage output and sampling measurement | PDF 60, printed 3-14 | Add sampling measurement to Example 1 and save data | Example 1 APIs plus `WGFMU_setMeasureEvent`, `writeResults` | Measurement event starts at 0 s, 100 points, 10 us interval, no averaging, AVERAGED data | `writeResults(101, "C:/temp/B1530A/data/ex02.csv")` saves time/value data | First example that creates measurement data |
| Example 3: Sampling with `checkError` | PDF 61, printed 3-15 | Demonstrate try/catch error handling and error queue readout | `checkError`, `WGFMU_getErrorSize`, `WGFMU_getError`; intentionally bad `WGFMU_setOperationMode(101, WGFMU_MEASURE_MODE_CURRENT)` | Same pulse/sampling as Example 2, but with duplicate event to cause overwrite warning | Result data not saved; error string displayed on exception | Line 18 intentionally passes measurement-mode constant as operation mode |
| Example 4: Treat warnings as errors | PDF 62, printed 3-16 | Promote severe warnings to errors during setup/execution | `WGFMU_treatWarningsAsErrors(WGFMU_WARNING_LEVEL_SEVERE)`, `checkError2` | Same pulse/sampling as Example 2 | Result data not saved | Demonstrates warning policy control for tooling validation |
| Example 5: Error summary after measurement | PDF 63, printed 3-17 | Read/display accumulated error summary without project subprogram dependency | `WGFMU_getErrorSummarySize`, `WGFMU_getErrorSummary`; intentionally bad `WGFMU_setOperationMode(101, WGFMU_MEASURE_MODE_CURRENT)` | Same pulse/sampling as Example 2 | Result data not saved; summary printed if non-empty | Useful pattern for post-run diagnostics |
| Example 6: Two-channel measurement with multiple sampling rates | PDF 64-66, printed 3-18 to 3-20 | Output two constant patterns and sample one channel using three events | `WGFMU_createPattern("v1")`, `WGFMU_createPattern("v2")`, `WGFMU_setMeasureEvent`, `WGFMU_addSequence`, `WGFMU_setMeasureMode(CURRENT)`, `writeResults` | Channel1 pattern `v1` at 0.5 V; Channel2 pattern `v2` at 1.0 V. Three events on `v2`: 10 kHz (100 us interval), 100 kHz (10 us), 1 MHz (1 us), each 32768 points, 10 ns averaging. | `writeResults(channel2, "C:/temp/B1530A/data/ex06.csv")` saves time and measured value for channel2 | Introduces multi-channel timing and large data volumes (32768 pts × 3 events = 98304 total points) |
| Example 7: Polling channel status | PDF 67, printed 3-21 | Replace blocking wait with progress polling | `WGFMU_getChannelStatus`, `WGFMU_getMeasureValueSize`, `WGFMU_getCompletedMeasureEventSize`, `writeResults` | Uses Example 6 measurement; waits until completed status, elapsed=total, measured=total, or event completed=total | Saves after polling indicates completion | Good pattern for long reliability/stress runs |
| Example 8: Event-specific completion and partial read | PDF 68, printed 3-22 | Wait for a specific event and read only its data slice | `WGFMU_isMeasureEventCompleted(channel2, "v2", "100kHz", 0, 0, 0, &completed, &index, &offset, &size)`, `writeResults2(channel2, offset, size, ...)` | Targets the `"100kHz"` event from Example 6 | Uses returned offset and size for event-specific partial data extraction | Best template for event-granular MCP data readout |
| Example 9: Id-Vg measurement | PDF 69-71, printed 3-23 to 3-25 | Full two-channel Id-Vg sweep with gate/drain patterns and per-Vd files | `WGFMU_openLogFile`, `WGFMU_clear`, `WGFMU_createPattern("Vg")`, `WGFMU_addVector`, `WGFMU_addSequence`, `WGFMU_createPattern("Vd")`, `WGFMU_setMeasureEvent("Vd","Id",...)`, `WGFMU_exportAscii`, `WGFMU_openSession`, `WGFMU_setOperationMode(FASTIV)`, `WGFMU_setMeasureMode(CURRENT)`, `WGFMU_execute`, `writeResults3`, `WGFMU_closeLogFile` | Gate: `vgMin=2 V`, `vgMax=3 V`, `vgStep=0.01 V`, `vgRiseTime=100 ns`, `vgStepLength=500 ns`, `vgStepDelay=200 ns`, `polarity=-1`. Drain: `vdMin=0 V`, `vdMax=10 V`, `vdStep=2 V`; drain step length = `(vgRiseTime + vgStepLength) * numberOfVgSteps`. | `writeResults3(gateChannel, drainChannel, numberOfVgSteps*i, numberOfVgSteps, fileName)` saves one Id-Vg file per Vd. `exportAscii` dumps waveform setup before online execution. | Most realistic device-characterization example. It is adjacent to Vth extraction workflows, but the manual does not define Vth extraction math. |
| Example 10: WGFMU pulse with SMU DC bias | PDF 72-73, printed 3-26 to 3-27 | Apply SMU DC bias while WGFMU performs pulse/sampling measurement | WGFMU pulse APIs; VISA `viOpenDefaultRM`, `viOpen`, `viPrintf("CN 201")`, `viPrintf("DV 201,0,3")`, `viPrintf("CL 201")`, `viClose`; `checkError3` | WGFMU pulse/sampling similar to Example 3; SMU channel 201 applies 3 V DC bias | No explicit WGFMU data save in excerpt; focus is combined VISA/WGFMU error handling | Requires `visa32.lib`; `checkError3` distinguishes VISA and WGFMU errors |
| Example 11: SMU sampling plus WGFMU measurement | PDF 74-75, printed 3-28 to 3-29 | Run SMU sampling measurement with WGFMU pulse/sampling | WGFMU pulse APIs; `WGFMU_setTimeout(120)`, VISA `*RST`, `CN 201`, `MV 201,0,0,5`, `MT 0,1,110,5`, `MM 10,201`, `ERRX?`, `XE`, `NUB?`, `CL 201` | SMU sampling condition is configured before WGFMU execute; `XE` starts SMU measurement, then `WGFMU_execute` starts WGFMU | Reads SMU data count via `NUB?`, then scans/prints SMU output buffer; WGFMU waits until completed | Shows synchronization via command ordering rather than WGFMU trigger output; requires `visa32.lib` |

## Example Lessons for Tool Builders

| Lesson | Evidence | MCP/Automation Use | Page Reference |
|---|---|---|---|
| Separate offline setup from online hardware execution | Examples define patterns/events/sequences before `openSession` or before channel connect | Let tools generate/validate waveform plans without touching hardware | PDF 49-51, 58-75 |
| Use `exportAscii` before risky waveform execution | Example 9 exports `C:/temp/B1530A/waveform/ex09.csv` before online execution | Add preflight export step for stress/reliability recipes | PDF 71, 99-100 |
| Use event offsets for partial reads | Example 8 returns offset/size from `isMeasureEventCompleted` | Read only completed sense windows during long runs | PDF 68, printed 3-22 |
| Use status polling for long sequences | Example 7 polls status, measured size, and event count | Avoid blind blocking during endurance/stress loops | PDF 67, printed 3-21 |
| Use RAW mode carefully | `setMeasureEvent` supports RAW but examples mostly use AVERAGED | RAW can multiply data volume; preflight memory budget | PDF 130-131, 151 |
| Treat warnings as policy | Example 4 promotes severe warnings | Tooling can fail fast on severe setup issues | PDF 62, printed 3-16 |
| SMU integration requires VISA | Examples 10-11 use `visa32.lib` and direct B1500A commands | MCP tools may need separate B1500A/SMU command layer, not just WGFMU library calls | PDF 72-75 |
| FeFET/NVM workflows are derived, not provided | No explicit FeFET/PUND/endurance/retention examples | Build from Example 1 pulse, Example 6 multi-channel sampling, Example 8 partial read, Example 9 Id-Vg, and DC guide | No explicit section; absence verified against TOC and index |

## Data Writer Helpers

| Helper | Intended Data | Example Usage | Page Reference |
|---|---|---|---|
| `writeResults` | WGFMU measurement results for one channel | Example 2 saves `ex02.csv` | PDF 53-56, 60 |
| `writeResults2` | Measurement data plus force/readback context; supports offset/size | Examples 6 and 8 | PDF 53-56, 64-68 |
| `writeResults3` | Correlates gate/channel force and drain/channel measured data using interpolated force value | Example 9 per-Vd Id-Vg files | PDF 53-56, 69-71 |

## Reliability / NVM Caveat

The manual lists NBTI application tests and RTS data analysis sample programs as included software on PDF 21 (printed 1-11), but does not include their algorithms, parameters, or timing diagrams. FeFET/FeCap/NVM concepts such as PUND, endurance, retention, wake-up, and switching kinetics are absent. Future tools should label any such workflows as derived from WGFMU primitives rather than manual-provided procedures.

---

## Opus Review

| Field | Value |
|---|---|
| Reviewer | opus-4.6-max |
| Review date | 2026-06-22 |
| Passes completed | 5 |
| Verification method | Multi-pass: (1) full file read and schema audit, (2) cross-reference against revised index for all 11 examples, (3) PDF verification of Examples 6/7/8/10/11 code and variable declarations on pages 64-75, (4) targeted corrections, (5) re-read and consistency check |

### Items Verified Against PDF

- Example 6: measurementPoints=32768, averagingTime=10e-9, intervals 100e-6/10e-6/1e-6, v1=0.5V, v2=1.0V confirmed (PDF 64-65)
- Example 6 uses `writeResults` (not `writeResults2`) confirmed (PDF 65, line 45)
- Example 8: `isMeasureEventCompleted(channel2, "v2", "100kHz", 0, 0, 0, ...)` confirmed (PDF 68)
- Example 10: SMU VISA commands CN/DV/CL, checkError3 error handling confirmed (PDF 72-73)
- Example 11: setTimeout(120), *RST, MV/MT/MM/XE/NUB? sequence confirmed (PDF 74-75)
- DC Measurement guide on PDF 76 confirmed

### Corrections Made

- Fixed Example 6: changed `writeResults2` to `writeResults` in Major API Calls column (PDF shows writeResults, not writeResults2)
- Fixed Example 6: corrected Data Readout Lesson from vague "Saves data with helper that can include forced voltage" to accurate `writeResults(channel2, ...)` description
- Added total data point calculation note (32768 × 3 = 98304)

### Remaining Uncertainties

- Example 9 Id-Vg variable declarations not fully character-verified (complex nested loop; PDF 69-71 confirmed structurally)
- The exact CSV output format from writeResults/writeResults2/writeResults3 is defined only in the project template code (PDF 53-56), not independently specified
- Whether example code represents the exact OCR character sequence or has been lightly reformatted is uncertain for long lines

### Completeness Assessment

All 11 examples from Chapter 3 are covered. Programming overview, project template, DC measurement guide, and example lessons table are all present. No example or support section from the index was found missing.
