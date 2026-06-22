# Unit Atom Audit - B1520A MFCMU

Date: 2026-06-22
Auditor: Opus 4.6 Max
Scope: B1520A MFCMU (Multi-Frequency Capacitance Measurement Unit)
User actual constraints: frequency 1 kHz–1 MHz, DC bias ±25 V, correction/compensation/SCUU/leakage complexity.

---

## Current Coverage Summary

### A Atoms (status/readback) — MFCMU-relevant

No dedicated MFCMU A atoms exist. Generic flex A atoms cover session, identity, module
discovery, data format, buffer, timestamps, and error management. These are all usable
as-is for MFCMU workflows. However, **MFCMU-specific readback is absent**: there is no
atom to query correction state, correction frequency list, correction data, load standard
values, or phase compensation mode.

Existing generic A atoms used by CMU workflows:

| Atom | Role in MFCMU context |
|---|---|
| `A_atom_flex_connect` | Session open, module discovery |
| `A_atom_flex_list_modules` | Identify B1520A slot |
| `A_atom_flex_get_status` | Pre-measurement status |
| `A_atom_flex_read_error_queue` | Post-correction/measurement error check |
| `A_atom_flex_set_data_format` | FMT for CMU data parsing |
| `A_atom_flex_configure_timestamp` | TSC for C-t and sweep timestamps |
| `A_atom_flex_clear_output_buffer` | BC before measurement |
| `A_atom_flex_query_buffer_count` | NUB? for data readback |
| `A_atom_flex_read_output_buffer` | Data read |
| `A_atom_flex_wait_opc` | Sync after ADJ? / CORR? |

### B Atoms (safety/state-control/correction) — MFCMU-relevant

6 dedicated CMU B atoms exist, plus 2 SCUU routing atoms:

| Atom | Basis | Coverage status |
|---|---|---|
| `B_atom_correction_cmu_set_correction` | `CORRST` | ✓ Open/Short/Load enable/disable |
| `B_atom_correction_cmu_measure_data` | `CORR?` | ✓ Correction data measurement |
| `B_atom_correction_cmu_set_phase_mode` | `ADJ` | ✓ Phase compensation mode select |
| `B_atom_correction_cmu_perform_phase_comp` | `ADJ?` | ✓ Phase compensation execute |
| `B_atom_correction_cmu_clear` | `CLCORR` | ✓ Clear correction data |
| `B_atom_correction_qscv_offset_cancel` | `QSZ` | N/A for MFCMU (QSCV only) |
| `B_atom_routing_scuu_set_path` | `SSP` | ✓ SCUU path switching |
| `B_atom_routing_scuu_set_indicator` | `SSL` | ✓ SCUU indicator |

### C Atoms (measurement/source/config/execute) — MFCMU-specific

20 dedicated CMU C atoms exist:

