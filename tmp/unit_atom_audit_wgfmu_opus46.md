# Unit Atom Audit — B1530A WGFMU

Auditor: opus-4.6-max  
Date: 2026-06-22  
Scope: A/B/C atom coverage for B1530A WGFMU (Waveform Generator / Fast Measurement Unit)

Sources audited:
- `src/b1500_test_agent/mcp/a_atoms.py` (WGFMU section, lines 346–533)
- `src/b1500_test_agent/mcp/b_atoms.py` (WGFMU section, lines 461–553)
- `src/b1500_test_agent/mcp/c_atoms.py` (WGFMU section, lines 524–841)
- `.agents/skills/.../references/mcp-tools/a-atoms.md`, `b-atoms.md`, `c-atoms.md`
- `references/manuals/b1530a-wgfmu-index.md`
- `references/manuals/structured/b1530a-wgfmu-api-reference.yaml`
- `references/manuals/structured/b1530a-wgfmu-waveform-timing.md`
- `references/manuals/structured/b1530a-wgfmu-error-codes.yaml`
- `references/manuals/structured/b1530a-wgfmu-examples.md`
- `tmp/c_atom_arbitration.md`

User-provided actual-system constraints:
- Min generated pulse width without measurement: **10 ns**
- Min generated pulse width with measurement: **100 ns**
- Measured max pulse voltage: **±10 V** (Vpp = 10 V)
- Important workflows: fast waveform/pulse, reliability, FeFET/NVM-style

---

## Current Coverage Summary

### A atoms — WGFMU (16 existing)

| # | Atom | API Covered | Status |
|---|---|---|---|
| 1 | `A_atom_wgfmu_open_session` | `WGFMU_openSession` | OK |
| 2 | `A_atom_wgfmu_close_session` | `WGFMU_closeSession` | OK |
| 3 | `A_atom_wgfmu_set_timeout` | `WGFMU_setTimeout` | OK |
| 4 | `A_atom_wgfmu_get_channel_ids` | `getChannelIdSize` + `getChannelIds` | OK |
| 5 | `A_atom_wgfmu_get_status` | `WGFMU_getStatus` | OK |
| 6 | `A_atom_wgfmu_get_channel_status` | `WGFMU_getChannelStatus` | OK |
| 7 | `A_atom_wgfmu_clear` | `WGFMU_clear` | OK |
| 8 | `A_atom_wgfmu_open_log` | `WGFMU_openLogFile` | OK |
| 9 | `A_atom_wgfmu_close_log` | `WGFMU_closeLogFile` | OK |
| 10 | `A_atom_wgfmu_read_error` | `getErrorSize` + `getError` | OK |
| 11 | `A_atom_wgfmu_read_error_summary` | `getErrorSummarySize` + `getErrorSummary` | OK |
| 12 | `A_atom_wgfmu_set_warning_level` | `WGFMU_setWarningLevel` | OK |
| 13 | `A_atom_wgfmu_read_warning_summary` | `getWarningSummarySize` + `getWarningSummary` | OK |
| 14 | `A_atom_wgfmu_export_ascii` | `WGFMU_exportAscii` | OK |
| 15 | `A_atom_wgfmu_get_completed_event_count` | `getCompletedMeasureEventSize` | OK |
| 16 | `A_atom_wgfmu_is_event_completed` | `isMeasureEventCompleted` | OK |

### B atoms — WGFMU (7 existing)

| # | Atom | API Covered | Status |
|---|---|---|---|
| 1 | `B_atom_lifecycle_wgfmu_initialize` | `WGFMU_initialize` | OK |
| 2 | `B_atom_calibration_wgfmu_self_calibration` | `WGFMU_doSelfCalibration` | OK |
| 3 | `B_atom_diagnostic_wgfmu_self_test` | `WGFMU_doSelfTest` | OK |
| 4 | `B_atom_policy_wgfmu_treat_warnings_as_errors` | `WGFMU_treatWarningsAsErrors` | OK |
| 5 | `B_atom_output_wgfmu_connect` | `WGFMU_connect` | OK |
| 6 | `B_atom_output_wgfmu_disconnect` | `WGFMU_disconnect` | OK |
| 7 | `B_atom_lifecycle_wgfmu_abort` | `WGFMU_abort` | OK |

