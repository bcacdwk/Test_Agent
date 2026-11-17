# AB Flow MCP Tools

AB flows are fake, orchestration-only workflow tools that compose existing
`A_flow_*`, `B_flow_*`, and a few narrow `A_atom_*` / `B_atom_*` tools into
operator-facing observe -> act -> verify sequences.

```text
AB_flow_<category>_<scope>_<subject>
```

## Semantics

`AB_flow_*` tools are the user-facing workflow layer. They do not perform real
hardware I/O, do not execute measurements, and return `fake: true` /
`hardware_touched: false`. They preserve child flow/atom payloads in
`child_results`, aggregate `flows_called` and `atoms_called`, and expose a
three-phase `phases` envelope:

- `observe`: A-class discovery, snapshots, context capture, or optional data preservation.
- `act`: B-class safety/state-control work, or a narrow B atom when the catalog calls for it.
- `verify`: A-class post-status, error drains, OPC waits, teardown, or narrow A atoms.

Emergency recovery may start the safety-improving B action before optional
observation. Non-emergency destructive or fixture-sensitive act phases require
the relevant acknowledgement input; when it is missing, the AB flow records a
warning and skips the gated act child while still preserving verification
evidence. Consumptive child flows, such as error drains and output-buffer reads,
make the parent AB response `consumptive: true` and keep the consumed data in
the returned audit payload.

## AB Flow Tools