| Atom | Basis | MM Mode | Coverage status |
|---|---|---|---|
| `C_atom_cmu_set_impedance_model` | `IMP` | all | ✓ |
| `C_atom_cmu_configure_signal` | `FC`, `ACV`, `DCV` | all | ✓ (gaps in params) |
| `C_atom_cmu_set_ranging_integration` | `RC`, `ACT` | all | ✓ (gaps in params) |
| `C_atom_cmu_configure_cv_dc_sweep` | `WDCV`, `WT`, `WM` | 18 | ⚠ wrong timing cmds |
| `C_atom_cmu_execute` | `XE` | generic | ✓ |
| `C_atom_cmu_measure_high_speed_spot` | `TC`, `TTC`, `TMACV`, `TMDCV` | none | ✓ |
| `C_atom_cmu_execute_spot_c` | `MM17`, `XE` | 17 | ✓ |
| `C_atom_cmu_execute_cv_dc_sweep` | `MM18`, `XE` | 18 | ✓ |
| `C_atom_cmu_configure_cf_sweep` | `WFC`, `WT`, `WM` | 22 | ⚠ wrong timing cmds |
| `C_atom_cmu_execute_cf_sweep` | `MM22`, `XE` | 22 | ✓ |
| `C_atom_cmu_configure_ac_level_sweep` | `WACV` | 23 | ⚠ missing timing/abort |
| `C_atom_cmu_execute_ac_level_sweep` | `MM`, `XE` | 23 | ⚠ should be `MM23` |
| `C_atom_cmu_configure_pulsed_spot_c` | `PT`, `PV`, `TC` | 19 | ❌ wrong basis cmds |
| `C_atom_cmu_execute_pulsed_spot_c` | `MM`, `XE` | 19 | ⚠ should be `MM19` |
| `C_atom_cmu_configure_pulsed_cv_sweep` | `PWDCV`, `PT` | 20 | ⚠ wrong pulse timing |
| `C_atom_cmu_execute_pulsed_cv_sweep` | `MM`, `XE` | 20 | ⚠ should be `MM20` |
| `C_atom_cmu_configure_ct_sampling` | `CT sampling` | 26 | ⚠ vague basis |
| `C_atom_cmu_execute_ct_sampling` | `MM`, `XE` | 26 | ⚠ should be `MM26` |
| `C_atom_cmu_measure_timer_start_ac_voltage` | `TACV` | none | ✓ |
| `C_atom_cmu_measure_timer_start_dc_voltage` | `TDCV` | none | ✓ |

**Totals: 20 C atoms, 6 B atoms, 0 dedicated A atoms.**

---

## Confident Missing A_atoms

| # | Proposed name | Basis command(s) | Rationale |
|---|---|---|---|
| A1 | `A_atom_flex_query_cmu_correction_status` | `CORRST?` | **Critical.** No way to read back which corrections (open/short/load) are currently enabled. Existing `B_atom_correction_cmu_set_correction` mentions `CORRST?` in its basis list but is a write-class atom, not a dedicated readback. A pure readback A atom is needed for pre-measurement verification. |
| A2 | `A_atom_flex_query_cmu_correction_freq_list` | `CORRL?` | **Important.** No way to verify which specific frequencies have correction data. Essential for checking that correction data covers the frequencies used in sweeps. |
| A3 | `A_atom_flex_query_cmu_correction_data` | `CORRDT?` | **Useful.** Allows reading back stored correction data for validation/export. Currently no atom wraps CORRDT? readback. |
| A4 | `A_atom_flex_query_cmu_load_standard` | `DCORR?` | **Useful for load correction.** Reads back the calibration reference values for the load correction standard. No current atom. |

**Count: 4 missing A atoms.**

---

## Confident Missing B_atoms

| # | Proposed name | Basis command(s) | Rationale |
|---|---|---|---|
| B1 | `B_atom_correction_cmu_add_frequency` | `CORRL` | **Critical.** Adds specific frequencies to the correction data set. Without this, correction data can only be measured at default frequencies, not at the actual test frequencies. The MFCMU correction workflow requires specifying frequencies with `CORRL` before `CORR?` to get correction data at those frequencies. This is especially important for the user's 1 kHz–1 MHz range. |
| B2 | `B_atom_correction_cmu_set_load_standard` | `DCORR` | **Important for load correction.** Sets calibration/reference values (Cp, G, or equivalent) for the load correction standard. Required when using load correction, which is needed for high-accuracy MFCMU measurements. |
| B3 | `B_atom_correction_cmu_set_correction_data` | `CORRDT` | **Useful for data transfer.** Directly sets correction data (e.g., from previously saved measurements). Allows restoring a known correction state without re-measuring open/short/load fixtures. |
| B4 | `B_atom_correction_cmu_measure_series_resistance` | `CORRSER?` | **Important for SCUU.** Performs series correction measurement and returns SCUU cable series resistance. This is specifically needed when using SCUU to compensate for cable resistance between SMU and MFCMU. Essential for the user's setup. |

**Count: 4 missing B atoms.**

---

## Confident Missing C_atoms

