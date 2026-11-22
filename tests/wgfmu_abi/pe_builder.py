"""Synthetic Windows DLL images for the ``locate()``/``read_pe`` tests (blueprint v2 7.1 "WGFMU fake-ABI", 8.1
``wgfmu_abi/``): a minimal, well-formed PE file with a COFF machine, a PE32 or PE32+ optional header, one section
holding an export directory (the named functions) and a version resource (``VS_FIXEDFILEINFO`` and a
``FileVersion`` string), laid out as the PE/COFF specification describes. Nothing here can be loaded or executed:
the "functions" have no code."""

from __future__ import annotations

import struct
from collections.abc import Iterable
from pathlib import Path

from b1500_test_agent.transport.wgfmu.dll import C_SIGNATURES, IMAGE_FILE_DLL, PE32_MAGIC, PE32_PLUS_MAGIC

X64 = 0x8664
X86 = 0x14C
ARM64 = 0xAA64
E_LFANEW = 0x80
FILE_ALIGNMENT = 0x200
SECTION_RVA = 0x1000
LAB_VERSION = "A.04.00.2440.5403"
"""The library release the lab installs (blueprint v2 7.5 step 2)."""
LAB_FIXED = (4, 0, 2440, 5403)


def _utf16(text: str) -> bytes:
    return (text + "\0").encode("utf-16-le")


def _align(data: bytes, boundary: int = 4) -> bytes:
    return data + b"\0" * (-len(data) % boundary)


def version_resource(text: str | None, fixed: tuple[int, int, int, int] | None) -> bytes:
    """A ``VS_VERSION_INFO`` blob: ``VS_FIXEDFILEINFO`` (when ``fixed``) and a ``FileVersion`` string (when
    ``text``)."""
    blob = _align(struct.pack("<HHH", 0, 52, 0) + _utf16("VS_VERSION_INFO"))
    if fixed is not None:
        major, minor, build, revision = fixed
        ms, ls = (major << 16) | minor, (build << 16) | revision
        blob += struct.pack("<13I", 0xFEEF04BD, 0x10000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 2, 0, 0, 0)
    if text is not None:
        blob = _align(blob + _utf16("StringFileInfo"))
        blob = _align(blob + struct.pack("<HHH", 0, len(text) + 1, 1) + _utf16("FileVersion"))
        blob += _utf16(text)
    return _align(blob)


def build_pe(*, machine: int = X64, magic: int | None = None, exports: Iterable[str] | None = None,
             export_table: bool = True, version: str | None = LAB_VERSION,
             fixed_version: tuple[int, int, int, int] | None = LAB_FIXED, dll: bool = True) -> bytes:
    """A synthetic DLL image. ``exports`` defaults to every function of the binding (``C_SIGNATURES``);
    ``export_table=False`` leaves the export directory out; ``magic`` defaults to PE32+ for x64/ARM64, else PE32."""
    names = sorted(C_SIGNATURES if exports is None else exports)
    if magic is None:
        magic = PE32_MAGIC if machine == X86 else PE32_PLUS_MAGIC
    plus = magic == PE32_PLUS_MAGIC
    opt_size = (112 if plus else 96) + 16 * 8
    headers = E_LFANEW + 4 + 20 + opt_size + 40
    raw_at = -(-headers // FILE_ALIGNMENT) * FILE_ALIGNMENT

    # section content: export directory, its tables and names, then the version resource
    section = bytearray(40)
    dll_name_at = len(section)
    section += b"wgfmu.dll\0"
    section = bytearray(_align(bytes(section)))
    functions_at = len(section)
    section += b"\0" * (4 * len(names))
    names_at = len(section)
    section += b"\0" * (4 * len(names))
    ordinals_at = len(section)
    section += b"".join(struct.pack("<H", i) for i in range(len(names)))
    section = bytearray(_align(bytes(section)))
    for i, name in enumerate(names):
        struct.pack_into("<I", section, names_at + 4 * i, SECTION_RVA + len(section))
        struct.pack_into("<I", section, functions_at + 4 * i, SECTION_RVA)  # no code behind any export
        section += name.encode("ascii") + b"\0"
    struct.pack_into("<IIHHIIIIIII", section, 0, 0, 0, 0, 0, SECTION_RVA + dll_name_at, 1, len(names), len(names),
                     SECTION_RVA + functions_at, SECTION_RVA + names_at, SECTION_RVA + ordinals_at)
    export_size = len(section)
    section = bytearray(_align(bytes(section)))
    resource_at = len(section)
    resource = version_resource(version, fixed_version) if (version or fixed_version) else b""
    section += resource
    virtual_size = len(section)
    section += b"\0" * (-len(section) % FILE_ALIGNMENT)

    image = bytearray(raw_at)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, E_LFANEW)
    image[E_LFANEW:E_LFANEW + 4] = b"PE\0\0"
    coff = E_LFANEW + 4
    characteristics = 0x0022 | (IMAGE_FILE_DLL if dll else 0)
    struct.pack_into("<HHIIIHH", image, coff, machine, 1, 0, 0, 0, opt_size, characteristics)
    opt = coff + 20
    struct.pack_into("<H", image, opt, magic)
    count_at, dirs_at = (opt + 108, opt + 112) if plus else (opt + 92, opt + 96)
    struct.pack_into("<I", image, count_at, 16)
    if export_table:
        struct.pack_into("<II", image, dirs_at, SECTION_RVA, export_size)
    if resource:
        struct.pack_into("<II", image, dirs_at + 16, SECTION_RVA + resource_at, len(resource))
    table = opt + opt_size
    struct.pack_into("<8sIIIIIIHHI", image, table, b".rdata", virtual_size, SECTION_RVA, len(section), raw_at,
                     0, 0, 0, 0, 0x40000040)
    return bytes(image) + bytes(section)


def write_dll(path: Path, **kwargs: object) -> str:
    """Write ``build_pe(**kwargs)`` to ``path`` (folders created); returns the path as a string."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_pe(**kwargs))  # type: ignore[arg-type]
    return str(path)
