"""The Windows loading path of the WGFMU binding, by platform injection (blueprint v2 7.1 "Windows CI ...
Windows-only paths unit-tested by platform injection", WP6.5 handoff "add WinDLL/locate() platform tests"; WP10.2).

Without an injected loader ``WgfmuDll`` loads with ``ctypes.WinDLL(path)``, and only after its probe said the file
is a loadable x64 DLL. These tests replace ``ctypes.WinDLL`` by a recorder (on Windows CI the real one exists but is
never called on a file; on the Mac it does not exist), so no real ``wgfmu.dll`` is ever loaded on any OS."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from b1500_test_agent.transport.wgfmu import api, dll
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from b1500_test_agent.transport.wgfmu.dll import WgfmuDll
from tests.sim import wgfmu_examples as wx
from tests.wgfmu_abi.fake_lib import FakeWgfmuLibrary
from tests.wgfmu_abi.pe_builder import X86, write_dll

pytestmark = pytest.mark.wgfmu


class Recorder:
    """Stands in for ``ctypes.WinDLL``: records the paths and returns a fake library over a simulated WGFMU."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def __call__(self, path: str) -> FakeWgfmuLibrary:
        self.paths.append(path)
        return FakeWgfmuLibrary(wx.station().sim, path=path)


@pytest.fixture
def win_dll(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(dll.ctypes, "WinDLL", recorder, raising=False)
    return recorder


def test_the_default_loader_is_windll_on_the_probed_path(tmp_path: Path, win_dll: Recorder) -> None:
    path = write_dll(tmp_path / "System32" / "wgfmu.dll")
    binding = WgfmuDll(path, platform="win32", bits=64)  # no loader injected
    assert not binding.loaded and win_dll.paths == []
    binding.open_session("GPIB0::17::INSTR")
    assert binding.channel_ids() == [101, 102]
    assert win_dll.paths == [path] and binding.loaded


def test_windll_is_not_called_for_a_library_the_probe_refuses(tmp_path: Path, win_dll: Recorder) -> None:
    for path in (write_dll(tmp_path / "SysWOW64" / "wgfmu.dll", machine=X86), str(tmp_path / "absent.dll")):
        binding = WgfmuDll(path, platform="win32", bits=64)
        with pytest.raises(WgfmuError) as caught:
            binding.open_session("GPIB0::17::INSTR")
        assert caught.value.wgfmu_code == api.LIBRARY_ERROR and "install library >= A.03.00" in caught.value.text
    assert win_dll.paths == []


def test_off_windows_the_binding_is_constructed_but_never_loaded(tmp_path: Path, win_dll: Recorder) -> None:
    binding = WgfmuDll(write_dll(tmp_path / "wgfmu.dll"), platform="darwin", bits=64)
    with pytest.raises(WgfmuError, match="only on Windows"):
        binding.initialize()
    assert win_dll.paths == [] and not binding.loaded


@pytest.mark.skipif(hasattr(dll.ctypes, "WinDLL"), reason="ctypes.WinDLL exists on this OS")
def test_without_windll_the_loader_refuses(tmp_path: Path) -> None:
    """On the Mac even a probe that (by injection) says loadable ends in a library error, not a crash."""
    binding = WgfmuDll(write_dll(tmp_path / "wgfmu.dll"), platform="win32", bits=64)
    with pytest.raises(WgfmuError) as caught:
        binding.clear()
    assert caught.value.wgfmu_code == api.LIBRARY_ERROR and "ctypes.WinDLL exists only on Windows" in caught.value.text


@pytest.mark.skipif(sys.platform != "win32", reason="the real ctypes.WinDLL exists only on Windows")
def test_on_windows_windll_exists_and_the_default_binding_uses_this_platform(tmp_path: Path,
                                                                             win_dll: Recorder) -> None:
    assert callable(win_dll)  # the real WinDLL was there and is replaced for the test
    binding = WgfmuDll(write_dll(tmp_path / "wgfmu.dll"))
    assert binding.platform == "win32" and binding.probe().loadable
    binding.clear()
    assert win_dll.paths == [binding.path]


def test_the_default_binding_takes_this_interpreter_s_platform_and_width() -> None:
    binding = WgfmuDll("C:\\Windows\\System32\\wgfmu.dll")
    assert binding.platform == sys.platform and binding.bits == dll.python_bits() == 64