### C atoms — WGFMU (19 existing)

| # | Atom | API Covered | Status |
|---|---|---|---|
| 1 | `C_atom_wgfmu_set_operation_mode` | `setOperationMode` | Schema gaps |
| 2 | `C_atom_wgfmu_configure_force_measure_ranges` | `setForceVoltageRange` + `setMeasureCurrentRange` | Over-bundled + incomplete |
| 3 | `C_atom_wgfmu_create_pattern` | `createPattern` | Minor gap |
| 4 | `C_atom_wgfmu_add_vectors` | `addVector` / `addVectors` | Missing limits |
| 5 | `C_atom_wgfmu_add_sequence` | `addSequence` | Type + limits gap |
| 6 | `C_atom_wgfmu_set_measure_event` | `setMeasureEvent` | **CRITICAL: missing 4 params** |
| 7 | `C_atom_wgfmu_update` | `WGFMU_update` | Minor note gap |
| 8 | `C_atom_wgfmu_execute` | `WGFMU_execute` | Minor note gap |
| 9 | `C_atom_wgfmu_read_measurement_values` | `getMeasureValue` / `getMeasureValues` | OK |
| 10 | `C_atom_wgfmu_set_vectors` | `setVector` / `setVectors` | OK |
| 11 | `C_atom_wgfmu_transform_pattern` | merge/multiply/offset | Over-bundled |
| 12 | `C_atom_wgfmu_set_range_event` | `setRangeEvent` | Schema gap |
| 13 | `C_atom_wgfmu_set_trigger_event` | `setTriggerOutEvent` | Missing `duration` |
| 14 | `C_atom_wgfmu_configure_force_measure_delay` | force/measure delay | Wrong basis |
| 15 | `C_atom_wgfmu_read_force_values` | `getForceValue` / `getForceValues` | OK |
| 16 | `C_atom_wgfmu_dc_force_measure` | `dcforceVoltage` + `dcmeasureValue` | Wrong API name |
| 17 | `C_atom_wgfmu_dc_measure_averaged` | `dcmeasureAveragedValue` | Wrong API name + missing params |
| 18 | `C_atom_wgfmu_read_measurement_values_partial` | `getMeasureValues` | OK |
| 19 | `C_atom_wgfmu_configure_alwg_cycle` | pattern + sequence | OK (convenience) |

**Totals: 16 A + 7 B + 19 C = 42 WGFMU atoms.** Manual has ~50 distinct API functions; effective coverage after accounting for get/set pairs and bundling ≈ 75%.

---

## Confident Missing A_atoms

| # | Proposed Atom | API Coverage | Why Needed | Confidence |
|---|---|---|---|---|
| A1 | `A_atom_wgfmu_get_measure_value_size` | `WGFMU_getMeasureValueSize` | Returns measured count vs total count — essential for progress polling during long stress runs (Example 7). Distinct from data-read C atom. | HIGH |
| A2 | `A_atom_wgfmu_get_measure_event_info` | `getMeasureEventSize` / `getMeasureEvent` / `getMeasureEvents` / `getMeasureEventAttribute` | Event-setup readback: pattern name, event name, cycle, loop, count, index, length, and raw setMeasureEvent attributes. Required for preflight validation and partial-read offset calculation. | HIGH |
| A3 | `A_atom_wgfmu_get_measure_times` | `getMeasureTimeSize` / `getMeasureTime` / `getMeasureTimes` | Sequence-level measurement timing readback. Useful for validating timing before execute. | MEDIUM |
| A4 | `A_atom_wgfmu_get_interpolated_force_value` | `WGFMU_getInterpolatedForceValue` | Returns interpolated voltage at arbitrary time — correlates measured data with applied waveform (used by writeResults3 in Example 9 Id-Vg). | MEDIUM |
| A5 | `A_atom_wgfmu_wait_until_completed` | `WGFMU_waitUntilCompleted` | Blocking wait until all connected channels complete. Classification: A-class because it is a synchronization/wait primitive, does not change output state. Alternative: could be folded into `C_atom_wgfmu_execute` as optional mode. | MEDIUM — classification ambiguous (A vs C helper) |

