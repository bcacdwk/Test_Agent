"""ctypes lint (blueprint v2 2.1 "Lint ownership: ``ctypes`` and ``wgfmu.dll`` only in ``transport/wgfmu/dll.py``",
10.0 guardrail 1, WP10.2 AC "layering lint: only dll.py imports ctypes").

Scanned: every ``*.py`` under ``src/``, ``scripts/`` and ``tests/``. Flagged outside
``src/b1500_test_agent/transport/wgfmu/dll.py``:

- an import of ``ctypes`` (``import ctypes[.x]``, ``from ctypes[.x] import ...``, or ``__import__`` /
  ``import_module`` / ``importorskip`` with a literal ``"ctypes[.x]"``), also inside functions;
- a library loader used as a name or attribute (``WinDLL``, ``windll``, ``CDLL``, ``cdll``, ``OleDLL``, ``oledll``,
  ``PyDLL``, ``LoadLibrary``, ``LoadLibraryEx``...): nothing else may load a DLL.

Mentions in strings and docstrings (messages, the S18 grader's patterns) are not code and are not flagged. The test
suite's fake library (``tests/wgfmu_abi/fake_lib.py``) uses the ctypes objects the binding hands it through their own
methods and needs no import; ``numpy.ctypeslib`` is numpy's, not an import of ``ctypes``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.wgfmu

ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("src", "scripts", "tests")
ALLOWED = frozenset({"src/b1500_test_agent/transport/wgfmu/dll.py"})
_CTYPES = re.compile(r"^ctypes(\.|$)")
_DYNAMIC_IMPORTERS = frozenset({"__import__", "import_module", "importorskip"})
LOADERS = frozenset({"WinDLL", "windll", "CDLL", "cdll", "OleDLL", "oledll", "PyDLL", "pydll", "LoadLibrary",
                     "LoadLibraryA", "LoadLibraryW", "LoadLibraryEx", "LoadLibraryExA", "LoadLibraryExW"})


def ctypes_uses(source: str) -> list[tuple[int, str]]:
    """``(line, what)`` of every ctypes import and DLL-loader name in ``source``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else []
            names += [f"{node.module}.{alias.name}" for alias in node.names if alias.name in LOADERS]
        found.extend((node.lineno, f"import {name}") for name in names if _CTYPES.match(name))
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            arg = node.args[0]
            if name in _DYNAMIC_IMPORTERS and isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and _CTYPES.match(arg.value):
                found.append((node.lineno, f"{name}({arg.value!r})"))
        if isinstance(node, ast.Name) and node.id in LOADERS:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in LOADERS:
            found.append((node.lineno, node.attr))
    return found


def test_only_the_dll_binding_imports_ctypes_or_loads_a_library() -> None:
    offenders = []
    scanned = 0
    for directory in SCANNED_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/.venv/" in f"/{rel}" or rel in ALLOWED:
                continue
            scanned += 1
            offenders.extend(f"{rel}:{line}: {what}" for line, what in ctypes_uses(path.read_text(encoding="utf-8")))
    assert scanned > 200
    assert offenders == []


def test_the_binding_is_where_ctypes_and_windll_are() -> None:
    """Not vacuous: the allowed module does import ctypes and name its loader."""
    (path,) = [ROOT / rel for rel in ALLOWED]
    found = {what for _, what in ctypes_uses(path.read_text(encoding="utf-8"))}
    assert "import ctypes" in found and "WinDLL" not in found  # WinDLL only as getattr(ctypes, "WinDLL")
    assert 'getattr(ctypes, "WinDLL", None)' in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("source", [
    "import ctypes",
    "import ctypes.wintypes as w",
    "import os, ctypes",
    "from ctypes import c_int",
    "from ctypes import WinDLL",
    "def f():\n    import ctypes\n",
    "import importlib\nc = importlib.import_module('ctypes')",
    "c = __import__('ctypes')",
    "lib = windll.wgfmu",
    "lib = x.WinDLL('wgfmu.dll')",
    "lib = CDLL('wgfmu.dll')",
    "kernel.LoadLibraryExW(path, None, 0)",
])
def test_detector_flags_ctypes_and_loaders(source: str) -> None:
    assert ctypes_uses(source)


@pytest.mark.parametrize("source", [
    "import ctypeslib",
    "import numpy as np\nview = np.ctypeslib.as_array(pointer, shape=(3,))",
    "text = 'load wgfmu.dll with ctypes.WinDLL'",
    '"""Docstring: ctypes.WinDLL(path)."""',
    "monkeypatch.setattr(module.ctypes, 'WinDLL', recorder, raising=False)",
])
def test_detector_ignores_strings_and_lookalikes(source: str) -> None:
    assert ctypes_uses(source) == []
