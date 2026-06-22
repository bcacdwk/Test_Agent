# A Flow Design - GPT55

## Scope and Principles

This document proposes a concrete pure `A_flow_*` catalog using the confirmed pattern:

```text
A_flow_{operation}_{interface}_{subject}
```

Allowed `operation` values are `discover`, `snapshot`, `drain`, `collect`, `prepare`, `select`, and `teardown`. Allowed `interface` values are `flex`, `wgfmu`, and `easyexpert`.

An `A_flow_*` may compose only current `A_atom_*` tools from `src/b1500_test_agent/mcp/server.py`. It must not call `B_atom_*` or future `C_atom_*` tools. It must not reset, initialize, calibrate, run diagnostics or self-test, abort, enable or disable channels, zero outputs, change DUT-facing output state, or execute a measurement.

The catalog intentionally avoids a complete cross product of operation x interface x subject. A flow is proposed only when it captures a repeated multi-atom pattern, a risky ordering rule, a consumptive read convention, or a stateful A-class software/session context that callers should not hand-roll repeatedly.

## Proposed A_flow Catalog

| Category | Flow Name | Purpose | Ordered Atom Sequence (current exact atom names) | Inputs | Outputs | Destructive/Consumptive? | Why This Deserves A_flow | Priority |
|---|---|---|---|---|---|---|---|---|
| discover | `A_flow_discover_flex_session` | Open or validate the direct FLEX/VISA path and capture minimum B1500A identity, module, status, error, and settings context. | `A_atom_flex_connect` -> `A_atom_flex_identify` -> `A_atom_flex_list_modules` -> `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` -> `A_atom_flex_query_settings` | `gpib_address`, `gpib_board`, `timeout_ms`, `include_settings=true` | Connection result, instrument identity, modules, status byte, non-clearing error snapshot, settings. | Opens or validates a direct session; reads error state but should not clear it. | This is the standard direct-interface entry bundle and establishes the context needed before any later FLEX work. | P0 |
| discover | `A_flow_discover_wgfmu_session` | Open a WGFMU library session, configure timeout, discover channel IDs, and capture initial status and summaries. | `A_atom_wgfmu_open_session` -> `A_atom_wgfmu_set_timeout` -> `A_atom_wgfmu_get_channel_ids` -> `A_atom_wgfmu_get_status` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | `address`, `timeout_s=100.0` | Session result, channel IDs, overall WGFMU status, error summary, warning summary. | Opens a WGFMU library session; changes timeout session state. | WGFMU has a separate session model from FLEX, and channel IDs are required for later WGFMU status/progress reads. | P0 |
| discover | `A_flow_discover_easyexpert_remote` | Identify the EasyEXPERT remote endpoint and discover workspace availability without selecting or running a test. | `A_atom_easyexpert_identify` -> `A_atom_easyexpert_read_system_error` -> `A_atom_easyexpert_list_workspaces` -> `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` | `include_workspace_name=true` | Host identity, first remote error entry, workspace catalog, current workspace state/name. | `A_atom_easyexpert_read_system_error` consumes one FIFO error entry in real semantics. | EasyEXPERT remote prerequisites differ from FLEX and WGFMU; this is the minimum remote-context discovery bundle. | P0 |
| discover | `A_flow_discover_easyexpert_catalogs` | Enumerate application tests and preset setup catalogs in the current EasyEXPERT workspace context. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_app_tests` -> `A_atom_easyexpert_list_preset_groups` -> repeat `A_atom_easyexpert_list_preset_setups` for requested groups -> `A_atom_easyexpert_read_system_error` | `preset_groups="all"`, `include_app_tests=true`, `max_groups` | Workspace state, application-test catalog, preset groups, preset setups by group, error entry. | Reads one EasyEXPERT error FIFO entry; may be large but does not select or execute anything. | Catalog fan-out is awkward and common enough to standardize, but remains separate from selection to avoid hidden software-context changes. | P1 |
| snapshot | `A_flow_snapshot_flex_status` | Capture a non-destructive direct B1500A health/status snapshot for logs, UI health panels, and debugging. | `A_atom_flex_get_status` -> `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` -> `A_atom_flex_query_settings` -> `A_atom_flex_query_buffer_count` -> optional `A_atom_flex_read_timestamp` | `clear_errors=false`, `include_timestamp=false` | Composite status, status byte, error snapshot, settings, output-buffer count, optional timestamp. | Non-destructive when `clear_errors=false`; should not drain the error queue. | This standardizes the common "what is the instrument state?" bundle while preserving raw per-atom evidence. | P0 |
| snapshot | `A_flow_snapshot_wgfmu_status` | Capture WGFMU overall and per-channel status with diagnostic summaries. | `A_atom_wgfmu_get_status` -> `A_atom_wgfmu_get_channel_ids` -> repeat `A_atom_wgfmu_get_channel_status` for selected channels -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | `channel_ids="discovered"`, `include_summaries=true` | Overall status, channel IDs, per-channel status, error summary, warning summary. | Non-destructive; summary read semantics should be treated as diagnostic readback. | Overall and channel status belong together for WGFMU monitoring, especially before or after external waveform workflows. | P0 |
| snapshot | `A_flow_snapshot_easyexpert_context` | Capture current EasyEXPERT workspace, selected setup/test, and bench metadata without changing selection. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` -> `A_atom_easyexpert_get_selected_name` -> `A_atom_easyexpert_get_device_tag` -> `A_atom_easyexpert_get_repeat_count` | `include_bench_metadata=true` | Workspace state/name, selected setup or app test name, device tag, repeat count. | Non-destructive; intentionally omits `A_atom_easyexpert_read_system_error` to avoid consuming the FIFO. | EasyEXPERT software context is easy to lose track of; this provides the read-only companion to select/prepare flows. | P1 |
| drain | `A_flow_drain_flex_errors` | Drain direct B1500A errors and annotate known codes. | `A_atom_flex_read_error_queue` with `clear_after_read=true` -> repeat `A_atom_flex_lookup_error` for returned codes -> `A_atom_flex_read_status_byte` | `max_errors`, `lookup_messages=true` | Drained errors, resolved messages, unresolved-code notes, final status byte. | Consumes or clears error state. | Error drain semantics are materially different from a snapshot; callers need one consistent audit shape. | P0 |
| drain | `A_flow_drain_wgfmu_errors` | Consume the next WGFMU error entry and capture surrounding summaries/status. | `A_atom_wgfmu_read_error` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` -> `A_atom_wgfmu_get_status` | `include_summaries=true` | Next error entry, accumulated error summary, warning summary, overall status. | `A_atom_wgfmu_read_error` may consume a queued error entry in real library semantics. | WGFMU has both one-entry and summary diagnostics; this flow makes the consumptive read explicit. | P1 |
| drain | `A_flow_drain_easyexpert_errors` | Drain EasyEXPERT remote system errors until no-error or a caller-specified bound. | repeat `A_atom_easyexpert_read_system_error` until code 0 or `max_errors` -> `A_atom_easyexpert_get_workspace_state` | `max_errors=20`, `stop_on_no_error=true` | Error entries, drained count, truncated flag, final workspace state. | Consumes EasyEXPERT FIFO error entries. | EasyEXPERT exposes FIFO system errors; bounded drain logic should be centralized rather than duplicated in clients. | P1 |
| collect | `A_flow_collect_flex_output_buffer` | Read already-produced FLEX output-buffer data without starting a measurement. | `A_atom_flex_wait_opc` -> `A_atom_flex_query_buffer_count` -> conditional `A_atom_flex_read_output_buffer` -> `A_atom_flex_query_buffer_count` -> `A_atom_flex_read_error_queue` -> `A_atom_flex_read_status_byte` | `timeout_s`, `max_items=100`, `read_when_empty=false`, `clear_errors=false` | Pre/post buffer counts, returned items, parser note, error snapshot, final status byte. | Reading the output buffer may be consumptive; it does not execute a measurement. | Count-read-count ordering prevents clients from confusing query responses with measurement output-buffer data. | P0 |
| collect | `A_flow_collect_wgfmu_event_progress` | Collect WGFMU progress and event-completion readbacks for work started elsewhere. | `A_atom_wgfmu_get_status` -> repeat `A_atom_wgfmu_get_channel_status` -> repeat `A_atom_wgfmu_get_completed_event_count` -> optional repeat `A_atom_wgfmu_is_event_completed` -> `A_atom_wgfmu_read_warning_summary` | `channel_ids`, `events=[]`, `include_warning_summary=true` | Overall status, per-channel status, completed event counts, event completion results, warning summary. | Non-destructive progress collection; no abort, initialize, connect, or measurement execution. | Long WGFMU workflows need a reusable progress readout that remains clearly A-class. | P1 |
| collect | `A_flow_collect_easyexpert_result` | Fetch the latest EasyEXPERT result block after another workflow has produced it. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_wait_opc` -> `A_atom_easyexpert_set_result_format` -> `A_atom_easyexpert_fetch_result` -> `A_atom_easyexpert_read_system_error` | `format_name="TEXT"`, `timeout_s` | Workspace state, operation-complete result, result format, latest result block, parser note, error entry. | Changes parser/result-format software context and consumes one error FIFO entry; does not run a test. | Result fetch is parser-sensitive and should always carry operation-complete and error context. | P0 |
| prepare | `A_flow_prepare_flex_output_buffer` | Prepare parser-facing FLEX output-buffer state before a future external measurement workflow writes data. | `A_atom_flex_wait_opc` -> `A_atom_flex_set_data_format` -> `A_atom_flex_configure_timestamp` -> optional `A_atom_flex_reset_timestamp` -> `A_atom_flex_clear_output_buffer` -> `A_atom_flex_query_buffer_count` -> `A_atom_flex_read_status_byte` | `format_mode=1`, `output_mode=1`, `timestamp_enabled=true`, `reset_timestamp=false`, `allow_clear_buffer=false`, `timeout_s` | Applied format, timestamp mode, optional timestamp reset result, confirmed buffer count, status byte. | Destructive when buffer is cleared; timestamp reset changes timing context. Require explicit `allow_clear_buffer=true`. | Format, timestamp, and buffer clearing define the later parser contract and should not be scattered across callers. | P1 |
| prepare | `A_flow_prepare_wgfmu_logging` | Configure WGFMU logging and warning level for a session opened elsewhere. | `A_atom_wgfmu_set_timeout` -> `A_atom_wgfmu_open_log` -> `A_atom_wgfmu_set_warning_level` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | `timeout_s`, `file_name`, `warning_level="NORMAL"` | Timeout result, log file result, warning-level setting result, error summary, warning summary. | Opens/changes log state and changes WGFMU warning-policy session state. | Logging and warning policy are stateful A-class setup that should be explicit and auditable before long WGFMU jobs. | P1 |
| select | `A_flow_select_easyexpert_workspace` | Select/open an EasyEXPERT workspace and verify ready context. | `A_atom_easyexpert_identify` -> `A_atom_easyexpert_list_workspaces` -> `A_atom_easyexpert_open_workspace` -> `A_atom_easyexpert_wait_opc` -> `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` -> `A_atom_easyexpert_read_system_error` | `workspace`, `timeout_s` | Host identity, workspace catalog, open result, OPC result, workspace state/name, error entry. | Changes EasyEXPERT software workspace context and consumes one error FIFO entry. | Workspace open is a multi-step remote handshake and should not be hidden inside catalog or result collection. | P0 |
| select | `A_flow_select_easyexpert_bench_context` | Select exactly one EasyEXPERT app test or preset setup without executing it. | `A_atom_easyexpert_get_workspace_state` -> branch app: `A_atom_easyexpert_list_app_tests` -> `A_atom_easyexpert_select_app_test`; branch preset: `A_atom_easyexpert_list_preset_groups` -> `A_atom_easyexpert_select_preset_group` -> `A_atom_easyexpert_list_preset_setups` -> `A_atom_easyexpert_select_preset_setup`; then `A_atom_easyexpert_get_selected_name` -> `A_atom_easyexpert_read_system_error` | `context_type="app_test" or "preset_setup"`, `test_name`, `preset_group`, `setup_name` | Workspace state, available catalog for the selected branch, selection result, selected name, error entry. | Changes EasyEXPERT software selection context and consumes one error FIFO entry; no measurement execution. | One branched flow avoids separate per-app/per-preset catalog explosion while keeping selection auditable. | P1 |
| teardown | `A_flow_teardown_flex_session` | Record final direct-session communication context and close the FLEX transport. | `A_atom_flex_query_buffer_count` -> `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` -> `A_atom_flex_query_settings` -> `A_atom_flex_disconnect` | `read_errors_clear=false`, `require_external_safe_state=true` | Final buffer count, status byte, error snapshot, settings, disconnect result. | Closes direct session; not a safe shutdown and does not zero or disable outputs. | Final context-before-close is a repeated logging need, but safety cleanup must remain outside A_flow. | P1 |
| teardown | `A_flow_teardown_wgfmu_session` | Capture final WGFMU diagnostics, close optional log, and close the WGFMU library session. | `A_atom_wgfmu_get_status` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` -> optional `A_atom_wgfmu_close_log` -> `A_atom_wgfmu_close_session` | `close_log=true`, `include_status=true` | Final WGFMU status, summaries, log-close result, session-close result. | Closes log/session; does not initialize WGFMU or alter channel output state. | Closing order and final diagnostics are easy to forget and should be standardized. | P1 |
| teardown | `A_flow_teardown_easyexpert_workspace` | Close the active EasyEXPERT workspace and capture close result/error context. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` -> `A_atom_easyexpert_close_workspace` -> `A_atom_easyexpert_wait_opc` -> `A_atom_easyexpert_read_system_error` | `timeout_s`, `ignore_no_workspace=true` | Pre-close workspace state/name, close result, OPC result, error entry. | Closes EasyEXPERT workspace context and consumes one error FIFO entry. | EasyEXPERT close should be symmetrical with workspace selection and must not be described as hardware-safe shutdown. | P1 |