**Count: 5 missing A atoms (3 high confidence, 2 medium)**

---

## Confident Missing B_atoms

| # | Proposed Atom | API Coverage | Why Needed | Confidence |
|---|---|---|---|---|
| B1 | `B_atom_lifecycle_wgfmu_abort_channel` | `WGFMU_abortChannel` | Per-channel abort — stops one channel while others continue running. Important for multi-channel reliability where one channel needs early termination. Current `B_atom_lifecycle_wgfmu_abort` only covers the all-channel variant. | HIGH |

**Count: 1 missing B atom**

---

## Confident Missing C_atoms

| # | Proposed Atom | API Coverage | Why Needed | Confidence |
|---|---|---|---|---|
| C1 | `C_atom_wgfmu_set_measure_mode` | `WGFMU_setMeasureMode` | Sets voltage vs current measurement mode per channel. Currently not a standalone atom — only partially implied by `configure_force_measure_ranges`. Changing to CURRENT auto-sets voltage range to 5 V. Essential for Fast IV current measurement workflows. | HIGH |
| C2 | `C_atom_wgfmu_set_measure_voltage_range` | `WGFMU_setMeasureVoltageRange` | Sets voltage measurement range (5 V / 10 V). Not covered explicitly — only force range and current range are in `configure_force_measure_ranges`. | HIGH |
| C3 | `C_atom_wgfmu_set_measure_enabled` | `WGFMU_setMeasureEnabled` / `isMeasureEnabled` | Enable/disable measurement per channel. DISABLE prevents measurement even if pattern has events — needed for force-only channels in multi-channel setups. | HIGH |
| C4 | `C_atom_wgfmu_set_trigger_out_mode` | `WGFMU_setTriggerOutMode` | Sets trigger output mode (DISABLE/START_EXECUTION/START_SEQUENCE/START_PATTERN/EVENT) and polarity. **Required prerequisite for `set_trigger_event`** (EVENT mode needed). Without this atom, trigger events are incomplete. | HIGH |
| C5 | `C_atom_wgfmu_dc_measure_value` | `WGFMU_dcmeasureValue` | Single-point DC voltage or current measurement (non-averaged). Current `dc_force_measure` bundles force+measure, and `dc_measure_averaged` only covers the averaged variant. This covers the simplest DC read. | MEDIUM |

**Count: 5 missing C atoms (4 high confidence, 1 medium)**

---

## Parameter / Schema Gaps In Existing Atoms

### CRITICAL

| # | Atom | Gap | Impact |
|---|---|---|---|
| P1 | `C_atom_wgfmu_set_measure_event` | **Missing 4 of 7 API parameters.** Current schema has only `channel_id`, `pattern`, `event`, `time_s`. Missing: `points` (int), `interval` (10 ns – 1.342 s), `average` (0 or 10 ns – 20.97 ms), `rdata` (AVERAGED/RAW). This is the most important WGFMU function — without these, no measurement can be configured. | BLOCKER — atom is non-functional for any real use |
| P2 | `C_atom_wgfmu_dc_measure_averaged` | Missing `points` (1–65535) and `interval` (1–65535 × 5 ns) parameters. Only has `channel_id` and `averaging_count`. API basis says "WGFMU_measureCurrent, averaging" which is wrong — should be `WGFMU_dcmeasureAveragedValue`. | Schema mismatch — wrong API name and missing params |
| P3 | `C_atom_wgfmu_dc_force_measure` | Basis says `WGFMU_dcforceVoltage, WGFMU_measureCurrent` — no WGFMU function called `measureCurrent` exists. Should be `WGFMU_dcforceVoltage` + `WGFMU_dcmeasureValue`. | Wrong API reference |

