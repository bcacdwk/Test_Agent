# A Flow Design - Opus48

Date: 2026-06-22
Status: design proposal only. No production code, no formal docs, no atom renames.
Source of truth for atom names: `src/b1500_test_agent/mcp/server.py` and
`.agents/skills/b1500-semiconductor-testing/references/instrument-interaction-tools.md`.
Old drafts (`tmp/a_flow_arbitration.md`, `tmp/a_flow_candidates_opus.md`,
`tmp/a_flow_candidates_gpt.md`) are treated as intent input only; every atom
reference below is re-pointed to the current live atom names.

## Scope and Principles

An `A_flow_*` composes **only** current `A_atom_*` tools into a reusable, ordered
sequence that captures one coherent read/session/context operation. The confirmed
pattern is:

```text
A_flow_{operation}_{interface}_{subject}
operation in { discover, snapshot, drain, collect, prepare, select, teardown }
interface in { flex, wgfmu, easyexpert }
subject     = short disambiguating noun (session, status, errors, output_buffer, result, workspace, ...)
```

Hard boundaries (what an A_flow must never do):

- **A atoms only.** No `B_atom_*`, no future `C_atom_*`.
- **No state control of the instrument or DUT.** No reset, initialize, abort,
  self-test, diagnostics, self-calibration, zero-cancel, channel enable/disable,
  output zeroing, routing, or correction.
- **No measurement.** No sweep/spot/pulse/CV execution, no EasyEXPERT app-test run.
  EasyEXPERT selection is A-class *software context only*; execution is C-class.
- **No safety claims.** A teardown is communication/software cleanup; it must never
  be marketed as a safe shutdown. Real safe shutdown needs B/AB flows.

Design principles applied to keep the catalog small and honest:

1. **Single transport per flow.** `flex`, `wgfmu`, and `easyexpert` are separate
   sessions with separate failure modes. No cross-interface "discover everything"
   mega-flow; that is the application layer's job.
2. **Name the goal, not the steps.** The first token is the value the flow adds over
   raw atoms; adding a step does not rename the flow.
3. **Not every permutation.** A flow exists only when it captures a repeated
   multi-atom recipe, a risky ordering rule (e.g. count-read-count), a consumptive
   read convention, or a stateful A-class context callers should not hand-roll.
4. **Serial on one session.** B1500A uses a one-response query buffer and EasyEXPERT
   permits a single remote connection, so atoms within a flow run serially.
5. **Mark side effects.** Flows that clear buffers, drain queues, open/close sessions,
   or change software context are flagged and gated by explicit inputs.

Total: **21 flows** (intentionally near the ~20 target). Coverage is symmetric where
it should be — `snapshot`, `drain`, and `teardown` each span all three interfaces —
and deliberately asymmetric where the interface lacks the concept (`select` is
EasyEXPERT-only; `collect` skips interfaces with no produced data to harvest).

## Proposed A_flow Catalog

