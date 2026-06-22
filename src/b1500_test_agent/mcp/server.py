"""FastMCP server entry point.

This server is intentionally fake-but-loadable. It exposes a stable atom-tool
surface for Cursor/Codex discovery while the real B1500A driver and safety
layer are developed. Every tool returns `fake: true` and must not be treated as
hardware control.

Naming convention:
  A_atom_<interface>_<action>    — read/discover/connect/session/context atoms
  B_atom_<risk_category>_<target>_<action> — safety/state-control atoms

A interfaces: flex (direct GPIB/VISA), wgfmu (B1530A library), easyexpert (remote)
B categories: safety, output, lifecycle, diagnostic, calibration, routing,
              correction, policy
B targets: b1500, smu, asu, scuu, cmu, qscv, wgfmu, easyexpert
"""

from fastmcp import FastMCP

mcp = FastMCP(
    name="b1500-test-agent",
    version="0.2.0",
    instructions=(
        "Fake-but-loadable B1500A MCP server for client discovery. "
        "A_atom tools are connection/communication/status atoms. "
        "B_atom tools are safety/state-control atoms. "
        "A second token: flex | wgfmu | easyexpert (interface). "
        "B second token: safety | output | lifecycle | diagnostic | "
        "calibration | routing | correction | policy (risk/operation). "
        "All tools return synthetic data and must not be treated as hardware control."
    ),
)

_FAKE_MODULES = [
    {"slot": 1, "type": "MPSMU", "channels": [1], "priority": "P0"},
    {"slot": 2, "type": "HRSMU", "channels": [2], "priority": "P0"},
    {"slot": 5, "type": "WGFMU", "channels": [5, 15], "priority": "P1"},
    {"slot": 6, "type": "HVSPGU", "channels": [6, 16], "priority": "P1"},
    {"slot": 7, "type": "MFCMU", "channels": [7], "priority": "P2"},
]

_EASYEXPERT_APPS = [
    "Id-Vg",
    "Id-Vd",
    "Vth gmMax",
    "C-V Sweep",
    "QSCV",
    "NandFlash IV-Write-IV",
]


def _fake_response(atom: str, flex_basis: list[str], **payload: object) -> dict:
    """Build a standard fake MCP response."""
    return {
        "atom": atom,
        "fake": True,
        "hardware_touched": False,
        "basis": flex_basis,
        **payload,
    }


def _parse_channels(channels: str) -> list[int]:
    """Parse a comma-separated channel list for fake channel-control tools."""
    if not channels.strip():
        return []
    return [int(part.strip()) for part in channels.split(",") if part.strip()]


def _atom_names(prefix: str) -> list[str]:
    """Return atom function names in definition order."""
    return [
        name
        for name, value in globals().items()
        if name.startswith(prefix) and callable(value)
    ]


# ---------------------------------------------------------------------------
# A class — flex: connection, communication, status, buffer atoms
# ---------------------------------------------------------------------------


@mcp.tool
def A_atom_flex_connect(
    gpib_address: int = 17,
    gpib_board: int = 0,
    timeout_ms: int = 600_000,
) -> dict:
    """Open a fake direct B1500A GPIB session and discover identity/modules.

    Basis: B1500A Programming Guide `*IDN?`, `UNT?`; PyVISA/GPIB setup.
    """
    return _fake_response(
        "A_atom_flex_connect",
        ["*IDN?", "UNT?"],
        connected=False,
        gpib_board=gpib_board,
        gpib_address=gpib_address,
        timeout_ms=timeout_ms,
        instrument_id="Keysight Technologies,B1500A,FAKE,0.0",
        modules=_FAKE_MODULES,
        warning="Fake connection only; real PyVISA transport is not implemented.",
    )


@mcp.tool
def A_atom_flex_disconnect() -> dict:
    """Close a fake direct B1500A session.

    Basis: direct session lifecycle. Real implementation should call B-class
    cleanup before closing transport.
    """
    return _fake_response(
        "A_atom_flex_disconnect",
        ["session.close"],
        connected=False,
        status="fake_disconnected",
        cleanup_note="Call B_atom_output_b1500_zero_all before real disconnect.",
    )


@mcp.tool
def A_atom_flex_identify() -> dict:
    """Return fake B1500A identity.

    Basis: B1500A Programming Guide `*IDN?`.
    """
    return _fake_response(
        "A_atom_flex_identify",
        ["*IDN?"],
        instrument_id="Keysight Technologies,B1500A,FAKE,0.0",
    )


@mcp.tool
def A_atom_flex_list_modules() -> dict:
    """Return fake installed B1500A module inventory.

    Basis: B1500A Programming Guide `UNT?`.
    """
    return _fake_response(
        "A_atom_flex_list_modules",
        ["UNT?"],
        modules=_FAKE_MODULES,
        channel_numbering="1-10 primary slot channels; 11-20 secondary channels.",
    )


@mcp.tool
def A_atom_flex_get_status() -> dict:
    """Return fake B1500A status, errors, module inventory, and settings summary.

    Basis: `UNT?`, `ERRX?`, `*STB?`, `*LRN?`.
    """
    return _fake_response(
        "A_atom_flex_get_status",
        ["UNT?", "ERRX?", "*STB?", "*LRN?"],
        connected=False,
        state="fake_offline",
        modules=_FAKE_MODULES,
        error_queue=[],
        status_byte=0,
        active_channels=[],
        current_settings={"format": "FMT 1,1", "timestamp": "disabled"},
    )


@mcp.tool
def A_atom_flex_query_settings() -> dict:
    """Return fake current B1500A settings.

    Basis: B1500A Programming Guide `*LRN?`.
    """
    return _fake_response(
        "A_atom_flex_query_settings",
        ["*LRN?"],
        settings={
            "format": "FMT 1,1",
            "timestamp": "disabled",
            "auto_calibration": "enabled",
            "active_channels": [],
        },
    )


