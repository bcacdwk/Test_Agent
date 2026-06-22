# AB Flow Design - Opus46

Date: 2026-06-22
Status: design proposal. No production code or formal docs modified.

---

## Scope and Principles

AB_flow is the **real user-facing workflow layer**. It is the first layer where an operator or automated client can accomplish a complete, auditable goal: start a session safely, recover from a fault, shut down without risk, perform maintenance with evidence, or prepare state with verification.

Why AB is necessary and cannot be replaced by calling A/B flows separately:

1. **Observe/Discover with A** — Capture the instrument's current identity, module map, settings, status, and error state before acting. This creates a pre-action audit record and validates that the intended target exists.
2. **Act/Change with B** — Perform the safety-critical, state-changing, or fixture-sensitive operation: abort, zero, reset, calibrate, route, correct.
3. **Verify/Log with A** — Re-read status, drain errors, and confirm the act succeeded. This creates a post-action audit record and proves the instrument reached the expected state.

Without AB, the caller must manually orchestrate A→B→A sequencing, handle partial failures across phases, and maintain audit continuity. AB_flow encodes:

- The **correct phase order** (observe→act→verify; emergency: act→verify)
- **Gate logic** (stop before B if A pre-check fails; stop before disconnect if B zero fails)
- **Failure preservation** (B safety evidence is never erased by a failed A verification)
- **Audit completeness** (pre/post snapshots, drained error annotations, operator acknowledgements)
- **Non-measurement boundary** (AB never executes IV/CV/pulse/EasyEXPERT tests; that is C/ABC)

### AB_flow Naming Convention

```
AB_flow_{workflow}_{scope}_{outcome}
```

- `workflow` ∈ {`startup`, `shutdown`, `recovery`, `maintenance`, `preparation`, `correction`, `configuration`}
- `scope` = the endpoint or target (`flex`, `wgfmu`, `easyexpert`, `asu`, `scuu`, `cmu`, `qscv`)
- `outcome` = short noun describing what is accomplished

### Composition Rules

- AB_flow **may** call: current `A_flow_*`, current `B_flow_*`, and direct `A_atom_*` / `B_atom_*` when a full flow is too broad.
- AB_flow **must NOT** call: future `C_atom_*`, or execute any measurement (IV/CV/pulse/WGFMU waveform/EasyEXPERT test run).
- AB_flow **must NOT** hide dangerous state changes behind discovery or readout names.

---

## Proposed AB_flow Catalog

### Summary: 16 flows across 7 categories

| # | Category | Flow Name | Priority |
|---|---|---|---|
| 1 | startup | `AB_flow_startup_flex_safe_session` | P0 |
| 2 | startup | `AB_flow_startup_wgfmu_baseline` | P0 |
| 3 | startup | `AB_flow_startup_easyexpert_workspace` | P1 |
| 4 | shutdown | `AB_flow_shutdown_flex_safe_session` | P0 |
| 5 | shutdown | `AB_flow_shutdown_wgfmu_session` | P1 |
| 6 | shutdown | `AB_flow_shutdown_easyexpert_workspace` | P1 |
| 7 | recovery | `AB_flow_recovery_flex_emergency` | P0 |
| 8 | recovery | `AB_flow_recovery_flex_reset_rediscover` | P0 |
| 9 | recovery | `AB_flow_recovery_easyexpert_abort` | P0 |
| 10 | maintenance | `AB_flow_maintenance_flex_self_test_cal` | P1 |
| 11 | maintenance | `AB_flow_maintenance_wgfmu_self_test_cal` | P1 |
| 12 | preparation | `AB_flow_preparation_flex_nonmeasurement_baseline` | P1 |
| 13 | preparation | `AB_flow_preparation_asu_low_current_path` | P1 |
| 14 | preparation | `AB_flow_preparation_scuu_signal_path` | P1 |
| 15 | correction | `AB_flow_correction_cmu_open_short_load` | P1 |
| 16 | correction | `AB_flow_correction_cmu_phase_compensation` | P1 |

---

### Full Catalog Table

