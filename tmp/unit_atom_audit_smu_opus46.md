# Unit Atom Audit — MPSMU / HRSMU

Date: 2026-06-22
Auditor: opus-4.6-max sub-agent
Focus: B1511B MPSMU (×2), B1517A HRSMU (×2)
System constraint: real external voltage ±42 V, max current ±100 mA

## Current Coverage Summary

### Module Representation

| Module | Model | Slots in fake_data | SMU_LIMITS defined | safety_limits.example | station-profile.example |
|--------|-------|--------------------|--------------------|----------------------|------------------------|
| MPSMU  | B1511B | slot 1 (1 unit) | 100 V / 0.1 A | 100 V / 0.1 A | 2 units (gate + drain) |
| HRSMU  | B1517A | slot 2 (1 unit) | 100 V / 0.1 A | 100 V / 0.1 A | not in example profile |

**Problem 1:** `fake_data.py` has only 1× MPSMU and 1× HRSMU. Real system has 2× each.
**Problem 2:** Station profile example has 2× MPSMU but 0× HRSMU. Inconsistent with real hardware.
**Problem 3:** None of the atom tools, schemas, or precondition lists distinguish MPSMU from HRSMU. Both share the generic `C_atom_smu_*` surface and identical compliance defaults. This is partly correct (same GPIB command set), but model-specific ranging, resolution, and low-current capabilities are invisible.

### A Atom Coverage for MPSMU/HRSMU

A atoms are interface/session/readback. The existing `flex` A atoms are module-generic, which is correct — there is no MPSMU/HRSMU-specific A-class GPIB command. The key commands (`*IDN?`, `UNT?`, `ERRX?`, `*STB?`, `*LRN?`, `FMT`, `TSC`/`TSR`/`TSQ`, `BC`, `NUB?`, `*SRE`, `*OPC?`) are all covered.

**SMU-relevant A gap count: 2** (see details below)

### B Atom Coverage for MPSMU/HRSMU

B atoms cover safety/state-control. Key ones exist: `CN`, `CL`, `DZ`, `RZ`, `WZ?`, `*RST`, `IN`, `AB`, `*TST?`, `*CAL?`, `DIAG?`, `FL`, `SSR`, `AZ`, `CM`, `SAP`/`SAR`/`SAL` (ASU), `SSP`/`SSL` (SCUU).

**SMU-relevant B gap count: 3** (see details below)

### C Atom Coverage for MPSMU/HRSMU

C atoms cover measurement/source primitives. 27 SMU C atoms exist covering: spot, sweep, pulsed, sampling, multi-channel, quasi-pulse, search, signal monitor, timer-start variants.

**SMU-relevant C gap count: 5 confident + 3 uncertain** (see details below)

---

## Confident Missing A_atoms

### A-1: `A_atom_flex_query_smu_settings` (readback of per-channel SMU state)

**What:** Readback of per-channel source/range/compliance/filter/series-resistor state using `*LRN?` type parameters specific to SMU channels. The existing `A_atom_flex_query_settings` sends a bare `*LRN?` which returns format/timestamp/auto-cal state — it does NOT return per-channel SMU source, range, or compliance information. The `*LRN?` command supports type values 0–56 with per-channel per-parameter readback.

**Why MPSMU/HRSMU needs it:** After error recovery, recipe transitions, or DUT contact/disconnect events, the agent needs to verify channel-level state (current source value, active range, compliance setting). This is especially important for HRSMU where the active current range determines measurement resolution.

**Basis:** `*LRN? type` with type values covering DV/DI output (type 0), measurement range (types 2–7), integration/ADC setup, compliance, etc. See PDF 446–452 / printed 4-129 to 4-135.

**Classification:** A (read-only query, no state change).

**Confidence:** HIGH — the existing `A_atom_flex_query_settings` is too coarse for SMU-specific verification.

### A-2: `A_atom_flex_query_compliance_status` (compliance reached readback)