@mcp.tool
def A_atom_flex_read_error_queue(clear_after_read: bool = False) -> dict:
    """Read fake B1500A error queue.

    Basis: B1500A Programming Guide `ERR?`, `ERRX?`.
    """
    return _fake_response(
        "A_atom_flex_read_error_queue",
        ["ERR?", "ERRX?"],
        clear_after_read=clear_after_read,
        errors=[],
        message="No fake errors queued.",
    )


@mcp.tool
def A_atom_flex_lookup_error(error_code: int = 0) -> dict:
    """Return fake message text for a B1500A error code.

    Basis: B1500A Programming Guide `EMG? code`.
    """
    return _fake_response(
        "A_atom_flex_lookup_error",
        ["EMG?"],
        error_code=error_code,
        message="No error" if error_code == 0 else "Fake lookup; consult structured error table.",
        coverage="EMG? supports 0-999; use ERRX? for extended errors.",
    )


@mcp.tool
def A_atom_flex_read_status_byte() -> dict:
    """Return fake B1500A status byte decode.

    Basis: status byte section and `*STB?`.
    """
    return _fake_response(
        "A_atom_flex_read_status_byte",
        ["*STB?"],
        status_byte=0,
        decoded={
            "data_ready_bit0": False,
            "wait_bit1": False,
            "interlock_open_bit3": False,
            "message_available": False,
            "operation_complete": True,
        },
    )


@mcp.tool
def A_atom_flex_wait_opc(timeout_s: float = 60.0) -> dict:
    """Pretend to wait for current operation completion.

    Basis: `*OPC?`; EasyEXPERT remote also uses `*OPC?` after long operations.
    """
    return _fake_response(
        "A_atom_flex_wait_opc",
        ["*OPC?"],
        timeout_s=timeout_s,
        complete=True,
    )


@mcp.tool
def A_atom_flex_set_data_format(format_mode: int = 1, output_mode: int = 1) -> dict:
    """Pretend to set B1500A measurement data output format.

    Basis: B1500A Programming Guide `FMT mode[, output]`.
    """
    return _fake_response(
        "A_atom_flex_set_data_format",
        ["FMT"],
        format_mode=format_mode,
        output_mode=output_mode,
        recommended_for_initial_driver=format_mode in {1, 5, 11, 15, 21, 25},
        parser_note="Prefer ASCII formats with status headers until binary parsers are validated.",
    )


@mcp.tool
def A_atom_flex_configure_timestamp(enabled: bool = True) -> dict:
    """Pretend to enable or disable B1500A timestamp output.

    Basis: B1500A Programming Guide `TSC mode`.
    """
    return _fake_response("A_atom_flex_configure_timestamp", ["TSC"], enabled=enabled)


@mcp.tool
def A_atom_flex_reset_timestamp() -> dict:
    """Pretend to reset the B1500A timestamp timer.

    Basis: B1500A Programming Guide `TSR`.
    """
    return _fake_response("A_atom_flex_reset_timestamp", ["TSR"], timestamp_s=0.0)


@mcp.tool
def A_atom_flex_read_timestamp() -> dict:
    """Return a fake B1500A timestamp value.

    Basis: B1500A Programming Guide `TSQ`.
    """
    return _fake_response("A_atom_flex_read_timestamp", ["TSQ"], timestamp_s=0.0)


@mcp.tool
def A_atom_flex_clear_output_buffer() -> dict:
    """Pretend to clear the B1500A output data buffer.

    Basis: B1500A Programming Guide `BC`.
    """
    return _fake_response(
        "A_atom_flex_clear_output_buffer",
        ["BC"],
        output_buffer_items=0,
        note="This is the measurement output buffer, not the one-response query buffer.",
    )


@mcp.tool
def A_atom_flex_query_buffer_count() -> dict:
    """Return fake count of data items in the B1500A output data buffer.

    Basis: B1500A Programming Guide `NUB?`.
    """
    return _fake_response(
        "A_atom_flex_query_buffer_count",
        ["NUB?"],
        output_buffer_items=0,
    )


@mcp.tool
def A_atom_flex_read_output_buffer(max_items: int = 100) -> dict:
    """Return fake measurement output-buffer data.

    Basis: B1500A output data buffer read after `XE` or high-speed spot commands.
    """
    return _fake_response(
        "A_atom_flex_read_output_buffer",
        ["output data buffer read"],
        max_items=max_items,
        items=[],
        parser_note="Real implementation must parse according to FMT mode and status headers.",
    )


@mcp.tool
def A_atom_flex_configure_srq(enable_mask: int = 0) -> dict:
    """Pretend to configure B1500A service request/status-byte interrupt mask.

    Basis: B1500A Programming Guide `*SRE`.
    """
    return _fake_response(
        "A_atom_flex_configure_srq",
        ["*SRE"],
        enable_mask=enable_mask,
        note="Status byte bit definitions must follow the audited structured table.",
    )


# ---------------------------------------------------------------------------
# A class — wgfmu: session, status, error/warning, logging atoms
# ---------------------------------------------------------------------------


@mcp.tool
def A_atom_wgfmu_open_session(address: str = "GPIB0::17::INSTR") -> dict:
    """Pretend to open a WGFMU instrument-library session.

    Basis: B1530A WGFMU `WGFMU_openSession`.
    """
    return _fake_response(
        "A_atom_wgfmu_open_session",
        ["WGFMU_openSession"],
        address=address,
        connected=False,
    )


@mcp.tool
def A_atom_wgfmu_close_session() -> dict:
    """Pretend to close a WGFMU instrument-library session.

    Basis: B1530A WGFMU `WGFMU_closeSession`.
    """
    return _fake_response("A_atom_wgfmu_close_session", ["WGFMU_closeSession"], connected=False)


