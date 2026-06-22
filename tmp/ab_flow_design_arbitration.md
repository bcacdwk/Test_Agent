# AB Flow Design Arbitration

Date: 2026-06-22

Status: accepted parent arbitration after reading:

- `tmp/ab_flow_design_opus46.md`
- `tmp/ab_flow_design_gpt55.md`

This is the source of truth for first-pass `AB_flow_*` implementation. AB flows are fake, user-facing workflow orchestrations that compose A flows, B flows, and occasional narrow A/B atoms. They do not call C atoms and do not execute measurements.

## Scope and Principles

AB_flow is the real operator/client workflow layer:

1. **Observe / discover with A**: capture target identity, context, status, errors, or existing data.
2. **Act / change state with B**: abort, zero, reset, preflight, calibrate, route, correct, standby.
3. **Verify / log with A**: drain errors, capture post status/context, close sessions, preserve audit evidence.

Emergency recovery may start with B action before A observation if delaying action would be unsafe.

## Accepted AB_flow Catalog

| Category | Flow Name | Priority | Ordered Sequence | Purpose |
|---|---|---:|---|---|
| startup | `AB_flow_startup_flex_safe_session` | P0 | `A_flow_discover_flex_session` -> `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `A_flow_snapshot_flex_status` | Standard safe direct FLEX/B1500A session entry before any later work. |
| startup | `AB_flow_startup_wgfmu_baseline_session` | P0 | `A_flow_discover_wgfmu_session` -> `B_flow_baseline_wgfmu_known_state` -> `A_flow_snapshot_wgfmu_diagnostics` | Standard WGFMU open-session baseline and diagnostic verification. |
| startup | `AB_flow_startup_easyexpert_workspace_standby` | P1 | `A_flow_discover_easyexpert_remote` -> `A_flow_select_easyexpert_workspace` -> `B_atom_output_easyexpert_set_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_snapshot_easyexpert_context` | Open EasyEXPERT workspace and explicitly set/verify standby context. |
| shutdown | `AB_flow_shutdown_flex_safe_session` | P0 | optional `A_flow_collect_flex_output_buffer` -> `A_flow_snapshot_flex_status` -> `B_flow_safe_state_b1500_zero_disable` -> `A_flow_drain_flex_errors` -> `A_flow_teardown_flex_session` | Preserve optional existing data, make outputs safe, drain/log errors, close direct session. |
| shutdown | `AB_flow_shutdown_wgfmu_safe_session` | P1 | `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_emergency_wgfmu_abort_disconnect` -> `A_flow_drain_wgfmu_errors` -> `A_flow_teardown_wgfmu_session` | Stop/disconnect WGFMU channels, collect diagnostics, close log/session. |
| shutdown | `AB_flow_shutdown_easyexpert_workspace_standby` | P1 | `A_flow_snapshot_easyexpert_context` -> `B_flow_emergency_easyexpert_abort_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_teardown_easyexpert_workspace` | Abort/standby EasyEXPERT context, drain remote errors, close workspace. |
| recovery | `AB_flow_recovery_flex_emergency_zero` | P0 | optional `A_flow_snapshot_flex_status` -> `B_flow_emergency_b1500_abort_zero` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Emergency direct B1500A recovery to verified zero/logged state. |
| recovery | `AB_flow_recovery_flex_reset_rediscover` | P0 | `A_flow_snapshot_flex_status` -> `B_flow_baseline_b1500_known_state` -> `A_atom_flex_identify` -> `A_atom_flex_list_modules` -> `A_atom_flex_query_settings` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Reset/init direct B1500A after bad state, then rediscover and verify. |
| recovery | `AB_flow_recovery_wgfmu_abort_disconnect` | P1 | optional `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_emergency_wgfmu_abort_disconnect` -> `A_flow_drain_wgfmu_errors` -> `A_flow_snapshot_wgfmu_diagnostics` | WGFMU stuck/failed sequencer recovery; does not close session. |
| recovery | `AB_flow_recovery_easyexpert_abort_standby` | P0 | optional `A_flow_snapshot_easyexpert_context` -> `B_flow_emergency_easyexpert_abort_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_snapshot_easyexpert_context` | EasyEXPERT abort/standby recovery with wait/error/context evidence. |
| maintenance | `AB_flow_maintenance_flex_self_test_calibration` | P1 | `A_flow_snapshot_flex_status` -> `B_flow_maintenance_b1500_self_test_calibration` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | B1500A self-test/calibration with pre/post evidence. |
| maintenance | `AB_flow_maintenance_wgfmu_self_test_calibration` | P1 | `A_flow_discover_wgfmu_session` -> `A_flow_prepare_wgfmu_logging` -> `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_maintenance_wgfmu_self_test_calibration` -> `A_flow_snapshot_wgfmu_diagnostics` | WGFMU self-test/calibration with session/log/diagnostic evidence. |
| preparation | `AB_flow_preparation_flex_nonmeasurement_baseline` | P1 | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_baseline_smu_housekeeping` -> `A_flow_prepare_flex_output_buffer` -> `A_flow_snapshot_flex_status` | Non-measurement baseline for later C work: preflight, SMU housekeeping, parser/buffer setup. |
| preparation | `AB_flow_preparation_asu_low_current_path` | P1 | `A_flow_discover_flex_session` -> `B_flow_preflight_b1500_gate` -> `B_flow_preparation_asu_low_current_path` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Prepare ASU low-current path with discovery, preflight, zero bracket, and post evidence. |
| preparation | `AB_flow_preparation_scuu_signal_path` | P1 | `A_flow_discover_flex_session` -> `B_flow_preflight_b1500_gate` -> `B_flow_preparation_scuu_signal_path` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Prepare SCUU path with discovery, preflight, zero bracket, and post evidence. |
| correction | `AB_flow_correction_cmu_open_short_load` | P1 | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_cmu_open_short_load` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | CMU open/short/load correction with fixture acknowledgement and pre/post evidence. |
| correction | `AB_flow_correction_cmu_phase_compensation` | P1 | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_cmu_phase_compensation` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | MFCMU phase compensation with open-terminal acknowledgement and post diagnostics. |
| correction | `AB_flow_correction_qscv_offset_cancel` | P1 | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_qscv_offset_cancel` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | QSCV offset-cancel precursor; does not run QSCV measurement. |
| correction | `AB_flow_correction_easyexpert_zero_cancel` | P1 | `A_flow_snapshot_easyexpert_context` -> `B_flow_correction_easyexpert_zero_cancel` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_snapshot_easyexpert_context` | EasyEXPERT zero-cancel correction with context/error verification. |

