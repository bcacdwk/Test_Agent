# AB Flow Design - GPT55

## Scope and Principles

AB_flow is the real user-facing workflow layer because it turns separate read and action primitives into an auditable operator runbook. A-only flows can observe, discover, select software context, drain queues, and collect already-produced data, but they cannot make safety or state-control changes. B-only flows can abort, zero, reset, initialize, route, calibrate, and correct, but they cannot prove what endpoint they acted on or preserve before/after diagnostic evidence. AB_flow is where these become one workflow: observe/discover with A, act/change with B, then verify/log with A.

The catalog below follows the confirmed naming pattern:

```text
AB_flow_{workflow}_{scope}_{outcome}
```

The workflow token is one of `startup`, `shutdown`, `recovery`, `maintenance`, `preparation`, `correction`, or `configuration`. The scope token names the governed session, endpoint, or fixture domain (`flex`, `wgfmu`, `easyexpert`, `asu`, `scuu`, `cmu`, `qscv`). The outcome token names the operator result, not every internal step.

AB_flow may compose current `A_flow_*`, current `B_flow_*`, and narrow direct `A_atom_*` / `B_atom_*` calls where a full flow would be too broad. It must not call future C atoms, must not execute IV/CV/pulse/WGFMU/EasyEXPERT measurements, and must not hide destructive state changes such as reset, buffer consumption, error clearing, routing, correction, or standby changes.

## Proposed AB_flow Catalog