@mcp.tool
def A_atom_wgfmu_set_timeout(timeout_s: float = 100.0) -> dict:
    """Pretend to set WGFMU session timeout.

    Basis: B1530A WGFMU `WGFMU_setTimeout`.
    """
    return _fake_response("A_atom_wgfmu_set_timeout", ["WGFMU_setTimeout"], timeout_s=timeout_s)


@mcp.tool
def A_atom_wgfmu_get_channel_ids() -> dict:
    """Return fake WGFMU channel IDs.

    Basis: B1530A WGFMU `WGFMU_getChannelIdSize` / `WGFMU_getChannelIds`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_channel_ids",
        ["WGFMU_getChannelIdSize", "WGFMU_getChannelIds"],
        channel_ids=[501, 502],
        note="WGFMU channel ID convention is slot*100 + channel.",
    )


@mcp.tool
def A_atom_wgfmu_get_status() -> dict:
    """Return fake overall WGFMU execution status.

    Basis: B1530A WGFMU `WGFMU_getStatus`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_status",
        ["WGFMU_getStatus"],
        status="IDLE",
        note="Overall WGFMU execution status; does not alter waveform or output state.",
    )


@mcp.tool
def A_atom_wgfmu_get_channel_status(channel_id: int = 501) -> dict:
    """Return fake per-channel WGFMU execution status.

    Basis: B1530A WGFMU `WGFMU_getChannelStatus`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_channel_status",
        ["WGFMU_getChannelStatus"],
        channel_id=channel_id,
        status="IDLE",
        elapsed_time_s=0.0,
        total_time_s=0.0,
    )


@mcp.tool
def A_atom_wgfmu_clear() -> dict:
    """Pretend to clear WGFMU software setup.

    Basis: B1530A WGFMU `WGFMU_clear`.
    """
    return _fake_response("A_atom_wgfmu_clear", ["WGFMU_clear"], status="fake_cleared")


@mcp.tool
def A_atom_wgfmu_open_log(file_name: str = "wgfmu.log") -> dict:
    """Pretend to open a WGFMU error/warning log file.

    Basis: B1530A WGFMU `WGFMU_openLogFile`.
    """
    return _fake_response("A_atom_wgfmu_open_log", ["WGFMU_openLogFile"], file_name=file_name)


@mcp.tool
def A_atom_wgfmu_close_log() -> dict:
    """Pretend to close the WGFMU log file.

    Basis: B1530A WGFMU `WGFMU_closeLogFile`.
    """
    return _fake_response("A_atom_wgfmu_close_log", ["WGFMU_closeLogFile"], closed=True)


@mcp.tool
def A_atom_wgfmu_read_error() -> dict:
    """Read fake WGFMU error queue entry.

    Basis: B1530A WGFMU `WGFMU_getErrorSize` / `WGFMU_getError`.
    """
    return _fake_response(
        "A_atom_wgfmu_read_error",
        ["WGFMU_getErrorSize", "WGFMU_getError"],
        errors=[],
    )


@mcp.tool
def A_atom_wgfmu_read_error_summary() -> dict:
    """Read fake WGFMU accumulated error summary.

    Basis: B1530A WGFMU `WGFMU_getErrorSummarySize` / `WGFMU_getErrorSummary`.
    """
    return _fake_response(
        "A_atom_wgfmu_read_error_summary",
        ["WGFMU_getErrorSummarySize", "WGFMU_getErrorSummary"],
        summary="",
    )


@mcp.tool
def A_atom_wgfmu_set_warning_level(level: str = "NORMAL") -> dict:
    """Pretend to set WGFMU warning level.

    Basis: B1530A WGFMU `WGFMU_setWarningLevel`.
    """
    return _fake_response("A_atom_wgfmu_set_warning_level", ["WGFMU_setWarningLevel"], level=level)


@mcp.tool
def A_atom_wgfmu_read_warning_summary() -> dict:
    """Read fake WGFMU accumulated warning summary.

    Basis: B1530A WGFMU `WGFMU_getWarningSummarySize` / `WGFMU_getWarningSummary`.
    """
    return _fake_response(
        "A_atom_wgfmu_read_warning_summary",
        ["WGFMU_getWarningSummarySize", "WGFMU_getWarningSummary"],
        summary="",
    )


@mcp.tool
def A_atom_wgfmu_export_ascii(file_name: str = "wgfmu_setup.csv") -> dict:
    """Pretend to export WGFMU setup summary to CSV for offline verification.

    Basis: B1530A WGFMU `WGFMU_exportAscii`.
    """
    return _fake_response(
        "A_atom_wgfmu_export_ascii",
        ["WGFMU_exportAscii"],
        file_name=file_name,
        note="Exports pattern, event, and sequence setup data to CSV. Essential for debugging.",
    )


@mcp.tool
def A_atom_wgfmu_get_completed_event_count(channel_id: int = 501) -> dict:
    """Return fake count of completed measurement events on a WGFMU channel.

    Basis: B1530A WGFMU `WGFMU_getCompletedMeasureEventSize`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_completed_event_count",
        ["WGFMU_getCompletedMeasureEventSize"],
        channel_id=channel_id,
        completed=0,
        total=0,
        note="Progress monitoring for long stress/measurement sequences.",
    )


@mcp.tool
def A_atom_wgfmu_is_event_completed(
    channel_id: int = 501, pattern: str = "", event: str = ""
) -> dict:
    """Check fake WGFMU measurement event completion status.

    Basis: B1530A WGFMU `WGFMU_isMeasureEventCompleted`.
    """
    return _fake_response(
        "A_atom_wgfmu_is_event_completed",
        ["WGFMU_isMeasureEventCompleted"],
        channel_id=channel_id,
        pattern=pattern,
        event=event,
        completed=False,
        data_index=0,
        data_size=0,
    )


