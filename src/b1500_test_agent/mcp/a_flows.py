"""A-class fake MCP flow tools."""

from fastmcp import FastMCP

from .common import _atom_skip, _atom_step, _flow_response
from .a_atoms import (
    A_atom_flex_connect,
    A_atom_flex_disconnect,
    A_atom_flex_identify,
    A_atom_flex_list_modules,
    A_atom_flex_get_status,
    A_atom_flex_query_settings,
    A_atom_flex_read_error_queue,
    A_atom_flex_lookup_error,
    A_atom_flex_read_status_byte,
    A_atom_flex_wait_opc,
    A_atom_flex_set_data_format,
    A_atom_flex_configure_timestamp,
    A_atom_flex_reset_timestamp,
    A_atom_flex_read_timestamp,
    A_atom_flex_clear_output_buffer,
    A_atom_flex_query_buffer_count,
    A_atom_flex_read_output_buffer,
    A_atom_flex_configure_srq,
    A_atom_wgfmu_open_session,
    A_atom_wgfmu_close_session,
    A_atom_wgfmu_set_timeout,
    A_atom_wgfmu_get_channel_ids,
    A_atom_wgfmu_get_status,
    A_atom_wgfmu_get_channel_status,
    A_atom_wgfmu_clear,
    A_atom_wgfmu_open_log,
    A_atom_wgfmu_close_log,
    A_atom_wgfmu_read_error,
    A_atom_wgfmu_read_error_summary,
    A_atom_wgfmu_set_warning_level,
    A_atom_wgfmu_read_warning_summary,
    A_atom_wgfmu_export_ascii,
    A_atom_wgfmu_get_completed_event_count,
    A_atom_wgfmu_is_event_completed,
    A_atom_easyexpert_identify,
    A_atom_easyexpert_clear_status,
    A_atom_easyexpert_wait_opc,
    A_atom_easyexpert_read_system_error,
    A_atom_easyexpert_list_workspaces,
    A_atom_easyexpert_open_workspace,
    A_atom_easyexpert_close_workspace,
    A_atom_easyexpert_get_workspace_state,
    A_atom_easyexpert_get_workspace_name,
    A_atom_easyexpert_set_result_format,
    A_atom_easyexpert_fetch_result,
    A_atom_easyexpert_list_app_tests,
    A_atom_easyexpert_select_app_test,
    A_atom_easyexpert_list_preset_groups,
    A_atom_easyexpert_select_preset_group,
    A_atom_easyexpert_list_preset_setups,
    A_atom_easyexpert_select_preset_setup,
    A_atom_easyexpert_get_selected_name,
    A_atom_easyexpert_set_device_tag,
    A_atom_easyexpert_get_device_tag,
    A_atom_easyexpert_set_repeat_count,
    A_atom_easyexpert_get_repeat_count,
    A_atom_easyexpert_reset_repeat_count,
    A_atom_easyexpert_set_app_test_param,
    A_atom_easyexpert_set_app_test_string,
    A_atom_easyexpert_load_setup,
)


# ---------------------------------------------------------------------------
# A class — flows: ordered, reusable compositions of A_atom_* subcommands
#
# Each A_flow_* orchestrates only A_atom_* tools into a single coherent
# read/session/context operation. Flows are fake and orchestration-only: they
# call the fake A_atom Python functions in series and aggregate their returned
# data. References to B_atom_* safe-shutdown/cleanup steps appear only in
# warning text, never as calls.
# ---------------------------------------------------------------------------


