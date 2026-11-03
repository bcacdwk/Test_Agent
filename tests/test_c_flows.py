"""Contracts for fake measurement composition, failure evidence and MCP discovery."""

import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client
from pydantic import ValidationError

from b1500_test_agent.mcp import c_atoms
from b1500_test_agent.mcp import c_flows as flows
from b1500_test_agent.schemas import c_flow as schema

WAVEFORM = {
    "channels": [
        {
            "channel_id": 502,
            "pattern": "read_pulse",
            "vectors": [{"delta_time_s": 2e-6, "voltage_v": 0.2}],
            "events": [{"time_s": 1e-7, "points": 2}],
        }
    ]
}


def _request(name: str) -> dict:
    if name == "C_flow_waveform_wgfmu_acquire":
        return WAVEFORM
    if name == "C_flow_waveform_spgu_sequence":
        return {"levels_v": [0.0, 0.1, 0.0]}
    return {}


@pytest.mark.parametrize("tool", flows.C_FLOW_FUNCTIONS, ids=lambda f: f.__name__)
def test_catalog_composes_only_fake_c_atoms(tool):
    result = tool(**({"request": _request(tool.__name__)} if _request(tool.__name__) else {}))
    assert result["ok"], result["warnings"]
    assert result["fake"] and result["hardware_touched"] is False
    assert result["measurement_completed"] is False
    assert result["cleanup"]["performed"] is False
    assert all(name.startswith("C_atom_") for name in result["atoms_called"])
    for record in result["atom_results"]:
        if record["status"] != "skipped":
            assert record["result"]["fake"]
            assert record["result"]["hardware_touched"] is False
    if result["contract_gaps"]:
        assert result["partial"]
        assert not result["simulation_completed"]
        assert all(
            r["status"] == "skipped"
            for r in result["atom_results"]
            if r["phase"] in {"execute", "read"}
        )
    json.dumps(result, allow_nan=False)


def test_spot_current_units_and_channel_forwarding():
    result = flows.C_flow_spot_smu_iv(
        schema.SmuSpot(
            channel=4,
            source="current",
            level=2e-6,
            compliance=0.5,
            ranging=schema.Ranging(measure_function="voltage"),
        )
    )
    assert result["atoms_called"] == [
        "C_atom_smu_configure_integration",
        "C_atom_smu_set_measurement_ranging",
        "C_atom_smu_set_measurement_mode",
        "C_atom_smu_force_current",
        "C_atom_smu_execute",
        "C_atom_smu_read_measurement_data",
    ]
    forced = result["atom_results"][3]["inputs"]
    assert forced["channel"] == 4
    assert forced["current_a"] == 2e-6
    assert forced["compliance_v"] == 0.5
    assert "compliance_a" not in forced
    assert result["outputs"]["data"][0]["data"] == {"rows": []}


@pytest.mark.parametrize("name", ["C_flow_spot_smu_high_speed", "C_flow_spot_cmu_high_speed"])
def test_high_speed_does_not_add_mm_xe_or_buffer_read(name):
    result = getattr(flows, name)()
    assert not any(
        "execute" in n or "set_measurement_mode" in n or "read_measurement_data" in n
        for n in result["atoms_called"]
    )
    assert result["simulation_completed"]


def test_pulse_timing_precedes_source():
    result = flows.C_flow_pulse_smu_spot()
    names = result["atoms_called"]
    assert names.index("C_atom_smu_configure_pulse_timing") < names.index(
        "C_atom_smu_configure_pulsed_spot_source"
    )
    assert names.index("C_atom_smu_execute_pulsed_spot") < names.index(
        "C_atom_smu_read_measurement_data"
    )


def test_pending_execute_skips_read(monkeypatch):
    monkeypatch.setattr(
        c_atoms,
        "C_atom_smu_execute",
        lambda **_: {
            "fake": True,
            "hardware_touched": False,
            "parameters": {"status": "fake_started"},
        },
    )
    result = flows.C_flow_sweep_smu_staircase()
    assert result["execution_state"] == "awaiting_completion"
    assert not result["simulation_completed"]
    assert result["atom_results"][-1]["status"] == "skipped"
    assert "C_atom_smu_read_measurement_data" not in result["atoms_called"]


@pytest.mark.parametrize(
    "atom",
    [
        "C_atom_smu_configure_integration",
        "C_atom_smu_execute",
        "C_atom_smu_read_measurement_data",
    ],
)
def test_exceptions_retain_evidence_and_skip_later_work(monkeypatch, atom):
    def fail(**kwargs):
        raise RuntimeError("injected atom failure")

    monkeypatch.setattr(c_atoms, atom, fail)
    result = flows.C_flow_spot_smu_iv()
    assert not result["ok"]
    assert result["execution_state"] == "failed"
    records = result["atom_results"]
    failed_index = next(i for i, r in enumerate(records) if r["status"] == "error")
    assert records[failed_index]["atom"] == atom
    assert records[failed_index]["error"]["type"] == "RuntimeError"
    assert all(r["status"] == "ok" for r in records[:failed_index])
    assert all(r["status"] == "skipped" for r in records[failed_index + 1 :])
    assert atom in result["atoms_called"]
    assert result["cleanup"]["performed"] is False


