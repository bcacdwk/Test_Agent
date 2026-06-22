# Instrument Interaction MCP Atom Tools

This reference documents the fake-but-loadable atom tools exposed by the B1500A MCP server. These tools are not real hardware control yet. They define the intended MCP surface and return `fake: true` / `hardware_touched: false`.

## Naming Taxonomy

**A atoms** — read-only interface/session/context/readback/discovery atoms:

```
A_atom_<interface>_<action>
```

- Interfaces: `flex` (direct GPIB/VISA FLEX commands), `wgfmu` (B1530A instrument library), `easyexpert` (EasyEXPERT remote control).
- These should not change DUT output state.
- EasyEXPERT application/preset selection is A-class (software-context selection, not execution).

**B atoms** — safety/state-control atoms categorized by risk or operation type:

```
B_atom_<risk_category>_<target>_<action>
```

- Categories: `safety`, `output`, `lifecycle`, `diagnostic`, `calibration`, `routing`, `correction`, `policy`.
- Targets: `b1500`, `smu`, `asu`, `scuu`, `cmu`, `qscv`, `wgfmu`, `easyexpert` (the hardware unit or interface the action applies to).
- `output` covers zero/disable/channel-output state operations (not split into subcategories).
- Category is determined by the nature of the risk/operation, not by which interface issues the command.

**Future C atoms** — measurement atoms (SMU/WGFMU/SPGU/CMU measurement recipes), not yet implemented.

Primary sources:

- `B1500A Programming Guide.pdf`
- `B1530A WGFMU.pdf`
- `Keysight EasyEXPERT Software.pdf`
- `test_agent/references/manuals/*-index.md`
- `test_agent/references/manuals/structured/*`

## A Class Atom Tools — flex

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `A_atom_flex_connect` | Open direct B1500A GPIB/VISA session and discover identity/modules. | `*IDN?`, `UNT?` | Fake only; real implementation must open VISA and create a lock. |
| `A_atom_flex_disconnect` | Close direct B1500A session. | Session lifecycle | Real flow should call `B_atom_output_b1500_zero_all` before closing. |
| `A_atom_flex_identify` | Query B1500A identity. | `*IDN?` | Query response buffer must be read immediately. |
| `A_atom_flex_list_modules` | Discover module inventory and channel map. | `UNT?` | Required before selecting channel-specific tools. |
| `A_atom_flex_get_status` | Composite status snapshot. | `UNT?`, `ERRX?`, `*STB?`, `*LRN?` | Does not replace individual diagnostic atoms. |
| `A_atom_flex_query_settings` | Read current settings. | `*LRN?` | Useful before/after failures. |
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

## B Class Atom Tools — safety

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_safety_b1500_abort` | Abort active B1500A operation. | `AB` | Follow with cleanup and error readback in real flow. |
| `B_atom_safety_b1500_check_interlock` | Check high-voltage interlock state. | `INTLKVTH?` / safety docs | Exact command semantics need real validation. |
| `B_atom_safety_b1500_preflight` | Aggregate readiness and safety checks. | `UNT?`, `ERRX?`, `*STB?`, `*LRN?`, interlock check | Standard gate before measurement atoms. |
| `B_atom_safety_easyexpert_abort_measurement` | Abort selected EasyEXPERT measurement. | `[:BENCh][:SELected]:ABORt` | Remote safety/cancel atom. |

## B Class Atom Tools — output

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_output_b1500_enable_channels` | Enable output/measurement channels. | `CN` | State-changing; validate channel map first. |
| `B_atom_output_b1500_disable_channels` | Disable channels. | `CL` | Empty input means all. |
| `B_atom_output_b1500_zero_outputs` | Force selected/all outputs to 0 V. | `DZ` | Safety cleanup primitive. |
| `B_atom_output_b1500_zero_all` | Force 0 V and disable all channels. | `DZ`, `CL` | Emergency-style cleanup atom. |
| `B_atom_output_b1500_confirm_zero` | Confirm output is near zero. | `WZ?` | Useful before contact/re-cabling. |
| `B_atom_output_b1500_recover_zeroed` | Restore settings saved by `DZ`. | `RZ` | Requires prior `DZ`; otherwise B1500A can report an error. |
| `B_atom_output_smu_set_filter` | Set SMU filter state. | `FL` | Initial setting is off. |
| `B_atom_output_smu_set_series_resistor` | Set SMU series resistor state. | `SSR` | Initial setting is off; paired with FL. |
| `B_atom_output_wgfmu_connect` | Enable WGFMU channel and connected RSU. | `WGFMU_connect` | B-class: enables channel output through RSU. |
| `B_atom_output_wgfmu_disconnect` | Disable WGFMU channel and connected RSU. | `WGFMU_disconnect` | B-class: disables channel output. |
| `B_atom_output_easyexpert_set_standby` | Set EasyEXPERT standby state. | `:STANDby:STATe` | Bias/standby state control. |