def A_flow_discover_flex_session(
    gpib_address: int = 17,
    gpib_board: int = 0,
    timeout_ms: int = 600_000,
) -> dict:
    """Open the direct FLEX/VISA path and capture identity/module/status context.

    Sequence: connect -> identify -> list modules -> query settings ->
    read status byte -> read error queue (non-clearing). Opens a session
    (non-idempotent); reads errors but does not clear them.
    """
    records: list[dict] = []
    _atom_step(
        records,
        A_atom_flex_connect,
        gpib_address=gpib_address,
        gpib_board=gpib_board,
        timeout_ms=timeout_ms,
    )
    _atom_step(records, A_atom_flex_identify)
    _atom_step(records, A_atom_flex_list_modules)
    _atom_step(records, A_atom_flex_query_settings)
    _atom_step(records, A_atom_flex_read_status_byte)
    _atom_step(records, A_atom_flex_read_error_queue, clear_after_read=False)
    return _flow_response(
        "A_flow_discover_flex_session",
        "discover",
        "flex",
        "session",
        records,
        "Canonical direct-entry bundle: open the FLEX session and capture the "
        "minimum identity, module, status, and non-clearing error context.",
        destructive=True,
        inputs={
            "gpib_address": gpib_address,
            "gpib_board": gpib_board,
            "timeout_ms": timeout_ms,
        },
        warnings=[
            "Opens a direct FLEX session and is not idempotent; the error queue is read but not cleared."
        ],
    )


def A_flow_discover_wgfmu_session(
    address: str = "GPIB0::17::INSTR",
    timeout_s: float = 100.0,
) -> dict:
    """Open a WGFMU library session and capture channel IDs, status, summaries.

    Sequence: open session -> set timeout -> get channel IDs -> get status ->
    read error summary -> read warning summary. Opens a session and changes the
    timeout session state.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_wgfmu_open_session, address=address)
    _atom_step(records, A_atom_wgfmu_set_timeout, timeout_s=timeout_s)
    _atom_step(records, A_atom_wgfmu_get_channel_ids)
    _atom_step(records, A_atom_wgfmu_get_status)
    _atom_step(records, A_atom_wgfmu_read_error_summary)
    _atom_step(records, A_atom_wgfmu_read_warning_summary)
    return _flow_response(
        "A_flow_discover_wgfmu_session",
        "discover",
        "wgfmu",
        "session",
        records,
        "Standard WGFMU library entry: open the session, set timeout, discover "
        "channel IDs, and capture initial status and error/warning summaries.",
        destructive=True,
        inputs={"address": address, "timeout_s": timeout_s},
        warnings=[
            "Opens a WGFMU library session and changes timeout session state; not idempotent."
        ],
    )


def A_flow_discover_easyexpert_remote() -> dict:
    """Identify the EasyEXPERT remote endpoint and read workspace availability.

    Sequence: identify -> read system error -> list workspaces ->
    get workspace state -> get workspace name. The system-error read consumes
    one FIFO entry; status is not cleared.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_identify)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    _atom_step(records, A_atom_easyexpert_list_workspaces)
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    _atom_step(records, A_atom_easyexpert_get_workspace_name)
    return _flow_response(
        "A_flow_discover_easyexpert_remote",
        "discover",
        "easyexpert",
        "remote",
        records,
        "Minimum EasyEXPERT remote-context bundle: identify the host and read "
        "workspace availability without selecting or running anything.",
        consumptive=True,
        warnings=[
            "EasyEXPERT system-error read consumes one FIFO entry (:SYSTem:ERRor:NEXT?); status is not cleared (*CLS not issued)."
        ],
    )