| Category | Flow | Sequence | Purpose | Key Validation / Side Effects | Priority |
|---|---|---|---|---|---|
| startup | `AB_flow_startup_flex_safe_session` | `A_flow_discover_flex_session` -> `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `A_flow_snapshot_flex_status` | Standard safe direct FLEX/B1500A session entry before later work. | Opens a fake FLEX session; preflight can return `ok: false` until device type and pin map are declared. | P0 |
| startup | `AB_flow_startup_wgfmu_baseline_session` | `A_flow_discover_wgfmu_session` -> `B_flow_baseline_wgfmu_known_state` -> `A_flow_snapshot_wgfmu_diagnostics` | Standard WGFMU open-session baseline and diagnostic verification. | Opens WGFMU session and initializes fake WGFMU state; optional warning policy is explicit. | P0 |
| startup | `AB_flow_startup_easyexpert_workspace_standby` | `A_flow_discover_easyexpert_remote` -> `A_flow_select_easyexpert_workspace` -> `B_atom_output_easyexpert_set_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_snapshot_easyexpert_context` | Open EasyEXPERT workspace and explicitly set/verify standby context. | Changes EasyEXPERT software context, consumes FIFO error entries from child A flows, and waits OPC. | P1 |
| shutdown | `AB_flow_shutdown_flex_safe_session` | optional `A_flow_collect_flex_output_buffer` -> `A_flow_snapshot_flex_status` -> `B_flow_safe_state_b1500_zero_disable` -> `A_flow_drain_flex_errors` -> `A_flow_teardown_flex_session` | Preserve optional existing data, make outputs safe, drain/log errors, close direct session. | Optional output collection is consumptive; safe-state zero/disable is destructive; teardown closes session. | P0 |
| shutdown | `AB_flow_shutdown_wgfmu_safe_session` | `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_emergency_wgfmu_abort_disconnect` -> `A_flow_drain_wgfmu_errors` -> `A_flow_teardown_wgfmu_session` | Stop/disconnect WGFMU channels, collect diagnostics, close log/session. | Emergency abort/disconnect is destructive; WGFMU error drain is consumptive. | P1 |
| shutdown | `AB_flow_shutdown_easyexpert_workspace_standby` | `A_flow_snapshot_easyexpert_context` -> `B_flow_emergency_easyexpert_abort_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_teardown_easyexpert_workspace` | Abort/standby EasyEXPERT context, drain remote errors, close workspace. | Standby/abort is destructive; drain and teardown consume FIFO error entries. | P1 |
| recovery | `AB_flow_recovery_flex_emergency_zero` | optional `A_flow_snapshot_flex_status` -> `B_flow_emergency_b1500_abort_zero` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Emergency direct B1500A recovery to verified zero/logged state. | Emergency act may run before observation; error drain is consumptive. | P0 |
| recovery | `AB_flow_recovery_flex_reset_rediscover` | `A_flow_snapshot_flex_status` -> `B_flow_baseline_b1500_known_state` -> `A_atom_flex_identify` -> `A_atom_flex_list_modules` -> `A_atom_flex_query_settings` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Reset/init direct B1500A after bad state, then rediscover and verify. | Requires `operator_ack=True` for the non-emergency destructive reset act; drain is consumptive. | P0 |
| recovery | `AB_flow_recovery_wgfmu_abort_disconnect` | optional `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_emergency_wgfmu_abort_disconnect` -> `A_flow_drain_wgfmu_errors` -> `A_flow_snapshot_wgfmu_diagnostics` | WGFMU stuck/failed sequencer recovery without closing session. | Emergency act can run before optional snapshot; WGFMU drain is consumptive. | P1 |
| recovery | `AB_flow_recovery_easyexpert_abort_standby` | optional `A_flow_snapshot_easyexpert_context` -> `B_flow_emergency_easyexpert_abort_standby` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_snapshot_easyexpert_context` | EasyEXPERT abort/standby recovery with wait/error/context evidence. | Emergency standby is destructive; EasyEXPERT error drain is consumptive. | P0 |
| maintenance | `AB_flow_maintenance_flex_self_test_calibration` | `A_flow_snapshot_flex_status` -> `B_flow_maintenance_b1500_self_test_calibration` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | B1500A self-test/calibration with pre/post evidence. | Requires `operator_ack=True`; calibration is optional and gated; error drain is consumptive. | P1 |
| maintenance | `AB_flow_maintenance_wgfmu_self_test_calibration` | `A_flow_discover_wgfmu_session` -> `A_flow_prepare_wgfmu_logging` -> `A_flow_snapshot_wgfmu_diagnostics` -> `B_flow_maintenance_wgfmu_self_test_calibration` -> `A_flow_snapshot_wgfmu_diagnostics` | WGFMU self-test/calibration with session/log/diagnostic evidence. | Requires `operator_ack=True` for maintenance act; logging setup changes session state. | P1 |
| preparation | `AB_flow_preparation_flex_nonmeasurement_baseline` | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_baseline_smu_housekeeping` -> `A_flow_prepare_flex_output_buffer` -> `A_flow_snapshot_flex_status` | Non-measurement baseline for later measurement-class work: preflight, SMU housekeeping, parser/buffer setup. | Preflight may fail until device metadata is declared; buffer clear remains gated by `allow_clear_buffer`. | P1 |
| preparation | `AB_flow_preparation_asu_low_current_path` | `A_flow_discover_flex_session` -> `B_flow_preflight_b1500_gate` -> `B_flow_preparation_asu_low_current_path` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Prepare ASU low-current path with discovery, preflight, zero bracket, and post evidence. | Fixture-sensitive routing requires `fixture_ack=True`; drain is consumptive. | P1 |
| preparation | `AB_flow_preparation_scuu_signal_path` | `A_flow_discover_flex_session` -> `B_flow_preflight_b1500_gate` -> `B_flow_preparation_scuu_signal_path` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | Prepare SCUU path with discovery, preflight, zero bracket, and post evidence. | Fixture-sensitive routing requires `fixture_ack=True`; drain is consumptive. | P1 |
| correction | `AB_flow_correction_cmu_open_short_load` | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_cmu_open_short_load` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | CMU open/short/load correction with fixture acknowledgement and pre/post evidence. | Requires `fixture_condition_ack=True`; correction data capture is fixture-sensitive; drain is consumptive. | P1 |
| correction | `AB_flow_correction_cmu_phase_compensation` | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_cmu_phase_compensation` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | MFCMU phase compensation with open-terminal acknowledgement and post diagnostics. | Requires `fixture_condition_ack=True`; phase compensation is fixture-sensitive; drain is consumptive. | P1 |
| correction | `AB_flow_correction_qscv_offset_cancel` | `A_flow_snapshot_flex_status` -> `B_flow_preflight_b1500_gate` -> `B_flow_correction_qscv_offset_cancel` -> `A_flow_drain_flex_errors` -> `A_flow_snapshot_flex_status` | QSCV offset-cancel precursor; does not run QSCV measurement. | Requires `fixture_condition_ack=True`; drain is consumptive. | P1 |
| correction | `AB_flow_correction_easyexpert_zero_cancel` | `A_flow_snapshot_easyexpert_context` -> `B_flow_correction_easyexpert_zero_cancel` -> `A_atom_easyexpert_wait_opc` -> `A_flow_drain_easyexpert_errors` -> `A_flow_snapshot_easyexpert_context` | EasyEXPERT zero-cancel correction with context/error verification. | Requires `operator_ack=True`; if measurement refresh is requested, also requires `fixture_condition_ack=True`; drain is consumptive. | P1 |

Total: 19 accepted AB flows. P0: 6. P1: 13.