| Category | Flow Name | Real-World Use Case | Ordered Sequence | Validation Checkpoints | Inputs | Outputs | Failure Handling | Why This Deserves AB_flow | Priority |
|---|---|---|---|---|---|---|---|---|---|
| **startup** | `AB_flow_startup_flex_safe_session` | Operator powers on bench, connects GPIB, wants verified session with preflight gate before any work. | 1. `A_flow_discover_flex_session` 2. `A_flow_snapshot_flex_status` 3. `B_flow_preflight_b1500_gate` 4. `A_flow_snapshot_flex_status` | Identity/modules discovered; no blocking errors; preflight passed; post-snapshot confirms no new hazards. | `gpib_address`, `gpib_board`, `timeout_ms`, `device_type`, `pin_map_known` | `instrument_id`, `modules`, `pre_status`, `preflight_result`, `post_status` | Stop before B if discovery fails. If preflight fails, return `ok=false` with evidence but do not proceed to any state-changing work. Post-snapshot failure → `partial=true`. | A alone cannot gate safety; B alone cannot open the session or prove identity. This is the canonical "cold start" workflow. | P0 |
| **startup** | `AB_flow_startup_wgfmu_baseline` | Operator needs WGFMU ready for pulse/stress work: session open, channels known, state initialized, diagnostics clean. | 1. `A_flow_discover_wgfmu_session` 2. `B_flow_baseline_wgfmu_known_state` 3. `A_flow_snapshot_wgfmu_diagnostics` | Session opened and channel IDs discovered; WGFMU initialized; no errors/warnings in diagnostics. | `address`, `timeout_s`, `set_warning_policy`, `warnings_as_errors` | `channel_ids`, `baseline_result`, `diagnostics` | Stop before B if session open fails. If initialize fails, still attempt diagnostics and return `partial=true`. | A opens session; B initializes state; A verifies. Neither layer alone delivers a ready WGFMU. | P0 |
| **startup** | `AB_flow_startup_easyexpert_workspace` | Operator wants EasyEXPERT workspace open and verified before selecting tests or running calibration. | 1. `A_flow_discover_easyexpert_remote` 2. `A_flow_select_easyexpert_workspace` 3. `B_flow_correction_easyexpert_zero_cancel` (with `measure_zero_cancel=false`, enable-only) 4. `A_flow_snapshot_easyexpert_context` | Remote identity confirmed; workspace opened and state verified; zero-cancel enabled; context snapshot clean. | `workspace`, `channel`, `timeout_s`, `operator_ack` | `remote_identity`, `workspace_state`, `zero_cancel_state`, `context_snapshot` | Stop if remote discovery fails. If workspace open fails, return error without touching zero-cancel. If zero-cancel fails, return `partial=true` with workspace open evidence. | Combines A discovery/workspace selection, B zero-cancel state control, and A context verification into one auditable entry point. | P1 |
| **shutdown** | `AB_flow_shutdown_flex_safe_session` | End-of-day or end-of-batch: safely close the direct B1500A session with output cleanup, final evidence, and transport disconnect. | 1. `A_flow_snapshot_flex_status` 2. `A_flow_collect_flex_output_buffer` (optional, gated by `preserve_buffer`) 3. `B_flow_safe_state_b1500_zero_disable` 4. `A_flow_drain_flex_errors` 5. `A_flow_teardown_flex_session` | Pre-close status recorded; optional stale data preserved; outputs zeroed/disabled/confirmed; errors drained; session closed with final context. | `channels`, `preserve_buffer` (bool), `allow_data_loss` (bool), `confirm_timeout_s` | `pre_status`, `collected_buffer`, `zero_confirmed`, `drained_errors`, `teardown_context` | If buffer collect fails and `allow_data_loss=false`, stop before B. If B zero/confirm fails, do NOT disconnect unless `force_disconnect=true`. Always attempt error drain even if B fails. | A-only teardown cannot claim safe outputs; B-only zero cannot disconnect or preserve context. The combined workflow is the real safe shutdown. | P0 |
| **shutdown** | `AB_flow_shutdown_wgfmu_session` | Close WGFMU session cleanly: bring to baseline state, capture final diagnostics, close log/session. | 1. `A_flow_snapshot_wgfmu_diagnostics` 2. `B_flow_baseline_wgfmu_known_state` 3. `A_flow_drain_wgfmu_errors` 4. `A_flow_teardown_wgfmu_session` | Pre-close diagnostics captured; WGFMU re-initialized to safe baseline; errors drained; session/log closed. | `set_warning_policy`, `warnings_as_errors`, `export_setup`, `close_log` | `pre_diagnostics`, `baseline_result`, `drained_errors`, `teardown_context` | If baseline fails, proceed to close only if `force_close=true`. Always capture final diagnostics regardless of B result. | B alone cannot close the session; A alone cannot initialize WGFMU state. Combined flow ensures nothing is left energized. | P1 |
| **shutdown** | `AB_flow_shutdown_easyexpert_workspace` | Put EasyEXPERT into standby, verify no pending activity, close workspace cleanly. | 1. `B_flow_emergency_easyexpert_abort_standby` (with `standby_enabled=true`) 2. `A_atom_easyexpert_wait_opc` 3. `A_atom_easyexpert_read_system_error` 4. `A_flow_teardown_easyexpert_workspace` | Standby/abort completes; OPC confirms no pending operation; system error captured; workspace closed and verified. | `standby_enabled`, `timeout_s`, `force_close` | `abort_standby_result`, `system_error`, `teardown_context` | If standby/abort fails, do not close unless `force_close=true`. If workspace close fails, return error state for manual intervention. | B stops activity; A waits/verifies/closes. Neither layer alone provides safe verified closure. | P1 |
| **recovery** | `AB_flow_recovery_flex_emergency` | Something went wrong during measurement: abort all activity, force outputs safe, drain errors, log final state. Emergency-first: B acts before A observes. | 1. `B_flow_emergency_b1500_abort_zero` 2. `A_flow_drain_flex_errors` 3. `A_flow_snapshot_flex_status` | Abort issued; outputs zeroed and confirmed; error queue drained with code annotations; final status shows no active operation or lingering hazard. | `confirm_timeout_s`, `max_errors`, `incident_id` | `emergency_result`, `zero_confirmed`, `drained_errors`, `post_status`, `audit_record` | Always attempt B emergency even if pre-state unknown. If B confirm-zero fails, still drain errors and snapshot (mark `partial=true`). Never auto-escalate to reset. | The canonical emergency AB: act first for safety, then observe to understand what happened. This is the floor-level recovery. | P0 |
| **recovery** | `AB_flow_recovery_flex_reset_rediscover` | After a severe fault or unknown state: snapshot current mess, reset instrument, then rediscover and verify clean state. | 1. `A_flow_snapshot_flex_status` (best-effort pre) 2. `B_flow_baseline_b1500_known_state` (includes zero→confirm→reset) 3. `A_atom_flex_identify` 4. `A_atom_flex_list_modules` 5. `A_atom_flex_query_settings` 6. `A_flow_drain_flex_errors` 7. `A_flow_snapshot_flex_status` | Pre-state recorded (even if degraded); zero confirmed before reset; instrument responds to `*IDN?` after reset; modules present; settings at defaults; no errors; clean status. | `initialize` (bool), `set_auto_calibration` (bool), `confirm_timeout_s`, `operator_ack` | `pre_status`, `baseline_result`, `identity`, `modules`, `settings`, `drained_errors`, `post_status` | If pre-snapshot fails, proceed anyway (mark warning). If B reset fails, return failure without attempting rediscovery. If rediscovery shows missing modules, return `partial=true`. | Full `A_flow_discover_flex_session` is too broad post-reset (re-opens session); direct atoms are appropriate for re-identification. B alone cannot prove it recovered; A alone cannot reset. | P0 |
| **recovery** | `AB_flow_recovery_easyexpert_abort` | EasyEXPERT measurement stuck or failed: abort, standby, wait for completion, capture remote error and state. | 1. `A_atom_easyexpert_get_workspace_state` (best-effort pre) 2. `B_flow_emergency_easyexpert_abort_standby` 3. `A_atom_easyexpert_wait_opc` 4. `A_flow_drain_easyexpert_errors` 5. `A_atom_easyexpert_get_workspace_state` | Pre workspace state captured; abort/standby issued; OPC confirms completion; errors drained; final workspace state is known and not "measuring". | `standby_enabled`, `timeout_s`, `force_clear` (for error drain) | `pre_workspace_state`, `abort_result`, `drained_errors`, `post_workspace_state` | If pre-state read fails, still run B abort (emergency priority). If OPC times out, capture partial evidence and warn. Always drain errors. | B aborts the activity; A waits, drains, and verifies. This is the EasyEXPERT emergency complement. | P0 |
| **maintenance** | `AB_flow_maintenance_flex_self_test_cal` | Scheduled maintenance: run B1500A self-test (and optionally self-calibration) with pre/post status evidence for compliance records. | 1. `A_flow_snapshot_flex_status` 2. `B_flow_maintenance_b1500_self_test_calibration` 3. `A_flow_drain_flex_errors` 4. `A_flow_snapshot_flex_status` | Pre-status shows no active operation; self-test passes; optional calibration passes; no new errors after maintenance; post-status matches expectations. | `run_self_calibration`, `repeat_self_test_after_calibration`, `confirm_timeout_s`, `operator_ack` | `pre_status`, `self_test_passed`, `calibration_performed`, `drained_errors`, `post_status` | If pre-status shows active operation, stop unless `allow_maintenance_with_pending=true`. If self-test fails, skip calibration unless `force_calibration=true`. Always drain errors and snapshot post. | Calibration without A context is unauditable. AB provides the before/after evidence that compliance records require. | P1 |
| **maintenance** | `AB_flow_maintenance_wgfmu_self_test_cal` | Scheduled WGFMU maintenance with diagnostic context before and after for traceability. | 1. `A_flow_snapshot_wgfmu_diagnostics` 2. `B_flow_maintenance_wgfmu_self_test_calibration` 3. `A_flow_drain_wgfmu_errors` 4. `A_flow_snapshot_wgfmu_diagnostics` | Pre-diagnostics clean (or acknowledged); self-test passes; optional calibration passes; no new errors; post-diagnostics clean. | `set_warning_policy`, `warnings_as_errors`, `initialize`, `run_self_calibration`, `repeat_self_test_after_calibration`, `operator_ack` | `pre_diagnostics`, `self_test_passed`, `calibration_performed`, `drained_errors`, `post_diagnostics` | If pre-diagnostics show errors and `allow_with_existing_errors=false`, stop. If maintenance fails, still drain errors and capture post diagnostics. | WGFMU maintenance is B; the surrounding A diagnostics create the evidence trail. | P1 |
| **preparation** | `AB_flow_preparation_flex_nonmeasurement_baseline` | Before a batch of measurements: set SMU housekeeping policy, prepare output buffer format, verify clean state. NOT a measurement start. | 1. `A_flow_snapshot_flex_status` 2. `B_flow_preflight_b1500_gate` 3. `B_flow_baseline_smu_housekeeping` 4. `A_flow_prepare_flex_output_buffer` 5. `A_flow_snapshot_flex_status` | Preflight passes; SMU policy applied; buffer format/timestamp set; buffer count at zero (or explicitly cleared); post-status clean. | `device_type`, `pin_map_known`, `set_auto_calibration`, `auto_calibration_enabled`, `set_adc_zero`, `adc_zero_enabled`, `filter_channels`, `format_mode`, `output_mode`, `timestamp_enabled`, `allow_clear_buffer` | `pre_status`, `preflight_result`, `smu_housekeeping`, `buffer_prep`, `post_status` | If preflight fails, do not change SMU state or clear buffer. If buffer has unread data and `allow_clear_buffer=false`, stop before clearing (preserves measurement data). | Spans B safety gate + B policy + A buffer preparation + A verification. No single A or B flow covers this complete pre-measurement baseline. | P1 |
| **preparation** | `AB_flow_preparation_asu_low_current_path` | Prepare ASU for ultra-low-current measurements: validate channel topology, safely switch routing path, verify no errors. | 1. `A_flow_snapshot_flex_status` 2. `B_flow_preflight_b1500_gate` 3. `B_flow_preparation_asu_low_current_path` 4. `A_flow_drain_flex_errors` 5. `A_flow_snapshot_flex_status` | Channel exists in module map; preflight passes; outputs zeroed before path switch; ASU path set; no errors after switch; clean post-status. | `channel`, `path`, `channels`, `confirm_timeout_s`, `fixture_ack`, `set_1pa_range`, `range_1pa_enabled`, `device_type`, `pin_map_known` | `pre_status`, `preflight_result`, `path_result`, `drained_errors`, `post_status` | If preflight fails or `fixture_ack=false`, stop before routing. If path switch fails, keep outputs disabled and drain errors. | ASU routing is topology/fixture-sensitive B work that requires A module-map context and A post-switch verification. | P1 |
| **preparation** | `AB_flow_preparation_scuu_signal_path` | Prepare SCUU for CMU measurements: safely switch SMU/CMU path with validation and verification. | 1. `A_flow_snapshot_flex_status` 2. `B_flow_preflight_b1500_gate` 3. `B_flow_preparation_scuu_signal_path` 4. `A_flow_drain_flex_errors` 5. `A_flow_snapshot_flex_status` | Channel/module context valid; preflight passes; outputs zeroed before route change; SCUU path set; no errors; clean status. | `channel`, `path_mode`, `channels`, `confirm_timeout_s`, `fixture_ack`, `set_indicator`, `device_type`, `pin_map_known` | `pre_status`, `preflight_result`, `path_result`, `drained_errors`, `post_status` | If preflight or fixture_ack fails, stop. If routing fails, stay in disabled state and drain. | Same pattern as ASU: A context → B safety+routing → A verification. | P1 |
| **correction** | `AB_flow_correction_cmu_open_short_load` | CMU calibration: measure open/short/load correction data with fixture acknowledgement, gated by preflight, verified by error drain. | 1. `A_flow_snapshot_flex_status` 2. `B_flow_preflight_b1500_gate` 3. `B_flow_correction_cmu_open_short_load` 4. `A_flow_drain_flex_errors` 5. `A_flow_snapshot_flex_status` | Pre-status clean; preflight passes; fixture condition acknowledged; correction data measured per type; correction enabled; no errors after; clean status. | `channel`, `correction_types`, `clear_existing`, `fixture_condition_ack`, `confirm_timeout_s`, `device_type`, `pin_map_known` | `pre_status`, `preflight_result`, `correction_result`, `drained_errors`, `post_status` | If preflight fails or fixture ack missing, stop. If individual correction type fails, B flow reports partial; still drain and snapshot. | CMU correction is fixture-sensitive B calibration that needs A context proof and A post-error verification. The operator must physically set open/short/load conditions. | P1 |
| **correction** | `AB_flow_correction_cmu_phase_compensation` | MFCMU phase compensation with open-terminal acknowledgement, zero bracket, and verified clean state after. | 1. `A_flow_snapshot_flex_status` 2. `B_flow_preflight_b1500_gate` 3. `B_flow_correction_cmu_phase_compensation` 4. `A_flow_drain_flex_errors` 5. `A_flow_snapshot_flex_status` | Preflight passes; fixture/open-terminal acknowledged; zero bracket holds; phase compensation completes (~30 s); no errors; clean status. | `channel`, `mode`, `fixture_condition_ack`, `confirm_timeout_s`, `device_type`, `pin_map_known` | `pre_status`, `preflight_result`, `phase_comp_result`, `drained_errors`, `post_status` | Stop if fixture ack missing. If compensation fails, drain errors and report. Never proceed to measurement with failed compensation. | Phase compensation is ~30 s of B correction requiring physical open terminals. A evidence before/after is essential for audit. | P1 |

