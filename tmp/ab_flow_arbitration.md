# AB Flow Arbitration

This is the parent-agent arbitration after reading:

- `tmp/ab_flow_candidates_opus.md`
- `tmp/ab_flow_candidates_gpt.md`

Scope: `AB_flow_*` may compose accepted `A_flow_*`, accepted `B_flow_*`, and narrow direct `A_atom_*` / `B_atom_*` calls when a full accepted flow is too broad. It must not call future `C_atom_*` tools or start any IV/CV/pulse/EasyEXPERT measurement.

Core pattern: observe/discover with A -> act/change state with B -> verify/log with A.

## Accepted AB_flow Set

| Flow Name | Priority | Sequence | Meaning |
|---|---|---|---|
| `AB_flow_start_b1500_safe_session` | P0 | `A_flow_discover_b1500_session` -> `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `A_flow_snapshot_b1500_status` | Standard direct B1500A safe-session entry. Establishes identity/modules/settings/error context and applies the B preflight gate. |
| `AB_flow_emergency_recover_b1500_session` | P0 | optional `A_flow_snapshot_b1500_status` -> `B_flow_emergency_abort_and_zero_outputs` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Emergency recovery: act to make outputs safe, then drain/log errors and capture final status. |
| `AB_flow_safe_shutdown_b1500_session` | P0 | optional `A_flow_collect_b1500_output_buffer` -> `B_flow_zero_disable_b1500_outputs` -> `A_flow_record_b1500_disconnect_context` | Safe direct-session shutdown. Preserves optional pre-existing data, then zeros/disables, records final context, and disconnects. |
| `AB_flow_reset_rediscover_b1500_state` | P0 | `A_flow_snapshot_b1500_status` -> `B_flow_reset_initialize_b1500_state` -> direct `A_atom_identify_b1500` -> direct `A_atom_list_installed_modules` -> direct `A_atom_query_current_settings` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Reset/initialize, then rediscover and verify instrument state. |
| `AB_flow_maintenance_b1500_self_test_calibration` | P1 | `A_flow_snapshot_b1500_status` -> `B_flow_self_test_calibrate_b1500` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Auditable B1500A self-test/calibration bracket with pre/post evidence. |
| `AB_flow_prepare_b1500_nonmeasurement_baseline` | P1 | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_configure_smu_baseline_state` -> `A_flow_prepare_b1500_output_buffer` -> `A_flow_snapshot_b1500_status` | Non-measurement baseline setup: housekeeping state plus parser/buffer preparation. |
| `AB_flow_configure_b1500_polling_with_safety_gate` | P2 | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `A_flow_configure_b1500_status_polling` -> `A_flow_snapshot_b1500_status` | Configure status/SRQ polling only after safety gate and with post-status capture. |
| `AB_flow_prepare_asu_low_current_path_verified` | P1 | `A_flow_discover_b1500_session` or `A_flow_snapshot_b1500_status` -> validate channel from A context -> `B_flow_prepare_asu_low_current_path` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Safe ASU low-current path preparation with module/context and post-error/status evidence. |
| `AB_flow_prepare_scuu_path_verified` | P1 | `A_flow_discover_b1500_session` or `A_flow_snapshot_b1500_status` -> validate channel/path -> `B_flow_prepare_scuu_path` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Safe SCUU path switching with context and verification. |
| `AB_flow_prepare_cmu_correction_verified` | P1 | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_prepare_cmu_correction_data` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | Open/short/load correction with fixture acknowledgement and post-error/status capture. |
| `AB_flow_perform_cmu_phase_compensation_verified` | P1 | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_perform_cmu_phase_compensation` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | MFCMU phase compensation with preflight and post diagnostics. |
| `AB_flow_perform_qscv_offset_cancel_verified` | P1 | `A_flow_snapshot_b1500_status` -> `B_flow_run_b1500_preflight_gate` -> `B_flow_perform_qscv_offset_cancel` -> `A_flow_drain_b1500_errors` -> `A_flow_snapshot_b1500_status` | QSCV offset-cancel precursor; not a QSCV measurement. |
| `AB_flow_open_wgfmu_safe_baseline` | P0 | `A_flow_discover_wgfmu_session` -> `B_flow_prepare_wgfmu_safe_baseline` -> `A_flow_snapshot_wgfmu_diagnostics` | Canonical WGFMU startup baseline: open session, initialize warning baseline, snapshot diagnostics. |
| `AB_flow_maintenance_wgfmu_self_test_calibration` | P1 | `A_flow_discover_wgfmu_session` or `A_flow_prepare_wgfmu_logging_session` -> `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_self_test_calibrate_wgfmu` -> `A_flow_snapshot_wgfmu_diagnostics` | WGFMU self-test/calibration with session and diagnostic evidence. |
| `AB_flow_close_wgfmu_session_safely` | P1 | `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_prepare_wgfmu_safe_baseline` -> `A_flow_close_wgfmu_session_with_diagnostics` | WGFMU safe-ish close: diagnostics, baseline, diagnostic close. Not a true emergency stop. |
| `AB_flow_easyexpert_abort_recover_remote` | P0 | optional `A_flow_discover_easyexpert_remote` or direct `A_atom_easyexpert_get_workspace_state` -> `B_flow_easyexpert_abort_to_standby` -> direct `A_atom_easyexpert_wait_operation_complete` -> direct `A_atom_easyexpert_read_system_error` -> direct `A_atom_easyexpert_get_workspace_state` | EasyEXPERT abort/standby recovery with operation-complete, error, and workspace-state evidence. |
| `AB_flow_open_easyexpert_workspace_zero_cancel` | P1 | `A_flow_discover_easyexpert_remote` -> `A_flow_open_easyexpert_workspace_context` -> `B_flow_easyexpert_zero_cancel_bracket` -> direct `A_atom_easyexpert_wait_operation_complete` -> direct `A_atom_easyexpert_read_system_error` -> direct `A_atom_easyexpert_get_workspace_state` | Open workspace and manage zero-cancel calibration state with remote verification. |
| `AB_flow_easyexpert_workspace_safe_teardown` | P1 | `B_flow_easyexpert_abort_to_standby` or direct `B_atom_easyexpert_set_standby` -> direct `A_atom_easyexpert_wait_operation_complete` -> direct `A_atom_easyexpert_read_system_error` -> `A_flow_teardown_easyexpert_workspace` | Put EasyEXPERT into standby/abort state, then close workspace with A verification. |

