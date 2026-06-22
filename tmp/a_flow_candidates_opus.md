# A Flow Candidates - Opus

## Scope

**A_flow tools compose exclusively A_atom tools** into reusable ordered (or partially parallel) sequences. They cover:

- **Connection / session lifecycle**: opening, discovering, and closing direct-GPIB, WGFMU instrument-library, and EasyEXPERT remote sessions.
- **Status / health snapshots**: reading status bytes, error queues, settings, and diagnostic summaries.
- **Error drain / diagnosis**: exhaustively reading and annotating error queues.
- **Output-buffer lifecycle**: preparing the measurement data buffer (format, timestamp, clear) and reading it back.
- **Discovery / catalog browsing**: enumerating modules, workspaces, application tests, and preset setups.
- **Result retrieval**: fetching measurement results from EasyEXPERT with error context.

A_flow tools **cannot**:

- Reset, initialize, or abort the instrument (B_atom).
- Enable/disable channels, zero outputs, or change DUT-facing output state (B_atom).
- Run self-test, self-calibration, or diagnostics (B_atom).
- Configure measurement recipes (future C_atom).
- Set compliance, ranging, force values, or sweep parameters (future C_atom).
- Perform safety checks or interlock queries (B_atom).

A_flow tools are the "eyes and ears" layer — they observe, discover, communicate, and retrieve data. They never push current or voltage into a DUT.

---

## Candidate A_flow Table

### B1500A Direct Flows

| Flow Name | Purpose | Ordered Atom Sequence | Parallelizable Steps | Inputs | Outputs | Why This Should Be A Flow | Risks / Caveats | Priority |
|---|---|---|---|---|---|---|---|---|
| `A_flow_discover_b1500_session` | Open a direct B1500A GPIB session and return a full startup snapshot: identity, module map, settings, and error state. | 1. `A_atom_connect_b1500` → 2. `A_atom_identify_b1500` ∥ `A_atom_list_installed_modules` → 3. `A_atom_query_current_settings` ∥ `A_atom_read_error_queue` | Steps 2a/2b parallelizable after connect completes; steps 3a/3b parallelizable after identity/modules return. | `gpib_address` (int, default 17), `gpib_board` (int, default 0), `timeout_ms` (int, default 600000) | `{ instrument_id, modules[], settings{}, errors[], connected }` | Every session starts with connect + discover. Four atoms that always run together; exposing them individually forces the caller to remember the correct order and handle partial failures. | If `connect` fails, the remaining atoms are meaningless — the flow must short-circuit. Real implementation must acquire a transport lock before proceeding. | **P0** |
| `A_flow_snapshot_b1500_health` | Read a comprehensive instrument health snapshot on an already-open session. Does not connect or disconnect. | 1. `A_atom_read_status_byte` ∥ `A_atom_read_error_queue` ∥ `A_atom_query_current_settings` ∥ `A_atom_read_timestamp` | All four atoms are fully parallelizable (independent GPIB queries on an existing session). | None (operates on active session) | `{ status_byte{decoded}, errors[], settings{}, timestamp_s }` | The most common "what's happening?" query. Individually calling four atoms is tedious and error-prone when done ad hoc. This is the go-to monitoring primitive. | Status byte and error queue are point-in-time snapshots; interleaving with ongoing measurements may produce stale reads. Consider OPC gating in real implementation. | **P0** |
| `A_flow_drain_b1500_errors` | Exhaustively read and annotate the B1500A error queue, translating each code to its human-readable message. | 1. `A_atom_read_error_queue(clear_after_read=False)` → 2. For each error code: `A_atom_lookup_error_message(error_code)` → 3. `A_atom_read_error_queue(clear_after_read=True)` | Step 2 lookups are parallelizable across error codes. Steps 1 and 3 are sequential (read-then-clear). | `clear` (bool, default True): whether to clear after draining | `{ annotated_errors[{code, message, severity}], count, cleared }` | Error codes alone are useless to an LLM or human operator. This flow turns opaque numeric errors into actionable diagnostics. The read-lookup-clear pattern is a standard recipe that should not be reinvented per caller. | `EMG?` only covers codes 0–999; extended errors from `ERRX?` may not have `EMG?` entries. The flow should fall back to structured-table lookup for out-of-range codes. Race condition: new errors can arrive between step 1 and step 3 in real hardware. | **P0** |
| `A_flow_prepare_data_output` | Configure the B1500A output data buffer for an upcoming measurement: set data format, enable/reset timestamps, and clear stale buffer contents. | 1. `A_atom_set_data_format` ∥ `A_atom_configure_timestamp` → 2. `A_atom_reset_timestamp` → 3. `A_atom_clear_output_buffer` | Step 1a/1b parallelizable (independent FMT and TSC commands). Steps 2 and 3 sequential (reset after config, clear after reset). | `format_mode` (int, default 1), `output_mode` (int, default 1), `timestamp_enabled` (bool, default True) | `{ format_mode, output_mode, timestamp_enabled, timestamp_s: 0.0, buffer_items: 0 }` | Pre-measurement buffer preparation is a 4-atom recipe that measurement flows (future AB/C flows) will always need. Forgetting `BC` before a new measurement means stale data contaminates results. Forgetting `TSR` means timestamps are wrong. | `FMT` mode determines the parser contract for `A_flow_read_buffered_results`; the two flows must agree. Real implementation should record the chosen format in session state. | **P1** |
| `A_flow_read_buffered_results` | Read measurement results from the B1500A output data buffer with item count and a final timestamp. | 1. `A_atom_query_output_buffer_count` → 2. `A_atom_read_output_buffer(max_items=count)` → 3. `A_atom_read_timestamp` | Steps are strictly sequential: count determines read size; timestamp is post-read metadata. | `max_items_override` (int, optional): cap on items to read regardless of buffer count | `{ buffer_count, items[], timestamp_s, truncated }` | Post-measurement readback is always count-then-read-then-timestamp. Callers should not need to remember `NUB?` before reading. The flow also handles the case where `NUB?` returns 0 (no data) gracefully. | If the FMT mode is binary, the items need specialized parsing. The flow should tag the active FMT mode in its response so downstream parsers know the contract. Buffer read is destructive; re-reading returns nothing. | **P1** |

