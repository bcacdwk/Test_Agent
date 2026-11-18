"""Manual queries (blueprint 5.2, WP5.8): tokenizer, BM25 ranking, title hits, OR-relax and synonyms, ``page``,
``toc`` and ``status`` on a synthetic corpus; the structured-extract fallback on the fixture tree; and the AC queries
on the committed corpus (always present, OD-1). One test rebuilds the real corpus when the PDFs are available."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.manuals import search
from b1500_test_agent.manuals.build import build_corpus, outline_bytes, page_line, pages_bytes
from b1500_test_agent.manuals.catalog import (
    CORPUS_BUDGET_BYTES,
    ENV_MANUALS_DIR,
    ManualError,
    ManualPaths,
    build_digest,
    load_catalog,
)
from b1500_test_agent.models.manuals import CorpusOutline, CorpusPage, DocOutline, ManualCatalog, OutlineEntry
from tests.fixtures.manuals.make_fixture import fixture_tree

pytestmark = pytest.mark.manuals

REPO = Path(__file__).resolve().parents[2]
REAL = ManualPaths(references=REPO / "references" / "manuals", manuals_dir=REPO / "no-pdfs-here", repo_root=REPO)
RULE = r"^(\d+-\d+) Header$"

PAGES: dict[str, list[tuple[str, str, str]]] = {
    "AA": [
        ("1-1", "Guide > 1 Intro", "1-1 Header\nThe selector routes the pulse generator to the device."),
        ("1-2", "Guide > Commands > ERSSP", ("1-2 Header\nERSSP\nERSSP port,status sets the selector path. "
                                             "Status 3 means PGU open. " + "Filler words about relays. " * 20)),
        ("1-3", "Guide > Commands > ERSSP?", "1-3 Header\nERSSP? returns the selector status of a port."),
        ("1-4", "Guide > Commands > WGFMU_setMeasureEvent", "1-4 Header\nWGFMU_setMeasureEvent defines events."),
        ("1-4", "Guide > Commands > WGFMU_setMeasureEvent", "Overflow page with the same running label."),
    ],
    "BB": [
        ("4-55", "UG > WGFMU_setMeasureEvent", ("WGFMU_setMeasureEvent WGFMU_setMeasureEvent defines a measure "
                                                "event (older edition) WGFMU_setMeasureEvent.")),
        ("4-56", "UG > Status", "status status status selector selector status of the older unit."),
    ],
    "AN-ZH": [
        ("1", "", "随机电报噪声（RTN）是 MOSFET 中的一种噪声。"),
        ("2", "", "先做开路校正，再做短路校正。µA 量程。"),
    ],
}
OUTLINES = {
    "AA": [OutlineEntry(level=0, title="Guide", p=1), OutlineEntry(level=1, title="1 Intro", p=1),
           OutlineEntry(level=1, title="Commands", p=2), OutlineEntry(level=2, title="ERSSP", p=2),
           OutlineEntry(level=2, title="ERSSP?", p=3), OutlineEntry(level=2, title="WGFMU_setMeasureEvent", p=4)],
    "BB": [OutlineEntry(level=0, title="UG", p=1), OutlineEntry(level=1, title="WGFMU_setMeasureEvent", p=1),
           OutlineEntry(level=1, title="Status", p=2)],
    "AN-ZH": [],
}


def _doc(doc_id: str, pages: int, priority: float, language: str = "en") -> dict[str, object]:
    return {"id": doc_id, "file": f"{doc_id}.pdf", "title": f"Manual {doc_id}", "edition": "Edition 1",
            "sha256": "ab" * 32, "size": 100, "pages": pages, "language": language, "kind": "user_guide",
            "priority": priority, "label_rule": RULE}


def make_tree(root: Path, *, with_corpus: bool = True) -> ManualPaths:
    """A references folder with a three-document catalog, synonyms and (optionally) its corpus."""
    root.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "symbols": {}, "docs": [_doc("AA", 5, 1.5), _doc("BB", 2, 0.8),
                                                  _doc("AN-ZH", 2, 1.0, "zh")]}
    (root / "catalog.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (root / "synonyms.yaml").write_text(yaml.safe_dump({"synonyms": {"switchbox": ["selector"]}},
                                                       allow_unicode=True), encoding="utf-8")
    if with_corpus:
        catalog = ManualCatalog.model_validate(data)
        lines = [page_line(CorpusPage(doc=doc, p=i, printed=printed, outline_path=path, text=text))
                 for doc, pages in PAGES.items() for i, (printed, path, text) in enumerate(pages, 1)]
        outline = CorpusOutline(catalog=build_digest(catalog), docs={
            doc: DocOutline(sha256="ab" * 32, pages=len(pages), chars=sum(len(t) for _, _, t in pages),
                            outline=OUTLINES[doc]) for doc, pages in PAGES.items()})
        (root / "corpus").mkdir()
        (root / "corpus" / "pages.jsonl.gz").write_bytes(pages_bytes(lines))
        (root / "corpus" / "outline.json").write_bytes(outline_bytes(outline))
    return ManualPaths(references=root, manuals_dir=root / "pdfs", manuals_dir_source="test")


@pytest.fixture
def tree(tmp_path: Path) -> ManualPaths:
    return make_tree(tmp_path / "ref")


# -- tokenizer and BM25 ------------------------------------------------------------------------------------------------


def test_tokenize_keeps_mnemonics_and_wgfmu_names_whole_and_bigrams_cjk() -> None:
    assert search.tokenize("ERSSP? port,status of the B1500A") == ["erssp", "port", "status", "b1500a"]
    assert search.tokenize("Call WGFMU_setMeasureEvent(ch)") == ["call", "wgfmu_setmeasureevent", "ch"]
    assert search.tokenize("随机电报噪声 开路") == ["随机", "机电", "电报", "报噪", "噪声", "开路"]
    assert search.tokenize("噪 4-115") == ["噪", "4", "115"]
    assert search.tokenize("1 µA") == search.tokenize("1 μA") == ["1", "μa"]  # NFKC: micro sign = mu
    assert search.tokenize("ＥＲＳＳＰ") == ["erssp"]  # full width folds to ASCII


def test_bm25_prefers_rare_terms_and_honours_and_or() -> None:
    from collections import Counter

    bags = [Counter({"common": 3, "rare": 1}), Counter({"common": 5}), Counter({"common": 1, "other": 1})]
    index = search.Bm25(bags, [1.0, 1.0, 1.0])
    assert index.idf("rare") > index.idf("common")
    assert set(index.score(["common", "rare"], require_all=True)) == {0}
    assert set(index.score(["rare", "other"], require_all=False)) == {0, 2}
    weighted = search.Bm25(bags, [1.0, 1.0, 10.0]).score(["common"], require_all=True)
    assert max(weighted, key=lambda i: weighted[i]) == 2


def test_snippet_is_short_and_centred_on_the_term() -> None:
    text = "intro " * 100 + "the ERSSP command " + "tail " * 100
    snip = search.snippet(text, ["erssp"])
    assert len(snip) <= search.SNIPPET_CHARS and "ERSSP" in snip and snip.startswith("…") and snip.endswith("…")
    assert search.snippet("short text", ["absent"]) == "short text"
    assert search.cite("PG", 433, "4-115") == "PG p433 (4-115)" and search.cite("PG", 5) == "PG p5"


# -- search -----------------------------------------------------------------------------------------------------------


def test_exact_title_hit_ranks_first(tree: ManualPaths) -> None:
    result = search.search(tree, "ERSSP status")
    assert result.ok and result.source == "corpus" and result.match == "all"
    top = result.hits[0]
    assert (top.doc, top.p, top.printed, top.title, top.title_hit) == ("AA", 2, "1-2", "ERSSP", True)
    assert top.cite == "AA p2 (1-2)" and "Header" not in top.snippet and len(top.snippet) <= 240
    # "Status" (BB p2) is a section title, not a command name: no title hit for the word "status"
    assert [h.title_hit for h in result.hits[1:]] == [False] * (len(result.hits) - 1)


def test_title_hits_prefer_the_more_authoritative_document(tree: ManualPaths) -> None:
    result = search.search(tree, "WGFMU_setMeasureEvent")
    assert [(h.doc, h.p, h.title_hit) for h in result.hits[:2]] == [("AA", 4, True), ("BB", 1, True)]
    data = yaml.safe_load(tree.catalog.read_text(encoding="utf-8"))
    data["docs"][0]["priority"], data["docs"][1]["priority"] = 0.8, 1.5
    tree.catalog.write_text(yaml.safe_dump(data), encoding="utf-8")
    flipped = search.search(tree, "WGFMU_setMeasureEvent")
    assert [(h.doc, h.p) for h in flipped.hits[:2]] == [("BB", 1), ("AA", 4)]


def test_whole_query_equal_to_a_title_is_a_title_hit(tree: ManualPaths) -> None:
    hit = search.search(tree, "1 intro").hits[0]
    assert (hit.doc, hit.p, hit.title_hit) == ("AA", 1, True)


def test_cjk_query_finds_the_chinese_page(tree: ManualPaths) -> None:
    result = search.search(tree, "随机电报噪声")
    assert [(h.doc, h.p) for h in result.hits] == [("AN-ZH", 1)]
    assert search.search(tree, "开路 校正").hits[0].doc == "AN-ZH"


def test_zero_hits_relax_to_any_term_then_synonyms(tree: ManualPaths) -> None:
    relaxed = search.search(tree, "selector zzzz")
    assert relaxed.ok and relaxed.match == "any" and "any term" in relaxed.message
    synonym = search.search(tree, "switchbox")
    assert synonym.ok and synonym.match == "synonyms" and "selector" in synonym.terms
    none = search.search(tree, "qqqq")
    assert not none.ok and none.match == "none" and none.hits == [] and "no page matches" in none.message


def test_doc_filter_and_k(tree: ManualPaths) -> None:
    only = search.search(tree, "status", docs=["bb"], k=1)
    assert only.docs == ["BB"] and [h.doc for h in only.hits] == ["BB"]
    with pytest.raises(ManualError, match="unknown manual 'XX'") as excinfo:
        search.search(tree, "status", docs=["XX"])
    assert excinfo.value.usage
    with pytest.raises(ManualError, match="no searchable words"):
        search.search(tree, "?! ...")
    with pytest.raises(ManualError, match="-k"):
        search.search(tree, "status", k=0)


def test_stale_corpus_still_answers_and_says_so(tree: ManualPaths) -> None:
    data = yaml.safe_load(tree.catalog.read_text(encoding="utf-8"))
    data["docs"][0]["label_rule"] = r"^(\d+)$"
    tree.catalog.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = search.search(tree, "ERSSP")
    assert result.ok and "stale" in result.message
    assert search.status(tree).corpus == "stale"


# -- page / toc / status -----------------------------------------------------------------------------------------------


def test_page_by_number_range_and_printed_label(tree: ManualPaths) -> None:
    one = search.page(tree, "aa", 2)
    assert [p.cite for p in one.pages] == ["AA p2 (1-2)"] and "ERSSP port,status" in one.pages[0].text
    many = search.page(tree, "AA", 2, to=5)
    assert [p.p for p in many.pages] == [2, 3, 4] and "at most 3 pages" in many.message
    printed = search.page(tree, "AA", printed="1-4")
    assert [p.p for p in printed.pages] == [4] and "also on PDF page(s) 5" in printed.message
    assert search.page(tree, "BB", 2, to=9).pages[-1].p == 2


def test_page_truncates_and_rejects_bad_requests(tree: ManualPaths) -> None:
    short = search.page(tree, "AA", 2, to=3, max_chars=200)
    assert short.pages[0].truncated and len(short.pages) == 1 and "--max-chars" in short.message
    for kwargs, message in [({"p": 9}, "PDF pages 1..5"), ({"p": 3, "to": 2}, "--to"),
                            ({"printed": "9-9"}, "labels 1-1 .. 1-4"), ({}, "one of them"),
                            ({"p": 1, "printed": "1-1"}, "one of them"), ({"p": 1, "max_chars": 10}, "--max-chars")]:
        with pytest.raises(ManualError, match=message):
            search.page(tree, "AA", **kwargs)  # type: ignore[arg-type]


def test_toc_lists_outline_with_labels_and_filters(tree: ManualPaths) -> None:
    full = search.toc(tree, "AA")
    assert [(e.level, e.title, e.p, e.printed) for e in full.entries][:3] == [
        (0, "Guide", 1, "1-1"), (1, "1 Intro", 1, "1-1"), (1, "Commands", 2, "1-2")]
    assert [e.title for e in search.toc(tree, "AA", grep="erssp").entries] == ["ERSSP", "ERSSP?"]
    assert [e.title for e in search.toc(tree, "AA", grep="ERSSP?").entries] == ["ERSSP", "ERSSP?"]
    assert search.toc(tree, "AA", grep="[").entries == []  # invalid regex -> literal text
    bare = search.toc(tree, "AN-ZH")
    assert bare.ok and bare.entries == [] and "manual page AN-ZH 1 --to 2" in bare.message


def test_status_reports_corpus_state(tree: ManualPaths, tmp_path: Path) -> None:
    current = search.status(tree)
    assert current.ok and current.corpus == "current" and current.docs_in_corpus == 3
    assert current.pages_in_corpus == 9 and current.catalog_pages == 9 and current.pdfs_found == 0
    assert [d.pdf for d in current.docs] == ["missing"] * 3 and "PDFs 0/3" in current.message
    tree.pages.write_bytes(b"not gzip")
    invalid = search.status(tree)
    assert not invalid.ok and invalid.corpus == "invalid" and "unreadable" in invalid.message
    with pytest.raises(ManualError, match="unreadable"):
        search.search(tree, "status")
    missing = make_tree(tmp_path / "bare", with_corpus=False)
    state = search.status(missing)
    assert not state.ok and state.corpus == "missing" and "manual build" in state.message


# -- structured-extract fallback ---------------------------------------------------------------------------------------


@pytest.fixture
def bare(tmp_path: Path) -> ManualPaths:
    root = fixture_tree(tmp_path / "ref", with_corpus=False, with_pdf=False)
    return ManualPaths(references=root, manuals_dir=root / "pdfs", manuals_dir_source="test")


def test_search_without_corpus_answers_from_the_extracts(bare: ManualPaths) -> None:
    result = search.search(bare, "FIXCMD selector")
    assert result.ok and result.source == "extracts"
    assert (result.hits[0].doc, result.hits[0].p, result.hits[0].source) == ("FX", 1, "extracts")
    row = next(h for h in result.hits if h.ref.startswith("extracts/fixture-index.md:L"))
    assert (row.p, row.printed, row.cite) == (1, "9-1", "FX p1 (9-1)")
    assert "uv run b1500 manual build" in result.message
    assert search.search(bare, "measure event").hits[0].p == 2


def test_page_and_toc_without_corpus(bare: ManualPaths) -> None:
    page = search.page(bare, "FX", 1)
    assert page.ok and page.source == "extracts" and "not the page text" in page.message
    assert {p.ref.split(":")[0] for p in page.pages} == {"extracts/fixture-index.md", "extracts/fixture-commands.yaml"}
    assert search.page(bare, "FX", printed="9-2").pages[0].p == 2
    with pytest.raises(ManualError, match="maps printed page"):
        search.page(bare, "FX", printed="7-7")
    toc = search.toc(bare, "FX", grep="fix")
    assert toc.source == "extracts" and [(e.title, e.p, e.printed) for e in toc.entries] == [
        ("Fixture Guide Index", None, ""), ("Chapter 9: Fixture Commands (PDF 1-2)", 1, ""), ("FIXCMD", 1, "9-1"),
        ("WGFMU_fixtureEvent", 2, "9-2")]


def test_fallback_for_a_document_without_extracts(bare: ManualPaths) -> None:
    data = yaml.safe_load(bare.catalog.read_text(encoding="utf-8"))
    data["docs"][0]["extracts"] = []
    bare.catalog.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    result = search.search(bare, "FIXCMD")
    assert not result.ok and "No structured extract covers FX" in result.message
    assert not search.page(bare, "FX", 1).ok and not search.toc(bare, "FX").ok


# -- the committed corpus (WP5.8 AC) -----------------------------------------------------------------------------------


def test_committed_corpus_is_current_and_within_budget() -> None:
    status = search.status(REAL)
    assert status.corpus == "current", status.message
    assert (status.docs_in_corpus, status.pages_in_corpus) == (16, 2315)
    assert status.corpus_bytes <= CORPUS_BUDGET_BYTES
    catalog = load_catalog(REAL.catalog)
    with gzip.open(REAL.pages, "rt", encoding="utf-8") as handle:
        first = json.loads(handle.readline())
    assert list(first) == ["doc", "p", "printed", "outline_path", "text"] and first["doc"] == catalog.ids[0]


def test_ac_erssp_status_top_hit_is_pg_433() -> None:
    top = search.search(REAL, "ERSSP status").hits[0]
    assert (top.doc, top.p, top.printed, top.title) == ("PG", 433, "4-115", "ERSSP")


def test_ac_wgfmu_function_top_hit_is_wg() -> None:
    top = search.search(REAL, "WGFMU_setMeasureEvent").hits[0]
    assert (top.doc, top.title, top.title_hit) == ("WG", "WGFMU_setMeasureEvent", True)


def test_ac_chinese_rtn_query_hits_the_rtn_note() -> None:
    assert "AN-RTN" in {hit.doc for hit in search.search(REAL, "随机电报噪声").hits}


def test_ac_printed_label_4_189_is_pdf_507() -> None:
    result = search.page(REAL, "PG", printed="4-189")
    assert [p.p for p in result.pages] == [507] and result.pages[0].cite == "PG p507 (4-189)"
    assert search.search(REAL, "SER load impedance").hits[0].p == 507


def test_committed_outline_has_one_entry_per_command() -> None:
    entries = search.toc(REAL, "PG", grep="^FMT$").entries
    assert [(e.title, e.p, e.printed) for e in entries] == [("FMT", 436, "4-118")]
    assert any(e.title == "WGFMU_setMeasureEvent" for e in search.toc(REAL, "WG").entries)


def _manuals_dir() -> Path:
    return Path(os.environ.get(ENV_MANUALS_DIR) or REPO.parent)


@pytest.mark.skipif(not (_manuals_dir() / "B1500A Programming Guide.pdf").is_file(),
                    reason="Keysight PDFs not available (set B1500_MANUALS_DIR)")
def test_real_corpus_rebuilds_byte_for_byte_from_the_pdfs() -> None:
    paths = ManualPaths(references=REAL.references, manuals_dir=_manuals_dir(), repo_root=REPO)
    report = build_corpus(paths, check=True)
    assert report.ok and report.identical is True, report.message
    assert report.pages == 2315 and report.seconds < 10
