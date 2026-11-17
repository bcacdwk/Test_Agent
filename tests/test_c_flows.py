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


VOLTAGE_BIAS = {"channel": 2, "level": 0.5, "compliance": 0.02, "irange": 0.1}
CURRENT_BIAS = {"channel": 3, "source": "current", "level": 1e-6, "compliance": 2.0}
BIASED = {
    "channel": 1,
    "bias_channels": [VOLTAGE_BIAS, CURRENT_BIAS],
    "measured_channels": [
        {"channel": 2},
        {"channel": 1, "ranging": {"range_mode": "fixed", "range_value": 1e-6}},
        {"channel": 3, "ranging": {"measure_function": "voltage", "module_type": "HRSMU"}},
    ],
}
BIASED_ATOMS = [
    "C_atom_smu_configure_integration",
    "C_atom_smu_set_measurement_ranging",
    "C_atom_smu_set_measurement_ranging",
    "C_atom_smu_set_measurement_ranging",
    "C_atom_smu_set_measurement_mode",
    "C_atom_smu_configure_sweep_timing",
    "C_atom_smu_configure_sweep_abort",
    "C_atom_smu_configure_staircase_sweep",
    "C_atom_smu_force_voltage",
    "C_atom_smu_force_current",
    "C_atom_smu_execute",
    "C_atom_smu_read_measurement_data",
]


def _request(name: str) -> dict:
    if name == "C_flow_waveform_wgfmu_acquire":
        return WAVEFORM
    if name == "C_flow_waveform_spgu_sequence":
        return {"levels_v": [0.0, 0.1, 0.0]}
    if name == "C_flow_sweep_smu_staircase_biased":
        return BIASED
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
            assert len(capabilities()["C_flows"]) == 31
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
    reference = root / "references/driver-map/legacy-catalog/c-flows.md"  # moved in WP0.4
    content = reference.read_text()
    for function in flows.C_FLOW_FUNCTIONS:
        assert f"`{function.__name__}`" in content


def test_biased_staircase_is_executable_c_only_composition():
    result = flows.C_flow_sweep_smu_staircase_biased(BIASED)
    assert result["atoms_called"] == BIASED_ATOMS
    assert [r["atom"] for r in result["atom_results"]] == BIASED_ATOMS
    assert (result["category"], result["object"], result["subject"]) == (
        "sweep",
        "smu",
        "staircase_biased",
    )
    assert result["execution_state"] == "simulated_complete"
    assert result["ok"] and not result["partial"] and result["simulation_completed"]
    assert result["contract_gaps"] == []
    assert result["fake"] and result["hardware_touched"] is False
    assert result["measurement_completed"] is False
    assert result["consumptive"] and result["cleanup"]["performed"] is False
    for record in result["atom_results"]:
        assert record["status"] == "ok"
        assert record["result"]["fake"] and record["result"]["hardware_touched"] is False
    inputs = [r["inputs"] for r in result["atom_results"]]
    assert [(i["channel"], i["measure_function"], i["range_mode"]) for i in inputs[1:4]] == [
        (2, "current", "auto"),
        (1, "current", "fixed"),
        (3, "voltage", "auto"),
    ]
    assert inputs[3]["module_type"] == "HRSMU"
    assert inputs[4] == {"mode": 2, "channels": "2,1,3"}
    assert inputs[7]["channel"] == 1 and inputs[7]["compliance"] == 0.001
    assert inputs[10] == {"timeout_s": 60.0, "operation": "staircase_biased"}
    reads = [r for r in result["atom_results"] if r["phase"] == "read"]
    assert len(reads) == 1 and reads[0]["atom"] == "C_atom_smu_read_measurement_data"
    assert result["outputs"]["data"] == [
        {"atom": "C_atom_smu_read_measurement_data", "data": {"rows": []}}
    ]
    assert [m["channel"] for m in result["inputs"]["measured_channels"]] == [2, 1, 3]
    json.dumps(result, allow_nan=False)