### HIGH

| # | Atom | Gap | Impact |
|---|---|---|---|
| P4 | `C_atom_wgfmu_set_trigger_event` | Missing `duration` parameter. API signature is `setTriggerOutEvent(pattern, event, time, duration)`. Without duration, trigger pulse width cannot be controlled. | Incomplete schema — default duration behavior undocumented |
| P5 | `C_atom_wgfmu_configure_force_measure_delay` | Basis says "WGFMU_setMeasureEvent, delay parameters" which is wrong. Should be `WGFMU_setForceDelay` + `WGFMU_setMeasureDelay`. Missing ±50 ns range / 625 ps resolution constraints. | Wrong API reference + missing constraints |
| P6 | `C_atom_wgfmu_configure_force_measure_ranges` | Over-bundled: covers `setForceVoltageRange` + `setMeasureCurrentRange` but omits `setMeasureMode` and `setMeasureVoltageRange`. Params use strings ("auto") without mapping to API constants (AUTO=3000, 3V=3001, etc.). | Missing 2 of 4 sub-APIs; string-to-constant mapping absent |
| P7 | `C_atom_wgfmu_set_operation_mode` | `mode` param is string "fast_iv" — no mapping to constants DC=2000, FASTIV=2001, PG=2002, SMU=2003. No documentation of mode-specific constraints (current measurement requires Fast IV/DC; PG gives 50 Ω output). | Missing constant mapping and mode constraint docs |
| P8 | `C_atom_wgfmu_set_range_event` | `range_value` is string "auto" — should map to current range constants (1µA=6001 through 10mA=6005). Missing ≥2 µs spacing constraint for 3+ consecutive range events. Missing note that range events must be outside averaging periods. | Missing constant mapping and timing constraints |

### MEDIUM

| # | Atom | Gap | Impact |
|---|---|---|---|
| P9 | `C_atom_wgfmu_add_sequence` | `repeat_count` typed as `int` but API allows up to 1,099,511,627,776 (~10^12). Should be typed as float or large-int. Missing 50 ns inter-sequence delay documentation. Missing max 512 sequences/channel limit. | Type overflow risk; missing ALWG limits |
| P10 | `C_atom_wgfmu_add_vectors` | Missing max 2048 vectors/pattern limit. Missing dTime range constraint (10 ns – 10995.116 s). Missing 10 ns resolution note. | Missing ALWG limits in schema |
| P11 | `C_atom_wgfmu_create_pattern` | Missing uniqueness constraint documentation — pattern name must be unique per API (error −12 on duplicate). | Minor schema doc gap |
| P12 | `C_atom_wgfmu_update` | Missing two-level validation note: `update` performs deferred high-limit parameter checks that may reject patterns accepted at `createPattern`/`addVector` time. | Validation behavior undocumented |
| P13 | `C_atom_wgfmu_execute` | Missing note that `execute` stops and restarts already-running channels. Missing note that channels keep last voltage after completion. | Behavioral subtlety undocumented |
| P14 | `C_atom_wgfmu_transform_pattern` | Over-bundled: merge, multiply, and offset are fundamentally different operations with different parameter semantics. `operation` string param tries to select among them, but merge needs direction (AXIS_TIME/AXIS_VOLTAGE), multiply needs factorT/factorV, offset needs offsetT/offsetV. | Single schema can't properly validate all three |

---

## Actual-System Limits To Encode

These are hardware/firmware constraints from the manual and user-provided system limits that should be documented in atom schemas, caution fields, or validation logic.

