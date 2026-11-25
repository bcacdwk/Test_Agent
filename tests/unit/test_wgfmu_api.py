"""``transport.wgfmu.api`` (blueprint v2 2.4): the protocol is exactly the blueprint's, its constants and error texts
match the manual extracts, and the simulator and the audit wrapper implement it with the same signatures."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.models.sim import LIBRARY_FUNCTIONS
from b1500_test_agent.models.sources import MeasureEvent
from b1500_test_agent.transport.base import TransportError
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuApi, WgfmuError
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu

pytestmark = pytest.mark.wgfmu

ROOT = Path(__file__).resolve().parents[2]
STRUCTURED = ROOT / "references" / "manuals" / "structured"
API_YAML = yaml.safe_load((STRUCTURED / "b1530a-wgfmu-api-reference.yaml").read_text(encoding="utf-8"))
ERRORS_YAML = yaml.safe_load((STRUCTURED / "b1530a-wgfmu-error-codes.yaml").read_text(encoding="utf-8"))

BLUEPRINT_METHODS = [
    "open_session", "close_session", "initialize", "clear", "set_timeout", "channel_ids", "set_operation_mode",
    "set_force_voltage_range", "set_measure_mode", "set_measure_current_range", "set_measure_voltage_range",
    "set_measure_enabled", "create_pattern", "add_vectors", "set_measure_event", "set_range_event", "add_sequence",
    "update", "connect", "disconnect", "execute", "wait_until_completed", "abort", "status", "channel_status",
    "measure_value_size", "measure_values", "dc_force_voltage", "dc_measure_value", "self_test", "self_calibration",
    "errors",
]
"""The methods of ``WgfmuApi`` in blueprint v2 2.4, in its order."""
WARNING_METHODS = ["set_warning_level", "warning_level", "treat_warnings_as_errors", "warnings"]
"""The warning queue of blueprint v2 1.2 ("error/warning queues"), added after them (WP10.8; orchestrator decision)."""


def _protocol_methods() -> list[str]:
    return [name for name, value in vars(WgfmuApi).items() if inspect.isfunction(value) and not name.startswith("_")]


def test_protocol_is_exactly_the_blueprint_one() -> None:
    methods = BLUEPRINT_METHODS + WARNING_METHODS
    assert _protocol_methods() == methods == list(api.API_METHODS) == list(LIBRARY_FUNCTIONS)
    assert list(api.C_FUNCTIONS) == methods


@pytest.mark.parametrize("impl", [SimWgfmu, AuditingWgfmu])
def test_implementations_have_the_protocol_signatures(impl: type) -> None:
    for name in BLUEPRINT_METHODS + WARNING_METHODS:
        expected = list(inspect.signature(getattr(WgfmuApi, name)).parameters)
        assert list(inspect.signature(getattr(impl, name)).parameters) == expected, name


def test_simulator_and_wrapper_are_runtime_instances(tmp_path: Path) -> None:
    from b1500_test_agent.transport.audit import MemoryAuditSink
    from tests.sim.wgfmu_examples import station

    st = station()
    assert isinstance(st.sim, WgfmuApi) and isinstance(AuditingWgfmu(st.sim, MemoryAuditSink(), backend="sim"),
                                                       WgfmuApi)


def _yaml_functions() -> set[str]:
    names: set[str] = set()
    for item in API_YAML["api_items"]:
        if item["type"] == "function":
            names.update(part.strip() for part in item["name"].split("/"))
    return names


def test_every_c_function_is_documented_in_the_api_extract() -> None:
    documented = _yaml_functions()
    used = {fn for fns in api.C_FUNCTIONS.values() for fn in fns}
    assert used <= documented, sorted(used - documented)


def _parse_limits(text: str) -> dict[str, int]:
    return {k.strip(): int(v) for k, v in (pair.split("=") for pair in text.split(","))}


def test_constants_match_the_api_extract() -> None:
    items = {item["name"]: item for item in API_YAML["api_items"]}
    c = api.LIBRARY_CONSTANTS
    for name, value in items["Operation mode constants"]["limits"].items():
        assert c[name] == value
    for name, value in items["Self-test/calibration return codes"]["limits"].items():
        assert c[name] == value

    def param(item: str, index: int) -> dict[str, int]:
        return _parse_limits(items[item]["parameters"][index]["limits"])

    ranges = param("WGFMU_setForceVoltageRange / WGFMU_getForceVoltageRange", 1)
    assert [ranges[k] for k in ("AUTO", "3V", "5V", "-10V", "+10V")] == list(api.FORCE_VOLTAGE_RANGES.values())
    modes = param("WGFMU_setMeasureMode / WGFMU_getMeasureMode", 1)
    assert [modes["VOLTAGE"], modes["CURRENT"]] == list(api.MEASURE_MODES.values())
    currents = param("WGFMU_setMeasureCurrentRange / WGFMU_getMeasureCurrentRange", 1)
    assert list(currents.values()) == list(api.MEASURE_CURRENT_RANGES.values())
    volts = param("WGFMU_setMeasureVoltageRange / WGFMU_getMeasureVoltageRange", 1)
    assert list(volts.values()) == list(api.MEASURE_VOLTAGE_RANGES.values())
    enabled = param("WGFMU_setMeasureEnabled / WGFMU_isMeasureEnabled", 1)
    assert [enabled["DISABLE"], enabled["ENABLE"]] == [api.MEASURE_ENABLED[False], api.MEASURE_ENABLED[True]]
    rdata = param("WGFMU_setMeasureEvent", 6)
    assert [rdata["AVERAGED"], rdata["RAW"]] == [api.MEASURE_EVENT_DATA[False], api.MEASURE_EVENT_DATA[True]]
    modes = param("WGFMU_setOperationMode / WGFMU_getOperationMode", 1)
    assert [modes[k] for k in ("DC", "FASTIV", "PG", "SMU")] == list(api.OPERATION_MODES.values())


def test_error_and_status_codes_match_the_error_extract() -> None:
    records = {r["code"]: r for r in ERRORS_YAML["records"]}
    for code, name in api.LIBRARY_ERROR_NAMES.items():
        assert records[code]["message"] == name
    assert set(api.LIBRARY_ERROR_NAMES) == set(range(-15, 0)) == set(api.LIBRARY_ERRORS)
    for name in ("WGFMU_NO_ERROR",) + tuple(f"WGFMU_STATUS_{s}" for s in (
            "COMPLETED", "DONE", "RUNNING", "ABORT_COMPLETED", "ABORTED", "RUNNING_ILLEGAL", "IDLE")) + tuple(
            f"WGFMU_WARNING_LEVEL_{w}" for w in ("OFF", "SEVERE", "NORMAL", "INFORMATION")):
        assert records[api.LIBRARY_CONSTANTS[name]]["message"] == name
    for code, message in api.OPERATION_ERRORS.items():
        assert records[code]["message"] == message, code
    assert {3050, *range(3304, 3317)} <= set(api.OPERATION_ERRORS)


def test_limits_agree_with_the_driver_module_spec_and_the_program_model() -> None:
    lim = api.LIMITS
    assert (lim["max_vectors"], lim["max_sequences"], lim["memory_points"]) == (
        WGFMU_SPEC.max_vectors, WGFMU_SPEC.max_sequences, WGFMU_SPEC.max_points)
    assert (lim["vector_dt_min_s"], lim["vector_dt_max_s"]) == WGFMU_SPEC.vector_dt_s
    assert (lim["interval_min_s"], lim["interval_max_s"]) == WGFMU_SPEC.interval_s
    assert (lim["average_min_s"], lim["average_max_s"]) == WGFMU_SPEC.average_s
    assert (lim["count_min"], lim["count_max"]) == WGFMU_SPEC.sequence_count
    assert lim["grid_s"] == WGFMU_SPEC.grid_s and lim["range_event_spacing_s"] == WGFMU_SPEC.range_event_spacing_s
    assert api.CURRENT_RANGE_A == WGFMU_SPEC.current_ranges
    assert {k: v for k, v in WGFMU_SPEC.force_ranges.items() if k != "auto"} == api.FORCE_RANGE_BOUNDS
    assert api.PG_FORCE_RANGES == WGFMU_SPEC.pg_force_ranges and api.PG_OUTPUT_OHM == WGFMU_SPEC.pg_output_ohm
    assert api.CURRENT_MODES == WGFMU_SPEC.current_modes
    event = MeasureEvent(pattern="p", event="e", t=0.0, points=10, interval=1e-7, average=2e-8, raw=True)
    assert event.data_points == 10 * (1 + int(2e-8 / lim["raw_sample_s"] + 1e-9))


def test_channel_ids() -> None:
    assert api.channel_ids_of([5, 2]) == [201, 202, 501, 502]
    assert all(api.is_channel_id(c) for c in (101, 102, 1001, 1002))
    assert not any(api.is_channel_id(c) for c in (1, 100, 103, 1101, True, "101", 101.0))


def test_wgfmu_error_carries_codes_and_maps_to_result_codes() -> None:
    fw = WgfmuError(3050, "firmware error 3050: Measurement data memory overflow error.", function="execute")
    assert isinstance(fw, TransportError)
    assert (fw.wgfmu_code, fw.rc, fw.code, fw.function) == (3050, -6, "instrument_error", "execute")
    assert str(fw) == "execute: firmware error 3050: Measurement data memory overflow error."
    lib = WgfmuError(-10, "add_vectors: -10 ...", function="add_vectors")
    assert (lib.rc, lib.code, str(lib)) == (-10, "instrument_error", "add_vectors: -10 ...")
    comm = WgfmuError(-5, "timeout")
    assert comm.code == "transport_error" and str(comm) == "timeout"


def test_error_text() -> None:
    assert api.error_text(-1, "dt 5e-09 s") == ("-1 WGFMU_PARAMETER_OUT_OF_RANGE_ERROR: Invalid parameter value "
                                                "was found. It will be out of the range. dt 5e-09 s")
    assert api.error_text(3304) == "firmware error 3304: Specified ALWG Vector Data size is out of absolute limits."
    assert re.match(r"^firmware error 3999: Firmware error was found\.$", api.error_text(3999))