---

## Category Notes

### startup

**What belongs:** First-contact workflows that bring an endpoint from cold/unknown/disconnected to safe, observed, and ready. Always includes session/connection opening OR workspace selection as the entry point, always ends with a verified-clean state.

**What does NOT belong:** Re-entry after a fault (that is `recovery`). Starting a measurement (that is future C/ABC). Changing routing or correction state (that is `preparation`/`correction`).

**Examples:** Opening the GPIB session and running preflight; opening the WGFMU library and initializing baseline; opening an EasyEXPERT workspace.

### shutdown

**What belongs:** Clean termination workflows that transition outputs to safe state, preserve final evidence, and close transport/sessions. Always ends with the session/workspace closed.

**What does NOT belong:** Emergency stops where timing matters more than orderly logging (that is `recovery`). Partial disconnects that leave sessions open.

**Examples:** Zero→disable→confirm→drain→disconnect for FLEX; initialize→drain→close for WGFMU; standby→wait→close for EasyEXPERT.

### recovery

**What belongs:** Fault response workflows where the system may be in an unknown, stuck, or hazardous state. May start with B action before A observation (emergency-first). Includes both immediate emergency recovery and deliberate reset-and-rediscover.

**What does NOT belong:** Normal startup (system was off, not broken). Scheduled maintenance (no fault occurred). Measurement retry (that is C/ABC).