| Category | Flow Name | Real-World Use Case | Ordered Sequence (exact current A_flow/B_flow/A_atom/B_atom names) | Validation Checkpoints | Inputs | Outputs | Failure Handling | Why This Deserves AB_flow | Priority |
|---|---|---|---|---|---|---|---|---|---|
| startup | `AB_flow_startup_flex_safe_session` | Operator/client opens the direct B1500A FLEX path and wants a safe, observed session before any later recipe work. | `A_flow_discover_flex_session` -> `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `A_flow_snapshot_flex_status` | Identity and modules discovered; pre-status captured; preflight `ok`/`preflight_passed`; post-status and non-clearing errors captured. | `gpib_address`, `gpib_board`, `timeout_ms`, `device_type`, `pin_map_known`, `include_timestamp` | Session discovery, module map, pre/post status snapshots, preflight result, warnings. | Stop on discovery failure. If preflight fails, return `ok=false` and do not escalate to reset, output enable, or measurement setup. If final snapshot fails, return `partial=true` with preflight evidence preserved. | Pure A can open/read but cannot gate safety; pure B can gate but cannot identify or verify the session. This is the default direct-session entry point. | P0 |
| startup | `AB_flow_startup_wgfmu_baseline_session` | Client opens WGFMU library access, initializes a known WGFMU baseline, and verifies diagnostics before waveform work exists. | `A_flow_discover_wgfmu_session` -> `B_flow_baseline_wgfmu_known_state` -> `A_flow_snapshot_wgfmu_diagnostics` | WGFMU session opened; channel IDs discovered; initialize/warning policy result recorded; final error/warning summaries captured. | `address`, `timeout_s`, `set_warning_policy`, `warnings_as_errors` | WGFMU channel IDs, baseline result, final diagnostics, warnings. | Stop if session discovery fails. If baseline succeeds but diagnostics fail, keep the session open and return `partial=true`. | WGFMU B flows require an open A session; A discovery alone cannot initialize or set warning policy. This is the canonical WGFMU open baseline. | P0 |
| startup | `AB_flow_startup_easyexpert_workspace_standby` | Operator opens an EasyEXPERT workspace and places remote standby state explicitly before selecting or running anything later. | `A_flow_discover_easyexpert_remote` -> `A_flow_select_easyexpert_workspace` -> `B_atom_output_easyexpert_set_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_snapshot_easyexpert_context` | Remote identity known; workspace open verified; standby atom result recorded; OPC complete; workspace/name/selection/tag/count context captured. | `workspace`, `timeout_s`, `standby_enabled` | Remote discovery, workspace context, standby state request result, final EasyEXPERT context. | Stop before standby if workspace open fails. If standby set fails, still attempt `A_atom_easyexpert_wait_opc` and final context when remote is responsive. | Existing B emergency abort flow is too broad for startup; the direct standby atom is the narrow B action needed between A open and A verify. | P1 |
| shutdown | `AB_flow_shutdown_flex_safe_session` | Close a direct B1500A session after preserving optional pre-existing output-buffer data and forcing outputs safe. | optional `A_flow_collect_flex_output_buffer` -> `A_flow_snapshot_flex_status` -> `B_flow_safe_state_b1500_zero_disable` -> `A_flow_drain_flex_errors` -> `A_flow_teardown_flex_session` | Optional buffer count/read/count recorded; pre-status captured; zero/disable confirmation; drained errors preserved; disconnect context recorded. | `collect_buffer`, `max_items`, `read_when_empty`, `channels`, `confirm_timeout_s`, `allow_data_loss`, `force_disconnect_after_failed_zero` | Optional consumed buffer data, pre-status, safe-state result, drained errors, teardown/disconnect result. | If buffer collection fails, stop unless `allow_data_loss=true`. If zero/disable confirmation fails, do not disconnect unless an explicit force policy is set. Always preserve drained errors in audit. | A teardown is explicitly not safe shutdown, and B safe-state cannot close/log the session. The combination is the real shutdown workflow. | P0 |
| shutdown | `AB_flow_shutdown_wgfmu_safe_session` | Stop/disconnect declared WGFMU channels, capture diagnostics, optionally export setup, and close WGFMU log/session. | `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_emergency_wgfmu_abort_disconnect` -> `A_flow_drain_wgfmu_errors` -> `A_flow_teardown_wgfmu_session` | Pre diagnostics; abort/disconnect per channel; drained WGFMU errors/summaries; optional ASCII export; log/session close. | `channel_ids`, `max_errors`, `export_setup`, `file_name`, `close_log` | Pre diagnostics, abort/disconnect result, drained errors, teardown result. | If pre diagnostics fail but the session appears live, still attempt abort/disconnect. If abort/disconnect fails, do not close by default unless caller policy explicitly permits close-after-failure. | A close cannot disable WGFMU outputs; B abort/disconnect cannot export or close the library session. | P1 |
| shutdown | `AB_flow_shutdown_easyexpert_workspace_standby` | Stop selected EasyEXPERT activity, set standby, drain remote errors, and close the workspace. | `A_flow_snapshot_easyexpert_context` -> `B_flow_emergency_easyexpert_abort_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_teardown_easyexpert_workspace` | Pre context captured; abort/standby result; OPC complete; drained FIFO errors; workspace close verified. | `standby_enabled`, `timeout_s`, `max_errors`, `force_clear`, `force_close_workspace` | Pre context, abort/standby result, drained errors, workspace teardown result. | If abort/standby fails, do not close workspace unless `force_close_workspace=true`. If drain consumes errors, all entries must be returned in audit. | A workspace teardown alone does not abort or standby; B abort/standby alone cannot verify or close workspace context. | P1 |
| recovery | `AB_flow_recovery_flex_emergency_zero` | Emergency response for direct B1500A activity: abort first, force outputs to zero/disabled, then collect errors/status evidence. | optional `A_flow_snapshot_flex_status` -> `B_flow_emergency_b1500_abort_zero` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Best-effort pre-status; abort attempted; zero-all/disable and `B_atom_output_b1500_confirm_zero` result inside B flow; drained error queue; final status. | `attempt_pre_snapshot`, `confirm_timeout_s`, `max_errors`, `lookup_messages`, `incident_id` | Emergency action result, zero confirmation, drained annotated errors, final status, incident audit record. | Emergency action runs even when pre-snapshot fails. If B abort fails, the B flow still attempts zero/confirm. If A verification fails after B, return safety action evidence with `partial=true`. | Emergency recovery is the strongest AB pattern: act for safety first, then verify/log with A. | P0 |
| recovery | `AB_flow_recovery_flex_reset_rediscover` | Return from unknown or corrupted B1500A state by zeroing/resetting/optional initializing, then rediscovering the instrument. | `A_flow_snapshot_flex_status` -> `B_flow_baseline_b1500_known_state` -> `A_atom_flex_identify` -> `A_atom_flex_list_modules` -> `A_atom_flex_query_settings` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Pre reset state captured; zero confirmed before reset; reset performed; identity/modules/settings rediscovered; reset-related errors drained; final status captured. | `confirm_timeout_s`, `initialize`, `set_auto_calibration`, `auto_calibration_enabled`, `operator_ack`, `allow_reset_without_snapshot` | Pre status, baseline/reset result, identity, module map, settings, drained errors, final status. | Stop before reset if pre-snapshot fails unless explicitly allowed. If reset succeeds but rediscovery fails, return `partial=true` and require manual review. | Reset is B state control; rediscovery and error drain are A. Full A discovery is too broad after an already-open reset, so direct A atoms are appropriate. | P0 |
| recovery | `AB_flow_recovery_wgfmu_abort_disconnect` | Recover WGFMU from a suspected active or failed sequencer state without closing the session immediately. | optional `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_emergency_wgfmu_abort_disconnect` -> `A_flow_drain_wgfmu_errors` -> `A_flow_snapshot_wgfmu_diagnostics` | Best-effort pre diagnostics; WGFMU abort; declared channels disconnected; per-entry errors drained; final summaries captured. | `attempt_pre_snapshot`, `channel_ids`, `max_errors`, `incident_id` | Abort/disconnect result, drained WGFMU errors, final diagnostics. | Run B emergency flow even if pre diagnostics fail. If channel list is empty, return `partial=true` because abort may have occurred without disconnect evidence. | Current B_flow now provides true WGFMU abort/disconnect, but A diagnostics are still needed to make recovery auditable. | P1 |
| recovery | `AB_flow_recovery_easyexpert_abort_standby` | Recover EasyEXPERT remote after a selected measurement or remote action must be stopped. | optional `A_flow_snapshot_easyexpert_context` -> `B_flow_emergency_easyexpert_abort_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_snapshot_easyexpert_context` | Optional pre workspace/selection context; abort/standby result; OPC complete; FIFO errors drained; final workspace/selection/tag/count context. | `attempt_pre_snapshot`, `standby_enabled`, `timeout_s`, `max_errors`, `force_clear`, `incident_id` | Abort/standby result, OPC result, drained errors, final context. | In emergency mode, run B abort/standby even if pre context fails. If A drain fails, return B result and mark final remote state unknown. | B remote stop lacks wait/error/context evidence; A context tools cannot abort. AB makes the stop recoverable and auditable. | P0 |
| maintenance | `AB_flow_maintenance_flex_self_test_calibration` | Run B1500A self-test and optional self-calibration with pre/post evidence for maintenance records. | `A_flow_snapshot_flex_status` -> `B_flow_maintenance_b1500_self_test_calibration` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Pre status has no active wait/data hazard; zero confirmed inside B flow; self-test/calibration results; drained errors; final status/settings. | `run_self_calibration`, `repeat_self_test_after_calibration`, `force_calibration_after_self_test_failure`, `operator_ack`, `confirm_timeout_s` | Pre/post status, maintenance results, calibration-performed flag, drained errors, warnings. | Stop before B maintenance if pre-status indicates active operation unless an explicit override exists. If calibration fails, still drain errors and snapshot. | Maintenance is not just B self-test/calibration; operators need identity/status/error evidence before and after. | P1 |
| maintenance | `AB_flow_maintenance_wgfmu_self_test_calibration` | Open/log a WGFMU maintenance session, run self-test and optional self-calibration, then capture diagnostics. | `A_flow_discover_wgfmu_session` -> `A_flow_prepare_wgfmu_logging` -> `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_maintenance_wgfmu_self_test_calibration` -> `A_flow_snapshot_wgfmu_diagnostics` | Session/channel discovery; log/warning setup; pre diagnostics; self-test/calibration results; final diagnostics. | `address`, `timeout_s`, `file_name`, `warning_level`, `run_self_calibration`, `initialize`, `operator_ack` | Session context, logging setup, pre/post diagnostics, WGFMU maintenance result. | If discover/logging fails, stop before B maintenance. If B maintenance fails, still attempt final diagnostics. | B maintenance requires an open session, and A diagnostics/logging give operators usable maintenance evidence. | P1 |
| preparation | `AB_flow_preparation_flex_nonmeasurement_baseline` | Prepare a direct-session baseline for later C work without arming outputs or starting measurement. | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_baseline_smu_housekeeping` -> `A_flow_prepare_flex_output_buffer` -> `A_flow_snapshot_flex_status` | Pre status; preflight passed; SMU housekeeping policy recorded; FMT/timestamp/buffer state prepared; final status and buffer count. | `device_type`, `pin_map_known`, `set_auto_calibration`, `auto_calibration_enabled`, `set_adc_zero`, `filter_channels`, `series_resistor_channels`, `format_mode`, `output_mode`, `timestamp_enabled`, `allow_clear_buffer` | Pre/post status, preflight result, SMU housekeeping result, parser/buffer prep result. | If preflight fails, skip housekeeping and buffer changes. If buffer has unread data and clear is not allowed, return `partial=true` and do not destroy it. | This spans B policy/housekeeping and A parser/buffer configuration, while remaining explicitly non-measurement. | P1 |
| preparation | `AB_flow_preparation_asu_low_current_path` | Prepare ASU low-current path after validating direct session context and forcing outputs safe. | `A_flow_discover_flex_session` -> `B_flow_preflight_b1500_gate` -> `B_flow_preparation_asu_low_current_path` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Module/channel context discovered; preflight/interlock result; zero/disable confirmed inside B prep; ASU path/1 pA/indicator/filter results; drained errors; final status. | `channel`, `path`, `channels`, `confirm_timeout_s`, `fixture_ack`, `set_1pa_range`, `range_1pa_enabled`, `set_indicator`, `indicator_enabled`, `set_smu_filter`, `smu_filter_enabled`, `device_type`, `pin_map_known` | Discovery context, preflight result, ASU preparation result, drained errors, final status. | Stop before path switch if discovery/preflight/fixture acknowledgement is missing. If B path flow fails after zeroing, keep outputs disabled and require manual review. | ASU routing is fixture-sensitive B work, but A discovery/error/status evidence is required for client trust. | P1 |
| preparation | `AB_flow_preparation_scuu_signal_path` | Prepare SCUU path for later SMU/CMU workflows without executing a measurement. | `A_flow_discover_flex_session` -> `B_flow_preflight_b1500_gate` -> `B_flow_preparation_scuu_signal_path` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Module/channel context; preflight passed; zero/disable confirmed; SCUU path/indicator result; drained errors; final status. | `channel`, `path_mode`, `channels`, `confirm_timeout_s`, `fixture_ack`, `set_indicator`, `indicator_enabled`, `device_type`, `pin_map_known` | Discovery context, preflight result, SCUU preparation result, drained errors, final status. | Stop before switching if fixture acknowledgement is absent or preflight fails. If post drain reports routing errors, return `ok=false` with outputs left safe. | SCUU routing needs A context plus B routing and A post-evidence; neither pure layer is enough. | P1 |
| correction | `AB_flow_correction_cmu_open_short_load` | Perform CMU open/short/load correction with fixture acknowledgement and before/after evidence. | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_cmu_open_short_load` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Pre status; preflight passed; zero confirmed inside correction flow; fixture condition acknowledged; correction types processed; drained errors; final status. | `channel`, `correction_types`, `confirm_timeout_s`, `clear_existing`, `fixture_condition_ack`, `device_type`, `pin_map_known` | Pre/post status, preflight result, correction results, processed types, drained errors. | If fixture acknowledgement is missing, stop before correction. If one type fails, do not claim that correction enabled; preserve per-type evidence. | Correction is B state/calibration work, but it is only useful when bracketed by A status and error evidence. | P1 |
| correction | `AB_flow_correction_cmu_phase_compensation` | Perform MFCMU phase compensation with open-terminal acknowledgement and post diagnostics. | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_cmu_phase_compensation` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Pre status; preflight passed; zero confirmed; fixture/open-terminal acknowledgement; phase mode and compensation result; drained errors; final status. | `channel`, `mode`, `confirm_timeout_s`, `fixture_condition_ack`, `device_type`, `pin_map_known` | Phase compensation result, drained errors, pre/post status, warnings. | Stop if preflight or fixture acknowledgement fails. If B compensation reports failure, still drain errors and snapshot. | This is a common CMU readiness step but not a CV measurement; AB makes the pre/post evidence explicit. | P1 |
| correction | `AB_flow_correction_qscv_offset_cancel` | Perform QSCV offset/zero cancellation before future QSCV recipes without running QSCV measurement. | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_qscv_offset_cancel` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Pre status; preflight passed; zero confirmed; fixture acknowledgement; offset cancel result; drained errors; final status. | `channel`, `confirm_timeout_s`, `fixture_condition_ack`, `device_type`, `pin_map_known` | Offset-cancel result, drained errors, pre/post status. | Stop before cancellation if preflight or fixture acknowledgement fails. If cancellation fails, do not continue into any future C recipe. | QSCV offset cancel is a valuable AB precursor because it is stateful correction but not measurement execution. | P1 |
| correction | `AB_flow_correction_easyexpert_zero_cancel` | Manage EasyEXPERT SMU zero-cancel state or refresh zero-cancel data with remote evidence. | `A_flow_snapshot_easyexpert_context` -> `B_flow_correction_easyexpert_zero_cancel` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_snapshot_easyexpert_context` | Workspace context captured; initial/final zero-cancel states inside B flow; optional zero-cancel measurement result; OPC complete; drained remote errors; final context. | `channel`, `disable_before_measure`, `measure_zero_cancel`, `fixture_condition_ack`, `operator_ack`, `timeout_s`, `max_errors`, `force_clear` | Zero-cancel result, OPC result, drained errors, final EasyEXPERT context. | If workspace context is unavailable, stop unless caller marks recovery/maintenance override. If fixture ack is missing, B flow skips measurement and AB returns `partial=true`. | EasyEXPERT zero-cancel is calibration/correction-like B work; A context/error evidence is required and no application test is executed. | P1 |
| configuration | `AB_flow_configuration_flex_srq_monitoring` | Configure FLEX SRQ/status-byte monitoring only after a safety gate and with post-status evidence. | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `A_atom_flex_configure_srq` -> `A_flow_snapshot_flex_status` | Pre status and current errors captured; preflight passed; SRQ mask request recorded; final status byte/errors/settings captured. | `enable_mask`, `device_type`, `pin_map_known`, `include_timestamp` | Pre/post snapshots, preflight result, SRQ configuration result, restore warning. | Stop if pre-snapshot or preflight fails. If final snapshot fails, return `partial=true` because SRQ state may be unknown. | The actual state change is A communication configuration, but automated clients should not alter monitoring policy without B safety context and A verification. | P2 |

