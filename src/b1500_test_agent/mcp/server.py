"""FastMCP server entry point.

This server is intentionally fake-but-loadable. It gives MCP clients a stable
surface to discover while the real B1500A driver and safety layer are developed.
Every tool returns `fake: true` and must not be treated as hardware control.
"""

from fastmcp import FastMCP

mcp = FastMCP(
    name="b1500-test-agent",
    version="0.1.0",
    instructions=(
        "Fake-but-loadable B1500A MCP server for client discovery. "
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


def _fake_response(tool: str, flex_basis: list[str], **payload: object) -> dict:
    """Build a standard fake MCP response."""
    return {
        "tool": tool,
        "fake": True,
        "hardware_touched": False,
        "flex_basis": flex_basis,
        **payload,
    }


def _parse_channels(channels: str) -> list[int]:
    """Parse a comma-separated channel list for fake channel-control tools."""
    if not channels.strip():
        return []
    return [int(part.strip()) for part in channels.split(",") if part.strip()]

@mcp.tool
def connect_b1500(gpib_address: int = 17, gpib_board: int = 0, timeout_ms: int = 600_000) -> dict:
    """Open a fake B1500A session and return synthetic identity and inventory.

    Programming Guide basis: `*IDN?` for identity and `UNT?` for installed modules.
    """
    return _fake_response(
        "connect_b1500",
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
def disconnect_b1500() -> dict:
    """Close a fake B1500A session after safe output cleanup.

    Programming Guide basis: `DZ` forces 0 V and `CL` disables output channels.
    """
    return _fake_response(
        "disconnect_b1500",
        ["DZ", "CL"],
        connected=False,
        status="fake_disconnected",
    )


@mcp.tool
def identify_b1500() -> dict:
    """Return fake B1500A identity.

    Programming Guide basis: `*IDN?`.
    """
    return _fake_response(
        "identify_b1500",
        ["*IDN?"],
        instrument_id="Keysight Technologies,B1500A,FAKE,0.0",
    )


@mcp.tool
def list_installed_modules() -> dict:
    """Return fake installed module inventory.

    Programming Guide basis: `UNT?`.
    """
    return _fake_response(
        "list_installed_modules",
        ["UNT?"],
        modules=_FAKE_MODULES,
        channel_numbering="1-10 primary slot channels; 11-20 secondary channels.",
    )


@mcp.tool
def get_instrument_status() -> dict:
    """Return fake B1500A status, errors, module inventory, and safety state.

    Programming Guide basis: `UNT?`, `ERRX?`, `*STB?`, and `*LRN?`.
    """
    return _fake_response(
        "get_instrument_status",
        ["UNT?", "ERRX?", "*STB?", "*LRN?"],
        connected=False,
        state="fake_offline",
        modules=_FAKE_MODULES,
        error_queue=[],
        status_byte=0,
        safety={
            "interlock": "unknown",
            "outputs_enabled": False,
            "raw_flex_enabled": False,
        },
    )


@mcp.tool
def query_current_settings() -> dict:
    """Return fake current instrument settings.

    Programming Guide basis: `*LRN?` learns current B1500A settings.
    """
    return _fake_response(
        "query_current_settings",
        ["*LRN?"],
        settings={
            "format": "FMT 1,1",
            "timestamp": "disabled",
            "auto_calibration": "enabled",
            "active_channels": [],
        },
    )


@mcp.tool
def read_error_queue(clear_after_read: bool = False) -> dict:
    """Return fake B1500A error queue.

    Programming Guide basis: `ERR?` and `ERRX?` read error code/message.
    """
    return _fake_response(
        "read_error_queue",
        ["ERR?", "ERRX?"],
        clear_after_read=clear_after_read,
        errors=[],
        message="No fake errors queued.",
    )


@mcp.tool
def read_status_byte() -> dict:
    """Return fake GPIB status byte.

    Programming Guide basis: status byte section and common `*STB?` query.
    """
    return _fake_response(
        "read_status_byte",
        ["*STB?"],
        status_byte=0,
        decoded={"message_available": False, "error_available": False, "operation_complete": True},
    )


@mcp.tool
def wait_operation_complete(timeout_s: float = 60.0) -> dict:
    """Pretend to wait for current operation completion.

    Programming Guide basis: `*OPC?` confirms operation completion.
    """
    return _fake_response(
        "wait_operation_complete",
        ["*OPC?"],
        timeout_s=timeout_s,
        complete=True,
    )


@mcp.tool
def reset_instrument() -> dict:
    """Pretend to reset B1500A to initial settings.

    Programming Guide basis: `*RST`. Do not combine `*RST` with other commands.
    """
    return _fake_response(
        "reset_instrument",
        ["*RST"],
        status="fake_reset_complete",
        caution="Real implementation must not concatenate *RST with other FLEX commands.",
    )


@mcp.tool
def initialize_instrument() -> dict:
    """Pretend to initialize B1500A without clearing the error buffer.

    Programming Guide basis: `IN`.
    """
    return _fake_response(
        "initialize_instrument",
        ["IN"],
        status="fake_initialized",
        caution="Use dedicated tool rather than raw `IN` command.",
    )


@mcp.tool
def abort_operation() -> dict:
    """Pretend to abort the active operation.

    Programming Guide basis: `AB`. Do not combine `AB` with other commands.
    """
    return _fake_response(
        "abort_operation",
        ["AB"],
        status="fake_aborted",
        caution="Real implementation should follow abort with safe cleanup and error readback.",
    )


@mcp.tool
def run_self_test() -> dict:
    """Return fake B1500A self-test result.

    Programming Guide basis: `*TST?`.
    """
    return _fake_response(
        "run_self_test",
        ["*TST?"],
        result_code=0,
        passed=True,
    )


@mcp.tool
def run_self_calibration() -> dict:
    """Return fake B1500A self-calibration result.

    Programming Guide basis: `*CAL?`. Real calibration may take several minutes.
    """
    return _fake_response(
        "run_self_calibration",
        ["*CAL?"],
        result_code=0,
        passed=True,
        caution="Real calibration should be scheduled and recorded in metadata.",
    )


@mcp.tool
def run_diagnostics(item: int = 0) -> dict:
    """Return fake diagnostics result.

    Programming Guide basis: `DIAG? item`.
    """
    return _fake_response(
        "run_diagnostics",
        ["DIAG?"],
        item=item,
        result_code=0,
        passed=True,
    )


@mcp.tool
def set_auto_calibration(enabled: bool) -> dict:
    """Pretend to enable or disable auto calibration.

    Programming Guide basis: `CM` auto calibration control.
    """
    return _fake_response(
        "set_auto_calibration",
        ["CM"],
        enabled=enabled,
        caution="Long batch jobs should make auto-calibration policy explicit.",
    )


@mcp.tool
def set_data_format(format_mode: int = 1, output_mode: int = 1) -> dict:
    """Pretend to set B1500A data output format.

    Programming Guide basis: `FMT mode[, output]`.
    """
    recommended = format_mode in {1, 5, 11, 15, 21, 25}
    return _fake_response(
        "set_data_format",
        ["FMT"],
        format_mode=format_mode,
        output_mode=output_mode,
        recommended_for_fake_driver=recommended,
        note="Initial parser work should prefer ASCII formats with status headers.",
    )


@mcp.tool
def configure_timestamp(enabled: bool = True) -> dict:
    """Pretend to enable or disable timestamp output.

    Programming Guide basis: `TSC mode`.
    """
    return _fake_response(
        "configure_timestamp",
        ["TSC"],
        enabled=enabled,
    )


@mcp.tool
def reset_timestamp() -> dict:
    """Pretend to reset the B1500A timestamp timer.

    Programming Guide basis: `TSR`.
    """
    return _fake_response(
        "reset_timestamp",
        ["TSR"],
        timestamp_s=0.0,
    )


@mcp.tool
def read_timestamp() -> dict:
    """Return a fake current timestamp value.

    Programming Guide basis: `TSQ`.
    """
    return _fake_response(
        "read_timestamp",
        ["TSQ"],
        timestamp_s=0.0,
    )


@mcp.tool
def enable_channels(channels: str) -> dict:
    """Pretend to enable source/measurement channels.

    Programming Guide basis: `CN ch1[,ch2,...]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "enable_channels",
        ["CN"],
        channels=parsed,
        outputs_enabled=bool(parsed),
        caution="Real implementation must validate channel installation and role before CN.",
    )


@mcp.tool
def disable_channels(channels: str = "") -> dict:
    """Pretend to disable source/measurement channels.

    Programming Guide basis: `CL [ch1,ch2,...]`; empty input means all channels.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "disable_channels",
        ["CL"],
        channels=parsed or "all",
        outputs_enabled=False,
    )


@mcp.tool
def zero_outputs(channels: str = "") -> dict:
    """Pretend to force selected or all channels to 0 V.

    Programming Guide basis: `DZ [ch]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "zero_outputs",
        ["DZ"],
        channels=parsed or "all",
        status="fake_zeroed",
    )


@mcp.tool
def zero_all_outputs() -> dict:
    """Pretend to force all outputs to 0 V and disable all channels.

    Programming Guide basis: `DZ` and `CL`.
    """
    return _fake_response(
        "zero_all_outputs",
        ["DZ", "CL"],
        status="fake_zeroed_and_disabled",
        outputs_enabled=False,
        channels="all",
        caution="Real implementation should be safe to call during errors and session cleanup.",
    )


@mcp.tool
def confirm_zero_outputs(timeout_s: float = 5.0) -> dict:
    """Pretend to confirm all outputs are within the zero-voltage threshold.

    Programming Guide basis: `WZ? [timeout]` returns whether outputs are within +/-2 V.
    """
    return _fake_response(
        "confirm_zero_outputs",
        ["WZ?"],
        timeout_s=timeout_s,
        within_2v=True,
    )


@mcp.tool
def check_interlock_status() -> dict:
    """Return fake interlock status for high-voltage planning.

    Design basis: interlock state must be checked before operations above 42 V.
    Programming Guide related command noted in design docs: `INTLKVTH?`.
    """
    return _fake_response(
        "check_interlock_status",
        ["INTLKVTH?"],
        interlock_closed="unknown",
        high_voltage_allowed=False,
        threshold_v=42.0,
    )


@mcp.tool
def run_preflight_checks(device_type: str = "unknown", pin_map_known: bool = False) -> dict:
    """Run fake preflight checks for a planned B1500A measurement."""
    checks = [
        {"name": "mcp_server_loaded", "passed": True},
        {"name": "real_transport_available", "passed": False},
        {"name": "pin_map_known", "passed": pin_map_known},
        {"name": "device_type_declared", "passed": device_type != "unknown"},
        {"name": "raw_flex_disabled", "passed": True},
    ]
    return _fake_response(
        "run_preflight_checks",
        ["UNT?", "ERRX?", "*STB?", "*LRN?", "INTLKVTH?"],
        device_type=device_type,
        passed=all(check["passed"] for check in checks),
        checks=checks,
        next_step="Implement real station profile and PyVISA transport before hardware use.",
    )


@mcp.resource("b1500://capabilities")
def capabilities() -> dict:
    """Describe the fake MCP capability surface."""
    return _fake_response(
        "capabilities_resource",
        [],
        tools=[
            "connect_b1500",
            "disconnect_b1500",
            "identify_b1500",
            "list_installed_modules",
            "get_instrument_status",
            "query_current_settings",
            "read_error_queue",
            "read_status_byte",
            "wait_operation_complete",
            "reset_instrument",
            "initialize_instrument",
            "abort_operation",
            "run_self_test",
            "run_self_calibration",
            "run_diagnostics",
            "set_auto_calibration",
            "set_data_format",
            "configure_timestamp",
            "reset_timestamp",
            "read_timestamp",
            "enable_channels",
            "disable_channels",
            "zero_outputs",
            "zero_all_outputs",
            "confirm_zero_outputs",
            "check_interlock_status",
            "run_preflight_checks",
        ],
        implementation_status="instrument-interaction-fake-tools",
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