**Examples:** Abort→zero→drain for emergency; reset→rediscover for corrupted state; EasyEXPERT abort→standby→drain.

### maintenance

**What belongs:** Scheduled instrument health checks (self-test, self-calibration) with pre/post evidence. These are operator-visible, potentially long-running, and produce compliance records. Always requires `operator_ack`.

**What does NOT belong:** CMU/QSCV correction (that is `correction` — fixture-dependent, not instrument-health). Quick status checks (that is A-only snapshot). ADC zero/filter changes (that is `preparation` — policy, not health check).

**Examples:** B1500A self-test + optional self-cal with before/after status; WGFMU self-test/cal with diagnostic summaries.

### preparation

**What belongs:** Non-measurement state setup that makes the instrument ready for upcoming measurement recipes. Includes SMU housekeeping policy, output buffer format, routing paths (ASU/SCUU). Always verified by post-snapshot; always gated by preflight.

**What does NOT belong:** The measurement itself (future C). Fixture-dependent correction/compensation (that is `correction`). Pure session opening (that is `startup`). Emergency state changes (that is `recovery`).

**Examples:** SMU baseline + buffer format for IV sweeps; ASU path switch for pA-class measurements; SCUU path switch for CV measurements.

### correction

**What belongs:** Fixture-dependent compensation and calibration workflows where the operator must physically prepare a specific condition (open/short/load standards, open terminals). Always requires `fixture_condition_ack`. Always preceded by zero bracket and preflight.

