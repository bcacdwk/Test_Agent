"""Locating and probing the WGFMU library without loading it (blueprint v2 2.4 ``WgfmuDll.locate(settings) ->
DllProbe`` "never raises: configured path, else %SystemRoot%\\System32\\wgfmu.dll; PE header machine read in pure
Python (0x8664 x64, 0x14c x86); non-Windows -> loadable: false", decision 6, §0.1 DLL facts, ATV-15; WP10.2).

Synthetic DLL images (``pe_builder.py``) stand in for the library: an x64 one is loadable on (injected) Windows by a
64-bit Python; a 32-bit one is not, "install library >= A.03.00" (the first release with the x64 DLL in System32; no
32-bit bridge); missing, unreadable, foreign and incomplete files are reported, never raised."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from b1500_test_agent.models.station import Settings, WgfmuSettings
from b1500_test_agent.transport.wgfmu import dll
from b1500_test_agent.transport.wgfmu.dll import (
    C_SIGNATURES,
    NOT_WINDOWS,
    PE32_MAGIC,
    PE32_PLUS_MAGIC,
    PeError,
    WgfmuDll,
    library_path,
    probe_library,
    read_pe,
)
from tests.wgfmu_abi.pe_builder import ARM64, LAB_VERSION, X64, X86, build_pe, write_dll

pytestmark = pytest.mark.wgfmu

INSTALL = "install library >= A.03.00"


# -- the PE reader -------------------------------------------------------------------------------------------------


def test_reads_machine_magic_exports_and_version_of_an_x64_dll() -> None:
    image = read_pe(build_pe())
    assert (image.machine, image.machine_name, image.magic, image.dll) == (0x8664, "x64", PE32_PLUS_MAGIC, True)
    assert image.exports == frozenset(C_SIGNATURES) and image.file_version == LAB_VERSION


def test_reads_a_32_bit_dll() -> None:
    image = read_pe(build_pe(machine=X86))
    assert (image.machine, image.machine_name, image.magic) == (0x14C, "x86", PE32_MAGIC)
    assert image.exports == frozenset(C_SIGNATURES)


@pytest.mark.parametrize(("kwargs", "version"), [
    ({"version": None}, "4.0.2440.5403"),  # numeric VS_FIXEDFILEINFO only
    ({"version": None, "fixed_version": None}, None),  # no version resource
    ({"version": "A.03.00.1234.0000", "fixed_version": (3, 0, 1234, 0)}, "A.03.00.1234.0000"),
])
def test_file_version_where_readable(kwargs: dict, version: str | None) -> None:
    assert read_pe(build_pe(**kwargs)).file_version == version


def test_other_machines_no_exports_and_no_dll_flag() -> None:
    assert read_pe(build_pe(machine=ARM64)).machine_name == "unknown"
    assert read_pe(build_pe(export_table=False)).exports is None
    assert read_pe(build_pe(exports=["WGFMU_openSession"])).exports == {"WGFMU_openSession"}
    assert read_pe(build_pe(dll=False)).dll is False


@pytest.mark.parametrize(("data", "fragment"), [
    (b"", "no MZ header"),
    (b"ELF\x7f" + bytes(200), "no MZ header"),
    (b"MZ" + bytes(10), "truncated"),
    (b"MZ" + bytes(0x3A) + (0x40).to_bytes(4, "little") + b"XX\0\0" + bytes(100), "no PE signature"),
])
def test_what_is_not_a_pe_image_is_a_pe_error(data: bytes, fragment: str) -> None:
    with pytest.raises(PeError, match=fragment):
        read_pe(data)


def test_a_truncated_dll_is_a_pe_error() -> None:
    image = build_pe()
    with pytest.raises(PeError):
        read_pe(image[:0x300])  # headers intact, the export section cut off
    corrupt = bytearray(image)
    corrupt[0x80 + 24:0x80 + 26] = (0x1234).to_bytes(2, "little")  # optional-header magic
    with pytest.raises(PeError, match="magic 0x1234"):
        read_pe(bytes(corrupt))


# -- probe_library: the verdicts --------------------------------------------------------------------------------------


def test_an_x64_library_is_loadable_on_windows(tmp_path: Path) -> None:
    path = write_dll(tmp_path / "wgfmu.dll")
    probe = probe_library(path, platform="win32", bits=64)
    assert probe.loadable and probe.exists and probe.machine == "x64" and probe.missing_exports == []
    assert probe.file_version == LAB_VERSION and probe.python_bits == 64 and probe.path == path
    assert "34/34 exports" in probe.message and "loadable" in probe.message


def test_a_32_bit_library_fails_install_a_03_00(tmp_path: Path) -> None:
    probe = probe_library(write_dll(tmp_path / "wgfmu.dll", machine=X86), platform="win32", bits=64)
    assert not probe.loadable and probe.exists and probe.machine == "x86"
    assert "a 32-bit DLL cannot load into 64-bit Python" in probe.message and INSTALL in probe.message


def test_a_missing_library_on_windows(tmp_path: Path) -> None:
    probe = probe_library(str(tmp_path / "System32" / "wgfmu.dll"), platform="win32", bits=64)
    assert not probe.loadable and not probe.exists and probe.machine is None
    assert "not found" in probe.message and INSTALL in probe.message


def test_off_windows_nothing_is_loadable_but_the_file_is_still_described(tmp_path: Path) -> None:
    path = write_dll(tmp_path / "wgfmu.dll")
    probe = probe_library(path, platform="darwin", bits=64)
    assert not probe.loadable and probe.machine == "x64" and probe.file_version == LAB_VERSION
    assert NOT_WINDOWS in probe.message
    missing = probe_library(str(tmp_path / "absent.dll"), platform="linux", bits=64)
    assert not missing.loadable and missing.message == NOT_WINDOWS


@pytest.mark.parametrize(("kwargs", "fragment"), [
    ({"exports": ["WGFMU_openSession", "WGFMU_closeSession"]}, "32 function(s) the binding needs are not exported"),
    ({"export_table": False}, "no export table"),
    ({"machine": ARM64}, "not an x64 DLL"),
    ({"magic": PE32_MAGIC}, "not an x64 DLL"),  # x64 machine with a 32-bit optional header
    ({"dll": False}, "the image is not a DLL"),
])
def test_an_incomplete_or_foreign_library_is_not_loadable(tmp_path: Path, kwargs: dict, fragment: str) -> None:
    probe = probe_library(write_dll(tmp_path / "wgfmu.dll", **kwargs), platform="win32", bits=64)
    assert not probe.loadable and probe.exists and fragment in probe.message, probe.message
    if "exports" in kwargs:
        assert len(probe.missing_exports) == 32 and "WGFMU_getMeasureValues" in probe.missing_exports


def test_a_32_bit_python_cannot_load_the_x64_library(tmp_path: Path) -> None:
    probe = probe_library(write_dll(tmp_path / "wgfmu.dll"), platform="win32", bits=32)
    assert not probe.loadable and probe.python_bits == 32 and "needs 64-bit Python" in probe.message


def test_unreadable_and_garbage_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    garbage = tmp_path / "garbage.dll"
    garbage.write_bytes(b"not a dll at all")
    probe = probe_library(str(garbage), platform="win32", bits=64)
    assert not probe.loadable and probe.exists and probe.machine == "unknown"
    assert "not a readable Windows DLL" in probe.message and INSTALL in probe.message
    folder = tmp_path / "folder.dll"
    folder.mkdir()
    assert not probe_library(str(folder), platform="win32").exists
    locked = write_dll(tmp_path / "locked" / "wgfmu.dll")

    def denied(path: str) -> bytes:
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(dll, "_read_library", denied)
    probe = probe_library(locked, platform="win32", bits=64)
    assert not probe.loadable and probe.exists and "Permission denied" in probe.message


def test_the_probe_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object) -> object:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(dll, "_probe", broken)
    probe = probe_library("C:/Windows/System32/wgfmu.dll", platform="win32", bits=64)
    assert not probe.loadable and "probe failed (RuntimeError: unexpected)" in probe.message


def test_the_probe_is_cached_until_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "wgfmu.dll"
    write_dll(path)
    first = probe_library(str(path), platform="win32", bits=64)
    assert probe_library(str(path), platform="win32", bits=64) is first
    path.write_bytes(build_pe(machine=X86) + b"\0" * 7)  # another size: probed again
    again = probe_library(str(path), platform="win32", bits=64)
    assert again.machine == "x86" and not again.loadable


# -- where the library is -------------------------------------------------------------------------------------------


def test_library_path_is_the_configured_one_else_system32() -> None:
    assert library_path(Settings.model_validate({"wgfmu": {"library": " D:\\Keysight\\wgfmu.dll "}})) == \
        "D:\\Keysight\\wgfmu.dll"
    assert library_path(WgfmuSettings(), {"SystemRoot": "E:\\WINNT"}) == "E:\\WINNT\\System32\\wgfmu.dll"
    assert library_path(Settings(), {"SYSTEMROOT": "C:\\Windows"}) == "C:\\Windows\\System32\\wgfmu.dll"
    assert library_path(Settings(), {}) == "C:\\Windows\\System32\\wgfmu.dll"


def test_locate_probes_the_selected_library(tmp_path: Path) -> None:
    x64 = write_dll(tmp_path / "x64" / "wgfmu.dll")
    probe = WgfmuDll.locate(Settings.model_validate({"wgfmu": {"library": x64}}), platform="win32", bits=64)
    assert probe.loadable and probe.path == x64
    default = WgfmuDll.locate(Settings(), platform="win32", environ={"SystemRoot": "Q:\\NoWindows"}, bits=64)
    assert default.path == "Q:\\NoWindows\\System32\\wgfmu.dll" and not default.exists and not default.loadable
    assert "not found" in default.message and INSTALL in default.message
    assert WgfmuDll.locate(Settings(), platform="darwin", environ={}).message == NOT_WINDOWS


@pytest.mark.skipif(sys.platform != "win32", reason="the installer's default path is a Windows path")
def test_locate_finds_a_32_bit_dll_at_the_installer_default(tmp_path: Path) -> None:
    root = tmp_path / "Windows"
    write_dll(root / "System32" / "wgfmu.dll", machine=X86)  # a 32-bit DLL where the default points
    default = WgfmuDll.locate(Settings(), environ={"SystemRoot": str(root)})
    assert default.exists and default.machine == "x86" and not default.loadable and INSTALL in default.message


def test_the_binding_probes_its_own_path_with_its_platform(tmp_path: Path) -> None:
    path = write_dll(tmp_path / "wgfmu.dll", machine=X64)
    assert WgfmuDll(path, platform="win32", bits=64).probe().loadable
    assert not WgfmuDll(path, platform="darwin", bits=64).probe().loadable
