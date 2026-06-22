# B Flow Design - GPT55

## Scope and Principles

This design defines a concrete pure `B_flow_*` catalog for the current fake MCP surface. It is a design artifact only; it does not modify production code or formal documentation.

Confirmed naming pattern:

```text
B_flow_{intent}_{target}_{subject}
```

Confirmed flow intent categories:

- `emergency`
- `safe_state`
- `preflight`
- `baseline`
- `maintenance`
- `preparation`
- `correction`

Pure B_flow boundary:

- A `B_flow_*` composes only current `B_atom_*` tools from `src/b1500_test_agent/mcp/b_atoms.py`.
- It must not call A/C atoms, open or close sessions, identify instruments, list modules, read generic status/error queues, drain errors, wait OPC, fetch output buffers/results, or execute measurements.
- It may use B-scope readback atoms that already exist, such as `B_atom_output_b1500_confirm_zero`, `B_atom_safety_b1500_check_interlock`, `B_atom_safety_b1500_preflight`, and `B_atom_calibration_easyexpert_query_zero_cancel_state`.
- A B_flow may put hardware or remote state into a safer or more controlled state, but it cannot claim complete verified health without later AB_flow observation and verification.
- Output/routing/correction flows should default to serial atom execution. Even per-channel loops should preserve order until the real driver has an audited batching layer.
- Do not wrap `B_atom_output_b1500_enable_channels` in a high-level flow yet. It lacks compliance, range, role, and station-profile validation atoms.

The catalog intentionally avoids every target/category permutation. It keeps only reusable brackets that either reduce risk, establish known state, or encode fixture-sensitive sequencing.

## Proposed B_flow Catalog