**What does NOT belong:** Instrument self-calibration (that is `maintenance` — no fixture dependency). EasyEXPERT zero-cancel enable-only without measurement (fold into `startup`). QSCV offset cancel could be here but is deferred (see Rejected).

**Examples:** CMU open/short/load correction data capture; CMU phase compensation with open terminals.

### configuration

**What belongs:** Optional client-observation setup (SRQ polling, status masks) gated by preflight. Low priority because missing `A_atom_query_service_request_mask` prevents reversibility.

**What does NOT belong:** Anything that changes DUT-facing state. This is strictly for how the client observes the instrument, not what the instrument does.

**Currently deferred:** `AB_flow_configuration_flex_srq_polling` — blocked by missing mask query atom. P2 when available.

---

## Rejected / Avoided AB_flow Combinations

| Rejected Candidate | Reason |
|---|---|
| `AB_flow_startup_full_station` (all transports at once) | FLEX, WGFMU, and EasyEXPERT have independent transports and failure modes. Cross-transport orchestration belongs to the application layer calling multiple focused AB flows. |
| `AB_flow_recovery_wgfmu_emergency_stop` | No `B_atom_lifecycle_wgfmu_abort` alone is insufficient for true emergency (channels keep voltage at abort). Need a dedicated `B_flow_emergency_wgfmu_abort_disconnect` + A drain. **However**, current `B_flow_emergency_wgfmu_abort_disconnect` already exists. Promoting to AB when WGFMU error drain after abort becomes a real need. Deferred P2. |
| `AB_flow_correction_qscv_offset_cancel` | Current B_flow exists, but the AB wrapper (preflight + drain + snapshot) adds only 4 atoms of boilerplate. Include if QSCV workflows become common. Deferred P2. |
| `AB_flow_correction_easyexpert_zero_cancel_refresh` | Measuring zero-cancel data is fixture-sensitive and belongs in correction, but the enable-only state toggle is simple enough to fold into `startup_easyexpert_workspace`. A standalone AB correction flow is P2 until EasyEXPERT measurement workflows (C) create demand. |
| `AB_flow_preparation_flex_srq_polling` | Missing `A_atom_query_service_request_mask` prevents reversible mask management. Cannot safely offer this without restore capability. Deferred until atom exists. |
| `AB_flow_run_iv_sweep_safely` | Requires C atoms (force/sweep/execute). AB does not execute measurements. |
| `AB_flow_enable_channels_for_measurement` | Missing compliance/range validation B atoms. Cannot safely enable outputs for measurement without knowing limits. Deferred to C/ABC design. |
| `AB_flow_auto_calibrate_everything` | Different targets (B1500A, WGFMU, CMU, EasyEXPERT) have different fixture assumptions and timing. A monolithic flow is unauditable and unsafe. |
| `AB_flow_easyexpert_select_and_run_test` | Selecting is A-class context; running is C-class measurement execution. AB boundary is clear. |
| `AB_flow_collect_results_then_shutdown` | Too broad: mixes data collection semantics with safety shutdown across potentially multiple transports. Keep as separate sequential calls at the application layer. |
| `AB_flow_recover_zeroed_and_continue` | `RZ` (recover zeroed) requires prior `DZ` context AND a measurement continuation plan. The continuation is C-class. AB can only offer the recovery-to-known-state, not resume. |

