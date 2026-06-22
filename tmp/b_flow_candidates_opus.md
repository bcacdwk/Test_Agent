# B Flow Candidates - Opus

## Scope

`B_flow_*` tools compose **only** existing `B_atom_*` tools. They cover safety, reset, initialization, diagnostics, calibration, channel/output state, path switching, zero/correction, and remote state-control workflows.

Allowed B_flow work:

- Direct B1500A reset / initialize / abort / zero / disable / confirm-zero actions.
- Self-test, self-calibration, diagnostics, and explicit auto-calibration policy.
- Safety gates and preflight checks represented by existing B atoms.
- SMU baseline state such as filter and ADC zero.
- ASU/SCUU path preparation when bracketed by zero/disable steps.
- CMU correction data, CMU phase compensation, and QSCV offset cancellation.
- WGFMU initialize, self-test, self-calibration, and warning-as-error policy.
- EasyEXPERT abort, standby, and SMU zero-cancel calibration state.

Not allowed in pure B_flow:

- No `A_atom_*` calls: no connect/disconnect, no identity, no module inventory, no status-byte read, no error queue read, no operation-complete wait, no output-buffer read, no EasyEXPERT workspace/catalog/result query.
- No `C_atom_*` calls: no force/measure recipes, no sweeps, no pulse waveform execution, no EasyEXPERT measurement run.
- No AB orchestration yet. If a workflow needs connection, status/error verification, operation-complete waits, or result collection, it should be deferred to later `AB_flow_*` design.

Important boundary: a pure `B_flow` can command or change safety/state, but it cannot independently observe the broader instrument/session state unless that observation is already encapsulated in a `B_atom_*` return. Real clients should usually call accepted `A_flow_*` discovery/status flows before and after B flows, but that composition belongs to AB_flow.

## Candidate B_flow Table

