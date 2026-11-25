"""``WgfmuDll`` marshalling against the ctypes-shaped fake library (blueprint v2 7.1 "WGFMU fake-ABI", 8.1
``wgfmu_abi/``; WP10.2): lazy load after the probe, ``argtypes``/``restype`` from the generated table, exactly the C
functions of ``api.C_FUNCTIONS`` per protocol method, ASCII ``c_char_p`` strings, ``wgfmu.h`` codes for the Python
literals, numpy buffers for vectors, out-parameters through ``byref``. Every call passes the fake's ctypes check
(argument count and each argtype's ``from_param``), so a marshalling slip fails here as it would in ctypes."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import C_FUNCTIONS, WgfmuError
from b1500_test_agent.transport.wgfmu.dll import C_SIGNATURES, WgfmuDll, argtypes_of
from tests.wgfmu_abi.conftest import Binding
from tests.wgfmu_abi.fake_lib import array, ctype_name, load

pytestmark = pytest.mark.wgfmu

ADDRESS = "GPIB0::17::INSTR"

SEQUENCE: list[tuple[str, tuple]] = [
    ("open_session", (ADDRESS,)), ("set_timeout", (100.0,)), ("initialize", ()), ("clear", ()), ("channel_ids", ()),
    ("set_warning_level", ("information",)), ("warning_level", ()), ("treat_warnings_as_errors", ("off",)),
    ("set_operation_mode", (101, "fastiv")), ("set_force_voltage_range", (101, "5v")),
    ("set_measure_mode", (101, "current")), ("set_measure_current_range", (101, "1ma")),
    ("set_measure_enabled", (101, True)), ("set_operation_mode", (102, "fastiv")),
    ("set_measure_mode", (102, "voltage")), ("set_measure_voltage_range", (102, "5v")),
    ("create_pattern", ("p", 0.0)), ("add_vectors", ("p", [1e-6, 1e-6], [1.0, 0.0])),
    ("set_measure_event", ("p", "m", 0.0, 10, 1e-7, 0.0, False)), ("set_range_event", ("p", "r", 1.5e-6, "10ma")),
    ("create_pattern", ("q", 0.0)), ("add_vectors", ("q", [2e-6], [0.5])),
    ("add_sequence", (101, "p", 1.0)), ("add_sequence", (102, "q", 1.0)), ("update", ()), ("connect", (101,)),
    ("execute", ()), ("wait_until_completed", ()), ("status", ()), ("channel_status", (101,)),
    ("measure_value_size", (101,)), ("measure_values", (101, 0, 10)),
    ("measure_values", (101, 5, 10)), ("warnings", ()),  # offset + size beyond the data: a normal warning
    ("abort", ()), ("disconnect", (101,)),
    ("set_operation_mode", (102, "dc")), ("dc_force_voltage", (102, 0.5)), ("dc_measure_value", (102,)),
    ("self_test", ()), ("self_calibration", ()), ("errors", ()), ("close_session", ()),
]
"""Every protocol method once (and a few twice), in an order the library accepts."""


def test_nothing_loads_before_the_first_call_and_the_table_is_bound(binding: Binding) -> None:
    dll = binding.dll
    assert not dll.loaded and binding.loads == []
    assert dll.probe().loadable  # a file read only
    assert binding.loads == []
    dll.clear()
    assert dll.loaded and binding.loads == [dll.path]
    lib = binding.lib
    for name in C_SIGNATURES:
        func = getattr(lib, name)
        assert [ctype_name(t) for t in func.argtypes] == [ctype_name(t) for t in argtypes_of(name)], name
        assert ctype_name(func.restype) == "c_int"
    dll.clear()
    assert binding.loads == [dll.path]  # loaded once


def test_every_method_calls_exactly_its_c_functions(binding: Binding) -> None:
    dll = binding.dll
    seen: set[str] = set()
    for method, args in SEQUENCE:
        before = len(binding.lib.calls) if dll.loaded else 0
        getattr(dll, method)(*args)
        names = [c.name for c in binding.lib.calls[before:]]
        expected = list(C_FUNCTIONS[method])
        if method == "channel_ids":
            assert names == ["WGFMU_getChannelIdSize", "WGFMU_getChannelIds"]
        elif method == "errors":
            assert names == ["WGFMU_getErrorSize"]  # nothing queued: one size query ends the drain
        elif method == "warnings":  # the size first, then the summary (WG p119 (4-49))
            assert names == ["WGFMU_getWarningSummarySize", "WGFMU_getWarningSummary"]
        else:
            assert names == expected[:1], (method, names)
        seen.add(method)
    assert seen == set(api.API_METHODS)
    assert {c.name for c in binding.lib.calls} == set(C_SIGNATURES) - {"WGFMU_getError"}


def test_strings_go_in_as_ascii_bytes(binding: Binding) -> None:
    dll = binding.dll
    dll.open_session(ADDRESS)
    dll.create_pattern("pulse", 0.25)
    dll.add_sequence(101, "pulse", 3)
    calls = {c.name: c.args for c in binding.lib.calls}
    assert calls["WGFMU_openSession"] == (b"GPIB0::17::INSTR",)
    assert calls["WGFMU_createPattern"] == (b"pulse", 0.25)
    assert calls["WGFMU_addSequence"] == (101, b"pulse", 3.0)
    assert binding.st.sim.session == ADDRESS and "pulse" in binding.st.sim._patterns


@pytest.mark.parametrize("bad", ["pulsé", "", "a\0b", 5, None, b"bytes"])
def test_a_string_that_is_not_plain_ascii_is_refused_before_the_library(binding: Binding, bad: object) -> None:
    with pytest.raises(WgfmuError) as caught:
        binding.dll.create_pattern(bad, 0.0)  # type: ignore[arg-type]
    err = caught.value
    assert (err.wgfmu_code, err.rc, err.function) == (api.ILLEGAL_STRING, api.ILLEGAL_STRING, "create_pattern")
    assert not binding.dll.loaded  # nothing reached (or even loaded) the library


TABLES = [
    ("set_operation_mode", api.OPERATION_MODES, "WGFMU_setOperationMode"),
    ("set_force_voltage_range", api.FORCE_VOLTAGE_RANGES, "WGFMU_setForceVoltageRange"),
    ("set_measure_mode", api.MEASURE_MODES, "WGFMU_setMeasureMode"),
    ("set_measure_current_range", api.MEASURE_CURRENT_RANGES, "WGFMU_setMeasureCurrentRange"),
    ("set_measure_voltage_range", api.MEASURE_VOLTAGE_RANGES, "WGFMU_setMeasureVoltageRange"),
]


@pytest.mark.parametrize(("method", "table", "c_name"), TABLES, ids=[t[0] for t in TABLES])
def test_literals_become_the_header_codes(binding: Binding, method: str, table: dict, c_name: str) -> None:
    dll = binding.dll
    dll.open_session(ADDRESS)
    for literal, code in table.items():
        getattr(dll, method)(101, literal)
        assert binding.lib.calls[-1].name == c_name and binding.lib.calls[-1].args == (101, code), literal
    count = len(binding.lib.calls)
    for bad in ("turbo", True, None, ["5v"]):
        with pytest.raises(WgfmuError) as caught:
            getattr(dll, method)(101, bad)
        assert caught.value.wgfmu_code == api.PARAMETER_OUT_OF_RANGE and caught.value.function == method
    assert len(binding.lib.calls) == count  # refused before the library


def test_flags_and_the_raw_data_mode(binding: Binding) -> None:
    dll = binding.dll
    dll.open_session(ADDRESS)
    dll.set_measure_enabled(101, True)
    dll.set_measure_enabled(101, False)
    assert [c.args for c in binding.lib.calls[-2:]] == [(101, 7001), (101, 7000)]
    with pytest.raises(WgfmuError, match="status 1"):
        dll.set_measure_enabled(101, 1)  # type: ignore[arg-type]
    dll.create_pattern("p", 0.0)
    dll.add_vectors("p", [1e-6], [0.0])
    dll.set_measure_event("p", "raw", 0.0, 4, 1e-7, 2e-8, True)
    dll.set_measure_event("p", "avg", 5e-7, 4, 1e-7, 2e-8, False)
    raw, averaged = binding.lib.calls[-2:]
    assert raw.args == (b"p", b"raw", 0.0, 4, 1e-7, 2e-8, api.MEASURE_EVENT_DATA[True]) == (
        b"p", b"raw", 0.0, 4, 1e-7, 2e-8, 12001)
    assert averaged.args[-1] == 12000


@pytest.mark.parametrize(("method", "args"), [
    ("connect", (True,)), ("connect", ("101",)), ("connect", (101.0,)), ("connect", (2 ** 31,)),
    ("set_timeout", (float("nan"),)), ("set_timeout", ("100",)), ("dc_force_voltage", (101, float("inf"))),
    ("set_measure_event", ("p", "e", 0.0, 1.5, 1e-7, 0.0, False)), ("measure_values", (101, 0, 0)),
])
def test_numbers_must_be_real_c_values(binding: Binding, method: str, args: tuple) -> None:
    with pytest.raises(WgfmuError) as caught:
        getattr(binding.dll, method)(*args)
    assert caught.value.wgfmu_code == api.PARAMETER_OUT_OF_RANGE and caught.value.function == method
    assert not binding.dll.loaded


def test_numpy_scalars_are_plain_c_values(binding: Binding) -> None:
    dll = binding.dll
    dll.open_session(ADDRESS)
    dll.connect(np.int64(101))  # type: ignore[arg-type]
    dll.set_timeout(np.float32(50.0))  # type: ignore[arg-type]
    connect, timeout = binding.lib.calls[-2:]
    assert connect.args == (101,) and type(connect.args[0]) is int
    assert timeout.args == (50.0,) and type(timeout.args[0]) is float


def test_vectors_go_in_as_contiguous_float64_buffers(binding: Binding) -> None:
    dll = binding.dll
    dll.create_pattern("p", 0.0)
    strided = np.array([1e-6, 9.9, 2e-6, 9.9, 3e-6], dtype=np.float64)[::2]  # not contiguous
    levels = np.array([1, 2, 3], dtype=np.int32)  # integers become doubles
    dll.add_vectors("p", strided, levels)
    call = binding.lib.calls[-1]
    assert call.name == "WGFMU_addVectors" and call.args[0] == b"p" and call.args[3] == 3
    assert array(call.args[1], 3).tolist() == [1e-6, 2e-6, 3e-6]
    assert array(call.args[2], 3).tolist() == [1.0, 2.0, 3.0]
    assert ctype_name(type(call.args[1])) == "LP_c_double"
    spec = binding.st.sim._patterns["p"]
    assert spec.dts == [100, 200, 300] and spec.volts == [1.0, 2.0, 3.0]  # 10 ns ticks


@pytest.mark.parametrize(("dt", "v"), [([1e-6, 2e-6], [1.0]), ([], []), (["x"], [1.0]), ([1e-6], [float("nan")])])
def test_bad_vectors_are_refused_before_the_library(binding: Binding, dt: list, v: list) -> None:
    with pytest.raises(WgfmuError) as caught:
        binding.dll.add_vectors("p", dt, v)
    assert caught.value.wgfmu_code == api.PARAMETER_OUT_OF_RANGE and not binding.dll.loaded


def test_out_parameters_are_read_back(binding: Binding) -> None:
    dll = binding.dll
    dll.open_session(ADDRESS)
    assert dll.channel_ids() == [101, 102]
    size_call, ids_call = binding.lib.calls[-2:]
    assert size_call.name == "WGFMU_getChannelIdSize" and load(size_call.args[0]) == 2
    assert load(ids_call.args[1]) == 2 and ctype_name(type(ids_call.args[0])) == "LP_c_int"
    status = dll.status()
    assert status == (api.STATUS_IDLE, 0.0, 0.0) and [type(x) for x in status] == [int, float, float]
    assert dll.channel_status(101) == (api.STATUS_IDLE, 0.0, 0.0)
    assert dll.measure_value_size(101) == (0, 0)
    dll.set_operation_mode(101, "dc")
    dll.dc_force_voltage(101, 0.75)
    dll.set_measure_mode(101, "voltage")
    dll.connect(101)
    assert dll.dc_measure_value(101) == pytest.approx(0.75)
    assert dll.self_test() == 0 and dll.last_detail == "PASS"


def test_the_fake_checks_marshalling_like_ctypes(bind, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a wrong table entry the fake's ctypes check refuses the call (``from_param``), as ctypes raises
    ``ArgumentError``; the binding reports it as a library error."""
    monkeypatch.setitem(C_SIGNATURES, "WGFMU_connect", ("const char*",))
    binding = bind()
    with pytest.raises(WgfmuError) as caught:
        binding.dll.connect(101)
    err = caught.value
    assert err.wgfmu_code == api.LIBRARY_ERROR and "WGFMU_connect raised TypeError" in str(err)
    assert binding.lib.calls == []  # refused before the function ran


def test_the_binding_is_a_runtime_wgfmu_api(binding: Binding) -> None:
    assert isinstance(binding.dll, api.WgfmuApi) and isinstance(binding.st.wg, api.WgfmuApi)
    import inspect

    for name in api.API_METHODS:
        expected = list(inspect.signature(getattr(api.WgfmuApi, name)).parameters)
        assert list(inspect.signature(getattr(WgfmuDll, name)).parameters) == expected, name
