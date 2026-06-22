# A Flow Arbitration

This is the parent-agent arbitration after reading:

- `tmp/a_flow_candidates_opus.md`
- `tmp/a_flow_candidates_gpt.md`

Scope: pure `A_flow_*` only. An `A_flow` may compose only `A_atom_*` tools. It must not reset, initialize, calibrate, abort, enable channels, zero outputs, change DUT-facing output state, run self-test, run diagnostics, or perform measurements.

## Accepted A_flow Set

| Flow Name | Priority | Atom Sequence | Notes |
|---|---|---|---|
| `A_flow_discover_b1500_session` | P0 | `A_atom_connect_b1500` -> `A_atom_identify_b1500` -> `A_atom_list_installed_modules` -> `A_atom_query_current_settings` -> `A_atom_read_error_queue` -> `A_atom_read_status_byte` | Standard direct B1500A entry flow. Use serial query order on real GPIB even if some reads are conceptually independent. |
| `A_flow_snapshot_b1500_status` | P0 | `A_atom_get_instrument_status` -> `A_atom_read_status_byte` -> `A_atom_read_error_queue` -> `A_atom_query_current_settings` -> `A_atom_query_output_buffer_count` | Unified non-destructive health/status snapshot. `clear_errors` should default false. |
| `A_flow_drain_b1500_errors` | P0 | `A_atom_read_error_queue(clear_after_read=true)` -> per-code `A_atom_lookup_error_message` -> `A_atom_read_status_byte` | Standard error drain and annotation flow. Must distinguish instrument lookup vs local structured-table lookup for extended codes. |
| `A_flow_collect_b1500_output_buffer` | P0 | `A_atom_wait_operation_complete` -> `A_atom_query_output_buffer_count` -> `A_atom_read_output_buffer` -> `A_atom_query_output_buffer_count` -> `A_atom_read_error_queue` -> `A_atom_read_status_byte` | Canonical output-buffer readout. It does not start measurement. |
| `A_flow_discover_wgfmu_session` | P0 | `A_atom_wgfmu_open_session` -> `A_atom_wgfmu_set_timeout` -> `A_atom_wgfmu_get_channel_ids` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | Standard WGFMU library entry flow. |
| `A_flow_snapshot_wgfmu_diagnostics` | P0 | `A_atom_wgfmu_read_error` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | Diagnostic snapshot for existing WGFMU session. |
| `A_flow_discover_easyexpert_remote` | P0 | `A_atom_easyexpert_identify_remote_host` -> `A_atom_easyexpert_read_system_error` -> `A_atom_easyexpert_list_workspaces` -> `A_atom_easyexpert_get_workspace_state` | Standard EasyEXPERT remote entry flow. Do not clear status by default; read errors first. |
| `A_flow_fetch_easyexpert_latest_result` | P0 | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_wait_operation_complete` -> `A_atom_easyexpert_set_result_format` -> `A_atom_easyexpert_fetch_latest_result` -> `A_atom_easyexpert_read_system_error` | Canonical EasyEXPERT result-readout flow. |
| `A_flow_prepare_b1500_output_buffer` | P1 | `A_atom_wait_operation_complete` -> `A_atom_set_data_format` -> `A_atom_configure_timestamp` -> optional `A_atom_reset_timestamp` -> `A_atom_clear_output_buffer` -> `A_atom_query_output_buffer_count` | Useful but stateful/destructive because it can clear unread data. Require explicit `allow_clear_buffer=true`; timestamp reset should be optional. |
| `A_flow_configure_b1500_status_polling` | P1 | `A_atom_configure_service_request` -> `A_atom_read_status_byte` -> `A_atom_read_error_queue` | Useful for clients that use SRQ/status-byte polling. Cannot restore previous mask until a query-mask atom exists. |
| `A_flow_record_b1500_disconnect_context` | P1 | optional `A_atom_query_output_buffer_count` / `A_atom_read_output_buffer` -> `A_atom_read_status_byte` -> `A_atom_read_error_queue` -> `A_atom_query_current_settings` -> `A_atom_disconnect_b1500` | A-only close-context flow. Must not be marketed as safe shutdown. Safe shutdown requires B/AB flow. |
| `A_flow_prepare_wgfmu_logging_session` | P1 | `A_atom_wgfmu_open_session` -> `A_atom_wgfmu_set_timeout` -> `A_atom_wgfmu_open_log_file` -> `A_atom_wgfmu_set_warning_level` -> `A_atom_wgfmu_get_channel_ids` -> `A_atom_wgfmu_read_error_summary` | Useful for long WGFMU jobs; still A-only because it changes library/logging session state, not DUT output state. |
| `A_flow_close_wgfmu_session_with_diagnostics` | P1 | `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` -> optional `A_atom_wgfmu_close_log_file` -> `A_atom_wgfmu_close_session` | A-only WGFMU teardown; does not initialize or zero WGFMU channels. |
| `A_flow_open_easyexpert_workspace_context` | P1 | `A_atom_easyexpert_identify_remote_host` -> `A_atom_easyexpert_list_workspaces` -> `A_atom_easyexpert_open_workspace` -> `A_atom_easyexpert_wait_operation_complete` -> `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_read_system_error` | Accept as A_flow: opens remote workspace but does not execute or alter DUT output. |
| `A_flow_discover_easyexpert_catalogs` | P1 | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_application_tests` -> `A_atom_easyexpert_list_preset_groups` -> per-group `A_atom_easyexpert_list_preset_setups` -> `A_atom_easyexpert_read_system_error` | Combines application-test and preset discovery. |
| `A_flow_select_easyexpert_application_context` | P1 | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_application_tests` -> `A_atom_easyexpert_select_application_test` -> optional `A_atom_easyexpert_get_selected_test_name` -> `A_atom_easyexpert_read_system_error` | Selects an EasyEXPERT application-test definition as software context only. This is A-class because it changes remote software selection, not DUT output and not measurement execution. |
| `A_flow_select_easyexpert_preset_setup_context` | P1 | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_preset_groups` -> `A_atom_easyexpert_open_preset_group` -> `A_atom_easyexpert_list_preset_setups` -> `A_atom_easyexpert_select_preset_setup` -> optional `A_atom_easyexpert_get_selected_test_name` -> `A_atom_easyexpert_read_system_error` | Selects an EasyEXPERT preset setup as software context only. This is A-class; actual run/execution remains future C-class. |
| `A_flow_teardown_easyexpert_workspace` | P1 | `A_atom_easyexpert_close_workspace` -> `A_atom_easyexpert_wait_operation_complete` -> `A_atom_easyexpert_read_system_error` | A-only workspace close. No measurement cleanup implied. |
| `A_flow_browse_easyexpert_presets` | P2 | `A_atom_easyexpert_list_preset_groups` -> per-group `A_atom_easyexpert_list_preset_setups` | Convenience subset of catalog discovery. Keep as P2; may be redundant if `A_flow_discover_easyexpert_catalogs` is implemented well. |