**What:** Read whether a specific channel has reached compliance. The `LIM?` command (PDF 443 / printed 4-126) returns the current/voltage compliance status of a channel. The `LOP?` command returns the compliance polarity/output side of a channel.

**Why MPSMU/HRSMU needs it:** Compliance monitoring is essential for safe MPSMU/HRSMU operation — when sourcing voltage, compliance-limited current indicates the DUT may be drawing more current than expected. The high-speed spot measurement status codes (N/T/C/W/X) also indicate compliance, but `LIM?` provides explicit per-channel query without requiring a measurement cycle.

**Basis:** `LIM?`, `LOP?` — PDF 443–444 / printed 4-126 to 4-127.

**Classification:** A (read-only query).

**Confidence:** HIGH — no existing atom covers explicit compliance status readback.

---

## Confident Missing B_atoms

### B-1: `B_atom_output_smu_set_compliance_limit` (set compliance polarity/limit)

**What:** The `LIM` command (PDF 443 / printed 4-126) sets the current compliance polarity/limit for SMU channels. This is distinct from the compliance parameter embedded in `DV`/`DI`/`WV`/`WI` — `LIM` restricts the overall compliance polarity independently.

**Why MPSMU/HRSMU needs it:** For leakage-sensitive HRSMU work, compliance polarity control prevents the SMU from searching through both polarities and potentially disturbing the DUT. For MPSMU, compliance limiting is a safety-layer constraint.

**Basis:** `LIM chnum,comp_polarity[,current_limit]` — PDF 443 / printed 4-126.

**Classification:** B (safety/policy constraint on output behavior).

**Confidence:** HIGH — `LIM` is listed in the command summary under "ASU / SCUU / SMU Conditioning" (PDF 321) alongside `FL`, `SSR`, etc. It belongs with the B-class SMU conditioning atoms.

### B-2: `B_atom_output_smu_set_output_switch_type` (normal vs high-speed output switching)

**What:** The `OS` command (PDF 478 / printed 4-161) and `OSX` command (PDF 479 / printed 4-162) control the output switch type — normal or extended (with trigger). While `OS` is listed as "obsolete", `OSX` provides output switch control with external trigger synchronization.

**Why MPSMU/HRSMU needs it:** For timing-sensitive pulsed measurements on MPSMU or synchronized output-on events with external trigger.

**Basis:** `OS`, `OSX` — PDF 478–479 / printed 4-161 to 4-162.

**Classification:** B (output state change).

**Confidence:** MEDIUM — `OS` is marked obsolete; `OSX` may be niche. Include as B but lower priority.

### B-3: `B_atom_safety_b1500_set_interlock_threshold` (INTLKVTH set)

**What:** The `INTLKVTH` command sets the interlock voltage threshold. Currently only `B_atom_safety_b1500_check_interlock` exists (which reads `INTLKVTH?`), but there is no atom to SET the threshold.

**Why MPSMU/HRSMU needs it:** Real system constraint is ±42 V. The interlock threshold should be configurable by the safety layer. Default after `*RST` is 42 V per safety conventions, but explicit setting is a safety-critical B-class operation.

**Basis:** `INTLKVTH voltage` — PDF 441 / printed 4-124.

**Classification:** B (safety policy setting).

**Confidence:** HIGH — the read side exists (`check_interlock` reads `INTLKVTH?`); the write side is missing.

---

## Confident Missing C_atoms

### C-1: `C_atom_smu_configure_qscv` (quasi-static CV)

**What:** Quasi-static CV (MM 13) uses SMU charge integration to measure capacitance without a CMU. Commands: `QSV`, `QST`, `QSM`, `QSL`, `QSO`, `QSC`, `QSR`, `QSZ`. Currently zero C atoms cover QSCV setup. Only `B_atom_correction_qscv_offset_cancel` (QSZ) exists as a B atom.

**Why MPSMU/HRSMU needs it:** QSCV is a core SMU-based capacitance technique. HRSMU with its superior low-current resolution is the ideal module for QSCV leakage compensation and charge measurement. MPSMU can also perform QSCV but with lower current resolution.