| Category | Flow Name | Purpose | Ordered Atom Sequence (current exact B_atom names) | Inputs | Outputs | State/Risk Effect | Why This Deserves B_flow | Priority |
|---|---|---|---|---|---|---|---|---|
| `emergency` | `B_flow_emergency_b1500_outputs` | Stop an active direct B1500A operation, force all outputs to zero/disabled, and confirm zero. | `B_atom_safety_b1500_abort` -> `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` | `confirm_timeout_s=5.0`, `reason`, `operator_ack` | Abort result, zero-all result, zero confirmation, aggregate `ok`, `partial`, warnings. | Aborts active operation; zeroes and disables all B1500 channels; confirmation is B-scope only. If abort fails, real flow should still attempt zero-all. | Core P0 safety primitive; old drafts agreed this is the main pure-B emergency bracket. | P0 |
| `emergency` | `B_flow_emergency_wgfmu_execution` | Stop a WGFMU sequencer and disconnect declared WGFMU output channels. | `B_atom_lifecycle_wgfmu_abort` -> per `channel_id`: `B_atom_output_wgfmu_disconnect` | `channel_ids=[501,502]`, `reason`, `operator_ack` | Abort result, per-channel disconnect results, disconnected channel list. | Aborts WGFMU execution; disconnects WGFMU/RSU channel outputs. Does not prove voltage zero or final execution status. | `B_atom_lifecycle_wgfmu_abort` leaves channel voltage at the abort moment; pairing it with disconnect is the reusable emergency pattern available with current B atoms. | P1 |
| `emergency` | `B_flow_emergency_easyexpert_measurement` | Abort the selected EasyEXPERT measurement and apply a requested standby policy. | `B_atom_safety_easyexpert_abort_measurement` -> `B_atom_output_easyexpert_set_standby` | `standby_enabled=true`, `reason`, `operator_ack` | Abort result, standby-set result, requested standby state. | Aborts remote measurement; changes EasyEXPERT standby state. Does not wait OPC, read system errors, or fetch results. | Useful remote stop primitive that keeps EasyEXPERT result/status handling out of pure B. | P0 |
| `safe_state` | `B_flow_safe_state_b1500_outputs` | Put selected or all B1500 output channels into zero/disabled non-emergency state. | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` | `channels=""`, `confirm_timeout_s=5.0`, `operator_ack` | Zero result, disable result, zero confirmation, normalized `channels`. | Forces selected/all outputs to zero, disables selected/all channels, confirms global zero threshold. | Standard reusable cleanup bracket before fixture changes, routing, correction, or AB teardown. | P0 |
| `safe_state` | `B_flow_safe_state_wgfmu_channels` | Disconnect declared WGFMU output channels without implying a full WGFMU reset. | per `channel_id`: `B_atom_output_wgfmu_disconnect` | `channel_ids=[501,502]`, `operator_ack` | Per-channel disconnect results, disconnected channel list. | Disables WGFMU/RSU channel outputs. Does not abort a running sequence unless caller uses emergency flow. | Keeps normal channel-output disconnect separate from emergency abort and from broader WGFMU baseline initialization. | P1 |
| `safe_state` | `B_flow_safe_state_easyexpert_standby` | Set EasyEXPERT standby state without aborting or changing workspace context. | `B_atom_output_easyexpert_set_standby` | `standby_enabled=true`, `operator_ack` | Standby-set result and requested standby state. | Changes EasyEXPERT standby state only. No wait/error readback. | Thin but useful non-emergency counterpart to abort-to-standby; avoids using an emergency flow for routine standby policy. | P2 |
| `preflight` | `B_flow_preflight_b1500_gate` | Run the B-only safety gate before risky B or future C operations. | `B_atom_safety_b1500_check_interlock` -> `B_atom_safety_b1500_preflight` | `device_type="unknown"`, `pin_map_known=false` | Interlock result, preflight checks, `passed`, `next_step`. | Reads B-scope safety/preflight state; does not energize outputs or verify session health. | Central reusable gate before output enable, routing, correction, maintenance, or measurement orchestration. | P0 |
| `baseline` | `B_flow_baseline_b1500_known_state` | Reset/initialize direct B1500A from a zero-output state. | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_lifecycle_b1500_reset` -> optional `B_atom_lifecycle_b1500_initialize` -> optional `B_atom_policy_b1500_set_auto_calibration` | `include_initialize=true`, `auto_calibration_enabled=null`, `confirm_timeout_s=5.0`, `operator_ack` | Zero confirmation, reset result, optional initialize result, optional auto-calibration policy result. | Destructive: zeros/disables outputs, resets instrument settings, optionally initializes state and changes auto-calibration policy. | Establishes a known state while keeping the risky `*RST`/`IN` bracket explicit and auditable. | P0 |
| `baseline` | `B_flow_baseline_smu_housekeeping` | Apply repeatable SMU housekeeping settings for externally validated channels. | optional `B_atom_policy_b1500_set_auto_calibration` -> optional `B_atom_calibration_smu_set_adc_zero` -> per channel optional `B_atom_output_smu_set_filter` -> per channel optional `B_atom_output_smu_set_series_resistor` | `channels`, `auto_calibration_enabled=null`, `adc_zero_enabled=null`, `filter_enabled=null`, `series_resistor_enabled=null`, `operator_ack` | Policy/settings results for requested options and channel list. | Changes SMU and B1500 policy state; no output enable or measurement setup. Not reversible without later query/restore atoms. | Consolidates commonly paired SMU housekeeping knobs without creating separate flows for filter, resistor, ADC zero, and auto-cal policy. | P1 |
| `baseline` | `B_flow_baseline_wgfmu_known_state` | Initialize WGFMU state and set the warning failure policy for later WGFMU work. | `B_atom_lifecycle_wgfmu_initialize` -> optional `B_atom_policy_wgfmu_treat_warnings_as_errors` | `warnings_as_errors=true`, `operator_ack` | Initialize result and optional warning-policy result. | Destructive WGFMU state reset; changes warning-as-error behavior. Requires an already-open WGFMU session outside B_flow. | Reusable WGFMU baseline bracket; old drafts treated it as P0 because many WGFMU flows assume initialized state and strict warning handling. | P0 |
| `maintenance` | `B_flow_maintenance_b1500_self_test_calibration` | Run B1500A self-test and optional self-calibration from a zero-output state. | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_diagnostic_b1500_self_test` -> optional `B_atom_calibration_b1500_self_calibration` -> optional `B_atom_diagnostic_b1500_self_test` | `run_calibration=true`, `post_calibration_self_test=true`, `confirm_timeout_s=5.0`, `operator_ack` | Pre self-test result, optional calibration result, optional post self-test result, aggregate `passed`. | Zeroes/disables outputs; self-calibration is scheduled/destructive maintenance state and should be recorded. | Captures the common test-calibrate-test maintenance bracket without A status/error readback. | P1 |
| `maintenance` | `B_flow_maintenance_wgfmu_self_test_calibration` | Run WGFMU self-test and optional self-calibration under explicit warning policy. | optional `B_atom_policy_wgfmu_treat_warnings_as_errors` -> optional `B_atom_lifecycle_wgfmu_initialize` -> `B_atom_diagnostic_wgfmu_self_test` -> optional `B_atom_calibration_wgfmu_self_calibration` -> optional `B_atom_diagnostic_wgfmu_self_test` | `warnings_as_errors=true`, `initialize_first=false`, `run_calibration=true`, `post_calibration_self_test=true`, `operator_ack` | Warning policy result, optional initialize result, self-test/calibration results, aggregate `passed`. | May reset WGFMU state and run long calibration; no A timeout/error-summary handling. | Keeps WGFMU health maintenance separate from session discovery/logging and from baseline initialization. | P1 |
| `preparation` | `B_flow_preparation_asu_low_current_path` | Safely switch an ASU channel path and optional low-current settings. | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_routing_asu_set_path` -> optional `B_atom_routing_asu_set_1pa_range` -> optional `B_atom_routing_asu_set_indicator` -> optional `B_atom_output_smu_set_filter` | `channel`, `channels`, `path="SMU"`, `enable_1pa_range=null`, `indicator_enabled=null`, `filter_enabled=null`, `confirm_timeout_s=5.0`, `fixture_ack`, `operator_ack` | Zero/disable results, ASU path result, optional 1 pA range/indicator/filter results. | Zeros/disables before switching ASU routing; changes fixture path and low-current range state. | High-value reusable path bracket; avoids direct routing changes without first reaching a zero-output state. | P1 |
| `preparation` | `B_flow_preparation_scuu_signal_path` | Safely switch an SCUU channel path and optional indicator state. | `B_atom_output_b1500_zero_outputs` -> `B_atom_output_b1500_disable_channels` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_routing_scuu_set_path` -> optional `B_atom_routing_scuu_set_indicator` | `channel`, `channels`, `path_mode="open"`, `indicator_enabled=null`, `confirm_timeout_s=5.0`, `fixture_ack`, `operator_ack` | Zero/disable results, SCUU path result, optional indicator result. | Zeros/disables before switching SCUU routing; changes SMU/CMU path state. | SCUU path switching is risky enough to deserve one audited bracket, but not separate flows for every `path_mode`. | P1 |
| `correction` | `B_flow_correction_cmu_open_short_load` | Measure and enable one or more CMU open/short/load correction types under fixture acknowledgement. | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> optional `B_atom_correction_cmu_clear` -> per correction type: `B_atom_correction_cmu_set_correction` (disable) -> `B_atom_correction_cmu_measure_data` -> `B_atom_correction_cmu_set_correction` (enable) | `channel`, `correction_types=["OPEN"]`, `clear_existing=false`, `fixture_condition_ack`, `confirm_timeout_s=5.0`, `operator_ack` | Zero confirmation, optional clear result, per-type correction measurement result, per-type enabled state. | Clears/enables CMU correction data; fixture-sensitive and destructive to correction state. | Encodes the open/short/load bracket once instead of separate flows per correction type. | P1 |
| `correction` | `B_flow_correction_cmu_phase_compensation` | Select MFCMU phase mode and perform phase compensation from a zero-output state. | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_correction_cmu_set_phase_mode` -> `B_atom_correction_cmu_perform_phase_comp` | `channel`, `mode="auto"`, `fixture_open_ack`, `confirm_timeout_s=5.0`, `operator_ack` | Zero confirmation, phase mode result, phase compensation result code. | Changes CMU phase-compensation mode and performs fixture-sensitive compensation. | Common correction sequence with manual fixture assumptions and a long-running operation; should not be hand-assembled by clients. | P1 |
| `correction` | `B_flow_correction_qscv_offset_cancel` | Perform QSCV zero/offset cancellation from a zero-output state. | `B_atom_output_b1500_zero_all` -> `B_atom_output_b1500_confirm_zero` -> `B_atom_correction_qscv_offset_cancel` | `channel`, `fixture_ack`, `confirm_timeout_s=5.0`, `operator_ack` | Zero confirmation and QSCV offset-cancel result code. | Changes QSCV correction/offset state. Does not run a QSCV measurement recipe. | Valuable pre-QSCV correction primitive that stays outside future C measurement execution. | P1 |
| `correction` | `B_flow_correction_easyexpert_zero_cancel` | Manage EasyEXPERT SMU zero-cancel state and optional refresh measurement. | `B_atom_calibration_easyexpert_query_zero_cancel_state` -> optional `B_atom_calibration_easyexpert_zero_cancel_off` -> optional `B_atom_calibration_easyexpert_measure_zero_cancel` -> `B_atom_calibration_easyexpert_zero_cancel_on` -> `B_atom_calibration_easyexpert_query_zero_cancel_state` | `channel="all"`, `measure_zero_cancel=false`, `force_off_first=true`, `enable_after=true`, `fixture_ack`, `operator_ack` | Initial state, optional off result, optional zero-cancel measurement result, final query result. | Changes EasyEXPERT zero-cancel calibration/correction state; optional measurement is fixture-sensitive. | Zero-cancel behaves like correction/compensation at the flow layer even though the current atoms live under `calibration`. | P1 |