| Flow Name | Purpose | Ordered Atom Sequence | Parallelizable Steps | Inputs | Outputs | Why This Should Be B Flow | Risks / Cautions | Priority (P0/P1/P2) |
|---|---|---|---|---|---|---|---|---|
| `B_flow_emergency_stop_b1500_outputs` | Abort the active direct B1500A operation, force all outputs to zero, disable all channels, and confirm zero output. | `B_atom_abort_operation` -> `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` | None. Emergency sequence should be strictly ordered. | `confirm_timeout_s` (float, default 5.0) | `aborted`, `zeroed_and_disabled`, `within_2v`, per-atom results | This is the core B-class safety primitive. It composes the existing abort, zero/disable, and zero-confirm atoms without needing A status reads. | Pure B_flow cannot drain errors or verify final status byte. Real emergency handling should later wrap this in AB_flow with A error/status capture. `AB` may fail or time out on real hardware; zero/disable should still be attempted. | P0 |
| `B_flow_zero_disable_b1500_outputs` | Put selected or all direct B1500A output channels into a non-sourcing state without aborting an active operation. | `B_atom_zero_outputs(channels)` -> `B_atom_disable_channels(channels)` -> `B_atom_confirm_zero_outputs` | None. Zero should precede disable, and confirm should follow both. | `channels` (str, default `""` for all), `confirm_timeout_s` (float, default 5.0) | `channels`, `zeroed`, `disabled`, `within_2v` | This is the standard non-emergency output shutdown bracket. It is reusable before fixture changes, path switching, or session teardown. | `B_atom_confirm_zero_outputs` currently confirms all outputs, not per-channel zero state. If `channels` is partial, response must state that confirmation is global. Pure B_flow cannot prove no unread measurement data remains. | P0 |
| `B_flow_reset_initialize_b1500_state` | Drive the direct B1500A into a known baseline state after outputs have been made safe. | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> `B_atom_reset_instrument` -> `B_atom_initialize_instrument` | None. `*RST` must remain isolated and ordered. | `confirm_timeout_s` (float, default 5.0), `include_initialize` (bool, default true) | `zeroed_and_disabled`, `within_2v`, `reset_complete`, `initialized` | Reset and initialize are B-class state-control actions. The zero/confirm bracket makes this a reusable safe baseline reset flow rather than a bare `*RST`. | Real `*RST` must not be concatenated with other FLEX commands. Pure B_flow cannot reconnect, re-identify modules, or read final settings; AB_flow should do that after reset. | P0 |
| `B_flow_run_b1500_preflight_gate` | Run safety/readiness gating before measurement-facing B or C work. | `B_atom_check_interlock_status` -> `B_atom_run_preflight_checks` | None. Interlock check should be evaluated before aggregate preflight result. | `device_type` (str, default `"unknown"`), `pin_map_known` (bool, default false) | `interlock`, `passed`, `checks[]`, `next_step` | Preflight is explicitly B-class because it gates whether measurement actions may proceed. It is reusable before channel enable, path switching, calibration, or C measurement recipes. | Existing fake `B_atom_run_preflight_checks` includes internal status-style basis text, but the flow still composes only B atoms. Pure B_flow cannot supplement it with accepted A_flow status snapshots. | P0 |
| `B_flow_self_test_calibrate_b1500` | Run a maintenance bracket for direct B1500A self-test and self-calibration. | `B_atom_run_self_test` -> optional `B_atom_run_self_calibration` -> optional `B_atom_run_self_test` | None. Long maintenance operations should be serialized. | `run_calibration` (bool, default true), `post_calibration_self_test` (bool, default true) | `pre_self_test`, `calibration`, `post_self_test`, aggregate `passed` | Self-test/calibration are B-class diagnostics and maintenance controls. The bracket captures the common pattern of testing before and after calibration. | Calibration may take time and should be scheduled/recorded. Pure B_flow cannot wait with `*OPC?` or drain errors; AB_flow should add A status/error capture. | P1 |
| `B_flow_configure_smu_baseline_state` | Set SMU housekeeping state consistently before low-current or repeatable measurements. | optional `B_atom_set_auto_calibration(enabled)` -> `B_atom_set_adc_zero(enabled)` -> for each channel: `B_atom_set_smu_filter(channel, enabled)` | Per-channel `B_atom_set_smu_filter` calls are parallelizable only if the transport layer supports safe command serialization; default to serial. | `channels` (list[int]), `auto_calibration` (bool|null), `adc_zero_enabled` (bool, default false), `filter_enabled` (bool, default false) | `auto_calibration`, `adc_zero_enabled`, `filters[{channel, enabled}]` | SMU baseline state is B-class setup that is separate from measurement recipes. This flow makes filter/ADC-zero policy explicit instead of accidental. | Pure B_flow cannot query previous values for restoration. Auto-calibration policy can affect timing and data comparability; response must record chosen policy. | P1 |
| `B_flow_prepare_asu_smu_path` | Safely prepare an ASU channel path and optional 1 pA range/indicator state. | `B_atom_zero_outputs(channel)` -> `B_atom_disable_channels(channel)` -> `B_atom_confirm_zero_outputs` -> `B_atom_set_asu_path(channel, path)` -> optional `B_atom_set_asu_1pa_range(channel, enabled)` -> optional `B_atom_set_asu_indicator(channel, enabled)` | The optional ASU 1 pA range and indicator calls are parallelizable after path switching if real transport allows; default to serial. | `channel` (int), `path` (str, default `"SMU"`), `enable_1pa_range` (bool|null), `indicator_enabled` (bool|null), `confirm_timeout_s` (float) | `channel`, `path`, `within_2v`, `one_pa_range`, `indicator` | ASU path switching is B-class because it changes fixture/instrument state. The zero/disable/confirm bracket reduces risk before changing path. | Requires correct ASU topology and channel ownership known from prior A_flow discovery. Pure B_flow cannot verify installed modules or channel map; AB_flow should add that validation. | P1 |
| `B_flow_prepare_scuu_path` | Safely prepare a SCUU channel path and indicator state. | `B_atom_zero_outputs(channel)` -> `B_atom_disable_channels(channel)` -> `B_atom_confirm_zero_outputs` -> `B_atom_set_scuu_path(channel, path_mode)` -> optional `B_atom_set_scuu_indicator(channel, enabled)` | None by default; path and indicator should be ordered for operator clarity. | `channel` (int), `path_mode` (str, default `"open"`), `indicator_enabled` (bool|null), `confirm_timeout_s` (float) | `channel`, `path_mode`, `within_2v`, `indicator` | SCUU switching is fixture path state, not measurement. The dedicated flow prevents direct `SSP` use without first zeroing and disabling the associated channel. | Requires external validation that SMU/CMU path is physically appropriate. Pure B_flow cannot verify module inventory or read final status. | P1 |
| `B_flow_prepare_cmu_correction_data` | Clear existing CMU correction data, perform open/short/load correction measurement, and enable that correction type. | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> optional `B_atom_clear_cmu_correction_data` -> `B_atom_set_cmu_correction_state(correction_type, enabled=False)` -> `B_atom_measure_cmu_correction_data(correction_type, channel)` -> `B_atom_set_cmu_correction_state(correction_type, enabled=True)` | None. Fixture-dependent correction operations must be serialized. | `correction_type` (str: `OPEN`/`SHOR`/`LOAD`), `channel` (int), `clear_existing` (bool, default false), `confirm_timeout_s` (float) | `correction_type`, `channel`, `measurement_result_code`, `enabled` | CMU correction is B-class calibration/state control. The flow captures a repeatable correction bracket and avoids enabling stale correction data by accident. | Requires the operator/fixture to be in the matching open/short/load condition. Pure B_flow cannot inspect fixture state or confirm final error queue. | P1 |
| `B_flow_perform_cmu_phase_compensation` | Select MFCMU phase compensation mode and perform compensation. | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> `B_atom_set_cmu_phase_compensation_mode(channel, mode)` -> `B_atom_perform_cmu_phase_compensation(channel)` | None. Compensation can take about 30 s and should be serialized. | `channel` (int), `mode` (str, default `"auto"`), `confirm_timeout_s` (float) | `channel`, `mode`, `result_code`, `within_2v` | Phase compensation is a B-class correction workflow, not a measurement recipe. The zero bracket reflects manual caution around open measurement terminals. | Requires correct open-terminal condition at the device side. Pure B_flow cannot wait via A `*OPC?` or read post-compensation errors. | P1 |
| `B_flow_perform_qscv_offset_cancel` | Prepare outputs safely and perform QSCV zero/offset cancellation. | `B_atom_zero_all_outputs` -> `B_atom_confirm_zero_outputs` -> `B_atom_perform_qscv_offset_cancel(channel)` | None. | `channel` (int), `confirm_timeout_s` (float) | `channel`, `result_code`, `within_2v` | QSCV offset cancellation is a reusable B-class correction step before QSCV recipes. It should be separate from future C measurement flows. | Exact fixture/readiness requirements must be documented before hardware use. Pure B_flow cannot verify final status or retrieve any measurement-like result beyond the atom return. | P2 |
| `B_flow_prepare_wgfmu_safe_baseline` | Initialize WGFMU state and set warning policy before WGFMU work. | `B_atom_wgfmu_initialize` -> `B_atom_wgfmu_treat_warnings_as_errors(enabled)` | None. | `warnings_as_errors` (bool, default true) | `initialized`, `warnings_as_errors` | WGFMU initialize is B-class state control. Warning policy is also B-class because it affects failure semantics of later WGFMU operations. | Pure B_flow cannot open a WGFMU session; accepted A_flow must do that separately. Pure B_flow also cannot read WGFMU error/warning summaries after initialization. | P0 |
| `B_flow_self_test_calibrate_wgfmu` | Run WGFMU/mainframe self-test and optional self-calibration under explicit warning policy. | optional `B_atom_wgfmu_treat_warnings_as_errors(enabled)` -> `B_atom_wgfmu_do_self_test` -> optional `B_atom_wgfmu_do_self_calibration` -> optional `B_atom_wgfmu_do_self_test` | None. Long WGFMU maintenance operations should be serialized. | `warnings_as_errors` (bool|null), `run_calibration` (bool, default true), `post_calibration_self_test` (bool, default true) | `warning_policy`, `pre_self_test`, `calibration`, `post_self_test`, aggregate `passed` | WGFMU self-test/calibration is a high-value maintenance bracket analogous to direct B1500A maintenance but uses the WGFMU library atoms. | Requires an existing WGFMU session from A_flow. Pure B_flow cannot set WGFMU timeout; accepted A_flow must do that before this maintenance bracket. | P1 |
| `B_flow_easyexpert_abort_to_standby` | Abort any selected EasyEXPERT measurement and place EasyEXPERT standby in a requested state. | `B_atom_easyexpert_abort_selected_measurement` -> `B_atom_easyexpert_set_standby(enabled)` | None. Abort should precede standby state change. | `standby_enabled` (bool, default false) | `aborted`, `standby_enabled` | EasyEXPERT abort/standby are B-class remote state controls. This flow gives callers one clear stop/standby primitive without fetching results or reading errors. | Pure B_flow cannot wait for `*OPC?` or read EasyEXPERT system error; AB_flow should verify completion and final remote errors. | P0 |
| `B_flow_easyexpert_measure_zero_cancel` | Perform EasyEXPERT SMU zero-cancel calibration and restore requested zero-cancel state. | optional `B_atom_easyexpert_zero_cancel_off(channel)` -> `B_atom_easyexpert_measure_zero_cancel(channel)` -> `B_atom_easyexpert_zero_cancel_on(channel)` -> `B_atom_easyexpert_query_zero_cancel_state(channel)` | None. Calibration and state restore should be ordered. | `channel` (str, default `"all"`), `force_off_first` (bool, default true), `enable_after_measure` (bool, default true) | `channel`, `measurement_result_code`, `zero_cancel_enabled` | Zero-cancel calibration is a B-class EasyEXPERT workflow. The state-query atom is already B-class, so this remains pure B_flow. | Requires EasyEXPERT remote/workspace context already prepared by A_flow. Pure B_flow cannot confirm operation completion or read system error. | P1 |