# ---------------------------------------------------------------------------
# A class — easyexpert: remote session, workspace, catalog, result atoms
# ---------------------------------------------------------------------------


@mcp.tool
def A_atom_easyexpert_identify() -> dict:
    """Return fake EasyEXPERT remote host identity.

    Basis: EasyEXPERT remote common `*IDN?`.
    """
    return _fake_response(
        "A_atom_easyexpert_identify",
        ["EasyEXPERT *IDN?"],
        host="EasyEXPERT-FAKE",
    )


@mcp.tool
def A_atom_easyexpert_clear_status() -> dict:
    """Pretend to clear EasyEXPERT remote status/error state.

    Basis: EasyEXPERT remote common `*CLS`.
    """
    return _fake_response("A_atom_easyexpert_clear_status", ["EasyEXPERT *CLS"], cleared=True)


@mcp.tool
def A_atom_easyexpert_wait_opc(timeout_s: float = 60.0) -> dict:
    """Pretend to wait for EasyEXPERT remote operation completion.

    Basis: EasyEXPERT remote common `*OPC?`.
    """
    return _fake_response(
        "A_atom_easyexpert_wait_opc",
        ["EasyEXPERT *OPC?"],
        timeout_s=timeout_s,
        complete=True,
    )


@mcp.tool
def A_atom_easyexpert_read_system_error() -> dict:
    """Read fake EasyEXPERT remote error queue.

    Basis: EasyEXPERT `:SYSTem:ERRor:NEXT?`.
    """
    return _fake_response(
        "A_atom_easyexpert_read_system_error",
        [":SYSTem:ERRor:NEXT?"],
        code=0,
        message="No error",
    )


@mcp.tool
def A_atom_easyexpert_list_workspaces() -> dict:
    """Return fake EasyEXPERT workspace catalog.

    Basis: EasyEXPERT `:WORKspace:CATalog?`.
    """
    return _fake_response(
        "A_atom_easyexpert_list_workspaces",
        [":WORKspace:CATalog?"],
        workspaces=["default"],
    )


@mcp.tool
def A_atom_easyexpert_open_workspace(workspace: str = "default") -> dict:
    """Pretend to open an EasyEXPERT workspace.

    Basis: EasyEXPERT `:WORKspace:OPEN`.
    """
    return _fake_response(
        "A_atom_easyexpert_open_workspace",
        [":WORKspace:OPEN"],
        workspace=workspace,
        opened=False,
    )


@mcp.tool
def A_atom_easyexpert_close_workspace() -> dict:
    """Pretend to close the active EasyEXPERT workspace.

    Basis: EasyEXPERT `:WORKspace:CLOSe`.
    """
    return _fake_response("A_atom_easyexpert_close_workspace", [":WORKspace:CLOSe"], closed=True)


@mcp.tool
def A_atom_easyexpert_get_workspace_state() -> dict:
    """Return fake EasyEXPERT workspace state.

    Basis: EasyEXPERT `:WORKspace:STATe?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_workspace_state",
        [":WORKspace:STATe?"],
        state="fake_no_workspace",
    )


@mcp.tool
def A_atom_easyexpert_get_workspace_name() -> dict:
    """Return fake EasyEXPERT active workspace name.

    Basis: EasyEXPERT `:WORKspace:NAME?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_workspace_name",
        [":WORKspace:NAME?"],
        name=None,
    )


@mcp.tool
def A_atom_easyexpert_set_result_format(format_name: str = "TEXT") -> dict:
    """Pretend to set EasyEXPERT remote result format.

    Basis: EasyEXPERT `:RESult:FORMat TEXT|XTR`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_result_format",
        [":RESult:FORMat"],
        format=format_name,
        supported=["TEXT", "XTR"],
    )


@mcp.tool
def A_atom_easyexpert_fetch_result() -> dict:
    """Return fake latest EasyEXPERT remote result block.

    Basis: EasyEXPERT `:RESult:FETch[:LATest]?`.
    """
    return _fake_response(
        "A_atom_easyexpert_fetch_result",
        [":RESult:FETch[:LATest]?"],
        result=None,
        parser_note="Real implementation must parse SCPI definite-length block data.",
    )


@mcp.tool
def A_atom_easyexpert_list_app_tests() -> dict:
    """Return fake EasyEXPERT application-test catalog.

    Basis: EasyEXPERT `:BENCh:APPlication:CATalog?` and Table 9-1.
    """
    return _fake_response(
        "A_atom_easyexpert_list_app_tests",
        [":BENCh:APPlication:CATalog?"],
        application_tests=_EASYEXPERT_APPS,
    )


@mcp.tool
def A_atom_easyexpert_select_app_test(test_name: str) -> dict:
    """Pretend to select an EasyEXPERT application-test definition.

    Basis: EasyEXPERT `[:BENCh]:APPlication:SELect "name"`.
    """
    return _fake_response(
        "A_atom_easyexpert_select_app_test",
        [":BENCh:APPlication:SELect"],
        test_name=test_name,
        selected=True,
        note="Software-context selection only; does not execute the test.",
    )


@mcp.tool
def A_atom_easyexpert_list_preset_groups() -> dict:
    """Return fake EasyEXPERT preset-group catalog.

    Basis: EasyEXPERT `:BENCh:PRESet:CATalog?`.
    """
    return _fake_response(
        "A_atom_easyexpert_list_preset_groups",
        [":BENCh:PRESet:CATalog?"],
        preset_groups=["My Favorite"],
    )


@mcp.tool
def A_atom_easyexpert_select_preset_group(preset_group: str = "My Favorite") -> dict:
    """Pretend to open/select an EasyEXPERT preset group.

    Basis: EasyEXPERT `[:BENCh]:PRESet:OPEN "name"`.
    """
    return _fake_response(
        "A_atom_easyexpert_select_preset_group",
        [":BENCh:PRESet:OPEN"],
        preset_group=preset_group,
        selected=True,
    )


@mcp.tool
def A_atom_easyexpert_list_preset_setups(preset_group: str = "My Favorite") -> dict:
    """Return fake EasyEXPERT setup catalog for a preset group.

    Basis: EasyEXPERT `:BENCh:PRESet:SETup:CATalog?`.
    """
    return _fake_response(
        "A_atom_easyexpert_list_preset_setups",
        [":BENCh:PRESet:SETup:CATalog?"],
        preset_group=preset_group,
        setups=[],
    )


@mcp.tool
def A_atom_easyexpert_select_preset_setup(setup_name: str) -> dict:
    """Pretend to select an EasyEXPERT preset setup.

    Basis: EasyEXPERT `[:BENCh]:PRESet:SETup:SELect "name"`.
    """
    return _fake_response(
        "A_atom_easyexpert_select_preset_setup",
        [":BENCh:PRESet:SETup:SELect"],
        setup_name=setup_name,
        selected=True,
        note="Software-context selection only; does not execute the setup.",
    )


@mcp.tool
def A_atom_easyexpert_get_selected_name() -> dict:
    """Return fake EasyEXPERT selected setup/test name.

    Basis: EasyEXPERT `[:BENCh][:SELected]:NAME?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_selected_name",
        [":BENCh:SELected:NAME?"],
        selected_name=None,
    )