def test_biased_staircase_forwards_per_channel_compliance_units():
    result = flows.C_flow_sweep_smu_staircase_biased(
        schema.BiasedSweep.model_validate(
            {**BIASED, "source": "current", "start": 0.0, "stop": 1e-6, "compliance": 5.0}
        )
    )
    records = {r["atom"]: r for r in result["atom_results"]}
    sweep = records["C_atom_smu_configure_staircase_sweep"]["inputs"]
    assert (sweep["channel"], sweep["source"], sweep["compliance"]) == (1, "current", 5.0)
    voltage = records["C_atom_smu_force_voltage"]
    assert voltage["inputs"] == {
        "channel": 2,
        "voltage_v": 0.5,
        "compliance_a": 0.02,
        "irange": 0.1,
        "range_mode": "auto",
        "comp_polarity": "auto",
    }
    assert voltage["result"]["parameters"]["compliance_a"] == 0.02
    current = records["C_atom_smu_force_current"]
    assert current["inputs"]["channel"] == 3
    assert current["inputs"]["current_a"] == 1e-6
    assert current["inputs"]["compliance_v"] == 2.0
    assert "compliance_a" not in current["inputs"] and "irange" not in current["inputs"]
    assert current["result"]["parameters"]["compliance_v"] == 2.0


def _biased(**changes) -> dict:
    return {**BIASED, **changes}


@pytest.mark.parametrize(
    "values,match",
    [
        (_biased(bias_channels=[VOLTAGE_BIAS, VOLTAGE_BIAS, CURRENT_BIAS]), "Bias channels"),
        (_biased(measured_channels=[{"channel": 2}, {"channel": 2}]), "Measured channels must"),
        (_biased(channel=2, measured_channels=[{"channel": 2}]), "swept channel must not"),
        (_biased(bias_channels=[{"channel": 2, "level": 0.5}, CURRENT_BIAS]), "0.compliance"),
        (_biased(bias_channels=[{**VOLTAGE_BIAS, "compliance": 0}, CURRENT_BIAS]), "0.compliance"),
        (_biased(bias_channels=[{"channel": 2, "compliance": 0.02}, CURRENT_BIAS]), "0.level"),
        (_biased(measured_channels=[{"channel": 4}]), "swept channel or bias channels"),
        (_biased(bias_channels=[]), "bias_channels"),
        (_biased(measured_channels=[]), "measured_channels"),
        ({k: v for k, v in BIASED.items() if k != "measured_channels"}, "measured_channels"),
        ({k: v for k, v in BIASED.items() if k != "channel"}, "(?m)^channel$"),
        (_biased(steps=1), "(?m)^steps$"),
        (_biased(steps=100_001), "(?m)^steps$"),
        (_biased(steps=40_000), "element bound"),
        (_biased(bias_channels=[VOLTAGE_BIAS, {**CURRENT_BIAS, "irange": 1e-3}]), "irange"),
        (_biased(sweep_type="log_positive", start=0.0), "logarithmic"),
        (_biased(raw_command="XE"), "raw_command"),
    ],
)
def test_biased_staircase_rejects_invalid_requests_before_any_atom(monkeypatch, values, match):
    calls = []
    for name in dir(c_atoms):
        if name.startswith("C_atom_"):
            monkeypatch.setattr(c_atoms, name, lambda _name=name, **_: calls.append(_name))
    with pytest.raises(ValidationError, match=match):
        flows.C_flow_sweep_smu_staircase_biased(values)
    assert calls == []


@pytest.mark.parametrize(
    "atom,index",
    [
        ("C_atom_smu_set_measurement_ranging", 1),
        ("C_atom_smu_force_current", 9),
        ("C_atom_smu_execute", 10),
        ("C_atom_smu_read_measurement_data", 11),
    ],
)
def test_biased_staircase_failure_keeps_audit_and_skips_later_steps(monkeypatch, atom, index):
    def fail(**kwargs):
        raise RuntimeError("injected atom failure")

    monkeypatch.setattr(c_atoms, atom, fail)
    result = flows.C_flow_sweep_smu_staircase_biased(BIASED)
    records = result["atom_results"]
    assert [r["atom"] for r in records] == BIASED_ATOMS
    assert not result["ok"] and result["partial"]
    assert result["execution_state"] == "failed"
    assert not result["simulation_completed"]
    assert records[index]["status"] == "error"
    assert records[index]["error"] == {"type": "RuntimeError", "message": "injected atom failure"}
    assert records[index]["inputs"] and records[index]["timestamp"]
    assert all(r["status"] == "ok" and r["result"]["fake"] for r in records[:index])
    assert all(r["status"] == "skipped" and r["result"] is None for r in records[index + 1 :])
    assert result["atoms_called"] == BIASED_ATOMS[: index + 1]
    assert result["consumptive"] is (atom == "C_atom_smu_read_measurement_data")
    assert result["fake"] and result["hardware_touched"] is False
    assert result["cleanup"]["performed"] is False
    assert any(atom in warning for warning in result["warnings"])