Total: 19 accepted flows. P0: 6. P1: 13. P2: 0 for first implementation.

## Rejected / Deferred

| Candidate | Decision |
|---|---|
| Full-station startup/shutdown across FLEX + WGFMU + EasyEXPERT | Too broad; separate transports and failure modes. Application layer can orchestrate focused AB flows. |
| Any IV/CV/pulse/WGFMU/EasyEXPERT measurement execution | Requires future C/ABC flows. |
| Channel-arm/output-enable readiness flows | Missing compliance/range/channel-role validation atoms and future C context. |
| `AB_flow_configuration_flex_srq_monitoring` | Deferred. Missing `A_atom_flex_query_srq_mask`, so configuration is not reversible. |
| `AB_flow_auto_calibrate_everything` | Too broad and unsafe; use endpoint-specific maintenance/correction flows. |
| EasyEXPERT select-and-run application test | Selection is A; execution is C. |
| WGFMU waveform programming/execution | Future C/ABC. |
| Result classification / device analysis | Future analysis/C/ABC, not AB. |

## Implementation Requirements

AB_flow response envelope should include:

- `flow`
- `flow_class`: `AB`
- `category`
- `scope`
- `outcome`
- `fake`
- `hardware_touched`
- `ok`
- `partial`
- `destructive`
- `consumptive`
- `fixture_sensitive`
- `operator_ack_required`
- `operator_ack_received`
- `phases`: `observe`, `act`, `verify`
- `flows_called`
- `atoms_called`
- `child_results`
- `inputs`
- `outputs`
- `warnings`
- `audit`

Phase rules:

- Normal AB flows: observe -> act -> verify.
- Emergency recovery: best-effort observe -> act -> verify, or act -> verify if observation would delay safety.
- If observe fails in non-emergency destructive workflows, skip act unless an explicit override input is provided.
- If act succeeds but verify fails, preserve act evidence and return `partial=true`.
- If a flow drains errors or reads buffers, preserve consumed data in the returned audit payload.

## Missing Items / Future Improvements

- `A_atom_flex_query_srq_mask`: needed for reversible SRQ configuration flow.
- `B_atom_output_b1500_query_channel_state` / `B_atom_output_b1500_confirm_disabled`: stronger safe shutdown verification.
- `B_atom_routing_asu_query_path` / `B_atom_routing_scuu_query_path`: direct routing verification.
- `B_atom_output_b1500_set_channel_compliance_limits`: safe channel-arm workflows.
- `B_atom_lifecycle_wgfmu_force_zero` or equivalent: stronger WGFMU emergency zero semantics.
- `A_atom_easyexpert_fetch_result_siblings`: broader EasyEXPERT result collection.