## Category Notes

### discover

Belongs here: first-contact, catalog, identity, module, channel-ID, workspace, and available-definition enumeration. Discovery may open or validate a session when that is the natural entry boundary for the interface.

Does not belong here: reset-and-rediscover, initialize-and-discover, preflight gates, self-test, calibration, channel enable/disable, or cross-interface "full bench discovery" mega-flows.

### snapshot

Belongs here: non-destructive current-state readback, status bytes, settings, workspace context, selected EasyEXPERT name, WGFMU status, channel status, and non-clearing summaries.

Does not belong here: queue drains, buffer reads that consume data, workspace/app/preset selection, result-format changes, buffer clears, or any operation that claims safety readiness.

### drain

Belongs here: intentionally consumptive reads of error queues or FIFO diagnostics, with bounded loops and annotation where available. `drain` exists separately from `snapshot` because audit and retry semantics differ.

Does not belong here: status snapshots that merely include an error count, non-consumptive summaries, clearing output buffers, or using errors as a preflight gate.

### collect

Belongs here: retrieval of data, result blocks, or progress/events that already exist because another workflow produced them. It never starts, configures, or validates a measurement.

Does not belong here: measurement execution, sweep setup, app-test run, channel enable, compliance/range setup, or "measure then collect" wrappers.