## Category Notes

### startup

Belongs here: opening or selecting a session/workspace and reaching a known, verified baseline before later work. Startup may use B baseline or narrow B state actions after A discovery. It must not run maintenance calibration, correction, routing, or measurement recipes.

Does not belong: full-station startup across FLEX + WGFMU + EasyEXPERT, measurement readiness that enables channels, or any flow that assumes a C recipe exists.

Examples: `AB_flow_startup_flex_safe_session`, `AB_flow_startup_wgfmu_baseline_session`.

### shutdown

Belongs here: preserving already-produced data when explicitly requested, zeroing/disabling or standby/abort cleanup, draining/logging errors, and closing sessions/workspaces. Shutdown is conservative: do not disconnect or close if the safety action cannot be verified unless the caller explicitly accepts that risk.

Does not belong: emergency fault recovery that needs B-first behavior, full station "disconnect all", or result interpretation.

Examples: `AB_flow_shutdown_flex_safe_session`, `AB_flow_shutdown_easyexpert_workspace_standby`.

### recovery

Belongs here: returning from active, failed, interrupted, unknown, or unsafe state to a logged safe/known state. Emergency recovery may start with B action before A observation to avoid delaying safety action.

Does not belong: scheduled maintenance, optional configuration, or automatic escalation from abort/zero into reset/calibration unless the flow name says so.