def A_flow_discover_easyexpert_catalogs(
    preset_groups: str = "all",
    include_app_tests: bool = True,
    max_groups: int = 10,
) -> dict:
    """Enumerate application tests and preset setup catalogs in the workspace.

    Sequence: get workspace state -> (optional) list app tests -> list preset
    groups -> per requested group list preset setups -> read system error.
    ``preset_groups`` is "all" or a comma-separated subset; the per-group
    fan-out is bounded by ``max_groups``. Consumes one FIFO error entry.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    if include_app_tests:
        _atom_step(records, A_atom_easyexpert_list_app_tests)
    else:
        _atom_skip(records, "A_atom_easyexpert_list_app_tests", "include_app_tests=False")
    groups_result = _atom_step(records, A_atom_easyexpert_list_preset_groups)
    discovered = list(groups_result.get("preset_groups", []) or [])
    if preset_groups.strip().lower() in {"", "all"}:
        requested = discovered
    else:
        wanted = {part.strip() for part in preset_groups.split(",") if part.strip()}
        requested = [group for group in discovered if group in wanted]
    bounded = requested[: max(0, max_groups)]
    for group in bounded:
        _atom_step(records, A_atom_easyexpert_list_preset_setups, preset_group=group)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    return _flow_response(
        "A_flow_discover_easyexpert_catalogs",
        "discover",
        "easyexpert",
        "catalogs",
        records,
        "Standardize the two-level catalog fan-out: enumerate runnable "
        "application tests and preset setups distinct from selecting them.",
        consumptive=True,
        groups_requested=bounded,
        truncated=len(requested) > max(0, max_groups),
        inputs={
            "preset_groups": preset_groups,
            "include_app_tests": include_app_tests,
            "max_groups": max_groups,
        },
        warnings=[
            "Consumes one EasyEXPERT FIFO error entry; catalog reads do not change software context."
        ],
    )


def A_flow_snapshot_flex_status(include_timestamp: bool = False) -> dict:
    """Non-destructive direct B1500A health snapshot.

    Sequence: get status -> read status byte -> read error queue (non-clearing)
    -> query settings -> query buffer count -> (optional) read timestamp. Safe
    to rerun; the error read is explicitly non-clearing.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_flex_get_status)
    _atom_step(records, A_atom_flex_read_status_byte)
    _atom_step(records, A_atom_flex_read_error_queue, clear_after_read=False)
    _atom_step(records, A_atom_flex_query_settings)
    _atom_step(records, A_atom_flex_query_buffer_count)
    if include_timestamp:
        _atom_step(records, A_atom_flex_read_timestamp)
    return _flow_response(
        "A_flow_snapshot_flex_status",
        "snapshot",
        "flex",
        "status",
        records,
        "The go-to non-destructive 'what is the instrument doing?' bundle for "
        "logs, UI panels, and bug reports.",
        inputs={"include_timestamp": include_timestamp},
    )


def A_flow_snapshot_wgfmu_diagnostics() -> dict:
    """Non-destructive WGFMU overall health snapshot.

    Sequence: get status -> read error summary -> read warning summary. Uses
    accumulative summaries (not the consuming single-entry read), so it is safe
    to rerun.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_wgfmu_get_status)
    _atom_step(records, A_atom_wgfmu_read_error_summary)
    _atom_step(records, A_atom_wgfmu_read_warning_summary)
    return _flow_response(
        "A_flow_snapshot_wgfmu_diagnostics",
        "snapshot",
        "wgfmu",
        "diagnostics",
        records,
        "Standard 'is the WGFMU healthy?' check that intentionally avoids the "
        "consuming per-entry error read (that lives in drain).",
    )


def A_flow_snapshot_easyexpert_context() -> dict:
    """Read current EasyEXPERT software context without changing it.

    Sequence: get workspace state -> get workspace name -> get selected name ->
    get device tag -> get repeat count. Deliberately omits the system-error read
    to avoid consuming the FIFO.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    _atom_step(records, A_atom_easyexpert_get_workspace_name)
    _atom_step(records, A_atom_easyexpert_get_selected_name)
    _atom_step(records, A_atom_easyexpert_get_device_tag)
    _atom_step(records, A_atom_easyexpert_get_repeat_count)
    return _flow_response(
        "A_flow_snapshot_easyexpert_context",
        "snapshot",
        "easyexpert",
        "context",
        records,
        "Read-only companion to the select_* and prepare flows: capture "
        "workspace, selection, and bench metadata without consuming the error FIFO.",
    )


