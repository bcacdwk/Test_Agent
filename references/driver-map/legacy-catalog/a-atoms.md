# A Atom MCP Tools

A atoms are interface/session/context/readback/discovery tools. They should not change DUT output state. EasyEXPERT application/preset selection is A-class because it changes software context only and does not execute measurement.

```text
A_atom_<interface>_<action>
```

Interfaces: `flex`, `wgfmu`, `easyexpert`.

## A Class Atom Tools — flex

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `A_atom_flex_connect` | Open direct B1500A GPIB/VISA session and discover identity/modules. | `*IDN?`, `UNT?` | Fake only; real implementation must open VISA and create a lock. |
| `A_atom_flex_disconnect` | Close direct B1500A session. | Session lifecycle | Real flow should call `B_atom_output_b1500_zero_all` before closing. |
| `A_atom_flex_identify` | Query B1500A identity. | `*IDN?` | Query response buffer must be read immediately. |
| `A_atom_flex_list_modules` | Discover module inventory and channel map. | `UNT?` | Required before selecting channel-specific tools. |
| `A_atom_flex_get_status` | Composite status snapshot. | `UNT?`, `ERRX?`, `*STB?`, `*LRN?` | Does not replace individual diagnostic atoms. |
| `A_atom_flex_query_settings` | Read current settings. | `*LRN?` | Useful before/after failures. |
| `A_atom_flex_query_smu_settings` | Read per-channel SMU source/range/compliance state. | `*LRN? type` | Finer than `query_settings`; matters for HRSMU range/resolution verification. |
| `A_atom_flex_query_compliance_status` | Read per-channel compliance reached/polarity. | `LIM?`, `LOP?` | Read-only; setting compliance limit is B-class (`LIM`). |
| `A_atom_flex_read_error_queue` | Read instrument error queue. | `ERR?`, `ERRX?` | Use `ERRX?` for extended errors. |
| `A_atom_flex_lookup_error` | Lookup message for an error code. | `EMG?` | `EMG?` covers 0-999; extended errors need structured table / `ERRX?`. |
| `A_atom_flex_read_status_byte` | Read status byte. | `*STB?`, status-byte section | Bit 0=data ready, bit 1=wait, bit 3=interlock open per audited structured data. |
| `A_atom_flex_wait_opc` | Wait for operation completion. | `*OPC?` | Used by B1500 direct and EasyEXPERT remote workflows. |
| `A_atom_flex_set_data_format` | Set measurement output format. | `FMT` | Parser-facing communication atom. |
| `A_atom_flex_configure_timestamp` | Enable/disable timestamp output. | `TSC` | Parser/timing configuration. |
| `A_atom_flex_reset_timestamp` | Reset timestamp timer. | `TSR` | Use before time-sensitive acquisitions. |
| `A_atom_flex_read_timestamp` | Read current timestamp. | `TSQ` | Metadata/diagnostics. |
| `A_atom_flex_clear_output_buffer` | Clear measurement output buffer. | `BC` | Distinct from one-response query buffer. |
| `A_atom_flex_query_buffer_count` | Read output-buffer item count. | `NUB?` | Use before reading measurement data. |
| `A_atom_flex_read_output_buffer` | Read fake measurement output-buffer data. | output data buffer read | Real parser depends on `FMT`. |
| `A_atom_flex_configure_srq` | Configure SRQ/status-byte mask. | `*SRE` | Status-system atom. |
| `A_atom_flex_query_spgu_status` | Read SPGU execution/output status. | `SPST?` | Read-only status for SPGU C execution monitoring. |
| `A_atom_flex_query_spgu_setup` | Read SPGU PG/ALWG and pulse setup (incl. load). | `SIM?`, `SPRM?`, `SPM?`, `SPPER?`, `SPT?`, `SPV?`, `SER?` | Composite verification readback for SPGU source setup. |
| `A_atom_flex_query_spgu_pulse_switch` | Read SPGU pulse switch state. | `ODSW?` | Read-only relay/switch verification; setting is B-class. |
| `A_atom_flex_query_spgu_load_impedance` | Read SPGU DUT load impedance. | `SER?` | Affects achievable pulse voltage; setting is C-class (`SER`). |
| `A_atom_flex_query_spgu_trigger_output` | Read SPGU trigger-output config. | `STGP?` | Read-only; setter is C-class (`STGP`). |
| `A_atom_flex_query_spgu_open_comp` | Read SPGU open-compensation state. | `SOPC?` | Read-only; setter is B-class (`SOPC`). |
| `A_atom_flex_query_spgu_short_comp` | Read SPGU short-compensation state. | `SOVC?` | Read-only; setter is B-class (`SOVC`). |
| `A_atom_flex_query_spgu_alwg_pattern` | Read SPGU ALWG pattern data. | `ALW?` | Debug/verification; setter is C-class (`ALW`). |
| `A_atom_flex_query_spgu_alwg_sequence` | Read SPGU ALWG sequence assignment. | `ALS?` | Debug/verification; setter is C-class (`ALS`). |
| `A_atom_flex_query_selector_status` | Read module selector status. | `ERS?` | Read-only selector status before/after routing. |
| `A_atom_flex_query_selector_mode` | Read selector/DIO mode and SMU/PG path. | `ERMOD?`, `ERSSP?` | Routing verification for selector/SPGU workflows. |
| `A_atom_flex_query_cmu_correction_status` | Read MFCMU open/short/load correction enable state. | `CORRST?` | Read-only; enabling is B-class (`CORRST`). |
| `A_atom_flex_query_cmu_correction_freq_list` | Read frequencies that have correction data. | `CORRL?` | Verify correction covers sweep frequencies (1 kHz-1 MHz). |
| `A_atom_flex_query_cmu_correction_data` | Read stored MFCMU correction data. | `CORRDT?` | Read-only; setting data is B-class (`CORRDT`). |
| `A_atom_flex_query_cmu_load_standard` | Read MFCMU load-correction standard values. | `DCORR?` | Read-only; setting standard is B-class (`DCORR`). |

