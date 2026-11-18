"""Loader for the golden FLEX fixtures in ``tests/fixtures/flex/*.txt`` (shared by the driver parser tests and the
simulator formatter tests; the two implementations share no code, only these fixtures).

Fixture convention (one instrument response per file, UTF-8, LF line ends):

- A header of ``# key: value`` lines, then exactly one body line.
- Required keys: ``source`` (manual citation; must name at least one ``PDF <page>`` of ``B1500A Programming
  Guide.pdf``), ``kind`` (``fmt1``, ``fmt5``, ``idn``, ``unt``, ``errx``, ``lop``, ``stb``, ``tst`` or ``lrn``) and
  ``command`` (what produced the response, ``synthetic`` for coverage lists).
- Data kinds (``fmt1``/``fmt5``) also need ``terminator`` (``crlf`` or ``comma``) and one ``point`` line per
  element, in order: ``<status> <channel> <data type> <12-character data>``.
- Query kinds need ``expect``: JSON with the parsed result (its shape is defined per kind by the tests).
- ``note`` lines (any number) say what was transcribed and what was assumed.
- The body is the response as the instrument sends it, without the final CR/LF of ``terminator: crlf`` (``wire``
  adds it back); with ``terminator: comma`` the trailing comma is part of the body.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "flex"
DATA_KINDS = frozenset({"fmt1", "fmt5"})
QUERY_KINDS = frozenset({"idn", "unt", "errx", "lop", "stb", "tst", "lrn"})
_PDF_PAGE = re.compile(r"\bPDF \d+")


@dataclass(frozen=True)
class ExpectedPoint:
    """One ``point:`` line: status, channel and data-type letters and the 12-character data field."""

    status: str
    channel: str
    data_type: str
    data: str


@dataclass(frozen=True)
class FlexFixture:
    """A parsed fixture file."""

    path: Path
    kind: str
    source: str
    command: str
    terminator: str | None
    points: tuple[ExpectedPoint, ...]
    expect: Any
    notes: tuple[str, ...]
    body: str

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def wire(self) -> str:
        """The response including its terminator as sent on the bus."""
        return self.body + "\r\n" if self.terminator == "crlf" else self.body


def load_fixture(path: Path) -> FlexFixture:
    """Parse and validate one fixture file; raises ``ValueError`` when it breaks the convention."""
    header: dict[str, list[str]] = {}
    body_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not body_lines and line.startswith("#"):
            key, sep, value = line[1:].strip().partition(":")
            if not sep:
                raise ValueError(f"{path.name}: header line without 'key:': {line!r}")
            header.setdefault(key.strip(), []).append(value.strip())
        else:
            body_lines.append(line)
    if len(body_lines) != 1 or not body_lines[0]:
        raise ValueError(f"{path.name}: expected exactly one non-empty body line, got {len(body_lines)}")
    for key in ("source", "kind", "command"):
        if len(header.get(key, [])) != 1:
            raise ValueError(f"{path.name}: needs exactly one '{key}:' line")
    source, kind, command = header["source"][0], header["kind"][0], header["command"][0]
    if not _PDF_PAGE.search(source):
        raise ValueError(f"{path.name}: source must cite a 'PDF <page>'")
    terminator = None
    points: tuple[ExpectedPoint, ...] = ()
    expect: Any = None
    if kind in DATA_KINDS:
        terminator = (header.get("terminator") or [""])[0]
        if terminator not in ("crlf", "comma"):
            raise ValueError(f"{path.name}: terminator must be crlf or comma")
        parsed = [value.split() for value in header.get("point", [])]
        if not parsed or any(len(fields) != 4 for fields in parsed):
            raise ValueError(f"{path.name}: needs 'point: <status> <channel> <type> <data>' lines")
        points = tuple(ExpectedPoint(*fields) for fields in parsed)
    elif kind in QUERY_KINDS:
        if len(header.get("expect", [])) != 1:
            raise ValueError(f"{path.name}: needs exactly one 'expect:' line")
        expect = json.loads(header["expect"][0])
    else:
        raise ValueError(f"{path.name}: unknown kind {kind!r}")
    return FlexFixture(
        path=path,
        kind=kind,
        source=source,
        command=command,
        terminator=terminator,
        points=points,
        expect=expect,
        notes=tuple(header.get("note", [])),
        body=body_lines[0],
    )


def all_fixtures(*kinds: str) -> list[FlexFixture]:
    """Every fixture (or those of the given kinds), sorted by file name."""
    fixtures = [load_fixture(path) for path in sorted(FIXTURE_DIR.glob("*.txt"))]
    return [f for f in fixtures if not kinds or f.kind in kinds]