## B Class Atom Tools — lifecycle

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_lifecycle_b1500_reset` | Reset B1500A to initial settings. | `*RST` | Must not be concatenated with other commands. |
| `B_atom_lifecycle_b1500_initialize` | Initialize instrument state. | `IN` | Dedicated safety/state-control atom. |
| `B_atom_lifecycle_wgfmu_initialize` | Reset all WGFMU channels. | `WGFMU_initialize` | WGFMU state-control atom. |
| `B_atom_lifecycle_wgfmu_abort` | Stop WGFMU sequencer on all channels. | `WGFMU_abort` | B-class: abort/safety primitive. Channels keep output voltage at moment of abort. |

## B Class Atom Tools — diagnostic

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_diagnostic_b1500_self_test` | Run B1500A self-test. | `*TST?` | Safety/diagnostic atom. |
| `B_atom_diagnostic_b1500_diagnostics` | Run diagnostics item. | `DIAG?` | Item map needs further extraction. |
| `B_atom_diagnostic_wgfmu_self_test` | Run WGFMU/mainframe self-test. | `WGFMU_doSelfTest` | Returns bitmask-style pass/fail result in real API. |

## B Class Atom Tools — calibration

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_calibration_b1500_self_calibration` | Run B1500A self-calibration. | `*CAL?` | Record in metadata. |
| `B_atom_calibration_smu_set_adc_zero` | Set SMU ADC zero function. | `AZ` | Initial setting is off. |
| `B_atom_calibration_wgfmu_self_calibration` | Run WGFMU/mainframe self-calibration. | `WGFMU_doSelfCalibration` | Timeout may be raised to 600 s. |
| `B_atom_calibration_easyexpert_zero_cancel_on` | Enable EasyEXPERT SMU zero cancel. | CALibration `ON` / `ON:ALL` | Calibration state atom. |
| `B_atom_calibration_easyexpert_zero_cancel_off` | Disable EasyEXPERT SMU zero cancel. | CALibration `OFF:ALL` | Calibration state atom. |
| `B_atom_calibration_easyexpert_measure_zero_cancel` | Measure EasyEXPERT SMU zero-cancel data. | CALibration `MEASure` | Zero-cancel calibration workflow. |
| `B_atom_calibration_easyexpert_query_zero_cancel_state` | Query EasyEXPERT zero-cancel state. | CALibration `STATe?` | Readback for calibration state. |

## B Class Atom Tools — routing

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_routing_asu_set_path` | Switch ASU path. | `SAP` | Requires ASU topology and DUT safety validation. |
| `B_atom_routing_asu_set_1pa_range` | Enable/disable ASU 1 pA auto-ranging. | `SAR` | Needed for atto/pA-class current workflows. |
| `B_atom_routing_asu_set_indicator` | Set ASU indicator state. | `SAL` | UI/fixture state indicator atom. |
| `B_atom_routing_scuu_set_path` | Switch SCUU path between open/SMU/CMU modes. | `SSP` | Use `SSP` rather than `CN` for SCUU modules. |
| `B_atom_routing_scuu_set_indicator` | Set SCUU indicator state. | `SSL` | UI/fixture state indicator atom. |

## B Class Atom Tools — correction

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_correction_cmu_set_correction` | Enable/disable CMU open/short/load correction. | `CORRST`, `CORRST?` | `OPEN`/`SHOR`/`LOAD` are type labels, not standalone commands. |
| `B_atom_correction_cmu_measure_data` | Measure CMU open/short/load correction data. | `CORR?` | Real implementation must require correct fixture condition. |
| `B_atom_correction_cmu_set_phase_mode` | Select MFCMU phase compensation mode. | `ADJ` | Often prerequisite for `ADJ?`. |
| `B_atom_correction_cmu_perform_phase_comp` | Perform MFCMU phase compensation. | `ADJ?` | Manual notes open measurement terminals and ~30 s operation. |
| `B_atom_correction_cmu_clear` | Clear CMU correction data. | `CLCORR` | Correction state reset atom. |
| `B_atom_correction_qscv_offset_cancel` | Perform QSCV offset/zero cancellation. | `QSZ` | Needed before QSCV recipes. |

## B Class Atom Tools — policy

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_policy_b1500_set_auto_calibration` | Set auto-calibration policy. | `CM` | Important for long batch runs. |
| `B_atom_policy_wgfmu_treat_warnings_as_errors` | Set WGFMU warning-as-error policy. | `WGFMU_treatWarningsAsErrors` | Converts selected warning behavior into stricter failure mode. |

## Implementation Notes

- Do not add a default `send_raw_flex_command` tool.
- If an expert raw command path is added later, it must be disabled by default, approval-gated, and audited.
- Query responses and measurement data buffers are different. Real tools must consume query responses promptly and not assume measurement data is available after errors.
- A/B atom names are intentionally stable MCP surface names. Do not expose legacy unprefixed aliases unless a migration layer is explicitly requested.