## Rejected / Too Broad B_flow Candidates

| Candidate | Why Rejected |
|---|---|
| `B_flow_connect_reset_initialize_b1500` | Requires `A_atom_connect_b1500` and likely A discovery/status reads. This should become an AB startup flow later. |
| `B_flow_safe_disconnect_b1500` | Safe disconnect needs B zero/disable plus `A_atom_disconnect_b1500` and likely A context recording. This is AB_flow, not pure B_flow. |
| `B_flow_reset_with_error_drain` | Reset is B, but error drain/status-byte verification requires accepted A flows. Defer to AB_flow. |
| `B_flow_run_b1500_diagnostics_set` | Pure B in principle, but current `DIAG?` item map is under-specified and the candidate is mostly a loop over one atom. Defer until the diagnostic item catalog is extracted. |
| `B_flow_enable_channels_for_measurement` | Existing `B_atom_enable_channels` can enable channels, but a robust enable-for-measurement flow needs A module/channel validation and C measurement-state/compliance setup. Too broad for pure B_flow as currently atomized. |
| `B_flow_run_measurement_preflight_and_execute` | Any actual measurement execution is C-class. B_flow may run preflight only; it must not run recipes. |
| `B_flow_prepare_output_buffer_and_enable_channels` | Output-buffer preparation uses A atoms (`FMT`, timestamp, `BC`, `NUB?`), while channel enable is B. This is AB or ABC composition. |
| `B_flow_wgfmu_open_initialize_selftest` | WGFMU open/timeout/channel discovery are A atoms; initialize/self-test are B atoms. Defer combined workflow to AB_flow. |
| `B_flow_wgfmu_abort_and_read_diagnostics` | WGFMU diagnostics use A atoms (`read_error`, summaries). Abort/stop support is also not currently represented as a B atom. |
| `B_flow_easyexpert_open_workspace_zero_cancel` | Workspace open/state/error handling is A-class; zero-cancel is B-class. Defer to AB_flow. |
| `B_flow_easyexpert_abort_wait_and_fetch_result` | Abort is B, but wait/result/error reads are A. This is AB_flow, not pure B_flow. |
| `B_flow_cmu_correction_with_error_status` | CMU correction is B, but status/error readback requires A atoms. Pure B_flow can perform correction only. |
| `B_flow_select_easyexpert_application_and_run` | Selecting/running an application test is not supported by current B atoms, and execution is C-class. |