### Timing Constraints

| # | Constraint | Value | Where To Encode | Source |
|---|---|---|---|---|
| L1 | Min generated pulse width (no measurement) | **10 ns** | `C_atom_wgfmu_add_vectors` and pattern atoms | User constraint + manual Table 1-6 (10 ns time resolution) |
| L2 | Min generated pulse width (with measurement) | **100 ns** | `C_atom_wgfmu_set_measure_event` | User constraint + manual Table 1-7/1-8 (settling + measurement window) |
| L3 | 5 ns internal sampling rate | 5 ns (fixed hardware clock) | `C_atom_wgfmu_set_measure_event` averaging note | Manual PDF 131 |
| L4 | `setMeasureEvent` interval range | 10 ns – 1.34217728 s, 10 ns resolution | `C_atom_wgfmu_set_measure_event` | Manual PDF 130–131, error 3312 |
| L5 | `setMeasureEvent` average range | 0 or 10 ns – 0.020971512 s, 10 ns res, ≤ interval | `C_atom_wgfmu_set_measure_event` | Manual PDF 131, error 3315/3316 |
| L6 | Inter-sequence delay | 50 ns (10 ns last voltage + 40 ns next initial) | `C_atom_wgfmu_add_sequence` | Manual PDF 86–87 |
| L7 | Adjacent events changing averaging | ≥ 100 ns between start times | `C_atom_wgfmu_set_measure_event` | Manual PDF 131 |
| L8 | Consecutive range change spacing | ≥ 2 µs for 3+ consecutive range events | `C_atom_wgfmu_set_range_event` | Manual PDF 134 |
| L9 | Vector dTime range | 10 ns – 10995.116 s, 10 ns resolution | `C_atom_wgfmu_add_vectors` | Manual PDF 88–89, error 3311 |
| L10 | Time resolution (universal) | 10 ns for all time parameters | All WGFMU C atoms | Manual PDF 24 |
| L11 | Force/measure delay range | ±50 ns, 625 ps resolution | `C_atom_wgfmu_configure_force_measure_delay` | Manual PDF 105, 129 |
| L12 | Range change time | < 150 µs | `C_atom_wgfmu_set_range_event` | Manual PDF 22 (supplemental) |

### Voltage Limits

| # | Constraint | Value | Where To Encode | Source |
|---|---|---|---|---|
| L13 | Max pulse voltage | **±10 V** (Vpp = 10 V) | All WGFMU force atoms; pattern validation | User constraint + manual Table 4-2 |
| L14 | Force voltage ranges | 3V: ±3 V; 5V: ±5 V; −10V: −10..0 V; +10V: 0..+10 V | `C_atom_wgfmu_configure_force_measure_ranges` | Manual PDF 142, 146 |
| L15 | PG mode max range | 3 V or 5 V only; ±10 V not available | `C_atom_wgfmu_set_operation_mode`, range atoms | Manual PDF 146 (Table 4-6) |
| L16 | PG 50 Ω output halving | Output divided by 50 Ω source impedance into 50 Ω load | `C_atom_wgfmu_set_operation_mode` PG note | Manual PDF 14 |
| L17 | No compliance feature | WGFMU has no output current limiter | All WGFMU force atoms — caution | Manual PDF 14 |
| L18 | RSU SMU path max | ±25 V / ±100 mA on RSU "From SMU" terminal | `B_atom_output_wgfmu_connect` note | Manual PDF 18 |

### Memory / Data Budget