| # | Proposed name | Basis command(s) | MM mode | Rationale |
|---|---|---|---|---|
| C1 | `C_atom_cmu_set_monitor_output` | `LMN` | all | **Critical.** `LMN` enables output of actual CMU oscillator level and DC bias monitor data alongside impedance measurement results. Without this, the agent cannot verify that the actual AC signal level and DC bias match the set values — a key requirement for accurate CV measurements where DUT impedance can cause the actual applied levels to differ from programmed values. No existing atom covers LMN. |
| C2 | `C_atom_cmu_read_measurement_data` | output buffer decode | all | **Important.** Analogous to `C_atom_smu_read_measurement_data`. CMU measurement data has different output format (primary + secondary impedance parameters, optional LMN monitor data, frequency data for sweeps). No CMU-specific decode wrapper exists. Currently reliant on generic `A_atom_flex_read_output_buffer`. |

**Count: 2 missing C atoms.**

---

## Parameter / Schema Gaps In Existing Atoms

### Critical — Wrong Command Basis

| # | Atom | Issue | Fix |
|---|---|---|---|
| P1 | `C_atom_cmu_configure_pulsed_spot_c` | Basis lists `PT`, `PV`, `TC` — these are **SMU pulse** commands. CMU pulsed spot C (MM19) requires `PTDCV` (CMU pulse timing), `PDCV` (CMU pulsed DC bias), not SMU `PT`/`PV`. `TC` is correct only for the high-speed spot measurement path, not for the MM19/XE path. | Change basis to `["PTDCV", "PDCV"]`. Parameters should be `pulse_base_v`, `pulse_bias_v`, `pulse_width_s`, `pulse_period_s` matching PTDCV/PDCV parameter domains. |
| P2 | `C_atom_cmu_configure_pulsed_cv_sweep` | Basis lists `PWDCV`, `PT` — `PT` is the SMU pulse timing command. Should use `PTDCV` for CMU pulse timing. | Change `PT` → `PTDCV` in basis. |
| P3 | `C_atom_cmu_configure_cv_dc_sweep` | Basis lists `WT`, `WM` — these are **generic SMU sweep timing/abort** commands. The actual CMU DC bias sweep uses `WTDCV` (CMU sweep timing) and `WMDCV` (CMU sweep abort), which have different parameters (e.g., `WTDCV` includes a `Mdelay` parameter for measurement delay). | Change basis to `["WDCV", "WTDCV", "WMDCV"]`. Add `delay_s`, `step_delay_s`, `measure_delay_s` parameters. |
| P4 | `C_atom_cmu_configure_cf_sweep` | Basis lists `WT`, `WM` — should use `WTFC` and `WMFC` for C-f sweep specific timing and abort. | Change basis to `["WFC", "WTFC", "WMFC"]`. |
| P5 | `C_atom_cmu_configure_ct_sampling` | Basis is `["CT sampling"]` — vague placeholder. Actual commands are `MDCV` (DC bias for C-t sampling) and `MTDCV` (sampling timing: interval, points). | Change basis to `["MDCV", "MTDCV"]`. Add `dc_bias_v`, `interval_s`, `samples` as explicit parameters mapped to these commands. |

### Important — Missing Parameters

| # | Atom | Issue | Fix |
|---|---|---|---|
| P6 | `C_atom_cmu_configure_signal` | Missing `channel` parameter. The `FC`, `ACV`, `DCV` commands all take `chnum`. | Add `channel: int` parameter. |
| P7 | `C_atom_cmu_set_impedance_model` | Missing `channel` parameter. `IMP` takes `chnum, mode`. | Add `channel: int` parameter. |
| P8 | `C_atom_cmu_set_ranging_integration` | Missing `channel` parameter. `RC` takes `chnum, range`. Missing `range_value` for fixed range. | Add `channel: int`, `range_value: float = 0.0` parameters. |
| P9 | `C_atom_cmu_configure_cv_dc_sweep` | Missing `delay_s`, `step_delay_s`, `measure_delay_s` parameters from `WTDCV`. Missing abort mode parameters from `WMDCV`. | Add timing and abort params matching WTDCV/WMDCV. |
| P10 | `C_atom_cmu_configure_cf_sweep` | Missing timing parameters from `WTFC` and abort parameters from `WMFC`. | Add timing/abort params. |
| P11 | `C_atom_cmu_configure_ac_level_sweep` | Missing timing (`WTACV`) and abort (`WMACV`) parameters entirely. Basis only lists `WACV`. | Add basis `["WACV", "WTACV", "WMACV"]`, add timing/abort params. |