## Missing B_atoms Noted During Planning

| Missing B Atom | Why It Is Genuinely Needed | Candidate Flow Impact |
|---|---|---|
| `B_atom_set_channel_compliance_limits` | A robust channel-enable or output-arm flow should set voltage/current compliance limits before enabling outputs. Current `B_atom_enable_channels` only performs `CN` and cannot express safety limits. | Blocks a high-confidence `B_flow_enable_channels_after_limits`; current plan rejects enable-for-measurement flows. |
| `B_atom_validate_channel_roles_for_output_state` | Pure B_flow has no way to validate that requested channels are appropriate for SMU/CMU/WGFMU/ASU/SCUU roles without A module discovery. A B-level validator could consume a station profile/pin map rather than querying hardware. | Would strengthen ASU/SCUU preparation and any future enable flow without requiring A atoms inside B_flow. |
| `B_atom_confirm_channel_disabled` | Existing `B_atom_confirm_zero_outputs` confirms zero-voltage threshold, but not channel disable state. A B-level disable confirmation would make output shutdown flows more auditable. | Improves `B_flow_zero_disable_b1500_outputs` and `B_flow_emergency_stop_b1500_outputs`. |
| `B_atom_wgfmu_abort_operation` | WGFMU-specific running-sequence abort/stop is not currently represented. `B_atom_wgfmu_initialize` is not a substitute for a controlled abort of an active WGFMU execution. | Blocks a pure `B_flow_emergency_stop_wgfmu` candidate. |
| `B_atom_easyexpert_query_standby_state` | `B_atom_easyexpert_set_standby` can set state, but a pure B_flow cannot verify idempotency or final standby state without a B query atom. | Improves `B_flow_easyexpert_abort_to_standby`. |
| `B_atom_easyexpert_select_application_test` | Phase 1 deferred EasyEXPERT application-test selection. If classified as state control, it belongs in B and would support selecting a test without executing it. | Enables a future pure-B state-selection flow, but still must not run the selected test. |
| `B_atom_easyexpert_select_preset_setup` | Preset setup selection changes EasyEXPERT working setup state without executing measurement. If treated as state control, it should be B. | Enables a future setup-selection B_flow after A catalog discovery. |

