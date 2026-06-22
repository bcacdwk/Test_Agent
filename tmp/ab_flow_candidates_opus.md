# AB Flow Candidates - Opus

## Scope

`AB_flow_*` tools combine accepted `A_flow_*` and accepted `B_flow_*` pieces, with occasional direct `A_atom_*` / `B_atom_*` calls only when an accepted full flow would be too broad for the checkpoint being performed.

AB_flow can:

- Discover or snapshot instrument/session state with A, perform safety/state-control/calibration/path actions with B, then verify or log with A.
- Connect/open sessions and immediately bring them to a safer or known baseline.
- Perform reset, initialization, abort, zero/disable, preflight, self-test, calibration, path switching, and correction workflows with surrounding A status/error capture.
- Read pre-existing output buffers or EasyEXPERT results using accepted A flows, as long as the AB_flow does not start a measurement.
- Close sessions/workspaces after B safety/state cleanup.

AB_flow cannot:

- Use `C_atom_*` or future C measurement recipes.
- Start IV/CV/pulse/WGFMU/EasyEXPERT measurements.
- Configure force/sweep/pulse recipes or compliance/range plans that are measurement-specific.
- Claim complete hardware health if a required A verification atom/flow is missing; it must report partial verification.
- Hide destructive state changes in generic discovery or readout names.

Core pattern: **A observe/discover -> B change/safety action -> A verify/log**. If a candidate cannot be expressed in this pattern without starting measurement, it is not an AB_flow.

## Candidate AB_flow Table

