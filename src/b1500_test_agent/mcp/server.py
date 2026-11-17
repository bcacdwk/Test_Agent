"""FastMCP server entry point.

This server is intentionally fake-but-loadable. It exposes a stable atom/flow
tool surface for Cursor/Codex discovery while the real B1500A driver and safety
layer are developed. Every tool returns ``fake: true`` and must not be treated
as hardware control.

Naming convention:
  A_atom_<interface>_<action>    -- read/discover/connect/session/context atoms
  B_atom_<risk_category>_<target>_<action> -- safety/state-control atoms
  C_atom_<object>_<action> -- measurement/source/configuration/execution atoms
  D_atom_<stage>_<subject>_<action> -- post-acquisition analysis placeholder atoms
  C_flow_<measurement_family>_<object>_<subject> -- C-only measurement compositions
  A_flow_<operation>_<interface>_<subject> -- A-only orchestration flows
  B_flow_<category>_<target>_<subject> -- B-only safety/state-control flows
  AB_flow_<category>_<scope>_<subject> -- user-facing observe/act/verify workflows
  D_flow_<operation>_<domain>_<subject> -- D-only analysis compositions over held evidence
  CD_flow_<operation>_<domain>_<subject> -- expect/measure/interpret/archive (one C flow + D)

A interfaces: flex (direct GPIB/VISA), wgfmu (B1530A library), easyexpert (remote)
B categories: safety, output, lifecycle, diagnostic, calibration, routing,
              correction, policy
B targets: b1500, smu, asu, scuu, cmu, qscv, wgfmu, easyexpert
C objects: smu, wgfmu, spgu, cmu, hvsmu, hcsmu, uhcu, hvmcu, uhvu, easyexpert
D stages: ingest, qualify, shape, derive, extract, assess, archive, render
D/CD flow operations: qualify, screen, analyze (D also archive); domains: iv, cv, timeseries, run
"""

from collections.abc import Callable

from fastmcp import FastMCP

from .a_atoms import A_ATOM_FUNCTIONS, register_a_atoms
from .a_flows import A_FLOW_FUNCTIONS, register_a_flows
from .ab_flows import AB_FLOW_FUNCTIONS, register_ab_flows
from .b_atoms import B_ATOM_FUNCTIONS, register_b_atoms
from .b_flows import B_FLOW_FUNCTIONS, register_b_flows
from .c_atoms import C_ATOM_FUNCTIONS, register_c_atoms
from .c_flows import C_FLOW_FUNCTIONS, register_c_flows
from .cd_flows import CD_FLOW_FUNCTIONS, register_cd_flows
from .common import _fake_response
from .d_atoms import D_ATOM_FUNCTIONS, register_d_atoms
from .d_flows import D_FLOW_FUNCTIONS, register_d_flows

mcp = FastMCP(
    name="b1500-test-agent",
    version="0.2.0",
    instructions=(
        "Fake-but-loadable B1500A MCP server for client discovery. "
        "A_atom tools are connection/communication/status atoms. "
        "B_atom tools are safety/state-control atoms. "
        "C_atom tools are measurement/source/configuration/execution atoms. "
        "A_flow tools are A-only orchestration flows. "
        "B_flow tools are B-only safety/state-control flows. "
        "C_flow tools are C-only fake measurement compositions with explicit completion/gap states. "
        "AB_flow tools are observe/act/verify workflow orchestrations. "
        "D_atom tools are hardware-free post-acquisition analysis placeholder stubs: they "
        "return content-free product references, never numbers, pass verdicts or files. "
        "D_flow tools compose D atoms only over a C flow envelope the caller already holds. "
        "CD_flow tools call one C flow (closed acquisition.kind), its D flow and the archive "
        "D flow; they are fake-only and never write files. "
        "A second token: flex | wgfmu | easyexpert (interface). "
        "B second token: safety | output | lifecycle | diagnostic | "
        "calibration | routing | correction | policy (risk/operation). "
        "C second token: smu | wgfmu | spgu | cmu | hvsmu | hcsmu | "
        "uhcu | hvmcu | uhvu | easyexpert (object). "
        "D second token: ingest | qualify | shape | derive | extract | assess | "
        "archive | render (stage). "
        "All tools return synthetic data and must not be treated as hardware control."
    ),
)


def _function_names(functions: list[Callable[..., dict]]) -> list[str]:
    """Return tool function names in registration order."""
    return [function.__name__ for function in functions]


register_a_atoms(mcp)
register_a_flows(mcp)
register_b_atoms(mcp)
register_b_flows(mcp)
register_c_atoms(mcp)
register_c_flows(mcp)
register_ab_flows(mcp)
register_d_atoms(mcp)
register_d_flows(mcp)
register_cd_flows(mcp)


@mcp.resource("b1500://capabilities")
def capabilities() -> dict:
    """Describe the fake MCP capability surface."""
    return _fake_response(
        "capabilities_resource",
        [],
        A_atoms=_function_names(A_ATOM_FUNCTIONS),
        B_atoms=_function_names(B_ATOM_FUNCTIONS),
        C_atoms=_function_names(C_ATOM_FUNCTIONS),
        D_atoms=_function_names(D_ATOM_FUNCTIONS),
        A_flows=_function_names(A_FLOW_FUNCTIONS),
        B_flows=_function_names(B_FLOW_FUNCTIONS),
        C_flows=_function_names(C_FLOW_FUNCTIONS),
        AB_flows=_function_names(AB_FLOW_FUNCTIONS),
        D_flows=_function_names(D_FLOW_FUNCTIONS),
        CD_flows=_function_names(CD_FLOW_FUNCTIONS),
        implementation_status=(
            "A/B/C atom fake tools plus A_flow, B_flow, C_flow, and AB_flow "
            "orchestration-only compositions; D atoms are hardware-free placeholder stubs (U1) "
            "with no computation and no file writes; D_flow and CD_flow compose them over fake "
            "C evidence (CD is fake-only, U7); real hardware and ABC transactions are not "
            "implemented."
        ),
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