### prepare

Belongs here: parser-facing format/timestamp setup, output-buffer cleanup with explicit consent, WGFMU logging, warning-level setup, and other A-class session/software setup that does not touch DUT output state.

Does not belong here: reset, initialize, zero output, channel enable/disable, safety preflight, route switching, correction/calibration, or hidden measurement recipe setup. Stateful prepare flows must advertise their side effects.

### select

Belongs here: EasyEXPERT workspace selection/open, application-test selection, preset-group selection, and preset-setup selection. These change remote software context but do not execute a measurement or alter DUT output state.

Does not belong here: running an EasyEXPERT test, selecting physical channels for output, routing paths, or setting force/sweep parameters. FLEX and WGFMU do not get select flows unless a future A atom exposes a similarly software-only context.

### teardown

Belongs here: final A-class context capture, log close, workspace close, and session disconnect/close. Teardown may close software or communication resources.

Does not belong here: safe shutdown, abort, zero, disable, initialize, output verification, or recovery. Any teardown that claims DUT safety belongs in B/AB design, not A_flow.

## Rejected / Avoided A_flow Combinations

| Candidate | Why rejected or avoided |
|---|---|
| `A_flow_discover_flex_wgfmu_easyexpert_system` | Cross-interface mega-flow. FLEX, WGFMU, and EasyEXPERT have different sessions and failure modes; callers can orchestrate the focused discovery flows. |
| `A_flow_teardown_flex_safe_session` | Safe teardown requires zero/disable/confirm operations from B atoms. Pure A teardown can only close/log context. |
| `A_flow_reset_discover_flex_session` | Reset and initialize are B-class lifecycle operations, even if followed by A discovery. |
| `A_flow_preflight_flex_ready` | Preflight gates safety and measurement permission, so it belongs outside A_flow. |
| `A_flow_prepare_flex_channels_and_buffer` | Channel enable/disable and output state changes are B-class; only buffer format/clear belongs in A. |
| `A_flow_measure_collect_flex_output_buffer` | Measurement execution is future C-class; only collecting an already-produced buffer belongs in A. |
| `A_flow_initialize_discover_wgfmu_session` | WGFMU initialize is B-class state control. Discovery can open the session and read status only. |
| `A_flow_prepare_wgfmu_clear_setup` | `A_atom_wgfmu_clear` is A-class but destructive to WGFMU software setup. Keep it as an explicit atom until a narrow guarded flow is justified. |
| `A_flow_select_easyexpert_app_test_*` per app | Per-test flow names explode with catalog contents. Use `A_flow_select_easyexpert_bench_context` with `context_type` and names as inputs. |
| `A_flow_select_easyexpert_preset_*` per group/setup | Per-preset wrappers duplicate catalog data and create a combinatorial catalog x setup surface. |
| `A_flow_prepare_easyexpert_full_recipe` | Broad app-test parameter editing can drift into C-like recipe setup. Keep selection in A and defer larger recipe-preparation flows until C boundaries are decided. |
| `A_flow_configure_flex_status_polling` | Valuable but omitted for now because current atoms can set SRQ mask but cannot read/restore the prior mask. Revisit after missing A atoms exist. |
| `A_flow_easyexpert_abort_fetch_result` | Abort is B-class; fetching a result can remain A-class as `A_flow_collect_easyexpert_result`. |
| Any `AB_flow_*` or mixed A/B wrapper | Explicitly out of scope. A_flow composes only A atoms. |

