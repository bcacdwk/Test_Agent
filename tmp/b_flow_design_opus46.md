# B Flow Design - Opus46

Date: 2026-06-22
Status: design only. No production code, no formal docs modified.
Source of truth for atom names: `src/b1500_test_agent/mcp/b_atoms.py` (38 B_atom tools).
Reference inputs: `tmp/flow_taxonomy_proposal_opus48.md`, `tmp/flow_taxonomy_proposal_gpt55.md`,
`tmp/b_flow_arbitration.md`, `tmp/b_flow_candidates_opus.md`, `tmp/b_flow_candidates_gpt.md`.

---

## Scope and Principles

**Naming pattern (confirmed):**

```text
B_flow_{intent}_{target}_{subject}
```

**Intent vocabulary (7 closed categories):**
`emergency`, `safe_state`, `preflight`, `baseline`, `maintenance`, `preparation`, `correction`

**Target vocabulary (reuses B_atom targets):**
`b1500`, `smu`, `asu`, `scuu`, `cmu`, `qscv`, `wgfmu`, `easyexpert`

**Hard constraints:**

1. A B_flow composes ONLY `B_atom_*` tools. No A_atom, no C_atom, no connect/disconnect, no identity/module inventory, no status/error drain, no result fetch, no output-buffer read, no measurement execution.
2. Serial execution within a single session. No parallel atom calls. The B1500A one-response buffer, WGFMU library state, and EasyEXPERT single remote connection all preclude concurrent state-changing commands.
3. If a design requires status/error readback, module discovery, or operation-complete wait, it is rejected from B_flow and deferred to AB_flow.
4. Flow names describe the operator intent/goal, not the atom sequence. Adding a step to a flow should not rename it.
5. Target 12-18 flows. Each flow must add value beyond calling atoms individually: enforced ordering, safety brackets, or multi-atom patterns that should always run together.

---

## Proposed B_flow Catalog