| # | Constraint | Value | Where To Encode | Source |
|---|---|---|---|---|
| L19 | Hardware memory | ~4 M data points/channel (typical, not guaranteed) | `C_atom_wgfmu_set_measure_event`, `C_atom_wgfmu_execute` | Manual PDF 24, 131 |
| L20 | RAW data expansion | raw_count = points × (1 + int(average / 5 ns)) | `C_atom_wgfmu_set_measure_event` rdata parameter | Manual PDF 151 |
| L21 | Max vectors per pattern | 2048 | `C_atom_wgfmu_add_vectors`, `C_atom_wgfmu_create_pattern` | Manual PDF 24 |
| L22 | Max sequences per channel | 512 | `C_atom_wgfmu_add_sequence` | Manual PDF 24 |
| L23 | Max loop count | 1 – 1,099,511,627,776 (~10^12) | `C_atom_wgfmu_add_sequence` | Manual PDF 86 |

### Current Measurement Timing (from Manual Table 1-7)

| DUT Current | Range | Min Pulse Width | Settling Time | Min Meas Window |
|---|---|---|---|---|
| 10 mA | 10 mA | 145 ns | 125 ns | 20 ns |
| 1 mA | 1 mA | 240 ns | 200 ns | 40 ns |
| 100 µA | 100 µA | 950 ns | 820 ns | 130 ns |
| 10 µA | 10 µA | 6.8 µs | 5.8 µs | 1 µs |
| 1 µA | 1 µA | 38.7 µs | 37 µs | 1.64 µs |
| 100 nA | 1 µA | 47 µs | 37 µs | 10 µs |

These should be encoded as a reference lookup in `C_atom_wgfmu_set_measure_event` or a shared timing-constraint table so agents can validate measurement feasibility against pulse width.

### Environmental / Physical

| # | Constraint | Value | Where To Encode | Source |
|---|---|---|---|---|
| L24 | Load capacitance limit | ≤ 25 pF for specified accuracy | WGFMU system caution | Manual PDF 19 |
| L25 | Cable length affects min rise/fall | 16 ns (1.5 m), 32 ns (3 m), 56 ns (5 m) | Pattern/pulse construction guidance | Manual PDF 23 |
| L26 | Jitter / skew | Jitter < 1 ns; inter-ch skew < 3 ns (no ESD) | Multi-channel timing note | Manual PDF 22 |

---

## Keep As Existing / No New Atom Needed

| Item | Reason |
|---|---|
| `A_atom_wgfmu_set_warning_level` covers `setWarningLevel` | `getWarningLevel` readback is low-priority; can be deferred or folded into `get_status` |
| `A_atom_wgfmu_export_ascii` | Well-placed as A atom; critical for preflight validation |
| `B_atom_lifecycle_wgfmu_abort` | Correct as B-class safety/abort |
| `B_atom_output_wgfmu_connect` / `disconnect` | Correct as B-class output control |
| `B_atom_calibration_wgfmu_self_calibration` | Correct as B-class calibration |
| `B_atom_policy_wgfmu_treat_warnings_as_errors` | Correct as B-class policy |
| `C_atom_wgfmu_read_force_values` | Correct placement — measurement-adjacent readback |
| `C_atom_wgfmu_read_measurement_values_partial` | Good for event-specific reads (Example 8 pattern) |
| `C_atom_wgfmu_configure_alwg_cycle` | Acceptable convenience wrapper over pattern + sequence |
| Pattern-level readback APIs (`getPatternForceValue*`, `getPatternMeasureTime*`, `getPatternInterpolatedForceValue`) | Low priority — offline setup verification; could be deferred to P2. Covered by `exportAscii` for most validation needs |
| FeFET/NVM workflows (PUND, endurance, retention, wake-up) | These are **recipes/flows**, not raw atoms. Should NOT be atoms. Manual has no FeFET content; build from primitives at flow layer. |
| WGFMU session in `A_atom_wgfmu_*` vs flex `A_atom_flex_*` | Correct separation — WGFMU has its own instrument library session distinct from GPIB/VISA flex session |

---

## Uncertain Items Requiring Parent/User Arbitration