## Category Notes

### emergency

Belongs here:

- Immediate stop or containment actions for a running or unknown operation.
- Flows where the first goal is to reduce risk before observation is possible.
- B1500A abort/zero, WGFMU abort/disconnect, and EasyEXPERT abort/standby.

Does not belong here:

- Normal teardown, session close, error drain, or result fetch. Those require A or AB.
- Broad reset/calibration actions that could destroy state but are not immediate emergency containment.
- Retrying or looping until verified healthy; pure B cannot verify generic health.

### safe_state

Belongs here:

- Non-emergency transitions to zero, disabled, disconnected, or standby state.
- Output cleanup before fixture movement, path switching, correction, or AB shutdown.

Does not belong here:

- Emergency aborts. Use `emergency` when a running operation may need to be stopped first.
- Channel enable/arm flows. Current `B_atom_output_b1500_enable_channels` has no compliance/range validation.
- Session disconnect or workspace close. Those are A/AB concerns.

### preflight

Belongs here:

- B-only safety gates such as interlock and aggregate readiness checks.
- Checks that intentionally do not energize outputs or change routing/correction state.

Does not belong here:

- Module discovery, station inventory, identity, status-byte, or error-queue verification. Those are A/AB.
- Hidden preflight inside every other B_flow. B_flow callers or AB_flow should decide when to gate.
- Measurement readiness claims. Pure B preflight is necessary but not sufficient for C execution.