| Category | Flow Name | Purpose | Ordered Atom Sequence (current exact atom names) | Inputs | Outputs | Destructive/Consumptive? | Why This Deserves A_flow | Priority |
|---|---|---|---|---|---|---|---|---|
| discover | `A_flow_discover_flex_session` | Open the direct FLEX/VISA path and capture the minimum identity, module, status, and error context. | `A_atom_flex_connect` -> `A_atom_flex_identify` -> `A_atom_flex_list_modules` -> `A_atom_flex_query_settings` -> `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` (`clear_after_read=false`) | `gpib_address=17`, `gpib_board=0`, `timeout_ms=600000` | Connection result, instrument id, modules[], settings, status-byte decode, non-clearing error snapshot. | **Opens session.** Reads errors but does not clear them. | Canonical direct-entry bundle; enforces correct order and short-circuits if `connect` fails. | P0 |
| discover | `A_flow_discover_wgfmu_session` | Open a WGFMU library session, set timeout, discover channel IDs, and capture initial status/summaries. | `A_atom_wgfmu_open_session` -> `A_atom_wgfmu_set_timeout` -> `A_atom_wgfmu_get_channel_ids` -> `A_atom_wgfmu_get_status` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | `address="GPIB0::17::INSTR"`, `timeout_s=100.0` | Session result, channel_ids[], overall status, error/warning summaries. | **Opens session;** changes timeout session state. | WGFMU has a separate session model; channel-ID discovery uses two internal API calls and is easy to misuse standalone. | P0 |
| discover | `A_flow_discover_easyexpert_remote` | Identify the EasyEXPERT remote endpoint and read workspace availability without selecting or running anything. | `A_atom_easyexpert_identify` -> `A_atom_easyexpert_read_system_error` -> `A_atom_easyexpert_list_workspaces` -> `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` | none (transport assumed up) | Host id, first error entry, workspaces[], workspace state/name. | **Consumes one FIFO error entry** (`:SYSTem:ERRor:NEXT?`). Does not `*CLS`. | EasyEXPERT prerequisites differ from FLEX/WGFMU; minimum remote-context bundle. Read errors first, never auto-clear. | P0 |
| discover | `A_flow_discover_easyexpert_catalogs` | Enumerate application tests and preset setup catalogs in the current workspace context. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_app_tests` -> `A_atom_easyexpert_list_preset_groups` -> per requested group `A_atom_easyexpert_list_preset_setups` -> `A_atom_easyexpert_read_system_error` | `preset_groups="all"`, `include_app_tests=true`, `max_groups` | Workspace state, application_tests[], preset_groups[], setups-by-group, error entry. | **Consumes one FIFO error entry.** Catalog reads are non-destructive; kept separate from `select` to avoid hidden context changes. | Two-level fan-out is awkward to hand-roll; standardizes discovery of runnable definitions distinct from selecting them. | P1 |
| snapshot | `A_flow_snapshot_flex_status` | Non-destructive direct B1500A health snapshot for logs, UI panels, and bug reports. | `A_atom_flex_get_status` -> `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` (`clear_after_read=false`) -> `A_atom_flex_query_settings` -> `A_atom_flex_query_buffer_count` | `clear_errors=false` (fixed) | Composite status, status byte, non-clearing errors, settings, output-buffer count. | **Non-destructive.** Error read is explicitly non-clearing. | The go-to "what is the instrument doing?" bundle; preserves the distinction between status byte, error queue, settings, and buffer readiness. | P0 |
| snapshot | `A_flow_snapshot_wgfmu_diagnostics` | Non-destructive WGFMU overall health snapshot. | `A_atom_wgfmu_get_status` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | none | Overall status, accumulated error summary, accumulated warning summary. | **Non-destructive.** Uses accumulative summaries (not the consuming single-entry read). | Standard "is the WGFMU healthy?" check; intentionally avoids `A_atom_wgfmu_read_error` so it stays non-consuming (that read lives in `drain`). | P0 |
| snapshot | `A_flow_snapshot_easyexpert_context` | Read current EasyEXPERT software context (workspace, selection, bench metadata) without changing it. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` -> `A_atom_easyexpert_get_selected_name` -> `A_atom_easyexpert_get_device_tag` -> `A_atom_easyexpert_get_repeat_count` | none | Workspace state/name, selected test/setup name, device tag, repeat count. | **Non-destructive.** Deliberately omits `read_system_error` to avoid consuming the FIFO. | Read-only companion to `select_*` and batch `prepare`; EasyEXPERT context is easy to lose track of. | P1 |
| drain | `A_flow_drain_flex_errors` | Drain the direct B1500A error queue and annotate known codes. | `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` (`clear_after_read=true`) -> per code `A_atom_flex_lookup_error` -> `A_atom_flex_read_status_byte` | `clear=true`, `lookup_messages=true`, `max_errors` | Initial/final status byte, drained errors[], resolved messages, unresolved extended-code notes. | **Drains/clears the error queue.** | Read-lookup-clear is a standard recipe; `EMG?` covers 0-999 so extended codes must fall back to the structured table. | P0 |
| drain | `A_flow_drain_wgfmu_errors` | Consume queued WGFMU error entries and capture surrounding summaries. | bounded loop `A_atom_wgfmu_read_error` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | `max_errors`, `include_summaries=true` | Drained error entries[], error summary, warning summary. | **Consumes the per-entry WGFMU error queue.** | WGFMU has both one-entry and summary diagnostics; this makes the consuming read explicit and distinct from `snapshot`. | P1 |
| drain | `A_flow_drain_easyexpert_errors` | Drain EasyEXPERT remote system errors until no-error or a caller bound. | bounded loop `A_atom_easyexpert_read_system_error` until code 0 -> optional `A_atom_easyexpert_clear_status` | `max_errors=20`, `stop_on_no_error=true`, `force_clear=false` | Error entries[], drained count, truncated flag, cleared flag. | **Consumes FIFO error entries;** optional `*CLS` clears remote status (gated by `force_clear`). | Bounded FIFO drain logic should be centralized, not duplicated per client; `*CLS` stays explicit. | P1 |
| collect | `A_flow_collect_flex_output_buffer` | Read already-produced FLEX output-buffer data; never starts a measurement. | `A_atom_flex_wait_opc` -> `A_atom_flex_query_buffer_count` -> conditional `A_atom_flex_read_output_buffer` -> `A_atom_flex_query_buffer_count` -> `A_atom_flex_read_error_queue` (`clear_after_read=false`) -> `A_atom_flex_read_status_byte` | `timeout_s`, `max_items=100`, `read_when_empty=false` | Pre/post buffer counts, items[], FMT parser note, non-clearing errors, status byte. | **Consumes output-buffer data** (reading drains it). Does not execute a measurement. | Count-read-count ordering prevents confusing query responses with measurement data; canonical readout. | P0 |
| collect | `A_flow_collect_easyexpert_result` | Fetch the latest EasyEXPERT result block after another workflow produced it. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_wait_opc` -> `A_atom_easyexpert_set_result_format` -> `A_atom_easyexpert_fetch_result` -> `A_atom_easyexpert_read_system_error` | `format_name="TEXT"`, `timeout_s` | Workspace state, OPC result, result format, latest result block, parser note, error entry. | **Changes result-format software context** and **consumes one FIFO error entry.** Does not run a test. | Result fetch is parser-sensitive and should always carry OPC + error context; kept distinct from execution (C). | P0 |
| collect | `A_flow_collect_wgfmu_progress` | Harvest WGFMU per-channel progress and measurement-event completion produced by an active sequence. | `A_atom_wgfmu_get_status` -> per channel `A_atom_wgfmu_get_channel_status` -> per channel `A_atom_wgfmu_get_completed_event_count` -> optional per event `A_atom_wgfmu_is_event_completed` -> `A_atom_wgfmu_read_warning_summary` | `channel_ids`, `events=[]`, `include_warning_summary=true` | Overall status, per-channel status, completed event counts, event-completion results, warning summary. | **Non-destructive** progress readback; no abort/initialize/connect/execution. | Long stress/reliability runs need a reusable progress harvest. **P2 because event progress is only meaningful during an active C-class measurement, which does not exist yet.** | P2 |
| prepare | `A_flow_prepare_flex_output_buffer` | Set parser-facing FLEX output-buffer state before an external measurement writes data. | `A_atom_flex_wait_opc` -> `A_atom_flex_set_data_format` -> `A_atom_flex_configure_timestamp` -> optional `A_atom_flex_reset_timestamp` -> `A_atom_flex_clear_output_buffer` -> `A_atom_flex_query_buffer_count` | `format_mode=1`, `output_mode=1`, `timestamp_enabled=true`, `reset_timestamp=false`, `allow_clear_buffer=false`, `timeout_s` | Applied format, timestamp mode, optional reset result, confirmed empty buffer count. | **Destructive: clears the output buffer (destroys unread data); changes FMT/timestamp session state.** Requires explicit `allow_clear_buffer=true`. | Format + timestamp + buffer-clear define the later parser contract for `collect_flex_output_buffer`; must agree and not be scattered across callers. | P1 |
| prepare | `A_flow_prepare_wgfmu_logging` | Configure WGFMU logging and warning policy for long-running external jobs. | `A_atom_wgfmu_set_timeout` -> `A_atom_wgfmu_open_log` -> `A_atom_wgfmu_set_warning_level` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` | `timeout_s`, `file_name="wgfmu.log"`, `warning_level="NORMAL"` | Timeout result, log-file path, warning-level setting, error/warning summaries. | **Stateful: opens a log file and changes WGFMU warning-policy session state.** Not DUT state. | Long WGFMU jobs need explicit, auditable logging + warning setup; assumes the session is already open (compose after `discover_wgfmu_session`). | P1 |
| select | `A_flow_select_easyexpert_workspace` | Open/select an EasyEXPERT workspace and verify it is ready. | `A_atom_easyexpert_list_workspaces` -> `A_atom_easyexpert_open_workspace` -> `A_atom_easyexpert_wait_opc` -> `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` -> `A_atom_easyexpert_read_system_error` | `workspace="default"`, `timeout_s` | Workspaces[], open result, OPC result, workspace state/name, error entry. | **Changes software context (opens workspace);** consumes one FIFO error entry. | The mandatory gateway for any EasyEXPERT work; open->wait->verify handshake should not be hidden inside discovery or collection. | P0 |
| select | `A_flow_select_easyexpert_app_test` | Select an EasyEXPERT application-test definition as software context (no execution). | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_app_tests` -> `A_atom_easyexpert_select_app_test` -> `A_atom_easyexpert_get_selected_name` -> `A_atom_easyexpert_read_system_error` | `test_name` | Workspace state, app_tests[], selection result, selected name, error entry. | **Changes software context (selected app test);** consumes one FIFO error entry. No measurement run. | Selecting a definition and verifying the selection is a fixed recipe; execution remains C-class. | P1 |
| select | `A_flow_select_easyexpert_preset_setup` | Select an EasyEXPERT preset setup (group then setup) as software context (no execution). | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_list_preset_groups` -> `A_atom_easyexpert_select_preset_group` -> `A_atom_easyexpert_list_preset_setups` -> `A_atom_easyexpert_select_preset_setup` -> `A_atom_easyexpert_get_selected_name` -> `A_atom_easyexpert_read_system_error` | `preset_group`, `setup_name` | Preset groups[], setups[], selection result, selected name, error entry. | **Changes software context (opens group + selects setup);** consumes one FIFO error entry. No measurement run. | Preset selection is genuinely a two-level operation (`:PRESet:OPEN` then `:SETup:SELect`); fixed sequence kept separate from app-test select for legibility. | P1 |
| teardown | `A_flow_teardown_flex_session` | Record final direct-session context, then close the FLEX transport. | `A_atom_flex_query_buffer_count` -> optional `A_atom_flex_read_output_buffer` -> `A_atom_flex_read_status_byte` -> `A_atom_flex_read_error_queue` (`clear_after_read=false`) -> `A_atom_flex_query_settings` -> `A_atom_flex_disconnect` | `read_remaining_output=false`, `max_items=100`, `require_external_safe_state=true` | Final buffer count/data, status byte, errors, settings, disconnect result. | **Closes session. NOT a safe shutdown** — does not zero/disable outputs (that is B). | Context-before-close is a recurring logging need; the safety cleanup must stay outside A and run first. | P1 |
| teardown | `A_flow_teardown_wgfmu_session` | Capture final WGFMU diagnostics, optionally export setup, close log, then close the session. | `A_atom_wgfmu_get_status` -> `A_atom_wgfmu_read_error_summary` -> `A_atom_wgfmu_read_warning_summary` -> optional `A_atom_wgfmu_export_ascii` -> optional `A_atom_wgfmu_close_log` -> `A_atom_wgfmu_close_session` | `export_setup=false`, `file_name`, `close_log=true` | Final status, summaries, export path, log-close result, session-close result. | **Closes log/session.** Does not initialize or zero WGFMU channels (that is B). | Diagnostics are lost after `closeSession`, and the log must close before the session; correct close order should be standardized. | P1 |
| teardown | `A_flow_teardown_easyexpert_workspace` | Capture context, close the active EasyEXPERT workspace, and verify the close. | `A_atom_easyexpert_get_workspace_state` -> `A_atom_easyexpert_get_workspace_name` -> `A_atom_easyexpert_close_workspace` -> `A_atom_easyexpert_wait_opc` -> `A_atom_easyexpert_read_system_error` | `timeout_s`, `ignore_no_workspace=true` | Pre-close state/name, close result, OPC result, error entry. | **Closes workspace software context;** consumes one FIFO error entry. No hardware cleanup implied. | Symmetric to `select_easyexpert_workspace`; close->wait->verify should not be confused with safe shutdown. | P1 |

