# Atom Taxonomy — Opus 4.6 Max Audit

Date: 2026-06-22

## Taxonomy Rationale

### Three-Level Naming: `{A|B}_atom_{subsystem}_{action}`

The naming scheme uses three levels separated by underscores after the class prefix:

1. **Class prefix** — `A_atom` or `B_atom` (unchanged from prior convention)
2. **Subsystem** — identifies which hardware/software interface the atom targets:
   - `b1500` — B1500A direct GPIB/VISA instrument commands
   - `wgfmu` — B1530A WGFMU instrument library API
   - `easyexpert` — EasyEXPERT remote control SCPI interface
3. **Action** — concise verb/noun describing the operation (e.g., `connect`, `get_status`, `self_test`)

**Why this scheme:**
- Subsystem-first ordering groups tools naturally in sorted lists and MCP tool catalogs.
- Avoids numeric ordering that couples naming to creation sequence.
- Keeps names short enough for MCP tool discovery while being unambiguous.
- Scales to future subsystems (e.g., `spgu`, `prober`) without restructuring.

### Classification Principles

**A atoms** — read/discover/connect/session/context/result-buffer/error/status/logging/catalog/selection:
- Do not directly change DUT output, safety-critical state, calibration state, or measurement execution.
- EasyEXPERT application/preset selection is A-class (changes software context, not DUT state).
- WGFMU status/error/warning queries, log file management, and setup export are A-class.

**B atoms** — reset/init/abort/self-test/self-calibration/diagnostics/zero/disable/channel-output/path/correction/phase-compensation/standby/zero-cancel/safety-gates:
- WGFMU `connect`/`disconnect` (channel output enable/disable) and `abort` are B-class.
- Compliance limits are NOT standalone B atoms; they are parameters of DV/DI/WV/WI source commands, deferred to C atoms.

## Old Name → New Name Mapping

### A Atoms — b1500 (18 renamed)

| Old Name | New Name |
|---|---|
| `A_atom_connect_b1500` | `A_atom_b1500_connect` |
| `A_atom_disconnect_b1500` | `A_atom_b1500_disconnect` |
| `A_atom_identify_b1500` | `A_atom_b1500_identify` |
| `A_atom_list_installed_modules` | `A_atom_b1500_list_modules` |
| `A_atom_get_instrument_status` | `A_atom_b1500_get_status` |
| `A_atom_query_current_settings` | `A_atom_b1500_query_settings` |
| `A_atom_read_error_queue` | `A_atom_b1500_read_error_queue` |
| `A_atom_lookup_error_message` | `A_atom_b1500_lookup_error` |
| `A_atom_read_status_byte` | `A_atom_b1500_read_status_byte` |
| `A_atom_wait_operation_complete` | `A_atom_b1500_wait_opc` |
| `A_atom_set_data_format` | `A_atom_b1500_set_data_format` |
| `A_atom_configure_timestamp` | `A_atom_b1500_configure_timestamp` |
| `A_atom_reset_timestamp` | `A_atom_b1500_reset_timestamp` |
| `A_atom_read_timestamp` | `A_atom_b1500_read_timestamp` |
| `A_atom_clear_output_buffer` | `A_atom_b1500_clear_output_buffer` |
| `A_atom_query_output_buffer_count` | `A_atom_b1500_query_buffer_count` |
| `A_atom_read_output_buffer` | `A_atom_b1500_read_output_buffer` |
| `A_atom_configure_service_request` | `A_atom_b1500_configure_srq` |

### A Atoms — wgfmu (3 renamed)

| Old Name | New Name |
|---|---|
| `A_atom_wgfmu_clear_setup` | `A_atom_wgfmu_clear` |
| `A_atom_wgfmu_open_log_file` | `A_atom_wgfmu_open_log` |
| `A_atom_wgfmu_close_log_file` | `A_atom_wgfmu_close_log` |

### A Atoms — easyexpert (5 renamed)