| # | Item | Options | Recommendation |
|---|---|---|---|
| U1 | `waitUntilCompleted` classification | (a) A atom — pure synchronization/wait, no output change. (b) Part of `C_atom_wgfmu_execute` as optional blocking mode. (c) Separate C helper atom. | Lean toward **A atom** since it's a blocking poll that does not alter measurement state. |
| U2 | `C_atom_wgfmu_transform_pattern` bundling | (a) Keep as one atom with `operation` selector. (b) Split into 3 atoms: `merge_patterns`, `multiply_pattern`, `offset_pattern`. | Lean toward **split** — each has fundamentally different parameter sets. Current single schema can't validate properly. |
| U3 | `C_atom_wgfmu_configure_force_measure_ranges` scope | (a) Expand to include `setMeasureMode` + `setMeasureVoltageRange`. (b) Split: keep ranges as-is, add separate `set_measure_mode` and `set_measure_voltage_range` atoms. | Lean toward **split** (option b) per arbitration principle: don't over-bundle when sub-functions have distinct effects (e.g. setting CURRENT mode auto-changes voltage range to 5 V). |
| U4 | `A_atom_wgfmu_clear` classification | Manual says `clear` removes software setup (patterns/sequences/errors/warnings) but does NOT change hardware state. Currently A. Could argue B because it removes measurement setup. | Keep as **A** — it doesn't touch output/hardware state. Consistent with arbitration boundary rules. |
| U5 | Should `dc_force_measure` bundle both force and measure? | (a) Keep bundled as convenience C atom. (b) Split into `dc_force_voltage` and `dc_measure_value` separate atoms. | Keep **bundled** but fix API names. The DC workflow is deliberately simplified (no patterns/sequences). Separate `dc_measure_value` should still be added (C5 above) for measure-without-force-change use cases. |

---

## Recommended Patch Set

### Priority 0 — Critical schema fixes (fix before any real use)

| # | Action | Details |
|---|---|---|
| R1 | **Fix `C_atom_wgfmu_set_measure_event` params** | Add `points: int`, `interval: float` (10 ns – 1.342 s), `average: float` (0 or 10 ns – 20.97 ms), `rdata: str` ("averaged" / "raw"). Add `eventEndTime` formula in notes. Add 100 ns inter-event spacing constraint. Add ~4M memory budget note. |
| R2 | **Fix `C_atom_wgfmu_dc_measure_averaged` params** | Add `points: int` (1–65535), `interval_ticks: int` (1–65535, × 5 ns). Fix basis to `WGFMU_dcmeasureAveragedValue`. |
| R3 | **Fix `C_atom_wgfmu_dc_force_measure` basis** | Change basis from `WGFMU_measureCurrent` to `WGFMU_dcforceVoltage` + `WGFMU_dcmeasureValue`. |
| R4 | **Fix `C_atom_wgfmu_configure_force_measure_delay` basis** | Change basis from "WGFMU_setMeasureEvent, delay parameters" to `WGFMU_setForceDelay` + `WGFMU_setMeasureDelay`. Add ±50 ns / 625 ps constraints. |
| R5 | **Fix `C_atom_wgfmu_set_trigger_event`** | Add `duration` parameter (float, seconds). |

### Priority 1 — Missing critical atoms

| # | Action | Details |
|---|---|---|
| R6 | **Add `C_atom_wgfmu_set_measure_mode`** | `channel_id`, `mode` (VOLTAGE/CURRENT). Note CURRENT requires Fast IV/DC and auto-sets voltage range to 5 V. |
| R7 | **Add `C_atom_wgfmu_set_measure_voltage_range`** | `channel_id`, `range` (5V/10V). Not effective in CURRENT mode. |
| R8 | **Add `C_atom_wgfmu_set_trigger_out_mode`** | `channel_id`, `mode` (DISABLE/START_EXECUTION/START_SEQUENCE/START_PATTERN/EVENT), `polarity` (POSITIVE/NEGATIVE). Required before `set_trigger_event`. |
| R9 | **Add `C_atom_wgfmu_set_measure_enabled`** | `channel_id`, `enabled` (ENABLE/DISABLE). Needed for force-only channels. |
| R10 | **Add `A_atom_wgfmu_get_measure_value_size`** | `channel_id` → `measured_count`, `total_count`. Essential for progress polling. |
| R11 | **Add `B_atom_lifecycle_wgfmu_abort_channel`** | `channel_id`. Per-channel abort. |

