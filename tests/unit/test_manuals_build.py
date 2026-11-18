"""Manual corpus build (blueprint 5.2, WP5.8): text normalisation, printed labels, outline paths, and the build /
``--check`` of the hand-written fixture PDF against the committed tiny corpus (``tests/fixtures/manuals/``)."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.manuals.build import (
    build_corpus,
    extract_pdf,
    infer_labels,
    normalize_label,
    normalize_text,
    outline_bytes,
    outline_paths,
    page_label,
    pages_bytes,
    read_pages,
    symbol_table,
)
from b1500_test_agent.manuals.catalog import ManualPaths, load_catalog
from b1500_test_agent.models.manuals import CorpusOutline, DocOutline, OutlineEntry
from tests.fixtures.manuals.make_fixture import FIXTURE_DIR, PDF_NAME, fixture_pdf, fixture_tree

pytestmark = pytest.mark.manuals

TABLE = symbol_table({"F057": "Ω", "F06D": "µ"})


def paths_for(tree: Path, pdfs: Path | None = None) -> ManualPaths:
    return ManualPaths(references=tree, manuals_dir=pdfs or tree / "pdfs", manuals_dir_source="test")


# -- normalisation ----------------------------------------------------------------------------------------------------


def test_normalize_text_cleans_pdfium_output() -> None:
    raw = ("Header  line \r\nrepro\x02duced and Id\x02\r\nVg\r\n50 , 1 A,  V\x1fend\t!\r\n"
           "\r\n\r\n\r\nFMT . . . . . . . . 4-118\r\n")
    unmapped: Counter[str] = Counter()
    text = normalize_text(raw + "", TABLE, unmapped)
    assert text.split("\n") == ["Header line", "reproduced and IdVg", "50 Ω, 1 µA, 10 V end !", "", "FMT ... 4-118"]
    assert unmapped == Counter({"U+F0FF": 1})


def test_symbol_table_falls_back_to_ascii_for_symbol_font_digits() -> None:
    table = symbol_table({})
    assert "".translate(table) == "*B15-9"
    assert "".translate(symbol_table({"F057": "Ω"})) == "Ω"
    assert 0xF0B1 not in table  # outside U+F020..U+F07E: only the catalog can map it


@pytest.mark.parametrize(("label", "expected"), [("4-115", "4-115"), ("4- 07", "4-7"), ("05", "5"),
                                                 ("Contents - 1", "Contents-1"), ("A-6", "A-6")])
def test_normalize_label(label: str, expected: str) -> None:
    assert normalize_label(label) == expected


PG_RULE = re.compile(r"^(?:([0-9A-Z]{1,2}-\d{1,3}) Keysight B1500 Series Programming Guide, Edition \d+|"
                     r"Keysight B1500 Series Programming Guide, Edition \d+ ([0-9A-Z]{1,2}-\d{1,3}))$")


@pytest.mark.parametrize(("text", "label"), [
    ("Keysight B1500 Series Programming Guide, Edition 15 4-115\nCommand Reference\nERSSP", "4-115"),
    ("4-116 Keysight B1500 Series Programming Guide, Edition 15\nCommand Reference", "4-116"),
    ("body\nmore\neven more\nlast\n4-2 Keysight B1500 Series Programming Guide, Edition 15", "4-2"),
    ("Contents\nKeysight B1500 Series Programming Guide, Edition 15\nBSVM ... 4-57", ""),
    ("one\ntwo\nthree\nKeysight B1500 Series Programming Guide, Edition 15 4-9\nfive\nsix\nseven", ""),
])
def test_page_label_reads_the_first_and_last_three_lines(text: str, label: str) -> None:
    assert page_label(text, PG_RULE) == label


def test_infer_labels_fills_chapter_title_pages_only() -> None:
    labels = ["", "", "", "1-2", "1-3", "", "2-2", "", "", "", "3", "4", "", "", "5-9", "", "5-11"]
    assert infer_labels(labels) == ["", "", "1-1", "1-2", "1-3", "2-1", "2-2", "", "1", "2", "3", "4", "5-7",
                                    "5-8", "5-9", "5-10", "5-11"]
    assert infer_labels(["1-3", "", "1-4"]) == ["1-3", "", "1-4"]  # predecessor already claims 1-3
    assert infer_labels(["", "", "2"]) == ["", "1", "2"]


def test_outline_paths_show_the_entry_of_each_page() -> None:
    outline = [OutlineEntry(level=0, title="Guide", p=1), OutlineEntry(level=1, title="4 Commands", p=3),
               OutlineEntry(level=2, title="Reference", p=3), OutlineEntry(level=3, title="SER", p=5),
               OutlineEntry(level=3, title="SER?", p=5), OutlineEntry(level=3, title="SIM", p=6),
               OutlineEntry(level=1, title="5 Errors", p=8)]
    paths = outline_paths(outline, 9)
    assert paths == ["Guide", "Guide", "Guide > 4 Commands > Reference", "Guide > 4 Commands > Reference",
                     "Guide > 4 Commands > Reference > SER", "Guide > 4 Commands > Reference > SIM",
                     "Guide > 4 Commands > Reference > SIM", "Guide > 5 Errors", "Guide > 5 Errors"]
    assert outline_paths([OutlineEntry(level=0, title="Late", p=3)], 3) == ["", "", "Late"]


def test_serialisation_is_deterministic() -> None:
    lines = ['{"doc":"FX","p":1,"printed":"","outline_path":"","text":"µ 随机"}']
    data = pages_bytes(lines)
    assert data == pages_bytes(lines)
    assert data[:4] == b"\x1f\x8b\x08\x00"  # gzip, deflate, no FNAME flag
    assert data[4:8] == b"\x00\x00\x00\x00"  # mtime 0
    assert read_pages(data) == lines
    outline = CorpusOutline(catalog="0" * 64, docs={
        "FX": DocOutline(sha256="1" * 64, pages=1, chars=4, outline=[OutlineEntry(level=0, title="Ω", p=1)]),
        "FY": DocOutline(sha256="2" * 64, pages=1, chars=0, outline=[])})
    text = outline_bytes(outline).decode("utf-8")
    assert CorpusOutline.model_validate_json(text) == outline
    assert '"title":"Ω"' in text and "\r" not in text and text.endswith("}\n")


# -- the fixture PDF ---------------------------------------------------------------------------------------------------


def test_fixture_pdf_is_deterministic_and_pinned_by_the_catalog() -> None:
    data = fixture_pdf()
    assert data == fixture_pdf() and data.startswith(b"%PDF-1.4")
    doc = load_catalog(FIXTURE_DIR / "catalog.yaml").docs[0]
    assert (hashlib.sha256(data).hexdigest(), len(data), doc.file) == (doc.sha256, doc.size, PDF_NAME)


def test_extract_pdf_reads_labels_outline_symbols_cjk_and_hyphens() -> None:
    catalog = load_catalog(FIXTURE_DIR / "catalog.yaml")
    item = extract_pdf(catalog.docs[0], fixture_pdf(), "x" * 64, symbol_table(catalog.symbols))
    first, second = item.pages
    assert [first.printed, second.printed] == ["9-1", "9-2"]  # 9-1 inferred from the running header 9-2
    assert first.outline_path == "9 Fixture Commands > FIXCMD"
    assert second.outline_path == "9 Fixture Commands > WGFMU_fixtureEvent"
    assert [(e.level, e.title, e.p) for e in item.outline] == [(0, "9 Fixture Commands", 1), (1, "FIXCMD", 1),
                                                               (1, "WGFMU_fixtureEvent", 2)]
    assert "50 Ω" in first.text and "1 µA" in first.text and "±5 %" in first.text
    assert "随机电报噪声 开路校正" in first.text and "reproduced" in first.text
    assert second.text.endswith("FIXCMD ... 9-1") and not item.unmapped


def test_unlisted_private_use_glyphs_are_dropped_and_reported(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref")
    catalog = yaml.safe_load((tree / "catalog.yaml").read_text(encoding="utf-8"))
    del catalog["symbols"]["F0B1"]
    (tree / "catalog.yaml").write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    report = build_corpus(paths_for(tree))
    assert report.ok and any("U+F0B1 x1" in w and "catalog symbols" in w for w in report.warnings)


# -- build and check ---------------------------------------------------------------------------------------------------


def test_build_reproduces_the_committed_tiny_corpus(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref", with_corpus=False)
    report = build_corpus(paths_for(tree))
    assert report.ok and report.mode == "build" and report.pages == 2, report
    [doc] = report.docs
    assert (doc.id, doc.pdf, doc.pages, doc.labelled, doc.outline) == ("FX", "ok", 2, 2, 3)
    committed = FIXTURE_DIR / "corpus"
    assert read_pages((tree / "corpus/pages.jsonl.gz").read_bytes()) == read_pages(
        (committed / "pages.jsonl.gz").read_bytes())
    assert (tree / "corpus/outline.json").read_bytes() == (committed / "outline.json").read_bytes()
    assert report.corpus_bytes == sum(f.stat().st_size for f in (tree / "corpus").iterdir())


def test_check_compares_byte_for_byte_and_writes_nothing(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref")
    before = {p.name: p.read_bytes() for p in (tree / "corpus").iterdir()}
    report = build_corpus(paths_for(tree), check=True)
    assert report.ok and report.mode == "check" and report.identical is True, report
    assert report.docs[0].check == "identical"
    assert {p.name: p.read_bytes() for p in (tree / "corpus").iterdir()} == before

    lines = read_pages(before["pages.jsonl.gz"])
    record = json.loads(lines[1])
    record["text"] += " edited"
    lines[1] = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    (tree / "corpus/pages.jsonl.gz").write_bytes(pages_bytes(lines))
    differs = build_corpus(paths_for(tree), check=True)
    assert not differs.ok and differs.identical is False and differs.docs[0].check == "differs"
    assert "differs from a rebuild: FX" in differs.message


def test_check_tolerates_a_different_gzip_encoder_of_the_same_content(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref")
    payload = gzip.decompress((tree / "corpus/pages.jsonl.gz").read_bytes())
    (tree / "corpus/pages.jsonl.gz").write_bytes(gzip.compress(payload, compresslevel=1, mtime=0))
    report = build_corpus(paths_for(tree), check=True)
    assert report.ok and report.identical is True and "differ only by the zlib build" in report.message


def test_check_with_a_stale_catalog_digest_fails(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref")
    catalog = yaml.safe_load((tree / "catalog.yaml").read_text(encoding="utf-8"))
    catalog["symbols"]["F0B4"] = "×"
    (tree / "catalog.yaml").write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    report = build_corpus(paths_for(tree), check=True)
    assert not report.ok and report.identical is False and "catalog digest" in report.message


def test_build_refuses_missing_pdfs_and_writes_nothing(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref", with_corpus=False, with_pdf=False)
    report = build_corpus(paths_for(tree))
    assert not report.ok and report.docs[0].pdf == "missing"
    assert "missing PDFs: FX" in report.message and "nothing written" in report.message
    assert not (tree / "corpus").exists()


def test_check_without_pdfs_is_not_verified_and_partial_check_names_missing_docs(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref", with_pdf=False)
    report = build_corpus(paths_for(tree), check=True)
    assert report.ok and report.identical is None and "not verified" in report.message
    tree = fixture_tree(tmp_path / "ref2")
    catalog = yaml.safe_load((tree / "catalog.yaml").read_text(encoding="utf-8"))
    extra = dict(catalog["docs"][0], id="FY", file="other.pdf", sha256="ab" * 32)
    catalog["docs"].append(extra)
    (tree / "catalog.yaml").write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    partial = build_corpus(paths_for(tree), check=True)
    assert "partial check: 1/1 present docs identical; not checked (PDF missing): FY" in partial.message
    assert partial.identical is None and [d.check for d in partial.docs] == ["identical", "not_checked"]


def test_edition_mismatch_warns_and_builds_from_the_found_file(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref", with_corpus=False)
    (tree / "pdfs" / PDF_NAME).write_bytes(fixture_pdf() + b"% another edition\n")
    report = build_corpus(paths_for(tree))
    assert report.ok and report.docs[0].pdf == "mismatch"
    assert any("edition mismatch" in w and "update catalog.yaml" in w for w in report.warnings)
    assert (tree / "corpus/pages.jsonl.gz").is_file()


def test_build_finds_a_renamed_copy_by_size_and_sha256(tmp_path: Path) -> None:
    tree = fixture_tree(tmp_path / "ref", with_corpus=False, with_pdf=False)
    nested = tmp_path / "pdfs" / "deeper" / "folder"
    nested.mkdir(parents=True)
    (nested / "renamed copy.pdf").write_bytes(fixture_pdf())
    (tmp_path / "pdfs" / "unrelated.pdf").write_bytes(b"%PDF-1.4 not a manual")
    report = build_corpus(paths_for(tree, tmp_path / "pdfs"))
    assert report.ok and report.docs[0].pdf == "ok" and report.docs[0].path.endswith("renamed copy.pdf")