| Old Name | New Name |
|---|---|
| `A_atom_easyexpert_identify_remote_host` | `A_atom_easyexpert_identify` |
| `A_atom_easyexpert_wait_operation_complete` | `A_atom_easyexpert_wait_opc` |
| `A_atom_easyexpert_fetch_latest_result` | `A_atom_easyexpert_fetch_result` |
| `A_atom_easyexpert_list_application_tests` | `A_atom_easyexpert_list_app_tests` |
| `A_atom_easyexpert_select_application_test` | `A_atom_easyexpert_select_app_test` |
| `A_atom_easyexpert_get_selected_test_name` | `A_atom_easyexpert_get_selected_name` |

### B Atoms — b1500 (28 renamed)

| Old Name | New Name |
|---|---|
| `B_atom_reset_instrument` | `B_atom_b1500_reset` |
| `B_atom_initialize_instrument` | `B_atom_b1500_initialize` |
| `B_atom_abort_operation` | `B_atom_b1500_abort` |
| `B_atom_run_self_test` | `B_atom_b1500_self_test` |
| `B_atom_run_self_calibration` | `B_atom_b1500_self_calibration` |
| `B_atom_run_diagnostics` | `B_atom_b1500_diagnostics` |
| `B_atom_set_auto_calibration` | `B_atom_b1500_set_auto_calibration` |
| `B_atom_enable_channels` | `B_atom_b1500_enable_channels` |
| `B_atom_disable_channels` | `B_atom_b1500_disable_channels` |
| `B_atom_zero_outputs` | `B_atom_b1500_zero_outputs` |
| `B_atom_zero_all_outputs` | `B_atom_b1500_zero_all_outputs` |
| `B_atom_confirm_zero_outputs` | `B_atom_b1500_confirm_zero` |
| `B_atom_check_interlock_status` | `B_atom_b1500_check_interlock` |
| `B_atom_run_preflight_checks` | `B_atom_b1500_preflight` |
| `B_atom_recover_zeroed_outputs` | `B_atom_b1500_recover_zeroed` |
| `B_atom_set_smu_filter` | `B_atom_b1500_set_smu_filter` |
| `B_atom_set_adc_zero` | `B_atom_b1500_set_adc_zero` |
| `B_atom_set_asu_path` | `B_atom_b1500_set_asu_path` |
| `B_atom_set_asu_1pa_range` | `B_atom_b1500_set_asu_1pa_range` |
| `B_atom_set_asu_indicator` | `B_atom_b1500_set_asu_indicator` |
| `B_atom_set_scuu_path` | `B_atom_b1500_set_scuu_path` |
| `B_atom_set_scuu_indicator` | `B_atom_b1500_set_scuu_indicator` |
| `B_atom_set_cmu_correction_state` | `B_atom_b1500_set_cmu_correction` |
| `B_atom_measure_cmu_correction_data` | `B_atom_b1500_measure_cmu_correction` |
| `B_atom_set_cmu_phase_compensation_mode` | `B_atom_b1500_set_cmu_phase_mode` |
| `B_atom_perform_cmu_phase_compensation` | `B_atom_b1500_perform_cmu_phase_comp` |
| `B_atom_clear_cmu_correction_data` | `B_atom_b1500_clear_cmu_correction` |
| `B_atom_perform_qscv_offset_cancel` | `B_atom_b1500_qscv_offset_cancel` |

### B Atoms — wgfmu (2 renamed)

| Old Name | New Name |
|---|---|
| `B_atom_wgfmu_do_self_calibration` | `B_atom_wgfmu_self_calibration` |
| `B_atom_wgfmu_do_self_test` | `B_atom_wgfmu_self_test` |

### B Atoms — easyexpert (1 renamed)

| Old Name | New Name |
|---|---|
| `B_atom_easyexpert_abort_selected_measurement` | `B_atom_easyexpert_abort_measurement` |

## Added Atoms and Source Basis

### New A Atoms (12 added)