## Category Notes

### discover (entry)

- **Belongs:** first contact + enumerate — open/validate a session, identify, read
  module/channel inventory, and browse catalogs. Discovery may open or validate a
  session when that is the natural entry boundary for the interface.
- **Does not belong:** reset-and-rediscover, initialize-and-discover (both B);
  preflight/interlock gating (B); self-test/calibration (B); cross-interface
  "full-bench discovery" (application-layer orchestration).
- **Note:** error reads at entry are non-clearing for FLEX (`clear_after_read=false`)
  but inherently FIFO-consuming for EasyEXPERT; that consume is marked, not hidden.

### snapshot (observe)

- **Belongs:** non-destructive current-state readback — status bytes, composite
  status, settings, buffer count, WGFMU overall status, EasyEXPERT software context,
  and non-consuming summaries.
- **Does not belong:** anything that clears or consumes (queue drains, buffer reads),
  selection changes, result-format changes, or readiness/safety claims.
- **Boundary call:** WGFMU per-channel/event progress is **not** snapshot — it is a
  harvest of produced measurement-event data, so it lives in `collect`.

### drain (observe, mutating)

- **Belongs:** intentionally consumptive reads of error/warning queues with bounded
  loops and annotation where available. `drain` is separate from `snapshot` because
  its audit, retry, and idempotency semantics differ (it mutates queue state).