### baseline

Belongs here:

- Known-state setup: B1500A reset/initialize, SMU housekeeping, WGFMU initialize/warning policy.
- Explicit state normalization that later workflows can assume.

Does not belong here:

- Fixture-specific path switching or correction data. Those are `preparation` or `correction`.
- Reversible policy bracketing unless query/restore atoms exist.
- Hidden calibration as part of startup; calibration must remain explicit maintenance or correction.

### maintenance

Belongs here:

- Instrument health operations: self-test, diagnostics, self-calibration.
- Slow or scheduled checks that should be logged by clients.

Does not belong here:

- Generic A snapshots or error drains.
- CMU/QSCV/EasyEXPERT correction data; those depend on fixture conditions and belong to `correction`.
- Broad diagnostics suites until the `DIAG?` item catalog is extracted and bounded.

### preparation

Belongs here:

- Non-measurement state preparation for later work: ASU/SCUU routing, low-current range, path indicators, and SMU filter helpers.
- Routing changes that must be bracketed by output zero/disable.

Does not belong here:

- Actual measurement recipe setup or execution.
- Channel enabling for measurement without compliance/range/role validation.
- Every path-mode permutation as a separate flow; use parameterized flows.

### correction

Belongs here:

- Fixture-sensitive correction or compensation: CMU open/short/load, CMU phase compensation, QSCV offset cancel, EasyEXPERT zero-cancel.
- Workflows that change correction/calibration state for later measurement recipes but do not execute those recipes.

Does not belong here:

- Instrument self-calibration that is a maintenance health operation.
- Measurement execution, result collection, or status/error verification.
- Correction flows that require module discovery or workspace/context setup inside B_flow.

## Rejected / Avoided B_flow Combinations