### Important — Wrong/Missing MM Mode Codes

| # | Atom | Issue | Fix |
|---|---|---|---|
| P12 | `C_atom_cmu_execute_ac_level_sweep` | Basis lists generic `MM` — should be `MM23`. | Fix basis to `["MM23", "XE"]`. |
| P13 | `C_atom_cmu_execute_pulsed_spot_c` | Basis lists generic `MM` — should be `MM19`. | Fix basis to `["MM19", "XE"]`. |
| P14 | `C_atom_cmu_execute_pulsed_cv_sweep` | Basis lists generic `MM` — should be `MM20`. | Fix basis to `["MM20", "XE"]`. |
| P15 | `C_atom_cmu_execute_ct_sampling` | Basis lists generic `MM` — should be `MM26`. | Fix basis to `["MM26", "XE"]`. |

### Moderate — Precondition Gaps

| # | Atom | Issue | Fix |
|---|---|---|---|
| P16 | `_CMU_PRE` (shared precondition list) | Missing `B_atom_routing_scuu_set_path`. SCUU path setup is a prerequisite for MFCMU measurements in typical configurations (MFCMU connects through SCUU). | Add `"B_atom_routing_scuu_set_path"` to `_CMU_PRE` or add a SCUU-aware variant `_CMU_SCUU_PRE`. |
| P17 | `_CMU_PRE` | Missing correction workflow atoms. Real MFCMU measurements should ideally have phase compensation and open/short correction as prerequisites. | Consider documenting correction as a recommended (not mandatory) precondition in atom schema. |
| P18 | `C_atom_cmu_configure_pulsed_spot_c` | Preconditions don't mention `C_atom_cmu_set_impedance_model` — pulsed spot C still needs IMP set. | Add `C_atom_cmu_set_impedance_model` to preconditions. |

---

## Actual-System Limits To Encode