- **Does not belong:** a `snapshot` that merely reports an error count; non-consuming
  summaries; clearing the measurement output buffer; using errors as a preflight gate.

### collect (read-out)

- **Belongs:** retrieval of data/results/progress that already exist because another
  (future C-class) workflow produced them — FLEX output buffer, EasyEXPERT result
  block, WGFMU event progress. It never starts, configures, or validates a measurement.
- **Does not belong:** measurement execution, sweep/spot setup, app-test run, channel
  enable, compliance/range setup, "measure then collect" wrappers.
- **Why no `collect_wgfmu_*` data flow yet:** WGFMU measurement *data* readout is
  C-class; only progress/event counts are A-class, and even those are deferred (P2)
  until a C measurement exists to produce them.

### prepare (setup, stateful)

- **Belongs:** parser-facing and session setup that does not touch DUT output —
  FLEX data-format/timestamp/output-buffer prep, WGFMU logging + warning policy.
- **Be careful (per the brief):** **buffer clear** and **logging/warning setup are
  stateful/destructive.** `prepare_flex_output_buffer` can destroy unread data and is
  gated behind `allow_clear_buffer=true`; `prepare_wgfmu_logging` mutates logging and
  warning-policy session state. Both advertise their side effects in the response.
- **Does not belong:** reset/initialize, zero output, channel enable/disable, safety
  preflight, routing, correction/calibration, or measurement recipe setup.