## Design Notes

### Naming

- Use `B_flow_<verb>_<domain>_<object>` with no numeric prefixes.
- Domains should be explicit: `b1500`, `wgfmu`, `easyexpert`, `asu`, `scuu`, `cmu`, `qscv`.
- Prefer verbs that expose safety semantics: `emergency_stop`, `zero_disable`, `reset_initialize`, `prepare`, `perform`, `run`, `configure`.
- Avoid names that imply verification by A status/error reads, such as `safe_disconnect`, `verified_reset`, or `healthy_startup`, unless those flows are later designed as AB flows.

### Return Schema

Recommended common response fields:

```python
{
    "flow": "B_flow_<name>",
    "fake": True,
    "hardware_touched": False,
    "atoms_called": ["B_atom_..."],
    "ok": bool,
    "partial": bool,
    "warnings": [str],
    "cautions": [str],
    "results": {
        "B_atom_name": {...}
    }
}
```

For real hardware, `hardware_touched` should become true when the flow sends real B-class commands.

### Idempotency

- Strongly idempotent or near-idempotent: `B_flow_zero_disable_b1500_outputs`, `B_flow_prepare_wgfmu_safe_baseline`, `B_flow_easyexpert_abort_to_standby` when repeated in the same target state.
- State-resetting but intentional: `B_flow_reset_initialize_b1500_state`, `B_flow_prepare_cmu_correction_data`, `B_flow_perform_qscv_offset_cancel`, `B_flow_easyexpert_measure_zero_cancel`.
- Maintenance operations: self-test/calibration flows are repeatable but not cheap; clients should record timing and operator intent.
- Recovery flow caution: do not create a `B_flow_recover_zeroed_outputs` default flow yet. `B_atom_recover_zeroed_outputs` requires a prior `DZ` and can produce error 205 otherwise. It should be exposed only inside a larger AB flow that knows the saved state context.

### Safety Semantics

- Output-affecting B flows should start from zero/disable when practical.
- `B_atom_abort_operation` is emergency/state control, not normal teardown. Normal teardown should use zero/disable and then later AB disconnect.
- `B_atom_enable_channels` should not be wrapped in a high-level flow until compliance/role validation atoms exist or AB/ABC orchestration can validate the full setup.
- Path switching flows must treat A_flow discovery as a prerequisite owned by the caller/AB layer. Pure B_flow receives validated channels and path modes as inputs.
- Correction/calibration flows must describe fixture assumptions in their warnings. The MCP server cannot infer fixture contact state from B atoms alone.
- If any atom in a safety flow fails, the flow response should report `partial=true` and continue only when continuing makes the system safer. Example: if `B_atom_abort_operation` fails, still attempt `B_atom_zero_all_outputs`.

### Client UX

- Present P0 B flows as explicit operator-intent actions, not background conveniences.
- Require confirmation metadata for destructive/state-resetting flows: `reason`, `operator`, or `requested_by` once the real hardware layer exists.
- Do not hide long-running calibration under generic startup commands. Calibration should remain a named B_flow with explicit opt-in.
- Pairing recommendations can be documented later, but not implemented here: A discovery/status before B flow, B state change, then A status/error capture after B flow belongs to AB_flow.