| Atom | Source Basis | Why Added |
|---|---|---|
| `A_atom_wgfmu_export_ascii` | B1530A `WGFMU_exportAscii` (PDF 99-100) | Debug/validation CSV export for offline waveform verification; essential tooling gap. |
| `A_atom_wgfmu_get_completed_event_count` | B1530A `WGFMU_getCompletedMeasureEventSize` (PDF 102) | Progress monitoring for long stress/measurement sequences; A-class read-only status. |
| `A_atom_wgfmu_is_event_completed` | B1530A `WGFMU_isMeasureEventCompleted` (PDF 126-127) | Event-level completion check with data index; A-class read-only. |
| `A_atom_easyexpert_get_workspace_name` | EasyEXPERT `:WORKspace:NAME?` (PDF 441-442) | Workspace name readback for session context verification. |
| `A_atom_easyexpert_set_device_tag` | EasyEXPERT `[:BENCh]:TAG` (PDF 427-432) | Device ID/sample metadata for wafer automation; explicitly documented. |
| `A_atom_easyexpert_get_device_tag` | EasyEXPERT `[:BENCh]:TAG?` (PDF 427-432) | Read-pair for set_device_tag. |
| `A_atom_easyexpert_set_repeat_count` | EasyEXPERT `[:BENCh]:COUNt` (PDF 427-432) | Batch repeat count; key for automated measurement loops. |
| `A_atom_easyexpert_get_repeat_count` | EasyEXPERT `[:BENCh]:COUNt?` (PDF 427-432) | Read-pair for repeat count. |
| `A_atom_easyexpert_reset_repeat_count` | EasyEXPERT `[:BENCh]:COUNt:RESet` (PDF 427-432) | Count reset before batch. |
| `A_atom_easyexpert_set_app_test_param` | EasyEXPERT `[:BENCh][:SELected]:NUMBer` (PDF 427-432) | Numeric parameter editing for application tests; explicitly documented remote API. |
| `A_atom_easyexpert_set_app_test_string` | EasyEXPERT `[:BENCh][:SELected]:STRing` (PDF 427-432) | String/resource parameter editing; used for SMU resource assignment. |
| `A_atom_easyexpert_load_setup` | EasyEXPERT `[:BENCh]:LOAD[:SETup]` (PDF 427-432) | Load XTS/XTR setup data; file-to-remote bridge. |

### New B Atoms (4 added)

| Atom | Source Basis | Why Added |
|---|---|---|
| `B_atom_b1500_set_series_resistor` | B1500A `SSR` (Table 2-13 initial settings, PDF 179) | Series resistor on/off; paired with FL (filter); initial setting off. |
| `B_atom_wgfmu_connect` | B1530A `WGFMU_connect` (PDF 91) | Enables WGFMU channel + RSU output. B-class: channel output control, analogous to CN. |
| `B_atom_wgfmu_disconnect` | B1530A `WGFMU_disconnect` (PDF 96) | Disables WGFMU channel + RSU output. B-class: channel output control, analogous to CL. |
| `B_atom_wgfmu_abort` | B1530A `WGFMU_abort` (PDF 85) | Stops WGFMU sequencer. B-class: abort/safety primitive. |

## Atoms Intentionally NOT Added

