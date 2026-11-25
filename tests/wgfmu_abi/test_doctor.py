"""``b1500 doctor``'s WGFMU library check and the probe's verdict on a library (blueprint v2 7.1 "b1500 doctor: WGFMU
DLL probe (path, version, x64, exports)", 10.6 row 10.2 AC "synthetic x86 header -> FAIL 'install library >=
A.03.00'"; WP10.2). The check locates the configured or default ``wgfmu.dll`` and reads it as a file; the platform is
injected, so the Windows verdicts are tested on every OS and nothing is ever loaded."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from b1500_test_agent.devtools.doctor import check_wgfmu_library
from b1500_test_agent.models.station import DllProbe, Settings
from b1500_test_agent.service.probe import library_status
from tests.wgfmu_abi.pe_builder import X86, write_dll

pytestmark = pytest.mark.wgfmu


def bundle(library: str, *, backend: str = "visa", wgfmu: bool = True) -> SimpleNamespace:
    """The parts of a ``ConfigBundle`` the check reads."""
    modules = [SimpleNamespace(type="WGFMU", slot=2)] if wgfmu else [SimpleNamespace(type="HRSMU", slot=3)]
    settings = Settings.model_validate({"wgfmu": {"library": library}})
    return SimpleNamespace(settings=settings, backend=backend, station=SimpleNamespace(modules=modules))


def test_an_x64_library_passes(tmp_path: Path) -> None:
    check = check_wgfmu_library(bundle(write_dll(tmp_path / "wgfmu.dll")), {}, windows=True)  # type: ignore[arg-type]
    assert check.name == "wgfmu library" and check.status == "PASS"
    assert "x64 DLL" in check.detail and "A.04.00.2440.5403" in check.detail and "39/39 exports" in check.detail


def test_a_synthetic_x86_header_fails_install_library_a_03_00(tmp_path: Path) -> None:
    """The WP10.2 AC, on any backend: a 32-bit DLL can never load into the lab's 64-bit Python."""
    x86 = write_dll(tmp_path / "SysWOW64" / "wgfmu.dll", machine=X86)
    for backend in ("visa", "sim"):
        check = check_wgfmu_library(bundle(x86, backend=backend), {}, windows=True)  # type: ignore[arg-type]
        assert check.status == "FAIL" and "install library >= A.03.00" in check.detail, check
        assert "x86 DLL (machine 0x14c)" in check.detail


@pytest.mark.parametrize(("backend", "wgfmu", "status"), [
    ("visa", True, "FAIL"),  # the lab PC with a WGFMU: WGFMU recipes need the library
    ("sim", True, "WARN"),  # a Windows PC rehearsing on the simulator
    ("visa", False, "WARN"),  # a station without a WGFMU
])
def test_a_missing_library_on_windows(tmp_path: Path, backend: str, wgfmu: bool, status: str) -> None:
    check = check_wgfmu_library(bundle(str(tmp_path / "absent" / "wgfmu.dll"), backend=backend, wgfmu=wgfmu),
                                {}, windows=True)  # type: ignore[arg-type]
    assert check.status == status and "not found: install library >= A.03.00" in check.detail


def test_off_windows_the_check_warns(tmp_path: Path) -> None:
    for library in (write_dll(tmp_path / "wgfmu.dll"), ""):
        check = check_wgfmu_library(bundle(library), {}, windows=False)  # type: ignore[arg-type]
        assert check.status == "WARN" and "loads only on Windows" in check.detail


def test_without_a_configuration_the_default_path_is_checked() -> None:
    check = check_wgfmu_library(None, {"SystemRoot": "Q:\\NoWindows"}, windows=True)
    assert check.status == "WARN" and "Q:\\NoWindows\\System32\\wgfmu.dll not found" in check.detail


@pytest.mark.parametrize(("probe", "required", "windows", "status"), [
    ({"loadable": True, "exists": True, "machine": "x64"}, True, True, "PASS"),
    ({"exists": True, "machine": "x64"}, True, False, "WARN"),
    ({"exists": False}, True, False, "WARN"),
    ({"exists": False}, True, True, "FAIL"),
    ({"exists": False}, False, True, "WARN"),
    ({"exists": True, "machine": "x86"}, False, True, "FAIL"),
    ({"exists": True, "machine": "x64", "missing_exports": ["WGFMU_abort"]}, False, True, "FAIL"),
])
def test_library_status_table(probe: dict, required: bool, windows: bool, status: str) -> None:
    assert library_status(DllProbe(path="wgfmu.dll", **probe), required=required, windows=windows) == status