## Rejected Or Deferred

| Candidate | Decision |
|---|---|
| Full-station startup/shutdown across B1500A + WGFMU + EasyEXPERT | Too broad; separate transports and failure modes. Application layer can call multiple focused AB flows. |
| Any IV/CV/pulse/WGFMU waveform/EasyEXPERT run flow | Requires future C atoms. |
| Enable channels for measurement readiness | Missing compliance/range/role validation atoms and future C context. |
| WGFMU emergency stop | Missing `B_atom_wgfmu_abort_operation`; initialize is not a true abort. |
| EasyEXPERT select-and-run application test | Selection is unresolved B state-control; running is C. |
| Auto-calibrate everything | Too broad and unsafe; use endpoint-specific maintenance/correction flows. |

## Missing Atoms / Flows To Consider

| Missing Item | Reason |
|---|---|
| `A_atom_query_service_request_mask` | Reversible status-polling configuration. |
| `A_atom_serial_poll_status_byte` | Accurate SRQ/interrupt semantics. |
| `A_atom_wgfmu_get_status`, `A_atom_wgfmu_get_channel_status` | Strong WGFMU post-action verification and progress monitoring. |
| `A_atom_easyexpert_get_selected_test_name`, `A_atom_easyexpert_fetch_result_siblings` | EasyEXPERT selected-test/result verification. |
| `B_atom_set_channel_compliance_limits` | Required before safe channel-arm flows. |
| `B_atom_confirm_channel_disabled`, `B_atom_query_channel_output_state` | Stronger output-safe verification. |
| `B_atom_query_asu_path`, `B_atom_query_scuu_path` | Direct path verification/restoration. |
| `B_atom_validate_path_switch_fixture_state` | Safer ASU/SCUU/CMU switching and correction workflows. |
| `B_atom_query_cmu_correction_state`, `B_atom_query_cmu_phase_compensation_mode` | Reversible CMU correction/phase workflows. |
| `B_atom_wgfmu_abort_operation` | True WGFMU emergency recovery. |
| `B_atom_easyexpert_query_standby_state`, `B_atom_easyexpert_query_selected_measurement_state` | Stronger EasyEXPERT abort/standby idempotency. |
| `B_atom_easyexpert_select_application_test`, `B_atom_easyexpert_select_preset_setup` | Needed if selected-test/setup state-control is classified as B. |

## Parent Arbitration Notes

- P0 AB flows are the ones users should see as safe-session, emergency, shutdown, and endpoint-baseline workflows.
- AB flows must return phased evidence: `observe`, `act`, `verify`.
- Emergency flows may start with B action before A observation.
- Non-emergency destructive flows should stop if A pre-observation fails unless explicitly overridden.
- Any flow that drains error queues or reads/clears buffers must preserve consumed data in the audit payload.
- AB_flow still cannot certify DUT safety, fixture correctness, or measurement validity without station profile and future C recipe validation.