## A Class Atom Tools — wgfmu

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `A_atom_wgfmu_open_session` | Open WGFMU instrument-library session. | `WGFMU_openSession` | Uses GPIB resource string. |
| `A_atom_wgfmu_close_session` | Close WGFMU session. | `WGFMU_closeSession` | WGFMU library cleanup. |
| `A_atom_wgfmu_set_timeout` | Set WGFMU session timeout. | `WGFMU_setTimeout` | Self-test/cal may temporarily use longer timeout. |
| `A_atom_wgfmu_get_channel_ids` | Discover WGFMU channel IDs. | `WGFMU_getChannelIdSize`, `WGFMU_getChannelIds` | Channel ID convention is slot*100+channel. |
| `A_atom_wgfmu_get_status` | Read overall WGFMU execution status. | `WGFMU_getStatus` | A-class readback; useful for diagnostics and progress monitoring. |
| `A_atom_wgfmu_get_channel_status` | Read per-channel WGFMU execution status. | `WGFMU_getChannelStatus` | Returns channel-level progress/status without changing output state. |
| `A_atom_wgfmu_clear` | Clear WGFMU software setup. | `WGFMU_clear` | Does not imply hardware output cleanup. |
| `A_atom_wgfmu_open_log` | Open WGFMU error/warning log. | `WGFMU_openLogFile` | Useful for long WGFMU runs. |
| `A_atom_wgfmu_close_log` | Close WGFMU log file. | `WGFMU_closeLogFile` | Complements open log. |
| `A_atom_wgfmu_read_error` | Read one WGFMU error entry. | `WGFMU_getErrorSize`, `WGFMU_getError` | Size-first string API. |
| `A_atom_wgfmu_read_error_summary` | Read accumulated WGFMU errors. | `WGFMU_getErrorSummarySize`, `WGFMU_getErrorSummary` | Summary diagnostics. |
| `A_atom_wgfmu_set_warning_level` | Set WGFMU warning level. | `WGFMU_setWarningLevel` | Warning policy atom. |
| `A_atom_wgfmu_read_warning_summary` | Read accumulated WGFMU warnings. | `WGFMU_getWarningSummarySize`, `WGFMU_getWarningSummary` | Summary diagnostics. |
| `A_atom_wgfmu_export_ascii` | Export WGFMU setup summary to CSV. | `WGFMU_exportAscii` | Debug/validation atom for offline waveform verification. |
| `A_atom_wgfmu_get_completed_event_count` | Read completed measurement event count. | `WGFMU_getCompletedMeasureEventSize` | Progress monitoring for long sequences. |
| `A_atom_wgfmu_is_event_completed` | Check specific event completion. | `WGFMU_isMeasureEventCompleted` | Event-level progress check with data index/size. |
| `A_atom_wgfmu_get_measure_value_size` | Read measured vs total data count. | `WGFMU_getMeasureValueSize` | Progress polling + partial-read offsets. |
| `A_atom_wgfmu_get_measure_event_info` | Read measurement-event setup/attributes. | `WGFMU_getMeasureEvent*` | Preflight validation and offset math. |
| `A_atom_wgfmu_get_measure_times` | Read sequence-level measurement start times. | `WGFMU_getMeasureTimes` | Timing validation before execute. |
| `A_atom_wgfmu_get_interpolated_force_value` | Read interpolated applied voltage at a time. | `WGFMU_getInterpolatedForceValue` | Correlate measured data with waveform. |
| `A_atom_wgfmu_wait_until_completed` | Block until all connected channels complete. | `WGFMU_waitUntilCompleted` | Sync primitive; no output-state change. |