Examples: `AB_flow_recovery_flex_emergency_zero`, `AB_flow_recovery_flex_reset_rediscover`, `AB_flow_recovery_easyexpert_abort_standby`.

### maintenance

Belongs here: instrument health operations such as self-test and self-calibration with pre/post evidence. Maintenance may be slow and operator-visible; it should record whether calibration was scheduled or incident-driven.

Does not belong: fixture-dependent correction such as CMU open/short/load, phase compensation, QSCV offset cancel, or EasyEXPERT zero-cancel refresh. Those belong in `correction`.

Examples: `AB_flow_maintenance_flex_self_test_calibration`, `AB_flow_maintenance_wgfmu_self_test_calibration`.

### preparation

Belongs here: non-measurement setup for later workflows, including SMU housekeeping, parser/output-buffer preparation, and safe fixture routing. Preparation may change state but must not execute a measurement or enable outputs for a recipe without missing compliance/range validation.

Does not belong: correction data capture, instrument self-calibration, or direct measurement recipe execution.

Examples: `AB_flow_preparation_flex_nonmeasurement_baseline`, `AB_flow_preparation_asu_low_current_path`, `AB_flow_preparation_scuu_signal_path`.

### correction

Belongs here: fixture-dependent compensation/correction workflows that prepare a measurement path but are not themselves DUT measurements in this A/B/AB design. These require explicit fixture/operator acknowledgement and strong post-error/status evidence.