### select (setup, software context)

- **Belongs (EasyEXPERT-only):** workspace open, application-test selection, and
  preset group+setup selection. **These change remote software context but remain
  A-class** — they do not execute a measurement or alter DUT output.
- **Does not belong:** running a test (C); selecting physical output channels (B);
  routing (B); setting force/sweep parameters (C).
- **Why FLEX/WGFMU have no `select`:** neither exposes an A-class "choose what to run"
  software context. Adding `select_flex_*` or `select_wgfmu_*` would be empty.

### teardown (teardown, A-only)

- **Belongs:** final A-class context capture plus log close, workspace close, and
  session disconnect/close.
- **Does not belong:** safe shutdown, abort, zero, disable, initialize, output
  verification, or recovery. **Any teardown claiming DUT safety is B/AB, not A.**
  All three teardown flows set `require_external_safe_state` expectations and must run
  *after* a B/AB safe-state flow on real hardware.

## Rejected / Avoided A_flow Combinations

| Candidate | Why rejected or avoided |
|---|---|
| `A_flow_discover_flex_wgfmu_easyexpert_system` | Cross-interface mega-flow; three sessions with three failure modes. The app orchestrates the focused discovery flows. |
| `A_flow_teardown_flex_safe_session` / `A_flow_shutdown_flex_*` | "Safe" teardown needs B zero/disable/confirm. Pure A teardown can only close and log context. |
| `A_flow_discover_flex_reset_rediscover` | Reset/initialize are B-class lifecycle, even when followed by A discovery. |
| `A_flow_discover_flex_preflight` | Preflight gates safety/measurement permission and is B-class. |
| `A_flow_prepare_flex_channels_and_buffer` | Channel enable/disable is B-class; only buffer/format/timestamp prep is A. |
| `A_flow_collect_flex_measure_then_buffer` | Measurement execution is future C-class; only harvesting an already-produced buffer is A. |
| `A_flow_discover_wgfmu_initialize` | `WGFMU_initialize` is B-class state control; discovery opens the session and reads status only. |
| `A_flow_prepare_wgfmu_clear_setup` | `A_atom_wgfmu_clear` is A-class but destructive to unsaved software setup; keep it an explicit atom until a narrowly guarded flow is justified. |
| `A_flow_select_easyexpert_<specific test/preset name>` | Per-name wrappers explode with catalog contents. Names are *inputs* to the two type-level select flows, not new flows. |
| `A_flow_select_easyexpert_bench_context` (one branched app-or-preset flow) | Considered (it hits 20), but a single flow running two different atom sequences via a `context_type` switch is "two flows in a trench coat." Kept `select_easyexpert_app_test` and `select_easyexpert_preset_setup` separate so each has a fixed, legible sequence. |
| `A_flow_prepare_flex_status_polling` | Valuable but **deferred to P2 / out of catalog**: `A_atom_flex_configure_srq` can set the SRQ mask but no atom can read/restore the prior mask, so the flow cannot be made reversible or safe for shared sessions (see Missing A_atoms). |
| `A_flow_prepare_easyexpert_batch_metadata` | Device-tag + repeat-count + result-format batch prep is a real P2 pattern, but folded into notes for now to avoid inflating `prepare`; revisit for wafer automation. |
| `A_flow_browse_easyexpert_presets` | Redundant convenience subset of `discover_easyexpert_catalogs`; not worth a separate flow. |
| `A_flow_collect_easyexpert_abort_and_fetch` | Abort is B-class; the fetch half is already `collect_easyexpert_result`. |
| `A_flow_*_easyexpert_zero_cancel_*` | Zero-cancel on/off/measure/query is B calibration/state-control, not A. |
| Any `AB_flow_*` / mixed A+B wrapper | Out of scope by definition. A_flow composes only A atoms. |