| Candidate / Combination | Decision |
|---|---|
| `B_flow_enable_channels_for_measurement` or any wrapper around `B_atom_output_b1500_enable_channels` | Rejected for now. The atom can issue `CN`, but the flow would need compliance limits, ranges, channel roles, module inventory, and C measurement context. |
| `B_flow_abort_zero_and_drain_errors` | Reject from pure B. Error/status drain is A; this belongs in AB recovery. |
| `B_flow_safe_disconnect_b1500` | Reject from pure B. Safe output state is B, but disconnect is A. |
| `B_flow_reset_rediscover_b1500_state` | Reject from pure B. Rediscovery/status verification requires A atoms. |
| `B_flow_connect_reset_initialize_b1500` | Reject from pure B. Connect/identity/module inventory are A. |
| `B_flow_wgfmu_open_initialize_self_test` | Reject from pure B. WGFMU open session, timeout, channel discovery, and diagnostics summaries are A; only initialize/self-test/calibration are B. |
| `B_flow_wgfmu_abort_and_read_diagnostics` | Reject from pure B. Abort is B; WGFMU status/error/warning summaries are A. |
| `B_flow_easyexpert_abort_wait_fetch_result` | Reject from pure B. Abort is B; wait OPC, system-error read, and result fetch are A. |
| `B_flow_easyexpert_open_workspace_zero_cancel` | Reject from pure B. Workspace open/state is A; zero-cancel is B. |
| `B_flow_cmu_correct_then_measure_cv` | Reject from pure B. CMU correction is B; CV measurement and result collection are future C/A/ABC work. |
| One flow per CMU correction type (`OPEN`, `SHOR`, `LOAD`) | Avoided. Use `B_flow_correction_cmu_open_short_load` with bounded `correction_types`. |
| One ASU/SCUU flow per path mode/channel | Avoided. Use parameterized `B_flow_preparation_asu_low_current_path` and `B_flow_preparation_scuu_signal_path`. |
| `B_flow_run_b1500_diagnostics_suite` | Deferred. Current `B_atom_diagnostic_b1500_diagnostics(item)` lacks an audited item catalog and would mostly be an unbounded loop. |
| Default `B_flow_safe_state_b1500_recover_zeroed` | Deferred. `B_atom_output_b1500_recover_zeroed` requires a prior `DZ`; without saved-state context it can create errors. Prefer AB/stateful orchestration later. |
| Cross-target `B_flow_emergency_full_station` | Rejected. It hides independent failure modes across FLEX/B1500, WGFMU, and EasyEXPERT and invites combinatorial expansion. |

## Missing B_atoms Needed Later

Only blockers for valuable future B_flow work are listed here.

| Missing B Atom | Blocks / Why It Matters |
|---|---|
| `B_atom_policy_b1500_validate_channels_for_state_change` | Would validate requested channels against a station profile/pin map without A hardware inventory. Blocks robust B-only output arm and stronger path-switching gates. |
| `B_atom_output_b1500_set_channel_compliance_limits` | Needed before any safe wrapper around `B_atom_output_b1500_enable_channels`. |
| `B_atom_output_b1500_set_channel_ranges` | Needed with compliance limits before channel-enable or source-arm flows can be safely designed. |
| `B_atom_output_b1500_confirm_channel_disabled` | Would make `safe_state` and emergency flows stronger than voltage-zero confirmation alone. |
| `B_atom_output_b1500_query_channel_output_state` | Needed for B-only output-state verification and idempotent cleanup. |
| `B_atom_policy_b1500_query_auto_calibration` / `B_atom_policy_b1500_restore_auto_calibration` | Needed for reversible auto-calibration policy bracketing. |
| `B_atom_output_smu_query_filter`, `B_atom_output_smu_query_series_resistor`, `B_atom_calibration_smu_query_adc_zero` | Needed for reversible SMU housekeeping rather than one-way baseline setting. |
| `B_atom_routing_asu_query_path`, `B_atom_routing_scuu_query_path` | Needed to verify or restore routing state after ASU/SCUU preparation. |
| `B_atom_routing_asu_validate_fixture_state`, `B_atom_routing_scuu_validate_fixture_state` | Needed before path switching when fixture/contact state must be proven inside pure B. |
| `B_atom_correction_cmu_query_correction`, `B_atom_correction_cmu_query_phase_mode` | Needed for reversible CMU correction/phase-compensation flows. |
| `B_atom_correction_qscv_query_offset_cancel_state` | Needed to verify QSCV offset-cancel state without A/C readback. |
| `B_atom_output_wgfmu_force_zero` / `B_atom_output_wgfmu_confirm_zero` | Needed for a true WGFMU zero-output safe-state flow; current abort/disconnect cannot prove voltage zero. |
| `B_atom_output_easyexpert_query_standby_state` | Needed to verify EasyEXPERT standby idempotently after safe-state or emergency flows. |
| `B_atom_safety_easyexpert_query_selected_measurement_state` | Needed to distinguish idle/running/aborted measurement state before/after EasyEXPERT abort. |