def A_flow_drain_flex_errors(max_errors: int = 20, lookup_messages: bool = True) -> dict:
    """Drain the direct B1500A error queue and annotate known codes.

    Sequence: read status byte -> read error queue (clearing) -> per code
    lookup error -> read status byte. Consumes/clears the error queue. ``EMG?``
    covers codes 0-999; extended codes fall back to the structured table.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_flex_read_status_byte)
    queue = _atom_step(records, A_atom_flex_read_error_queue, clear_after_read=True)
    errors = list(queue.get("errors", []) or [])
    if lookup_messages:
        for entry in errors[: max(0, max_errors)]:
            code = entry.get("code") if isinstance(entry, dict) else entry
            _atom_step(records, A_atom_flex_lookup_error, error_code=int(code))
    _atom_step(records, A_atom_flex_read_status_byte)
    return _flow_response(
        "A_flow_drain_flex_errors",
        "drain",
        "flex",
        "errors",
        records,
        "Standard read-lookup-clear recipe: drain the error queue and resolve "
        "known codes, capturing the status byte before and after.",
        consumptive=True,
        drained_count=len(errors),
        truncated=len(errors) > max(0, max_errors),
        inputs={"max_errors": max_errors, "lookup_messages": lookup_messages},
        warnings=[
            "Clears the B1500A error queue; codes above 999 need the structured error table (EMG? covers only 0-999)."
        ],
    )


def A_flow_drain_wgfmu_errors(max_errors: int = 20) -> dict:
    """Consume queued WGFMU error entries and capture surrounding summaries.

    Sequence: bounded loop of read error -> read error summary -> read warning
    summary. Consumes the per-entry WGFMU error queue.
    """
    records: list[dict] = []
    drained = 0
    truncated = False
    for index in range(max(0, max_errors)):
        result = _atom_step(records, A_atom_wgfmu_read_error)
        entries = result.get("errors", []) or []
        if not entries:
            break
        drained += len(entries)
        if index == max_errors - 1:
            truncated = True
    _atom_step(records, A_atom_wgfmu_read_error_summary)
    _atom_step(records, A_atom_wgfmu_read_warning_summary)
    return _flow_response(
        "A_flow_drain_wgfmu_errors",
        "drain",
        "wgfmu",
        "errors",
        records,
        "Make the consuming WGFMU per-entry error read explicit and distinct "
        "from the non-consuming snapshot, with bounded looping.",
        consumptive=True,
        drained_count=drained,
        truncated=truncated,
        inputs={"max_errors": max_errors},
        warnings=["Consumes per-entry WGFMU error queue entries via the size-first read API."],
    )


def A_flow_drain_easyexpert_errors(
    max_errors: int = 20,
    stop_on_no_error: bool = True,
    force_clear: bool = False,
) -> dict:
    """Drain EasyEXPERT remote system errors until no-error or a caller bound.

    Sequence: bounded loop of read system error (until code 0 / max) ->
    (optional) clear status. Consumes FIFO entries; the optional ``*CLS`` is
    gated behind explicit ``force_clear``.
    """
    records: list[dict] = []
    reads = 0
    drained = 0
    truncated = False
    for index in range(max(0, max_errors)):
        result = _atom_step(records, A_atom_easyexpert_read_system_error)
        reads += 1
        has_error = bool(result.get("code", 0))
        if has_error:
            drained += 1
        if stop_on_no_error and not has_error:
            break
        if index == max_errors - 1:
            truncated = True
    if force_clear:
        _atom_step(records, A_atom_easyexpert_clear_status)
    else:
        _atom_skip(
            records,
            "A_atom_easyexpert_clear_status",
            "force_clear=False; remote *CLS not issued",
        )
    clear_note = (
        " Issues *CLS to clear remote status."
        if force_clear
        else " *CLS skipped (force_clear=False)."
    )
    return _flow_response(
        "A_flow_drain_easyexpert_errors",
        "drain",
        "easyexpert",
        "errors",
        records,
        "Centralize bounded FIFO drain logic so clients do not hand-roll it; "
        "keep the remote *CLS explicit.",
        consumptive=True,
        destructive=force_clear,
        reads=reads,
        drained_count=drained,
        truncated=truncated,
        cleared=force_clear,
        inputs={
            "max_errors": max_errors,
            "stop_on_no_error": stop_on_no_error,
            "force_clear": force_clear,
        },
        warnings=["Consumes EasyEXPERT FIFO error entries." + clear_note],
    )


def A_flow_collect_flex_output_buffer(
    timeout_s: float = 60.0,
    max_items: int = 100,
    read_when_empty: bool = False,
) -> dict:
    """Read already-produced FLEX output-buffer data; never starts a measurement.

    Sequence: wait OPC -> query buffer count -> (conditional) read output buffer
    -> query buffer count -> read error queue (non-clearing) -> read status
    byte. Reading the output buffer drains it (consumptive).
    """
    records: list[dict] = []
    _atom_step(records, A_atom_flex_wait_opc, timeout_s=timeout_s)
    pre = _atom_step(records, A_atom_flex_query_buffer_count)
    pre_count = int(pre.get("output_buffer_items", 0) or 0)
    read_performed = False
    if pre_count > 0 or read_when_empty:
        _atom_step(records, A_atom_flex_read_output_buffer, max_items=max_items)
        read_performed = True
    else:
        _atom_skip(
            records,
            "A_atom_flex_read_output_buffer",
            "output buffer empty and read_when_empty=False",
        )
    post = _atom_step(records, A_atom_flex_query_buffer_count)
    _atom_step(records, A_atom_flex_read_error_queue, clear_after_read=False)
    _atom_step(records, A_atom_flex_read_status_byte)
    return _flow_response(
        "A_flow_collect_flex_output_buffer",
        "collect",
        "flex",
        "output_buffer",
        records,
        "Canonical count-read-count readout that prevents confusing query "
        "responses with measurement output-buffer data; never executes a measurement.",
        consumptive=read_performed,
        pre_count=pre_count,
        post_count=int(post.get("output_buffer_items", 0) or 0),
        read_performed=read_performed,
        inputs={"timeout_s": timeout_s, "max_items": max_items, "read_when_empty": read_when_empty},
        warnings=[
            "Reading the output buffer consumes it. Output-buffer data is distinct from one-response query buffers."
        ],
    )


def A_flow_collect_easyexpert_result(format_name: str = "TEXT", timeout_s: float = 60.0) -> dict:
    """Fetch the latest EasyEXPERT result block after another workflow produced it.

    Sequence: get workspace state -> wait OPC -> set result format ->
    fetch result -> read system error. Changes the result-format software
    context and consumes one FIFO error entry; does not run a test.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    _atom_step(records, A_atom_easyexpert_wait_opc, timeout_s=timeout_s)
    _atom_step(records, A_atom_easyexpert_set_result_format, format_name=format_name)
    _atom_step(records, A_atom_easyexpert_fetch_result)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    return _flow_response(
        "A_flow_collect_easyexpert_result",
        "collect",
        "easyexpert",
        "result",
        records,
        "Parser-sensitive result fetch that always carries OPC and error "
        "context; kept distinct from measurement execution (C-class).",
        destructive=True,
        consumptive=True,
        inputs={"format_name": format_name, "timeout_s": timeout_s},
        warnings=[
            "Changes EasyEXPERT result-format software context (no atom can read/restore the prior format) and consumes one FIFO error entry.",
            "Does not execute a test; only harvests an already-produced result.",
        ],
    )