---

## Missing Atoms/Flows Needed Later

| Missing Item | Blocks | Impact |
|---|---|---|
| `A_atom_flex_query_srq_mask` | `AB_flow_configuration_flex_srq_polling` | Cannot make SRQ configuration reversible without querying the prior mask. |
| `B_atom_output_b1500_query_channel_state` | Stronger zero/disable verification | Currently we confirm zero voltage (`WZ?`), but cannot programmatically confirm the CL (disable) completed per-channel. |
| `B_atom_routing_asu_query_path` / `B_atom_routing_scuu_query_path` | Direct path-state verification in preparation flows | Currently AB path flows verify by absence of errors, not positive path readback. |
| `B_atom_safety_b1500_set_compliance` | Future channel-arm / measurement-readiness AB flows | Cannot safely enable channels for measurement without compliance limits set. |
| `B_atom_lifecycle_wgfmu_abort` + per-channel zero | True WGFMU emergency AB recovery | `WGFMU_abort` leaves channels at last voltage; need explicit zero or the AB recovery is incomplete. |
| `A_atom_easyexpert_query_measurement_state` | Stronger EasyEXPERT abort verification | Currently relies on workspace state + OPC; direct measurement-state query would be more reliable. |
| `B_atom_diagnostic_b1500_diagnostics` item catalog | Future `AB_flow_maintenance_flex_diagnostics` | DIAG item numbers are not yet mapped; cannot offer a targeted diagnostics AB flow. |