| Candidate | Source | Reason Deferred |
|---|---|---|
| `LIM` / `LIM?` (compliance limit) | B1500A PDF 443 | Per classification guidance: compliance limits are parameters of DV/DI/WV/WI source commands, deferred to C atoms. `LIM` sets a per-channel compliance limit but is tightly coupled to measurement configuration. |
| `CMM` (measurement operation mode) | B1500A PDF 379 | C-class: selects compliance/current/voltage/force-side measurement mode; part of measurement setup, not safety/state-control. |
| `ACH` (channel number remapping) | B1500A PDF 352 | A-class candidate but specialized; station profile tooling should handle channel mapping outside atom layer. |
| `AIT` / `AV` / `AAD` (ADC integration time, averaging, ADC selection) | B1500A PDF 350-353 | C-class: measurement configuration parameters, not A/B scope. |
| `RI` / `RV` / `RC` / `RM` (measurement ranging) | B1500A PDF 499-504 | C-class: measurement range setup. |
| `MM` / `XE` (measurement mode / execute) | B1500A PDF 469, 569 | C-class: measurement mode selector and execution trigger. |
| `DV` / `DI` / `WV` / `WI` (force/sweep source) | B1500A various | C-class: source/measurement commands. |
| `TI` / `TV` / `TIV` (high-speed spot measurement) | B1500A PDF 534, 544 | C-class: direct measurement triggers. |
| `PAD` (parallel ADC) | B1500A PDF 481 | C-class: measurement optimization. |
| SPGU commands (`SIM`, `SPM`, `SPT`, `SPV`, etc.) | B1500A PDF 504-521 | C-class: SPGU pulse setup and execution. SPGU path/mode atoms may become B-class when SPGU module support is designed. |
| `WGFMU_execute` / `WGFMU_waitUntilCompleted` | B1530A PDF 99, 141 | C-class: measurement execution. |
| `WGFMU_createPattern` / `addVector` / `addSequence` etc. | B1530A various | C-class: waveform construction. |
| `WGFMU_setOperationMode` / range/mode functions | B1530A various | C-class: measurement configuration. |
| `WGFMU_dcforceVoltage` / `dcmeasureValue` | B1530A PDF 95-96 | C-class: DC measurement. |
| `[:BENCh][:SELected]:RUN` (execute measurement) | EasyEXPERT PDF 427-432 | C-class: measurement execution trigger. |
| `:RESult:FETch:SIBLings?` / `:RESult:RECycle` | EasyEXPERT PDF 436-438 | Low priority; sibling results and recycling are convenience features. Can be added later. |
| `[:BENCh]:LOAD[:SETup]` query response | EasyEXPERT PDF 427-432 | Block-data-based; real implementation needs SCPI block encoding. Added the set-side atom. |
| Trigger I/O commands (`TGP`, `TGPC`, etc.) | B1500A PDF 527+ | Borderline B/C-class; trigger configuration is tightly coupled to measurement mode and should be designed holistically with C atoms. |
| DIO commands (`ERM`, `ERC`) | B1500A PDF 397+ | Specialized; external relay/DIO control. Defer until fixture automation design. |
| ER* expander/selector commands | B1500A PDF 397-434 | Specialized for B1505A/B1506A/B1507A module selectors and expanders. Defer until specific module support is designed. |
| `HVSMUOP` (HVSMU operation mode) | B1500A PDF 438 | Specialized HVSMU mode switching. Defer until HVSMU module support. |

## Tool Count Summary

| Category | Count |
|---|---|
| A atoms — b1500 | 18 |
| A atoms — wgfmu | 16 |
| A atoms — easyexpert | 26 |
| **Total A atoms** | **60** |
| B atoms — b1500 | 29 |
| B atoms — wgfmu | 7 |
| B atoms — easyexpert | 6 |
| **Total B atoms** | **42** |
| **Grand Total** | **102** |

## Remaining Gaps / Questions

1. **SPGU B atoms**: When SPGU module support is designed, `SIM` (operation mode), SPGU output control, and SPGU trigger commands may need B-class atoms. Currently deferred.

2. **Trigger I/O atoms**: `TGP`, `TGPC`, `TGSI`, `TGSO`, `TGXO`, `TGMO` configure trigger ports. These are borderline B/C-class and should be designed together with C measurement atoms.

3. **Program memory atoms**: `SCR`, `END`, `DO`, `RU`, `LST?`, `VAR` manage internal program memory. These don't fit A/B classification cleanly; they may need a utility category.

4. **`INTLKVTH` (set) vs `INTLKVTH?` (query)**: Currently only the query is exposed via `B_atom_b1500_check_interlock`. The `INTLKVTH` set command could be a safety-critical B atom for configuring the interlock threshold. Deferred pending safety policy decision.

5. **EasyEXPERT `[:BENCh][:SELected]:NUMBer?` / `:STRing?` (query)**: Read-sides of app test parameters not added; add when parameter verification workflows are needed.

6. **WGFMU `getMeasureValueSize`**: Count of available measurement data points; A-class. Not added because it's tightly coupled to data retrieval (C-class workflow). Add when C atoms are designed.

7. **`CORRDT` / `CORRDT?` / `CORRL` / `CORRL?` / `DCORR` / `DCORR?`**: CMU correction data management commands. More detailed than the existing correction atoms. Defer to CMU workflow design.

8. **EasyEXPERT CALibration `FULLrange` / `PLC`**: More specific zero-cancel calibration commands. The current atoms cover ON/OFF/MEASure/STATe which is the primary workflow.