def A_flow_prepare_flex_output_buffer(
    format_mode: int = 1,
    output_mode: int = 1,
    timestamp_enabled: bool = True,
    reset_timestamp: bool = False,
    allow_clear_buffer: bool = False,
    timeout_s: float = 60.0,
) -> dict:
    """Set parser-facing FLEX output-buffer state before an external measurement.

    Sequence: wait OPC -> set data format -> configure timestamp -> (optional)
    reset timestamp -> (gated) clear output buffer -> query buffer count.
    Changes FMT/timestamp session state; clearing the buffer destroys unread
    data and requires explicit ``allow_clear_buffer=True``.
    """
    records: list[dict] = []
    warnings: list[str] = ["Changes FMT/timestamp session state for the FLEX session."]
    partial = False
    _atom_step(records, A_atom_flex_wait_opc, timeout_s=timeout_s)
    _atom_step(
        records,
        A_atom_flex_set_data_format,
        format_mode=format_mode,
        output_mode=output_mode,
    )
    _atom_step(records, A_atom_flex_configure_timestamp, enabled=timestamp_enabled)
    if reset_timestamp:
        _atom_step(records, A_atom_flex_reset_timestamp)
    if allow_clear_buffer:
        _atom_step(records, A_atom_flex_clear_output_buffer)
        warnings.append("Cleared the output buffer (allow_clear_buffer=True): unread data is destroyed.")
    else:
        _atom_skip(
            records,
            "A_atom_flex_clear_output_buffer",
            "allow_clear_buffer=False gate not satisfied",
        )
        warnings.append(
            "Output-buffer clear skipped: set allow_clear_buffer=True to clear it (destroys unread data)."
        )
        partial = True
    _atom_step(records, A_atom_flex_query_buffer_count)
    return _flow_response(
        "A_flow_prepare_flex_output_buffer",
        "prepare",
        "flex",
        "output_buffer",
        records,
        "Define the parser contract (format + timestamp + buffer state) that "
        "collect_flex_output_buffer later depends on, in one auditable place.",
        destructive=True,
        partial=partial,
        buffer_cleared=allow_clear_buffer,
        inputs={
            "format_mode": format_mode,
            "output_mode": output_mode,
            "timestamp_enabled": timestamp_enabled,
            "reset_timestamp": reset_timestamp,
            "allow_clear_buffer": allow_clear_buffer,
            "timeout_s": timeout_s,
        },
        warnings=warnings,
    )