## Missing A_atoms Needed Later

Only atoms that block an otherwise-valuable A_flow are listed.

| Missing A atom | Blocked A_flow | Why it blocks |
|---|---|---|
| `A_atom_flex_query_srq_mask` | `A_flow_prepare_flex_status_polling` (deferred P2) | `A_atom_flex_configure_srq` can set `*SRE` but nothing can capture/restore the prior mask; without it the flow is irreversible and unsafe to ship for shared sessions. |
| `A_atom_wgfmu_get_warning_level` | Fully reversible `A_flow_prepare_wgfmu_logging`; richer non-mutating WGFMU snapshot | The surface can set warning level but cannot read the previous value for audit/restore, so `prepare_wgfmu_logging` cannot guarantee a clean rollback. |
| `A_atom_easyexpert_get_result_format` | Reversible `A_flow_collect_easyexpert_result`; non-mutating result-context snapshot | `collect_easyexpert_result` sets the result format but cannot read/restore the prior parser format, so it mutates context it cannot undo. |

Non-blocking but enabling (noted, not required now): explicit
`A_atom_easyexpert_open_session` / `A_atom_easyexpert_close_session` for a true remote
socket lifecycle (today the workspace boundary substitutes), `A_atom_flex_serial_poll_status_byte`
(serial poll vs `*STB?` differ in clearing semantics), and
`A_atom_easyexpert_fetch_result_siblings` for multi-result harvest. None of these block
a P0/P1 flow above.