Does not belong: broad "calibrate everything" flows, scheduled instrument self-calibration, or CV/QSCV measurement execution after correction.

Examples: `AB_flow_correction_cmu_open_short_load`, `AB_flow_correction_qscv_offset_cancel`, `AB_flow_correction_easyexpert_zero_cancel`.

### configuration

Belongs here: client-observation or communication policy changes, such as SRQ/status monitoring, when they need safety gating and post-readback evidence. This category should stay small until reversible query/restore atoms exist.

Does not belong: parser/buffer preparation that directly supports result collection (`preparation`), warning/logging setup that belongs to WGFMU startup/maintenance, or any hidden station-wide policy change.

Example: `AB_flow_configuration_flex_srq_monitoring`.

## Rejected / Avoided AB_flow Combinations

| Rejected Candidate | Why Rejected |
|---|---|
| `AB_flow_startup_full_station_all_transports` | Too broad. FLEX, WGFMU, and EasyEXPERT have separate sessions, locks, error models, and failure handling. A higher-level client can call focused AB flows and aggregate results. |
| `AB_flow_shutdown_all_sessions` | Too broad and unsafe because direct B1500A, WGFMU, and EasyEXPERT teardown have different safety semantics. |
| `AB_flow_run_iv_sweep_after_preflight` | Requires future C atoms for source setup, sweep execution, data generation, and result interpretation. |
| `AB_flow_run_cv_after_cmu_correction` | CMU correction can be AB; CV execution is C. |
| `AB_flow_program_wgfmu_waveform_and_measure` | WGFMU session/baseline/logging can be AB, but waveform programming, sequence execution, and data production are future C scope. |
| `AB_flow_easyexpert_select_run_fetch_application_test` | Selecting software context is A; running the selected test is C. Fetching an existing result is A and should remain separate from execution. |
| `AB_flow_enable_channels_for_measurement_readiness` | Current atoms lack compliance/range/role validation and recipe context. Enabling outputs for a measurement would hide dangerous state changes. |
| `AB_flow_apply_compliance_and_arm_outputs` | Missing B compliance/range atoms and future C recipe constraints. |
| `AB_flow_recover_zeroed_outputs_and_continue` | `B_atom_output_b1500_recover_zeroed` requires prior `DZ` context, and continuing a measurement requires C orchestration. |
| `AB_flow_auto_calibrate_everything` | Too broad across B1500A, WGFMU, EasyEXPERT, CMU, and QSCV. These have different fixture assumptions, durations, and audit records. |
| `AB_flow_collect_and_classify_results` | Reading existing buffers/results is A; classifying them as device measurement results belongs to C/analysis layers. |
| `AB_flow_clear_all_errors_everywhere` | Hides destructive queue consumption and spans transports. Error drains must be endpoint-specific and explicitly audited. |
| `AB_flow_safe_everything` | "Safe" is a claim to prove with phases/checkpoints, not a useful workflow category. |

