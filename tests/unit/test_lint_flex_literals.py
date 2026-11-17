"""FLEX-literal lint (blueprint 2): only ``driver/commands.py`` spells FLEX commands in string literals.

Detector: every non-docstring string literal under ``src/b1500_test_agent`` (f-strings with each placeholder
rendered as ``0``, bytes decoded as latin-1) is searched for a mnemonic from the manual's command summary
(``references/manuals/structured/b1500a-command-summary.yaml``: detailed records and the grouped index), upper case,
in command position:

- at the start of the literal, of a line, or after ``;``, followed by end of text, ``?``, ``;``, ``,``, a digit, or
  whitespace plus a number (``DV 1,0,5``, ``AB``, ``*RST``, ``LOP?``, ``f"DV {ch},..."``);
- anywhere after whitespace when followed by whitespace and a number (``send DV 1,0,5``).

Ordinary words do not match: prose such as ``"DZ failed"`` or ``"AB testing"``, identifiers such as ``"SIM::x"``, and
response headers that are not mnemonics (``"LOP"``). Docstrings (module, class, function and attribute docstrings,
i.e. bare string statements) are documentation and are not scanned.

Exemptions (relative to ``src/b1500_test_agent``):
- ``driver/commands.py``: the builders, the one place FLEX text is assembled (blueprint 2.3);
- ``transport/sim/``: the simulator implements the instrument side of FLEX (blueprint 3).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "src" / "b1500_test_agent"
SUMMARY = ROOT / "references" / "manuals" / "structured" / "b1500a-command-summary.yaml"

ALLOWED_FILES = {"driver/commands.py": "FLEX builders and constants (blueprint 2.3)"}
EXEMPT_PREFIXES = {"transport/sim/": "simulator: the instrument side of FLEX (blueprint 3)"}


def flex_mnemonics() -> set[str]:
    data = yaml.safe_load(SUMMARY.read_text(encoding="utf-8"))
    names = {record["command"] for record in data["commands"]}
    for group in data["grouped_command_index"]:
        names.update(group["commands"])
    return names


def _patterns(mnemonics: set[str]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    alternation = "|".join(re.escape(m) for m in sorted(mnemonics, key=lambda m: (-len(m), m)))
    command_position = re.compile(rf"(?:^|;)[ \t]*({alternation})(?=$|[?;,\d]|\s+[-+.\d]|\s+$)", re.MULTILINE)
    after_space = re.compile(rf"(?<=\s)({alternation})(?=\s+[-+]?\d)")
    return command_position, after_space


PATTERNS = _patterns(flex_mnemonics())


def find_flex(text: str) -> list[str]:
    """Mnemonics found in command position in ``text`` (see the module docstring)."""
    command_position, after_space = PATTERNS
    return [m.group(1) for m in command_position.finditer(text)] + [m.group(1) for m in after_space.finditer(text)]


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Bare string statements: module/class/function docstrings and attribute docstrings."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def string_literals(source: str) -> list[tuple[int, str]]:
    """``(line, text)`` of every non-docstring string or bytes literal; f-string placeholders become ``0``."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                skip.add(id(value))
                parts.append(value.value if isinstance(value, ast.Constant) else "0")
            found.append((node.lineno, "".join(str(p) for p in parts)))
        elif isinstance(node, ast.Constant) and id(node) not in skip:
            if isinstance(node.value, str):
                found.append((node.lineno, node.value))
            elif isinstance(node.value, bytes):
                found.append((node.lineno, node.value.decode("latin-1")))
    return found


def flex_hits(path: Path) -> list[str]:
    hits = []
    for line, text in string_literals(path.read_text(encoding="utf-8")):
        hits.extend(f"{path.relative_to(ROOT).as_posix()}:{line}: {m} in {text!r}" for m in find_flex(text))
    return hits


def _scanned_files() -> list[Path]:
    files = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        rel = path.relative_to(PACKAGE_DIR).as_posix()
        if rel in ALLOWED_FILES or rel.startswith(tuple(EXEMPT_PREFIXES)):
            continue
        files.append(path)
    return files


def test_only_commands_py_holds_flex_mnemonics_in_string_literals() -> None:
    files = _scanned_files()
    assert any(p.name == "b1500.py" for p in files)  # the driver itself is scanned
    hits = [hit for path in files for hit in flex_hits(path)]
    assert hits == []


def test_commands_py_is_detected_so_the_lint_is_not_vacuous() -> None:
    hits = flex_hits(PACKAGE_DIR / "driver" / "commands.py")
    found = {hit.split(": ")[1].split(" in ")[0] for hit in hits}
    assert {"XE", "AB", "*RST", "*IDN?", "UNT?", "ERRX?", "LOP?", "DV", "WV", "CN", "MM", "WT"} <= found


@pytest.mark.parametrize(
    "text",
    [
        "DV 1,0,5,0.1",
        "AB",
        "*RST",
        "LOP?",
        "ERRX?",
        "UNT? 1",
        "XE",
        "CL",
        "MM 2,1,3",
        "WT 0.5,0.1",
        "RI 2,-20",
        "x;DV 1",
        "AB;CN",
        "send DV 1,0,5 now",
        "FMT 1,1\nXE",
        "DV ",
    ],
)
def test_detector_flags_commands(text: str) -> None:
    assert find_flex(text)


@pytest.mark.parametrize(
    "text",
    [
        "DZ failed",
        "AB testing",
        "Abort",
        "SIM::nmos_basic",
        "sim",
        "V",
        "I",
        "GNDU",
        "HRSMU",
        "B1500A",
        "LOP",
        "Table 4-3",
        "NAI+1.00000E-09",
        "cleanup AB then DZ",
        "*IDN? answer is malformed",
        "the CL state",
        "",
    ],
)
def test_detector_ignores_ordinary_text(text: str) -> None:
    assert find_flex(text) == []


def test_string_literal_extraction_skips_docstrings_and_renders_fstrings() -> None:
    source = '''
"""Module docstring: DV 1,0,5."""
X = 1
"""Attribute docstring: WV 1,1,0,0,1,11,1E-3."""
def f(ch):
    """Function docstring: AB."""
    x = f"DV {ch},0,{ch}"
    y = b"XE"
    return "AB" + x
'''
    texts = [text for _, text in string_literals(source)]
    assert "DV 0,0,0" in texts and "XE" in texts and "AB" in texts
    assert not any("docstring" in text for text in texts)
    assert sorted(m for text in texts for m in find_flex(text)) == ["AB", "DV", "XE"]