## Missing A_atoms Needed Later

| Missing A atom | Valuable blocked A_flow | Why it blocks the flow |
|---|---|---|
| `A_atom_flex_query_srq_mask` | `A_flow_prepare_flex_status_polling` | Current `A_atom_flex_configure_srq` can set the mask but cannot capture/restore prior client policy. |
| `A_atom_flex_serial_poll_status_byte` | Interrupt-oriented FLEX status polling/drain flows | Serial poll and `*STB?` can have different clearing semantics; a correct SRQ flow should expose the serial-poll path explicitly. |
| `A_atom_wgfmu_get_warning_level` | Reversible `A_flow_prepare_wgfmu_logging` and richer WGFMU snapshots | Current surface can set warning level but cannot read the previous value for audit or restoration. |
| `A_atom_easyexpert_get_result_format` | Non-mutating EasyEXPERT result-context snapshot and reversible result collection | Current collection sets result format but cannot report or restore the previous parser format. |
| `A_atom_easyexpert_open_session` and `A_atom_easyexpert_close_session` | True EasyEXPERT remote session discover/teardown | Current EasyEXPERT atoms model remote commands but not socket/session lifecycle explicitly. |
| `A_atom_easyexpert_fetch_result_siblings` | Multi-result EasyEXPERT collection | Current `A_atom_easyexpert_fetch_result` covers latest result only; sibling/result-set collection should not be faked by repeated latest fetches. |