## Missing Atoms/Flows Needed Later

Only the items below block valuable AB workflows or would materially improve verification:

| Missing Item | Why Needed | Blocked / Weakened AB Workflows |
|---|---|---|
| `B_atom_set_channel_compliance_limits` | Required before any safe channel-arm or output-enable AB workflow. | Keeps channel-enable preparation rejected. |
| `B_atom_confirm_channel_disabled` | Zero confirmation alone does not prove channels are disabled. | Stronger shutdown and recovery verification. |
| `B_atom_query_channel_output_state` | Needed to verify output enable/disable state directly. | Stronger safe shutdown, emergency recovery, and future output-arm workflows. |
| `B_atom_validate_channels_for_state_change` | Station profile, pin map, role, and channel validation should be B-native before state changes. | Safer ASU/SCUU/correction and future channel operations. |
| `B_atom_query_asu_path` | Direct ASU path readback is missing. | Would strengthen `AB_flow_preparation_asu_low_current_path` and enable restore workflows. |
| `B_atom_query_scuu_path` | Direct SCUU path readback is missing. | Would strengthen `AB_flow_preparation_scuu_signal_path` and enable restore workflows. |
| `B_atom_validate_path_switch_fixture_state` | Operator acknowledgement is not the same as formal fixture-state validation. | Safer ASU/SCUU/CMU/QSCV correction flows. |
| `B_atom_query_cmu_correction_state` | Needed to verify enabled/disabled CMU correction state after OSL correction. | Stronger CMU correction and reversible correction workflows. |
| `B_atom_query_cmu_phase_compensation_mode` | Needed to verify or restore phase compensation mode. | Stronger CMU phase compensation workflows. |
| `A_atom_query_service_request_mask` | Needed to make SRQ/status monitoring changes reversible. | Keeps `AB_flow_configuration_flex_srq_monitoring` P2. |
| `A_atom_serial_poll_status_byte` | Needed for true SRQ/interrupt clearing semantics distinct from `*STB?`. | Stronger emergency/status-monitoring flows. |
| `B_atom_easyexpert_query_standby_state` | Current EasyEXPERT standby verification relies on B atom return plus A context/errors. | Stronger EasyEXPERT startup/shutdown/recovery. |
| `B_atom_easyexpert_query_selected_measurement_state` | Needed to know whether abort is idempotent or whether a selected measurement is still active. | Stronger EasyEXPERT abort and teardown workflows. |
| `A_atom_easyexpert_get_selected_test_name` | Current selected-name atom exists, but a more explicit selected-test query would improve audit semantics if EasyEXPERT selection grows. | Future EasyEXPERT selection/verification flows. |
| `A_atom_easyexpert_fetch_result_siblings` | Needed for complete EasyEXPERT result collection without running tests. | Keeps broad EasyEXPERT result export rejected. |
| `B_flow_diagnostic_b1500_item_suite` | A diagnostics-suite B flow would need a DIAG item catalog and policy. | Future maintenance diagnostics beyond self-test/calibration. |