| Flow Name | Purpose | Ordered Flow/Atom Sequence | Validation Checkpoints | Failure Handling | Inputs | Outputs | Why This Should Be AB Flow | Risks / Cautions | Priority (P0/P1/P2) |
|---|---|---|---|---|---|---|---|---|---|
| `AB_flow_start_b1500_safe_session` | Establish a direct B1500A session, capture baseline state, and run the B-class preflight gate before any stateful work. | `A_flow_discover_b1500_session` -> `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `A_flow_snapshot_b1500_status` | Verify identity/modules were discovered; verify preflight `passed`; compare pre/post status snapshots; ensure error queue is not worse after preflight. | If discovery fails, stop before B. If preflight fails, return `ok=false` and do not run reset/enable/measurement. If post-snapshot fails, mark `partial=true` but preserve preflight result. | `gpib_address`, `gpib_board`, `timeout_ms`, `device_type`, `pin_map_known` | `instrument_id`, `modules`, `pre_status`, `preflight`, `post_status`, `warnings` | Startup needs A discovery plus B safety gate. Pure A cannot preflight; pure B cannot connect or verify state. | Fake preflight currently includes synthetic transport checks. Real preflight policy must be station-specific and may intentionally fail until hardware transport is implemented. | P0 |
| `AB_flow_emergency_recover_b1500_session` | Recover from an active or suspected unsafe B1500A operation by capturing context when possible, aborting/zeroing, then draining errors and snapshotting final state. | optional `A_flow_snapshot_b1500_status` -> `B_flow_emergency_abort_and_zero_outputs` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Pre-snapshot best effort; B confirm-zero result is mandatory; final status must show no data-ready/wait hazard where available; drained errors are annotated. | Always attempt B emergency flow even if pre-snapshot fails. If `B_atom_abort_operation` fails inside B flow, still attempt zero/disable/confirm. If A drain fails after zero, return `partial=true` with B results preserved. | `attempt_pre_snapshot` (bool, default true), `confirm_timeout_s`, `clear_errors` (default true), `incident_id` | `pre_status`, `emergency_action`, `annotated_errors`, `post_status`, `audit_record` | Emergency recovery is the canonical AB pattern: observe if possible, make safe with B, then observe and drain with A. | A status reads may time out during a severe fault. Error drain is destructive by default; audit log must retain drained entries. | P0 |
| `AB_flow_safe_shutdown_b1500_session` | Safely prepare a direct B1500A session for disconnect by optionally collecting pre-existing buffered data, zeroing/disabling outputs, recording final context, and disconnecting. | optional `A_flow_collect_b1500_output_buffer` -> `B_flow_zero_disable_b1500_outputs` -> `A_flow_record_b1500_disconnect_context` | If `collect_buffer=true`, confirm output buffer count reaches expected post-read count; B confirm-zero must pass; disconnect-context A flow records final status/errors/settings before close. | If buffer collection fails, continue only when `allow_data_loss=true`; otherwise stop before B shutdown. If B zero/disable fails, do not disconnect unless `force_disconnect_after_failed_zero=true` is explicitly allowed by policy. | `channels` (default all), `collect_buffer` (bool), `allow_data_loss` (bool), `confirm_timeout_s` | `collected_buffer`, `shutdown_action`, `disconnect_context`, `disconnected` | Accepted A close-context flow explicitly is not safe shutdown by itself; accepted B zero/disable cannot disconnect. AB is required. | Reading output buffer may consume data. A disconnect after failed zero is dangerous; default must be conservative. | P0 |
| `AB_flow_reset_rediscover_b1500_state` | Reset/initialize B1500A state safely, then rediscover identity/modules/settings and drain/reset-related errors. | `A_flow_snapshot_b1500_status` -> `B_flow_reset_initialize_b1500_state` -> direct `A_atom_identify_b1500` -> direct `A_atom_list_installed_modules` -> direct `A_atom_query_current_settings` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Pre-snapshot records starting state; B confirm-zero/reset/initialize must complete; post direct atoms verify instrument still responds and module map is present; final snapshot verifies no lingering status hazard. | If pre-snapshot fails but caller sets `allow_reset_without_snapshot=true`, proceed and mark audit warning. If reset succeeds but rediscovery fails, return `partial=true` and require manual intervention. | `include_initialize` (bool), `confirm_timeout_s`, `allow_reset_without_snapshot` (bool) | `pre_status`, `reset_result`, `identity`, `modules`, `settings`, `annotated_errors`, `post_status` | Reset is B, rediscovery is A. Full accepted `A_flow_discover_b1500_session` includes connect and is too broad after an already-open reset, so direct A atoms are appropriate. | `*RST` must stay isolated. Reset may clear or alter settings expected by downstream code; final settings must be treated as authoritative. | P0 |
| `AB_flow_maintenance_b1500_self_test_calibration` | Run direct B1500A maintenance self-test/calibration with pre/post status and error capture. | `A_flow_snapshot_b1500_status` -> `B_flow_self_test_calibrate_b1500` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Require pre-status to show no active output/wait condition before maintenance; B result must pass; drained errors are annotated; post-status is compared with pre-status. | If pre-status indicates active operation or unread buffer, stop unless `allow_maintenance_with_pending_state=true`. If calibration fails, skip post self-test only if B flow reports unsafe continuation. | `run_calibration`, `post_calibration_self_test`, `allow_maintenance_with_pending_state` | `pre_status`, `maintenance_result`, `annotated_errors`, `post_status`, `passed` | Calibration/self-test without A context is hard to audit. AB provides before/after status and error evidence. | Calibration can be slow and should be scheduled. This still does not replace external calibration records. | P1 |
| `AB_flow_prepare_b1500_nonmeasurement_baseline` | Prepare a non-measurement baseline for later recipes: status snapshot, preflight gate, SMU housekeeping policy, output-buffer preparation, and final status. | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_configure_smu_baseline_state` -> `A_flow_prepare_b1500_output_buffer` -> `A_flow_snapshot_b1500_status` | Preflight must pass; SMU baseline B flow records chosen auto-cal/filter/ADC-zero policy; output-buffer flow must confirm count is zero; final snapshot checks errors/status. | If output buffer contains unread data and `allow_clear_buffer=false`, stop before clearing. If preflight fails, do not change SMU baseline or clear buffer. | `device_type`, `pin_map_known`, `channels`, `auto_calibration`, `adc_zero_enabled`, `filter_enabled`, `format_mode`, `output_mode`, `timestamp_enabled`, `allow_clear_buffer` | `pre_status`, `preflight`, `smu_baseline`, `buffer_prep`, `post_status` | This is not a measurement setup, but it spans A buffer/status configuration and B housekeeping policy. | It can clear unread buffer data and alter auto-cal/filter/ADC-zero state. It must be explicitly named as nonmeasurement baseline, not recipe execution. | P1 |
| `AB_flow_configure_b1500_polling_with_safety_gate` | Configure status polling/SRQ behavior only after a B-class preflight gate and then verify status/error state. | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `A_flow_configure_b1500_status_polling` -> `A_flow_snapshot_b1500_status` | Preflight must pass; A polling flow records status byte and errors after mask set; final snapshot confirms status view. | If preflight fails, do not alter SRQ mask. If polling config succeeds but final snapshot fails, mark `partial=true` and warn mask may need manual restoration. | `enable_mask`, `device_type`, `pin_map_known` | `pre_status`, `preflight`, `polling_config`, `post_status` | SRQ/status polling is A, but should be gated by B preflight in automated clients. | Existing A arbitration notes no query-mask atom exists, so mask restoration is not available. | P2 |
| `AB_flow_prepare_asu_low_current_path_verified` | Discover channel/module context, run ASU low-current path preparation, then verify direct B1500A status/errors. | `A_flow_discover_b1500_session` or `A_flow_snapshot_b1500_status` -> validate requested channel from discovered modules/settings -> `B_flow_prepare_asu_low_current_path` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Validate requested channel exists and is plausible for ASU use from A discovery/session context; B confirm-zero must pass; final A snapshot must not show new errors. | If channel validation fails, do not switch path. If B path flow fails after zero/disable, keep outputs disabled and require manual review. | `channel`, `path`, `enable_1pa_range`, `indicator_enabled`, `filter_enabled`, `confirm_timeout_s`, `require_discovery` | `discovery_or_pre_status`, `validated_channel`, `path_result`, `annotated_errors`, `post_status` | ASU path switching needs A discovery/validation and B path state changes. Neither A nor B alone is sufficient. | A module inventory may not fully describe ASU topology; station profile validation is still needed. Path switching can affect DUT fixture routing. | P1 |
| `AB_flow_prepare_scuu_path_verified` | Discover/validate context, safely switch SCUU path, and verify errors/status afterward. | `A_flow_discover_b1500_session` or `A_flow_snapshot_b1500_status` -> validate requested channel/path mode -> `B_flow_prepare_scuu_path` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Validate channel and requested path mode before B; B confirm-zero must pass; final A snapshot and drained errors must be acceptable. | If validation is incomplete, require `allow_unverified_fixture_path=true`. If post error drain reports path errors, return `ok=false` but leave safe disabled state. | `channel`, `path_mode`, `indicator_enabled`, `confirm_timeout_s`, `allow_unverified_fixture_path` | `pre_context`, `path_result`, `annotated_errors`, `post_status` | SCUU path switching is exactly an AB workflow: A context + B routing + A readback. | Pure A cannot switch paths; pure B cannot know whether SCUU exists. Final status cannot physically verify cabling. | P1 |
| `AB_flow_prepare_cmu_correction_verified` | Perform CMU open/short/load correction with precondition snapshot and post error/status capture. | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_prepare_cmu_correction_data` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Pre-status should show no active operation; preflight must pass; caller must acknowledge fixture condition; B correction result must pass; final errors/status are logged. | If fixture acknowledgement missing, stop before B correction. If B measurement/correction fails, do not enable correction state unless B flow reports it already did; final A drain is still attempted. | `correction_type`, `channel`, `fixture_condition_ack`, `clear_existing`, `device_type`, `pin_map_known`, `confirm_timeout_s` | `pre_status`, `preflight`, `correction_result`, `annotated_errors`, `post_status` | CMU correction is B, but correctness and auditability depend on A status/error capture around it. | The correction atom performs a calibration-style measurement of fixture condition, but not a DUT measurement recipe. Requires correct open/short/load physical setup. | P1 |
| `AB_flow_perform_cmu_phase_compensation_verified` | Perform MFCMU phase compensation with preflight, zero bracket, and post status/error evidence. | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_perform_cmu_phase_compensation` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Preflight must pass; open-terminal/fixture acknowledgement required; B result code checked; final A drain/snapshot logged. | If preflight fails or fixture ack is missing, stop before compensation. If A post-check fails, return `partial=true` with B result preserved. | `channel`, `mode`, `fixture_condition_ack`, `device_type`, `pin_map_known`, `confirm_timeout_s` | `pre_status`, `preflight`, `phase_compensation`, `annotated_errors`, `post_status` | Phase compensation is stateful B correction requiring A evidence before/after. | Can take around 30 seconds. Pure AB still cannot prove physical terminal openness; operator/station profile must attest it. | P1 |
| `AB_flow_perform_qscv_offset_cancel_verified` | Perform QSCV offset/zero cancellation with status/error capture and no QSCV measurement execution. | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_perform_qscv_offset_cancel` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Pre-status no active operation; preflight passes; B offset cancel result code checked; post-status/errors logged. | If preflight fails, do not cancel. If B cancel reports failure, still drain errors and snapshot. | `channel`, `device_type`, `pin_map_known`, `confirm_timeout_s` | `pre_status`, `preflight`, `offset_cancel`, `annotated_errors`, `post_status` | QSCV offset cancellation is B state/correction; surrounding A makes it auditable and ready for later C recipes. | Must not be confused with running QSCV measurement. Exact fixture requirements remain to be validated. | P2 |
| `AB_flow_open_wgfmu_safe_baseline` | Open a WGFMU session, initialize WGFMU baseline/warning policy, and capture diagnostics. | `A_flow_discover_wgfmu_session` -> `B_flow_prepare_wgfmu_safe_baseline` -> `A_flow_snapshot_wgfmu_diagnostics` | A discovery must open session and discover channel IDs; B initialize/warning policy must complete; final A diagnostics must have no blocking errors/warnings. | If A open/discovery fails, do not run B. If B initialize succeeds but final diagnostics fail, return `partial=true` and keep session open for manual handling. | `address`, `timeout_s`, `warnings_as_errors` | `wgfmu_session`, `channel_ids`, `baseline_result`, `diagnostics` | WGFMU baseline requires A session open and B initialize. This is the canonical WGFMU startup AB flow. | WGFMU initialize changes channel/library state. Pure AB cannot verify execution status until missing A status atoms are added. | P0 |
| `AB_flow_maintenance_wgfmu_self_test_calibration` | Run WGFMU self-test/calibration with A diagnostics before and after. | `A_flow_discover_wgfmu_session` or `A_flow_prepare_wgfmu_logging_session` -> `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_self_test_calibrate_wgfmu` -> `A_flow_snapshot_wgfmu_diagnostics` | Session/channel discovery must succeed; pre-diagnostics captured; B self-test/calibration result pass; post diagnostics checked. | If pre-diagnostics show errors and `allow_maintenance_with_existing_errors=false`, stop before B. If B maintenance fails, still run final diagnostics. | `address`, `timeout_s`, `log_file`, `warnings_as_errors`, `run_calibration`, `post_calibration_self_test`, `allow_maintenance_with_existing_errors` | `session_context`, `pre_diagnostics`, `maintenance_result`, `post_diagnostics` | WGFMU maintenance combines A session/diagnostics and B self-test/calibration; accepted pure flows intentionally separate these. | A flow timeout must be large enough for maintenance. Missing A WGFMU status atoms limit progress/state verification. | P1 |
| `AB_flow_close_wgfmu_session_safely` | Bring WGFMU to safe baseline, capture diagnostics, and close the WGFMU session/log. | `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_prepare_wgfmu_safe_baseline` -> `A_flow_close_wgfmu_session_with_diagnostics` | Pre-close diagnostics recorded; B initialize/warning policy should complete; A close flow records final summaries and closes optional log/session. | If pre-diagnostics fail, still attempt B baseline unless session is unavailable. If B baseline fails, do not close by default unless `force_close_after_baseline_failure=true`. | `warnings_as_errors`, `close_log_file`, `force_close_after_baseline_failure` | `pre_diagnostics`, `baseline_result`, `close_context`, `closed` | Pure A close does not initialize/clear WGFMU state; pure B baseline cannot close session. AB provides a safer teardown. | `WGFMU_initialize` is not a substitute for aborting an active sequence if a WGFMU abort atom is missing. | P1 |
| `AB_flow_open_easyexpert_workspace_zero_cancel` | Discover EasyEXPERT remote, open a workspace, run EasyEXPERT SMU zero-cancel bracket, and record remote errors/state. | `A_flow_discover_easyexpert_remote` -> `A_flow_open_easyexpert_workspace_context` -> `B_flow_easyexpert_zero_cancel_bracket` -> direct `A_atom_easyexpert_wait_operation_complete` -> direct `A_atom_easyexpert_read_system_error` -> direct `A_atom_easyexpert_get_workspace_state` | Remote identity/workspace state must be known; workspace open must complete; B zero-cancel state query must report enabled if requested; final system error must be no-error. | If workspace open fails, do not run B zero-cancel. If zero-cancel fails, still read system error and workspace state. | `workspace`, `channel`, `force_off_first`, `measure_zero_cancel`, `enable_after_measure`, `timeout_s` | `remote_context`, `workspace_context`, `zero_cancel`, `system_error`, `workspace_state` | EasyEXPERT zero-cancel needs A remote/workspace context plus B calibration/state actions. Direct A atoms are used for tight post-B verification instead of broader catalog/result flows. | Zero-cancel is calibration/state control, not a test run. Requires EasyEXPERT remote to be ready; no selected application test is executed. | P1 |
| `AB_flow_easyexpert_abort_recover_remote` | Abort selected EasyEXPERT measurement/state, set standby, wait, and read remote error/workspace state. | `A_flow_discover_easyexpert_remote` or direct `A_atom_easyexpert_get_workspace_state` -> `B_flow_easyexpert_abort_to_standby` -> direct `A_atom_easyexpert_wait_operation_complete` -> direct `A_atom_easyexpert_read_system_error` -> direct `A_atom_easyexpert_get_workspace_state` | Pre workspace state captured; B abort/standby completes; `*OPC?` completes; system error is logged; final workspace state is known. | If A pre-state fails, still run B abort when `emergency=true`. If B abort fails, still attempt A error read if remote is responsive. | `standby_enabled`, `timeout_s`, `emergency`, `discover_first` | `pre_context`, `abort_standby`, `operation_complete`, `system_error`, `workspace_state` | Accepted B EasyEXPERT stop lacks wait/error readback; accepted A flows cannot abort. AB is required for recoverable remote stop. | Abort may discard running measurement state; fetching latest result is intentionally not included unless caller separately asks to collect pre-existing results. | P0 |
| `AB_flow_easyexpert_workspace_safe_teardown` | Stop selected EasyEXPERT activity, place standby, then close workspace with A verification. | `B_flow_easyexpert_abort_to_standby` -> direct `A_atom_easyexpert_wait_operation_complete` -> direct `A_atom_easyexpert_read_system_error` -> `A_flow_teardown_easyexpert_workspace` | Abort/standby sent first; operation complete and system error read before workspace close; teardown flow closes and reads final remote error. | If abort reports failure, do not close workspace unless `force_close_workspace=true`. If close fails, return final error state from teardown flow. | `standby_enabled`, `timeout_s`, `force_close_workspace` | `abort_standby`, `pre_close_error`, `teardown_context`, `closed` | A-only workspace teardown does not stop/standby selected activity; B-only abort cannot close or verify. | Pure AB still cannot guarantee DUT output state outside EasyEXPERT standby semantics. | P1 |

## Rejected / Too Broad AB_flow Candidates

| Candidate | Why Rejected |
|---|---|
| `AB_flow_full_station_startup` | Too broad: direct B1500A, WGFMU, and EasyEXPERT use separate transports and failure modes. A higher-level application should call focused AB flows and aggregate results. |
| `AB_flow_run_iv_sweep_safely` | Requires future C measurement atoms for force/sweep/execute/read semantics. AB can prepare and verify state only. |
| `AB_flow_run_cv_sweep_with_cmu_correction` | CMU correction can be AB, but CV sweep execution is C. |
| `AB_flow_run_wgfmu_pulse_recipe` | WGFMU session/baseline can be AB, but waveform programming/execution/result retrieval belongs to C/AC/ABC design. |
| `AB_flow_easyexpert_select_and_run_application_test` | Selecting may become B, discovery is A, but running the selected test is C-class measurement execution. |
| `AB_flow_enable_channels_for_measurement` | Current B arbitration deferred enable-for-measurement because compliance/range validation atoms are missing and measurement context is C. |
| `AB_flow_apply_compliance_and_arm_outputs` | Missing B compliance/range atoms and likely future C recipe context. |
| `AB_flow_recover_zeroed_outputs_and_continue_measurement` | `B_atom_recover_zeroed_outputs` requires prior `DZ` context; continuing a measurement requires C orchestration. |
| `AB_flow_wgfmu_emergency_stop` | Missing `B_atom_wgfmu_abort_operation`; `B_flow_prepare_wgfmu_safe_baseline` is not a controlled abort. |
| `AB_flow_export_easyexpert_all_results` | Existing A result flow fetches latest result only; broader export/sibling-result collection needs missing A atoms and may be too broad. |
| `AB_flow_auto_calibrate_everything` | Direct B1500A, WGFMU, EasyEXPERT, CMU, and QSCV calibration/correction operations are separate with different fixture assumptions. A monolithic flow would be unsafe and unauditable. |
| `AB_flow_collect_existing_results_then_make_safe` | Too broad across direct B1500A and EasyEXPERT transports. Keep result collection and safety recovery in focused domain-specific AB flows unless a higher-level application orchestrates them. |

## Missing Atoms / Flows Noted During Planning

| Missing Atom / Flow | Why It Is Needed | Impact |
|---|---|---|
| `B_atom_set_channel_compliance_limits` | Needed before any robust AB channel-enable/output-arm workflow. | Keeps `AB_flow_enable_channels_for_measurement` rejected. |
| `B_atom_confirm_channel_disabled` and `B_atom_query_channel_output_state` | Needed to verify that B zero/disable flows reached disabled state, not only near-zero voltage. | Would strengthen emergency and safe shutdown verification. |
| `B_atom_validate_channels_for_state_change` | Needed to validate station profile/pin map/channel roles without relying only on A hardware discovery. | Would make ASU/SCUU and future channel-enable AB flows safer. |
| `B_atom_query_asu_path` / `B_atom_query_scuu_path` | Needed for direct verification of path switching and reversible restore flows. | Current AB path flows verify errors/status but cannot confirm actual path state. |
| `B_atom_validate_path_switch_fixture_state` | Needed to formally validate fixture/contact state before ASU/SCUU/CMU path or correction changes. | Current AB flows require external `fixture_condition_ack`. |
| `A_atom_wgfmu_get_status` / `A_atom_wgfmu_get_channel_status` | Needed to verify WGFMU running/idle/channel progress after initialize/self-test/calibration. | Limits WGFMU AB flows to error/warning diagnostics. |
| `B_atom_wgfmu_abort_operation` | Needed for a true WGFMU emergency stop flow. | Prevents accepting `AB_flow_wgfmu_emergency_stop`. |
| `A_atom_query_service_request_mask` | Needed to make status polling configuration reversible and auditable. | `AB_flow_configure_b1500_polling_with_safety_gate` cannot restore previous mask. |
| `B_atom_query_auto_calibration_policy`, `B_atom_query_smu_filter_state`, `B_atom_query_adc_zero_state` | Needed for reversible SMU baseline configuration. | Current baseline flow records requested state but cannot restore previous state. |
| `B_atom_easyexpert_query_standby_state` / `B_atom_easyexpert_query_selected_measurement_state` | Needed for stronger EasyEXPERT abort/standby idempotency. | Current EasyEXPERT AB recovery relies on A workspace/error state plus B atom return. |
| `B_atom_easyexpert_select_application_test` / `B_atom_easyexpert_select_preset_setup` | Needed if EasyEXPERT state selection is classified as B state control. | Would enable AB selection-and-verify flows that still do not execute tests. |
| `A_atom_easyexpert_get_selected_test_name` | Needed to verify selected EasyEXPERT test/setup after a future B selection atom. | Blocks safe AB selected-test verification. |
| `A_atom_easyexpert_fetch_result_siblings` | Needed for complete EasyEXPERT result collection without running a new measurement. | Keeps broad EasyEXPERT result export rejected. |

## Design Notes

### Naming

- Use `AB_flow_<verb>_<domain>_<object>` with no numeric prefixes.
- Names should make safety/action explicit: `start_b1500_safe_session`, `emergency_recover_b1500_session`, `reset_rediscover_b1500_state`.
- Avoid names that imply measurement execution: no `run_iv`, `run_cv`, `run_pulse`, `execute_test`, or `measure_device`.
- Use `verified` only when the flow has an A verification step after the B action. If final verification is partial because atoms are missing, say so in `warnings`.

### Return Schema

AB_flow responses should include both flow-level and checkpoint-level detail:

```python
{
    "flow": "AB_flow_<name>",
    "fake": True,
    "hardware_touched": False,
    "ok": bool,
    "partial": bool,
    "phase": "discover|precheck|action|verify|teardown|failed",
    "flows_called": ["A_flow_...", "B_flow_..."],
    "atoms_called": ["A_atom_...", "B_atom_..."],
    "checkpoints": [
        {"name": "pre_status", "ok": true, "result_ref": "..."},
        {"name": "b_action", "ok": true, "result_ref": "..."},
        {"name": "post_verify", "ok": true, "result_ref": "..."}
    ],
    "warnings": [],
    "cautions": [],
    "audit": {
        "requested_by": "...",
        "reason": "...",
        "timestamp": "...",
        "consumed_buffers": false,
        "cleared_errors": false
    },
    "results": {}
}
```

For fake tools, `hardware_touched` remains false. For real B-class actions, `hardware_touched` should be true even when surrounding A reads are non-destructive.

### Error Semantics

- AB flows should distinguish:
  - **precheck failure**: no B action attempted.
  - **B action failure**: safety/state operation failed; attempt A logging if safe.
  - **post-verification failure**: B action may have succeeded, but final state cannot be proven.
  - **audit/data-loss warning**: output buffer or error queue was consumed/cleared.
- Emergency flows should favor safety over observability. If A pre-snapshot fails, still run B emergency actions when requested.
- Non-emergency destructive flows should favor observability over action. If A pre-snapshot or buffer preservation fails, stop unless explicitly overridden.
- Error drains are destructive. Any AB flow using `A_flow_drain_b1500_errors` must preserve drained error records in the return/audit payload.

### Idempotency

- Mostly idempotent: `AB_flow_start_b1500_safe_session`, `AB_flow_zero_disable...`-style shutdown when repeated, `AB_flow_open_wgfmu_safe_baseline` if session reuse is handled.
- Intentionally state-resetting: `AB_flow_reset_rediscover_b1500_state`, correction/phase/QSCV flows, EasyEXPERT zero-cancel.
- Emergency recovery is repeatable but should create a new audit event each time.
- Flows that clear buffers/errors are not idempotent from a data/audit perspective, even if final instrument state repeats.

### Audit Logging

- Every AB flow should record `requested_by`, `reason`, and an `operator_intent` string once real hardware is enabled.
- Any flow that can consume output buffers or clear error queues must record `consumed_buffers` / `cleared_errors`.
- Maintenance/calibration flows should record calibration date/time, result codes, and whether the run was scheduled or incident-driven.
- Path/correction flows should record fixture acknowledgements, channel numbers, correction type/path mode, and station profile version when available.

### Implementation Boundaries

- Prefer composing accepted A/B flows first. Use direct atoms only for narrow verification steps where a full accepted flow would reconnect, rediscover catalogs, fetch unrelated data, or close a session prematurely.
- Keep GPIB/EasyEXPERT/WGFMU execution serial unless the transport layer explicitly supports concurrent calls.
- Do not fold P2 convenience flows into P0 safety flows. P0 flows must remain predictable and auditable.