## Implementation Notes

### Return schema

Recommended response envelope for every future `B_flow_*`:

```python
{
    "flow": "B_flow_<intent>_<target>_<subject>",
    "flow_class": "B",
    "category": "<emergency|safe_state|preflight|baseline|maintenance|preparation|correction>",
    "target": "<b1500|smu|asu|scuu|cmu|qscv|wgfmu|easyexpert>",
    "subject": "<short noun>",
    "fake": True,
    "hardware_touched": False,
    "ok": True,
    "partial": False,
    "destructive": False,
    "fixture_sensitive": False,
    "operator_ack_required": False,
    "atoms_called": ["B_atom_..."],
    "atom_results": [
        {"atom": "B_atom_...", "inputs": {}, "status": "ok", "result": {}}
    ],
    "inputs": {},
    "outputs": {},
    "warnings": [],
    "cautions": [],
    "failure_policy": "serial_stop_on_failure"
}
```

Flag guidance:

- `destructive=true` for reset, initialize, policy mutation, routing, correction clearing, zero-cancel measurement, self-calibration, and channel-output state changes.
- `fixture_sensitive=true` for ASU/SCUU path switching, CMU correction, CMU phase compensation, QSCV offset cancel, and EasyEXPERT zero-cancel measurement.
- `operator_ack_required=true` for emergency, reset, calibration, routing, correction, and any state reset that can affect fixtures or DUTs.

### Sequencing

- Default execution is serial and ordered exactly as listed in the catalog.
- Per-channel or per-correction loops must be bounded and recorded with duplicate atom names in `atoms_called`.
- Optional atoms should be recorded as skipped audit records, but skipped atoms must not appear in `atoms_called`.
- Do not run state-changing atoms in parallel over one B1500A, WGFMU, or EasyEXPERT session until a real transport layer explicitly supports audited batching.

### Serial vs parallel

- Emergency flows are strictly serial. Continue from abort to zero/disconnect only when doing so can reduce risk.
- Correction and calibration flows are serial because fixture state can change between steps.
- Path and SMU per-channel setup should also be serial by default; apparent independence at the Python level does not imply safe instrument concurrency.

### Fake semantics

- Current atoms return `fake: true` and `hardware_touched: false`; flows should preserve that.
- Fake B_flow implementations should still exercise gating, skip, partial, warning, and acknowledgement paths so clients can build correct UI and audit behavior before real transport exists.
- Atom `basis` fields should remain per-atom result data; the flow should not synthesize a new command string that hides atom boundaries.

### Operator acknowledgement

- Inputs such as `operator_ack`, `fixture_ack`, `fixture_condition_ack`, `fixture_open_ack`, and `reason` should be part of destructive or fixture-sensitive flow signatures.
- In fake mode, missing acknowledgement may set `ok=false` or `partial=true` without touching atoms, depending on implementation policy.
- Real implementations should log operator identity and reason outside the B_flow core, but the flow response should carry acknowledgement values for audit.

### Failure policy

- Safety-improving cleanup should continue when possible. Example: if `B_atom_safety_b1500_abort` fails, still attempt `B_atom_output_b1500_zero_all` and `B_atom_output_b1500_confirm_zero`.
- For destructive baseline, routing, maintenance, and correction flows, default to stop-on-first-failure after the safe-output bracket.
- Every partial run should return the first failed atom, all successful prior atom results, skipped remaining atoms, and a warning that AB_flow status/error verification is required before continuing.
- B_flow must never hide a failure by automatically performing reset, calibration, or recovery steps not named in the flow.
