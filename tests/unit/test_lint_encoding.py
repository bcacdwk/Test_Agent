"""UTF-8 lint (AGENTS.md "Windows-safe code", blueprint v2 7.1/8.1, WP6.5): every text-mode file or pipe names its
encoding.

Without ``encoding=``, Python uses the locale's code page: UTF-8 on macOS, but cp1252 or cp936 on the Windows lab PC
unless ``PYTHONUTF8=1`` is set, so the same code reads or writes different bytes there (or fails on ``Ω``, ``µ`` and
CJK text). Scanned: every ``*.py`` under ``src/``, ``scripts/`` and ``tests/``. Flagged when no encoding is given:

- the builtin ``open(...)``/``io.open(...)`` in text mode (no ``b`` in the mode);
- ``<path>.open(mode, ...)`` with a literal text mode (``"r"``, ``"w"``, ``"a"``, ``"x"``, ``"+"``), or a text-only
  keyword (``newline``, ``errors``). A bare ``.open()`` is left out: in this code base it is a transport, a session
  or the run store, never a file;
- ``.read_text()`` / ``.write_text()`` (encoding as keyword or positional argument);
- ``subprocess.run|Popen|check_output|check_call|call`` with ``text=True`` / ``universal_newlines=True``;
- ``tempfile.TemporaryFile|NamedTemporaryFile|SpooledTemporaryFile`` in a text mode and ``io.TextIOWrapper``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("src", "scripts", "tests")
SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "check_call", "call"})
TEMPFILES = frozenset({"TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile"})
TEXT_ONLY_KEYWORDS = frozenset({"newline", "errors"})


def _keywords(node: ast.Call) -> set[str]:
    return {k.arg for k in node.keywords if k.arg is not None}


def _literal(node: ast.expr | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _mode(node: ast.Call, position: int) -> object:
    """The literal mode argument (positional ``position`` or keyword ``mode``); ``None`` when absent, ``...`` when
    not a literal."""
    if len(node.args) > position:
        value = _literal(node.args[position])
        return value if value is not None else ...
    for keyword in node.keywords:
        if keyword.arg == "mode":
            value = _literal(keyword.value)
            return value if value is not None else ...
    return None


def _has_encoding(node: ast.Call, position: int) -> bool:
    return "encoding" in _keywords(node) or len(node.args) > position


def _text_mode(mode: object) -> bool:
    return isinstance(mode, str) and "b" not in mode


def problems_in(source: str) -> list[tuple[int, str]]:
    """``(line, what)`` of every text-mode call without an encoding in ``source``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
        builtin_open = isinstance(func, ast.Name) and name == "open" or (owner == "io" and name == "open")
        if builtin_open:
            mode = _mode(node, 1)
            if (mode is None or _text_mode(mode)) and not _has_encoding(node, 3):
                found.append((node.lineno, f"open({mode!r}) without encoding"))
        elif name == "open" and isinstance(func, ast.Attribute):
            mode = _mode(node, 0)
            textish = _text_mode(mode) or (mode is None and bool(_keywords(node) & TEXT_ONLY_KEYWORDS))
            if textish and not _has_encoding(node, 2):
                found.append((node.lineno, f".open({mode!r}) without encoding"))
        elif name in ("read_text", "write_text") and isinstance(func, ast.Attribute):
            if not _has_encoding(node, 0 if name == "read_text" else 1):
                found.append((node.lineno, f".{name}() without encoding"))
        elif owner == "subprocess" and name in SUBPROCESS_CALLS:
            text = any(k.arg in ("text", "universal_newlines") and _literal(k.value) is True for k in node.keywords)
            if text and "encoding" not in _keywords(node):
                found.append((node.lineno, f"subprocess.{name}(text=True) without encoding"))
        elif name in TEMPFILES:
            mode = _mode(node, 0)
            if _text_mode(mode) and "encoding" not in _keywords(node):
                found.append((node.lineno, f"{name}({mode!r}) without encoding"))
        elif name == "TextIOWrapper" and "encoding" not in _keywords(node) and len(node.args) < 2:
            found.append((node.lineno, "TextIOWrapper without encoding"))
    return found


def scanned_files() -> list[Path]:
    return sorted(p for d in SCANNED_DIRS for p in (ROOT / d).rglob("*.py") if ".venv" not in p.parts)


def test_every_text_mode_io_names_its_encoding() -> None:
    files = scanned_files()
    assert len(files) > 300
    problems = [f"{path.relative_to(ROOT).as_posix()}:{line}: {what}"
                for path in files for line, what in problems_in(path.read_text(encoding="utf-8"))]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(("source", "count"), [
    ("open('x')", 1),
    ("open('x', 'w')", 1),
    ("open('x', 'rb')", 0),
    ("open('x', encoding='utf-8')", 0),
    ("io.open('x', 'a')", 1),
    ("p.open('w')", 1),
    ("p.open('w', encoding='utf-8', newline='\\n')", 0),
    ("p.open('xb')", 0),
    ("p.open(newline='')", 1),
    ("transport.open()", 0),
    ("store.open(run_id, unfinished=True)", 0),
    ("p.read_text()", 1),
    ("p.read_text('utf-8')", 0),
    ("p.write_text(s)", 1),
    ("p.write_text(s, 'utf-8')", 0),
    ("p.write_text(s, encoding='utf-8', newline='\\n')", 0),
    ("subprocess.run(['git'], text=True)", 1),
    ("subprocess.run(['git'], text=True, encoding='utf-8')", 0),
    ("subprocess.run(['git'], capture_output=True)", 0),
    ("tempfile.TemporaryFile('w+')", 1),
    ("tempfile.TemporaryFile('w+', encoding='utf-8')", 0),
    ("io.TextIOWrapper(buf)", 1),
    ("io.TextIOWrapper(buf, encoding='cp1252')", 0),
])
def test_the_lint_flags_exactly_the_text_mode_calls(source: str, count: int) -> None:
    assert len(problems_in(source)) == count, source
