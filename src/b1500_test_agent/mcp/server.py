"""FastMCP server entry point.

This server is intentionally fake-but-loadable. It gives MCP clients a stable
surface to discover while the real B1500A driver and safety layer are developed.
Every tool returns `fake: true` and must not be treated as hardware control.
"""

from typing import Literal

from fastmcp import FastMCP

mcp = FastMCP(
    name="b1500-test-agent",
    version="0.1.0",
    instructions=(
        "Fake-but-loadable B1500A MCP server for client discovery. "
        "All tools return synthetic data and must not be treated as hardware control."
    ),
)


@mcp.tool
def ping() -> dict:
    """Check that the B1500A Test Agent MCP server is alive."""
    return {
        "ok": True,
        "fake": True,
        "server": "b1500-test-agent",
        "message": "B1500A Test Agent MCP server is reachable.",
    }


@mcp.tool
def connect_b1500_fake(gpib_address: int = 17) -> dict:
    """Pretend to connect to a Keysight B1500A via GPIB.

    This is a smoke-test tool for MCP discovery only. It does not open VISA,
    does not send FLEX commands, and does not touch real hardware.
    """
    return {
        "connected": False,
        "fake": True,
        "gpib_address": gpib_address,
        "instrument_id": "Keysight Technologies,B1500A,FAKE,0.0",
        "warning": "Fake connection only; real PyVISA transport is not implemented.",
    }


@mcp.tool
def get_instrument_status() -> dict:
    """Return fake B1500A status and module inventory."""
    return {
        "connected": False,
        "fake": True,
        "state": "fake_offline",
        "modules": [
            {"slot": 1, "type": "MPSMU", "channels": [1], "priority": "P0"},
            {"slot": 2, "type": "HRSMU", "channels": [2], "priority": "P0"},
            {"slot": 5, "type": "WGFMU", "channels": [5, 15], "priority": "P1"},
            {"slot": 6, "type": "HVSPGU", "channels": [6, 16], "priority": "P1"},
            {"slot": 7, "type": "MFCMU", "channels": [7], "priority": "P2"},
        ],
        "safety": {
            "interlock": "unknown",
            "outputs_enabled": False,
            "raw_flex_enabled": False,
        },
    }


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
    return {
        "fake": True,
        "device_type": device_type,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "next_step": "Implement real station profile and PyVISA transport before hardware use.",
    }


@mcp.tool
def measure_spot_iv_fake(
    channel: int,
    force_value: float = 0.0,
    force_quantity: Literal["voltage", "current"] = "voltage",
    compliance_a: float = 0.001,
) -> dict:
    """Return a fake single-point IV measurement result.

    This tool exists only to verify that Cursor can display and call MCP tools.
    """
    measured_current_a = force_value * 1e-9 if force_quantity == "voltage" else compliance_a / 10
    return {
        "fake": True,
        "channel": channel,
        "force_quantity": force_quantity,
        "force_value": force_value,
        "compliance_a": compliance_a,
        "measurement": {
            "current_a": measured_current_a,
            "voltage_v": force_value if force_quantity == "voltage" else 0.0,
            "status_code": "N",
        },
        "warning": "Synthetic data only; no B1500A command was sent.",
    }


@mcp.tool
def zero_all_outputs_fake() -> dict:
    """Pretend to zero and disable all outputs."""
    return {
        "fake": True,
        "status": "all_outputs_already_disabled",
        "commands_that_real_driver_would_use": ["DZ", "CL"],
    }


@mcp.resource("b1500://capabilities")
def capabilities() -> dict:
    """Describe the fake MCP capability surface."""
    return {
        "fake": True,
        "tools": [
            "ping",
            "connect_b1500_fake",
            "get_instrument_status",
            "run_preflight_checks",
            "measure_spot_iv_fake",
            "zero_all_outputs_fake",
        ],
        "implementation_status": "mcp-discovery-smoke-test",
    }


@mcp.resource("b1500://safety-policy")
def safety_policy() -> dict:
    """Expose initial safety policy reminders as an MCP resource."""
    return {
        "fake": True,
        "rules": [
            "Do not expose raw FLEX commands by default.",
            "Validate station profile, pin map, module limits, compliance, and interlock before sourcing.",
            "Use typed command builders and auditable transactions.",
            "Cleanup must reach DZ and CL on failure when real transport is implemented.",
        ],
    }


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