def A_flow_prepare_wgfmu_logging(
    timeout_s: float = 100.0,
    file_name: str = "wgfmu.log",
    warning_level: str = "NORMAL",
) -> dict:
    """Configure WGFMU logging and warning policy for long-running jobs.

    Sequence: set timeout -> open log -> set warning level -> read error summary
    -> read warning summary. Opens a log file and changes the WGFMU
    warning-policy session state (not DUT state). Assumes the session is open.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_wgfmu_set_timeout, timeout_s=timeout_s)
    _atom_step(records, A_atom_wgfmu_open_log, file_name=file_name)
    _atom_step(records, A_atom_wgfmu_set_warning_level, level=warning_level)
    _atom_step(records, A_atom_wgfmu_read_error_summary)
    _atom_step(records, A_atom_wgfmu_read_warning_summary)
    return _flow_response(
        "A_flow_prepare_wgfmu_logging",
        "prepare",
        "wgfmu",
        "logging",
        records,
        "Give long WGFMU jobs explicit, auditable logging and warning-policy "
        "setup; compose after discover_wgfmu_session.",
        destructive=True,
        inputs={"timeout_s": timeout_s, "file_name": file_name, "warning_level": warning_level},
        warnings=[
            "Opens a WGFMU log file and changes warning-level session state; no atom can read the prior warning level for rollback."
        ],
    )


def A_flow_select_easyexpert_workspace(workspace: str = "default", timeout_s: float = 60.0) -> dict:
    """Open/select an EasyEXPERT workspace and verify it is ready.

    Sequence: list workspaces -> open workspace -> wait OPC -> get workspace
    state -> get workspace name -> read system error. Changes software context
    and consumes one FIFO error entry.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_list_workspaces)
    _atom_step(records, A_atom_easyexpert_open_workspace, workspace=workspace)
    _atom_step(records, A_atom_easyexpert_wait_opc, timeout_s=timeout_s)
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    name = _atom_step(records, A_atom_easyexpert_get_workspace_name)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    return _flow_response(
        "A_flow_select_easyexpert_workspace",
        "select",
        "easyexpert",
        "workspace",
        records,
        "Mandatory gateway for EasyEXPERT work: open -> wait -> verify handshake "
        "that should not be hidden inside discovery or collection.",
        destructive=True,
        consumptive=True,
        workspace_name=name.get("name"),
        inputs={"workspace": workspace, "timeout_s": timeout_s},
        warnings=[
            "Changes EasyEXPERT software context (opens a workspace) and consumes one FIFO error entry."
        ],
    )


