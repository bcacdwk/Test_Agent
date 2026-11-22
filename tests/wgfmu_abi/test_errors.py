"""Return codes and error strings of the WGFMU binding (blueprint v2 2.4 "rc < 0 -> WgfmuError(code, summary)", 7.1
"error strings"; WP10.2): a negative code raises ``WgfmuError`` carrying the library's error string (read with
``WGFMU_getErrorSize``/``WGFMU_getError``, WG p97 (4-27)), the firmware code of a ``WGFMU_FW_ERROR`` and the result
code (``transport_error`` for a communication error, else ``instrument_error``); the string stays available to
``errors()`` as it does on the simulator; crashes, missing exports and unloadable libraries become
``WGFMU_LIBRARY_ERROR`` before anything else happens."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu
from b1500_test_agent.transport.wgfmu.dll import C_SIGNATURES, WgfmuDll
from tests.sim import wgfmu_examples as wx
from tests.wgfmu_abi.conftest import Binding
from tests.wgfmu_abi.fake_lib import FakeWgfmuLibrary
from tests.wgfmu_abi.pe_builder import X86, write_dll

pytestmark = pytest.mark.wgfmu

ADDRESS = "GPIB0::17::INSTR"


def _duplicate_pattern(wg: object) -> WgfmuError:
    wg.create_pattern("p", 0.0)  # type: ignore[attr-defined]
    with pytest.raises(WgfmuError) as caught:
        wg.create_pattern("p", 0.0)  # type: ignore[attr-defined]
    return caught.value


def test_a_library_error_matches_the_simulator_exactly(binding: Binding) -> None:
    direct = _duplicate_pattern(wx.station().sim)
    via = _duplicate_pattern(binding.dll)
    assert (via.wgfmu_code, via.rc, via.text, via.function, via.code, str(via)) == (
        direct.wgfmu_code, direct.rc, direct.text, direct.function, direct.code, str(direct))
    assert via.wgfmu_code == api.PATTERN_ALREADY_EXISTS and "WGFMU_PATTERN_ALREADY_EXISTS_ERROR" in via.text
    names = [c.name for c in binding.lib.calls]
    # the failure drains the queue (the last string belongs to this call): size, string, size = 0
    assert names[-4:] == ["WGFMU_createPattern", "WGFMU_getErrorSize", "WGFMU_getError", "WGFMU_getErrorSize"]
    # the string was read for the exception and is still reported by errors(), as on the simulator
    assert binding.dll.errors() == [via.text] and binding.dll.errors() == []


def test_firmware_errors_carry_the_firmware_code(bind) -> None:
    binding = bind()
    dll = binding.dll
    dll.create_pattern("long", 0.0)
    dll.add_vectors("long", [1e-6] * 2049, [0.0] * 2049)  # one vector more than a pattern holds
    dll.add_sequence(101, "long", 1)
    dll.open_session(ADDRESS)
    dll.set_operation_mode(101, "fastiv")
    with pytest.raises(WgfmuError) as caught:
        dll.update()
    err = caught.value
    assert (err.wgfmu_code, err.rc, err.code, err.function) == (3304, api.FW_ERROR, "instrument_error", "update")
    assert "3304" in err.text


@pytest.mark.parametrize(("rc", "text", "code", "result"), [
    (api.FW_ERROR, "WGFMU_execute: Firmware error was found. 3050 Measurement data memory overflow error.", 3050,
     "instrument_error"),
    (api.FW_ERROR, "WGFMU_execute: Firmware error was found.", api.FW_ERROR, "instrument_error"),
    (api.FW_ERROR, "firmware error 13050 (not a firmware code)", api.FW_ERROR, "instrument_error"),
    (api.COMMUNICATION_ERROR, "WGFMU_execute: IO library error was found.", api.COMMUNICATION_ERROR,
     "transport_error"),
    (api.CONTEXT_ERROR, "", api.CONTEXT_ERROR, "instrument_error"),
])
def test_return_codes_become_wgfmu_errors(binding: Binding, rc: int, text: str, code: int, result: str) -> None:
    binding.dll.clear()
    binding.lib.fail("WGFMU_execute", rc, text)
    with pytest.raises(WgfmuError) as caught:
        binding.dll.execute()
    err = caught.value
    assert (err.wgfmu_code, err.rc, err.code, err.function) == (code, rc, result, "execute")
    if text:
        assert err.text == text
    else:  # nothing queued: the manual's description of the code
        assert err.text == f"execute: {api.error_text(rc)}" and "Context error" in err.text
    assert str(err).startswith("execute: ")


def test_older_queued_strings_are_kept_and_the_last_one_explains_the_failure(binding: Binding) -> None:
    binding.dll.clear()
    binding.lib.pending.extend(["older 1", "older 2"])
    binding.lib.fail("WGFMU_update", api.UNIDENTIFIED_ERROR, "update: the latest")
    with pytest.raises(WgfmuError, match="the latest"):
        binding.dll.update()
    assert binding.dll.errors() == ["older 1", "older 2", "update: the latest"]


def test_clear_also_empties_the_strings_read_for_exceptions(binding: Binding) -> None:
    _duplicate_pattern(binding.dll)
    binding.dll.clear()
    assert binding.dll.errors() == []


def test_errors_drains_the_queue_oldest_first(binding: Binding) -> None:
    dll = binding.dll
    dll.clear()
    binding.lib.pending.extend(["first", "second"])
    assert dll.errors() == ["first", "second"] and dll.errors() == []
    names = [c.name for c in binding.lib.calls[1:]]
    assert names == ["WGFMU_getErrorSize", "WGFMU_getError", "WGFMU_getErrorSize", "WGFMU_getError",
                     "WGFMU_getErrorSize", "WGFMU_getErrorSize"]


def test_a_crash_in_the_library_is_a_library_error(binding: Binding) -> None:
    binding.dll.clear()
    binding.lib.crash("WGFMU_execute", OSError("exception: access violation reading 0x00000000"))
    with pytest.raises(WgfmuError) as caught:
        binding.dll.execute()
    err = caught.value
    assert err.wgfmu_code == api.LIBRARY_ERROR and err.function == "execute"
    assert "WGFMU_execute raised OSError: exception: access violation" in err.text


def test_a_library_without_an_export_fails_before_any_call(bind) -> None:
    binding = bind(exports=sorted(set(C_SIGNATURES) - {"WGFMU_getStatus", "WGFMU_abort"}))
    with pytest.raises(WgfmuError) as caught:
        binding.dll.clear()
    err = caught.value
    assert err.wgfmu_code == api.LIBRARY_ERROR and err.function == "clear"
    assert "does not export WGFMU_abort, WGFMU_getStatus" in err.text and "install library >= A.03.00" in err.text
    assert not binding.dll.loaded and binding.loads == [binding.dll.path]


def test_a_loader_failure_is_a_library_error(dll_path: str) -> None:
    def refuse(path: str) -> object:
        raise OSError(f"[WinError 193] %1 is not a valid Win32 application: '{path}'")

    dll = WgfmuDll(dll_path, loader=refuse, platform="win32", bits=64)
    with pytest.raises(WgfmuError) as caught:
        dll.open_session(ADDRESS)
    assert caught.value.wgfmu_code == api.LIBRARY_ERROR and "cannot load" in caught.value.text
    assert "WinError 193" in caught.value.text and not dll.loaded


def test_an_unloadable_library_is_never_handed_to_the_loader(tmp_path: Path) -> None:
    loads: list[str] = []
    x86 = write_dll(tmp_path / "SysWOW64" / "wgfmu.dll", machine=X86)
    dll = WgfmuDll(x86, loader=lambda p: loads.append(p), platform="win32", bits=64)
    with pytest.raises(WgfmuError) as caught:
        dll.open_session(ADDRESS)
    err = caught.value
    assert err.wgfmu_code == api.LIBRARY_ERROR and err.code == "instrument_error"
    assert "a 32-bit DLL cannot load into 64-bit Python: install library >= A.03.00" in err.text
    assert loads == [] and not dll.loaded
    missing = WgfmuDll(str(tmp_path / "absent" / "wgfmu.dll"), loader=lambda p: loads.append(p), platform="win32")
    with pytest.raises(WgfmuError, match="not found: install library >= A.03.00"):
        missing.channel_ids()
    assert loads == []


def test_the_audit_records_return_and_firmware_codes(binding: Binding) -> None:
    sink = MemoryAuditSink()
    wg = AuditingWgfmu(binding.dll, sink, backend="visa")
    wg.clear()
    binding.lib.fail("WGFMU_execute", api.FW_ERROR, "Firmware error was found. 3050 overflow")
    with pytest.raises(WgfmuError):
        wg.execute()
    event = sink.events[-1]
    assert event.cmd == "WGFMU_execute" and event.backend == "visa"
    assert event.data == {"fn": "execute", "rc": api.FW_ERROR, "code": 3050}
    assert event.error is not None and "3050 overflow" in event.error


def test_simulator_faults_reach_the_caller_through_the_binding(bind) -> None:
    """A ``wgfmu_error`` fault of the simulator (as a real library would fail) comes back with its code."""
    from b1500_test_agent.models.sim import WgfmuErrorFault

    binding = bind()
    binding.st.flex.instrument.inject(WgfmuErrorFault(fn="open_session", code=3001))
    with pytest.raises(WgfmuError) as caught:
        binding.dll.open_session(ADDRESS)
    assert (caught.value.wgfmu_code, caught.value.rc) == (3001, api.FW_ERROR)
    assert isinstance(binding.st.sim, SimWgfmu) and binding.st.sim.session is None
    lib = binding.lib
    assert isinstance(lib, FakeWgfmuLibrary) and lib.names()[0] == "WGFMU_openSession"


def test_a_refused_argument_is_queued_like_a_library_error(binding: Binding) -> None:
    with pytest.raises(WgfmuError) as caught:
        binding.dll.set_operation_mode(101, "current")  # type: ignore[arg-type]
    err = caught.value
    assert type(err).__name__ == "ArgumentRefused" and isinstance(err, WgfmuError)
    assert err.text == ("set_operation_mode: -1 WGFMU_PARAMETER_OUT_OF_RANGE_ERROR: Invalid parameter value was found. "
                        "It will be out of the range. mode 'current' (allowed: dc, fastiv, pg, smu)")
    assert binding.dll.errors() == [err.text]  # as SimWgfmu reports the same call