def test_explicit_atom_failure_is_not_hidden(monkeypatch):
    original = c_atoms.C_atom_smu_execute

    def fail(**kwargs):
        payload = original(**kwargs)
        payload["parameters"]["result_code"] = -1
        return payload

    monkeypatch.setattr(c_atoms, "C_atom_smu_execute", fail)
    result = flows.C_flow_spot_smu_iv()
    assert not result["ok"]
    assert result["atom_results"][-2]["result"]["parameters"]["result_code"] == -1
    assert result["atom_results"][-1]["status"] == "skipped"


def test_unexpected_hardware_marker_stops_fake_runner(monkeypatch):
    monkeypatch.setattr(
        c_atoms,
        "C_atom_smu_configure_integration",
        lambda **_: {
            "fake": False,
            "hardware_touched": True,
        },
    )
    result = flows.C_flow_spot_smu_iv()
    assert result["hardware_touched"] is True
    assert result["fake"] is False
    assert not result["ok"]
    assert len(result["atoms_called"]) == 1


def test_spgu_handoff_never_stops_immediately():
    for result in (
        flows.C_flow_pulse_spgu_train(),
        flows.C_flow_waveform_spgu_sequence({"levels_v": [0, 0.1, 0]}),
    ):
        assert result["execution_state"] == "awaiting_completion"
        assert result["atoms_called"][-1] == "C_atom_spgu_start_output"
        assert "C_atom_spgu_stop_output" not in result["atoms_called"]
        assert result["outputs"]["data"] == []
        assert result["atom_results"][-1]["inputs"]["count"] > 0


def test_waveform_builds_all_channels_before_one_update_execute():
    second = {**WAVEFORM["channels"][0], "channel_id": 501, "pattern": "second"}
    result = flows.C_flow_waveform_wgfmu_acquire({"channels": WAVEFORM["channels"] + [second]})
    names = result["atoms_called"]
    assert names.count("C_atom_wgfmu_update") == names.count("C_atom_wgfmu_execute") == 1
    assert max(i for i, n in enumerate(names) if n == "C_atom_wgfmu_add_sequence") < names.index(
        "C_atom_wgfmu_update"
    )
    reads = [r for r in result["atom_results"] if r["phase"] == "read"]
    assert [r["inputs"]["channel_id"] for r in reads] == [502, 501]


@pytest.mark.parametrize(
    "model,values",
    [
        (schema.SmuSpot, {"compliance": -1}),
        (schema.SmuSpot, {"level": float("nan")}),
        (schema.SmuSpot, {"raw_command": "XE"}),
        (schema.SmuSweep, {"sweep_type": "log_positive", "start": 0}),
        (schema.PulseTiming, {"width_s": 1, "period_s": 0.1}),
        (schema.SynchronousSweep, {"channel": 2, "secondary_channel": 2}),
        (schema.MultiSweep, {"channels": [1, 1]}),
        (schema.SpguPulse, {"count": 0}),
        (schema.RemoteRepeat, {"repeat_count": 0}),
        (schema.WgfmuDc, {"points": 65536}),
        (schema.MeasureEvent, {"average_s": 1e-3, "interval_s": 1e-4}),
        (schema.WgfmuWaveform, {"channels": WAVEFORM["channels"] * 2}),
        (
            schema.WgfmuWaveform,
            {"channels": [{**WAVEFORM["channels"][0], "events": [{"time_s": 1.0}]}]},
        ),
    ],
)
def test_invalid_requests_fail_before_composition(model, values):
    with pytest.raises(ValidationError):
        model.model_validate(values)


def test_mcp_discovery_call_and_existing_capabilities():
    from b1500_test_agent.mcp.server import capabilities, mcp

    async def exercise():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert len(capabilities()["C_flows"]) == 30
            for function in flows.C_FLOW_FUNCTIONS:
                tool = tools[function.__name__]
                input_schema = (
                    tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema
                )
                assert "request" in input_schema["properties"]
                args = _request(function.__name__)
                result = await client.call_tool(
                    function.__name__, {"request": args} if args else {}
                )
                assert not result.is_error
            for family in ("A_atoms", "B_atoms", "C_atoms", "A_flows", "B_flows", "AB_flows"):
                assert set(capabilities()[family]) <= tools.keys()

    asyncio.run(exercise())


def test_reference_catalog_matches_registered_names():
    root = Path(__file__).resolve().parents[1]
    reference = root / ".agents/skills/b1500-semiconductor-testing/references/mcp-tools/c-flows.md"
    content = reference.read_text()
    for function in flows.C_FLOW_FUNCTIONS:
        assert f"`{function.__name__}`" in content