| # | Category | Flow Name | Purpose | Ordered Atom Sequence (exact current B_atom names) | Inputs | Outputs | State/Risk Effect | Why This Deserves B_flow | Priority |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `emergency` | `B_flow_emergency_b1500_abort_zero` | Stop active B1500A operation and force all outputs to verified zero. | `B_atom_safety_b1500_abort` → `B_atom_output_b1500_zero_all` → `B_atom_output_b1500_confirm_zero` | `confirm_timeout_s: float = 5.0` | `aborted`, `zeroed_and_disabled`, `within_2v`, per-atom results | Aborts active operation; zeros and disables all outputs. Most aggressive B-class state change. | Core safety primitive. Abort alone leaves unknown output state; zero alone may not stop an active sweep. The three-step bracket is the minimum reliable emergency sequence. | P0 |
| 2 | `emergency` | `B_flow_emergency_wgfmu_abort_initialize` | Stop WGFMU sequencer and reset all channels to initial state. | `B_atom_lifecycle_wgfmu_abort` → `B_atom_lifecycle_wgfmu_initialize` | (none) | `aborted`, `initialized`, per-atom results | Stops WGFMU sequencer (outputs frozen at abort-moment voltage); then resets all WGFMU channels to initial state. | Abort alone leaves channels at their frozen voltage. Initialize resets all channels but cannot stop a running sequencer. Only the bracket is safe. | P0 |
| 3 | `emergency` | `B_flow_emergency_easyexpert_abort_standby` | Abort selected EasyEXPERT measurement and disable standby output hold. | `B_atom_safety_easyexpert_abort_measurement` → `B_atom_output_easyexpert_set_standby(enabled=False)` | `standby_enabled: bool = False` | `aborted`, `standby_state`, per-atom results | Aborts EasyEXPERT measurement; sets standby OFF so channels do not maintain bias between tests. | Abort without standby-off can leave EasyEXPERT maintaining output bias. The pair is the standard EasyEXPERT emergency stop. | P0 |
| 4 | `safe_state` | `B_flow_safe_state_b1500_zero_disable` | Zero selected/all channels, disable them, and confirm zero output. Non-emergency variant that does not abort. | `B_atom_output_b1500_zero_outputs(channels)` → `B_atom_output_b1500_disable_channels(channels)` → `B_atom_output_b1500_confirm_zero` | `channels: str = ""` (empty = all), `confirm_timeout_s: float = 5.0` | `channels`, `zeroed`, `disabled`, `within_2v`, per-atom results | Zeros selected/all outputs (DZ), disables channels (CL), confirms all outputs near zero (WZ?). Does NOT abort. | Distinct from emergency: used before fixture changes, path switching, or session teardown when no active operation needs stopping. Zero-before-disable ordering prevents transients. | P0 |
| 5 | `preflight` | `B_flow_preflight_b1500_gate` | Verify safety readiness (interlock + aggregate checks) before measurement-facing work. | `B_atom_safety_b1500_check_interlock` → `B_atom_safety_b1500_preflight(device_type, pin_map_known)` | `device_type: str = "unknown"`, `pin_map_known: bool = False` | `interlock_state`, `high_voltage_allowed`, `preflight_passed`, `checks[]`, per-atom results | Read-only safety gate. Does not change any output or instrument state. | Interlock check alone misses software-level readiness; preflight alone misses hardware interlock. The combined gate is the standard pre-work safety check. | P0 |
| 6 | `baseline` | `B_flow_baseline_b1500_reset` | Drive B1500A to a known baseline state: zero, confirm, reset, optionally initialize. | `B_atom_output_b1500_zero_all` → `B_atom_output_b1500_confirm_zero` → `B_atom_lifecycle_b1500_reset` → (optional) `B_atom_lifecycle_b1500_initialize` | `include_initialize: bool = True`, `confirm_timeout_s: float = 5.0` | `zeroed_and_disabled`, `within_2v`, `reset_complete`, `initialized` (if requested), per-atom results | Zeros/disables all outputs, then resets (`*RST`) and optionally initializes (`IN`). **Destructive**: destroys all current instrument settings. | Bare `*RST` without prior zero is unsafe (output state during reset is undefined). Bare zero without reset leaves accumulated settings. The bracket is the safe known-state recipe. | P0 |
| 7 | `baseline` | `B_flow_baseline_wgfmu_initialize` | Reset all WGFMU channels and set warning policy for subsequent work. | `B_atom_lifecycle_wgfmu_initialize` → `B_atom_policy_wgfmu_treat_warnings_as_errors(enabled)` | `warnings_as_errors: bool = True` | `initialized`, `warnings_as_errors`, per-atom results | Resets all WGFMU channels; sets warning-as-error policy. Requires an already-open WGFMU session (A-class). | Initialize without explicit warning policy leaves WGFMU in default permissive mode. The pair is the standard WGFMU entry baseline. | P0 |
| 8 | `baseline` | `B_flow_baseline_smu_housekeeping` | Set SMU-level policy defaults: auto-calibration, ADC zero, per-channel filter and series resistor. | (optional) `B_atom_policy_b1500_set_auto_calibration(enabled)` → `B_atom_calibration_smu_set_adc_zero(enabled)` → per-channel `B_atom_output_smu_set_filter(channel, enabled)` → per-channel `B_atom_output_smu_set_series_resistor(channel, enabled)` | `channels: list[int]`, `auto_calibration: bool | None = None` (skip if None), `adc_zero_enabled: bool = False`, `filter_enabled: bool = False`, `series_resistor_enabled: bool = False` | `auto_calibration_set`, `adc_zero_set`, per-channel `filter_states`, per-channel `series_resistor_states`, per-atom results | Sets policy/output-conditioning state. Does not enable/disable channels or change output voltage. | Four independent atom types that should be set consistently before low-current or repeatable measurements. Ad-hoc single-atom calls risk inconsistent SMU policy. | P1 |
| 9 | `maintenance` | `B_flow_maintenance_b1500_self_test_cal` | Run B1500A self-test and optional self-calibration bracket for instrument health verification. | `B_atom_diagnostic_b1500_self_test` → (optional) `B_atom_calibration_b1500_self_calibration` → (optional) `B_atom_diagnostic_b1500_self_test` | `run_calibration: bool = True`, `post_calibration_self_test: bool = True` | `pre_self_test`, `calibration` (if requested), `post_self_test` (if requested), `aggregate_passed`, per-atom results | Runs diagnostic/calibration operations. Self-calibration may modify internal calibration coefficients. **Long-running** (calibration can take minutes). | The test-calibrate-retest pattern catches calibration-induced regressions. Running self-test alone misses calibration drift; running calibration without post-test misses calibration failure. | P1 |
| 10 | `maintenance` | `B_flow_maintenance_wgfmu_self_test_cal` | Run WGFMU self-test and optional self-calibration bracket under explicit warning policy. | (optional) `B_atom_policy_wgfmu_treat_warnings_as_errors(enabled)` → `B_atom_diagnostic_wgfmu_self_test` → (optional) `B_atom_calibration_wgfmu_self_calibration` → (optional) `B_atom_diagnostic_wgfmu_self_test` | `warnings_as_errors: bool | None = None` (skip if None), `run_calibration: bool = True`, `post_calibration_self_test: bool = True` | `warning_policy` (if set), `pre_self_test`, `calibration` (if requested), `post_self_test` (if requested), `aggregate_passed`, per-atom results | Runs WGFMU diagnostic/calibration. Self-calibration can take up to 600 s. | Same test-calibrate-retest rationale as B1500A. Warning policy should be explicit before long maintenance; permissive mode can mask WGFMU issues. | P1 |
| 11 | `preparation` | `B_flow_preparation_asu_low_current` | Safely switch ASU path and configure low-current measurement routing. | `B_atom_output_b1500_zero_outputs(channels)` → `B_atom_output_b1500_disable_channels(channels)` → `B_atom_output_b1500_confirm_zero` → `B_atom_routing_asu_set_path(channel, path)` → (optional) `B_atom_routing_asu_set_1pa_range(channel, enabled)` → (optional) `B_atom_routing_asu_set_indicator(channel, enabled)` → (optional) `B_atom_output_smu_set_filter(channel, enabled)` | `channel: int`, `path: str = "SMU"`, `enable_1pa_range: bool | None = None`, `indicator_enabled: bool | None = None`, `filter_enabled: bool | None = None`, `confirm_timeout_s: float = 5.0` | `within_2v`, `path_set`, `1pa_range` (if set), `indicator` (if set), `filter` (if set), per-atom results | Zeros and disables the channel, then switches ASU path and configures routing. Changes fixture signal path. | ASU path switching without prior zero/disable risks transients through the switch unit. The zero-disable-confirm bracket before path change is the B1500A manual's documented safe practice. | P1 |
| 12 | `preparation` | `B_flow_preparation_scuu_path` | Safely switch SCUU routing path between open/SMU/CMU modes. | `B_atom_output_b1500_zero_outputs(channels)` → `B_atom_output_b1500_disable_channels(channels)` → `B_atom_output_b1500_confirm_zero` → `B_atom_routing_scuu_set_path(channel, path_mode)` → (optional) `B_atom_routing_scuu_set_indicator(channel, enabled)` | `channel: int`, `path_mode: str = "open"`, `indicator_enabled: bool | None = None`, `confirm_timeout_s: float = 5.0` | `within_2v`, `path_mode_set`, `indicator` (if set), per-atom results | Zeros and disables the channel, then switches SCUU path. Changes SMU/CMU signal routing. | Same rationale as ASU: direct `SSP` without zero/disable is unsafe. SCUU specifically requires `SSP` instead of `CN` for path control. | P1 |
| 13 | `correction` | `B_flow_correction_cmu_open_short_load` | Perform one CMU correction type (OPEN/SHOR/LOAD): zero outputs, optionally clear, disable correction, measure data, enable correction. | `B_atom_output_b1500_zero_all` → `B_atom_output_b1500_confirm_zero` → (optional) `B_atom_correction_cmu_clear` → `B_atom_correction_cmu_set_correction(correction_type, enabled=False)` → `B_atom_correction_cmu_measure_data(correction_type, channel)` → `B_atom_correction_cmu_set_correction(correction_type, enabled=True)` | `correction_type: str` (OPEN / SHOR / LOAD), `channel: int`, `clear_existing: bool = False`, `confirm_timeout_s: float = 5.0` | `within_2v`, `cleared` (if requested), `correction_disabled`, `measurement_result_code`, `correction_enabled`, per-atom results | Zeros all outputs; modifies CMU correction state and data. **Fixture-sensitive**: requires physical open/short/load condition. | The disable-measure-enable ordering prevents measurement against stale correction data. Enabling without measuring applies uncalibrated correction. The bracket enforces the correct sequence. | P1 |
| 14 | `correction` | `B_flow_correction_cmu_phase_comp` | Set MFCMU phase compensation mode and perform compensation from a safe output state. | `B_atom_output_b1500_zero_all` → `B_atom_output_b1500_confirm_zero` → `B_atom_correction_cmu_set_phase_mode(channel, mode)` → `B_atom_correction_cmu_perform_phase_comp(channel)` | `channel: int`, `mode: str = "auto"`, `confirm_timeout_s: float = 5.0` | `within_2v`, `mode_set`, `phase_comp_result_code`, per-atom results | Zeros all outputs; performs phase compensation (~30 s). **Fixture-sensitive**: requires open measurement terminals at the device side. | Mode must be set before compensation is performed. Performing compensation without zero state risks invalid results. The bracket enforces safe sequencing. | P1 |
| 15 | `correction` | `B_flow_correction_qscv_offset_cancel` | Perform QSCV zero/offset cancellation from a safe output state. | `B_atom_output_b1500_zero_all` → `B_atom_output_b1500_confirm_zero` → `B_atom_correction_qscv_offset_cancel(channel)` | `channel: int`, `confirm_timeout_s: float = 5.0` | `within_2v`, `offset_cancel_result_code`, per-atom results | Zeros all outputs; performs QSCV offset cancellation. Required before QSCV measurement recipes. | Offset cancellation without prior zero state can produce incorrect correction data. The bracket is thin but enforces the safe prerequisite. | P1 |
| 16 | `correction` | `B_flow_correction_easyexpert_zero_cancel` | Manage EasyEXPERT SMU zero-cancel state: optionally disable, measure, enable, and query final state. | (optional) `B_atom_calibration_easyexpert_zero_cancel_off(channel)` → (optional) `B_atom_calibration_easyexpert_measure_zero_cancel(channel)` → `B_atom_calibration_easyexpert_zero_cancel_on(channel)` → `B_atom_calibration_easyexpert_query_zero_cancel_state(channel)` | `channel: str = "all"`, `force_off_first: bool = True`, `measure_data: bool = True` | `zero_cancel_off` (if requested), `measurement_result` (if requested), `zero_cancel_on`, `final_state`, per-atom results | Changes EasyEXPERT zero-cancel calibration state. Measurement has fixture/timing assumptions. | The off-measure-on-query sequence prevents enabling zero-cancel without fresh measurement data. Query at end confirms the state actually changed. | P1 |