## Rejected Or Deferred

| Candidate | Decision |
|---|---|
| `A_flow_full_system_discovery` | Reject for now. Too broad: direct B1500A, WGFMU library, and EasyEXPERT remote are separate transports with separate failure modes. A higher-level app can call three P0 discovery flows. |
| `A_flow_safe_disconnect_b1500` | Reject from A. Requires B safety cleanup (`B_atom_zero_all_outputs`, confirmation). Consider `AB_flow_safe_disconnect_b1500` later. |
| `A_flow_connect_and_reset_b1500` | Reject from A. Reset/initialize are B atoms. |
| `A_flow_preflight_check` | Reject from A. Preflight is B because it gates safety and measurement permission. |
| `A_flow_wgfmu_initialize_and_discover` | Reject from A. WGFMU initialize is B. |
| `A_flow_wgfmu_enable_logging` | Reject as too thin unless folded into `A_flow_prepare_wgfmu_logging_session`. |

## Missing A_atoms To Consider Later

| Missing Atom | Why |
|---|---|
| `A_atom_query_service_request_mask` | Needed to make `A_flow_configure_b1500_status_polling` reversible. |
| `A_atom_serial_poll_status_byte` | Useful because serial poll and `*STB?` have different clearing semantics. |
| `A_atom_wgfmu_get_status` | Would improve WGFMU diagnostics with execution state. |
| `A_atom_wgfmu_get_channel_status` | Needed for long WGFMU progress monitoring. |
| `A_atom_wgfmu_get_warning_level` | Completes warning-level readback. |
| `A_atom_easyexpert_open_remote_session` / `A_atom_easyexpert_close_remote_session` | Useful if socket lifecycle is represented explicitly. |
| `A_atom_easyexpert_open_preset_group` | Likely needed before listing setups in a preset group. |
| `A_atom_easyexpert_select_application_test` | Exposed by EasyEXPERT `[:BENCh]:APPlication:SELect`; belongs to A because it changes software context only and does not execute measurement. |
| `A_atom_easyexpert_select_preset_setup` | Exposed by EasyEXPERT `[:BENCh]:PRESet:SETup:SELect`; belongs to A because it changes software context only and does not execute measurement. |
| `A_atom_easyexpert_fetch_result_siblings` | Useful for application-test sibling results. |
| `A_atom_easyexpert_get_selected_test_name` | Useful before execution verification. |

## Parent Arbitration Notes

- Prefer serial atom execution for real GPIB/EasyEXPERT/WGFMU sessions unless the transport layer explicitly supports safe concurrent queries.
- Flow return schema should include: `flow`, `fake`, `hardware_touched`, `atoms_called`, `partial`, `ok`, `warnings`, and raw per-atom results.
- A_flow names have no numeric ordering.
- This arbitration is the accepted Phase 1 result. B_flow planning should now proceed using only B atoms and should not revisit A_flow except to note composition boundaries.