| # | Limit | Source | Current representation | Recommended action |
|---|---|---|---|---|
| L1 | **Frequency range: 1 kHz to 5 MHz** (B1520A hardware). User interest: **1 kHz to 1 MHz**. | B1520A spec; user constraint | `C_atom_cmu_configure_signal` has `frequency_hz` param with no validation. | Add `min_frequency_hz=1000`, `max_frequency_hz=5_000_000` schema limits. Encode user system limit as soft-clip at 1 MHz. |
| L2 | **DC bias: MFCMU internal ±25 V**. ±100 V via SMU/SCUU path. User actual: **±25 V**. | PDF 348 DC bias ranges table; user constraint | `C_atom_cmu_configure_signal` has `dc_bias_v` param with no range check. | Add `max_dc_bias_internal_v=25.0`, document SMU/SCUU path required for >25 V. User limit matches MFCMU internal limit exactly. |
| L3 | **AC level: ~10 mV to 250 mV** (depends on frequency and impedance range). | PDF 347 AC level ranges table | `C_atom_cmu_configure_signal` has `ac_level_v=0.03` default with no range check. | Add `min_ac_level_v=0.010`, `max_ac_level_v=0.250` schema limits. Note frequency-dependent actual ranges. |
| L4 | **Impedance range depends on frequency.** Fixed ranges available: 50 Ω to 300 kΩ, but not all ranges available at all frequencies. | PDF 347 range tables | `C_atom_cmu_set_ranging_integration` has `range_mode: str` with no code validation. | Add structured `RC` range code enum/table reference. |
| L5 | **SCUU is prerequisite for MFCMU DC bias >25 V** and for Kelvin (4-terminal-pair) measurements. | Programming guide Ch2 CMU modes; SSP command | Not encoded in `_CMU_PRE` or any atom schema. | Encode SCUU path as prerequisite when DC bias exceeds ±25 V or Kelvin mode is needed. |
| L6 | **Correction data is frequency-specific.** Open/short/load correction data must cover the actual measurement frequencies. | `CORRL` / `CORR?` command pages | No atom enforces or recommends matching correction frequencies to measurement frequencies. | Add schema note / validation logic linking correction frequency list to sweep/spot frequency. |
| L7 | **Phase compensation requires open terminals at device side** and ~30 seconds execution time. | ADJ? command notes | `B_atom_correction_cmu_perform_phase_comp` mentions this in caution text. | Adequate, but add `expected_duration_s=30` and `fixture_condition="open_at_device_side"` to schema. |
| L8 | **Frequency resolution depends on range.** 0.001 Hz (1–10 kHz), 0.01 Hz (10–100 kHz), 0.1 Hz (100 kHz–1 MHz), 1 Hz (1–5 MHz). | PDF 347 | Not encoded anywhere. | Add frequency resolution table reference to `C_atom_cmu_configure_signal` or `C_atom_cmu_configure_cf_sweep`. |
| L9 | **MFCMU occupies 1 slot** and uses channel numbering `chnum = slot_number` (1–10). | UNT? / Table 4-1 | Implicit in `_CMU_PRE` module discovery. | No change needed, but document in atom skill that MFCMU channel is a single chnum. |
| L10 | **SMU leakage current through SCUU** can affect low-capacitance measurements. User noted this as a concern. | Application notes; user constraint | Not represented in any atom or precondition. | Add a leakage-check note or soft precondition to SCUU-path atoms. Consider a `B_atom_diagnostic_scuu_leakage_precheck` atom or at minimum a schema note. |

---

## Keep As Existing / No New Atom Needed

| Atom / Command | Rationale |
|---|---|
| `B_atom_lifecycle_b1500_reset` / `*RST` | Resets CMU to initial settings including IMP=Cp-G, RC=auto, ACT=auto, corrections off, ACV=0V/1kHz. Adequate. |
| `B_atom_lifecycle_b1500_initialize` / `IN` | Initializes CMU channels. Adequate. |
| `B_atom_safety_b1500_abort` / `AB` | Aborts CMU measurement. Adequate. |
| `B_atom_output_b1500_enable_channels` / `CN` | Enables MFCMU channel. Adequate. |
| `B_atom_output_b1500_disable_channels` / `CL` | Disables MFCMU channel. Adequate. |
| `B_atom_output_b1500_zero_outputs` / `DZ` | Zeroes MFCMU output. Adequate. |
| `B_atom_correction_cmu_clear` / `CLCORR` | Clears correction frequency list. Adequate. |
| `B_atom_correction_cmu_set_correction` / `CORRST` | Enable/disable open/short/load. Adequate (but schema needs `channel` param fix, see P-items). |
| `B_atom_correction_cmu_measure_data` / `CORR?` | Measure correction data. Adequate (but schema needs `correction_type` enum). |
| `B_atom_correction_cmu_set_phase_mode` / `ADJ` | Phase compensation mode. Adequate. |
| `B_atom_correction_cmu_perform_phase_comp` / `ADJ?` | Phase compensation execute. Adequate. |
| `B_atom_routing_scuu_set_path` / `SSP` | SCUU path switching. Adequate. |
| `B_atom_routing_scuu_set_indicator` / `SSL` | SCUU indicator. Adequate. |
| `C_atom_cmu_set_impedance_model` / `IMP` | Adequate (needs `channel` param fix). |
| `C_atom_cmu_configure_signal` / `FC,ACV,DCV` | Adequate (needs `channel` param and limit fixes). |
| `C_atom_cmu_set_ranging_integration` / `RC,ACT` | Adequate (needs param fixes). |
| `C_atom_cmu_execute` / `XE` | Generic execute. Adequate. |
| `C_atom_cmu_measure_high_speed_spot` / `TC,TTC,TMACV,TMDCV` | Adequate. |
| `C_atom_cmu_execute_spot_c` / `MM17,XE` | Adequate. |
| `C_atom_cmu_execute_cv_dc_sweep` / `MM18,XE` | Adequate. |
| `C_atom_cmu_execute_cf_sweep` / `MM22,XE` | Adequate. |
| `C_atom_cmu_measure_timer_start_ac_voltage` / `TACV` | Adequate. |
| `C_atom_cmu_measure_timer_start_dc_voltage` / `TDCV` | Adequate. |
| Generic flex A atoms (format, buffer, timestamp, error) | All adequate for MFCMU use. |