**Basis:** `QSV`, `QST`, `QSM`, `QSL`, `QSO`, `QSC`, `QSR` — PDF 493–499 / printed 4-176 to 4-182. MM 13 detail: PDF 115–118 / printed 2-27 to 2-30.

**Classification:** C (measurement configuration and execution).

**Recommended split:**
- `C_atom_smu_configure_qscv` — set `QSV`, `QST`, `QSM`, `QSL`, `QSO`, `QSC`, `QSR`
- `C_atom_smu_execute_qscv` — execute MM 13 + XE

**Confidence:** HIGH — QSCV is a documented MM mode (13) with specific required commands. Complete gap.

### C-2: `C_atom_smu_configure_staircase_sweep_with_pulsed_bias` (MM 5)

**What:** MM 5 combines a staircase sweep on one channel with pulsed bias on another. Required commands: `WV`/`WI`, `PT`, `PV`/`PI`, `WM`. Currently no C atom covers this composite mode explicitly. The existing `C_atom_smu_configure_staircase_sweep` handles MM 2 only, and `C_atom_smu_configure_pulsed_spot_source` handles PV/PI but not the MM 5 combination.

**Why MPSMU/HRSMU needs it:** MM 5 is commonly used for MOSFET Id-Vd with pulsed gate bias — a core MPSMU/HRSMU use case.

**Basis:** MM 5 — PDF 97–99 / printed 2-10 to 2-12.

**Classification:** C (measurement configuration).

**Confidence:** HIGH — MM 5 is a distinct measurement mode not covered by any existing C atom.

### C-3: Trigger I/O configuration atoms

**What:** Trigger system configuration commands `TGP`, `TGPC`, `TGSI`, `TGSO`, `TGXO`, `TGMO`, `TM`, `PAX`, `WSX`. These configure trigger input/output ports, trigger polarity, step-trigger synchronization, and trigger-based pause/wait.

**Why MPSMU/HRSMU needs it:** For synchronized multi-SMU measurements (e.g., gate MPSMU sweep with drain MPSMU measurement triggered per step), trigger configuration is essential. Also needed for SPGU-SMU synchronization when MPSMU measures during SPGU pulsing (HRSMU for leakage after stress).

**Basis:** PDF 162–174 / printed 2-74 to 2-86; trigger commands PDF 521–533 / printed 4-204 to 4-216.

**Classification:** C (measurement configuration) for `C_atom_smu_configure_trigger_io`; the trigger commands configure measurement-quality-affecting parameters.

**Recommended split:**
- `C_atom_smu_configure_trigger_io` — `TGP`, `TGPC`, `TGSI`, `TGSO`, `TGXO`, `TGMO`
- `C_atom_smu_set_trigger_mode` — `TM`

**Confidence:** HIGH — trigger configuration is entirely absent from the current atom surface.

### C-4: `C_atom_smu_set_parallel_measurement` (PAD, PCH)

**What:** `PAD` enables parallel A/D conversion for faster multi-channel measurement. `PCH` sets which channels participate in parallel measurement. Conditions: high-speed ADC, non-pulsed mode, fixed measurement range.

**Why MPSMU/HRSMU needs it:** With 2× MPSMU + 2× HRSMU, multi-channel measurements benefit from PAD to reduce total measurement time. The agent currently has no way to enable parallel measurement.

**Basis:** `PAD` — PDF 480–481 / printed 4-163 to 4-164. `PCH` — PDF 482 / printed 4-165.

**Classification:** C (measurement configuration affecting speed/quality).

**Confidence:** HIGH — PAD is documented in the command summary (PDF 322) under measurement setup.

### C-5: `C_atom_smu_configure_high_speed_spot` (HSS)

**What:** The `HSS` command (PDF 436 / printed 4-119) selects which high-speed spot measurement is set as a return-to-standard measurement. This affects the behavior of `TI`/`TV`/`TIV` when used in high-speed ADC mode.