## Implementation Notes

Return schema should be structured and audit-friendly:

```python
{
    "flow": "A_flow_<operation>_<interface>_<subject>",
    "flow_class": "A",
    "category": "<operation>",
    "interface": "<flex|wgfmu|easyexpert>",
    "subject": "<subject>",
    "fake": True,
    "hardware_touched": False,
    "ok": True,
    "partial": False,
    "inputs": {},
    "outputs": {},
    "warnings": [],
    "destructive": False,
    "consumptive": False,
    "atoms_called": [],
    "atom_results": []
}
```

Sequencing should default to serial execution on one FLEX, WGFMU, or EasyEXPERT session. Even when reads are logically independent, real instrument query buffers and single-connection remotes make concurrent transport commands risky. Parallelism should be limited to client-side parsing or to clearly independent sessions.

Data-dependent loops must be bounded. Error drains should stop on no-error or `max_errors`, and catalog fan-out should use `max_groups` or paging if the real catalog can be large.

Partial failure is expected. A flow should return every completed atom result, set `partial=true`, and stop when a later atom depends on a failed earlier atom. It should not mask a transport/session failure behind a generic success.

Fake semantics must remain explicit. These flows should preserve atom-level `fake: true` and `hardware_touched: false` style fields, should not imply that a fake connection is real, and should not claim DUT safety. A pure A teardown is communication/software cleanup only; any safety cleanup is B/AB territory.