---

## Uncertain Items Requiring Parent/User Arbitration

| # | Item | Options | Auditor lean |
|---|---|---|---|
| U1 | **Should `B_atom_correction_cmu_set_correction` include `channel` as an explicit parameter?** `CORRST` takes `chnum, corr_type, mode`. Current atom has `correction_type` and `enabled` but no `channel`. | (a) Add channel param. (b) Leave as-is, assume channel from context. | (a) — explicit channel is safer for multi-MFCMU configs. |
| U2 | **Should `_CMU_PRE` include SCUU path as a hard prerequisite?** Some MFCMU setups don't use SCUU (direct cable). | (a) Add to `_CMU_PRE`. (b) Create `_CMU_SCUU_PRE` variant. (c) Leave as optional documented note. | (b) — create variant. Most real setups use SCUU but not all. |
| U3 | **Should `C_atom_cmu_read_measurement_data` be a new C atom or should the generic `A_atom_flex_read_output_buffer` + C-flow decode be sufficient?** | (a) New C atom. (b) Keep generic A + future C-flow decode. | (a) — CMU data format (primary+secondary+optional LMN+optional freq) is sufficiently different from SMU data to warrant a dedicated decode atom, parallel to `C_atom_smu_read_measurement_data`. |
| U4 | **Should correction workflow order be encoded as preconditions in atom schemas, or as a separate C-flow?** The canonical order is: phase comp → open correction → short correction → (optional load correction) → enable corrections. | (a) Encode in preconditions. (b) Future C-flow only. (c) Both. | (c) — preconditions give guidance at atom level; C-flow provides full recipe. |
| U5 | **Should leakage/SMU precheck for SCUU path get a dedicated B atom?** User noted CMU + SCUU + leakage as a key concern. | (a) New `B_atom_diagnostic_scuu_leakage_precheck`. (b) Document as caution in existing SCUU atom. (c) Defer to C-flow. | (b) for now — a dedicated diagnostic atom is premature without knowing the exact measurement procedure, but the concern should be documented. |
| U6 | **`C_atom_cmu_configure_pulsed_spot_c` parameter set.** After fixing basis to PTDCV/PDCV, should params include `pulse_base_v` and `pulse_measure_v` (from PDCV) or keep existing `pulse_bias_v` / `pulse_width_s`?** | (a) Align to PTDCV/PDCV parameter names. (b) Keep abstract names. | (a) — align to actual command parameters for clarity. |

---

## Recommended Patch Set

### Priority 0 — Critical fixes to existing atoms (schema correctness)