@mcp.tool
def A_atom_easyexpert_set_device_tag(device_id: str = "") -> dict:
    """Pretend to set the EasyEXPERT Device ID tag for sample metadata.

    Basis: EasyEXPERT `[:BENCh]:TAG "deviceid"`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_device_tag",
        [":BENCh:TAG"],
        device_id=device_id,
    )


@mcp.tool
def A_atom_easyexpert_get_device_tag() -> dict:
    """Return fake EasyEXPERT Device ID tag.

    Basis: EasyEXPERT `[:BENCh]:TAG?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_device_tag",
        [":BENCh:TAG?"],
        device_id="",
    )


@mcp.tool
def A_atom_easyexpert_set_repeat_count(count: int = 1) -> dict:
    """Pretend to set EasyEXPERT measurement repeat count.

    Basis: EasyEXPERT `[:BENCh]:COUNt count`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_repeat_count",
        [":BENCh:COUNt"],
        count=count,
    )


@mcp.tool
def A_atom_easyexpert_get_repeat_count() -> dict:
    """Return fake EasyEXPERT measurement repeat count.

    Basis: EasyEXPERT `[:BENCh]:COUNt?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_repeat_count",
        [":BENCh:COUNt?"],
        count=1,
    )


@mcp.tool
def A_atom_easyexpert_reset_repeat_count() -> dict:
    """Pretend to reset EasyEXPERT repeat count field.

    Basis: EasyEXPERT `[:BENCh]:COUNt:RESet`.
    """
    return _fake_response(
        "A_atom_easyexpert_reset_repeat_count",
        [":BENCh:COUNt:RESet"],
        count=0,
    )


@mcp.tool
def A_atom_easyexpert_set_app_test_param(param_name: str = "", value: float = 0.0) -> dict:
    """Pretend to set a numeric parameter of the selected EasyEXPERT application test.

    Basis: EasyEXPERT `[:BENCh][:SELected]:NUMBer "param", value`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_app_test_param",
        [":BENCh:SELected:NUMBer"],
        param_name=param_name,
        value=value,
        note="Only works for application-test parameter names; not for classic-test fields.",
    )


@mcp.tool
def A_atom_easyexpert_set_app_test_string(param_name: str = "", value: str = "") -> dict:
    """Pretend to set a string parameter of the selected EasyEXPERT application test.

    Basis: EasyEXPERT `[:BENCh][:SELected]:STRing "param", "value"`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_app_test_string",
        [":BENCh:SELected:STRing"],
        param_name=param_name,
        value=value,
        note="Used for resource strings like SMU1:HP or string parameters.",
    )


@mcp.tool
def A_atom_easyexpert_load_setup(format_type: str = "XTS") -> dict:
    """Pretend to load an EasyEXPERT setup from block data.

    Basis: EasyEXPERT `[:BENCh]:LOAD[:SETup] setup`.
    """
    return _fake_response(
        "A_atom_easyexpert_load_setup",
        [":BENCh:LOAD:SETup"],
        format_type=format_type,
        loaded=False,
        note="Real implementation requires SCPI definite-length block encoding of XTS/XTR data.",
    )


# ---------------------------------------------------------------------------
# B class — b1500/smu targets: lifecycle, safety, diagnostic, calibration,
#     policy, output, routing, correction atoms
# ---------------------------------------------------------------------------


@mcp.tool
def B_atom_lifecycle_b1500_reset() -> dict:
    """Pretend to reset B1500A to initial settings.

    Basis: B1500A Programming Guide `*RST`.
    """
    return _fake_response(
        "B_atom_lifecycle_b1500_reset",
        ["*RST"],
        status="fake_reset_complete",
        caution="Real implementation must not concatenate *RST with other FLEX commands.",
    )


@mcp.tool
def B_atom_lifecycle_b1500_initialize() -> dict:
    """Pretend to initialize B1500A state.

    Basis: B1500A Programming Guide `IN`.
    """
    return _fake_response("B_atom_lifecycle_b1500_initialize", ["IN"], status="fake_initialized")


@mcp.tool
def B_atom_safety_b1500_abort() -> dict:
    """Pretend to abort the active operation.

    Basis: B1500A Programming Guide `AB`.
    """
    return _fake_response(
        "B_atom_safety_b1500_abort",
        ["AB"],
        status="fake_aborted",
        caution="Real implementation should follow abort with safe cleanup and error readback.",
    )


