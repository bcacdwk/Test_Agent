"""The manual-corpus fixture (blueprint 8.1 ``fixtures/manuals/``): a hand-written two-page PDF, generated
deterministically (no dates, no ids), plus the tiny corpus ``corpus/`` built from it with ``catalog.yaml``.

The PDF exercises what the real manuals need: a chapter title page without a printed label (inferred ``9-1``), a
running header ``9-2 Fixture Guide, Edition 1``, a nested outline (``9 Fixture Commands`` > ``FIXCMD``,
``WGFMU_fixtureEvent``), Simplified Chinese text (predefined CJK font STSong-Light, UniGB-UCS2-H), private-use
glyphs (a font whose ToUnicode map sends W, m and 0xB1 to U+F057, U+F06D, U+F0B1, like the manuals' Symbol fonts), a
word hyphenated across two lines (PDFium marks it with U+0002) and table-of-contents leader dots.

Regenerate the committed corpus after changing this file or ``catalog.yaml`` (update the catalog's sha256 and size
first; ``fixture_pdf()`` prints them):

    uv run python -m tests.fixtures.manuals.make_fixture
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
PDF_NAME = "fixture-guide.pdf"

_TO_UNICODE = (
    b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering "
    b"(UCS) /Supplement 0 >> def /CMapName /Adobe-Identity-UCS def /CMapType 2 def 1 begincodespacerange <00> <FF> "
    b"endcodespacerange 3 beginbfchar <57> <F057> <6D> <F06D> <B1> <F0B1> endbfchar endcmap CMapName currentdict "
    b"/CMap defineresource pop end end"
)


def _literal(text: str) -> str:
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _ucs2(text: str) -> str:
    return "<" + "".join(f"{ord(char):04X}" for char in text) + ">"


def _content(runs: list[tuple[int, int, str, int, str]]) -> bytes:
    """Text runs ``(x, y, font, size, operand)`` as a content stream."""
    return "\n".join(f"BT /{font} {size} Tf {x} {y} Td {operand} Tj ET" for x, y, font, size, operand in runs
                     ).encode("latin-1")


def _stream(data: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


PAGE_1 = _content([
    (72, 720, "F1", 14, _literal("9 Fixture Commands")),
    (72, 690, "F1", 10, _literal("FIXCMD sets the fixture selector output state.")),
    (72, 676, "F1", 10, _literal("The output impedance is 50 ")), (196, 676, "F3", 10, _literal("W")),
    (72, 662, "F2", 10, _ucs2("随机电报噪声 开路校正")),
    (72, 648, "F1", 10, _literal("No part may be repro-")),
    (72, 634, "F1", 10, _literal("duced without consent; range 1 ")), (210, 634, "F3", 10, _literal("m")),
    (217, 634, "F1", 10, _literal("A to 10 mA, ")), (270, 634, "F3", 10, "<B1>"),
    (276, 634, "F1", 10, _literal("5 %.")),
])
PAGE_2 = _content([
    (72, 750, "F1", 9, _literal("9-2 Fixture Guide, Edition 1")),
    (72, 720, "F1", 10, _literal("WGFMU_fixtureEvent defines a measure event of the fixture.")),
    (72, 706, "F1", 10, _literal("Status 3 means PGU open.")),
    (72, 692, "F1", 10, _literal("FIXCMD . . . . . . . . . . 9-1")),
])

_RESOURCES = b"/Resources << /Font << /F1 7 0 R /F2 8 0 R /F3 9 0 R >> >>"
_OBJECTS: list[bytes] = [
    b"<< /Type /Catalog /Pages 2 0 R /Outlines 12 0 R /PageMode /UseOutlines >>",  # 1
    b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",  # 2
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] " + _RESOURCES + b" /Contents 5 0 R >>",  # 3
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] " + _RESOURCES + b" /Contents 6 0 R >>",  # 4
    _stream(PAGE_1),  # 5
    _stream(PAGE_2),  # 6
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",  # 7
    b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [10 0 R] >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 11 0 R >>",  # 9
    (b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering "
     b"(GB1) /Supplement 4 >> /FontDescriptor 16 0 R >>"),  # 10
    _stream(_TO_UNICODE),  # 11
    b"<< /Type /Outlines /First 13 0 R /Last 13 0 R /Count 3 >>",  # 12
    b"<< /Title (9 Fixture Commands) /Parent 12 0 R /First 14 0 R /Last 15 0 R /Count 2 /Dest [3 0 R /Fit] >>",
    b"<< /Title (FIXCMD) /Parent 13 0 R /Next 15 0 R /Dest [3 0 R /Fit] >>",  # 14
    b"<< /Title (WGFMU_fixtureEvent) /Parent 13 0 R /Prev 14 0 R /Dest [4 0 R /Fit] >>",  # 15
    (b"<< /Type /FontDescriptor /FontName /STSong-Light /Flags 6 /FontBBox [0 -200 1000 900] /ItalicAngle 0 "
     b"/Ascent 880 /Descent -120 /CapHeight 880 /StemV 80 >>"),  # 16
]


def fixture_pdf() -> bytes:
    """The fixture PDF: same bytes on every call and platform (PDF 1.4, classic xref table)."""
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(_OBJECTS, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(_OBJECTS) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(_OBJECTS) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def fixture_tree(target: Path, *, with_corpus: bool = True, with_pdf: bool = True) -> Path:
    """A ``references/manuals``-like folder at ``target`` (catalog, synonyms, extracts, optionally the committed
    corpus) and, with ``with_pdf``, the PDF in ``target/pdfs/``. Returns ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    for name in ("catalog.yaml", "synonyms.yaml"):
        shutil.copy(FIXTURE_DIR / name, target / name)
    shutil.copytree(FIXTURE_DIR / "extracts", target / "extracts", dirs_exist_ok=True)
    if with_corpus:
        shutil.copytree(FIXTURE_DIR / "corpus", target / "corpus", dirs_exist_ok=True)
    if with_pdf:
        (target / "pdfs").mkdir(exist_ok=True)
        (target / "pdfs" / PDF_NAME).write_bytes(fixture_pdf())
    return target


def main() -> int:
    """Print the PDF's sha256/size and rebuild ``corpus/`` from it with the committed catalog."""
    from b1500_test_agent.manuals.build import build_corpus
    from b1500_test_agent.manuals.catalog import ManualPaths

    data = fixture_pdf()
    print(f"{PDF_NAME}: sha256 {hashlib.sha256(data).hexdigest()} size {len(data)}")
    with tempfile.TemporaryDirectory() as temp:
        pdfs = Path(temp)
        (pdfs / PDF_NAME).write_bytes(data)
        report = build_corpus(ManualPaths(references=FIXTURE_DIR, manuals_dir=pdfs, manuals_dir_source="fixture"))
    print(report.message)
    for line in report.warnings + report.problems:
        print(f"  {line}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
