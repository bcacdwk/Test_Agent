# B Flow Arbitration

This is the parent-agent arbitration after reading:

- `tmp/b_flow_candidates_opus.md`
- `tmp/b_flow_candidates_gpt.md`

Scope: pure `B_flow_*` only. A `B_flow` may compose only `B_atom_*` tools. It must not connect, disconnect, query instrument identity, list modules, drain errors, fetch results, or run measurements.

## Accepted B_flow Set

| Flow Name | Priority | Atom Sequence | Notes |
|---|---|---|---|
| `B_flow_emergency_abort_and_zero_outputs` | P0 | `B_atom_abort_operation` -> `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` | Core direct-B1500 emergency state-control primitive. If abort fails, real implementation should still attempt zero/disable. |
| `B_flow_zero_disable_b1500_outputs` | P0 | `B_atom_zero_outputs` -> `B_atom_disable_channels` -> `B_atom_confirm_zero_outputs` | Standard non-emergency output shutdown bracket for selected/all channels. |
| `B_flow_reset_initialize_b1500_state` | P0 | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> `B_atom_reset_instrument` -> optional `B_atom_initialize_instrument` | Known-state reset after safe output handling. Does not verify status; AB_flow should do that. |
| `B_flow_run_b1500_preflight_gate` | P0 | `B_atom_check_interlock_status` -> `B_atom_run_preflight_checks` | B-only safety gate. It does not replace A discovery/status snapshots. |
| `B_flow_self_test_calibrate_b1500` | P1 | `B_atom_run_self_test` -> optional `B_atom_run_self_calibration` -> optional `B_atom_run_self_test` | Maintenance bracket. No A status/error readback included. |
| `B_flow_configure_smu_baseline_state` | P1 | optional `B_atom_set_auto_calibration` -> `B_atom_set_adc_zero` -> per-channel `B_atom_set_smu_filter` | Sets SMU housekeeping policy; not a measurement setup. |
| `B_flow_prepare_asu_low_current_path` | P1 | `B_atom_zero_outputs` -> `B_atom_disable_channels` -> `B_atom_confirm_zero_outputs` -> `B_atom_set_asu_path` -> optional `B_atom_set_asu_1pa_range` -> optional `B_atom_set_asu_indicator` -> optional `B_atom_set_smu_filter` | ASU path/low-current preparation with safe output bracket. |
| `B_flow_prepare_scuu_path` | P1 | `B_atom_zero_outputs` -> `B_atom_disable_channels` -> `B_atom_confirm_zero_outputs` -> `B_atom_set_scuu_path` -> optional `B_atom_set_scuu_indicator` | SCUU path switching bracket; real flow needs prior A discovery/station validation. |
| `B_flow_prepare_cmu_correction_data` | P1 | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> optional `B_atom_clear_cmu_correction_data` -> `B_atom_set_cmu_correction_state(..., false)` -> `B_atom_measure_cmu_correction_data` -> `B_atom_set_cmu_correction_state(..., true)` | Open/short/load correction bracket. Requires physical fixture condition acknowledgement. |
| `B_flow_perform_cmu_phase_compensation` | P1 | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> `B_atom_set_cmu_phase_compensation_mode` -> `B_atom_perform_cmu_phase_compensation` | MFCMU phase compensation bracket. |
| `B_flow_perform_qscv_offset_cancel` | P1 | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> `B_atom_perform_qscv_offset_cancel` | QSCV offset/zero cancel before future QSCV measurement recipes. |
| `B_flow_prepare_wgfmu_safe_baseline` | P0 | `B_atom_wgfmu_initialize` -> `B_atom_wgfmu_treat_warnings_as_errors` | WGFMU baseline state and warning policy. Requires WGFMU session from A/AB layer. |
| `B_flow_self_test_calibrate_wgfmu` | P1 | optional `B_atom_wgfmu_treat_warnings_as_errors` -> `B_atom_wgfmu_do_self_test` -> optional `B_atom_wgfmu_do_self_calibration` -> optional `B_atom_wgfmu_do_self_test` | WGFMU maintenance bracket. No A diagnostics included. |
| `B_flow_easyexpert_abort_to_standby` | P0 | `B_atom_easyexpert_abort_selected_measurement` -> `B_atom_easyexpert_set_standby` | EasyEXPERT remote stop/standby state-control. AB_flow should add wait/error readback. |
| `B_flow_easyexpert_zero_cancel_bracket` | P1 | optional `B_atom_easyexpert_zero_cancel_off` -> optional `B_atom_easyexpert_measure_zero_cancel` -> `B_atom_easyexpert_zero_cancel_on` -> `B_atom_easyexpert_query_zero_cancel_state` | EasyEXPERT SMU zero-cancel calibration/state bracket. |