## Implementation Notes

**Return schema.** Every A_flow returns an audit-friendly, fake-preserving dict:

```python
{
    "flow": "A_flow_<operation>_<interface>_<subject>",
    "flow_class": "A",
    "category": "<operation>",          # discover|snapshot|drain|collect|prepare|select|teardown
    "interface": "<flex|wgfmu|easyexpert>",
    "subject": "<subject>",
    "fake": True,                        # inherited from atoms
    "hardware_touched": False,           # A_flow never touches hardware
    "ok": True,                          # all atoms succeeded
    "partial": False,                    # some atoms ran before a stop
    "destructive": False,               # clears/opens/closes/changes-context
    "consumptive": False,               # drains a queue or buffer
    "inputs": {...},
    "outputs": {...},                    # normalized top-level summary fields
    "warnings": [...],
    "atoms_called": [...],               # ordered names actually invoked
    "atom_results": [                    # raw per-atom evidence, preserved verbatim
        {"name": "...", "inputs": {...}, "result": {...}, "status": "ok", "elapsed_ms": 0}
    ],
}
```

**Sequencing.** Default to **serial** execution on one FLEX, WGFMU, or EasyEXPERT
session. The B1500A one-response query buffer and EasyEXPERT's single remote
connection make concurrent transport commands unsafe. Flows short-circuit when a
later atom depends on a failed earlier atom (e.g. `connect` fails -> skip the rest),
returning `partial=true` with all completed atom results rather than masking the
failure.

**Serial vs parallel.** Because every A_flow is single-transport, there is **no
intra-flow instrument parallelism**. Parallelism is allowed only across *independent*
sessions (an application calling `discover_flex_session`, `discover_wgfmu_session`, and
`discover_easyexpert_remote` concurrently) or for client-side parsing after atoms
return. Data-dependent loops (`drain_*`, per-channel/per-group fan-out) must be bounded
by `max_errors` / `max_groups` with a truncation flag.

**Fake semantics.** Atoms return `fake: true` / `hardware_touched: false`; flows
aggregate without claiming reality. A flow must not report `connected: true`,
must not imply DUT readiness or measurement validity, and must not describe a teardown
as safe shutdown. **Destructive/consumptive flags are honored even in fake mode** so
client code paths (e.g. the `allow_clear_buffer=true` gate, the `force_clear` gate,
the FIFO-consume warnings) are exercised before real transport exists. Read-only
flows (`snapshot_*`, non-clearing `collect`/`discover` reads) are safe to rerun;
`discover_*`, `prepare_*`, `select_*`, `drain_*`, and `teardown_*` are non-idempotent
and should check preconditions or return a clear "already in target state" result.