## A Class Atom Tools — easyexpert

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `A_atom_easyexpert_identify` | Identify EasyEXPERT remote host. | EasyEXPERT remote `*IDN?` | This is EasyEXPERT host identity, not direct B1500 identity. |
| `A_atom_easyexpert_clear_status` | Clear EasyEXPERT remote status/errors. | EasyEXPERT `*CLS` | Remote common command. |
| `A_atom_easyexpert_wait_opc` | Wait for EasyEXPERT remote operation. | EasyEXPERT `*OPC?` | Used after workspace/result operations. |
| `A_atom_easyexpert_read_system_error` | Read EasyEXPERT remote error queue. | `:SYSTem:ERRor:NEXT?` | FIFO remote error queue. |
| `A_atom_easyexpert_list_workspaces` | List EasyEXPERT workspaces. | `:WORKspace:CATalog?` | Remote workspace discovery. |
| `A_atom_easyexpert_open_workspace` | Open EasyEXPERT workspace. | `:WORKspace:OPEN` | Requires EasyEXPERT remote preconditions. |
| `A_atom_easyexpert_close_workspace` | Close active EasyEXPERT workspace. | `:WORKspace:CLOSe` | Confirm with `*OPC?` in real flow. |
| `A_atom_easyexpert_get_workspace_state` | Query workspace state. | `:WORKspace:STATe?` | Remote readiness check. |
| `A_atom_easyexpert_get_workspace_name` | Query active workspace name. | `:WORKspace:NAME?` | Workspace name readback. |
| `A_atom_easyexpert_set_result_format` | Set remote result format. | `:RESult:FORMat TEXT\|XTR` | Parser-facing EasyEXPERT atom. |
| `A_atom_easyexpert_fetch_result` | Fetch latest remote result block. | `:RESult:FETch[:LATest]?` | Real parser must strip SCPI definite-length block header. |
| `A_atom_easyexpert_list_app_tests` | List EasyEXPERT application tests. | `:BENCh:APPlication:CATalog?`, Table 9-1 | Discovery for recipe selection. |
| `A_atom_easyexpert_select_app_test` | Select an EasyEXPERT application-test definition. | `:BENCh:APPlication:SELect` | A-class software context selection only; does not execute the test. |
| `A_atom_easyexpert_list_preset_groups` | List preset groups. | `:BENCh:PRESet:CATalog?` | Saved setup discovery. |
| `A_atom_easyexpert_select_preset_group` | Open/select an EasyEXPERT preset group. | `:BENCh:PRESet:OPEN` | A-class software context selection. |
| `A_atom_easyexpert_list_preset_setups` | List setups in preset group. | `:BENCh:PRESet:SETup:CATalog?` | Saved classic setup discovery. |
| `A_atom_easyexpert_select_preset_setup` | Select an EasyEXPERT preset setup. | `:BENCh:PRESet:SETup:SELect` | A-class software context selection only; execution remains C-class. |
| `A_atom_easyexpert_get_selected_name` | Query selected setup/test name. | `:BENCh:SELected:NAME?` | A-class readback for context verification. |
| `A_atom_easyexpert_set_device_tag` | Set EasyEXPERT Device ID tag. | `:BENCh:TAG` | Sample metadata for wafer automation. |
| `A_atom_easyexpert_get_device_tag` | Read EasyEXPERT Device ID tag. | `:BENCh:TAG?` | Sample metadata readback. |
| `A_atom_easyexpert_set_repeat_count` | Set measurement repeat count. | `:BENCh:COUNt` | Batch automation count. |
| `A_atom_easyexpert_get_repeat_count` | Read measurement repeat count. | `:BENCh:COUNt?` | Batch count readback. |
| `A_atom_easyexpert_reset_repeat_count` | Clear repeat count field. | `:BENCh:COUNt:RESet` | Count reset before batch. |
| `A_atom_easyexpert_set_app_test_param` | Set numeric parameter of selected app test. | `:BENCh:SELected:NUMBer` | App test parameter editing. |
| `A_atom_easyexpert_set_app_test_string` | Set string parameter of selected app test. | `:BENCh:SELected:STRing` | Resource string / parameter editing. |
| `A_atom_easyexpert_load_setup` | Load setup from XTS/XTR block data. | `:BENCh:LOAD:SETup` | File-to-remote setup bridge. |