def A_flow_select_easyexpert_app_test(test_name: str) -> dict:
    """Select an EasyEXPERT application-test definition as software context.

    Sequence: get workspace state -> list app tests -> select app test ->
    get selected name -> read system error. Changes software context and
    consumes one FIFO error entry; no measurement is executed.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    _atom_step(records, A_atom_easyexpert_list_app_tests)
    _atom_step(records, A_atom_easyexpert_select_app_test, test_name=test_name)
    selected = _atom_step(records, A_atom_easyexpert_get_selected_name)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    return _flow_response(
        "A_flow_select_easyexpert_app_test",
        "select",
        "easyexpert",
        "app_test",
        records,
        "Select an application-test definition and verify the selection; "
        "execution remains C-class.",
        destructive=True,
        consumptive=True,
        selected_name=selected.get("selected_name"),
        inputs={"test_name": test_name},
        warnings=[
            "Changes EasyEXPERT software context (selected app test) and consumes one FIFO error entry; does not run the test."
        ],
    )


def A_flow_select_easyexpert_preset_setup(
    preset_group: str = "My Favorite",
    setup_name: str = "",
) -> dict:
    """Select an EasyEXPERT preset setup (group then setup) as software context.

    Sequence: get workspace state -> list preset groups -> select preset group
    -> list preset setups -> select preset setup -> get selected name ->
    read system error. Changes software context and consumes one FIFO error
    entry; no measurement is executed.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_easyexpert_get_workspace_state)
    _atom_step(records, A_atom_easyexpert_list_preset_groups)
    _atom_step(records, A_atom_easyexpert_select_preset_group, preset_group=preset_group)
    _atom_step(records, A_atom_easyexpert_list_preset_setups, preset_group=preset_group)
    _atom_step(records, A_atom_easyexpert_select_preset_setup, setup_name=setup_name)
    selected = _atom_step(records, A_atom_easyexpert_get_selected_name)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    return _flow_response(
        "A_flow_select_easyexpert_preset_setup",
        "select",
        "easyexpert",
        "preset_setup",
        records,
        "Two-level preset selection (:PRESet:OPEN then :SETup:SELect) kept as a "
        "fixed, legible sequence separate from app-test select.",
        destructive=True,
        consumptive=True,
        selected_name=selected.get("selected_name"),
        inputs={"preset_group": preset_group, "setup_name": setup_name},
        warnings=[
            "Changes EasyEXPERT software context (opens a preset group and selects a setup) and consumes one FIFO error entry; does not run the setup."
        ],
    )