### Priority 2 — Schema hardening and limits encoding

| # | Action | Details |
|---|---|---|
| R12 | **Add ALWG limits to `add_vectors`** | Schema note: max 2048 vectors/pattern; dTime 10 ns – 10995.116 s; 10 ns resolution. |
| R13 | **Add ALWG limits to `add_sequence`** | Max 512 sequences/channel; count up to ~10^12; 50 ns inter-sequence delay note. Fix `repeat_count` type to float. |
| R14 | **Add constant mappings to operation mode/range atoms** | Map string params to API constant integers in all WGFMU C atoms (operation mode, force range, measure range, current range, rdata, trigger mode). |
| R15 | **Add ±10 V / Vpp=10 V constraint documentation** | Caution note on all force-related WGFMU atoms about max ±10 V hardware limit plus no-compliance warning. |
| R16 | **Add measurement timing reference table** | Encode Table 1-7 / Table 1-8 settling times as structured data accessible to agents for pulse width validation. |
| R17 | **Add range event constraints to `set_range_event`** | ≥2 µs for 3+ consecutive changes; must be outside averaging period; current range constants 6001–6005. |
| R18 | **Document memory budget formula** | Add RAW expansion formula and ~4M limit to `set_measure_event` and `execute` notes. |

### Priority 3 — Lower-priority additions

| # | Action | Details |
|---|---|---|
| R19 | **Add `A_atom_wgfmu_get_measure_event_info`** | Event setup readback for preflight validation. |
| R20 | **Add `A_atom_wgfmu_wait_until_completed`** or fold into execute | Blocking wait — classification pending U1. |
| R21 | **Add `C_atom_wgfmu_dc_measure_value`** | Single-point DC measurement. |
| R22 | **Split `C_atom_wgfmu_transform_pattern`** | Into `merge_patterns`, `multiply_pattern`, `offset_pattern` — pending U2. |
| R23 | **Add `A_atom_wgfmu_get_interpolated_force_value`** | Data correlation readback (used by writeResults3). |
| R24 | **Add `A_atom_wgfmu_get_measure_times`** | Sequence-level timing readback. |

---

## Summary Counts

| Category | Count |
|---|---|
| Existing WGFMU atoms (A+B+C) | 42 |
| Confident missing A atoms | 5 |
| Confident missing B atoms | 1 |
| Confident missing C atoms | 5 |
| Parameter/schema gaps (critical) | 3 |
| Parameter/schema gaps (high) | 5 |
| Parameter/schema gaps (medium) | 6 |
| Actual-system limits not encoded | 26 |
| Uncertain items for arbitration | 5 |
| Recommended patches (P0 critical) | 5 |
| Recommended patches (P1 missing atoms) | 6 |
| Recommended patches (P2 schema hardening) | 7 |
| Recommended patches (P3 lower priority) | 6 |
| **Total recommended patches** | **24** |

### Top 5 Recommended Additions

1. **Fix `C_atom_wgfmu_set_measure_event`** — missing 4 of 7 parameters makes it non-functional
2. **Add `C_atom_wgfmu_set_trigger_out_mode`** — without this, trigger events are incomplete
3. **Add `C_atom_wgfmu_set_measure_mode`** — required for any current measurement workflow
4. **Add `A_atom_wgfmu_get_measure_value_size`** — essential for progress polling in reliability/stress runs
5. **Fix `C_atom_wgfmu_configure_force_measure_delay`** — wrong API basis makes it misleading
