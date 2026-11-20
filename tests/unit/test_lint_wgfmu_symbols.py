"""WGFMU-symbol lint (blueprint v2 2.1 "Lint ownership"): the instrument library's symbols (``WGFMU_*`` C functions
and ``wgfmu.h`` constants) appear only in ``transport/wgfmu/`` and ``transport/sim/wgfmu.py``.

Detector: every ``WGFMU_<name>`` token in a non-docstring string literal (f-strings with placeholders rendered as
``0``) or in an identifier (names, attributes, definitions, arguments, keywords, imports) of a module under
``src/b1500_test_agent`` is a library symbol when it is

- a C function: ``WGFMU_`` followed by a lower-case letter (``WGFMU_openSession``, ``WGFMU_dcforceVoltage``), or
- a library constant: a name of ``transport.wgfmu.api.LIBRARY_CONSTANTS`` or of the manual extracts
  (``references/manuals/structured/b1530a-wgfmu-*.yaml``), or a name of one of the header's constant families
  (``WGFMU_OPERATION_MODE_*``, ``WGFMU_MEASURE_EVENT_*``, ``WGFMU_STATUS_*``, ``*_ERROR`` ...).

The package's own names that merely start with the module name (``WGFMU_SPEC``, ``WGFMU_GRID_S``,
``WGFMU_RAW_FORMAT``) are not library symbols. Docstrings are documentation and are not scanned (as in the FLEX
lint). Code elsewhere reaches the library only through the ``WgfmuApi`` protocol and its Python literals.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from b1500_test_agent.transport.wgfmu.api import LIBRARY_CONSTANTS
from tests.unit.test_lint_flex_literals import string_literals

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "src" / "b1500_test_agent"
STRUCTURED = ROOT / "references" / "manuals" / "structured"
ALLOWED_PREFIXES = ("transport/wgfmu/",)
ALLOWED_FILES = ("transport/sim/wgfmu.py",)

TOKEN = re.compile(r"WGFMU_[A-Za-z0-9_]*")
FUNCTION = re.compile(r"^WGFMU_[a-z][A-Za-z0-9]*$")
FAMILY = re.compile(
    r"^WGFMU_(?:OPERATION_MODE|FORCE_VOLTAGE_RANGE|MEASURE_MODE|MEASURE_VOLTAGE_RANGE|MEASURE_CURRENT_RANGE"
    r"|MEASURE_ENABLED|MEASURE_EVENT|TRIGGER_OUT|AXIS|STATUS|WARNING_LEVEL)_[A-Z0-9_]+$"
    r"|^WGFMU_(?:[A-Z0-9_]+_)?ERROR(?:_CODE_MIN)?$|^WGFMU_(?:NO_ERROR|PASS|FAIL)$"
)


def _extract_names() -> set[str]:
    names: set[str] = set()
    for path in sorted(STRUCTURED.glob("b1530a-wgfmu-*.yaml")):
        text = path.read_text(encoding="utf-8")
        names.update(m for m in TOKEN.findall(text) if not FUNCTION.match(m) and m.upper() == m)
    return names


CONSTANTS = frozenset(LIBRARY_CONSTANTS) | frozenset(_extract_names())


def is_library_symbol(token: str) -> bool:
    return bool(FUNCTION.match(token)) or token in CONSTANTS or bool(FAMILY.match(token))


def _identifiers(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names = [node.name]
        elif isinstance(node, ast.arg) or isinstance(node, ast.keyword) and node.arg:
            names = [node.arg]
        elif isinstance(node, ast.alias):
            names = [node.name, node.asname or ""]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        found.extend((getattr(node, "lineno", 0), n) for n in names if n)
    return found


def symbol_hits(source: str, where: str = "<source>") -> list[str]:
    """``where:line: symbol`` for every library symbol in string literals and identifiers of ``source``."""
    if "WGFMU_" not in source:  # no token at all: skip the parse
        return []
    hits = []
    texts = string_literals(source) + _identifiers(ast.parse(source))
    for line, text in texts:
        hits.extend(f"{where}:{line}: {tok}" for tok in TOKEN.findall(text) if is_library_symbol(tok))
    return hits


def _files(allowed: bool) -> list[Path]:
    out = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        rel = path.relative_to(PACKAGE_DIR).as_posix()
        if (rel.startswith(ALLOWED_PREFIXES) or rel in ALLOWED_FILES) == allowed:
            out.append(path)
    return out


def test_library_symbols_only_in_the_wgfmu_transport_and_its_simulator() -> None:
    files = _files(allowed=False)
    scanned = {p.relative_to(PACKAGE_DIR).as_posix() for p in files}
    assert {"models/sources.py", "rules/builtin/pulse.py", "driver/modules.py", "transport/sim/wgfmu_engine.py",
            "transport/sim/wgfmu_checks.py", "transport/factory.py"} <= scanned
    hits = [h for p in files for h in symbol_hits(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())]
    assert hits == []


def test_the_allowed_modules_hold_library_symbols_so_the_lint_is_not_vacuous() -> None:
    hits = [h for p in _files(allowed=True) for h in symbol_hits(p.read_text(encoding="utf-8"))]
    found = {h.rsplit(": ", 1)[1] for h in hits}
    assert {"WGFMU_openSession", "WGFMU_addVectors", "WGFMU_setMeasureEvent", "WGFMU_OPERATION_MODE_FASTIV",
            "WGFMU_MEASURE_EVENT_DATA_RAW", "WGFMU_STATUS_COMPLETED", "WGFMU_FW_ERROR"} <= found


@pytest.mark.parametrize("source", [
    "lib.WGFMU_openSession(b'GPIB0::17::INSTR')",
    "fn = getattr(lib, 'WGFMU_execute')",
    "mode = WGFMU_OPERATION_MODE_FASTIV",
    "from wgfmu import WGFMU_MEASURE_EVENT_DATA_RAW",
    "def WGFMU_dcforceVoltage(ch, v): ...",
    "x = {'WGFMU_STATUS_COMPLETED': 10000}",
    "rc = WGFMU_PARAMETER_OUT_OF_RANGE_ERROR",
    "rc = WGFMU_NO_ERROR",
    "msg = f'call WGFMU_getMeasureValues({ch})'",
    "call(WGFMU_TRIGGER_OUT_MODE_EVENT=1)",
])
def test_detector_flags_library_symbols(source: str) -> None:
    assert symbol_hits(source)


@pytest.mark.parametrize("source", [
    '"""Docstring naming WGFMU_setMeasureEvent and WGFMU_OPERATION_MODE_DC."""',
    "WGFMU_SPEC = WgfmuSpec()",
    "from b1500_test_agent.models.sources import WGFMU_GRID_S, WGFMU_SEQUENCE_GAP_S",
    "WGFMU_RAW_FORMAT = 'b1500-wgfmu-raw'",
    "pattern = r'\\bWGFMU_\\w+'",
    "name = 'wgfmu_call'",
    "text = 'the WGFMU library'",
])
def test_detector_ignores_package_names_and_documentation(source: str) -> None:
    assert symbol_hits(source) == []