@mcp.tool
def B_atom_diagnostic_b1500_self_test() -> dict:
    """Return fake B1500A self-test result.

    Basis: B1500A Programming Guide `*TST?`.
    """
    return _fake_response("B_atom_diagnostic_b1500_self_test", ["*TST?"], result_code=0, passed=True)


@mcp.tool
def B_atom_calibration_b1500_self_calibration() -> dict:
    """Return fake B1500A self-calibration result.

    Basis: B1500A Programming Guide `*CAL?`.
    """
    return _fake_response(
        "B_atom_calibration_b1500_self_calibration",
        ["*CAL?"],
        result_code=0,
        passed=True,
        caution="Real calibration should be scheduled and recorded in metadata.",
    )


@mcp.tool
def B_atom_diagnostic_b1500_diagnostics(item: int = 0) -> dict:
    """Return fake B1500A diagnostics result.

    Basis: B1500A Programming Guide `DIAG? item`.
    """
    return _fake_response("B_atom_diagnostic_b1500_diagnostics", ["DIAG?"], item=item, result_code=0, passed=True)


@mcp.tool
def B_atom_policy_b1500_set_auto_calibration(enabled: bool) -> dict:
    """Pretend to set B1500A auto-calibration policy.

    Basis: B1500A Programming Guide `CM`.
    """
    return _fake_response(
        "B_atom_policy_b1500_set_auto_calibration",
        ["CM"],
        enabled=enabled,
        caution="Long batch jobs should make auto-calibration policy explicit.",
    )


@mcp.tool
def B_atom_output_b1500_enable_channels(channels: str) -> dict:
    """Pretend to enable source/measurement channels.

    Basis: B1500A Programming Guide `CN ch1[,ch2,...]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_b1500_enable_channels",
        ["CN"],
        channels=parsed,
        outputs_enabled=bool(parsed),
        caution="Real implementation must validate module installation and role before CN.",
    )


@mcp.tool
def B_atom_output_b1500_disable_channels(channels: str = "") -> dict:
    """Pretend to disable selected or all source/measurement channels.

    Basis: B1500A Programming Guide `CL [ch1,ch2,...]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_b1500_disable_channels",
        ["CL"],
        channels=parsed or "all",
        outputs_enabled=False,
    )


@mcp.tool
def B_atom_output_b1500_zero_outputs(channels: str = "") -> dict:
    """Pretend to force selected or all channels to 0 V.

    Basis: B1500A Programming Guide `DZ [ch]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response("B_atom_output_b1500_zero_outputs", ["DZ"], channels=parsed or "all", status="fake_zeroed")


@mcp.tool
def B_atom_output_b1500_zero_all() -> dict:
    """Pretend to force all outputs to 0 V and disable all channels.

    Basis: B1500A Programming Guide `DZ` and `CL`.
    """
    return _fake_response(
        "B_atom_output_b1500_zero_all",
        ["DZ", "CL"],
        status="fake_zeroed_and_disabled",
        outputs_enabled=False,
        channels="all",
    )


@mcp.tool
def B_atom_output_b1500_confirm_zero(timeout_s: float = 5.0) -> dict:
    """Pretend to confirm all outputs are within the zero-voltage threshold.

    Basis: B1500A Programming Guide `WZ? [timeout]`.
    """
    return _fake_response("B_atom_output_b1500_confirm_zero", ["WZ?"], timeout_s=timeout_s, within_2v=True)


@mcp.tool
def B_atom_safety_b1500_check_interlock() -> dict:
    """Return fake high-voltage interlock state.

    Basis: B1500A design safety notes and `INTLKVTH?` reference.
    """
    return _fake_response(
        "B_atom_safety_b1500_check_interlock",
        ["INTLKVTH?"],
        interlock_closed="unknown",
        high_voltage_allowed=False,
        threshold_v=42.0,
    )


@mcp.tool
def B_atom_safety_b1500_preflight(device_type: str = "unknown", pin_map_known: bool = False) -> dict:
    """Run fake readiness checks before any measurement recipe."""
    checks = [
        {"name": "mcp_server_loaded", "passed": True},
        {"name": "real_transport_available", "passed": False},
        {"name": "pin_map_known", "passed": pin_map_known},
        {"name": "device_type_declared", "passed": device_type != "unknown"},
        {"name": "raw_flex_disabled", "passed": True},
    ]
    return _fake_response(
        "B_atom_safety_b1500_preflight",
        ["UNT?", "ERRX?", "*STB?", "*LRN?", "INTLKVTH?"],
        device_type=device_type,
        passed=all(check["passed"] for check in checks),
        checks=checks,
        next_step="Implement real station profile and PyVISA transport before hardware use.",
    )