**Why MPSMU/HRSMU needs it:** The existing `C_atom_smu_measure_high_speed_spot` calls `TI`/`TV`/`TIV` but does not configure `HSS` beforehand. HSS is a prerequisite for controlled high-speed spot behavior.

**Basis:** `HSS` — PDF 436 / printed 4-119.

**Classification:** C (measurement configuration).

**Confidence:** MEDIUM-HIGH — HSS is used in high-speed spot workflows but may be implicit in many simple cases.

---

## Parameter / Schema Gaps In Existing Atoms

### P-1: `C_atom_smu_force_voltage` — missing `comp_polarity` and `irange` parameters

The `DV` command syntax is: `DV chnum,vrange,voltage[,Icomp[,comp_polarity[,irange]]]`.
Current atom schema has: `channel`, `voltage_v`, `compliance_a`, `range_mode`.
Missing: `comp_polarity` (limit compliance to positive/negative), `irange` (explicit compliance current range).

**Impact for MPSMU/HRSMU:** HRSMU leakage work often requires compliance polarity control to avoid bipolar compliance search. Explicit `irange` matters when the compliance range differs from measurement range.

### P-2: `C_atom_smu_force_current` — missing `comp_polarity` parameters

The `DI` command syntax is: `DI chnum,irange,current[,Vcomp[,comp_polarity]]`.
Current atom schema has: `channel`, `current_a`, `compliance_v`, `range_mode`.
Missing: `comp_polarity`.

### P-3: `C_atom_smu_configure_staircase_sweep` — missing sweep type (linear/log)

The `WV`/`WI` commands support linear and log sweep modes (PDF 567–568). The current atom has `source`, `start`, `stop`, `steps`, `compliance` but no `sweep_type` parameter for linear vs logarithmic.

**Impact for MPSMU/HRSMU:** Log sweeps are common for MOSFET sub-threshold Id-Vg characterization — a primary HRSMU use case.

### P-4: `C_atom_smu_configure_staircase_sweep` — compliance polarity not exposed

Same issue as P-1: the `WV`/`WI` compliance parameter should support polarity constraints.

### P-5: `C_atom_smu_configure_integration` — ADC type parameter lacks model-specific validation

The `AAD` command selects high-speed vs high-resolution ADC. HRSMU benefits most from high-resolution ADC for low-current measurements. The current schema accepts any string for `adc` but does not validate or guide model-specific choices. The `AIT` command has different integration time options depending on ADC type.

**Recommended:** Add validation hint or enum constraint: `adc` should be `"high_speed"` or `"high_resolution"`. Add note that HRSMU + high-resolution ADC is the recommended combination for sub-nA measurements.

### P-6: `C_atom_smu_set_measurement_ranging` — missing MPSMU/HRSMU range table awareness

Current schema accepts `range_mode` (auto/fixed) and `range_value` (float) but does not encode:
- MPSMU current ranges: 1 nA to 100 mA (ranges 11–19 in Table 4-2/4-3)
- HRSMU current ranges: 10 pA to 100 mA (ranges 9–19 in Table 4-2/4-3); with ASU: 1 pA (range 8)
- MPSMU voltage ranges: 0.5 V to 100 V (ranges 2–12)
- HRSMU voltage ranges: 0.5 V to 100 V (ranges 2–12)

The difference is critical: HRSMU's 10 pA range gives ~0.01 pA resolution, while MPSMU's lowest is 1 nA range (~1 pA resolution). With ASU, HRSMU reaches 1 pA range (~0.001 pA resolution).

**Recommended:** Schema should include validation hints or at least model-specific notes. The agent needs to know which ranges are available for each module type when selecting measurement ranges.

### P-7: `C_atom_smu_configure_sweep_timing` — missing `trigger_delay_s` parameter

