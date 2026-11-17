"""pyvisa lint (blueprint 2, 9.0 guardrail 1): only ``src/b1500_test_agent/transport/visa.py`` imports ``pyvisa``.

Scanned: every ``*.py`` under ``src/``, ``scripts/`` and ``tests/``. An import is ``import pyvisa[.x]``,
``from pyvisa[.x] import ...``, or a call ``__import__``/``import_module``/``importorskip`` with a literal
``"pyvisa[.x]"`` argument. Other packages that merely start with the name (``pyvisa_sim``) are not ``pyvisa``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("src", "scripts", "tests")
ALLOWED = frozenset({"src/b1500_test_agent/transport/visa.py"})
_PYVISA = re.compile(r"^pyvisa(\.|$)")
_DYNAMIC_IMPORTERS = frozenset({"__import__", "import_module", "importorskip"})


def pyvisa_imports(source: str) -> list[int]:
    """Line numbers of every pyvisa import in ``source``."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else []
        else:
            names = []
        if any(_PYVISA.match(name) for name in names):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            arg = node.args[0]
            if (
                name in _DYNAMIC_IMPORTERS
                and isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and _PYVISA.match(arg.value)
            ):
                lines.append(node.lineno)
    return lines


def test_only_transport_visa_imports_pyvisa() -> None:
    offenders = []
    scanned = 0
    for directory in SCANNED_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/.venv/" in f"/{rel}" or rel in ALLOWED:
                continue
            scanned += 1
            offenders.extend(f"{rel}:{line}" for line in pyvisa_imports(path.read_text(encoding="utf-8")))
    assert scanned > 20
    assert offenders == []


@pytest.mark.parametrize(
    "source",
    [
        "import pyvisa",
        "import pyvisa.constants as c",
        "import os, pyvisa",
        "from pyvisa import ResourceManager",
        "from pyvisa.resources import MessageBasedResource",
        "def f():\n    import pyvisa\n",
        "import importlib\nvisa = importlib.import_module('pyvisa')",
        "visa = __import__('pyvisa')",
        "import pytest\nvisa = pytest.importorskip('pyvisa')",
    ],
)
def test_detector_flags_pyvisa_imports(source: str) -> None:
    assert pyvisa_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "import pyvisa_sim",
        "from pyvisa_sim import x",
        "text = 'import pyvisa'",
        "from .pyvisa import x",
        "import visa_tools",
        "x = 'pyvisa'",
    ],
)
def test_detector_ignores_other_code(source: str) -> None:
    assert pyvisa_imports(source) == []