| Patch | Target | Change |
|---|---|---|
| **FIX-P1** | `C_atom_cmu_configure_pulsed_spot_c` | Change basis from `["PT", "PV", "TC"]` → `["PTDCV", "PDCV"]`. Update parameters to match PTDCV/PDCV. |
| **FIX-P2** | `C_atom_cmu_configure_pulsed_cv_sweep` | Change basis `"PT"` → `"PTDCV"`. |
| **FIX-P3** | `C_atom_cmu_configure_cv_dc_sweep` | Change basis from `["WDCV", "WT", "WM"]` → `["WDCV", "WTDCV", "WMDCV"]`. Add `delay_s`, `step_delay_s`, `measure_delay_s` params. |
| **FIX-P4** | `C_atom_cmu_configure_cf_sweep` | Change basis from `["WFC", "WT", "WM"]` → `["WFC", "WTFC", "WMFC"]`. |
| **FIX-P5** | `C_atom_cmu_configure_ct_sampling` | Change basis from `["CT sampling"]` → `["MDCV", "MTDCV"]`. Add `dc_bias_v` param. |
| **FIX-P12–15** | 4 execute atoms | Fix generic `"MM"` → specific `"MM23"`, `"MM19"`, `"MM20"`, `"MM26"` in respective basis lists. |

### Priority 1 — Missing atoms (high value for user workflows)

| Patch | New atom | Basis |
|---|---|---|
| **ADD-C1** | `C_atom_cmu_set_monitor_output` | `LMN` |
| **ADD-B1** | `B_atom_correction_cmu_add_frequency` | `CORRL` |
| **ADD-B4** | `B_atom_correction_cmu_measure_series_resistance` | `CORRSER?` |
| **ADD-A1** | `A_atom_flex_query_cmu_correction_status` | `CORRST?` |
| **ADD-A2** | `A_atom_flex_query_cmu_correction_freq_list` | `CORRL?` |

### Priority 2 — Schema enrichment and remaining missing atoms

| Patch | Target / New atom | Change |
|---|---|---|
| **FIX-P6–8** | 3 existing C atoms | Add `channel: int` parameter to `set_impedance_model`, `configure_signal`, `set_ranging_integration`. |
| **FIX-P9–11** | 3 configure atoms | Add timing/abort params from WTDCV/WMDCV, WTFC/WMFC, WTACV/WMACV. |
| **FIX-P16** | `_CMU_PRE` | Add SCUU-path-aware variant. |
| **ADD-C2** | `C_atom_cmu_read_measurement_data` | CMU-specific output buffer decode wrapper. |
| **ADD-B2** | `B_atom_correction_cmu_set_load_standard` | `DCORR` |
| **ADD-B3** | `B_atom_correction_cmu_set_correction_data` | `CORRDT` |
| **ADD-A3** | `A_atom_flex_query_cmu_correction_data` | `CORRDT?` |
| **ADD-A4** | `A_atom_flex_query_cmu_load_standard` | `DCORR?` |

### Priority 3 — Limit encoding

| Patch | Target | Change |
|---|---|---|
| **LIM-L1** | `C_atom_cmu_configure_signal` | Add `min_frequency_hz`, `max_frequency_hz` schema limits. |
| **LIM-L2** | `C_atom_cmu_configure_signal` | Add `max_dc_bias_internal_v=25.0` limit; document SCUU path for >25 V. |
| **LIM-L3** | `C_atom_cmu_configure_signal` | Add `min_ac_level_v`, `max_ac_level_v` limits. |
| **LIM-L4** | `C_atom_cmu_set_ranging_integration` | Add RC range code reference table. |
| **LIM-L8** | `C_atom_cmu_configure_signal` / cf_sweep | Add frequency resolution table reference. |

---

## Summary Statistics

| Category | Count |
|---|---|
| Existing MFCMU-relevant A atoms (generic) | ~10 |
| Existing MFCMU-relevant B atoms | 8 (6 CMU + 2 SCUU) |
| Existing MFCMU C atoms | 20 |
| **Missing A atoms** | **4** |
| **Missing B atoms** | **4** |
| **Missing C atoms** | **2** |
| **Critical basis/command errors in existing atoms** | **5** |
| **MM mode code errors** | **4** |
| **Missing parameter gaps** | **6** |
| **Precondition gaps** | **3** |
| **Actual-system limits to encode** | **10** |
| **Uncertain items for arbitration** | **6** |
| **Total recommended patches** | **~30** |
