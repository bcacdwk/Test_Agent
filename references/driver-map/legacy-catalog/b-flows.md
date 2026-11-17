# B Flow MCP Tools

B flows are fake, orchestration-only tools that compose current `B_atom_*` tools
into ordered safety/state-control operations. They never call `A_atom_*` or
future `C_atom_*` tools.

```text
B_flow_<category>_<target>_<subject>
```

## B Flow Tools

`B_flow_*` tools are **fake and orchestration-only**. Each flow calls only current
`B_atom_*` Python functions in serial order, preserves each atom payload in
`atom_results`, and returns `fake: true` / `hardware_touched: false`. They do not
connect to instruments, query buffers, drain errors, wait OPC through A atoms, or
execute measurements.

**Response envelope** (every flow): `flow`, `flow_class: "B"`, `category`,
`target`, `subject`, `fake`, `hardware_touched`, `ok`, `partial`, `destructive`,
`fixture_sensitive`, `operator_ack_required`, `atoms_called` (ordered names
actually invoked), `atom_results` (per-atom audit records; skipped atoms are
recorded with `status: "skipped"` but excluded from `atoms_called`), `inputs`,
`outputs`, `warnings`, and `purpose`.

**Warning and acknowledgement semantics:** emergency flows continue toward
safety-improving atoms when possible. Non-emergency baseline, preparation, and
correction flows gate later state-changing steps on zero/confirmation
prerequisites. Fixture-sensitive flows expose `fixture_ack` or
`fixture_condition_ack`; when the acknowledgement is missing, correction/routing
actions are skipped and the response is `partial` with a warning. Destructive or
operator-visible flows expose `operator_ack`; fake mode records and warns when it
is absent so client approval paths can be exercised, but no real hardware is
touched.

| Category | Flow | Ordered Atom Sequence (exact `B_atom_*` names) | Purpose | Risk / State Effect | Priority |
|---|---|---|---|---|---|
| emergency | `B_flow_emergency_b1500_abort_zero` | `B_atom_safety_b1500_abort` -> `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` | Core direct B1500A emergency bracket. | Destructive safety cleanup; continues zero/confirm after abort. | P0 |
| emergency | `B_flow_emergency_wgfmu_abort_disconnect` | `B_atom_lifecycle_wgfmu_abort` -> per-channel `B_atom_output_wgfmu_disconnect` | Stop WGFMU sequencer and disconnect declared WGFMU outputs. | Destructive safety cleanup; channel fan-out is explicit. | P0 |
| emergency | `B_flow_emergency_easyexpert_abort_standby` | `B_atom_safety_easyexpert_abort_measurement` -> `B_atom_output_easyexpert_set_standby` | Abort EasyEXPERT selected measurement and set requested standby state. | Destructive remote safety/standby state change. | P0 |
| safe_state | `B_flow_safe_state_b1500_zero_disable` | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` | Standard non-emergency output cleanup bracket. | Destructive output cleanup; no measurement execution. | P0 |
| preflight | `B_flow_preflight_b1500_gate` | `B_atom_safety_b1500_check_interlock` -> `B_atom_safety_b1500_preflight` | Explicit B-only safety/readiness gate. | Non-destructive gate; failed preflight returns `ok: false`. | P0 |
| baseline | `B_flow_baseline_b1500_known_state` | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_lifecycle_b1500_reset` -> optional `B_atom_lifecycle_b1500_initialize` -> optional `B_atom_policy_b1500_set_auto_calibration` | Known-state reset bracket after zero/confirm. | Destructive reset; warns when `operator_ack` is absent. | P0 |
| baseline | `B_flow_baseline_wgfmu_known_state` | `B_atom_lifecycle_wgfmu_initialize` -> optional `B_atom_policy_wgfmu_treat_warnings_as_errors` | WGFMU initialized baseline and warning policy. | Destructive WGFMU state reset; requires an existing session. | P0 |
| baseline | `B_flow_baseline_smu_housekeeping` | optional `B_atom_policy_b1500_set_auto_calibration` -> optional `B_atom_calibration_smu_set_adc_zero` -> per-channel optional `B_atom_output_smu_set_filter` -> per-channel optional `B_atom_output_smu_set_series_resistor` | Establish repeatable SMU housekeeping policy. | State-policy changes only; does not enable outputs. | P1 |
| maintenance | `B_flow_maintenance_b1500_self_test_calibration` | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_diagnostic_b1500_self_test` -> optional `B_atom_calibration_b1500_self_calibration` -> optional `B_atom_diagnostic_b1500_self_test` | B1500A self-test/calibration bracket. | Operator-visible; calibration is optional and gated after self-test. | P1 |
| maintenance | `B_flow_maintenance_wgfmu_self_test_calibration` | optional `B_atom_policy_wgfmu_treat_warnings_as_errors` -> optional `B_atom_lifecycle_wgfmu_initialize` -> `B_atom_diagnostic_wgfmu_self_test` -> optional `B_atom_calibration_wgfmu_self_calibration` -> optional `B_atom_diagnostic_wgfmu_self_test` | WGFMU maintenance bracket. | Operator-visible; requires an existing WGFMU session. | P1 |
| preparation | `B_flow_preparation_asu_low_current_path` | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_routing_asu_set_path` -> optional `B_atom_routing_asu_set_1pa_range` -> optional `B_atom_routing_asu_set_indicator` -> optional `B_atom_output_smu_set_filter` | Safe bracket for ASU low-current routing. | Fixture/topology-sensitive routing; requires `fixture_ack`. | P1 |
| preparation | `B_flow_preparation_scuu_signal_path` | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_routing_scuu_set_path` -> optional `B_atom_routing_scuu_set_indicator` | Safe bracket for SCUU routing. | Fixture/topology-sensitive routing; requires `fixture_ack`. | P1 |
| correction | `B_flow_correction_cmu_open_short_load` | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> optional `B_atom_correction_cmu_clear` -> per type: disable `B_atom_correction_cmu_set_correction` -> `B_atom_correction_cmu_measure_data` -> enable `B_atom_correction_cmu_set_correction` | CMU open/short/load correction for one or more types. | Fixture-sensitive correction; requires `fixture_condition_ack`. | P1 |
| correction | `B_flow_correction_cmu_phase_compensation` | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_correction_cmu_set_phase_mode` -> `B_atom_correction_cmu_perform_phase_comp` | MFCMU phase compensation bracket. | Fixture/open-terminal-sensitive correction; requires `fixture_condition_ack`. | P1 |
| correction | `B_flow_correction_qscv_offset_cancel` | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_correction_qscv_offset_cancel` | QSCV offset/zero cancel precursor. | Fixture-sensitive correction; does not execute QSCV measurement. | P1 |
| correction | `B_flow_correction_easyexpert_zero_cancel` | `B_atom_calibration_easyexpert_query_zero_cancel_state` -> optional `B_atom_calibration_easyexpert_zero_cancel_off` -> optional `B_atom_calibration_easyexpert_measure_zero_cancel` -> `B_atom_calibration_easyexpert_zero_cancel_on` -> `B_atom_calibration_easyexpert_query_zero_cancel_state` | EasyEXPERT zero-cancel calibration/state bracket. | Operator-visible zero-cancel state change; optional measurement requires fixture acknowledgement. | P1 |