def A_flow_teardown_flex_session(read_remaining_output: bool = False, max_items: int = 100) -> dict:
    """Record final direct-session context, then close the FLEX transport.

    Sequence: query buffer count -> (optional) read output buffer -> read status
    byte -> read error queue (non-clearing) -> query settings -> disconnect.
    Closes the session; this is NOT a safe shutdown.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_flex_query_buffer_count)
    consumed = False
    if read_remaining_output:
        _atom_step(records, A_atom_flex_read_output_buffer, max_items=max_items)
        consumed = True
    else:
        _atom_skip(records, "A_atom_flex_read_output_buffer", "read_remaining_output=False")
    _atom_step(records, A_atom_flex_read_status_byte)
    _atom_step(records, A_atom_flex_read_error_queue, clear_after_read=False)
    _atom_step(records, A_atom_flex_query_settings)
    _atom_step(records, A_atom_flex_disconnect)
    return _flow_response(
        "A_flow_teardown_flex_session",
        "teardown",
        "flex",
        "session",
        records,
        "Capture context-before-close for logging, then disconnect; the safety "
        "cleanup must stay outside A and run first.",
        destructive=True,
        consumptive=consumed,
        inputs={"read_remaining_output": read_remaining_output, "max_items": max_items},
        warnings=[
            "Closes the direct FLEX session. NOT a safe shutdown: run a B-class safe-state flow (e.g. B_atom_output_b1500_zero_all) before teardown on real hardware."
        ],
    )


def A_flow_teardown_wgfmu_session(
    export_setup: bool = False,
    file_name: str = "wgfmu_setup.csv",
    close_log: bool = True,
) -> dict:
    """Capture final WGFMU diagnostics, optionally export setup, close log/session.

    Sequence: get status -> read error summary -> read warning summary ->
    (optional) export ASCII -> (optional) close log -> close session. Closes the
    log/session; this is NOT WGFMU hardware cleanup.
    """
    records: list[dict] = []
    _atom_step(records, A_atom_wgfmu_get_status)
    _atom_step(records, A_atom_wgfmu_read_error_summary)
    _atom_step(records, A_atom_wgfmu_read_warning_summary)
    if export_setup:
        _atom_step(records, A_atom_wgfmu_export_ascii, file_name=file_name)
    else:
        _atom_skip(records, "A_atom_wgfmu_export_ascii", "export_setup=False")
    if close_log:
        _atom_step(records, A_atom_wgfmu_close_log)
    else:
        _atom_skip(records, "A_atom_wgfmu_close_log", "close_log=False")
    _atom_step(records, A_atom_wgfmu_close_session)
    return _flow_response(
        "A_flow_teardown_wgfmu_session",
        "teardown",
        "wgfmu",
        "session",
        records,
        "Standardize WGFMU close order: diagnostics are lost after closeSession "
        "and the log must close before the session.",
        destructive=True,
        inputs={"export_setup": export_setup, "file_name": file_name, "close_log": close_log},
        warnings=[
            "Closes the WGFMU log/session. Does not initialize or zero WGFMU channels (that is B-class)."
        ],
    )


def A_flow_teardown_easyexpert_workspace(timeout_s: float = 60.0, ignore_no_workspace: bool = True) -> dict:
    """Capture context, close the active EasyEXPERT workspace, and verify the close.

    Sequence: get workspace state -> get workspace name -> close workspace ->
    wait OPC -> read system error. Closes software context and consumes one FIFO
    error entry; no hardware cleanup is implied.
    """
    records: list[dict] = []
    warnings: list[str] = []
    state = _atom_step(records, A_atom_easyexpert_get_workspace_state)
    _atom_step(records, A_atom_easyexpert_get_workspace_name)
    no_workspace = "no_workspace" in str(state.get("state", "")).lower()
    closed = False
    partial = False
    if no_workspace and ignore_no_workspace:
        _atom_skip(
            records,
            "A_atom_easyexpert_close_workspace",
            "no active workspace and ignore_no_workspace=True",
        )
        warnings.append("No active EasyEXPERT workspace to close (ignore_no_workspace=True).")
        partial = True
    else:
        _atom_step(records, A_atom_easyexpert_close_workspace)
        closed = True
    _atom_step(records, A_atom_easyexpert_wait_opc, timeout_s=timeout_s)
    _atom_step(records, A_atom_easyexpert_read_system_error)
    warnings.append(
        "Closes the EasyEXPERT workspace software context and consumes one FIFO error entry; not a hardware-safe shutdown."
    )
    return _flow_response(
        "A_flow_teardown_easyexpert_workspace",
        "teardown",
        "easyexpert",
        "workspace",
        records,
        "Symmetric to select_easyexpert_workspace: close -> wait -> verify, never "
        "to be confused with safe hardware shutdown.",
        destructive=closed,
        consumptive=True,
        partial=partial,
        closed=closed,
        inputs={"timeout_s": timeout_s, "ignore_no_workspace": ignore_no_workspace},
        warnings=warnings,
    )


A_FLOW_FUNCTIONS = [
    A_flow_discover_flex_session,
    A_flow_discover_wgfmu_session,
    A_flow_discover_easyexpert_remote,
    A_flow_discover_easyexpert_catalogs,
    A_flow_snapshot_flex_status,
    A_flow_snapshot_wgfmu_diagnostics,
    A_flow_snapshot_easyexpert_context,
    A_flow_drain_flex_errors,
    A_flow_drain_wgfmu_errors,
    A_flow_drain_easyexpert_errors,
    A_flow_collect_flex_output_buffer,
    A_flow_collect_easyexpert_result,
    A_flow_prepare_flex_output_buffer,
    A_flow_prepare_wgfmu_logging,
    A_flow_select_easyexpert_workspace,
    A_flow_select_easyexpert_app_test,
    A_flow_select_easyexpert_preset_setup,
    A_flow_teardown_flex_session,
    A_flow_teardown_wgfmu_session,
    A_flow_teardown_easyexpert_workspace,
]


def register_a_flows(mcp: FastMCP) -> None:
    """Register all A_flow_* tools on a FastMCP instance."""
    for tool in A_FLOW_FUNCTIONS:
        mcp.tool(tool)
