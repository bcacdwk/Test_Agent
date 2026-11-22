"""Fixtures of the WGFMU fake-ABI suite (blueprint v2 7.1, 8.1 ``wgfmu_abi/``): the real ``WgfmuDll`` with the
platform injected (``win32``, 64-bit) over a synthetic x64 ``wgfmu.dll`` file (its PE header is all the probe reads)
and ``FakeWgfmuLibrary`` as the loaded library, backed by ``SimWgfmu`` on a simulated B1500A (the WG examples'
mainframe: WGFMU in slot 1, HRSMU in slot 2). No real ``wgfmu.dll`` is ever loaded, on any OS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu
from b1500_test_agent.transport.wgfmu.dll import WgfmuDll
from tests.sim import wgfmu_examples as wx
from tests.wgfmu_abi.fake_lib import FakeWgfmuLibrary
from tests.wgfmu_abi.pe_builder import write_dll


@dataclass
class Binding:
    """A ``WgfmuDll`` over a fake library on a simulated station (``st.sim`` is the backend)."""

    dll: WgfmuDll
    st: wx.Station
    loads: list[str]

    @property
    def lib(self) -> FakeWgfmuLibrary:
        assert self.dll.loaded, "the library is not loaded yet"
        return self.dll._lib


def make_binding(path: str, scenario: SimScenario | None = None, *, exports: list[str] | None = None) -> Binding:
    st = wx.station(scenario)
    loads: list[str] = []

    def load(library: str) -> FakeWgfmuLibrary:
        loads.append(library)
        return FakeWgfmuLibrary(st.sim, exports=exports, path=library)

    dll = WgfmuDll(path, loader=load, platform="win32", bits=64)
    st.wg = AuditingWgfmu(dll, MemoryAuditSink(), backend="visa")
    return Binding(dll, st, loads)


@pytest.fixture
def dll_path(tmp_path: Path) -> str:
    """A synthetic x64 ``wgfmu.dll`` exporting every function of the binding."""
    return write_dll(tmp_path / "System32" / "wgfmu.dll")


@pytest.fixture
def binding(dll_path: str) -> Binding:
    return make_binding(dll_path)


@pytest.fixture
def bind(dll_path: str) -> Callable[..., Binding]:
    """``bind(scenario=None, exports=None)``: a binding on another simulated station."""
    return lambda scenario=None, **kw: make_binding(dll_path, scenario, **kw)