def test_biased_staircase_bias_failure_status_blocks_execution(monkeypatch):
    original = c_atoms.C_atom_smu_force_voltage

    def fail(**kwargs):
        payload = original(**kwargs)
        payload["parameters"]["result_code"] = -1
        return payload

    monkeypatch.setattr(c_atoms, "C_atom_smu_force_voltage", fail)
    result = flows.C_flow_sweep_smu_staircase_biased(BIASED)
    records = {r["atom"]: r for r in result["atom_results"]}
    assert not result["ok"] and result["execution_state"] == "failed"
    assert records["C_atom_smu_force_voltage"]["result"]["parameters"]["result_code"] == -1
    for skipped in BIASED_ATOMS[9:]:
        assert records[skipped]["status"] == "skipped"
        assert skipped not in result["atoms_called"]


def test_biased_staircase_mcp_schema_and_rejection():
    from b1500_test_agent.mcp.server import mcp

    name = "C_flow_sweep_smu_staircase_biased"

    async def exercise():
        async with Client(mcp) as client:
            tool = {t.name: t for t in await client.list_tools()}[name]
            input_schema = tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema
            assert input_schema["required"] == ["request"]

            def resolve(node: dict) -> dict:
                ref = node.get("$ref")
                return resolve(input_schema["$defs"][ref.split("/")[-1]]) if ref else node

            request = resolve(input_schema["properties"]["request"])
            assert set(request["required"]) == {"channel", "bias_channels", "measured_channels"}
            bias = resolve(request["properties"]["bias_channels"]["items"])
            assert {"channel", "level", "compliance"} <= set(bias["required"])
            measured = resolve(request["properties"]["measured_channels"]["items"])
            assert "ranging" in measured["properties"]
            accepted = await client.call_tool(name, {"request": BIASED})
            assert not accepted.is_error
            rejected = await client.call_tool(
                name, {"request": _biased(channel=2)}, raise_on_error=False
            )
            assert rejected.is_error

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "flow,values",
    [
        (flows.C_flow_sweep_cmu_cf, {"start": 0.0, "stop": 1e6}),
        (flows.C_flow_sweep_cmu_cf, {"start": 1e6, "stop": -1e3}),
        (flows.C_flow_sweep_cmu_ac_level, {"start": -0.1, "stop": 0.1}),
        (flows.C_flow_sweep_cmu_ac_level, {"start": 0.0, "stop": 0.1}),
    ],
)
def test_cmu_cf_and_ac_level_endpoints_fail_in_the_request_schema(monkeypatch, flow, values):
    """Non-positive endpoints are a request ValidationError before any atom (not a ValueError)."""
    calls = []
    for name in dir(c_atoms):
        if name.startswith("C_atom_"):
            monkeypatch.setattr(c_atoms, name, lambda _name=name, **_: calls.append(_name))
    with pytest.raises(ValidationError, match="endpoints must be positive"):
        flow(values)
    with pytest.raises(ValidationError, match="endpoints must be positive"):
        schema.CmuPositiveSweep.model_validate(values)
    assert calls == []


def test_cmu_cv_sweep_keeps_signed_endpoints():
    assert flows.C_flow_sweep_cmu_cv({"start": -1.0, "stop": 1.0})["ok"]
    assert schema.CmuSweep.model_validate({"start": -1.0, "stop": 0.0}).start == -1.0