## Implementation Notes

### Return Schema

Every AB_flow should return a response envelope that preserves both the high-level workflow state and every called child result:

```python
{
    "flow": "AB_flow_<workflow>_<scope>_<outcome>",
    "flow_class": "AB",
    "category": "<startup|shutdown|recovery|maintenance|preparation|correction|configuration>",
    "scope": "<flex|wgfmu|easyexpert|asu|scuu|cmu|qscv>",
    "outcome": "<short outcome>",
    "fake": True,
    "hardware_touched": False,
    "ok": True,
    "partial": False,
    "destructive": False,
    "consumptive": False,
    "fixture_sensitive": False,
    "operator_ack_required": False,
    "phases": {
        "observe": [],
        "act": [],
        "verify": []
    },
    "flows_called": [],
    "atoms_called": [],
    "checkpoints": [],
    "inputs": {},
    "outputs": {},
    "warnings": [],
    "audit": {}
}
```

`flows_called` and `atoms_called` must preserve order. Child flow/atom payloads should not be summarized away; the AB result can include normalized outputs, but raw child results are the audit source of truth.

### Observe / Act / Verify Phases

Non-emergency AB flows default to:

```text
observe -> act -> verify
```

If `observe` fails in a non-emergency destructive workflow, do not run B state-changing actions unless the input names an explicit override. This protects operators from reset, correction, routing, or buffer clearing without pre-evidence.