---

## Implementation Notes

### Return Schema

Every `AB_flow_*` returns:

```python
{
    "flow": "AB_flow_{workflow}_{scope}_{outcome}",
    "flow_class": "AB",
    "workflow": str,        # startup|shutdown|recovery|maintenance|preparation|correction|configuration
    "scope": str,           # flex|wgfmu|easyexpert|asu|scuu|cmu|qscv
    "outcome": str,         # short noun
    "fake": True,
    "hardware_touched": False,
    "ok": bool,             # all phases succeeded
    "partial": bool,        # some phases succeeded, others skipped/failed
    "phases": {
        "observe": { ... },  # pre-action A results
        "act": { ... },      # B action results
        "verify": { ... },   # post-action A results
    },
    "atoms_called": [...],   # ordered list of all atom/flow names actually invoked
    "atom_results": [...],   # per-atom/flow audit records
    "inputs": { ... },
    "outputs": { ... },
    "warnings": [...],
    "operator_ack_required": bool,
    "operator_ack_received": bool,
    "fixture_sensitive": bool,
    "audit_record": {
        "pre_status_hash": str | None,
        "post_status_hash": str | None,
        "errors_drained": int,
        "timestamp_start": str,
        "timestamp_end": str,
        "incident_id": str | None,
    },
}
```

### Observe / Act / Verify Phases

Every AB_flow MUST structure its execution into these phases:

1. **Observe** (A): Capture pre-state. May be best-effort in emergency flows. Records what the instrument looks like before any action. MUST be preserved even if Act fails.