@mcp.tool
def B_atom_output_b1500_recover_zeroed(channels: str = "") -> dict:
    """Pretend to restore channel settings saved by `DZ`.

    Basis: B1500A Programming Guide `RZ [ch]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_b1500_recover_zeroed",
        ["RZ"],
        channels=parsed or "all",
        status="fake_recovered",
        caution="Real implementation requires a prior DZ; otherwise error 205 is expected.",
    )


@mcp.tool
def B_atom_output_smu_set_filter(channel: int, enabled: bool = False) -> dict:
    """Pretend to set SMU filter state.

    Basis: B1500A Programming Guide `FL`; initial setting table lists SMU filter off.
    """
    return _fake_response(
        "B_atom_output_smu_set_filter",
        ["FL"],
        channel=channel,
        enabled=enabled,
    )


@mcp.tool
def B_atom_output_smu_set_series_resistor(channel: int, enabled: bool = False) -> dict:
    """Pretend to set SMU series resistor state.

    Basis: B1500A Programming Guide `SSR`; initial setting table lists series resistor off.
    """
    return _fake_response(
        "B_atom_output_smu_set_series_resistor",
        ["SSR"],
        channel=channel,
        enabled=enabled,
    )


@mcp.tool
def B_atom_calibration_smu_set_adc_zero(enabled: bool = False) -> dict:
    """Pretend to set SMU ADC zero function.

    Basis: B1500A Programming Guide `AZ`; initial setting table lists ADC zero off.
    """
    return _fake_response("B_atom_calibration_smu_set_adc_zero", ["AZ"], enabled=enabled)


@mcp.tool
def B_atom_routing_asu_set_path(channel: int, path: str = "SMU") -> dict:
    """Pretend to switch ASU path.

    Basis: B1500A Programming Guide `SAP`; initial state is SMU side.
    """
    return _fake_response(
        "B_atom_routing_asu_set_path",
        ["SAP"],
        channel=channel,
        path=path,
        caution="Real implementation must verify ASU topology and DUT safety before switching.",
    )


@mcp.tool
def B_atom_routing_asu_set_1pa_range(channel: int, enabled: bool = False) -> dict:
    """Pretend to enable/disable ASU 1 pA auto-ranging.

    Basis: B1500A Programming Guide `SAR`.
    """
    return _fake_response(
        "B_atom_routing_asu_set_1pa_range",
        ["SAR"],
        channel=channel,
        enabled=enabled,
    )


@mcp.tool
def B_atom_routing_asu_set_indicator(channel: int, enabled: bool = True) -> dict:
    """Pretend to set ASU indicator state.

    Basis: B1500A Programming Guide `SAL`.
    """
    return _fake_response(
        "B_atom_routing_asu_set_indicator",
        ["SAL"],
        channel=channel,
        enabled=enabled,
    )


@mcp.tool
def B_atom_routing_scuu_set_path(channel: int, path_mode: str = "open") -> dict:
    """Pretend to switch SCUU path.

    Basis: B1500A Programming Guide `SSP`; use SSP instead of CN for SCUU modules.
    """
    return _fake_response(
        "B_atom_routing_scuu_set_path",
        ["SSP"],
        channel=channel,
        path_mode=path_mode,
        caution="Real implementation must validate SMU/CMU path and force safe state before switching.",
    )


@mcp.tool
def B_atom_routing_scuu_set_indicator(channel: int, enabled: bool = True) -> dict:
    """Pretend to set SCUU indicator state.

    Basis: B1500A Programming Guide `SSL`.
    """
    return _fake_response(
        "B_atom_routing_scuu_set_indicator",
        ["SSL"],
        channel=channel,
        enabled=enabled,
    )


@mcp.tool
def B_atom_correction_cmu_set_correction(correction_type: str, enabled: bool = False) -> dict:
    """Pretend to enable/disable CMU open/short/load correction.

    Basis: B1500A Programming Guide `CORRST` / `CORRST?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_set_correction",
        ["CORRST", "CORRST?"],
        correction_type=correction_type,
        enabled=enabled,
        note="OPEN/SHOR/LOAD are CORRST type labels, not standalone commands.",
    )


@mcp.tool
def B_atom_correction_cmu_measure_data(correction_type: str, channel: int) -> dict:
    """Pretend to measure CMU open/short/load correction data.

    Basis: B1500A Programming Guide `CORR?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_measure_data",
        ["CORR?"],
        correction_type=correction_type,
        channel=channel,
        result_code=0,
        caution="Real implementation must require correct open/short/load fixture condition.",
    )


@mcp.tool
def B_atom_correction_cmu_set_phase_mode(channel: int, mode: str = "auto") -> dict:
    """Pretend to select MFCMU phase compensation mode.

    Basis: B1500A Programming Guide `ADJ`.
    """
    return _fake_response(
        "B_atom_correction_cmu_set_phase_mode",
        ["ADJ"],
        channel=channel,
        mode=mode,
    )