Emergency recovery flows may use:

```text
act -> verify
```

or:

```text
best_effort_observe -> act -> verify
```

If the best-effort A snapshot fails, the B safety action should still run when the flow is explicitly an emergency/recovery flow. Verification failure after B action must not erase B safety evidence; return `partial=true`.

### Audit Log Semantics

AB audit fields should include `requested_by`, `reason`, `incident_id` when relevant, `operator_ack`, `fixture_ack`, `station_profile_id`, `timestamp`, `consumed_buffers`, `cleared_errors`, `reset_performed`, `calibration_performed`, `correction_types_processed`, and `force_override_used`.

Any flow that calls `A_flow_drain_flex_errors`, `A_flow_drain_wgfmu_errors`, `A_flow_drain_easyexpert_errors`, `A_flow_collect_flex_output_buffer`, or `A_atom_flex_clear_output_buffer` must explicitly mark the operation as consumptive/destructive as appropriate and return the consumed data or a clear note that fake data was empty.

### Failure Policy

Precheck failure means B action was not attempted. B action failure means the safety/state operation failed or returned `ok=false`; AB should still attempt A logging when doing so is safe. Post-verification failure means the action may have succeeded but AB cannot prove final state.

Default policies:

- Emergency recovery favors safety action over observability.
- Non-emergency startup, maintenance, preparation, correction, and configuration favor observability before state change.
- Shutdown favors preserving data and proving zero/disable before disconnect.
- Correction and routing require `fixture_ack` or `fixture_condition_ack`; missing acknowledgement skips the state-changing B step.
- Operator-visible reset, calibration, and EasyEXPERT zero-cancel flows require `operator_ack` in real mode; fake mode records missing acknowledgement as a warning for client gating tests.

### Operator Acknowledgement

Use operator acknowledgement for actions that are destructive, slow, fixture-sensitive, or likely to surprise an operator:

- Reset/initialize and self-calibration.
- CMU open/short/load correction, phase compensation, QSCV offset cancellation.
- EasyEXPERT zero-cancel measurement refresh.
- Any force close/disconnect after failed safe-state verification.

Fixture acknowledgement is separate from operator acknowledgement. A user can approve a flow while still failing to confirm the required fixture condition; in that case correction/routing must be skipped.

### Fake Semantics

All current tools are fake orchestration tools. AB implementations should preserve:

```text
fake: true
hardware_touched: false
```

The fake AB layer should still exercise real client logic: gates, skips, warnings, `partial`, `ok=false`, consumptive flags, destructive flags, and acknowledgement warnings. It must never be presented as hardware control.

When real transport is implemented later, A read-only calls may remain non-destructive, while B and AB state-changing calls should set `hardware_touched: true`. The same names and phase/checkpoint semantics should carry forward so client code does not need to learn a new workflow model.