The `WT` command syntax is: `WT hold,delay[,Sdelay[,Tdelay[,Mdelay]]]`.
Current atom has `hold_s`, `delay_s`, `step_delay_s`. Missing: `trigger_delay_s` (Tdelay) and `measure_delay_s` (Mdelay for CMU sweep timing variant WTDCV).

### P-8: `C_atom_smu_configure_sampling` — missing `post_output` and `hold_base` parameters

The sampling measurement commands include `MSP` (post-measurement source output), and `MT` supports `hold_base` (hold time for base source). Current atom bundles `MCC`, `ML`, `MT`, `MSC`, `MI`, `MV`, `MSP` but the schema parameters are limited to `channels`, `interval_s`, `samples`, `source_channel`. Missing: log/linear mode, hold times, post-output, abort function settings.

### P-9: System-wide ±42 V constraint not represented in any atom schema

The real system operates with ±42 V external voltage limit. No atom, precondition, or schema validation enforces this. The `safety_limits.example.yaml` has `require_interlock_above_v: 42.0` and `MPSMU max_voltage_v: 100.0` / `HRSMU max_voltage_v: 100.0`, but the C atom default parameters use values that could exceed 42 V (e.g., `C_atom_smu_configure_staircase_sweep` `stop: float = 1.0` is fine but the schema doesn't prevent `stop=50.0`).

**Recommended:** Add a profile-level constraint that flows/recipes enforce, not individual atom parameters. But atom schemas should include `max_voltage_v` and `max_current_a` as safety hints derived from the active station profile.

---

## Model-Specific MPSMU vs HRSMU Notes

### Resolution and Sensitivity

| Parameter | MPSMU (B1511B) | HRSMU (B1517A) | Impact on Atoms |
|-----------|---------------|----------------|-----------------|
| Min current range | 1 nA (range 11) | 10 pA (range 9); 1 pA with ASU (range 8) | `C_atom_smu_set_measurement_ranging` needs module-aware validation |
| Current resolution at min range | ~1 pA | ~0.01 pA (10 fA); 0.001 pA with ASU | HRSMU is 100-1000× more sensitive |
| Max voltage (module spec) | ±100 V | ±100 V | Same but system-limited to ±42 V |
| Max current | ±100 mA | ±100 mA | Same |
| Voltage ranges | 0.5 V, 2 V, 5 V, 20 V, 40 V, 100 V | Same set | Identical |
| Self-test error codes | 3001–3701 (shared HP/MPSMU range) | 4001–4701 (HRSMU-specific range) | `B_atom_diagnostic_b1500_self_test` / error lookup should note different code ranges |
| ASU compatibility | Yes (B1511B) | Yes (B1517A) | Both support ASU but HRSMU benefits more for pA/fA work |
| High-resolution ADC benefit | Moderate | Critical for sub-nA measurements | `C_atom_smu_configure_integration` should recommend HR ADC for HRSMU leakage work |

### Use-Case-Specific Gaps

**HRSMU leakage measurement workflow:**
1. Needs ASU path switching → `B_atom_routing_asu_set_path` exists ✓
2. Needs 1 pA auto-range enable → `B_atom_routing_asu_set_1pa_range` exists ✓
3. Needs high-resolution ADC selection → `C_atom_smu_configure_integration` exists ✓ (but no HRSMU guidance)
4. Needs low-current ranging → `C_atom_smu_set_measurement_ranging` exists ✓ (but no HRSMU-specific validation)
5. Needs compliance polarity control → **MISSING** in DV/DI atoms (P-1, P-2 above)
6. Needs ADC zero for offset cancel → `B_atom_calibration_smu_set_adc_zero` exists ✓

**MPSMU standard MOSFET characterization workflow:**
1. Id-Vg sweep → `C_atom_smu_configure_staircase_sweep` exists ✓
2. Id-Vd family curves → needs multi-sweep or synchronous sweep, both exist ✓
3. Log sweep for sub-threshold → `C_atom_smu_configure_staircase_sweep` exists but missing log mode (P-3)
4. Pulsed IV → `C_atom_smu_configure_pulsed_spot_source` and `C_atom_smu_configure_pulsed_sweep` exist ✓
5. Multi-channel synchronized → `C_atom_smu_configure_synchronous_sweep_source` exists ✓
6. Trigger synchronization → **MISSING** (C-3 above)

### Current Range Tables (for validation reference)

**MPSMU (B1511B) current measurement ranges per Table 4-3:**

| Range code | Range value | Auto/Fixed |
|-----------|------------|-----------|
| 11 | 1 nA | Limited auto / fixed |
| 12 | 10 nA | Limited auto / fixed |
| 13 | 100 nA | Limited auto / fixed |
| 14 | 1 µA | Limited auto / fixed |
| 15 | 10 µA | Limited auto / fixed |
| 16 | 100 µA | Limited auto / fixed |
| 17 | 1 mA | Limited auto / fixed |
| 18 | 10 mA | Limited auto / fixed |
| 19 | 100 mA | Limited auto / fixed |

**HRSMU (B1517A) current measurement ranges per Table 4-3:**

| Range code | Range value | Auto/Fixed |
|-----------|------------|-----------|
| 8 | 1 pA (ASU required) | Limited auto / fixed |
| 9 | 10 pA | Limited auto / fixed |
| 10 | 100 pA | Limited auto / fixed |
| 11 | 1 nA | Limited auto / fixed |
| 12 | 10 nA | Limited auto / fixed |
| 13 | 100 nA | Limited auto / fixed |
| 14 | 1 µA | Limited auto / fixed |
| 15 | 10 µA | Limited auto / fixed |
| 16 | 100 µA | Limited auto / fixed |
| 17 | 1 mA | Limited auto / fixed |
| 18 | 10 mA | Limited auto / fixed |
| 19 | 100 mA | Limited auto / fixed |

---

## Keep As Existing / No New Atom Needed

The following are confirmed adequate for MPSMU/HRSMU use:

| Existing Atom | Why It Works |
|---------------|-------------|
| `A_atom_flex_connect` | Module-generic; UNT? returns MPSMU/HRSMU type strings for discovery |
| `A_atom_flex_list_modules` | Returns module type per slot including MPSMU/HRSMU |
| `A_atom_flex_get_status` | Composite status is module-generic |
| `A_atom_flex_read_error_queue` | Error queue is mainframe-level |
| `A_atom_flex_wait_opc` | Module-generic sync |
| `A_atom_flex_set_data_format` | Module-generic parser config |
| `A_atom_flex_configure_timestamp` | Module-generic |
| `B_atom_lifecycle_b1500_reset` | Resets all modules including MPSMU/HRSMU |
| `B_atom_lifecycle_b1500_initialize` | Same |
| `B_atom_safety_b1500_abort` | Module-generic abort |
| `B_atom_safety_b1500_check_interlock` | Reads INTLKVTH? — relevant for ±42 V limit |
| `B_atom_safety_b1500_preflight` | Aggregate readiness check |
| `B_atom_output_b1500_enable_channels` | CN for SMU channels |
| `B_atom_output_b1500_disable_channels` | CL for SMU channels |
| `B_atom_output_b1500_zero_outputs` | DZ for safety |
| `B_atom_output_b1500_zero_all` | DZ + CL emergency |
| `B_atom_output_b1500_confirm_zero` | WZ? for safe disconnect |
| `B_atom_output_b1500_recover_zeroed` | RZ after DZ |
| `B_atom_output_smu_set_filter` | FL — applicable to both |
| `B_atom_output_smu_set_series_resistor` | SSR — applicable to both |
| `B_atom_calibration_smu_set_adc_zero` | AZ — applicable to both |
| `B_atom_calibration_b1500_self_calibration` | *CAL? covers all modules |
| `B_atom_diagnostic_b1500_self_test` | *TST? covers all modules (error codes differ per module) |
| `B_atom_policy_b1500_set_auto_calibration` | CM — module-generic |
| `B_atom_routing_asu_set_path` | SAP — relevant for both with ASU |
| `B_atom_routing_asu_set_1pa_range` | SAR — critical for HRSMU + ASU |
| `B_atom_routing_asu_set_indicator` | SAL — minor but exists |
| `B_atom_routing_scuu_set_path` | SSP — relevant for SMU+CMU SCUU path |
| `C_atom_smu_set_measurement_mode` | MM — generic SMU mode selector |
| `C_atom_smu_set_measurement_operation` | CMM — per-channel operation |
| `C_atom_smu_configure_integration` | AAD/AIT/AV/PAD — generic but needs HRSMU guidance notes |
| `C_atom_smu_set_measurement_ranging` | RI/RV/RM — generic but needs range validation (see P-6) |
| `C_atom_smu_force_voltage` | DV — works for both (needs parameter additions P-1) |
| `C_atom_smu_force_current` | DI — works for both (needs parameter additions P-2) |
| `C_atom_smu_measure_high_speed_spot` | TI/TV/TIV — works for both |
| `C_atom_smu_configure_staircase_sweep` | WV/WI — works (needs log mode P-3) |
| `C_atom_smu_configure_sweep_timing` | WT — works (needs trigger delay P-7) |
| `C_atom_smu_execute` | XE — module-generic |
| `C_atom_smu_read_measurement_data` | Buffer read — module-generic |
| All pulsed/sampling/multi-channel C atoms | Work for both module types |

---

## Uncertain Items Requiring Parent/User Arbitration

### U-1: `ACH` channel mapping — A or B?

The `ACH` command (PDF 352 / printed 4-35) remaps channel numbers. This could be A (session/context change) or B (state change affecting measurement routing). The current atom surface does not include it.

**Question:** Is `ACH` needed for this system? With 2× MPSMU + 2× HRSMU in fixed slots, channel mapping may not be needed. If the system uses ACH for DUT-specific pin remapping, it needs an atom.

**Recommendation:** Defer unless user confirms channel remapping is needed.

### U-2: `WNCC` multi-channel sweep count — separate C atom or parameter?

`WNCC` (PDF not individually verified; listed in command summary under "Multi-channel Pulse/Sweep Setup") specifies the number of channels for multi-channel sweep. Currently `C_atom_smu_configure_multi_sweep` uses `WNX` but does not mention `WNCC`.

**Question:** Is `WNCC` needed as a parameter in the existing multi-sweep atom, or is it implicit from the channel count in `MM`?

### U-3: `WNU?` multi-channel sweep step count query — A atom?

`WNU?` queries the number of sweep steps. This is a read-only query that could be A-class.

**Question:** Does the agent need to query step count, or is it always known from the setup?

### U-4: Should GNDU have any atom representation?

The B1500A GNDU (ground unit) is topology/reference. The arbitration document rejects GNDU as a C atom category. But GNDU channels can participate in `CN`/`CL` and `DZ`. For MPSMU/HRSMU multi-terminal measurements (e.g., 4-terminal MOSFET), GNDU may be the reference node.

**Question:** Should there be a note in `B_atom_output_b1500_enable_channels` that GNDU channels are valid `CN` targets?

### U-5: Program memory atoms (`SCR`/`END`/`DO`/`RU`/`LST?`/`VAR`)

Program memory allows storing up to 100 command sequences on the B1500A. These could enable autonomous batch runs. No atoms exist for program memory.

**Question:** Is program memory a target for this system? If so, it needs A atoms (list, query) and B/C atoms (store, execute).

**Recommendation:** Defer — program memory is a legacy feature and the MCP agent orchestration likely supersedes it.

---

## Recommended Patch Set

### Priority 0 (before first real hardware use)

| # | Type | Name | Key Commands | Rationale |
|---|------|------|-------------|-----------|
| 1 | A atom | `A_atom_flex_query_smu_settings` | `*LRN? type` | Per-channel state verification |
| 2 | B atom | `B_atom_safety_b1500_set_interlock_threshold` | `INTLKVTH` | ±42 V system constraint |
| 3 | Schema fix | `C_atom_smu_force_voltage` | `DV` | Add `comp_polarity`, `irange` params |
| 4 | Schema fix | `C_atom_smu_force_current` | `DI` | Add `comp_polarity` param |
| 5 | Schema fix | `C_atom_smu_configure_staircase_sweep` | `WV`/`WI` | Add `sweep_type` (linear/log) and `comp_polarity` |
| 6 | Data fix | `fake_data.py` | — | Update to 2×MPSMU + 2×HRSMU |

### Priority 1 (core measurement enablement)

| # | Type | Name | Key Commands | Rationale |
|---|------|------|-------------|-----------|
| 7 | C atom | `C_atom_smu_configure_qscv` | `QSV`, `QST`, `QSM`, `QSL`, `QSO`, `QSC`, `QSR` | QSCV is critical for HRSMU CV work |
| 8 | C atom | `C_atom_smu_execute_qscv` | `MM 13`, `XE` | QSCV execution |
| 9 | C atom | `C_atom_smu_configure_trigger_io` | `TGP`, `TGPC`, `TGSI`, `TGSO`, `TGXO`, `TGMO` | Multi-SMU sync |
| 10 | C atom | `C_atom_smu_set_trigger_mode` | `TM` | Trigger mode selector |
| 11 | A atom | `A_atom_flex_query_compliance_status` | `LIM?`, `LOP?` | Compliance monitoring |
| 12 | B atom | `B_atom_output_smu_set_compliance_limit` | `LIM` | Safety constraint |
| 13 | Schema fix | `C_atom_smu_set_measurement_ranging` | `RI`, `RV` | Add MPSMU/HRSMU range validation hints |

### Priority 2 (advanced measurement)

| # | Type | Name | Key Commands | Rationale |
|---|------|------|-------------|-----------|
| 14 | C atom | `C_atom_smu_configure_staircase_sweep_pulsed_bias` | MM 5 setup | MOSFET pulsed bias sweep |
| 15 | C atom | `C_atom_smu_set_parallel_measurement` | `PAD`, `PCH` | Multi-SMU speed optimization |
| 16 | C atom | `C_atom_smu_configure_high_speed_spot` | `HSS` | Controlled high-speed spot behavior |
| 17 | Schema fix | `C_atom_smu_configure_sweep_timing` | `WT` | Add `trigger_delay_s` |
| 18 | Schema fix | `C_atom_smu_configure_sampling` | sampling commands | Add log/linear, hold times, post-output |

### Fake Data / Configuration Fixes

| # | File | Change |
|---|------|--------|
| 19 | `fake_data.py` | Add second MPSMU (slot 3) and second HRSMU (slot 4) to match real system |
| 20 | `station-profile.example.yaml` | Add HRSMU entries and match 2×MPSMU + 2×HRSMU |
| 21 | `safety_limits.example.yaml` | Add system-level `external_max_voltage_v: 42.0` distinct from module spec max |

---

## Summary Counts

| Category | Count |
|----------|-------|
| Missing A atoms (confident) | 2 |
| Missing B atoms (confident) | 3 |
| Missing C atoms (confident) | 5 |
| Parameter/schema gaps in existing atoms | 9 |
| Uncertain items for arbitration | 5 |
| Data/config fixes needed | 3 |
| **Total recommended patches** | **21** (P0: 6, P1: 7, P2: 5, Config: 3) |

Top 5 most impactful additions:
1. **QSCV atoms** (C-1) — enables a complete SMU-based capacitance workflow critical for HRSMU
2. **Interlock threshold setter** (B-3) — safety-critical for ±42 V system
3. **Compliance polarity params** (P-1, P-2) — essential for controlled HRSMU leakage work
4. **Log sweep mode** (P-3) — enables sub-threshold MOSFET characterization
5. **Trigger I/O atoms** (C-3) — enables synchronized multi-SMU measurement