**Summary:** 16 flows total. P0 = 7 flows (#1-#7). P1 = 9 flows (#8-#16).

---

## Category Notes

### emergency

**What belongs:** immediate stop/recover actions for unknown, fault, or runaway states. The system may already be in an unsafe condition. The flow must be aggressive: abort first, then force safe output state, then confirm.

**What does NOT belong:** non-emergency output shutdown (use `safe_state`), normal session teardown (that is AB_flow), any flow that needs A-class error/status readback before acting. Emergency flows act first, verify later (at the AB layer).

**Failure policy:** continue even when individual atoms fail. If abort fails, still attempt zero/initialize. Report `partial=true` but always attempt the full sequence. This is the only category where "try everything" overrides "stop on failure."

**Flows:** `emergency_b1500_abort_zero` (P0), `emergency_wgfmu_abort_initialize` (P0), `emergency_easyexpert_abort_standby` (P0).

### safe_state

**What belongs:** deliberate, non-emergency transitions to a non-sourcing output state. No active operation is running (or the caller knows it is idle). The flow zeros selected/all channels, disables them, and confirms.

**What does NOT belong:** emergency abort (use `emergency`), session reset (use `baseline`), anything that needs module discovery to decide which channels to zero. `safe_state` operates on caller-specified or all channels without querying the instrument.

**Why `safe_state` is separate from `emergency`:** emergency includes abort (stops active operations) and is always all-channels. `safe_state` can target specific channels and does not abort, making it safe to use before fixture changes or path switching without disrupting other channels.

**Flows:** `safe_state_b1500_zero_disable` (P0). WGFMU and EasyEXPERT do not need separate safe_state flows: WGFMU's `baseline_wgfmu_initialize` covers the non-emergency safe state (channel reset without abort), and EasyEXPERT standby-off is a single atom not worth wrapping.

### preflight

**What belongs:** read-only safety gates that verify readiness conditions before measurement-facing work. Must be explicit, user-visible actions — never hidden background checks.

**What does NOT belong:** any flow that changes output state, enables channels, or modifies instrument configuration. Preflight observes and gates; it does not act. A-class status/error snapshots are also excluded (those are A_flow territory); preflight uses only B-class safety atoms.

**Why separate from `baseline`:** preflight is read-only and idempotent; baseline modifies state. They serve different lifecycle stages: preflight gates entry, baseline establishes the starting point.

**Flows:** `preflight_b1500_gate` (P0). WGFMU and EasyEXPERT do not have equivalent B-class preflight atoms; their readiness checks require A-class session/status queries and belong in AB_flow.

### baseline

**What belongs:** establishing a known, default, or clean instrument state. Includes reset/initialize (B1500A), WGFMU channel reset + policy, and SMU-level housekeeping defaults. Baseline flows can be destructive (they overwrite current settings by design).

**What does NOT belong:** emergency actions (use `emergency`), measurement-specific setup (use `preparation` or `correction`), anything that needs prior A-class discovery to decide what to set. Baseline flows take explicit inputs; they do not query the instrument first.

**Key distinction:** `baseline_b1500_reset` destroys all settings and returns to factory defaults. `baseline_smu_housekeeping` sets specific SMU policies without resetting the entire instrument. Choose based on how much state needs to change.

**Flows:** `baseline_b1500_reset` (P0), `baseline_wgfmu_initialize` (P0), `baseline_smu_housekeeping` (P1).

### maintenance

**What belongs:** instrument-health operations: self-test, self-calibration, and diagnostics brackets. Maintenance flows are long-running, should be scheduled and recorded, and produce pass/fail results that the AB layer should capture with pre/post A-class status snapshots.

**What does NOT belong:** fixture-dependent correction/compensation (use `correction`), policy-only settings that do not exercise the instrument (use `baseline`), any flow that needs A-class OPC wait or error drain (AB_flow adds those).

**Pattern:** test → (optional) calibrate → (optional) retest. The retest catches calibration-induced regressions. Warning policy (WGFMU) is set at the start to ensure strict failure reporting during long maintenance operations.

**Flows:** `maintenance_b1500_self_test_cal` (P1), `maintenance_wgfmu_self_test_cal` (P1). A `maintenance_b1500_diagnostics_suite` (loop over `B_atom_diagnostic_b1500_diagnostics` items) is deferred until the diagnostic item catalog is extracted (currently a single under-specified `DIAG?` with an item parameter).

### preparation

**What belongs:** signal-path and module-routing setup that requires a safe-output bracket before switching. Currently covers ASU low-current path configuration and SCUU path switching. The pattern is: zero/disable → confirm → switch path → (optional) configure routing accessories.

**What does NOT belong:** output-buffer/format preparation (A-class), measurement recipe parameters (C-class), fixture-dependent correction (use `correction`), compliance/range setup before channel enable (blocked by missing atoms). Preparation flows change how signals are routed; they do not set up measurement parameters.

**Constraint:** preparation flows assume the caller/AB layer has already verified module installation and channel topology via A-class discovery. Pure B_flow receives validated channel numbers and path modes as inputs.

**Flows:** `preparation_asu_low_current` (P1), `preparation_scuu_path` (P1). Channel-enable preparation is intentionally excluded (see Rejected section).

### correction

**What belongs:** fixture-dependent calibration and compensation workflows that require specific physical conditions (open/short/load fixtures, open terminals, etc.). Always includes a zero-output bracket before correction measurement. Applies to CMU correction, CMU phase compensation, QSCV offset cancellation, and EasyEXPERT zero-cancel.

**What does NOT belong:** instrument-level self-calibration (use `maintenance`), ADC zero / auto-calibration policy (use `baseline`), anything that claims the correction is valid without fixture verification (that is an AB_flow responsibility).

**Fixture acknowledgement:** all correction flows should require explicit operator acknowledgement of fixture condition in real implementation. The fake layer documents the requirement in warnings but does not enforce it.

**Note on EasyEXPERT zero-cancel:** classified as `correction` at the flow level because the workflow pattern (disable → measure → enable → verify) matches fixture-dependent compensation, even though the underlying atoms are categorized as `calibration` in the atom layer. This follows the taxonomy proposal's recommendation.

**Flows:** `correction_cmu_open_short_load` (P1), `correction_cmu_phase_comp` (P1), `correction_qscv_offset_cancel` (P1), `correction_easyexpert_zero_cancel` (P1).

---

## Rejected / Avoided B_flow Combinations

| Candidate | Reason for Rejection |
|---|---|
| `B_flow_*_enable_channels_*` | `B_atom_output_b1500_enable_channels` (CN) lacks compliance/range validation. No `B_atom_set_compliance_limits` exists. Enabling channels without compliance is unsafe. Deferred until missing atoms exist or AB/ABC orchestration can validate the full setup. |
| `B_flow_*_recover_zeroed_*` | `B_atom_output_b1500_recover_zeroed` (RZ) requires a prior DZ and produces error 205 otherwise. Without B-class state tracking of whether DZ was called, wrapping RZ in a flow risks silent errors. Defer to AB_flow where A-class error readback can detect the error. |
| `B_flow_safe_state_wgfmu_disconnect` | Per-channel disconnect loop. Too thin: `B_atom_lifecycle_wgfmu_initialize` already resets all channels. No added ordering or safety value beyond calling the atom. WGFMU non-emergency safe state is covered by `baseline_wgfmu_initialize`. |
| `B_flow_safe_state_easyexpert_standby` | Single-atom wrapper around `B_atom_output_easyexpert_set_standby`. No ordering or bracket value. If abort is not needed, the atom suffices. |
| `B_flow_*_connect_*` / `B_flow_*_disconnect_*` | Connect/disconnect are A_atom operations. Any flow needing session open/close is AB_flow by definition. |
| `B_flow_*_with_error_drain_*` / `B_flow_*_with_status_*` | Error/status reads require A_atom tools. Even `B_flow_emergency_abort_zero_drain_errors` crosses the A boundary. Defer to AB_flow. |
| `B_flow_maintenance_b1500_diagnostics_suite` | A loop over `B_atom_diagnostic_b1500_diagnostics(item)` for multiple items. The diagnostic item catalog (`DIAG?` item map) is under-specified. Defer until item semantics are extracted from hardware documentation. |
| `B_flow_preparation_*_with_preflight` | Adding preflight to every preparation/correction flow creates coupling and duplication. Preflight is a separate gate (flow #5) that the caller/AB_flow should invoke before preparation. Keeps each flow focused and reusable. |
| `B_flow_preparation_b1500_channel_policy` (broad) | A broad flow combining preflight + interlock + filter + ADC zero + enable_channels. Too many concerns; splits into `preflight_b1500_gate` + `baseline_smu_housekeeping` + (deferred) enable. |
| `B_flow_emergency_all_*` / `B_flow_*_full_system_*` | Cross-target flows spanning B1500 + WGFMU + EasyEXPERT. Different transport failure modes; cross-target orchestration is the application layer's job, not a single B_flow. |
| `B_flow_*_select_easyexpert_*` | EasyEXPERT app-test/preset selection may be B-class state control, but currently classified as A_atom. If reclassified later, a pure B selection flow could exist, but it still would not execute measurement (C-class). |
| `B_flow_correction_cmu_full_correction` (all 3 types) | Running OPEN + SHORT + LOAD in one flow requires three different fixture conditions. Each correction type needs separate operator acknowledgement. Composing all three creates a rigid sequence; callers should invoke `correction_cmu_open_short_load` three times with different types and fixture changes between calls. |

---

## Missing B_atoms Needed Later

| Missing Atom | Why Needed | Which B_flow It Blocks |
|---|---|---|
| `B_atom_output_b1500_set_compliance_limits` | Sets voltage/current compliance per channel before enabling outputs. Without it, `enable_channels` is unsafe for automated use. | Blocks a high-confidence `B_flow_preparation_b1500_enable_safe` or similar. |
| `B_atom_output_b1500_query_channel_state` | B-class readback of channel enabled/disabled/zeroed state. Current `confirm_zero` only checks voltage threshold, not channel enable state. | Would strengthen `safe_state_b1500_zero_disable` with disable verification. |
| `B_atom_policy_b1500_query_auto_calibration` | Needed to bracket `set_auto_calibration` and restore the prior policy. Currently no way to read the existing policy without A-class `*LRN?`. | Blocks reversible auto-calibration bracketing in `baseline_smu_housekeeping`. |
| `B_atom_output_smu_query_filter` / `B_atom_output_smu_query_series_resistor` | Needed for reversible SMU settings. Currently fire-and-forget. | Would enable save-restore patterns in `baseline_smu_housekeeping`. |
| `B_atom_routing_asu_query_path` / `B_atom_routing_scuu_query_path` | Verify path switching or restore prior path after preparation. | Would strengthen `preparation_asu_low_current` and `preparation_scuu_path`. |
| `B_atom_correction_cmu_query_correction_state` | Verify correction enable/disable state after correction bracket. | Would add final-state verification to `correction_cmu_open_short_load`. |
| `B_atom_output_b1500_confirm_disabled` | Confirm channels are actually disabled (distinct from voltage being near zero). | Would strengthen `safe_state_b1500_zero_disable` and emergency flows. |

---

## Implementation Notes

### Response Envelope

Adapt the existing `_flow_response` pattern from `common.py` for B_flow. Each B_flow response should include:

```python
{
    "flow": "B_flow_<name>",
    "flow_class": "B",
    "intent": "<emergency|safe_state|preflight|baseline|maintenance|preparation|correction>",
    "target": "<b1500|smu|asu|scuu|cmu|qscv|wgfmu|easyexpert>",
    "subject": "<subject>",
    "fake": True,
    "hardware_touched": False,
    "ok": bool,
    "partial": bool,
    "destructive": bool,
    "atoms_called": ["B_atom_..."],
    "atom_results": [{"atom": "...", "inputs": {...}, "status": "ok|skipped", "result": {...}}],
    "warnings": [str],
    "purpose": str,
    "inputs": {...},
    # flow-specific summary fields
}
```

Key differences from A_flow envelope: `flow_class: "B"`, uses `intent` and `target` instead of `category` and `interface`, no `consumptive` flag (B_flows do not consume read buffers/queues).

### Sequencing

All B_flow atoms execute serially via `_atom_step`. No parallel execution within a flow. This matches A_flow behavior and the B1500A transport constraints.

Optional atoms use `_atom_skip` when their gate condition is not met, preserving audit trail.

Per-channel loops (SMU housekeeping filter/resistor, WGFMU disconnect) iterate serially over the provided channel list.

### Fake Semantics

Same as A_flow: all tools return `fake: true`, `hardware_touched: false`. Flow functions call the fake B_atom Python functions in series and aggregate their data. No real instrument commands are sent.

### Failure Policy

| Category | On atom failure... |
|---|---|
| `emergency` | **Continue**: attempt all remaining atoms. Report `partial=true`. The goal is maximum safety regardless of individual atom errors. |
| `safe_state` | **Continue**: attempt zero → disable → confirm even if zero fails. Same rationale as emergency but less aggressive. |
| `preflight` | **Stop and report**: a failed gate means "not ready." Return `ok=false` with the failing check. |
| `baseline` | **Stop after zero/confirm bracket**: if zero/confirm fails, do not proceed to reset. Reset without confirmed zero is unsafe. |
| `maintenance` | **Stop on critical failure**: if pre-test fails, skip calibration. If calibration fails, still run post-test if requested (to document the failure). |
| `preparation` | **Stop if zero/confirm bracket fails**: do not switch paths unless outputs are confirmed safe. |
| `correction` | **Stop if zero/confirm bracket fails**: do not measure correction data unless outputs are confirmed safe. |

### Destructive / State-Change Classification

| Flow | Destructive | Fixture-sensitive | Long-running |
|---|---|---|---|
| `emergency_b1500_abort_zero` | Yes (aborts, zeros, disables) | No | No |
| `emergency_wgfmu_abort_initialize` | Yes (aborts, resets channels) | No | No |
| `emergency_easyexpert_abort_standby` | Yes (aborts, changes standby) | No | No |
| `safe_state_b1500_zero_disable` | Yes (zeros, disables) | No | No |
| `preflight_b1500_gate` | No (read-only) | No | No |
| `baseline_b1500_reset` | **Yes** (destroys all settings) | No | No |
| `baseline_wgfmu_initialize` | Yes (resets all channels) | No | No |
| `baseline_smu_housekeeping` | Yes (changes SMU policy) | No | No |
| `maintenance_b1500_self_test_cal` | Yes (modifies cal coefficients) | No | **Yes** (minutes) |
| `maintenance_wgfmu_self_test_cal` | Yes (modifies cal coefficients) | No | **Yes** (up to 600 s) |
| `preparation_asu_low_current` | Yes (zeros, changes path) | **Yes** (ASU topology) | No |
| `preparation_scuu_path` | Yes (zeros, changes routing) | **Yes** (SMU/CMU wiring) | No |
| `correction_cmu_open_short_load` | Yes (modifies correction data) | **Yes** (open/short/load fixture) | No |
| `correction_cmu_phase_comp` | Yes (performs compensation) | **Yes** (open terminals) | **Yes** (~30 s) |
| `correction_qscv_offset_cancel` | Yes (applies offset cancel) | **Yes** (fixture state) | No |
| `correction_easyexpert_zero_cancel` | Yes (modifies zero-cancel state) | **Yes** (measurement condition) | No |

### Operator Acknowledgement

For real hardware implementation, the following flows should require explicit operator acknowledgement metadata (`reason`, `operator`, or `fixture_condition_ack`):

- `baseline_b1500_reset` — destroys all instrument settings
- `maintenance_*` — long-running calibration
- `correction_cmu_open_short_load` — requires matching fixture condition per correction type
- `correction_cmu_phase_comp` — requires open measurement terminals
- `correction_qscv_offset_cancel` — fixture requirements TBD

The fake layer documents these requirements in `warnings` but does not enforce them.

### Registration Pattern

B_flow functions should follow the same registration pattern as A_flow in `server.py`:

```python
B_FLOW_FUNCTIONS = [B_flow_emergency_b1500_abort_zero, ...]

def register_b_flows(mcp: FastMCP) -> None:
    for tool in B_FLOW_FUNCTIONS:
        mcp.tool(tool)
```

Add to `server.py`:

```python
from .b_flows import B_FLOW_FUNCTIONS, register_b_flows
register_b_flows(mcp)
```

And update the `capabilities` resource to include `B_flows=_function_names(B_FLOW_FUNCTIONS)`.