### WGFMU Session Flows

| Flow Name | Purpose | Ordered Atom Sequence | Parallelizable Steps | Inputs | Outputs | Why This Should Be A Flow | Risks / Caveats | Priority |
|---|---|---|---|---|---|---|---|---|
| `A_flow_discover_wgfmu_session` | Open a WGFMU instrument-library session, configure timeout, discover channels, and capture initial error/warning state. | 1. `A_atom_wgfmu_open_session` → 2. `A_atom_wgfmu_set_timeout` → 3. `A_atom_wgfmu_get_channel_ids` ∥ `A_atom_wgfmu_read_error` ∥ `A_atom_wgfmu_read_error_summary` | Step 3 atoms are parallelizable after timeout is set. Steps 1–2 are sequential (session must exist before timeout, channels before errors). | `address` (str, default "GPIB0::17::INSTR"), `timeout_s` (float, default 100.0) | `{ connected, channel_ids[], timeout_s, errors[], error_summary }` | WGFMU session startup is a mandatory 4–5 step sequence. The channel-ID discovery uses two API calls internally (`getChannelIdSize` + `getChannelIds`), making it especially easy to misuse standalone. | WGFMU session is separate from the B1500A direct session — both may be needed simultaneously. If `openSession` fails (e.g., DLL not loaded), subsequent calls will fail silently in the real library. | **P0** |
| `A_flow_snapshot_wgfmu_diagnostics` | Read a full WGFMU error and warning diagnostic snapshot on an open session. | 1. `A_atom_wgfmu_read_error` ∥ `A_atom_wgfmu_read_error_summary` ∥ `A_atom_wgfmu_read_warning_summary` | All three atoms are fully parallelizable. | None (operates on active WGFMU session) | `{ errors[], error_summary, warning_summary }` | The three-call pattern is the standard "is the WGFMU healthy?" check. Individually querying errors, error summary, and warning summary is verbose and often incomplete when done ad hoc (callers forget warnings). | Summaries are cumulative since last clear; they may contain stale entries from prior operations. Consider adding `A_atom_wgfmu_clear_setup` as an optional pre-step if a fresh baseline is needed (but that changes software state, so it's opt-in). | **P1** |
| `A_flow_teardown_wgfmu_session` | Capture final diagnostics, close the log file (if open), and close the WGFMU session. | 1. `A_atom_wgfmu_read_error_summary` ∥ `A_atom_wgfmu_read_warning_summary` → 2. `A_atom_wgfmu_close_log_file` → 3. `A_atom_wgfmu_close_session` | Step 1 atoms parallelizable; steps 2–3 sequential (close log before session). | None | `{ error_summary, warning_summary, log_closed, session_closed }` | WGFMU teardown must capture diagnostics before closing the session (errors are lost after `closeSession`). The log file must close before the session, otherwise the library may leak file handles. Real implementations often forget the close order. | Real teardown should call `B_atom_wgfmu_initialize` (B class) before this A_flow to reset channel outputs. This flow intentionally omits that — callers must compose with B_flow. | **P1** |

### EasyEXPERT Remote Flows

| Flow Name | Purpose | Ordered Atom Sequence | Parallelizable Steps | Inputs | Outputs | Why This Should Be A Flow | Risks / Caveats | Priority |
|---|---|---|---|---|---|---|---|---|
| `A_flow_discover_easyexpert_session` | Identify the EasyEXPERT remote host, clear stale status, and discover the full catalog of workspaces, application tests, and preset groups. | 1. `A_atom_easyexpert_identify_remote_host` → 2. `A_atom_easyexpert_clear_status` → 3. `A_atom_easyexpert_list_workspaces` ∥ `A_atom_easyexpert_list_application_tests` ∥ `A_atom_easyexpert_list_preset_groups` | Step 3 atoms are fully parallelizable. Steps 1–2 are sequential (identify before clear, clear before catalog). | None (EasyEXPERT remote connection assumed established at transport level) | `{ host, workspaces[], application_tests[], preset_groups[], status_cleared }` | First thing any EasyEXPERT remote client does: identify, clear errors, then discover what's available. The three catalog queries are independent and benefit from parallelism. | EasyEXPERT remote requires the EasyEXPERT software to be running on the B1500A controller PC. If the host is not reachable, `identify` will timeout. The `clear_status` call destroys any pending error state — log it first if needed. | **P0** |
| `A_flow_open_easyexpert_workspace` | Open an EasyEXPERT workspace, wait for completion, verify state, and configure result format. | 1. `A_atom_easyexpert_open_workspace` → 2. `A_atom_easyexpert_wait_operation_complete` → 3. `A_atom_easyexpert_get_workspace_state` → 4. `A_atom_easyexpert_set_result_format` | Strictly sequential: each step depends on the prior step's success. | `workspace` (str, default "default"), `result_format` (str, default "TEXT") | `{ workspace, opened, state, result_format, complete }` | Opening a workspace is a multi-step handshake: open → wait → verify → configure. Skipping `*OPC?` after open can lead to queries on a not-yet-ready workspace. Skipping the state check means you don't know if open actually succeeded (it returns before the workspace is fully loaded). | If the workspace doesn't exist, open returns an error (code 201). The flow should detect this and return a clear error instead of proceeding to wait/verify. `*OPC?` has a timeout; large workspaces may need longer. | **P1** |
| `A_flow_fetch_easyexpert_result` | Fetch the latest EasyEXPERT remote measurement result and check for system errors. | 1. `A_atom_easyexpert_fetch_latest_result` → 2. `A_atom_easyexpert_read_system_error` | Sequential: fetch first, then check for errors. | None (result must be available from prior measurement execution) | `{ result, error_code, error_message }` | Result fetch without error check is dangerous: a stale or failed result looks valid. This two-step pattern ensures every result comes with its error context. Simple but critical for data integrity. | `:RESult:FETch[:LATest]?` returns SCPI definite-length block data that needs parsing. The result may be `null` if no measurement has run. Error queue is FIFO — reading consumes the entry. | **P1** |
| `A_flow_browse_easyexpert_presets` | Enumerate all EasyEXPERT preset groups and the setups within each group. | 1. `A_atom_easyexpert_list_preset_groups` → 2. For each group: `A_atom_easyexpert_list_preset_setups(group)` | Step 2 iterations are parallelizable across groups. | None | `{ groups[{ name, setups[] }] }` | Preset browsing requires a two-level query: groups first, then setups per group. The fan-out pattern is awkward for individual atom callers to implement correctly and benefits from a single flow call. | Groups may be empty. Some groups may contain many setups. The flow should cap iteration or page results to avoid overwhelming the response. Real EasyEXPERT preset names may contain spaces and special characters — use exact quoting. | **P2** |
| `A_flow_teardown_easyexpert_workspace` | Close the active EasyEXPERT workspace, wait for completion, and capture any final system errors. | 1. `A_atom_easyexpert_close_workspace` → 2. `A_atom_easyexpert_wait_operation_complete` → 3. `A_atom_easyexpert_read_system_error` | Strictly sequential: close → wait → error check. | None | `{ closed, complete, error_code, error_message }` | Workspace close without `*OPC?` can leave EasyEXPERT in a transitional state. Without the error check, a failed close goes unnoticed. The three-step pattern mirrors the open flow and should be symmetric. | If no workspace is open, `close` returns an error. The flow should handle this gracefully (idempotent close). `*OPC?` timeout applies. | **P1** |

---

## Rejected / Too Broad A_flow Candidates

| Candidate | Why Rejected |
|---|---|
| `A_flow_connect_and_reset_b1500` | Requires `B_atom_reset_instrument` (`*RST`) or `B_atom_initialize_instrument` (`IN`). Reset is a state-changing B_atom that affects all channel settings and output state. Must be an AB_flow. |
| `A_flow_safe_disconnect_b1500` | Requires `B_atom_zero_all_outputs` (`DZ` + `CL`) before `A_atom_disconnect_b1500`. The safety cleanup is B-class. Must be a B_flow or AB_flow. |
| `A_flow_preflight_check` | Requires `B_atom_run_preflight_checks` (which internally queries interlock, transport, and pin-map readiness). The preflight gate is B-class because it controls whether measurements may proceed. |
| `A_flow_self_test_and_calibrate` | Requires `B_atom_run_self_test` and `B_atom_run_self_calibration`. Both are B-class because they can temporarily change instrument state and take minutes. |
| `A_flow_enable_measurement_channels` | Requires `B_atom_enable_channels` (`CN`). Enabling channels is a state-changing B_atom that allows current/voltage output. |
| `A_flow_initialize_wgfmu_session` | Requires `B_atom_wgfmu_initialize`. The `initialize` call resets all WGFMU channel states, which is B-class. |
| `A_flow_emergency_stop` | Requires `B_atom_abort_operation` + `B_atom_zero_all_outputs`. This is the core B-class safety primitive. |
| `A_flow_full_system_discovery` | Composes `A_flow_discover_b1500_session` + `A_flow_discover_wgfmu_session` + `A_flow_discover_easyexpert_session`. Too broad for a single flow — three independent transport sessions with different failure modes. Should be orchestrated by the caller or a higher-level workflow, not a single A_flow. |
| `A_flow_wgfmu_enable_logging` | Only two atoms (`set_warning_level` → `open_log_file`). Too thin to justify a flow abstraction; callers can sequence them directly. |
| `A_flow_configure_srq_for_data_ready` | `A_atom_configure_service_request` is a single atom with a bitmask parameter. The "flow" would just be one atom call — no composition value. |

---

## Missing A_atoms Noted During Planning

| Missing Atom | Basis | Why Needed | Domain |
|---|---|---|---|
| `A_atom_wgfmu_get_status` | `WGFMU_getStatus` (PDF pp. 101, 123) | Returns overall WGFMU execution status (COMPLETED / RUNNING / IDLE / ABORTED / etc.). Required by `A_flow_snapshot_wgfmu_diagnostics` to report whether the WGFMU is idle, running, or in an error state. Currently the diagnostics flow can only report errors/warnings but not execution status. | WGFMU |
| `A_atom_wgfmu_get_channel_status` | `WGFMU_getChannelStatus` (PDF pp. 102, 154–155) | Returns per-channel execution status with elapsed and total time. Essential for monitoring long WGFMU stress/reliability runs. Could extend `A_flow_snapshot_wgfmu_diagnostics` or support a future poll/progress flow. | WGFMU |
| `A_atom_easyexpert_get_selected_test_name` | `[:BENCh][:SELected]:NAME?` (EasyEXPERT Ch. 6) | Returns the name of the currently selected/loaded test definition. Useful for `A_flow_discover_easyexpert_session` to report what test is currently active, and for pre-execution verification ("are we about to run the right test?"). | EasyEXPERT |

**Not proposed** (borderline, deferred):

- `A_atom_wgfmu_get_completed_measure_event_size`: Returns completed/total measure event counts. This is closer to C-class measurement progress than A-class status, because it's only meaningful during an active measurement. Defer to C_atom or AC_flow design.
- `A_atom_easyexpert_select_application_test`: `[:BENCh]:APPlication:SELect`. Changes which test definition is loaded in EasyEXPERT. Borderline A/B — it doesn't affect DUT output, but it does change application state in a way that sets up for execution. Defer classification until B_flow / AB_flow design.

---

## Design Notes

### Naming Convention

- `A_flow_<verb>_<domain>_<noun>` — e.g., `A_flow_discover_b1500_session`, `A_flow_snapshot_wgfmu_diagnostics`.
- Domains: `b1500` (direct GPIB), `wgfmu` (instrument library), `easyexpert` (remote).
- Verbs: `discover` (initial connect + enumerate), `snapshot` (read-only health/status), `drain` (exhaustive read + clear), `prepare` (configure for upcoming operation), `read` / `fetch` (retrieve data), `browse` (enumerate catalogs), `teardown` (close/cleanup without state changes), `open` (establish sub-session like workspace).
- No numbered prefixes. No `_01_`, `_02_` in names.

### Return Schema

All A_flow tools should return a dict with:

```python
{
    "flow": "A_flow_<name>",
    "ok": bool,             # True if all atoms succeeded
    "atoms_called": [...],  # ordered list of atom names actually invoked
    "partial": bool,        # True if some atoms succeeded before a failure
    "error": str | None,    # first error encountered, if any
    # ...domain-specific payload fields
}
```

This enables callers to distinguish full success, partial success (e.g., connect succeeded but module query failed), and total failure.

### Idempotency

- **Idempotent flows** (safe to retry): `snapshot_b1500_health`, `snapshot_wgfmu_diagnostics`, `drain_b1500_errors`, `read_buffered_results`, `fetch_easyexpert_result`, `browse_easyexpert_presets`.
- **Non-idempotent flows** (side effects on retry): `discover_b1500_session` (opens connection), `discover_wgfmu_session` (opens session), `discover_easyexpert_session` (clears status), `prepare_data_output` (resets timestamp/buffer), `open_easyexpert_workspace` (opens workspace), `teardown_*` (closes sessions/workspaces).
- Non-idempotent flows should check preconditions (e.g., "is session already open?") and either skip redundant atoms or return a clear "already in target state" response.

### Parallelism Strategy

- Flows with `∥` steps should use `asyncio.gather` or equivalent when a real async transport is available.
- During fake/test mode, sequential execution is fine — the parallelism markers serve as implementation guidance.
- The `A_flow_drain_b1500_errors` step-2 fan-out (per-error-code lookup) is the only flow with data-dependent parallelism; all others have statically known parallel groups.

### Client UX Considerations

- Flows should return structured data, not raw SCPI strings. The atom layer handles SCPI parsing; the flow layer handles composition.
- Discovery flows (`discover_*`) should be the recommended first call in any new session. Client documentation should list them as entry points.
- Snapshot flows (`snapshot_*`) should be cheap enough to call frequently (e.g., after every measurement cycle) as health monitors.
- Teardown flows should be called in `finally` blocks. They must not raise exceptions that mask the original error.

### Composition with B_flow / AB_flow

- `A_flow_discover_b1500_session` is the "A half" of a full startup sequence. The "B half" adds `B_atom_reset_instrument` + `B_atom_run_preflight_checks`. They compose into `AB_flow_startup_b1500_session`.
- `A_flow_teardown_wgfmu_session` is the "A half" of a full WGFMU cleanup. The "B half" prepends `B_atom_wgfmu_initialize`. They compose into `BA_flow_teardown_wgfmu_session` (B first, then A).
- `A_flow_prepare_data_output` is the "A half" of a pre-measurement bracket. The "B half" adds `B_atom_enable_channels` + compliance/range setup.
- These composition patterns should be documented explicitly when B_flow design begins.

### Priority Summary

| Priority | Count | Flows |
|---|---|---|
| **P0** | 4 | `discover_b1500_session`, `snapshot_b1500_health`, `drain_b1500_errors`, `discover_wgfmu_session`, `discover_easyexpert_session` |
| **P1** | 7 | `prepare_data_output`, `read_buffered_results`, `snapshot_wgfmu_diagnostics`, `teardown_wgfmu_session`, `open_easyexpert_workspace`, `fetch_easyexpert_result`, `teardown_easyexpert_workspace` |
| **P2** | 1 | `browse_easyexpert_presets` |

(Note: P0 count is 5 because `discover_easyexpert_session` was elevated to P0 during analysis — it's the mandatory entry point for any EasyEXPERT remote work.)