## Rejected Or Deferred

| Candidate | Decision |
|---|---|
| `B_flow_safe_disconnect_b1500` | Reject from pure B. Requires `A_atom_disconnect_b1500`; AB_flow candidate. |
| `B_flow_connect_reset_and_verify_b1500` | Reject from pure B. Requires A connect/discovery/status; AB_flow candidate. |
| `B_flow_abort_zero_and_drain_errors` | Reject from pure B. Error drain is A. AB emergency recovery candidate. |
| `B_flow_enable_channels_for_measurement` | Defer. Current atoms lack compliance/range validation and C measurement context. |
| `B_flow_run_b1500_diagnostics_set` | Defer until diagnostic item catalog is extracted; currently mostly a loop over `B_atom_run_diagnostics`. |
| `B_flow_wgfmu_open_initialize_self_test` | Reject from pure B. WGFMU open/timeout/channel discovery are A. AB_flow candidate. |
| `B_flow_easyexpert_abort_wait_fetch_result` | Reject from pure B. Wait/error/result fetch are A. AB_flow candidate. |
| `B_flow_easyexpert_open_workspace_zero_cancel` | Reject from pure B. Workspace open/state is A. AB_flow candidate. |
| `B_flow_select_easyexpert_application_test` | Defer. Needs new B atoms and classification discussion; selection changes app state but does not execute. |

## Missing B_atoms To Consider Later

| Missing Atom | Why |
|---|---|
| `B_atom_set_channel_compliance_limits` | Needed before robust channel-enable or output-arm flows. |
| `B_atom_validate_channels_for_state_change` | Would validate station profile/pin map without A hardware query. |
| `B_atom_confirm_channel_disabled` | Stronger audit than voltage-zero confirmation alone. |
| `B_atom_query_channel_output_state` | Needed for B-only state verification. |
| `B_atom_query_auto_calibration_policy` / `B_atom_restore_auto_calibration_policy` | Needed for reversible auto-calibration bracketing. |
| `B_atom_query_smu_filter_state` / `B_atom_query_adc_zero_state` | Needed for reversible SMU baseline flows. |
| `B_atom_query_asu_path` / `B_atom_query_scuu_path` | Needed to verify path switching or restore prior path. |
| `B_atom_validate_path_switch_fixture_state` | Needed before ASU/SCUU switching. |
| `B_atom_query_cmu_correction_state` / `B_atom_query_cmu_phase_compensation_mode` | Needed for reversible CMU correction/phase flows. |
| `B_atom_wgfmu_abort_operation` | Needed for WGFMU emergency stop flow. |
| `B_atom_easyexpert_query_standby_state` / `B_atom_easyexpert_query_selected_measurement_state` | Needed for EasyEXPERT idempotent stop/standby flows. |
| `B_atom_easyexpert_select_application_test` / `B_atom_easyexpert_select_preset_setup` | Likely B state-control atoms, but defer until AB_flow discussion. |

## Parent Arbitration Notes

- P0 B_flow should be explicit operator-intent actions, not hidden background conveniences.
- B_flow may make the system safer, but without A readbacks it cannot claim complete verified health.
- Most B_flow execution should be serial. Do not assume safe parallel state-changing commands over one instrument session.
- Flow return schema should include `flow`, `fake`, `hardware_touched`, `atoms_called`, `ok`, `partial`, `warnings`, `cautions`, and raw per-atom results.
- This arbitration is the accepted Phase 2 result. AB_flow planning should now combine accepted A_flow and B_flow pieces into verified workflows.
