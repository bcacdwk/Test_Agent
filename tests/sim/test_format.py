"""Simulator formatter (``transport/sim/format.py``) against golden fixtures in ``tests/fixtures/flex/format/``.

The Programming Guide prints no raw ASCII data strings, so each fixture builds the wire text from the element
definition (Table 1-6, PDF 50) and cites every table it relies on in its ``source:`` key; one fixture also checks
the character positions read by the manual's own program example (Table 3-7, PDF 206). Kinds: ``data`` (elements →
wire text), ``values`` (number → 12-character D field), ``channels`` (channel number → Table 1-11 letter). The
driver parser keeps its own, independent fixtures at the top level of ``tests/fixtures/flex/`` (blueprint 3).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.transport.sim import format as fmt
from tests.sim.helpers import FIXTURE_DIR

FORMAT_FIXTURES = sorted((FIXTURE_DIR / "flex" / "format").glob("*.yaml"))


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_fixture_set_is_complete() -> None:
    kinds = {load(p)["kind"] for p in FORMAT_FIXTURES}
    assert kinds == {"data", "values", "channels"} and len(FORMAT_FIXTURES) >= 6


@pytest.mark.parametrize("path", FORMAT_FIXTURES, ids=lambda p: p.stem)
def test_golden_fixture(path: Path) -> None:
    fixture = load(path)
    assert re.search(r"PDF \d+", fixture["source"]), "every fixture cites a PDF page"
    if fixture["kind"] == "data":
        elements = [fmt.Element(str(s), c if isinstance(c, int) else str(c), str(t), float(v))
                    for s, c, t, v in fixture["elements"]]
        wire = fmt.format_elements(elements, fixture["fmt"])
        assert wire == fixture["wire"]
        for start, length, expected in fixture.get("slices", []):
            assert wire[start - 1:start - 1 + length] == expected
        body = wire.removesuffix(fmt.terminator(fixture["fmt"]))
        assert all(len(e) == fmt.ELEMENT_WIDTH for e in body.split(","))
    elif fixture["kind"] == "values":
        for value, field in fixture["cases"]:
            assert fmt.format_value(float(value)) == field
            assert len(field) == 12 and float(field) == pytest.approx(float(value), rel=1e-5, abs=1e-99)
    else:
        for channel, letter in fixture["cases"]:
            assert fmt.channel_letter(channel) == letter


@pytest.mark.parametrize("value", [1e-15, 3.3e-12, -7.77777e-7, 0.5, 2.0, 99.99, 1e5, -1e-100])
def test_value_field_has_twelve_characters_and_engineering_exponent(value: float) -> None:
    field = fmt.format_value(value)
    match = re.fullmatch(r"([+-])(\d{1,3})\.(\d+)E([+-]\d\d)", field)
    assert match and len(field) == 12
    assert len(match.group(2)) + len(match.group(3)) == 6
    assert int(match.group(4)) % 3 == 0


@pytest.mark.parametrize(("bad", "error"), [(lambda: fmt.channel_letter(11), ValueError),
                                            (lambda: fmt.channel_letter(103), ValueError),
                                            (lambda: fmt.format_value(float("nan")), ValueError),
                                            (lambda: fmt.terminator(2), ValueError),
                                            (lambda: fmt.Element("Q", 1, "I", 0.0).text(), ValueError),
                                            (lambda: fmt.Element("N", 1, "q", 0.0).text(), ValueError)])
def test_invalid_inputs_are_rejected(bad: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        bad()


def test_formatter_shares_no_code_with_the_driver_parser() -> None:
    """Blueprint 3: ``format.py`` is written independently of ``driver/parser.py`` (no imports either way)."""
    source = Path(fmt.__file__).read_text(encoding="utf-8")
    imported = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)}
    imported |= {a.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for a in node.names}
    assert not any(name and ("driver" in name or "parser" in name) for name in imported)