@mcp.tool
def B_atom_correction_cmu_perform_phase_comp(channel: int) -> dict:
    """Pretend to perform MFCMU phase compensation.

    Basis: B1500A Programming Guide `ADJ?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_perform_phase_comp",
        ["ADJ?"],
        channel=channel,
        result_code=0,
        caution="Real manual notes open measurement terminals at device side; operation may take about 30 seconds.",
    )


@mcp.tool
def B_atom_correction_cmu_clear() -> dict:
    """Pretend to clear CMU correction data.

    Basis: B1500A Programming Guide `CLCORR`.
    """
    return _fake_response("B_atom_correction_cmu_clear", ["CLCORR"], cleared=True)


@mcp.tool
def B_atom_correction_qscv_offset_cancel(channel: int) -> dict:
    """Pretend to perform QSCV zero/offset cancellation.

    Basis: B1500A Programming Guide QSCV command group `QSZ`.
    """
    return _fake_response("B_atom_correction_qscv_offset_cancel", ["QSZ"], channel=channel, result_code=0)


# ---------------------------------------------------------------------------
# B class — wgfmu targets: lifecycle, calibration, diagnostic, policy, output atoms
# ---------------------------------------------------------------------------


@mcp.tool
def B_atom_lifecycle_wgfmu_initialize() -> dict:
    """Pretend to reset all WGFMU channels.

    Basis: B1530A WGFMU `WGFMU_initialize`.
    """
    return _fake_response("B_atom_lifecycle_wgfmu_initialize", ["WGFMU_initialize"], status="fake_initialized")


@mcp.tool
def B_atom_calibration_wgfmu_self_calibration() -> dict:
    """Pretend to run WGFMU/mainframe self-calibration.

    Basis: B1530A WGFMU `WGFMU_doSelfCalibration`.
    """
    return _fake_response(
        "B_atom_calibration_wgfmu_self_calibration",
        ["WGFMU_doSelfCalibration"],
        result_code=0,
        detail="fake pass",
        timeout_auto_s=600,
    )


@mcp.tool
def B_atom_diagnostic_wgfmu_self_test() -> dict:
    """Pretend to run WGFMU/mainframe self-test.

    Basis: B1530A WGFMU `WGFMU_doSelfTest`.
    """
    return _fake_response(
        "B_atom_diagnostic_wgfmu_self_test",
        ["WGFMU_doSelfTest"],
        result_code=0,
        detail="fake pass",
        timeout_auto_s=600,
    )


@mcp.tool
def B_atom_policy_wgfmu_treat_warnings_as_errors(enabled: bool = False) -> dict:
    """Pretend to set WGFMU warning-as-error policy.

    Basis: B1530A WGFMU `WGFMU_treatWarningsAsErrors`.
    """
    return _fake_response(
        "B_atom_policy_wgfmu_treat_warnings_as_errors",
        ["WGFMU_treatWarningsAsErrors"],
        enabled=enabled,
    )


@mcp.tool
def B_atom_output_wgfmu_connect(channel_id: int = 501) -> dict:
    """Pretend to enable a WGFMU channel and connected RSU.

    Basis: B1530A WGFMU `WGFMU_connect`.
    """
    return _fake_response(
        "B_atom_output_wgfmu_connect",
        ["WGFMU_connect"],
        channel_id=channel_id,
        connected=False,
        note="Enables WGFMU channel output through RSU. B-class: channel output control.",
    )


@mcp.tool
def B_atom_output_wgfmu_disconnect(channel_id: int = 501) -> dict:
    """Pretend to disable a WGFMU channel and connected RSU.

    Basis: B1530A WGFMU `WGFMU_disconnect`.
    """
    return _fake_response(
        "B_atom_output_wgfmu_disconnect",
        ["WGFMU_disconnect"],
        channel_id=channel_id,
        connected=False,
        note="Disables WGFMU channel output. B-class: channel output control.",
    )


@mcp.tool
def B_atom_lifecycle_wgfmu_abort() -> dict:
    """Pretend to stop WGFMU sequencer on all channels.

    Basis: B1530A WGFMU `WGFMU_abort`.
    """
    return _fake_response(
        "B_atom_lifecycle_wgfmu_abort",
        ["WGFMU_abort"],
        status="fake_aborted",
        note="Channels keep output voltage at moment of abort.",
    )


# ---------------------------------------------------------------------------
# B class — easyexpert targets: safety, output, calibration atoms
# ---------------------------------------------------------------------------


@mcp.tool
def B_atom_safety_easyexpert_abort_measurement() -> dict:
    """Pretend to abort the selected EasyEXPERT measurement.

    Basis: EasyEXPERT `[:BENCh][:SELected]:ABORt`.
    """
    return _fake_response(
        "B_atom_safety_easyexpert_abort_measurement",
        ["[:BENCh][:SELected]:ABORt"],
        status="fake_aborted",
    )


@mcp.tool
def B_atom_output_easyexpert_set_standby(enabled: bool = False) -> dict:
    """Pretend to set EasyEXPERT standby state.

    Basis: EasyEXPERT `:STANDby:STATe 0|OFF|1|ON`.
    """
    return _fake_response("B_atom_output_easyexpert_set_standby", [":STANDby:STATe"], enabled=enabled)


@mcp.tool
def B_atom_calibration_easyexpert_zero_cancel_on(channel: str = "all") -> dict:
    """Pretend to enable EasyEXPERT SMU zero cancel.

    Basis: EasyEXPERT CALibration subsystem `ON` / `ON:ALL`.
    """
    return _fake_response("B_atom_calibration_easyexpert_zero_cancel_on", [":CALibration:...:ON"], channel=channel)


@mcp.tool
def B_atom_calibration_easyexpert_zero_cancel_off(channel: str = "all") -> dict:
    """Pretend to disable EasyEXPERT SMU zero cancel.

    Basis: EasyEXPERT CALibration subsystem `OFF:ALL`.
    """
    return _fake_response("B_atom_calibration_easyexpert_zero_cancel_off", [":CALibration:...:OFF:ALL"], channel=channel)


@mcp.tool
def B_atom_calibration_easyexpert_measure_zero_cancel(channel: str = "all") -> dict:
    """Pretend to measure EasyEXPERT SMU zero-cancel data.

    Basis: EasyEXPERT CALibration subsystem `MEASure`.
    """
    return _fake_response(
        "B_atom_calibration_easyexpert_measure_zero_cancel",
        [":CALibration:...:MEASure"],
        channel=channel,
        result_code=0,
    )


@mcp.tool
def B_atom_calibration_easyexpert_query_zero_cancel_state(channel: str = "all") -> dict:
    """Pretend to query EasyEXPERT SMU zero-cancel state.

    Basis: EasyEXPERT CALibration subsystem `STATe?`.
    """
    return _fake_response(
        "B_atom_calibration_easyexpert_query_zero_cancel_state",
        [":CALibration:...:STATe?"],
        channel=channel,
        enabled=False,
    )


# ---------------------------------------------------------------------------
# MCP resources
# ---------------------------------------------------------------------------


@mcp.resource("b1500://capabilities")
def capabilities() -> dict:
    """Describe the fake MCP capability surface."""
    return _fake_response(
        "capabilities_resource",
        [],
        A_atoms=_atom_names("A_atom_"),
        B_atoms=_atom_names("B_atom_"),
        implementation_status="A/B atom fake tools; C measurement atoms intentionally not added yet.",
    )


@mcp.resource("b1500://safety-policy")
def safety_policy() -> dict:
    """Expose initial safety policy reminders as an MCP resource."""
    return _fake_response(
        "safety_policy_resource",
        [],
        rules=[
            "Do not expose raw FLEX commands by default.",
            "Validate station profile, pin map, module limits, compliance, and interlock before sourcing.",
            "Use typed command builders and auditable transactions.",
            "Cleanup must reach DZ and CL on failure when real transport is implemented.",
        ],
    )


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