2. **Act** (B): Perform the state-changing operation. Gates: if Observe reveals a blocking condition (active operation, failed preflight, missing fixture ack), Act is skipped and the flow returns `ok=false` with the Observe evidence explaining why.

3. **Verify** (A): Capture post-state. MUST be attempted even if Act partially failed. The Act evidence is NEVER erased by a failed Verify. Verify includes error drain (consumptive) and status snapshot (non-destructive).

**Exception for emergency recovery:** The order becomes Act→Verify (skip Observe, or best-effort Observe that does not delay Act).

### Audit Log Semantics

- Pre-action and post-action snapshots are both preserved in the audit record
- Drained error entries are annotated with EMG? lookups and included in the audit
- Operator acknowledgements (`operator_ack`, `fixture_condition_ack`) are recorded with timestamp
- Consumed queue entries (FIFO drains) are preserved in the response since they are destroyed on the instrument
- `incident_id` is a caller-supplied correlation tag for emergency/recovery flows

### Failure Policy

| Situation | Default Policy |
|---|---|
| A Observe fails | Stop before B Act (except emergency flows) |
| B Act fails partially (e.g., zero confirmed but reset failed) | Still run A Verify; return `partial=true` |
| B Act fails completely (e.g., zero not confirmed) | Still run A Verify where safe; return `ok=false` |
| A Verify fails | Preserve B Act results; return `partial=true` |
| Emergency: transport broken | Attempt B anyway; if both fail, return all available evidence |
| Fixture ack missing | Stop before fixture-sensitive B steps; return `ok=false` |
| Preflight fails | Stop before destructive B steps; return preflight evidence |
| Buffer has unread data | Stop before clearing unless `allow_clear_buffer=true` |
| B zero/confirm fails before disconnect | Do NOT disconnect unless `force_disconnect=true` |

### Operator Acknowledgement

Flows requiring `operator_ack`:
- All maintenance flows (scheduled, potentially long, changes instrument state)
- All correction flows (fixture-dependent, requires physical setup)
- `recovery_flex_reset_rediscover` (destroys settings)
- `startup_easyexpert_workspace` (when `measure_zero_cancel=true`)

The fake implementation records `operator_ack_required=true` and `operator_ack_received=<input>` so that client gating paths are exercised even in fake mode.

### Fake Semantics

All AB_flows in fake mode:
- Call fake A_flow/B_flow/atom functions in series
- Aggregate their returned payloads into the phased structure
- Return `fake: true`, `hardware_touched: false`
- Exercise all gating logic (preflight, fixture_ack, zero confirmation) using fake return values
- Record skip/partial/failure paths accurately so client error-handling code is testable
- Do NOT short-circuit: even fake emergency flows run the full abort→zero→confirm→drain→snapshot sequence

---

## Priority Summary

**P0 (6 flows)** — Must exist for any real usage:
1. `AB_flow_startup_flex_safe_session`
2. `AB_flow_startup_wgfmu_baseline`
3. `AB_flow_shutdown_flex_safe_session`
4. `AB_flow_recovery_flex_emergency`
5. `AB_flow_recovery_flex_reset_rediscover`
6. `AB_flow_recovery_easyexpert_abort`

**P1 (10 flows)** — Important for real workflows:
7. `AB_flow_startup_easyexpert_workspace`
8. `AB_flow_shutdown_wgfmu_session`
9. `AB_flow_shutdown_easyexpert_workspace`
10. `AB_flow_maintenance_flex_self_test_cal`
11. `AB_flow_maintenance_wgfmu_self_test_cal`
12. `AB_flow_preparation_flex_nonmeasurement_baseline`
13. `AB_flow_preparation_asu_low_current_path`
14. `AB_flow_preparation_scuu_signal_path`
15. `AB_flow_correction_cmu_open_short_load`
16. `AB_flow_correction_cmu_phase_compensation`

**Deferred P2:**
- `AB_flow_correction_qscv_offset_cancel`
- `AB_flow_correction_easyexpert_zero_cancel_refresh`
- `AB_flow_configuration_flex_srq_polling`
- `AB_flow_recovery_wgfmu_emergency` (pending stronger abort+zero atoms)
