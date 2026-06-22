# B Flow Design Arbitration

Date: 2026-06-22

Status: parent arbitration after reading:

- `tmp/b_flow_design_opus46.md`
- `tmp/b_flow_design_gpt55.md`

This is the accepted design for first-pass `B_flow_*` implementation. B flows compose only `B_atom_*` tools. They do not connect, identify, query module inventory, drain errors, fetch buffers/results, wait OPC through A atoms, or execute measurements.

## Accepted B_flow Catalog

| Category | Flow Name | Priority | Atom Sequence | Purpose / Notes |
|---|---|---:|---|---|
| emergency | `B_flow_emergency_b1500_abort_zero` | P0 | `B_atom_safety_b1500_abort` -> `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` | Core direct B1500A emergency bracket. Continue zero/confirm even if abort fails. |
| emergency | `B_flow_emergency_wgfmu_abort_disconnect` | P0 | `B_atom_lifecycle_wgfmu_abort` -> per-channel `B_atom_output_wgfmu_disconnect` | Stop WGFMU sequencer and disconnect declared WGFMU outputs. Prefer this over initialize in an emergency; initialize remains baseline. |
| emergency | `B_flow_emergency_easyexpert_abort_standby` | P0 | `B_atom_safety_easyexpert_abort_measurement` -> `B_atom_output_easyexpert_set_standby` | Abort EasyEXPERT selected measurement and set requested standby state. |
| safe_state | `B_flow_safe_state_b1500_zero_disable` | P0 | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` | Standard non-emergency output cleanup bracket. |
| preflight | `B_flow_preflight_b1500_gate` | P0 | `B_atom_safety_b1500_check_interlock` -> `B_atom_safety_b1500_preflight` | Explicit B-only safety/readiness gate. |
| baseline | `B_flow_baseline_b1500_known_state` | P0 | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_lifecycle_b1500_reset` -> optional `B_atom_lifecycle_b1500_initialize` -> optional `B_atom_policy_b1500_set_auto_calibration` | Known-state reset bracket after zero/confirm. Destructive. |
| baseline | `B_flow_baseline_wgfmu_known_state` | P0 | `B_atom_lifecycle_wgfmu_initialize` -> optional `B_atom_policy_wgfmu_treat_warnings_as_errors` | WGFMU initialized baseline and warning policy. Requires pre-existing WGFMU session. |
| baseline | `B_flow_baseline_smu_housekeeping` | P1 | optional `B_atom_policy_b1500_set_auto_calibration` -> optional `B_atom_calibration_smu_set_adc_zero` -> per-channel optional `B_atom_output_smu_set_filter` -> per-channel optional `B_atom_output_smu_set_series_resistor` | Establish repeatable SMU housekeeping policy. No output enable. |
| maintenance | `B_flow_maintenance_b1500_self_test_calibration` | P1 | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_diagnostic_b1500_self_test` -> optional `B_atom_calibration_b1500_self_calibration` -> optional `B_atom_diagnostic_b1500_self_test` | B1500A self-test/calibration bracket. Long-running and operator-visible. |
| maintenance | `B_flow_maintenance_wgfmu_self_test_calibration` | P1 | optional `B_atom_policy_wgfmu_treat_warnings_as_errors` -> optional `B_atom_lifecycle_wgfmu_initialize` -> `B_atom_diagnostic_wgfmu_self_test` -> optional `B_atom_calibration_wgfmu_self_calibration` -> optional `B_atom_diagnostic_wgfmu_self_test` | WGFMU maintenance bracket. Requires pre-existing WGFMU session. |
| preparation | `B_flow_preparation_asu_low_current_path` | P1 | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_routing_asu_set_path` -> optional `B_atom_routing_asu_set_1pa_range` -> optional `B_atom_routing_asu_set_indicator` -> optional `B_atom_output_smu_set_filter` | Safe bracket for ASU low-current routing. Fixture/topology-sensitive. |
| preparation | `B_flow_preparation_scuu_signal_path` | P1 | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_routing_scuu_set_path` -> optional `B_atom_routing_scuu_set_indicator` | Safe bracket for SCUU routing. Fixture/topology-sensitive. |
| correction | `B_flow_correction_cmu_open_short_load` | P1 | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> optional `B_atom_correction_cmu_clear` -> per type: disable `B_atom_correction_cmu_set_correction` -> `B_atom_correction_cmu_measure_data` -> enable `B_atom_correction_cmu_set_correction` | CMU open/short/load correction for one or more types. Fixture acknowledgement required. |
| correction | `B_flow_correction_cmu_phase_compensation` | P1 | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_correction_cmu_set_phase_mode` -> `B_atom_correction_cmu_perform_phase_comp` | MFCMU phase compensation bracket. Fixture/open-terminal sensitive. |
| correction | `B_flow_correction_qscv_offset_cancel` | P1 | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_correction_qscv_offset_cancel` | QSCV offset/zero cancel precursor. Not a QSCV measurement. |
| correction | `B_flow_correction_easyexpert_zero_cancel` | P1 | `B_atom_calibration_easyexpert_query_zero_cancel_state` -> optional `B_atom_calibration_easyexpert_zero_cancel_off` -> optional `B_atom_calibration_easyexpert_measure_zero_cancel` -> `B_atom_calibration_easyexpert_zero_cancel_on` -> `B_atom_calibration_easyexpert_query_zero_cancel_state` | EasyEXPERT zero-cancel calibration/state bracket. |

Total: 16 accepted flows. P0: 7. P1: 9. P2: 0 for first implementation.

## Rejected / Deferred

| Candidate | Decision |
|---|---|
| Any B flow wrapping `B_atom_output_b1500_enable_channels` | Deferred. Current atom lacks compliance/range/channel role validation. |
| `B_flow_maintenance_b1500_diagnostics_suite` | Deferred until `DIAG?` item catalog is extracted. |
| `B_flow_safe_state_wgfmu_channels` | Rejected as too thin; use `B_atom_output_wgfmu_disconnect` directly or emergency WGFMU flow. |
| `B_flow_safe_state_easyexpert_standby` | Rejected as too thin; use `B_atom_output_easyexpert_set_standby` directly or emergency EasyEXPERT flow. |
| Any B flow that drains errors, reads status, fetches result, or waits OPC via A atoms | Reject from pure B; belongs to AB. |
| Any flow that runs IV/CV/pulse/EasyEXPERT measurement | Reject from B; belongs to future C/ABC. |

## Implementation Requirements

Use the same style as A flows:

- `flow`
- `flow_class`: `B`
- `category`: one of the seven categories
- `target`
- `subject`
- `fake`: true
- `hardware_touched`: false
- `ok`
- `partial`
- `destructive`
- `fixture_sensitive`
- `operator_ack_required`
- `atoms_called`
- `atom_results`
- `inputs`
- `outputs`
- `warnings`
- `purpose`

Failure policy:

- `emergency`: continue to later safety-improving atoms when possible.
- `safe_state`: continue zero/disable/confirm when possible.
- `preflight`: stop/report failure.
- `baseline`: if zero/confirm fails, do not reset/initialize.
- `maintenance`: self-test failure should skip calibration unless explicitly overridden.
- `preparation`: if zero/confirm fails, do not switch routing.
- `correction`: if zero/confirm or fixture acknowledgement fails, do not perform correction.

Operator acknowledgement should be represented in inputs and warnings for destructive or fixture-sensitive flows. Fake flows should enforce gates enough to exercise UI/client paths, but no real hardware is touched.
